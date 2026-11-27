import { useEffect, useState } from "react";
import { api, ApiError } from "./api";

type OutputEntry = { round: number; robot: number; text: string; truncated: boolean };
type LogEvent = {
  seq: number;
  event: string;
  ts?: string;
  data: Record<string, unknown> & { team?: "A" | "B"; entries?: OutputEntry[] };
};
type Log = { attempt: number; items: LogEvent[] };
const eventLabels: Record<string, string> = {
  "match.start": "Match started",
  "match.result": "Match result",
  "match.end": "Match ended",
  "team.usage": "Usage",
  "team.output": "Output",
  "team.failure": "Failure",
  "platform.diagnostics": "Platform diagnostics",
};

export function MatchLogs({ matchId }: { matchId: string }) {
  const path = `/matches/${encodeURIComponent(matchId)}`;
  const [draft, setDraft] = useState("");
  const [attempt, setAttempt] = useState("");
  const [revision, setRevision] = useState(0);
  const [log, setLog] = useState<Log>();
  const [error, setError] = useState("");
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    const query = attempt ? `?attempt=${encodeURIComponent(attempt)}` : "";
    api<Log>(`${path}/logs/${query}`, { signal: controller.signal })
      .then((result) => { if (!controller.signal.aborted) setLog(result); })
      .catch((error: Error) => {
        if (controller.signal.aborted) return;
        if (error instanceof ApiError && error.status === 404) setMissing(true);
        else setError(error.message);
      });
    return () => controller.abort();
  }, [path, attempt, revision]);

  function load(next: string) {
    setLog(undefined);
    setError("");
    setMissing(false);
    setAttempt(next);
    setRevision((value) => value + 1);
  }

  const busy = !log && !error && !missing;
  return (
    <>
      <div className="workspace-heading">
        <h1>Match log</h1><a href={path}>Back to match</a>
      </div>
      <section className="panel" aria-label="Recorded attempt">
        <form onSubmit={(event) => { event.preventDefault(); if (draft && !busy) load(String(Number(draft))); }}>
          <label>Attempt number
            <input type="number" required min={1} max={100} step={1} value={draft}
              onChange={(event) => setDraft(event.target.value)} />
          </label>
          <div className="notice-actions">
            <button className="primary" type="submit" disabled={busy || !draft}>View attempt</button>
            <button className="text-button" type="button" disabled={busy}
              onClick={() => { setDraft(""); load(""); }}>Latest recorded log</button>
          </div>
        </form>
      </section>
      {busy && <p role="status">Loading match log…</p>}
      {error && <p className="error" role="alert">{error}</p>}
      {missing && <p role="status">{attempt ? "This attempt log is unavailable to your account."
        : "No match log is available to your account."}</p>}
      {log && <section className="panel" aria-label="Log events">
        <h2>Attempt {log.attempt}</h2>
        {log.items.length ? <ol className="match-log-events">
          {log.items.map((event) => <li key={event.seq}><EventDetails event={event} /></li>)}
        </ol> : <p>No log events were recorded.</p>}
      </section>}
    </>
  );
}

function EventDetails({ event }: { event: LogEvent }) {
  const title = eventLabels[event.event] ?? event.event;
  const { team, entries, entries_omitted_in_middle: omitted, entries_total: total, ...fields } = event.data;
  const fieldList = Object.entries(fields).filter(([, value]) => value != null);
  const heading = <>{team ? `Team ${team} ${title.toLowerCase()}` : title}
    {event.ts && <> · <time dateTime={event.ts}>{new Date(event.ts).toLocaleString()}</time></>}
  </>;
  if (!fieldList.length && !entries) return <p>{heading}</p>;
  return (
    <details className="validation-details">
      <summary>{heading}</summary>
      {fieldList.length > 0 && <dl>{fieldList.map(([field, value]) => (
        <div key={field}><dt>{field.replaceAll("_", " ")}</dt>
          <dd>{typeof value === "object" ? <pre>{JSON.stringify(value, null, 2)}</pre> : String(value)}</dd></div>
      ))}</dl>}
      {typeof omitted === "number" && omitted > 0 && typeof total === "number" && (
        <p>{omitted} of {total} output entries were omitted from the middle of the log.</p>
      )}
      {entries && (entries.length ? <ul className="match-log-output">{entries.map((entry, index) => (
        <li key={index}>
          <p>Round {entry.round} · Robot {entry.robot}{entry.truncated && " · Truncated"}</p>
          <pre>{entry.text}</pre>
        </li>
      ))}</ul> : <p>No output recorded.</p>)}
    </details>
  );
}
