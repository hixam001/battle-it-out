# tournament_flow

The steps between the libraries (BIO-EPIC-03; `docs/CHANGE_NOTICES.md` CN-018). The registry, the queue, the map pool and bracket, and the replay vault each work alone. This package is the one place that joins them in a safe order, so the API that will sit on top has one call per step. Standard library only. It authenticates nobody: the caller passes the `Actor` (or the Organizer's id) and decides who may call what.

```python
from backend.tournament_flow import flow as F
fl = F.Flow(registry, orchestrator_store, job_queue)

F.upload(fl, actor, team, tournament, "bot.py", data, idempotency_key=k, deadline_at=t)   # stores the version and queues its check
F.sweep_checks(fl)                                       # queues unchecked versions that have no job (dead jobs are left to an operator)
F.open_bracket(fl, tournament, bracket_id, team_ids, pool_id, catalogue, engine_version, deadline_at=t)
                                                         # after the deadline: pin, then draw with exactly the pinned versions
F.start_round(fl, bracket_id, 1, "org-1")                # re-hash every pinned bot, check it is the drawn version, start, queue
F.housekeeping(fl, vault)                                # sweep, store replays of finished games, finish interrupted purges
```

| Step | Refused when | Safe to repeat |
|---|---|---|
| `upload` | deadline passed, not the captain, file too large (the registry's rules) | yes: same version, same job |
| `open_bracket` | before the deadline; a check is still pending; fewer than two teams with an active bot | yes: the stored draw comes back; pins are write-once |
| `start_round` | bracket without a tournament; a pinned version differs from the drawn one; a pinned file no longer matches its hash (staff incident); the previous round is not complete | yes: one job; nothing for a completed round |

A team with no active version is **excluded and listed** by `open_bracket`. Fewer than two such teams is refused **before** the write-once pin is made (CN-019 fixed a defect where the pin came first and the tournament could never be drawn again). Whether it should instead lose by forfeit or be replaced by a house bot is an owner decision (CN-018 D4).

## Tests

```
python3 -m unittest backend.tournament_flow.tests.test_flow -v
BIO_INTEGRATION=1 python3 -m unittest backend.tournament_flow.tests.test_flow.RealFlow -v   # about 46 s
```

## Not done

The API that calls these functions; tournament, deadline and registration storage is in `backend/tournaments/` (CN-019), whose `scheduler.tick` calls `open_bracket` and `housekeeping`; registration storage; notifications; house bots; independent review.
