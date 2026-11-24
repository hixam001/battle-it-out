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
