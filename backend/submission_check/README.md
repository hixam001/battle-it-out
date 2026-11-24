# submission_check

The upload check for a participant's `bot.py` (BIO-202, BIO-REQ-04, SRD-050/051; `docs/CHANGE_NOTICES.md` CN-013). Standard library only. It is **a library, not a service**: no upload endpoint, no storage and no activation state exist yet; this module answers "may this file become active?" for them.

## What it does

1. **Static check** with `backend/bot_validator` (file name, one file, UTF-8, syntax, `turn()`, imports, names). Any error rejects the upload before a game is played.
2. **Trial match on both sides.** The exact bytes that were validated are copied into a private staging folder and play two full games on `DefaultSmall` against a pinned reference bot (the scaffold's `examplefuncsplayer_py`, SHA-256 in `trial.py`; a different reference file stops the check): the candidate as side A, then as side B. Games run through the real launcher: sandbox, limits, failure classification, host lock (same engine port as tournament matches).
3. **A verdict** with three outcomes:

| Status | Meaning | Participant told |
|---|---|---|
| `valid` | static check passed and no bot failure on either side | may become active (`may_activate`) |
| `rejected` | static error, or the bot crashed, hung, broke the protocol or breached a limit | what to change, per reason (`S-*` static, `T-CRASH`, `T-LIMIT`) |
| `inconclusive` | platform failure, busy host, or the reference bot failed | nobody blamed; try again; never active |

Losing every game is still `valid`: the check asks whether the bot runs, not whether it is good. A participant fault in one game wins over an inconclusive other game.

```python
from pathlib import Path
from backend.submission_check import trial as T
from backend.match_runner import launcher as L

play = T.launcher_play(L.DEFAULT_SCAFFOLD, py, Path("/var/lib/bio/trials"), lock_path=Path("/var/lib/bio/host.lock"))
verdict = T.check_submission(Path("upload/bot.py"), play=play)      # a file, or a folder holding only bot.py
T.may_activate(verdict, verdict["sha256"])                          # True only for status valid and this exact file
```

The verdict holds `status`, `stage` (`static` or `trial`), `reasons` (`code`, `line`, `message`, `side`), `warnings`, `sha256`, `bytes`, `trials` (one row per game), and `own_output` (what the bot itself printed, taken from the participant view of the structured log, already redacted and clipped; labelled as the bot's own text). Reason messages use fixed wording: nothing a bot printed becomes a reason line.

## Limits of this check

- A bot can behave well for two trial games and badly later (different map, different opponent). The tournament classification still applies: the trial is not a proof.
- The trial map is fixed (`DefaultSmall`); which maps and how many games is an owner decision (the PRD says only "runtime compatibility").
- `rejected` for a bot failure uses the same classification as tournaments (CN-005/006), so the interim limits (DEC-04) decide what is rejected.
- Nothing stores the verdict, throttles uploads or queues checks. Two uploads at once wait for the host lock.
- No independent review.

## Tests

```bash
backend/.venvs/py3.15/bin/python -m unittest backend.submission_check.tests.test_trial
BIO_INTEGRATION=1 backend/.venvs/py3.15/bin/python -m unittest backend.submission_check.tests.test_trial   # also plays real games (about 20 s)
```

21 tests: 19 unit (fake game player) and 2 real (the example bot is valid; `hang_py` is rejected with `T-LIMIT`, `crash_py` with `T-CRASH`).
