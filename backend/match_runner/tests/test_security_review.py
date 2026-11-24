# SPDX-License-Identifier: AGPL-3.0-only
"""Regression tests for the security review findings SR-01 to SR-05 (docs/SECURITY_REVIEW.md, CN-008).

Unit tests always run. The match tests need `BIO_INTEGRATION=1`, the primary Python environment, Gradle
offline, bubblewrap and `ss`.

    BIO_INTEGRATION=1 python3 -m unittest backend.match_runner.tests.test_security_review -v
"""
import json
import os
import shutil
import socket
import stat
import struct
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from backend.bot_validator import validator as V
from backend.match_runner import launcher as L
from backend.match_runner import sandbox as SB

HERE = Path(__file__).resolve().parent
EXAMPLE_BOT = L.DEFAULT_SCAFFOLD / "src" / "examplefuncsplayer_py"
END_TURN = {"method": 1, "params": [0]}


def frame(obj) -> bytes:
    body = json.dumps(obj).encode()
    return struct.pack(">I", len(body)) + body


def read_frame(sock):
    head = b""
    while len(head) < 4:
        chunk = sock.recv(4 - len(head))
        if not chunk:
            return None
        head += chunk
    (n,) = struct.unpack(">I", head)
    body = b""
    while len(body) < n:
        body += sock.recv(n - len(body))
    return json.loads(body)


