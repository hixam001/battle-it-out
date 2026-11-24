# Battle It Out

INNOFEST **Battle It Out** is a Battlecode-style programming competition. Participants submit one Python file, `bot.py`, and the platform runs their bots against each other in the existing **Battlecode 2026** engine: invitation-based registration, bot validation, single-elimination brackets, tie-breaks, replays, notifications, and an immutable audit trail.

## Project status

**Early stage: only the execution foundation exists.** What is in the repository today:

- the requirement and design documents in [`docs/`](docs/);
- the Battlecode 2026 scaffold, vendored at [`backend/battlecode26-scaffold/`](backend/battlecode26-scaffold/);
- project state and working rules in [`handoff.md`](handoff.md).

There is **no API, database, worker, or website yet**. The delivery order is fixed: scaffold and Python 3.13 compatibility first, then safe bot execution and match automation, then backend, then registration and submissions, then tournament operations, then the website. See [`docs/PROJECT_PLAN.md`](docs/PROJECT_PLAN.md).

Known open issues (details in the plan and architecture documents):

- The engine package officially supports only Python 3.12. Python 3.12 to 3.15 (latest stable, 3.15.2) pass our tests through `backend/match_runner/`, on Linux x86_64 only; the engine's authors do not support this (`docs/CHANGE_NOTICES.md` CN-001).
- The engine's bot sandbox is weak (it allows `open`, attribute-walk escapes and infinite loops); isolation and limits are still to be built (`docs/TECHNICAL_DOCUMENTATION.md` section 3.5).
- Running Python bots through Gradle fails or hangs on Linux. Use `python3 backend/match_runner/launcher.py run ...` (see `backend/match_runner/README.md`); a match of the example bot takes about 3 seconds.
- The scaffold is licensed under AGPL-3.0; the project's own license is not yet decided.

## Quick start (local match)

Requirements: **JDK 21 or newer** (the Battlecode engine server is a Java program), [`uv`](https://docs.astral.sh/uv/), and network access the first time (engine and Python downloads). Participants write Python bots only; Java bots were removed.

```bash
cd backend/battlecode26-scaffold && ./gradlew build && cd ../..      # first time: downloads the engine jar
python3 backend/match_runner/setup_env.py 3.15                       # pinned environment, hash-checked engine package
python3 backend/match_runner/launcher.py verify
python3 backend/match_runner/launcher.py run --team-a examplefuncsplayer_py --team-b examplefuncsplayer_py \
    --out-dir /tmp/bio-match                                          # prints a JSON summary; replay and logs in --out-dir
```

Checked on 2026-11-24 on Python 3.12, 3.13, 3.14 and 3.15: the example match finishes in about 3 seconds (team A wins in round 1290) with the same replay on every version. Other versions: `setup_env.py 3.14` and `--python-version 3.14`. The cold-clone `./gradlew build` was not tested.

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
