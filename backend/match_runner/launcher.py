"""Match launcher for the Battlecode scaffold (BIO-003 / BIO-004).

Why this exists: the scaffold's Gradle task for Python bots uses `python3` from PATH and
starts the runner with `--new-process`, which deadlocks on Linux (see
docs/TECHNICAL_DOCUMENTATION.md section 3.2). This launcher starts the Python runner
itself, with an explicit interpreter and redirected output, then runs only the Java
server task, then stops the runner it started.

Limits: one match per host at a time (the engine uses fixed loopback port 27185). Not a
sandbox: bots run with the engine's language-level restrictions only.

    python launcher.py verify
    python launcher.py run --team-a examplefuncsplayer_py --team-b examplefuncsplayer_py \\
        --lang-a python --lang-b python --out-dir /somewhere/outside/repo
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

RESULT_RE = re.compile(r"\[server\]\s+(\S+)\s+\((A|B)\) wins \(round (\d+)\)")
REASON_RE = re.compile(r"\[server\] Reason: (.+)")


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


def venv_python(scaffold: Path) -> Path:
    return scaffold / ".venv" / "bin" / "python"


def verify(scaffold: Path, lock: dict) -> list[str]:
    """Return a list of problems; empty means every pinned fact matches."""
    problems: list[str] = []
    py = venv_python(scaffold)
    if not py.exists():
        return [f"venv interpreter not found: {py}"]

    out = subprocess.run(
        [str(py), "-c",
         "import sys, importlib.metadata as m;"
         f"print('%d.%d' % sys.version_info[:2]);print(m.version('{lock['engine_package']['name']}'))"],
        capture_output=True, text=True)
    if out.returncode != 0:
        problems.append(f"cannot query venv interpreter: {out.stderr.strip()[:200]}")
    else:
        pyver, pkgver = out.stdout.split()
        if pyver != lock["python"]:
            problems.append(f"venv Python is {pyver}, pinned {lock['python']}")
        if pkgver != lock["engine_package"]["metadata_version"]:
            problems.append(f"installed package {pkgver}, pinned {lock['engine_package']['metadata_version']}")

    ev = (scaffold / "engine_version.txt").read_text().strip()
    if ev != lock["engine_version"]:
        problems.append(f"engine_version.txt is {ev}, pinned {lock['engine_version']}")

    tar = scaffold / ".temp" / "battlecode.tar.gz"
    if tar.exists():
        got = sha256_of(tar)
        if got != lock["engine_package"]["artifact_sha256"]:
            problems.append(f".temp/battlecode.tar.gz sha256 {got[:12]}..., pinned {lock['engine_package']['artifact_sha256'][:12]}...")
    return problems


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def build_runner_cmd(scaffold: Path, team_a: str, team_b: str, lang_a: str, lang_b: str,
                     nodelay: bool) -> list[str]:
    src = str(scaffold / "src")
    py = str(venv_python(scaffold))
    base = [py, "-I", str(HERE / "nodelay_shim.py")] if nodelay else [py, "-m", "battlecode26"]
    return base + [
        "--teamA", team_a if lang_a == "python" else "/",
        "--teamB", team_b if lang_b == "python" else "/",
        "--dirA", src, "--dirB", src,
    ]


def build_gradle_cmd(scaffold: Path, team_a: str, team_b: str, lang_a: str, lang_b: str,
                     maps: str, replay: Path, offline: bool) -> list[str]:
    cmd = [str(scaffold / "gradlew"), "runJavaLocal", "--console=plain"]
    if offline:
        cmd.append("--offline")
    cmd += [f"-PlanguageA={lang_a}", f"-PlanguageB={lang_b}",
            f"-PteamA={team_a}", f"-PteamB={team_b}",
            f"-Pmaps={maps}", f"-Preplay={replay}"]
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
    }


def run_match(scaffold: Path, team_a: str, team_b: str, lang_a: str, lang_b: str,
              maps: str, out_dir: Path, timeout: int, offline: bool, nodelay: bool) -> dict:
    lock = load_lock()
    problems = verify(scaffold, lock)
    if problems:
        raise LauncherError("version check failed: " + "; ".join(problems))
    port = lock["crossplay_port"]
    if port_in_use(port):
        raise LauncherError(f"loopback port {port} is already in use (another match running?)")

    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    replay = out_dir / f"{team_a}-vs-{team_b}-{stamp}.bc26"
    runner_log = out_dir / f"runner-{stamp}.log"
    server_log = out_dir / f"server-{stamp}.log"

    runner = None
    gradle_exit = None
    timed_out = False
    start = time.monotonic()
    try:
        if "python" in (lang_a, lang_b):
            with open(runner_log, "wb") as rl:
                runner = subprocess.Popen(
                    build_runner_cmd(scaffold, team_a, team_b, lang_a, lang_b, nodelay),
                    stdin=subprocess.DEVNULL, stdout=rl, stderr=subprocess.STDOUT,
                    start_new_session=True, cwd=scaffold)
        with open(server_log, "wb") as sl:
            try:
                gradle = subprocess.run(
                    build_gradle_cmd(scaffold, team_a, team_b, lang_a, lang_b, maps, replay, offline),
                    stdin=subprocess.DEVNULL, stdout=sl, stderr=subprocess.STDOUT,
                    cwd=scaffold, timeout=timeout)
                gradle_exit = gradle.returncode
            except subprocess.TimeoutExpired:
                timed_out = True
    finally:
        runner_exit = None
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
        "ok": gradle_exit == 0 and result["finished"] and not timed_out,
        "timed_out": timed_out,
        "gradle_exit": gradle_exit,
        "runner_exit": runner_exit,
        "seconds": seconds,
        "rounds_per_second": round(result["round"] / seconds, 2) if result["round"] else None,
        "replay": str(replay) if replay.exists() else None,
        "replay_bytes": replay.stat().st_size if replay.exists() else None,
        "tcp_nodelay_shim": nodelay,
        "logs": {"server": str(server_log), "runner": str(runner_log) if runner else None},
    })
    return result


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--scaffold", type=Path, default=DEFAULT_SCAFFOLD)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("verify", help="check interpreter, package, engine version and artifact hash against the lock")
    r = sub.add_parser("run", help="run one match")
    r.add_argument("--team-a", required=True)
    r.add_argument("--team-b", required=True)
    r.add_argument("--lang-a", choices=["python", "java"], default="python")
    r.add_argument("--lang-b", choices=["python", "java"], default="python")
    r.add_argument("--maps", default="DefaultSmall")
    r.add_argument("--out-dir", type=Path, default=None, help="replay and logs; default: a new temp dir")
    r.add_argument("--timeout", type=int, default=1800, help="seconds; the server task is stopped after this")
    r.add_argument("--no-offline", action="store_true", help="let Gradle use the network")
    r.add_argument("--tcp-nodelay", action="store_true", help="experimental socket shim, see nodelay_shim.py")
    args = p.parse_args(argv)
    scaffold = args.scaffold.resolve()

    if args.cmd == "verify":
        problems = verify(scaffold, load_lock())
        print(json.dumps({"ok": not problems, "problems": problems}, indent=2))
        return 0 if not problems else 1

    out_dir = (args.out_dir or Path(tempfile.mkdtemp(prefix="bio-match-"))).resolve()
    try:
        res = run_match(scaffold, args.team_a, args.team_b, args.lang_a, args.lang_b,
                        args.maps, out_dir, args.timeout, not args.no_offline, args.tcp_nodelay)
    except LauncherError as e:
        print(json.dumps({"ok": False, "error": str(e)}, indent=2))
        return 2
    print(json.dumps(res, indent=2))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
