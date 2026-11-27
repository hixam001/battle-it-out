import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api, ApiError } from "./api";

type TournamentSummary = { id: string; name: string; status: string };
type TournamentReview = TournamentSummary & {
  version: number;
  description: string;
  registration_deadline: string | null;
  submission_deadline: string | null;
  map_pool_id: string | null;
};
type ReviewAction = "approve" | "reject";
const tournamentPath = (id: string) => `/tournaments/${encodeURIComponent(id)}/`;

export function Approvals({ tournaments, loading, loadError, refreshQueue, onReview }: {
  tournaments: TournamentSummary[];
  loading: boolean;
  loadError: string;
  refreshQueue: () => Promise<void>;
  onReview: (tournament: TournamentReview) => void;
}) {
  const pending = tournaments.filter((item) => item.status === "pending_approval");
  const [selected, setSelected] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const current = pending.find((item) => item.id === selected) ?? pending[0];

  async function refresh() {
    setRefreshing(true);
    setError("");
    try {
      await refreshQueue();
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setRefreshing(false);
    }
  }

  return (
    <>
      <div className="workspace-heading">
        <h1>Tournament approvals</h1>
        <button className="text-button" onClick={refresh} disabled={refreshing}>
          {refreshing ? "Refreshing…" : "Refresh queue"}
        </button>
      </div>
      {(error || loadError) && <p className="error" role="alert">{error || loadError}</p>}
      {message && <p className="success" role="status">{message}</p>}
      {loading ? <p role="status">Loading approval queue…</p> : current ? (
        <>
          <section className="panel">
            <label>
              Pending tournament
              <select value={current.id} onChange={(event) => {
                setSelected(event.target.value);
                setMessage("");
              }}>
                {pending.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
              </select>
            </label>
          </section>
          <Review key={current.id} tournamentId={current.id} onReview={(result) => {
            onReview(result);
            setMessage(result.status === "approved"
              ? `${result.name} approved. Registration can now be opened separately.`
              : `${result.name} rejected. The Organizer can edit and resubmit it.`);
          }} />
        </>
      ) : !loadError && !error && <p>No tournaments are awaiting approval.</p>}
    </>
  );
}

function Review({ tournamentId, onReview }: {
  tournamentId: string;
  onReview: (tournament: TournamentReview) => void;
}) {
  const path = tournamentPath(tournamentId);
  const [record, setRecord] = useState<TournamentReview>();
  const [revision, setRevision] = useState(0);
  const [action, setAction] = useState<ReviewAction>("approve");
  const [confirmed, setConfirmed] = useState(false);
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [stale, setStale] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    api<TournamentReview>(path, { signal: controller.signal })
      .then(setRecord)
      .catch((error: Error) => { if (!controller.signal.aborted) setError(error.message); });
    return () => controller.abort();
  }, [path, revision]);

  function reload() {
    setRecord(undefined);
    setConfirmed(false);
    setReason("");
    setError("");
    setStale(false);
    setRevision((value) => value + 1);
  }

  const ready = Boolean(record && record.status === "pending_approval" && !stale && !busy &&
    (action === "approve" ? confirmed : reason.trim()));

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!record || !ready) return;
    const body = action === "approve" ? { confirm: true } : { reason: reason.trim() };
    setBusy(true);
    setError("");
    try {
      const result = await api<TournamentReview>(path + action + "/", {
        method: "POST",
        body: JSON.stringify({ ...body, expected_version: record.version }),
      });
      onReview(result);
    } catch (error) {
      setError((error as Error).message);
      if (error instanceof ApiError && [403, 404, 409].includes(error.status)) setStale(true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel tournament-overview">
      {error && <p className="error" role="alert">{error}</p>}
      {(stale || (!record && error)) &&
        <button className="text-button" onClick={reload}>Reload tournament details</button>}
      {!record ? !error && <p role="status">Loading tournament details…</p> : (
        <>
          <h2>{record.name}</h2>
          {record.description && <p>{record.description}</p>}
          <dl>
            <div><dt>Registration deadline</dt><dd><Deadline value={record.registration_deadline} /></dd></div>
            <div><dt>Submission deadline</dt><dd><Deadline value={record.submission_deadline} /></dd></div>
            <div><dt>Map pool</dt><dd>{record.map_pool_id || "Not selected"}</dd></div>
          </dl>
          {record.status === "pending_approval" ? (
            <form onSubmit={submit}>
              <label>Decision
                <select value={action} disabled={busy || stale} onChange={(event) => {
                  setAction(event.target.value === "reject" ? "reject" : "approve");
                  setConfirmed(false);
                  setError("");
                }}>
                  <option value="approve">Approve</option>
                  <option value="reject">Reject</option>
                </select>
              </label>
              {action === "approve" ? (
                <label className="review-confirm">
                  <input type="checkbox" checked={confirmed} disabled={busy || stale}
                    onChange={(event) => setConfirmed(event.target.checked)} />
                  Confirm tournament approval
                </label>
              ) : (
                <label>
                  Rejection reason
                  <textarea required maxLength={500} value={reason} disabled={busy || stale}
                    onChange={(event) => setReason(event.target.value)} />
                </label>
              )}
              <button className="primary" type="submit" disabled={!ready}>
                {busy ? "Saving decision…" : action === "approve" ? "Approve tournament" : "Reject tournament"}
              </button>
            </form>
          ) : <p role="status">This tournament is now {record.status.replaceAll("_", " ")}. Refresh the queue.</p>}
        </>
      )}
    </section>
  );
}

function Deadline({ value }: { value: string | null }) {
  if (!value) return <>Unavailable</>;
  return <time dateTime={value}>{new Date(value).toLocaleString(undefined, { timeZoneName: "short" })}</time>;
}
