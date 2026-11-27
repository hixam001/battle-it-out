import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api, ApiError } from "./api";
import { InitialCodes } from "./initial-codes";

type Tournament = { id: string; name: string; status: string };
type Fields = {
  email: string; team_key: string; team_name: string; member_number: number; role_label: "captain" | "member";
};
type Entry = Fields & {
  id: string; locked_at: string | null; version: number;
  status: "unregistered" | "pending_verification" | "registered";
};
type Report = {
  counts: Record<Entry["status"], number>;
  closed: boolean;
  excluded: string[];
  teams_without_registered_captain: string[];
  teams_without_captain_on_roster: string[];
};
type ImportReceipt = {
  created: number; updated: number; unchanged: number; rejected: { row: number; reason: string }[];
};

export function Roster({ tournament }: { tournament?: Tournament }) {
  if (!tournament) return <section className="empty"><h1>Official roster</h1><p>This tournament is unavailable.</p></section>;
  return <TournamentRoster tournament={tournament} />;
}

function TournamentRoster({ tournament }: { tournament: Tournament }) {
  const path = `/tournaments/${encodeURIComponent(tournament.id)}/roster/`;
  const [records, setRecords] = useState<{ items: Entry[]; report: Report }>();
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [editor, setEditor] = useState<Entry>();
  const [revision, setRevision] = useState(0);
  const refresh = () => { setEditor(undefined); setRevision((value) => value + 1); };

  useEffect(() => {
    const controller = new AbortController();
    const options = { signal: controller.signal };
    setError("");
    Promise.all([api<{ items: Entry[] }>(path, options), api<Report>(path + "report/", options)])
      .then(([response, report]) => { if (!controller.signal.aborted) setRecords({ items: response.items, report }); })
      .catch((error: Error) => {
        if (controller.signal.aborted) return;
        setRecords(undefined);
        setError(error.message);
      });
    return () => controller.abort();
  }, [path, revision]);

  const report = records?.report;
  const editable = Boolean(report && (["draft", "rejected"].includes(tournament.status) ||
    (!report.closed && ["approved", "registration_open"].includes(tournament.status))));
  const excluded = new Set(report?.excluded);
  return (
    <>
      <div className="workspace-heading">
        <div><p className="eyebrow">{tournament.name}</p><h1>Official roster</h1></div>
        <a href={`/organizer/tournaments/${encodeURIComponent(tournament.id)}`}>Back to tournament</a>
      </div>
      {error ? <p className="error" role="alert">{error}</p> :
        !records || !report ? <p role="status">Loading roster…</p> : (
          <>
            <section className="panel tournament-overview">
              <div className="panel-toolbar"><h2>Registration report</h2>
                <button className="text-button" onClick={refresh}>Refresh roster</button></div>
              <dl>
                <div><dt>Registered</dt><dd>{report.counts.registered}</dd></div>
                <div><dt>Pending verification</dt><dd>{report.counts.pending_verification}</dd></div>
                <div><dt>Unregistered</dt><dd>{report.counts.unregistered}</dd></div>
              </dl>
              {report.closed && <p>Registration deadline passed. Excluded entries: {report.excluded.length}.</p>}
              {report.teams_without_captain_on_roster.length > 0 &&
                <p>Teams without a roster captain: {report.teams_without_captain_on_roster.join(", ")}.</p>}
              {report.teams_without_registered_captain.length > 0 &&
                <p>Teams awaiting a verified captain: {report.teams_without_registered_captain.join(", ")}.</p>}
            </section>
            {editable && <RosterImport path={path} onImport={refresh} />}
            {!report.closed && ["approved", "registration_open"].includes(tournament.status) &&
              <InitialCodes tournamentId={tournament.id} entries={records.items} />}
            <section className="panel">
              <h2>Roster entries</h2>
              {message && <p className="success" role="status">{message}</p>}
              {records.items.length ? (
                <div className="table-wrap"><table aria-label="Official roster entries">
                  <thead><tr><th scope="col">Official email</th><th scope="col">Team</th>
                    <th scope="col">Member</th><th scope="col">Status</th><th scope="col">Actions</th></tr></thead>
                  <tbody>{records.items.map((entry) => (
                    <tr key={entry.id}>
                      <th scope="row">{entry.email}</th><td>{entry.team_name} ({entry.team_key})</td>
                      <td>{entry.member_number} · {entry.role_label}</td>
                      <td>{entry.status.replaceAll("_", " ")}{excluded.has(entry.id) && " · Excluded"}</td>
                      <td>{editable && !entry.locked_at && entry.status === "unregistered" ? (
                        <button className="text-button" disabled={Boolean(editor)} aria-label={`Correct ${entry.email}`}
                          onClick={() => { setMessage(""); setEditor(entry); }}>Correct</button>
                      ) : "Locked"}</td>
                    </tr>
                  ))}</tbody>
                </table></div>
              ) : <p>No roster entries.</p>}
            </section>
            {editor && <CorrectEntry key={editor.id} entry={editor} path={path} cancel={() => setEditor(undefined)}
              onSave={() => { refresh(); setMessage("Roster entry corrected."); }} />}
          </>
        )}
      {!records && error && <button className="text-button" onClick={refresh}>Retry loading roster</button>}
    </>
  );
}

