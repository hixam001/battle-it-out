# Battle It Out --- API Contract

**Version:** 1.0\
**Status:** Proposed contract; endpoints require implementation review\
**API style:** REST/JSON, versioned under `/api/v1`\
**Notation:** Jira issue IDs link endpoint groups to delivery work.

> This contract defines the proposed web-platform API, not the internal
> Battlecode engine interface. Exact engine runner calls must be
> discovered from the repository during BIO-EPIC-00/01. All endpoints
> require server-side authorization. Examples are illustrative schemas,
> not final serialization decisions.

## 1. Contract-wide rules

-   Base path: `/api/v1`.
-   JSON request/response unless uploading a file.
-   Authentication: secure session or bearer token. `[DECIDE]` Select
    auth mechanism and token/session policy.
-   All timestamps use ISO 8601 UTC.
-   IDs are opaque identifiers; never trust client-supplied ownership or
    role.
-   Every protected operation checks role **and** tournament
    assignment/team membership server-side.
-   Error envelope:

``` json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "The uploaded file must be named bot.py.",
    "details": {},
    "request_id": "req_..."
  }
}
```

-   Common errors: `400 VALIDATION_ERROR`, `401 UNAUTHENTICATED`,
    `403 FORBIDDEN`, `404 NOT_FOUND`, `409 STATE_CONFLICT`,
    `410 EXPIRED`, `413 FILE_TOO_LARGE`, `415 UNSUPPORTED_MEDIA_TYPE`,
    `422 BOT_VALIDATION_FAILED`, `429 RATE_LIMITED`,
    `500 INTERNAL_ERROR`, `503 SERVICE_UNAVAILABLE`.
-   Do not reveal whether another team's private resource exists; return
    a safe `404` where appropriate.
-   Destructive actions require explicit confirmation payload and a
    non-empty reason.
-   State-changing operations create audit events in the same
    transaction or a durable outbox workflow.
-   Use idempotency keys for operations that may be retried, especially
    match start, upload finalization, deadline extension, and
    destructive actions.
-   Pagination: cursor or page-based. `[DECIDE]` Standardize one
    approach before implementation.
-   File download endpoints must stream only after authorization;
    storage URLs must be short-lived and private.

## 2. Authentication and profile --- BIO-EPIC-04

### POST `/auth/register`

**Purpose:** Create account as part of valid participant registration.\
**Access:** Public entry point, but requires official email and
invitation code.\
**Request:**

``` json
{
  "email": "participant@example.org",
  "invitation_code": "one-time-code",
  "password": "user-supplied-secret"
}
```

**Success `201`:**

``` json
{
  "user_id": "usr_123",
  "team_id": "team_123",
  "tournament_id": "trn_123",
  "email_verification_required": true,
  "registration_status": "pending_verification"
}
```

**Errors:** `400` malformed input; `409` already registered/code
consumed; `422` email not on roster or code invalid; `410` registration
closed/code expired; `429` rate limited. Invalid attempts must not
consume code or permanently block a legitimate retry.

### POST `/auth/verify-email`

**Purpose:** Complete email verification.\
**Access:** Public with verification token.\
**Request:** `{"token":"..."}`\
**Success:** `{"status":"verified","registration_status":"active"}`\
**Errors:** `400`, `410`, `409`.

### POST `/auth/login`

**Purpose:** Authenticate.\
**Access:** Public.\
**Request:** `{"email":"...","password":"..."}`\
**Success:** Session/token representation `[DECIDE]`.\
**Errors:** `401`, `429`.

### POST `/auth/logout`

**Purpose:** End session.\
**Access:** Authenticated.\
**Success:** `{"status":"logged_out"}`.

### GET `/me`

**Purpose:** Current user's profile and role-scoped memberships.\
**Access:** Authenticated.\
**Success:** user identity, role, team/tournament memberships,
notification preferences. Never return password hashes or invitation
secrets.

### POST `/me/deletion-request`

**Purpose:** Request account deletion.\
**Access:** Participant.\
**Request:** `{"confirm":true}`\
**Success:**
`{"status":"queued","execute_after":"...","can_cancel":true}` or
`{"status":"scheduled","execute_after":"..."}`.\
**Rules:** If team actively competing, queue until
elimination/tournament end.\
**Errors:** `403`, `409`.

