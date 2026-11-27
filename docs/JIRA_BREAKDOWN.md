# Battle It Out --- Jira breakdown of BIO-EPIC-04 to BIO-EPIC-08

**Version:** 1.2 (proposed numbering; CN-028 activated feature scope)\
**Date:** 2026-11-26\
**Change notices:** CN-024, CN-026–030 in `CHANGE_NOTICES.md`\
**Audience:** the project owner and contributors who must order the remaining work and open the matching Jira issues.

PRD §10 and PROJECT_PLAN §6 define the tasks of BIO-EPIC-00 to BIO-EPIC-03 and leave the later epics "to be broken down". This file does that. It follows the ID scheme of PRD §10: a Jira key is `BIO-NNN` and the hundreds digit is the epic number. **These numbers are proposed.** If the tracker assigns other numbers, change them here and in the references (never give one number two meanings).

## How to read this

- **Covers** lists requirement IDs (`SRD-nnn`, `BIO-REQ-nn`, `BIO-NFR-nn`) of `REQUIREMENTS_COVERAGE.md`, and the test cases of `TEST_PLAN.md`. A requirement is closed only when its row in the coverage matrix says so.
- **State today** is taken from the repository on 2026-11-25, not from intentions:
  - **Library done**: the rules exist as a tested library with JSON-file stores (`backend/...`, named by its change notice). What remains is the layer around it. It is not accepted by the owner or reviewed independently.
  - **Not started**: no code exists.
  - **Owner first**: an open decision (`DEC-nn`) must be answered before the task can be finished. Nothing is invented here; the default in force is named where one exists.
- **Needs** names the tasks (and decisions) that must come first. A task with no entry can start as soon as the epic starts.
- Every task needs: tests that were run (unit, plus the integration or security tests named in `TEST_PLAN.md`), the coverage rows updated in the same pull request, and no claim without evidence (PRD §12).
- What each existing library still lacks is listed in `REQUIREMENTS_COVERAGE.md` and the backlog in `handoff.md`; this file only orders it.

## Work that belongs to earlier epics and is still open

These keep their original keys. They are listed because later epics wait for them; no new key is created.

| Key | Open part | State today | Needs |
|---|---|---|---|
| BIO-204 | Benchmark the limits on target hardware and publish the fixed numbers | Interim profile only | Owner first: DEC-04 |
| BIO-203 | Independent review of the sandbox (SR-06) | Self-review only | A reviewer outside the project |
| BIO-303 | House bots and their bracket algorithm; the qualification cutoff draw (SRD-027) | Refused on purpose; no draw | Owner first: DEC-06, DEC-14 |
| BIO-306 | New random seed on a retry (TC-04); a real Admin alert channel | Seed is not controllable in the engine; alert is a function | Engine change or an accepted waiver; BIO-409 for the channel |
| BIO-305 | Replay endpoint, object storage, player | Vault (CN-012) and private download (BIO-605 / CN-032); object storage and player open | BIO-408, DEC-10 |
| BIO-102 | Python 3.13 and 3.15 never run on the development machine | **Done by hand 2026-11-25 (CN-025):** the whole suite passes on 3.12 to 3.15, unit and real games, through `backend/run_tests.py --matrix`; what is left is running it automatically | BIO-804 (CI matrix), DEC-03 |

---

## BIO-EPIC-04 --- Backend foundation (P1)

**Exit gate (PRD):** API permission and persistence tests pass (TC-07, part). CN-028 resolves the application stack part of DEC-11; production providers/deployment and the complete core backend exit gate remain open.

