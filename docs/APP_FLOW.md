# Battle It Out --- Application Flow

**Version:** 1.0\
**Status:** Functional flow baseline\
**Date:** 2026-11-04

## 1. Entry points

1.  **Local developer entry:** repository checkout and scaffold setup.
    This is the first delivery surface; no website is required for Phase
    1--3.
2.  **Participant entry:** invitation-based registration using official
    roster email and single-use code.
3.  **Organizer entry:** authenticated dashboard; access limited to
    assigned tournaments.
4.  **Admin entry:** authenticated global administration dashboard.
5.  **Notification entry:** email link or in-app dashboard notification
    opens the relevant tournament, submission, match, or administrative
    record after authorization.

Anonymous public browsing is not assumed for tournament results. The
landing page is deferred.

## 2. Detailed happy paths

### FLOW-01 --- Developer sets up scaffold and runs a bot

**Jira:** BIO-EPIC-00 / BIO-EPIC-01

1.  Developer clones/opens `battlecode26-scaffold`.
2.  Developer checks documented supported OS, Python version,
    Java/Gradle requirements.
3.  Setup script creates isolated environment and installs pinned
    dependencies.
4.  Setup verifies Python 3.13 compatibility.
5.  Developer runs scaffold smoke test.
6.  Developer runs reference Python bot against itself or another
    reference bot.
7.  Developer inspects match result/log/replay.
8.  Developer runs existing Java local baseline to detect regressions.

**Success state:** reproducible environment; engine executes Python
bots; version report is generated.

**Error states:** - Unsupported Python version → stop with required
version and setup guidance. - Dependency resolution failure → show
package/version conflict and preserve logs. - Engine/client mismatch →
fail fast with version report; do not silently download an unpinned
version. - Missing runner entrypoint → report the exact incompatible
import/API surface. - Match failure → classify bot failure versus
engine/platform failure.

**Edge cases:** - Fresh machine with no global packages. - Python 3.13
interpreter exists but dependency is incompatible. - User has stale
virtual environment. - Java baseline works while Python runner fails. -
Worker is interrupted during match.

### FLOW-02 --- Admin/Organizer creates tournament

**Jira:** BIO-EPIC-06

1.  Admin or Organizer opens tournament management.
2.  User creates draft with name, description, and independent
    registration/submission deadlines.
3.  Organizer reviews configuration and submits for approval.
4.  Admin sees pending approval queue.
5.  Admin approves or rejects with reason.
6.  If rejected, Organizer sees reason, edits draft, and resubmits.
7.  Once approved, tournament becomes eligible for
    publication/registration.
8.  Assigned Organizer manages permitted settings until relevant
    deadlines.

**Success state:** approved tournament is available to authorized
participants when registration opens.

**Error states:** - Organizer tries to publish before approval → block
and show pending approval. - Unassigned Organizer opens tournament →
deny access. - Missing/invalid deadline → field-level validation. -
Post-deadline setting change → require Admin deadline extension or
emergency override. - Rejection without reason → reject request as
invalid.

**Edge cases:** - Admin creates own tournament (no Organizer approval
queue required). - Two staff members edit simultaneously → optimistic
concurrency conflict; reload latest. - Approval occurs after intended
registration date → require Admin to correct dates before opening. -
Emergency override is used → reason, audit, and participant notification
required.

### FLOW-03 --- Roster import and invitation registration

**Jira:** BIO-EPIC-05

1.  Admin/assigned Organizer imports official roster.
2.  System validates rows and shows import summary.
3.  Staff corrects unregistered roster entries.
4.  System issues unique single-use invitation codes. `[DECIDE]` whether
    code is per participant or team; recommended per participant.
5.  Participant opens registration entry point.
6.  Participant enters official email and code and creates account.
7.  System checks email/code against roster and deadline.
8.  Participant verifies email.
9.  System marks registration complete and locks email, team assignment,
    member number, and role.
10. Participant lands on team dashboard.

**Success state:** participant is registered and associated with the
official team.

