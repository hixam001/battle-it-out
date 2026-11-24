# SPDX-License-Identifier: AGPL-3.0-only
"""Match launcher for the Battlecode scaffold (BIO-003 / BIO-004).

Participants write Python bots only. This launcher starts the engine's Python runner
(`runner_entry.py`, any tested CPython from 3.12 up) and the engine's Java *server* task, which is
the existing Battlecode engine and is not replaced. It exists because the scaffold's Gradle task
for Python bots uses `python3` from PATH and deadlocks with `--new-process` on Linux (see
docs/TECHNICAL_DOCUMENTATION.md section 3.2).

Safety (BIO-203/204): by default each team runs in its own bubblewrap sandbox process (no network, read-only
root, seccomp filter, optional cgroup limits) with a resource guard, behind a router in front of the Java
server. `--no-sandbox` and `--no-limits` exist for development only. Limit: one match per host at a time (the
engine's fixed loopback port 27185).

    python3 backend/match_runner/setup_env.py 3.15            # once per Python version
    python3 backend/match_runner/launcher.py verify
    python3 backend/match_runner/launcher.py run --team-a examplefuncsplayer_py \\
        --team-b examplefuncsplayer_py --out-dir /somewhere/outside/repo
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import re
import socket
import subprocess
import sys
import os
import signal
import tempfile
import time
from pathlib import Path

try:  # works both as a script (python backend/match_runner/launcher.py) and as a package module
    from backend.match_runner import guard as guard_mod
    from backend.match_runner import match_log as log_mod
    from backend.match_runner import sandbox as sandbox_mod
except ImportError:  # pragma: no cover - script mode without the repo root on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from backend.match_runner import guard as guard_mod
    from backend.match_runner import match_log as log_mod
    from backend.match_runner import sandbox as sandbox_mod

HERE = Path(__file__).resolve().parent
LOCK_PATH = HERE / "versions.lock.json"
DEFAULT_SCAFFOLD = HERE.parent / "battlecode26-scaffold"
VENVS = HERE.parent / ".venvs"
DEFAULT_LIMITS = HERE / "limits.provisional.json"

# Engine lines are matched at the start of a line, and the LAST match wins. The router rewrites every
# runner-supplied text so a bot cannot start a line with `[server]` (BIO-206, CN-007); anchoring and
# taking the last match are the second layer in case that ever fails: the engine prints the result
# after every bot has finished.
RESULT_RE = re.compile(r"^\[server\]\s+(\S+)\s+\((A|B)\) wins \(round (\d+)\)\s*$", re.MULTILINE)
REASON_RE = re.compile(r"^\[server\] Reason: (.+)$", re.MULTILINE)
FINISHED_RE = re.compile(r"^\[server\] -+ Match Finished -+\s*$", re.MULTILINE)
SERVER_ERROR_RE = re.compile(r"^\[server:(?:warning|error)\] (?!\(Stacktrace Error\)$)(.+)$", re.MULTILINE)


class LauncherError(Exception):
    pass


def load_lock(path: Path = LOCK_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def resolve_python(version: str | None, explicit: Path | None, lock: dict) -> Path:
    if explicit is not None:
        return explicit
    return VENVS / f"py{version or lock['primary_python']}" / "bin" / "python"


def verify(scaffold: Path, py: Path, lock: dict) -> list[str]:
    """Return a list of problems; empty means every pinned fact matches."""
    if not py.exists():
        return [f"interpreter not found: {py} (create it with setup_env.py)"]
    probe = (
        "import sys, importlib.metadata as m, json;"
        "print(json.dumps({'py': '%d.%d' % sys.version_info[:2], 'full': sys.version.split()[0],"
        f" 'pkgs': {{n: m.version(n) for n in ['{lock['engine_package']['name']}', *{list(lock['dependencies'])!r}]}}}}))"
    )
    out = subprocess.run([str(py), "-c", probe], capture_output=True, text=True)
    if out.returncode != 0:
        return [f"cannot query interpreter: {out.stderr.strip()[-200:]}"]
    info = json.loads(out.stdout)
    problems: list[str] = []
    if info["py"] not in lock["tested_python"]:
        problems.append(f"Python {info['py']} is not in the tested list {lock['tested_python']}")
    want = {lock["engine_package"]["name"]: lock["engine_package"]["metadata_version"], **lock["dependencies"]}
    for name, ver in want.items():
        got = info["pkgs"].get(name)
        if got != ver:
            problems.append(f"package {name} is {got}, pinned {ver}")
    ev = (scaffold / "engine_version.txt").read_text().strip()
    if ev != lock["engine_version"]:
        problems.append(f"engine_version.txt is {ev}, pinned {lock['engine_version']}")
    cached = HERE.parent / ".cache" / f"engine-{lock['engine_version']}" / "battlecode.tar.gz"
    if cached.exists() and sha256_of(cached) != lock["engine_package"]["artifact_sha256"]:
        problems.append("cached engine package has the wrong SHA-256")
    return problems


def interpreter_version(py: Path) -> str:
    out = subprocess.run([str(py), "-c", "import sys;print(sys.version.split()[0])"], capture_output=True, text=True)
    return out.stdout.strip()


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def build_runner_cmd(py: Path, bots_dir: Path, side: str, name: str, socket_tuning: bool,
                     limits: Path | None = None, ipc_socket: Path | None = None) -> list[str]:
    """Runner for ONE team (`side` is "A" or "B"); the other slot is "/" (no bot)."""
    if side not in ("A", "B"):
        raise ValueError(side)
    cmd = [str(py), "-I", str(HERE / "runner_entry.py"), f"--team{side}", name, f"--dir{side}", str(bots_dir)]
    if not socket_tuning:
        cmd.append("--no-socket-tuning")
    cmd += ["--limits", str(limits)] if limits is not None else ["--measure"]
    if ipc_socket is not None:
        cmd += ["--ipc-socket", str(ipc_socket)]
    return cmd


def build_gradle_cmd(scaffold: Path, team_a: str, team_b: str, maps: str, replay: Path, offline: bool,
                     class_dir: Path | None = None) -> list[str]:
    cmd = [str(scaffold / "gradlew"), "runJavaLocal", "--console=plain"]
    if offline:
        cmd.append("--offline")
    cmd += ["-PlanguageA=python", "-PlanguageB=python",
            f"-PteamA={team_a}", f"-PteamB={team_b}", f"-Pmaps={maps}", f"-Preplay={replay}"]
    if class_dir is not None:
        cmd += [f"-PclassLocationA={class_dir}", f"-PclassLocationB={class_dir}"]
    return cmd


def parse_result(log_text: str) -> dict:
    results = list(RESULT_RE.finditer(log_text))
    reasons = list(REASON_RE.finditer(log_text))
    m = results[-1] if results else None
    r = reasons[-1] if reasons else None
    return {
        "winner": m.group(2) if m else None,
        "winning_team": m.group(1) if m else None,
        "round": int(m.group(3)) if m else None,
        "reason": r.group(1).strip() if r else None,
        "finished": FINISHED_RE.search(log_text) is not None,
        "server_errors": [e.strip() for e in SERVER_ERROR_RE.findall(log_text)],
    }


GUARD_RE = re.compile(r"^BIO-GUARD-(VIOLATION|USAGE) (\{.*\})$", re.MULTILINE)


def parse_guard_records(runner_log_text: str) -> dict:
    """Read the guard's records from the runner log (last of each kind wins; bad JSON is ignored)."""
    out: dict = {}
    for kind, body in GUARD_RE.findall(runner_log_text):
        try:
            out[kind.lower()] = json.loads(body)
        except ValueError:
            continue
    return out


