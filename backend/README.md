# Backend

Home of the Battle It Out execution foundation and, later, the web backend.

## Layout

- `battlecode26-scaffold/` — the Battlecode 2026 Java/Python scaffold, vendored
  into this repository. It is the existing game engine integration the rest of
  the backend is built on (the project does not replace the Battlecode engine).
  Planned additions (bot validator, runner/sandbox, match orchestration, API)
  are added next to it under `backend/`, following the epics in `docs/PRD.md`.

## Provenance of `battlecode26-scaffold/`

- Upstream: https://github.com/battlecode/battlecode26-scaffold
- Imported from upstream commit `f69e2ab872a0061c9d4a684aa1dd798a0829da85`
  ("Bump engine version to 1.2.4").
- The upstream `.git` history is not kept here; the scaffold is now tracked by
  this repository. Upstream updates must be merged manually.
- Local changes made before import (present in the first commit):
  - `engine_version.txt`: `1.2.4` -> `1.2.6` (written by `./gradlew update`).
  - `src/examplefuncsplayer/RobotPlayer.java`: rewritten example bot.

## Local setup notes

- `run.py` currently requires Python exactly 3.12 (project target is 3.13; not
  yet verified, see `handoff.md`).
- Generated/local directories (`.venv`, `.gradle`, `build`, `client`, `matches`,
  `.temp`) are git-ignored and recreated by the scaffold tooling.
