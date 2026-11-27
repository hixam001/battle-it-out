import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api } from "./api";

type Entry = { id: string; email: string; status: string };
type IssueResponse = {
  issued: { entry_id: string; code_id: string; code: string }[];
  skipped: { entry_id: string; reason: string }[];
};
type Receipt = Omit<IssueResponse, "issued"> & { issued: (IssueResponse["issued"][number] & { email: string })[] };

export function InitialCodes({ tournamentId, entries, onIssued }: {
  tournamentId: string; entries?: Entry[]; onIssued?: () => void;
}) {
  const base = `/tournaments/${encodeURIComponent(tournamentId)}/`;
  const path = base + "invitation-codes/";
  const [eligible, setEligible] = useState<Entry[]>();
  const [selected, setSelected] = useState(new Set<string>());
  const [receipt, setReceipt] = useState<Receipt>();
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    const options = { signal: controller.signal };
    const roster = entries ? Promise.resolve(entries) : api<{ items: Entry[] }>(base + "roster/", options)
      .then((response) => response.items);
    Promise.all([roster, api<{ items: { entry_id: string }[] }>(path, options)])
      .then(([roster, codes]) => {
        if (controller.signal.aborted) return;
        const issued = new Set(codes.items.map((code) => code.entry_id));
        const available = roster.filter((entry) => entry.status === "unregistered" && !issued.has(entry.id));
        setEligible(available);
        setSelected((values) => new Set(available.filter((entry) => values.has(entry.id)).map((entry) => entry.id)));
      })
      .catch((error: Error) => {
        if (controller.signal.aborted) return;
        setEligible(undefined);
        setSelected(new Set());
        setError(error.message);
      });
    return () => controller.abort();
  }, [base, path, entries, revision]);

  async function issue(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected.size || busy) return;
    setBusy(true);
    setError("");
    setReceipt(undefined);
    try {
      const recipients = new Map(eligible?.map((entry) => [entry.id, entry.email]));
      const result = await api<IssueResponse>(path, {
        method: "POST", body: JSON.stringify({ roster_entry_ids: Array.from(selected) }),
      });
      setReceipt({ ...result, issued: result.issued.map((item) => ({
        ...item, email: recipients.get(item.entry_id) ?? item.entry_id,
      })) });
      setSelected(new Set());
      setRevision((value) => value + 1);
      onIssued?.();
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel" aria-labelledby="initial-code-heading">
      <h2 id="initial-code-heading">Issue first invitation codes</h2>
      {error && <p className="error" role="alert">{error}</p>}
      {!eligible ? !error && <p role="status">Checking eligible roster entries…</p> :
        eligible.length === 0 ? <p>No roster entries are eligible for first issuance.</p> : (
          <form onSubmit={issue}>
            {eligible.map((entry) => (
              <label className="review-confirm" key={entry.id}>
                <input type="checkbox" disabled={busy} checked={selected.has(entry.id)}
                  onChange={(event) => {
                    const checked = event.target.checked;
                    setSelected((values) => {
                      const next = new Set(values);
                      if (checked) next.add(entry.id);
                      else next.delete(entry.id);
                      return next;
                    });
                  }} />
                {entry.email}
              </label>
            ))}
            <button className="primary" type="submit" disabled={busy || selected.size === 0}>
              {busy ? "Issuing…" : "Issue selected codes"}
            </button>
          </form>
        )}
      {receipt && <IssueReceipt receipt={receipt} dismiss={() => setReceipt(undefined)} />}
    </section>
  );
}

function IssueReceipt({ receipt, dismiss }: { receipt: Receipt; dismiss: () => void }) {
  return (
    <section aria-label="Initial invitation receipt">
      <div className="panel-toolbar">
        <h3>Initial invitation receipt</h3>
        <button className="text-button" onClick={dismiss}>Dismiss issuance receipt</button>
      </div>
      <p role="status">Issued {receipt.issued.length}. Skipped {receipt.skipped.length}.</p>
      {receipt.issued.length > 0 && (
        <>
          <p>Match each code to its roster entry and share it privately.</p>
          <div className="table-wrap">
            <table aria-label="Issued invitation codes">
              <thead><tr><th scope="col">Roster participant</th><th scope="col">Code ID</th><th scope="col">Code</th></tr></thead>
              <tbody>{receipt.issued.map((entry) => (
                <tr key={entry.code_id}><th scope="row">{entry.email}</th><td>{entry.code_id}</td>
                  <td><code>{entry.code}</code></td></tr>
              ))}</tbody>
            </table>
          </div>
        </>
      )}
      {receipt.skipped.length > 0 && <ul>{receipt.skipped.map((entry) => (
        <li key={entry.entry_id}>{entry.entry_id} · {entry.reason}</li>
      ))}</ul>}
    </section>
  );
}
