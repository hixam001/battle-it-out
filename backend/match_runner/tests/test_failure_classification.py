# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for bot-failure versus platform-failure classification (BIO-205, TC-04).

Unit tests always run. The match tests need `BIO_INTEGRATION=1`, the primary Python environment from
setup_env.py, Gradle offline, bubblewrap and `ss`.

    BIO_INTEGRATION=1 python3 -m unittest backend.match_runner.tests.test_failure_classification -v
"""
import os
import shutil
import signal
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

from backend.match_runner import launcher as L
from backend.match_runner import sandbox as SB

HERE = Path(__file__).resolve().parent
EXAMPLE_BOT = L.DEFAULT_SCAFFOLD / "src" / "examplefuncsplayer_py"
CLEAN = {"server_errors": [], "finished": True}
UNFINISHED = {"server_errors": [], "finished": False}
BOTH = ["A", "B"]


def router(first_end=None, connected=BOTH):
    return {"connected": connected, "first_end": first_end, "error": None}


def ended(leg, how="closed"):
    return {"leg": leg, "how": how, "after_seconds": 1.0}


class DescribeExit(unittest.TestCase):
    def test_signals_codes_and_unknown(self):
        self.assertEqual(L.describe_exit(139), {"exit_status": 139, "signal": "SIGSEGV"})
        self.assertEqual(L.describe_exit(137)["signal"], "SIGKILL")
        self.assertEqual(L.describe_exit(-9)["signal"], "SIGKILL")
        self.assertEqual(L.describe_exit(3), {"exit_status": 3, "signal": None})
        self.assertEqual(L.describe_exit(0), {"exit_status": 0, "signal": None})
        self.assertEqual(L.describe_exit(None), {"exit_status": None, "signal": None})
        self.assertIsNone(L.describe_exit(250)["signal"])     # 250 - 128 is not a signal number


class Rules(unittest.TestCase):
    """The decision table, one row per test. Nothing here needs an engine."""

    def classify(self, result, violation=None, exit_=None, timeout=False, r=None, exits=None):
        return L.classify(result, violation, exit_, timeout, r, exits)

    def test_a_clean_finished_match_is_normal_whatever_closed_first(self):
        c = self.classify(CLEAN, exit_=0, r=router(ended("server")))
        self.assertEqual(c["classification"], "normal")
        # at the end of a game the runners may hang up before the server does; that is not a crash
        self.assertEqual(self.classify(CLEAN, exit_=0, r=router(ended("runner:A")))["classification"], "normal")

    def test_runner_hangs_up_first_in_an_unfinished_match_is_a_bot_crash_for_that_team(self):
        for side, other in (("A", "B"), ("B", "A")):
            c = self.classify(UNFINISHED, r=router(ended(f"runner:{side}")), exits={side: 139})
            self.assertEqual((c["classification"], c["loser"], c["winner_by_forfeit"]), ("bot_crash", side, other))
            self.assertEqual(c["evidence"]["signal"], "SIGSEGV")
            self.assertEqual(L.OUTCOME[c["classification"]], "bot_failure")

    def test_server_error_text_does_not_turn_a_runner_hangup_into_a_platform_failure(self):
        # When a runner dies the Java server prints a bug-report banner as a consequence.
        res = {"server_errors": ["Please report this to the 6.9610 devs"], "finished": False}
        c = self.classify(res, r=router(ended("runner:B")), exits={"B": 3})
        self.assertEqual((c["classification"], c["loser"]), ("bot_crash", "B"))

    def test_server_hangs_up_first_is_a_platform_failure_with_no_loser(self):
        res = {"server_errors": ["boom"], "finished": False}
        c = self.classify(res, r=router(ended("server", "error: reset")))
        self.assertEqual((c["classification"], c["kind"]), ("platform_failure", "engine_failure"))
        self.assertNotIn("loser", c)
        self.assertNotIn("winner_by_forfeit", c)

    def test_a_runner_that_never_connected_is_the_platforms_fault(self):
        c = self.classify(UNFINISHED, r=router(None, connected=["A"]))
        self.assertEqual((c["classification"], c["kind"]), ("platform_failure", "runner_start_failure"))
        self.assertIn("B", c["detail"])

    def test_no_evidence_at_all_is_a_platform_failure(self):
        c = self.classify(UNFINISHED, r=router(None))
        self.assertEqual((c["classification"], c["kind"]), ("platform_failure", "unknown"))

    def test_timeout_is_a_platform_failure_even_when_a_runner_hung_up(self):
        c = self.classify(UNFINISHED, timeout=True, r=router(ended("runner:A")))
        self.assertEqual((c["classification"], c["kind"]), ("platform_failure", "match_timeout"))

    def test_a_guard_violation_beats_the_router_evidence(self):
        c = self.classify(UNFINISHED, violation={"team": "A", "kind": "memory"}, exit_=70, r=router(ended("runner:B")))
        self.assertEqual((c["classification"], c["loser"]), ("bot_violation", "A"))

    def test_every_classification_maps_to_a_worker_outcome(self):
        self.assertEqual(L.OUTCOME, {"normal": "completed", "bot_violation": "bot_failure",
                                     "bot_crash": "bot_failure", "platform_failure": "platform_failure"})

    def test_without_router_evidence_the_old_behaviour_stays(self):
        self.assertEqual(self.classify(UNFINISHED, exit_=3)["classification"], "platform_failure")


class RouterEvidence(unittest.TestCase):
    """The router records which leg of the connection ended first, from outside every sandbox."""

    def setUp(self):
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(1)
        self.dir = tempfile.TemporaryDirectory()
        self.router = SB.Router(Path(self.dir.name), self.srv.getsockname()[1])
        self.a, self.b = socket.socket(socket.AF_UNIX), socket.socket(socket.AF_UNIX)
        self.a.connect(str(self.router.paths["A"]))
        self.b.connect(str(self.router.paths["B"]))
        self.engine, _ = self.srv.accept()
        self.engine.settimeout(5)

    def tearDown(self):
        for s_ in (self.a, self.b, self.engine, self.srv):
            s_.close()
        self.router.close()
        self.dir.cleanup()

    def wait_end(self):
        for _ in range(100):
            if self.router.stats["first_end"]:
                return self.router.stats["first_end"]
            time.sleep(0.05)
        self.fail("router never noticed the end")

    def test_both_runners_are_listed_as_connected(self):
        self.assertEqual(sorted(self.router.stats["connected"]), BOTH)

    def test_runner_closing_first_is_recorded_as_that_runner(self):
        self.b.close()
        self.assertEqual(self.wait_end()["leg"], "runner:B")
        time.sleep(0.2)      # the shutdown ends the other legs too; the first one must stay
        self.assertEqual(self.router.stats["first_end"]["leg"], "runner:B")

    def test_server_closing_first_is_recorded_as_the_server(self):
        self.engine.close()
        self.assertEqual(self.wait_end()["leg"], "server")

    def test_oversized_frame_is_charged_to_the_runner_that_sent_it(self):
        import struct
        self.a.sendall(struct.pack(">I", SB.MAX_FRAME_BYTES + 1))
        end = self.wait_end()
        self.assertEqual(end["leg"], "runner:A")
        self.assertTrue(end["how"].startswith("error"))

    def test_a_missing_runner_shows_in_connected(self):
        with tempfile.TemporaryDirectory() as d:
            r = SB.Router(Path(d), 1, connect_timeout=0.6)
            c = socket.socket(socket.AF_UNIX)
            try:
                c.connect(str(r.paths["A"]))
                for _ in range(100):
                    if r.stats["error"]:
                        break
                    time.sleep(0.05)
                self.assertEqual(r.stats["connected"], ["A"])
                self.assertIn("never connected", r.stats["error"])
            finally:
                c.close()
                r.close()


def _server_pid(port: int) -> int | None:
    """PID of the engine server (the JVM listening on `port`); None unless it really is the server."""
    out = subprocess.run(["ss", "-ltnpH", f"sport = :{port}"], capture_output=True, text=True).stdout
    for part in out.split("pid=")[1:]:
        pid = int(part.split(",")[0])
        try:
            cmd = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
        except OSError:
            continue
        if "-Dbc.game." in cmd:        # the Battlecode server JVM, never a shared Gradle daemon
            return pid
    return None


@unittest.skipUnless(os.environ.get("BIO_INTEGRATION") == "1", "set BIO_INTEGRATION=1 to run real matches")
@unittest.skipUnless(shutil.which("bwrap") and shutil.which("ss"), "bubblewrap and ss are needed")
class MatchesWithFailures(unittest.TestCase):
    """Real matches; the failing side is injected, never mocked (TC-04)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.bots = Path(cls.tmp.name) / "bots"
        cls.bots.mkdir()
        shutil.copytree(EXAMPLE_BOT, cls.bots / "examplefuncsplayer_py")
        for name in ("crash_py", "segv_py", "exit0_py", "sigkill_py", "cpuload_py"):
            shutil.copytree(HERE / "bots" / name, cls.bots / name)
        cls.py = L.resolve_python(None, None, L.load_lock())

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def match(self, a, b, sandbox=True, timeout=90):
        with tempfile.TemporaryDirectory() as out:
            return L.run_match(L.DEFAULT_SCAFFOLD, self.py, self.bots, a, b, "DefaultSmall", Path(out),
                               timeout, True, True, sandbox=sandbox)

    def assert_bot_crash(self, bot, loser, status=None, sig=None, sandbox=True):
        other = "A" if loser == "B" else "B"
        names = {"A": "examplefuncsplayer_py", "B": "examplefuncsplayer_py"}
        names[loser] = bot
        r = self.match(names["A"], names["B"], sandbox=sandbox)
        self.assertEqual(r["classification"], "bot_crash", r)
        self.assertEqual(r["outcome"], "bot_failure")
        self.assertEqual((r["loser"], r["winner_by_forfeit"]), (loser, other))
        self.assertIsNone(r["winner"])      # the engine never finished this game
        self.assertFalse(r["ok"])
        ev = r["evidence"]
        self.assertEqual(ev["first_end"]["leg"], f"runner:{loser}")
        if status is not None:
            self.assertEqual(ev["exit_status"], status)
        self.assertEqual(ev["signal"], sig)
        self.assertLess(r["seconds"], 30)
        self.assertFalse(L.port_in_use(L.load_lock()["crossplay_port"]), "server must be stopped")
        return r

    def test_bot_that_exits_with_an_error_code_loses(self):
        self.assert_bot_crash("crash_py", "B", status=3)

    def test_bot_that_exits_with_code_zero_mid_game_loses(self):
        self.assert_bot_crash("exit0_py", "B", status=0)

    def test_bot_that_segfaults_loses(self):
        self.assert_bot_crash("segv_py", "B", status=139, sig="SIGSEGV")

    def test_bot_killed_by_sigkill_loses(self):
        self.assert_bot_crash("sigkill_py", "B", status=137, sig="SIGKILL")

    def test_the_crashing_bot_in_the_first_slot_loses_too(self):
        self.assert_bot_crash("crash_py", "A", status=3)

    def test_crash_without_the_sandbox_is_classified_the_same_way(self):
        self.assert_bot_crash("segv_py", "B", sig="SIGSEGV", sandbox=False)

    def test_normal_match_is_completed_and_the_server_closed_first(self):
        r = self.match("cpuload_py", "cpuload_py")
        self.assertEqual((r["classification"], r["outcome"]), ("normal", "completed"))
        self.assertEqual(r["router"]["first_end"]["leg"], "server")
        self.assertNotIn("loser", r)

    def test_engine_server_killed_mid_match_is_a_platform_failure_with_no_loser(self):
        port = L.load_lock()["crossplay_port"]
        killed = {}

        def killer():
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                pid = _server_pid(port)
                if pid:
                    time.sleep(1.2)       # let the game start; a match takes about 4 s
                    try:
                        os.kill(pid, signal.SIGKILL)
                        killed["pid"] = pid
                    except ProcessLookupError:
                        pass
                    return
                time.sleep(0.1)

        t = threading.Thread(target=killer, daemon=True)
        t.start()
        r = self.match("cpuload_py", "cpuload_py")
        t.join(5)
        self.assertIn("pid", killed, "the test never found the engine server to kill")
        self.assertEqual(r["classification"], "platform_failure", r)
        self.assertEqual(r["outcome"], "platform_failure")
        self.assertEqual(r["kind"], "engine_failure")
        self.assertNotIn("loser", r)
        self.assertNotIn("winner_by_forfeit", r)
        self.assertIsNone(r["winner"])
        self.assertFalse(r["ok"])
        self.assertEqual(r["router"]["first_end"]["leg"], "server")
        self.assertFalse(L.port_in_use(port))


if __name__ == "__main__":
    unittest.main()