| Key | Task | Covers | State today | Needs |
|---|---|---|---|---|
| BIO-401 | Decide and record the stack: language/framework, database, email provider and domain, object storage, hosting, session model, pagination style. Approve the proposed stack in the technical documentation | DEC-11; API_CONTRACT §1, §9 | **Partially decided (CN-028):** Django/DRF + PostgreSQL and React/TypeScript approved; hosting/email/object storage and remaining production choices open | Owner |
| BIO-402 | Database schema and migrations from `DATA_MODEL.md` (entities, states, constraints, matrices); constraints that the libraries enforce in code become database constraints | BIO-NFR-04, BIO-NFR-06; TC-07 | Feature auth/identity/assignment/dispute/audit/receipt/limiter schema migrated (CN-028); full legacy-library schema still open | BIO-401 |
| BIO-403 | Replace the JSON-file stores of the libraries behind their existing interfaces (submission registry, work queue, tournaments, registration, notifications, orchestrator and bracket, replay vault index). Keep every library test passing on the new store; add a crash and concurrency test per store | SRD-012, SRD-053; BIO-NFR-04 | Library done, JSON stand-ins | BIO-402 |
| BIO-404 | API skeleton: `/api/v1`, error envelope with `request_id`, status mapping (`400` to `503`), idempotency keys, pagination, optimistic concurrency (`expected_version`), health | API_CONTRACT §1 | Feature REST routes/scoped idempotency (CN-028); common errors, request IDs and liveness (CN-029); PostgreSQL readiness and recovery (CN-051). Pagination, global idempotency/concurrency, remaining core routes and production readiness remain open | BIO-401 |
| BIO-405 | Accounts and sessions: create an account from a verified registration claim, password hashing, email verification, login, logout, `GET /me`, rate limiting on login and code claims, CSRF as the chosen model requires | SRD-039, SRD-040; BIO-REQ-11; API_CONTRACT §2 | Native Django login/logout/sessions, CSRF, durable failure limits and provisioned accounts implemented (CN-028); public registration/verification/recovery remain open | BIO-401, BIO-404 |
| BIO-406 | Roles and tournament scope: user and role records, **Organizer assignment records**, policy functions, one place that builds the `Actor` each library takes, server-side check on every operation, safe `404` for hidden resources. Close the contract gap: add the user, role and Organizer-assignment endpoints to `API_CONTRACT.md` (open question: may one user hold several roles) | BIO-REQ-11, BIO-NFR-05, SRD-063; TC-07 | CN-026 contract proposal remains; feature-scoped identity/explicit assignment/current Actor adapter and operator provisioning implemented (CN-028), not the complete global role API/policy | BIO-404, BIO-405; owner reviews CN-026 and role policy before implementation |
| BIO-407 | Append-only audit log: permanent, written in the same transaction or a durable outbox, read by role and tournament scope, kept after a tournament is deleted. Feed it from the audit entries, series history and incidents the libraries already keep | SRD-062, SRD-063, BIO-NFR-06; TC-07 | PostgreSQL feature audit is append-only (CN-028). Scoped audit includes series history and the three incident stores used by Admin operations (CN-042/048/050). Permanent legacy migration and full purge/recovery remain | BIO-402 |
| BIO-408 | Private file storage: submissions and replays outside the web root, streamed after authorization, short-lived private URLs, no long-lived public link; the 256 KiB upload cap (interim) confirmed | BIO-NFR-08, SRD-056, SRD-058, BIO-REQ-08 | Authorized feature source/bundle delivery implemented (CN-028); full private object storage/retention and production caps remain open | BIO-401 |
| BIO-409 | Run the services: the queue worker (`--notify`), the deadline timer (`scheduler.tick`), `deliver_emails` and `housekeeping` as supervised processes with configuration; a real Admin alert channel for dead jobs, given-up emails and retry caps; a worker image with pinned runtime | SRD-002, SRD-006, SRD-007, BIO-NFR-03; PROJECT_PLAN D5 | **Interim JSON-store slice built (CN-027):** configured worker/maintenance/email/alert processes, reviewable systemd template and real-engine subprocess lifecycle. No production deployment, provider/channel or pinned image | BIO-403 for production; interim wiring is stack-neutral |
| BIO-410 | Permission and persistence test suite for the exit gate: role by scope matrix, cross-tournament IDOR, restart and recovery of every store, duplicate delivery of a job | TC-07; security tests of TEST_PLAN §4 | Feature PostgreSQL HTTP/permission/CSRF/rollback tests implemented (CN-028); full epic exit suite remains open | BIO-406, BIO-407 |

## BIO-EPIC-05 --- Registration and submissions (P1)

**Exit gate (PRD):** the participant flow passes with privacy and deadline rules (TC-06, TC-02 over the API).

