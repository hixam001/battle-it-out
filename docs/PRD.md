# Battle It Out --- Product Requirements Document (PRD)

**Project:** INNOFEST Battle It Out\
**Document status:** Working baseline for implementation planning\
**Version:** 1.0\
**Last updated:** 2026-11-04\
**Requirement notation:** Jira-style Epics/Stories, priorities, and
Given/When/Then acceptance criteria.

> **Decision discipline:** "Confirmed" means established in project
> discussions. "Proposed" means a recommended implementation approach
> that still needs approval. `[DECIDE]` marks an unresolved product or
> technical decision. Do not silently turn proposed choices into
> requirements.

## 1. Problem statement

INNOFEST needs a Battlecode-style programming competition platform in
which participants submit Python bots that compete automatically in a
controlled game environment. The competition should be approachable to
beginners, including participants using AI-assisted development, while
retaining enough strategic depth to challenge experienced programmers.

The immediate technical risk is not the public website: it is whether
the existing Battlecode 2026 scaffold can be adapted, run reproducibly,
and execute participant Python bots reliably. The project will therefore
prove the game runtime and tournament execution path before building the
landing page and participant-facing website.

The platform must also support controlled tournament administration,
invitation-based registration, private source-code handling, automated
match outcomes, transparent tie resolution, notifications, and durable
historical records.

## 2. Product goals (SMART)

  --------------------------------------------------------------------------
  ID                Priority          Goal                Target /
                                                          measurement
  ----------------- ----------------- ------------------- ------------------
  BIO-G01           P0                Establish a         A clean setup on
                                      reproducible        the agreed Python
                                      competition         3.13 environment
                                      scaffold compatible installs and runs
                                      with the target     the reference
                                      Python runtime.     Python bot and a
                                                          test bot without
                                                          manual patching.

  BIO-G02           P0                Execute participant Two independently
                                      Python bots safely  submitted `bot.py`
                                      and                 files complete a
                                      deterministically   match; crashes and
                                      enough for          resource-limit
                                      competition use.    violations are
                                                          classified as bot
                                                          losses; engine
                                                          failures are
                                                          distinguishable.

  BIO-G03           P0                Automate the        A test bracket can
                                      competition's match run sequentially,
                                      lifecycle.          record results,
                                                          advance winners,
                                                          apply tie-break
                                                          maps, and invoke
                                                          the final
                                                          coin-flip rule
                                                          when required.

  BIO-G04           P1                Provide controlled  Admin, Organizer,
                                      tournament,         and Participant
                                      registration, and   permission tests
                                      submission          pass for all
                                      management.         documented
                                                          critical
                                                          operations.

  BIO-G05           P1                Make competition    Participants
                                      outcomes and        receive dashboard
                                      important changes   notifications for
                                      visible and         major events;
                                      auditable.          email can be
                                                          disabled
                                                          independently;
                                                          audit records
                                                          remain immutable
                                                          and retained.
  --------------------------------------------------------------------------

## 3. Success metrics

1.  **Environment reproducibility:** 100% of clean-machine setup checks
    pass for the approved OS/Python/dependency matrix.
2.  **Match execution reliability:** At least 99% of valid test matches
    complete without platform-caused failure in the agreed pilot test
    set. `[DECIDE]` sample size and acceptance threshold after
    benchmarking.
3.  **Failure classification:** 100% of injected bot crashes, timeouts,
    instruction-limit violations, and platform failures are classified
    into the correct category in automated tests.
4.  **Permission correctness:** 100% pass rate across critical
    role/access-control tests, including source-code privacy and
    Admin-only operations.
5.  **Tournament integrity:** Every completed match references the exact
    bot versions, map, engine version, seed, result, and relevant
    execution logs needed for audit. Replay retention follows the
    archive policy.

## 4. Personas

### PERS-01 --- Participant / Team member

-   Wants to register using the official roster email and invitation
    code.
-   Wants a clear, beginner-friendly way to submit and validate one
    Python bot file.
-   Wants to test, replace, and track their own submissions before the
    deadline.
-   Wants to see their own match results, bracket progress,
    notifications, and available replays.
-   Must not access another team's source code.

### PERS-02 --- Tournament Organizer

-   Wants to create and manage assigned tournaments, edit approved
    tournament settings before lock, manage official imported rosters,
    and operate rounds.
-   Needs to inspect/download source code for teams in assigned
    tournaments.