### DELETE `/me/deletion-request`

**Purpose:** Cancel a pending deletion request.\
**Access:** Requesting participant only.\
**Success:** `{"status":"cancelled"}`.\
**Errors:** `409` if already executed/not cancellable.

## 3. Tournament administration --- BIO-EPIC-06

### POST `/tournaments`

**Purpose:** Create tournament draft.\
**Access:** Admin or Organizer.\
**Request:**

``` json
{
  "name": "INNOFEST Battle It Out",
  "description": "Battlecode-style programming competition",
  "registration_deadline": "2027-01-10T18:00:00Z",
  "submission_deadline": "2027-01-12T18:00:00Z"
}
```

**Success `201`:** tournament object with `status:"draft"` for Admin;
Organizer-created draft enters `pending_approval` when submitted.\
**Errors:** `400`, `403`, `422`.

### GET `/tournaments`

**Purpose:** List tournaments visible to caller.\
**Access:** Authenticated; Admin global, Organizer assigned, Participant
registered/eligible visibility.\
**Success:** paginated tournament summaries. Anonymous visibility is not
assumed.

### GET `/tournaments/{tournament_id}`

**Purpose:** Tournament detail.\
**Access:** scoped authenticated user.\
**Success:** settings and lifecycle fields allowed for role.

### PATCH `/tournaments/{tournament_id}`

**Purpose:** Edit permitted settings.\
**Access:** Admin or assigned Organizer.\
**Request:** partial allowed fields, with `expected_version` recommended
for optimistic concurrency.\
**Rules:** Organizer cannot edit unassigned tournament. After deadline,
ordinary change requires Admin deadline extension first. Emergency
override is separate endpoint.\
**Errors:** `403`, `404`, `409`, `422`.

### POST `/tournaments/{id}/submit-for-approval`

**Purpose:** Submit Organizer-created draft for Admin approval.\
**Access:** Creating Organizer.\
**Success:** `{"status":"pending_approval"}`.

### POST `/tournaments/{id}/approve`

**Purpose:** Approve tournament.\
**Access:** Admin only.\
**Request:** `{"confirm":true}`\
**Success:** `{"status":"approved"}`.

### POST `/tournaments/{id}/reject`

**Purpose:** Reject tournament with reason.\
**Access:** Admin only.\
**Request:** `{"reason":"Please correct the tournament schedule."}`\
**Success:** `{"status":"rejected","reason":"..."}`.

### POST `/tournaments/{id}/extend-deadline`

**Purpose:** Extend registration or submission deadline.\
**Access:** Admin only.\
**Request:**

``` json
{
  "deadline_type": "registration",
  "new_deadline": "2027-01-15T18:00:00Z",
  "reason": "Approved extension",
  "confirm": true
}
```

**Success:** updated deadline, affected participant count, notification
event ID. Unused invitation codes remain valid until the new
registration deadline. Submission extension reopens submissions.\
**Errors:** `400`, `403`, `409`, `422`.

### POST `/tournaments/{id}/emergency-override`

**Purpose:** Admin emergency change after lock without extending
deadline.\
**Access:** Admin only.\
**Request:**
`{"setting":"...","value":"...","reason":"...","confirm":true}`\
**Success:** updated setting and audit event. Must notify affected
participants with setting, reason, time, and authorizer.\
**Errors:** `400`, `403`, `409`.

### POST `/tournaments/{id}/archive`

**Purpose:** Archive tournament and delete replay files.\
**Access:** Admin or assigned Organizer, subject to tournament lifecycle
policy.\
**Request:** `{"confirm":true}`\
**Success:** `{"status":"archived","replays_deleted":true}`. Results,
brackets, standings, and match history remain.

### DELETE `/tournaments/{id}`

**Purpose:** Permanently delete tournament operational data.\
**Access:** Admin only.\
**Request:** `{"confirm":true,"reason":"..."}`\
**Success:** `{"status":"deleted","audit_event_id":"..."}`. Audit logs
remain permanently.\
**Errors:** `403`, `409`, `422`.

## 4. Roster, teams, invitations --- BIO-EPIC-05

### POST `/tournaments/{id}/roster/import`