def _stop_group(proc: subprocess.Popen, grace: float = 5.0) -> None:
    """Stop a process we started in its own session (and everything it spawned)."""
    if proc.poll() is not None:
        return
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            return
        try:
            proc.wait(timeout=grace)
            return
        except subprocess.TimeoutExpired:
            continue


def describe_exit(code: int | None) -> dict:
    """Plain description of a runner exit status (bubblewrap and shells report a signal as 128+N)."""
    if code is None:
        return {"exit_status": None, "signal": None}
    if code > 128:
        try:
            return {"exit_status": code, "signal": signal.Signals(code - 128).name}
        except ValueError:
            pass
    if code < 0:
        try:
            return {"exit_status": code, "signal": signal.Signals(-code).name}
        except ValueError:
            pass
    return {"exit_status": code, "signal": None}


def _other(side: str) -> str:
    return "B" if side == "A" else "A"


def classify(result: dict, violation: dict | None, runner_exit: int | None, timed_out: bool,
             router: dict | None = None, runner_exits: dict | None = None) -> dict:
    """Decide who is responsible (BIO-205). Never invents a winner for a platform failure.

    Rules, in order (PRD: a bot crash, timeout or limit breach is an automatic loss, no rematch;
    anything else is a platform failure that may be retried):
      1. The guard recorded a limit breach by a team -> `bot_violation`; with no team -> platform.
      2. The wall-clock timeout of the whole match hit -> platform.
      3. The match finished and nothing failed -> `normal`.
      4. The match did NOT finish. With router evidence, who ended the connection first decides:
           * a team's runner never connected            -> platform (the platform failed to start it);
           * a team's runner ended it first             -> `bot_crash`: that team loses;
           * the engine server ended it first / no clue -> platform.
         A runner's own log is never used as proof: bot code runs inside that process and can print
         anything. The router sits outside every sandbox, so a bot cannot forge what it sees. The
         price: if the engine's Python code crashes inside a runner (a platform bug), that team is
         charged. That cannot be told apart from a bot that crashes on purpose, and the opposite choice
         would let a losing bot force replays by crashing itself. The evidence is kept in the result.
    """
    if violation is not None and violation.get("team") in ("A", "B"):
        loser = violation["team"]
        return {"classification": "bot_violation", "loser": loser, "winner_by_forfeit": _other(loser)}
    if violation is not None or runner_exit in (guard_mod.EXIT_PLATFORM,):
        return {"classification": "platform_failure", "kind": "limit_breach_no_bot",
                "detail": "limit breached while no bot was running"}
    if timed_out:
        return {"classification": "platform_failure", "kind": "match_timeout",
                "detail": "match wall-clock timeout, no bot violation recorded"}
    finished_ok = result["finished"] and not result["server_errors"]
    if router is not None and not finished_ok:
        connected = set(router.get("connected") or [])
        missing = sorted({"A", "B"} - connected)
        if missing:
            return {"classification": "platform_failure", "kind": "runner_start_failure",
                    "detail": f"runner for team {', '.join(missing)} never connected to the engine"}
        end = router.get("first_end") or {}
        leg = end.get("leg", "")
        if leg.startswith("runner:"):
            loser = leg.split(":", 1)[1]
            ex = describe_exit((runner_exits or {}).get(loser))
            return {"classification": "bot_crash", "kind": "runner_ended_connection",
                    "loser": loser, "winner_by_forfeit": _other(loser),
                    "detail": f"team {loser}'s process ended the engine connection first ({end.get('how')})",
                    "evidence": {"first_end": end, **ex}}
        if leg == "server":
            return {"classification": "platform_failure", "kind": "engine_failure",
                    "detail": "the engine server ended the connection first",
                    "evidence": {"first_end": end}}
        return {"classification": "platform_failure", "kind": "unknown",
                "detail": "the match did not finish and no side is known to have ended it"}
    if runner_exit not in (0, None) or result["server_errors"] or not result["finished"]:
        return {"classification": "platform_failure", "kind": "unfinished",
                "detail": "runner or server did not finish cleanly"}
    return {"classification": "normal"}


