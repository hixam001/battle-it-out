# Changelog

All notable changes to this project are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). The project has no tagged releases yet, so everything is under **Unreleased**. Entries reference pull requests on `hixam001/battle-it-out`; dates are the merge dates.

## [Unreleased]

### Added

- **Bot execution limits and sandbox (BIO-203/204, first version):** `backend/match_runner/guard.py` (wall-clock watchdog for turns and start-up, memory check, rlimits, usage measurements, uncaught-exception counts), `sandbox.py` (bubblewrap: no network, read-only root, only the two teams' bot folders, unix-socket bridge to the engine server), `limits.provisional.json` (**provisional, unapproved numbers**, DEC-04), automatic `normal` / `bot_violation` / `platform_failure` classification in the launcher, hostile test bots (`hang_py`, `hang_init_py`, `memhog_py`, `allocbomb_py`, `escape_py`) and tests. The sandboxed example match produces the identical replay on Python 3.12 to 3.15 in about the same time.
- **License and notices (CN-003):** root `LICENSE` (AGPL-3.0-only, same text as the Battlecode scaffold), SPDX identifiers on our source files, `THIRD_PARTY_NOTICES.md`, `docs/LICENSING.md` (what each Battlecode component declares, AGPL obligations, open items), and a dated modification notice in the one edited scaffold file.
- **Bot policy and validator (CN-004):** `docs/BOT_POLICY.md` and `backend/bot_validator/` (policy generated from the engine, validator with error and warning codes, 13 tests including an agreement test against the real engine runner and a drift check).
- `backend/match_runner/`: command-line match launcher for Python bots on Python 3.12, 3.13, 3.14 and 3.15 (Linux), with pinned versions and engine-package SHA-256 in `versions.lock.json`, `setup_env.py` (reproducible environments via `uv`), `runner_entry.py` (runs the engine's runner on newer Pythons and removes socket latency), test bots, 14 unit tests and opt-in real-match integration tests. A full match of the example bot takes about 3 seconds on every tested version, down from 12 to 23 minutes, with an identical replay.
- `docs/CHANGE_NOTICES.md`: CN-001 (latest stable Python, 3.15.2, replaces the 3.13 target) and CN-002 (Java bots removed); notices added to the PRD, SRD, TEST_PLAN and APP_FLOW headers.
- **Documentation set** (this change): `docs/PROJECT_PLAN.md`, `docs/ARCHITECTURE.md`, `docs/TECHNICAL_DOCUMENTATION.md`, `docs/USER_GUIDE.md`, `docs/ADMIN_GUIDE.md`, a full `README.md`, and this changelog.
- `PRODUCT.md`: product context for design tooling, derived from the requirement documents (#4, 2026-11-24).
- Root `.gitignore` ignoring `.claude/settings.local.json`, `.claude/skills/`, `.claude/agents/`, `.agents/`, and `skills-lock.json` (#4, 2026-11-24).
- Agent skills `security-audit` (#2) and `impeccable` (#3) were installed and merged on 2026-11-24, then untracked again in #4 (see Removed).
- Requirement and design documents: `docs/PRD.md`, `docs/SRD.md`, `docs/API_CONTRACT.md`, `docs/DATA_MODEL.md`, `docs/TEST_PLAN.md`, `docs/APP_FLOW.md` (#1, 2026-11-05).
- `handoff.md`: project state, working rules, document digest, and task log (#1, 2026-11-05).
- Battlecode 2026 scaffold vendored at `backend/battlecode26-scaffold/` from upstream `battlecode/battlecode26-scaffold` commit `f69e2ab`, with two local changes: `engine_version.txt` set to 1.2.6 and a rewritten example `RobotPlayer.java`. `backend/README.md` records provenance (#1, 2026-11-05).

### Changed

- `launcher.py run` now runs matches inside the sandbox with the limits profile **by default** and stops the Java server shortly after the runner dies. The JSON summary gains `classification`, `loser`, `winner_by_forfeit`, `violation`, `usage`, `sandbox` and `limits_profile`. `--no-sandbox` and `--no-limits` exist for development and measurement only.
- Jira/requirement ID scheme: PRD scope items renumbered from the duplicate `BIO-101..110`, `BIO-201..208`, `BIO-301..305` to `BIO-REQ-01..23`; PRD and test plan bumped to v1.1, and test-plan Jira references now point only at defined task keys or epic IDs (#1, 2026-11-05).

### Removed

- Java bot support (CN-002): the Java example bot `src/examplefuncsplayer/RobotPlayer.java`, the Java placeholder test, the Java defaults in `gradle.properties`, and the Java options of the launcher. The Java engine server is the game engine and stays.
- Agent and skill files (`.claude/skills/`, `.claude/agents/`, `.agents/`, `skills-lock.json`) are no longer tracked by git; the files stay on each developer's machine. Reinstall locally with the install commands recorded in `handoff.md` (#4, 2026-11-24).

### Known issues

- The engine package officially supports only Python 3.12 (`Requires-Python <3.13`). Python 3.12 to 3.15 pass our tests through `runner_entry.py`; this is unsupported by the engine's authors and was tested on Linux x86_64 only.
- The engine's bot sandbox allows `open`, attribute-walk escapes and infinite loops; it offers no wall-clock or CPU limit for pure Python code. The validator only warns about them (same policy as Battlecode). The launcher's guard and sandbox contain these on the host, but both teams still share one process, the numeric limits are unapproved, and there is no seccomp or cgroup layer (`docs/TECHNICAL_DOCUMENTATION.md` section 3.6).
- The Battlecode Java engine declares no license; written confirmation is needed from the Battlecode team (`docs/LICENSING.md`).
- The scaffold's Gradle task for Python bots fails on Linux as shipped (wrong `python3` from `PATH`; `--new-process` start-up deadlock; missing class directory now that Java bots are gone). Use the launcher.
- The only automated test is a placeholder (`1 + 1`); the scaffold's Python `verify` checks only for the text `def turn():`.
