# Battle It Out

INNOFEST **Battle It Out** is a Battlecode-style programming competition. Participants submit one Python file, `bot.py`, and the platform runs their bots against each other in the existing **Battlecode 2026** engine: invitation-based registration, bot validation, single-elimination brackets, tie-breaks, replays, notifications, and an immutable audit trail.

## Project status

**Early stage: only the execution foundation exists.** What is in the repository today:

- the requirement and design documents in [`docs/`](docs/);
- the Battlecode 2026 scaffold, vendored at [`backend/battlecode26-scaffold/`](backend/battlecode26-scaffold/);
- project state and working rules in [`handoff.md`](handoff.md).

There is **no API, database, worker, or website yet**. The delivery order is fixed: scaffold and Python 3.13 compatibility first, then safe bot execution and match automation, then backend, then registration and submissions, then tournament operations, then the website. See [`docs/PROJECT_PLAN.md`](docs/PROJECT_PLAN.md).

Known open issues (details in the plan and architecture documents):

- Python 3.13 is the target, but the scaffold launcher `run.py` accepts only Python 3.12, and 3.13 has not been tried.
- Running Python bots through Gradle fails or hangs on Linux unless the Python 3.12 venv is first on `PATH` and the runner is started outside Gradle; see `docs/TECHNICAL_DOCUMENTATION.md` section 3.2 for the verified workaround and its limits.
- The scaffold is licensed under AGPL-3.0; the project's own license is not yet decided.

## Quick start (local engine baseline)

Requirements: **JDK 21 or newer**. A cold clone needs network access on the first build to download the engine and client.

```bash
cd backend/battlecode26-scaffold
./gradlew build                      # first time: downloads engine and client
./gradlew runLocal --offline -Preplay=/tmp/baseline.bc26
```

Checked on 2026-11-24 (Java vs Java, warm cache): the match finishes in about 2 seconds and writes a replay. `-Preplay=` puts the replay where you choose; without it, the replay goes to `matches/` and replaces a file of the same name. The cold-clone `./gradlew build` was not tested.

To run Python bots you need a **Python 3.12** environment with the engine's `battlecode26` package; see [`docs/TECHNICAL_DOCUMENTATION.md`](docs/TECHNICAL_DOCUMENTATION.md) section 3 for what is verified and what is not before you rely on it.

## Repository layout

| Path | What it is |
|---|---|
| `docs/` | Specifications (PRD, SRD, API contract, data model, test plan, app flow) and guides |
| `backend/battlecode26-scaffold/` | Vendored Battlecode 2026 scaffold (Java and Python example bots, Gradle build, `run.py`) |
| `backend/README.md` | Provenance and local notes for the scaffold |
| `PRODUCT.md` | Product context for design tooling, derived from the docs |
| `handoff.md` | Current state, working rules, and task log: read this first |
| `CHANGELOG.md` | Notable changes |

## Documentation

| Read this | If you want to |
|---|---|
| [`docs/PRD.md`](docs/PRD.md), [`docs/SRD.md`](docs/SRD.md) | Know what must be built and why |
| [`docs/PROJECT_PLAN.md`](docs/PROJECT_PLAN.md) | See scope, phases, risks, and open decisions |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Understand how the system is designed and where the risks are |
| [`docs/TECHNICAL_DOCUMENTATION.md`](docs/TECHNICAL_DOCUMENTATION.md) | Work on the code: layout, build, bot contract, database, API |
| [`docs/API_CONTRACT.md`](docs/API_CONTRACT.md), [`docs/DATA_MODEL.md`](docs/DATA_MODEL.md) | Implement endpoints or the schema |
| [`docs/APP_FLOW.md`](docs/APP_FLOW.md) | Follow user flows, screens and edge cases |
| [`docs/TEST_PLAN.md`](docs/TEST_PLAN.md) | Know how the work will be verified |
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

The repository root has no license file yet. `backend/battlecode26-scaffold/` is under the **GNU Affero General Public License v3** (see its `LICENSE`). Choosing the project license and understanding the obligations that come with the scaffold's license is an open decision; see `docs/PROJECT_PLAN.md` risk R5.
