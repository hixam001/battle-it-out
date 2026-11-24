# match_runner

Runs one Battlecode match between two **Python** bots from the command line, on Linux, on Python 3.12 to 3.15. It replaces the scaffold's Gradle path for Python bots, which fails as shipped, and runs the engine's Python runner on newer Pythons than the engine officially supports. Java bots are not supported (`docs/CHANGE_NOTICES.md` CN-002); the Java engine *server* is still what plays the game.

Status: first building block of the execution foundation (BIO-003/BIO-004). It is **not** a sandbox and **not** the future match service.

## Files

| File | Purpose |
|---|---|
| `versions.lock.json` | Pins: primary and tested Python versions, engine 1.2.6, engine package SHA-256, dependency versions, loopback port |
| `setup_env.py` | Creates `backend/.venvs/py<version>` from the lock with `uv`; downloads and hash-checks the engine package into `backend/.cache/` |
| `launcher.py` | `verify` and `run` commands |
| `runner_entry.py` | Starts the engine's Python runner on any tested Python and tunes the socket (see below) |
| `tests/` | Unit tests, integration tests, and test bots (`featuretest_py`, `cpuload_py`, `hang_py`) |

## Use

```bash
python3 backend/match_runner/setup_env.py 3.15                 # once per Python version (3.12, 3.13, 3.14, 3.15 tested)
python3 backend/match_runner/launcher.py verify
python3 backend/match_runner/launcher.py run --team-a examplefuncsplayer_py --team-b examplefuncsplayer_py \
    --out-dir /path/outside/repo
```

Options: `--python-version X.Y` or `--python PATH` (default: the lock's primary version, 3.15), `--bots-dir DIR` (default: scaffold `src`), `--maps`, `--timeout SECONDS` (default 1800), `--no-offline`, `--no-socket-tuning`. The launcher itself uses only the standard library. Exit codes: 0 match finished cleanly, 1 verify or match failed, 2 could not start (version check, missing bot, busy port).

## What `run` does

1. Checks the pins: interpreter version is in the tested list, installed `battlecode26` 1.2.2 (the content of the official 1.2.6 release), `RestrictedPython` 8.1, `flatbuffers` 24.3.25, `engine_version.txt` 1.2.6, cached artifact SHA-256.
2. Refuses to start if loopback port 27185 is in use (fixed by the engine: one match per host at a time).
3. Starts `runner_entry.py` in the chosen environment, output to a log file, in its own session.
4. Runs only `./gradlew runJavaLocal` (the Java server) with a timeout, passing an empty class directory (the server treats a missing one as a team error).
5. Stops the runner it started if it is still alive, and prints a JSON summary: winner, round, reason, server errors, seconds, rounds per second, Python version, replay path and SHA-256, exit codes, log paths. `ok` is false on a timeout, an abnormal runner exit, a non-zero Gradle exit, an unfinished match, or any server-reported error.

## What `runner_entry.py` changes (the engine package is not modified)

- Imports the engine on Python 3.13+, where its unused opcode table raises `KeyError`, and calls `play()` directly because the engine's `main()` rejects every Python except 3.12.
- Sets `TCP_NODELAY`, sends each message with one write, and asks for immediate ACKs (`TCP_QUICKACK`). Without this a match took 12 to 23 minutes instead of about 3 seconds; replays were byte-identical. Linux only.

## Tests

```bash
backend/.venvs/py3.15/bin/python -m unittest backend.match_runner.tests.test_launcher      # 14 unit tests; also run on 3.12-3.14
BIO_INTEGRATION=1 python3 -m unittest backend.match_runner.tests.test_launcher             # real matches: golden output, hang timeout
```

## Not covered

Windows or macOS; free-threaded or alpha Pythons; other maps and bot pairings; container isolation, resource limits and bot validation (BIO-201..204); two matches at once; any claim about reliability beyond the recorded runs (`docs/TECHNICAL_DOCUMENTATION.md` section 3.5).
