import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api } from "./api";

type Tournament = {
  id: string;
  status: string;
  deadlines: { submission: number };
  teams?: string[];
  captain_teams?: string[];
};

type TeamProfile = {
  name: string;
  members: { member_number: number; role_label: string; is_captain: boolean }[];
};
type Bracket = {
  teams: string[];
  champion: string | null;
  rounds: { matches: { a: string | null; b: string | null; winner: string | null }[] }[];
};

type Finding = { code: string; message: string; line?: number | null; side?: "A" | "B" };
type Version = {
  id: string;
  version: number;
  format?: string;
  is_active: boolean;
  validation_status: string;
  check_in_progress: boolean;
  validations: { stage: string; status: string; reasons: Finding[]; warnings: Finding[] }[];
};

type Dependency = { name: string; version: string; description: string };
type Catalog = { items: Dependency[]; max_bytes: number; max_files: number };

const teamPath = (cup: Tournament, team: string) =>
  `/tournaments/${encodeURIComponent(cup.id)}/teams/${encodeURIComponent(team)}/`;

function TeamPicker({ teams, team, change }: {
  teams: string[]; team: string; change: (team: string) => void;
}) {
  if (teams.length < 2) return null;
  return (
    <label>
      Team
      <select value={team} onChange={(event) => change(event.target.value)}>
        {teams.map((id) => <option key={id} value={id}>{id}</option>)}
      </select>
    </label>
  );
}

export function Team({ cup }: { cup: Tournament }) {
  const teams = cup.teams ?? [];
  const [selected, setSelected] = useState("");
  const team = teams.includes(selected) ? selected : teams[0];
  if (!team) return <p>No verified team is available for this tournament.</p>;
  return (
    <section className="panel">
      <TeamPicker teams={teams} team={team} change={setSelected} />
      <TeamRoster key={team} cup={cup} team={team} />
    </section>
  );
}

