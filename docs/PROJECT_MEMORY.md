---
id: battle-it-out-project-memory
type: project
status: active
created: 2026-11-26
updated: 2026-11-26
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

- Latest continuation on 2026-11-26: PR #37 (CN-029 HTTP errors/liveness)
  merged into `main`; fetched base is `f551850`. **BIO-607 recipient
  notification API** starts there on `BIO-607-notification-api` (CN-030),
  with no stacked dependency. The owner
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
  Notifications remain JSON-backed; UI, providers and full BIO-607 stay open.
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
- Coverage currently records **17 DONE / 61 PARTIAL / 13 TODO / 0 DEFERRED**
  across **91** requirements. DONE denotes the documented library/tool scope,
  not owner acceptance or an independent security review. Counts and row-level
  gaps live in [REQUIREMENTS_COVERAGE.md](REQUIREMENTS_COVERAGE.md).
- The platform now has a tested **Django/DRF/PostgreSQL feature API and
  React website**, plus the existing execution libraries/JSON stores and service
  commands. No production service/website is deployed. Full core registration,
  account recovery, tournament-management API/screens and legacy-store migration
  remain unimplemented; feature implementation is not launch acceptance.

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
| `submission_bundle` | Bounded flat Python ZIPs, native local-module checks, aggregate digests and curated pinned biohelpers source; exact trials/activation/pins/export | `bundle.py`; CN-028 |
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
   proposal remains open. Legacy creator fallback remains outside these scoped
   feature routes and must be replaced before the full role API is implemented.
2. **Service operation:** deploy/supervise the CN-027/028 worker, maintenance,
   email, alert and web processes; approve/implement real email/Admin adapters;
   target-host restart/outage drills; pinned worker/container image and runtime
   digest; secure production database/configuration/TLS. The systemd template is
   validated syntax, not deployed supervision. One-host/fixed-port assumptions,
   the nonrenewed 2400-second match-attempt lease, resume authority and final
   retry-cap policy remain. Live adapter compilation needs the pinned JAR/JDK;
   operational failed-email alert receipt retention still needs policy.
3. **Execution gates:** realistic target-hardware limits benchmark (DEC-04),
   independent sandbox/security review, SR-06 Java-exception classification and
   SR-03 parameter-type residual, engine seed control or accepted TC-04 waiver,
   house-bot algorithm (DEC-06), qualification-cutoff draw/audit (DEC-14), and
   complete TC-05 including these scenarios. Map pools exist; custom-map safety,
   suitability, per-round re-verification and production persistence remain.
   Other OSes, 3.16/free-threaded builds and CI remain unverified/unbuilt. New
   native bundle/live tests do not close any of these execution gates.
4. **Registration/submissions:** roster/invitation/team/claim/verification
   endpoints and code delivery; final error/media-type contracts; locked-entry
   Admin exception; team size/name/captain policy, source retention/deletion,
   approved upload/version/limiter caps and manual-activation decision. HTTP
   upload/history/source/bundle delivery and queued checks now exist and use the
   official stored deadline/current roster Actor. Interim caps are 256 KiB and
   500 versions/team; bundle input ceiling is 32 files. Native flat modules and
   curated biohelpers 1.0.0 are supported; more packages require review/pins,
   additional languages follow compatibility work, and arbitrary participant
   installs/custom runtimes remain unapproved.
5. **Tournament operations and deletion:** remaining tournament/deadline/
   bracket/round/archive HTTP operations and permission tests; explicit map-pool
   selection; full result publication and paused-job mutation controls; queued/
   cancelable account deletion, historical-roster removal without changed
   results, captain transfer/no successor (DEC-07), team delete/restore after
   archive, permanent tournament deletion across every legacy/new package with
   audit retained. Feature match disputes now support private comments/staff
   review/version/idempotency and immutable history; appeals/reopening/outcome
   correction policy and automatic notices remain. The Admin operations reader
   is implemented; additional action controls remain open.
6. **Notifications:** screens, staff/unlinked recipient provisioning, PostgreSQL
   store migration, real provider and deployment; announcements, automatic notice
   calls after extension/override, affected-user
   counts, Organizer approval/rejection and dispute notices; mandatory security
   email policy, owner wording/retry review, expiry alerts and real outage drill.
   Check/round/draw adapters and failed-email alert retry hooks already exist.
   CN-030 supplies linked-participant feed/read/preferences HTTP endpoints with
   current explicit links and the shared service store; this does not close the
   remaining event/delivery/UI work or decide global pagination.
7. **Replays/logs/privacy:** role-scoped match-log HTTP delivery, object storage,
   short-lived URLs, full browser replay player (DEC-10), deployed purge schedule,
   backups/restore, indicator-text exposure review, durable log retention and
   complete end-to-end privacy verification. Private live numeric boards now
   omit arbitrary text, check current scope per poll and are denied/purged after
   archive. Full viewer overlays/traps/animations and production reconnect/load
   evidence remain. CN-032 adds current-scope native replay downloads from the
   private vault. Production retention of worker-side artifacts, raw native
   indicator text review and browser playback remain open.
8. **Website and launch:** remaining registration/account settings/notification,
   team, tournament creation/approval/deadline/round management, full bracket/
   replay/coin-flip and Admin mutation screens. Public landing and the private
   live/analytics/submission/dispute/operations console now exist. Branding,
   usability, formal accessibility/nonvisual play-by-play and full FLOW-01–08
   acceptance remain; production capacity/outage/concurrency/multi-host tests,
   backups/recovery, deployment/TLS, CI matrix/real-engine checks, runbooks, pilot
   and go-live approval are still open. No release dates before the benchmark.
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
| [CHANGE_NOTICES.md](CHANGE_NOTICES.md) | CN-001–032 decisions, corrections, defaults, proposals and test evidence |
| [API_CONTRACT.md](API_CONTRACT.md), [DATA_MODEL.md](DATA_MODEL.md) | Proposed API, entities, constraints, state/access/retention matrices |
| [APP_FLOW.md](APP_FLOW.md), [../PRODUCT.md](../PRODUCT.md) | User journeys, route inventory, product context; planned screens |
| [ARCHITECTURE.md](ARCHITECTURE.md), [TECHNICAL_DOCUMENTATION.md](TECHNICAL_DOCUMENTATION.md) | Design boundaries, runner/worker mechanics, commands and troubleshooting |
| [PROJECT_PLAN.md](PROJECT_PLAN.md), [JIRA_BREAKDOWN.md](JIRA_BREAKDOWN.md), [REQUIREMENTS_COVERAGE.md](REQUIREMENTS_COVERAGE.md) | Roadmap, dependencies and evidence-based completion |
| [TEST_PLAN.md](TEST_PLAN.md), [SECURITY_REVIEW.md](SECURITY_REVIEW.md), [BOT_POLICY.md](BOT_POLICY.md) | Acceptance gates, self-review residuals, actual bot contract |
| [USER_GUIDE.md](USER_GUIDE.md), [ADMIN_GUIDE.md](ADMIN_GUIDE.md) | Planned full core flows; CN-028 feature console is implemented separately |
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
