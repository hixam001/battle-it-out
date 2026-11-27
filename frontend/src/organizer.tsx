import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { api, ApiError } from "./api";

type Summary = { id: string; name: string; status: string };
type Tournament = Summary & {
  description: string;
  registration_deadline: string | null;
  submission_deadline: string | null;
  rejection_reason: string | null;
  created_by: string;
  version: number;
};
type Fields = { name: string; description: string; registration_deadline: string; submission_deadline: string };
type Apply = (record: Tournament) => void;

const blank: Fields = { name: "", description: "", registration_deadline: "", submission_deadline: "" };
const editable = ["draft", "rejected", "approved", "registration_open"];
const formatStatus = (status: string) => status[0].toUpperCase() + status.slice(1).replaceAll("_", " ");
const managePath = (id: string) => `/organizer/tournaments/${encodeURIComponent(id)}`;
const apiPath = (id: string) => `/tournaments/${encodeURIComponent(id)}/`;

function localInput(value: string | null) {
  if (!value) return "";
  const date = new Date(value);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}

function settings(record: Tournament): Fields {
  return {
    name: record.name,
    description: record.description,
    registration_deadline: localInput(record.registration_deadline),
    submission_deadline: localInput(record.submission_deadline),
  };
}

export function Organizer({ id, userId, tournaments, navigate, onChange }: {
  id?: string; userId: number; tournaments: Summary[]; navigate: (path: string) => void; onChange: Apply;
}) {
  if (id === "new") {
    return (
      <>
        <div className="workspace-heading"><h1>New tournament</h1><a href="/organizer">All tournaments</a></div>
        <section className="panel">
          <TournamentForm save={(record) => { onChange(record); navigate(managePath(record.id)); }} />
        </section>
      </>
    );
  }
  if (id) return <ManagedTournament id={id} userId={userId} onChange={onChange} />;
  return (
    <>
      <div className="workspace-heading"><h1>Manage tournaments</h1><a href={managePath("new")}>New tournament</a></div>
      <section className="panel" aria-label="Assigned tournaments">
        {tournaments.length > 0 ? (
          <div className="table-wrap">
            <table aria-label="Assigned tournaments">
              <thead><tr><th scope="col">Tournament</th><th scope="col">Status</th></tr></thead>
              <tbody>{tournaments.map((record) => (
                <tr key={record.id}>
                  <th scope="row"><a href={managePath(record.id)}>{record.name}</a></th>
                  <td>{formatStatus(record.status)}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        ) : <p>No tournaments are assigned to this account.</p>}
      </section>
    </>
  );
}

function ManagedTournament({ id, userId, onChange }: { id: string; userId: number; onChange: Apply }) {
  const [record, setRecord] = useState<Tournament>();
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState(false);
  const [stale, setStale] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    api<Tournament>(apiPath(id), { signal: controller.signal })
      .then((record) => { setRecord(record); onChange(record); })
      .catch((error: Error) => { if (!controller.signal.aborted) setError(error.message); });
    return () => controller.abort();
  }, [id, onChange, revision]);

  function refresh() {
    setRecord(undefined);
    setError("");
    setMessage("");
    setStale(false);
    setRevision((value) => value + 1);
  }

  function update(tournament: Tournament, text: string) {
    setRecord(tournament);
    onChange(tournament);
    setMessage(text);
  }

  async function transition(action: "submit-for-approval" | "open-registration", success: string) {
    if (!record || busy || stale) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const response = await api<Tournament>(apiPath(id) + action + "/", {
        method: "POST",
        body: JSON.stringify({ expected_version: record.version }),
      });
      update(response, success);
    } catch (error) {
      setError((error as Error).message);
      if (error instanceof ApiError && error.status === 409) setStale(true);
    } finally {
      setBusy(false);
    }
  }

  const canSubmit = record?.created_by === String(userId) && ["draft", "rejected"].includes(record.status);
  return (
    <>
      <div className="workspace-heading">
        <h1>{record?.name ?? "Tournament settings"}</h1>
        <a href="/organizer">All tournaments</a>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      {message && <p className="success" role="status">{message}</p>}
      {!record ? error ? <button className="text-button" onClick={refresh}>Retry loading tournament</button>
        : <p role="status">Loading tournament…</p> : (
        <>
          <section className="panel tournament-overview">
            <div className="panel-toolbar">
              <h2>Tournament status</h2>
              <button className="text-button" onClick={refresh} disabled={busy}>Refresh tournament</button>
            </div>
            <p role="status">{formatStatus(record.status)}</p>
            {!editable.includes(record.status) && record.description && <p>{record.description}</p>}
            {record.status === "rejected" && <p><strong>Rejection reason:</strong> {record.rejection_reason}</p>}
            {record.status === "pending_approval" && <p>The Admin is reviewing this version.</p>}
            <dl>
              <div><dt>Registration deadline</dt><dd>{formatDeadline(record.registration_deadline)}</dd></div>
              <div><dt>Submission deadline</dt><dd>{formatDeadline(record.submission_deadline)}</dd></div>
            </dl>
            {canSubmit && <button className="primary" disabled={stale || busy}
              onClick={() => transition("submit-for-approval", "Submitted for Admin approval.")}>
              {record.status === "rejected" ? "Resubmit for approval" : "Submit for approval"}
            </button>}
            {record.status === "approved" && <button className="primary" disabled={stale || busy}
              onClick={() => transition("open-registration", "Registration is open.")}>Open registration</button>}
          </section>
          {editable.includes(record.status) && <section className="panel">
            <h2>Edit tournament</h2>
            <TournamentForm key={record.version} record={record} disabled={stale || busy} conflict={() => setStale(true)}
              save={(updated) => update(updated, "Tournament settings saved.")} />
          </section>}
        </>
      )}
    </>
  );
}

