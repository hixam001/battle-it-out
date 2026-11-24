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
        self.assertIn("INTERIM", doc["_status"])
        self.assertIn("NOT benchmark-approved", doc["_status"])


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
    def cmd(self, team="A", fd=None):
        py = L.resolve_python(None, None, L.load_lock())
        return SB.build_command(py, L.HERE / "runner_entry.py", team, Path("/srv/bots/alpha"),
                                Path("/tmp/x.sock"), L.DEFAULT_LIMITS, [], seccomp_fd=fd)

    def test_namespaces_and_hardening_flags(self):
        cmd = self.cmd(fd=9)
        for flag in ("--unshare-user", "--unshare-pid", "--unshare-net", "--unshare-ipc", "--die-with-parent",
                     "--new-session", "--clearenv", "--remount-ro", "--seccomp"):
            self.assertIn(flag, cmd)
        self.assertEqual(cmd[cmd.index("--cap-drop") + 1], "ALL")
        self.assertEqual(cmd[cmd.index("--seccomp") + 1], "9")

    def test_only_this_teams_own_folder_is_mounted_read_only(self):
        for team, other in (("A", "B"), ("B", "A")):
            cmd = self.cmd(team)
            self.assertEqual(cmd.count("/srv/bots"), 0)  # the parent directory (other participants) is never mounted
            pairs = [(cmd[i + 1], cmd[i + 2]) for i, a in enumerate(cmd) if a in ("--ro-bind", "--bind")]
            self.assertIn(("/srv/bots/alpha", f"/work/{team}/alpha"), pairs)
            self.assertFalse([dst for _, dst in pairs if dst.startswith(f"/work/{other}")])
            writable = [cmd[i + 2] for i, a in enumerate(cmd) if a == "--bind"]
            self.assertEqual(writable, ["/ipc/engine.sock"])
            self.assertNotIn("/home", [dst for _, dst in pairs])

    def test_runner_arguments(self):
        tail = self.cmd("B")
        tail = tail[tail.index("-I") - 1:]
        for arg in ("--in-sandbox", "--limits", "--ipc-socket"):
            self.assertIn(arg, tail)
        self.assertEqual(tail[tail.index("--teamB") + 1], "alpha")
        self.assertEqual(tail[tail.index("--dirB") + 1], "/work/B")
        self.assertNotIn("--teamA", tail)   # the other slot stays "/" (no bot) in this process

    def test_bad_team_is_rejected(self):
        with self.assertRaises(ValueError):
            self.cmd("C")


class Seccomp(unittest.TestCase):
    def test_program_shape(self):
        prog = SB.seccomp_program()
        self.assertEqual(len(prog) % 8, 0)
        self.assertLess(len(prog), 4096)
        # Every instruction is a valid classic-BPF load, jump or return.
        import struct
        n = len(prog) // 8
        for i in range(n):
            code, jt, jf, k = struct.unpack_from("<HBBI", prog, i * 8)
            self.assertIn(code, (0x20, 0x15, 0x45, 0x06))
            if code in (0x15, 0x45):
                self.assertLess(i + 1 + jt, n)
                self.assertLess(i + 1 + jf, n)
        self.assertEqual(struct.unpack_from("<HBBI", prog, (n - 1) * 8)[3], SB.SECCOMP_RET_ALLOW)

    @unittest.skipUnless(shutil.which("bwrap"), "bubblewrap not installed")
    def test_filter_blocks_dangerous_calls_and_keeps_threads_and_fork(self):
        code = (
            "import ctypes, threading, os, errno\n"
            "libc = ctypes.CDLL(None, use_errno=True)\n"
            "def call(n):\n"
            "    r = libc.syscall(n, 0, 0, 0, 0); return r, errno.errorcode.get(ctypes.get_errno())\n"
            "print('ptrace', *call(101)); print('bpf', *call(321)); print('io_uring', *call(425))\n"
            "try:\n    os.unshare(os.CLONE_NEWUSER); print('unshare allowed')\n"
            "except OSError as e: print('unshare', errno.errorcode[e.errno])\n"
            "out = []; t = [threading.Thread(target=lambda i=i: out.append(i)) for i in range(20)]\n"
            "[x.start() for x in t]; [x.join() for x in t]; print('threads', len(out))\n"
            "pid = os.fork()\n"
            "if pid == 0: os._exit(0)\n"
            "os.waitpid(pid, 0); print('fork ok')\n")
        py = L.resolve_python(None, None, L.load_lock())
        fd = SB.seccomp_pipe()
        try:
            r = subprocess.run(SB.build_probe_command(py, code, fd), capture_output=True, text=True,
                               pass_fds=(fd,), timeout=60)
        finally:
            os.close(fd)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout.splitlines()
        self.assertEqual(out, ["ptrace -1 EPERM", "bpf -1 EPERM", "io_uring -1 EPERM", "unshare EPERM",
                               "threads 20", "fork ok"])


