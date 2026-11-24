# bot_validator

Early static check of a participant's `bot.py` against the Battlecode engine's own bot policy (BIO-201). The policy is written down in [`docs/BOT_POLICY.md`](../../docs/BOT_POLICY.md); here it is data (`policy.json`) generated from the installed engine.

```bash
python3 backend/bot_validator/validator.py path/to/bot.py          # or a directory that holds only bot.py
backend/.venvs/py3.15/bin/python backend/bot_validator/generate_policy.py --check   # policy vs engine
```

Output is JSON. Exit code 0: no errors (warnings allowed; add `--fail-on-warning` to fail on them), 1: errors, 2: input missing. Run it with the Python that runs matches, because the syntax check uses the running interpreter.

| Code | Kind | Meaning |
|---|---|---|
| `E-FILES`, `E-ENCODING`, `E-SIZE` | error | not exactly one `bot.py`; not UTF-8; over `max_bytes` (unset until the owner decides) |
| `E-SYNTAX` | error | does not parse (with line number) |
| `E-NO-TURN`, `E-TURN-SIGNATURE` | error | no top-level `turn()`, or it takes parameters or is async |
| `E-IMPORT` | error | import outside `random`, `math`, `enum`, `battlecode26`, or relative import |
| `E-NAME` | error | name not defined for bots in the engine (for example `sum`, `dict`, `print`): a `NameError` at run time |
| `W-RISKY-NAME`, `W-RISKY-ATTRIBUTE` | warning | `open`, `setattr`, `delattr`, `__import__`, or an attribute such as `__subclasses__`: allowed by the engine, relevant to isolation |

It is **not a security boundary**: it over-approximates which names are defined, ignores strings and dynamic tricks, and the engine allows risky constructs. Host isolation and time limits are separate work (BIO-203/204, DEC-04).

## Tests

```bash
backend/.venvs/py3.15/bin/python -m unittest backend.bot_validator.tests.test_validator
```

13 tests: unit tests for every code, the repository's bots, a drift check of `policy.json` against the engine, and a cross-check that the validator and the real engine runner accept or reject the same module-level code. Without the engine installed, the two engine tests are skipped.
