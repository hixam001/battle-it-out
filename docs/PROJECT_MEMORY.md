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

- Latest continuation on 2026-11-26: PR #33 (the shared-memory handoff) is
  merged; fetched `origin/main` is `3e4f867`. **BIO-406's documentation
  slice** starts there on `BIO-406-access-control-contract`: CN-026 proposes
  user/role/Organizer-assignment API routes, model constraints and 14 planned
  TC-07 cases. No endpoint, authentication, role store or library behavior
  was implemented. BIO-406 remains open for owner decisions and implementation.
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
- Coverage currently records **17 DONE / 50 PARTIAL / 19 TODO / 5 DEFERRED**
  across **91** requirements. DONE denotes the documented library/tool scope,
  not owner acceptance or an independent security review. Counts and row-level
  gaps live in [REQUIREMENTS_COVERAGE.md](REQUIREMENTS_COVERAGE.md).
- The platform has **no HTTP API, production database, accounts/authentication,
  or website**. It has tested Python libraries, durable local JSON stores, and
  a queue worker CLI. A timer function exists; no deployed service runs it.

## Product and owner agreements

INNOFEST Battle It Out runs participant bots in the **existing Battlecode 2026
engine**. Each submission is one UTF-8 `bot.py` with top-level `turn()` and no
arguments. No replacement engine, Java bots, ZIP/multi-file submissions, or
participant-installed packages. Java remains necessary for the engine server.

- Delivery order: execution foundation and automation (epics 00–03), backend
  (04), registration/submissions (05), operations (06), website (07), QA/pilot
  and launch (08). Unresolved execution gates remain open; do not infer that a
  successful local match authorizes starting the website.
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
  a key. [JIRA_BREAKDOWN.md](JIRA_BREAKDOWN.md) proposes 46 later tasks
  `BIO-401..410`, `501..508`, `601..611`, `701..709`, `801..808`. No real tracker
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

The safe application path is: roster claim and verification → membership-derived
Actor → `tournament_flow.upload` → queued two-sided trial → latest-valid version
→ `scheduler.tick(registration=..., notifications=...)` after the submission
deadline → preview playable teams, pin and draw from a verified map pool →
Organizer calls `tournament_flow.start_round` → re-hash pins and queue → worker
plays sequential matches → results/notifications/replays → archive and purge.
Pass the stored deadline from `tournaments.deadline`; never take it from a client.
`tick` never starts rounds. Omitting `registration=` falls back to teams that
uploaded, so production wiring must supply registration. Worker notifications
require `--notify`. These are callable flows, not running production services.

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

## Complete remaining backlog

This list reconciles Claude's `project-unimplemented-backlog.md` after CN-025
with current code and the coverage matrix; nothing here is closed by intake.

1. **Backend foundation (epic 04):** DEC-11 stack/database/hosting/email/storage
   approval; schema/migrations and replacement of all JSON stores; HTTP API,
   common errors/pagination/idempotency/concurrency; accounts/passwords/email
   verification/login/logout/sessions/recovery; centralized roles and real
   Organizer assignments; append-only permanent audit with transactional/outbox
   writes; private authorized file delivery. User/role/Organizer-assignment
   routes now have a contract proposal (BIO-406, CN-026), with no implementation.
   Single/multiple roles, staff/participant combinations, permission composition
   and initial Admin/staff provisioning/recovery remain undecided. Review
   CN-026's proposed access/revocation rules before implementing them; replace
   the creator-based permission fallback, not only the `Actor` construction.
2. **Service operation:** supervise worker, deadline tick, email delivery and
   housekeeping; real Admin alerts for capped matches/dead jobs/failed email;
   worker container/image and runtime digest; secure deployment/configuration.
   One-host/fixed-port assumptions remain. Queue jobs have heartbeat, but the
   orchestrator's separate 2400-second attempt lease is not renewed. Resume
   authority and final retry-cap policy need confirmation.
3. **Execution gates:** realistic target-hardware limits benchmark (DEC-04),
   independent sandbox/security review, SR-06 Java-exception classification and
   SR-03 parameter-type residual, engine seed control or accepted TC-04 waiver,
   house-bot algorithm (DEC-06), qualification-cutoff draw/audit (DEC-14), and
   complete TC-05 including these scenarios. Map pools exist; custom-map safety,
   suitability, per-round pool re-verification, and production pool persistence
   remain. Other OSes, 3.16 and free-threaded builds are unverified; no CI.
4. **Registration/submissions:** endpoints and error mapping, code delivery,
   account and verification-email integration, locked-entry Admin exception,
   team size/name/captain policy, source retention, approved upload and limiter
   caps/throttling, manual-activation decision. Registry defaults are 256 KiB
   per file and 500 versions/team, not approved product limits. Engine imports
   remain restricted to random/math/enum/battlecode26; no arbitrary stdlib or
   preinstalled third-party bot libraries. Production callers must supply the
   official deadline, authenticated Actor, and roster-aware timer configuration.