**Error states:** - Unknown email → generic roster mismatch message;
code remains unused. - Invalid code → retry allowed; code not
consumed. - Expired/revoked/used code → explain that code is no longer
valid and direct participant to Organizer/Admin support without exposing
code status to an attacker. - Registration closed → block new
registration. - Email verification expired → allow safe resend flow
`[DECIDE]`. - Duplicate account → guide login/recovery; do not create
duplicate membership.

**Edge cases:** - Registration deadline extended: unused codes remain
valid until new deadline; notify affected participants. - Registration
closes with incomplete signup/verification: participant excluded. -
Staff attempts to edit roster after successful registration: reject
normal edit; any correction policy requires Admin exception
`[DECIDE]`. - Lost/compromised code: only Admin revokes and replaces. -
Invalid attempts: do not consume code or permanently lock legitimate
participant; apply abuse protection without blocking ordinary retries.

### FLOW-04 --- Participant submits bot

**Jira:** BIO-EPIC-05

1.  Participant opens own team submission page.
2.  UI displays submission deadline, current active version, validation
    state, and history.
3.  Participant selects one file named exactly `bot.py`.
4.  Server checks authorization, deadline, file name/type/size, and
    single-file policy.
5.  Validator runs syntax/import/entrypoint/runtime checks in a
    controlled environment.
6.  If valid, version is saved immutably and becomes active.
7.  If invalid, version is retained as rejected history (subject to
    retention policy), error is shown, and prior active version remains
    active.
8.  Participant may upload another version before deadline.
9.  At deadline, submission endpoint locks.
10. Admin extension reopens submissions and notifies affected
    participants.

**Success state:** latest valid submission is active and can be selected
for future matches.

**Error states:** - Wrong filename/ZIP/multiple files → reject. -
Syntax/import/entrypoint failure → show safe validation report. - Upload
after deadline → reject with deadline details. - Unauthorized team
upload → deny. - Worker/validator outage → mark as infrastructure
failure, not bot invalidity; allow safe retry. - Invalid replacement →
keep previous active version.

**Edge cases:** - Two uploads race → serialize version
allocation/activation. - Duplicate request retries → idempotency
prevents duplicate versions. - Deadline passes while validation is
running → define whether upload timestamp or validation completion
controls eligibility `[DECIDE]`; recommended accepted upload timestamp
before deadline may finish validation after deadline. - Match starts
while new submission is validating → match uses already-active immutable
version.

### FLOW-05 --- Organizer runs a tournament round

**Jira:** BIO-EPIC-03 / BIO-EPIC-06

1.  Organizer opens assigned tournament control panel.
2.  System displays round readiness, active bracket, eligible teams, and
    active bot versions.
3.  Organizer starts the round.
4.  System queues matches in sequential order.
5.  Worker launches each match with exact map, bot versions,
    engine/runtime version, seed, and resource profile.
6.  On completion, system records result and replay, then advances
    winner.
7.  Next match starts automatically within the round.
8.  When all round matches are complete, system marks round complete and
    waits for Organizer to start next round.
9.  Organizer reviews round summary and starts next round.

**Success state:** round completes sequentially and bracket advances
exactly once per match.

**Error states:** - Round not ready (missing active bot/map/slot) →
block start with actionable reason. - Organizer not assigned → deny. -
Bot crash/timeout/limit breach → bot loses; opponent advances. -
Engine/platform failure → retry same map and bot versions with new
seed. - Retry cap reached → alert Admin and pause affected match for
intervention `[DECIDE]`. - Duplicate start click → idempotent response;
do not duplicate matches.

**Edge cases:** - Odd number of teams → automatic bye. - Human vs
house-bot slot → apply approved house-bot rules; house bot cannot
champion. - Normal tie → run one tie-break map. - Final tie → run three
tie-break maps sequentially. - Remaining tie → automatic 50/50 coin
flip, display and log. - Match completion event delivered twice → only
one result/advancement.

### FLOW-06 --- Participant views result and replay

**Jira:** BIO-EPIC-07

1.  Participant opens tournament dashboard or match-result notification.
2.  System checks tournament registration/access.
3.  Participant sees match result, bracket progression, scores, and
    tie-resolution details.
4.  If replay exists and tournament is not archived, participant may
    view/download it.
5.  After archive, replay link is unavailable; historical result
    remains.

**Success state:** participant sees authorized tournament history and
replay only while retained.