class Routing(unittest.TestCase):
    def test_spawn_and_start_turn_select_the_owner(self):
        owner = {}
        self.assertEqual(SB.route_for({"type": "spawn_bot", "team": 1, "id": 7}, owner, "A"), (["B"], "B"))
        self.assertEqual(SB.route_for({"type": "spawn_bot", "team": 0, "id": 3}, owner, "B"), (["A"], "A"))
        self.assertEqual(SB.route_for({"type": "start_turn", "id": 7, "round": 5}, owner, "A"), (["B"], "B"))
        self.assertEqual(SB.route_for({"type": "start_turn", "id": 3, "round": 5}, owner, "B"), (["A"], "A"))

    def test_destroy_goes_to_owner_without_changing_current(self):
        owner = {7: "B", 3: "A"}
        self.assertEqual(SB.route_for({"type": "destroy_bot", "id": 7}, owner, "A"), (["B"], "A"))
        self.assertEqual(SB.route_for({"type": "destroy_bot", "id": 3}, owner, "A"), (["A"], "A"))

    def test_end_game_goes_to_both_and_replies_to_current(self):
        self.assertEqual(SB.route_for({"type": "end_game"}, {}, "B"), (["A", "B"], "B"))
        for reply in (None, 5, "x", [1, 2], {"type": 2, "x": 1, "y": 2}, {"type": "unknown"}):
            self.assertEqual(SB.route_for(reply, {}, "B"), (["B"], "B"))

    def test_unknown_robot_falls_back_to_current(self):
        self.assertEqual(SB.route_for({"type": "start_turn", "id": 99}, {}, "B"), (["B"], "B"))


def _send_frame(sock, payload: bytes):
    import struct
    sock.sendall(struct.pack(">I", len(payload)) + payload)


def _recv_frame(sock):
    import struct
    head = b""
    while len(head) < 4:
        c = sock.recv(4 - len(head))
        if not c:
            return None
        head += c
    (n,) = struct.unpack(">I", head)
    body = b""
    while len(body) < n:
        body += sock.recv(n - len(body))
    return body