-   Must not revoke/replace invitation codes, change participant-locked
    identity/team assignments, modify or activate participant
    submissions, or access unassigned tournaments.
-   Needs audit visibility for assigned tournaments.

### PERS-03 --- Platform Admin

-   Has global authority to approve/reject tournaments, manage all
    tournaments, handle compromised invitation codes, perform emergency
    overrides, restore deleted teams, and permanently delete
    tournaments.
-   Needs system-health visibility and incident alerts.
-   Must provide a reason for destructive actions and emergency
    overrides.

## 5. Scope and priorities

### P0 --- Critical execution foundation

-   \[BIO-101\] Audit the existing Battlecode 2026 repository, scaffold,
    engine, client, Python runner, and dependency compatibility.
-   \[BIO-102\] Make the scaffold reproducible and compatible with the
    approved Python 3.13 target.
-   \[BIO-103\] Execute a single-file Python bot (`bot.py`) using the
    supported Battlecode engine interface.
-   \[BIO-104\] Validate bot entrypoint, syntax, imports, and runtime
    compatibility before activation.
-   \[BIO-105\] Run two Python bots in an isolated execution environment
    with globally fixed resource limits.
-   \[BIO-106\] Distinguish bot-caused failures from platform/engine
    failures.
-   \[BIO-107\] Automate sequential matches, result capture, bracket
    advancement, tie-break maps, and final coin flip.
-   \[BIO-108\] Generate and retain match replay files until tournament
    archive; delete replay files at archive.
-   \[BIO-109\] Implement platform-failure retry policy: retry up to 10
    times, then alert Admin. `[DECIDE]` whether 10 means total attempts
    or 10 retries after the first attempt.
-   \[BIO-110\] Prove the engine path end-to-end before starting the
    public website.

### P1 --- Tournament operations and web platform

-   \[BIO-201\] Implement authentication, roles, and tournament-scoped
    access.
-   \[BIO-202\] Implement tournament creation, Admin approval/rejection,
    and lifecycle controls.
-   \[BIO-203\] Import official roster, validate email/code
    registration, and enforce locked participant identity after
    successful registration.
-   \[BIO-204\] Implement one-file bot submissions, validation, version
    history, activation, and deadline locking.
-   \[BIO-205\] Implement Admin/Organizer tournament operations and
    audit logging.
-   \[BIO-206\] Implement automated email and mandatory dashboard
    notifications.
-   \[BIO-207\] Implement participant dashboard, bracket/results views,
    and replay access.
-   \[BIO-208\] Implement team/account deletion lifecycle and retention
    rules.

### P2 --- Enhancements / later release

-   \[BIO-301\] Public landing page and marketing website.
-   \[BIO-302\] Live match viewing, if approved.
-   \[BIO-303\] Additional languages, multi-file submissions, custom
    dependencies, or participant-defined environments.
-   \[BIO-304\] Advanced analytics and historical performance
    dashboards.
-   \[BIO-305\] Match dispute workflow and additional administrative
    reporting. `[DECIDE]`

## 6. Core product rules

### 6.1 Tournament lifecycle and approval

-   Admins and Organizers may create tournaments.
-   An Organizer-created tournament must be approved by an Admin before
    it is published or registration opens.
-   An Admin may approve or reject. Rejection must include a reason.
-   An Organizer may edit a rejected tournament and resubmit it.
-   Once approved, an assigned Organizer may edit that tournament's
    settings until the relevant deadline; a second approval is not
    required for ordinary permitted changes.
-   Registration and submission deadlines are configured independently.
-   Admin may extend either deadline, including after it has passed.
    Relevant participants receive email and dashboard notifications.
-   After a deadline, normal configuration changes require the Admin to
    extend the relevant deadline first. An emergency Admin override may
    bypass this requirement, must include a reason, and must notify
    affected participants with the changed setting, reason, time, and
    authorizer.
-   `[DECIDE]` Whether there is a separate configuration-freeze deadline
    in addition to registration and submission deadlines.

### 6.2 Registration and roster

-   Registration is invitation-based and uses the participant's official
    roster email plus an invitation code.
-   Invalid email/code attempts do not consume the code and do not
    permanently block the participant; they may retry with correct
    details.
-   Unused codes expire when registration closes. If the deadline is
    extended, unused codes remain valid until the new deadline.
