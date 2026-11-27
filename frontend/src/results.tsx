import { useEffect, useState } from "react";
import { ApiError, api } from "./api";

type GameRef = { match_id: string; status: string };
type Sides<T> = { A: T; B: T };
type Pairing = {
  index: number;
  a: string | null;
  b: string | null;
  bye: boolean;
  winner: string | null;
  result_type: string | null;
  series: { status: string; wins: Sides<number>; games: GameRef[] } | null;
};
type Bracket = {
  status: string;
  champion: string | null;
  rounds: { number: number; final: boolean; status: string; matches: Pairing[] }[];
};
type Game = GameRef & {
  kind: "primary" | "tiebreak";
  map: string;
  outcome: "decided" | "tied" | "forfeit" | null;
  winner_team: string | null;
  round: number | null;
};
type Match = {
  tournament_id: string;
  round_number: number;
  series: {
    stage: "normal" | "final";
    status: string;
    teams: Sides<string>;
    wins: Sides<number>;
    versions: Sides<string>;
    games: Game[];
    tiebreak_maps: string[];
    result: { winner_team: string; result_type: string } | null;
    coin_flip: { result_team: string; probability_each: number; drawn_at: string } | null;
  };
};
type ReplayStatus = { status: "available" | "pending" | "unavailable" | "archived" };

const states: Record<string, string> = {
  pending: "Pending",
  scheduled: "Scheduled",
  ready: "Ready to start",
  queued: "Queued",
  running: "Running",
  in_progress: "In progress",
  platform_failed: "Platform failure",
  retry_queued: "Retry queued",
  paused: "Paused",
  bot_forfeit: "Bot forfeit",
  completed: "Completed",
};
const decisions: Record<string, string> = {
  normal: "Main game",
  tiebreak: "Tie-break games",
  coin_flip: "Tournament coin flip",
  bot_forfeit: "Bot forfeit",
  bye: "Bye",
};
const matchPath = (id: string) => `/matches/${encodeURIComponent(id)}`;
const bracketPath = (id: string) => `/participant/tournaments/${encodeURIComponent(id)}/bracket`;
const stateLabel = (state: string) => states[state] ?? state.replaceAll("_", " ");

function useResult<T>(path: string) {
  const [data, setData] = useState<T>();
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    api<T>(path, { signal: controller.signal })
      .then((result) => { setError(""); setData(result); })
      .catch((error: Error) => {
        if (controller.signal.aborted) return;
        setData(undefined);
        setError(error instanceof ApiError && error.status === 404
          ? "This record is unavailable to your account." : error.message);
      });
    return () => controller.abort();
  }, [path, revision]);
  return { data, error, refresh: () => setRevision((value) => value + 1) };
}

export function BracketResults({ tournament }: { tournament: { id: string; name: string; status: string } }) {
  const { data, error, refresh } = useResult<{ bracket: Bracket | null }>(
    `/tournaments/${encodeURIComponent(tournament.id)}/bracket/`,
  );
  const bracket = data?.bracket;
  return (
    <>
      <div className="workspace-heading">
        <div><p className="eyebrow">{tournament.name}</p><h1>Bracket &amp; results</h1></div>
        <button className="text-button" onClick={refresh}>Refresh bracket</button>
      </div>
      {error ? <p className="error" role="alert">{error}</p> :
        !data ? <p role="status">Loading bracket…</p> :
        !bracket ? <section className="panel"><h2>Awaiting bracket draw</h2></section> : (
          <>
            <p className="bracket-overview">
              {tournament.status === "archived" ? "Archived" : stateLabel(bracket.status)}
              {bracket.champion && <> · Champion <strong>{bracket.champion}</strong></>}
            </p>
            <div className="bracket-rounds">
              {bracket.rounds.map((round) => (
                <section className="panel bracket-round" key={round.number} aria-labelledby={`round-${round.number}`}>
                  <h2 id={`round-${round.number}`}>{round.final ? "Final" : `Round ${round.number}`}</h2>
                  <p>{stateLabel(round.status)}</p>
                  <ol>
                    {round.matches.map((match) => <PairingCard key={match.index} match={match} />)}
                  </ol>
                </section>
              ))}
            </div>
          </>
        )}
    </>
  );
}

function PairingCard({ match }: { match: Pairing }) {
  const latest = match.series?.games.at(-1);
  return (
    <li className="bracket-pairing">
      <h3>{match.a ?? "To be decided"} {match.bye ? "· Bye" : `vs ${match.b ?? "To be decided"}`}</h3>
      {match.series && <p>Game wins <strong>{match.series.wins.A}–{match.series.wins.B}</strong></p>}
      {match.winner ? (
        <p><strong>{match.winner} advances</strong>
          {match.result_type && <> · {decisions[match.result_type]}</>}
        </p>
      ) : <p>{latest ? stateLabel(latest.status) : "Pending"}</p>}
      {latest && <a href={matchPath(latest.match_id)}>Match details</a>}
    </li>
  );
}

