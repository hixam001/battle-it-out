import hashlib
import json
import socket
import tempfile
import unittest
from pathlib import Path

from backend.match_runner import launcher as L

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

    def test_unfinished_match(self):
        r = L.parse_result("[server] Match Starting\n[A: #3@5] hello\n")
        self.assertIsNone(r["winner"])
        self.assertFalse(r["finished"])


class Commands(unittest.TestCase):
    scaffold = Path("/x/scaffold")

    def test_runner_cmd_uses_venv_and_no_new_process(self):
        cmd = L.build_runner_cmd(self.scaffold, "a", "b", "python", "python", nodelay=False)
        self.assertEqual(cmd[0], "/x/scaffold/.venv/bin/python")
        self.assertEqual(cmd[1:3], ["-m", "battlecode26"])
        self.assertNotIn("--new-process", cmd)
        self.assertEqual(cmd[cmd.index("--teamA") + 1], "a")

    def test_runner_cmd_non_python_team_is_slash(self):
        cmd = L.build_runner_cmd(self.scaffold, "a", "b", "java", "python", nodelay=False)
        self.assertEqual(cmd[cmd.index("--teamA") + 1], "/")
        self.assertEqual(cmd[cmd.index("--teamB") + 1], "b")

    def test_runner_cmd_nodelay_uses_shim(self):
        cmd = L.build_runner_cmd(self.scaffold, "a", "b", "python", "python", nodelay=True)
        self.assertTrue(cmd[2].endswith("nodelay_shim.py"))

    def test_gradle_cmd(self):
        cmd = L.build_gradle_cmd(self.scaffold, "a", "b", "python", "java", "DefaultSmall", Path("/o/r.bc26"), True)
        self.assertEqual(cmd[1], "runJavaLocal")
        self.assertIn("--offline", cmd)
        self.assertIn("-PlanguageB=java", cmd)
        self.assertIn("-Preplay=/o/r.bc26", cmd)
        self.assertNotIn("--offline", L.build_gradle_cmd(self.scaffold, "a", "b", "python", "python", "m", Path("/o"), False))


class VerifyAndPorts(unittest.TestCase):
    def test_verify_reports_missing_venv(self):
        with tempfile.TemporaryDirectory() as d:
            problems = L.verify(Path(d), L.load_lock())
        self.assertTrue(any("venv interpreter not found" in p for p in problems))

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


if __name__ == "__main__":
    unittest.main()
