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
web-process liveness. GET/HEAD `/ready/` is public and probes the default
PostgreSQL connection with the web application's credentials (BIO-404 / CN-051).
It runs `SELECT 1` with a 3-second connection timeout and a 2-second statement
timeout and returns `200 {"status":"ready"}` on success. PostgreSQL connection
or query availability errors return a redacted `503 SERVICE_UNAVAILABLE`.
Both paths use private/no-store and a fresh request ID. HEAD returns no body.
Worker, engine, JSON-store and deployment readiness remain separate.
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

The draft, detail, edit, approval and opening routes below are implemented for
the scoped Django API (BIO-601 / CN-047). Mutations use JSON and session CSRF.
Detail and mutation responses include a `version` and ISO 8601 UTC deadline
fields. A hidden or missing tournament returns `404`.

### POST `/tournaments/`

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

**Success `201`:** tournament object with a server-generated ID and
`status:"draft"`. An Organizer receives an explicit assignment to their draft.
The required `Idempotency-Key` binds the normalized request to this account.
An identical retry returns the current tournament, a changed request using the
same key conflicts, and revocation blocks a retry from recreating access.\
**Errors:** `400`, `403`, `404`, `409`.

### GET `/tournaments`

**Purpose:** List tournaments visible to caller.\
**Access:** Authenticated; Admin global, Organizer assigned, Participant
registered/eligible visibility.\
**Success:** `items` and caller `role`, using the existing list response for
the console. A summary keeps `deadlines` in epoch seconds and `teams` limited
to the caller's verified teams. Global pagination remains part of BIO-404.

### GET `/tournaments/{tournament_id}`

**Purpose:** Tournament detail.\
**Access:** scoped authenticated user.\
**Success:** settings, status and version. Staff also see approval and
rejection metadata. Participant detail is limited to the tournaments they
have joined once registration opens, including archived tournaments.

### PATCH `/tournaments/{tournament_id}`

**Purpose:** Edit permitted settings.\
**Access:** Admin or assigned Organizer.\
**Request:** `expected_version` as a positive integer and at least one of
`name`, `description`, `registration_deadline` or `submission_deadline`.
The dedicated map-pool endpoint validates a pool before selecting it.\
**Rules:** Organizer cannot edit unassigned tournament. After deadline,
ordinary change requires Admin deadline extension first. Emergency
override is separate endpoint.\
**Errors:** `400`, `403`, `404`, `409`.

### POST `/tournaments/{id}/submit-for-approval`

**Purpose:** Submit Organizer-created draft for Admin approval.\
**Access:** Creating Organizer with a current assignment (see §2.3).\
**Request:** `{"expected_version":1}`. The same route accepts a rejected
draft at its current version.\
**Success:** updated tournament with `status:"pending_approval"`.

### POST `/tournaments/{id}/approve`

**Purpose:** Approve tournament.\
**Access:** Admin only.\
**Request:** `{"confirm":true,"expected_version":2}`. Admin-created
drafts can be approved directly.\
**Success:** updated tournament with `status:"approved"`.

### POST `/tournaments/{id}/reject`

**Purpose:** Reject tournament with reason.\
**Access:** Admin only.\
**Request:** `{"reason":"Please correct the tournament schedule.","expected_version":2}`.\
**Success:** updated tournament with `status:"rejected"` and
`rejection_reason`. The rejection keeps its audit entry after resubmission.

### POST `/tournaments/{id}/open-registration/`

**Access:** Current Admin or assigned Organizer.\
**Request:** `{"expected_version":3}`.\
**Success:** updated tournament with `status:"registration_open"`.
Only an approved tournament can open, and its registration deadline must be
in the future. A stale version or a conflicting state returns `409`.

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

### POST `/tournaments/{id}/roster/import/`

**Purpose:** Import official roster.\
**Access:** Current Admin or explicitly assigned Organizer, session CSRF
and `Idempotency-Key`.\
**Request:** The existing CN-020 formats are supported. Send one UTF-8 CSV
part named `file` with columns `email,team_key,team_name,member_number,role`,
or JSON containing a `rows` array of those objects. The interim limits are
1 MiB and 2,000 rows.\
**Success:** `200` with `batch_id`, `created`, `updated`, `unchanged` and
redacted `rejected` row numbers and reasons. Rows are assessed individually.
A retry by the same actor for the same tournament and key reuses the batch
summary. A different payload under the same key returns `409`. The roster
store retains the audited summary and discards the file.

