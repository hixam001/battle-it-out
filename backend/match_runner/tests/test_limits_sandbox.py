# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for the resource guard, the sandbox command and the result classification (BIO-203/204).

Unit tests always run. Tests that run real matches need `BIO_INTEGRATION=1`, the primary Python
environment from setup_env.py, Gradle offline and bubblewrap (they are skipped without bwrap).

    BIO_INTEGRATION=1 python3 -m unittest backend.match_runner.tests.test_limits_sandbox -v
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from backend.match_runner import guard as G
from backend.match_runner import launcher as L
from backend.match_runner import sandbox as SB
from backend.match_runner.tests import escape_probe as E

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
EXAMPLE_BOT = L.DEFAULT_SCAFFOLD / "src" / "examplefuncsplayer_py"
GOLDEN_EXAMPLE_REPLAY_SHA = "a08779089a8cc2b714bae4394502e4b4f34231c8ffd0fb4037b5ef6feaaac301"
GOOD = {"turn_wall_seconds": 1, "init_wall_seconds": 2, "memory_rss_mb": 512, "address_space_mb": 4096,
        "cpu_seconds": 900, "open_files": 256, "output_bytes": 1 << 24, "max_tasks": 512}


class LimitsProfile(unittest.TestCase):
    def test_valid_profile(self):
        self.assertEqual(G.Limits.from_dict(GOOD).max_tasks, 512)

    def test_missing_unknown_and_bad_values_are_rejected(self):
        for bad in ({k: v for k, v in GOOD.items() if k != "memory_rss_mb"},
                    {**GOOD, "extra": 1}, {**GOOD, "turn_wall_seconds": 0}, {**GOOD, "turn_wall_seconds": -1},
                    {**GOOD, "turn_wall_seconds": "1"}, {**GOOD, "open_files": True}):
            with self.assertRaises(ValueError, msg=str(bad)):
                G.Limits.from_dict(bad)

    def test_provisional_profile_loads_and_is_labelled_unapproved(self):
        limits, doc = G.load_profile(L.DEFAULT_LIMITS)
        self.assertIsInstance(limits, G.Limits)
        self.assertIn("NOT APPROVED", doc["_status"])


class TeamAttribution(unittest.TestCase):
    def test_labels_follow_call_order_even_when_a_slot_is_empty(self):
        g = G.Guard(None)
        code_b = {"bot": "x"}
        g.register_code(None)      # team A has no bot
        g.register_code(code_b)    # team B
        self.assertEqual(g.team_of(code_b), "B")
        self.assertEqual(g.team_of({"bot": "other"}), "?")

    def test_same_bot_for_both_teams_gets_two_labels(self):
        g = G.Guard(None)
        a, b = {"bot": "same"}, {"bot": "same"}
        g.register_code(a)
        g.register_code(b)
        self.assertEqual((g.team_of(a), g.team_of(b)), ("A", "B"))

    def test_stats_and_exception_counting(self):
        g = G.Guard(None)
        g.begin("A", "turn"); g.end()
        g.begin("A", "init"); g.end()
        g.count_exception(False)
        s = g.usage()["teams"]["A"]
        self.assertEqual((s["turns"], s["inits"], s["exceptions"]), (1, 1, 1))


