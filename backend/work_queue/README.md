# work_queue

A durable job queue and a worker program that runs outside the web/API process (BIO-EPIC-03, SRD-007; `docs/CHANGE_NOTICES.md` CN-017). Standard library only. It connects two things that already existed as libraries: the **upload check** (`submission_registry.run_check`) and the **round runner** (`bracket.run_round`). It is a worker, not a scheduler: nothing yet puts jobs in the queue except the commands below, because there is no API.

## What it does

- **A job carries ids only** (`submission_id`, or `bracket_id` and `round_no`), never a path or code. The handler looks everything else up, and only two job kinds exist.
- **One live job per key.** Queueing the same work twice returns the first job. Finished or dead work does not block new work, so a paused round can be started again.
- **One worker holds a job at a time**: claim token plus lease (default 120 s). While a handler runs, a helper thread renews the lease every third of it, so a half-hour match is not mistaken for a dead worker. A worker that dies stops renewing; after the lease another worker takes the job and that counts as one failure.
- **A worker that lost its job cannot overwrite the new worker's outcome** (`Stale`); it only learns that it lost.
- **Failures are retried with a growing wait** (30 s, 60 s, 120 s ... up to 1 h) and at most `max_attempts` (5, interim) times; then the job is `dead`, an incident is stored and the alert function is called (at least once, same delivery code as the match store). `Permanent` (bad configuration, work that no longer exists) is dead at once. Waiting for somebody else's work (`Defer`) is not a failure, but is bounded (1000 deferrals).
- **A signal is not a failure.** The first SIGTERM/Ctrl-C lets the running job finish and then stops; a second hands the job back immediately without counting a failure.
- **Operators** can read jobs and counts and `revive` a dead job (the actor is recorded; who may do it is the API's decision).
- A damaged queue file is never treated as an empty queue.

## What a handler decides

| Situation | Job result |
|---|---|
| version checked `valid` or `rejected` | done (the registry recorded it and applied the activation rule) |
| check `inconclusive` (platform could not tell) | **failure**, retried later; nobody is blamed, nothing becomes active; dead with an incident at the cap |
| the check could not run (`CheckError`, crash) | failure, claim given back so the version can be claimed again |
| unknown or damaged stored version | dead at once (the registry already stored its own incident) |
| another worker holds the check or the round | deferred 60 s, no failure |
| round completed | done |
| a game is paused (retry cap, configuration error) | done with `paused: true`; the orchestrator holds the incident; after an operator resumes the game the round is queued again |
| round not started by an Organizer, unknown bracket | dead at once |

## Running it

```
python3 -m backend.work_queue.service --data-dir /srv/bio enqueue-check ta-v1
python3 -m backend.work_queue.service --data-dir /srv/bio enqueue-round tournament-1 1
python3 -m backend.work_queue.service --data-dir /srv/bio run          # until SIGTERM
python3 -m backend.work_queue.service --data-dir /srv/bio run --once   # the jobs due now, then exit
python3 -m backend.work_queue.service --data-dir /srv/bio status
```

Everything lives under `--data-dir`: `queue.json`, `registry.json` and `submissions/` (the bot folders, which are also the match runner's bots dir), `matches.json` (the orchestrator store with the brackets), `host.lock` (shared by trial games and tournament games: one engine match per host, the engine's port is fixed), `out/`. The alert function of `run` prints a JSON line; a real Admin channel does not exist yet. The worker itself is trusted code and should run as an unprivileged user; every bot is in its own sandbox (`backend/match_runner`).

```python
from backend.work_queue import jobs as J, service
q = J.JobQueue("queue.json")
J.enqueue_check(q, "ta-v1")
service.build_worker(Path("data")).run_until_idle()
```

## Tests

```
python3 -m unittest backend.work_queue.tests.test_jobs backend.work_queue.tests.test_handlers -v
BIO_INTEGRATION=1 python3 -m unittest backend.work_queue.tests.test_handlers.WorkerProgram -v   # real games, about 45 s
```

## Not done

No API or scheduler (nothing enqueues a check when a participant uploads, and nothing calls `purge_pending`, `verify_pins` or notification jobs); more than one host (the engine port and the JSON stores assume one); a container or image for the worker; a real Admin alert channel; the orchestrator's own per-attempt lease (2400 s) is not renewed, so a single match longer than that is still treated as lost; the database (DEC-11); no independent review.
