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
│   └── battlecode26-scaffold/   Battlecode 2026 scaffold (upstream f69e2ab + local edits)
│       ├── build.gradle  gradle.properties  gradlew  gradlew.bat  gradle/wrapper/
│       ├── engine_version.txt  client_version.txt
│       ├── run.py               Python launcher (requires Python 3.12)
│       ├── src/
│       │   ├── examplefuncsplayer/RobotPlayer.java      Java example bot
│       │   └── examplefuncsplayer_py/bot.py             Python example bot
│       ├── test/examplefuncsplayer/RobotPlayerTest.java placeholder test
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
| Python **3.12 exactly** for `run.py` | `REQUIRED_PYTHON_VERSION = (3, 12)`; any other version raises `Python 3.12 is required.` | *Verified*: system `python3` here is 3.14.10 and was rejected |
| Python 3.13 | Project target; **untried** | `[DECIDE]` patch version (DEC-03) |
| Virtual environment | The scaffold expects the engine's Python package (`battlecode26`) and `RestrictedPython` in the interpreter that runs bots | *Verified*: local `.venv` is CPython 3.12.15 with `battlecode26` 1.2.2 and `RestrictedPython` 8.1 |
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
| `verify` | Run the Java instrumenter's package verification (`battlecode.instrumenter.Verifier`) for a team package |
| `listPlayers` | List packages containing `RobotPlayer.java` or `.scala` |
| `listMaps` | List available `.map26` maps |
| `version` | Print configured engine and client versions |
| `checkNewVersion` | Compare configured versions to the published ones |
| `update` | Overwrite `engine_version.txt` and `client_version.txt` with the latest published versions (network) |
| `installPyLocal` | Install the already-downloaded Python engine package |
| `downloadPyPackage` | Download the Python engine package (via `run.py update`) |
| `unpackClient` | Download and unpack the desktop client into `client/` |
| `zipForSubmit` | Zip all of `src/` into `submission.zip` |

### 3.2 Run a match

*Verified* (Java vs Java, replay written outside the repo so existing replays are untouched):

```bash
cd backend/battlecode26-scaffold
./gradlew runLocal --offline -Preplay=/some/path/java-baseline.bc26
```

Observed result: `examplefuncsplayer (A) wins (round 860)`, reason "The winning team destroyed all of the enemy team's rat kings", about 2 seconds, replay about 61 KB. Without `-Preplay`, the replay goes to `matches/<teamA>-vs-<teamB>-on-<maps>.bc26` (name truncated to 80 characters) and overwrites a file of the same name.

**Python bots: verified on 2026-11-24 only with a manual launch, not with the shipped Gradle command.** The intended command, `./gradlew runLocal -PlanguageA=python -PteamA=examplefuncsplayer_py -PlanguageB=python -PteamB=examplefuncsplayer_py`, does not work as shipped on Linux. Two causes were established by running it and reading the code:

1. **Wrong interpreter.** `build.gradle` starts `python3` from `PATH`. Here that is the system Python 3.14, which has no `battlecode26` package and is rejected by `run.py`, hence `No module named battlecode26` / `Python 3.12 is required`. Putting `.venv/bin` first on `PATH` fixes it, but an already running Gradle daemon keeps the `PATH` it started with (observed: the first retry still failed until `--no-daemon` was used).
2. **Start-up deadlock.** `runPyLocal` calls the runner with `--new-process`. The spawned runner inherits Gradle's output pipe and retries `127.0.0.1:27185` until the Java server accepts, but the Java server task is ordered after `runPyLocal` and Gradle waits for the pipe to close. Result: no output until the timeout. (The Windows branch uses `DETACHED_PROCESS`, which avoids this; the Linux branch does not.)

**Workaround that worked** (Python 3.12 venv, engine 1.2.6, package 1.2.2): start the runner yourself in the background with its output redirected, then run only the server task.

```bash
cd backend/battlecode26-scaffold
.venv/bin/python -m battlecode26 --teamA examplefuncsplayer_py --teamB examplefuncsplayer_py \
    --dirA "$PWD/src" --dirB "$PWD/src" > /path/outside/repo/runner.log 2>&1 < /dev/null &
PATH="$PWD/.venv/bin:$PATH" ./gradlew runJavaLocal --no-daemon --offline \
    -PlanguageA=python -PlanguageB=python -PteamA=examplefuncsplayer_py -PteamB=examplefuncsplayer_py \
    -Preplay=/path/outside/repo/match.bc26
```

