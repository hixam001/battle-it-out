# Battle It Out frontend (CN-028)

React/TypeScript with Vite; the application stack was selected by the owner on
2026-11-26. The public landing page explains the real competition and clearly
labels its illustrative arena. The authenticated console supplies private live
boards, analytics/CSV export, Python and bundle uploads, disputes and an Admin
operations reader. It uses the real [Django API](../backend/webapp/README.md),
not localStorage authentication or fabricated results.

```bash
npm ci --prefix frontend
npm run dev --prefix frontend
npm run build --prefix frontend
```

Start Django on `127.0.0.1:8000` and Vite on `127.0.0.1:5173`; Vite proxies `/api`
on the same origin. All service/data directories must be outside `frontend/`.
Production static assets are generated into ignored `frontend/dist/`. Hosting,
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

Browser fixtures must target loopback and use disposable seeded accounts/data.
To run the shipped Playwright flows, provision the labeled fixture described
in the test source, start both servers, and install a local test browser:

```bash
cd frontend
npx playwright install chromium
npm test
```

`BIO_WEB_BASE_URL` overrides the loopback test URL. `BIO_BROWSER_PATH` can point
to an already installed compatible Chromium executable. Screenshots go to
ignored test-results. Desktop/mobile layout, keyboard navigation, real login,
analytics, dispute/comment, submissions catalogue, logout and Admin operations
are exercised. These fixtures are testing data, never production evidence.