-   Participants who have not completed signup, email verification, and
    code validation by the deadline are excluded.
-   Admin and assigned Organizers may correct the imported official
    roster before participant registration.
-   After successful registration, email, team assignment, member
    number, and role are locked.
-   Only Admin may revoke a lost/compromised invitation code and issue a
    replacement.
-   `[DECIDE]` Whether one code is issued per participant or per team
    member. Recommended: one unique, single-use code per participant.

### 6.3 Bot submissions

-   Initial release accepts Python only and exactly one file named
    `bot.py`; no ZIP or supporting files.
-   Standard library and preinstalled third-party libraries may be used.
    Participants cannot install packages. All bots use the same
    preconfigured runtime.
-   Invalid submissions are rejected immediately with a useful reason.
    Participants may correct and resubmit before the deadline.
-   Only a successfully validated submission may become active.
-   The latest valid submission becomes active. If a replacement is
    invalid, the previous valid active submission remains active.
-   Previous versions remain in submission history.
-   Submission is locked after the deadline. Admin may extend the
    deadline, reopening submissions.
-   Each match stores the exact submission version used.
-   Participants can view/download their own files and history.
    Organizers assigned to a tournament can view/download source code
    but cannot modify, upload, delete, or activate it. Other teams'
    source code remains private throughout the tournament.
-   `[DECIDE]` Whether only the team captain may submit. Recommended:
    captain-only submission with team-visible history.

### 6.4 Match execution and tournament rules

-   Matches run sequentially; an Organizer starts each round.
-   The system selects/executes matches, records results, advances
    winners, and prepares the next match.
-   Tournament bracket is single-elimination with random pairings and
    automatic byes. Human teams receive bye priority over house bots.
-   House bots may fill bracket gaps but cannot advance or become
    champions. Exact house-bot placement/advancement algorithm needs
    approval and proof-of-concept testing.
-   A normal-stage match tie uses one predefined tie-breaker map
    automatically.
-   A final match tie uses three predefined tie-breaker maps
    automatically and sequentially.
-   If the result remains tied after the designated tie-breaker map(s),
    the system performs an automatic 50/50 digital coin flip. It is
    publicly displayed to authenticated tournament users and logged; no
    rerolls.
-   A qualification cutoff tie is resolved by an automatic random
    digital draw once scores and available slots are finalized. Tied
    teams and available slots are shown to tournament participants;
    result is logged; no reruns or manual changes.
-   A bot crash, timeout, or instruction-limit violation is an automatic
    loss/elimination; no rematch; opponent advances.
-   A platform/engine failure restarts the match from the beginning with
    the same map and bot versions but a new random seed.
-   Platform failures retry up to 10 times, then alert Admin. Exact
    attempt counting is `[DECIDE]`.
-   Every match generates a replay. Replay access is available to
    authenticated tournament participants until archive. At archive,
    replay files are deleted and cannot be retrieved, including by
    Admin/Organizers. Match results, scores, brackets, standings, and
    match history remain visible to authenticated users until permanent
    tournament deletion.
-   `[DECIDE]` Whether live match viewing is required in the initial web
    release.

### 6.5 Notifications

-   Dashboard notifications are mandatory.
-   Participants may disable email notifications while keeping dashboard
    notifications.
-   Major events trigger notifications: tournament announcements,
    registration/submission deadline changes, validation outcomes, match
    results, qualification, elimination, and other material tournament
    updates.
-   Delivery attempts and failures should be recorded and retried
    safely.
-   `[DECIDE]` Email provider, notification templates, and which
    security/account emails are mandatory.

### 6.6 Roles and privacy

-   **Admin:** global access; only Admin can revoke/replace codes,
    permanently delete tournaments, restore deleted teams, and perform
    emergency overrides.
-   **Organizer:** access only to assigned tournaments; may manage
    permitted tournament settings and roster before participant
    registration; may view/download assigned teams' source code; may not
    alter submissions or participant-locked details.
-   **Participant:** access only to own team data and tournament
    information available to registered participants; can view/download
    own bot files and relevant logs.
-   Other teams' source code is private throughout the tournament.
-   Results and tournament history are available to authenticated users
    registered on the website with appropriate tournament access;
    anonymous public access is not assumed.
-   Audit logs are immutable and permanently retained. Participants see
    only their own team/tournament-relevant logs; Organizers see
    assigned tournament logs; Admin sees all. Sensitive personal/admin
    information is hidden.