export function TeamRoster({ cup, team }: { cup: Tournament; team: string }) {
  const path = teamPath(cup, team);
  const [profile, setProfile] = useState<TeamProfile>();
  const [error, setError] = useState("");
  const [standing, setStanding] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    api<TeamProfile>(path, { signal: controller.signal })
      .then(setProfile)
      .catch((error: Error) => { if (!controller.signal.aborted) setError(error.message); });
    return () => controller.abort();
  }, [path]);
  useEffect(() => {
    if (cup.status === "archived") return;
    const controller = new AbortController();
    api<{ bracket: Bracket | null }>(`/tournaments/${encodeURIComponent(cup.id)}/bracket/`,
      { signal: controller.signal })
      .then(({ bracket }) => {
        if (!bracket) setStanding("Awaiting bracket draw");
        else if (!bracket.teams.includes(team)) setStanding("No bracket entry");
        else if (bracket.champion === team) setStanding("Champion");
        else {
          const eliminated = bracket.rounds.some((round) => round.matches.some(
            ({ a, b, winner }) => (a === team || b === team) && winner !== null && winner !== team,
          ));
          setStanding(eliminated ? "Eliminated" : "Active in bracket");
        }
      })
      .catch(() => { if (!controller.signal.aborted) setStanding("Bracket status unavailable"); });
    return () => controller.abort();
  }, [cup.id, cup.status, team]);

  if (error) return <p className="error" role="alert">{error}</p>;
  if (!profile) return <p role="status">Loading team roster…</p>;
  return (
    <>
      <h2>{profile.name}</h2>
      <p role="status">{cup.status === "archived" ? "Archived" : standing}</p>
      {profile.members.length > 0 ? (
        <table aria-label="Verified team members">
          <thead><tr><th scope="col">Member slot</th><th scope="col">Role</th></tr></thead>
          <tbody>
            {profile.members.map((member) => (
              <tr key={member.member_number}>
                <td>{member.member_number}</td>
                <td>{member.is_captain ? "Captain" : member.role_label}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : <p>No verified members yet.</p>}
    </>
  );
}

export function Submissions({ cup, role, refreshTournament }: {
  cup: Tournament; role: string; refreshTournament: () => Promise<void>;
}) {
  const teams = cup.teams ?? [];
  const [selected, setSelected] = useState("");
  const [staffTeam, setStaffTeam] = useState("");
  const participant = role === "participant";
  const team = participant ? (teams.includes(selected) ? selected : teams[0]) : selected;
  return (
    <>
      {participant ? (
        <TeamPicker teams={teams} team={team ?? ""} change={setSelected} />
      ) : (
        <form className="panel" onSubmit={(event) => {
          event.preventDefault();
          setSelected(staffTeam.trim());
        }}>
          <label>
            Team ID
            <input value={staffTeam} onChange={(event) => setStaffTeam(event.target.value)} required />
          </label>
          <button className="text-button" type="submit">Load team submissions</button>
        </form>
      )}
      {team ? (
        <TeamSubmissions key={team} cup={cup} team={team}
          captain={participant && (cup.captain_teams ?? []).includes(team)}
          refreshTournament={refreshTournament} />
      ) : participant && <p>No verified team is available for this tournament.</p>}
    </>
  );
}

function TeamSubmissions({ cup, team, captain, refreshTournament }: {
  cup: Tournament; team: string; captain: boolean; refreshTournament: () => Promise<void>;
}) {
  const path = teamPath(cup, team) + "submissions/";
  const [catalog, setCatalog] = useState<Catalog>();
  const [file, setFile] = useState<{ data: File; key: string }>();
  const [message, setMessage] = useState("");
  const [uploadError, setUploadError] = useState("");
  const [catalogError, setCatalogError] = useState("");
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  const [clock, setClock] = useState(() => Date.now() / 1000);
  const locked = clock >= cup.deadlines.submission;
  const history = useSubmissionHistory(path, revision);

  useEffect(() => {
    const controller = new AbortController();
    api<Catalog>("/dependencies/", { signal: controller.signal })
      .then(setCatalog)
      .catch((error: Error) => { if (!controller.signal.aborted) setCatalogError(error.message); });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (locked) return;
    const timer = window.setInterval(() => setClock(Date.now() / 1000), 1000);
    return () => window.clearInterval(timer);
  }, [locked]);

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file || !captain || locked || busy) return;
    const form = event.currentTarget;
    setBusy(true);
    setUploadError("");
    setMessage("");
    try {
      const body = new FormData();
      body.append("file", file.data);
      const version = await api<Version>(path, {
        method: "POST", body, headers: { "Idempotency-Key": file.key },
      });
      setMessage(`Version ${version.version} queued for validation.`);
      form.reset();
      setFile(undefined);
    } catch (error) {
      setUploadError((error as Error).message);
    } finally {
      setBusy(false);
      setRevision((value) => value + 1);
    }
  }

  async function refresh() {
    setUploadError("");
    setClock(Date.now() / 1000);
    setRevision((value) => value + 1);
    try {
      await refreshTournament();
    } catch (error) {
      setUploadError((error as Error).message);
    }
  }

  return (
    <>
      <div className="two-col">
        <section className="panel">
          <h2>Upload your strategy</h2>
          {locked ? <p role="status">Submissions are locked. The deadline has passed.</p> :
            !captain ? <p>Only the team captain can upload a bot.</p> : (
              <>
                <p>Upload <code>bot.py</code> or a flat Python ZIP bundle. The entry point is <code>turn()</code>.</p>
                <form onSubmit={upload}>
                  <label className="file-label">
                    Python bot or bundle
                    <input type="file" accept=".py,.zip" required disabled={busy} onChange={(event) => {
                      const data = event.target.files?.[0];
                      setFile(data ? { data, key: crypto.randomUUID() } : undefined);
                    }} />
                  </label>
                  {catalog && <p className="muted">
                    Limit: {catalog.max_bytes / 1024} KiB expanded, up to {catalog.max_files} input files.
                  </p>}
                  <button className="primary" disabled={busy || !file}>
                    {busy ? "Uploading…" : "Upload for validation"}
                  </button>
                </form>
              </>
            )}
          {message && <p className="success" role="status">{message}</p>}
          {uploadError && <p className="error" role="alert">{uploadError}</p>}
        </section>
        <section className="panel">
          <h2>Curated dependencies</h2>
          <p>Declare exact versions in <code>requirements.json</code>. The platform snapshots the pinned source.</p>
          {catalogError && <p className="error" role="alert">{catalogError}</p>}
          {catalog?.items.map((item) => (
            <div key={`${item.name}@${item.version}`} className="dependency">
              <code>{item.name} / {item.version}</code>
              <p>{item.description}</p>
            </div>
          ))}
          {catalog?.items[0] && <pre>{JSON.stringify({ [catalog.items[0].name]: catalog.items[0].version }, null, 2)}</pre>}
        </section>
      </div>
      <SubmissionHistory cup={cup} {...history} refresh={refresh} />
    </>
  );
}

function useSubmissionHistory(path: string, revision: number) {
  const [versions, setVersions] = useState<Version[] | null>(null);
  const [historyError, setHistoryError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    setHistoryError("");
    api<{ items: Version[] }>(path, { signal: controller.signal })
      .then((data) => { if (!controller.signal.aborted) setVersions(data.items); })
      .catch((error: Error) => {
        if (controller.signal.aborted) return;
        setVersions(null);
        setHistoryError(error.message);
      });
    return () => controller.abort();
  }, [path, revision]);
  return { versions, historyError };
}

