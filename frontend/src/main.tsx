import React, { useCallback, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { api, setCsrfToken } from "./api";
import { Inbox, TournamentNotices } from "./notifications";
import { Submissions, Team } from "./participant";
import { BracketResults, MatchResult, Replay } from "./results";
import { Approvals } from "./approvals";
import { adminTournamentList, adminTournamentSettings, organizerTournamentPath, TournamentManagement } from "./tournament-management";
import { AnnouncementForm } from "./announcements";
import { GlobalAudit } from "./audit";
import { DeadlineControls } from "./deadlines";
import { InvitationControls } from "./invitations";
import { Roster } from "./roster";
import { RoundControls } from "./rounds";
import { StaffTeams } from "./staff-teams";
import "./style.css";

type User = { id: number; username: string; admin: boolean };
type Cup = {
  id: string;
  name: string;
  description: string;
  status: string;
  deadlines: { registration: number; submission: number };
  teams?: string[];
  captain_teams?: string[];
};
type Bot = {
  id: number;
  x: number;
  y: number;
  team: number;
  kind: number;
  health: number;
  cheese: number;
  dir: number;
};
type Board = {
  width: number;
  height: number;
  round: number;
  updated_at: number;
  finished: boolean;
  robots: Bot[];
  walls: { x: number; y: number }[];
  dirt: { x: number; y: number }[];
  cheese?: { x: number; y: number }[];
  teams?: {
    team: number;
    cheese_transferred: number;
    cat_damage: number;
    alive_kings: number;
    alive_rats: number;
  }[];
};
type Match = {
  series_id: string;
  match_id: string;
  round: number;
  a: string;
  b: string;
  status: string;
  game_status: string;
  map: string;
  winner: string | null;
  board: Board | null;
};
type Dispute = {
  id: string;
  series_id: string;
  team_id: string;
  title: string;
  description?: string;
  status: string;
  version: number;
  resolution: string;
  events?: { kind: string; body: string; created_at: string }[];
};
const key = () => ({ "Idempotency-Key": crypto.randomUUID() });
const label = (value: string) => value.replaceAll("_", " ");
const date = (stamp: number) =>
  new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
    timeZoneName: undefined,
  }).format(stamp * 1000);