class MethodRange(unittest.TestCase):
    def test_unknown_methods_are_refused(self):
        for m in (0, -1, 108, 9999):
            with self.assertRaises(SB.ProtocolViolation, msg=m):
                SB.canonical_runner_frame(json.dumps({"method": m, "params": []}).encode())

    def test_the_first_and_last_engine_methods_pass(self):
        for m in (1, 107):
            SB.canonical_runner_frame(json.dumps({"method": m, "params": []}).encode())

    def test_the_range_matches_the_installed_engine(self):
        py = L.resolve_python(None, None, L.load_lock())
        if not py.exists():
            self.skipTest("primary Python environment not set up")
        out = subprocess.run([str(py), "-c", "from battlecode26.crossplay import CrossPlayMethod as M;"
                              "v=[m.value for m in M if m.value];print(min(v),max(v),len(v))"],
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        lo, hi, n = map(int, out.stdout.split())
        self.assertEqual((lo, hi), (SB.MIN_METHOD, SB.MAX_METHOD))
        self.assertEqual(n, hi - lo + 1, "method numbers are no longer contiguous")


class TurnRule(unittest.TestCase):
    def test_calls_only_from_the_current_runner(self):
        self.assertIsNone(SB.check_turn("A", False, "A", {"A": 0, "B": 0}))
        self.assertIn("out of turn", SB.check_turn("B", False, "A", {"A": 0, "B": 5}))

    def test_nulls_only_when_a_notice_is_waiting_for_one(self):
        self.assertIsNone(SB.check_turn("B", True, "A", {"A": 0, "B": 1}))
        self.assertIn("not asked for", SB.check_turn("A", True, "A", {"A": 0, "B": 0}))


class RouterTurns(unittest.TestCase):
    """The router checks whose turn it is, from outside every sandbox (SR-01) and times silent runners (SR-02)."""

    def start(self, deadline=None):
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(1)
        self.dir = tempfile.TemporaryDirectory()
        self.router = SB.Router(Path(self.dir.name), self.srv.getsockname()[1], turn_deadline=deadline)
        self.a, self.b = socket.socket(socket.AF_UNIX), socket.socket(socket.AF_UNIX)
        self.a.connect(str(self.router.paths["A"]))
        self.b.connect(str(self.router.paths["B"]))
        self.engine, _ = self.srv.accept()
        for s_ in (self.a, self.b, self.engine):
            s_.settimeout(5)

    def tearDown(self):
        for name in ("a", "b", "engine", "srv"):
            if hasattr(self, name):
                getattr(self, name).close()
        if hasattr(self, "router"):
            self.router.close()
            self.dir.cleanup()

    def wait_end(self):
        for _ in range(100):
            if self.router.stats["first_end"]:
                return self.router.stats["first_end"]
            time.sleep(0.05)
        self.fail("router never noticed the end")

    def test_a_call_from_the_idle_team_never_reaches_the_server(self):
        self.start()
        self.b.sendall(frame(END_TURN))               # team A is current at the start
        end = self.wait_end()
        self.assertEqual(end["leg"], "runner:B")
        self.assertIn("out of turn", end["how"])
        self.engine.settimeout(1)
        try:
            self.assertEqual(self.engine.recv(1), b"")  # closed, and no byte was forwarded first
        except (socket.timeout, TimeoutError):
            pass                                        # also fine: nothing arrived

    def test_the_current_runner_may_call(self):
        self.start()
        self.a.sendall(frame(END_TURN))
        self.assertEqual(read_frame(self.engine), END_TURN)
        self.assertIsNone(self.router.stats["first_end"])

    def test_the_turn_follows_the_server(self):
        self.start()
        self.engine.sendall(frame({"type": "start_turn", "id": 7, "round": 1}))   # unknown robot: stays with A
        self.engine.sendall(frame({"type": "spawn_bot", "id": 8, "team": 1}))     # team B becomes current
        self.assertEqual(read_frame(self.b)["type"], "spawn_bot")
        self.b.sendall(frame(None))                                               # B answers the notice
        self.assertIsNone(read_frame(self.engine))
        self.b.sendall(frame(END_TURN))
        self.assertEqual(read_frame(self.engine), END_TURN)
        self.assertIsNone(self.router.stats["first_end"])

    def test_a_null_that_was_not_asked_for_is_refused(self):
        self.start()
        self.a.sendall(frame(None))
        end = self.wait_end()
        self.assertEqual(end["leg"], "runner:A")
        self.assertIn("not asked for", end["how"])

    def test_the_idle_team_may_answer_a_destroy_notice(self):
        self.start()
        self.engine.sendall(frame({"type": "spawn_bot", "id": 9, "team": 1}))
        read_frame(self.b)
        self.b.sendall(frame(None))
        read_frame(self.engine)
        self.engine.sendall(frame({"type": "spawn_bot", "id": 5, "team": 0}))     # team A's robot
        read_frame(self.a)
        self.a.sendall(frame(None))
        read_frame(self.engine)
        self.engine.sendall(frame({"type": "start_turn", "id": 5, "round": 1}))   # A is current
        read_frame(self.a)
        self.engine.sendall(frame({"type": "destroy_bot", "id": 9}))              # B's robot, nested in A's turn
        self.assertEqual(read_frame(self.b)["type"], "destroy_bot")
        self.b.sendall(frame(None))
        self.assertIsNone(read_frame(self.engine))
        self.assertIsNone(self.router.stats["first_end"])

    def test_a_silent_runner_is_charged_by_the_routers_own_clock(self):
        self.start(deadline=0.5)
        self.engine.sendall(frame({"type": "spawn_bot", "id": 1, "team": 0}))
        end = self.wait_end()
        self.assertEqual(end["leg"], "runner:A")
        self.assertTrue(end["how"].startswith("deadline"), end)

    def test_an_answering_runner_is_not_charged(self):
        self.start(deadline=0.6)
        self.engine.sendall(frame({"type": "spawn_bot", "id": 1, "team": 0}))
        read_frame(self.a)
        self.a.sendall(frame(None))
        time.sleep(1.0)                                # idle between turns is not silence
        self.assertIsNone(self.router.stats["first_end"])

    def test_end_game_stops_the_clock(self):
        self.start(deadline=0.4)
        self.engine.sendall(frame({"type": "end_game"}))
        time.sleep(0.9)
        self.assertIsNone(self.router.stats["first_end"])


class ValidatorHostileFiles(unittest.TestCase):
    """The validator runs on the host against uploaded files (SR-04)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def codes(self, path):
        r = V.validate_path(path)
        self.assertFalse(r["ok"], r)
        return [e["code"] for e in r["errors"]]

    def test_a_symlink_named_bot_py_is_refused_not_followed(self):
        (self.dir / "bot.py").symlink_to("/dev/zero")
        self.assertEqual(self.codes(self.dir), ["E-FILES"])
        self.assertEqual(self.codes(self.dir / "bot.py"), ["E-FILES"])

    def test_a_symlink_to_a_host_file_is_refused(self):
        secret = self.dir / "secret.txt"
        secret.write_text("def turn():\n    pass\n")
        d = self.dir / "up"
        d.mkdir()
        (d / "bot.py").symlink_to(secret)
        self.assertEqual(self.codes(d), ["E-FILES"])

    def test_a_link_loop_does_not_recurse(self):
        (self.dir / "bot.py").symlink_to(".")
        self.assertEqual(self.codes(self.dir), ["E-FILES"])

    @unittest.skipUnless(hasattr(os, "mkfifo"), "needs mkfifo")
    def test_a_fifo_does_not_block_the_validator(self):
        os.mkfifo(self.dir / "bot.py")
        t0 = time.monotonic()
        self.assertEqual(self.codes(self.dir), ["E-FILES"])
        self.assertLess(time.monotonic() - t0, 2)

    def test_a_file_over_the_safety_ceiling_is_refused_without_parsing_it(self):
        (self.dir / "bot.py").write_bytes(b"def turn():\n    pass\n# " + b"x" * V.HARD_READ_LIMIT)
        self.assertEqual(self.codes(self.dir), ["E-SIZE"])

    def test_source_too_deep_to_parse_is_an_error_not_a_crash(self):
        (self.dir / "bot.py").write_text("def turn():\n    x = " + "-" * 50000 + "1\n")
        self.assertEqual(self.codes(self.dir), ["E-SYNTAX"])

    def test_nul_bytes_are_an_error_not_a_crash(self):
        (self.dir / "bot.py").write_bytes(b"def turn():\n    pass\n\x00\n")
        self.assertEqual(self.codes(self.dir), ["E-SYNTAX"])

    def test_a_normal_bot_still_passes(self):
        (self.dir / "bot.py").write_text("def turn():\n    pass\n")
        self.assertTrue(V.validate_path(self.dir)["ok"])


class TeamFolderNames(unittest.TestCase):
    def test_names_are_folder_names_not_paths(self):
        for bad in ("../x", "a/b", "..", ".hidden", "", "a b", "x" * 65, "a\nb"):
            self.assertIsNone(L.TEAM_DIR_RE.match(bad), bad)
        for good in ("examplefuncsplayer_py", "team-1.v2", "A"):
            self.assertIsNotNone(L.TEAM_DIR_RE.match(good), good)

    def test_run_match_refuses_a_traversal_name_before_doing_anything(self):
        py = L.resolve_python(None, None, L.load_lock())
        with tempfile.TemporaryDirectory() as out:
            with self.assertRaises(L.LauncherError):
                L.run_match(L.DEFAULT_SCAFFOLD, py, L.DEFAULT_SCAFFOLD / "src", "../src/examplefuncsplayer_py",
                            "examplefuncsplayer_py", "DefaultSmall", Path(out), 5, True, True)


@unittest.skipUnless(os.environ.get("BIO_INTEGRATION") == "1", "set BIO_INTEGRATION=1 to run real matches")
@unittest.skipUnless(shutil.which("bwrap") and shutil.which("ss"), "bubblewrap and ss are needed")
class HostileBotsAreChargedToTheSender(unittest.TestCase):
    """Real sandboxed matches; the hostile bot is team A and the victim is a normal bot (team B)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.bots = Path(cls.tmp.name) / "bots"
        cls.bots.mkdir()
        shutil.copytree(EXAMPLE_BOT, cls.bots / "examplefuncsplayer_py")
        for name in ("oot_py", "stop_py", "badmethod_py"):
            shutil.copytree(HERE / "bots" / name, cls.bots / name)
        cls.py = L.resolve_python(None, None, L.load_lock())

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def match(self, a, b="examplefuncsplayer_py", timeout=90):
        with tempfile.TemporaryDirectory() as out:
            return L.run_match(L.DEFAULT_SCAFFOLD, self.py, self.bots, a, b, "DefaultSmall", Path(out),
                               timeout, True, True)

    def assert_sender_loses(self, bot, kind):
        r = self.match(bot)
        self.assertEqual(r["classification"], "bot_crash", r)
        self.assertEqual((r["loser"], r["winner_by_forfeit"], r["kind"]), ("A", "B", kind), r)
        self.assertEqual(r["outcome"], "bot_failure")
        self.assertFalse(r["timed_out"])
        self.assertFalse(L.port_in_use(L.load_lock()["crossplay_port"]), "server must be stopped")
        return r

    def test_out_of_turn_frames_cannot_hurt_the_other_team(self):
        for _ in range(3):      # the old behaviour depended on timing: wins for A, losses for B, platform failures
            self.assert_sender_loses("oot_py", "protocol_violation")

    def test_a_bot_that_freezes_its_own_process_loses_instead_of_forcing_a_timeout(self):
        r = self.assert_sender_loses("stop_py", "runner_unresponsive")
        self.assertLess(r["seconds"], 40)

    def test_an_unknown_engine_method_is_the_senders_fault_not_a_platform_failure(self):
        self.assert_sender_loses("badmethod_py", "protocol_violation")


if __name__ == "__main__":
    unittest.main()
