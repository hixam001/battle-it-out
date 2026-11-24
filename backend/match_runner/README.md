# match_runner

Starts one Battlecode match from the command line, for Python and Java bots, on Linux. It replaces the scaffold's Gradle path for Python bots, which fails as shipped (wrong `python3` from `PATH`, and a start-up deadlock with `--new-process`; see `docs/TECHNICAL_DOCUMENTATION.md` section 3.2).

Status: first building block of the execution foundation (BIO-003/BIO-004). It is **not** a sandbox and **not** the future match service.

## What it does

1. Checks the pins in `versions.lock.json`: the venv interpreter is Python 3.12, the installed `battlecode26` package is 1.2.2 (the content of the official 1.2.6 release), `engine_version.txt` is 1.2.6, and, if present, `.temp/battlecode.tar.gz` has the pinned SHA-256.
2. Refuses to start if loopback port 27185 is already in use (the engine uses a fixed port, so one match per host at a time).
3. Starts the Python runner itself (`.venv/bin/python -m battlecode26 ...`, no `--new-process`, output to a log file, its own session).
4. Runs only `./gradlew runJavaLocal` (the Java server) with a timeout.
5. Stops the runner it started (terminate, then kill) and prints a JSON summary: winner, round, reason, seconds, rounds per second, replay path and size, exit codes, log paths.

## Use

```bash
python3 backend/match_runner/launcher.py verify
python3 backend/match_runner/launcher.py run \
    --team-a examplefuncsplayer_py --team-b examplefuncsplayer_py \
    --lang-a python --lang-b python --out-dir /path/outside/repo
```

The launcher itself uses only the standard library, so any Python 3 can start it; the bots run in the scaffold's `.venv` (3.12). Exit codes: 0 match finished, 1 verify or match failed, 2 could not start (version check, busy port). Without `--out-dir`, a new temporary directory is used. Use `--tcp-nodelay` to try the experimental socket shim (`nodelay_shim.py`).

## Tests

```bash
python3 -m unittest backend.match_runner.tests.test_launcher
```

The unit tests cover result parsing, command construction, the lock file and the port check. The matches themselves are checked by running them; results are in `handoff.md` and `docs/TECHNICAL_DOCUMENTATION.md`.

## Not covered

Windows or macOS; Python 3.13 (TC-01); container isolation, resource limits and bot validation (BIO-201..204); running two matches at once; any claim about reliability beyond the runs recorded in the handoff.