### PATCH `/tournaments/{id}/roster/{entry_id}/`

**Purpose:** Correct an unregistered roster entry.\
**Access:** Current Admin or explicitly assigned Organizer with session CSRF.\
**Request:** `expected_version` as a positive integer and at least one of
`email`, `team_key`, `team_name`, `member_number`, `role_label`. A claim
locks the entry. Stale versions and closed or locked entries return `409`.
Hidden and mismatched tournament/entry IDs share `404`.

### GET `/tournaments/{id}/roster/` and GET `/tournaments/{id}/roster/report/`

Current Admins and explicitly assigned Organizers can read the roster and
the exclusion report. The roster includes official email addresses and
row versions for corrections. The report lists status counts, teams
missing a roster or registered captain, and entry IDs excluded after the
stored registration deadline. Both responses are private/no-store.

These four BIO-501 routes use the existing roster and interim format rules
(CN-020/044).

### GET and POST `/tournaments/{id}/invitation-codes/`

**Implemented (BIO-502 / CN-049):** Current Admins and assigned Organizers
can GET `items` with code IDs, roster entry IDs, statuses and issuance and
revocation dates. The list omits code values, hashes and free-form reasons.
Unused status follows the stored registration deadline, including extensions.

POST requires session CSRF and JSON `{"roster_entry_ids":["..."]}` with
1–2,000 IDs. It issues first codes for eligible entries while registration has
an approved future deadline. The `200` response returns `issued` (each with
`entry_id`, `code_id` and `code`) and `skipped` (each with `entry_id` and
`reason`). A repeated issue returns skips for already-issued entries. The
service stores hashes, and only the first successful issuance response
contains the plaintext code.

### POST `/tournaments/{id}/invitation-codes/{code_id}/revoke/`

**Purpose:** Revoke lost/compromised code.\
**Access:** Current Admin session and CSRF.\
**Request:** `{"reason":"Reported compromised","confirm":true}`\
**Success:** `200` with revoked code metadata. The first revocation records
the reason in the audit. Repeating it adds no new audit entry.

### POST `/tournaments/{id}/invitation-codes/{code_id}/replace/`

**Purpose:** Issue replacement code.\
**Access:** Current Admin session and CSRF.\
**Request:**
`{"reason":"Replacement for compromised code","confirm":true}`\
**Success:** `200` with `code_id`, `replaces` and the new `code`. A retry on
the old ID returns `409`. The old code remains unusable. All invitation
responses use private/no-store. Public signup, verification and delivery
remain part of BIO-502.

### GET `/tournaments/{id}/teams/{team_id}/`

**Implemented (BIO-503 / CN-045):** Current verified team members, an
explicitly assigned Organizer and Admin can read `id`, `tournament_id`,
`name` and verified `members` in member-number order. Each member has
`member_number`, `role_label` and `is_captain`. The profile has no contact,
account or invitation data. Archived profiles use the same current scope.
Missing, foreign, mismatched and deleted scopes share `404`.

The roster remains authoritative for team size, official name and captain.
The existing CN-020 rules admit corrections only before a claim locks the
affected entries. Account-deletion cleanup and final DEC-12 policy remain
separate work.

The participant console takes its team selection and upload affordance from
the scoped tournament list. Each console row includes `teams` and
`captain_teams`, the subset the current participant captains. The upload
endpoint still checks current authorization and the stored deadline.

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

### POST `/tournaments/{id}/teams/{team_id}/submissions/`

The registered team captain may upload one multipart `file` with the session
CSRF token and an `Idempotency-Key` header. The file is either a UTF-8
`bot.py` or a flat Python bundle ZIP. The server reads the current submission
deadline from the tournament record.

A successful upload returns `201` with the version record. The check runs
asynchronously on the existing worker. A new version awaiting the check
includes these fields.

``` json
{
  "id": "team-a-v4",
  "version": 4,
  "validation_status": "validating"
}
```

- `400` for missing or duplicate fields and an invalid idempotency key.
- `403` for a visible team without upload privileges, and `404` for hidden or
  mismatched team/tournament scope.
- `409` after the stored deadline or when the same key is used for a different
  submission. A retry of an earlier accepted upload reuses its version.
- `413` for the interim size or ZIP file-count limits, and `415` when the
  request is outside multipart form data.
