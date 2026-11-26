import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api } from "./api";

type Notice = {
  id: string;
  tournament_id: string;
  title: string;
  body: string;
  created_at: string;
  read: boolean;
  email_status: string;
};
type Feed = { items: Notice[]; total: number; unread: number };
type Preferences = { email_enabled: boolean; dashboard_enabled: true };

const pageSize = 20;
const preferencePath = "/me/notification-preferences/";
const noticeDate = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeStyle: "short",
});

function denied(error: unknown) {
  return error instanceof ApiError && [401, 403].includes(error.status);
}

function NoticeItem({ notice, tournament, action }: {
  notice: Notice;
  tournament?: string;
  action?: { busy: boolean; toggle: () => void };
}) {
  return (
    <li className="notice-item" data-unread={!notice.read}>
      <div>
        <div className="notice-meta">
          {tournament && <span>{tournament}</span>}
          <time dateTime={notice.created_at}>{noticeDate.format(new Date(notice.created_at))}</time>
          <span className="notice-state">{notice.read ? "Read" : "Unread"}</span>
        </div>
        <h3>{notice.title}</h3>
        <p>{notice.body}</p>
        {notice.email_status === "failed" && <p className="muted">Email delivery failed.</p>}
        {notice.email_status === "no_address" && <p className="muted">No address available for email delivery.</p>}
      </div>
      {action && (
        <button className="notice-control" aria-disabled={action.busy}
          onClick={() => { if (!action.busy) action.toggle(); }}>
          {notice.read ? "Mark unread" : "Mark read"}
        </button>
      )}
    </li>
  );
}

function EmailPreference({ onDenied }: { onDenied: () => void }) {
  const [preferences, setPreferences] = useState<Preferences | null>(null);
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    setError("");
    api<Preferences>(preferencePath, { signal: controller.signal })
      .then(setPreferences)
      .catch((error: Error) => {
        if (controller.signal.aborted) return;
        if (denied(error)) onDenied();
        else setError(error.message);
      });
    return () => controller.abort();
  }, [revision, onDenied]);

  const save = async (enabled: boolean) => {
    setBusy(true);
    setError("");
    setStatus("");
    try {
      const saved = await api<Preferences>(preferencePath, {
        method: "PATCH",
        body: JSON.stringify({ email_enabled: enabled }),
      });
      setPreferences(saved);
      setStatus(saved.email_enabled ? "Email notifications enabled." : "Email notifications disabled.");
    } catch (error) {
      if (denied(error)) onDenied();
      else setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel notice-preference" aria-labelledby="delivery-heading">
      <h2 id="delivery-heading">Notification delivery</h2>
      <p>Dashboard notifications are always on.</p>
      {preferences ? (
        <label className="notice-choice">
          <input type="checkbox" checked={preferences.email_enabled} disabled={busy}
            onChange={(e) => void save(e.target.checked)} />
          Email notifications
        </label>
      ) : error ? (
        <button className="notice-control" onClick={() => setRevision(revision + 1)}>Retry preferences</button>
      ) : <p role="status">Loading email preference…</p>}
      {error && <p className="error" role="alert">{error}</p>}
      <div role="status">{busy ? "Saving preference…" : status}</div>
    </section>
  );
}

