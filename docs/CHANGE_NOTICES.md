# Change notices

Decisions from the owner that change or narrow what the requirement documents (PRD, SRD, TEST_PLAN, APP_FLOW) say. The original text of those documents is left as written; each carries a pointer to this file. Remove a notice here only when the requirement documents themselves are revised.

## CN-001 — Python runtime: latest stable CPython (2026-11-24)

- **Owner instruction:** the platform must run on the latest Python version.
- **Replaces:** the "Python 3.13" target (PRD, SRD-003, TEST_PLAN TC-01, APP_FLOW FLOW-01). 3.13 stays in the tested matrix, so every statement of the form "Python 3.13 compatibility is verified" can still be satisfied.
- **What "latest" meant on 2026-11-24:** `uv python list` offered 3.15.2 as the newest stable release (3.16.0a2 is an alpha and was not used). Primary runtime: **3.15.2**. Also tested: 3.14.10, 3.13.18, 3.12.15.
- **Evidence:** `docs/TECHNICAL_DOCUMENTATION.md` section 3.5 (test matrix, 2026-11-24, Linux x86_64 only).
- **Caveat that matters:** the official engine package declares `Requires-Python >=3.12,<3.13` and its own entry point rejects every Python except 3.12. The project runs it on newer versions through its own entry point (`backend/match_runner/runner_entry.py`), without modifying the package. The engine authors do not support this; compatibility is only what our tests show. Re-run the matrix whenever the engine package or the Python version changes.
- **Still open:** DEC-03 (exact patch version and OS matrix) needs the owner's confirmation of 3.15.2 and of Linux x86_64 as the only tested platform.

## CN-002 — Java bots removed (2026-11-24)

- **Owner instruction:** remove Java support, as the requirements say participants submit Python only.
- **What was removed:** the Java example bot (`src/examplefuncsplayer/RobotPlayer.java`), the Java placeholder test, the Java defaults in `gradle.properties`, and every Java-bot option of the match launcher.
- **What stays:** the Java *engine server* (`battlecode.server.Main` from the official engine jar). The requirement is to use the existing Battlecode engine, and that engine is a Java program; Python bots are played through it. Java 21 and Gradle remain prerequisites for running matches.
- **Replaces:** "Run Java local baseline" in TEST_PLAN TC-01 and its checklist item "Java baseline still runs", and step 8 and an edge case in APP_FLOW FLOW-01. The baseline is now a Python-vs-Python match of the example bot: `examplefuncsplayer_py (A) wins (round 1290)`, replay SHA-256 `a08779089a8cc2b714bae4394502e4b4f34231c8ffd0fb4037b5ef6feaaac301`.
- **Consequence found while doing it:** without a Java class directory the engine server reports `Error while loading player ...` and the game runs to round 2000 with no bots. The launcher therefore gives the server an empty class directory. Running `./gradlew runLocal` by hand needs the same (`-PclassLocationA=<empty dir> -PclassLocationB=<empty dir>`).

## CN-003 — Project license: AGPL-3.0, same as the Battlecode scaffold (2026-11-24)

- **Owner instruction:** use the same license as Battlecode, to comply with the Battlecode licenses.
- **Decision implemented:** the project is licensed **AGPL-3.0-only** (root `LICENSE`, SPDX headers on our source files). Battlecode itself is mixed: the scaffold is AGPL-3.0, the Python engine package declares MIT, and the Java engine declares **no license** (see `LICENSING.md`). AGPL-3.0 is the only Battlecode license that governs code this project copies and modifies.
- **Resolves:** PROJECT_PLAN R5 and ARCHITECTURE A-05 / ADR-10 ("project license", previously open).
- **Obligations to carry:** modification notices for scaffold changes (section 5a), source offer to network users (section 13, for the future website). Details and open items (copyright holder, participant terms, **the unlicensed Java engine**) in `LICENSING.md`. Not legal advice.

## CN-004 — Bot policy: the engine's own rules (2026-11-24)

- **Owner instruction:** use the same policy as Battlecode.
- **Decision implemented:** bots may import only `random`, `math`, `enum` and `battlecode26`, and may use only the builtins and globals the engine gives them; single file `bot.py` with `turn()`. Written down in `BOT_POLICY.md`, generated into `backend/bot_validator/policy.json`, enforced early by the validator, and checked against the engine by tests.
- **Replaces:** PRD "Standard library and preinstalled third-party libraries may be used" and SRD-005. Those statements describe something the engine does not allow.
- **Not changed:** what the engine permits but the platform must contain (`open`, attribute walks, infinite loops) stays allowed by the *policy* and is reported as warnings. It is handled by isolation and limits (BIO-203/204, DEC-04), not by this policy. Making those rejections would need a new change notice.
- **Still open:** the numeric limits (DEC-04) and the upload size cap.

