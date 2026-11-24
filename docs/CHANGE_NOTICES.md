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

## CN-008 — Router turn checks, a host-side response deadline, hardened validator (2026-11-24)

- **Task:** self-review of `backend/match_runner` (`docs/SECURITY_REVIEW.md`, SR-01 to SR-06). Engineer's decisions under the owner's delegation (see CN-005).
- **Owner confirmation (2026-11-24):** the owner confirmed that these rules stay ("The rules stay"): the sender is charged for protocol violations and for a silent runner, and the router's response deadline stands. The deadline's numeric slack (2 s plus twice the limit) was not discussed and remains tied to the benchmark (DEC-04). Still reversible by a later change notice.
- **Defects found in my own earlier work and fixed** (each reproduced in a real sandboxed match first):
  - **SR-01 (High):** a bot could send engine calls during the other team's turn; the engine server read them as the other team's robot. Results could be manipulated (2 of 5 runs an A win in round 1, 2 of 5 a forfeit charged to the victim). The router now accepts a call only from the runner whose turn it is, and a null only as the answer to a notice it forwarded; a frame that breaks this is dropped and charged to the sender.
  - **SR-02 (Medium):** a bot could freeze its own process, and the in-process guard with it; the match then ended as a `platform_failure` after the whole-match timeout (a free replay). The router now has its own clock: a runner silent for more than `2 x max(turn, start-up limit) + 2 s` after being handed work is charged (`runner_unresponsive`).
  - **SR-03 (Medium):** an engine method number outside the engine's range crashed the Java server and was reported as a `platform_failure`. The router now refuses it and charges the sender.
  - **SR-04 (Medium, latent) and SR-05 (Low):** the validator reads only regular files (no symlinks, FIFOs, devices), at most 2 MiB, and reports unparseable or too-deep source as `E-SYNTAX`; team folder names must match `[A-Za-z0-9][A-Za-z0-9._-]{0,63}`.
- **Behaviour changes:** new classification kinds under `bot_crash`: `protocol_violation` and `runner_unresponsive` (outcome `bot_failure`, the other team wins by forfeit, no rematch); public log wording per kind; `launcher.py` passes a deadline to the router whenever a limits profile is in force; validator results for hostile files change from a crash or hang to `E-FILES`, `E-SIZE` or `E-SYNTAX`; a normal match's `first_end` leg is no longer asserted by the tests (it is a race once `end_game` is sent; it never affected the result).
- **Trade-offs chosen on purpose:** the deadline slack (2 s plus twice the limit) is a guess and a heavily loaded host could charge a healthy runner; the 2 MiB validator ceiling is a safety limit for the validator itself, not the upload cap (`max_bytes` stays an owner decision); a frame with a valid method number and bad parameters is still attributed by which side closed the connection first.
- **Not fixed:** SR-06 (server-side Java exceptions are not counted as server errors) and the parameter-type residual in SR-03. A human or third-party review is still open.
- **Replaces:** nothing in the PRD. It makes CN-006's rule ("a bot cannot dodge a loss by breaking the match") true for three more ways of breaking it.

## CN-009 — Match jobs with platform retry and an Admin incident (2026-11-24)

- **Task:** BIO-306 and the core of BIO-301/302, in `backend/match_orchestrator/` (library only; no service, queue, API or database). Engineer's decisions under the owner's delegation (see CN-005); every item below is reversible by a later notice.
- **D1. Retry cap = 10 attempts in total** (the first plus nine retries), the DEC-05 recommendation. SRD-011 says "retry up to 10 times", which can also mean 11 attempts; the code takes `max_attempts` as a parameter (1 to 100). Only platform failures count; a bot failure ends the match.
- **D2. State after the cap is called `paused`** (DATA_MODEL left the name and the resume authority open). An incident `retry_cap_reached` is stored and the alert function is called. `resume_paused(match, actor, extra_attempts)` exists as a mechanism; **who may call it is not decided here**.
- **D3. A worker that disappears counts as a platform failure** (`worker_lost`) once its lease expires, and counts towards the cap, so a poison match cannot loop forever.
- **D4. A launcher answer is accepted only if it is consistent.** A winner without `ok: true` (non-zero exit, timeout) is retried instead of published, because the replay may be incomplete. Anything malformed is a platform failure; the platform never invents a winner.
- **D5. Configuration errors do not retry.** A missing bot folder or failed version check pauses the match at once (`configuration_error`). Port busy and host-lock timeout stay retryable.
- **D6. A match is played with the exact submission versions stored when it was created**; folders are `bots_dir/<submission reference>`, which an upload service must make immutable.
- **Behaviour change in `backend/match_runner`:** `launcher.PortBusyError` (a subclass of `LauncherError`) is raised for a busy loopback port; nothing else changed.
- **Not met, and why:** TC-04 requires "a new random seed" per retry. The engine's tie-break seed cannot be controlled (CN-005), so attempts record `seed: null` and a retry replays the same inputs. The orchestrator already passes a seed to the run function when one is supplied (`seed_fn`), so this needs only an engine-side change. The Admin alert has no real channel yet (notifications are a later epic): it is a function parameter, and an undelivered incident stays pending.
- **Still open:** DEC-11 (the JSON file store is a stand-in), BIO-303/304/305, who may resume a paused match, lease length versus match length (no heartbeat), and an independent review.
- **Replaces:** nothing in the PRD. It implements SRD-010/011, DATA_MODEL "Match" and the idempotency rule for worker jobs (API_CONTRACT section 8).

