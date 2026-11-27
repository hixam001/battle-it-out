import { useEffect, useState } from "react";
import { api } from "./api";

type Incident = {
  id: string;
  source: string;
  incident_type: string;
  job_id: string | null;
  match_id: string | null;
  tournament_id: string | null;
  attempt_count: number | null;
  alerted_admin_at: string | null;
};
type OperationsSnapshot = {
  status: { open_incidents: number; unalerted_incidents: number; unalerted_failed_emails: number };
  incidents: Incident[];
  dead_jobs: { id: string; kind: string; failures: number }[];
  audit: { action: string; tournament_id: string; created_at: string }[];
};

const readable = (value: string) => value.replaceAll("_", " ");

export function Operations() {
  const [data, setData] = useState<OperationsSnapshot>();
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    api<OperationsSnapshot>("/admin/operations/", { signal: controller.signal })
      .then((snapshot) => { if (!controller.signal.aborted) setData(snapshot); })
      .catch((error: Error) => { if (!controller.signal.aborted) setError(error.message); });
    return () => controller.abort();
  }, [revision]);

  function refresh() {
    setData(undefined);
    setError("");
    setRevision((value) => value + 1);
  }

  const loading = !data && !error;
  return (
    <>
      <div className="workspace-heading">
        <h1>Operations</h1>
        <button className="text-button" onClick={refresh} disabled={loading}>Refresh operations</button>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      {loading && <p role="status">Loading service state…</p>}
      {data && <>
        <div className="stats">
          <div><span>Open incidents</span><strong>{data.status.open_incidents}</strong></div>
          <div><span>Unalerted incidents</span><strong>{data.status.unalerted_incidents}</strong></div>
          <div><span>Failed emails awaiting alert</span><strong>{data.status.unalerted_failed_emails}</strong></div>
          <div><span>Dead jobs</span><strong>{data.dead_jobs.length}</strong></div>
        </div>
        <section className="panel">
          <h2>Open incidents</h2>
          {data.incidents.length ? <div className="table-wrap">
            <table aria-label="Open incidents">
              <thead><tr><th scope="col">Incident</th><th scope="col">Source</th><th scope="col">Reference</th>
                <th scope="col">Attempts</th><th scope="col">Admin alert</th></tr></thead>
              <tbody>{data.incidents.map((incident) => (
                <tr key={`${incident.source}/${incident.id}`}>
                  <th scope="row">{readable(incident.incident_type)}</th><td>{incident.source}</td>
                  <td>{incident.match_id ?? incident.job_id ?? incident.tournament_id ?? incident.id}</td>
                  <td>{incident.attempt_count ?? "—"}</td>
                  <td>{incident.alerted_admin_at ? <Timestamp value={incident.alerted_admin_at} /> : "Pending"}</td>
                </tr>
              ))}</tbody>
            </table>
          </div> : <p>No open incidents.</p>}
        </section>
        <section className="panel">
          <h2>Dead jobs</h2>
          {data.dead_jobs.length ? <div className="table-wrap">
            <table aria-label="Dead jobs">
              <thead><tr><th scope="col">Job ID</th><th scope="col">Type</th><th scope="col">Failures</th></tr></thead>
              <tbody>{data.dead_jobs.map((job) => (
                <tr key={job.id}><th scope="row">{job.id}</th><td>{readable(job.kind)}</td><td>{job.failures}</td></tr>
              ))}</tbody>
            </table>
          </div> : <p>No dead jobs.</p>}
        </section>
        <section className="panel">
          <div className="panel-toolbar">
            <h2>Recent audit events</h2><a href="/admin/audit">Open global audit log</a>
          </div>
          {data.audit.length ? data.audit.map((item, index) => (
            <div className="map-row" key={index}>
              <strong>{readable(item.action)}</strong>
              <span>{item.tournament_id} · <Timestamp value={item.created_at} /></span>
            </div>
          )) : <p>No web audit events recorded.</p>}
        </section>
      </>}
    </>
  );
}

function Timestamp({ value }: { value: string }) {
  return <time dateTime={value}>{new Date(value).toLocaleString(undefined, { timeZoneName: "short" })}</time>;
}