OUTCOME = {"normal": "completed", "bot_violation": "bot_failure", "bot_crash": "bot_failure",
           "platform_failure": "platform_failure"}


def merge_usage(per_side: dict[str, dict | None]) -> dict | None:
    """Combine the two runner processes' usage records (one per team)."""
    got = {k: v for k, v in per_side.items() if v}
    if not got:
        return None
    teams: dict = {}
    for side, u in got.items():
        for team, stats in u.get("teams", {}).items():
            if team == side:      # a process may only report on its own team
                teams[team] = stats
    return {
        "peak_rss_mib": max(u["peak_rss_mib"] for u in got.values()),
        "peak_vm_mib": max((u.get("peak_vm_mib") or 0) for u in got.values()),
        "peak_threads": max(u.get("peak_threads", 0) for u in got.values()),
        "cpu_seconds": round(sum(u.get("cpu_seconds", 0) for u in got.values()), 2),
        "wall_seconds": max(u.get("wall_seconds", 0) for u in got.values()),
        "teams": teams,
        "processes": got,
    }


def run_match(scaffold: Path, py: Path, bots_dir: Path, team_a: str, team_b: str, maps: str,
              out_dir: Path, timeout: int, offline: bool, socket_tuning: bool,
              sandbox: bool = True, limits_path: Path | None = DEFAULT_LIMITS,
              cgroup: bool | None = None, trace_id: str | None = None, match_id: str | None = None,
              attempt: int = 1, submissions: dict | None = None) -> dict:
    """Run one match: one runner process per team, a router in front of the engine server.

    `cgroup`: None = use kernel cgroup limits if a user systemd manager is available, True = require,
    False = never. Only applies with the sandbox.

    `trace_id`, `match_id`, `attempt`, `submissions` ({"A": ref, "B": ref}) are echoed into the result and
    into the structured log (BIO-206); a trace id is generated when none is given.
    """
    try:
        trace_id = log_mod.check_ref(trace_id, "trace_id") or log_mod.new_trace_id()
        match_id = log_mod.check_ref(match_id, "match_id")
        submissions = {k: log_mod.check_ref(v, f"submission_{k.lower()}") for k, v in (submissions or {}).items()}
    except ValueError as e:
        raise LauncherError(str(e))
    if not isinstance(attempt, int) or attempt < 1:
        raise LauncherError("attempt must be an integer >= 1")
    started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    lock = load_lock()
    problems = verify(scaffold, py, lock)
    if problems:
        raise LauncherError("version check failed: " + "; ".join(problems))
    for t in (team_a, team_b):
        if not (bots_dir / t).is_dir():
            raise LauncherError(f"bot directory not found: {bots_dir / t}")
    limits = None
    if limits_path is not None:
        try:
            limits = guard_mod.load_profile(limits_path)[0]
        except (OSError, ValueError, KeyError) as e:
            raise LauncherError(f"bad limits profile {limits_path}: {e}")
    use_cgroup = False
    if sandbox:
        try:
            sandbox_mod.check_available()
        except sandbox_mod.SandboxUnavailable as e:
            raise LauncherError(f"{e}; install it or pass --no-sandbox (NOT safe for untrusted bots)")
        if limits is None:
            raise LauncherError("the sandbox needs a limits profile")
        use_cgroup = sandbox_mod.cgroup_available() if cgroup is None else cgroup
        if cgroup and not sandbox_mod.cgroup_available():
            raise LauncherError("--require-cgroup: no usable `systemd-run --user` scope on this host")
    port = lock["crossplay_port"]
    if port_in_use(port):
        raise LauncherError(f"loopback port {port} is already in use (another match running?)")

    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    events_path = out_dir / f"match-{stamp}.events.jsonl"
    replay = out_dir / f"{team_a}-vs-{team_b}-{stamp}.bc26"
    server_log = out_dir / f"server-{stamp}.log"
    runner_logs = {"A": out_dir / f"runner-A-{stamp}.log", "B": out_dir / f"runner-B-{stamp}.log"}
    # The Java server loads a class directory for every team, even Python ones, and treats a missing
    # directory as a team error (the game then runs to round 2000 with no bots). With no Java bots in
    # the scaffold nothing creates that directory, so give the server an empty one.
    class_dir = out_dir / "empty-classes"
    class_dir.mkdir(exist_ok=True)

    names = {"A": team_a, "B": team_b}
    sock_dir = Path(tempfile.mkdtemp(prefix="bio-ipc-"))  # short path: unix socket paths are limited
    router = sandbox_mod.Router(sock_dir, port)
    seccomp_fds: list[int] = []
    cmds: dict[str, list[str]] = {}
    for side in ("A", "B"):
        if sandbox:
            fd = sandbox_mod.seccomp_pipe()
            seccomp_fds.append(fd)
            cmd = sandbox_mod.build_command(py, HERE / "runner_entry.py", side, bots_dir / names[side],
                                            router.paths[side], limits_path,
                                            [] if socket_tuning else ["--no-socket-tuning"], seccomp_fd=fd)
            if use_cgroup:
                cmd = sandbox_mod.cgroup_prefix(limits.memory_rss_mb * 2, limits.max_tasks + 32) + cmd
        else:
            cmd = build_runner_cmd(py, bots_dir, side, names[side], socket_tuning, limits_path, router.paths[side])
        cmds[side] = cmd

    runners: dict[str, subprocess.Popen] = {}
    gradle = None
    gradle_exit = None
    runner_exit: dict[str, int | None] = {"A": None, "B": None}
    died_order: list[str] = []
    early_exit: dict[str, int | None] = {}   # runners that were already dead before we stopped anything
    timed_out = False
    died_at = None
    start = time.monotonic()
    try:
        with open(runner_logs["A"], "wb") as la, open(runner_logs["B"], "wb") as lb, open(server_log, "wb") as sl:
            for side, log in (("A", la), ("B", lb)):
                runners[side] = subprocess.Popen(
                    cmds[side], stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                    start_new_session=True, cwd=scaffold, pass_fds=tuple(seccomp_fds))
            for fd in seccomp_fds:      # the children have their own copies
                os.close(fd)
            seccomp_fds = []
            gradle = subprocess.Popen(
                build_gradle_cmd(scaffold, team_a, team_b, maps, replay, offline, class_dir),
                stdin=subprocess.DEVNULL, stdout=sl, stderr=subprocess.STDOUT,
                start_new_session=True, cwd=scaffold)
            while gradle.poll() is None:
                if time.monotonic() - start > timeout:
                    timed_out = True
                    break
                for side, r in runners.items():
                    if r.poll() is not None and r.returncode != 0 and side not in died_order:
                        died_order.append(side)
                        died_at = died_at or time.monotonic()
                fe = router.stats["first_end"]
                if (died_at is None and fe and fe["leg"].startswith("runner:")
                        and not FINISHED_RE.search(server_log.read_text(errors="replace"))):
                    died_at = time.monotonic()  # a runner hung up (even with exit 0) and the game is not over
                if died_at and time.monotonic() - died_at > 3:
                    break           # a runner died: the server would wait for it forever
                time.sleep(0.1)
    finally:
        for fd in seccomp_fds:
            os.close(fd)
        early_exit = {s_: r.returncode for s_, r in runners.items() if r.poll() is not None}
        if gradle is not None:
            _stop_group(gradle)
            gradle_exit = gradle.returncode
        if any(r.poll() is None for r in runners.values()):
            time.sleep(1)  # the runners exit by themselves when the server ends the game
        for side, r in runners.items():
            _stop_group(r)
            runner_exit[side] = r.returncode
        router.close()
        for f in sock_dir.iterdir():
            f.unlink()
        sock_dir.rmdir()
    seconds = round(time.monotonic() - start, 1)

    result = parse_result(server_log.read_text(errors="replace"))
    per_side = {side: parse_guard_records(runner_logs[side].read_text(errors="replace")) for side in "AB"}
    # Which process wrote a record decides which team it is about: a bot can print any text, so the
    # team named inside a record is never trusted.
    violation = None
    for side in died_order + [s_ for s_ in "AB" if s_ not in died_order]:
        v = per_side[side].get("violation")
        if v is not None:
            v = dict(v)
            if v.get("team") != side:
                v["claimed_team"] = v.get("team")
                v["team"] = side if v.get("team") in ("A", "B") else v.get("team")
            violation = v
            break
    usage = merge_usage({side: per_side[side].get("usage") or (per_side[side].get("violation") or {}).get("usage")
                         for side in "AB"})
    exits = [e for e in (runner_exit["A"], runner_exit["B"]) if e not in (0, None)]
    combined_exit = exits[0] if exits else (0 if None not in runner_exit.values() else None)
    verdict = classify(result, violation, combined_exit, timed_out, router.stats, early_exit)
    verdict["outcome"] = OUTCOME[verdict["classification"]]    # the worker contract's three values
    if verdict["classification"] in ("bot_violation", "bot_crash"):
        # The engine never finished this game; do not report its (absent) winner.
        result["winner"] = result["winning_team"] = result["round"] = None
    result.update(verdict)
    result.update({
        "ok": (verdict["classification"] == "normal" and gradle_exit == 0 and not timed_out),
        "violation": violation,
        "usage": usage,
        "timed_out": timed_out,
        "gradle_exit": gradle_exit,
        "runner_exit": runner_exit,
        "runner_exit_early": early_exit,
        "router": router.stats,
        "python": interpreter_version(py),
        "seconds": seconds,
        "rounds_per_second": round(result["round"] / seconds, 2) if result["round"] else None,
        "replay": str(replay) if replay.exists() else None,
        "replay_sha256": sha256_of(replay) if replay.exists() else None,
        "replay_bytes": replay.stat().st_size if replay.exists() else None,
        "socket_tuning": socket_tuning,
        "sandbox": sandbox,
        "cgroup": use_cgroup,
        "limits_profile": str(limits_path) if limits_path else None,
        "logs": {"server": str(server_log), "runner_A": str(runner_logs["A"]), "runner_B": str(runner_logs["B"])},
        "trace_id": trace_id,
        "match_id": match_id,
        "attempt": attempt,
    })
    result["structured_log"] = write_structured_log(
        result, events_path, server_log, started_at, names, submissions, maps, lock, limits_path, limits,
        redact_paths={"scaffold": scaffold, "bots": bots_dir, "out": out_dir, "repo": HERE.parents[1],
                      "tmp": tempfile.gettempdir()})
    return result