The runner exits by itself when the server ends the game. If you abort, stop the runner by its PID.

*Observed result* of one full control match (`examplefuncsplayer_py` against itself on `DefaultSmall`): `examplefuncsplayer_py (A) wins (round 1290)`, reason "The winning team destroyed all of the enemy team's rat kings", Gradle exit 0, 706 seconds, replay about 64 KB, no stray processes afterwards. Caveat: this run used a small wrapper that sets `TCP_NODELAY` and merges the two writes of each message on the Python side (see below); the unpatched runner was only run for partial matches (23 rounds in the first 30 s versus 46 with the patch, including JVM start-up), so the unpatched full-match time and outcome were not measured. The wrapper only changes socket behaviour, but outcome equality was not tested.

**Throughput is low.** About 1.6 to 1.8 rounds per second (a full match needs minutes, against about 2 seconds for Java-vs-Java), with the runner at about 0.3% CPU, so the time is spent waiting, not computing. Each message is sent as a 4-byte length followed by the JSON body in two `sendall` calls and neither the Python client nor the Java `CrossPlay` server sets `TCP_NODELAY` (read from the Python source and `javap` output of the 1.2.6 jar). That is a plausible cause, supported by the roughly 2x gain from the wrapper, but the remaining delay is not explained. This matters for DEC-04 (time limits) and for tournament scheduling: do not size match time budgets from the Java baseline.

Two further cautions: (1) `runLocal` with a Python team depends on `installPyLocal`, which reinstalls the package on every run because it compares package metadata `1.2.2` with `engine_version.txt` `1.2.6`; (2) a hung run can leave a `python -m battlecode26` process behind, so check `ps` and stop only your own process by PID.

### 3.3 Configuration properties (`gradle.properties` plus `-P` overrides)

| Property | Default in file | Meaning |
|---|---|---|
| `teamA`, `teamB` | `examplefuncsplayer` | Team package names under `src/` |
| `languageA`, `languageB` | `java` | `java` or `python` |
| `maps` | `DefaultSmall` | Map name(s) |
| `debug` | `false` | Engine debug methods |
| `outputVerbose` | `true` | Print bot output to the console |
| `showIndicators` | `true` | Include bot indicator strings in replays |
| `validateMaps` | `true` | Validate maps before running |
| `alternateOrder` | `false` | Alternate team order |
| `compatibilityClient` | `false` | Download the Electron client instead of the Tauri one |
| `replay` | (unset) | Replay output path (default `matches/<names>.bc26`) |
| `waitForClient` | `false` | Pause until a client connects |
| `classLocationA/B`, `packageNameA/B` | derived | Where team classes and packages are found |
| `onSaturn`, `gcloudToken`, `forceReinstallPy` | unset | Organizer-internal distribution options of the scaffold |

The Java engine reads these through JVM system properties such as `-Dbc.game.team-a`, `-Dbc.game.maps`, `-Dbc.server.save-file`, `-Dbc.server.mode=headless`, `-Dbc.server.validate-maps`. The server is pointed at a `maps` directory (`-Dbc.server.map-path=maps`; it does not exist locally), and `listMaps` reads `.map26` files from both that directory and the engine jar. The default map `DefaultSmall` ran successfully, so it is available from the jar.

### 3.4 `run.py` tasks (*Verified*: `tasks`, `verify`, `test`; others read, not run)

Run with the Python 3.12 interpreter, from the scaffold root: `.venv/bin/python run.py <task> [options]`.

| Task | Behavior |
|---|---|
| `tasks` | Prints `tasks, test, update, verify, run, install_current_version, zip_submission` |
| `verify --p1 <team>` | Passes if `src/<team>/bot.py` exists and its text contains `def turn():`. *Verified*: passes for `examplefuncsplayer_py`, fails for the Java package `examplefuncsplayer`. **It checks neither syntax nor imports.** |
| `test` | Runs every `*.py` file under `test/`; *Verified*: prints `No tests found.` |
| `update` | Downloads the latest engine Python package to `.temp/` and installs it; writes `engine_version.txt` |
| `install_current_version` | Installs the package for the version in `engine_version.txt` when the installed one differs |
| `run --p1 --p2 [--p1-dir --p2-dir --debug]` | Starts the Python cross-play runner (`from battlecode26 import _main`) |
| `zip_submission` | Zips `src/**/*.py` into `submission.zip` |

## 4. Writing and running bots