export function ReadOnlySubmissions({ cup, team }: { cup: Tournament; team: string }) {
  const [revision, setRevision] = useState(0);
  const history = useSubmissionHistory(teamPath(cup, team) + "submissions/", revision);
  return <SubmissionHistory cup={cup} {...history} refresh={() => setRevision((value) => value + 1)} />;
}

function SubmissionHistory({ cup, versions, historyError, refresh }: {
  cup: Tournament; versions: Version[] | null; historyError: string; refresh: () => void;
}) {
  const active = versions?.find((version) => version.is_active);
  return (
    <section className="panel" aria-labelledby="submission-history">
      <div className="panel-toolbar">
        <h2 id="submission-history">Submission history</h2>
        <button className="text-button" onClick={refresh}>Refresh submissions</button>
      </div>
      {historyError ? <p className="error" role="alert">{historyError}</p> :
        !versions ? <p role="status">Loading submission history…</p> :
        versions.length === 0 ? <p>No stored versions for this team.</p> : (
          <>
            <p>Active version: <strong>{active ? `v${active.version}` : "None"}</strong></p>
            <div className="table-wrap">
              <table aria-label="Submission versions">
                <thead><tr>
                  <th scope="col">Version</th>
                  <th scope="col">Format</th>
                  <th scope="col">Validation</th>
                  <th scope="col">Active</th>
                  <th scope="col">Download</th>
                </tr></thead>
                <tbody>
                  {versions.map((version) => (
                    <tr key={version.id}>
                      <th scope="row">v{version.version}</th>
                      <td>{version.format === "python-bundle" ? "Python ZIP" : "Python"}</td>
                      <td><Validation version={version} /></td>
                      <td>{version.is_active ? "Active" : "—"}</td>
                      <td><a href={`/api/v1/tournaments/${encodeURIComponent(cup.id)}/submissions/${encodeURIComponent(version.id)}/download/`}
                        aria-label={`Download v${version.version}`}>Download</a></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
    </section>
  );
}

function Validation({ version }: { version: Version }) {
  const status = version.validation_status;
  const label = status === "validating"
    ? version.check_in_progress ? "Validation in progress" : "Queued for validation"
    : status === "inconclusive" ? "Check inconclusive" : status === "invalid" ? "Rejected" : "Valid";

  return (
    <details className="validation-details">
      <summary aria-label={`Validation for v${version.version}: ${label}`}>{label}</summary>
      {status === "inconclusive" && <p>A platform issue interrupted validation. The active bot stays in place.</p>}
      {version.validations.map((check, index) => (
        <div key={`${check.stage}-${index}`}>
          <p><strong>{check.stage.replaceAll("_", " ")}</strong> · {check.status}</p>
          {check.reasons.length + check.warnings.length > 0 && (
            <ul>
              {[...check.reasons, ...check.warnings].map((finding, index) => (
                <li key={index}>
                  {finding.line != null && `Line ${finding.line}: `}
                  {finding.side && `Side ${finding.side}: `}{finding.message}
                </li>
              ))}
            </ul>
          )}
        </div>
      ))}
    </details>
  );
}
