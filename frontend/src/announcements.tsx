import { useRef, useState } from "react";
import type { FormEvent } from "react";
import { api } from "./api";

type Tournament = { id: string; name: string; status: string };
type Receipt = { id: string; recipients: number; email_queued: number };
const published = ["approved", "registration_open", "running", "completed"];

export function AnnouncementForm({ tournament }: { tournament: Tournament }) {
  const [headline, setHeadline] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [receipt, setReceipt] = useState<Receipt>();
  const [busy, setBusy] = useState(false);
  const attempt = useRef<{ payload: string; key: string }>(null);
  const canPublish = published.includes(tournament.status);

  async function publish(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canPublish || busy || !headline.trim() || !message.trim()) return;
    setError("");
    setReceipt(undefined);
    if (/[\u0000-\u001f\u007f]/u.test(headline) || /[\u0000-\u001f\u007f]/u.test(message)) {
      setError("Use plain text without line breaks or tabs.");
      return;
    }
    const payload = JSON.stringify({ headline: headline.trim(), message: message.trim() });
    if (attempt.current?.payload !== payload) attempt.current = { payload, key: crypto.randomUUID() };
    setBusy(true);
    try {
      const published = await api<Receipt>(`/tournaments/${encodeURIComponent(tournament.id)}/announcements/`, {
        method: "POST",
        headers: { "Idempotency-Key": attempt.current.key },
        body: payload,
      });
      setReceipt(published);
      attempt.current = null;
      setHeadline("");
      setMessage("");
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="workspace-heading"><h1>Post announcement</h1></div>
      <section className="panel" aria-label="Tournament announcement">
        <h2>{tournament.name}</h2>
        {canPublish ? (
          <>
            <p>The verified roster receives this in the participant inbox. Email follows each recipient's preference.</p>
            <form onSubmit={publish}>
              <label>Headline
                <input required maxLength={120} value={headline} disabled={busy}
                  onChange={(event) => setHeadline(event.target.value)} />
              </label>
              <label>Message
                <textarea required maxLength={2000} value={message} disabled={busy}
                  aria-describedby="announcement-text-hint" onChange={(event) => setMessage(event.target.value)} />
              </label>
              <p className="muted" id="announcement-text-hint">Write a single paragraph of plain text.</p>
              <button className="primary" type="submit" disabled={busy || !headline.trim() || !message.trim()}>
                {busy ? "Posting…" : "Publish announcement"}
              </button>
            </form>
            {error && <p className="error" role="alert">{error}</p>}
            {receipt && (
              <p className="success" role="status">
                {receipt.recipients === 0 ? "No verified roster accounts received this announcement."
                  : `Inbox notices posted: ${receipt.recipients}. Emails queued: ${receipt.email_queued}.`}
              </p>
            )}
          </>
        ) : <p>Announcements are available after approval and before archive.</p>}
      </section>
    </>
  );
}
