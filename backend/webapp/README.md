# Django feature platform (CN-028)

The owner activated BIO-REQ-19–23 on 2026-11-26 and selected Django/DRF,
PostgreSQL and React/TypeScript. The first language expansion is **flat Python
modules plus curated dependencies**; other languages follow engine compatibility
work. Live viewing remains private to signed-in tournament members, assigned
Organizers and Admins. Hosting, email and object storage are still undecided.

This app adds real HTTP endpoints and PostgreSQL records around the existing
execution libraries. Existing tournament/registration/submission/match stores
remain JSON; this is not the full BIO-403 database migration or every core API.

The React app in [frontend](../../frontend/README.md) supplies the public landing
page, private match room, analytics, bot uploads, disputes and an Admin operations
reader. No production deployment is included.

## Install and run

Run commands from the repository root. Provision PostgreSQL and the existing
engine/worker prerequisites first; never put private state under the frontend.

```bash
uv venv --python backend/.venvs/py3.15/bin/python backend/.venvs/web
uv pip install --python backend/.venvs/web/bin/python -r backend/webapp/requirements.lock.txt
```

Supply `BIO_WEB_SECRET_KEY` from a protected environment/secret mechanism
(a private random value), `BIO_PGDATABASE`, `BIO_PGUSER`, `BIO_PGPASSWORD`,
`BIO_PGHOST`, `BIO_PGPORT`, and `BIO_DATA_DIR`. All application and service
processes must use the **same** private `BIO_DATA_DIR`/service `data_dir`.
For local HTTP only, set `BIO_WEB_DEBUG=1`; production defaults use secure session
and CSRF cookies. Configure `BIO_WEB_HOSTS` and `BIO_WEB_ORIGINS` for the actual
origin. No deployment topology, TLS or reverse-proxy policy is implied.

```bash
backend/.venvs/web/bin/python backend/webapp/manage.py migrate
backend/.venvs/web/bin/python backend/webapp/manage.py createsuperuser
backend/.venvs/web/bin/python backend/webapp/manage.py runserver 127.0.0.1:8000
```

Run the [service worker/maintenance](../services/README.md) separately and the
[frontend](../../frontend/README.md) on port 5173. Development Vite proxies `/api`
to Django on loopback; a deployed build needs an equivalent same-origin route.
Do not deploy Django's development server. A launch-grade server configuration
and production provider/image/deployment work remain open.

## Accounts and scope

Native Django password hashing and session authentication are the reversible
initial implementation. Session reads and login issue CSRF tokens; login,
logout and authenticated mutations enforce CSRF. Login failure limits are
PostgreSQL-backed: 10 attempts per source/account in 15 minutes, an **interim**
operator policy. Public account registration, recovery and verification-email
delivery are still part of the wider backend backlog. The landing page accurately
directs users to their Organizer for account access.

Create ordinary Django accounts through trusted operator administration (for
example the Django shell with `create_user` and an interactively supplied
password). Public APIs cannot set roles, roster links or assignments. Then:

```bash
backend/.venvs/web/bin/python backend/webapp/manage.py provision_access username --roster-user-id EXISTING_VERIFIED_ROSTER_ID --reason 'Official roster account link'
backend/.venvs/web/bin/python backend/webapp/manage.py provision_access staff-user --organizer-tournament TOURNAMENT_ID --reason 'Tournament assignment'
backend/.venvs/web/bin/python backend/webapp/manage.py provision_access staff-user --organizer-tournament TOURNAMENT_ID --revoke --reason 'Assignment ended'
```

A participant's account email must match the verified official roster identity.
Every request derives participant teams/captaincy from the current registration
store, or Organizer scope from active PostgreSQL assignments. No creator bypass
is used by this API. Django superusers have Admin scope; ordinary `is_staff`
does not grant tournament access. Separate staff/participant accounts are the
interim provisioning rule while broader role composition remains unresolved.
The command locks the account and records an audit event with the scope change.
These are operator tools, not the full proposed CN-026 user/role API.

## Implemented routes

Canonical paths use a trailing slash, except the CSV export.