def write_structured_log(result: dict, events_path: Path, server_log: Path, started_at: str, names: dict,
                         submissions: dict, maps: str, lock: dict, limits_path: Path | None,
                         limits, redact_paths: dict) -> dict:
    """Build and write the structured log (BIO-206). A failure here must never lose the match result."""
    try:
        ctx = {
            "trace_id": result["trace_id"], "match_id": result["match_id"], "attempt": result["attempt"],
            "teams": names, "submissions": submissions, "map": maps, "engine_version": lock["engine_version"],
            "started_at": started_at, "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "limits": dataclasses.asdict(limits) if limits is not None else None,
            "limits_profile": limits_path.stem if limits_path else None,
        }
        events = log_mod.build_events(result, ctx, server_log.read_text(errors="replace"),
                                      log_mod.Redactor(redact_paths))
        return log_mod.write_jsonl(events_path, events)
    except Exception as e:   # noqa: BLE001 - reported in the result, not raised
        return {"error": f"{type(e).__name__}: {e}"}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--scaffold", type=Path, default=DEFAULT_SCAFFOLD)
    p.add_argument("--python-version", help="use backend/.venvs/py<version>; default: primary_python from the lock")
    p.add_argument("--python", type=Path, help="explicit interpreter (overrides --python-version)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("verify", help="check interpreter, packages, engine version and cached artifact hash against the lock")
    r = sub.add_parser("run", help="run one match between two Python bots")
    r.add_argument("--team-a", required=True)
    r.add_argument("--team-b", required=True)
    r.add_argument("--bots-dir", type=Path, default=None, help="directory holding <team>/bot.py; default: scaffold src")
    r.add_argument("--maps", default="DefaultSmall")
    r.add_argument("--out-dir", type=Path, default=None, help="replay and logs; default: a new temp dir")
    r.add_argument("--timeout", type=int, default=1800, help="seconds; the server task is stopped after this")
    r.add_argument("--no-offline", action="store_true", help="let Gradle use the network")
    r.add_argument("--no-socket-tuning", action="store_true", help="disable TCP_NODELAY/QUICKACK tuning (for comparison)")
    r.add_argument("--no-sandbox", action="store_true",
                   help="run the runner without bubblewrap (development only; NOT safe for untrusted bots)")
    r.add_argument("--limits", type=Path, default=DEFAULT_LIMITS,
                   help="limits profile JSON; default: limits.provisional.json (numbers not yet approved, DEC-04)")
    r.add_argument("--require-cgroup", action="store_true",
                   help="fail if kernel cgroup limits (systemd-run --user) are unavailable; default: use them if present")
    r.add_argument("--no-cgroup", action="store_true", help="do not use kernel cgroup limits")
    r.add_argument("--trace-id", help="correlation id echoed into the result and log; default: a new random id")
    r.add_argument("--match-id", help="platform match id echoed into the result and log")
    r.add_argument("--attempt", type=int, default=1, help="attempt number echoed into the result and log")
    r.add_argument("--submission-a", help="submission reference of team A, echoed into the log")
    r.add_argument("--submission-b", help="submission reference of team B, echoed into the log")
    r.add_argument("--no-limits", action="store_true",
                   help="measure only: no limits are enforced (implies --no-sandbox); usage is still recorded")
    lg = sub.add_parser("logs", help="print the part of a structured match log that a role may read")
    lg.add_argument("file", type=Path, help="a match-*.events.jsonl file")
    lg.add_argument("--role", required=True, choices=log_mod.ROLES)
    lg.add_argument("--team", choices=("A", "B"), help="the reader's team (required for --role participant)")
    args = p.parse_args(argv)
    if args.cmd == "logs":
        try:
            for e in log_mod.view(log_mod.read_jsonl(args.file), args.role, args.team):
                print(json.dumps(e, separators=(",", ":")))
        except (OSError, ValueError) as e:
            print(json.dumps({"ok": False, "error": str(e)}), file=sys.stderr)
            return 2
        return 0
    scaffold = args.scaffold.resolve()
    lock = load_lock()
    py = resolve_python(args.python_version, args.python, lock)

    if args.cmd == "verify":
        problems = verify(scaffold, py, lock)
        print(json.dumps({"ok": not problems, "python": str(py), "problems": problems}, indent=2))
        return 0 if not problems else 1

    out_dir = (args.out_dir or Path(tempfile.mkdtemp(prefix="bio-match-"))).resolve()
    bots_dir = (args.bots_dir or scaffold / "src").resolve()
    try:
        res = run_match(scaffold, py, bots_dir, args.team_a, args.team_b, args.maps, out_dir,
                        args.timeout, not args.no_offline, not args.no_socket_tuning,
                        sandbox=not (args.no_sandbox or args.no_limits),
                        limits_path=None if args.no_limits else args.limits,
                        cgroup=False if args.no_cgroup else (True if args.require_cgroup else None),
                        trace_id=args.trace_id, match_id=args.match_id, attempt=args.attempt,
                        submissions={"A": args.submission_a, "B": args.submission_b})
    except LauncherError as e:
        print(json.dumps({"ok": False, "error": str(e)}, indent=2))
        return 2
    print(json.dumps(res, indent=2))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
