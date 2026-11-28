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

## Tie-break maps and the coin flip (`tiebreak.py`, BIO-304, CN-010)

A tournament match is a **series** of games; each game is an ordinary match with the retry rules above. A game is *tied* when the engine's reason line says it was decided by its own unseeded coin flip (the engine pick is ignored). Tied game 0 -> 1 predefined tie-break map (normal stage) or 3 maps (final), always all played, in order; more tie-break map wins decides; still equal -> one 50/50 coin flip from `secrets`, drawn and stored in one transaction, never redrawn. A bot failure in any game forfeits the series. The series result is advanced once (`take_series_advancement`); `public_view` is what may be shown to tournament users.

```python
from backend.match_orchestrator import tiebreak as T
T.create_series(store, "r1m3", "team-a", "team-b", "DefaultSmall", "sub-a-v3", "sub-b-v1", "final", ["TieA", "TieB", "TieC"])
T.run_series_job(store, "r1m3", run_fn, alert=notify_admin)       # games are named r1m3-g0 ... r1m3-g3
result = T.take_series_advancement(store, "r1m3")                  # once; None afterwards
```

## Bracket and rounds (`bracket.py`, BIO-302/303, CN-011)

`create_bracket` draws a single-elimination bracket once (random, recorded, never redrawn) with automatic byes for human teams; `start_round` is the Organizer's action and is allowed only when the previous round is complete; `run_round` plays the round's matches one after another (each a CN-010 series) and advances every winner exactly once; a paused game pauses the round. **House bots are refused** until the owner decides DEC-06.

```python
from backend.match_orchestrator import bracket as B
B.create_bracket(store, "open-2026", [{"team": "team-a", "submission": "sub-a-v3"}, ...],
                 {"play": ["DefaultSmall"], "tiebreak_normal": ["TieN"], "tiebreak_final": ["TieF1", "TieF2", "TieF3"]})
B.start_round(store, "open-2026", 1, "org-7")             # Organizer
B.run_round(store, "open-2026", 1, run_fn)                # worker; safe to repeat or run twice
B.public_view(B.get_bracket(store, "open-2026"))          # what participants may see
```

## Map pools (`maps.py`, BIO-303/304, CN-014)

Where the map names come from. `load_engine_maps(jar)` lists the maps inside the pinned engine jar with the SHA-256 of each file (read as a zip, nothing extracted). `create_pool` stores a pool: the played maps, **1** tie-break map for a normal tie and **3** for a final tie, all from that catalogue, with the engine version and every file hash pinned. A pool is never edited (a different set is a new pool id); a tie-break map may not also be a played map. `verify_pool` reports a missing map, a changed file or a different engine; `create_bracket_from_pool` refuses to draw a bracket on a pool that fails and records the pool id on the bracket. Custom (Organizer-uploaded) maps are not supported.

## Replays (`replays.py`, BIO-305, CN-012)

A vault for the engine's `.bc26` replay files (one per game) plus an index. Stored files are private (0600), checked on the way in (hash equal to the launcher's, complete gzip), and served only through the access rule: Admin any tournament, Organizer assigned ones, participant tournaments they are registered in; no access looks exactly like "no such replay"; after archive everyone gets `Gone`, Admin included. Archive marks first, then deletes, then verifies; a failed or interrupted purge is finished by `purge_pending`. Results and brackets are never touched.

```python
from backend.match_orchestrator import replays as R
vault = R.Vault("/srv/replays", R.ReplayIndex("/srv/replays.json"))
R.collect_bracket(vault, store, "open-2026", "open-2026")           # after each round; once per game, safe to repeat
h = R.fetch_replay(vault, "open-2026-r1-m0-g0", R.Viewer("participant", frozenset({"open-2026"})))   # NotFound / Gone / Unavailable otherwise
R.archive_tournament(vault, "open-2026", actor="admin-1")          # {"status": "archived", "replays_deleted": True, ...}
R.purge_pending(vault)                                              # retry incomplete purges and sweep restored files from archived tournaments
```

## Whole-tournament test (CN-015)

`tests/test_tournament_e2e.py` runs everything above together on the real engine: pool, five-team bracket, rounds, tie-breaks, replays, archive (about 48 s, `BIO_INTEGRATION=1`). Run it after changing any of these modules:

```
BIO_INTEGRATION=1 python3 -m unittest backend.match_orchestrator.tests.test_tournament_e2e -v
```

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
| `bracket.py` | Bracket draw, byes, Organizer-started rounds, idempotent advancement, public view |
| `maps.py` | Map pools: engine map catalogue with hashes, pinned pools, verification, bracket from a pool |
| `tiebreak.py` | Series of games: tie detection, tie-break maps, coin flip, series result, public view |
| `store.py` | `JsonFileStore`: one JSON file, an exclusive lock across processes, atomic write; a damaged file is an error, never an empty store |
| `tests/test_orchestrator.py` | 34 tests: 30 unit tests with a fake run function, 4 real matches (`BIO_INTEGRATION=1`) |
| `tests/test_bracket.py` | 23 tests: 22 unit, 1 real 3-team tournament (`BIO_INTEGRATION=1`) |
| `tests/test_maps.py` | 34 tests: 32 unit, 1 on the real engine jar, 1 real final series on pool maps (`BIO_INTEGRATION=1`) |
| `tests/test_tiebreak.py` | 31 tests: 28 unit tests, 3 real series (`BIO_INTEGRATION=1`) |

```bash
backend/.venvs/py3.15/bin/python -m unittest backend.match_orchestrator.tests.test_orchestrator backend.match_orchestrator.tests.test_tiebreak backend.match_orchestrator.tests.test_bracket backend.match_orchestrator.tests.test_maps
BIO_INTEGRATION=1 backend/.venvs/py3.15/bin/python -m unittest backend.match_orchestrator.tests.test_orchestrator backend.match_orchestrator.tests.test_tiebreak backend.match_orchestrator.tests.test_bracket   # plays real matches, about 75 s
```

## Not covered (and why it matters)

- **A new random seed per retry is not possible yet.** The engine's tie-break seed is not controllable (CN-005). The code passes a seed from an optional `seed_fn` into every attempt and stores it, but the launcher ignores it, and `seed` is `null` in every attempt unless a function is given. TC-04's "new seed" is therefore **not met**; a retry replays the same inputs and may or may not differ in a coin-flip tie.
- **The store is a stand-in.** DEC-11 (database and hosting) is undecided. A JSON file is fine for one host; it does not scale, has no history of old versions and keeps host paths of replays and logs (staff-only). Replace `JsonFileStore` with transactions on the real database; `create_match`, `claim`, `finish` and the rest are written as one transaction each for that purpose.
- **`take_advancement` is only the first guard.** If the caller crashes after taking it and before advancing the bracket, the claim is lost. BIO-303 must make advancement idempotent on the match id.
- **No heartbeat.** A long match that outlives its lease is taken over (see above).
- **One match per host at a time** (the engine's fixed port). The host lock serialises matches in this package; two hosts need two engines.
- **Not here:** house bots (DEC-06), custom maps and where the chosen pool is stored, the qualification-cutoff draw (DEC-14), replay endpoint, object storage and a player (the vault, access rule and purge are `replays.py`), the real Admin notification channel, who may resume a paused match, scheduling and the web API.
- **No independent review.** Written and tested by the same assistant; the tests encode my reading of PRD SRD-010/011 and TC-04.
