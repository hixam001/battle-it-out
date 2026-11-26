# Battle It Out --- API Contract

**Version:** 1.3 (BIO-607 recipient notification API; CN-030)\
**Status:** Proposed core contract with the implemented feature subset identified below\
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

### 1.1 Implemented HTTP boundary --- BIO-404 / CN-029

The Django feature API now implements the error envelope above for application
and framework responses under `/api/v1`. Every response receives a fresh
server-generated `X-Request-ID` (`req_` plus 32 hexadecimal characters); every
error repeats it in `error.request_id` and includes object-shaped `details`.
Caller-supplied IDs are ignored. Responses use `private, no-store`, including
login failures and framework errors. Idempotent replays receive new request IDs;
stored mutation results do not retain request correlation metadata.

The common status/code pairs above are implemented; additional framework pairs
are `405 METHOD_NOT_ALLOWED` and `406 NOT_ACCEPTABLE`. Original HTTP status,
`Allow`, `Retry-After` and cookies survive normalization. Known library refusals
map to their documented `403`/`404`/`409`/`413`/`503` statuses. Single validation
messages remain actionable; field errors appear in `details`. All `404` errors
use generic identical wording, and all server errors have fixed wording with
empty details, including when debug mode is enabled. Unexpected exceptions,
including ordinary `ValueError`, stay server failures and reach Django logging.

GET/HEAD `/health/` is public, returns `200 {"status":"ok"}`, and checks only
web-process liveness. It does not access accounts, PostgreSQL, JSON stores or the
engine; database/worker readiness and production health monitoring remain open.
The implemented `/auth/login/` takes JSON `username`/`password` (CN-028) and now
returns `415` for unsupported request media types. CSRF refusals use the same
JSON envelope without exposing origin/configuration diagnostics.

This slice does not standardize pagination, add missing core endpoints or
extend idempotency/concurrency to every mutation. Those BIO-404 gaps remain open.

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
**Success:** user identity, `roles`, `access_version`, verified
team/tournament memberships and active Organizer assignments (IDs only),
notification preferences. An unverified claim is not an authorized
membership. `roles` is a list representation; multiple-role policy remains
`[DECIDE]` (see §2.1). Never return password hashes or invitation secrets.

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

### 2.1 Identity and authorization rules --- BIO-406

**Proposal, not implemented or owner-approved:** §2.1–2.3 close the
contract gap identified in CN-024. CN-026 records the proposed choices.
The role/scope requirements remain PRD §6.6 and DATA_MODEL §7. DEC-11
still gates API implementation; no auth mechanism is selected here.

- Authenticate to a server-owned `User.id`, then load current account
  status, effective role grants, active Organizer assignments and verified
  registration memberships. Reject suspended/deleted accounts. A claim
  awaiting email verification gives no team or tournament authority.
- Build each library `Actor` through one trusted adapter: `user_id` from
  authentication; staff role from grants; Organizer `tournament_ids` from
  active assignments; participant `team_ids`, `captain_of` and
  `tournament_ids` from verified registration. The existing
  `registration.actor_for` supplies the participant membership rules, not
  account authentication. Never deserialize an `Actor` from a request.
- Resolve every resource's tournament/team from stored relationships.
  A supplied path ID identifies a target; it never proves ownership.
  Reject unexpected body fields, including client-supplied authority,
  `assigned_by`, `granted_by`, or membership/captain flags.
- Check the operation as well as scope: assignment does not allow
  approving a tournament, replacing codes, editing locked roster fields,
  or changing/activating a participant submission. A platform role is
  separate from the locked roster's member/captain role; changing grants
  cannot create a registration, change a team or bypass verification.
- Apply current authorization before returning an idempotent replay or
  issuing a file response. Revocation must take effect on subsequent
  requests using existing sessions/tokens; stale role claims or caches
  cannot preserve access. Recheck permission with the mutation's commit
  so a concurrent revocation cannot authorize a later write.
- `401` means no valid authentication. On Admin-only user/role routes,
  authenticate and reject non-Admins with `403` before looking up target
  IDs. For tournament routes, hidden and nonexistent tournaments (or
  mismatched child IDs) both return `404 NOT_FOUND`; a caller who can see
  the tournament but lacks the operation receives `403 FORBIDDEN`.
- Role/assignment changes and their redacted audit event commit together
  or through a durable transactional outbox. A failed audit write cannot
  leave changed access without a durable event. A no-op retry creates no
  second transition/event. These are permanent BIO-407 audit records,
  not the current libraries' bounded local audit lists.
