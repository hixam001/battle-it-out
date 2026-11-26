# Battle It Out --- Test Plan

**Version:** 1.3 (BIO-404 HTTP boundary regressions; CN-029)\
**Status:** Baseline test strategy\
**Date:** 2026-11-26

> **Owner change notice (2026-11-24):** the Python runtime target is now the latest stable CPython (3.15.2 tested; 3.13 remains in the matrix) Java bots are removed (the Java engine server stays), the project license is AGPL-3.0 (same as the Battlecode scaffold) and the bot rules are the engine's own (imports `random`, `math`, `enum`, `battlecode26` only; this replaces any "standard library" wording). See [`CHANGE_NOTICES.md`](CHANGE_NOTICES.md) CN-001 to CN-004. The text below is unchanged.

## 1. Test objectives

Prove that the Battlecode scaffold is reproducible, Python 3.13
compatibility is real, participant bots execute safely, bot failures are
separated from platform failures, tournament rules are
deterministic/auditable, and role/privacy/deadline rules cannot be
bypassed.

Testing begins with local engine/runtime tests. Web/API testing follows
only after the execution foundation passes.

## 2. Test environment

### Required environments

-   Clean Linux development environment matching the agreed supported
    OS.
-   Approved Python 3.13 patch release.
-   Pinned Battlecode engine/client/package versions.
-   Isolated worker image matching production.
-   Test database, queue, object storage emulator or staging bucket, and
    email sandbox for later phases.

### Test fixtures

-   Reference/example Python bot.
-   Minimal valid `bot.py`.
-   Syntax-invalid bot.
-   Missing/incorrect entrypoint bot.
-   Import-failing bot.
-   Bot that crashes during execution.
-   Bot that intentionally exceeds time limit.
-   Bot that exceeds memory/instruction limit.
-   Bot that completes normally.
-   Simulated engine/worker failure.
-   Two teams with known bot versions and maps.
-   Fixture tournaments for normal round, final, qualification cutoff
    tie, archive, and deletion.

### Version evidence

Record exact Python, engine, client, package, OS, worker image digest,
and dependency versions in each test report. Never report "Python 3.13
compatible" based only on local interpreter availability.

## 3. Critical test cases (8)

### TC-01 --- Clean scaffold install and Python 3.13 compatibility

**Jira:** BIO-101 / BIO-102\
**Priority:** P0\
**Steps:** 1. Start from a clean checkout and clean environment. 2.
Install using documented setup instructions. 3. Verify pinned
interpreter and package versions. 4. Run scaffold smoke tests and
reference Python bot. 5. Run Java local baseline to ensure existing
engine behavior was not broken. **Expected:** - No reliance on a
developer's global packages. - Setup completes from documented
commands. - Python 3.13 runtime starts the Python bot successfully. -
Engine/client/package versions match approved matrix. - Existing Java
baseline still runs. - Any incompatible dependency is identified and
pinned/replaced with evidence.

### TC-02 --- Single-file bot validation and version activation

**Jira:** BIO-202 / BIO-EPIC-05\
**Priority:** P0\
**Steps:** 1. Upload valid `bot.py`. 2. Upload wrong filename, ZIP,
syntax-invalid file, missing entrypoint, and import-failing file. 3.
Upload a valid replacement. 4. Upload an invalid replacement after a
valid version is active. **Expected:** - Only one file named exactly
`bot.py` is accepted. - Invalid files are rejected with actionable
reason. - Valid submission becomes active. - Latest valid version
supersedes previous valid version. - Invalid replacement never replaces
active version. - Every version and validation outcome remains in
history.

### TC-03 --- Two-bot match and resource enforcement

**Jira:** BIO-203 / BIO-204 / BIO-205\
**Priority:** P0\
**Steps:** 1. Launch two independent valid bot submissions through the
actual engine. 2. Record exact bot versions, map, seed, engine/runtime,
and resource measurements. 3. Run bots that exceed each configured
resource limit. **Expected:** - Valid bots complete a match. - Each bot
is isolated from the other and host services. - Global
time/memory/instruction limits are enforced. - Limit breach is
classified as bot failure and produces automatic loss. - Numeric limits
are documented only after benchmark approval.