### 6.7 Deletion and retention

-   Participants may request account deletion.
-   If the participant's team is actively competing, deletion is queued
    until the team is eliminated or the tournament ends. Participant may
    cancel the queued request before execution.
-   On deletion, the participant is removed from historical team rosters
    entirely; do not display a "Deleted Participant" placeholder.
-   Historical match results, scores, brackets, and standings do not
    change.
-   If the deleted participant was captain, transfer captaincy to the
    next eligible team member when deletion executes. `[DECIDE]`
    Handling if no eligible member remains.
-   Teams remain in logs and can be deleted after tournament archive.
    Admin and assigned Organizers may delete an archived tournament's
    teams with confirmation and mandatory reason. Only Admin may restore
    an individually deleted team.
-   Team deletion removes active team profile/management access but
    preserves historical results and audit logs.
-   Only Admin may permanently delete a tournament. Requires
    confirmation and mandatory reason. Associated operational
    tournament/team data is deleted; audit logs remain permanently.
-   Tournament archive deletes replay files but preserves results,
    brackets, standings, and match history.

## 7. Detailed user scenarios

### SCN-01 --- Participant registers and submits a bot

1.  Admin/Organizer imports official roster and invitation codes are
    issued.
2.  Participant enters official email and code, completes signup and
    email verification.
3.  System validates the code and locks email, team assignment, member
    number, and role.
4.  Participant uploads exactly `bot.py`.
5.  Validator checks file name, syntax, entrypoint/imports, and runtime
    compatibility.
6.  Valid version becomes active; invalid version is rejected and does
    not replace the previous active version.
7.  Participant can view/download their own versions and validation
    results.
8.  At submission deadline, submissions lock unless Admin extends the
    deadline.

**Expected result:** No participant can register against an unlisted
email or invalid code; no invalid submission becomes active; no other
team's code is exposed.

### SCN-02 --- Organizer creates and operates a tournament

1.  Organizer creates a tournament in draft state.
2.  Organizer submits it for Admin approval.
3.  Admin approves or rejects with reason.
4.  If rejected, Organizer edits and resubmits.
5.  Once approved, Organizer configures permitted settings and manages
    the assigned tournament before deadlines.
6.  Organizer imports/corrects official roster before participant
    registrations lock those entries.
7.  Organizer starts a round; system runs sequential matches, records
    results, and advances winners.
8.  Organizer can inspect/download assigned teams' source code but
    cannot alter submissions.
9.  Audit log records all relevant changes.

**Expected result:** Organizer cannot publish an unapproved tournament
or access another Organizer's tournament.

### SCN-03 --- Tie and execution failure handling

1.  A match ends in a tie.
2.  System runs the one normal-stage tie-break map or the three final
    tie-break maps sequentially.
3.  If still tied, system performs the automatic 50/50 coin flip and
    records/displays the outcome.
4.  If a bot crashes or exceeds resource limits, it loses automatically.
5.  If the engine/platform fails, system retries/restarts using the same
    map and bot versions with a new seed.
6.  After the configured retry cap, Admin is alerted.

**Expected result:** Bot failures never trigger platform retries;
platform failures never count as bot losses; all outcomes are traceable.

## 8. Non-functional requirements

  -----------------------------------------------------------------------
  ID                      Requirement             Priority
  ----------------------- ----------------------- -----------------------
  BIO-NFR-01              Bot execution must be   P0
                          isolated from host      
                          services, other bots,   
                          and user data.          

  BIO-NFR-02              CPU/time, memory, and   P0
                          instruction limits must 
                          be globally fixed for   
                          the platform and        
                          consistently enforced.  
                          Numeric values must be  
                          benchmarked; do not     
                          invent them.            

  BIO-NFR-03              Runtime, engine,        P0
                          dependencies, and       
                          worker image must be    
                          version-pinned and      
                          reproducible.           

  BIO-NFR-04              Match records must      P0
                          reference exact bot     
                          versions, map, engine   
                          version, seed, result,  
                          and execution attempt.  

  BIO-NFR-05              Role and                P0
                          tournament-scope checks 
                          must be enforced        
                          server-side on every    
                          protected operation.    

  BIO-NFR-06              Audit records must be   P1
                          append-only and         
                          retained permanently.   

  BIO-NFR-07              Dashboard notifications P1
                          must remain available   
                          even when email is      
                          disabled.               

  BIO-NFR-08              Submission files must   P0
                          be private and served   
                          only after              
                          authorization.          

  BIO-NFR-09              System must back up     P1
                          critical database data  
                          and support tested      
                          recovery.               

  BIO-NFR-10              Logs must avoid secrets P1
                          and minimize            
                          unnecessary personal    
                          data.                   

  BIO-NFR-11              Concurrent match        P1 / `[DECIDE]`
                          capacity and tournament 
                          load targets must be    
                          established by load     
                          testing.                

  BIO-NFR-12              UI must clearly         P1
                          communicate deadlines,  
                          validation state, match 
                          state, and permission   
                          errors.                 
  -----------------------------------------------------------------------