function Mark() {
  return (
    <span className="mark" aria-hidden="true">
      <i />
      <i />
      <i />
      <i />
    </span>
  );
}
function Arena({
  board,
  demo = false,
}: {
  board?: Board | null;
  demo?: boolean;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const element = canvas.current;
    if (!element) return;
    const ctx = element.getContext("2d");
    if (!ctx) return;
    const width = board?.width || 24,
      height = board?.height || 18;
    const scale = 24;
    element.width = width * scale;
    element.height = height * scale;
    ctx.fillStyle = "#191a2b";
    ctx.fillRect(0, 0, element.width, element.height);
    ctx.strokeStyle = "#27283a";
    ctx.lineWidth = 1;
    for (let x = 0; x <= width; x++) {
      ctx.beginPath();
      ctx.moveTo(x * scale, 0);
      ctx.lineTo(x * scale, element.height);
      ctx.stroke();
    }
    for (let y = 0; y <= height; y++) {
      ctx.beginPath();
      ctx.moveTo(0, y * scale);
      ctx.lineTo(element.width, y * scale);
      ctx.stroke();
    }
    const cell = (x: number, y: number, color: string) => {
      ctx.fillStyle = color;
      ctx.fillRect(
        x * scale + 2,
        (height - 1 - y) * scale + 2,
        scale - 4,
        scale - 4,
      );
    };
    if (board) {
      for (const c of board.walls) cell(c.x, c.y, "#52536b");
      for (const c of board.dirt) cell(c.x, c.y, "#696050");
      for (const c of board.cheese || []) cell(c.x, c.y, "#e8ba55");
      for (const r of board.robots) {
        ctx.fillStyle =
          r.team === 1 ? "#e7f06b" : r.team === 2 ? "#ff8b7a" : "#a6a8c5";
        ctx.beginPath();
        ctx.arc(
          (r.x + 0.5) * scale,
          (height - r.y - 0.5) * scale,
          r.kind === 2 ? 10 : 7,
          0,
          Math.PI * 2,
        );
        ctx.fill();
        if (r.kind === 2) {
          ctx.fillStyle = "#191a2b";
          ctx.fillRect(
            (r.x + 0.5) * scale - 2,
            (height - r.y - 0.5) * scale - 2,
            4,
            4,
          );
        }
      }
    } else if (demo) {
      for (let x = 5; x < 19; x++) {
        if (x < 10 || x > 13) cell(x, 8, "#515268");
      }
      for (const [x, y, color] of [
        [3, 3, "#e7f06b"],
        [4, 5, "#e7f06b"],
        [7, 6, "#e7f06b"],
        [9, 4, "#e7f06b"],
        [19, 14, "#ff8b7a"],
        [17, 12, "#ff8b7a"],
        [14, 13, "#ff8b7a"],
        [13, 10, "#ff8b7a"],
      ] as const) {
        cell(x, y, color);
      }
      ctx.strokeStyle = "#e7f06b80";
      ctx.setLineDash([5, 5]);
      ctx.beginPath();
      ctx.moveTo(4 * scale, 4 * scale);
      ctx.lineTo(10 * scale, 4 * scale);
      ctx.lineTo(10 * scale, 9 * scale);
      ctx.stroke();
      ctx.setLineDash([]);
    }
  }, [board, demo]);
  return (
    <canvas
      ref={canvas}
      className="arena"
      role="img"
      aria-label={
        demo
          ? "Illustrated example strategy arena, not a live match"
          : `Match board at round ${board?.round || 0}; ${board?.robots.length || 0} robots. Team A is yellow, team B is coral.`
      }
    />
  );
}
function Landing({ open }: { open: () => void }) {
  return (
    <>
      <header className="public-nav">
        <a className="wordmark" href="#">
          <Mark />
          BATTLE IT OUT<span className="event-label">INNOFEST</span>
        </a>
        <nav aria-label="Main navigation">
          <a href="#how">How it works</a>
          <a href="#rules">The rules</a>
          <button onClick={open} className="small-button">
            Competition console
          </button>
        </nav>
      </header>
      <main id="main-content" tabIndex={-1}>
        <section className="hero">
          <div className="hero-copy">
            <p className="eyebrow">
              <span className="line" /> CODE. COMPETE. ADAPT.
            </p>
            <h1>
              YOUR CODE.
              <br />
              YOUR STRATEGY.
              <br />
              <em>THEIR PROBLEM.</em>
            </h1>
            <p className="lede">
              Build a Python bot. Send it into the arena. Let your strategy do
              the talking.
            </p>
            <div className="hero-actions">
              <button className="primary" onClick={open}>
                Enter the competition console
              </button>
              <a href="#how">Explore the format</a>
            </div>
            <p className="hero-foot">
              An INNOFEST programming competition
              <br />
              Powered by the existing Battlecode 2026 engine.
            </p>
          </div>
          <div className="arena-frame">
            <div className="arena-toolbar">
              <span>THE STRATEGY LAB</span>
              <span className="tag">ILLUSTRATION</span>
            </div>
            <Arena demo />
            <div className="arena-footer">
              <span>
                <i className="legend a" /> YOUR STRATEGY
              </span>
              <span>
                <i className="legend b" /> THE OPPOSITION
              </span>
            </div>
            <p className="caption">
              Illustrated arena. Real matches are visible to signed-in
              tournament members.
            </p>
            <div className="floating-note">
              <code>def turn():</code>
              <span>Make your next move.</span>
            </div>
          </div>
        </section>
        <section className="format-strip" aria-label="Competition format">
          <span>PYTHON BOTS</span>
          <b>×</b>
          <span>SINGLE ELIMINATION</span>
          <b>×</b>
          <span>ONE SHARED RULE SET</span>
          <b>×</b>
          <span>REAL ENGINE. REAL RESULTS.</span>
        </section>
        <section className="how-section" id="how">
          <div className="section-heading">
            <p className="eyebrow">FROM IDEA TO ARENA</p>
            <h2>
              A little code.
              <br />A lot of possibility.
            </h2>
            <p>
              Start with your tournament invitation. Bring a strategy worth
              testing.
            </p>
          </div>
          <div className="steps">
            <article>
              <span className="step-icon">{"{ }"}</span>
              <h3>Build your bot</h3>
              <p>
                Use Python and a <code>turn()</code> entry point. Submit{" "}
                <code>bot.py</code> on its own, or a flat bundle with helper
                modules and curated dependencies.
              </p>
            </article>
            <article>
              <span className="step-icon">✓</span>
              <h3>Put it to the test</h3>
              <p>
                Every upload is validated and plays trial games. Your latest
                valid version becomes active. An invalid replacement keeps your
                previous bot in play.
              </p>
            </article>
            <article>
              <span className="step-icon">⚑</span>
              <h3>Let strategy decide</h3>
              <p>
                The Organizer starts each round. Watch your match, study the
                results, and follow the bracket as winners advance.
              </p>
            </article>
          </div>
        </section>
        <section className="rules-section" id="rules">
          <div>
            <p className="eyebrow">KNOW THE PLAYING FIELD</p>
            <h2>
              Clear rules.
              <br />
              Room for clever code.
            </h2>
            <button className="primary" onClick={open}>
              Open your tournament
            </button>
          </div>
          <dl>
            <div>
              <dt>Invitation-only entry</dt>
              <dd>
                Register through your official tournament invitation. Your team
                and role come from the roster.
              </dd>
            </div>
            <div>
              <dt>One environment for everyone</dt>
              <dd>
                Platform-wide execution limits apply. Dependencies come from the
                published curated catalogue; participant package installation is
                unavailable.
              </dd>
            </div>
            <div>
              <dt>Every outcome has a record</dt>
              <dd>
                Tie-break maps resolve ties before a stored digital coin flip.
                Results, analytics and disputes make the outcome reviewable.
              </dd>
            </div>
            <div>
              <dt>Your source stays with your team</dt>
              <dd>
                Other teams cannot see your bot. Tournament members can watch
                private live boards; replays are removed when the tournament is
                archived.
              </dd>
            </div>
          </dl>
        </section>
        <section className="closing">
          <p className="eyebrow">THE NEXT MOVE IS YOURS</p>
          <h2>Bring a better strategy.</h2>
          <p>
            Sign in with the account provisioned for your tournament. Contact
            your Organizer if you need an invitation or account access.
          </p>
          <button className="primary" onClick={open}>
            Open competition console
          </button>
        </section>
      </main>
      <footer className="public-footer">
        <a href="#" className="wordmark">
          <Mark />
          BATTLE IT OUT
        </a>
        <span>
          INNOFEST · Built on Battlecode 2026
          <br />
          An independent competition; no affiliation or endorsement implied.
        </span>
      </footer>
    </>
  );
}
const consoleLinks = [
  { page: "dashboard", href: "/dashboard", label: "Dashboard", icon: "⌂" },
  { page: "notifications", href: "/notifications", label: "Notifications", icon: "◈" },
  { page: "live", href: "/#console", label: "Match room", icon: "◉" },
  { page: "bracket", href: "/bracket", label: "Bracket & results", icon: "▦" },
  { page: "analytics", href: "/#analytics", label: "Analytics", icon: "▥" },
  { page: "team", href: "/participant/team", label: "My team", icon: "◇" },
  { page: "submissions", href: "/participant/submissions", label: "Bot submissions", icon: "⌘" },
  { page: "disputes", href: "/#disputes", label: "Match disputes", icon: "☷" },
  { page: "operations", href: "/#operations", label: "Operations", icon: "⚙" },
  { page: "approvals", href: "/admin/approvals", label: "Approvals", icon: "✓" },
  { page: "audit", href: "/admin/audit", label: "Audit log", icon: "☷" },
  { page: "admin-tournaments", href: adminTournamentList, label: "Manage tournaments", icon: "▤" },
  { page: "deadlines", href: "/admin/tournaments", label: "Deadline controls", icon: "◷" },
  { page: "invitations", href: "/admin/invitations", label: "Invitation codes", icon: "⌁" },
  { page: "organizer", href: "/organizer", label: "Manage tournaments", icon: "▤" },
  { page: "announce", href: "/announcements/new", label: "Post announcement", icon: "◈" },
] as const;
type ConsolePage = (typeof consoleLinks)[number]["page"] | "match" | "replay"
  | "organizer-roster" | "organizer-rounds" | "organizer-teams" | "admin-roster" | "admin-teams";