### TC-04 --- Bot failure versus platform failure

**Jira:** BIO-205 / BIO-306\
**Priority:** P0\
**Steps:** 1. Inject bot crash, timeout, and instruction-limit
violation. 2. Inject engine crash, worker crash, and infrastructure
error. 3. Observe match state and retry behavior. **Expected:** -
Bot-caused failure produces automatic loss; no rematch/platform retry. -
Platform failure is classified separately. - Platform retry preserves
map and exact bot versions but uses a new random seed. - Retry cap is
enforced and Admin alert is created. - Duplicate job delivery does not
duplicate result or bracket advancement.

### TC-05 --- Match automation, tie-breaks, and bracket progression

**Jira:** BIO-301 / BIO-302 / BIO-303 / BIO-304\
**Priority:** P0\
**Steps:** 1. Generate bracket with an odd and even number of human
teams. 2. Include house-bot filler scenarios. 3. Start round and allow
sequential matches to complete. 4. Force a normal-stage tie and a final
tie. 5. Force qualification cutoff tie. **Expected:** - Pairings and
automatic byes follow approved rules. - Human teams receive bye
priority. - House bots cannot become champions or advance as human
teams. - Normal tie invokes one tie-break map. - Final tie invokes three
tie-break maps sequentially. - Remaining tie invokes automatic 50/50
coin flip, visibly recorded and audited. - Qualification draw occurs
only after scores/slots finalized; displayed and logged. - Winners
advance exactly once.

### TC-06 --- Registration, invitations, and deadline transitions

**Jira:** BIO-EPIC-05 / BIO-EPIC-06\
**Priority:** P1\
**Steps:** 1. Import official roster. 2. Attempt registration with
unknown email, invalid code, expired code, and valid code. 3. Retry with
correct details after invalid attempt. 4. Complete verification and
registration. 5. Extend registration deadline and test unused code. 6.
Attempt registration after final close. **Expected:** - Only official
email/code pair succeeds. - Invalid attempt does not consume code or
permanently block user. - Successful registration locks
email/team/member number/role. - Unused codes expire at close; extension
preserves them until new deadline. - Incomplete registrations are
excluded at deadline. - Only Admin can revoke/replace compromised code.

### TC-07 --- Permissions, privacy, audit, and deletion

**Jira:** BIO-EPIC-04 / BIO-EPIC-05 / BIO-EPIC-06\
**Priority:** P0\
**Steps:** 1. Test Admin, assigned Organizer, unassigned Organizer,
participant, and unrelated participant. 2. Attempt cross-tournament
access and source-code downloads. 3. Attempt Organizer source
modification and invitation replacement. 4. Request account deletion
while team active; cancel; request again and execute after team is
inactive. 5. Delete/restore archived team and permanently delete
tournament. **Expected:** - Every operation respects role and tournament
scope. - Other teams' source code is never accessible to participants. -
Organizer may download assigned source but cannot alter/activate it. -
Only Admin revokes/replaces code, restores team, and permanently deletes
tournament. - Queued deletion can be cancelled; deleted participant is
removed from historical roster display. - Results/brackets/standings
remain unchanged by participant/team deletion. - Audit logs are
immutable and retained after tournament deletion.

#### TC-07 access-control contract cases --- BIO-406 / BIO-410

**Planned, not executed:** these check the proposed API_CONTRACT §2.1–2.3
after DEC-11, the role-cardinality policy and CN-026 choices are resolved.
Documentation checks cannot satisfy the API permission exit gate.