| Method | `/api/v1` path | Behavior |
|---|---|---|
| GET/HEAD | `/health/` | Public process liveness only; no database, account, legacy-store or engine access |
| GET | `/auth/session/` | Current user or null and masked CSRF token; private/no-store |
| POST | `/auth/login/`, `/auth/logout/` | CSRF-protected session lifecycle |
| GET | `/notifications/` | Linked recipient's bounded feed, unread/tournament filters and counts |
| PATCH | `/notifications/{id}/` | Recipient-only read/unread setter; same-team notices remain private |
| GET/PATCH | `/me/notification-preferences/` | Shared worker email preference; dashboard always enabled |
| GET | `/tournaments/` | Only current accessible tournaments and own teams |
| GET | `/dependencies/` | Public curated dependency names, versions and hashes |
| GET | `/tournaments/{id}/live/` | Authoritative match metadata and allowlisted numeric latest boards; authorization on every poll; archived returns 410 |
| GET | `/matches/{match_id}/replay/` | Current-scope `.bc26` attachment from the private replay vault; hidden/missing 404, archived 410, unavailable 503 |
| GET | `/tournaments/{id}/analytics/` | Team win rates/byes, series decisions, failures, maps, version results, round progress and median/p95 attempt time |
| GET | `/tournaments/{id}/analytics.csv` | Authorized team CSV with formula escaping |
| GET/POST | `/tournaments/{id}/teams/{team}/submissions/` | Authorized history; captain-only upload using the stored official deadline; queues validation |
| GET | `/tournaments/{id}/submissions/{version}/download/` | Authorized source/bundle; staff reads audited; private/no-store |
| GET/POST | `/tournaments/{id}/disputes/` | Team-private dispute list/create tied to a real match |
| GET/POST | `/tournaments/{id}/disputes/{uuid}/` | Team/staff comments and review transitions with optimistic revision |
| GET | `/admin/operations/` | Admin-only counts, safe incident metadata, dead jobs and recent feature audit events |

Analytics never changes results. Engine coin-flip picks count as tied games;
series coin flips count separately. Byes do not inflate played games or wins.
Missing runtime samples remain absent rather than invented zeroes. Attempt p95
uses the nearest rank; median uses the ordinary sample median. Version IDs are
match metadata; source bytes, host paths, provider errors and claim tokens are
not part of analytics, live boards or the operations reader.

## Recipient notifications (BIO-607 / CN-030)

These routes require the explicit operator-created participant roster link.
Legacy inbox recipients are roster IDs; Django numeric account IDs are never
used as a fallback. Unlinked accounts and staff return `403`; staff recipient
provisioning remains open. A staff role never grants another person's inbox.
The link is read again each request. Personal historical notices do not require
current tournament access.

The feed accepts only `limit` (1–200, default 50), `offset` (0–2147483647,
default 0), `unread_only` (`true`/`false`) and `tournament_id`. It returns
`items`, `total` and `unread`, newest first with ID as the timestamp tie-break.
Counts precede paging; `unread` precedes the unread-only filter. Invalid,
unknown or repeated query parameters return `400`. This interim offset adapter
follows the library; concurrent inserts may shift pages and global pagination
is still undecided.

PATCH takes exactly `{"read":true|false}` or `{"email_enabled":true|false}`
on the respective route, with actual JSON booleans and session CSRF. Read-state
retries preserve the timestamp; preference retries add no duplicate audit.
Missing/foreign notification IDs receive the same `404`. Preferences and reads
use the same private `notifications.json` as service workers. Turning email off
keeps dashboard notices and skips queued email when delivery runs. GET
preferences returns `email_enabled` and always-true `dashboard_enabled`.
Delivery errors/provider fields are never returned. Announcements, real
providers, automatic deadline/override notices and notification UI are separate
follow-ups; the PostgreSQL migration of notification state remains open.

## Dispute workflow

Registered members may open a dispute only for a match involving their team;
their team and assigned staff can read it. Staff review states are:

```text
open -> reviewing -> awaiting_participant -> reviewing
                   -> resolved / rejected
open -> rejected
awaiting_participant -> resolved / rejected
```