- Every role/assignment mutation requires `Idempotency-Key`, an integer
  `expected_version` from the relevant current record, `confirm:true` and a
  non-empty trimmed `reason`. Keys are scoped to authenticated caller and
  method/target; reusing a key with a different payload is `409`. After
  current authorization, an identical replay returns its stored response
  before revision comparison. A fresh request with a stale revision
  conflicts even when it would otherwise be a no-op.

`[DECIDE]` One role or multiple roles per account, combinations of staff
and participant roles, and permission composition if multiple are allowed.
The current `Actor.role` is singular; neither an implicit role union nor
a client-selected role is authorized by this proposal. Resolve the policy
and adapter design before implementing role mutation. Initial Admin/staff
account provisioning and recovery also need an owner decision; public
registration never accepts a requested staff role.

### 2.2 Users and roles --- BIO-406

All routes in this subsection are **Admin-only**. Other users use `/me`
and existing scoped team/roster routes. They do not get a global user
directory, account-email lookup or another user's profile.

#### GET `/users`

**Purpose:** Find existing accounts for access administration.\
**Success `200`:** paginated summaries with only `id`, `email`, `status`,
`email_verified_at`, `roles`, `access_version`. Pagination follows the
still-open §1 decision. Deleted-account email is omitted under the
account-deletion policy. No password hashes, tokens, invitation secrets,
source files or cross-tournament membership expansion.\
**Errors:** `400` invalid query, `401`, `403`.

#### GET `/users/{user_id}`

**Purpose:** Read the same account summary and its current role revision
before a change.\
**Success `200`:** one summary in the `/users` shape.\
**Errors:** `401`, `403`, `404` unknown user.

#### GET `/roles`

**Purpose:** Read the fixed role catalogue.\
**Success `200`:** `{"roles":["ADMIN","ORGANIZER","PARTICIPANT"]}`.
Wire names map explicitly to the libraries' lowercase role strings.
No custom-role creation or permission-editing endpoint is proposed.\
**Errors:** `401`, `403`.

#### PUT `/users/{user_id}/roles`

**Purpose:** Replace the account's effective role set atomically, after
the role-cardinality decision above.\
**Request:** `Idempotency-Key` header and:

``` json
{
  "roles": ["ORGANIZER"],
  "expected_version": 3,
  "reason": "Appointed to tournament operations",
  "confirm": true
}
```

**Success `200`:** `user_id`, effective `roles`, new `access_version`,
`audit_event_id`. `expected_version` compares the user's `access_version`,
not a profile/settings revision. Duplicate names and unknown roles are
invalid. A list representation does not decide how many grants are legal.\
**Rules (proposed):** only an existing verified active account may receive
grants. A role change never edits locked roster fields or credentials.
With a current revision, replacing roles with the same set is a `200`
no-op: unchanged `access_version` and `audit_event_id:null`.
Removing `ORGANIZER` revokes all active assignments in the same commit;
restoring the role never restores revoked assignments. Serialize changes
that remove Admin access so they cannot remove the last active Admin;
the initial-Admin/recovery path remains separate and unresolved.\
**Errors:** `400` missing/invalid fields, `401`, `403`, `404` unknown user,
`409 STATE_CONFLICT` stale revision, ineligible account, last-Admin
removal, or idempotency key reused with a different request. An identical
retry returns the stored response only after current authorization.

### 2.3 Organizer assignments --- BIO-406

An assignment grants tournament scope only while its account has the
effective `ORGANIZER` role. Admin access remains global. Assignment does
not change tournament approval, deadlines, team membership or roster locks.
Admin manages assignments; Organizers cannot assign themselves or others.

#### GET `/tournaments/{tournament_id}/organizer-assignments`

**Access:** Admin or currently assigned Organizer; no participant access.\
**Success `200`:** paginated assignment records plus the tournament's
`access_version`. Each record exposes only `id`, `tournament_id`,
`organizer_user_id`, `assigned_by`, `assigned_at`, `revoked_by`, `revoked_at`.
Default list contains active assignments; `include_revoked=true` is
Admin-only. Organizer responses do not expand account email/profile or
include audit reasons.\
**Errors:** `400` invalid query, `401`, `403`, safe `404` per §2.1.

#### POST `/tournaments/{tournament_id}/organizer-assignments`

**Access:** Admin only.\
**Request:** `Idempotency-Key` header and:

``` json
{
  "organizer_user_id": "usr_123",
  "expected_version": 2,
  "reason": "Assigned to operate this tournament",
  "confirm": true
}
```

