# Battle It Out --- Technical & API Documentation

**Version:** 1.0\
**Status:** Developer reference. Sections 1 to 4 describe code that exists and was checked on 2026-11-24. Sections 5 to 8 summarize the proposed database, interfaces and endpoints; their canonical sources are `DATA_MODEL.md` and `API_CONTRACT.md`, and nothing in them is implemented yet.\
**Date:** 2026-11-24\
**Audience:** developers working on the scaffold, the bot runner, the backend, or the worker.

> **Labels.** *Verified* = I ran it or read the code on 2026-11-24. *Proposed* = design intent, not code. `[DECIDE]` = unresolved. Where a command was not run, the text says so. If this document and a canonical source (`API_CONTRACT.md`, `DATA_MODEL.md`, the code) disagree, the canonical source wins; fix this file.

## 1. Repository layout

```text
battle-it-out/
├── README.md                    project overview and quick start
├── CHANGELOG.md                 notable changes
├── PRODUCT.md                   product context for design tooling (derived from docs)
├── handoff.md                   current state, rules, task log (read first)
├── .gitignore                   ignores local settings and agent/skill files
├── docs/                        specifications and guides
│   ├── PRD.md  SRD.md  APP_FLOW.md  API_CONTRACT.md  DATA_MODEL.md  TEST_PLAN.md
│   └── PROJECT_PLAN.md  ARCHITECTURE.md  TECHNICAL_DOCUMENTATION.md
│       USER_GUIDE.md  ADMIN_GUIDE.md
├── backend/
│   ├── README.md                provenance and local notes for the vendored scaffold
│   ├── match_runner/            match launcher, guard, sandbox, pinned versions, env setup, tests (BIO-003/004, BIO-203/204)
│   ├── .venvs/ .cache/          git-ignored; created by match_runner/setup_env.py
│   └── battlecode26-scaffold/   Battlecode 2026 scaffold (upstream f69e2ab + local edits)
│       ├── build.gradle  gradle.properties  gradlew  gradlew.bat  gradle/wrapper/
│       ├── engine_version.txt  client_version.txt
│       ├── run.py               scaffold launcher (accepts only Python 3.12; not used by match_runner)
│       ├── src/
│       │   └── examplefuncsplayer_py/bot.py             Python example bot
│       └── LICENSE              GNU AGPL v3
└── .github/modernize/java-upgrade/   tooling hook scripts (not part of the product)
```

Git-ignored, local-only directories inside the scaffold (recreated by tooling): `.venv`, `.gradle`, `build/`, `client/`, `matches/`, `.temp/`. Agent and skill directories (`.claude/skills`, `.claude/agents`, `.agents`, `skills-lock.json`) are also ignored.

The backend described in later sections (API, database, worker) does not exist yet; where it will live under `backend/` is `[DECIDE]`. A reasonable starting point is sibling packages next to the scaffold, but that is a proposal, not a decision.

## 2. Prerequisites and environment

| Requirement | Detail | Status |
|---|---|---|
| JDK 21 or newer | `build.gradle` throws "The engine must be run using >= Java 21 JDK" below 21 | *Verified* (JDK 21.0.13 used) |
| Gradle | Wrapper `gradle-8.10`; use `./gradlew`, no system Gradle needed | *Verified* |
| Python (latest stable; 3.15.2 primary) | Run through `match_runner/runner_entry.py`, which works on 3.12 to 3.15 (section 3.5). `uv` creates the environments | *Verified* on 3.12.15, 3.13.18, 3.14.10, 3.15.2 (Linux x86_64); `[DECIDE]` exact patch and OS matrix (DEC-03, `CHANGE_NOTICES.md` CN-001) |
| `uv` | `backend/match_runner/setup_env.py` calls it to create environments from `versions.lock.json` | *Verified* (uv 0.13.5) |
| Scaffold `run.py` | Accepts only Python 3.12 (`REQUIRED_PYTHON_VERSION = (3, 12)`); the match launcher does not use it | *Verified*; its `verify` and `test` tasks are of little value (section 3.4) |
| Environments | `backend/.venvs/py<version>`: the engine package `battlecode26` 1.2.2 (installed `--no-deps`, hash-checked) plus `RestrictedPython` 8.1 and `flatbuffers` 24.3.25 | *Verified*; the older scaffold `.venv` (3.12.15) still exists and is only used by `run.py` |
| Network (first build) | Gradle downloads the engine/client from `releases.battlecode.org`; the Python package comes from `.temp/battlecode.tar.gz` | Offline runs need a warm cache; a cold-clone build was **not** tested |

**Version facts to keep in mind** (*Verified*): `engine_version.txt` = `1.2.6`, `client_version.txt` = `1.0.6`, installed Python package `battlecode26` = `1.2.2`. The package number is not drift: the official release artifact for engine 1.2.6 (`releases.battlecode.org/maven/org/battlecode/battlecode26-python/1.2.6/battlecode.tar.gz`) contains package 1.2.2, and the copy in `.temp/` is byte-identical to it (SHA-256 `bf52c038...8b03f9`, checked 2026-11-24). Side effect: `run.py install_current_version` compares `1.2.2` with `1.2.6` and so reinstalls the package on every `runLocal` with a Python team. The build also reports that client `1.0.7` is available (server says `release_version_client` 1.0.7, `release_version_public` 1.2.6). Pinning the versions and the artifact hash is BIO-003/BIO-101.

## 3. Build, run and configuration

### 3.1 Gradle tasks (*Verified* with `./gradlew tasks --group battlecode`)

Run from `backend/battlecode26-scaffold/`.

| Task | Purpose |
|---|---|
| `build` | Compile and test; also downloads the client (`unpackClient`) |
| `runLocal` | Run a match locally without updating anything and without starting the client |
| `run` | Same as `runLocal`, but first updates the Python package for Python teams (needs network) |
| `verify` | Run the Java instrumenter's package verification for a team package (only meaningful for Java packages; unused now) |
| `listPlayers` | List packages containing `RobotPlayer.java` or `.scala` (now always empty) |
| `listMaps` | List available `.map26` maps |
| `version` | Print configured engine and client versions |
| `checkNewVersion` | Compare configured versions to the published ones |
| `update` | Overwrite `engine_version.txt` and `client_version.txt` with the latest published versions (network) |
| `installPyLocal` | Install the already-downloaded Python engine package |
| `downloadPyPackage` | Download the Python engine package (via `run.py update`) |
| `unpackClient` | Download and unpack the desktop client into `client/` |
| `zipForSubmit` | Zip all of `src/` into `submission.zip` |