**Purpose:** Import official roster.\
**Access:** Admin or assigned Organizer.\
**Request:** multipart roster file or validated JSON. `[DECIDE]` file
format.\
**Success:** import summary with created/updated/rejected rows.\
**Rules:** corrections allowed before participant registration locks the
row. No editing locked participant identity/team/member number/role.

### PATCH `/tournaments/{id}/roster/{entry_id}`

**Purpose:** Correct an unregistered roster entry.\
**Access:** Admin or assigned Organizer.\
**Request:** allowed fields only.\
**Errors:** `403`, `404`, `409` if participant already registered.

### POST `/tournaments/{id}/invitation-codes`

**Purpose:** Issue invitation codes for eligible roster entries.\
**Access:** Admin or assigned Organizer for initial issuance;
replacement issuance is Admin-only.\
**Request:** `{"roster_entry_ids":["..."]}`\
**Success:** issuance summary. Secret code values must be shown only to
authorized issuer at issuance and stored hashed where feasible.

### POST `/tournaments/{id}/invitation-codes/{code_id}/revoke`

**Purpose:** Revoke lost/compromised code.\
**Access:** Admin only.\
**Request:** `{"reason":"Reported compromised","confirm":true}`\
**Success:** revoked status and audit event.

### POST `/tournaments/{id}/invitation-codes/{code_id}/replace`

**Purpose:** Issue replacement code.\
**Access:** Admin only.\
**Request:**
`{"reason":"Replacement for compromised code","confirm":true}`\
**Success:** replacement issued. Old code remains unusable.

### GET `/teams/{team_id}`

**Purpose:** Team profile.\
**Access:** team members, assigned Organizer, Admin.\
**Success:** team data with deleted members omitted from historical
roster display.

### DELETE `/teams/{team_id}`

**Purpose:** Delete archived tournament team operational profile.\
**Access:** Admin or assigned Organizer, only after tournament archive.\
**Request:** `{"confirm":true,"reason":"..."}`\
**Success:** deleted state and audit event. Historical results/audit
retained.

### POST `/teams/{team_id}/restore`

**Purpose:** Restore deleted team.\
**Access:** Admin only.\
**Success:** restored state. Not available after permanent tournament
deletion.

## 5. Bot submissions --- BIO-EPIC-05

### POST `/teams/{team_id}/submissions`

**Purpose:** Upload a new bot version.\
**Access:** Team participant with submission permission; captain-only is
`[DECIDE]`.\
**Request:** multipart file named exactly `bot.py`; include idempotency
key.\
**Success `202`:**

``` json
{
  "submission_id": "sub_123",
  "version": 4,
  "status": "validating"
}
```

**Errors:** `400`, `403`, `409` deadline closed, `413`, `415`, `422`.
Invalid upload must not replace current active version.

### GET `/teams/{team_id}/submissions`

**Purpose:** List own team's submission versions/history.\
**Access:** team members, assigned Organizer, Admin.\
**Success:** version, timestamp, validation status/reason, active flag,
match usage references. Source access remains private.

### GET `/submissions/{submission_id}/download`

**Purpose:** Download source file.\
**Access:** owning team, assigned Organizer, Admin.\
**Success:** authorized file stream. No public URL.

### GET `/submissions/{submission_id}/validation`

**Purpose:** Read validation outcome.\
**Access:** owning team, assigned Organizer, Admin.\
**Success:** structured checks and safe error messages.

### POST `/submissions/{submission_id}/activate`

**Purpose:** Manual activation only if product later requires it.\
**Access:** Admin-only operational override, not a participant action.
`[DECIDE]` Prefer automatic activation of latest valid version and omit
this endpoint if no manual override is required.

## 6. Brackets, matches, results, replays --- BIO-EPIC-03/06

### POST `/tournaments/{id}/bracket/generate`

**Purpose:** Generate single-elimination bracket.\
**Access:** Admin or assigned Organizer before bracket lock.\
**Request:** `{"confirm":true}`\
**Success:** bracket version and pairing summary. Random pairing,
automatic byes, human-team bye priority; house-bot rules pending
decision.

### POST `/tournaments/{id}/rounds/{round_id}/start`

