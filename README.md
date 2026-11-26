# Battle It Out

INNOFEST **Battle It Out** is a Battlecode-style programming competition. Participants submit Python `bot.py`, alone or in a flat-module bundle with curated dependencies, and the platform runs their bots against each other in the existing **Battlecode 2026** engine: invitation-based registration, bot validation, single-elimination brackets, tie-breaks, replays, notifications, and an immutable audit trail.

## Project status

**Execution libraries and an initial web feature platform are implemented.**

- Existing Battlecode engine and sandboxed Python workers, queue, tournament flow, registry, roster, notifications and replay vault.
- [Django/DRF feature API with PostgreSQL](backend/webapp/README.md): sessions, current roster/Organizer scope, submissions, analytics, disputes, recipient notifications/preferences and an Admin operations reader. Notification state still uses the shared legacy store.
- [React/TypeScript website](frontend/README.md): public landing page and private feature console, with desktop/mobile browser checks.
- [Native Python bundles](backend/submission_bundle/README.md) and [private live boards](backend/live_view/README.md), verified with real engine games.
- Durable continuation notes in [project memory](docs/PROJECT_MEMORY.md) and [handoff](handoff.md).

The owner activated the five former deferred features and selected Django/DRF,
PostgreSQL and React/TypeScript (CN-028). Other languages follow compatibility
work. No production website/services are deployed; many core endpoints/screens,
the legacy JSON-store migration and execution/launch gates remain open. See
[coverage](docs/REQUIREMENTS_COVERAGE.md) for the exact remaining gaps.

[`backend/services/`](backend/services/README.md) now provides interim single-host worker, maintenance, email and alert commands with configuration and a reviewable systemd template (BIO-409; CN-027). Maintenance always uses the roster, notifications and replay vault. Providers/channels are operator-supplied; no production services are deployed.

Known open issues (details in the plan and architecture documents):

- The engine package officially supports only Python 3.12. Python 3.12 to 3.15 (latest stable, 3.15.2) pass our tests through `backend/match_runner/`, on Linux x86_64 only; the engine's authors do not support this (`docs/CHANGE_NOTICES.md` CN-001).
- The engine's bot sandbox is weak (it allows `open`, attribute-walk escapes and infinite loops); our per-team OS isolation and provisional limits are implemented, with benchmarking and independent review still open (`docs/TECHNICAL_DOCUMENTATION.md` section 3.5).
- Running Python bots through Gradle fails or hangs on Linux. Use `python3 backend/match_runner/launcher.py run ...` (see `backend/match_runner/README.md`); a match of the example bot takes about 3 seconds.
- The match runner has had one self-review (`docs/SECURITY_REVIEW.md`, CN-008): five defects were fixed, two residual risks stay open, and a human or third-party review is still needed. Isolation is for Linux x86_64 only.
- The Battlecode Java engine declares no license; written confirmation from the Battlecode team is still needed (`docs/LICENSING.md`).

## Quick start (local match)