| Key | Task | Covers | State today | Needs |
|---|---|---|---|---|
| BIO-501 | Roster endpoints: import, correct an unregistered entry, staff report with exclusions | SRD-038, BIO-REQ-13; API_CONTRACT §4 | **Implemented (CN-044):** current scoped staff, audited idempotent CSV/JSON import, optimistic correction and private report [PR #52](https://github.com/hixam001/battle-it-out/pull/52) | CN-020 format and size limits remain the interim defaults |
| BIO-502 | Invitation codes over the API: issue (Admin or assigned Organizer), revoke and replace (Admin only), list; **delivery of a code to its participant**; claim and confirm endpoints that use the failed-attempt limiter with the real source address | SRD-039, SRD-040, SRD-041, SRD-043; TC-06 | Staff list, issue, revoke and replace HTTP implemented (CN-049). Public claim, confirmation and delivery remain open | BIO-405, BIO-406, BIO-607 for the email |
| BIO-503 | Team endpoints: team view (no emails), roster display, captain and members; team size and name-edit policy applied | SRD-042; DEC-12; API_CONTRACT §4 | **Implemented (CN-045):** current scoped, contact-free team profile from the verified roster. Existing size, captain and claim-lock rules apply [PR #53](https://github.com/hixam001/battle-it-out/pull/53) | Final DEC-12 policy and account deletion are tracked separately |
| BIO-504 | Upload endpoint: multipart with one `bot.py` or flat Python ZIP, size cap (`413`), media type (`415`), actionable static failures (`422`), stored deadline, check queued by `tournament_flow.upload` | SRD-004, SRD-050, SRD-054, BIO-REQ-14; TC-02 | **Implemented (CN-040):** current scoped captain, validated multipart shape, explicit error mapping, persisted static findings, idempotent upload and queue. Final cap approval and production acceptance remain [PR #48](https://github.com/hixam001/battle-it-out/pull/48) | BIO-404, BIO-406, BIO-408 |
| BIO-505 | Submission read endpoints: history, validation result, download (team and assigned Organizer, staff reads audited), manual activation only if the owner wants it (default: latest valid is active) | SRD-051 to SRD-053, SRD-056, SRD-057; API_CONTRACT §5 | Complete (CN-036): scoped history with match IDs, validation details and source/bundle downloads; staff reads audited. Latest valid activation applies automatically [PR #44](https://github.com/hixam001/battle-it-out/pull/44) | Verified against the existing BIO-504 upload path (CN-028) |
| BIO-506 | Privacy tests over HTTP: another team's source, another tournament, guessed ids, path traversal and odd filenames, ZIP rejection, Organizer cannot change or activate | SRD-058, BIO-NFR-08; TC-07 | HTTP team/foreign-scope/staff-write privacy and bundle path tests implemented (CN-028); full production/security matrix still open | BIO-504, BIO-505 |
| BIO-507 | Registration and deadline transitions end to end (TC-06): unknown email, bad and expired code, retry after a failure, verification, extension keeps unused codes, close, exclusion at the deadline, with notices | SRD-041, SRD-044, SRD-054; TC-06 | Library tests (CN-020, CN-021) | BIO-502, BIO-504 |
| BIO-508 | Account recovery and resend of the verification email, at the smallest scope the owner approves | DEC-13 | Owner first | Owner |

## BIO-EPIC-06 --- Tournament operations (P1)

**Exit gate (PRD):** Admin and Organizer lifecycle tests pass (TC-07, TC-08).

| Key | Task | Covers | State today | Needs |
|---|---|---|---|---|
| BIO-601 | Tournament endpoints: create, list and get by role, edit with `expected_version`, submit for approval, approve, reject with a reason, resubmit | SRD-030 to SRD-033, BIO-REQ-12, BIO-REQ-15; API_CONTRACT §3 | **Implemented (CN-047):** scoped HTTP lifecycle with explicit creator assignment, version checks and manual registration opening | Approval notices are BIO-607 and staff screens are BIO-707 |
| BIO-602 | Deadline endpoints: extend (reopens uploads, count of affected participants in the answer) and emergency override; call `notify_notice` after each | SRD-034 to SRD-037; DEC-08 | **Implemented (CN-041):** confirmed Admin actions, durable audit and publication, affected account count, maintenance retries. Admin screens and provider deployment are tracked separately [PR #49](https://github.com/hixam001/battle-it-out/pull/49) | BIO-601, BIO-607 |
| BIO-603 | Bracket and round endpoints: generate (the timer does it at the deadline), start a round (Organizer, one at a time), bracket and match views, map pool chosen and stored per tournament, tie-break and coin-flip data for display | SRD-020 to SRD-028, BIO-REQ-07; API_CONTRACT §6 | Complete (CN-034/038): scoped reads and staff map selection, confirmed draw and sequential round start. UI and house-bot/qualification policies remain separately tracked [PR #46](https://github.com/hixam001/battle-it-out/pull/46) | Existing explicit staff scope and worker queue |
| BIO-604 | Admin operations on trouble: list and resume a paused match (who may resume is open), revive a dead job, read incidents; an Admin console of what is stuck | SRD-011, BIO-REQ-09, BIO-REQ-15 | Safe read-only operations API/UI implemented (CN-028); paused-match resume/dead-job mutation controls and policy remain open | BIO-409, BIO-406 |
| BIO-605 | Replay and log endpoints: authorized replay before archive, `404`/`410` rules, and role-scoped logs | BIO-REQ-08, SRD-063; API_CONTRACT §6 | **Implemented (CN-032/046):** verified private replay downloads and scoped structured attempt logs [PR #54](https://github.com/hixam001/battle-it-out/pull/54) | Browser playback remains BIO-705/DEC-10; production retention and storage are follow-up work |
| BIO-606 | Archive and retention jobs: archive endpoint (Admin or assigned Organizer by rule), scheduled `purge_pending`, vault backups | SRD-070; TC-08 | Scoped, confirmed archive HTTP and shared purge recovery (CN-035); production scheduling, worker-output retention and vault backup/recovery remain | BIO-409, BIO-803 |
| BIO-607 | Notification endpoints and delivery: feed, read, preferences; announcements written by an Organizer; a real email provider adapter; mandatory security emails (owner decides which); the TC-08 provider-outage drill | SRD-060, SRD-061, BIO-REQ-16, BIO-NFR-07; TC-08; API_CONTRACT §7 | Recipient API and inbox, deadline notices and scoped announcement publishing (CN-030/031/041/052). Staff recipients, approval and dispute notices, announcement screen, provider/deployment/outage drill and SQL migration remain | BIO-401, BIO-409; owner: CN-022 D2/D3/D5 |
| BIO-608 | Account deletion lifecycle: request queued while the team competes, cancel, execute when inactive, remove from rosters with results unchanged, captain transfer (DEC-07 for no successor) | SRD-065 to SRD-067, BIO-REQ-18; TC-07; FLOW-07 | Not started | BIO-406; owner: DEC-07 |
| BIO-609 | Team deletion after archive and Admin-only restore; permanent tournament deletion (Admin only, audit kept) **including the data other libraries hold** (`purge_tournament` of registration, notifications, registry, flow, bracket) | SRD-068, SRD-069, BIO-REQ-18; TC-07; FLOW-08 | Library done for tournaments and replays; the rest not started | BIO-407, BIO-608 |
| BIO-610 | Audit log read endpoint for a tournament and for the Admin | SRD-062, SRD-063; API_CONTRACT §7 | **Implemented (CN-042):** current-role scoped and global read APIs over the existing web and library audit records, with pagination and retained deleted-tournament audit for Admin [PR #50](https://github.com/hixam001/battle-it-out/pull/50) | BIO-407 owns permanent storage and remaining history sources |
| BIO-611 | Lifecycle test suite for the exit gate: approval flow, extension notices with email off, archive removes replays and keeps results, destructive actions need reason and confirmation | TC-07, TC-08 | Library tests | BIO-601 to BIO-610 |

## BIO-EPIC-07 --- Website and participant UI (P1)

**Exit gate (PRD):** usability and end-to-end acceptance complete. CN-028 activates local feature/landing work while the execution gate remains open; the tasks below are ordered so that each screen needs only endpoints of the earlier epics. Design work follows `PRODUCT.md` and the `impeccable` skill (a `DESIGN.md` is recorded from the first finished screens).

| Key | Task | Covers | State today | Needs |
|---|---|---|---|---|
| BIO-701 | Frontend foundation: stack (BIO-401), design tokens and `DESIGN.md`, routing and guards by role, API client with the error envelope and `request_id`, accessible components, mobile and keyboard baseline | BIO-NFR-12; APP_FLOW §7 | Complete (CN-028/031/037): React/TypeScript/Vite foundation, shared API client, direct route guards and desktop/mobile keyboard tests. Product-wide acceptance remains BIO-708 [PR #45](https://github.com/hixam001/battle-it-out/pull/45) | Approved stack and BIO-404 error envelope |
| BIO-702 | Account screens: `/login`, `/register` (email, code, password, verification), `/account/settings` (email toggle, deletion request and cancel) | SRD-039, SRD-060, SRD-065; FLOW-03, FLOW-07 | Real session login/logout UI implemented (CN-028); registration/settings/verification/deletion screens remain open | BIO-405, BIO-502, BIO-608 |
| BIO-703 | `/dashboard`, `/notifications`, tournament overview with deadlines and notices | SRD-060, BIO-REQ-17, BIO-NFR-12 | Delivered locally (CN-031): dashboard status/deadlines/notices, recipient inbox, read/unread paging and email preference. Staff notices and deployment are tracked separately | BIO-607 recipient API (CN-030) |
| BIO-704 | `/participant/team` and `/participant/submissions`: upload, validating, valid, invalid with reasons, locked after the deadline, history | SRD-050 to SRD-054, BIO-NFR-12; FLOW-04 | Python/bundle upload, validation/active history and authorized downloads implemented (CN-028); complete team screen and richer rejection display remain open | BIO-503, BIO-504, BIO-505 |
| BIO-705 | Bracket, results and match detail: pending, running, retrying, completed; tie-break maps and the coin flip shown and explained; replay page and player | SRD-026, SRD-028, BIO-REQ-17; FLOW-06 | Private match metadata/live board and analytics implemented (CN-028); full bracket/replay and coin-flip presentation remain open | BIO-603, BIO-605 |
| BIO-706 | Organizer screens: new tournament, manage and resubmit, roster import and correction, rounds, teams and source download | BIO-REQ-15; FLOW-02, FLOW-03, FLOW-05 | Not started | BIO-501, BIO-601, BIO-603 |
| BIO-707 | Admin screens: approvals, tournament management, deadlines and overrides, invitations, incidents and stuck jobs, global audit | BIO-REQ-15, SRD-062; FLOW-08 | Read-only Admin health/incident/dead-job/audit console implemented (CN-028); approvals and remaining Admin mutation screens remain open | BIO-502, BIO-602, BIO-604, BIO-610 |
| BIO-708 | Usability and end-to-end acceptance: scripted walk of FLOW-01 to FLOW-08 for each role, accessibility check, copy review (English wording of notices is unreviewed) | BIO-NFR-12; TEST_PLAN §5 | Feature desktop/mobile keyboard/login/analytics/dispute/submission/Admin browser flows pass (CN-028); complete FLOW-01–08 and formal accessibility acceptance remain | BIO-702 to BIO-707 |
| BIO-709 | Public landing page | BIO-REQ-19 | **Active, local implementation (CN-028):** React page with responsive/keyboard checks; public deployment/branding acceptance remain open | Owner activated; hosting remains open |

## BIO-EPIC-08 --- QA, pilot and production (P0 launch gate)

**Exit gate (PRD):** the go-live checklist is signed off; no open Blocker or Critical defect (TEST_PLAN §7).

| Key | Task | Covers | State today | Needs |
|---|---|---|---|---|
| BIO-801 | Security test pass: IDOR, authorization matrix, upload abuse, rate limiting, SQL injection, XSS, CSRF, audit tampering, bot escape and exhaustion; **an independent review** of the sandbox and the web layer; every Blocker and Critical closed | BIO-NFR-01, BIO-NFR-05, BIO-NFR-06; TEST_PLAN §4 | Sandbox self-review only (CN-008) | BIO-410, BIO-708; a reviewer |
| BIO-802 | Reliability and load tests: repeated matches on one worker, a worker crash during a match, queue redelivery and duplicate completion, several tournaments, database, object-storage and email-provider outages; capacity numbers and more than one host (engine port is fixed today) | BIO-NFR-11, BIO-NFR-02; TEST_PLAN §4 | One match per host | BIO-409, BIO-403 |
| BIO-803 | Backups and a tested recovery: database, submissions, replay vault; restore in staging without breaking match references; replay purge recovery | BIO-NFR-09; TC-08; DEC-13 | Not started | BIO-403, BIO-408 |
| BIO-804 | Deployment: environments (development, staging, production), worker image with pinned runtime and engine, secrets, TLS and email domain, CI that runs the Python 3.12 to 3.15 matrix and the real-engine tests, supported OS matrix | BIO-NFR-03, SRD-002, SRD-003; DEC-03 | Linux x86_64 only; no CI | BIO-401, BIO-409 |
| BIO-805 | Runbooks: incident handling (paused match, dead job, given-up email), deadline extension, restore, replay purge, key rotation; update `ADMIN_GUIDE.md` and `USER_GUIDE.md` to the real screens | TEST_PLAN §5; ADMIN_GUIDE | Interim runbook and console guides (CN-033); local recovery and signing-key rehearsal. Target-host adoption, provider drills and runbook sign-off remain | BIO-707, BIO-803 for production |
| BIO-806 | Licensing and terms before anything is published or served: written word from the Battlecode team on the unlicensed Java engine, the copyright holder, participant terms, the AGPL section 13 source offer | PROJECT_PLAN R5; `LICENSING.md` | Open items listed | Owner |
| BIO-807 | Pilot tournament: plan (size, dates, rollback), run with real participants or volunteers, review; at least 99% of valid matches without platform failure (sample size is open) | PRD §3; TC-05; BIO-G03 | Not started | BIO-801 to BIO-805 |
| BIO-808 | Go-live checklist and sign-off: all P0 acceptance tests, security and recovery tests, pilot reviewed, runbooks tested | TEST_PLAN §5, §7 | Not started | all of the above |

---

## Order that the dependencies allow

1. **Owner answers that unlock work:** DEC-11 (BIO-401), then DEC-06, DEC-14, DEC-04, DEC-07, DEC-10, DEC-12, DEC-13 in the order the tasks above need them. Confirming the change-notice defaults listed in `handoff.md` removes the rest of the open questions.
2. **Stack-neutral work that does not wait:** review the drafted BIO-406 access-control contract (CN-026), review/deploy the interim BIO-409 service wiring (CN-027) with approved provider/channel adapters, and the written parts of BIO-805 and BIO-806. The BIO-406 documentation slice is drafted; the implementation still needs its dependencies and owner decisions.
3. **Critical path:** BIO-401 → BIO-402/404 → BIO-403/405/406/407/408 → BIO-409 → BIO-410 (epic 04 exit) → epic 05 and 06 endpoints in parallel → BIO-701 and the screens → BIO-801 to BIO-808.

## Activated feature tasks — CN-028

The owner activated BIO-REQ-19–23, selected the application stack and narrowed
initial language expansion to Python multi-file/curated dependencies. These keys
extend the proposed numbering without reusing any existing task. No tracker
issues were created. Existing execution/production gates remain open.

| Key | Active scope / implementation | Remaining work |
|---|---|---|
| BIO-509 | **Implemented (CN-028/043):** native flat Python bundle validation, immutable hashes, trial/activation/pins and reproducible authorized upload/download, including the 32-file boundary [PR #51](https://github.com/hixam001/battle-it-out/pull/51) | Final limits, deployment acceptance and later language compatibility are tracked separately |
| BIO-510 | **Implemented (CN-039):** reviewed digest per exact release, public catalogue, verified snapshot and reproducible export [PR #47](https://github.com/hixam001/battle-it-out/pull/47) | Future package selection and review are follow-up work under CN-028 |
| BIO-612 | Team-private match disputes, comments, staff review, versions/idempotency and PostgreSQL audit/history | Appeals/reopening/outcome correction policy and notifications |
| BIO-613 | Read-only Admin operations/incidents/dead-job/audit console | Additional mutation controls and resume authority policies |
| BIO-710 | Private native-engine numeric live boards, current-scope HTTP polling and React rendering | Production scale/reconnect evidence and full viewer overlays |
| BIO-711 | Team/version/map/round/failure/latency analytics with CSV and React views | Owner analytics acceptance and production data/load evidence |

BIO-401 is now **partially decided**: Django/DRF, PostgreSQL and React/TypeScript
are approved; hosting, email, object storage and remaining production choices
are still open. BIO-405/406 have a feature-scoped native-session/identity/assignment
adapter and operator provisioning, not their complete account/role endpoint
scope. BIO-402/403 remain open for the full existing-library database migration.

## Keeping this file true

- When a task is opened in Jira, write the real key next to the proposed one and keep both until the old references are changed.
- When a task closes, change **State today** with the pull request that closed it, and update the coverage matrix in the same pull request.
- A task that turns out larger than one pull request is split with a new number, never by reusing one.
