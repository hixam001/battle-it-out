import { useEffect, useState } from "react";
import { api } from "./api";
import { ReadOnlySubmissions, TeamRoster } from "./participant";

type Tournament = { id: string; name: string; status: string; deadlines: { submission: number } };
type RosterTeam = { team_key: string; team_name: string };

export function OrganizerTeams({ tournament }: { tournament?: Tournament }) {
  if (!tournament) return <section className="empty"><h1>Tournament teams</h1><p>This tournament is unavailable.</p></section>;
  return <TeamDirectory tournament={tournament} />;
}

function TeamDirectory({ tournament }: { tournament: Tournament }) {
  const id = encodeURIComponent(tournament.id);
  const [teams, setTeams] = useState<Map<string, string>>();
  const [selected, setSelected] = useState("");
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setError("");
    api<{ items: RosterTeam[] }>(`/tournaments/${id}/roster/`, { signal: controller.signal })
      .then(({ items }) => {
        if (controller.signal.aborted) return;
        const directory = new Map<string, string>();
        for (const entry of items) directory.set(entry.team_key, entry.team_name);
        setTeams(directory);
        setSelected((current) => directory.has(current) ? current : directory.keys().next().value ?? "");
      })
      .catch((error: Error) => {
        if (controller.signal.aborted) return;
        setTeams(undefined);
        setSelected("");
        setError(error.message);
      });
    return () => controller.abort();
  }, [id, revision]);

  return (
    <>
      <div className="workspace-heading">
        <div><p className="eyebrow">{tournament.name}</p><h1>Tournament teams</h1></div>
        <a href={`/organizer/tournaments/${id}`}>Back to tournament</a>
      </div>
      <section className="panel" aria-label="Team directory">
        <button className="text-button" onClick={() => setRevision((value) => value + 1)}>Refresh team list</button>
        {error ? <p className="error" role="alert">{error}</p> :
          !teams ? <p role="status">Loading teams…</p> :
          teams.size === 0 ? <p>No teams are on the roster.</p> : (
            <label>Team
              <select value={selected} onChange={(event) => setSelected(event.target.value)}>
                {Array.from(teams, ([team, name]) => <option key={team} value={team}>{name} ({team})</option>)}
              </select>
            </label>
          )}
      </section>
      {teams?.has(selected) && (
        <>
          <section className="panel" aria-label="Selected team">
            <TeamRoster key={selected} cup={tournament} team={selected} />
          </section>
          <ReadOnlySubmissions key={selected} cup={tournament} team={selected} />
        </>
      )}
    </>
  );
}
