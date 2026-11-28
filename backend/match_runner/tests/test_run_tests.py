# SPDX-License-Identifier: AGPL-3.0-only
"""Tests of backend/run_tests.py: it must find every test module and never report a silent pass."""
import importlib.util
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backend import run_tests as R


class FindModules(unittest.TestCase):
    def test_every_test_file_is_listed_and_importable(self):
        on_disk = sorted(p for p in R.BACKEND.glob("*/tests/test_*.py"))
        names = R.test_modules()
        self.assertEqual(len(names), len(on_disk))
        self.assertGreaterEqual(len(names), 20)
        for name in names:
            self.assertTrue(name.startswith("backend."))
            self.assertIsNotNone(importlib.util.find_spec(name), name)

    def test_this_file_is_listed(self):
        self.assertIn("backend.match_runner.tests.test_run_tests", R.test_modules())

    def test_prefix_filter(self):
        names = R.test_modules(["backend.work_queue"])
        self.assertTrue(names)
        self.assertTrue(all(n.startswith("backend.work_queue") for n in names))
        self.assertEqual(R.test_modules(["backend.no_such_package"]), [])
        self.assertEqual(R.test_modules(["backend.work_queue", "backend.registration"]),
                         sorted(R.test_modules(["backend.work_queue"]) + R.test_modules(["backend.registration"])))

    def test_files_that_are_not_tests_are_left_out(self):
        names = R.test_modules()
        self.assertFalse(any(n.endswith(".escape_probe") for n in names))
        self.assertFalse(any(".tests.__init__" in n for n in names))


class Versions(unittest.TestCase):
    def test_matrix_defaults_to_the_lock(self):
        lock = json.loads(R.LOCK.read_text(encoding="utf-8"))
        self.assertEqual(R.tested_versions(), lock["tested_python"])
        self.assertEqual(R.tested_versions(), ["3.12", "3.13", "3.14", "3.15"])

    @unittest.skipUnless(shutil.which("uv"), "uv not installed")
    def test_a_missing_python_is_an_error_not_a_skip(self):
        with self.assertRaises(SystemExit) as caught:
            R.find_python("2.5")
        self.assertIn("2.5", str(caught.exception))


class Exit(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        sys.path.insert(0, str(self.tmp))
        self.addCleanup(sys.path.remove, str(self.tmp))

    def _module(self, name: str, body: str) -> str:
        (self.tmp / f"{name}.py").write_text(body, encoding="utf-8")
        self.addCleanup(sys.modules.pop, name, None)
        return name

    def test_a_failing_module_fails_the_run(self):
        name = self._module("zz_failing", "import unittest\nclass T(unittest.TestCase):\n    def test_x(self):\n        self.fail('no')\n")
        with mock.patch.object(R, "test_modules", return_value=[name]), \
                mock.patch.object(sys, "stderr", new=io.StringIO()), \
                mock.patch.object(R.os, "chdir"):
            self.assertEqual(R.main([]), 1)

    def test_a_passing_module_passes(self):
        name = self._module("zz_passing", "import unittest\nclass T(unittest.TestCase):\n    def test_x(self):\n        pass\n")
        with mock.patch.object(R, "test_modules", return_value=[name]), \
                mock.patch.object(sys, "stderr", new=io.StringIO()), \
                mock.patch.object(R.os, "chdir"):
            self.assertEqual(R.main([]), 0)

    def test_skip_fails_only_when_required(self):
        name = self._module("zz_skipped", "import unittest\nclass T(unittest.TestCase):\n    def test_x(self):\n        self.skipTest('fixture')\n")
        with mock.patch.object(R, "test_modules", return_value=[name]), \
                mock.patch.object(sys, "stderr", new=io.StringIO()), \
                mock.patch.object(R.os, "chdir"):
            self.assertEqual(R.main([]), 0)
            self.assertEqual(R.main(["--require-no-skips"]), 1)

    def test_a_run_of_zero_tests_is_not_a_pass(self):
        name = self._module("zz_empty", "x = 1\n")
        with mock.patch.object(R, "test_modules", return_value=[name]), \
                mock.patch.object(sys, "stderr", new=io.StringIO()), \
                mock.patch.object(R.os, "chdir"):
            self.assertEqual(R.main([]), 2)

    def test_a_filter_that_matches_nothing_is_an_error(self):
        with mock.patch.object(sys, "stderr", new=io.StringIO()):
            self.assertEqual(R.main(["backend.no_such_package"]), 2)

    def test_a_module_that_does_not_import_fails_the_run(self):
        name = self._module("zz_broken", "import no_such_module_anywhere\n")
        with mock.patch.object(R, "test_modules", return_value=[name]), \
                mock.patch.object(sys, "stderr", new=io.StringIO()), \
                mock.patch.object(R.os, "chdir"):
            self.assertEqual(R.main([]), 1)


class Matrix(unittest.TestCase):
    def _run(self, codes: dict, **kwargs):
        calls = []

        def fake_run(cmd, cwd=None, env=None, **kw):
            calls.append((cmd, cwd, env))
            return mock.Mock(returncode=codes[cmd[0]])

        with mock.patch.object(R, "find_python", side_effect=lambda v: f"/py/{v}"), \
                mock.patch.object(R.subprocess, "run", side_effect=fake_run), \
                mock.patch("builtins.print"):
            rc = R.run_matrix(["3.12", "3.13"], kwargs.get("prefixes", []), kwargs.get("integration", False),
                              require_no_skips=kwargs.get("require_no_skips", False))
        return rc, calls

    def test_all_pass(self):
        rc, calls = self._run({"/py/3.12": 0, "/py/3.13": 0})
        self.assertEqual(rc, 0)
        self.assertEqual([c[0][0] for c in calls], ["/py/3.12", "/py/3.13"])
        self.assertTrue(all(c[1] == R.ROOT for c in calls))

    def test_one_failure_fails_the_matrix_but_the_rest_still_run(self):
        rc, calls = self._run({"/py/3.12": 1, "/py/3.13": 0})
        self.assertEqual(rc, 1)
        self.assertEqual(len(calls), 2)

    def test_integration_flag_reaches_the_child_and_its_environment(self):
        rc, calls = self._run({"/py/3.12": 0, "/py/3.13": 0}, integration=True)
        for cmd, _cwd, env in calls:
            self.assertIn("--integration", cmd)
            self.assertEqual(env["BIO_INTEGRATION"], "1")

    def test_no_integration_flag_by_default(self):
        rc, calls = self._run({"/py/3.12": 0, "/py/3.13": 0})
        for cmd, _cwd, _env in calls:
            self.assertNotIn("--integration", cmd)
            self.assertNotIn("--require-no-skips", cmd)

    def test_require_no_skips_reaches_each_child(self):
        rc, calls = self._run({"/py/3.12": 0, "/py/3.13": 1}, integration=True, require_no_skips=True)
        self.assertEqual(rc, 1)
        for cmd, _cwd, _env in calls:
            self.assertIn("--require-no-skips", cmd)

    def test_prefixes_are_passed_on(self):
        rc, calls = self._run({"/py/3.12": 0, "/py/3.13": 0}, prefixes=["backend.registration"])
        for cmd, _cwd, _env in calls:
            self.assertIn("backend.registration", cmd)


if __name__ == "__main__":
    unittest.main()
