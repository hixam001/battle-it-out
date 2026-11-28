# Battle It Out frontend (CN-028)

React/TypeScript with Vite; the application stack was selected by the owner on
2026-11-26. The public landing page explains the real competition and clearly
labels its illustrative arena. The authenticated console supplies private live
boards, analytics/CSV export, Python and bundle uploads, disputes, a tournament
dashboard, a personal inbox and an Admin operations reader. It uses the real
[Django API](../backend/webapp/README.md),
not localStorage authentication or fabricated results.

```bash
npm ci --prefix frontend
npm run dev --prefix frontend
npm run build --prefix frontend
```

The **Frontend build** workflow uses Node.js 26.13.1 and runs these install
and build steps for frontend or workflow changes on pull requests to `main`
and pushes to `main`. See [the workflow](../.github/workflows/frontend.yml).

Start Django on `127.0.0.1:8000` and Vite on `127.0.0.1:5173`; Vite proxies `/api`
on the same origin. All service/data directories must be outside `frontend/`.
Production static assets are generated into ignored `frontend/dist/`. Serve
`index.html` for `/login`, `/dashboard`, `/notifications`, `/account/settings`, `/participant/team` and
`/participant/submissions`, `/bracket`,
`/participant/tournaments/{id}/bracket`, `/matches/{id}` and
`/matches/{id}/replay`, `/matches/{id}/logs`, `/admin`, `/admin/approvals`, `/admin/audit`,
`/admin/manage-tournaments`, `/admin/manage-tournaments/new`,
`/admin/manage-tournaments/{id}/settings`, `/admin/manage-tournaments/{id}/roster`,
`/admin/manage-tournaments/{id}/teams`, `/admin/manage-tournaments/{id}/audit`,
`/admin/tournaments`, `/admin/tournaments/{id}`, `/admin/invitations`, `/organizer`,
`/organizer/tournaments/new`, `/organizer/tournaments/{id}`,
`/organizer/tournaments/{id}/roster`, `/organizer/tournaments/{id}/rounds`,
`/organizer/tournaments/{id}/teams`, `/organizer/tournaments/{id}/audit` and
`/announcements/new`; retain the same-origin
`/api` route to Django. Hosting,
TLS, reverse proxy and public deployment remain operator/deployment work; no
external Site has been created or published. Native session cookies and masked
CSRF tokens protect the API; no credential is stored in browser localStorage.

The palette and typography are an initial design choice documented in
[DESIGN.md](../DESIGN.md), not approved branding. Google Fonts are progressive
styling with system fallbacks; no imagery, sponsor claims, participant counts,
real event dates or production results are invented.

Live boards show engine-derived robots, walls, dirt, cheese and team score
counters through numeric snapshots. The engine transport opens no WebSocket
listener. The view omits arbitrary indicator/label strings and bot messages;
it is a simplified board, not the full upstream desktop player's overlays.
Membership/assignment is rechecked at every poll. Archive removes access and
maintenance removes the retained live snapshots.

Analytics includes team/round/map summaries, version performance, coin flips,
forfeits, platform failures, observed median/p95 attempt duration and team CSV.
Dispute comments and status changes use optimistic revisions and idempotency;
reviews never automatically alter a result. **Operations** shows open
incident references, attempt and alert state, dead job IDs and failure counts,
and recent audit events. Admins can refresh the snapshot. The prior
`/#operations` address still opens the page.

The dashboard shows the selected tournament's status, both deadlines in your
browser timezone, and its three latest personal notices. The linked-participant
inbox at `/notifications` keeps historical notices available and supports unread
filtering, paging, read/unread actions and email preferences. Turning email off
keeps dashboard notices active. Linked participants can change the same email
preference from **Account settings**. Refresh returns to the first page of
the current inbox filter and picks up new notices.

My team shows the verified roster and the team's recorded bracket standing
for the selected tournament. Bot submissions shows the active version,
history, downloads and expandable check results. Only the current captain
gets an upload form while the selected tournament's deadline is open.
Refresh submissions picks up new verdicts and any deadline change. The former
`/#submissions` address still opens submission history.

