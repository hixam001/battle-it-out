# Security review of the match runner (SR-01 to SR-06)

- **Date:** 2026-11-24. **Branch:** `BIO-EPIC-02-match-runner-security-review`. **Change notice:** CN-008.
- **Scope:** `backend/match_runner/` (launcher, sandbox and router, guard, runner entry, structured log) and `backend/bot_validator/validator.py`, at the commit that followed BIO-206.
- **Method:** reading the source and the installed engine package (`battlecode26` 1.2.2 from release 1.2.6), then confirming each suspicion with a hostile test bot in a real sandboxed match on this machine (Linux x86_64, bubblewrap, Python 3.15.2). Nothing outside this machine was touched. Guidance-mode review with the repository's `security-audit` skill; the skill's full six-phase workflow with report files was **not** run.
- **Not independent.** The reviewer is the same assistant that wrote most of this code. Treat this as a self-review that found real defects, not as the independent review the plan calls for (handoff step 1(a) stays open for a human or third party).

## Summary

| ID | Finding | Severity | Status |
|---|---|---|---|
| SR-01 | A bot could send engine calls while it was the *other* team's turn; the engine server read them as the other team's robot talking | **High** | Fixed and tested |
| SR-02 | A bot could freeze its own process (and the guard thread with it); the match then waited out the whole timeout and was labelled `platform_failure` (a free replay) | Medium | Fixed and tested |
| SR-03 | A bot could send an engine method number that does not exist; the Java server crashed and the match was labelled `platform_failure` (a free replay) | Medium | Fixed and tested |
| SR-04 | The validator, which runs on the host on uploaded files, followed symlinks, blocked on FIFOs, read any size into memory and crashed on deeply nested source | Medium (latent: no upload endpoint exists yet) | Fixed and tested |
| SR-05 | Team folder names were not checked, so `../x` reached the bind-mount and Gradle arguments | Low | Fixed and tested |
| SR-06 | A Java exception printed by the engine server is not counted as a server error, so a match that finished after one is `normal` | Informational | Open (residual) |

Severity follows the skill's anchors; likelihood and impact are stated for each finding. SR-01 is rated High because it changes who wins a match. SR-02 and SR-03 are Medium because they need the retry loop (BIO-306, not built) to turn into repeated free replays, and the PRD's retry cap and Admin alert limit the damage.

## SR-01: out-of-turn frames reach the server as the other team (High)

- **Boundary:** team A's sandboxed process versus team B. The engine server has one connection for both teams and cannot tell the two runners apart; only the router can.
- **Cause:** the router checked the *shape* of a runner frame (CN-007) but not *whose turn it was*. Bot code can reach the engine's socket client (`battlecode26.crossplay._client`) because the engine `exec()`s bot source without RestrictedPython, and can start a thread (`threading` through the attribute walk), so a thread can send at any moment.
- **Reproduction (before the fix, real sandboxed matches, hostile bot as team A, the example bot as team B):** in 5 runs the server read A's `RESIGN` call as B's: 2 runs were recorded `normal`, **A wins in round 1**; 2 runs were `bot_crash` with **B (the victim) the loser**; 1 was `platform_failure`. The Java server printed `Expected null response, got: {"method":99,"params":[]}` while spawning B's robot. The control (two example bots) ended `normal` in round 1310 every time. Side effect: text sent out of turn is printed with the other team's `[B: #id@round]` prefix, so a bot could also write into the victim's visible log.
- **Impact:** a participant can manipulate match results against a team that did nothing wrong; the victim could be charged a forfeit. This defeats the isolation CN-005 D3 was built for.
- **Fix (CN-008):** `sandbox.py` `check_turn`. A call (anything but null) is accepted only from the runner whose turn it is; a null is accepted only when the router has forwarded a `spawn_bot` or `destroy_bot` notice to that runner and has not yet seen the answer. A frame that breaks the rule is not forwarded, ends that runner's connection and is charged to the sender (the router knows which socket it came from; a bot cannot forge that).
- **After the fix:** 3 of 3 runs `bot_crash`, loser A, `kind: protocol_violation`, about 2 s; B untouched.
- **Residual:** within its own turn a bot may still send any valid call, which is the engine's API and not a boundary.
- **Follow-up (CN-025, 2026-11-25):** "3 of 3 runs" was too small a sample. Re-running the suite on Python 3.13 to 3.15 showed an intermittent case: the router refused the frame and recorded the violation, but the engine had already logged the game as finished, so `classify` said `normal` and the hostile team won. Now a protocol violation seen by the router is charged to the sender whether or not a result was logged. 120 real matches since then: no failure.

## SR-02: a bot can freeze its own guard (Medium)

- **Cause:** the guard's watchdog thread lives in the same process as the bot. `os.kill(os.getpid(), SIGSTOP)` (reachable through the attribute walk; the seccomp list does not deny `kill`) stops every thread, including the watchdog. A C call that holds the GIL would do the same. The only remaining clock was the whole-match timeout (1800 s by default), and the classifier then reported `platform_failure`, "no loser, retryable" (CN-006 rule 2).
- **Reproduction (before):** a bot that stops itself in round 3: the match ran until the timeout (40 s in the test), `platform_failure`, `timed_out: true`, no loser.
- **Impact:** a losing bot can avoid its loss and cost the platform one full timeout per attempt; with up to 10 retries that is up to about 5 hours of one worker per match.
- **Fix (CN-008):** a clock outside the sandbox. The router records when it hands work to a runner (`spawn_bot`, `start_turn`, a reply to a call, a `destroy_bot` notice) and when the runner answers. A runner that stays silent longer than `2 x max(turn limit, start-up limit) + 2 s` (6 s with the interim profile) is ended and charged (`kind: runner_unresponsive`). The deadline is given by the launcher from the limits profile; without a profile there is none.
- **After the fix:** `bot_crash`, loser A, 8.8 s.
- **Trade-off:** on a badly overloaded host a healthy runner could miss the deadline and be charged. The slack is a guess (DEC-04, same status as the other numbers); it should be set from the benchmark.

