# Battle It Out --- Project Plan & Scope Statement

> **CN-028 owner update (2026-11-26):** the five deferred feature groups are active. Django/DRF, PostgreSQL and React/TypeScript are selected; live viewing is tournament-private; Python bundles/curated dependencies precede additional languages. Local web feature implementation is authorized while existing execution gates remain open. No gate completion or production deployment is implied; earlier scheduling/deferral text below is the historical baseline where it conflicts.

**Version:** 1.0\
**Status:** Working baseline\
**Date:** 2026-11-24\
**Audience:** project owner, contributors, and tournament stakeholders who need to know what is being built, in what order, and what is still undecided.\
**Requirement coverage:** every requirement, whether Battlecode provides it and what is built is tracked in `REQUIREMENTS_COVERAGE.md`; what Battlecode lacks is ours to develop.

**Sources:** `PRD.md` (v1.1), `SRD.md`, `APP_FLOW.md`, `API_CONTRACT.md`, `DATA_MODEL.md`, `TEST_PLAN.md`, `PRODUCT.md`, `handoff.md`, and the code in `backend/`.

> **Labels used in this document.** *Confirmed* = established in the requirement documents. *Proposed* = recommended but not approved. `[DECIDE]` = unresolved; do not assume an answer. *Observed* = checked directly in the repository or by running a command on 2026-11-24. This plan contains no calendar dates for future work on purpose: the PRD requires sprint dates to be set only after the repository audit and a hardware benchmark.

## 1. Background and purpose

INNOFEST needs a Battlecode-style programming competition in which participants submit a single Python bot (`bot.py`) that competes automatically in the existing Battlecode 2026 engine. It must be approachable for beginners (including participants using AI assistance) and still deep enough for experienced programmers. The platform controls registration, submissions, matches, brackets, results, notifications, and an immutable audit history.

The largest early risk is technical, not visual: can the Battlecode 2026 scaffold be reproduced, run on Python 3.13, and execute participant bots safely and reliably? The plan therefore proves the execution path first and builds the website last.

## 2. Objectives and success criteria

| ID | Objective | Measure (from PRD §2-3) | Priority |
|---|---|---|---|
| BIO-G01 | Reproducible scaffold on Python 3.13 | A clean setup installs and runs the reference Python bot and a test bot with no manual patching | P0 |
| BIO-G02 | Safe, deterministic bot execution | Two independently submitted `bot.py` files complete a match; crashes and limit violations are bot losses; engine failures are distinguishable | P0 |
| BIO-G03 | Automated match lifecycle | A test bracket runs sequentially, records results, advances winners, applies tie-break maps, and uses the final coin flip when required | P0 |
| BIO-G04 | Controlled tournament, registration and submission management | Admin / Organizer / Participant permission tests pass for all documented critical operations | P1 |
| BIO-G05 | Visible, auditable outcomes | Dashboard notifications for major events; email can be disabled; audit records are immutable and retained | P1 |

Success metrics (PRD §3): 100% clean-machine setup checks pass; at least 99% of valid pilot matches complete without platform-caused failure (`[DECIDE]` sample size); 100% of injected failures classified correctly; 100% of critical permission tests pass; every completed match records bot versions, map, engine version, seed, result and attempt.

## 3. Scope statement

### 3.1 In scope (confirmed)

1. **Execution foundation (P0).** Audit and reproduce the Battlecode 2026 scaffold; Python 3.13 compatibility; one-file `bot.py` contract; bot validation; isolated worker with fixed platform-wide limits; bot-failure versus platform-failure classification; sequential matches with bracket advancement, byes, house bots, tie-break maps, coin flip, replays, and a platform-failure retry policy (up to 10, then alert Admin).
2. **Backend and tournament operations (P1).** Authentication and roles; tournament creation, approval and lifecycle; roster import and invitation-code registration; bot submissions with version history; Admin/Organizer operations; audit log; email and dashboard notifications; deletion and retention rules; participant dashboards, bracket/results views and replay access.
3. **Quality gate (P0 launch gate).** Security, load, backup/recovery, a pilot tournament, deployment, and runbooks.

### 3.2 Out of scope for the first release (confirmed)