class RouterForwards(unittest.TestCase):
    """A fake engine server and two fake runners: frames are routed and never mixed up. Runner frames are
    rebuilt from their parsed content (same message, canonical bytes; see test_structured_log.py)."""

    def test_end_to_end_routing(self):
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0)); srv.listen(1)
        port = srv.getsockname()[1]
        with tempfile.TemporaryDirectory() as d:
            router = SB.Router(Path(d), port)
            a = socket.socket(socket.AF_UNIX); b = socket.socket(socket.AF_UNIX); engine = socket.socket()
            try:
                a.connect(str(router.paths["A"]))
                b.connect(str(router.paths["B"]))
                for s_ in (a, b):
                    s_.settimeout(5)
                engine.close()
                engine, _ = srv.accept()
                engine.settimeout(5)
                # spawn for team B reaches only B; B's answer reaches the server unchanged
                _send_frame(engine, json.dumps({"type": "spawn_bot", "team": 1, "id": 4}).encode())
                self.assertEqual(json.loads(_recv_frame(b))["id"], 4)
                _send_frame(b, b"null")
                self.assertEqual(_recv_frame(engine), b"null")
                # a reply while B is current goes to B; a destroy for A's robot goes to A only
                _send_frame(engine, json.dumps({"type": "spawn_bot", "team": 0, "id": 3}).encode())
                self.assertEqual(json.loads(_recv_frame(a))["id"], 3)
                _send_frame(a, b"null"); self.assertEqual(_recv_frame(engine), b"null")
                _send_frame(engine, json.dumps({"type": "start_turn", "id": 4, "round": 1}).encode())
                self.assertEqual(json.loads(_recv_frame(b))["round"], 1)
                _send_frame(b, b'{"method":13,"params":[]}')
                self.assertEqual(_recv_frame(engine), b'{"method": 13, "params": []}')   # rebuilt, same content
                _send_frame(engine, json.dumps({"type": "destroy_bot", "id": 3}).encode())   # nested notice
                self.assertEqual(json.loads(_recv_frame(a))["type"], "destroy_bot")
                _send_frame(a, b"null")
                self.assertEqual(_recv_frame(engine), b"null")
                _send_frame(engine, b"17")                                                  # the reply B waits for
                self.assertEqual(_recv_frame(b), b"17")
                # end_game reaches both
                _send_frame(engine, json.dumps({"type": "end_game"}).encode())
                self.assertEqual(json.loads(_recv_frame(a))["type"], "end_game")
                self.assertEqual(json.loads(_recv_frame(b))["type"], "end_game")
                self.assertIsNone(router.stats["error"])
            finally:
                for sock in (a, b, engine):
                    sock.close()
                router.close(); srv.close()

    def test_oversized_runner_frame_ends_the_connection(self):
        import struct
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0)); srv.listen(1)
        with tempfile.TemporaryDirectory() as d:
            router = SB.Router(Path(d), srv.getsockname()[1])
            a = socket.socket(socket.AF_UNIX); b = socket.socket(socket.AF_UNIX); engine = socket.socket()
            try:
                a.connect(str(router.paths["A"]))
                b.connect(str(router.paths["B"]))
                engine.close()
                engine, _ = srv.accept()
                a.sendall(struct.pack(">I", SB.MAX_FRAME_BYTES + 1))
                b.settimeout(5)
                self.assertEqual(b.recv(10), b"")        # the whole match connection is closed
                self.assertIn("exceeds", router.stats["error"])
            finally:
                for sock in (a, b, engine):
                    sock.close()
                router.close(); srv.close()


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
        for name in ("hang_py", "hang_init_py", "memhog_py", "allocbomb_py", "cpuload_py", "forge_py"):
            shutil.copytree(HERE / "bots" / name, cls.bots / name)
        cls.py = L.resolve_python(None, None, L.load_lock())

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def match(self, a, b, sandbox=True, timeout=90):
        with tempfile.TemporaryDirectory() as out:
            return L.run_match(L.DEFAULT_SCAFFOLD, self.py, self.bots, a, b, "DefaultSmall", Path(out),
                               timeout, True, True, sandbox=sandbox)

    def test_normal_match_in_sandbox_runs_both_teams_to_the_end(self):
        r = self.match("examplefuncsplayer_py", "examplefuncsplayer_py")
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["classification"], "normal")
        self.assertEqual(r["runner_exit"], {"A": 0, "B": 0})
        self.assertIsNone(r["router"]["error"])
        self.assertEqual(r["round"], 1310)   # both teams play identical seeded bots: a tie decided by the engine
        self.assertIn(r["winner"], ("A", "B"))
        self.assertLess(r["seconds"], 30)
        t = r["usage"]["teams"]
        self.assertEqual(t["A"]["turns"], 1310)
        self.assertEqual(t["B"]["turns"], 1310)
        self.assertEqual(set(r["usage"]["processes"]), {"A", "B"})

    def test_sandbox_and_plain_runs_play_the_same_game(self):
        sand = self.match("cpuload_py", "cpuload_py")
        plain = self.match("cpuload_py", "cpuload_py", sandbox=False)
        self.assertEqual((sand["classification"], plain["classification"]), ("normal", "normal"))
        self.assertEqual(sand["round"], plain["round"])

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

    def test_forged_guard_record_is_charged_to_the_process_that_wrote_it(self):
        # Team B prints a record that blames team A and exits like the guard. Team B is the loser.
        r = self.match("examplefuncsplayer_py", "forge_py")
        self.assertEqual(r["classification"], "bot_violation", r)
        self.assertEqual((r["loser"], r["winner_by_forfeit"]), ("B", "A"))
        self.assertEqual(r["violation"]["claimed_team"], "A")
        self.assertEqual(r["violation"]["team"], "B")

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
        self.assertEqual(probes["list_work"], "OK ['A', 'limits.json']")   # the opposing team's code is not mounted
        self.assertTrue(probes["read_other_team"].startswith("BLOCKED"), probes["read_other_team"])
        self.assertTrue(probes["ptrace"].startswith("BLOCKED"), probes["ptrace"])
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