function RosterImport({ path, onImport }: { path: string; onImport: () => void }) {
  const [selected, setSelected] = useState<{ file: File; key: string }>();
  const [receipt, setReceipt] = useState<ImportReceipt>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected || busy) return;
    const form = event.currentTarget;
    const { file, key } = selected;
    setBusy(true);
    setReceipt(undefined);
    setError("");
    try {
      const type = file.name.split(".").at(-1)?.toLowerCase();
      if (type !== "csv" && type !== "json") throw new Error("Choose a CSV or JSON roster file.");
      if (file.size > 1_048_576) throw new Error("The roster file must be 1 MiB or smaller.");
      const body = type === "csv" ? new FormData() : await file.text();
      if (body instanceof FormData) body.append("file", file);
      const result = await api<ImportReceipt>(path + "import/", {
        method: "POST", body, headers: { "Idempotency-Key": key },
      });
      setReceipt(result);
      form.reset();
      setSelected(undefined);
      onImport();
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel">
      <h2>Import roster</h2>
      <p>Use a CSV or JSON file up to 1 MiB. Fields: <code>email,team_key,team_name,member_number,role</code>.
        JSON files wrap the entries in <code>{'{ "rows": [...] }'}</code>.</p>
      <form onSubmit={submit}>
        <label>Roster file
          <input type="file" required accept=".csv,.json" disabled={busy} onChange={(event) => {
            const file = event.target.files?.[0];
            setSelected(file ? { file, key: crypto.randomUUID() } : undefined);
          }} />
        </label>
        <button className="primary" disabled={busy || !selected}>{busy ? "Importing…" : "Import roster"}</button>
      </form>
      {error && <p className="error" role="alert">{error}</p>}
      {receipt && <>
        <p role="status">Created {receipt.created}. Updated {receipt.updated}. Unchanged {receipt.unchanged}.{" "}
          Rejected {receipt.rejected.length}.</p>
        {receipt.rejected.length > 0 && <ul aria-label="Rejected roster rows">{receipt.rejected.map((row) => (
          <li key={row.row}>Row {row.row}: {row.reason}</li>
        ))}</ul>}
      </>}
    </section>
  );
}

function CorrectEntry({ path, entry, cancel, onSave }: {
  path: string; entry: Entry; cancel: () => void; onSave: () => void;
}) {
  const [fields, setFields] = useState<Fields>({
    email: entry.email, team_key: entry.team_key, team_name: entry.team_name,
    member_number: entry.member_number, role_label: entry.role_label,
  });
  const [error, setError] = useState("");
  const [stale, setStale] = useState(false);
  const [busy, setBusy] = useState(false);
  const changed = Object.entries(fields).filter(([key, value]) => entry[key as keyof Fields] !== value);

  function update<K extends keyof Fields>(name: K, value: Fields[K]) {
    setFields((current) => ({ ...current, [name]: value }));
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || stale || changed.length === 0) return;
    setBusy(true);
    setError("");
    try {
      await api(path + encodeURIComponent(entry.id) + "/", {
        method: "PATCH",
        body: JSON.stringify({ ...Object.fromEntries(changed), expected_version: entry.version }),
      });
      onSave();
    } catch (error) {
      setError((error as Error).message);
      setStale(error instanceof ApiError && error.status === 409);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel">
      <h2>Correct roster entry</h2>
      <form onSubmit={submit}>
        <label>Official email
          <input type="email" value={fields.email} required maxLength={254} disabled={busy || stale}
            onChange={(event) => update("email", event.target.value)} />
        </label>
        <label>Team ID
          <input value={fields.team_key} required maxLength={40} disabled={busy || stale}
            onChange={(event) => update("team_key", event.target.value)} />
        </label>
        <label>Team name
          <input value={fields.team_name} required maxLength={80} disabled={busy || stale}
            onChange={(event) => update("team_name", event.target.value)} />
        </label>
        <label>Member number
          <input type="number" min={1} max={99} required value={fields.member_number || ""} disabled={busy || stale}
            onChange={(event) => update("member_number", Number(event.target.value))} />
        </label>
        <label>Role
          <select value={fields.role_label} disabled={busy || stale}
            onChange={(event) => update("role_label", event.target.value === "captain" ? "captain" : "member")}>
            <option value="captain">Captain</option><option value="member">Member</option>
          </select>
        </label>
        {error && <p className="error" role="alert">{error}{stale && " Refresh the roster before trying again."}</p>}
        <div className="notice-actions">
          <button className="primary" disabled={busy || stale || changed.length === 0}>Save correction</button>
          <button className="text-button" type="button" disabled={busy} onClick={cancel}>Cancel</button>
        </div>
      </form>
    </section>
  );
}
