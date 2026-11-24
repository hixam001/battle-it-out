# SPDX-License-Identifier: AGPL-3.0-only
"""Run with any interpreter; the engine-dependent tests run only where `battlecode26` is installed:
    backend/.venvs/py3.15/bin/python -m unittest backend.bot_validator.tests.test_validator
"""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from backend.bot_validator import validator as V

ROOT = Path(__file__).resolve().parents[3]
GOOD = "from battlecode26 import *\nfrom random import randint\n\ndef turn():\n    log('x' + str(randint(0, 3)))\n"


def codes(result, kind="errors"):
    return sorted(f["code"] for f in result[kind])


class Source(unittest.TestCase):
    def test_good_bot(self):
        r = V.validate_source(GOOD)
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["warnings"], [])

    def test_syntax_error(self):
        r = V.validate_source("def turn(:\n  pass\n")
        self.assertEqual(codes(r), ["E-SYNTAX"])
        self.assertEqual(r["errors"][0]["line"], 1)

    def test_missing_turn_and_bad_signature(self):
        self.assertEqual(codes(V.validate_source("x = 1\n")), ["E-NO-TURN"])
        self.assertEqual(codes(V.validate_source("def turn(a):\n    pass\n")), ["E-TURN-SIGNATURE"])
        self.assertEqual(codes(V.validate_source("async def turn():\n    pass\n")), ["E-TURN-SIGNATURE"])
        self.assertEqual(codes(V.validate_source("class T:\n    def turn(self):\n        pass\n")), ["E-NO-TURN"])

    def test_imports(self):
        for ok in ["import random", "import math", "import enum", "from math import sqrt", "from battlecode26 import *"]:
            self.assertTrue(V.validate_source(ok + "\ndef turn():\n    pass\n")["ok"], ok)
        for bad in ["import os", "import sys", "import time", "from collections import deque",
                    "import math.floor", "from . import x", "import random, os", "from os import path"]:
            r = V.validate_source(bad + "\ndef turn():\n    pass\n")
            self.assertIn("E-IMPORT", codes(r), bad)

    def test_unknown_builtins_are_errors(self):
        for name in ["sum", "max", "min", "dict", "map", "super", "type", "print", "getattr", "eval", "exec", "object"]:
            r = V.validate_source(f"def turn():\n    return {name}\n")
            self.assertEqual(codes(r), ["E-NAME"], name)

    def test_bound_names_and_scopes_are_not_flagged(self):
        src = ("import math\nX = 1\ndef f(a, *b, **c):\n    return [i for i in range(a)] + list(b)\n"
               "class K:\n    def m(self):\n        return self\n"
               "def turn():\n    global X\n    try:\n        pass\n    except Exception as e:\n        log(str(e))\n"
               "    match X:\n        case [p, *q]:\n            log(str(p))\n    if (w := 3) > 2:\n        log(str(w))\n"
               "    f2 = lambda z: z + 1\n    log(str(f2(1)))\n")
        r = V.validate_source(src)
        self.assertTrue(r["ok"], r)

    def test_risky_constructs_are_warnings_not_errors(self):
        r = V.validate_source("def turn():\n    f = open\n    setattr\n    ().__class__.__base__.__subclasses__()\n    __import__('math')\n")
        self.assertTrue(r["ok"], r)
        self.assertEqual(codes(r, "warnings"), ["W-RISKY-ATTRIBUTE"] * 3 + ["W-RISKY-NAME"] * 3)
        flagged = sorted(w["message"].split("'")[1] for w in r["warnings"])
        self.assertEqual(flagged, sorted(["open", "setattr", "__import__", "__class__", "__base__", "__subclasses__"]))

    def test_size_limit_only_when_policy_sets_one(self):
        policy = dict(V.load_policy(), max_bytes=10)
        self.assertEqual(codes(V.validate_source(GOOD, policy)), ["E-SIZE"])
        self.assertIsNone(V.load_policy()["max_bytes"])  # an owner decision (DEC); never invented


class Paths(unittest.TestCase):
    def test_directory_rules(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            self.assertIn("E-FILES", codes(V.validate_path(d)))
            (d / "bot.py").write_text(GOOD)
            self.assertTrue(V.validate_path(d)["ok"])
            (d / "helper.py").write_text("x = 1\n")
            r = V.validate_path(d)
            self.assertFalse(r["ok"])
            self.assertIn("E-FILES", codes(r))

    def test_file_name_and_encoding(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "mybot.py").write_text(GOOD)
            self.assertIn("E-FILES", codes(V.validate_path(d / "mybot.py")))
            (d / "bot.py").write_bytes(b"\xff\xfe\x00bad")
            self.assertIn("E-ENCODING", codes(V.validate_path(d / "bot.py")))

    def test_repo_bots(self):
        ok = [ROOT / "backend/battlecode26-scaffold/src/examplefuncsplayer_py",
              ROOT / "backend/match_runner/tests/bots/cpuload_py",
              ROOT / "backend/match_runner/tests/bots/hang_py"]
        for p in ok:
            self.assertTrue(V.validate_path(p)["ok"], p)
        r = V.validate_path(ROOT / "backend/match_runner/tests/bots/featuretest_py")
        self.assertEqual(sorted({e["message"].split("'")[1] for e in r["errors"]}),
                         sorted(["super", "eval", "exec", "sum", "max", "dict", "map", "type", "print", "getattr"]))


@unittest.skipUnless(importlib.util.find_spec("battlecode26"), "engine package not installed in this interpreter")
class AgainstEngine(unittest.TestCase):
    def test_policy_has_not_drifted_from_engine(self):
        from backend.bot_validator import generate_policy as G
        fresh = G.read_engine()
        current = json.loads(G.POLICY_PATH.read_text())
        for k in ["engine_package", "allowed_imports", "allowed_builtins", "engine_globals", "battlecode26_exports"]:
            self.assertEqual(current[k], fresh[k], k)

    def test_validator_and_engine_agree_on_module_level_code(self):
        from backend.match_runner import runner_entry
        runner_entry.import_engine()
        from battlecode26.runner import RobotRunner
        from battlecode26.wrappers import _GAME_METHODS

        def engine_accepts(src):
            r = RobotRunner(code={"bot": src}, game_methods=_GAME_METHODS, error_method=lambda *a: None, bytecode_limit=10**9)
            try:
                r.init_robot()
                return True
            except Exception:
                return False
            finally:
                r.kill()

        cases = {
            "good": "from battlecode26 import *\nx = abs(-1)\ndef turn():\n    pass\n",
            "import_ok": "import math\nimport random\nimport enum\ndef turn():\n    pass\n",
            "import_os": "import os\ndef turn():\n    pass\n",
            "import_sys": "import sys\ndef turn():\n    pass\n",
            "from_collections": "from collections import deque\ndef turn():\n    pass\n",
            "builtin_sum": "x = sum([1])\ndef turn():\n    pass\n",
            "builtin_dict": "x = dict(a=1)\ndef turn():\n    pass\n",
            "builtin_print": "print('x')\ndef turn():\n    pass\n",
            "builtin_super": "x = super\ndef turn():\n    pass\n",
            "builtin_type": "x = type(1)\ndef turn():\n    pass\n",
            "class_ok": "class A:\n    def f(self):\n        return 1\nx = A().f()\ndef turn():\n    pass\n",
        }
        for name, src in cases.items():
            self.assertEqual(V.validate_source(src)["ok"], engine_accepts(src), name)


if __name__ == "__main__":
    unittest.main()