### 3.2 Run a match

Participants write Python bots only; the Java *engine server* is what plays the game (CN-002). Use the match launcher, not the scaffold's Gradle task for Python bots:

```bash
python3 backend/match_runner/setup_env.py 3.15          # once; creates backend/.venvs/py3.15 from versions.lock.json
python3 backend/match_runner/launcher.py verify          # checks interpreter, package pins, engine version, cached artifact hash
python3 backend/match_runner/launcher.py run --team-a examplefuncsplayer_py --team-b examplefuncsplayer_py \
    --out-dir /path/outside/repo                         # --python-version 3.14 to use another environment
```

*Observed* (2026-11-24, example bot against itself on `DefaultSmall`, all four Python versions): `examplefuncsplayer_py (A) wins (round 1290)`, reason "The winning team destroyed all of the enemy team's rat kings", 2.8 to 3.3 s including JVM start-up, and the replay has the same SHA-256 on every version (`a08779089a8c...`). The earlier Java-vs-Java baseline took 5.2 s through the launcher (round 860, a different game), so Python matches are not slower than the old Java baseline for this bot. This is one light bot; heavier bots are limited by the speed of Python (section 3.5).

The launcher starts `runner_entry.py` in the chosen environment (the engine's Python runner), runs only `./gradlew runJavaLocal` (the Java server) with a timeout, stops the runner it started, and prints a JSON summary. It refuses to start when versions differ from the pins or loopback port 27185 is busy (one match per host at a time). It marks a run failed if the server logs a team error, the runner exits abnormally, or the timeout is hit. Details and exit codes: `backend/match_runner/README.md`.

**Why not the scaffold's Gradle task** (`./gradlew runLocal -PlanguageA=python ...`)? Three problems, found by running it and reading the code:

1. **Wrong interpreter.** `build.gradle` starts `python3` from `PATH` (system 3.14 here: no package, and `run.py` rejects it). A running Gradle daemon also keeps the `PATH` it started with.
2. **Start-up deadlock.** `runPyLocal` calls the runner with `--new-process`; the spawned runner holds Gradle's output pipe while it retries `127.0.0.1:27185`, but the Java server task is ordered after it and Gradle waits for the pipe to close. (The Windows branch uses `DETACHED_PROCESS`, which avoids it.)
3. **Missing class directory.** With no Java bots there is no compiled-classes directory, and the engine server treats that as a team error for Python teams too (`Error while loading player ...: ILLEGAL Team is known to have errors`); the game then runs to round 2000 on a coin flip with no bots acting. The launcher passes `-PclassLocationA/B=<empty dir>`; do the same if you run Gradle by hand.

**Why matches used to take 12 to 23 minutes, and what fixed it.** The engine's Python client sends each message as two writes (4-byte length, then JSON) and neither it nor the Java `CrossPlay` server sets `TCP_NODELAY`, so Nagle's algorithm and delayed ACKs cost about 40 ms per message, and every game call is a round trip. `runner_entry.py` sets `TCP_NODELAY`, sends one write per message and asks for immediate ACKs (`TCP_QUICKACK`) around each receive; message contents are unchanged. *Measured* on 3.12 with the example bot: 1400 s without, 704 s with `TCP_NODELAY` and a single write, about 3 s with `TCP_QUICKACK` added. The replay was byte-identical in all three cases. Use `--no-socket-tuning` to switch it off for comparison. Linux only (`TCP_QUICKACK`).

### 3.3 Configuration properties (`gradle.properties` plus `-P` overrides)

| Property | Default in file | Meaning |
|---|---|---|
| `teamA`, `teamB` | `examplefuncsplayer_py` | Team directory names under `src/` |
| `languageA`, `languageB` | `python` | Language of each team; the launcher always passes `python` (Java bots were removed, CN-002) |
| `maps` | `DefaultSmall` | Map name(s) |
| `debug` | `false` | Engine debug methods |
| `outputVerbose` | `true` | Print bot output to the console |
| `showIndicators` | `true` | Include bot indicator strings in replays |
| `validateMaps` | `true` | Validate maps before running |
| `alternateOrder` | `false` | Alternate team order |
| `compatibilityClient` | `false` | Download the Electron client instead of the Tauri one |
| `replay` | (unset) | Replay output path (default `matches/<names>.bc26`) |
| `waitForClient` | `false` | Pause until a client connects |
| `classLocationA/B`, `packageNameA/B` | derived | Where team classes and packages are found; **must point to an existing directory** even for Python teams (an empty one is enough, see section 3.2) |
| `onSaturn`, `gcloudToken`, `forceReinstallPy` | unset | Organizer-internal distribution options of the scaffold |

The Java engine reads these through JVM system properties such as `-Dbc.game.team-a`, `-Dbc.game.maps`, `-Dbc.server.save-file`, `-Dbc.server.mode=headless`, `-Dbc.server.validate-maps`. The server is pointed at a `maps` directory (`-Dbc.server.map-path=maps`; it does not exist locally), and `listMaps` reads `.map26` files from both that directory and the engine jar. The default map `DefaultSmall` ran successfully, so it is available from the jar.

### 3.4 `run.py` tasks (*Verified*: `tasks`, `verify`, `test`; others read, not run)

Run with the scaffold's Python 3.12 interpreter, from the scaffold root: `.venv/bin/python run.py <task> [options]`. The match launcher does not use `run.py`.

| Task | Behavior |
|---|---|
| `tasks` | Prints `tasks, test, update, verify, run, install_current_version, zip_submission` |
| `verify --p1 <team>` | Passes if `src/<team>/bot.py` exists and its text contains `def turn():`. *Verified*: passes for `examplefuncsplayer_py`. **It checks neither syntax nor imports.** |
| `test` | Runs every `*.py` file under `test/`; *Verified*: prints `No tests found.` |
| `update` | Downloads the latest engine Python package to `.temp/` and installs it; writes `engine_version.txt` |
| `install_current_version` | Installs the package for the version in `engine_version.txt` when the installed one differs |
| `run --p1 --p2 [--p1-dir --p2-dir --debug]` | Starts the Python cross-play runner (`from battlecode26 import _main`) |
| `zip_submission` | Zips `src/**/*.py` into `submission.zip` |

### 3.5 Python version test matrix (*Verified*, 2026-11-24, Linux x86_64, CachyOS, JDK 21)

Every row is a full match through `launcher.py` in a fresh environment built by `setup_env.py` from `versions.lock.json`. Test bots live in `backend/match_runner/tests/bots/`.

| Python | Example bot, 1290 rounds | Feature bot, 1310 rounds | CPU-load bot, 1310 rounds |
|---|---|---|---|
| 3.12.15 | 3.3 s | 2.1 s | 4.3 s |
| 3.13.18 | 2.8 s | 2.0 s | 4.4 s |
| 3.14.10 | 2.9 s | 2.0 s | 5.7 s |
| 3.15.2 | 3.2 s | 2.1 s | 4.6 s |

- **Same behaviour on every version.** The feature bot (`featuretest_py`) logs 32 deterministic lines covering arithmetic, strings, collections, classes, generators, closures, exceptions, the walrus operator, `match`, recursion, seeded `random`, `math`, `*args/**kwargs`, and the sandbox probes below; the output is identical on 3.12, 3.13, 3.14 and 3.15 (`tests/expected_featuretest.txt`). The example bot's replay has the same SHA-256 on all four. Replays of the two do-nothing test bots vary from run to run on the same version (two different hashes in five runs, same round and winner); the cause was not investigated.
- **Why newer Pythons needed work.** The engine package's `instrument.py` builds a table of CPython 3.12 opcode names when imported and raises `KeyError: 'KW_NAMES'` on 3.13 and later; its `main()` rejects anything but 3.12. Nothing in the package calls `Instrument.instrument()` (the runner `exec()`s the bot source), so the table is unused; `runner_entry.py` lets the import succeed by giving a copy of `dis.opmap` the missing names for that import only (`dis.opmap` is read-only on 3.15). The engine package itself is not modified.
- **Speed is not a version problem.** Python 3.15 ran the CPU-load bot in 4.6 s against 4.3 s on 3.12; differences between versions were within about 30% on one machine and were not repeated enough to rank versions.
- **What was not tested:** other operating systems, free-threaded builds, 3.16, other maps, matches between different bots, and long or memory-heavy bots.

**Sandbox probes** (from `featuretest_py`, identical on all four versions). The engine does not use RestrictedPython's compiler; the runner `exec()`s the bot's source with a reduced builtins table. Observed:

| Probe | Result |
|---|---|
| `import os`, `import sys` | blocked (`ImportError`); `import math` allowed |
| `eval`, `exec` | blocked (not defined) |
| `open` | **available** (the runner adds it to the builtins) |
| `().__class__.__base__.__subclasses__()` | **allowed**: attribute access is not guarded, the usual route out of such sandboxes |
| `setattr`, `delattr` | available |
| `dict`, `sum`, `min`, `max`, `map`, `filter`, `any`, `all`, `super`, `type`, `object`, `property`, `next`, `iter`, `getattr`, `print`, `classmethod`, `staticmethod` | **not defined** (`NameError`); dict literals, comprehensions, `sorted`, `zip`, `enumerate`, `set`, `range`, `len`, `abs`, `pow`, `round`, `divmod` work |
| `while True: pass` in `turn()` | **never stops inside the engine**: the match hangs until something outside ends it. The launcher's guard now does (section 3.6) |

These are facts for the bot validator (BIO-201), the sandbox (BIO-203/204) and the limits (DEC-04): the engine gives no protection against file access or a runaway bot, so the platform must enforce host-level isolation and wall-clock limits itself (done in section 3.6, with the gaps listed there), and the allowed-builtins list is far narrower than the PRD's "standard library".

### 3.6 Bot execution limits and sandbox (*Verified* by tests, 2026-11-24, Linux x86_64, bubblewrap 0.13.1)

`backend/match_runner/` runs every match as **two runner processes, one per team, each inside its own bubblewrap sandbox with a resource guard**, joined to the Java engine server by a host-side **router**. All of it is on by default; `--no-sandbox` (development only) and `--no-limits` (measure only) turn layers off. Decisions behind it: `CHANGE_NOTICES.md` CN-005.

**Why the design looks like this (read from `battlecode26/runner.py`, `__main__.py` and the Java `CrossPlay` class).** In the official setup every robot of both teams is a thread of ONE Python runner process, which connects to the Java server over ONE TCP connection (the server opens a single `ServerSocket` on port 27185 and accepts once). The runner's main thread waits for a turn with `Event.wait()` and no timeout, and a bot's top-level code is `exec()`d on the main thread, so `while True: pass` hangs the whole match; nothing limits memory; and the two teams share memory, module state and the `random` stream.

| Layer | What it does | Evidence |
|---|---|---|
| One process per team + `Router` (`sandbox.py`) | Each team's runner connects to its own unix socket; the router connects once to the Java server and sends each server message to the right team: `spawn_bot` by team, `start_turn` by robot id, `destroy_bot` to the robot's owner without changing the active team, `end_game` to both, anything else to the active team. Runner-to-server frames are forwarded whole and unchanged, capped at 8 MiB | A full match runs 1310 rounds with 1310 turns per team and zero errors; unit tests for each routing rule; a fake server and two fake runners test end to end; an oversized frame closes the connection |
| Guard watchdog thread (`guard.py`, one per team process) | Ends the process with a `BIO-GUARD-VIOLATION` line when one robot's turn or start-up exceeds the wall-clock limit, or the team's resident memory exceeds the limit while one of its robots runs. A thread, not an exception, so bot code cannot catch it | `hang_py` (endless turn) and `hang_init_py` (endless import) forfeit in about 3 s, naming the right team, round and robot; `memhog_py` forfeits at about 555 MiB, 3 of 3 runs |
| Operating-system limits (`resource.setrlimit`) | Address space, CPU seconds, open files, file size (also caps the runner log), core dumps off, and processes plus threads (`RLIMIT_NPROC`, only inside the sandbox's private user namespace, where counting starts at zero) | `allocbomb_py` (one 4-billion-element list) gets `MemoryError`, only that robot dies; the fork loop stops at 508 children against a limit of 512 |
| Sandbox (`sandbox.py`, bubblewrap) | New user, PID, IPC, UTS and network namespaces; all capabilities dropped; killed with the launcher; read-only root; only `/usr`, the interpreter, the venv, the match runner directory and **that team's own bot folder** mounted, read-only; private size-capped `/tmp`; no home directory, no repository, no other participants' bots, and not the opposing team's code | The hostile `escape_py` bot (uses the attribute-walk hole to reach the real `__import__`, `os`, `socket`, `ctypes`) could not read a canary file outside the sandbox, could not reach a TCP listener on the host's loopback (0 hits), had no internet route, could not write to `/usr` or its bot folder, saw 2 processes, saw only `/work/A` (opposing team `/work/B` does not exist) |
| seccomp filter (`seccomp_program`, hand-assembled classic BPF, no library) | Denies `ptrace`, `mount`, `bpf`, `io_uring_*`, `keyctl`, `userfaultfd`, `unshare`, `setns`, `perf_event_open`, module loading, `kexec`, `process_vm_*`, new-mount API calls; `clone3` returns `ENOSYS` so glibc falls back to `clone`, and `clone` with any namespace flag is refused; wrong architecture kills | 46 instructions; in the sandbox `ptrace`, `bpf`, `io_uring_setup` and `unshare(CLONE_NEWUSER)` return `EPERM` while 20 threads and `fork` still work; the hostile bot's `ptrace` is blocked; without the filter the nested `unshare` succeeds |
| cgroup limits (`systemd-run --user --scope`) | Kernel-enforced backstop per team process: `MemoryMax` = 2x the memory limit, no swap, `TasksMax` = task limit + 32. Used automatically when a user systemd manager is available (`--require-cgroup` makes it mandatory, `--no-cgroup` disables it) | Manual check: a 400 MB allocation in a 300 MB scope is killed (exit 137); every sandboxed test match ran with `cgroup: true` |
| Engine link | The sandbox has no network at all. The runner connects over a bind-mounted unix socket; the router talks to the Java server on `127.0.0.1:27185` with `TCP_NODELAY` and `TCP_QUICKACK` (without them the match runs at about 2 rounds/s) | Example match: about 4 s |

**Results** leave each runner as single lines on its stdout (`BIO-GUARD-VIOLATION {json}`, `BIO-GUARD-USAGE {json}`), which the launcher reads from that team's runner log. There is no writable state directory in the sandbox. **The team named inside a record is never trusted**: a bot can print any text, so the launcher takes the team from the process that wrote the record (a forged record blaming the other team is charged to the writer and kept as `claimed_team`; tested with `forge_py`). The launcher classifies each run: `normal`, `bot_violation` (names `loser` and `winner_by_forfeit`; the engine winner is withheld because the engine never finished the game) or `platform_failure` (timeout, runner or server crash without a record, a limit breached while no robot was running). A `platform_failure` never produces a winner. When a runner dies, the launcher stops the Java server about 3 s later instead of waiting for its own timeout.

**Limits profile.** `backend/match_runner/limits.provisional.json` holds one platform-wide profile (every field required, no hidden defaults): `turn_wall_seconds` 1.0, `init_wall_seconds` 2.0, `memory_rss_mb` 512 (per team process), `address_space_mb` 4096, `cpu_seconds` 900, `open_files` 256, `output_bytes` 16 MiB, `max_tasks` 512. **Interim, not benchmark-approved** (CN-005 D1; PRD BIO-NFR-02, DEC-04): generous multiples of what three small bots used (longest turn 19 ms, start-up 1.4 ms, peak RSS 22 MiB, VmPeak 329 MiB, 4 threads, 2.4 s CPU), which is not a representative benchmark. Every match records `usage` (per team: turns, longest turn, total turn time, start-up time, uncaught exceptions; per process: peak RSS, VmPeak, peak threads, CPU) so real numbers can be chosen.

**Behaviour that differs from the official runner (CN-005 D4).** Because each team has its own process, bots no longer share Python module state or the global `random` stream. The example bot calls `random.seed(6147)`: in the official one-process setup both teams' bots drew from one interleaved stream (earlier runs: A wins in round 1290); now each team has an independent stream, the two example bots play identical games and the match ends in round 1310 with the engine's coin flip, whose winner varies from run to run (A in 4 of 6 runs, B in 2 of 6). No seed property was found among the server's `bc.*` settings, so replay hashes of tied games are not reproducible. Games decided by play (not by the coin flip) are not affected by this.

**Failure classification (BIO-205, CN-006; *Verified* by `tests/test_failure_classification.py`).** `launcher.classify` turns the evidence of one match into one of four classifications, and `outcome` maps them to the worker contract: `normal` -> `completed`; `bot_violation` and `bot_crash` -> `bot_failure`; `platform_failure` -> `platform_failure`. Rules, in order:

| # | Evidence | Result |
|---|---|---|
| 1 | The guard of team X recorded a limit breach | `bot_violation`, X loses |
| 2 | A breach was recorded with no bot running (the engine itself grew) | `platform_failure` |
| 3 | The match wall-clock timeout hit | `platform_failure` |
| 4 | The match finished with no server errors | `normal` (whoever closed first) |
| 5 | Unfinished, and a team's runner never connected | `platform_failure` (`runner_start_failure`) |
| 6 | Unfinished, and a team's runner closed the engine connection first (any exit code, including 0, a signal, or a frame over 8 MiB) | `bot_crash`, that team loses, `evidence` = leg, exit status, signal |
| 7 | Unfinished, and the engine server closed first | `platform_failure` (`engine_failure`), no loser |
| 8 | Anything else | `platform_failure` (`unknown`) |

The deciding fact is `router.first_end`, recorded by the host-side `Router`; a bot cannot forge it, whereas a line in the runner's log can be printed by the bot. When a runner dies the Java server crashes within milliseconds and prints a bug-report banner, so server error text alone is **not** used to blame the platform. Tested with real matches: a bot that calls `os._exit(3)`, `os._exit(0)`, segfaults (`faulthandler`), or kills itself with `SIGKILL` loses in either slot, with and without the sandbox; killing the engine JVM mid-match (found by its listening port and `-Dbc.game` argument, never the Gradle daemon) gives `platform_failure` with no loser. A runner that is not seen to connect, an engine-first hang-up and the other rows are covered by unit tests of the decision table. The trade-off and limits (engine-side Python crashes inside a runner are charged to the team; outside kills look the same) are in CN-006.

**Known gaps (do not treat this as finished isolation):**

- **No protection from a kernel or bubblewrap vulnerability.** Unprivileged user namespaces must be enabled on the host; the seccomp list is a denylist, not an allowlist, written for x86_64 only.
- **Memory is per team process, not per robot.** All robots of one team share the team's limit.
- **An uncaught exception in one robot does not end the match** (CN-005 D2): the engine kills that robot and continues (`allocbomb_py`); the guard counts these per team.
- **Retries live one layer up:** the launcher only reports `platform_failure`; `backend/match_orchestrator` retries it (CN-009, `backend/match_orchestrator/README.md`). A runner killed from outside is charged to its team (CN-006).
- **The tie-break seed is not controllable** (above), which also blocks TC-04's "retry with a new random seed". For the same reason the engine's own coin flip (`The winning team won arbitrarily (coin flip).`) is treated as a tie, not a result: `backend/match_orchestrator/tiebreak.py` plays the tie-break maps and makes the platform's own recorded 50/50 draw (CN-010).
- **The router is trusted code on the host.** Server messages are parsed only for the message type and robot id; a malformed server message is forwarded to the active team. Runner frames are validated and rebuilt (CN-007), and since CN-008 also checked for *whose turn it is* (a call only from the current runner, a null only as the answer to a forwarded `spawn_bot`/`destroy_bot`), for a known engine method number (1 to 107), and against a host-side response deadline (a silent runner is charged after `2 x max(turn, start-up limit) + 2 s`). A hostile bot can still send any valid call with any parameters, up to 8 MiB per frame, during its own turn (the server is the engine's own code, part of the trusted base); a call with bad parameters can crash the server, and who is blamed then depends on which side closes first (`docs/SECURITY_REVIEW.md` SR-03/SR-06). Flooding is bounded by the turn time limit.
- The sandbox shows empty parent directory names of the mounted paths (for example `/home/<user>`); it does not show their contents.
- Linux x86_64 only; one match per host (fixed port 27185 on the host side).

### 3.7 Log integrity and structured match logs (BIO-206, CN-007; *Verified* by `tests/test_structured_log.py`)

**Log integrity (a defect found and fixed in this task).** The engine's Java server prints a bot's `log(...)` text after a `[A: #3@2] ` prefix without escaping line breaks. Before CN-007 the launcher parsed the winner, reason and server errors from that console log with unanchored patterns and took the first match, so a bot could print `[server] ... (A) wins (round 2)` or `[server:error] ...` on a line of its own and change its own match's result or force a `platform_failure` (reproduced; the two new tests fail on the old router). Now:

| Layer | What it does |
|---|---|
| `Router` -> `canonical_runner_frame` | Every runner frame is parsed (strict JSON: no `NaN`, no invalid UTF-8, bounded nesting) and rebuilt from the parsed value, so the engine sees exactly what was checked even if Python and Java would read the raw bytes differently. Allowed: `null` or `{method: int, params: list}`; anything else ends that runner's connection. |
| `sanitise_text` | In every string (and key) of a frame, each line break kind (`\n \r \v \f` FS GS RS NEL U+2028 U+2029) becomes a newline plus `  | `; other control characters, including ESC, are dropped. No line after the first of any bot text can start like an engine line. |
| `launcher.parse_result` | Patterns anchored to the start of a line (`^[server] ...`), last match wins; the end-of-match banner must be a whole line. |

**Structured log.** Each `run` writes `match-<stamp>.events.jsonl` next to the replay and returns `structured_log: {path, schema, events, bytes, sha256}`. One JSON object per line, schema 1, built after the match from facts the launcher already holds (`match_log.build_events`):

| Event | Visibility | Content |
|---|---|---|
| `match.start` | all | map, team names and submission references, engine version, Python version, `seed: null` (not controllable), the limits in force and the profile name (`approved: false`), start time |
| `team.usage` | team:X | turns, inits, longest turn and init in ms, total turn time, uncaught exceptions, game-action exceptions |
| `team.output` | team:X | what the team's robots logged through `log(...)` and engine error messages about them: `{round, robot, text}` entries, the first 40 and last 40 (middle omitted and counted), at most 20 lines and 500 characters each, redacted |
| `team.failure` | team:X | only for a bot failure: `limit_exceeded` (kind, measured, limit, unit, round) or `process_ended` |
| `match.result` | all | outcome, classification, winner and loser (side and name), round, a plain reason (engine text for a normal match, platform wording otherwise; never bot-written text), `retryable`, `replay_available` |
| `platform.diagnostics` | staff | classification kind and detail, evidence (which side closed first, exit status, signal), Gradle and runner exits, timeout flag, router counters, sandbox and cgroup flags, per-process usage, timing, replay size and SHA-256, server errors, the engine's own `[server...]` lines |
| `match.end` | all | event count, finish time |

Every event has `schema`, `seq`, `trace_id`, `match_id` (null if none), `attempt`, `event`, `visibility`, `data`, and `ts` only where a time was actually measured (start and end; the other events are derived afterwards, not timed). Identifiers passed with `--trace-id`, `--match-id`, `--attempt`, `--submission-a/b` must match `[A-Za-z0-9._:-]{1,64}`; without `--trace-id` a random one is generated.

`launcher.py logs FILE --role participant --team A|B`, `--role organizer` or `--role admin` prints the part of a log a role may read (`match_log.view`). A participant sees `all` plus their own team; an Organizer `all` plus both teams; an Admin everything including `staff`. This is the engineer's default (CN-007), not an approved rule.

**Redaction (best effort, BIO-NFR-10).** `Redactor` replaces the scaffold, bot, output and repository paths, home directories, e-mail and IP addresses (except `127.0.0.1`), bearer tokens, JWTs, well-known token shapes, `password=`/`token=`-style pairs and long mixed-case/digit tokens, and drops control characters. Guard records come from a runner log that a bot can write to, so only finite numbers and short lowercase identifiers are copied from them into events.

**Not done:** storage and retention of logs (DATA_MODEL `MatchLog` is still a proposal), the API endpoint, a retry loop that would write one log per attempt, and an end-to-end secret scan (the redactor is pattern based). Matches run for the tests: unit 3.12 to 3.15; integration on 3.15 including a normal match, two injection bots and a crashing bot.

## 4. Writing and running bots

### 4.1 Python bot contract (current engine behavior, *Verified* by reading `battlecode26`)

- Location: `src/<team>/bot.py`. The runner loads every `*.py` file in that directory as a module.
- Entry point: a top-level `turn()` function, called once per robot turn. The scaffold example keeps state in module globals (`turn_count`).
- Global objects provided by `from battlecode26 import *`: `rc` (the robot controller) and `log(...)`. Types and enums: `Direction`, `MapLocation`, `MapInfo`, `RobotInfo`, `Message`, `Team`, `UnitType`, `TrapType`, `GameConstants`, `GameActionException`, `GameActionExceptionType`. Helpers: `direction_to`, `distance_squared_to`, `is_adjacent_to`, `is_within_distance_squared`, `bottom_left_distance_squared_to`, `get_all_type_locations`.
- Typical calls used by the example: `rc.can_move_forward()`, `rc.move_forward()`, `rc.can_turn()`, `rc.turn(direction)`, `rc.get_direction()`, `rc.get_location()`, `rc.get_type()`, `rc.set_indicator_string(text)`.
- Imports: only `random`, `math`, `enum`, `battlecode26` (a single-file bot has no modules of its own). Anything else raises `ImportError`; relative imports are rejected. **This is the adopted bot policy (CN-004), stricter than the PRD's "standard library and preinstalled libraries" wording**; the full policy is in `BOT_POLICY.md` and is checked early by `backend/bot_validator/`.
- Errors: the example wraps game calls in `try/except GameActionException` and a generic `except Exception`, logging via `log(...)`. What the runner does with an uncaught exception was not checked; follow the example's pattern.
- Builtins: the sandbox offers a reduced set (section 3.5): for example no `dict()`, `sum`, `min`, `max`, `map`, `super`, `type`, `property`, `print`; use `log(...)` for output.
- Compute budget: the runner has a bytecode counter (default 20000) but charges it only for game API calls (each has a cost); **pure Python computation is not limited** (verified with an infinite loop, section 3.5). The platform's official limits are `[DECIDE]` (DEC-04) and must be wall-clock based.
- Platform submission rule (confirmed requirement): exactly one file named `bot.py`; no ZIP, no extra files. Multi-module bots that work with the raw engine are therefore not allowed on the platform.

For the game rules, units and the complete `rc` API, use the official Battlecode 2026 documentation (`https://play.battlecode.org/bc26/quick_start`, referenced in the scaffold README). This repository does not duplicate it.

### 4.2 Java bots

Removed (CN-002). The Java engine server remains and is not a bot language.

### 4.3 Tests

The scaffold's only test (a Java `1 + 1` placeholder) was removed with the Java bots. Tests now are the launcher's: `backend/.venvs/py3.15/bin/python -m unittest backend.match_runner.tests.test_launcher` (14 unit tests, run on 3.12 to 3.15), `backend.match_runner.tests.test_limits_sandbox` (limits, sandbox, router) and `backend.match_runner.tests.test_failure_classification` (BIO-205; 16 unit tests, 8 real-match tests with `BIO_INTEGRATION=1`), `backend.match_runner.tests.test_structured_log` (BIO-206; frame and text sanitising, parser forgery, redaction, event building and views, plus 4 real matches with `BIO_INTEGRATION=1`), plus real-match integration tests with `BIO_INTEGRATION=1 python3 -m unittest backend.match_runner.tests.test_launcher` (feature bot against `expected_featuretest.txt`, and a hanging bot stopped by the timeout). **Run everything:** `python3 backend/run_tests.py` runs every backend test module on the current Python (751 tests; 48 skipped without `BIO_INTEGRATION`); `python3 backend/run_tests.py --matrix` runs them on each `tested_python` of `versions.lock.json` through `uv`; add `--integration` for real engine games (about 6 minutes per Python, one match at a time because the engine port is fixed); a name prefix (`backend.work_queue`) filters. The exit code is not 0 if a module does not import, no test ran or any version failed. Three tests (`AgainstEngine`, `RunnerEntry`) need the engine package inside the interpreter and run only in the `backend/.venvs/py<version>` environments. Result of 2026-11-25 (CN-025): 751 pass on 3.12, 3.13, 3.14 and 3.15, unit and with real games. The planned test strategy and eight critical cases are in `TEST_PLAN.md`.

## 5. Database (proposed, not implemented)

Full definitions: `DATA_MODEL.md`. Summary for developers:

| Area | Entities | Notes |
|---|---|---|
| Identity and access | `User`, `Role`, `UserRole`, `OrganizerAssignment`, `NotificationPreference` | Email normalized and unique while active; password hash only; multi-role per user is `[DECIDE]` |
| Tournament | `Tournament`, `TournamentApproval`, `TournamentDeadline`, `TournamentSetting`, `TournamentMap`, `TournamentArchive` | Versioned settings; deadline history kept; maps immutable by version (normal tie-break count 1, final 3) |
| Roster and teams | `ImportedRosterEntry`, `RosterImportBatch`, `Team`, `TeamMember`, `InvitationCode`, `InvitationCodeIssue` | Codes stored hashed, single-use; registration locks email, team, member number, role |
| Submissions and execution | `BotSubmission`, `SubmissionValidation`, `ExecutionProfile`, `Round`, `Bracket`, `BracketSlot`, `HouseBot`, `Match`, `MatchAttempt`, `MatchReplay`, `MatchLog` | `file_name == "bot.py"`; content hash and version immutable; one active valid submission per team |
| Notifications, audit, incidents | `Notification`, `NotificationDelivery`, `AuditLog`, `AccountDeletionRequest`, `TeamDeletionEvent`, `SystemIncident` | `AuditLog` append-only, redacted payloads, no raw codes or passwords |

Key constraints and indexes (from `DATA_MODEL.md` §5, §8):

- Unique active normalized user email; unique `(tournament_id, email_normalized)` on roster entries; unique `(team_id, version_number)` on submissions.
- Partial unique index: at most one active valid submission per team and tournament.
- A match references two immutable submission versions, the same map and versions across platform retries, and a new seed on each retry; a bot failure is not retried.
- Result recording and bracket advancement are atomic and idempotent; idempotency keys are unique per actor and operation scope.
- Foreign keys use `RESTRICT` (or explicit archival services) for history; no cascade from user or team deletion to results, brackets or audit.
- Suggested indexes: `Match(tournament_id, round_id, status)`, `MatchAttempt(match_id, attempt_number)`, `Notification(recipient_user_id, read_at, dashboard_created_at)`, `AuditLog(tournament_id, created_at)`, `AuditLog(team_id, created_at)`.

Open schema decisions: multiple roles per account, invitation granularity, team size and captain selection, roster file format and retention, upload size cap and source retention, post-retry-cap state name, house-bot representation, replay artifact shape, account anonymization details, whether logs live in the database or object storage.

## 6. Interfaces

| Interface | Type | Direction | Status |
|---|---|---|---|
| Browser to API | REST/JSON over HTTPS under `/api/v1` | client to server | Proposed (section 7) |
| API to job queue | Queue messages (match, validation, replay purge, notification jobs) | server to worker | Proposed |
| Worker to engine | Process invocation of the Battlecode engine, one match per isolated container | worker to engine | Proposed; local equivalent verified for Java teams only |
| Java engine to Python bot runner | JSON over loopback TCP `127.0.0.1` | engine to bot process | *Verified* by reading `battlecode26/crossplay.py` |
| API/worker to file storage | Private S3-compatible object storage, short-lived authorized access | both | Proposed |
| API to email provider | Provider SDK or SMTP with delivery tracking | server to provider | `[DECIDE]` provider |

### 6.1 Internal match-worker contract (proposed; API contract §8)

Never exposed as a public HTTP endpoint; implemented behind the queue boundary.

| Direction | Fields |
|---|---|
| Job input | `match_id`, `tournament_id`, `map_id` (immutable map version), `engine_version`, `runtime_image_digest`, two immutable `submission_id`/version references, `seed`, resource-limit profile id, `attempt_number`, trace/correlation id |
| Job output | `execution_status` (`completed`, `bot_failure`, `platform_failure`), winner/loser or tie, bot failure reason, engine exit status, resource usage measurements, replay artifact reference, structured logs (format: section 3.7), and the map, seed, runtime and submission versions echoed back |

Rules: never trust a worker-supplied team or submission relationship without checking it against the match record; a bot failure is a game result and a platform failure is a retryable incident; retries keep map and bot versions and change the seed; the retry cap alerts Admin; duplicate delivery must not publish a result or advance a bracket twice.

## 7. REST API (proposed)

Canonical source: `API_CONTRACT.md`. All endpoints sit under `/api/v1` and need server-side checks of role and tournament assignment or team membership.

### 7.1 Conventions

- JSON requests and responses; file uploads are multipart; timestamps are ISO 8601 UTC; ids are opaque.
- Error envelope:

```json
{ "error": { "code": "VALIDATION_ERROR", "message": "The uploaded file must be named bot.py.", "details": {}, "request_id": "req_..." } }
```

- Status codes in use: `400 VALIDATION_ERROR`, `401 UNAUTHENTICATED`, `403 FORBIDDEN`, `404 NOT_FOUND`, `409 STATE_CONFLICT`, `410 EXPIRED`, `413 FILE_TOO_LARGE`, `415 UNSUPPORTED_MEDIA_TYPE`, `422 BOT_VALIDATION_FAILED`, `429 RATE_LIMITED`, `500 INTERNAL_ERROR`, `503 SERVICE_UNAVAILABLE`.
- Return a safe `404` instead of `403` where revealing a private resource's existence would leak information (for example another team's submission).
- Destructive operations require an explicit confirmation payload and a non-empty reason.
- Use idempotency keys for match start, upload finalization, deadline extension and destructive actions; use `expected_version` for optimistic concurrency on settings and bracket state.
- File downloads stream only after authorization; no long-lived public storage URLs.
- Every state-changing operation writes an audit event in the same transaction (or via a durable outbox) and a notification event where required.
- Open: authentication mechanism (session or bearer token), pagination style (cursor or page), upload size cap, roster file format.

### 7.2 Endpoint index

Epic numbers are the PRD epics that deliver each group.

| Method and path | Access | Purpose | Epic |
|---|---|---|---|
| `POST /auth/register` | public with official email and invitation code | Create the account for a valid roster entry; invalid attempts do not consume the code | 04 |
| `POST /auth/verify-email` | public with token | Complete email verification | 04 |
| `POST /auth/login` | public | Authenticate | 04 |
| `POST /auth/logout` | authenticated | End the session | 04 |
| `GET /me` | authenticated | Profile, memberships, notification preferences | 04 |
| `POST /me/deletion-request` | participant | Request account deletion (queued while the team is competing) | 04 |
| `DELETE /me/deletion-request` | requester | Cancel a pending deletion request | 04 |
| `PATCH /me/notification-preferences` | authenticated | Set `email_enabled`; dashboard notifications cannot be disabled | 04 |
| `POST /tournaments` | Admin, Organizer | Create a draft | 06 |
| `GET /tournaments` | authenticated, scoped | List visible tournaments | 06 |
| `GET /tournaments/{id}` | scoped | Tournament detail | 06 |
| `PATCH /tournaments/{id}` | Admin, assigned Organizer | Edit permitted settings (locked after deadline) | 06 |
| `POST /tournaments/{id}/submit-for-approval` | creating Organizer | Move a draft to `pending_approval` | 06 |
| `POST /tournaments/{id}/approve` | Admin | Approve | 06 |
| `POST /tournaments/{id}/reject` | Admin | Reject with a reason | 06 |
| `POST /tournaments/{id}/extend-deadline` | Admin | Extend registration or submission deadline | 06 |
| `POST /tournaments/{id}/emergency-override` | Admin | Change a locked setting with a reason; notifies participants | 06 |
| `POST /tournaments/{id}/archive` | Admin, assigned Organizer | Archive; deletes replay files | 06 |
| `DELETE /tournaments/{id}` | Admin | Permanently delete operational data; audit stays | 06 |
| `POST /tournaments/{id}/roster/import` | Admin, assigned Organizer | Import the official roster | 05 |
| `PATCH /tournaments/{id}/roster/{entry_id}` | Admin, assigned Organizer | Correct an unregistered entry | 05 |
| `POST /tournaments/{id}/invitation-codes` | Admin, assigned Organizer | Issue initial codes | 05 |
| `POST /tournaments/{id}/invitation-codes/{code_id}/revoke` | Admin | Revoke a lost or compromised code | 05 |
| `POST /tournaments/{id}/invitation-codes/{code_id}/replace` | Admin | Issue a replacement code | 05 |
| `GET /teams/{team_id}` | team members, assigned Organizer, Admin | Team profile | 05 |
| `DELETE /teams/{team_id}` | Admin, assigned Organizer | Delete an archived tournament's team | 05 |
| `POST /teams/{team_id}/restore` | Admin | Restore a deleted team | 05 |
| `POST /teams/{team_id}/submissions` | team participant (captain-only is `[DECIDE]`) | Upload a new `bot.py` version (`202`, status `validating`) | 05 |
| `GET /teams/{team_id}/submissions` | team members, assigned Organizer, Admin | Version history | 05 |
| `GET /submissions/{id}/download` | owning team, assigned Organizer, Admin | Download source | 05 |
| `GET /submissions/{id}/validation` | owning team, assigned Organizer, Admin | Validation outcome | 05 |
| `POST /submissions/{id}/activate` | Admin only, optional | Manual activation (automatic activation of the latest valid version is the expected rule) | 05 |
| `POST /tournaments/{id}/bracket/generate` | Admin, assigned Organizer | Generate single-elimination bracket | 03 |
| `POST /tournaments/{id}/rounds/{round_id}/start` | assigned Organizer, Admin | Start the next sequential round | 03 |
| `GET /tournaments/{id}/bracket` | tournament participant or staff | Bracket and progression | 03 |
| `GET /matches/{id}` | tournament participant or staff | Match result, tie-break details, version ids (never source) | 03 |
| `GET /matches/{id}/replay` | tournament participant or staff | Replay while retained; `410` after archive | 03 |
| `GET /matches/{id}/logs` | scoped participant or staff | Redacted execution summary | 03 |
| `GET /notifications` | authenticated | Dashboard feed | 06 |
| `PATCH /notifications/{id}` | recipient | Mark read | 06 |
| `GET /tournaments/{id}/audit-logs` | Admin; assigned Organizer; participant (own scope) | Scoped, redacted, immutable records | 04 |

### 7.3 Example: upload a submission

```http
POST /api/v1/teams/team_123/submissions
Content-Type: multipart/form-data
Idempotency-Key: 8f6c...

file=@bot.py
```

```json
{ "submission_id": "sub_123", "version": 4, "status": "validating" }
```

Errors: `400` malformed, `403` not allowed to upload, `409` deadline closed, `413` too large, `415` wrong type, `422` validation failed. An invalid upload never replaces the active version. (The header name `Idempotency-Key` is illustrative; the contract only requires an idempotency key.)

## 8. Developer workflow

1. **Read** `handoff.md` and the relevant documents before changing anything.
2. **Branch** per task using Jira notation (`BIO-NNN-short-description`, or `BIO-EPIC-0N-short-description` for epic-level work). Never commit directly to `main`.
3. **Change** one concern at a time; keep documents in sync (PRD/SRD first, then dependent docs).
4. **Test** with the real engine. Record exact versions (Python, engine, client, packages, OS, image digest) and never claim compatibility without a test that ran.
5. **Commit, push, open a pull request.** No co-author or generated-by lines.
6. **Close the task:** append an entry to `handoff.md` (Jira ID, files changed, tests run and results, risks, new decisions) and update `CHANGELOG.md`.

### 8.1 Troubleshooting (all *Verified* unless marked)

| Symptom | Cause | Fix |
|---|---|---|
| `RuntimeError: Python 3.12 is required.` | You ran the scaffold's `run.py` (or `python -m battlecode26`) with another Python | Use `backend/match_runner/launcher.py`, which does not need it |
| `The engine must be run using >= Java 21 JDK` | JDK older than 21 | Install JDK 21 or newer |
| `Player is not valid!` from `run.py verify` | `src/<team>/bot.py` missing or lacks `def turn():` | Check the file |
| `No module named battlecode26` when Gradle starts a Python team | `build.gradle` runs `python3` from `PATH`, which is not an environment with the package | Use the launcher (section 3.2) |
| Match ends in round 2000 by coin flip and the server log says `Error while loading player` | The engine server needs an existing class directory even for Python teams | Use the launcher, or pass `-PclassLocationA/B=<empty dir>` |
| `version check failed` from the launcher | Interpreter, package or `engine_version.txt` differs from `versions.lock.json` | Run `setup_env.py <version>` and `launcher.py verify`; change the pins only with a recorded test |
| `loopback port 27185 is already in use` | Another match (or a leftover runner/server) holds the engine's fixed port | Wait, or stop your own leftover process by PID |
| A run hangs and a `runner_entry.py` process stays alive | A bot never returns from `turn()`, or the server died | The launcher's timeout stops it; if you started things by hand, stop your own process by PID and do not kill other Java processes (editors and Gradle daemons use them) |
| Existing replay overwritten | Default replay path is `matches/<teamA>-vs-<teamB>-on-<maps>.bc26` | Pass `-Preplay=<path>` |
| Build prints "NEW BATTLECODE VERSION AVAILABLE" | Published client or engine is newer than the configured version | Informational; update deliberately with `./gradlew update` in its own PR and re-run the baseline |

## 9. Licensing note

The vendored scaffold carries the GNU Affero General Public License v3 (`backend/battlecode26-scaffold/LICENSE`). The repository root has no license file. What this means for distributing or network-serving this project has not been analyzed and is an open owner decision (`PROJECT_PLAN.md` R5). This note is not legal advice.
