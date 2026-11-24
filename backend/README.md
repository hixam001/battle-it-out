# Backend

Home of the Battle It Out execution foundation and, later, the web backend.

## Layout

- `battlecode26-scaffold/` — the Battlecode 2026 Java/Python scaffold, vendored
  into this repository. It is the existing game engine integration the rest of
  the backend is built on (the project does not replace the Battlecode engine).
  Planned additions (bot validator, runner/sandbox, match orchestration, API)
  are added next to it under `backend/`, following the epics in `docs/PRD.md`.
- `bot_validator/` — static check of a `bot.py` against the engine's own bot policy
  (`policy.json` generated from the engine; see its `README.md` and
  `docs/BOT_POLICY.md`).
- `match_runner/` — command-line match launcher for Python bots on Python 3.12
  to 3.15, with pinned versions (`versions.lock.json`), environment setup, a
  resource guard and bubblewrap sandbox (limits are provisional), and tests.
- `match_orchestrator/` — match jobs on top of the launcher: platform retry
  with a cap, Admin incident, exactly-once result, tie-break maps and the 50/50 coin flip, bracket with byes and an Organizer-started round runner (library; `docs/CHANGE_NOTICES.md` CN-009, CN-010, CN-011).
  See its `README.md`.

## Provenance of `battlecode26-scaffold/`

- Upstream: https://github.com/battlecode/battlecode26-scaffold
- Imported from upstream commit `f69e2ab872a0061c9d4a684aa1dd798a0829da85`
  ("Bump engine version to 1.2.4").
- The upstream `.git` history is not kept here; the scaffold is now tracked by
  this repository. Upstream updates must be merged manually.
- Local changes made before import (present in the first commit):
  - `engine_version.txt`: `1.2.4` -> `1.2.6` (written by `./gradlew update`).
  - `src/examplefuncsplayer/RobotPlayer.java`: rewritten example bot.
- Local changes made later (2026-11-24, `docs/CHANGE_NOTICES.md` CN-002): the Java
  example bot and the Java placeholder test were removed, and `gradle.properties`
  defaults now name the Python example (`examplefuncsplayer_py`, `python`).

## Local setup notes

- The scaffold's `run.py` requires Python exactly 3.12 and is not used by the
  match launcher, which runs the engine on Python 3.12 to 3.15
  (`match_runner/README.md`, `docs/CHANGE_NOTICES.md` CN-001).
- Generated/local directories (`.venv`, `.gradle`, `build`, `client`, `matches`,
  `.temp`) are git-ignored and recreated by the scaffold tooling. `backend/.venvs/`
  and `backend/.cache/` (created by `match_runner/setup_env.py`) are git-ignored too.