export function MatchResult({ matchId }: { matchId: string }) {
  const { data, error, refresh } = useResult<Match>(matchPath(matchId) + "/");
  const series = data?.series;
  const currentGame = series?.games.find((game) => game.match_id === matchId);
  return (
    <>
      <div className="workspace-heading">
        <div>
          {series && <p className="eyebrow">{series.stage === "final" ? "Final" : `Round ${data?.round_number}`}</p>}
          <h1>{series ? `${series.teams.A} vs ${series.teams.B}` : "Match details"}</h1>
        </div>
        <button className="text-button" onClick={refresh}>Refresh result</button>
      </div>
      {error ? <p className="error" role="alert">{error}</p> :
        !series || !data ? <p role="status">Loading match…</p> : (
          <>
            <section className="panel" aria-label="Series result">
              <div className="panel-toolbar"><h2>Series result</h2><a href={bracketPath(data.tournament_id)}>Back to bracket</a></div>
              <p>Game wins <strong>{series.wins.A}–{series.wins.B}</strong></p>
              {series.result ? <p><strong>{series.result.winner_team} won</strong> · {decisions[series.result.result_type]}</p> :
                <p>{stateLabel(series.status)}</p>}
              <p>Bot versions <code>{series.versions.A}</code> and <code>{series.versions.B}</code></p>
              {series.coin_flip && (
                <div className="recorded-coin">
                  <h3>Recorded coin flip</h3>
                  <p>The tie persisted after the tie-break games. Each team had a {series.coin_flip.probability_each * 100}%
                    chance, and the one recorded flip selected <strong>{series.coin_flip.result_team}</strong>.</p>
                  <time dateTime={series.coin_flip.drawn_at}>{new Date(series.coin_flip.drawn_at).toLocaleString()}</time>
                </div>
              )}
            </section>
            <section className="panel" aria-label="Games in this series">
              <h2>Games</h2>
              {series.tiebreak_maps.length > 0 && <p>Tie-break map order: {series.tiebreak_maps.join(", ")}</p>}
              <ol className="series-games">
                {series.games.map((game, index) => (
                  <li key={game.match_id} aria-current={game.match_id === matchId ? "true" : undefined}>
                    <div>
                      <h3>Game {index + 1} · {game.map}</h3>
                      <p>{game.kind === "tiebreak" ? "Tie-break game" : "Main game"}
                        {" · "}{game.outcome === "tied" ? "Tied" : stateLabel(game.status)}
                        {game.winner_team && <> · {game.winner_team} won</>}
                        {game.round != null && <> · Engine round {game.round}</>}
                      </p>
                    </div>
                    {game.match_id === matchId ? <span className="muted">Selected game</span> :
                      <a href={matchPath(game.match_id)}>Select game {index + 1}</a>}
                  </li>
                ))}
              </ol>
            </section>
            {currentGame && (
              <section className="panel" aria-label="Game artifacts">
                <h2>Selected game</h2>
                <p>{currentGame.map} · {stateLabel(currentGame.status)}</p>
                <a href={matchPath(matchId) + "/replay"}>Replay</a>
                {" · "}
                <a href={matchPath(matchId) + "/logs"}>Structured match log</a>
              </section>
            )}
          </>
        )}
    </>
  );
}

export function Replay({ matchId }: { matchId: string }) {
  const path = matchPath(matchId);
  const { data, error, refresh } = useResult<ReplayStatus>(path + "/replay-status/");
  return (
    <>
      <div className="workspace-heading">
        <h1>Match replay</h1>
        <a href={path}>Back to match</a>
      </div>
      <section className="panel" aria-label="Replay availability">
        {error ? <p className="error" role="alert">{error}</p> :
          !data ? <p role="status">Checking replay availability…</p> :
          data.status === "available" ? (
            <>
              <p>Open the native .bc26 file in the Battlecode replay client.</p>
              <a href={`/api/v1${path}/replay/`} download>Download replay</a>
            </>
          ) : (
            <p role="status">{data.status === "archived" ? "Replay no longer available. The tournament is archived." :
              data.status === "pending" ? "Replay is pending while the game is in progress." : "Replay is unavailable."}</p>
          )}
        <p><button className="text-button" onClick={refresh}>Refresh replay status</button></p>
      </section>
    </>
  );
}
