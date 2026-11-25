# tournaments

The tournament record, its approval and deadlines, and the timer that acts on them (BIO-EPIC-06; `docs/CHANGE_NOTICES.md` CN-019; PRD 6.1, API contract section 3). The other libraries take "the tournament" and "the deadline" as arguments; this is where those come from. Standard library only. It authenticates nobody: the caller passes a `registry.Actor` (`user_id`, `role`, and for Organizers and participants the tournament ids they may see). Times are epoch seconds; the API layer converts from and to ISO-8601 UTC.

```python
from backend.tournaments import tournaments as T, scheduler as S
reg = T.Tournaments.at("data/tournaments.json")

T.create(reg, organizer, "t1", "INNOFEST", "text", registration_deadline, submission_deadline, idempotency_key=k)
T.submit_for_approval(reg, organizer, "t1")            # the creating Organizer
T.approve(reg, admin, "t1", confirm=True)              # or T.reject(reg, admin, "t1", "reason")
T.edit(reg, organizer, "t1", {"map_pool_id": "pool1"}, expected_version=3)
T.open_registration(reg, admin, "t1")
T.extend_deadline(reg, admin, "t1", "submission", later, "reason", confirm=True)   # -> {"tournament", "notice"}
T.emergency_override(reg, admin, "t1", "name", "x", "reason", confirm=True)        # -> {"tournament", "notice"}
T.deadline(reg, "t1", "submission")                    # what registry.submit / flow.open_bracket get as deadline_at

S.tick(reg, flow, catalogue=cat, engine_version=v, vault=vault, alert=send)        # run every minute
T.archive(reg, admin, "t1", vault, confirm=True)       # completed -> archived, replays deleted first
T.delete(reg, admin, "t1", "reason", confirm=True)     # keeps the id, the history and the audit
```

| Step | Who | Refused when |
|---|---|---|
| `create` | Admin, Organizer | participant; id exists; deadline in the past; registration after submission |
| `submit_for_approval` | creating Organizer | not draft or rejected; registration deadline passed |
| `approve` / `reject` | Admin | not pending (an Admin's own draft may be approved directly); no `confirm`; no reason |
| `edit` | Admin, managing Organizer | pending, running or later; the field's deadline passed (`DeadlineLocked`); stale `expected_version` |
| `extend_deadline` | Admin | no confirm or reason; not later than now and than the current value; bracket already drawn |
| `emergency_override` | Admin | no confirm or reason; not name, description or map pool; map pool after the draw; archived or deleted |
| `archive` | Admin, managing Organizer | not completed |
| `delete` | Admin | running; completed but not archived |

A hidden tournament and a missing one give the same `NotFound`. A participant sees only published tournaments listed in their `tournament_ids`, with the public fields.

## The timer

`scheduler.tick` draws the bracket of every `registration_open` tournament whose submission deadline has passed, marks it `running`, marks finished ones `completed`, runs `flow.housekeeping` and delivers open incidents. It is safe to repeat and to resume after a crash. It **never starts a round** (the Organizer's control). A tournament that cannot be drawn is reported as `blocked` with one staff incident per reason; checks still running are `waiting`.

## Tests

```
python3 -m unittest backend.tournaments.tests.test_tournaments backend.tournaments.tests.test_scheduler -v
```

## Not done

The API and authentication; real Organizer assignments (the creating Organizer counts as assigned); a timer that is wired by default to the roster (pass `registration=` to `tick`; the fallback is still "teams that uploaded"); a timer process (`tick(notifications=..., registration=...)` tells the excluded teams, CN-023; nothing runs it); cleanup of the data other libraries hold for a deleted tournament; the database (DEC-11); independent review.