type ConsoleRoute = { page: ConsolePage; id?: string; create?: boolean };
const detailRoutes: [RegExp, ConsolePage][] = [
  [/^\/participant\/tournaments\/([^/#]+)\/bracket$/, "bracket"],
  [/^\/matches\/([^/#]+)\/replay$/, "replay"],
  [/^\/matches\/([^/#]+)$/, "match"],
  [/^\/organizer\/tournaments\/([^/#]+)\/roster$/, "organizer-roster"],
  [/^\/organizer\/tournaments\/([^/#]+)\/rounds$/, "organizer-rounds"],
  [/^\/organizer\/tournaments\/([^/#]+)\/teams$/, "organizer-teams"],
  [/^\/organizer\/tournaments\/([^/#]+)$/, "organizer"],
  [/^\/admin\/manage-tournaments\/([^/#]+)\/settings$/, "admin-tournaments"],
  [/^\/admin\/manage-tournaments\/([^/#]+)\/roster$/, "admin-roster"],
  [/^\/admin\/manage-tournaments\/([^/#]+)\/teams$/, "admin-teams"],
  [/^\/admin\/tournaments\/([^/#]+)$/, "deadlines"],
];

function currentRoute(address: string): ConsoleRoute | null {
  const normalized = address.replace(/\/$/, "");
  if (normalized === "/#submissions") return { page: "submissions" };
  if (normalized === `${adminTournamentList}/new`) return { page: "admin-tournaments", create: true };
  for (const [pattern, page] of detailRoutes) {
    const match = normalized.match(pattern);
    if (!match) continue;
    try {
      return { page, id: decodeURIComponent(match[1]) };
    } catch {
      return null;
    }
  }
  const link = consoleLinks.find(({ href }) => href === normalized);
  return link ? { page: link.page } : null;
}

function SkipToContent() {
  return (
    <a className="skip" href="#main-content" onClick={(event) => {
      const main = document.getElementById("main-content");
      if (main) {
        event.preventDefault();
        main.focus();
      }
    }}>
      Skip to content
    </a>
  );
}

function App() {
  const [user, setUser] = useState<User | null>(null),
    [checking, setChecking] = useState(true),
    [address, setAddress] = useState(() => location.pathname + location.hash);
  const route = currentRoute(address);
  const [error, setError] = useState("");
  useEffect(() => {
    const onLocation = () => setAddress(location.pathname + location.hash);
    window.addEventListener("hashchange", onLocation);
    window.addEventListener("popstate", onLocation);
    return () => {
      window.removeEventListener("hashchange", onLocation);
      window.removeEventListener("popstate", onLocation);
    };
  }, []);
  useEffect(() => {
    api("/auth/session/")
      .then((data) => {
        setCsrfToken(data.csrf);
        setUser(data.user);
      })
      .catch(() =>
        setError(
          "The competition API is unavailable. The public guide remains available.",
        ),
      )
      .finally(() => setChecking(false));
  }, []);
  const open = () => {
    location.hash = "console";
    window.scrollTo(0, 0);
  };
  if (!route)
    return (
      <>
        <SkipToContent />
        {error && (
          <p className="offline" role="status">
            {error}
          </p>
        )}
        <Landing open={open} />
      </>
    );
  if (checking)
    return (
      <main className="login-shell">
        <p role="status">Checking your session…</p>
      </main>
    );
  if (!user)
    return (
      <Login
        done={setUser}
        back={() => { location.href = "/"; }}
      />
    );
  return (
    <>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <Console
        user={user}
        route={route}
        navigate={(href) => {
          if (location.pathname + location.hash !== href) history.pushState(null, "", href);
          setAddress(location.pathname + location.hash);
          window.scrollTo(0, 0);
        }}
        logout={async () => {
          try {
            await api("/auth/logout/", { method: "POST" });
            setUser(null);
          } catch (e) {
            setError((e as Error).message);
          }
        }}
      />
    </>
  );
}
function Login({ done, back }: { done: (u: User) => void; back: () => void }) {
  const [name, setName] = useState(""),
    [password, setPassword] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  return (
    <main className="login-shell">
      <button className="text-button back" onClick={back}>
        Back to Battle It Out
      </button>
      <div className="login-card">
        <Mark />
        <p className="eyebrow">INNOFEST COMPETITION CONSOLE</p>
        <h1>
          Back to
          <br />
          the arena.
        </h1>
        <p>Use your provisioned tournament account.</p>
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            setError("");
            try {
              const session = await api("/auth/session/");
              setCsrfToken(session.csrf);
              const data = await api("/auth/login/", {
                method: "POST",
                body: JSON.stringify({ username: name, password }),
              });
              setCsrfToken(data.csrf);
              done(data.user);
            } catch (e) {
              setError((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          <label>
            Username
            <input
              autoComplete="username"
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          <label>
            Password
            <input
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          <button className="primary" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>
        <p className="muted">
          Need account access? Contact your tournament Organizer.
        </p>
      </div>
    </main>
  );
}
function Console({ user, route, navigate, logout }: {
  user: User; route: ConsoleRoute; navigate: (href: string) => void; logout: () => void;
}) {
  const { page, id } = route;
  const [cups, setCups] = useState<Cup[]>([]),
    [selected, setSelected] = useState(""),
    [role, setRole] = useState(""),
    [loading, setLoading] = useState(true),
    [error, setError] = useState("");
  const refreshTournament = useCallback(async () => {
    const data = await api<{ items: Cup[]; role: string }>("/tournaments/");
    setCups(data.items);
    setRole(data.role);
    setError("");
    setSelected((id) => data.items.some((item) => item.id === id) ? id : data.items[0]?.id || "");
  }, []);
  const applyTournament = useCallback((record: {
    id: string; name: string; description: string; status: string;
    registration_deadline: string | null; submission_deadline: string | null;
  }) => {
    setCups((items) => {
      const prior = items.find((cup) => cup.id === record.id);
      const summary = {
        id: record.id, name: record.name, description: record.description, status: record.status,
        deadlines: {
          registration: record.registration_deadline ? Date.parse(record.registration_deadline) / 1000
            : prior?.deadlines.registration ?? 0,
          submission: record.submission_deadline ? Date.parse(record.submission_deadline) / 1000
            : prior?.deadlines.submission ?? 0,
        },
      };
      return prior ? items.map((cup) => cup.id === record.id ? summary : cup) : [...items, summary];
    });
  }, []);
  useEffect(() => {
    refreshTournament().catch((e) => setError(e.message)).finally(() => setLoading(false));
  }, [refreshTournament]);
  const scopedTournament = (page === "bracket" || page === "deadlines") && id;
  const cup = cups.find((c) => c.id === (scopedTournament || selected));
  const organizerPage = page.startsWith("organizer");
  const adminManagement = page.startsWith("admin-");
  const staffSettingsPath = adminManagement ? adminTournamentSettings : organizerTournamentPath;
  const showTournament = !organizerPage && !adminManagement && !["notifications", "operations", "approvals",
    "audit", "match", "replay"].includes(page);
  const canOpen = (target: ConsolePage) => {
    if (target.startsWith("admin-") || ["operations", "approvals", "audit", "deadlines", "invitations"].includes(target)) return user.admin;
    if (target === "announce") return user.admin || role === "organizer" || loading;
    if (target.startsWith("organizer")) {
      return role === "organizer" || (loading && !user.admin);
    }
    if (target === "notifications") return !user.admin && role !== "organizer";
    if (target === "team") return role === "participant" || (loading && !user.admin);
    return true;
  };
  return (
    <div className="console">
      <SkipToContent />
      <aside className="sidebar">
        <a className="wordmark" href="/">
          <Mark />
          BATTLE
          <br />
          IT OUT
        </a>
        <p className="eyebrow">COMPETITION CONSOLE</p>
        <nav aria-label="Console">
          {consoleLinks.filter((link) => canOpen(link.page) && (!loading || !["notifications", "team", "organizer", "announce"].includes(link.page))).map((link) => (
            <a key={link.page} href={link.href} aria-current={page === link.page ? "page" : undefined}
              onClick={(event) => {
                if (event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
                event.preventDefault();
                navigate(link.href);
                document.getElementById("main-content")?.focus();
              }}>
              <span className="nav-icon" aria-hidden="true">{link.icon}</span> {link.label}
            </a>
          ))}
        </nav>
        <div className="account">
          <strong>{user.username}</strong>
          <span>{label(role)}</span>
          <button onClick={logout}>Sign out</button>
        </div>
      </aside>
      <main className="workspace" id="main-content" tabIndex={-1}>
        <header className="workspace-top">
          <span className="eyebrow">INNOFEST / COMPETITION</span>
          {showTournament && cups.length > 0 && <label className="cup-picker">
            Tournament
            <select
              aria-label="Tournament"
              value={cup?.id ?? ""}
              onChange={(e) => {
                setSelected(e.target.value);
                if (scopedTournament) navigate(page === "deadlines" ? "/admin/tournaments" : "/bracket");
              }}
            >
              {!cup && <option value="" disabled>Select a tournament</option>}
              {cups.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </label>}
        </header>
        {error && showTournament && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {!canOpen(page) ? (
          <section className="empty">
            <h1>Access required</h1>
            <p role="alert">{page === "operations"
              ? "Admin access is required to open Operations."
              : page === "approvals" ? "Admin access is required to review tournaments."
              : page === "audit" ? "Admin access is required to open the global audit log."
              : adminManagement ? "Admin access is required to manage tournaments here."
              : page === "deadlines" ? "Admin access is required to change deadlines and locked settings."
              : page === "invitations" ? "Admin access is required to manage invitation codes."
              : organizerPage ? "Organizer access is required to manage tournaments."
              : page === "announce" ? "Tournament staff access is required to post announcements."
              : page === "team" ? "My team is available to participant accounts."
              : "Notifications are available to linked participant accounts."}</p>
            <a href="/dashboard">Open Dashboard</a>
          </section>
        ) : page === "notifications" ? (
          loading ? <p role="status">Checking notification access…</p> :
            <Inbox tournaments={new Map(cups.map((item) => [item.id, item.name]))} />
        ) : page === "operations" ? (
          <Operations />
        ) : page === "approvals" ? (
          <Approvals tournaments={cups} loading={loading} loadError={error} refreshQueue={refreshTournament}
            onReview={(review) => setCups((items) => items.map((cup) => cup.id === review.id
              ? { ...cup, status: review.status } : cup))} />
        ) : page === "audit" ? (
          <GlobalAudit tournaments={cups} />
        ) : page === "organizer" || page === "admin-tournaments" ? (
          loading ? <p role="status">Loading tournaments…</p> :
            <TournamentManagement key={`${page}/${id ?? ""}/${Boolean(route.create)}`} id={id} userId={user.id}
              admin={page === "admin-tournaments"} create={Boolean(route.create || (page === "organizer" && id === "new"))}
              tournaments={cups} loadError={error} navigate={navigate} onChange={applyTournament} />
        ) : page === "organizer-roster" || page === "admin-roster" ? (
          loading ? <p role="status">Loading tournament access…</p> : id &&
            <Roster key={id} tournament={cups.find((record) => record.id === id)} backPath={staffSettingsPath(id)} />
        ) : page === "organizer-rounds" ? (
          loading ? <p role="status">Loading Organizer access…</p> :
            <RoundControls key={id} tournament={cups.find((record) => record.id === id)} />
        ) : page === "organizer-teams" || page === "admin-teams" ? (
          loading ? <p role="status">Loading tournament access…</p> : id &&
            <StaffTeams key={id} tournament={cups.find((record) => record.id === id)} backPath={staffSettingsPath(id)} />
        ) : page === "match" ? (
          id && <MatchResult key={id} matchId={id} />
        ) : page === "replay" ? (
          id && <Replay key={id} matchId={id} />
        ) : loading ? (
          <p role="status">Loading tournaments…</p>
        ) : page === "dashboard" ? (
          <Dashboard cup={cup} role={role} unavailable={Boolean(error)} />
        ) : page === "announce" ? (
          cup ? <AnnouncementForm key={cup.id} tournament={cup} /> :
            <section className="empty"><h1>Post announcement</h1>
              {!error && <p>No tournaments are available to your account.</p>}
            </section>
        ) : page === "deadlines" ? (
          cup ? <DeadlineControls key={cup.id} tournament={cup} refresh={refreshTournament}
            settingsPath={adminTournamentSettings(cup.id)} /> :
            <section className="empty"><h1>Deadline controls</h1>
              {!error && <p>{scopedTournament ? "This tournament is unavailable." : "No tournaments are available."}</p>}
            </section>
        ) : page === "invitations" ? (
          cup ? <InvitationControls key={cup.id} tournament={cup} /> :
            <section className="empty"><h1>Invitation codes</h1>
              {!error && <p>No tournaments are available.</p>}
            </section>
        ) : page === "bracket" ? (
          cup ? <BracketResults key={cup.id} tournament={cup} /> :
            <section className="empty">
              <h1>Bracket &amp; results</h1>
              <p>{scopedTournament ? "This tournament is unavailable." : "No tournaments yet."}</p>
            </section>
        ) : cup ? (
          <>
            <div className="workspace-heading">
              <div>
                <p className="eyebrow">
                  {cup.name} / {label(cup.status)}
                </p>
                <h1>
                  {
                    {
                      live: "The match room",
                      analytics: "Beyond the scoreboard",
                      team: "My team",
                      submissions: "Your next contender",
                      disputes: "A fair hearing",
                    }[page]
                  }
                </h1>
              </div>
              <p className="deadline">
                Submission deadline
                <br />
                <strong>{date(cup.deadlines.submission)}</strong>
                <br />
                {Intl.DateTimeFormat().resolvedOptions().timeZone}
              </p>
            </div>
            <div key={`${cup.id}/${page}`}>
              {page === "live" ? (
                <Live cup={cup} />
              ) : page === "analytics" ? (
                <Analytics cup={cup} />
              ) : page === "submissions" ? (
                <Submissions cup={cup} role={role} refreshTournament={refreshTournament} />
              ) : page === "team" ? (
                <Team cup={cup} />
              ) : (
                <Disputes cup={cup} role={role} />
              )}
            </div>
          </>
        ) : !error && (
          <section className="empty">
            <h1>No tournaments yet.</h1>
            <p>
              Your registered tournaments and active Organizer assignments will
              appear here. Contact your Organizer if you expected access.
            </p>
          </section>
        )}
      </main>
    </div>
  );
}
function Dashboard({ cup, role, unavailable }: { cup?: Cup; role: string; unavailable: boolean }) {
  const timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  return (
    <>
      <div className="workspace-heading"><h1>Dashboard</h1></div>
      {cup ? (
        <>
          <section className="panel tournament-overview" aria-labelledby="overview-heading">
            <h2 id="overview-heading">{cup.name}</h2>
            {cup.description && <p>{cup.description}</p>}
            <dl>
              <div><dt>Status</dt><dd className="tournament-status">{label(cup.status)}</dd></div>
              <div><dt>Registration deadline</dt><dd>
                <time dateTime={new Date(cup.deadlines.registration * 1000).toISOString()}>{date(cup.deadlines.registration)}</time>
              </dd></div>
              <div><dt>Submission deadline</dt><dd>
                <time dateTime={new Date(cup.deadlines.submission * 1000).toISOString()}>{date(cup.deadlines.submission)}</time>
              </dd></div>
            </dl>
            <p className="muted">Timezone {timeZone}</p>
          </section>
          {role === "participant" && <TournamentNotices key={cup.id} tournamentId={cup.id} />}
        </>
      ) : !unavailable && <p>No tournaments yet. Contact your Organizer if you expected access.</p>}
    </>
  );
}
function Live({ cup }: { cup: Cup }) {
  const [matches, setMatches] = useState<Match[]>([]),
    [chosen, setChosen] = useState(""),
    [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    const load = () =>
      api(`/tournaments/${cup.id}/live/`)
        .then((data) => {
          if (active) {
            setMatches(data.items);
            setError("");
            setChosen(
              (old) =>
                old ||
                data.items.find((m: Match) => m.status === "running")
                  ?.series_id ||
                data.items[0]?.series_id ||
                "",
            );
          }
        })
        .catch((e) => {
          if (active) setError(e.message);
        });
    load();
    const timer = setInterval(load, 1000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [cup.id]);
  const match = matches.find((m) => m.series_id === chosen);
  const board = match?.board;
  return (
    <>
      <div className="panel-toolbar">
        <p>Private boards for your tournament. Updates every second.</p>
        {matches.length > 0 && (
          <select
            aria-label="Match"
            value={chosen}
            onChange={(e) => setChosen(e.target.value)}
          >
            {matches.map((m) => (
              <option key={m.series_id} value={m.series_id}>
                Round {m.round} · {m.a} vs {m.b}
              </option>
            ))}
          </select>
        )}
      </div>
      {error ? (
        <p className="error" role="alert">
          {error}
        </p>
      ) : !match ? (
        <div className="empty">
          <h2>Waiting for the opening move.</h2>
          <p>
            No match has started. The Organizer starts each round once the
            bracket is ready.
          </p>
        </div>
      ) : (
        <>
          <div className="match-header">
            <div>
              <i className="legend a" />
              <strong>{match.a}</strong>
            </div>
            <span>
              ROUND {match.round} / {match.map}
              <b>VS</b>
            </span>
            <div>
              <strong>{match.b}</strong>
              <i className="legend b" />
            </div>
          </div>
          <p><a href={`/matches/${encodeURIComponent(match.match_id)}`}>Match details</a></p>
          <div className="live-board">
            {board ? (
              <Arena board={board} />
            ) : (
              <div className="empty">
                <h2>
                  {match.status === "completed"
                    ? "This match has finished."
                    : "The arena is getting ready."}
                </h2>
                <p>
                  {match.status === "completed"
                    ? "No live board was retained for this game. Its recorded result remains available."
                    : "The live board appears when the engine begins its game."}
                </p>
              </div>
            )}
            <div className="board-status">
              <span>
                {board ? `Engine round ${board.round}` : "Waiting for board"}
              </span>
              <span>
                {board?.finished
                  ? "Game finished"
                  : board && Date.now() / 1000 - board.updated_at > 5
                    ? "Updates delayed"
                    : label(match.game_status)}
              </span>
              <span>
                {match.winner
                  ? `${match.winner} advances`
                  : board
                    ? `${board.robots.length} robots on the board`
                    : "Results are recorded when play ends."}
              </span>
            </div>
          </div>
          <div className="two-col">
            {board?.teams?.map((t) => (
              <div className="panel" key={t.team}>
                <strong>{t.team === 1 ? match.a : match.b}</strong>
                <p>
                  {t.alive_kings} kings · {t.alive_rats} rats ·{" "}
                  {t.cheese_transferred} cheese transferred · {t.cat_damage} cat
                  damage
                </p>
              </div>
            ))}
          </div>
          <p className="muted">
            Yellow: team A · Coral: team B · Gray: neutral · Larger circles:
            kings. This view omits bot messages and indicators.
          </p>
        </>
      )}
    </>
  );
}
function Analytics({ cup }: { cup: Cup }) {
  const [data, setData] = useState<any>(null),
    [error, setError] = useState("");
  useEffect(() => {
    api(`/tournaments/${cup.id}/analytics/`)
      .then(setData)
      .catch((e) => setError(e.message));
  }, [cup.id]);
  if (error)
    return (
      <p className="error" role="alert">
        {error}
      </p>
    );
  if (!data) return <p role="status">Loading recorded results…</p>;
  return (
    <>
      <div className="panel-toolbar">
        <p>
          Computed from recorded games and attempts. Byes do not count as played
          matches.
        </p>
        <a
          className="small-button"
          href={`/api/v1/tournaments/${cup.id}/analytics.csv`}
        >
          Download team CSV
        </a>
      </div>
      <div className="stats">
        {[
          ["Teams", data.totals.teams],
          ["Decided matches", data.totals.completed],
          ["Games played", data.totals.games],
          ["Platform failures", data.totals.platform_failures],
        ].map(([l, v]) => (
          <div key={l}>
            <span>{l}</span>
            <strong>{v}</strong>
          </div>
        ))}
      </div>
      <div className="two-col">
        <section className="panel">
          <h2>Attempt latency</h2>
          <dl className="numbers">
            <div>
              <dt>Median</dt>
              <dd>
                {data.latency.median_seconds === null
                  ? "—"
                  : `${data.latency.median_seconds}s`}
              </dd>
            </div>
            <div>
              <dt>95th percentile</dt>
              <dd>
                {data.latency.p95_seconds === null
                  ? "—"
                  : `${data.latency.p95_seconds}s`}
              </dd>
            </div>
            <div>
              <dt>Measured attempts</dt>
              <dd>{data.latency.samples}</dd>
            </div>
          </dl>
          <p className="muted">
            Observed wall time, including failed attempts. Missing timing data
            is excluded.
          </p>
        </section>
        <section className="panel">
          <h2>Round progress</h2>
          {data.rounds.map((r: any) => (
            <div className="map-row" key={r.number}>
              <strong>Round {r.number}</strong>
              <span>
                {r.completed} decided · {label(r.status)}
              </span>
            </div>
          ))}
        </section>
      </div>
      <section className="panel">
        <h2>Team performance</h2>
        <div className="table-wrap">
          <table aria-label="Team performance">
            <thead>
              <tr>
                {["Team", "Played", "Wins", "Losses", "Byes", "Win rate"].map(
                  (s) => (
                    <th key={s}>{s}</th>
                  ),
                )}
              </tr>
            </thead>
            <tbody>
              {data.teams.map((t: any) => (
                <tr key={t.team}>
                  <td>
                    <strong>{t.team}</strong>
                  </td>
                  <td>{t.played}</td>
                  <td>{t.wins}</td>
                  <td>{t.losses}</td>
                  <td>{t.byes}</td>
                  <td>
                    <span
                      className="rate"
                      style={
                        {
                          "--rate": `${(t.win_rate || 0) * 100}%`,
                        } as React.CSSProperties
                      }
                    >
                      {t.win_rate === null
                        ? "—"
                        : `${Math.round(t.win_rate * 100)}%`}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!data.teams.length && (
          <p className="muted">
            Metrics will appear after the tournament is drawn.
          </p>
        )}
      </section>
      <section className="panel">
        <h2>Bot version performance</h2>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Version</th>
                <th>Team</th>
                <th>Finished games</th>
                <th>Wins</th>
                <th>Ties</th>
                <th>Forfeits</th>
              </tr>
            </thead>
            <tbody>
              {data.versions.map((v: any) => (
                <tr key={v.submission}>
                  <td>{v.submission}</td>
                  <td>{v.team}</td>
                  <td>{v.games}</td>
                  <td>{v.wins}</td>
                  <td>{v.ties}</td>
                  <td>{v.forfeits}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="muted">
          Engine coin-flip picks count as ties. Series coin flips are reported
          separately.
        </p>
      </section>
      <div className="two-col">
        <section className="panel">
          <h2>How matches were decided</h2>
          <dl className="numbers">
            <div>
              <dt>Bot forfeits</dt>
              <dd>{data.totals.forfeits}</dd>
            </div>
            <div>
              <dt>Digital coin flips</dt>
              <dd>{data.totals.coin_flips}</dd>
            </div>
            <div>
              <dt>Byes</dt>
              <dd>{data.totals.byes}</dd>
            </div>
            <div>
              <dt>Bot failures</dt>
              <dd>{data.totals.bot_failures}</dd>
            </div>
          </dl>
        </section>
        <section className="panel">
          <h2>Map workload</h2>
          {data.maps.length ? (
            data.maps.map((m: any) => (
              <div className="map-row" key={m.map}>
                <strong>{m.map}</strong>
                <span>
                  {m.games} games / {m.attempts} attempts
                </span>
              </div>
            ))
          ) : (
            <p className="muted">No game attempts recorded.</p>
          )}
        </section>
      </div>
    </>
  );
}
function Disputes({ cup, role }: { cup: Cup; role: string }) {
  const [items, setItems] = useState<Dispute[]>([]),
    [matches, setMatches] = useState<Match[]>([]),
    [selected, setSelected] = useState<Dispute | null>(null),
    [error, setError] = useState(""),
    [title, setTitle] = useState(""),
    [description, setDescription] = useState(""),
    [sid, setSid] = useState(""),
    [message, setMessage] = useState(""),
    [status, setStatus] = useState("reviewing"),
    [busy, setBusy] = useState(false);
  const staff = role === "admin" || role === "organizer";
  const load = () =>
    api(`/tournaments/${cup.id}/disputes/`)
      .then((d) => setItems(d.items))
      .catch((e) => setError(e.message));
  const select = (id: string) =>
    api(`/tournaments/${cup.id}/disputes/${id}/`)
      .then((d) => {
        setSelected(d);
        setMessage("");
        setStatus(d.status === "open" ? "reviewing" : "resolved");
      })
      .catch((e) => setError(e.message));
  useEffect(() => {
    load();
    api(`/tournaments/${cup.id}/live/`)
      .then((d) => {
        setMatches(d.items);
        setSid(d.items[0]?.series_id || "");
      })
      .catch(() => {});
  }, [cup.id]);
  const closed = selected && ["resolved", "rejected"].includes(selected.status);
  return (
    <>
      <p className="intro">
        Raise a question about a match. Your team and assigned staff can follow
        the review. A review never automatically changes a result or reruns a
        game.
      </p>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="two-col disputes-layout">
        <section className="panel">
          <h2>Review queue</h2>
          {items.length ? (
            items.map((d) => (
              <button
                key={d.id}
                className={
                  "dispute-row " + (selected?.id === d.id ? "selected" : "")
                }
                onClick={() => select(d.id)}
              >
                <strong>{d.title}</strong>
                <span>
                  {d.team_id} · {label(d.status)}
                </span>
              </button>
            ))
          ) : (
            <p className="muted">No disputes visible to your account.</p>
          )}
          {!staff && (
            <form
              className="new-dispute"
              onSubmit={async (e) => {
                e.preventDefault();
                setBusy(true);
                setError("");
                try {
                  const d = await api(`/tournaments/${cup.id}/disputes/`, {
                    method: "POST",
                    headers: key(),
                    body: JSON.stringify({
                      series_id: sid,
                      title,
                      description,
                    }),
                  });
                  setSelected(d);
                  setTitle("");
                  setDescription("");
                  load();
                } catch (e) {
                  setError((e as Error).message);
                } finally {
                  setBusy(false);
                }
              }}
            >
              <h3>Open a match dispute</h3>
              <label>
                Match
                <select
                  required
                  value={sid}
                  onChange={(e) => setSid(e.target.value)}
                >
                  <option value="">Select a match</option>
                  {matches.map((m) => (
                    <option key={m.series_id} value={m.series_id}>
                      {m.a} vs {m.b} · round {m.round}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Title
                <input
                  maxLength={160}
                  required
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                />
              </label>
              <label>
                What should staff review?
                <textarea
                  maxLength={4000}
                  required
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                />
              </label>
              <button className="primary" disabled={busy || !sid}>
                {busy ? "Opening…" : "Open dispute"}
              </button>
            </form>
          )}
        </section>
        <section className="panel">
          {!selected ? (
            <div className="empty">
              <h2>Make the question clear.</h2>
              <p>
                Select a dispute to see its history and continue the
                conversation.
              </p>
            </div>
          ) : (
            <>
              <p className="eyebrow">
                {label(selected.status)} / REVISION {selected.version}
              </p>
              <h2>{selected.title}</h2>
              <p className="preserve">{selected.description}</p>
              <ol className="timeline">
                {selected.events?.map((event, i) => (
                  <li key={i}>
                    <span>
                      {label(event.kind)} ·{" "}
                      {new Date(event.created_at).toLocaleString()}
                    </span>
                    <p className="preserve">{event.body}</p>
                  </li>
                ))}
              </ol>
              {closed ? (
                <p className="success">Review closed: {selected.resolution}</p>
              ) : (
                <form
                  onSubmit={async (e) => {
                    e.preventDefault();
                    setError("");
                    setBusy(true);
                    try {
                      const body = staff
                        ? {
                            expected_version: selected.version,
                            status,
                            resolution: message,
                          }
                        : { expected_version: selected.version, message };
                      const d = await api(
                        `/tournaments/${cup.id}/disputes/${selected.id}/`,
                        {
                          method: "POST",
                          headers: key(),
                          body: JSON.stringify(body),
                        },
                      );
                      setSelected(d);
                      setMessage("");
                      load();
                    } catch (e) {
                      setError((e as Error).message);
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  {staff && (
                    <label>
                      Review status
                      <select
                        value={status}
                        onChange={(e) => setStatus(e.target.value)}
                      >
                        {(selected.status === "open"
                          ? ["reviewing", "rejected"]
                          : selected.status === "reviewing"
                            ? ["awaiting_participant", "resolved", "rejected"]
                            : ["reviewing", "resolved", "rejected"]
                        ).map((s) => (
                          <option value={s} key={s}>
                            {label(s)}
                          </option>
                        ))}
                      </select>
                    </label>
                  )}
                  <label>
                    {staff ? "Reason / resolution" : "Add a comment"}
                    <textarea
                      maxLength={4000}
                      required
                      value={message}
                      onChange={(e) => setMessage(e.target.value)}
                    />
                  </label>
                  <button className="primary" disabled={busy}>
                    {busy
                      ? "Saving…"
                      : staff
                        ? "Record review decision"
                        : "Send comment"}
                  </button>
                </form>
              )}
            </>
          )}
        </section>
      </div>
    </>
  );
}
function Operations() {
  const [data, setData] = useState<any>(null),
    [error, setError] = useState("");
  useEffect(() => {
    api("/admin/operations/")
      .then(setData)
      .catch((e) => setError(e.message));
  }, []);
  if (error)
    return (
      <p className="error" role="alert">
        {error}
      </p>
    );
  if (!data) return <p role="status">Loading service state…</p>;
  return (
    <>
      <div className="workspace-heading">
        <div>
          <p className="eyebrow">ADMIN / SERVICE HEALTH</p>
          <h1>Eyes on the operation.</h1>
        </div>
      </div>
      <div className="stats">
        {[
          ["Open incidents", data.status.open_incidents],
          ["Unalerted incidents", data.status.unalerted_incidents],
          ["Failed emails awaiting alert", data.status.unalerted_failed_emails],
          ["Dead jobs", data.dead_jobs.length],
        ].map(([l, v]) => (
          <div key={l}>
            <span>{l}</span>
            <strong>{v}</strong>
          </div>
        ))}
      </div>
      <section className="panel">
        <h2>Open incidents</h2>
        {data.incidents.length ? (
          data.incidents.map((i: any) => (
            <div className="map-row" key={i.id}>
              <strong>{label(i.incident_type)}</strong>
              <span>
                {i.source} · {i.match_id || i.job_id || i.tournament_id || i.id}
              </span>
            </div>
          ))
        ) : (
          <p>No open incidents.</p>
        )}
      </section>
      <section className="panel">
        <div className="panel-toolbar">
          <h2>Recent audit events</h2><a href="/admin/audit">Open global audit log</a>
        </div>
        {data.audit.length ? (
          data.audit.map((a: any, i: number) => (
            <div className="map-row" key={i}>
              <strong>{label(a.action)}</strong>
              <span>
                {a.tournament_id} · {new Date(a.created_at).toLocaleString()}
              </span>
            </div>
          ))
        ) : (
          <p>No web audit events recorded.</p>
        )}
      </section>
    </>
  );
}
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
