# Battle It Out --- Software Requirements Document (SRD)

**Version:** 1.0\
**Status:** Working baseline\
**Date:** 2026-11-04

## 1. Goal

Build a reliable, controlled Battlecode-style competition platform for
INNOFEST. Participants submit a Python bot that competes in the existing
Battlecode 2026 game engine. The system manages tournament registration,
submissions, matches, brackets, results, notifications, and audit
history.

**Implementation order:** scaffold modernization and Python 3.13
compatibility first; bot execution and match automation second; backend
and website later. The landing page is explicitly deferred until the
execution foundation is proven.

## 2. Users and roles

  ---------------------------------------------------------------------------
  Role              Scope             Main capabilities Restrictions
  ----------------- ----------------- ----------------- ---------------------
  Admin             Global            Approve/reject    Destructive actions
                                      tournaments;      and emergency
                                      manage all        overrides require
                                      tournaments;      confirmation/reason
                                      revoke/replace    and audit.
                                      compromised       
                                      invitation codes; 
                                      extend deadlines; 
                                      emergency         
                                      override; restore 
                                      deleted teams;    
                                      permanently       
                                      delete            
                                      tournaments; view 
                                      all audit logs.   

  Organizer         Assigned          Create tournament Cannot publish own
                    tournaments only  drafts; manage    tournament without
                                      approved assigned Admin approval;
                                      tournaments; edit cannot revoke/replace
                                      official roster   codes; cannot modify
                                      before            participant-locked
                                      participant       details or
                                      registration;     participant
                                      start rounds;     submissions; cannot
                                      view/download     permanently delete
                                      assigned teams'   tournament.
                                      source; view      
                                      assigned audit    
                                      logs.             

  Participant       Own team +        Register with     Cannot see other
                    authorized        official          teams' source code;
                    tournament views  email/code;       cannot change locked
                                      submit and track  roster identity/team
                                      own bot versions; assignment; cannot
                                      view own files,   manage tournament
                                      validation, match settings.
                                      history, results, 
                                      brackets,         
                                      notifications,    
                                      permitted         
                                      replays/logs;     
                                      request account   
                                      deletion.         
  ---------------------------------------------------------------------------

## 3. MVP workflow

The MVP is delivered in technical slices. The first demonstrable MVP is
a local execution proof, not a public website.

1.  Audit and reproduce the existing Battlecode 2026 scaffold.
2.  Make the scaffold compatible with the approved Python 3.13
    environment.
3.  Run two independent single-file Python bots (`bot.py`) through the
    existing engine.
4.  Validate submissions and enforce global resource limits in an
    isolated worker.
5.  Distinguish bot failure from platform failure.
6.  Automate sequential matches, result capture, bracket advancement,
    tie-break maps, coin flip, replay generation, and platform retry.
7.  Build the backend and role-protected tournament workflows.
8.  Build registration, invitation, team, and submission management.
9.  Build the participant/admin/organizer website and landing page.
10. Run a pilot and production readiness checks.

## 4. Must-have requirements

### 4.1 Scaffold and execution --- P0

-   **SRD-001:** Existing Battlecode 2026 engine remains the source of
    game simulation.
-   **SRD-002:** Clean setup must be reproducible using pinned
    dependencies and documented commands.
-   **SRD-003:** Python 3.13 compatibility must be verified, not
    assumed.
-   **SRD-004:** Initial participant submission is exactly one Python
    file named `bot.py`; no ZIP or supporting files.
-   **SRD-005:** Standard library and preinstalled third-party libraries
    are allowed; user package installation is not.
-   **SRD-006:** All bots use the same runtime image/environment.
-   **SRD-007:** Execution occurs outside the web/API process in an
    isolated worker.
-   **SRD-008:** Platform-wide CPU/time, memory, and instruction limits
    are enforced consistently. Numeric values are established by
    benchmark.
-   **SRD-009:** Bot crash, timeout, or instruction-limit violation
    results in automatic loss/elimination; no rematch.
-   **SRD-010:** Platform/engine failure is not a bot loss. The match
    restarts with same map and bot versions, but a new random seed.
-   **SRD-011:** Platform failures retry up to 10 times and then alert
    Admin. `[DECIDE]` attempt-count interpretation.
-   **SRD-012:** Every match records exact bot versions, map,
    engine/runtime version, seed, attempts, result, and logs.

### 4.2 Tournament and match rules --- P0/P1

-   **SRD-020:** Tournament format is single-elimination with random
    pairings and automatic byes.
