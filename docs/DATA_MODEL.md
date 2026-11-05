# Battle It Out --- Data Model

**Version:** 1.0\
**Status:** Proposed logical model; physical schema requires review\
**Date:** 2026-11-04

## 1. Modeling principles

1.  Separate account identity, official roster identity, team
    membership, and tournament participation.
2.  Store immutable submission versions; matches point to exact
    versions, never "latest".
3.  Preserve match results, bracket progression, and audit history
    independently of account/team profile deletion.
4.  Treat replay files as disposable artifacts: archive deletes the
    binary but not match metadata.
5.  Use explicit lifecycle states and append-only audit events for
    sensitive transitions.
6.  Enforce authorization at the service/API layer and, where supported,
    database row-level boundaries.
7.  Store timestamps in UTC; display in the user's locale.
8.  Do not cascade-delete audit records or historical match outcomes.

## 2. Entities

### 2.1 Identity and access

  ----------------------------------------------------------------------------
  Entity                     Fields                  Type / notes
  -------------------------- ----------------------- -------------------------
  `User`                     `id`,                   UUID/opaque ID; unique
                             `email_normalized`,     normalized email while
                             `password_hash`,        active; never store
                             `status`,               plaintext password.
                             `email_verified_at`,    Status:
                             `created_at`,           `pending_verification`,
                             `deleted_at`            `active`,
                                                     `deletion_queued`,
                                                     `deleted`, `suspended`.

  `Role`                     `id`, `name`            Enum or lookup: `ADMIN`,
                                                     `ORGANIZER`,
                                                     `PARTICIPANT`.

  `UserRole`                 `user_id`, `role_id`,   Many-to-many or one
                             `granted_by`,           primary role; `[DECIDE]`
                             `granted_at`            whether users can hold
                                                     multiple roles.

  `OrganizerAssignment`      `id`,                   Scopes Organizer access
                             `organizer_user_id`,    to assigned tournament.
                             `tournament_id`,        
                             `assigned_by`,          
                             `assigned_at`,          
                             `revoked_at`            

  `NotificationPreference`   `user_id`,              Dashboard notification
                             `email_enabled`,        cannot be disabled.
                             `updated_at`            
  ----------------------------------------------------------------------------

### 2.2 Tournament and approval

  --------------------------------------------------------------------------
  Entity                  Fields                     Type / notes
  ----------------------- -------------------------- -----------------------
  `Tournament`            `id`, `name`,              Status: `draft`,
                          `description`, `status`,   `pending_approval`,
                          `created_by`,              `rejected`, `approved`,
                          `approved_by`,             `registration_open`,
                          `created_at`,              `running`, `completed`,
                          `approved_at`,             `archived`, `deleted`.
                          `archived_at`,             State transitions
                          `deleted_at`, `version`    validated.

  `TournamentApproval`    `id`, `tournament_id`,     Decision `approved` or
                          `reviewer_user_id`,        `rejected`; rejection
                          `decision`, `reason`,      reason required.
                          `created_at`               

  `TournamentDeadline`    `id`, `tournament_id`,     Types: `registration`,
                          `deadline_type`,           `submission`; history
                          `deadline_at`,             retained. Emergency
                          `changed_by`, `reason`,    overrides stored
                          `created_at`,              separately as
                          `superseded_at`            audit/state-change
                                                     records.

  `TournamentSetting`     `id`, `tournament_id`,     Versioned settings;
                          `key`, `value_json`,       only approved editable
                          `version`, `updated_by`,   keys.
                          `updated_at`               

  `TournamentMap`         `id`, `tournament_id`,     Map files/engine
                          `map_key`, `map_version`,  references are
                          `stage`, `sequence`,       immutable by version.
                          `is_tiebreaker`, `active`  Normal tie-break count
                                                     = 1; final = 3.

  `TournamentArchive`     `id`, `tournament_id`,     Archive event and
                          `archived_by`,             replay purge result.
                          `archived_at`,             
                          `replay_deletion_status`   
  --------------------------------------------------------------------------