Public landing page before the execution foundation passes its exit gate; additional bot languages; multi-file or ZIP submissions; participant-installed dependencies or custom runtimes; anonymous public results; live match streaming (unless later approved); advanced analytics and spectator features; a match-dispute workflow (unless separately approved); per-tournament execution limits (limits are global); any replacement for the Battlecode engine.

### 3.3 Scope boundaries and rules that must not be bent

- The Battlecode 2026 engine stays the source of game simulation (SRD-001).
- Nothing in the website phase starts until BIO-EPIC-01 to BIO-EPIC-03 pass their exit gate.
- Numeric limits (time, memory, instructions) come from benchmarks and are never invented.
- Permissions are enforced on the server for every protected operation.
- Compatibility, isolation, resource enforcement and reliability are never claimed without a test that proves them.

## 4. Assumptions, constraints, dependencies

**Assumptions** (not yet verified): a single worker host is sufficient for the first tournament (`[DECIDE]` load targets); the official roster arrives in an importable format (`[DECIDE]` format); organizers will operate rounds manually, as the PRD describes.

**Constraints:** Python only; exactly one `bot.py`; same runtime image for every bot; no participant-installed packages; Java 21 or newer is enforced by the scaffold build (*Observed*: `build.gradle` throws below JDK 21); the Python target is the latest stable CPython (3.15.2 tested; 3.12 to 3.14 also pass; CN-001), run through `backend/match_runner/runner_entry.py` because the scaffold's `run.py` accepts only 3.12 (*Observed*). Java bots are removed (CN-002); the Java engine server stays.

**External dependencies:** the Battlecode engine, client and Python package releases (served from `releases.battlecode.org` and `api.battlecode.org`); third-party packages on Python 3.13; worker hardware; email provider and domain; object storage; hosting.

## 5. Deliverables

| # | Deliverable | Epic | Exit evidence |
|---|---|---|---|
| D1 | Version matrix and audit of the scaffold, runner API and dependencies | BIO-EPIC-00 | Approved technical baseline and unresolved-decision register |
| D2 | Reproducible Python 3.13 setup with pinned dependencies and smoke tests | BIO-EPIC-01 | Clean environment runs the reference Python bot and tests (TC-01) |
| D3 | `bot.py` contract, validator, isolated runner, resource limits, failure classification, structured logs | BIO-EPIC-02 | Two independent bots complete matches; injected failures classified correctly (TC-02, TC-03, TC-04) |
| D4 | Match and tournament automation: bracket, byes, house bots, tie-breaks, coin flip, replay lifecycle, retry and alerts | BIO-EPIC-03 | A full simulated tournament passes end to end (TC-05) |
| D5 | Backend: auth, roles, database, API, audit, storage, job queue | BIO-EPIC-04 | API permission and persistence tests pass (TC-07) |
| D6 | Registration and submission management | BIO-EPIC-05 | Participant flow passes with privacy and deadline rules (TC-06) |
| D7 | Tournament operations: approval, deadlines, notifications, deletion, archive | BIO-EPIC-06 | Admin/Organizer lifecycle tests pass (TC-07, TC-08) |
| D8 | Website and dashboards (landing page included) | BIO-EPIC-07 | Usability and end-to-end acceptance complete |
| D9 | QA, pilot tournament, deployment, runbooks | BIO-EPIC-08 | Go-live checklist signed off; no open Blocker/Critical defects |
| D10 | Documentation set (this plan, architecture, technical/API, README and changelog, user and admin guides) | all | Reviewed and kept in sync with the code |

## 6. Work breakdown and roadmap

Jira issue keys are `BIO-NNN` where the hundreds digit is the epic number; scope items in PRD §5 are requirement IDs `BIO-REQ-01..23` (see PRD §10, "ID scheme"). The EPIC-00 to EPIC-03 tasks are defined below; the proposed tasks of EPIC-04 to EPIC-08 are in [`JIRA_BREAKDOWN.md`](JIRA_BREAKDOWN.md) (CN-024).