**Error states:** - Not registered/authorized → deny or return safe
not-found. - Replay missing before archive due to processing failure →
show unavailable state and create staff incident. - Tournament archived
→ show "Replay no longer available"; preserve result details. -
Tournament permanently deleted → operational tournament content
unavailable; audit retained for authorized Admin.

### FLOW-07 --- Account deletion

**Jira:** BIO-EPIC-05 / BIO-EPIC-06

1.  Participant opens account settings and requests deletion.
2.  System checks whether team is actively competing.
3.  If active, request enters queued state and shows expected trigger
    condition.
4.  Participant may cancel while queued.
5.  Once team is eliminated or tournament ends, deletion is
    scheduled/executed according to retention policy.
6.  User is removed from historical team roster display entirely.
7.  If user was captain, captaincy transfers to next eligible member.
8.  Match results, scores, brackets, and standings remain unchanged.

**Success state:** account deletion completes without rewriting
competition outcomes.

**Error states:** - Request cannot be processed due to active
competition → queue, do not immediately delete. - User attempts
cancellation after execution → reject. - No eligible successor for
captaincy → apply unresolved policy `[DECIDE]`; do not silently
disqualify team.

### FLOW-08 --- Archive/delete team or tournament

**Jira:** BIO-EPIC-06

**Team deletion:** 1. Tournament is archived. 2. Admin or assigned
Organizer opens team management. 3. User selects delete, confirms, and
provides mandatory reason. 4. System removes active team
profile/management access; historical results and audit logs remain. 5.
Admin may restore team while tournament still exists.

**Tournament archive:** 1. Authorized staff archives completed
tournament. 2. System deletes replay binaries and records purge
completion. 3. Results, brackets, standings, and match history remain
visible to authenticated authorized users.

**Permanent tournament deletion:** 1. Admin opens destructive action. 2.
UI clearly lists irreversible impact. 3. Admin confirms and enters
mandatory reason. 4. System deletes associated operational
tournament/team data. 5. Audit logs remain permanently.

## 3. Error-state and edge-case matrix

  -----------------------------------------------------------------------
  Condition               System behavior         User feedback / audit
  ----------------------- ----------------------- -----------------------
  Invalid invitation      Do not consume code;    Safe error message;
  email/code              permit retry.           abuse protection; log
                                                  security event without
                                                  raw code.

  Registration deadline   Reject new              Show close time and
  closed                  registration.           support route.

  Deadline extended       Preserve unused         Email + dashboard
                          codes/reopen            notification.
                          submissions as          
                          applicable.             

  Invalid bot upload      Reject and preserve     Validation reason and
                          previous active         history entry.
                          version.                

  Bot crashes/overruns    Automatic               Match result and safe
                          loss/elimination.       logs; no retry.

  Platform/engine crash   Retry with same map/bot Operational incident
                          versions and new seed.  log.

  Retry cap exhausted     Stop automatic retry    Admin incident;
                          and alert Admin.        participant-facing
                                                  state remains clear.

  Match tie               Execute configured      Publicly visible result
                          tie-break map(s), then  and audit.
                          coin flip if still      
                          tied.                   

  Organizer changes       Deny.                   Explain Admin
  locked setting                                  extension/override
                                                  process.

  Emergency Admin         Apply permitted         Mandatory reason,
  override                override.               audit, participant
                                                  notification.

  Archive                 Delete replay binaries  Results/history remain;
                          only.                   replay unavailable.

  Permanent tournament    Remove operational      Confirmation/reason;
  delete                  tournament data.        audit remains.
  -----------------------------------------------------------------------

## 4. Navigation map

