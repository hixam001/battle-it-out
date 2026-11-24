# SPDX-License-Identifier: AGPL-3.0-only
"""Match launcher for the Battlecode scaffold (BIO-003 / BIO-004).

Participants write Python bots only. This launcher starts the engine's Python runner
(`runner_entry.py`, any tested CPython from 3.12 up) and the engine's Java *server* task, which is
the existing Battlecode engine and is not replaced. It exists because the scaffold's Gradle task
for Python bots uses `python3` from PATH and deadlocks with `--new-process` on Linux (see
docs/TECHNICAL_DOCUMENTATION.md section 3.2).

Limits: one match per host at a time (fixed loopback port 27185). Not a sandbox.

    python3 backend/match_runner/setup_env.py 3.15            # once per Python version
    python3 backend/match_runner/launcher.py verify
    python3 backend/match_runner/launcher.py run --team-a examplefuncsplayer_py \\
        --team-b examplefuncsplayer_py --out-dir /somewhere/outside/repo
"""
from __future__ import annotations

import argparse
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
    from backend.match_runner import sandbox as sandbox_mod
except ImportError:  # pragma: no cover - script mode without the repo root on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from backend.match_runner import guard as guard_mod
    from backend.match_runner import sandbox as sandbox_mod

HERE = Path(__file__).resolve().parent
LOCK_PATH = HERE / "versions.lock.json"
DEFAULT_SCAFFOLD = HERE.parent / "battlecode26-scaffold"
VENVS = HERE.parent / ".venvs"
DEFAULT_LIMITS = HERE / "limits.provisional.json"

RESULT_RE = re.compile(r"\[server\]\s+(\S+)\s+\((A|B)\) wins \(round (\d+)\)")
REASON_RE = re.compile(r"\[server\] Reason: (.+)")
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