## 9. Dependencies and constraints

### Confirmed constraints

-   Existing Battlecode 2026 scaffold and engine are the foundation.
-   Initial bot language is Python only.
-   Initial submission is a single `bot.py` file.
-   Target compatibility objective is Python 3.13.
-   Website/landing page is intentionally later than scaffold and bot
    execution.
-   No participant-installed dependencies.
-   Match resource limits are platform-wide, not tournament-specific.

### Proposed technical stack --- approval required

-   Frontend: React + TypeScript.
-   Backend/API: Django + Django REST Framework.
-   Database: PostgreSQL.
-   Background jobs: Celery + Redis.
-   Execution: isolated container/worker processes; do not run untrusted
    bots inside the web/API process.
-   File storage: private S3-compatible object storage or equivalent.
-   Realtime updates: polling initially; WebSockets only if live updates
    materially require them.
-   Deployment: containerized services behind a reverse proxy.
-   `[DECIDE]` Confirm stack, hosting provider, object storage, email
    provider, and worker hardware.

### Key external dependencies

-   Battlecode engine's actual Python runner API and supported Python
    versions.
-   Third-party package compatibility with Python 3.13.
-   Match replay format and playback tooling.
-   Worker hardware capacity and benchmarked resource limits.
-   Email provider and domain configuration.

## 10. Release plan / Jira roadmap

Dates are intentionally not invented. Set sprint dates after the
repository audit and hardware benchmark.

  ------------------------------------------------------------------------------------------------------
  Phase              Jira Epic      Priority       Scope                           Exit gate
  ------------------ -------------- -------------- ------------------------------- ---------------------
  0 --- Discovery    BIO-EPIC-00    P0             Repo audit, requirements        Approved technical
  and baseline                                     freeze, version matrix,         baseline and
                                                   architecture decisions,         unresolved-decision
                                                   reproducible baseline.          register.

  1 --- Scaffold     BIO-EPIC-01    P0             Python 3.13 compatibility,      Clean environment
  modernization                                    dependency pinning, setup       runs reference Python
                                                   scripts, Java/Python local      bot and tests.
                                                   parity.                         

  2 --- Python bot   BIO-EPIC-02    P0             Single-file bot validation,     Two independent
  execution                                        runner, sandbox, global limits, Python bots complete
                                                   failure classification.         matches; injected
                                                                                   failures classified
                                                                                   correctly.

  3 ---              BIO-EPIC-03    P0             Sequential match orchestration, Full simulated
  Match/tournament                                 bracket advancement, byes/house tournament passes
  automation                                       bots, tie-break maps, coin      end-to-end.
                                                   flip, replay, retry policy.     

  4 --- Backend      BIO-EPIC-04    P1             Auth, roles, database, API,     API permission and
  foundation                                       audit foundation, storage, job  persistence tests
                                                   queue.                          pass.

  5 --- Registration BIO-EPIC-05    P1             Roster, invitations,            Participant flow
  and submissions                                  registration, team membership,  passes with privacy
                                                   bot                             and deadline rules.
                                                   upload/versioning/validation.   

  6 --- Tournament   BIO-EPIC-06    P1             Admin approval, Organizer       Admin/Organizer
  operations                                       controls, deadlines,            lifecycle tests pass.
                                                   notifications,                  
                                                   deletion/retention.             

  7 --- Website and  BIO-EPIC-07    P1             Landing page, dashboards,       Usability and
  participant UI                                   submission UI,                  end-to-end acceptance
                                                   brackets/results, replay        complete.
                                                   access.                         

  8 --- QA, pilot,   BIO-EPIC-08    P0 launch gate Security, load, recovery, pilot Go-live checklist
  production                                       tournament, deployment,         signed off.
                                                   runbooks.                       
  ------------------------------------------------------------------------------------------------------