5. **Tournament operations and deletion:** HTTP operations and permission tests,
   explicit map-pool selection, authenticated results publication, incident and
   paused-job controls; queued/cancelable account deletion, historical-roster
   removal without changed results, captain transfer/no successor (DEC-07),
   team deletion/restore after archive, and permanent tournament deletion across
   every package's data with audit retained. A tournament tombstone and purge
   helpers do not implement the full deletion lifecycle.
6. **Notifications:** endpoints/screens, real email adapter/provider, service
   delivery, announcements, automatic `notify_notice` after extension/override,
   affected-participant counts, Organizer approval/rejection notices, mandatory
   security-email policy, owner-reviewed wording/retry defaults, expiry and
   given-up-email alerts, real provider-outage drill. Check/round/draw event
   adapters already exist; do not re-list those as unimplemented.
7. **Replays/logs/privacy:** authorized HTTP replay/log delivery, object storage,
   short-lived URLs and browser player (DEC-10), scheduled purge and vault
   backups/restore; replay indicator-text exposure review; durable log storage,
   retention and audit/notification visibility. Current redaction is best effort
   and limited to match logs; no complete end-to-end privacy verification.
8. **Website and launch:** every participant/Organizer/Admin screen, dashboard,
   bracket/results/replay view and coin-flip display; design/accessibility/
   usability; cross-role HTTP security tests; capacity/load/outage/concurrency
   tests, multi-host design, backups/recovery drill, deployment environments/TLS,
   CI matrix and real-engine tests, runbooks, pilot and go-live sign-off. Cold
   clone setup still needs evidence; no release dates before the benchmark.
9. **Owner/legal and deferred work:** written Battlecode Java-engine license
   clarification, copyright holder, participant terms, network source offer;
   review proposed Jira numbering/mapping and create actual tracker issues;
   decide whether to update the local client pin (1.0.6) separately. P2 remains
   landing page, live viewing, other languages/multi-file/custom dependencies,
   advanced analytics, disputes and extra admin tools.

## Decision register and next work

The proposed React/TypeScript + Django/DRF + PostgreSQL + Celery/Redis +
S3-compatible stack is **not approved**. **DEC-11 / BIO-401** unlocks the backend.
The **BIO-406 contract gap** now has a reviewable documentation proposal
(CN-026); user/role/assignment persistence, policies and HTTP implementation
remain open. The next independent engineering candidate is **BIO-409 service
wiring** on current stores (interim; production persistence still depends on
BIO-403). Account deletion requires DEC-07; API implementation requires DEC-11.
Review the CN-026 proposal and settle role cardinality/composition and initial
Admin/staff provisioning before implementing BIO-406.

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
| DEC-08, DEC-09 | Separate config-freeze deadline undecided; live viewing deferred |
| DEC-10, DEC-11 | Replay browser support and production stack/hosting/email/storage unresolved |
| DEC-12, DEC-13 | Team edits/size/captain policy and recovery/disputes/retention unresolved |

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
| [CHANGE_NOTICES.md](CHANGE_NOTICES.md) | CN-001–026 decisions, corrections, defaults, proposals and test evidence |
| [API_CONTRACT.md](API_CONTRACT.md), [DATA_MODEL.md](DATA_MODEL.md) | Proposed API, entities, constraints, state/access/retention matrices |
| [APP_FLOW.md](APP_FLOW.md), [../PRODUCT.md](../PRODUCT.md) | User journeys, route inventory, product context; planned screens |
| [ARCHITECTURE.md](ARCHITECTURE.md), [TECHNICAL_DOCUMENTATION.md](TECHNICAL_DOCUMENTATION.md) | Design boundaries, runner/worker mechanics, commands and troubleshooting |
| [PROJECT_PLAN.md](PROJECT_PLAN.md), [JIRA_BREAKDOWN.md](JIRA_BREAKDOWN.md), [REQUIREMENTS_COVERAGE.md](REQUIREMENTS_COVERAGE.md) | Roadmap, dependencies and evidence-based completion |
| [TEST_PLAN.md](TEST_PLAN.md), [SECURITY_REVIEW.md](SECURITY_REVIEW.md), [BOT_POLICY.md](BOT_POLICY.md) | Acceptance gates, self-review residuals, actual bot contract |
| [USER_GUIDE.md](USER_GUIDE.md), [ADMIN_GUIDE.md](ADMIN_GUIDE.md) | Planned product behavior; no functioning website is implied |
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
the exact remaining gap. No implementation requirement changed during intake
or the BIO-406 documentation slice. The user/role/Organizer-assignment contract
is no longer absent; it is proposed in API_CONTRACT §2.1–2.3, not implemented.