### 2.3 Official roster, invitation, team

  ---------------------------------------------------------------------------------
  Entity                  Fields                  Type / notes
  ----------------------- ----------------------- ---------------------------------
  `ImportedRosterEntry`   `id`, `tournament_id`,  Editable by Admin/assigned
                          `team_external_key`,    Organizer until registration
                          `team_name`,            locks the entry. Unique
                          `email_normalized`,     constraints on tournament/email
                          `member_number`,        and team/member number as
                          `role_label`,           appropriate.
                          `import_batch_id`,      
                          `registered_user_id`,   
                          `locked_at`             

  `RosterImportBatch`     `id`, `tournament_id`,  Do not store original roster file
                          `uploaded_by`,          longer than necessary; `[DECIDE]`
                          `source_filename`,      retention.
                          `created_at`,           
                          `summary_json`          

  `Team`                  `id`, `tournament_id`,  Status: `active`, `eliminated`,
                          `official_key`, `name`, `archived`, `deleted`; deleted
                          `status`, `created_at`, team can be restored by Admin
                          `deleted_at`,           while tournament exists.
                          `deleted_by`,           
                          `deletion_reason`,      
                          `restored_at`           

  `TeamMember`            `id`, `team_id`,        Registration locks core
                          `user_id`,              identity/assignment. Deleted user
                          `roster_entry_id`,      must not appear as a placeholder
                          `member_number`,        in historical roster display.
                          `role_label`,           
                          `joined_at`, `left_at`, 
                          `is_captain`            

  `InvitationCode`        `id`,                   Store hash, not plaintext.
                          `roster_entry_id`,      Single-use. Only Admin can
                          `code_hash`, `status`,  revoke/replace compromised code.
                          `issued_by`,            
                          `issued_at`,            
                          `expires_at`,           
                          `consumed_at`,          
                          `revoked_at`,           
                          `replaced_by_id`        

  `InvitationCodeIssue`   `id`,                   Audit-friendly
                          `invitation_code_id`,   issuance/revocation/replacement
                          `action`,               history.
                          `actor_user_id`,        
                          `reason`, `created_at`  
  ---------------------------------------------------------------------------------

### 2.4 Submission and execution

  ----------------------------------------------------------------------------
  Entity                   Fields                      Type / notes
  ------------------------ --------------------------- -----------------------
  `BotSubmission`          `id`, `team_id`,            File name exactly
                           `tournament_id`,            `bot.py`; immutable
                           `version_number`,           content hash and
                           `file_name`, `storage_key`, version. Only valid
                           `content_hash`,             submission can be
                           `uploaded_by`,              active.
                           `uploaded_at`,              
                           `validation_status`,        
                           `validation_report_json`,   
                           `is_active`, `activated_at` 

  `SubmissionValidation`   `id`, `submission_id`,      Tracks syntax, import,
                           `validator_version`,        entrypoint, file
                           `status`, `checks_json`,    policy, runtime checks.
                           `failure_code`,             
                           `message_safe`,             
                           `started_at`, `finished_at` 

  `ExecutionProfile`       `id`, `name`,               Platform-wide profile.
                           `runtime_image_digest`,     Numeric limits
                           `python_version`,           benchmarked and fixed;
                           `engine_version`,           avoid
                           `time_limit`,               tournament-specific
                           `memory_limit`,             override.
                           `instruction_limit`,        
                           `created_at`                

  `Match`                  `id`, `tournament_id`,      Match references exact
                           `round_id`, `match_number`, bot versions.
                           `team_a_id`, `team_b_id`,   `result_type`:
                           `submission_a_id`,          `normal`,
                           `submission_b_id`,          `bot_forfeit`,
                           `map_id`, `seed`, `status`, `tiebreak`,
                           `winner_team_id`,           `coin_flip`,
                           `result_type`,              `platform_abort` etc.
                           `started_at`, `finished_at` 

  `MatchAttempt`           `id`, `match_id`,           Bot failure is terminal
                           `attempt_number`, `seed`,   match result; platform
                           `execution_profile_id`,     failure may retry. Same
                           `status`, `failure_class`,  map/submission versions
                           `failure_reason`,           across retry; new seed.
                           `resource_usage_json`,      
                           `worker_version`,           
                           `started_at`,               
                           `finished_at`, `trace_id`   

  `MatchReplay`            `id`, `match_id`,           Replay artifact; at
                           `storage_key`, `format`,    archive delete file and
                           `created_at`, `deleted_at`, set deleted metadata.
                           `deletion_reason`           Do not delete match
                                                       record.

  `MatchLog`               `id`, `match_id`,           Visibility scoped;
                           `attempt_id`, `visibility`, redact secrets and host
                           `storage_key` or            details.
                           `content_json`,             
                           `created_at`                

  `Round`                  `id`, `tournament_id`,      Sequential rounds;
                           `round_number`, `status`,   Organizer starts each
                           `started_at`,               round.
                           `completed_at`              

  `Bracket`                `id`, `tournament_id`,      Bracket snapshot;
                           `version`, `status`,        edits/overrides
                           `generated_at`,             audited.
                           `generated_by`, `locked_at` 

  `BracketSlot`            `id`, `bracket_id`,         Human bye priority;
                           `round_id`, `slot_number`,  house-bot rule pending
                           `team_id`, `house_bot_id`,  final specification.
                           `source_match_id`, `is_bye` 

  `HouseBot`               `id`, `name`,               Cannot become
                           `submission_id`, `enabled`, tournament champion or
                           `created_at`                advance as a human
                                                       team.
  ----------------------------------------------------------------------------

