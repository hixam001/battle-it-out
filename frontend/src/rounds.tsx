import { useEffect, useRef, useState } from "react";
import { api } from "./api";

type Tournament = { id: string; name: string; status: string; deadlines: { submission: number } };
type Pool = { id: string; maps: { play: string[]; tiebreak_normal: string[]; tiebreak_final: string[] } };
type MapPools = { items: Pool[]; selected_id: string | null; version: number };
type Round = {
  number: number; status: string; final: boolean;
  matches: { index: number }[];
};
type Bracket = { rounds: Round[]; map_pool_id: string | null; teams: string[] };
type Data = { bracket: Bracket | null; pools: MapPools };
type Decision = { action: "draw" } | { action: "start"; round: number };

export function RoundControls({ tournament }: { tournament?: Tournament }) {
  if (!tournament) return <section className="empty"><h1>Manage rounds</h1><p>This tournament is unavailable.</p></section>;
  return <TournamentRounds tournament={tournament} />;
}

function TournamentRounds({ tournament }: { tournament: Tournament }) {
  const id = encodeURIComponent(tournament.id);
  const path = `/tournaments/${id}/`;
  const [data, setData] = useState<Data>();
  const [selected, setSelected] = useState("");
  const [confirmed, setConfirmed] = useState<Decision>();
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [actionError, setActionError] = useState("");
  const [message, setMessage] = useState("");
  const roundKeys = useRef(new Map<number, string>());

  useEffect(() => {
    const controller = new AbortController();
    const options = { signal: controller.signal };
    setLoadError("");
    Promise.all([api<{ bracket: Bracket | null }>(path + "bracket/", options), api<MapPools>(path + "map-pool/", options)])
      .then(([result, pools]) => {
        if (controller.signal.aborted) return;
        setData({ bracket: result.bracket, pools });
        setSelected(pools.selected_id ?? "");
      })
      .catch((error: Error) => {
        if (controller.signal.aborted) return;
        setData(undefined);
        setLoadError(error.message);
      });
    return () => controller.abort();
  }, [path, revision]);

  function refresh() {
    setConfirmed(undefined);
    setActionError("");
    setRevision((value) => value + 1);
  }

  async function run(action: () => Promise<string>) {
    if (busy) return;
    setBusy(true);
    setMessage("");
    setActionError("");
    try {
      setMessage(await action());
      refresh();
    } catch (error) {
      setActionError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function start(round: number) {
    let key = roundKeys.current.get(round);
    if (!key) {
      key = crypto.randomUUID();
      roundKeys.current.set(round, key);
    }
    return run(async () => {
      const result = await api<{ status: string }>(path + `rounds/${round}/start/`, {
        method: "POST", body: JSON.stringify({ confirm: true, idempotency_key: key }),
      });
      return result.status === "completed" ? `Round ${round} is complete.` : `Round ${round} queued.`;
    });
  }

  const locked = Date.now() / 1000 >= tournament.deadlines.submission;
  const canSelect = !data?.bracket && (["draft", "rejected"].includes(tournament.status) ||
    (!locked && ["approved", "registration_open"].includes(tournament.status)));
  const canDraw = data && !data.bracket && locked && Boolean(data.pools.selected_id) && tournament.status === "registration_open";
  const pool = data?.pools.items.find((pool) => pool.id === (data.bracket?.map_pool_id ?? selected));
  return (
    <>
      <div className="workspace-heading">
        <div><p className="eyebrow">{tournament.name}</p><h1>Manage rounds</h1></div>
        <a href={`/organizer/tournaments/${id}`}>Back to tournament</a>
      </div>
      <div className="panel-toolbar">
        <button className="text-button" onClick={refresh} disabled={busy}>Refresh rounds</button>
        <a href={`/participant/tournaments/${id}/bracket`}>Open bracket &amp; results</a>
      </div>
      {message && <p className="success" role="status">{message}</p>}
      {actionError && <p className="error" role="alert">{actionError}</p>}
      {loadError ? <p className="error" role="alert">{loadError}</p> :
        !data ? <p role="status">Loading round controls…</p> : (
          <>
            <section className="panel">
              <h2>Map pool</h2>
              <p>Selected pool: {data.bracket?.map_pool_id ?? data.pools.selected_id ?? "None"}</p>
              {canSelect && <form onSubmit={(event) => {
                event.preventDefault();
                if (!selected || selected === data.pools.selected_id) return;
                void run(async () => {
                  await api(path + "map-pool/", {
                    method: "PUT", body: JSON.stringify({ map_pool_id: selected, expected_version: data.pools.version }),
                  });
                  return "Map pool selected.";
                });
              }}>
                <label>Available map pools
                  <select value={selected} disabled={busy} onChange={(event) => setSelected(event.target.value)}>
                    <option value="">Select a map pool</option>
                    {data.pools.items.map((pool) => <option key={pool.id} value={pool.id}>{pool.id}</option>)}
                  </select>
                </label>
                <button className="text-button" disabled={busy || !selected || selected === data.pools.selected_id}>Save map pool</button>
              </form>}
              {pool && <p>Play: {pool.maps.play.join(", ")}. Normal tie-break: {pool.maps.tiebreak_normal.join(", ")}.
                Final tie-breaks: {pool.maps.tiebreak_final.join(", ")}.</p>}
            </section>
            {!data.bracket ? (
              <section className="panel">
                <h2>Bracket draw</h2>
                <p>The draw pins the eligible teams’ bot versions. Rounds start separately.</p>
                {canDraw ? (
                  <>
                    <label className="review-confirm">
                      <input type="checkbox" checked={confirmed?.action === "draw"} disabled={busy}
                        onChange={(event) => setConfirmed(event.target.checked ? { action: "draw" } : undefined)} />
                      Confirm bracket generation
                    </label>
                    <button className="primary" disabled={busy || confirmed?.action !== "draw"} onClick={() => run(async () => {
                      const result = await api<{ excluded: string[] }>(path + "bracket/generate/", {
                        method: "POST", body: JSON.stringify({ confirm: true }),
                      });
                      return result.excluded.length ? `Bracket generated. Excluded teams: ${result.excluded.join(", ")}.`
                        : "Bracket generated. No rounds have been started.";
                    })}>Generate bracket</button>
                  </>
                ) : <p>Draw requires a selected pool, open registration status, and the submission deadline to have passed.</p>}
              </section>
            ) : (
              <section className="panel">
                <h2>Rounds</h2>
                <p>{data.bracket.teams.length} teams in the draw.</p>
                <ol className="series-games">{data.bracket.rounds.map((round) => {
                  const checked = confirmed?.action === "start" && confirmed.round === round.number;
                  const count = round.matches.length;
                  return (
                    <li key={round.number}>
                      <div><h3>{round.final ? "Final" : `Round ${round.number}`}</h3>
                        <p>{round.status.replaceAll("_", " ")} · {count} {count === 1 ? "pairing" : "pairings"}</p>
                      </div>
                      {round.status === "ready" && <div>
                        <label className="review-confirm">
                          <input type="checkbox" checked={checked} disabled={busy}
                            onChange={(event) => setConfirmed(event.target.checked ? { action: "start", round: round.number } : undefined)} />
                          Confirm start of round {round.number}
                        </label>
                        <button className="primary" disabled={busy || !checked}
                          onClick={() => start(round.number)}>Start round {round.number}</button>
                      </div>}
                    </li>
                  );
                })}</ol>
              </section>
            )}
          </>
        )}
    </>
  );
}