``` text
Local Engineering
  └── Repository
      ├── Environment Setup
      ├── Scaffold Smoke Test
      ├── Python Bot Validation
      ├── Local Match Runner
      └── Match Logs / Replay

Authenticated Web App (later phase)
  ├── Sign in
  ├── Participant
  │   ├── Dashboard
  │   ├── My Team
  │   ├── Bot Submission
  │   │   ├── Upload
  │   │   ├── Validation Result
  │   │   └── Version History
  │   ├── Tournament
  │   │   ├── Overview
  │   │   ├── Bracket / Results
  │   │   ├── Match Detail
  │   │   └── Replay (until archive)
  │   ├── Notifications
  │   ├── Relevant Audit History
  │   └── Account / Deletion Request
  ├── Organizer (assigned tournaments)
  │   ├── Organizer Dashboard
  │   ├── Create Tournament
  │   ├── Approval Status
  │   ├── Roster Import / Correction
  │   ├── Tournament Settings / Deadlines
  │   ├── Bracket / Round Controls
  │   ├── Team Source Viewer (read/download only)
  │   ├── Team Archive/Delete
  │   └── Assigned Audit Logs
  └── Admin
      ├── Global Dashboard
      ├── Tournament Approval Queue
      ├── All Tournaments
      ├── User / Role / Organizer Assignment
      ├── Invitation Revocation / Replacement
      ├── Deadline Extension / Emergency Override
      ├── System Incidents / Worker Health
      ├── Team Restore
      ├── Permanent Tournament Deletion
      └── Global Audit Logs
```

## 5. Screen / route inventory (web phase)

  ---------------------------------------------------------------------------------------------------------------------------
  Route                                     Access          Purpose                Main UI/actions     Key states
  ----------------------------------------- --------------- ---------------------- ------------------- ----------------------
  `/login`                                  Public          Authenticate           Email/password,     Idle, invalid
                                                                                   login               credentials, rate
                                                                                                       limited

  `/register`                               Public with     Participant            Email, code,        Invalid code, pending
                                            invite          registration           password,           verification,
                                                                                   verification        complete, closed

  `/dashboard`                              Authenticated   Role-specific landing  Tournament cards,   Empty, active,
                                                                                   alerts              archived

  `/participant/team`                       Participant     Team overview          Roster, team info   Active, eliminated,
                                                                                                       archived

  `/participant/submissions`                Participant     Bot upload/history     Upload `bot.py`,    No submission,
                                                                                   view versions       validating, valid,
                                                                                                       invalid, locked

  `/participant/tournaments/{id}`           Registered      Tournament overview    Status, deadlines,  Registration, running,
                                            participant                            notices             completed, archived

  `/participant/tournaments/{id}/bracket`   Authorized      Bracket/results        Bracket, scores,    Pending, in progress,
                                            participant                            match links         complete

  `/matches/{id}`                           Authorized      Match detail           Result, tie-breaks, Scheduled, running,
                                            tournament user                        logs                completed,
                                                                                                       failed/retrying

  `/matches/{id}/replay`                    Authorized user Replay                 Player/download     Available, processing,
                                            before archive  playback/download                          archived/unavailable

  `/notifications`                          Authenticated   Dashboard notification Read/unread         Empty, unread,
                                                            feed                                       delivery issue

  `/account/settings`                       Authenticated   Preferences/deletion   Email toggle,       Active, queued,
                                                                                   deletion request    cancelled

  `/organizer`                              Organizer       Assigned tournament    Open/create         Empty, pending, active
                                                            list                   tournament          

  `/organizer/tournaments/new`              Organizer       Create draft           Tournament form     Draft, validation
                                                                                                       error

  `/organizer/tournaments/{id}`             Assigned        Manage tournament      Overview/settings   Pending approval,
                                            Organizer                                                  rejected, approved,
                                                                                                       locked

  `/organizer/tournaments/{id}/roster`      Assigned        Import/correct roster  Import, edit        Import errors, locked
                                            Organizer                              unlocked rows       entries

  `/organizer/tournaments/{id}/rounds`      Assigned        Start/manage rounds    Start round, view   Not ready, ready,
                                            Organizer                              progress            running, complete

  `/organizer/tournaments/{id}/teams`       Assigned        Team administration    View/download       Active, archived,
                                            Organizer                              source; delete      deleted
                                                                                   after archive       

  `/admin`                                  Admin           Global operations      Global status,      Healthy, warning,
                                                                                   incidents           incident

  `/admin/approvals`                        Admin           Review Organizer       Approve/reject with Pending, approved,
                                                            tournaments            reason              rejected

  `/admin/tournaments/{id}`                 Admin           Full tournament        Settings,           Active, locked,
                                                            management             deadlines,          archived
                                                                                   overrides           

  `/admin/invitations`                      Admin           Revoke/replace         Revoke, replace     Active, consumed,
                                                            compromised codes                          expired, revoked

  `/admin/audit`                            Admin           Global audit           Filter/search       Empty, results
  ---------------------------------------------------------------------------------------------------------------------------

