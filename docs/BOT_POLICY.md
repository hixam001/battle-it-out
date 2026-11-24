# Bot policy

Status: adopted 2026-11-24 on the owner's instruction (CN-004 in [`CHANGE_NOTICES.md`](CHANGE_NOTICES.md)): **the platform's bot rules are the Battlecode engine's own rules.** Where the PRD or SRD say "standard library and preinstalled third-party libraries" (PRD section on bot contract, SRD-005), this policy replaces them, because the engine only allows the imports below.

The machine-readable policy is [`backend/bot_validator/policy.json`](../backend/bot_validator/policy.json), generated from the installed engine package (`generate_policy.py`), and enforced early by the validator ([`backend/bot_validator/`](../backend/bot_validator/README.md)). The numbers below were read from engine package `battlecode26` 1.2.2 (the contents of the official 1.2.6 release) and checked against the real engine by tests.

## 1. File rules (platform rule, from the PRD)

- Exactly one file named `bot.py`; no ZIP, no other files.
- UTF-8 text; it must parse on the Python version that runs matches (latest stable, CN-001).
- A top-level function `turn()` with no parameters, called once per robot turn.
- Size limit: **not set** (`[DECIDE]`: upload size cap). The validator has a `max_bytes` field that stays empty until the owner decides.

## 2. Imports (the engine's allowlist)

Only: `battlecode26`, `enum`, `math`, `random`. Anything else raises `ImportError` in the engine (checked: `os`, `sys`, `time`, `json`, `re`, `collections` are refused). Relative imports are refused. Because the platform accepts a single file, importing your own modules is not possible. `from battlecode26 import *` gives the game types and functions listed in section 4.

## 3. Builtins (the engine's table)

Available (83):

`ArithmeticError`, `AssertionError`, `AttributeError`, `BaseException`, `BufferError`,
`BytesWarning`, `DeprecationWarning`, `EOFError`, `EnvironmentError`, `Exception`, `False`,
`FloatingPointError`, `FutureWarning`, `GeneratorExit`, `IOError`, `ImportError`, `ImportWarning`,
`IndentationError`, `IndexError`, `KeyError`, `KeyboardInterrupt`, `LookupError`, `MemoryError`,
`NameError`, `None`, `NotImplementedError`, `OSError`, `OverflowError`,
`PendingDeprecationWarning`, `ReferenceError`, `RuntimeError`, `RuntimeWarning`, `StopIteration`,
`SyntaxError`, `SyntaxWarning`, `SystemError`, `SystemExit`, `TabError`, `True`, `TypeError`,
`UnboundLocalError`, `UnicodeDecodeError`, `UnicodeEncodeError`, `UnicodeError`,
`UnicodeTranslateError`, `UnicodeWarning`, `UserWarning`, `ValueError`, `Warning`,
`ZeroDivisionError`, `abs`, `bool`, `bytes`, `callable`, `chr`, `complex`, `delattr`, `divmod`,
`enumerate`, `float`, `frozenset`, `hash`, `hex`, `id`, `int`, `isinstance`, `issubclass`, `len`,
`list`, `oct`, `open`, `ord`, `pow`, `range`, `repr`, `round`, `set`, `setattr`, `slice`, `sorted`,
`str`, `tuple`, `zip`

**Everything else in Python's builtins is not available** (a `NameError` when used; the validator reports `E-NAME`). The full set of standard builtin names differs between Python versions, so it is not listed here; the list above is authoritative. Notable absences: `dict(...)` (dict literals and comprehensions work), `sum`, `min`, `max`, `map`, `filter`, `any`, `all`, `next`, `iter`, `super`, `type`, `object`, `property`, `classmethod`, `staticmethod`, `getattr`, `print` (use `log(...)`).

## 4. Names the engine provides

Globals: `Direction`, `GameActionException`, `MapInfo`, `MapLocation`, `RobotInfo`, `Team`, `TrapType`,
`UnitType`, `bottom_left_distance_squared_to`, `direction_to`, `distance_squared_to`,
`get_all_type_locations`, `instrument`, `is_adjacent_to`, `is_within_distance_squared`, `log`,
`rc`. From `from battlecode26 import *` also: `GameActionExceptionType`, `GameConstants`, `Message`, `RobotController`.

## 5. What the engine allows but the platform must still contain

The engine does not restrict the following, and this policy does not change that (same policy as Battlecode). The validator reports them as **warnings**, not errors; they are not a security boundary:

- `open`, `setattr`, `delattr`, `__import__` (and attribute walks such as `().__class__.__base__.__subclasses__()`) are usable. Attribute names the validator warns about: `__class__`, `__base__`, `__bases__`, `__mro__`, `__subclasses__`, `__globals__`, `__code__`,
`__builtins__`, `__dict__`, `__closure__`, `__getattribute__`, `__import__`, `__loader__`,
`__reduce__`, `__reduce_ex__`.
- There is **no limit on pure Python computation**: the engine's bytecode counter only charges game API calls, so `while True: pass` never ends. Wall-clock, memory and output limits are `[DECIDE]` (DEC-04) and must be enforced by the platform.

Therefore the real protection is host-level: a container per match with no network, a read-only file system, CPU, memory and time limits (BIO-203/204). Until that exists, **do not run untrusted bots on a machine that holds anything of value.** If the owner later wants these warnings to become rejections, that is a change to this policy (a new change notice), not a bug fix.

## 6. How the policy is kept honest

- `generate_policy.py --check` compares `policy.json` with the installed engine and fails on drift; run it whenever the engine package or Python version changes (it is also a unit test).
- A test runs the same code through the validator and through the real engine runner and requires the same accept or reject verdict for module-level code.
- The validator is a best-effort static check: it over-approximates which names are defined, so it can miss a name error but should not reject a valid bot. The engine is authoritative.