**Success `201`:** `assignment`, new tournament `access_version`,
`audit_event_id`. `assigned_by` and timestamps are server-owned.
`expected_version` compares the tournament's assignment revision
(`access_version`), separate from its settings `version`.\
**Rules:** target account must be verified, active and hold `ORGANIZER`;
tournament must exist and not be deleted. At most one active assignment
per user/tournament. With a current revision, an already-active pair is a
`200` no-op with the existing assignment and unchanged revision (no new
audit event; `audit_event_id:null`). A revoked pair gets a new assignment
ID when reassigned.\
**Errors:** `400`, `401`, `403`, `404` unknown tournament/user,
`409` stale revision, ineligible user, deleted tournament, or key conflict.

#### DELETE `/tournaments/{tournament_id}/organizer-assignments/{assignment_id}`

**Access:** Admin only.\
**Request:** `Idempotency-Key` header and
`{"expected_version":3,"reason":"Assignment ended","confirm":true}`.\
**Success `200`:** revoked `assignment`, new tournament `access_version`,
`audit_event_id`. This revokes access, not the history record. With a
current revision, an already-revoked assignment is a `200` no-op with
unchanged revision and `audit_event_id:null`.\
**Errors:** `400`, `401`, `403`, `404` missing or cross-tournament
assignment, `409` stale revision or key conflict.

**Creator and revocation rules (proposed):** creating an Organizer draft
also creates that Organizer's assignment and its audit event atomically.
The creator remains subject to Admin approval. Creation is the only
automatic assignment; after revocation, `created_by` remains history and
cannot grant access, including edit/resubmit. Removing the `ORGANIZER`
role revokes assignments and increments each affected tournament's
`access_version`; role and assignment mutations must serialize with each
other. Reassignment never revives old records. Tournament deletion removes
operational assignments while retaining their permanent redacted audit.
The current `tournaments._manages` creator fallback must be replaced when
BIO-406 is implemented; constructing an empty-scope `Actor` alone cannot
enforce creator revocation. No current library behavior changes here.

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
**Access:** Creating Organizer with a current assignment (see §2.3).\
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

### POST `/tournaments/{id}/extend-deadline/`

**Purpose:** Extend registration or submission deadline.\
**Access:** Current Admin session, session CSRF, and `Idempotency-Key`.\
**Request:**

``` json
{
  "deadline_type": "registration",
  "new_deadline": "2027-01-15T18:00:00Z",
  "reason": "Approved extension",
  "confirm": true
}
```

The new time must include a timezone and be later than both the current
deadline and the present time. Registration may not extend past submission.
Unused codes follow the registration deadline. Extending submission reopens
uploads while the tournament is open and its entry versions are unpinned.

### POST `/tournaments/{id}/emergency-override/`

**Purpose:** Admin emergency change after lock without extending
deadline.\
**Access:** Current Admin session, session CSRF, and `Idempotency-Key`.\
**Request:**
`{"setting":"...","value":"...","reason":"...","confirm":true}`\
The supported settings are `name`, `description`, and `map_pool_id`.
A supplied pool ID must exist. The map pool is fixed once entries are
pinned or the draw is recorded. The notice records the setting, reason,
time and authorizer. An override leaves the deadlines in place.

**Implemented (BIO-602 / CN-041):** Both actions return `200` with the
updated `tournament`, `audit_event_id`, `notification_event_id`,
`affected_participants` and `notification_status`. The audience contains
accounts holding an official roster place, including pending verification.
`published` means the dashboard notices exist and eligible email delivery is
queued. `pending` means the change and its notice are durably committed and
service maintenance will retry publication. Repeating the same key and
normalized action as the same Admin reuses the recorded result and can finish
pending publication. A different deadline action under that key returns
`409`. Invalid input is `400`, hidden resources are `404`, and forbidden
or conflicting lifecycle actions return `403` or `409`.

### POST `/tournaments/{id}/archive`

**Purpose:** Archive tournament and delete replay files.\
**Access:** Admin or assigned Organizer, subject to tournament lifecycle
policy.\
**Request:** `{"confirm":true}`\
**Success:** `{"status":"archived","replays_deleted":true}`. Results,
brackets, standings, and match history remain.

**Implemented (BIO-606 / CN-035):** `POST /api/v1/tournaments/{id}/archive/`
requires a current Admin session or explicit Organizer assignment, session CSRF
and exactly the JSON confirmation above. A visible participant receives `403`.
Missing, deleted and out-of-scope tournaments share `404`. An invalid lifecycle
state or exhausted audit capacity returns `409` before vault changes.