| Case | Request / setup | Expected result |
|---|---|---|
| AC-01 | Anonymous requests to every user/role/assignment route | `401`; no directory or assignment data |
| AC-02 | Admin lists/reads users and roles; Organizer/participant tries the same with known and unknown user IDs | Admin sees only documented summary fields; non-Admins always get `403` before target lookup; own profile stays on `/me` |
| AC-03 | Client adds role, scope, captain flags or grant-author fields to public registration, profile or assignment bodies | Rejected; no staff grant, membership or caller-controlled `Actor` |
| AC-04 | Admin grants a legal role set, including a same-role no-op and an identical idempotent retry | One effective transition/audit event at most; stable revision on no-op; roster locks and membership unchanged |
| AC-05 | Unknown/duplicate roles, illegal role combination under the chosen policy, unverified/suspended/deleted target, stale revision, missing reason/confirmation, or changed payload under the same key | `400` or `409` per contract, no partial grant or audit; exact status selected by the documented validation category |
| AC-06 | Concurrent Admin removals that would leave no active Admin | One must conflict; last-active-Admin invariant survives concurrency |
| AC-07 | Admin assigns an eligible Organizer; retries; revokes; reassigns | One active pair, no duplicate event on no-op/retry, increasing collection revision on changes, new ID after revocation |
| AC-08 | Unassigned Organizer guesses a tournament; participant lists assignments; assigned Organizer attempts assignment writes | Hidden/missing tournament both `404`; visible but forbidden operation `403`; no email/profile expansion |
| AC-09 | Assignment ID from another tournament; Admin assigns an ineligible account or deleted tournament | Cross-tournament child `404`; ineligible/deleted state `409`; no new assignment |
| AC-10 | Revoke creator assignment, then use old session/token or idempotency key to edit/resubmit or download source | Denied by current scope; `created_by`, cached claims and stored responses cannot restore authority |
| AC-11 | Remove Organizer role while assignment creation races; later restore role | No effective assignment survives removal; relevant revisions advance; no old assignment revives; current authorization checked at mutation commit |
| AC-12 | Build participant Actor from unverified claim, verified member, captain, and unrelated team | Only verified membership supplies scope; only the current captain can upload under the interim default; no unrelated source access |
| AC-13 | Fail audit/outbox persistence during role/assignment mutation, then retry; delete tournament afterward | No unaudited committed change; at most one transition/event; redacted permanent audit survives tournament deletion |
| AC-14 | Assigned Organizer reads source then attempts upload/activation, code replacement or approval | Read is allowed and staff source read audited; forbidden mutation remains forbidden despite assignment |

### TC-08 --- Replay, notifications, archive, and recovery

**Jira:** BIO-305 / BIO-EPIC-06 / BIO-EPIC-08\
**Priority:** P1\
**Steps:** 1. Complete matches and generate replay artifacts. 2. Verify
replay access for authorized tournament users and denial for
unauthorized users. 3. Disable participant email preference and trigger
match result/deadline events. 4. Archive tournament. 5. Verify replay
deletion and historical result visibility. 6. Simulate notification
delivery failure and restore from backup in staging. **Expected:** -
Replay works for authorized users before archive. - Archive deletes
replay binaries; no role can recover them. - Match results, brackets,
standings, and match history remain visible to authorized signed-in
users. - Dashboard notifications are created regardless of email
preference. - Email delivery follows preference and retries failures. -
Backup/restore procedure recovers critical state without corrupting
match references.

#### Implemented notification HTTP subset (BIO-607 / CN-030)

`backend.webapp.tests_notifications` runs 17 cases with real PostgreSQL accounts
and temporary legacy notification/registration state:

- Recipient-only feeds and read/unread mutation: another team and a same-team
  member's notice have the same `404` as a missing ID. Staff privileges do not
  grant inbox access. Explicit participant links prevent numeric Django/roster
  ID collisions; removing the link takes effect on the next read/write.
- Bounded offset pages, equal-time ordering, tournament/unread filters and
  counts, empty unknown-tournament results, rejection of malformed/duplicate/
  unknown query parameters, and omission of provider/recipient/internal fields.
- Absolute-state read/unread and email-preference retries preserve timestamps
  and avoid duplicate audit; a failed preference audit rolls back the write.
  Dashboard-disable attempts, non-booleans, identity injection, invalid JSON
  and unsupported media are refused without changing state.
- Real login/session CSRF on both PATCH routes, successful token-bearing
  mutations, anonymous/deactivated denial, method errors and no-store/request-ID
  envelopes. Historical personal notices remain readable without tournament
  scope.
- HTTP-disabled email is seen by a fresh service runtime, which skips queued
  deliveries; new roster-derived team notices still appear once in the feed.
  Injected provider failure leaves dashboard notices intact.