Requirements: **JDK 21 or newer** (the Battlecode engine server is a Java program), [`uv`](https://docs.astral.sh/uv/), and network access the first time (engine and Python downloads). Participants write Python bots only; Java bots were removed.

```bash
cd backend/battlecode26-scaffold && ./gradlew build && cd ../..      # first time: downloads the engine jar
python3 backend/match_runner/setup_env.py 3.15                       # pinned environment, hash-checked engine package
python3 backend/match_runner/launcher.py verify
python3 backend/match_runner/launcher.py run --team-a examplefuncsplayer_py --team-b examplefuncsplayer_py \
    --out-dir /tmp/bio-match                                          # prints a JSON summary; replay and logs in --out-dir
```

All backend tests: `python3 backend/run_tests.py` (this Python), `--matrix` (every Python of the lock), `--integration` (real games); 751 tests pass on 3.12, 3.13, 3.14 and 3.15 (2026-11-25). Checked on 2026-11-24 on Python 3.12, 3.13, 3.14 and 3.15: the example match finishes in about 3 seconds (team A wins in round 1290) with the same replay on every version. Other versions: `setup_env.py 3.14` and `--python-version 3.14`. The cold-clone `./gradlew build` was not tested.

## Repository layout

| Path | What it is |
|---|---|
| `docs/` | Specifications (PRD, SRD, API contract, data model, test plan, app flow) and guides |
| `backend/battlecode26-scaffold/` | Vendored Battlecode 2026 scaffold (Python example bot, Gradle build, `run.py`) |
| `backend/match_runner/` | Match launcher, pinned environments, test bots |
| `backend/match_orchestrator/` | Match jobs with platform retry, incidents, exactly-once result, tie-break maps and coin flip (library) |
| `backend/bot_validator/` | Bot validator and the engine-derived bot policy |
| `LICENSE`, `THIRD_PARTY_NOTICES.md` | AGPL-3.0 and third-party notices |
| `backend/README.md` | Provenance and local notes for the scaffold |
| `PRODUCT.md` | Product context for design tooling, derived from the docs |
| `handoff.md` | Current state, working rules, and task log: read this first |
| `CHANGELOG.md` | Notable changes |

## Documentation

| Read this | If you want to |
|---|---|
| [`docs/PROJECT_MEMORY.md`](docs/PROJECT_MEMORY.md) | Resume from the reconciled Claude/Codex checkpoint, working rules and complete remaining backlog |
| [`docs/PRD.md`](docs/PRD.md), [`docs/SRD.md`](docs/SRD.md) | Know what must be built and why |
| [`docs/PROJECT_PLAN.md`](docs/PROJECT_PLAN.md) | See scope, phases, risks, and open decisions |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Understand how the system is designed and where the risks are |
| [`docs/TECHNICAL_DOCUMENTATION.md`](docs/TECHNICAL_DOCUMENTATION.md) | Work on the code: layout, build, bot contract, database, API |
| [`docs/API_CONTRACT.md`](docs/API_CONTRACT.md), [`docs/DATA_MODEL.md`](docs/DATA_MODEL.md) | Implement endpoints or the schema |
| [`docs/APP_FLOW.md`](docs/APP_FLOW.md) | Follow user flows, screens and edge cases |
| [`docs/TEST_PLAN.md`](docs/TEST_PLAN.md) | Know how the work will be verified |
| [`docs/JIRA_BREAKDOWN.md`](docs/JIRA_BREAKDOWN.md) | The proposed Jira tasks of BIO-EPIC-04 to BIO-EPIC-08 with requirements covered, state today and dependencies |
| [`docs/REQUIREMENTS_COVERAGE.md`](docs/REQUIREMENTS_COVERAGE.md) | See, requirement by requirement, what Battlecode provides, what is built and what we still must develop |
| [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md) | Learn the participant and organizer experience (planned platform) |
| [`docs/ADMIN_GUIDE.md`](docs/ADMIN_GUIDE.md) | Learn the platform Admin's responsibilities (planned platform) |

Documents label what is confirmed, proposed (needs approval), and unresolved (`[DECIDE]`). Do not turn a proposal into a requirement silently.

## Contributing

- Every task gets a branch named with Jira notation (for example `BIO-102-python-313-setup`, or `BIO-EPIC-0N-short-description` for epic-level work), then commit, push, and a pull request. No direct commits to `main`.
- Do not add co-authors or generated-by lines to commits, pushes, or pull requests.
- Read [`handoff.md`](handoff.md) before starting, and append a task-log entry when you finish. Report Jira ID, files changed, tests run and results, risks, and new decisions.
- Never claim compatibility, isolation, resource enforcement, or match reliability without a test that actually ran.
- Agent and skill files (`.claude/skills`, `.claude/agents`, `.agents`, `skills-lock.json`) are git-ignored: install them locally if you use them.

## License

The project is licensed under the **GNU Affero General Public License v3.0 only** (`LICENSE`), the same license as the Battlecode scaffold it builds on (`docs/CHANGE_NOTICES.md` CN-003). Third-party components and the licenses they declare are in [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md); obligations and open items (copyright holder, participant terms, the Java engine's missing license, the source offer for a network-served site) are in [`docs/LICENSING.md`](docs/LICENSING.md). This is not legal advice.