| Phase | Epic | Priority | Defined tasks | Exit gate |
|---|---|---|---|---|
| 0 Discovery and baseline | BIO-EPIC-00 | P0 | BIO-001 inspect repository; BIO-002 map Python runner; BIO-003 record engine/client/package versions; BIO-004 clean-environment baseline; BIO-005 resolve `[DECIDE]` items that affect execution | Approved technical baseline and decision register |
| 1 Scaffold modernization | BIO-EPIC-01 | P0 | BIO-101 pin dependencies; BIO-102 Python 3.13 setup; BIO-103 repair Python runner integration; BIO-104 smoke tests; BIO-105 document clean setup | Clean environment runs the reference Python bot and tests |
| 2 Python bot execution | BIO-EPIC-02 | P0 | BIO-201 define bot contract; BIO-202 validate `bot.py`; BIO-203 run bot in isolated worker; BIO-204 enforce resource limits; BIO-205 classify bot/platform failure; BIO-206 structured logs | Two independent bots complete matches; injected failures classified |
| 3 Match / tournament automation | BIO-EPIC-03 | P0 | BIO-301 match orchestration; BIO-302 sequential round runner; BIO-303 bracket/bye/house-bot rules; BIO-304 tie-break maps and coin flip; BIO-305 replay lifecycle; BIO-306 platform retry and Admin alert | Full simulated tournament passes |
| 4 Backend foundation | BIO-EPIC-04 | P1 | BIO-401 to BIO-410 (proposed): stack decision, schema, store adapters, API skeleton, accounts and sessions, roles and scope, audit log, private storage, services, permission tests | API permission and persistence tests pass |
| 5 Registration and submissions | BIO-EPIC-05 | P1 | BIO-501 to BIO-508 (proposed): roster, codes, teams, upload, submission reads, privacy tests, TC-06 flow, account recovery | Participant flow passes with privacy and deadline rules |
| 6 Tournament operations | BIO-EPIC-06 | P1 | BIO-601 to BIO-611 (proposed): tournament, deadline, bracket and round endpoints, Admin trouble tools, replays and logs, archive jobs, notifications, deletion lifecycle, audit read, lifecycle tests | Admin/Organizer lifecycle tests pass |
| 7 Website and participant UI | BIO-EPIC-07 | P1 | BIO-701 to BIO-709 (proposed): frontend foundation, account, dashboard, submission, bracket and replay, Organizer, Admin screens, acceptance; landing page and feature console now implemented locally (CN-028), with remaining core screens/acceptance open | Usability and end-to-end acceptance complete |
| 8 QA, pilot, production | BIO-EPIC-08 | P0 launch gate | BIO-801 to BIO-808 (proposed): security and independent review, reliability and load, backups, deployment and CI, runbooks, licensing and terms, pilot, sign-off | Go-live checklist signed off |

```mermaid
flowchart LR
  E0[EPIC-00<br/>Discovery] --> E1[EPIC-01<br/>Scaffold + Py 3.13]
  E1 --> E2[EPIC-02<br/>Bot runner + sandbox]
  E2 --> E3[EPIC-03<br/>Match automation]
  E3 -->|execution gate| E4[EPIC-04<br/>Backend]
  E4 --> E5[EPIC-05<br/>Registration + submissions]
  E5 --> E6[EPIC-06<br/>Tournament ops]
  E6 --> E7[EPIC-07<br/>Website]
  E7 --> E8[EPIC-08<br/>QA + pilot + launch]
```

### 6.1 Current status (as of 2026-11-25)

**The execution foundation (BIO-EPIC-00 to BIO-EPIC-03) is built as tested libraries; the platform around it (BIO-EPIC-04 and later) is not.** The source of truth is [`REQUIREMENTS_COVERAGE.md`](REQUIREMENTS_COVERAGE.md): 17 requirements done, 50 partial, 19 not built, 5 deferred (of 91).