def build_runner_cmd(py: Path, bots_dir: Path, team_a: str, team_b: str, socket_tuning: bool,
                     limits: Path | None = None) -> list[str]:
    cmd = [str(py), "-I", str(HERE / "runner_entry.py"),
           "--teamA", team_a, "--teamB", team_b, "--dirA", str(bots_dir), "--dirB", str(bots_dir)]
    if not socket_tuning:
        cmd.append("--no-socket-tuning")
    cmd += ["--limits", str(limits)] if limits is not None else ["--measure"]
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
    m = RESULT_RE.search(log_text)
    r = REASON_RE.search(log_text)
    return {
        "winner": m.group(2) if m else None,
        "winning_team": m.group(1) if m else None,
        "round": int(m.group(3)) if m else None,
        "reason": r.group(1).strip() if r else None,
        "finished": "Match Finished" in log_text,
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


def classify(result: dict, violation: dict | None, runner_exit: int | None, timed_out: bool) -> dict:
    """Decide who is responsible. Bot limit breaches are bot failures (PRD: automatic loss, no rematch).

    Never invents a winner for a platform failure.
    """
    if violation is not None and violation.get("team") in ("A", "B"):
        loser = violation["team"]
        return {"classification": "bot_violation", "loser": loser, "winner_by_forfeit": "B" if loser == "A" else "A"}
    if violation is not None or runner_exit in (guard_mod.EXIT_PLATFORM,):
        return {"classification": "platform_failure", "detail": "limit breached while no bot was running"}
    if timed_out:
        return {"classification": "platform_failure", "detail": "match wall-clock timeout, no bot violation recorded"}
    if runner_exit not in (0, None) or result["server_errors"] or not result["finished"]:
        return {"classification": "platform_failure", "detail": "runner or server did not finish cleanly"}
    return {"classification": "normal"}


def run_match(scaffold: Path, py: Path, bots_dir: Path, team_a: str, team_b: str, maps: str,
              out_dir: Path, timeout: int, offline: bool, socket_tuning: bool,
              sandbox: bool = True, limits_path: Path | None = DEFAULT_LIMITS) -> dict:
    lock = load_lock()
    problems = verify(scaffold, py, lock)
    if problems:
        raise LauncherError("version check failed: " + "; ".join(problems))
    for t in (team_a, team_b):
        if not (bots_dir / t).is_dir():
            raise LauncherError(f"bot directory not found: {bots_dir / t}")
    if limits_path is not None:
        try:
            guard_mod.load_profile(limits_path)
        except (OSError, ValueError, KeyError) as e:
            raise LauncherError(f"bad limits profile {limits_path}: {e}")
    if sandbox:
        try:
            sandbox_mod.check_available()
        except sandbox_mod.SandboxUnavailable as e:
            raise LauncherError(f"{e}; install it or pass --no-sandbox (NOT safe for untrusted bots)")
        if limits_path is None:
            raise LauncherError("the sandbox needs a limits profile")
    port = lock["crossplay_port"]
    if port_in_use(port):
        raise LauncherError(f"loopback port {port} is already in use (another match running?)")

    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    replay = out_dir / f"{team_a}-vs-{team_b}-{stamp}.bc26"
    runner_log = out_dir / f"runner-{stamp}.log"
    server_log = out_dir / f"server-{stamp}.log"
    # The Java server loads a class directory for every team, even Python ones, and treats a missing
    # directory as a team error (the game then runs to round 2000 with no bots). With no Java bots in
    # the scaffold nothing creates that directory, so give the server an empty one.
    class_dir = out_dir / "empty-classes"
    class_dir.mkdir(exist_ok=True)

    bridge = None
    sock_dir = None
    if sandbox:
        sock_dir = Path(tempfile.mkdtemp(prefix="bio-ipc-"))  # short path: unix socket paths are limited
        bridge = sandbox_mod.Bridge(sock_dir / "engine.sock", port)
        runner_cmd = sandbox_mod.build_command(
            py, HERE / "runner_entry.py", {"A": bots_dir / team_a, "B": bots_dir / team_b},
            bridge.path, limits_path, [] if socket_tuning else ["--no-socket-tuning"])
    else:
        runner_cmd = build_runner_cmd(py, bots_dir, team_a, team_b, socket_tuning, limits_path)

    runner = gradle = None
    gradle_exit = runner_exit = None
    timed_out = False
    runner_died_at = None
    start = time.monotonic()
    try:
        with open(runner_log, "wb") as rl, open(server_log, "wb") as sl:
            runner = subprocess.Popen(runner_cmd, stdin=subprocess.DEVNULL, stdout=rl, stderr=subprocess.STDOUT,
                                      start_new_session=True, cwd=scaffold)
            gradle = subprocess.Popen(
                build_gradle_cmd(scaffold, team_a, team_b, maps, replay, offline, class_dir),
                stdin=subprocess.DEVNULL, stdout=sl, stderr=subprocess.STDOUT,
                start_new_session=True, cwd=scaffold)
            while gradle.poll() is None:
                if time.monotonic() - start > timeout:
                    timed_out = True
                    break
                if runner.poll() is not None and runner.returncode != 0:
                    # The runner died (bot violation or crash): the server would wait for it forever.
                    runner_died_at = runner_died_at or time.monotonic()
                    if time.monotonic() - runner_died_at > 3:
                        break
                time.sleep(0.1)
    finally:
        if gradle is not None:
            _stop_group(gradle)
            gradle_exit = gradle.returncode
        if runner is not None:
            if runner.poll() is None:
                time.sleep(1)  # the runner exits by itself when the server ends the game
            _stop_group(runner)
            runner_exit = runner.returncode
        if bridge is not None:
            bridge.close()
        if sock_dir is not None:
            for f in sock_dir.iterdir():
                f.unlink()
            sock_dir.rmdir()
    seconds = round(time.monotonic() - start, 1)

    result = parse_result(server_log.read_text(errors="replace"))
    records = parse_guard_records(runner_log.read_text(errors="replace"))
    violation = records.get("violation")
    usage = records.get("usage") or (violation or {}).get("usage")
    verdict = classify(result, violation, runner_exit, timed_out)
    if verdict["classification"] == "bot_violation":
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
        "python": interpreter_version(py),
        "seconds": seconds,
        "rounds_per_second": round(result["round"] / seconds, 2) if result["round"] else None,
        "replay": str(replay) if replay.exists() else None,
        "replay_sha256": sha256_of(replay) if replay.exists() else None,
        "replay_bytes": replay.stat().st_size if replay.exists() else None,
        "socket_tuning": socket_tuning,
        "sandbox": sandbox,
        "limits_profile": str(limits_path) if limits_path else None,
        "logs": {"server": str(server_log), "runner": str(runner_log)},
    })
    return result


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
    r.add_argument("--no-limits", action="store_true",
                   help="measure only: no limits are enforced (implies --no-sandbox); usage is still recorded")
    args = p.parse_args(argv)
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
                        limits_path=None if args.no_limits else args.limits)
    except LauncherError as e:
        print(json.dumps({"ok": False, "error": str(e)}, indent=2))
        return 2
    print(json.dumps(res, indent=2))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
