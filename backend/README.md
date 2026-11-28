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
- `submission_check/` — upload check: static check, then a trial match on both sides; decides whether a `bot.py` may become active
- `submission_registry/` — versions, validation history, active version, deadline lock and access rules for submissions (library; `docs/CHANGE_NOTICES.md` CN-016)
- `services/` — interim configured worker, roster-aware maintenance, email and alert processes; systemd template and real-process lifecycle test ([README](services/README.md), CN-027). No production deployment/provider/image is supplied.
- `webapp/` — Django/DRF/PostgreSQL feature API, current session/roster/assignment scope, analytics, submissions, disputes, recipient notification/preferences adapter and Admin operations ([README](webapp/README.md), CN-028/030). Notification state remains in the shared JSON store.
- `submission_bundle/` — bounded flat Python ZIPs, native module checks, curated source snapshots and complete integrity binding ([README](submission_bundle/README.md), CN-028).
- `live_view/` — transport-only numeric board adapter for the existing engine; no raw streaming listener ([README](live_view/README.md), CN-028).
- `work_queue/` — durable job queue and a worker process outside the web process: runs the upload check and tournament rounds, with leases, retry and dead-job incidents (`docs/CHANGE_NOTICES.md` CN-017)
- `tournament_flow/` — the steps that join registry, queue, pins, bracket and round: upload queues its check, pins then draw after the deadline, round start re-hashes the pinned bots, housekeeping (`docs/CHANGE_NOTICES.md` CN-018)
- `tournaments/` — the tournament record and its rules: approval, rejection, two deadlines with history, edits frozen by deadline, Admin extension and emergency override (each with its notice), archive, delete, role-based visibility, and `scheduler.tick` that draws the bracket at the submission deadline, from the roster when given `registration=` (`docs/CHANGE_NOTICES.md` CN-019, CN-021).
- `registration/` — the official roster, one single-use invitation code per participant, claiming a place with email and code (wrong attempts consume nothing and are limited), the lock after registration, and the participant `Actor` (teams, captain-of) for the submission registry (`docs/CHANGE_NOTICES.md` CN-020).
- `notifications/` — dashboard notifications (always created), the email preference, fixed templates for the major events and an email outbox with leases, retry and give-up; the email provider is passed in (`docs/CHANGE_NOTICES.md` CN-022).
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

The **Backend unit matrix** workflow installs the Python families listed in
`match_runner/versions.lock.json`, creates the primary launcher environment
and runs `backend/run_tests.py --matrix` on Ubuntu 24.04. Each run reports
the exact interpreter versions. See [the workflow](../.github/workflows/backend-units.yml).

- The scaffold's `run.py` requires Python exactly 3.12 and is not used by the
  match launcher, which runs the engine on Python 3.12 to 3.15
  (`match_runner/README.md`, `docs/CHANGE_NOTICES.md` CN-001).
- Generated/local directories (`.venv`, `.gradle`, `build`, `client`, `matches`,
  `.temp`) are git-ignored and recreated by the scaffold tooling. `backend/.venvs/`
  and `backend/.cache/` (created by `match_runner/setup_env.py`) are git-ignored too.