Built and tested (evidence: change notices CN-001 to CN-025, pull requests #1 to #31, all merged):
- Pinned, reproducible match runner on Python 3.12 to 3.15 (Linux x86_64), per-team sandbox and limits (interim numbers), failure classification, structured logs.
- Bot validator, upload check with a trial match, submission registry (versions, activation, deadline lock, privacy).
- Match orchestration with retry, tie-break maps and coin flip, single-elimination bracket with byes, replay vault and archive purge, worker queue, the flow between upload and round.
- Tournament lifecycle and deadline timer, roster, invitation codes and registration, notifications and their sources.
- All of the above are **libraries with JSON-file stores**: no HTTP API, database, accounts, website, running services or worker image exist.

Not done (see `JIRA_BREAKDOWN.md` for the tasks): the full backend foundation (needs DEC-11), remaining endpoints and screens, deletion and retention, load and recovery tests, an independent security review, the pilot, and the owner decisions DEC-04, DEC-06, DEC-07, DEC-10, DEC-11, DEC-13, DEC-14. The whole backend suite was run on Python 3.12, 3.13, 3.14 and 3.15 on 2026-11-25 (CN-025). CN-075 adds the frontend build check. The hosted Python matrix and real-engine CI remain BIO-804 work.

### 6.2 Recommended next work (in order)

The proposed tasks, their dependencies and the order they allow are in [`JIRA_BREAKDOWN.md`](JIRA_BREAKDOWN.md). In short: (1) the owner answers DEC-11 so that BIO-EPIC-04 can start, and the decisions that block the open parts of BIO-EPIC-02 and BIO-EPIC-03 (DEC-04, DEC-06, DEC-14); (2) stack-neutral work meanwhile (the API contract gap for users, roles and Organizer assignments, service wiring, licensing and runbook text); (3) the backend foundation, then the endpoints of BIO-EPIC-05 and BIO-EPIC-06, then the website, then the launch gate.

## 7. Decisions needed before work can proceed

| Needed before | Decision | Source |
|---|---|---|
| BIO-EPIC-01 | Exact Python 3.13 patch version and supported OS matrix | DEC-03 |
| BIO-EPIC-02 | Numeric time, memory and instruction limits (benchmark first); upload size cap (the import policy is decided: CN-004) | DEC-04, R3 |
| BIO-EPIC-02/03 | Retry cap: 10 total attempts (recommended) or 10 retries after the first | DEC-05 |
| BIO-EPIC-03 | House-bot bracket algorithm; qualification-draw inputs and randomness audit | DEC-06, DEC-14 |
| BIO-EPIC-03 | Replay format and browser playback | DEC-10 |
| BIO-EPIC-04 | Stack, hosting, email provider, object storage; auth/session model; pagination style | DEC-11 + API contract §9 |
| BIO-EPIC-05 | Invitation code granularity; who may upload (captain-only recommended); team size and captain rules; roster file format; upload size cap | DEC-01, DEC-02, DEC-12 |
| BIO-EPIC-06 | Captain deleted with no successor; config-freeze deadline; account recovery and disputes; source retention | DEC-07, DEC-08, DEC-13 |
| Before any code is published or served | **Open licensing items** (R5): Java engine confirmation, copyright holder, participant terms | new |

The full register is in PRD §11 and `PRODUCT.md`.

## 8. Risk register

Likelihood and impact are qualitative judgments by the author of this plan, not measurements.

| ID | Risk | Evidence | Impact | Mitigation | Status |
|---|---|---|---|---|---|
| R1 | The engine package does not officially support Python above 3.12, yet the project runs it on 3.15 | *Verified 2026-11-24*: tested 3.12, 3.13, 3.14, 3.15 with identical results; the package's `Requires-Python` is `<3.13` and its `main()` rejects other versions; we bypass both in `runner_entry.py` | Medium | Pins in `versions.lock.json`; re-run the matrix on any engine or Python change; keep 3.12 as fallback; owner to confirm CN-001 and DEC-03 | Mitigated |
| R2 | Python-bot matches did not start through Gradle and took 12 to 23 minutes | *Verified 2026-11-24*: wrong `python3` on `PATH`, `--new-process` deadlock, and Nagle plus delayed-ACK stalls (about 40 ms per message, no `TCP_NODELAY` on either side). The launcher fixes the first two and `runner_entry.py` sets `TCP_NODELAY` and `TCP_QUICKACK`: a full match now takes about 3 s with an identical replay | Low | Keep the launcher as the only supported way to run matches | Mitigated |
| R3 | The engine's Python runner restricts imports more than the PRD promises | *Observed* in `battlecode26/runner.py`: a bot may import only its own modules plus `random`, `math`, `enum`, `battlecode26`; the PRD says "standard library and preinstalled libraries" | Medium | Decide the import policy (DEC-04 area) and document it in the bot contract; update PRD if the engine's rule is accepted | Open |
| R4 | Engine-level restrictions are not host isolation | *Observed*: Python bots run in a Python process under RestrictedPython with bytecode counting and talk to the Java server over loopback TCP; PRD BIO-NFR-01 requires isolation from host services, other bots and user data | High | Add container/OS-level isolation (no network, read-only filesystem, CPU/memory/process limits) per the worker design; prove with the security tests in the test plan | **Mitigated, not closed (2026-11-24):** one bubblewrap sandbox per team with seccomp, optional cgroups, a wall-clock/memory guard and a router, tested with hostile bots (TECHNICAL_DOCUMENTATION §3.6, CN-005). Still open: independent security review, benchmark-approved numeric limits (DEC-04), engine seed control (TC-04) |
| R5 | Licensing: AGPL-3.0 scaffold, and a Java engine with no declared license | *Observed 2026-11-24*: scaffold is AGPL-3.0, Python engine package MIT, Java engine jar and repository have no license. The project is now AGPL-3.0-only (CN-003) | Medium | Obligations and open items in `docs/LICENSING.md`: get written confirmation from the Battlecode team about the engine, decide the copyright holder and participant terms, plan the section 13 source offer; this plan makes no legal conclusion | Partly resolved |
| R6 | Weak existing validation | *Observed*: `run.py verify` only checks that `bot.py` exists and contains the text `def turn():`; the bundled Java test is `assertEquals(2, 1+1)` | Medium | BIO-202 builds real syntax/import/entrypoint/runtime validation; BIO-104 adds meaningful smoke tests | Open |
| R7 | Vendored scaffold falls behind upstream | Upstream history is not kept; the build already reports client 1.0.7 available while 1.0.6 is configured | Low | Update deliberately via `./gradlew update` in its own PR with a re-run of the baseline | Open |
| R8 | Unbenchmarked resource limits | The engine's default bytecode limit is 20000 but is "updated by game"; PRD limits are undecided | Medium | Benchmark on target hardware (DEC-04) before any numeric claim | Open |
| R9 | Undecided stack, hosting, email, storage | PRD §9 lists the stack as proposed only | Medium | Approve the stack at the end of Phase 0 (DEC-11) | Open |
| R10 | Single recorded contributor | Git history and policy show one contributor | Medium | Keep `handoff.md` current; small PRs; documented decisions | Ongoing |

## 9. Governance and working agreements

- **Owner:** Hisham Ahmed is the sole recorded contributor. Tournament roles (Admin, Organizer, Participant) are product roles, not project-team roles.
- **Branching and delivery:** every task gets a branch named with Jira notation (`BIO-NNN-short-description`, or `BIO-EPIC-0N-short-description` for epic-level work), then commit, push, and a pull request. Work is never done directly on `main`.
- **Attribution:** no co-author or generated-by lines in commits, pushes or pull requests.
- **Start and end of every task:** read `handoff.md` and memory first; append a task-log entry to `handoff.md` at the end.
- **Definition of done** (PRD §12): each change reports Jira ID, files changed, tests run, results, risks, and any newly discovered decision. A test counts only if it was actually run; the engine is never mocked as the sole proof of Python 3.13 compatibility.
- **Change control:** a changed requirement updates the PRD/SRD first, then dependent documents; a new unresolved question is added to the decision register with `[DECIDE]`. Proposed choices never silently become requirements.
- **Severity and release gate:** Blocker, Critical, Major, Minor as defined in `TEST_PLAN.md` §7. No production launch with open Blocker or Critical defects; all P0 acceptance tests pass; the pilot tournament is completed and reviewed.

## 10. Reporting and review

Progress is tracked in `handoff.md` (task log, next steps) and in pull requests. Each epic closes only when its exit gate evidence exists: test reports with exact versions (Python, engine, client, packages, OS, worker image digest). Review the plan at the end of each phase and whenever a `[DECIDE]` item is resolved.

## 11. Document map

| Need | Document |
|---|---|
| What the product must do | `PRD.md`, `SRD.md`, `PRODUCT.md` |
| How the system is structured | `ARCHITECTURE.md` |
| Code, build, database, API reference | `TECHNICAL_DOCUMENTATION.md`, `API_CONTRACT.md`, `DATA_MODEL.md` |
| How users and screens behave | `APP_FLOW.md`, `USER_GUIDE.md`, `ADMIN_GUIDE.md` |
| How it is verified | `TEST_PLAN.md` |
| Current state and history | `handoff.md`, `../CHANGELOG.md`, `../README.md` |
