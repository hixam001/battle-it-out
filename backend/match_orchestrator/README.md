# match_orchestrator

Drives one match to a final state, with platform retry (BIO-301 core, BIO-306; `docs/CHANGE_NOTICES.md` CN-009). Standard library only. It sits on top of `backend/match_runner` and is **a library, not a service**: nothing starts it yet, there is no queue, no web API and no database.

## What it does

- **Bot failure is a result, not a retry.** A crash, timeout or limit breach (`outcome: bot_failure`) ends the match at once: the other team wins by forfeit, `result_type: bot_forfeit`.
- **Platform failure is retried** with the same map and the same submission versions, up to `max_attempts` (default **10 in total**, DEC-05 recommendation, interim). Waits between attempts grow by 2 s per failure up to 30 s.
- **At the cap** the match becomes `paused`, an incident is stored (`retry_cap_reached`) and the alert function is called. Delivery is at-least-once: an incident whose alert failed stays pending (`alert_error`) and `deliver_alerts` sends it later. An operator can `resume_paused` with more attempts.
- **A result is recorded once.** A duplicate job, a second worker or a late answer from a replaced worker changes nothing. `take_advancement` returns the result to bracket logic exactly once.
- **A worker that disappears is replaced.** Each attempt holds a lease; after it expires the next worker records the lost attempt as a platform failure (`worker_lost`, counted towards the cap) and takes over.
- **An answer is never trusted blindly.** A launcher result that is not a dict, lacks a winner, contradicts itself, or has a winner but did not exit cleanly is a platform failure (`malformed_result`, `unclean_completion`), never an invented result.
- **Retrying cannot help** when a bot folder is missing or the version check fails (`ConfigurationError`): the match is paused at once with a `configuration_error` incident instead of spending ten attempts on the same mistake. A busy engine port or a host lock timeout is a normal, retryable platform failure.

States follow `docs/DATA_MODEL.md`: `scheduled -> queued -> running -> completed`, retries `running -> platform_failed -> retry_queued -> running`, bot failure `running -> bot_forfeit -> completed`. `paused` is **our** name for the state after the cap; the final name and who may resume are open decisions.

## Use

```python
from pathlib import Path
from backend.match_orchestrator import orchestrator as O
from backend.match_orchestrator.store import JsonFileStore
from backend.match_runner import launcher as L

store = JsonFileStore(Path("/var/lib/bio/matches.json"))
O.create_match(store, "match-17", "team-a", "team-b", "DefaultSmall", "sub-a-v3", "sub-b-v1")
run_fn = O.launcher_run_fn(L.DEFAULT_SCAFFOLD, py, bots_dir, out_root, lock_path=Path("/var/lib/bio/host.lock"))
O.run_match_job(store, "match-17", run_fn, alert=notify_admin)     # safe to call twice, or from two workers
result = O.take_advancement(store, "match-17")                       # the result, once; None afterwards
```

`launcher_run_fn` expects one folder per submission version, `bots_dir/<submission reference>/bot.py`, so the same folder is played in every attempt. Output (replay, logs) goes to `out_root/<match id>/attempt-<n>/`. The lease (`lease_seconds`, default 2400 s) must be longer than the launcher timeout (default 1800 s) or a slow healthy match can be taken over; the late worker's answer is then dropped, but the match would have been played twice.

## Files

| File | Purpose |
|---|---|
| `orchestrator.py` | Match and attempt state machine, retry loop, incidents and alerts, host lock, launcher adapter |
| `store.py` | `JsonFileStore`: one JSON file, an exclusive lock across processes, atomic write; a damaged file is an error, never an empty store |
| `tests/test_orchestrator.py` | 34 tests: 30 unit tests with a fake run function, 4 real matches (`BIO_INTEGRATION=1`) |

```bash
backend/.venvs/py3.15/bin/python -m unittest backend.match_orchestrator.tests.test_orchestrator
BIO_INTEGRATION=1 backend/.venvs/py3.15/bin/python -m unittest backend.match_orchestrator.tests.test_orchestrator   # plays 3 real matches, about 13 s
```

## Not covered (and why it matters)

- **A new random seed per retry is not possible yet.** The engine's tie-break seed is not controllable (CN-005). The code passes a seed from an optional `seed_fn` into every attempt and stores it, but the launcher ignores it, and `seed` is `null` in every attempt unless a function is given. TC-04's "new seed" is therefore **not met**; a retry replays the same inputs and may or may not differ in a coin-flip tie.
- **The store is a stand-in.** DEC-11 (database and hosting) is undecided. A JSON file is fine for one host; it does not scale, has no history of old versions and keeps host paths of replays and logs (staff-only). Replace `JsonFileStore` with transactions on the real database; `create_match`, `claim`, `finish` and the rest are written as one transaction each for that purpose.
- **`take_advancement` is only the first guard.** If the caller crashes after taking it and before advancing the bracket, the claim is lost. BIO-303 must make advancement idempotent on the match id.
- **No heartbeat.** A long match that outlives its lease is taken over (see above).
- **One match per host at a time** (the engine's fixed port). The host lock serialises matches in this package; two hosts need two engines.
- **Not here:** bracket, byes and house bots (BIO-303), tie-break maps and coin flip (BIO-304), replay storage and deletion (BIO-305), the real Admin notification channel, who may resume a paused match, scheduling and the web API.
- **No independent review.** Written and tested by the same assistant; the tests encode my reading of PRD SRD-010/011 and TC-04.
