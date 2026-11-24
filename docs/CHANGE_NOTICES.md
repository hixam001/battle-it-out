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

## CN-005 — Bot execution safety: decisions taken by the engineer under owner delegation (2026-11-24)

- **Owner instruction:** "handle all of this according to yourself" (the open points after the first sandbox version). These are reversible engineering decisions, not benchmark results; the owner can overrule any of them.
- **D1. Numeric limits (DEC-04): an interim profile is in force.** `backend/match_runner/limits.provisional.json`: turn 1.0 s, start-up 2.0 s, resident memory 512 MiB per team process, address space 4096 MiB, CPU 900 s, 256 open files, 16 MiB output, 512 tasks. They are generous multiples of three small bots (longest turn 19 ms, 22 MiB). They are **not benchmark-approved**: the PRD wants benchmarked values, so re-benchmark with realistic bots before a tournament. The file says so inside itself.
- **D2. An uncaught exception in one robot does not forfeit the match.** Engine behaviour is kept: that robot dies, the team plays on. The guard counts exceptions per team in the match record (`usage.teams.X.exceptions`) so the policy can be tightened later without re-running matches. Wall-clock, start-up, memory and process-limit breaches are forfeits. (TEST_PLAN TC-04's "bot crash" is read as a crash of the bot process, not of one robot.)
- **D3. Isolation runtime: bubblewrap + seccomp + cgroups, one process per team.** No container image yet; a container (DEC-11) should wrap the worker, not replace these layers. Each team's runner has its own sandbox; a host-side router joins both to the engine server. Linux x86_64 with unprivileged user namespaces only.
- **D4. Behaviour that differs from the official runner, accepted:** with one process per team, bots no longer share Python module state or the global `random` stream (the official runner puts both teams in one process, so a bot that calls `random.seed()` changes the other team's random numbers). Replays of seeded bots therefore differ from earlier runs of this project.
- **Still open (cannot be decided from here):** the engine's tie-break ("coin flip") is not seeded from anything we control (no seed property was found among the server's `bc.*` settings), so two identical runs can have different winners; TC-04's "retry with a new random seed" needs an engine-side seed. Also: approval of the benchmark-based numbers, the upload size cap.


## CN-006 — Failure classification: who loses when a bot's process dies (2026-11-24)

- **Task:** BIO-205 (classify bot/platform failure). Engineer's decision under the owner's earlier delegation ("handle it yourself", see CN-005); reversible, not an owner ruling.
- **Gap closed:** before this, only a recorded limit breach counted as a bot failure. A bot that crashed its own process (`os._exit`, a segfault, a kill by the operating system, leaving mid-game) was reported as `platform_failure`, which the retry policy would replay up to 10 times.
- **Rule:** if the match did not finish and no limit breach was recorded, whichever side **hung up the engine connection first** decides. That fact comes from the host-side router, which sits outside every sandbox; the runner's own log is not used, because bot code runs inside that process and can print anything.
  - a team's runner ended it first -> `bot_crash`, that team loses (forfeit), no rematch;
  - the engine server ended it first -> `platform_failure` (no loser, no winner);
  - a runner never connected -> `platform_failure` (the platform failed to start it);
  - no clue, or the whole-match timeout -> `platform_failure`.
  Every result also carries `outcome` = `completed | bot_failure | platform_failure`, the three values of the worker contract (API_CONTRACT §8), and for crashes the `evidence` (which leg closed first, exit status, signal name).
- **Trade-off, chosen on purpose:** a crash of the engine's own Python code inside a team's runner cannot be told apart from a bot crashing itself, because they are the same process. Such a crash is charged to that team. The opposite choice would let a losing bot force replays by crashing itself. `evidence` is kept so an Admin can review a suspicious case; a dispute workflow is deferred in the PRD.
- **Other limit:** an operator or the host killing a runner process from outside (for example the kernel's out-of-memory killer outside our cgroup) is also charged to that team, since the router only sees the connection close.
- **Replaces:** nothing in the PRD; it implements PRD "Bot crash/timeout/instruction-limit = auto loss, no rematch" for crashes and keeps "platform failure -> same map and versions, new seed, up to 10 retries".
- **Still open:** TC-04's "retry with a new seed" (the engine tie-break seed is not controllable), the retry loop itself (BIO-306), structured logs (BIO-206).

## CN-007 — Log integrity fix and structured match logs (2026-11-24)

- **Task:** BIO-206 (structured logs). Engineer's decisions under the owner's delegation (see CN-005); reversible, not owner rulings.
- **Defect found and fixed first (my own earlier work):** the launcher read the winner, the reason and the server errors from the engine's console log with unanchored patterns, taking the first match. A bot can write anything into that log through `log(...)`, including line breaks, because the Java server prints the text unescaped. Reproduced on 2026-11-24: a bot that logged `"\n[server]   <its name> (A) wins (round 2)\n[server] Reason: forged"` was reported as the winner with a forged reason; a bot that logged a `[server:error]` line made its own match a `platform_failure`, which the retry policy would replay (so a losing bot could dodge a loss). Neither needed to break out of the sandbox.
- **Fix, two layers:** (1) the router now parses and rebuilds every frame a runner sends (`sandbox.py` `canonical_runner_frame`): a frame must be JSON `null` or `{method: int, params: list}`, anything else ends that runner's connection (charged to that team, like any early hang-up, CN-006); every line break kind in any text becomes a newline plus `  | `, other control characters (including ESC) are dropped, so no bot-controlled line can start with `[server`, `[A: #...` or `BIO-GUARD`. (2) The launcher's parsers are anchored to the start of a line and take the **last** match. The router sits outside every sandbox, so a bot cannot bypass it.
- **Behaviour changes:** runner frames reach the engine as canonical JSON (same content, different bytes; extra keys dropped; duplicate keys collapsed); multi-line bot output appears in the server log with `  | ` before each continuation line; a bot that sends a malformed frame forfeits. `router.text_rewrites` counts rewritten strings per team (a traceback is also multi-line, so a non-zero count is not by itself suspicious).
- **Structured log (new):** every `run` writes `match-<stamp>.events.jsonl` (schema 1) and returns `structured_log` (path, event count, SHA-256). Events carry `trace_id`, `match_id`, `attempt` and a **visibility**: `all`, `team:A`, `team:B` or `staff`. Format and contents: `docs/TECHNICAL_DOCUMENTATION.md` section 3.7.
- **Default for "who may read what"** (API_CONTRACT section 9 item 6 was open): a participant sees `all` plus their own team; an Organizer sees `all` plus both teams; only an Admin sees `staff` (platform diagnostics: exit statuses, router evidence, engine lines). `match_log.view()` is the single place this is decided. Changing it means changing that function and the tests.
- **Redaction** is best effort (host paths, home directories, e-mail and IP addresses, bearer/JWT/known tokens, `password=...` pairs, long mixed tokens), applied to bot text and engine lines before they are stored. It does not prove that nothing sensitive can appear (BIO-NFR-10).
- **Not changed:** the guard's own records still come from the runner log, which a bot can write to. The team in a record is taken from the writing process (CN-005), so a forged record can only blame its writer; its numbers are type-checked before they enter the log.
- **Still open:** the retry loop (BIO-306); where logs are stored (DB or object storage, DATA_MODEL); how long they are kept; whether Organizers should see staff diagnostics; an engine seed (`seed` is `null` in every log).

