# Changelog

All notable changes to this project are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). The project has no tagged releases yet, so everything is under **Unreleased**. Entries reference pull requests on `hixam001/battle-it-out`; dates are the merge dates.

## [Unreleased]

### Added

- `backend/match_runner/`: command-line match launcher for Python and Java bots (Linux), pinned versions and artifact hash in `versions.lock.json`, an opt-in `TCP_NODELAY` shim, and unit tests (`python3 -m unittest backend.match_runner.tests.test_launcher`). Verified 2026-11-24 with full Python-vs-Python matches (A wins round 1290, replay identical with and without the shim).
- **Documentation set** (this change): `docs/PROJECT_PLAN.md`, `docs/ARCHITECTURE.md`, `docs/TECHNICAL_DOCUMENTATION.md`, `docs/USER_GUIDE.md`, `docs/ADMIN_GUIDE.md`, a full `README.md`, and this changelog.
- `PRODUCT.md`: product context for design tooling, derived from the requirement documents (#4, 2026-11-24).
- Root `.gitignore` ignoring `.claude/settings.local.json`, `.claude/skills/`, `.claude/agents/`, `.agents/`, and `skills-lock.json` (#4, 2026-11-24).
- Agent skills `security-audit` (#2) and `impeccable` (#3) were installed and merged on 2026-11-24, then untracked again in #4 (see Removed).
- Requirement and design documents: `docs/PRD.md`, `docs/SRD.md`, `docs/API_CONTRACT.md`, `docs/DATA_MODEL.md`, `docs/TEST_PLAN.md`, `docs/APP_FLOW.md` (#1, 2026-11-05).
- `handoff.md`: project state, working rules, document digest, and task log (#1, 2026-11-05).
- Battlecode 2026 scaffold vendored at `backend/battlecode26-scaffold/` from upstream `battlecode/battlecode26-scaffold` commit `f69e2ab`, with two local changes: `engine_version.txt` set to 1.2.6 and a rewritten example `RobotPlayer.java`. `backend/README.md` records provenance (#1, 2026-11-05).

### Changed

- Jira/requirement ID scheme: PRD scope items renumbered from the duplicate `BIO-101..110`, `BIO-201..208`, `BIO-301..305` to `BIO-REQ-01..23`; PRD and test plan bumped to v1.1, and test-plan Jira references now point only at defined task keys or epic IDs (#1, 2026-11-05).

### Removed

- Agent and skill files (`.claude/skills/`, `.claude/agents/`, `.agents/`, `skills-lock.json`) are no longer tracked by git; the files stay on each developer's machine. Reinstall locally with the install commands recorded in `handoff.md` (#4, 2026-11-24).

### Known issues

- Python 3.13 compatibility is unverified; the scaffold launcher `run.py` accepts only Python 3.12.
- The Gradle Python-bot path fails on Linux as shipped (wrong `python3` from `PATH`; `--new-process` start-up deadlock). Use the new launcher (see Added). Python matches run at about 0.9 rounds per second (1.8 with the opt-in shim); the remaining latency is unexplained.
- The only automated test is a placeholder (`1 + 1`); the scaffold's Python `verify` checks only for the text `def turn():`.
- The scaffold is AGPL-3.0 and the project has no license of its own yet.
