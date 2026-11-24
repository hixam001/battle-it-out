# SPDX-License-Identifier: AGPL-3.0-only
"""Unit tests (always run) and an opt-in integration test (BIO_INTEGRATION=1).

Run with any environment from setup_env.py, e.g.:
    backend/.venvs/py3.15/bin/python -m unittest backend.match_runner.tests.test_launcher
    BIO_INTEGRATION=1 python3 -m unittest backend.match_runner.tests.test_launcher
"""
import hashlib
import importlib.util
import os
import socket
import tempfile
import unittest
from pathlib import Path

from backend.match_runner import launcher as L

HERE = Path(__file__).resolve().parent

SAMPLE_LOG = """[server] -------------------- Match Starting --------------------
[server] a_py vs. b_py on DefaultSmall
[server]             a_py (A) wins (round 1290)
[server] Reason: The winning team destroyed all of the enemy team's rat kings.
[server] -------------------- Match Finished --------------------
"""


class ParseResult(unittest.TestCase):
    def test_finished_match(self):
        r = L.parse_result(SAMPLE_LOG)
        self.assertEqual((r["winner"], r["winning_team"], r["round"], r["finished"]), ("A", "a_py", 1290, True))
        self.assertIn("rat kings", r["reason"])

    def test_server_error_is_reported(self):
        log = ("[server:warning] (Stacktrace Error)\n"
               "[server:warning] Error while loading player x_py: ILLEGAL Team is known to have errors\n"
               "Stack trace: \n" + SAMPLE_LOG)
        r = L.parse_result(log)
        self.assertEqual(len(r["server_errors"]), 1)
        self.assertIn("Error while loading player", r["server_errors"][0])
        self.assertEqual(L.parse_result(SAMPLE_LOG)["server_errors"], [])

    def test_unfinished_match(self):
        r = L.parse_result("[server] Match Starting\n[A: #3@5] hello\n")
        self.assertIsNone(r["winner"])
        self.assertFalse(r["finished"])


class Commands(unittest.TestCase):
    py = Path("/x/venv/bin/python")

    def test_runner_cmd(self):
        cmd = L.build_runner_cmd(self.py, Path("/x/bots"), "a", "b", True)
        self.assertEqual(cmd[:2], ["/x/venv/bin/python", "-I"])
        self.assertTrue(cmd[2].endswith("runner_entry.py"))
        self.assertNotIn("--new-process", cmd)
        self.assertNotIn("--no-socket-tuning", cmd)
        self.assertEqual(cmd[cmd.index("--teamA") + 1], "a")
        self.assertEqual(cmd[cmd.index("--dirB") + 1], "/x/bots")

    def test_runner_cmd_without_tuning(self):
        self.assertIn("--no-socket-tuning", L.build_runner_cmd(self.py, Path("/b"), "a", "b", False))

    def test_gradle_cmd_is_python_only(self):
        cmd = L.build_gradle_cmd(Path("/x/scaffold"), "a", "b", "DefaultSmall", Path("/o/r.bc26"), True)
        self.assertEqual(cmd[1], "runJavaLocal")
        self.assertIn("--offline", cmd)
        self.assertIn("-PlanguageA=python", cmd)
        self.assertIn("-PlanguageB=python", cmd)
        self.assertIn("-Preplay=/o/r.bc26", cmd)
        self.assertFalse([a for a in cmd if a.startswith("-PclassLocation")])
        with_dir = L.build_gradle_cmd(Path("/s"), "a", "b", "m", Path("/o"), True, Path("/c"))
        self.assertIn("-PclassLocationA=/c", with_dir)
        self.assertIn("-PclassLocationB=/c", with_dir)
        self.assertNotIn("--offline", L.build_gradle_cmd(Path("/s"), "a", "b", "m", Path("/o"), False))

    def test_resolve_python(self):
        lock = L.load_lock()
        self.assertTrue(str(L.resolve_python(None, None, lock)).endswith(f"py{lock['primary_python']}/bin/python"))
        self.assertTrue(str(L.resolve_python("3.13", None, lock)).endswith("py3.13/bin/python"))
        self.assertEqual(L.resolve_python("3.13", Path("/p"), lock), Path("/p"))