## CN-010 — Tie-break maps and the 50/50 coin flip (2026-11-24)

- **Task:** BIO-304 (PRD 6.4, SCN-03, TEST_PLAN TC-05), in `backend/match_orchestrator/tiebreak.py` (library only). Engineer's decisions under the owner's delegation (see CN-005); every item is reversible by a later notice.
- **Found in the engine source first:** the engine has no tie result. If points, robots alive and cheese are equal it calls an unseeded `Math.random()` inside the game and still names a winner, printing `The winning team won arbitrarily (coin flip).` (`battlecode.server.Server`, `DominationFactor.WON_BY_DUBIOUS_REASONS`). Its other tie-breakers (points, then robots alive, then cheese) are part of the game's own rules.
- **D1. A game is TIED when, and only when, the engine's reason line is that coin flip.** The engine's pick is stored (`engine_pick_ignored`) and never used. Games decided by points, robots alive, cheese, destroyed rat kings or resignation are decided. The line is an engine line that the launcher parses anchored (CN-007); bots cannot forge it. If the PRD means something else by "tie" (for example any game decided by a secondary tie-breaker), change `_absorb` only.
- **D2. A match is a series of games.** Game 0 is the scheduled map. If it is tied: normal stage = 1 predefined tie-break map, final = 3, played one after the other on the same teams and the same submission versions. The maps are fixed when the series is created. Each game is an ordinary match, so it has its own platform retry (cap per game), incident and exactly-once handling.
- **D3. Final stage: all three maps are always played** (PRD: "three maps automatically and sequentially"), even if two already decide it, so all three replays exist. The winner is the team with more tie-break map wins. A tie-break map that is tied again counts for nobody. Equal wins (including 0-0) go to the coin flip. The first game's result does not count once it is tied.
- **D4. A bot failure in any game ends the series at once** and the other team wins (`bot_forfeit`); remaining tie-break maps are not played (PRD: no rematch, opponent advances).
- **D5. The coin flip** is drawn once, by `secrets.randbelow(2)` (operating-system randomness), inside the same store transaction that records it, only when the series has no flip yet and is not finished. It is never redrawn: repeated jobs, second workers and restarts read the stored flip. A coin function that returns anything but `A` or `B` records nothing. The record (`id`, time, side, team, both tied teams, the games played, tie-break wins, `probability_each: 0.5`, `rerolls_allowed: false`) and the series `history` are the audit trail; `public_view` shows the flip without host paths, hashes or bot details.
- **D6. A game result needs the engine's reason line** to be accepted inside a series (otherwise the attempt is a platform failure, `missing_reason`, and is retried), because deciding "win or tie" without it would be a guess. Standalone matches are unchanged.
- **D7. Games of a series are never advanced on their own.** `take_advancement` returns nothing for them; `take_series_advancement` hands the series result to the bracket once.
- **Tested for real:** the example bot against itself on `DefaultSmall` ties by the engine's coin flip at round 1310 every time (symmetric position), so a real final-stage series plays four games and ends in one coin flip (3 of 3 probes, plus the integration test).
- **Not done:** where the tie-break maps are stored and chosen (TournamentMap, tournament setup), the qualification-cutoff draw (separate rule, needs the draw inputs, DEC-14), the screen and API that show the flip, the Admin audit log (the series `history` is only the source), who may resume a paused game, and the engine seed (TC-04). No independent review.
- **Replaces:** nothing in the PRD. It implements PRD 6.4 tie handling and SCN-03 on top of CN-009.
