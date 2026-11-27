import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api } from "./api";
import { InitialCodes } from "./initial-codes";

type Tournament = { id: string; name: string; status: string; deadlines: { registration: number } };
type Invitation = {
  id: string;
  entry_id: string;
  status: "issued" | "revoked" | "consumed" | "expired";
  issued_at: string;
  replaced_by: string | null;
};
type Replacement = { code_id: string; code: string };
type Action = "revoke" | "replace";

export function InvitationControls({ tournament }: { tournament: Tournament }) {
  const path = `/tournaments/${encodeURIComponent(tournament.id)}/invitation-codes/`;
  const [items, setItems] = useState<Invitation[]>();
  const [selected, setSelected] = useState<string>();
  const [replacement, setReplacement] = useState<Replacement>();
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const open = ["approved", "registration_open"].includes(tournament.status) &&
    tournament.deadlines.registration > Date.now() / 1000;
  const invitation = items?.find((item) => item.id === selected);

  useEffect(() => {
    const controller = new AbortController();
    setError("");
    api<{ items: Invitation[] }>(path, { signal: controller.signal })
      .then((response) => setItems(response.items))
      .catch((error: Error) => {
        if (controller.signal.aborted) return;
        setItems(undefined);
        setError(error.message);
      });
    return () => controller.abort();
  }, [path, revision]);

  return (
    <>
      <div className="workspace-heading">
        <div><p className="eyebrow">{tournament.name}</p><h1>Invitation codes</h1></div>
        <button className="text-button" disabled={Boolean(selected)} onClick={() => {
          setSelected(undefined);
          setReplacement(undefined);
          setMessage("");
          setRevision((value) => value + 1);
        }}>Refresh invitation codes</button>
      </div>
      {message && <p className="success" role="status">{message}</p>}
      {replacement && (
        <section className="panel" aria-labelledby="replacement-code">
          <div className="panel-toolbar">
            <h2 id="replacement-code">Replacement code</h2>
            <button className="text-button" onClick={() => setReplacement(undefined)}>Dismiss replacement code</button>
          </div>
          <p>Share this code privately with the roster participant. It is displayed here once.</p>
          <p>Code ID <code>{replacement.code_id}</code></p>
          <output aria-label="New invitation code"><code>{replacement.code}</code></output>
        </section>
      )}
      <section className="panel" aria-label="Invitation list">
        {error ? <p className="error" role="alert">{error}</p> :
          !items ? <p role="status">Loading invitation codes…</p> :
          items.length === 0 ? <p>No codes have been issued for this tournament.</p> : (
            <div className="table-wrap">
              <table aria-label="Invitation metadata">
                <thead><tr>
                  <th scope="col">Code ID</th><th scope="col">Roster entry</th><th scope="col">Status</th>
                  <th scope="col">Issued</th><th scope="col">Actions</th>
                </tr></thead>
                <tbody>
                  {items.map((item) => (
                    <tr key={item.id}>
                      <th scope="row">{item.id}</th><td>{item.entry_id}</td>
                      <td>{item.replaced_by ? "Replaced" : item.status}</td>
                      <td><time dateTime={item.issued_at}>{new Date(item.issued_at).toLocaleString()}</time></td>
                      <td>{actions(item, open).length > 0 && (
                        <button className="text-button" aria-label={`Manage code ${item.id}`}
                          disabled={Boolean(selected)}
                          onClick={() => { setReplacement(undefined); setMessage(""); setSelected(item.id); }}>
                          Manage
                        </button>
                      )}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
      </section>
      {open && !selected && !replacement &&
        <InitialCodes tournamentId={tournament.id} onIssued={() => setRevision((value) => value + 1)} />}
      {invitation && (
        <ManageInvitation key={invitation.id} invitation={invitation} path={path} open={open}
          cancel={() => setSelected(undefined)} complete={(result) => {
            setSelected(undefined);
            setReplacement(result);
            setMessage(result ? "Invitation replaced. The old code is revoked." : "Invitation revoked.");
            setRevision((value) => value + 1);
          }} />
      )}
    </>
  );
}

function actions(invitation: Invitation, open: boolean): Action[] {
  if (invitation.status === "consumed" || invitation.replaced_by) return [];
  const available: Action[] = invitation.status === "revoked" ? [] : ["revoke"];
  if (open) available.push("replace");
  return available;
}

function ManageInvitation({ invitation, path, open, cancel, complete }: {
  invitation: Invitation; path: string; open: boolean; cancel: () => void; complete: (result?: Replacement) => void;
}) {
  const available = actions(invitation, open);
  const [action, setAction] = useState(available[0]);
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const ready = !busy && confirmed && reason.trim() && available.includes(action);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!ready) return;
    setBusy(true);
    setError("");
    try {
      const result = await api<Replacement | Invitation>(path + `${encodeURIComponent(invitation.id)}/${action}/`, {
        method: "POST", body: JSON.stringify({ reason: reason.trim(), confirm: true }),
      });
      complete("code" in result ? result : undefined);
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel" aria-label="Manage selected invitation">
      <h2>Manage invitation</h2>
      <p>Code ID <code>{invitation.id}</code></p>
      <form onSubmit={submit}>
        <label>Action
          <select value={action} disabled={busy} onChange={(event) => {
            setAction(event.target.value === "replace" ? "replace" : "revoke");
            setConfirmed(false);
            setError("");
          }}>
            {available.map((item) => <option key={item} value={item}>{item === "replace" ? "Replace" : "Revoke"}</option>)}
          </select>
        </label>
        <label>Reason
          <textarea required maxLength={500} value={reason} disabled={busy}
            onChange={(event) => setReason(event.target.value)} />
        </label>
        <label className="review-confirm">
          <input type="checkbox" checked={confirmed} disabled={busy} onChange={(event) => setConfirmed(event.target.checked)} />
          Confirm this invitation change
        </label>
        {error && <p className="error" role="alert">{error}</p>}
        <div className="notice-actions">
          <button className="primary" type="submit" disabled={!ready}>
            {busy ? "Saving…" : action === "replace" ? "Replace invitation" : "Revoke invitation"}
          </button>
          <button className="text-button" type="button" disabled={busy} onClick={cancel}>Cancel</button>
        </div>
      </form>
    </section>
  );
}