The archive transition is recorded once. `200` with `replays_deleted:false`
means archive succeeded and the on-disk purge needs retry. The archive blocks
vault access in either case. Maintenance retries interrupted/failed purges;
another confirmed request verifies the folder again without duplicating the
archive event. This response describes the shared replay vault. Worker output,
backups and production storage follow their retention workflows.

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

**Implemented (BIO-603 / CN-034):** `GET /api/v1/tournaments/{id}/bracket/`
returns `tournament_id` and a `bracket` object once a draw is stored. The bracket
contains the recorded draw, registered playoff teams, map-pool ID when recorded,
rounds, pairings, byes, game IDs/status, advancement and champion. The `bracket`
field is `null` before a draw. Scores require additional engine result data.

### GET `/matches/{match_id}`

**Purpose:** Match details/result.\
**Access:** authenticated user with tournament access.\
**Success:** teams, map, status, result, tie-break details, bot version
identifiers; no source code.

**Implemented (BIO-603 / CN-034):** `GET /api/v1/matches/{match_id}/` takes
a game ID exposed by the bracket pairing's `series.games`. The response contains
`tournament_id`, selected `match_id`, `round_number` and the enclosing `series`.
The series reports the two pinned version IDs, maps, ordered game outcomes,
winner/result type and recorded coin flip when applicable. A drawn/paused game
without a decision has a `null` result. Engine scores, raw paths, diagnostics,
and replay availability are outside this projection.

Both reads use current participant membership, explicit Organizer assignment or
Admin scope. Archived tournaments retain results. Missing, deleted and hidden
objects return the same `404`. Responses are private and non-cacheable.

### GET `/matches/{match_id}/replay`

**Purpose:** Retrieve replay while retained.\
**Access:** authenticated tournament participant/staff with access.\
**Implemented (BIO-605 / CN-032):** `GET /api/v1/matches/{match_id}/replay/`
streams the current vault artifact as an `application/octet-stream` attachment
with a `.bc26` filename and `Cache-Control: private, no-store`. Use the game
`match_id`, distinct from `series_id`; the live match list exposes both IDs.
A session and current verified roster membership, explicit Organizer assignment,
or Admin scope are required. The route verifies the opened file against the
vault digest and rechecks vault archive state before returning the stream.

**Errors:** `401` for no session. A missing vault entry, deleted tournament or
record outside current scope returns the same `404`. A visible archived replay
returns `410`, including for Admins. An indexed replay with a missing or damaged
file returns `503` and records a staff incident. Errors use the shared JSON
envelope even when the client requests `application/octet-stream`.

The archive boundary blocks new downloads. A download admitted before the
archive boundary may already be in progress. Object storage and browser
playback remain follow-up work.

### GET `/matches/{match_id}/logs`

**Purpose:** Read safe match logs.\
**Access:** scoped participant/staff; sensitive worker/secret data
excluded.\
**Success:** redacted execution summary. Detailed staff diagnostics may
be Admin-only.

## 7. Notifications and audit --- BIO-EPIC-04/06

**Implemented recipient subset (BIO-607 / CN-030):** the notification routes
below use canonical trailing slashes and the existing shared notification store.
The session account must have the explicit operator-provisioned participant
roster link described in CN-028. No recipient ID comes from the request or from
the Django account's numeric ID. Staff privileges do not grant inbox access.
Unlinked and staff accounts return `403`; their recipient provisioning and
approval/rejection notices remain follow-up work. Anonymous requests return
`401`. Link changes take effect on the next request. Personal notices remain
recipient-owned after tournament scope ends; filtering a nonexistent tournament
returns an empty feed without disclosing its existence.

### GET `/notifications`

**Purpose:** List current user's notifications.\
**Access:** linked authenticated recipient, as above.\
**Query:** optional `limit` (1–200, default 50), `offset` (0–2147483647,
default 0), `unread_only` (`true` or `false`, default `false`) and
`tournament_id` (safe opaque identifier). Unknown/repeated parameters and invalid
values return `400`.\
**Success:** `200 {"items":[],"total":0,"unread":0}`. Items contain only `id`,
`tournament_id`, `event_type`, `title`, `body`, `created_at`, `read`, `read_at`
and `email_status`. Delivery errors, provider metadata, event keys and recipient
IDs are excluded. Sort is newest first, then ID for equal timestamps. `total`
counts the filtered feed before paging; `unread` counts unread items in the
tournament filter before the `unread_only` filter and paging.

This is the existing library's bounded offset pagination as an interim adapter,
not a global pagination decision. Pages are independent reads; concurrent new
notices can shift offsets. Global cursor/snapshot behavior remains BIO-404 work.

### PATCH `/notifications/{id}`

