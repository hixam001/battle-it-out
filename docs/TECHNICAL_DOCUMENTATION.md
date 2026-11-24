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
│   ├── match_runner/            match launcher, pinned versions, env setup, tests (BIO-003/004)
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
| `while True: pass` in `turn()` | **never stops**: the match hangs until the launcher's timeout (the `hang_py` bot; runner killed, port freed) |

These are facts for the bot validator (BIO-201), the sandbox (BIO-203/204) and the limits (DEC-04): the engine gives no protection against file access or a runaway bot, so the platform must enforce host-level isolation and wall-clock limits itself, and the allowed-builtins list is far narrower than the PRD's "standard library".

## 4. Writing and running bots

### 4.1 Python bot contract (current engine behavior, *Verified* by reading `battlecode26`)

- Location: `src/<team>/bot.py`. The runner loads every `*.py` file in that directory as a module.
- Entry point: a top-level `turn()` function, called once per robot turn. The scaffold example keeps state in module globals (`turn_count`).
- Global objects provided by `from battlecode26 import *`: `rc` (the robot controller) and `log(...)`. Types and enums: `Direction`, `MapLocation`, `MapInfo`, `RobotInfo`, `Message`, `Team`, `UnitType`, `TrapType`, `GameConstants`, `GameActionException`, `GameActionExceptionType`. Helpers: `direction_to`, `distance_squared_to`, `is_adjacent_to`, `is_within_distance_squared`, `bottom_left_distance_squared_to`, `get_all_type_locations`.
- Typical calls used by the example: `rc.can_move_forward()`, `rc.move_forward()`, `rc.can_turn()`, `rc.turn(direction)`, `rc.get_direction()`, `rc.get_location()`, `rc.get_type()`, `rc.set_indicator_string(text)`.
- Imports: a bot may import its own modules plus `random`, `math`, `enum`, `battlecode26`. Anything else raises `ImportError('Module "<name>" does not exist.')`. Relative imports and import cycles are rejected. **This is stricter than the PRD's "standard library and preinstalled libraries" wording; the policy is undecided** (see `PROJECT_PLAN.md` R3).
- Errors: the example wraps game calls in `try/except GameActionException` and a generic `except Exception`, logging via `log(...)`. What the runner does with an uncaught exception was not checked; follow the example's pattern.
- Builtins: the sandbox offers a reduced set (section 3.5): for example no `dict()`, `sum`, `min`, `max`, `map`, `super`, `type`, `property`, `print`; use `log(...)` for output.
- Compute budget: the runner has a bytecode counter (default 20000) but charges it only for game API calls (each has a cost); **pure Python computation is not limited** (verified with an infinite loop, section 3.5). The platform's official limits are `[DECIDE]` (DEC-04) and must be wall-clock based.
- Platform submission rule (confirmed requirement): exactly one file named `bot.py`; no ZIP, no extra files. Multi-module bots that work with the raw engine are therefore not allowed on the platform.

For the game rules, units and the complete `rc` API, use the official Battlecode 2026 documentation (`https://play.battlecode.org/bc26/quick_start`, referenced in the scaffold README). This repository does not duplicate it.

### 4.2 Java bots

Removed (CN-002). The Java engine server remains and is not a bot language.

### 4.3 Tests

The scaffold's only test (a Java `1 + 1` placeholder) was removed with the Java bots. Tests now are the launcher's: `backend/.venvs/py3.15/bin/python -m unittest backend.match_runner.tests.test_launcher` (14 unit tests, run on 3.12 to 3.15), plus real-match integration tests with `BIO_INTEGRATION=1 python3 -m unittest backend.match_runner.tests.test_launcher` (feature bot against `expected_featuretest.txt`, and a hanging bot stopped by the timeout). The planned test strategy and eight critical cases are in `TEST_PLAN.md`.

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
| Job output | `execution_status` (`completed`, `bot_failure`, `platform_failure`), winner/loser or tie, bot failure reason, engine exit status, resource usage measurements, replay artifact reference, structured logs, and the map, seed, runtime and submission versions echoed back |

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