This does not close full TC-08: no real provider, notification UI, production
outage or backup/restore drill is exercised. Staff recipients, announcement and
automatic deadline/override endpoints, and notification-store migration remain
open. Web tests require explicit module labels in the webapp README; the backend
execution runner does not discover these modules.

## 4. Additional test categories

### Unit tests

-   Deadline state transitions.
-   Invitation code validation and consumption.
-   Submission validation and active-version selection.
-   Role/scope policy functions.
-   Bracket advancement idempotency.
-   Tie-break map selection and coin-flip result recording.
-   Notification event generation.
-   Archive and deletion services.

### Integration tests

-   Python runner ↔ Battlecode engine.
-   API ↔ database.
-   API ↔ object storage.
-   Queue ↔ isolated worker.
-   Worker ↔ result/replay persistence.
-   Notification outbox ↔ email provider.

### Security tests

-   Path traversal and malicious filenames.
-   Archive/ZIP upload rejection.
-   Bot filesystem/network escape attempts.
-   CPU/memory exhaustion and process spawning abuse.
-   Secret/environment-variable exposure.
-   Cross-team/cross-tournament IDOR.
-   Unauthorized file download.
-   Rate limiting on login and invitation validation.
-   SQL injection/XSS/CSRF as applicable to selected auth model.
-   Audit tampering attempts.

### Reliability/load tests

-   Repeated matches on one worker.
-   Worker crash during match.
-   Queue redelivery and duplicate completion.
-   Multiple tournament queues and expected concurrent match load.
-   Database/Redis/object storage outage.
-   Notification provider outage.
-   Backup restore and replay purge job recovery.

## 5. Pre-demo checklist

### Scaffold / execution demo

-   [ ] Clean checkout and setup instructions work.
-   [ ] Python 3.13 patch version and package matrix recorded.
-   [ ] Reference Python bot starts.
-   [ ] Two independent Python bots complete a match.
-   [ ] Java baseline still runs.
-   [ ] Valid/invalid bot validation demonstrated.
-   [ ] Crash/timeout/limit failure classified correctly.
-   [ ] Platform failure retry uses same map/submissions and new seed.
-   [ ] Replay generated and readable.
-   [ ] No secret keys or personal data in repository/logs.

### Tournament demo

-   [ ] Bracket generated and matches run sequentially.
-   [ ] Bye and house-bot scenarios tested.
-   [ ] Normal tie uses one tie-break map.
-   [ ] Final tie uses three tie-break maps.
-   [ ] Coin flip and qualification draw are visible and logged.
-   [ ] Result advances winner exactly once.

### Web platform demo

-   [ ] Admin/Organizer/Participant accounts prepared.
-   [ ] Organizer approval flow works.
-   [ ] Roster and invitation registration works.
-   [ ] Submission history and privacy work.
-   [ ] Deadline extension notification works.
-   [ ] Dashboard notifications work with email disabled.
-   [ ] Archive removes replay files but preserves results.
-   [ ] Destructive actions require reason and confirmation.
-   [ ] Audit log is available only within role scope.

### Interim operations rehearsal (BIO-805 / CN-033)

The [operations runbook](OPERATIONS_RUNBOOK.md) records status triage,
incident escalation and staging restore steps for the current reference setup.
A disposable PostgreSQL and file-state restore verified fixture scope, source
digest, match/dispute references, notification preferences and archived vault
files. A local signing-key change invalidated an old session and accepted a
fresh CSRF login. The service lifecycle suite exercises real engine games,
purge recovery and injected send/alert failures. Target-host, provider and
production restore acceptance remain open.

## 6. Known limitations / unresolved test inputs

-   Python 3.13 compatibility is a target until TC-01 passes.
-   Exact engine runner API must be verified against repository source.
-   Numeric time, memory, and instruction limits are not yet approved;
    benchmark first.
-   Retry cap interpretation (10 total attempts vs 10 retries) is
    unresolved.
-   House-bot bracket algorithm needs exact acceptance examples.
-   Invitation code granularity and captain-only upload are unresolved.
-   Replay format and browser player support are unresolved.
-   Live match viewing is not confirmed.
-   Load/concurrency targets and upload-size cap are unresolved.
-   Account deletion anonymization must be reviewed against applicable
    privacy/legal requirements.

## 7. Defect severity and release gates