A reason is required for each staff transition. Team comments and staff review
events increment `version`; send `expected_version` and an `Idempotency-Key`.
Creation also requires an idempotency key. Reused keys with different content
conflict; current scope is checked before a stored response. Mutations, event,
audit and receipt share one PostgreSQL transaction. PostgreSQL triggers refuse
updates/deletes to audit and dispute-event rows.

Closing a review **does not change results, redraw randomness, resume matches
or rerun games**. Outcome corrections, appeals, reopening rules, automatic
notifications and a broader Admin mutation console need separate policies/work.
Existing source-upload mutations retain the registry's own durable audit and
idempotency; cross-store SQL/JSON transactions are not claimed.

## HTTP errors and request IDs (BIO-404 / CN-029)

Every `/api/v1` response has a fresh server-generated `X-Request-ID` and
`Cache-Control: private, no-store`. Incoming request IDs are ignored. Every
application/framework error uses the API contract's JSON envelope:

```json
{"error":{"code":"STATE_CONFLICT","message":"The dispute changed. Reload before editing.","details":{},"request_id":"req_0123456789abcdef0123456789abcdef"}}
```

The body ID matches the response header, including on idempotent conflict
replays; request IDs are not saved in mutation receipts. Codes are stable
uppercase values from [API_CONTRACT](../../docs/API_CONTRACT.md). Field validation
keeps structured `details`; single validation messages remain actionable.
Login requires JSON and unsupported media types return `415`.

The outer response middleware covers DRF exceptions, directly returned errors,
Django CSRF failures, method refusals and unknown routes. It retains status codes,
cookies and headers such as `Allow` and `Retry-After`. Missing/hidden resources
share generic `404` text. Unexpected failures remain `500`, use fixed wording
with empty details even in debug mode, and still reach Django exception logs.
The API completion logger records only the request ID and status; existing
Django exception-log access/retention still requires operational controls.

This follows Django's [exception-to-response middleware behavior](https://docs.djangoproject.com/en/dev/topics/http/middleware/#exception-handling)
and addresses the [DRF handler's exception-only scope](https://www.django-rest-framework.org/api-guide/exceptions/#custom-exception-handling).
The health endpoint only proves this web process can respond; it is **not**
database/worker/engine readiness or production monitoring. Pagination, global
idempotency/concurrency and remaining core routes are still BIO-404 work.

## Verification

```bash
backend/.venvs/web/bin/python backend/webapp/manage.py check
backend/.venvs/web/bin/python backend/webapp/manage.py test backend.webapp.tests backend.webapp.tests_http backend.webapp.tests_notifications backend.webapp.tests_replays
backend/.venvs/py3.15/bin/python backend/run_tests.py
backend/.venvs/py3.15/bin/python backend/run_tests.py --integration
```

Web tests require a disposable PostgreSQL database/role with permission to create
the test database; no SQLite fallback hides database trigger behavior. Test
fixtures remain in temporary directories. Browser tests use explicitly labeled
local fixture data; no real accounts or competitions are exercised.
Use explicit test-module labels: directory discovery of `backend.webapp` loses
the package context because `backend` is a namespace directory. The
`backend.webapp.tests_http` boundary suite also runs independently without a
database; the feature suite checks real session/CSRF, receipt and privacy behavior
against PostgreSQL. `backend/run_tests.py` covers the separate execution-library
suites and does not discover these web modules.

`tests_notifications` adds real-account/session/CSRF, recipient and numeric-ID
collision privacy, filters/paging, idempotent read/preference, rollback and
shared-worker outbox tests. Injected provider failures are local test doubles,
not evidence of a real provider-outage drill.

`tests_replays` checks streamed bytes, current session scope, archive refusal,
damage incidents and on-disk vault purge without removing results. Use game
`match_id` from the scoped live match list for downloads. `.bc26` is a native
engine attachment. Hosting, browser playback and the match-log route are
separate work.

Pinned web versions are Django 6.1.3, DRF 3.18.3 and psycopg 3.3.9; the separate
web environment preserves the bot environment pins. Django documents Python 3.15
support from 6.1.3 in its [6.1 release notes](https://docs.djangoproject.com/en/6.1/releases/6.1/).
The [DRF requirements](https://www.django-rest-framework.org/) informed the chosen
supported runtime; installed versions and actual tests remain the evidence here.