Bracket & results shows recorded rounds, byes, game wins and progression.
Match detail shows the game order, pinned bot versions, tie-break maps and
the recorded coin flip when it decided a series. The replay page offers a
native download while retained and explains archive or unavailable states.
Playback uses the Battlecode client.
**Structured match log** shows the latest verified attempt and opens an
earlier numbered attempt on request. The API supplies event fields and team
output according to the current viewer's role.

Admins can review pending Organizer tournaments through **Approvals**.
The queue reuses the server's confirmation, required rejection reasons
and version checks. **Manage tournaments** lists all available tournaments,
creates and edits drafts, directly approves Admin-created drafts after
confirmation and opens registration as a separate action. It links each
tournament to its deadline controls, roster import and correction, and
the team directory with validation history and audited source downloads.
**Audit log** pages through role-filtered events and accepts an exact
tournament ID, including one whose tournament has been deleted.
**Deadline controls** shows the current deadlines and supports confirmed
extensions and locked-setting overrides with a reason. The receipt reports
affected accounts and the dashboard notice state.
**Invitation codes** lists code metadata and supports confirmed revocation
or replacement. A new code appears in the successful replacement receipt.
The Admin invitation page and Organizer roster page also support first
issuance for eligible entries, with a one-time receipt.

Organizers use **Manage tournaments** to create drafts, revise assigned
tournaments, send them for approval and open registration upon approval.
The form shows rejection reasons and applies existing deadline and version
checks. Refresh tournament loads a new decision or reloads stale settings.
**Manage roster** shows registration progress, imports CSV or JSON and
corrects unlocked entries with a version check.
**Manage rounds** selects a stored map pool, confirms the bracket draw and
queues each ready round separately.
**View teams** shows verified rosters, bracket standing, history, validation
findings and audited source downloads in assigned tournaments.
**Tournament audit log** shows the paginated role-scoped feed for the current
tournament. It is available from both Admin and Organizer settings.

Admins and assigned Organizers can confirm archive from a completed
tournament's management page. The archive panel reports replay removal or
a pending maintenance retry and links to the retained bracket.

**Post announcement** lets current tournament staff publish a headline and
message to the selected tournament's verified roster. The form reports
inbox and email-queue counts and retries unchanged text with the same key.

The landing page links to `/login`, which opens the dashboard after sign-in.
Direct console links preserve their destination through sign-in. Operations is
Admin-only, and the personal inbox uses participant scope. The API remains
authoritative for account and tournament access. The shared API client preserves
error codes, details and server request IDs. A visible request ID gives support
a reference when an API call fails. The first keyboard stop on the public page
and in the console jumps to main content when activated.
The console keeps the current section visible inside its navigation strip.
Keyboard activation of a console link moves focus to the main content.

Browser fixtures must target loopback and use disposable seeded accounts/data.
The **Web and browser tests** workflow provisions those services and runs
the Chromium suite for frontend and backend changes to `main`.
See [the workflow](../.github/workflows/web-tests.yml).
Use the [Django local environment](../backend/webapp/README.md#install-and-run)
with `BIO_WEB_DEBUG=1`, a fresh PostgreSQL database named `bio_qa_*`, and a new
absolute `BIO_DATA_DIR`. Run the fixture commands from the repository root:

```bash
backend/.venvs/web/bin/python backend/webapp/manage.py migrate
backend/.venvs/web/bin/python -m frontend.tests.seed_fixture
```

Start Django with `BIO_ENGINE_JAR="$BIO_DATA_DIR/fixture-engine.jar"` for
this disposable test environment, then start Vite and run the browser suite.
The seed script creates the synthetic catalogue for the draw test. Leave
the match worker stopped.

```bash
cd frontend
npx playwright install chromium
npm test
```

`BIO_WEB_BASE_URL` overrides the loopback test URL. `BIO_BROWSER_PATH` can point
to an installed compatible Chromium executable. CI uses the runner's version
and prints it in the test log. Screenshots go to
ignored test-results. Desktop/mobile layout, keyboard navigation, real login,
analytics, dispute/comment, submissions catalogue, logout, Admin operations,
the dashboard and private inbox are exercised using local test data. Additional
checks cover direct role-restricted links, the keyboard skip link and a real
failed-login response with its matching request ID.
