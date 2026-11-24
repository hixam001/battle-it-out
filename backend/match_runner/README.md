# match_runner

Runs one Battlecode match between two **Python** bots from the command line, on Linux, on Python 3.12 to 3.15. It replaces the scaffold's Gradle path for Python bots, which fails as shipped, and runs the engine's Python runner on newer Pythons than the engine officially supports. Java bots are not supported (`docs/CHANGE_NOTICES.md` CN-002); the Java engine *server* is still what plays the game.

Status: execution foundation (BIO-003/004 launcher; BIO-203/204 limits and sandbox). It is **not** the future match service. By default every match runs as two processes, one per team, each in its own bubblewrap sandbox with a seccomp filter, optional cgroup limits and a resource guard, behind a router in front of the Java server. The numeric limits are an **interim profile, not benchmark-approved** (DEC-04, `docs/CHANGE_NOTICES.md` CN-005) and no independent security review has been done. Read `docs/TECHNICAL_DOCUMENTATION.md` section 3.6 before relying on it.

## Files

| File | Purpose |
|---|---|
| `versions.lock.json` | Pins: primary and tested Python versions, engine 1.2.6, engine package SHA-256, dependency versions, loopback port |
| `setup_env.py` | Creates `backend/.venvs/py<version>` from the lock with `uv`; downloads and hash-checks the engine package into `backend/.cache/` |
| `launcher.py` | `verify` and `run` commands |
| `runner_entry.py` | Starts the engine's Python runner on any tested Python, tunes the socket, installs the guard (see below) |
| `guard.py` | In-process watchdog: turn and start-up wall-clock limits, memory limit, rlimits, usage measurements; writes `BIO-GUARD-*` lines to stdout |
| `sandbox.py` | bubblewrap command builder, seccomp filter, cgroup prefix, and the `Router` that joins the two team processes to the Java server |
| `limits.provisional.json` | The one platform-wide limits profile (**interim, not benchmark-approved**) |
| `tests/` | Unit and integration tests; test bots: `featuretest_py`, `cpuload_py`, and hostile ones `hang_py`, `hang_init_py`, `memhog_py`, `allocbomb_py`, `escape_py`, `forge_py` (never put these in a tournament) |

## Use

```bash
python3 backend/match_runner/setup_env.py 3.15                 # once per Python version (3.12, 3.13, 3.14, 3.15 tested)
python3 backend/match_runner/launcher.py verify
python3 backend/match_runner/launcher.py run --team-a examplefuncsplayer_py --team-b examplefuncsplayer_py \
    --out-dir /path/outside/repo
```

Options: `--python-version X.Y` or `--python PATH` (default: the lock's primary version, 3.15), `--bots-dir DIR` (default: scaffold `src`), `--maps`, `--timeout SECONDS` (default 1800), `--no-offline`, `--no-socket-tuning`, `--limits FILE` (default `limits.provisional.json`), `--no-sandbox` (development only, **not safe for untrusted bots**), `--no-limits` (measure only; implies `--no-sandbox`), `--no-cgroup`, `--require-cgroup`. Needs `bwrap` (bubblewrap) and unprivileged user namespaces for the default mode; kernel cgroup limits are used automatically when `systemd-run --user` works. The launcher itself uses only the standard library. Exit codes: 0 match finished cleanly, 1 verify or match failed, 2 could not start (version check, missing bot, busy port).

## What `run` does

1. Checks the pins: interpreter version is in the tested list, installed `battlecode26` 1.2.2 (the content of the official 1.2.6 release), `RestrictedPython` 8.1, `flatbuffers` 24.3.25, `engine_version.txt` 1.2.6, cached artifact SHA-256.
2. Refuses to start if loopback port 27185 is in use (fixed by the engine: one match per host at a time).
3. Starts the `Router` (one unix socket per team, one TCP connection to the Java server) and one `runner_entry.py` per team inside its own sandbox, each logging to its own file, in its own session.
4. Starts only `./gradlew runJavaLocal` (the Java server), passing an empty class directory (the server treats a missing one as a team error), and watches all processes. If a runner dies, the server is stopped about 3 s later; the overall `--timeout` still applies.
5. Stops what it started and prints a JSON summary: `classification` (`normal`, `bot_violation` or `bot_crash` with `loser` and `winner_by_forfeit`, or `platform_failure` with a `kind`), `outcome` (`completed`, `bot_failure` or `platform_failure`, the worker contract's values), `evidence` (for a crash: which side closed the engine connection first, exit status, signal), `violation` (team, kind, measured value, limit, round, robot id; the team comes from the process that wrote the record, not from its text), `usage` (measured time and memory per team and per process), winner, round, reason, seconds, Python version, replay path and SHA-256, exit codes, log paths. `ok` is true only for a `normal` match with a clean exit.

## What `runner_entry.py` changes (the engine package is not modified)

- Imports the engine on Python 3.13+, where its unused opcode table raises `KeyError`, and calls `play()` directly because the engine's `main()` rejects every Python except 3.12.
- Sets `TCP_NODELAY`, sends each message with one write, and asks for immediate ACKs (`TCP_QUICKACK`). Without this a match took 12 to 23 minutes instead of about 3 seconds; replays were byte-identical. Linux only.

## Tests

```bash
backend/.venvs/py3.15/bin/python -m unittest backend.match_runner.tests.test_launcher backend.match_runner.tests.test_limits_sandbox   # unit tests (also run on 3.12-3.14)
BIO_INTEGRATION=1 backend/.venvs/py3.15/bin/python -m unittest backend.match_runner.tests.test_launcher backend.match_runner.tests.test_limits_sandbox   # real matches: golden output, forfeits, sandbox escape probe
```

## Not covered

Windows or macOS; free-threaded or alpha Pythons; other maps and bot pairings; independent security review; benchmark-approved numeric limits; engine tie-break seed; two matches at once; any claim about reliability beyond the recorded runs (`docs/TECHNICAL_DOCUMENTATION.md` sections 3.5 and 3.6).
