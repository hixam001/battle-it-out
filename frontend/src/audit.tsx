import { useEffect, useState } from "react";
import { api } from "./api";

type Item = {
  id: string;
  source: string;
  action: string;
  created_at: string;
  tournament_id: string | null;
  actor_id?: string;
  detail: Record<string, string | number | boolean>;
};
type Page = { items: Item[]; next_offset: number | null };
const pageSize = 25;
const readable = (value: string) => value.replaceAll("_", " ");

export function GlobalAudit({ tournaments }: { tournaments: { id: string; name: string }[] }) {
  const [draft, setDraft] = useState("");
  const [filter, setFilter] = useState("");
  const [offset, setOffset] = useState(0);
  const [revision, setRevision] = useState(0);
  const [page, setPage] = useState<Page>();
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    const query = new URLSearchParams({ limit: String(pageSize), offset: String(offset) });
    if (filter) query.set("tournament_id", filter);
    setPage(undefined);
    setError("");
    api<Page>(`/admin/audit-logs/?${query}`, { signal: controller.signal })
      .then((response) => { if (!controller.signal.aborted) setPage(response); })
      .catch((error: Error) => { if (!controller.signal.aborted) setError(error.message); });
    return () => controller.abort();
  }, [filter, offset, revision]);

  function search(tournament: string) {
    setFilter(tournament.trim());
    setOffset(0);
    setRevision((value) => value + 1);
  }

  return (
    <>
      <div className="workspace-heading">
        <h1>Global audit log</h1>
        <button className="text-button" onClick={() => search(filter)}>Refresh audit log</button>
      </div>
      <section className="panel" aria-label="Audit filters">
        <form onSubmit={(event) => { event.preventDefault(); search(draft); }}>
          <label>Tournament ID
            <input value={draft} onChange={(event) => setDraft(event.target.value)}
              maxLength={40} list="audit-tournaments" placeholder="All tournaments" />
          </label>
          <datalist id="audit-tournaments">
            {tournaments.map((item) => <option key={item.id} value={item.id} label={item.name} />)}
          </datalist>
          <div className="notice-actions">
            <button className="primary" type="submit">Apply filter</button>
            <button className="text-button" type="button" disabled={!draft && !filter}
              onClick={() => { setDraft(""); search(""); }}>Clear filter</button>
          </div>
        </form>
      </section>
      <section className="panel" aria-labelledby="audit-events">
        <h2 id="audit-events">Audit events</h2>
        {filter && <p>Tournament ID <code>{filter}</code></p>}
        {error ? <p className="error" role="alert">{error}</p> :
          !page ? <p role="status">Loading audit events…</p> :
          page.items.length === 0 ? <p>No audit events match this filter.</p> :
            <div className="table-wrap">
              <table aria-label="Global audit events">
                <thead><tr>
                  <th scope="col">Date</th><th scope="col">Action</th><th scope="col">Source</th>
                  <th scope="col">Tournament ID</th><th scope="col">Actor ID</th><th scope="col">Details</th>
                </tr></thead>
                <tbody>{page.items.map((item) => <AuditRow key={`${item.source}/${item.id}`} item={item} />)}</tbody>
              </table>
            </div>}
        <nav className="notice-actions notice-pagination" aria-label="Audit pages">
          <button className="text-button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - pageSize))}>
            Previous
          </button>
          <span aria-live="polite">Page {Math.floor(offset / pageSize) + 1}</span>
          <button className="text-button" disabled={page?.next_offset == null} onClick={() => {
            if (page?.next_offset != null) setOffset(page.next_offset);
          }}>Next</button>
        </nav>
      </section>
    </>
  );
}

function AuditRow({ item }: { item: Item }) {
  const details = Object.entries(item.detail);
  return (
    <tr>
      <td><time dateTime={item.created_at}>{new Date(item.created_at).toLocaleString()}</time></td>
      <th scope="row">{readable(item.action)}</th>
      <td>{readable(item.source)}</td>
      <td>{item.tournament_id ?? "—"}</td>
      <td>{item.actor_id ?? "—"}</td>
      <td>{details.length > 0 ? (
        <details className="validation-details">
          <summary>Event details</summary>
          <dl>{details.map(([field, value]) => (
            <div key={field}><dt>{readable(field)}</dt><dd>{String(value)}</dd></div>
          ))}</dl>
        </details>
      ) : "—"}</td>
    </tr>
  );
}