function InboxFeed({ tournaments, onDenied }: {
  tournaments: ReadonlyMap<string, string>;
  onDenied: () => void;
}) {
  const [feed, setFeed] = useState<Feed | null>(null);
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [offset, setOffset] = useState(0);
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const unreadFilter = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const controller = new AbortController();
    api<Feed>(`/notifications/?limit=${pageSize}&offset=${offset}&unread_only=${unreadOnly}`, {
      signal: controller.signal,
    }).then((result) => {
      if (controller.signal.aborted) return;
      if (offset && offset >= result.total) {
        setOffset(Math.floor(Math.max(0, result.total - 1) / pageSize) * pageSize);
        return;
      }
      setFeed(result);
      setLoading(false);
    }).catch((error: Error) => {
      if (controller.signal.aborted) return;
      if (denied(error)) onDenied();
      else setError(error.message);
      setLoading(false);
    });
    return () => controller.abort();
  }, [offset, unreadOnly, revision, onDenied]);

  const refresh = (nextOffset: number) => {
    setLoading(true);
    setError("");
    setFeed(null);
    setOffset(nextOffset);
    setRevision(revision + 1);
  };
  const toggle = async (notice: Notice) => {
    setSaving(true);
    setError("");
    setStatus("");
    try {
      const updated = await api<Notice>(`/notifications/${encodeURIComponent(notice.id)}/`, {
        method: "PATCH",
        body: JSON.stringify({ read: !notice.read }),
      });
      setStatus(updated.read ? "Notification marked read." : "Notification marked unread.");
      if (unreadOnly) {
        unreadFilter.current?.focus();
        refresh(offset);
      } else {
        setFeed((current) => current && {
          ...current,
          items: current.items.map((item) => item.id === updated.id ? updated : item),
          unread: Math.max(0, current.unread + Number(notice.read) - Number(updated.read)),
        });
      }
    } catch (error) {
      if (denied(error)) onDenied();
      else setError((error as Error).message);
    } finally {
      setSaving(false);
    }
  };
  const busy = loading || saving;
  const filter = (onlyUnread: boolean) => {
    if (busy || onlyUnread === unreadOnly) return;
    setUnreadOnly(onlyUnread);
    setStatus("");
    refresh(0);
  };

  return (
    <section className="panel notice-feed" aria-labelledby="inbox-heading">
      <div className="notice-toolbar">
        <div>
          <h2 id="inbox-heading">Inbox</h2>
          {feed && <p>{feed.unread} unread</p>}
        </div>
        <div className="notice-actions" role="group" aria-label="Show notifications">
          <button className="notice-control" aria-pressed={!unreadOnly} aria-disabled={busy}
            onClick={() => filter(false)}>All</button>
          <button className="notice-control" aria-pressed={unreadOnly} ref={unreadFilter}
            aria-disabled={busy} onClick={() => filter(true)}>Unread</button>
        </div>
        <button className="notice-control" disabled={busy} onClick={() => { setStatus(""); refresh(0); }}>Refresh</button>
      </div>
      <div role="status">{loading ? "Loading notifications…" : status}</div>
      {error && <p className="error" role="alert">{error}</p>}
      {feed && (feed.items.length ? (
        <ul className="notice-list">
          {feed.items.map((notice) => (
            <NoticeItem key={notice.id} notice={notice} tournament={tournaments.get(notice.tournament_id)}
              action={{ busy, toggle: () => void toggle(notice) }} />
          ))}
        </ul>
      ) : <p>{unreadOnly ? "No unread notifications." : "No notifications yet."}</p>)}
      {feed && feed.total > pageSize && (
        <nav className="notice-actions notice-pagination" aria-label="Notification pages">
          <button className="notice-control" disabled={!offset || busy} onClick={() => refresh(offset - pageSize)}>Previous</button>
          <p>{offset + 1}–{offset + feed.items.length} of {feed.total}</p>
          <button className="notice-control" disabled={offset + pageSize >= feed.total || busy}
            onClick={() => refresh(offset + pageSize)}>Next</button>
        </nav>
      )}
    </section>
  );
}

const NO_ACCESS = "Notifications are available to signed-in participants with a linked tournament account.";

export function Inbox({ tournaments }: { tournaments: ReadonlyMap<string, string> }) {
  const [blocked, block] = useState(false);
  const onDenied = useCallback(() => block(true), []);
  return (
    <>
      <div className="workspace-heading"><h1>Notifications</h1></div>
      {blocked ? <div className="panel"><p role="alert">{NO_ACCESS}</p></div> : (
        <div className="notice-layout">
          <InboxFeed tournaments={tournaments} onDenied={onDenied} />
          <EmailPreference onDenied={onDenied} />
        </div>
      )}
    </>
  );
}

export function TournamentNotices({ tournamentId }: { tournamentId: string }) {
  const [feed, setFeed] = useState<Feed | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    api<Feed>(`/notifications/?limit=3&tournament_id=${encodeURIComponent(tournamentId)}`, {
      signal: controller.signal,
    }).then(setFeed).catch((error: Error) => {
      if (!controller.signal.aborted) setError(denied(error) ? NO_ACCESS : error.message);
    });
    return () => controller.abort();
  }, [tournamentId]);

  return (
    <section className="panel notice-feed" aria-labelledby="tournament-notices-heading">
      <div className="notice-toolbar">
        <h2 id="tournament-notices-heading">Tournament notices</h2>
        {feed && <a href="/notifications">Open inbox</a>}
      </div>
      {error ? <p className="error" role="alert">{error}</p> : !feed ? <p role="status">Loading notices…</p> :
        feed.items.length ? (
          <ul className="notice-list">
            {feed.items.map((notice) => <NoticeItem key={notice.id} notice={notice} />)}
          </ul>
        ) : <p>No notices for this tournament yet.</p>}
    </section>
  );
}