- `422` for an unsupported filename, invalid ZIP or static bot validation
  failure. A single-file bot that reaches the static check stays in
  history with `error.details.submission_id` and `error.details.reasons`
  including a stable code, actionable message and a line when available.
  No check is queued for it. The active version is retained.

### GET `/teams/{team_id}/submissions`

**Purpose:** List own team's submission versions/history.\
**Access:** team members, assigned Organizer, Admin.\
**Success:** version, timestamp, validation status/reason, active flag,
match usage references. Source access remains private.

The implemented route is `GET /tournaments/{id}/teams/{team_id}/submissions/`.
It returns `items` ordered by version, with `match_ids` for official games in
the requested tournament that reference each version. A visible roster team
with no uploads has an empty history. Staff history reads record a
`submission_history_read` audit event.

### GET `/submissions/{submission_id}/download`

**Purpose:** Download source file.\
**Access:** owning team, assigned Organizer, Admin.\
**Success:** authorized file stream. No public URL.

### GET `/submissions/{submission_id}/validation`

**Purpose:** Read validation outcome.\
**Access:** owning team, assigned Organizer, Admin.\
**Success:** structured checks and safe error messages.

The implemented route is `GET /tournaments/{id}/submissions/{submission_id}/validation/`.
It returns `id`, `tournament_id`, `team_id`, `version`, `is_active`,
`validation_status`, `check_in_progress` and ordered `validations`. Each check
has its stage, outcome, findings and recorded timestamps. Trial summaries can
include side, judgment, outcome, classification, round and runtime. Staff
reads record a `submission_validation_read` audit event. Source bytes and
worker claims are excluded. Both reads use current session scope and the
requested tournament. Unknown, foreign and hidden IDs share `404` errors.

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

The implemented route uses a trailing slash and exact JSON confirmation.
It draws one open tournament after its stored submission deadline using the
registered teams, pinned valid versions and its verified map pool. It returns
`{bracket, excluded}` and preserves an existing draw on retry. Neither the
manual request nor the automatic scheduler starts a round. Pending checks,
an invalid map pool or lifecycle state return `409`. An unavailable server
engine catalogue returns `503`.

### POST `/tournaments/{id}/rounds/{round_id}/start`

**Purpose:** Start the next sequential round.\
**Access:** assigned Organizer or Admin.\
**Request:** `{"confirm":true,"idempotency_key":"..."}`\
**Success:** round enters `running`; match jobs queued.

The implemented route is `POST /tournaments/{id}/rounds/{round_number}/start/`.
It requires session CSRF and the exact JSON confirmation and idempotency key
above. The server rechecks staff access before replaying a saved response.
Results contain `round_number`, `status` and `job_id` (`null` for a completed
round). A later round whose predecessor is incomplete, a paused round or
invalid pinned files return `409`. Repeating a start queues at most one job.

### GET and PUT `/tournaments/{id}/map-pool/`

Admin or explicitly assigned Organizer. GET returns `selected_id`, `version`
and `items` containing the available immutable pool IDs, map names and engine
versions. PUT requires session CSRF and exactly
`{"map_pool_id":"...","expected_version":3}`. It selects an existing pool
under the normal configuration deadline and optimistic version rules. The
generated bracket retains its stored pool. A stale revision or locked
tournament returns `409`.

### GET `/tournaments/{id}/bracket`

**Purpose:** View bracket and progression.\
**Access:** authenticated tournament participant/staff with access.\
**Success:** bracket, match statuses, scores, advancement.

**Implemented (BIO-603 / CN-034):** `GET /api/v1/tournaments/{id}/bracket/`
returns `tournament_id` and a `bracket` object once a draw is stored. The bracket
contains the recorded draw, registered playoff teams, map-pool ID when recorded,
rounds, pairings, byes, game IDs/status, advancement and champion. The `bracket`
field is `null` before a draw. The series includes win counts by side based on
the recorded game outcomes. Raw engine point totals require additional result data.

### GET `/matches/{match_id}`

**Purpose:** Match details/result.\
**Access:** authenticated user with tournament access.\
**Success:** teams, map, status, result, tie-break details, bot version
identifiers; no source code.

**Implemented (BIO-603 / CN-034):** `GET /api/v1/matches/{match_id}/` takes
a game ID exposed by the bracket pairing's `series.games`. The response contains
`tournament_id`, selected `match_id`, `round_number` and the enclosing `series`.
The series reports the two pinned version IDs, maps, ordered game outcomes,
winner/result type, win counts and recorded coin flip when applicable. A drawn/paused game
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

