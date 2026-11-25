# notifications

Dashboard notifications and optional email (BIO-EPIC-06; `docs/CHANGE_NOTICES.md` CN-022; SRD-060/061, PRD 6.5, BIO-NFR-07, API contract section 7). Other libraries already return notices (a deadline was extended, a setting was overridden); this is where they are delivered. Standard library only. It authenticates nobody: the caller passes a `registry.Actor`. The email provider is a function the caller passes (no provider is chosen, DEC-11). Times are epoch seconds.

```python
from backend.notifications import notifications as N
c = N.Notifications.at("data/notifications.json")

# the system creates notifications (timer, API after an Admin action)
out = T.extend_deadline(treg, admin, "t1", "submission", later, "outage", confirm=True)
N.notify_notice(c, registration, out["notice"])                    # everybody who holds a place in t1
N.notify_audience(c, registration, "eliminated", "t1", {"team": "Alpha", "round": 2},
                  event_key="elim:t1:alpha:2", team_id="alpha")    # one team
N.notify(c, "announcement", "t1", ["u1", "u2"], {"headline": "...", "message": "..."}, event_key="ann:7")

# the recipient reads (GET /notifications, PATCH /notifications/{id}, PATCH /me/notification-preferences)
N.list_notifications(c, actor, unread_only=True, limit=50)         # {"items", "total", "unread"}
N.mark_read(c, actor, notification_id)
N.update_preferences(c, actor, {"email_enabled": False})           # the dashboard cannot be switched off

# the outbox worker (run every minute; the provider is never called while the store is locked)
N.deliver_emails(c, send=provider, address_of=lookup)              # {"sent", "retry", "skipped", "failed"}
```

## Rules

- **The dashboard copy is always created**, whatever the email preference; the email is a separate delivery record. A provider outage, a bad address or a given-up email never touches the dashboard copy.
- **Idempotent by `event_key`** (and recipient): repeating an event, or a retried timer, creates nothing new and does not reset the read state.
- **Fixed templates.** `N.EVENTS` lists the event types (announcement, deadline_extended, emergency_override, validation_accepted, validation_rejected, registration_excluded, team_excluded, match_result, qualified, eliminated). Parameters are checked by kind and length; text is data, never a format string.
- **Email.** A delivery is claimed with a lease, sent outside the lock, then recorded; a crash in between sends it again after the lease (at least once; the provider gets `idempotency_key` to drop repeats). `Permanent` from the provider, or no usable address, ends it at once; anything else is retried after 1, 4, 16, 64 minutes, up to 5 attempts, then it is `failed` (`email_failed` in the audit, id in the report for the caller to alert on). The preference is read again at send time.
- **Privacy.** The store holds user ids, not addresses (`address_of` is asked at send time; `registration.official_email` is the stand-in until accounts exist). Provider errors are stored without anything that looks like an address. A notification is readable and markable only by its recipient; anybody else, and a missing id, get the same `NotFound`. Admin reads delivery records (no address).
- **Deletion.** `purge_tournament` (Admin, `confirm`, only after the tournament was deleted) removes its notifications and deliveries; the audit keeps ids and counts.

## Sources (CN-023)

`sources.py` turns events of the other libraries into `notify` calls, from ids only (no caller-built text):

| Function | Event | Told |
|---|---|---|
| `validation_result(center, roster, registry, submission_id)` | check ended `valid` (and active) or `invalid`; inconclusive is not news | verified members of the team |
| `round_results(center, roster, store, bracket_id, round_no)` | each decided match: `match_result`, `qualified` (not in the final; also a bye), `eliminated` | verified members of each team |
| `draw_exclusions(center, roster, tournament_id, teams)` | `team_excluded` and `registration_excluded` (claimed, email never verified) | the team's accounts; the unfinished claimants |

Wiring: `check_submission_handler(..., on_decided=)`, `run_round_handler(..., on_round=)`, `scheduler.tick(..., notifications=, registration=)` (notices go out before the tournament is marked running), and `python3 -m backend.work_queue.service --data-dir D --notify run` (needs `tournaments.json`, `registration.json`, `notifications.json` in `D`). Every call is idempotent by event key.

## Tests

```
python3 -m unittest backend.notifications.tests.test_notifications backend.notifications.tests.test_sources -v
```

## Not done

The HTTP API; a real email provider and its templates in HTML or other languages; the announcement event (an Organizer writes it; needs the API) and calling `notify_notice` after `extend_deadline`/`emergency_override` (the caller still has to); the worker and timer as running services started with `--notify`; mandatory security or account emails (open decision); account deletion (SRD-065..067); the database (DEC-11); independent review.
