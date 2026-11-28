---
id: battle-it-out-project-memory
type: project
status: active
created: 2026-11-26
updated: 2026-11-28
confidence: high
source: Claude project memory and sessions, repository sources, and GitHub PR status
tags:
  - battle-it-out
  - innofest
  - project-memory
---

# Battle It Out: project memory

Read this and the latest [handoff task log](../handoff.md#8-task-log-append-newest-at-the-bottom)
before starting work. This is a curated continuation note for Codex and other
contributors. Requirements remain in the specifications; implementation status
comes from code, tests, and merged commits. Update this note and the complete
remaining backlog after every task.

## Verified checkpoint and where Claude stopped

- BIO-606 / CN-084 continues replay maintenance when a tournament is archived
  during collection. The same pass completes pending purges.
- BIO-802 / CN-083 verifies queue and match lease recovery after an abrupt
  worker exit and one result and advancement per game after redelivery.
  PR #91 merged into `main` at `8237351` after all three hosted checks passed.
- BIO-804 / CN-082 extends real-engine replay smoke to all four pinned
  Python families, checks the interpreter recorded by the match and fixes
  the replay registration race exposed by its first hosted run (BIO-606).
  PR #90 merged into `main` at `26d61af` after all three hosted checks passed.
- BIO-705 / CN-081 shows the recorded game and tie-break map order on the
  scoped bracket page.
  PR #89 merged into `main` at `1cfdc10` after all four hosted checks passed.
- BIO-304 / CN-080 rechecks pinned map pools at round start and configured
  worker execution. Map drift blocks games until the catalogue is repaired.
  PR #88 merged into `main` at `5547f08` after all three hosted checks passed.
- BIO-803 / CN-079 reconciles restored replay files under completed archive
  purge receipts. A disposable PostgreSQL and service-state restore passed.
  PR #87 merged into `main` at `43a178f` after all three hosted checks passed.
- BIO-804 / CN-078 adds the primary-Python Battlecode engine smoke workflow.
  PR #86 merged into `main` at `3c89849` after all three hosted checks passed.
- BIO-804 / CN-077 adds hosted Django and Chromium Playwright checks.
  PR #85 merged into `main` at `874e567` after all three hosted checks passed.
- BIO-804 / CN-076 adds the Python backend unit matrix on GitHub Actions.
  PR #84 merged into `main` at `0ba1ce6` after all four hosted unit runs passed.
- BIO-804 / CN-075 adds a clean frontend build check on GitHub Actions.
  PR #83 merged into `main` at `f18d7c1` after its hosted build passed.
- BIO-611 / CN-074 expands local lifecycle acceptance for email-off notices,
  verified replay archive and unchanged result payloads.
  PR #82 merged into `main` at `a299868`.
- BIO-610 / CN-073 adds scoped tournament audit views to both staff consoles.
  The production build and all 31 browser tests passed.
  PR #81 merged into `main` at `e75d797`.
- BIO-708 / CN-072 improves visibility and keyboard focus in the shared
  console navigation. The production build and 30 browser tests passed.
  PR #80 merged into `main` at `879a04e`.
- BIO-705 / CN-071 adds the structured match log view for recorded attempts.
  The production build and all 29 browser tests passed.
  PR #79 merged into `main` at `0a1e028`.
- BIO-702 / CN-070 adds `/login` for provisioned accounts and opens the
  dashboard after authentication. The build and 28 browser tests passed.
  PR #78 merged into `main` at `7e9cea2`.
- BIO-702 / CN-069 adds the linked participant account settings page
  with the shared inbox email preference. The build and all 28 browser tests passed.
  PR #77 merged into `main` at `dcd6278`.
- BIO-604 / CN-068 adds Admin Operations triage at `/admin`, with attempt
  and alert state, dead jobs and refresh. The build and 27 browser tests passed.
  PR #76 merged into `main` at `449fa64`.
- BIO-707 / CN-067 adds Admin roster and team management links, including
  audited source downloads. The production build and 27 browser tests passed.
  PR #75 merged into `main` at `28dd7c5`.
- BIO-606 / CN-066 adds the shared staff archive panel and replay purge
  receipts. The production build and all 26 Playwright tests passed.
  PR #74 merged into `main` at `c3971ec`.
- BIO-707 / CN-065 adds Admin tournament listing, draft creation, versioned
  settings, direct approval of Admin drafts and manual registration opening.
  PR #73 merged into `main` at `9f83f3c`.
- BIO-502 / CN-064 adds first invitation issuance to the Admin and
  Organizer consoles. The production build and all 24 Playwright tests
  passed. PR #72 merged into main at `8765fbd`.
- BIO-706 / CN-063 adds the Organizer team directory and audited source
  download, completing the local BIO-706 screens. The production build
  and all 23 Playwright tests passed. PR #70 merged at `77ee8da`.
- BIO-706 / CN-062 adds Organizer map and round controls. The production
  build and all 22 Playwright tests passed. PR #69 merged into main at
  `377940d`.
- BIO-706 / CN-061 adds the Organizer roster screen. The production build
  and all 21 Playwright tests passed. PR #68 merged into main at `8271400`.
- BIO-707 / CN-060 adds Admin invitation controls. The production build
  and all 20 Playwright tests passed. PR #67 merged into main at
  `711c289`.
- BIO-707 / CN-059 adds Admin deadline controls. The production build,
  all 19 Playwright tests and all 147 Django tests passed. Backend unit
  mode had 738 passes and 48 expected skips. PR #66 merged into main at
  `8077df2`.
- BIO-707 / CN-058 adds the global audit screen. The production build
  and all 18 Playwright tests passed. PR #65 merged into main at
  `4c19c20`.
- BIO-607 / CN-057 adds the staff announcement screen. The production
  build and all 17 Playwright tests passed. PR #64 merged into main at
  `300b9d7`.
- BIO-706 / CN-056 adds the assigned Organizer tournament lifecycle screens.
  The production build and all 16 Playwright cases passed. PR #63 merged
  into main at `88594e1`.
- BIO-707 / CN-055 adds the Admin approval queue. All 14 Playwright
  tests and the production build passed. PR #62 merged into main at
  `84c6e13`.
- BIO-705 / CN-054 adds scoped bracket, game results and a native replay
  page. The production build, all 12 Playwright and all 147 Django cases
  passed. PR #61 merged into main at `3158801`.
- BIO-704 / CN-053 delivers the participant team and submissions screens.
  The production build, 10 Playwright tests and 145 Django tests passed.
  The announcement API in PR #60 merged into main at `9255e2a`.
- BIO-607 / CN-052 adds staff announcement publishing to the verified roster.
  The dashboard entries, optional email queue, author audit and retry receipt
   commit together. The staff screen followed in CN-057. Other notice
   sources and production delivery remain open. All 145 Django tests and
   101 notification tests passed for CN-052.
- The owner approved PRs #58 and #59. The reconciled branch preserves
  CN-050 and CN-051 and the full 91-row coverage matrix. Queue and replay
  incidents join the Admin audit feed, and `/api/v1/ready/` probes PostgreSQL.
  All 140 Django tests passed on the reconciled branch.
- BIO-601 / CN-047 implements local HTTP tournament lifecycle with current
  staff scope, explicit Organizer creator assignment, version-checked edits
  and approval transitions, and manual registration opening. Approval notices
  and staff UI remain open. The branch keeps 44 of the previously tracked 45
  Jira items open.
- PRs #55–57 merged to main at `4413b90`. Their combined Python changes passed
  all 137 Django tests. The merge preserved CN-047–049, all 91 coverage rows
  and the three task logs.
- On 2026-11-27, PRs #44–54 landed individually on main. The latest
  handoff records the combined verification and 45 remaining Jira items.
- On 2026-11-26, PRs #39–43 integrate the participant
  dashboard and inbox, scoped replay downloads, operator runbook, bracket and
  game reads, and confirmed tournament archive. The owner approved merging all
  five to `main`. See CN-031–035 and the handoff for implementation and checks.
  The owner
  activated all five deferred groups, selected Django/DRF + PostgreSQL and
  React/TypeScript, chose private tournament live viewing, and chose Python
  bundles/curated dependencies before other language compatibility work.
- Implemented locally: React landing/feature console; Django session/CSRF and
  current roster/explicit Organizer scope; real upload/history/download;
  native Python multi-file bundles and pinned helper dependency; private numeric
  live boards through a transport-only engine adapter; version/map/round/failure/
  timing analytics and CSV; PostgreSQL transactional disputes and append-only
  audit/history; read-only Admin operations. No production hosting or complete
  core API/JSON-store migration is claimed. Other languages remain follow-up.
- CN-029 adds shared Django/DRF JSON errors, server-generated request IDs,
  no-store API responses and public GET/HEAD process liveness. Framework and
  application refusals share codes/envelopes; hidden-resource and server-error
  wording is redacted. This is a BIO-404 slice, not complete core API acceptance.
- CN-030 adds the linked participant's notification feed, read/unread and
  email-preference API using the existing service notification store. Explicit
  roster links avoid numeric Django/legacy-recipient ID collisions; staff and
  unlinked recipient provisioning remain open. Offset pagination is interim,
  setters are idempotent, and dashboard notices survive email-off/outage tests.
  Notifications remain JSON-backed. Providers and full BIO-607 stay open.
- CN-031 adds the React `/dashboard` (tournament status, both deadlines and
  recent notices) and `/notifications` (linked participant feed, offset pages,
  read/unread and email preference). Browser coverage uses real sessions and a
  reproducible disposable database/data fixture.
- CN-032–035 add native replay downloads, the interim operations runbook,
  bracket/game history reads and confirmed archive with retryable vault purge.
  Browser replay playback, full results screens and production recovery remain open.
- CN-039 completes BIO-510 for the approved catalogue. Each exact release has
  a recorded SHA-256. Publishing and uploading verify the source, and stored
  bundles keep their original hashes and release pins. The only published
  release is biohelpers 1.0.0.
- CN-040 completes the local BIO-504 upload contract. It verifies the scoped
  captain, accepts exactly one multipart file and passes the current official
  deadline to the shared store/queue flow. Static rejections return actionable
  findings and never change the active bot.
- CN-041 completes BIO-602 for the local Admin API. Deadline extension and
  locked-setting override commit an audit and a notice for the affected roster
  accounts. Maintenance retries pending notices. The scheduler uses the
  current deadline under the tournament store lock before pinning.
- CN-042 completes the BIO-610 read APIs for scoped tournament audit and
  Admin global audit over existing event stores. Verified participants see
  their teams' audit and public tournament events. Admins can filter
  retained deletion audit by tournament ID.
- CN-043 completes the local BIO-509 bundle export. Stable ZIP metadata and
  optional dependency declarations allow a 32-file bundle to be uploaded
  again with its original hash when it has no dependencies.
- CN-044 completes the BIO-501 roster API. Admins and assigned Organizers
  can import bounded CSV/JSON, correct unclaimed entries with a version
  check, and retrieve the roster and exclusion report.
- CN-045 completes BIO-503 team reads. The private roster profile exposes
  verified member slots and captain with current tournament and team scope.
  CN-020 still governs the interim team size and registered-name lock.
- CN-046 completes the BIO-605 match-log API alongside native replay
  downloads. The HTTP view verifies the recorded attempt's structured log
  and returns the CN-007 role projection with allowlisted diagnostic fields.
- On 2026-11-26 the checkout initially had clean `main` at `839cda7` (PR #31),
  while Claude's last session and newest memory described CN-025 / PR #32.
  GitHub confirmed [PR #32](https://github.com/hixam001/battle-it-out/pull/32)
  merged on 2026-11-25 at 09:40:40 Asia/Karachi. Fetched `origin/main` is
  `7322441`, containing Claude's last implementation commit `8c32719`.
  GitHub had no open PRs at the intake check; this memory task has its own branch.
- Claude's last task was **BIO-102**, branch `BIO-102-python-313-315-runs`:
  whole-backend Python verification, `backend/run_tests.py`, and a real
  protocol-violation classification race fix (CN-025).
- The race: a hostile bot sent an out-of-turn frame; the router rejected it,
  but the engine had already logged a result, so classification could accept
  the hostile bot's win. `_router_protocol_violation` / `_runner_fault` now
  charge the sender even after a logged result. Guard limit and match timeout
  retain precedence; an ordinary runner disconnect does not override a result.
- Historical evidence in CN-025: **751 tests** on each of Python 3.12.15,
  3.13.18, 3.14.10, 3.15.2, in unit and real-game modes. The race regression
  ran 20 times each on 3.13 and 3.15, totaling 120 real matches. Unit mode
  skips integration cases; three engine-dependent tests need the project venv.
  These are Claude's recorded results, not a new four-version run by Codex.
- Coverage currently records **26 DONE / 55 PARTIAL / 10 TODO / 0 DEFERRED**
  across **91** requirements. DONE denotes the documented library/tool scope,
  not owner acceptance or an independent security review. Counts and row-level
  gaps live in [REQUIREMENTS_COVERAGE.md](REQUIREMENTS_COVERAGE.md).
- The platform now has a tested **Django/DRF/PostgreSQL feature API and
  React website**, plus the existing execution libraries/JSON stores and service
  commands. No production service/website is deployed. Full core registration,
  account recovery, tournament-management screens and legacy-store migration
  remain open. The local tournament lifecycle API is in CN-047.

## Product and owner agreements

INNOFEST Battle It Out runs participant bots in the **existing Battlecode 2026
engine**. Each submission has UTF-8 entry `bot.py` with top-level `turn()` and
no arguments. The owner now also permits bounded flat Python ZIP bundles with
curated exact-version source dependencies (CN-028); legacy one-file uploads keep
their semantics. No participant package installation, arbitrary custom runtime
or Java bot language is enabled. Additional languages follow compatibility work.
Java remains the existing engine server and its optional private event transport;
no replacement simulation is built.

- Delivery order: execution foundation and automation (epics 00–03), backend
  (04), registration/submissions (05), operations (06), website (07), QA/pilot
  and launch (08). CN-028's explicit owner activation authorizes the new local
  website/feature work while unresolved execution gates remain open; it does not
  count those gates as passed or authorize a production launch.
- Owner/contributor: Hisham Ahmed. A new task gets a Jira-named branch, commit,
  push, and PR to **main**. No co-author/generated-by lines. Do not merge unless
  instructed. Verify the base: PRs #11–#13 once merged into parent branches;
  PR #14 repaired their absence from main.
- HTTPS pushes here need the existing GitHub CLI credential helper; plain
  `git push` cannot prompt for credentials. Use per-command configuration:
  `git -c credential.helper= -c 'credential.helper=!gh auth git-credential' push ...`.
  Preserve global Git configuration and never copy credential values into memory.
- Before work, read handoff and memory; after work, update both and retain the
  **whole unimplemented backlog**, not only the latest task's caveats. Report
  Jira ID, changed files, actual tests/results, risks, and decisions.
- Epics are `BIO-EPIC-00..08`; task keys are `BIO-NNN` with epic-based hundreds;
  requirements are `BIO-REQ-01..23`, `SRD-nnn`, and `BIO-NFR-01..12`. Do not reuse
  a key. [JIRA_BREAKDOWN.md](JIRA_BREAKDOWN.md) proposes 52 later tasks
  `BIO-401..410`, `501..510`, `601..613`, `701..711`, `801..808` (CN-028
  adds bundle/dependency/dispute/operations/live/analytics work). No real tracker
  issues were created; reconcile real keys if assigned later.
- Keep confirmed rules, proposed stack choices, delegated interim defaults,
  and unresolved `[DECIDE]` items distinct. Earlier delegation authorized
  reversible engineering choices recorded as change notices, not treating
  every open product decision as approved.
- Agent/skill files are local and ignored. `PRODUCT.md` is shared product
  context; visual direction belongs in a future `DESIGN.md`. Installed
  security-audit guidance is relevant to security work; impeccable is for
  later UI work. Intake did not run a new security audit or design workflow.
- Anything the requirements need that Battlecode does not provide is ours to
  develop. Never equate engine capabilities with a complete competition platform.

## Architecture and working code

The scaffold was vendored from upstream commit `f69e2ab872a0061c9d4a684aa1dd798a0829da85`
into `backend/battlecode26-scaffold/`; there is no nested Git repository. Upstream
updates are manual. Our sibling Python packages use standard-library local
stores with `flock`, atomic replacement, file/directory fsync, and failure on
corruption. An exception in `JsonFileStore.transaction()` discards the write;
raise a refusal after the transaction when its audit/limiter write must survive.

| Component | What exists | Main references |
|---|---|---|
| `match_runner` | Launcher, pinned venvs, engine compatibility entrypoint, per-team guard, bubblewrap sandboxes, host router, seccomp, optional cgroups, failure classification and structured role-filtered logs | `launcher.py`, `runner_entry.py`, `guard.py`, `sandbox.py`, `match_log.py`; CN-001/002/005–008/025 |
| `bot_validator` | Engine-derived import/builtin policy, bounded hostile-file handling, actionable static errors/warnings, policy drift check | `validator.py`, `policy.json`, `generate_policy.py`; CN-004 |
| `submission_check` | Exact checked bytes play both sides against a pinned reference bot; valid/rejected/inconclusive verdict, hash-bound activation | `trial.py`; CN-013 |
| `submission_registry` | Immutable numbered versions, claimed checks, latest-valid activation, history/download with role checks, deadline lock, write-once tournament pins and re-hashing | `registry.py`; CN-016 |
| `match_orchestrator` | Retry/incident/exactly-once results, series, bracket/byes/sequential rounds, immutable engine-map pools, replay vault/access/archive purge | `orchestrator.py`, `tiebreak.py`, `bracket.py`, `maps.py`, `replays.py`; CN-009–012/014/015 |
| `work_queue` | Durable idempotent jobs, leases/heartbeat/takeover, backoff/dead/revive, check/round handlers and separate worker CLI | `jobs.py`, `worker.py`, `handlers.py`, `service.py`; CN-017/023 |
| `tournament_flow` | Upload→queue check, recover missed check jobs, pin→draw, verify pinned files→start/queue round, replay/check housekeeping | `flow.py`; CN-018 |
| `tournaments` | Tournament state/approval, independent deadlines, extensions/overrides, archive/delete record, deadline tick | `tournaments.py`, `scheduler.py`; CN-019/021/023 |
| `registration` | Official CSV/JSON roster, invitation issue/revoke/replace, claim/confirm, limiter, membership-derived participant Actor and registered teams | `registration.py`; CN-020/021 |
| `notifications` | Mandatory dashboard feed, recipient-only reads, email preference/outbox/leases/retry, event adapters and worker/timer hooks | `notifications.py`, `sources.py`; CN-022/023 |
| `services` | Configured notification-enabled worker, roster-aware maintenance with vault/live cleanup, separate email/alert processes through optional adapters; locks, signals, status and systemd template | `runner.py`; CN-027/028 |
| `submission_bundle` | Bounded flat Python ZIPs, native local-module checks, aggregate digests and reviewed exact-release biohelpers source; exact trials/activation/pins/export | `bundle.py`; CN-028/039 |
| `live_view` | Transport-only NetServer adapter, unchanged engine/schema, numeric board snapshots with no raw listener; private HTTP polling and archive cleanup | `transport.py`, `transport/battlecode/server/NetServer.java`; CN-028 |
| `webapp` / `frontend` | Django/DRF/PostgreSQL feature sessions/scope/API, transactional disputes/audit, analytics and Admin reader; React public landing/feature console | Package READMEs, `DESIGN.md`; CN-028 |

The safe application path is: roster claim and verification → membership-derived
Actor → `tournament_flow.upload` → queued two-sided trial → latest-valid version
→ `scheduler.tick(registration=..., notifications=...)` after the submission
deadline → preview playable teams, pin and draw from a verified map pool →
Organizer calls `tournament_flow.start_round` → re-hash pins and queue → worker
plays sequential matches → results/notifications/replays → archive and purge.
Pass the stored deadline from `tournaments.deadline`; never take it from a client.
`tick` never starts rounds. Omitting `registration=` falls back to teams that
uploaded, so production wiring must supply registration. The legacy worker needs
`--notify`; the service worker always enables hooks, and service maintenance
always supplies registration, notifications and the vault. No production
services are deployed.

Service entry point: `backend/.venvs/py3.15/bin/python -m backend.services.runner
--config /absolute/path/services.json ROLE [--once]`, where ROLE is `worker`,
`maintenance`, `emails`, `alerts` or `status`. See [service operations](../backend/services/README.md)
for the exact command, configuration and systemd template. Each role has a
separate process lock; long matches/provider waits do not delay the timer.
`adapter_factory: null` leaves email/alerts pending, without consuming attempts
or acknowledging incidents. Optional trusted adapters supply send/address lookup
and Admin alert handoff. Delivery is at least once; adapters must deduplicate by
notification/incident ID. No provider credentials belong in repository config.
The shared vault paths are `replays/` and `replays.json`; use the same vault for
archive. `email-alerts.json` records successful failed-email alert handoffs.

## Rules and non-obvious lessons to preserve

- Bot crash/time/limit/protocol failure means forfeit, with no rematch. Platform
  failure retries the same map and exact bot versions. Current default is
  **10 total attempts**, then paused + incident + alert callback (interim).
  A controllable new engine seed is absent: match seeds are null and TC-04's
  new-seed condition is **not met**.
- A game decided by the engine's unseeded coin flip counts as tied for our
  series. Normal tie: one map; final tie: all three predefined maps, majority
  of map wins; still tied: one stored `secrets` coin flip, never redrawn.
  Winners advance once. House bots are deliberately refused until DEC-06.
- Only the highest valid version becomes active. An invalid or inconclusive
  replacement, or a late older verdict, cannot displace a newer valid one.
  At/after deadline, upload stores nothing. Pending trials delay drawing.
  A team without an active bot is excluded and listed (CN-018 D4, interim).
  Check two playable teams **before** making write-once pins (CN-019 repair).
- Participant source is private; team members, assigned Organizer, and Admin
  may read, with staff reads recorded. Only the captain uploads under the
  current default; staff cannot modify/activate through the registry.
  Library Actor parameters are trusted inputs, not authentication.
- Invitation failures consume nothing. Successful claims lock roster identity;
  only verified memberships count. Codes expire against the live deadline,
  so extension preserves unused codes. Only Admin revokes/replaces codes.
- Archive deletes replay binaries for every role while keeping match/bracket
  history. Unauthorized replay access is 404; an authorized archived replay is
  410. Verify deletion on disk; an API-like Gone result alone proves nothing.
  Preserve the user's existing `scaffold/matches/*.bc26` files during testing.
- Dashboard notifications persist when email is off. Event creation/delivery
  must be repeatable. A failed draw notification leaves the tournament open
  for the next tick; a failed result notification must not replay a game.
- The engine's reduced Python builtins/imports are not host isolation. Bots
  can use `open` and attribute walks; pure Python loops evade engine game-call
  accounting. Guard plus host router deadlines and OS isolation are essential.
  Never trust bot-writable text for winners, team blame, or platform faults.
  CN-007 canonicalizes frames and neutralizes multiline log forgery; CN-008
  enforces turns and host response timeouts; CN-025 closes the result race.
- For changes to timing-sensitive router/classification code, repeat real-game
  regressions 20+ times on at least two Pythons. Equal-length same-second
  mutation edits can reuse stale `.pyc`; invalidate the affected cache before
  judging a surviving mutation. A passing sample is not an independent audit.

## Runtime and verification

`backend/match_runner/versions.lock.json` pins primary Python **3.15**, tested
minors **3.12–3.15**, engine **1.2.6**, RestrictedPython **8.1**, flatbuffers
**24.3.25**, artifact SHA-256, and engine port **27185**. The official engine
1.2.6 Python artifact contains package metadata **1.2.2**; this is not drift.
The engine supports Python 3.12 officially; newer versions use our opcode-table
import workaround and direct runner entrypoint. Observed support is Linux
x86_64 only. Installed venvs were confirmed at the four patch versions above
on 2026-11-26; this does not assert that they are today's upstream releases.

JDK 21+, `uv`, bubblewrap, and unprivileged user namespaces are needed for the
documented match path; cgroups are used when available. TCP_NODELAY/QUICKACK
removed the historical 12–23 minute socket stalls; reference matches were
recorded around three seconds. The engine still uses one fixed port, so trial
and tournament matches share a host lock. Stock `run.py` insists on 3.12 and
the Gradle Python launch can deadlock; use the project launcher.
Current provisional limits live in `backend/match_runner/limits.provisional.json`;
do not replace them or describe them as benchmark-approved without evidence.

```bash
python3 backend/match_runner/launcher.py verify
backend/.venvs/py3.15/bin/python backend/run_tests.py
python3 backend/run_tests.py --matrix
python3 backend/run_tests.py --matrix --integration
backend/.venvs/py3.15/bin/python backend/run_tests.py backend.work_queue
```

`run_tests.py` discovers `backend/*/tests/test_*.py`; plain discovery from the
non-package `backend/` is unsuitable. Matrix mode finds interpreters through
`uv`; engine-dependent tests need matching project venvs to avoid skips.
Real matches must run sequentially. Keep test artifacts in temporary paths.

Codex intake verification on 2026-11-26: launcher `verify` passed; on project
Python 3.15.2, **751 tests discovered, 706 passed, 45 skipped**, in 10.853 seconds.
The initial restricted run hit denied socket creation and bubblewrap networking;
the successful rerun used the same command outside Codex's restricted sandbox.
Those environment failures were not product regressions. The real-game
four-version matrix was not repeated for this documentation/memory task.

BIO-409 verification on 2026-11-26: 18 new service tests, 17 unit cases passing
on Python 3.12.15, 3.13.18, 3.14.10 and 3.15.2; all 18 pass with the real-engine
subprocess lifecycle on project Python 3.15.2 (37.336 seconds). Full backend
unit mode: **769 discovered, 723 passed, 46 skipped**. A temporary local-path
copy of the systemd template passes `systemd-analyze verify`; no unit was
installed or started. Restricted uv discovery and systemd verification needed
an unrestricted rerun. Real games/full backend checks ran outside the restricted
sandbox. No real email/Admin provider, production restart drill or new
four-version whole-backend integration matrix was run. Test state/replays stayed
in temporary directories; existing user replays were preserved.

## Complete remaining backlog

This list reconciles Claude's `project-unimplemented-backlog.md` after CN-025
with current code and the coverage matrix; nothing here is closed by intake.

1. **Backend foundation (epic 04):** full schema/migrations and replacement
   of legacy JSON stores; pagination/global idempotency/concurrency, remaining
   core routes and dependency readiness/production health monitoring; public
   invitation-linked account registration, verification
   email, password recovery and account lifecycle; global user/role/assignment
   API and role-composition/revision/last-Admin policy; unified permanent audit
   and production private file delivery. Django/DRF, PostgreSQL and React/TS are
   approved; hosting/email/object storage and other production choices are not.
   The feature session/scope adapter, operator roster linking, explicit Organizer
   assignments and feature audit tables now exist. CN-029 supplies shared HTTP
   errors/request IDs and process liveness. CN-026's full administration
   proposal remains open. CN-051 adds a PostgreSQL readiness probe with
   verified unavailable/recovery behavior. Worker and deployment monitoring
   remain open. Legacy creator fallback remains outside these scoped
   feature routes and must be replaced before the full role API is implemented.
   CN-042 reads current-role scoped audit across the existing stores. Permanent
   migration remains open. CN-048 and CN-050 add official series history and
   Admin-only match, queue and replay incidents to the existing feeds. Retention
   after full purge and recovery evidence remain open.
2. **Service operation:** deploy/supervise the CN-027/028 worker, maintenance,
   email, alert and web processes; approve/implement real email/Admin adapters;
   target-host restart/outage drills; pinned worker/container image and runtime
   digest; secure production database/configuration/TLS. The systemd template is
   validated syntax, not deployed supervision. One-host/fixed-port assumptions,
   the nonrenewed 2400-second match-attempt lease, resume authority and final
   retry-cap policy remain. Live adapter compilation needs the pinned JAR/JDK;
   operational failed-email alert receipt retention still needs policy.
   CN-083 exercises replacement across both expired leases with fixture games.
3. **Execution gates:** realistic target-hardware limits benchmark (DEC-04),
   independent sandbox/security review, SR-06 Java-exception classification and
   SR-03 parameter-type residual, engine seed control or accepted TC-04 waiver,
   house-bot algorithm (DEC-06), qualification-cutoff draw/audit (DEC-14), and
   complete TC-05 including these scenarios. The round-start route and
   configured worker re-verify pinned map pools (CN-080). Custom-map safety,
   suitability and production persistence remain.
   Other OSes, 3.16/free-threaded builds and wider real-engine CI remain open. New
   native bundle/live tests do not close any of these execution gates.
4. **Registration/submissions:** public claim and verification endpoints and
   invitation delivery; remaining registration API contracts; locked-entry
   Admin exception; team size/name/captain policy, source retention/deletion,
   approved upload/version/limiter caps and manual-activation decision. HTTP
   upload/history/source/bundle delivery and queued checks now exist and use the
   official stored deadline/current roster Actor. CN-044 adds scoped staff
   roster reads, import, correction and exclusions. CN-061 adds the Organizer
   roster screen. CN-045 adds team profiles.
   CN-049 adds staff invitation code metadata and issue/revoke/replace endpoints.
   CN-060 adds Admin console listing, revocation and replacement. CN-064
   adds first issuance for selected eligible roster entries.
   Plaintext codes appear only in successful issuance or replacement responses.
   BIO-504 defines multipart,
   size and actionable static-error responses. Interim caps are 256 KiB and
   500 versions/team; the 32-file bundle ceiling is verified on export and
   re-upload (BIO-509). Native flat modules and
   curated biohelpers 1.0.0 are supported with exact release/digest verification
   (BIO-510). More packages require source and module collision review and pins,
   additional languages follow compatibility work, and arbitrary participant
   installs/custom runtimes remain unapproved.
5. **Tournament operations and deletion:** approval and rejection notices,
   management screens and cross-store deletion; raw engine point display
   and paused-job mutation controls; queued/
   cancelable account deletion, historical-roster removal without changed
   results, captain transfer/no successor (DEC-07), team delete/restore after
   archive, permanent tournament deletion across every legacy/new package with
   audit retained. Feature match disputes now support private comments/staff
   review/version/idempotency and immutable history; appeals/reopening/outcome
   correction policy and automatic notices remain. The Admin operations reader
   includes attempt and alert details and dead jobs (CN-068). Recovery
   action controls await their policy. CN-034 delivers
   current-scope bracket and game result reads, including archived history. CN-035 adds confirmed archive for current
   Admins and assigned Organizers. CN-054 adds bracket, game details and
   recorded tie resolution in the console. CN-081 shows the stored main and
   tie-break map lists on the scoped bracket page. CN-038 delivers staff map-pool selection,
   bracket draw and sequential round-start actions. CN-047 adds draft creation,
   detail, edit, submit, approve, reject and open registration over HTTP.
   CN-055 adds the Admin approval queue. CN-056 adds the Organizer list,
   draft creation/edit, approval workflow and manual registration opening.
   CN-058 adds the paginated global audit screen for Admins. CN-073 adds
   the tournament audit screen for Admins and assigned Organizers. CN-059 adds
   the Admin extension and emergency override forms with notice receipts.
   CN-062 adds the Organizer map selection, draw and round-start console.
   CN-065 adds Admin tournament listing, draft creation, settings and
   registration opening. CN-066 adds confirmed staff archive, vault purge
   receipts and a link to retained results. CN-067 adds Admin roster import
   and team review with audited source downloads. CN-074 verifies that
   archived replay URLs return `410` and official results stay identical.
6. **Notifications:** staff/unlinked recipient provisioning, PostgreSQL
   store migration, real provider and deployment; Organizer approval/rejection
   and dispute notices; mandatory security
   email policy, owner wording/retry review, expiry alerts and real outage drill.
   Check/round/draw adapters and failed-email alert retry hooks already exist.
   CN-030 supplies linked-participant feed/read/preferences HTTP endpoints with
   current explicit links and the shared service store. CN-031 implements the
   linked-participant inbox and deadline/notice dashboard. CN-041 delivers
   extension and override notices with affected accounts counted. CN-052 adds
   scoped announcement publishing to the verified roster. CN-057 adds
   staff authoring and receipt counts in the console. Staff inboxes and a
   final pagination contract remain open. CN-069 adds the linked participant
   account settings route for the same email preference.
7. **Replays/logs/privacy:** object storage,
   short-lived URLs, full browser replay player (DEC-10), deployed purge schedule,
   backups/restore, indicator-text exposure review, durable log retention and
   complete end-to-end privacy verification. Private live numeric boards now
   omit arbitrary text, check current scope per poll and are denied/purged after
   archive. Full viewer overlays/traps/animations and production reconnect/load
   evidence remain. CN-032 adds current-scope native replay downloads from the
   private vault. CN-046 exposes verified role-scoped structured attempt logs,
   and CN-071 adds the match log screen with attempt selection.
   CN-054 adds the replay availability and download screen.
   CN-079 covers stale archived files in a disposable restore. Target-host
   backup retention and recovery objectives remain open.
   CN-084 covers continued maintenance through a concurrent archive.
   Production retention of worker-side artifacts, raw native
   indicator text review and browser playback remain open.
8. **Website and launch:** remaining registration/account lifecycle,
   incident controls, browser replay playback and remaining
   Admin mutation screens. Public landing and the private
   live/analytics/submission/dispute/operations console now exist. CN-053 adds
   direct team and submission routes, bracket standing and validation details.
   CN-063 adds the equivalent assigned Organizer team and source view.
   CN-070 adds the public sign-in address for provisioned accounts.
   CN-072 adds current-section visibility and keyboard focus coverage.
   Branding,
   usability, formal accessibility/nonvisual play-by-play and full FLOW-01–08
   acceptance remain; production capacity/outage/concurrency/multi-host tests,
   target-host backups/recovery, deployment/TLS, wider real-engine CI,
   runbook adoption/sign-off, pilot and go-live approval remain open. CN-033
   supplies an interim runbook and console guide with disposable restore and
   web signing-key rehearsal. CN-075–077 add CI for the frontend build,
   backend unit matrix, Django and browser tests. CN-078/082 add real-engine
   replay smoke on all locked Python families. No release dates before the
   benchmark.
9. **Owner/legal and follow-up scope:** written Battlecode Java-engine license
   clarification, copyright holder, participant terms and network source offer;
   reconcile proposed Jira numbering/create real issues; decide client pin
   update separately. All five former deferred requirement groups are active
   PARTIAL work. Additional languages explicitly follow engine compatibility;
   further dependencies, custom runtime policy, richer analytics and dispute
   outcome/appeal policies need separate work/decisions. Hosting is not approved.

## Decision register and next work

The owner selected **React/TypeScript + Django/DRF + PostgreSQL** for the
activated features (CN-028). DEC-11 / BIO-401 is **partially decided**: hosting,
email, object storage, replacement of legacy persistence and remaining production
choices are open; Celery/Redis/S3 were not silently approved. Native Django
sessions and scoped operator provisioning are reversible initial implementation
choices, not final global role/recovery policy.

BIO-REQ-19–23 are all active PARTIAL requirements. The first language expansion
is native flat Python bundles and pinned curated source; other languages come
after compatibility work. DEC-09 is resolved for **private** tournament viewing,
not public spectators. The owner request authorizes this local web work while
execution gates remain open. Next work is the retained execution gates, complete
core backend/database/account flows, remaining screens and production decisions.
Account deletion still needs DEC-07; full BIO-406 needs its unreviewed role/
composition/revision/provisioning policy choices. BIO-409 production deployment,
real providers/channels and image digest remain open.

CN-026 proposes Admin-only global user/role/access administration, a scoped
assignment list for Organizers, current authorization on requests/idempotent
responses and mutation commit, separate user/tournament access revisions,
atomic access/audit writes, and concurrent last-active-Admin protection.
Organizer creation would record an explicit assignment; revocation would
remove creator access and role restoration would not revive old assignments.
These are **proposals for review**, not newly approved requirements or
running defaults. Current `tournaments._manages` still grants creator access;
clearing an Actor's assignment scope alone cannot implement revocation.

BIO-406 documentation verification on 2026-11-26: JSON examples, local links,
unique method/path pairs (seven new routes), 14 unique planned TC-07 cases,
all 91 unchanged requirement statuses, preserved nine-category backlog,
whitespace and added-line credential scan. Backend tests and real games were
not rerun for this docs-only change. No HTTP permission result is claimed.

| Decision | Current position |
|---|---|
| DEC-01, DEC-02 | Per-participant codes and captain-only uploads implemented as defaults; not silently promoted to final owner approval |
| DEC-03 | Pinned/tested versions above; owner confirmation of production patch/OS matrix and fallback remains |
| DEC-04 | Global limits provisional, not benchmark-approved; trial map/count and upload cap also need confirmation |
| DEC-05 | 10 total attempts default; interpretation and resume policy remain interim |
| DEC-06, DEC-14 | House bots and qualification draw unbuilt pending algorithms/inputs/audit |
| DEC-07 | Captain deletion with no successor unresolved |
| DEC-08 | Separate config-freeze deadline undecided |
| DEC-09 | Owner approved private viewing for signed-in tournament members, assigned Organizers and Admins (CN-028); public spectators not approved |
| DEC-10, DEC-11 | Full replay browser support unresolved; app stack approved, hosting/email/object storage and remaining production choices open |
| DEC-12, DEC-13 | Team policy and account recovery/retention unresolved; initial private dispute review approved/implemented, appeals and outcome corrections open |

Recorded defaults awaiting owner review include CN-005 D1/D2, CN-013 D1/D2,
CN-018 D4, CN-019 D1–D7, CN-020 D1/D2/D4/D5/D6, CN-021 D1/D3,
CN-022 D2/D3/D5, CN-023 D2/D3/D4/D6, CN-024 D1/D4. CN-008's
protocol/deadline rules were explicitly retained by the owner; numeric slack
still needs benchmarking. The project license and engine-derived bot policy
were decided in CN-003/004; they are not fresh open decisions. Separately,
CN-026 D1–D3 are proposed access-control policies awaiting review, and D4
records unresolved role/provisioning decisions; none is an implemented default.

## Source map and stale-context corrections

| Source | Use |
|---|---|
| [PRD.md](PRD.md), [SRD.md](SRD.md) | Product rules and numbered requirements; read their change-notice headers |
| [CHANGE_NOTICES.md](CHANGE_NOTICES.md) | CN-001–036 decisions, corrections, defaults, proposals and test evidence |
| [CHANGE_NOTICES.md](CHANGE_NOTICES.md) | Numbered decisions, corrections, defaults, proposals and test evidence |
| [API_CONTRACT.md](API_CONTRACT.md), [DATA_MODEL.md](DATA_MODEL.md) | Proposed API, entities, constraints, state/access/retention matrices |
| [APP_FLOW.md](APP_FLOW.md), [../PRODUCT.md](../PRODUCT.md) | User journeys, route inventory, product context; planned screens |
| [ARCHITECTURE.md](ARCHITECTURE.md), [TECHNICAL_DOCUMENTATION.md](TECHNICAL_DOCUMENTATION.md) | Design boundaries, runner/worker mechanics, commands and troubleshooting |
| [PROJECT_PLAN.md](PROJECT_PLAN.md), [JIRA_BREAKDOWN.md](JIRA_BREAKDOWN.md), [REQUIREMENTS_COVERAGE.md](REQUIREMENTS_COVERAGE.md) | Roadmap, dependencies and evidence-based completion |
| [TEST_PLAN.md](TEST_PLAN.md), [SECURITY_REVIEW.md](SECURITY_REVIEW.md), [BOT_POLICY.md](BOT_POLICY.md) | Acceptance gates, self-review residuals, actual bot contract |
| [USER_GUIDE.md](USER_GUIDE.md), [ADMIN_GUIDE.md](ADMIN_GUIDE.md), [OPERATIONS_RUNBOOK.md](OPERATIONS_RUNBOOK.md) | Current feature console, planned Admin flows and interim service runbook (CN-033) |
| [LICENSING.md](LICENSING.md), [../THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md), [../LICENSE](../LICENSE) | AGPL-3.0-only project and open component/launch obligations |
| [../handoff.md](../handoff.md), [../CHANGELOG.md](../CHANGELOG.md), package READMEs and source | Task history and actual implementation; older narrative can be stale |

Intake sources also included Claude's project-specific
`~/.claude/projects/-home-hixam-Downloads-Innofest-battle-it-out/memory/`
index and workflow/document/component/backlog notes, plus project session
history, especially final session `ac7da701-ce0d-48ab-aad4-a3e4098ce007.jsonl`.
Only curated project facts are retained here; raw transcripts and credential
material were not imported. Claude's original files were left unchanged.

Do not repeat these stale statements from older sections/notes: Python 3.13
and 3.15 were never tested; no queue/registration/notification code exists;
Jira breakdown is undone; only a placeholder test exists; PR #32 is still
open; project license/import policy is undecided. The 2026-11-05 snapshot in
handoff §3 is historical. Several coverage gap descriptions lag later wiring;
retain their current status counts while consulting code and CN-018–025 for
the exact remaining gap. CN-027 adds interim service commands without closing any
requirement status. No implementation requirement changed during intake
or the BIO-406 documentation slice. The user/role/Organizer-assignment contract
is no longer absent; it is proposed in API_CONTRACT §2.1–2.3, not implemented.


## CN-028 continuation evidence

On project Python 3.15.2, full backend unit mode discovered 779 tests: 731 passed,
48 integration cases skipped. The complete real-engine suite then passed **all
779** in 332.531 seconds. Targeted native bundle/live/service integration passed
28 tests; the service archive assertion was separately checked with all 18
service tests, including deletion of retained live-board JSON. Additive bundle/
validator unit checks passed on 3.12.15/3.13.18/3.14.10 (22 discovered, 19 passed,
3 expected skips per interpreter). This is current evidence, not Claude's CN-025
four-version whole-backend integration result.

The PostgreSQL feature suite covers 20 HTTP/CSRF/privacy/transaction/history/
provisioning cases on Django 6.1.3/DRF 3.18.3/psycopg 3.3.9. React/TypeScript
production build passes and three desktop/mobile Playwright flows pass using
labeled disposable local fixtures. A stalled browser installer was repaired by
extracting its already-downloaded archive under /tmp; no production browser,
account or competition was touched. Source/runtime state remains separated.
No external Site/provider/channel was created/published/contacted. Temporary
PostgreSQL, previews and output are task-owned; existing user replays remain.

Two bounded read-only research agents inspected engine streaming/native modules
under the Sites skill's research-delegation guidance. They made no code changes
or independent security audit. No public skill/index/graph update was needed.

## CN-029 continuation evidence

BIO-404 implements one JSON error envelope across Django/DRF exceptions,
direct responses, CSRF, method refusals and unknown routes; fresh server-owned
request IDs on all API responses; private/no-store responses; and public
GET/HEAD `/api/v1/health/` process liveness without PostgreSQL/legacy-store/engine
access. Status/retry/method headers survive normalization. Hidden resources use
generic `404` wording; server failures are redacted even in debug mode and still
reach Django exception logging. Ordinary unexpected `ValueError` is now a `500`,
rather than a client-validation error. Login explicitly requires JSON (`415`).

Current verification on project Python 3.15.2: 23 PostgreSQL feature tests plus
17 HTTP-boundary tests pass, including real session CSRF and stored conflict
replays with fresh request IDs. Django system checks and migration drift checks
pass; no schema migration is needed. The standalone boundary suite also passes
with database access forbidden. Full backend unit mode: 779 discovered,
731 passed / 48 integration cases skipped, 11.470 seconds. No new real-engine,
browser or four-version run is claimed; CN-025/028 remain historical evidence.
Disposable private PostgreSQL clusters use Unix sockets under `/tmp` and are
stopped after checks. Existing data/replays are preserved.

Use explicit Django test labels `backend.webapp.tests backend.webapp.tests_http
backend.webapp.tests_notifications` (the last module was added in CN-030):
directory discovery loses package context in this namespace layout. The separate
`backend/run_tests.py` runner covers execution-library suites, not web modules.
An initial broad-label test attempt failed discovery; explicit labels pass.
An initial module filename shadowed Python's `http` package under manage.py;
the corrected `api_errors.py` avoids the collision.

BIO-404 still needs pagination, global idempotency/concurrency, missing core
routes and dependency/production readiness. Liveness is not database or worker
readiness. Existing Django exception-log access/retention needs operational
review. Requirement counts remain 17 DONE / 61 PARTIAL / 13 TODO / 0 DEFERRED;
all nine complete backlog categories above remain. No new product/provider/
hosting approval or public skill/derived graph/index change is made.

## CN-030 continuation evidence

BIO-607 exposes GET `/api/v1/notifications/`, PATCH
`/api/v1/notifications/{id}/` and GET/PATCH
`/api/v1/me/notification-preferences/`. Only the explicit operator-linked
participant roster recipient is used; Django numeric IDs, client fields and
staff scope never select an inbox. Anonymous requests are `401`; unlinked/staff
accounts are `403`; another recipient's notice and a missing one are identical
`404`, including within the same team. Links are read on each request. Personal
historical notices remain readable independently of current tournament scope.

The shared notification library supplies bounded offset pages, counts and
filters; equal-time ordering uses ID. Unknown/repeated/invalid query fields are
refused. The offset choice is interim; new notices may shift pages. JSON-only
PATCH with session CSRF sets absolute read/preference state, preserving read
timestamps and avoiding duplicate preference audit on retries. Preference
conflicts roll back state. Workers use the same `notifications.json`; disabling
email skips queued deliveries without dropping dashboard notices. Provider
errors, recipient IDs and internal event/delivery metadata stay out of HTTP.

Current project Python 3.15.2 verification: **57 web tests pass** (23 existing
PostgreSQL feature, 17 HTTP boundary and 17 notification cases), 5.228 seconds.
System and migration-drift checks pass with no new migration. Full backend unit
mode: **779 discovered, 731 passed / 48 skipped**, 11.576 seconds. Real sessions,
CSRF, deactivation, same-team privacy, numeric-ID collision, pagination,
idempotent setters, rollback and fresh worker runtime/email-off/injected-outage
are covered. Disposable private PostgreSQL clusters under `/tmp` are stopped
after checks; no real provider, browser, engine game or four-version matrix was
run for this adapter slice. Existing data/replays are preserved.

Next independent candidates are the recipient notification UI (BIO-703) or a
bounded core schema/store-migration slice. Staff recipient/account lifecycle,
announcements/automatic event calls, real providers/hosting, global pagination,
full PostgreSQL migration and every retained execution gate remain open. All
91 statuses stay **17 DONE / 61 PARTIAL / 13 TODO / 0 DEFERRED**; all nine complete
backlog categories above remain. No public skill or generated graph/index update
is needed; repository Markdown is the durable memory destination.

## CN-031 continuation evidence

BIO-703 adds direct dashboard/inbox links and addressable existing console
sections. The dashboard shows the selected tournament's status, registration and
submission deadlines with local timezone and three scoped personal notices.
The inbox is independent of current tournament membership, uses 20-item offset
pages with an unread filter and refresh, and updates read state and email through
the existing CSRF/session client. Email remains optional and dashboard notices
stay enabled. Servers serving the built React app need a fallback for the two
new paths and same-origin forwarding for the API. No hosted deployment occurred.

TypeScript and Vite production build passed. All five Playwright tests passed
in 10 seconds with real Django sessions and disposable PostgreSQL and legacy
state. The seed script reuses the existing fixture and requires a new local
`bio_qa_*` database and state path. No new engine/backend matrix, production
provider or formal accessibility test ran. All nine backlog categories and the
91 requirement statuses remain. An independent candidate is private replay
download against the existing vault (BIO-605), with browser playback still
dependent on DEC-10.

## CN-032 continuation evidence

BIO-605 private native replay delivery was started from merged `origin/main` at
`22ec3dc` on `BIO-605-private-replay-download` while BIO-703 was open to main.
It uses server-derived membership/Organizer scope for a vault lookup, current
tournament lifecycle checks and a verified file descriptor. Existing callers of
`fetch_replay` still get a verified handle. The live list adds the latest game
match ID alongside the series ID. Binary responses are private attachments;
hidden/deleted/missing replays share `404`, visible archived replays return
`410`, and a missing or damaged indexed file returns `503` and records an
incident. The vault rechecks archive status after verifying the file.

All 66 Django tests passed in 6.314 s with disposable PostgreSQL, including
nine new replay cases. System and migration-drift checks passed. Backend unit
mode found 779 tests, 731 passed and 48 skipped. All 39 targeted replay
integration cases passed in 18.735 s, including collection, verified fetch,
on-disk purge and retained history for an engine-native replay. Temporary test
outputs preserved existing user replays.

Post-archive requests receive no replay. An already-admitted stream may finish,
and production cleanup of worker output copies remains open. Native file
contents include whatever the engine records; indicator-text policy, the
browser player, log delivery, object storage and recovery remain open. All 91
requirement statuses and nine backlog categories remain. Independent follow-up:
BIO-805 operator runbooks for the interim services.

## CN-033 continuation evidence

BIO-805 starts at merged `origin/main` `22ec3dc` on
`BIO-805-interim-operator-runbooks`. [OPERATIONS_RUNBOOK.md](OPERATIONS_RUNBOOK.md)
covers current health and status commands, incident triage, deadline/purge
escalation and isolated backup, recovery and key rotation. The current
Admin/participant/Organizer guides reflect the merged feature console from
that base. Resume, revive and deadline mutation are still trusted library
operations with role/HTTP workflow follow-up. No new operations policy is set.

A disposable PostgreSQL/file fixture verified backup checksums and restore,
current account scope, byte-identical source and digest, match/dispute
references, preferences and retained/archived replay state. An old web session
failed after a disposable signing-key change and fresh CSRF login passed.
Service integration all 18 passed in 33.445 s (real games and archive);
34 work-queue and 53 tournament tests passed. Production time/capacity claims,
provider/target-host outage drills, recovery objectives and runbook sign-off
remain pending. All 91 requirement statuses and all nine backlog categories
remain. Independent next work can expose the existing bracket state to scoped
HTTP reads (BIO-603).

## CN-034 continuation evidence

BIO-603 started from `22ec3dc` on `BIO-603-bracket-result-api` while three
other task PRs were open to main. Current session scope gates
`GET /api/v1/tournaments/{id}/bracket/` and `GET /api/v1/matches/{match_id}/`.
The bracket uses the scheduler's tournament ID or a linked legacy bracket.
Match detail resolves a game ID through the stored bracket/series relationship.
It exposes allowlisted result, map, version and coin-flip fields. Archive
retains history; deleted and out-of-scope records share the missing response.
The API performs no draw, retry, advancement or replay lookup during reads.

All 64 Django tests passed (seven new, 5.786 s). System and migration-drift
checks passed. Selected bracket/series unit mode found 55 cases, with 51
passes and four real-game skips. SRD-028 advances to PARTIAL. Coverage remains
91 rows and nine backlog categories. Bracket/round mutations, map-pool
selection, score fields and complete results UI remain open.

## CN-035 continuation evidence

BIO-606 `BIO-606-tournament-archive-api` starts from `22ec3dc` while earlier
task PRs are open against main. The session-CSRF archive endpoint admits Admin
and current explicit Organizer assignments, validates exact confirmation and
only archives completed/already archived tournaments. It uses the shared
vault. The transition is recorded once and failing deletion returns
`replays_deleted: false` while access stays blocked. Maintenance retries the
purge. Per-tournament purge locking protects the shared filesystem. The
legacy tournament store is locked through purge to preserve the audit slot;
archive is a low-frequency blocking operation on that store.

63 Django tests passed (six new, 6.143 s) with disposable PostgreSQL, plus
system and migration-drift checks. All 111 selected replay, tournament and
service integration cases passed in 48.461 s with real engine runs. Current
verification used temporary paths. Full production purge of worker outputs,
backup/restore after live archive, permanent-delete workflow and other
remaining backlog categories still apply. All 91 requirement rows remain.

The code from PRs #39–43 was first exercised together in a disposable checkout.
The production frontend build and all 79 Django tests passed, including
replay downloads, result visibility and archive/retention together. The merge
resolutions preserve all five change notices and task-log entries, the updated
coverage and the nine-category backlog.

## Merge-batch verification

PR #39 was already on main. Reconciled #40–43 in order, retaining the
individual task histories, shared API/test evidence and current user guide.
The combined branch passed 79 Django tests (8.847 s) plus system and migration
checks, 111 targeted real-engine integration tests (50.654 s), the production
frontend build and five Playwright cases (10.7 s). Test state and replays were
temporary. Results publication SRD-028 is PARTIAL. All 91 rows and nine
backlog categories remain.

## CN-036 continuation evidence

BIO-505 closes submission reads on `BIO-505-submission-read-api` from
`d66b95d`. History lists exact game IDs from stored brackets. The per-version
validation route returns current state and ordered findings. Both reads use
current tournament and team/Organizer scope. Visible roster teams without
uploads return an empty list. Successful staff metadata reads use the
PostgreSQL feature audit. Source and bundle reads keep their integrity checks
and existing registry audit. Current activation remains automatic.

All 85 Django tests and Django system/migration checks passed. Registry and
bundle unit mode ran 70 cases with 67 passes and three integration skips.
SRD-057 is DONE; 18 DONE / 61 PARTIAL / 12 TODO / 0 DEFERRED across 91 rows.
The full backlog remains above. BIO-506 extends the HTTP privacy checks across the submission routes. Production retention remains open.

## CN-037 continuation evidence

BIO-701 completes the existing web foundation from `d66b95d` on
`BIO-701-frontend-foundation`. The shared frontend client retains status,
error code, details and the server request ID. Keyboard skip navigation moves
focus without changing the route. Direct Operations and inbox links show
scope-aware refusals and preserve the requested path through sign-in.

The production frontend build and all eight browser cases passed against
local fixture Django/PostgreSQL in 12.1 s. The three new cases verify the
participant Operations guard, the Organizer inbox guard and a real failed
login with its matching server request ID. The mock competition and sessions
were disposable. Coverage statuses and all nine backlog categories remain.
Complete usability/accessible-flow acceptance remains BIO-708.

## CN-038 continuation evidence

BIO-603 closes the bracket and round API from `d66b95d` on
`BIO-603-bracket-round-actions`. Staff can select a stored pool, confirm a draw
once the submission deadline passes and confirm a sequential round start.
The draw uses the existing scheduler logic, verified roster, map pins and
idempotent exclusion notices. Web uses configured `BIO_ENGINE_JAR` to verify
its map catalogue; the worker owns execution. Round start cannot requeue a
paused round. Results expose recorded game win counts by side.

85 Django tests passed in 9.221 s. Django system and migration-drift checks
passed. 164 selected library/service cases passed in 79.846 s with real engine
games. SRD-023 advances to DONE on this branch. All nine backlog categories and
91 requirement rows remain. Full results UI, raw engine point totals, recovery
authority, house bots, and cutoff draws remain separately tracked.

## Merge reconciliation evidence for PRs #44–54

The locally reconciled PRs complete submission reads and uploads, frontend
foundation, bracket and round actions, exact dependency pins and reproducible
bundles, deadline notices, audit feeds, roster and team reads, and structured
match-log delivery. The owner authorized the eleven PRs to merge into main individually, in
number order. Their tested conflict resolutions are retained in the merges.

All 127 Django cases and 412 targeted integration cases passed together.
Backend unit mode passed 738 of 786 cases with 48 expected skips. The frontend
production build and eight Playwright checks passed. See the latest handoff for
test context. All nine backlog categories remain and track the remaining
45 Jira items after the open implementation PRs.

## CN-052 continuation evidence

BIO-607 adds `POST /api/v1/tournaments/{id}/announcements/` on
`BIO-607-tournament-announcements` from `eda8358`. Admins and assigned
Organizers publish bounded text to verified roster accounts in a published,
unarchived tournament. The existing dashboard feed and email preference
apply. The notification store commits the audience, delivery queue,
author-attributed audit and retry receipt together. Keys are scoped to the
author and tournament and the retry returns the original counts. Temporary
test data exercised both authorization and deletion retention.

All 145 Django tests passed on disposable PostgreSQL, with system and
migration checks, and all 101 notification library tests passed on project
Python 3.15.2. All 91 statuses and nine backlog categories remain. Staff
authoring UI, account provisioning for staff recipients, real provider and
PostgreSQL notification migration remain open.

## CN-053 continuation evidence

BIO-704 starts from merged main at `9255e2a` on
`BIO-704-participant-team-submissions`. My team combines the private verified
roster with recorded bracket standings. Bot submissions uses current team
scope and captaincy from the console tournament list. It shows the deadline
lock, the active bot, expandable check findings and private file downloads.
Refreshing reloads the current tournament and history. The existing
`/#submissions` link still works and staff have a read-only team lookup.

The production build, all 10 Playwright cases (15.8 s), all 145 Django
cases (16.980 s), system and migration-drift checks passed on disposable
state. The invalid and queued uploads in the browser kept the previous
active version. All 91 requirement statuses and nine backlog categories
remain. BIO-704 is implemented locally; 43 tracked Jira items remain.

## CN-054 continuation evidence

BIO-705 starts from merged main at `3158801` on
`BIO-705-bracket-match-results`. Bracket and game links use recorded round,
pairing, game win, bot version, tie-break and coin-flip fields. The replay
page checks current game scope and vault index status and streams the
retained native attachment through the existing download endpoint.
Browser playback still depends on DEC-10, and raw engine points remain open.

All 147 Django tests passed in 17.727 s with system and migration checks.
The production build and all 12 Playwright tests passed (18.4 s) on
disposable services. The tests exercised a recorded four-game final, a
native-extension fixture attachment and archive with preserved history.
Worker-scoped fixture sessions reduced repeated loopback sign-ins after the
first browser run reached the existing login limiter. The orchestrator
selection ran 164 cases, with 153 passes and 11 expected integration skips.
All 91 statuses, nine backlog categories and 43 open Jira items remain.

## CN-055 continuation evidence

BIO-707 starts from merged main at `84c6e13` on `BIO-707-admin-approval-queue`.
The Admin route shows pending Organizer submissions and loads the current
version and settings before each review. The approval confirmation or rejection
reason goes to the existing lifecycle API. A competing review requires
reloading details, and opening registration stays separate.

The production build and all 14 Playwright tests passed in 22.2 seconds
against disposable state. The two new cases exercise approval, rejection,
a stale decision and participant route refusal. All 91 requirement
statuses, nine backlog categories and 43 open Jira items remain. Deadline,
invitation and incident controls, dedicated audit and formal acceptance
remain open.

## CN-056 continuation evidence

BIO-706 starts from merged main at `88594e1` on
`BIO-706-organizer-tournament-management`. The Organizer console lists
assigned tournaments and supports draft creation, edits, review submission
and resubmission, with rejection reasons and manual registration opening.
The form converts browser-local deadlines to UTC and sends only edited
fields. Lifecycle actions reuse current assignment and version checks.

The production build and all 16 Playwright tests passed (23.5 s) on
disposable state. The browser exercises both sides of the approval flow
and participant and unassigned-Organizer refusals. The initial edit test
selector stopped on the populated textarea and was corrected to use its
accessible textbox name. All 91 statuses, nine backlog categories and 43
open Jira items remain. Roster, round and dedicated team screens remain
under BIO-706.

## CN-057 continuation evidence

BIO-607 starts from merged main at `300b9d7` on
`BIO-607-announcement-composer`. Admins and assigned Organizers use the
staff console to select a tournament, publish plain text and see inbox/email
counts. Eligibility follows the API. Retries of the same form payload use
the original key.

The production build and all 17 Playwright tests passed (55.3 s) against
disposable state. The browser dropped a successful response, retried and
verified one copy in the recipient's inbox. All 91 statuses, nine backlog
categories and 43 open Jira items remain. Staff recipients, automatic
approval and dispute notices, production delivery and SQL migration remain.

## CN-058 continuation evidence

BIO-707 starts from merged main at `4c19c20` on
`BIO-707-global-audit-screen`. Admins page the existing global feed and
filter by exact tournament ID, including retired records. The screen
uses the server's projected metadata and admits no participant access.
Offset pages follow the live feed and can shift as events are appended.

The production build and all 18 Playwright tests passed (32.5 s) against
disposable services. The browser check exercises forward/back pagination,
retained deletion history, metadata disclosure and role refusal. All 91
statuses, nine backlog categories and 43 open Jira items remain. Admin
deadline, invitation and incident actions and permanent audit migration
remain open.

## CN-059 continuation evidence

BIO-707 starts from merged main at `8077df2` on
`BIO-707-admin-deadline-controls`. The Admin tournament console reuses
the existing deadline API to extend dates or override locked settings.
The forms require a reason and confirmation, reuse the key on the same
payload retry, and display the affected count and notice state.

The production build and 19 Playwright cases passed on disposable state.
The browser checked a locked override, a deadline extension and both
participant notices. All 147 Django tests passed with system and migration
checks. Python 3.15 unit mode found 786 tests, with 738 passes and 48
expected integration skips. All 91 statuses, nine backlog categories and
43 open Jira items remain. Admin invitation and incident controls and
formal acceptance remain.

## CN-060 continuation evidence

BIO-707 starts from merged main at `711c289` on
`BIO-707-admin-invitation-controls`. The console lists invitation metadata
and submits confirmed revocation or replacement with a reason through the
existing Admin-only API. A new value is only held in the current browser
view after a successful replacement.

The production build and 20 Playwright tests passed (31.5 s), including both
actions, dismissal and retention of safe list metadata, and Organizer
refusal. All 91 statuses, nine backlog categories and 43 open Jira items
remain. Staff initial issuance UI, public claim/verification, delivery,
and Admin incident actions remain open.

## CN-061 continuation evidence

BIO-706 starts from merged main at `8271400` on
`BIO-706-organizer-roster-screen`. The scoped Organizer roster page
shows registration and captain status, imports CSV or JSON, reports
rejected rows and submits version-checked corrections. Locked entries and
foreign tournament data stay protected by the existing API.

The production build and all 21 Playwright cases passed (29.8 s), including
both imports, correction, report and scope. All 91 statuses, nine backlog
categories and 43 open Jira items remain. Initial invitation issuance in
the console and dedicated round and team management remain open.

## CN-062 continuation evidence

BIO-706 starts from merged main at `377940d` on
`BIO-706-organizer-round-controls`. The assigned Organizer screen shows
map pools and bracket readiness and invokes existing confirmed draw and
idempotent round-start APIs. The draw and queueing are separate actions.

The production build and all 22 Playwright tests passed (32.2 s),
including map selection, scoped draw, separate start and a foreign-link
refusal. The browser fixture uses a synthetic catalogue and queues
without running matches. All 91 statuses, nine backlog categories and
43 open Jira items remain. Dedicated team management, staff invitation
issuance and full acceptance remain open.

## CN-063 continuation evidence

BIO-706 starts from merged main at `77ee8da` on
`BIO-706-organizer-team-source`. The assigned Organizer team directory
uses the official roster for team selection, current team scope for
verified profiles and bracket standings, and the existing submission
check and download views. It completes the local BIO-706 screen scope.

The production build and all 23 Playwright tests passed (35.2 s). The
browser checks two team profiles, exact source bytes, the staff audit
entry and foreign scope. All 91 requirement statuses and nine backlog
categories remain, with 42 tracked Jira items open. Initial invitation
issuance is BIO-502, team deletion is BIO-609 and formal acceptance is
BIO-708.

## CN-064 continuation evidence

BIO-502 starts from merged main at `5e4247f` on
`BIO-502-staff-initial-invitation-issuance`. The Admin invitation page
and Organizer roster page use current eligibility and the existing
first-issue API. Success shows each new code alongside its official
email until dismissed or leaving the view.

The production build and all 24 Playwright tests passed (39.1 s),
including both staff roles and no plaintext in the subsequent list.
All 91 statuses, nine backlog categories and 42 open Jira items remain.
Public claims, verification and automated delivery remain open.

## CN-065 continuation evidence

BIO-707 starts from merged main at `8765fbd` on
`BIO-707-admin-tournament-management`. The Admin console shares the
tournament form and version checks with Organizer management, uses direct
confirmed approval for Admin-created drafts, and opens registration in a
separate action. Staff detail exposes the persisted creator role for this
control. Existing deadline addresses are linked from settings.

The production build, 147 Django tests, migration and system checks, and
the Python 3.15 backend unit run passed. The unit run had 738 passes and
48 expected integration skips. The 25-case browser suite covers stale edits,
direct approval, registration, role refusal and desktop/mobile rendering.
All 91 requirement statuses, nine backlog categories and 42 tracked Jira
items remain. Staff archive controls are the next ready lifecycle slice.

## CN-066 continuation evidence

BIO-606 starts from merged main at `9f83f3c` on
`BIO-606-staff-archive-controls`. The Admin and assigned Organizer consoles
share a confirmation form for completed tournaments. Archive reports vault
purge completion or pending retry. Archived tournaments link to results
and allow purge verification through the same scoped API.

The production build and all 26 Playwright tests passed (52.8 s). The
Admin test downloads a disposable replay and verifies the archived result
and download state. The Organizer test verifies scope, simulates the
pending receipt and checks purge after reload. The on-disk failure and
maintenance retry are covered by existing Django archive tests. Production
scheduling, retention, backups and deletion remain. All 91 statuses, nine
backlog categories and 42 tracked Jira items remain.

## CN-067 continuation evidence

BIO-707 starts from merged main at `c3971ec` on
`BIO-707-admin-roster-and-teams`. Admin settings link to the shared roster
and verified team directory. They use the existing role checks, versioned
roster correction and audited source delivery. Return links follow the
current staff console.

The production build and all 27 Playwright tests passed (45.0 s). The
browser verified CSV import, private team display, exact source bytes,
the Admin download audit and route refusal before scoped requests. All
91 statuses, nine backlog categories and 42 open Jira items remain.
The Admin Operations reader can surface existing stuck-job details;
recovery mutations still need their policy decisions.

## CN-068 continuation evidence

BIO-604 starts from merged main at `28dd7c5` on
`BIO-604-admin-operations-triage`. The Admin Operations console uses
the existing read-only API to display incident attempts and alert state,
dead job IDs and failures, and recent audit events. It supports refresh
and has a direct `/admin` address alongside the earlier hash address.

The production build and all 27 Playwright tests passed (44.1 s).
The local fixture uses the existing libraries to record a paused match
and dead job without running an engine or worker. Browser coverage
checks both records, refresh, and participant refusal on both addresses.
All 91 statuses, nine backlog categories and 42 Jira items remain.
Recovery authority remains open. The linked participant settings page
can reuse the inbox email preference next.

## CN-069 continuation evidence

BIO-702 starts from merged main at `449fa64` on
`BIO-702-participant-account-settings`. Linked participants can manage the
same email preference in account settings and the inbox. The existing API
enforces current recipient scope and keeps dashboard delivery enabled.

The production build and all 28 Playwright tests passed (46.3 s). The
browser verified keyboard changes, persisted state across both views,
retained dashboard notices and access checks. Earlier runs exposed the
asynchronous checkbox assertion and the existing ten-attempt source limit.
Fixture sessions were reused for the successful run. All 91 statuses,
nine backlog categories and 42 tracked Jira items remain. Public signup,
verification and account deletion remain open.

## CN-070 continuation evidence

BIO-702 starts from merged main at `dcd6278` on
`BIO-702-dedicated-sign-in`. The landing guide links to the dedicated
session form at `/login`. Successful direct sign-in and existing sessions
at that address open the dashboard. Protected addresses keep their own
post-login destination. The existing username/password and CSRF contract
still applies.

The production build and all 28 Playwright tests passed (48.5 s). The
browser checks the public link, existing sessions, bad credentials and
the matching HTTP request ID, plus protected deep links. All 91 statuses,
nine backlog categories and 42 Jira items remain. The next ready results
slice can show existing scoped match logs in the console.

## CN-071 continuation evidence

BIO-705 starts from merged main at `7e9cea2` on
`BIO-705-structured-match-log-view`. The selected game's log opens the
latest verified attempt and accepts a numbered attempt. The page displays
the API's current-role event projection with expandable details and output
as text. It distinguishes missing logs from API errors.

The production build and all 29 Playwright tests passed (45.7 s). The
browser uses a real, disposable log fixture and verifies a participant's
own side, both sides for the assigned Organizer, and diagnostics for the
Admin. All 91 statuses, nine backlog categories and 42 tracked Jira items
remain. Browser replay playback, raw engine scores, formal accessibility
and log retention remain open.

## CN-072 continuation evidence

BIO-708 starts from merged main at `0a1e028` on
`BIO-708-console-navigation-accessibility`. The console identifies the
current section on nested routes and scrolls its navigation area to keep
the active link within view. Keyboard activation moves focus to the main
region. The link focus outline stays visible inside the scrolling area.

The production build and all 30 Playwright tests passed (45.5 s). The
browser checks a nested Admin page on mobile, keyboard activation and
a short desktop viewport after resizing. All 91 statuses, nine backlog
categories and 42 tracked Jira items remain. Formal accessibility and
full workflow acceptance remain open. The existing scoped tournament
audit endpoint can supply the missing Organizer audit screen.

## CN-073 continuation evidence

BIO-610 starts from merged main at `879a04e` on
`BIO-610-staff-tournament-audit-view`. Staff management links to the
existing scoped tournament feed. Both audit screens share event rows
and paging. Admin global filtering remains available for retained records.

The production build and all 31 Playwright tests passed (44.8 s). The
browser verifies event details and return navigation for both staff roles
and refusal before requesting an unassigned Organizer's feed. An earlier
run exposed an intermittent navigation visibility assertion. The scroll
offset now rounds to whole pixels and observes the active link size.
All 91 statuses, nine backlog categories and 42 tracked Jira items remain.
The lifecycle browser suite can next exercise deadline notices with email off.

## CN-074 continuation evidence

BIO-611 starts from merged main at `e75d797` on
`BIO-611-web-lifecycle-acceptance`. The browser disables participant email
in settings and verifies both new Admin deadline notices with disabled email
status. The archive flow checks exact fixture replay contents, `410` after
purge and equality of the official result payload across archive.

The production build, 31 Playwright tests (45.0 s), 147 Django tests
(15.7 s), and Django system and migration checks passed. The backend unit
matrix passed on CPython 3.12.15, 3.13.18, 3.14.10 and 3.15.2, with 735 of
786 cases passing and 51 skips on each interpreter. All 91 statuses and
nine backlog categories remain, with 42 Jira items open. Deletion and
production provider outage and restore still gate full acceptance.
All 235 targeted orchestrator, work-queue and service cases also passed
in integration mode on Python 3.15.2 (278.3 s), using the pinned engine
and temporary outputs. GitHub Actions is enabled for the next CI slice.

## CN-075 continuation evidence

BIO-804 starts from merged main at `a299868` on
`BIO-804-frontend-build-ci`. GitHub Actions installs the frontend lockfile
and type-checks and builds on Ubuntu 24.04 with Node.js 26.13.1. The workflow
runs for frontend and workflow changes on pull requests to `main` and
pushes to `main`. It uses pinned checkout and Node actions.

A clean local export passed `npm ci` and `npm run build` with Node.js
26.13.1 and npm 12.2.3. Hosted evidence is recorded in the PR build check.
All 91 statuses, nine backlog categories and 42 open Jira items remain.
Backend matrix, real-engine and browser CI and deployment remain open.

## CN-076 continuation evidence

BIO-804 starts from merged main at `f18d7c1` on
`BIO-804-backend-unit-matrix-ci`. GitHub Actions reads the Python families
from the existing test runner, installs managed Python with uv 0.13.10,
and uses the pinned primary launcher environment to dispatch the unit
matrix on Ubuntu 24.04. The run reports the exact Python patch versions.

The hosted matrix passed on CPython 3.12.16, 3.13.18, 3.14.10 and 3.15.2.
Each interpreter ran 786 cases with 729 passes and 57 skips. See the
[hosted matrix](https://github.com/hixam001/battle-it-out/actions/runs/46114109966).
All 91 statuses, nine backlog categories and 42 open Jira items remain.
Web, browser and real-engine CI remain separate verification work.

## CN-077 continuation evidence

BIO-804 starts from merged main at `0ba1ce6` on
`BIO-804-web-and-browser-ci`. The workflow runs Django system, migration
and HTTP checks with disposable PostgreSQL 18.7. It then seeds the
browser fixture and starts Django and Vite on loopback to run the
Chromium Playwright suite. Python 3.15.2, Node.js 26.13.1 and the existing
dependency locks govern the application runtime. The job uses the Ubuntu
runner's installed Chromium and reports the browser version.

Shell blocks passed syntax checks. The PR's Web and browser tests check
records hosted verification. The current local evidence is in CN-074.
All 91 statuses, nine backlog categories and 42 Jira items remain.
Hosted real-engine checks and deployment are open.

## CN-078 continuation evidence

BIO-804 starts from merged main at `874e567` on
`BIO-804-hosted-engine-smoke`. It carries forward the earlier local draft
workflow, selecting JDK 21, installing the primary Python launcher
environment, starting the sandbox and resolving the Gradle runtime. It
runs the replay integration module with sample bots and temporary output.
The first hosted run on Ubuntu 24.04 hit `RTM_NEWADDR` at bubblewrap
startup. The job uses Ubuntu 26.04 for its packaged AppArmor support for
bubblewrap's namespace setup.
All 40 replay cases passed locally on Python 3.15.2 in 20.362 seconds.
All five workflow shell steps passed `bash -n`.
The [hosted smoke run](https://github.com/hixam001/battle-it-out/actions/runs/46115982843)
passed all 40 cases with Python 3.15.2, JDK 21.0.13.1, bubblewrap 0.11.1
and engine 1.2.6 on Ubuntu 26.04. PR #86 merged to `main` at `3c89849`
after the hosted unit matrix and web/browser checks also passed.
Wider hosted integration coverage and deployment remain open. All 91
requirement statuses, nine backlog categories and 42 Jira items remain.

## CN-079 continuation evidence

BIO-803 starts from merged `main` at `3c89849` on
`BIO-803-reconcile-restored-replays`. Maintenance resumes incomplete vault
purges and rechecks archived tournament folders whose purge already finished.
It sweeps restored files through the existing serialized purge and records
failures, including a restored dangling link. An absent archived folder
adds no purge attempt. Official results and other tournaments stay intact.

The two new replay regressions failed before the fix. Python 3.15.2 passed
740 of 788 backend unit cases with 48 expected skips, then all 42 replay
integration cases in 21.836 seconds. A PostgreSQL 18.7 and private-state restore
verified backup checksums, current Admin scope, replay `410` before and after
housekeeping, byte-identical match state, equal bracket and game responses,
and a no-op repeat cleanup. All fixture files were disposable.

BIO-NFR-09 moves to PARTIAL. All 91 requirements, nine backlog categories
and 42 open Jira items remain. Production restore, retention and worker output
cleanup still need their existing decisions and evidence.

PR #87 merged into `main` at `43a178f` after the hosted engine smoke test,
backend unit matrix and web/browser checks passed.

## CN-080 continuation evidence

BIO-304 starts from merged `main` at `43a178f` on
`BIO-304-verify-maps-before-rounds`. The API rechecks the pinned map pool
against the configured catalogue before starting a round, and the configured
worker verifies it again when the round job runs. A refused request leaves
the round ready and the original key reusable. A worker mismatch uses the
normal queue retry path before a game attempt exists.

Python 3.15.2 ran 789 backend cases with 741 passes and 48 expected skips.
All 148 Django cases and the system and migration checks passed with disposable
PostgreSQL. All 52 service and map cases passed with real-engine integration
in 65.656 seconds. The regressions verify changed maps on both paths, same-key
repair, one completion and no replay of a completed round. All 91 requirement statuses,
nine backlog categories and 42 Jira items remain. The configured JAR must be
the launcher's engine JAR. Custom-map approval and production persistence
remain open.

PR #88 merged into `main` at `5547f08` after the unit matrix, real-engine
smoke test and web/browser checks passed.

## CN-081 continuation evidence

BIO-705 starts from merged `main` at `5547f08` on
`BIO-705-bracket-map-order`. The scoped API projects the bracket's saved
main-game and tie-break names. The console adds a native disclosure with
the final tie-breaks in an ordered list. Archive retains the map lists with
the official bracket. Full replay playback and raw engine points remain open.
The production build, all 148 Django cases and all 32 Playwright cases
passed with disposable services. The new browser case checks keyboard
access and the final map order at a 390-pixel viewport. All 91 requirement
statuses, nine backlog categories and 42 Jira items remain.

PR #89 merged into `main` at `1cfdc10` after the frontend build, unit matrix,
real-engine smoke and web/browser checks passed.

## CN-082 continuation evidence

BIO-804 starts from merged `main` at `1cfdc10` on
`BIO-804-real-engine-python-matrix`. The Ubuntu 26.04 job builds each
launcher environment listed in `versions.lock.json` and runs the replay
integration module for each family in sequence. The real game checks the
recorded match interpreter. The job fails if any family fails. Locally all
42 cases passed on each of Python 3.12.15, 3.13.18, 3.14.10 and 3.15.2, and
all five workflow shell steps passed syntax checks. The first hosted run
passed all four real match cases and exposed an intermittent registration
failure in two jobs. File creation now shares the archive state lock and
purged temporary copies return an archive refusal. Two deterministic
interleavings reproduced the failure before the fix. Both archive race
tests passed 20 repetitions each on Python 3.13.18 and 3.15.2 after the fix.
The patched local and hosted runs each passed all 43 cases per Python family.
The [hosted smoke run](https://github.com/hixam001/battle-it-out/actions/runs/46118073197)
passed on Python 3.12.16, 3.13.18, 3.14.10 and 3.15.2. PR #90 merged to
`main` at `26d61af` after the unit matrix and web/browser checks also passed.
Full hosted integration and target-host deployment remain open. All 91
requirement statuses, nine backlog categories and 42 Jira items remain.

## CN-083 continuation evidence

BIO-802 starts `BIO-802-worker-loss-redelivery` from the verified `main`
at `1cfdc10`. It fast-forwards onto the PR #90 merge at `26d61af` before
publication. The fixture launches a disposable worker process and exits it
from the game adapter after a queue claim and game attempt. The clock advances
through the two lease expiries. Recovery records the first attempt as a
platform failure and keeps the pinned map and submissions. A duplicate queued
round leaves the completed match and bracket records unchanged. The game
adapter uses fixture results.

The queue suite passed 54 of 55 cases with one integration skip on Python
3.12.15, 3.13.18, 3.14.10 and 3.15.2. All 55 passed with real-engine
integration enabled on Python 3.15.2. The full backend run on that version
passed 743 of 791 cases with 48 expected skips. All 91 statuses, nine backlog categories
and 42 open Jira items remain. Target-host engine-process cleanup, provider
outages, capacity and multi-host validation remain open.

PR #91 merged into `main` at `8237351` after the engine smoke, backend unit
matrix and web/browser checks passed.

## CN-084 continuation evidence

BIO-606 starts `BIO-606-archive-during-maintenance` from `26d61af` and
fast-forwards to merged `main` at `8237351` before publication. An archive
that begins after the initial replay check can stop collection for its own
bracket. Maintenance lists that bracket as skipped and continues the next
tournament and scheduled purges. The deterministic source-verification
regression reproduced the aborted pass before the fix and verifies
continuation and unchanged official records after it.

All 51 tournament-flow and service tests passed with real-engine integration
on Python 3.15.2 in 81.662 seconds. On the updated branch 744 of 792 backend
unit tests passed with 48 expected skips. All 91 requirement statuses, nine backlog
categories and 42 Jira items remain. Production scheduling and retention
still need their documented decisions and evidence.