### GET `/matches/{match_id}/logs/`

**Implemented (BIO-605 / CN-046):** Returns the official game's redacted
structured log. The default is the newest recorded attempt with a log.
Pass `attempt` from 1 to 100 to select an earlier attempt. The response
contains `match_id`, `tournament_id`, `attempt` and ordered `items`.

Current members of the two playing teams see shared events and only their
own side's output and usage. An explicitly assigned Organizer sees both
teams. An Admin also sees allowlisted diagnostic fields. The API checks
the worker's recorded size, SHA-256, game, attempt and trace identity before
projecting the log. Host paths, raw worker diagnostics and the storage
metadata are excluded.

An unavailable log reference, missing game or unauthorized scope returns
`404`. An indexed log that fails verification returns `503`. Logs retained
under the existing worker policy remain available after archive to authorized
readers. Replay purge follows the separate archive rules above.

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
Deadline changes publish participant notices (CN-041). Real email providers
and mandatory security-email policy remain open.

### POST `/tournaments/{id}/announcements/`

**Implemented (BIO-607 / CN-052).** Current Admin or assigned Organizer,
with session CSRF and a safe `Idempotency-Key` of 1–128 characters. Send an
exact JSON object with `headline` (up to 120 characters) and `message`
(up to 2,000 characters). Both are nonempty plain text without control
characters. The server trims surrounding whitespace.

**Success:** `201` with `id`, `recipients` and `email_queued`. The server
selects verified roster accounts for that tournament. Each gets one dashboard
notice, and accounts with email enabled get one queued email. An empty
audience returns zero counts. The author, event ID and counts are recorded
in staff audit alongside the inbox entries, delivery queue and retry receipt
in one notification-store transaction. The audit omits announcement text.

The key is scoped to the author and tournament. Retrying the same text
returns the original counts without adding recipients or queuing again.
Changing the text with that key returns `409`. The tournament must be
approved, registration open, running or completed on every attempt.
Unavailable lifecycle states and capacity conflicts return `409`.
Hidden, deleted and missing tournaments share `404`. The authoring screen
and real email delivery remain follow-up work.

### GET `/tournaments/{id}/audit-logs/` and GET `/admin/audit-logs/`

**Implemented (BIO-610 / CN-042):** Read-only audit across PostgreSQL feature
actions and existing tournament, registration, submission and notification
audit stores. BIO-407 / CN-048 and CN-050 add official series history and
match, queue and replay incident events. Both routes return `items` and a
nullable `next_offset`.
The optional parameters are `limit` (1–200, default 50) and `offset`
(0–2147483647). Records are ordered newest first with a deterministic
source and sequence tie-break. Appends can shift offset pages.

The tournament route uses current verified roster or explicit Organizer scope.
Participants see public lifecycle events, their own teams' upload/verdict
metadata, disputes and official series history. Assigned Organizers see
tournament staff activity and official series history. Incident openings and
resolutions are visible to Admins. The global route additionally accepts
`tournament_id`, including IDs of deleted tournaments with retained audit.
Missing and hidden scoped tournaments share `404`. Archive retains access
for currently authorized roles.

Records contain `id`, `source`, `action`, `created_at`, `tournament_id`,
an explicit `detail` projection and a role-appropriate `actor_id` for staff.
Series records include the series ID and stage, with a stored coin-flip ID
and winning side and team for a flip. Incidents include their ID, type and
`incident_source` (`match`, `queue` or `replay`), plus game ID, job ID and
kind, or attempt count when recorded. Match and round-job events use the
stored bracket, and submission-check jobs use the stored version's tournament.
Replay incidents use the vault index's tournament ID. Unassigned events
appear only in the unfiltered Admin feed.
Free-form reasons, invitation/provider credentials, source and host paths are
excluded. Private/no-store and the shared error envelope apply.

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

- GET/HEAD `/health/` checks process liveness and `/ready/` probes PostgreSQL.
- Session lifecycle: GET `/auth/session/`, POST `/auth/login/`, POST `/auth/logout/`.
- GET `/tournaments/` lists current accessible records.
- GET `/dependencies/` is public. It returns `items` with a `name`, exact
  `version`, reviewed `sha256` and `description` for each verified release,
  plus the interim `max_files` and `max_bytes` limits. A bundle may declare
  one version per name in `requirements.json`. Stored bundles keep their
  original release pins.
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