-   **SRD-021:** Human teams receive bye priority over house bots.
-   **SRD-022:** House bots may fill bracket gaps but cannot advance or
    become champions. Exact algorithm requires approval and tests.
-   **SRD-023:** Matches run sequentially; an Organizer starts each
    round.
-   **SRD-024:** Normal-stage match tie triggers one predefined
    tie-breaker map automatically.
-   **SRD-025:** Final match tie triggers three predefined tie-breaker
    maps automatically and sequentially.
-   **SRD-026:** If still tied, a 50/50 digital coin flip automatically
    determines the winner; display and log outcome; no rerolls.
-   **SRD-027:** Qualification cutoff tie is resolved by automatic
    digital draw when scores and available slots are finalized; display
    tied teams/slots; log; no reruns/manual changes.
-   **SRD-028:** Results publish automatically to authenticated users
    with appropriate tournament access.

### 4.3 Tournament lifecycle and registration

-   **SRD-030:** Admin and Organizer may create tournament drafts.
-   **SRD-031:** Organizer-created tournament requires Admin approval
    before publication/registration.
-   **SRD-032:** Rejection includes reason; Organizer may edit and
    resubmit.
-   **SRD-033:** Assigned Organizer may edit approved tournament
    settings until relevant deadline.
-   **SRD-034:** Registration and submission deadlines are independent.
-   **SRD-035:** Admin may extend deadlines, including after expiry;
    affected participants receive email and dashboard notification.
-   **SRD-036:** Normal post-deadline changes require Admin to extend
    the relevant deadline first.
-   **SRD-037:** Emergency Admin override may bypass deadline lock,
    requires reason, audit, and participant notifications.
-   **SRD-038:** Official roster is imported and can be corrected by
    Admin/assigned Organizer before participant registration.
-   **SRD-039:** Participant registers using official email and valid
    invitation code.
-   **SRD-040:** Invalid attempts do not consume the code and do not
    permanently block participant retry.
-   **SRD-041:** Codes are single-use and expire at registration close;
    extension preserves unused codes until the new deadline.
-   **SRD-042:** Successful registration locks email, team assignment,
    member number, and role.
-   **SRD-043:** Only Admin may revoke a compromised/lost code and issue
    replacement.
-   **SRD-044:** Participants not fully registered, verified, and
    code-validated by deadline are excluded.

### 4.4 Bot submission and privacy

-   **SRD-050:** Invalid upload is rejected immediately with actionable
    reason.
-   **SRD-051:** Only a valid submission may become active.
-   **SRD-052:** Latest valid submission becomes active; invalid
    replacement does not displace previous valid active version.
-   **SRD-053:** Previous versions and validation outcomes remain in
    history.
-   **SRD-054:** Submissions lock at deadline; Admin extension reopens
    them.
-   **SRD-055:** Match references exact bot version used.
-   **SRD-056:** Participant may view/download own source and history.
-   **SRD-057:** Assigned Organizer may view/download assigned source
    but cannot modify, upload, delete, or activate it.
-   **SRD-058:** Other teams' source code remains private throughout the
    tournament.

### 4.5 Notifications, audit, deletion, retention

-   **SRD-060:** Dashboard notifications are mandatory; participant may
    disable email independently.
-   **SRD-061:** Major tournament, validation, deadline, result,
    qualification, and elimination events trigger notifications.
-   **SRD-062:** Audit logs are immutable and permanently retained.
-   **SRD-063:** Participants see only relevant own-team/tournament
    logs; Organizers see assigned tournament logs; Admin sees all.
-   **SRD-064:** Sensitive personal/admin data is hidden from
    unauthorized viewers.
-   **SRD-065:** Participant deletion request is queued while their team
    is actively competing; requester may cancel before execution.
-   **SRD-066:** On deletion, participant is removed from historical
    rosters entirely; match results/scores/brackets/standings remain
    unchanged.
-   **SRD-067:** Captaincy transfers to next eligible member when
    captain account deletion executes. `[DECIDE]` no-successor behavior.
-   **SRD-068:** Teams may be deleted after tournament archive by Admin
    or assigned Organizer, with confirmation and mandatory reason; only
    Admin may restore.
-   **SRD-069:** Permanent tournament deletion is Admin-only, requires
    confirmation and reason, removes associated operational data, and
    retains audit logs.
-   **SRD-070:** Tournament archive deletes replay files but retains
    results, brackets, standings, and match history.

## 5. Not in MVP / explicitly deferred

-   Public landing page and marketing website before execution
    foundation.
