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

Start Django on `127.0.0.1:8000` and Vite on `127.0.0.1:5173`; Vite proxies `/api`
on the same origin. All service/data directories must be outside `frontend/`.
Production static assets are generated into ignored `frontend/dist/`. Serve
`index.html` for `/dashboard`, `/notifications`, `/participant/team` and
`/participant/submissions`, `/bracket`,
`/participant/tournaments/{id}/bracket`, `/matches/{id}` and
`/matches/{id}/replay`; retain the same-origin
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
reviews never automatically alter a result. Operations is a read-only Admin
reader, leaving existing incident/resume authority decisions open.

The dashboard shows the selected tournament's status, both deadlines in your
browser timezone, and its three latest personal notices. The linked-participant
inbox at `/notifications` keeps historical notices available and supports unread
filtering, paging, read/unread actions and email preferences. Turning email off
keeps dashboard notices active. Refresh returns to the first page of the current
filter and picks up new notices.

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

Direct console links preserve the destination through sign-in. Operations is
Admin-only, and the personal inbox uses participant scope. The API remains
authoritative for account and tournament access. The shared API client preserves
error codes, details and server request IDs. A visible request ID gives support
a reference when an API call fails. The first keyboard stop on the public page
and in the console jumps to main content when activated.

Browser fixtures must target loopback and use disposable seeded accounts/data.
Use the [Django local environment](../backend/webapp/README.md#install-and-run)
with `BIO_WEB_DEBUG=1`, a fresh PostgreSQL database named `bio_qa_*`, and a new
absolute `BIO_DATA_DIR`. Run the fixture commands from the repository root:

```bash
backend/.venvs/web/bin/python backend/webapp/manage.py migrate
backend/.venvs/web/bin/python -m frontend.tests.seed_fixture
```

Start both servers and run the browser suite:

```bash
cd frontend
npx playwright install chromium
npm test
```

`BIO_WEB_BASE_URL` overrides the loopback test URL. `BIO_BROWSER_PATH` can point
to an already installed compatible Chromium executable. Screenshots go to
ignored test-results. Desktop/mobile layout, keyboard navigation, real login,
analytics, dispute/comment, submissions catalogue, logout, Admin operations,
the dashboard and private inbox are exercised using local test data. Additional
checks cover direct role-restricted links, the keyboard skip link and a real
failed-login response with its matching request ID.