class GuardKillsProcess(unittest.TestCase):
    """The watchdog ends the process with a record; run it in a child process (it calls os._exit)."""

    def run_child(self, body: str):
        code = ("import sys, time; sys.path.insert(0, %r)\n"
                "from backend.match_runner import guard as G\n"
                "lim = G.Limits.from_dict(%r)\n" % (str(REPO), {**GOOD, "turn_wall_seconds": 0.2})) + body
        return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30)

    def test_turn_over_wall_limit_is_a_bot_violation(self):
        r = self.run_child("g = G.Guard(lim); g.start(); g.last_msg = {'round': 7, 'id': 42}\n"
                           "g.begin('B', 'turn'); time.sleep(5)\n")
        self.assertEqual(r.returncode, G.EXIT_VIOLATION)
        rec = L.parse_guard_records(r.stdout)["violation"]
        self.assertEqual((rec["team"], rec["kind"], rec["round"], rec["robot_id"]), ("B", "turn_wall_time", 7, 42))
        self.assertGreater(rec["measured"], 0.2)

    def test_turn_within_limit_is_fine(self):
        r = self.run_child("g = G.Guard(lim); g.start(); g.begin('A', 'turn'); time.sleep(0.05); g.end(); g.stop()\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("BIO-GUARD-VIOLATION", r.stdout)

    def test_memory_over_limit_at_turn_end_is_charged_to_that_team(self):
        r = self.run_child("lim = G.Limits.from_dict({**%r, 'memory_rss_mb': 60})\n"
                           "g = G.Guard(lim); g.begin('A', 'turn'); junk = bytearray(200 << 20); junk[::4096] = b'x' * len(junk[::4096]); g.end()\n"
                           % GOOD)
        self.assertEqual(r.returncode, G.EXIT_VIOLATION)
        rec = L.parse_guard_records(r.stdout)["violation"]
        self.assertEqual((rec["team"], rec["kind"]), ("A", "memory"))


class Classification(unittest.TestCase):
    clean = {"server_errors": [], "finished": True}

    def test_normal(self):
        self.assertEqual(L.classify(self.clean, None, 0, False)["classification"], "normal")

    def test_bot_violation_names_loser_and_forfeit_winner(self):
        c = L.classify(self.clean, {"team": "A", "kind": "turn_wall_time"}, 70, False)
        self.assertEqual((c["classification"], c["loser"], c["winner_by_forfeit"]), ("bot_violation", "A", "B"))
        self.assertEqual(L.classify(self.clean, {"team": "B"}, 70, False)["winner_by_forfeit"], "A")

    def test_no_team_is_a_platform_failure_not_a_bot_loss(self):
        self.assertEqual(L.classify(self.clean, {"team": None, "kind": "memory"}, 71, False)["classification"],
                         "platform_failure")

    def test_timeout_crash_and_server_error_are_platform_failures(self):
        self.assertEqual(L.classify(self.clean, None, None, True)["classification"], "platform_failure")
        self.assertEqual(L.classify(self.clean, None, 1, False)["classification"], "platform_failure")
        self.assertEqual(L.classify({"server_errors": ["x"], "finished": True}, None, 0, False)["classification"],
                         "platform_failure")
        self.assertEqual(L.classify({"server_errors": [], "finished": False}, None, 0, False)["classification"],
                         "platform_failure")

    def test_parse_guard_records_ignores_garbage_and_takes_last(self):
        text = ('noise\nBIO-GUARD-USAGE {"a":1}\nBIO-GUARD-USAGE {broken\nBIO-GUARD-USAGE {"a":2}\n'
                'BIO-GUARD-VIOLATION {"team":"A"}\n')
        self.assertEqual(L.parse_guard_records(text), {"usage": {"a": 2}, "violation": {"team": "A"}})


@unittest.skipUnless(shutil.which("bwrap"), "bubblewrap not installed")
class SandboxCommand(unittest.TestCase):
    def cmd(self):
        py = L.resolve_python(None, None, L.load_lock())
        return SB.build_command(py, L.HERE / "runner_entry.py",
                                {"A": Path("/srv/bots/alpha"), "B": Path("/srv/bots/beta")},
                                Path("/tmp/x.sock"), L.DEFAULT_LIMITS, [])

    def test_namespaces_and_hardening_flags(self):
        cmd = self.cmd()
        for flag in ("--unshare-user", "--unshare-pid", "--unshare-net", "--unshare-ipc", "--die-with-parent",
                     "--new-session", "--clearenv", "--remount-ro"):
            self.assertIn(flag, cmd)
        self.assertEqual(cmd[cmd.index("--cap-drop") + 1], "ALL")

    def test_only_the_two_bot_folders_are_mounted_and_read_only(self):
        cmd = self.cmd()
        self.assertEqual(cmd.count("/srv/bots"), 0)  # the parent directory (other participants) is never mounted
        pairs = [(cmd[i + 1], cmd[i + 2]) for i, a in enumerate(cmd) if a in ("--ro-bind", "--bind")]
        self.assertIn(("/srv/bots/alpha", "/work/A/alpha"), pairs)
        self.assertIn(("/srv/bots/beta", "/work/B/beta"), pairs)
        writable = [cmd[i + 2] for i, a in enumerate(cmd) if a == "--bind"]
        self.assertEqual(writable, ["/ipc/engine.sock"])
        self.assertNotIn("/home", [dst for _, dst in pairs])

    def test_runner_arguments(self):
        cmd = self.cmd()
        tail = cmd[cmd.index("-I") - 1:]
        for arg in ("--in-sandbox", "--limits", "--ipc-socket"):
            self.assertIn(arg, tail)
        self.assertEqual(tail[tail.index("--teamA") + 1], "alpha")
        self.assertEqual(tail[tail.index("--dirB") + 1], "/work/B")


class BridgeForwards(unittest.TestCase):
    def test_bytes_pass_both_ways_unchanged(self):
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0)); srv.listen(1)
        port = srv.getsockname()[1]
        seen = []

        def server():
            c, _ = srv.accept()
            seen.append(c.recv(100))
            c.sendall(b"pong\x00\xff")
            c.close()

        threading.Thread(target=server, daemon=True).start()
        with tempfile.TemporaryDirectory() as d:
            bridge = SB.Bridge(Path(d) / "s.sock", port)
            try:
                c = socket.socket(socket.AF_UNIX)
                c.connect(str(bridge.path))
                c.sendall(b"ping\x01")
                got = b""
                while len(got) < 6:
                    chunk = c.recv(10)
                    if not chunk:
                        break
                    got += chunk
                c.close()
            finally:
                bridge.close()
        srv.close()
        self.assertEqual(seen, [b"ping\x01"])
        self.assertEqual(got, b"pong\x00\xff")


