# Battle It Out --- Test Plan

**Version:** 1.1 (Jira references aligned with PRD §10 ID scheme)\
**Status:** Baseline test strategy\
**Date:** 2026-11-05

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
