# submission_registry

Versions, validation history, the active version, the deadline lock and access rules for participants' `bot.py` files (BIO-EPIC-05, BIO-REQ-14, SRD-050 to SRD-058; `docs/CHANGE_NOTICES.md` CN-016). Standard library plus this repository's `bot_validator`, `submission_check` and the match store. It is **a library, not a service**: no HTTP endpoint, no authentication, no tournament storage. The caller passes who is asking (`Actor`) and the current deadline.

## Flow

```python
from backend.submission_registry import registry as R
from backend.submission_check import trial as T

reg = R.Registry(Path("/var/lib/bio/submissions"), Path("/var/lib/bio/registry.json"))   # root is private, outside the web root

v = R.submit(reg, captain, "team-a", "t1", "bot.py", data, idempotency_key=key, deadline_at=deadline_epoch)
v["validation_status"]        # "validating", or "invalid" with the static reasons in v["validations"]

play = T.launcher_play(scaffold, py, out_root, lock_path=Path("/var/lib/bio/host.lock"))
R.run_check(reg, v["id"], lambda folder: T.check_submission(folder, play=play))   # a worker; one at a time per version

R.history(reg, actor, "team-a")                     # members, assigned Organizer, Admin; others get NotFound
R.download(reg, actor, v["id"])                      # SourceHandle(path, sha256, size), bytes re-verified, staff reads audited

pins = R.pin_tournament(reg, "t1", ["team-a", "team-b"], deadline_at=deadline_epoch)   # once, after the deadline
folder = R.pinned_folder(reg, "t1", "team-a")        # reg.root / "team-a-v3": the bots_dir entry for the match runner
```

## Rules

| Rule | Where |
|---|---|
| Only the captain uploads; Organizer and Admin read only; outsiders get `NotFound` | `submit`, `history`, `download` |
| Static check at upload; every upload, valid or not, is a numbered version in the history | `submit` |
| Only a valid verdict for the exact stored bytes makes a version valid; the highest valid version is active; a rejected, inconclusive or invalid one never displaces it | `record_verdict` |
| At or after the deadline nothing is stored; a later deadline (an extension) reopens | `submit` |
| Same idempotency key returns the same version; the same key with other bytes is a conflict | `submit` |
| One worker per version at a time; a dead worker's claim lapses after the lease; a stale worker cannot write | `claim_check`, `record_verdict` |
| Stored folders are read-only and hashed again before use; a mismatch is `Unavailable` and a staff incident | `claim_check`, `download`, `pinned_folder`, `verify_pins` |
| Which version a team plays with is fixed once, after the deadline, and cannot move | `pin_tournament` |

Statuses: `validating` (needs a trial), `valid`, `invalid` (static or trial rejection), `inconclusive` (platform could not tell; check again). `is_active` is true for at most one version per team.

## Limits

- The deadline is trusted from the caller; there is no storage or extension flow for it (EPIC-06).
- The state is one JSON file with the match store's lock rules (DEC-11); source files are on local disk with file modes only.
- 256 KiB per file and 500 versions per team are interim numbers.
- The bot's own output from the trial is not stored (CN-016 D8).
- Nothing deletes source files or applies a retention rule (DEC-13).
- No independent review.

## Tests

```bash
backend/.venvs/py3.15/bin/python -m unittest backend.submission_registry.tests.test_registry
BIO_INTEGRATION=1 backend/.venvs/py3.15/bin/python -m unittest backend.submission_registry.tests.test_registry   # also plays real games (about 35 s)
```