-   **Blocker:** bot isolation escape, cross-team source leak, wrong
    match winner, corrupt bracket advancement, audit tampering, or
    unbounded execution.
-   **Critical:** incorrect bot/platform failure classification,
    incorrect tie-break/coin-flip, unauthorized Admin-only action, data
    loss.
-   **Major:** deadline/invitation/submission behavior wrong,
    notifications missing, replay lifecycle wrong.
-   **Minor:** non-blocking UI/layout defects or wording.

**Release gate:** No production launch with open Blocker/Critical
defects. All P0 acceptance tests pass. Security and recovery tests pass.
Pilot tournament is completed and reviewed.

## 8. Reusable test prompt

Create tests for the current Jira issue using this plan. Include happy
path, invalid input, permission denial, retry/idempotency, and relevant
lifecycle transitions. For bot execution, use the actual Battlecode
engine and approved runtime image. Never mock the engine for the only
proof of Python 3.13 compatibility. Record versions, seed, bot
submission IDs, expected result, observed result, logs, and pass/fail
evidence. Do not claim a test passed unless it was run.


## 9. Activated feature verification — CN-028

BIO-REQ-19–23 are now active. The following evidence complements the original
TC-02/05/07/08 plan; it does not close the execution/production acceptance gates.

| Surface | Required verification / implemented checks |
|---|---|
| Python bundles | ZIP traversal/duplicates/symlinks/expansion limits; every module checked; curated exact versions; complete-digest verdict and pin binding; changed helper/dependency refusal; authorized reproducible export; real two-sided native-module engine trial |
| Private live board | Real board changes observed before completion; native schema only; no raw WebSocket listener; numeric allowlist/private file mode; baseline engine round/reason comparison; scope revoked on next poll; archived access denied and frame files purged |
| PostgreSQL API | Anonymous/foreign scope denial; current roster/assignment authority; staff source read audit; stored deadline/captain upload gate; CSRF/session and independent durable source/account login limits |
| Disputes | Team-private actual match reference; idempotent create; payload mismatch; optimistic conflict; staff-only transitions/reason; comments/closed-state behavior; result records unchanged; state/audit/receipt rollback; database rejection of audit-history changes |
| React | Production build/type check; desktop/mobile overflow and keyboard navigation; labeled illustration; real login, analytics/version/timing view, dispute/comment, submission catalogue, logout and Admin operations |

Use the documented package/backend runner plus the PostgreSQL-specific command:

```bash
backend/.venvs/py3.15/bin/python backend/run_tests.py
backend/.venvs/py3.15/bin/python backend/run_tests.py --integration
backend/.venvs/web/bin/python backend/webapp/manage.py test backend.webapp.tests backend.webapp.tests_http
npm run build --prefix frontend
npm test --prefix frontend
```

Browser tests require labeled disposable local fixture accounts and both local
servers. Database tests require PostgreSQL; SQLite is not equivalent evidence
for the history triggers. Real matches run sequentially and all output stays in
temporary directories. Other language runtimes, production deployment/load,
full browser replay playback, formal accessibility and independent security
review remain separate acceptance work.

## 10. HTTP boundary verification — BIO-404 / CN-029

The standalone `backend.webapp.tests_http` suite verifies the same JSON envelope
for Django and DRF errors, direct refusals and unknown routes; stable status/code
pairs; field errors/actionable validation; malformed JSON/media types; both CSRF
paths; `Allow`/`Retry-After`; fresh header/body IDs with incoming IDs ignored;
safe `404` and redacted server failures in debug and normal mode. Unexpected
exceptions must still reach Django logging. ID/status completion logs must not
copy private paths. Successful liveness must run without database access or
legacy-store initialization; HEAD returns no body. Non-API responses are outside
this middleware's scope.

The PostgreSQL feature suite adds real login/session-CSRF checks, identical
hidden/missing tournament errors, and idempotent `409` replay with a fresh ID
while the stored receipt and dispute state remain unchanged. Use the explicit
module labels above; directory discovery loses package context in this
repository's namespace layout. These web suites are separate from the execution
library runner. Database readiness, load, production monitoring and remaining
BIO-404 pagination/global idempotency/concurrency are not covered by liveness.