function formatDeadline(value: string | null) {
  return value ? <time dateTime={value}>{new Date(value).toLocaleString(undefined, { timeZoneName: "short" })}</time>
    : "Unavailable";
}

function TournamentForm({ record, save, disabled, conflict }: {
  record?: Tournament; save: Apply; disabled?: boolean; conflict?: () => void;
}) {
  const initial = record ? settings(record) : blank;
  const [fields, setFields] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const token = useRef<{ payload: string; key: string }>(null);
  const published = record?.status === "approved" || record?.status === "registration_open";
  const registrationLocked = published && Date.parse(record.registration_deadline ?? "") <= Date.now();
  const submissionLocked = published && Date.parse(record.submission_deadline ?? "") <= Date.now();

  function field<K extends keyof Fields>(name: K, value: Fields[K]) {
    setFields((current) => ({ ...current, [name]: value }));
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || disabled) return;
    const changed = (Object.keys(fields) as (keyof Fields)[]).filter((key) => !record || fields[key] !== initial[key]);
    if (!changed.length) return;
    setBusy(true);
    setError("");
    try {
      const body = Object.fromEntries(changed.map((key) => [
        key, key.endsWith("_deadline") ? new Date(fields[key]).toISOString() : fields[key],
      ]));
      if (record) {
        save(await api<Tournament>(apiPath(record.id), {
          method: "PATCH", body: JSON.stringify({ ...body, expected_version: record.version }),
        }));
      } else {
        const payload = JSON.stringify(body);
        if (token.current?.payload !== payload) token.current = { payload, key: crypto.randomUUID() };
        save(await api<Tournament>("/tournaments/", {
          method: "POST", body: payload, headers: { "Idempotency-Key": token.current.key },
        }));
      }
    } catch (error) {
      setError((error as Error).message);
      if (error instanceof ApiError && error.status === 409) conflict?.();
    } finally {
      setBusy(false);
    }
  }

  const noChanges = record && (Object.keys(fields) as (keyof Fields)[]).every((key) => fields[key] === initial[key]);
  return (
    <form onSubmit={submit}>
      {(registrationLocked || submissionLocked) && <p>Locked fields require an Admin deadline extension before editing.</p>}
      <label>Tournament name
        <input required maxLength={120} value={fields.name} disabled={disabled || busy || submissionLocked}
          onChange={(event) => field("name", event.target.value)} />
      </label>
      <label>Description
        <textarea maxLength={2000} value={fields.description} disabled={disabled || busy || submissionLocked}
          onChange={(event) => field("description", event.target.value)} />
      </label>
      <div className="two-col">
        <label>Registration deadline
          <input type="datetime-local" required={!record || Boolean(initial.registration_deadline)}
            value={fields.registration_deadline} disabled={disabled || busy || registrationLocked}
            onChange={(event) => field("registration_deadline", event.target.value)} />
        </label>
        <label>Submission deadline
          <input type="datetime-local" required={!record || Boolean(initial.submission_deadline)}
            value={fields.submission_deadline} disabled={disabled || busy || submissionLocked}
            onChange={(event) => field("submission_deadline", event.target.value)} />
        </label>
      </div>
      <p className="muted">Timezone {Intl.DateTimeFormat().resolvedOptions().timeZone}</p>
      {error && <p className="error" role="alert">{error}</p>}
      <button className="primary" type="submit" disabled={disabled || busy || noChanges}>
        {busy ? "Saving…" : record ? "Save settings" : "Create draft"}
      </button>
    </form>
  );
}