### Phase 0--3 task breakdown (first implementation priority)

-   **BIO-EPIC-00:** BIO-001 inspect repository; BIO-002 map Python
    runner; BIO-003 record engine/client/package versions; BIO-004
    create clean-environment baseline; BIO-005 resolve `[DECIDE]` items
    affecting execution.
-   **BIO-EPIC-01:** BIO-101 pin dependencies; BIO-102 add Python 3.13
    setup; BIO-103 repair/update Python runner integration; BIO-104 add
    smoke tests; BIO-105 document clean setup.
-   **BIO-EPIC-02:** BIO-201 define bot contract; BIO-202 validate
    `bot.py`; BIO-203 run bot in isolated worker; BIO-204 enforce
    resource limits; BIO-205 classify bot/platform failure; BIO-206
    capture structured logs.
-   **BIO-EPIC-03:** BIO-301 match orchestration; BIO-302 sequential
    round runner; BIO-303 bracket/bye/house-bot rules; BIO-304 tie-break
    maps and coin flip; BIO-305 replay lifecycle; BIO-306 platform retry
    and Admin alert.

## 11. Open decisions register

  -----------------------------------------------------------------------
  ID                      Decision needed         Recommended direction
  ----------------------- ----------------------- -----------------------
  DEC-01                  One invitation code per Unique single-use code
                          participant or per      per participant.
                          team?                   

  DEC-02                  Who may upload official Captain-only; team
                          bot?                    members can view
                                                  history.

  DEC-03                  Exact Python 3.13 patch Pin patch version and
                          version and OS matrix?  worker image after
                                                  compatibility tests.

  DEC-04                  Numeric time, memory,   Benchmark
                          instruction limits?     representative bots on
                                                  target hardware, then
                                                  publish fixed global
                                                  limits.

  DEC-05                  Retry cap: 10 total     10 total attempts to
                          attempts or 10 retries  avoid
                          after initial?          ambiguous/unbounded
                                                  behavior.

  DEC-06                  Exact house-bot bracket Human teams receive
                          algorithm?              byes first; house bots
                                                  never advance/champion.
                                                  Simulate edge cases.

  DEC-07                  If captain is deleted   Mark team
                          and no eligible member  inactive/captainless;
                          remains?                do not invent a
                                                  successor.

  DEC-08                  Separate                Avoid separate deadline
                          configuration-freeze    unless operationally
                          deadline?               needed.

  DEC-09                  Live match viewing in   Defer; prioritize
                          initial release?        post-match
                                                  results/replays.

  DEC-10                  Match replay            Reuse engine-native
                          format/player?          replay format first;
                                                  validate browser
                                                  playback separately.

  DEC-11                  Backend/frontend stack, Approve proposed stack
                          hosting, email, object  in Phase 0.
                          storage?                

  DEC-12                  Team size, captain      Use official imported
                          selection, team name    roster; define policy
                          edits?                  before registration
                                                  opens.

  DEC-13                  Account recovery and    Define before public
                          match dispute workflow? launch; not required
                                                  for scaffold proof.

  DEC-14                  Qualification cutoff    Specify exact eligible
                          draw inputs and         teams/slots and
                          randomization audit     auditable randomness
                          method?                 before implementation.
  -----------------------------------------------------------------------

## 12. Reusable implementation prompt

You are implementing INNOFEST Battle It Out, a Battlecode 2026-based
programming competition. Read this PRD and the related `SRD.md`,
`API_CONTRACT.md`, `DATA_MODEL.md`, `TEST_PLAN.md`, and `APP_FLOW.md`
before changing code. Treat confirmed requirements as mandatory,
proposed architecture as pending approval, and every `[DECIDE]` item as
unresolved. Work in the current phase only. Preserve the existing
Battlecode engine rather than creating a second game engine. The first
priority is reproducible scaffold modernization and Python 3.13
compatibility, followed by safe execution of one-file Python bots
(`bot.py`) and automated matches. Do not start the landing page or
website before the execution foundation passes its exit gate. For every
change, provide Jira issue ID, files changed, tests run, results, risks,
and any newly discovered decision. Never claim compatibility, isolation,
resource enforcement, or match reliability without a test proving it.