**Purpose:** Start the next sequential round.\
**Access:** assigned Organizer or Admin.\
**Request:** `{"confirm":true,"idempotency_key":"..."}`\
**Success:** round enters `running`; match jobs queued.

### GET `/tournaments/{id}/bracket`

**Purpose:** View bracket and progression.\
**Access:** authenticated tournament participant/staff with access.\
**Success:** bracket, match statuses, scores, advancement.

### GET `/matches/{match_id}`

**Purpose:** Match details/result.\
**Access:** authenticated user with tournament access.\
**Success:** teams, map, status, result, tie-break details, bot version
identifiers; no source code.

### GET `/matches/{match_id}/replay`

**Purpose:** Retrieve replay while retained.\
**Access:** authenticated tournament participant/staff with access.\
**Success:** replay stream or short-lived authorized URL.\
**Errors:** `404` if no access; `410` after archive/deletion.

### GET `/matches/{match_id}/logs`

**Purpose:** Read safe match logs.\
**Access:** scoped participant/staff; sensitive worker/secret data
excluded.\
**Success:** redacted execution summary. Detailed staff diagnostics may
be Admin-only.

## 7. Notifications and audit --- BIO-EPIC-04/06

### GET `/notifications`

**Purpose:** List current user's notifications.\
**Access:** Authenticated.\
**Success:** dashboard notification feed.

### PATCH `/notifications/{id}`

**Purpose:** Mark notification read.\
**Access:** recipient only.\
**Request:** `{"read":true}`.

### PATCH `/me/notification-preferences`

**Purpose:** Configure email preference.\
**Access:** Authenticated.\
**Request:** `{"email_enabled":false}`. Dashboard notifications remain
mandatory and cannot be disabled.

### GET `/tournaments/{id}/audit-logs`

**Purpose:** Read scoped audit log.\
**Access:** Admin global; assigned Organizer for assigned tournament;
Participant for own team/tournament-relevant entries.\
**Success:** redacted, paginated immutable records.

## 8. Internal match-worker contract (not public API)

The worker interface should be implemented behind a queue/job boundary,
not exposed as a public HTTP endpoint.

**Input fields:** - `match_id` - `tournament_id` - `map_id` / immutable
map version - `engine_version` - `runtime_image_digest` - two immutable
`submission_id`/version references - seed - resource-limit profile ID -
attempt number - trace/correlation ID

**Worker output fields:** - `execution_status`:
`completed | bot_failure | platform_failure` - winner/loser or tie - bot
failure reason where applicable - engine exit status - resource usage
measurements - replay artifact reference - structured logs - map, seed,
runtime and submission versions echoed back

**Critical rules:** - Never trust a worker-supplied team or submission
relationship without validating against the match record. - A bot
failure is a game result; a platform failure is a retryable
infrastructure incident. - Platform retry uses the same map and bot
versions with a new seed. - Retry cap alerts Admin. - Worker jobs must
be idempotent; duplicate delivery must not publish duplicate results or
advance a bracket twice.

## 9. Contract rules and unresolved decisions

1.  Confirm auth/session model, pagination, upload size, roster file
    format, and storage strategy.
2.  Confirm whether invitation codes are per participant or team.
3.  Confirm participant upload authority (captain-only or all members).
4.  Confirm whether manual activation endpoint is needed; automatic
    latest-valid activation is the expected rule.
5.  Confirm exact worker retry attempt count.
6.  Confirm what match logs participants may view versus staff
    diagnostics.
7.  Confirm whether live match state requires a websocket endpoint.
8.  API must never return another team's source file or a long-lived
    public storage URL.
9.  Use optimistic concurrency for settings/bracket state where
    concurrent edits could corrupt tournament state.
10. All important mutations must create immutable audit events and
    notification events where required.

## 10. Reusable implementation prompt

Implement the API contract for the current Jira epic only. Preserve the
stated HTTP method, route, role, scope, state transition, and error
behavior. Enforce permissions on the server. Do not leak source files,
invitation secrets, or personal data. Add request/response validation
and tests for both allowed and denied cases. Treat `[DECIDE]` items as
unresolved and do not silently choose a behavior. For worker
integration, inspect the real Battlecode runner interface rather than
inventing engine APIs.