### 2.5 Notifications, audit, deletion, incidents

  ----------------------------------------------------------------------------
  Entity                     Fields                    Type / notes
  -------------------------- ------------------------- -----------------------
  `Notification`             `id`,                     Dashboard is mandatory;
                             `recipient_user_id`,      email preference only
                             `tournament_id`,          controls email
                             `event_type`, `title`,    delivery.
                             `body`,                   
                             `dashboard_created_at`,   
                             `read_at`, `email_status` 

  `NotificationDelivery`     `id`, `notification_id`,  Delivery retry
                             `channel`, `status`,      tracking.
                             `attempt_count`,          
                             `provider_message_id`,    
                             `last_error`,             
                             `updated_at`              

  `AuditLog`                 `id`, `actor_user_id`,    Append-only,
                             `actor_role_snapshot`,    permanently retained.
                             `tournament_id`,          Never store passwords,
                             `team_id`, `action`,      raw invitation codes,
                             `target_type`,            secrets, or unnecessary
                             `target_id`, `reason`,    personal data.
                             `before_json_redacted`,   
                             `after_json_redacted`,    
                             `request_id`,             
                             `created_at`              

  `AccountDeletionRequest`   `id`, `user_id`,          Status: `queued`,
                             `status`, `requested_at`, `scheduled`,
                             `execute_after`,          `cancelled`,
                             `cancelled_at`,           `executed`. Queue while
                             `executed_at`             team active.

  `TeamDeletionEvent`        `id`, `team_id`,          Reversible by Admin
                             `actor_user_id`,          until tournament
                             `reason`, `deleted_at`,   permanently deleted.
                             `restored_at`,            
                             `restored_by`             

  `SystemIncident`           `id`, `match_id`,         Tracks platform
                             `incident_type`,          failures and retry cap
                             `attempt_count`,          alert.
                             `status`,                 
                             `alerted_admin_at`,       
                             `details_redacted`,       
                             `created_at`,             
                             `resolved_at`             
  ----------------------------------------------------------------------------

## 3. Relationships

-   `Tournament 1—N ImportedRosterEntry`
-   `Tournament 1—N Team`
-   `Tournament 1—N TournamentDeadline`
-   `Tournament 1—N TournamentMap`
-   `Tournament 1—N OrganizerAssignment`
-   `Tournament 1—N Round`
-   `Tournament 1—1..N Bracket` (versions)
-   `Team 1—N TeamMember`
-   `Team 1—N BotSubmission`
-   `BotSubmission 1—N SubmissionValidation`
-   `Round 1—N Match`
-   `Match 1—N MatchAttempt`
-   `Match 1—0..1 MatchReplay` (or multiple artifacts if engine
    requires)