## 6. Decision points (IF--THEN)

-   **IF** an Organizer creates a tournament, **THEN** it remains
    unavailable for registration until Admin approval.
-   **IF** Admin rejects it, **THEN** rejection reason is mandatory and
    Organizer may edit/resubmit.
-   **IF** participant email/code is invalid, **THEN** do not consume
    code and allow retry.
-   **IF** registration succeeds, **THEN** lock email, team, member
    number, and role.
-   **IF** registration deadline is extended, **THEN** preserve unused
    codes until new deadline and notify affected participants.
-   **IF** a bot upload is invalid, **THEN** reject it and keep prior
    active version.
-   **IF** a new valid bot is uploaded before deadline, **THEN** make it
    active and preserve prior version history.
-   **IF** submission deadline closes, **THEN** lock uploads until Admin
    extends it.
-   **IF** a bot crashes or exceeds a resource limit, **THEN** award
    automatic loss and do not retry.
-   **IF** engine/platform fails, **THEN** retry with same map and bot
    versions but new seed.
-   **IF** platform failures reach retry cap, **THEN** stop and alert
    Admin.
-   **IF** a normal match ties, **THEN** run one tie-break map.
-   **IF** a final ties, **THEN** run three tie-break maps sequentially.
-   **IF** still tied, **THEN** run and publish/log a 50/50 coin flip.
-   **IF** qualification cutoff is tied, **THEN** automatically draw
    among tied teams for remaining slots after scores/slots finalize.
-   **IF** team is actively competing when participant requests account
    deletion, **THEN** queue deletion and allow cancellation.
-   **IF** tournament is archived, **THEN** delete replay files but
    preserve results/brackets/standings/history.
-   **IF** archived team is deleted, **THEN** preserve historical
    results/audit and allow Admin restoration.
-   **IF** tournament is permanently deleted, **THEN** only Admin may
    perform it with confirmation/reason; operational data is removed and
    audit retained.
-   **IF** user disables email notifications, **THEN** dashboard
    notifications remain mandatory.
-   **IF** Organizer attempts Admin-only action, **THEN** deny
    server-side and log the attempt where appropriate.

## 7. UX and accessibility notes

-   Display registration and submission deadlines with timezone.
-   Distinguish "uploaded", "validating", "valid/active", "invalid", and
    "locked".
-   Explain why a bot failed without exposing host secrets or other
    team's code.
-   Clearly distinguish bot loss from platform retry.
-   Display tie-break sequence and coin-flip result transparently.
-   Destructive actions require a clear confirmation step and reason
    field.
-   Do not rely on disabled buttons alone for authorization; server must
    enforce every permission.
-   Use plain-language onboarding and explain the one-file Python
    submission contract.
-   Landing page and public marketing content are later-phase
    deliverables.

## 8. Unresolved flow decisions

-   `[DECIDE]` Exact invitation code granularity.
-   `[DECIDE]` Captain-only or all-team-member upload.
-   `[DECIDE]` Manual versus scheduled tournament registration opening.
-   `[DECIDE]` Whether upload timestamp or validation completion
    determines deadline eligibility when validation straddles deadline.
-   `[DECIDE]` Retry cap interpretation and post-cap match state.
-   `[DECIDE]` House-bot bracket algorithm.
-   `[DECIDE]` Replay format/player and live viewing.
-   `[DECIDE]` No-successor captain deletion behavior.
-   `[DECIDE]` Account recovery, resend verification, and dispute flows.

## 9. Reusable implementation prompt

Implement the flow for the current Jira story only. Follow the happy
path, error states, edge cases, and decision rules in this document.
Enforce access on the server, not only in navigation/UI. Keep
participant source code private. Preserve the rule that the execution
scaffold and bot runner come before the landing page. If a required
behavior is marked `[DECIDE]`, pause and request a decision rather than
inventing it.