-   Additional bot languages.
-   Multi-file/ZIP submissions.
-   Participant-installed dependencies or custom runtime environments.
-   Public anonymous access to tournament results.
-   Live match streaming/viewing unless later approved.
-   Advanced analytics, spectator features, and social/community
    features.
-   Match dispute workflow unless separately approved.
-   Custom per-tournament execution limits; limits are global.
-   Any replacement game engine; reuse Battlecode 2026.

## 6. Acceptance checks

  -----------------------------------------------------------------------
  Check                               Pass condition
  ----------------------------------- -----------------------------------
  AC-SRD-01                           A clean environment installs and
                                      runs the reference Python bot under
                                      approved Python 3.13.

  AC-SRD-02                           Two different `bot.py` submissions
                                      complete a match through the actual
                                      engine.

  AC-SRD-03                           Syntax/import/entrypoint failures
                                      are rejected before activation.

  AC-SRD-04                           Injected bot
                                      crash/timeout/instruction-limit
                                      violations produce bot loss;
                                      injected engine failure produces
                                      platform retry.

  AC-SRD-05                           Retry uses same map and bot
                                      versions with a new seed; retry cap
                                      triggers Admin alert.

  AC-SRD-06                           Normal and final tie-break maps run
                                      in the correct count/order; coin
                                      flip resolves remaining tie and is
                                      logged.

  AC-SRD-07                           Unauthorized user cannot read
                                      another team's source code or
                                      access unassigned tournament
                                      operations.

  AC-SRD-08                           Invalid invite attempts do not
                                      consume codes; successful
                                      registration locks roster fields.

  AC-SRD-09                           Invalid replacement submission does
                                      not replace the active valid
                                      version.

  AC-SRD-10                           Archive deletes replay files but
                                      leaves match results and bracket
                                      history.

  AC-SRD-11                           Tournament permanent deletion is
                                      Admin-only, reasoned, confirmed,
                                      and audit-preserving.

  AC-SRD-12                           Dashboard notifications remain
                                      enabled when email is disabled.
  -----------------------------------------------------------------------

## 7. Build notes and Jira roadmap

### Epics

-   **BIO-EPIC-00 --- Discovery and technical baseline (P0):**
    repository audit, dependency/version inventory, engine integration
    map, decision register.
-   **BIO-EPIC-01 --- Scaffold modernization (P0):** Python 3.13, pinned
    dependencies, reproducible setup, smoke tests.
-   **BIO-EPIC-02 --- Bot runner and sandbox (P0):** one-file contract,
    validation, isolated execution, resource limits, failure
    classification.
-   **BIO-EPIC-03 --- Match and tournament automation (P0):** sequential
    rounds, bracket, byes, house bots, tie-breaks, coin flip, replay,
    retries.
-   **BIO-EPIC-04 --- Backend foundation (P1):** authentication, role
    permissions, persistence, API, audit.
-   **BIO-EPIC-05 --- Registration and submissions (P1):** roster,
    invitation codes, teams, submission versions.
-   **BIO-EPIC-06 --- Tournament operations (P1):** approval, deadlines,
    notifications, deletion, archive.
-   **BIO-EPIC-07 --- Website and dashboards (P1):** landing page,
    participant and staff UI.
-   **BIO-EPIC-08 --- QA and launch (P0 launch gate):** security, load,
    recovery, pilot, deployment.

### Build notes

-   Do not begin frontend/landing-page implementation while BIO-EPIC-01
    to BIO-EPIC-03 are unproven.
-   First inspect actual runner API and dependency support; do not
    blindly upgrade packages.
-   Pin Python patch version, package versions, engine version, and
    worker image.
-   Benchmark limits before setting numeric resource values.
-   Treat untrusted bot code as hostile. Isolate process/container,
    filesystem, network, CPU, memory, and wall-clock access.
-   Keep execution worker separate from API/web server.
-   Make state transitions explicit and auditable.
-   Avoid cascading deletion of historical match/result/audit data.
-   All permissions must be enforced server-side, not merely hidden in
    UI.

## 8. Unresolved decisions

See PRD §11. Highest-priority decisions before implementation:
invitation granularity, uploader authority, Python patch/runtime matrix,
resource limits, retry counting, house-bot algorithm, and exact replay
support.

## 9. Reusable prompt

Implement the Battle It Out requirements in this SRD using the current
Jira phase. Read the PRD and API/data/test/flow documents as well. Do
not invent missing rules. Mark unresolved items `[DECIDE]`. Preserve the
Battlecode 2026 engine. Start with the scaffold and Python 3.13
compatibility; do not build the website first. Add automated tests for
every acceptance check and report evidence rather than assumptions.
