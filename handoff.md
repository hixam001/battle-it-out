# Battle It Out — Handoff

> Living document. Read this (and memory) at the start of every task. Append an entry to the **Task log** at the end of every task.
> Owner / sole contributor: Hisham Ahmed. Remote: `https://github.com/hixam001/battle-it-out.git`

## 1. Project in one paragraph

INNOFEST "Battle It Out" is a Battlecode-2026-style programming competition. Participants submit **one Python file, `bot.py`**, which plays automatically in the **existing Battlecode 2026 engine** (no replacement engine). The platform covers invitation-based registration, bot submissions, single-elimination brackets, tie-breaks, replays, notifications, audit, and retention. **Order of work: scaffold + Python 3.13 first → bot execution + match automation second → backend → website/landing page last.** Do not start the website/landing page until BIO-EPIC-01..03 pass their exit gate.

## 2. Workflow rules (from the owner — mandatory)

1. **Start of every task:** read this file, read memory, load this handoff into memory, *then* proceed.
2. **New task = new branch** named with Jira notation (e.g. `BIO-101-pin-dependencies`; keys follow the PRD §10 ID scheme in §3 below; for epic-level work use `BIO-EPIC-0N-…`), then commit, **push**, and **open a pull request**.
3. **No co-authors, ever.** No `Co-Authored-By` trailers, no "Generated with Claude Code" lines in commits, pushes, or PRs. Hisham Ahmed is the only contributor.
4. **End of every task:** append an entry to the Task log below and update memory.
5. Per PRD §12: for every change report Jira ID, files changed, tests run, results, risks, new decisions. Never claim compatibility/isolation/limits/reliability without a test that proves it. Don't invent values for `[DECIDE]` items — ask.

## 3. Repository state (as of 2026-11-05, after task BIO-EPIC-00 integration)

- Branch `BIO-EPIC-00-backend-scaffold-integration` (PR open against `main`; `main` = `27439bc Initial commit` until merged).
- Layout: `docs/` (six spec docs), `backend/` (home of the execution foundation and future web backend), `backend/battlecode26-scaffold/` (vendored Battlecode 2026 scaffold, **now tracked by this repo — no nested git**), `handoff.md`, `.github/modernize/java-upgrade/` (tool-use hook scripts; `.gitignore` = `**/*`), `README.md` (title only).
- `backend/README.md` records provenance: upstream `battlecode/battlecode26-scaffold` commit `f69e2ab872a0061c9d4a684aa1dd798a0829da85`; upstream history not kept (updates are manual merges). Backup of the original nested `.git` was only kept in the session scratchpad (temporary) — it is just upstream history; re-clone upstream if ever needed.
- Local modifications imported with the scaffold: `engine_version.txt` 1.2.4→1.2.6 (from `./gradlew update`), rewritten `src/examplefuncsplayer/RobotPlayer.java`. `client_version.txt` = 1.0.6 (upstream now offers client 1.0.7).
- Scaffold files: `build.gradle`, `gradle.properties` (defaults: java vs java, map `DefaultSmall`), Java player `src/examplefuncsplayer/RobotPlayer.java`, Python player `src/examplefuncsplayer_py/bot.py` (`from battlecode26 import *`, `turn()` with global `rc`), test `test/examplefuncsplayer/RobotPlayerTest.java`, `run.py`.
- `run.py` **hard-requires Python exactly 3.12** (`REQUIRED_PYTHON_VERSION = (3, 12)`) and pip-installs the engine from `.temp/`.
- Ignored/local only (not in git): `.venv` (uv CPython 3.12.15, `battlecode26` imports OK; its `activate` script still hardcodes an older path `/home/hixam/Downloads/Innofest/battlecode26-scaffold/.venv` — recreate the venv rather than relying on `activate`), `.gradle`, `build/`, `client/` (AppImage), `matches/`, `.temp/`.
- Editor note: the VS Code Java/NetBeans extension may recreate `docs/battlecode26-scaffold/.gradle/nb-cache` at the old path; delete it and reopen the project from `backend/battlecode26-scaffold`.