### 4.1 Python bot contract (current engine behavior, *Verified* by reading `battlecode26`)

- Location: `src/<team>/bot.py`. The runner loads every `*.py` file in that directory as a module.
- Entry point: a top-level `turn()` function, called once per robot turn. The scaffold example keeps state in module globals (`turn_count`).
- Global objects provided by `from battlecode26 import *`: `rc` (the robot controller) and `log(...)`. Types and enums: `Direction`, `MapLocation`, `MapInfo`, `RobotInfo`, `Message`, `Team`, `UnitType`, `TrapType`, `GameConstants`, `GameActionException`, `GameActionExceptionType`. Helpers: `direction_to`, `distance_squared_to`, `is_adjacent_to`, `is_within_distance_squared`, `bottom_left_distance_squared_to`, `get_all_type_locations`.
- Typical calls used by the example: `rc.can_move_forward()`, `rc.move_forward()`, `rc.can_turn()`, `rc.turn(direction)`, `rc.get_direction()`, `rc.get_location()`, `rc.get_type()`, `rc.set_indicator_string(text)`.
- Imports: a bot may import its own modules plus `random`, `math`, `enum`, `battlecode26`. Anything else raises `ImportError('Module "<name>" does not exist.')`. Relative imports and import cycles are rejected. **This is stricter than the PRD's "standard library and preinstalled libraries" wording; the policy is undecided** (see `PROJECT_PLAN.md` R3).
- Errors: the example wraps game calls in `try/except GameActionException` and a generic `except Exception`, logging via `log(...)`. What the runner does with an uncaught exception was not checked; follow the example's pattern.
- Compute budget: the runner counts bytecode and reports "Ran out of bytecode" when it hits the limit. The default constant is 20000 and is described as updated by the game. The platform's official limit values are `[DECIDE]` (DEC-04).
- Platform submission rule (confirmed requirement): exactly one file named `bot.py`; no ZIP, no extra files. Multi-module bots that work with the raw engine are therefore not allowed on the platform.

For the game rules, units and the complete `rc` API, use the official Battlecode 2026 documentation (`https://play.battlecode.org/bc26/quick_start`, referenced in the scaffold README). This repository does not duplicate it.

### 4.2 Java bot contract (scaffold)

A class `RobotPlayer` in package `<team>` with `public static void run(RobotController rc) throws GameActionException`, containing a loop that ends each turn with `Clock.yield()`. The platform does not accept Java bots; Java is used for the scaffold baseline and engine tests only.

### 4.3 Tests

The only test is `RobotPlayerTest.testSanity` (`assertEquals(2, 1 + 1)`), a placeholder that proves the toolchain compiles and runs, not that any bot works. There are no Python tests. The planned test strategy and eight critical cases are in `TEST_PLAN.md`.

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
| `RuntimeError: Python 3.12 is required.` | `run.py` accepts only Python 3.12; system Python here is 3.14 | Use the project's 3.12 interpreter (for example `.venv/bin/python run.py ...`) |
| `The engine must be run using >= Java 21 JDK` | JDK older than 21 | Install JDK 21 or newer |
| `Player is not valid!` from `run.py verify` | `src/<team>/bot.py` missing or lacks `def turn():` (the Java example package has no `bot.py`) | Verify the Python example (`--p1 examplefuncsplayer_py`) |
| `No module named battlecode26` when Gradle starts a Python team | `build.gradle` runs `python3` from `PATH`, which is not the venv | Put `.venv/bin` first on `PATH` and run Gradle with `--no-daemon` (a running daemon keeps its old `PATH`); see section 3.2 |
| A run hangs and a `python -m battlecode26` process stays alive | Python runner waiting for the engine (cause not established) | Stop your own stray process by PID; do not kill other Java processes (editors and Gradle daemons use them) |
| Existing replay overwritten | Default replay path is `matches/<teamA>-vs-<teamB>-on-<maps>.bc26` | Pass `-Preplay=<path>` |
| Build prints "NEW BATTLECODE VERSION AVAILABLE" | Published client or engine is newer than the configured version | Informational; update deliberately with `./gradlew update` in its own PR and re-run the baseline |

## 9. Licensing note

The vendored scaffold carries the GNU Affero General Public License v3 (`backend/battlecode26-scaffold/LICENSE`). The repository root has no license file. What this means for distributing or network-serving this project has not been analyzed and is an open owner decision (`PROJECT_PLAN.md` R5). This note is not legal advice.
