import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { api } from "./api";

type Tournament = { id: string; name: string; status: string; deadlines: { registration: number; submission: number } };
type Action = "extend-deadline" | "emergency-override";
type Receipt = { affected_participants: number; notification_status: "pending" | "published"; audit_event_id: string };
type Pool = { id: string };
const extend = "extend-deadline";
const override = "emergency-override";

export function DeadlineControls({ tournament, refresh, settingsPath }: {
  tournament: Tournament; refresh: () => Promise<void>; settingsPath: string;
}) {
  const [chosen, setChosen] = useState<Action>(extend);
  const canExtend = ["approved", "registration_open"].includes(tournament.status);
  const preDraw = canExtend;
  const canOverride = (preDraw || ["running", "completed"].includes(tournament.status)) &&
    tournament.deadlines.submission <= Date.now() / 1000;
  const action = chosen === extend && canExtend ? extend : canOverride ? override : extend;
  const available = canExtend || canOverride;

  return (
    <>
      <div className="workspace-heading">
        <div><p className="eyebrow">{tournament.name}</p><h1>Deadline controls</h1></div>
        <a href={settingsPath}>Tournament settings</a>
      </div>
      <section className="panel tournament-overview">
        <h2>Current deadlines</h2>
        <dl>
          <div><dt>Registration deadline</dt><dd><Deadline stamp={tournament.deadlines.registration} /></dd></div>
          <div><dt>Submission deadline</dt><dd><Deadline stamp={tournament.deadlines.submission} /></dd></div>
        </dl>
      </section>
      {available ? (
        <section className="panel" aria-label="Deadline action">
          {canExtend && canOverride && <label>Action
            <select value={action} onChange={(event) => setChosen(event.target.value === override ? override : extend)}>
              <option value={extend}>Extend a deadline</option>
              <option value={override}>Override a locked setting</option>
            </select>
          </label>}
          <ChangeForm key={action} tournament={tournament} action={action} preDraw={preDraw} refresh={refresh} />
        </section>
      ) : <p>No deadline action is available in the current tournament state.</p>}
    </>
  );
}

function Deadline({ stamp }: { stamp: number }) {
  const time = new Date(stamp * 1000);
  return Number.isNaN(time.getTime()) ? <>Unavailable</> :
    <time dateTime={time.toISOString()}>{time.toLocaleString(undefined, { timeZoneName: "short" })}</time>;
}

function ChangeForm({ tournament, action, preDraw, refresh }: {
  tournament: Tournament; action: Action; preDraw: boolean; refresh: () => Promise<void>;
}) {
  const extending = action === extend;
  const path = `/tournaments/${encodeURIComponent(tournament.id)}/`;
  const [field, setField] = useState(extending ? "submission" : "name");
  const [value, setValue] = useState("");
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [pools, setPools] = useState<Pool[]>();
  const [receipt, setReceipt] = useState<Receipt>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const token = useRef<{ payload: string; key: string }>(null);

  useEffect(() => {
    if (field !== "map_pool_id") return;
    const controller = new AbortController();
    api<{ items: Pool[] }>(path + "map-pool/", { signal: controller.signal })
      .then((data) => setPools(data.items))
      .catch((error: Error) => { if (!controller.signal.aborted) setError(error.message); });
    return () => controller.abort();
  }, [field, path]);

  const ready = Boolean(!busy && confirmed && reason.trim() && (value.trim() || field === "description"));
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!ready) return;
    setBusy(true);
    setError("");
    setReceipt(undefined);
    try {
      const change = extending
        ? { deadline_type: field, new_deadline: new Date(value).toISOString() }
        : { setting: field, value: value.trim() };
      const payload = JSON.stringify({ ...change, reason: reason.trim(), confirm: true });
      if (token.current?.payload !== payload) token.current = { payload, key: crypto.randomUUID() };
      const result = await api<Receipt>(path + action + "/", {
        method: "POST", headers: { "Idempotency-Key": token.current.key }, body: payload,
      });
      setReceipt(result);
      setConfirmed(false);
      setValue("");
      setReason("");
      token.current = null;
      await refresh();
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function chooseField(next: string) {
    setField(next);
    setValue("");
    setConfirmed(false);
    setError("");
    setReceipt(undefined);
  }

  return (
    <>
      <h2>{extending ? "Extend a deadline" : "Override a locked setting"}</h2>
      <form onSubmit={submit}>
        <label>{extending ? "Deadline" : "Locked setting"}
          <select disabled={busy} value={field} onChange={(event) => chooseField(event.target.value)}>
            {extending ? (
              <><option value="submission">Submission</option><option value="registration">Registration</option></>
            ) : (
              <><option value="name">Tournament name</option><option value="description">Description</option>
                {preDraw && <option value="map_pool_id">Map pool</option>}</>
            )}
          </select>
        </label>
        {extending ? (
          <label>New deadline
            <input type="datetime-local" required disabled={busy} value={value} onChange={(event) => setValue(event.target.value)} />
          </label>
        ) : field === "map_pool_id" ? (
          <label>Replacement map pool
            <select value={value} required disabled={busy || !pools?.length} onChange={(event) => setValue(event.target.value)}>
              <option value="">{pools?.length ? "Select pool" : "No pools available"}</option>
              {pools?.map((pool) => <option key={pool.id} value={pool.id}>{pool.id}</option>)}
            </select>
          </label>
        ) : field === "description" ? (
          <label>Replacement description
            <textarea maxLength={2000} disabled={busy} value={value} onChange={(event) => setValue(event.target.value)} />
          </label>
        ) : (
          <label>Replacement name
            <input required maxLength={120} disabled={busy} value={value} onChange={(event) => setValue(event.target.value)} />
          </label>
        )}
        {extending && <p className="muted">Timezone {Intl.DateTimeFormat().resolvedOptions().timeZone}</p>}
        <label>Reason
          <textarea required maxLength={500} disabled={busy} value={reason} onChange={(event) => setReason(event.target.value)} />
        </label>
        <label className="review-confirm">
          <input type="checkbox" disabled={busy} checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />
          Confirm this change for {tournament.name}
        </label>
        <button className="primary" type="submit" disabled={!ready}>
          {busy ? "Saving…" : extending ? "Extend deadline" : "Apply emergency override"}
        </button>
      </form>
      {error && <p className="error" role="alert">{error}</p>}
      {receipt && <p className="success" role="status">
        Change recorded. Affected accounts: {receipt.affected_participants}.{" "}
        {receipt.notification_status === "published" ? "Dashboard notices published."
          : "Dashboard notices are pending and will retry automatically."}
      </p>}
    </>
  );
}