## SR-03: an unknown method number crashes the server (Medium)

- **Reproduction (before):** a bot sends `{"method": 9999, "params": []}` in its own turn. The Java server throws `Protocol error: Invalid JSON received from client` and closes the connection first, so the router's evidence said "server ended it first": `platform_failure`, no loser. Two other malformed-parameter frames were charged to the sender, but only because the runner happened to close first.
- **Fix (CN-008):** the router refuses method numbers outside the engine's range (`MIN_METHOD`..`MAX_METHOD` = 1..107) and charges the sender. A test compares the range with the installed engine so a package update cannot silently widen it.
- **Residual (not verified as a defect):** a frame with a valid method number but bad parameters (for example `RC_MOVE` with a string) makes the server throw inside that robot's thread. In two runs the sender was charged, because its runner closed first; which side closes first is a race, so a `platform_failure` is possible. A robust fix needs the router to understand parameter types, or the classifier to read the server's `Exception in thread "<bot>.RobotPlayer #id"` line (see SR-06). Left open on purpose: it would encode engine details that change between engine versions.

## SR-04: the validator on hostile files (Medium, latent)

- **Cause:** `validate_path` read `bot.py` with `Path.read_bytes()`: it followed symlinks, blocked on a FIFO, read any size into memory, and `ast.parse` raised an uncaught `MemoryError` on deeply nested source. A directory containing a symlink named `bot.py` to `.` also recursed.
- **Reproduction (before, with a 2 GB memory limit and a 20 s timeout):** symlink to `/dev/zero`: `MemoryError`; FIFO: no result after 20 s; deeply nested expression: traceback; a 300 MB file: accepted.
- **Impact:** whoever runs the validator on the host (the future upload endpoint) could be stalled or run out of memory by one participant. No endpoint exists yet, so nothing is exposed today.
- **Fix (CN-008):** the file is opened with `O_NOFOLLOW | O_NONBLOCK`, must be a regular file, and at most `HARD_READ_LIMIT` (2 MiB) is read; a link, a folder or a special file named `bot.py` is `E-FILES`; too large is `E-SIZE`; unparseable or too deep is `E-SYNTAX` instead of a crash. The 2 MiB figure is a safety ceiling for the validator's own memory, **not** the product's upload limit (still an owner decision).
- **Still advisable:** run the validator inside the same sandbox as the bots (it is stdlib only) and with a process memory limit.

## SR-05: team folder names (Low)

`run_match` accepted any string as a team folder name. A name such as `../x` would have been joined to the bots directory and bind-mounted into the sandbox, and was passed to Gradle. The launcher now accepts only `[A-Za-z0-9][A-Za-z0-9._-]{0,63}`. Names should still be generated by the platform (not typed by users) when the orchestration layer is built.

## SR-06: server-side Java exceptions are not "server errors" (Informational, open)

The launcher counts only `[server:error]` / `[server:warning]` lines. The Java server prints an uncaught exception in a robot thread as a plain `Exception in thread ...` line, so a match that finished after one is `normal`. With SR-01 and SR-03 fixed a bot can no longer cause these from outside its own turn, but engine faults of that kind are invisible to the classifier. Recommended: treat such a line as evidence in the staff diagnostics and decide with the owner whether it should block a result.

## Reviewed with no finding

- **Sandbox command (`sandbox.py`, `base_args`, `build_command`):** namespaces (user, pid, net, ipc, uts, cgroup), `--cap-drop ALL`, `--clearenv`, `--die-with-parent`, `--new-session`, read-only root, only the team's own bot folder, a size-capped private `/tmp`; no host path other than `/usr`, the venv, the runner folder and the interpreter is mounted. The existing escape probe (host file, host loopback, internet, writes to read-only paths, other team's folder, `ptrace`) still passes.
- **Router sockets:** created in a private temporary directory (mode 0700) and set to 0600; each listener accepts exactly one connection; a runner can only reach its own socket.
- **seccomp program:** the BPF assembly and the denylist were read; behaviour was tested before (BIO-203/204). Not extended in this review.
- **Structured log views (`match_log.py`):** visibility rules, caps and redaction read; no way found for one team's output to appear in the other's view except through SR-01 (now closed).
- **Guard records:** the team in a record is taken from the writing process (CN-005), so a forged record can only blame its writer.

## Not covered

- Kernel and bubblewrap vulnerabilities, other kernels or distributions, non-x86_64, Windows and macOS.
- The Java engine server (trusted code, no source available here).
- A bot that stays inside every limit but behaves badly (for example finishing every turn just under the limit).
- An output-flooding test: one attempt (30 frames of 4 MiB through `log`) was stopped by the turn limit after about a second with no log growth, so the effect is **unverified**; the per-frame cap of 8 MiB and the turn limit bound it.
- Two matches at once, resource exhaustion of the host by many matches, the future web application and API.
- Any human penetration test.

## How to re-run

`BIO_INTEGRATION=1 python3 -m unittest backend.match_runner.tests.test_security_review -v` (26 tests; 3 are real sandboxed matches and need bubblewrap, `ss`, Gradle offline and the primary Python environment). The hostile bots are `backend/match_runner/tests/bots/{oot_py,stop_py,badmethod_py}`.