class VerifyAndPorts(unittest.TestCase):
    def test_verify_reports_missing_interpreter(self):
        problems = L.verify(L.DEFAULT_SCAFFOLD, Path("/nonexistent/python"), L.load_lock())
        self.assertTrue(any("interpreter not found" in p for p in problems))

    def test_sha256_of(self):
        with tempfile.NamedTemporaryFile() as f:
            f.write(b"abc"); f.flush()
            self.assertEqual(L.sha256_of(Path(f.name)), hashlib.sha256(b"abc").hexdigest())

    def test_port_in_use(self):
        s = socket.socket(); s.bind(("127.0.0.1", 0)); s.listen(1)
        port = s.getsockname()[1]
        try:
            self.assertTrue(L.port_in_use(port))
        finally:
            s.close()
        self.assertFalse(L.port_in_use(port))

    def test_lock_file_shape(self):
        lock = L.load_lock()
        self.assertEqual(len(lock["engine_package"]["artifact_sha256"]), 64)
        self.assertEqual(lock["crossplay_port"], 27185)
        self.assertIn(lock["primary_python"], lock["tested_python"])


@unittest.skipUnless(importlib.util.find_spec("battlecode26"), "engine package not installed in this interpreter")
class RunnerEntry(unittest.TestCase):
    def test_import_engine_restores_opmap(self):
        import dis
        from backend.match_runner import runner_entry
        before = dis.opmap
        engine_main = runner_entry.import_engine()
        self.assertIs(dis.opmap, before)
        self.assertTrue(callable(engine_main.play))


@unittest.skipUnless(os.environ.get("BIO_INTEGRATION") == "1", "set BIO_INTEGRATION=1 to run real matches")
class MatchIntegration(unittest.TestCase):
    """Runs real matches with the primary Python environment (needs setup_env.py and Gradle offline)."""

    def run_bot(self, bot):
        with tempfile.TemporaryDirectory() as out:
            return L.run_match(L.DEFAULT_SCAFFOLD, L.resolve_python(None, None, L.load_lock()), HERE / "bots",
                               bot, bot, "DefaultSmall", Path(out), 120, True, True), Path(out)

    def test_feature_bot_matches_golden_output(self):
        with tempfile.TemporaryDirectory() as out:
            res = L.run_match(L.DEFAULT_SCAFFOLD, L.resolve_python(None, None, L.load_lock()), HERE / "bots",
                              "featuretest_py", "featuretest_py", "DefaultSmall", Path(out), 120, True, True)
            self.assertTrue(res["ok"], res)
            lines = set()
            for line in Path(res["logs"]["server"]).read_text().splitlines():
                if "FT:" in line:
                    lines.add(line.split("] ", 1)[1])
            expected = set((HERE / "expected_featuretest.txt").read_text().splitlines())
            self.assertEqual(sorted(lines), sorted(expected))

    def test_hanging_bot_is_stopped_by_overall_timeout_when_no_limits_are_set(self):
        # Measure-only mode (no limits profile, no sandbox): only the launcher's wall-clock timeout protects.
        with tempfile.TemporaryDirectory() as out:
            res = L.run_match(L.DEFAULT_SCAFFOLD, L.resolve_python(None, None, L.load_lock()), HERE / "bots",
                              "hang_py", "hang_py", "DefaultSmall", Path(out), 20, True, True,
                              sandbox=False, limits_path=None)
            self.assertTrue(res["timed_out"])
            self.assertFalse(res["ok"])
            self.assertEqual(res["classification"], "platform_failure")
            self.assertFalse(L.port_in_use(L.load_lock()["crossplay_port"]))

    def test_hanging_bot_is_a_bot_violation_with_default_limits(self):
        with tempfile.TemporaryDirectory() as out:
            res = L.run_match(L.DEFAULT_SCAFFOLD, L.resolve_python(None, None, L.load_lock()), HERE / "bots",
                              "hang_py", "hang_py", "DefaultSmall", Path(out), 60, True, True)
            self.assertFalse(res["timed_out"])
            self.assertEqual(res["classification"], "bot_violation")
            self.assertFalse(L.port_in_use(L.load_lock()["crossplay_port"]))


if __name__ == "__main__":
    unittest.main()
