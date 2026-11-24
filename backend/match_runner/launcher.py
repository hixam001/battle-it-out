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
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOCK_PATH = HERE / "versions.lock.json"
DEFAULT_SCAFFOLD = HERE.parent / "battlecode26-scaffold"
VENVS = HERE.parent / ".venvs"

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


def build_runner_cmd(py: Path, bots_dir: Path, team_a: str, team_b: str, socket_tuning: bool) -> list[str]:
    cmd = [str(py), "-I", str(HERE / "runner_entry.py"),
           "--teamA", team_a, "--teamB", team_b, "--dirA", str(bots_dir), "--dirB", str(bots_dir)]
    if not socket_tuning:
        cmd.append("--no-socket-tuning")
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


def run_match(scaffold: Path, py: Path, bots_dir: Path, team_a: str, team_b: str, maps: str,
              out_dir: Path, timeout: int, offline: bool, socket_tuning: bool) -> dict:
    lock = load_lock()
    problems = verify(scaffold, py, lock)
    if problems:
        raise LauncherError("version check failed: " + "; ".join(problems))
    for t in (team_a, team_b):
        if not (bots_dir / t).is_dir():
            raise LauncherError(f"bot directory not found: {bots_dir / t}")
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

    runner = None
    gradle_exit = None
    timed_out = False
    runner_exit = None
    start = time.monotonic()
    try:
        with open(runner_log, "wb") as rl:
            runner = subprocess.Popen(
                build_runner_cmd(py, bots_dir, team_a, team_b, socket_tuning),
                stdin=subprocess.DEVNULL, stdout=rl, stderr=subprocess.STDOUT,
                start_new_session=True, cwd=scaffold)
        with open(server_log, "wb") as sl:
            try:
                gradle = subprocess.run(
                    build_gradle_cmd(scaffold, team_a, team_b, maps, replay, offline, class_dir),
                    stdin=subprocess.DEVNULL, stdout=sl, stderr=subprocess.STDOUT,
                    cwd=scaffold, timeout=timeout)
                gradle_exit = gradle.returncode
            except subprocess.TimeoutExpired:
                timed_out = True
    finally:
        if runner is not None:
            if runner.poll() is None:
                time.sleep(1)  # the runner exits by itself when the server ends the game
            if runner.poll() is None:
                runner.terminate()
                try:
                    runner.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    runner.kill()
                    runner.wait()
            runner_exit = runner.returncode
    seconds = round(time.monotonic() - start, 1)

    result = parse_result(server_log.read_text(errors="replace"))
    result.update({
        "ok": (gradle_exit == 0 and result["finished"] and not timed_out and runner_exit == 0
               and not result["server_errors"]),
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
                        args.timeout, not args.no_offline, not args.no_socket_tuning)
    except LauncherError as e:
        print(json.dumps({"ok": False, "error": str(e)}, indent=2))
        return 2
    print(json.dumps(res, indent=2))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