**Purpose:** Set read/unread state.\
**Access:** linked recipient only, including for same-team notices.\
**Request:** exactly `{"read":true}` or `{"read":false}`, with a JSON boolean.\
**Success:** `200`, the updated notification in the same item format. Repeating
the same state preserves `read_at`; setting unread clears it. Missing/foreign
IDs receive identical generic `404` errors. Mutations require session CSRF and
JSON (`415` for unsupported media, `400` for malformed/invalid bodies).

### GET `/me/notification-preferences`

**Purpose:** Read current recipient's email preference.\
**Access:** linked authenticated recipient.\
**Success:** `200 {"email_enabled":true,"dashboard_enabled":true}` by default.

### PATCH `/me/notification-preferences`

**Purpose:** Configure email preference.\
**Access:** linked authenticated recipient; session CSRF required.\
**Request:** exactly `{"email_enabled":false}` or `{"email_enabled":true}`
as JSON. Extra fields, non-boolean values and dashboard-disable attempts return
`400`; unsupported media returns `415`.\
**Success:** `200`, the preference object above. Dashboard notifications remain
mandatory. The service worker reads the same preference and rechecks queued
emails before delivery; disabling email does not remove dashboard notices.
Changes and their preference audit share the notification-store transaction.
Store/audit capacity conflicts return `409` and roll back the preference.

Both PATCH routes set an absolute state and are naturally idempotent; this
slice needs no idempotency-key receipt. Every response uses CN-029's fresh
request ID and `private, no-store`; errors use the shared envelope. No SQL/JSON
cross-store transaction or full notification database migration is claimed.
The [participant inbox](../frontend/README.md) uses these endpoints (CN-031).
Announcements, automatic extension/override notices, real email providers and
mandatory security-email policy remain open.

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
11. `[DECIDE]` One role or multiple roles, staff/participant combinations
    and permission composition; initial Admin/staff account provisioning
    and recovery. CN-026's Admin-only grant/assignment control, last-Admin
    protection and creator/revocation rules are proposals awaiting review.

## 10. Reusable implementation prompt

Implement the API contract for the current Jira epic only. Preserve the
stated HTTP method, route, role, scope, state transition, and error
behavior. Enforce permissions on the server. Do not leak source files,
invitation secrets, or personal data. Add request/response validation
and tests for both allowed and denied cases. Treat `[DECIDE]` items as
unresolved and do not silently choose a behavior. For worker
integration, inspect the real Battlecode runner interface rather than
inventing engine APIs.


## 11. Implemented feature API — CN-028 / CN-029

The owner activated BIO-REQ-19–23 and selected Django/DRF/PostgreSQL with a React
frontend. The authoritative implemented route table, session/CSRF behavior,
private access rules and request shapes are in the
[web application README](../backend/webapp/README.md). These routes are a tested
feature slice; older endpoint groups above remain proposed unless implemented.
Canonical new paths use a trailing slash except `analytics.csv`.

- GET/HEAD `/health/` implements process liveness; §1.1 records the shared error/request-ID behavior.
- Session lifecycle: GET `/auth/session/`, POST `/auth/login/`, POST `/auth/logout/`.
- GET `/tournaments/` lists current accessible records; GET `/dependencies/` is a public pinned catalogue.
- GET `/tournaments/{id}/live/` supplies numeric board snapshots and safe match metadata, with current authorization on every poll, private/no-store cache policy and 410 after archive.
- GET `/tournaments/{id}/analytics/` and `/analytics.csv` expose results-derived team/version/map/round and failure/timing statistics. No source, host path or bot output is included.
- GET/POST `/tournaments/{id}/teams/{team}/submissions/` and GET `/tournaments/{id}/submissions/{version}/download/` implement team-private history, captain upload using the stored deadline, queued validation and authorized source/bundle delivery. POST accepts one multipart `file` and requires `Idempotency-Key`.
- GET/POST `/tournaments/{id}/disputes/` and `/disputes/{uuid}/` support match-bound team-private review. Creation body: `series_id`, `title`, `description`. Update body: `expected_version` and either `message`, or staff `status` plus `resolution`. Both mutation forms require `Idempotency-Key`; state/event/audit/receipt persistence is one PostgreSQL transaction. Closing a review does not change match results or replay a game.
- GET `/admin/operations/` is Admin-only and read-only, returning counts, incident metadata, dead jobs and recent feature audit events.

Existing core stores remain JSON. Native Django accounts/sessions plus operator
roster links and Organizer assignments provide current scope for these routes;
public account registration/recovery, global role APIs and the full CN-026
administration/concurrency contract are still open. No full BIO-403 migration,
production hosting, provider integration or complete backend is claimed.