-   `Match N—1 Team` for each side and winner
-   `Match N—1 BotSubmission` for each side
-   `User 1—N Notification`
-   `User 1—N AuditLog` as actor; audit may retain a pseudonymous actor
    reference after account deletion
-   `User 1—0..N AccountDeletionRequest`
-   `Tournament 1—N AuditLog`
-   `Team 1—N AuditLog`

## 4. State models

### Tournament

`draft → pending_approval → approved → registration_open → running → completed → archived → deleted`

-   `pending_approval → rejected → pending_approval` after Organizer
    edits/resubmits.
-   Admin may create/approve directly according to permissions.
-   Actual transition from approved to registration open/running depends
    on configured dates and operational controls. `[DECIDE]` whether
    opening is manual or scheduled.
-   `deleted` is terminal for operational data; audit remains.

### Submission

`uploaded → validating → valid → active`

or

`uploaded → validating → invalid`

-   Only `valid` may become `active`.
-   New valid version supersedes previous active version.
-   Invalid replacement does not change active version.
-   Submission after deadline rejected unless Admin extends deadline.

### Match

`scheduled → queued → running → completed`

Platform failure path:
`running → platform_failed → retry_queued → running`

Bot failure path: `running → bot_forfeit → completed`

-   Retry preserves map and submission versions, changes seed.
-   Duplicate worker completion must not duplicate advancement.
-   After retry cap, incident is alerted to Admin and match pauses for
    operational handling. `[DECIDE]` final paused state name and resume
    authority.

### Account deletion

`requested → queued (if team active) → scheduled → executed`

or `requested/queued → cancelled`.

## 5. Constraints and validation

### Identity / roster

-   Normalize email before lookup and uniqueness checks.
-   One official roster entry per eligible participant per tournament.
-   Successful registration locks email, team, member number, and role.
-   Do not update locked roster fields through normal roster endpoint.
-   Invitation code must be single-use, unexpired, unrevoked, and linked
    to eligible roster entry.
-   Invalid attempts must not consume the code.

### Team

-   Team belongs to exactly one tournament.
-   Team deletion allowed only after tournament archive.
-   Team delete requires reason and confirmation.
-   Only Admin restores.
-   Team deletion must not cascade to matches, results, brackets, or
    audit logs.
-   Tournament permanent deletion removes associated operational records
    but not audit logs.

### Submission

-   `file_name == "bot.py"`.
-   One file only; no ZIP or supporting files.
-   Enforce configured maximum upload size `[DECIDE]`.
-   Content hash immutable.
-   Version number unique within team/tournament.
-   A submission can be active only if validation status is valid.
-   At most one active submission per team/tournament.
-   Match submission references immutable.

### Match

-   Both sides must reference valid team/house-bot participant and
    immutable submission version.
-   Same map and submission versions across platform retries.
-   New seed on each platform retry.
-   Bot failure is not retryable.
-   Match result and bracket advancement must be atomic/idempotent.

### Notifications and audit

-   Dashboard notification created for each required event even when
    email disabled.
-   Audit log is append-only; no update/delete endpoints.
-   Redact sensitive fields before persistence.
-   Audit access is role- and scope-filtered.

## 6. Deletion and retention matrix

  ----------------------------------------------------------------------------------------------
  Data                 At account deletion At team        At tournament  At permanent tournament
                                           deletion       archive        deletion
  -------------------- ------------------- -------------- -------------- -----------------------
  User account /       Remove/anonymize    No direct      No direct      Associated accounts
  credentials          after queued        effect.        effect.        follow account policy.
                       period; preserve                                  
                       only necessary                                    
                       pseudonymous audit                                
                       reference.                                        

  Historical team      Remove deleted      Team           Retain.        Delete operational
  roster               participant         operational                   roster.
                       entirely; no        profile                       
                       placeholder.        removed.                      

  Match results/scores Retain unchanged.   Retain         Retain and     Delete operational
                                           unchanged.     remain         results as part of
                                                          viewable.      tournament data.

  Brackets/standings   Retain unchanged.   Retain         Retain.        Delete operational
                                           unchanged.                    records.

  Bot source files     Apply               Retain or      Retain only if Delete operational
                       retention/privacy   delete         needed for     source artifacts unless
                       policy; do not      according to   match audit;   legally/operationally
                       expose to other     tournament     access policy  required; `[DECIDE]`.
                       teams.              policy         remains.       
                                           `[DECIDE]`; no                
                                           public access.                

  Replay binaries      No direct effect.   No direct      Delete; no     Already deleted at
                                           effect.        Admin          archive; purge any
                                                          recovery.      remaining.

  Audit logs           Retain permanently; Retain         Retain         Retain permanently.
                       pseudonymize actor  permanently.   permanently.   
                       as needed.                                        
  ----------------------------------------------------------------------------------------------