### Jira / requirement ID scheme (fixed in PRD v1.1, TEST_PLAN v1.1)
- Epics: `BIO-EPIC-00..08`.
- Jira issue keys: `BIO-NNN`, hundreds digit = epic (`BIO-001..005` EPIC-00, `BIO-1NN` EPIC-01 … `BIO-8NN` EPIC-08). Only EPIC-00..03 tasks are defined (PRD §10). EPIC-04..08 tasks get keys when broken down; docs refer to the epic ID until then.
- Requirement IDs (PRD §5 scope list): `BIO-REQ-01..23` (were the duplicate `BIO-101..110`, `201..208`, `301..305`). Not Jira keys. Traceability REQ→epic table in PRD §10 (proposed).
- Test plan Jira references now use defined task keys or epic IDs only (TC-02, 03, 06, 07, 08 changed).
- Real Jira assigns keys sequentially; if the tracker numbers differ from PRD §10, update the docs — never reuse a number.

## 4. Document digest (all in `docs/`; scaffold README is in `backend/battlecode26-scaffold/`)

### PRD.md — product requirements (v1.0, 2026-11-04)
- Goals: BIO-G01 reproducible scaffold on Python 3.13; G02 safe deterministic bot execution (bot failure ≠ platform failure); G03 automated match lifecycle (advance, tie-break maps, final coin flip); G04 controlled tournament/registration/submission mgmt; G05 visible, auditable outcomes/notifications.
- Personas: Participant (own team only), Organizer (assigned tournaments only; may view/download source, may NOT alter submissions/locked identity/codes), Admin (global; sole authority for code revoke/replace, restore team, permanent tournament delete, emergency override).
- Priorities: **P0** repo audit, Py3.13 scaffold, run single `bot.py`, validate, isolated execution w/ global limits, failure classification, sequential matches/bracket/tie-breaks/coin flip, replay lifecycle, retry policy, prove engine before website. **P1** auth/roles, tournament lifecycle, roster/codes, submissions, audit, notifications, dashboards, deletion lifecycle. **P2** landing page, live viewing, extra languages/multi-file, analytics, disputes.
- Rules: Organizer-created tournaments need Admin approval (reject needs reason; resubmit allowed); registration & submission deadlines independent; Admin may extend (even after expiry); post-deadline edits need extension or emergency override (reason + notify). Invitation = official roster email + single-use code; invalid attempts don't consume code; unused codes expire at close/extension; registration locks email/team/member#/role. Submissions: only `bot.py`, latest valid becomes active, invalid replacement keeps previous active, immutable versions, match stores exact version. Matches: sequential, Organizer starts each round, single-elimination, random pairing, automatic byes (humans before house bots), house bots can't advance/win; normal tie → 1 tie-break map, final tie → 3 maps sequentially, then 50/50 coin flip (no rerolls, logged, displayed); qualification-cutoff tie → automatic random draw. Bot crash/timeout/instruction-limit = auto loss, no rematch. Platform failure → restart same map + same bot versions, **new seed**, retry up to 10 then alert Admin. Replays kept until archive, then deleted for everyone; results/brackets/history remain. Notifications: dashboard mandatory, email optional. Audit logs immutable, permanent, scope-filtered. Deletion: account deletion queued while team competing (cancelable), participant removed entirely from historical rosters (no placeholder), captaincy transfers; team delete only after archive (Admin/Organizer; Admin restores); only Admin permanently deletes tournaments (audit survives).
- NFRs: isolation (P0), global fixed benchmarked limits (don't invent numbers), pinned reproducible runtime, exact-version match records, server-side authz everywhere, append-only audit, private submission files, backups/recovery, secret-free logs, load targets via testing.
- Proposed (NOT approved) stack: React+TS, Django+DRF, PostgreSQL, Celery+Redis, isolated container workers, S3-compatible private storage, polling first, containerized behind reverse proxy.
- Roadmap: EPIC-00 Discovery → 01 Scaffold modernization → 02 Bot runner/sandbox → 03 Match/tournament automation → 04 Backend → 05 Registration/submissions → 06 Tournament ops → 07 Website → 08 QA/pilot/launch. Phase 0–3 task breakdown is in PRD §10.
- Open decisions DEC-01..DEC-14 (PRD §11).

### SRD.md — software requirements
SRD-001..012 (engine/scaffold/sandbox/limits/failure), 020..028 (bracket/ties/results), 030..044 (lifecycle/registration), 050..058 (submissions/privacy), 060..070 (notifications/audit/deletion/retention). AC-SRD-01..12 acceptance checks. Deferred: landing page, other languages, ZIP/multi-file, user deps, anonymous results, live streaming, analytics, disputes, per-tournament limits, any replacement engine. Build notes: treat bot code as hostile; keep worker separate from API; explicit auditable state transitions; no cascading deletes of history; permissions server-side.

### API_CONTRACT.md — proposed REST `/api/v1`
Groups: auth/profile (`/auth/register|verify-email|login|logout`, `/me`, `/me/deletion-request`), tournaments (CRUD, `submit-for-approval`, `approve`, `reject`, `extend-deadline`, `emergency-override`, `archive`, `DELETE`), roster/invitations/teams (`roster/import`, `roster/{id}`, `invitation-codes` issue/revoke/replace, `teams/{id}` get/delete/restore), submissions (`POST/GET /teams/{id}/submissions`, `/submissions/{id}/download|validation`, optional manual `activate`), bracket/matches (`bracket/generate`, `rounds/{id}/start`, `bracket`, `/matches/{id}`, `/replay`, `/logs`), notifications/audit. Standard error envelope + codes; idempotency keys; destructive actions need `confirm` + `reason`; safe 404 for other teams' resources; short-lived private file URLs. Internal match-worker contract (queue boundary, not public): inputs (match, map version, engine version, runtime image digest, two submission versions, seed, limit profile, attempt, trace id) → outputs (`completed|bot_failure|platform_failure`, winner/tie, reason, resource usage, replay ref, logs); idempotent, duplicate delivery must not double-advance. Open: auth mechanism, pagination style, upload cap, roster file format, code granularity, uploader authority.

### DATA_MODEL.md — proposed logical model
Entities across identity (User, Role, UserRole, OrganizerAssignment, NotificationPreference), tournament (Tournament, Approval, Deadline, Setting, Map, Archive), roster/team (ImportedRosterEntry, RosterImportBatch, Team, TeamMember, InvitationCode(+Issue)), execution (BotSubmission, SubmissionValidation, ExecutionProfile, Match, MatchAttempt, MatchReplay, MatchLog, Round, Bracket, BracketSlot, HouseBot), ops (Notification(+Delivery), AuditLog, AccountDeletionRequest, TeamDeletionEvent, SystemIncident). State machines for tournament / submission / match / account deletion. Key constraints: immutable submissions, one active per team, new seed on retry, RESTRICT not CASCADE for history, partial unique index for active submission, retention matrix, access matrix. Open: multi-role users, code granularity, team size/captain, roster retention, upload cap, retry-cap post-state, house-bot representation, replay artifact shape, anonymization/legal, log storage.

### TEST_PLAN.md
Environment: clean Linux, approved Py 3.13 patch, pinned engine/client/packages, worker image matching prod. Fixtures: valid/invalid/crashing/timeout/limit-exceeding bots, simulated engine failure, fixture tournaments. **Eight critical cases:** TC-01 clean install + Py3.13 (BIO-101/102); TC-02 bot validation + activation; TC-03 two-bot match + resource enforcement; TC-04 bot vs platform failure + retry; TC-05 automation/tie-breaks/bracket; TC-06 registration/invites/deadlines; TC-07 permissions/privacy/audit/deletion; TC-08 replay/notifications/archive/recovery. Plus unit/integration/security/reliability categories, pre-demo checklists (scaffold / tournament / web), severity levels and release gate (no Blocker/Critical open, all P0 pass, pilot done). **Never mock the engine as the sole proof of Py3.13 compatibility; record exact versions in every report.**

### APP_FLOW.md
Entry points; FLOW-01 developer scaffold setup (error states: unsupported Python → stop with guidance, no silent unpinned downloads), FLOW-02 tournament creation/approval, FLOW-03 roster + invitation registration, FLOW-04 submission, FLOW-05 organizer runs a round, FLOW-06 results/replay, FLOW-07 account deletion, FLOW-08 archive/delete. Error/edge matrix, navigation map, route inventory (`/login`, `/register`, `/dashboard`, `/participant/*`, `/organizer/*`, `/admin/*`, `/matches/{id}`…), IF–THEN decision list, UX notes, unresolved flow decisions.

### backend/battlecode26-scaffold/README.md
Stock Java scaffold README: `./gradlew build|run|update|zipForSubmit|tasks`, config in `gradle.properties`, player code under `src/`, maps under `maps/`, matches under `matches/`.

## 5. Unresolved `[DECIDE]` items (do not invent answers)

DEC-01 code per participant vs team (rec: per participant) · DEC-02 captain-only upload (rec: yes) · DEC-03 exact Python 3.13 patch + OS matrix · DEC-04 numeric time/memory/instruction limits (benchmark first) · DEC-05 retry cap 10 total vs 10 retries (rec: 10 total) · DEC-06 house-bot bracket algorithm · DEC-07 captain deleted with no successor (rec: captainless/inactive) · DEC-08 separate config-freeze deadline · DEC-09 live viewing (rec: defer) · DEC-10 replay format/player (rec: engine-native first) · DEC-11 stack/hosting/email/storage · DEC-12 team size/captain/name edits · DEC-13 account recovery + disputes · DEC-14 qualification-draw inputs + audit method. Also: auth/session model, pagination, upload size cap, roster file format, manual vs scheduled registration opening, deadline-vs-validation timing, post-retry-cap match state, source retention, log storage.

## 6. Key finding — first thing to fix

**Docs target Python 3.13; the scaffold currently pins Python 3.12.** `run.py` raises unless `sys.version_info[:2] == (3, 12)`, and `.venv` is CPython 3.12 (uv 0.13.5). Whether the `battlecode26` engine package works on 3.13 is **unverified** — that is exactly TC-01 / BIO-EPIC-01. Don't "fix" by editing the version check blindly: inspect the engine package (`.temp/battlecode.tar.gz` if present, or the installed `battlecode26` in `.venv`) and dependencies first.

## 7. Next recommended steps

1. BIO-EPIC-00: audit the scaffold (runner API, engine/client/package versions), produce the version matrix, run the Java baseline and the Python reference bot on 3.12 as the control (`./gradlew build --offline` already passes post-move).
2. BIO-EPIC-01: attempt Python 3.13 in a clean env; record the result with exact versions (TC-01). Don't just edit the 3.12 check in `run.py`.
3. Decide the `backend/` layout for the first built-on-top component (suggested: sibling packages next to `battlecode26-scaffold/`, e.g. bot validator and runner, before any Django code — execution foundation comes first).
4. Get decisions on DEC-03/04/05 before BIO-EPIC-02.
5. Optional: add a root `.gitignore`, and decide whether to take upstream client 1.0.7 (`./gradlew update`).

## 8. Task log (append newest at the bottom)

### 2026-11-05 — Onboarding: analyze docs, create handoff, seed memory
- Jira ID: none yet (no code changes; no branch/commit/PR made).
- Read PRD, SRD, API_CONTRACT, DATA_MODEL, TEST_PLAN, APP_FLOW, scaffold README, plus scaffold versions/`run.py`/`bot.py`.
- Files created: `handoff.md` (this file). Memory seeded: user profile, workflow rules, project overview, one memory per doc, scaffold state, open decisions, handoff pointer.
- Tests run: none (documentation task).
- Risks / findings: Py 3.12 vs 3.13 mismatch (§6); nested git repo in `docs/`; overlapping Jira IDs in PRD; version files vs nested git log differ.
- New decisions needed: Jira ID scheme; how to track the scaffold in the repo (submodule / vendor / exclude).

### 2026-11-05 — BIO-EPIC-00: integrate scaffold into backend + fix duplicate Jira IDs
- Branch `BIO-EPIC-00-backend-scaffold-integration` (epic-level branch because no task key exists for this work yet — rename if a Jira issue is created). Commits: (1) add six spec docs unchanged, (2) fix Jira IDs, (3) move scaffold into `backend/` and track it, (4) handoff update.
- Files changed: `docs/PRD.md` (v1.1: §5 scope IDs → `BIO-REQ-01..23`, new "ID scheme" subsection + traceability table in §10), `docs/TEST_PLAN.md` (v1.1: Jira refs on TC-02/03/06/07/08), `backend/README.md` (new), `backend/battlecode26-scaffold/**` (16 source files, moved from untracked `docs/battlecode26-scaffold`, nested `.git` removed), `handoff.md`.
- Tests run: `./gradlew build --offline` in the new location → exit 0 (only prints the "new client 1.0.7 available" notice); `.venv/bin/python` = 3.12.15 and `import battlecode26` OK. Not run: Python bot match, Java match, anything on Python 3.13. `git add -n` confirmed only the 16 source files + handoff/README are tracked (no `.venv`/`build`/`client`).
- Risks: upstream sync is now manual; `.venv/bin/activate` has a stale hardcoded path (venv still imports fine); IDE may recreate the old `docs/` path stub; REQ→epic table is my proposed mapping, needs owner confirmation.
- Decisions made by owner: vendor scaffold into backend and build on top of it; fix reused Jira IDs. Decisions I made (reversible): layout `backend/battlecode26-scaffold/`; `BIO-REQ-nn` naming; epic-level branch name.
- Still open: all `[DECIDE]` items (§5); Python 3.13 compatibility still unverified.