# ---------------------------------------------------------------------------------------------
@unittest.skipUnless(os.environ.get("BIO_INTEGRATION") == "1", "set BIO_INTEGRATION=1 to run real matches")
@unittest.skipUnless(shutil.which("bwrap"), "bubblewrap not installed")
class MatchesUnderLimits(unittest.TestCase):
    """Real matches through the engine, the sandbox and the guard."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.bots = Path(cls.tmp.name) / "bots"
        cls.bots.mkdir()
        shutil.copytree(EXAMPLE_BOT, cls.bots / "examplefuncsplayer_py")
        for name in ("hang_py", "hang_init_py", "memhog_py", "allocbomb_py", "cpuload_py"):
            shutil.copytree(HERE / "bots" / name, cls.bots / name)
        cls.py = L.resolve_python(None, None, L.load_lock())

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def match(self, a, b, sandbox=True, timeout=90):
        with tempfile.TemporaryDirectory() as out:
            return L.run_match(L.DEFAULT_SCAFFOLD, self.py, self.bots, a, b, "DefaultSmall", Path(out),
                               timeout, True, True, sandbox=sandbox)

    def test_normal_match_in_sandbox_matches_unsandboxed_golden_replay(self):
        r = self.match("examplefuncsplayer_py", "examplefuncsplayer_py")
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["classification"], "normal")
        self.assertEqual(r["replay_sha256"], GOLDEN_EXAMPLE_REPLAY_SHA)
        self.assertEqual((r["winner"], r["round"]), ("A", 1290))
        self.assertLess(r["seconds"], 30)
        self.assertGreater(r["usage"]["teams"]["A"]["turns"], 1000)

    def test_usage_is_measured(self):
        u = self.match("cpuload_py", "cpuload_py")["usage"]
        self.assertGreater(u["peak_rss_mib"], 5)
        self.assertGreater(u["teams"]["A"]["max_turn_seconds"], 0)
        self.assertGreaterEqual(u["peak_threads"], 2)

    def assert_forfeit(self, bot, kind, sandbox):
        r = self.match("examplefuncsplayer_py", bot, sandbox=sandbox)
        self.assertEqual(r["classification"], "bot_violation", r)
        self.assertEqual((r["loser"], r["winner_by_forfeit"], r["violation"]["kind"]), ("B", "A", kind))
        self.assertFalse(r["ok"])
        self.assertIsNone(r["winner"])   # the engine never finished this game: no engine winner is reported
        self.assertLess(r["seconds"], 40)
        self.assertFalse(L.port_in_use(L.load_lock()["crossplay_port"]), "server must be stopped")

    def test_endless_turn_is_a_forfeit_for_the_right_team(self):
        self.assert_forfeit("hang_py", "turn_wall_time", True)

    def test_endless_turn_without_sandbox_is_also_caught(self):
        self.assert_forfeit("hang_py", "turn_wall_time", False)

    def test_endless_init_is_a_forfeit(self):
        self.assert_forfeit("hang_init_py", "init_wall_time", True)

    def test_memory_growth_is_a_forfeit(self):
        self.assert_forfeit("memhog_py", "memory", True)

    def test_huge_single_allocation_kills_only_that_robot_and_is_counted(self):
        r = self.match("examplefuncsplayer_py", "allocbomb_py")
        self.assertEqual(r["classification"], "normal", r)  # engine behaviour: the robot dies, the match goes on
        self.assertGreaterEqual(r["usage"]["teams"]["B"]["exceptions"], 1)
        self.assertEqual(r["usage"]["teams"]["A"]["exceptions"], 0)

    def test_hostile_bot_cannot_reach_host_files_network_or_processes(self):
        listener = E.HostListener()
        try:
            work = Path(self.tmp.name) / "escape"
            canary = work / "canary.txt"
            work.mkdir(exist_ok=True)
            canary.write_text("SECRET-CANARY-123")
            (work / "bots").mkdir(exist_ok=True)
            shutil.copytree(EXAMPLE_BOT, work / "bots" / "examplefuncsplayer_py", dirs_exist_ok=True)
            E.stage_escape_bot(work / "bots", canary, listener.port, 3000, REPO)
            with tempfile.TemporaryDirectory() as out:
                r = L.run_match(L.DEFAULT_SCAFFOLD, self.py, work / "bots", "escape_py", "examplefuncsplayer_py",
                                "DefaultSmall", Path(out), 90, True, True, sandbox=True,
                                limits_path=self.relaxed_turn_profile(Path(out)))
                probes = E.probe_lines(Path(r["logs"]["server"]))
                log = Path(r["logs"]["server"]).read_text()
        finally:
            listener.close()
        self.assertEqual(listener.hits, 0, "a sandboxed bot reached a service on the host's loopback")
        self.assertNotIn("SECRET-CANARY-123", log)
        for name in ("read_canary", "connect_host_loopback", "connect_internet", "write_bot_dir", "write_usr"):
            self.assertTrue(probes[name].startswith("BLOCKED"), f"{name}: {probes.get(name)}")
        self.assertEqual(probes["visible_pids"], "OK 2")   # only the sandbox's own processes
        forks = int(probes["fork_count"])
        self.assertLess(forks, GOOD["max_tasks"], "fork bomb must hit the process limit")
        self.assertGreater(forks, 0)

    def relaxed_turn_profile(self, out: Path) -> Path:
        """The escape bot sleeps while forking; give turns enough time so only the sandbox is under test."""
        doc = json.loads(L.DEFAULT_LIMITS.read_text())
        doc["limits"]["turn_wall_seconds"] = 20
        p = out / "limits-relaxed.json"
        p.write_text(json.dumps(doc))
        return p


if __name__ == "__main__":
    unittest.main()