## 7. Access matrix

  --------------------------------------------------------------------------
  Resource/action                Admin Assigned Organizer        Participant
  ----------------- ------------------ ------------------ ------------------
  All tournaments                  Yes                 No                 No

  Assigned                         Yes     Yes, permitted                 No
  tournament                                       fields 
  management                                              

  Approve/reject                   Yes                 No                 No
  tournament                                              

  Correct                          Yes                Yes                 No
  unregistered                                            
  roster                                                  

  Revoke/replace                   Yes                 No                 No
  compromised code                                        

  View/download                    Yes                Yes      Own team only
  assigned bot                                            
  source                                                  

  Modify/activate       Admin override                 No    Upload own team
  participant       only if explicitly                    version subject to
  submission                  designed                                policy

  Start round                      Yes                Yes                 No

  View                             Yes           Assigned      Authenticated
  bracket/results                                                 tournament
                                                                 participant

  View match replay                Yes           Assigned         Tournament
  before archive                                                 participant

  View own scoped                  Yes      Assigned logs                Own
  audit                                                      team/tournament
                                                                        logs

  Global audit logs                Yes                 No                 No

  Delete archived                  Yes           Assigned                 No
  team                                                    

  Restore deleted                  Yes                 No                 No
  team                                                    

  Permanently                      Yes                 No                 No
  delete tournament                                       

  Emergency                        Yes                 No                 No
  override                                                
  --------------------------------------------------------------------------

## 8. Recommended indexes / integrity constraints

-   Unique index on normalized active user email.
-   Unique `(tournament_id, email_normalized)` on roster entries.
-   Unique `(team_id, version_number)` on submissions.
-   Partial unique index for one active valid submission per
    team/tournament.
-   Index `Match(tournament_id, round_id, status)`.
-   Index `MatchAttempt(match_id, attempt_number)`.
-   Index
    `Notification(recipient_user_id, read_at, dashboard_created_at)`.
-   Index `AuditLog(tournament_id, created_at)` and
    `(team_id, created_at)`.
-   Foreign-key delete policies should use `RESTRICT` or explicit
    service-level archival for historical records, not blind cascade.
-   Idempotency key unique per actor/operation scope.

## 9. Open decisions

-   `[DECIDE]` Multiple roles per account or one role.
-   `[DECIDE]` Invitation code granularity.
-   `[DECIDE]` Team size and captain selection.
-   `[DECIDE]` Roster import format and retention.
-   `[DECIDE]` Upload size cap and source retention after tournament
    deletion.
-   `[DECIDE]` Exact worker retry cap interpretation and post-cap match
    state.
-   `[DECIDE]` House-bot bracket representation.
-   `[DECIDE]` Whether replay artifact is one file or multiple.
-   `[DECIDE]` Account deletion anonymization details and legal
    retention requirements.
-   `[DECIDE]` Whether match logs are stored in DB or object storage.

## 10. Reusable implementation prompt

Implement the data model for the current Jira epic. Use immutable
versioned submissions and match references. Do not cascade-delete
historical results, bracket data, or audit logs when a user or team is
deleted. Preserve archive behavior: replay files are deleted while
results/history remain. Enforce unique constraints and explicit state
transitions. Keep sensitive data out of audit payloads. Mark every
unresolved schema decision rather than inventing a value.
