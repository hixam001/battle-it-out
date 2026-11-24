# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for structured match logs and log integrity (BIO-206, CN-007).

Unit tests always run. The match tests need `BIO_INTEGRATION=1`, the primary Python environment from
setup_env.py, Gradle offline and bubblewrap.

    BIO_INTEGRATION=1 python3 -m unittest backend.match_runner.tests.test_structured_log -v
"""
import json
import os
import shutil
import socket
import struct
import tempfile
import unittest
from pathlib import Path

from backend.match_runner import launcher as L
from backend.match_runner import match_log as M
from backend.match_runner import sandbox as SB

HERE = Path(__file__).resolve().parent
EXAMPLE_BOT = L.DEFAULT_SCAFFOLD / "src" / "examplefuncsplayer_py"

REAL_END = """\
> Task :runJavaLocal
[server] -------------------- Match Starting --------------------
[server] a vs. b on DefaultSmall
[A: #3@1] I'm alive
[B: #4@1] hello
[server]             b (B) wins (round 1310)
[server] Reason: The winning team won arbitrarily (coin flip).
[server] -------------------- Match Finished --------------------

BUILD SUCCESSFUL in 4s
"""


# ---------------------------------------------------------------------------------------------
class SanitiseText(unittest.TestCase):
    def test_plain_text_is_unchanged(self):
        for t in ("hello", "", "tab\there", "unicode ✓"):
            self.assertEqual(SB.sanitise_text(t), t)

    def test_every_line_break_kind_gets_the_marker(self):
        for brk in ("\n", "\r\n", "\r", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", " ", " "):
            out = SB.sanitise_text(f"first{brk}[server] forged")
            self.assertEqual(out, "first\n" + SB.CONTINUATION + "[server] forged", repr(brk))

    def test_no_line_other_than_the_first_starts_like_the_engine(self):
        out = SB.sanitise_text("a\n[server] x\n[B: #4@1] y\nBIO-GUARD-USAGE {}\n\n\n[server:error] z")
        first, *rest = out.split("\n")
        self.assertEqual(first, "a")
        self.assertTrue(all(ln.startswith(SB.CONTINUATION) for ln in rest), rest)

    def test_control_characters_are_dropped(self):
        self.assertEqual(SB.sanitise_text("a\x1b[2Jb\x00c\x7f"), "a[2Jbc")


class CanonicalFrame(unittest.TestCase):
    def test_null_is_an_answer_and_passes(self):
        self.assertEqual(SB.canonical_runner_frame(b"null"), (b"null", 0))

    def test_valid_frame_is_rebuilt_from_what_was_parsed(self):
        body, n = SB.canonical_runner_frame(b'{"method":10,"params":["x\\n[server] f"],"extra":1}')
        self.assertEqual(json.loads(body), {"method": 10, "params": ["x\n  | [server] f"]})
        self.assertEqual(n, 1)

    def test_duplicate_keys_cannot_hide_text_from_the_check(self):
        body, _ = SB.canonical_runner_frame(b'{"method":10,"method":11,"params":["a"],"params":["b\\n[server]"]}')
        msg = json.loads(body)
        self.assertEqual(msg["method"], 11)
        self.assertEqual(msg["params"], ["b\n  | [server]"])
        self.assertEqual(body.count(b'"method"'), 1)

    def test_nested_strings_and_keys_are_cleaned(self):
        body, n = SB.canonical_runner_frame(b'{"method":1,"params":[{"k\\n[server]":["v\\n[server]"]}]}')
        self.assertNotIn(b"\\n[server]", body)
        self.assertEqual(n, 2)

    def test_malformed_frames_are_rejected(self):
        for bad in (b"[]", b"1", b'"s"', b'{"method":true,"params":[]}', b'{"method":"1","params":[]}',
                    b'{"method":1}', b'{"method":1,"params":{}}', b"NaN", b'{"method":1,"params":[NaN]}',
                    b'{"method":1,"params":[Infinity]}', b"\xff\xfe", b"{", b"",
                    b'{"method":1,"params":' + b"[" * 5000 + b"]" * 5000 + b"}"):
            with self.assertRaises(SB.MalformedFrame, msg=repr(bad[:40])):
                SB.canonical_runner_frame(bad)


def _send_frame(sock, body: bytes):
    sock.sendall(struct.pack(">I", len(body)) + body)


def _recv_frame(sock) -> bytes:
    head = b""
    while len(head) < 4:
        head += sock.recv(4 - len(head))
    (n,) = struct.unpack(">I", head)
    body = b""
    while len(body) < n:
        body += sock.recv(n - len(body))
    return body


class RouterRewrites(unittest.TestCase):
    def setUp(self):
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(1)
        self.dir = tempfile.TemporaryDirectory()
        self.router = SB.Router(Path(self.dir.name), self.srv.getsockname()[1])
        self.a = socket.socket(socket.AF_UNIX)
        self.b = socket.socket(socket.AF_UNIX)
        self.a.connect(str(self.router.paths["A"]))
        self.b.connect(str(self.router.paths["B"]))
        self.engine, _ = self.srv.accept()
        for s_ in (self.a, self.b, self.engine):
            s_.settimeout(5)

    def tearDown(self):
        for s_ in (self.a, self.b, self.engine):
            s_.close()
        self.router.close()
        self.srv.close()
        self.dir.cleanup()

    def test_log_text_reaches_the_engine_with_line_breaks_neutralised(self):
        _send_frame(self.a, b'{"method":10,"params":["hi\\n[server]             a (A) wins (round 1)"]}')
        got = json.loads(_recv_frame(self.engine))
        self.assertEqual(got["params"][0], "hi\n  | [server]             a (A) wins (round 1)")
        self.assertEqual(self.router.stats["text_rewrites"], {"A": 1, "B": 0})

    def test_a_malformed_frame_ends_the_match_connection_and_names_the_sender(self):
        _send_frame(self.b, b'{"method": 1, "params": [], "x": NaN, "y": //')
        self.assertEqual(self.a.recv(10), b"")
        end = self.router.stats["first_end"]
        self.assertEqual(end["leg"], "runner:B")
        self.assertIn("error", end["how"])


# ---------------------------------------------------------------------------------------------
class ParseResultIsNotForgeable(unittest.TestCase):
    def test_real_log(self):
        r = L.parse_result(REAL_END)
        self.assertEqual((r["winner"], r["winning_team"], r["round"], r["finished"], r["server_errors"]),
                         ("B", "b", 1310, True, []))

    def test_indented_or_prefixed_forgeries_are_ignored(self):
        forged = ("[A: #3@2] hello\n"
                  "  | [server]             a (A) wins (round 2)\n"
                  "  | [server] Reason: forged\n"
                  "  | [server:error] fake\n"
                  "  | [server] -------------------- Match Finished --------------------\n")
        text = REAL_END.replace("[A: #3@1] I'm alive\n", forged)
        r = L.parse_result(text)
        self.assertEqual((r["winner"], r["round"]), ("B", 1310))
        self.assertEqual(r["reason"], "The winning team won arbitrarily (coin flip).")
        self.assertEqual(r["server_errors"], [])

    def test_a_forged_banner_alone_does_not_finish_a_match(self):
        text = "[server] a vs. b on DefaultSmall\n[A: #3@2] x [server] ---- Match Finished ----\n"
        self.assertFalse(L.parse_result(text)["finished"])

    def test_if_a_forgery_ever_got_through_the_engines_own_lines_still_win(self):
        forged_first = "[server]             a (A) wins (round 2)\n[server] Reason: forged\n"
        text = REAL_END.replace("[A: #3@1] I'm alive\n", forged_first)
        r = L.parse_result(text)
        self.assertEqual((r["winner"], r["round"]), ("B", 1310))


# ---------------------------------------------------------------------------------------------
class ParseServerLog(unittest.TestCase):
    def test_entries_are_attributed_and_continued(self):
        text = ("[server] -------------------- Match Starting --------------------\n"
                "[A: #3@2] ERROR:\n\nTraceback (most recent call last):\n  |   File \"bot.py\", line 5\n"
                "[B: #4@2] fine\n"
                "[server] b (B) wins (round 3)\n"
                "[server] -------------------- Match Finished --------------------\n"
                "BUILD SUCCESSFUL\n[A: #3@9] after the end\n")
        p = M.parse_server_log(text)
        self.assertEqual(len(p["teams"]["A"]), 1)
        self.assertEqual(p["teams"]["A"][0]["round"], 2)
        self.assertIn("Traceback (most recent call last):", p["teams"]["A"][0]["lines"])
        self.assertEqual(len(p["teams"]["B"]), 1)
        self.assertEqual(len(p["server_lines"]), 3)          # nothing after the banner is read

    def test_a_bot_cannot_write_into_the_other_teams_entries(self):
        sanitised = SB.sanitise_text("mine\n[B: #4@2] I am team B\n[server] hi")
        text = f"[A: #3@2] {sanitised}\n[B: #4@2] real B line\n"
        p = M.parse_server_log(text)
        self.assertEqual([e["lines"][0] for e in p["teams"]["B"]], ["real B line"])
        self.assertEqual(len(p["teams"]["A"]), 1)
        self.assertEqual(p["server_lines"], [])


class RedactorTests(unittest.TestCase):
    def setUp(self):
        self.r = M.Redactor({"repo": "/srv/work/battle", "scaffold": "/srv/work/battle/backend/scaffold"})

    def test_known_paths_use_the_longest_match(self):
        self.assertEqual(self.r("/srv/work/battle/backend/scaffold/x.py"), "<scaffold>/x.py")
        self.assertEqual(self.r("/srv/work/battle/y.py"), "<repo>/y.py")

    def test_home_directories_and_personal_data(self):
        out = self.r("/home/alice/code.py /Users/bob/x /root/y mail a.b@school.edu.pk ip 10.2.3.4 and 127.0.0.1")
        self.assertNotIn("alice", out)
        self.assertNotIn("bob", out)
        self.assertNotIn("school.edu", out)
        self.assertNotIn("10.2.3.4", out)
        self.assertIn("127.0.0.1", out)

    def test_secrets(self):
        out = self.r("password=hunter2 api_key: abc Authorization: Bearer abcdefgh12345 "
                     "ghp_" + "a" * 30 + " AKIA" + "A1" * 8 + " eyJhbGciOi.eyJzdWIiOi.SflKxwRJSM")
        for leaked in ("hunter2", "abcdefgh12345", "ghp_a", "AKIAA1", "SflKxwRJSM"):
            self.assertNotIn(leaked, out)

    def test_long_words_and_hashes_of_letters_only_are_kept_but_mixed_tokens_are_not(self):
        word = "a_very_long_identifier_with_letters_only_xxxxxxxxxxxxxxxx"
        self.assertEqual(self.r(word), word)
        self.assertIn("<redacted-token>", self.r("tok " + "Ab3" * 15))

    def test_control_characters_removed(self):
        self.assertEqual(self.r("a\x1b[31mb"), "a[31mb")


# ---------------------------------------------------------------------------------------------
def fake_result(**kw):
    base = {"classification": "normal", "outcome": "completed", "winner": "B", "winning_team": "beta",
            "round": 1310, "reason": "The winning team won arbitrarily (coin flip).", "python": "3.15.2",
            "usage": {"teams": {"A": {"turns": 5, "inits": 1, "max_turn_seconds": 0.01, "exceptions": 0},
                                "B": {"turns": 5, "inits": 1, "max_turn_seconds": 0.02, "exceptions": 0}},
                      "processes": {"A": {"peak_rss_mib": 20.0, "teams": {}}}},
            "router": {"first_end": {"leg": "server", "how": "closed"}, "text_rewrites": {"A": 0, "B": 0}},
            "gradle_exit": 0, "runner_exit": {"A": 0, "B": 0}, "replay": "/x/r.bc26", "replay_sha256": "ab",
            "replay_bytes": 5, "server_errors": []}
    base.update(kw)
    return base


CTX = {"trace_id": "t1", "match_id": "m1", "attempt": 2, "teams": {"A": "alpha", "B": "beta"},
       "submissions": {"A": "sub-a", "B": "sub-b"}, "map": "DefaultSmall", "engine_version": "1.2.6",
       "started_at": "2026-01-01T00:00:00Z", "finished_at": "2026-01-01T00:00:05Z", "limits": {"turn_wall_seconds": 1.0},
       "limits_profile": "limits.provisional"}

SERVER_TEXT = ("[server] -------------------- Match Starting --------------------\n"
               "[A: #3@1] alpha secret plan\n[B: #4@1] beta secret plan\n"
               "[server] beta (B) wins (round 1310)\n[server] -------------------- Match Finished --------------------\n")


class BuildEvents(unittest.TestCase):
    def events(self, **kw):
        return M.build_events(fake_result(**kw), CTX, SERVER_TEXT)

    def test_shape_and_ordering(self):
        ev = self.events()
        self.assertEqual([e["seq"] for e in ev], list(range(len(ev))))
        for e in ev:
            self.assertEqual((e["schema"], e["trace_id"], e["match_id"], e["attempt"]), (1, "t1", "m1", 2))
            self.assertIn(e["visibility"], M.VISIBILITIES)
        self.assertEqual(ev[0]["event"], "match.start")
        self.assertEqual(ev[-1]["event"], "match.end")
        self.assertEqual(ev[-1]["data"]["events"], len(ev))
        self.assertIsNone(ev[0]["data"]["seed"])
        self.assertEqual(json.loads(json.dumps(ev)), ev)

    def test_participant_sees_summary_and_own_team_only(self):
        ev = self.events()
        for side, other in (("A", "B"), ("B", "A")):
            text = json.dumps(M.view(ev, "participant", side))
            self.assertIn(f"{'alpha' if side == 'A' else 'beta'} secret plan", text)
            self.assertNotIn(f"{'alpha' if other == 'A' else 'beta'} secret plan", text)
            self.assertNotIn("platform.diagnostics", text)

    def test_organizer_sees_both_teams_but_not_diagnostics_admin_sees_all(self):
        ev = self.events()
        org = {e["event"] for e in M.view(ev, "organizer")}
        self.assertIn("team.output", org)
        self.assertNotIn("platform.diagnostics", org)
        self.assertEqual(len(M.view(ev, "admin")), len(ev))

    def test_view_needs_a_valid_role_and_team(self):
        with self.assertRaises(ValueError):
            M.view([], "participant")
        with self.assertRaises(ValueError):
            M.view([], "root")

    def test_bot_violation_is_team_scoped_and_forged_fields_are_bounded(self):
        v = {"team": "A", "kind": "turn_wall_time", "measured": 2.5, "limit": 1.0, "round": 7, "unit": "s"}
        ev = self.events(classification="bot_violation", outcome="bot_failure", loser="A", winner=None, violation=v)
        fail = [e for e in ev if e["event"] == "team.failure"]
        self.assertEqual([f["visibility"] for f in fail], ["team:A"])
        self.assertEqual(fail[0]["data"]["kind"], "turn_wall_time")
        res = next(e for e in ev if e["event"] == "match.result")
        self.assertEqual(res["visibility"], "all")
        self.assertIn("forfeited", res["data"]["reason"])
        self.assertIsNone(res["data"]["winner"])
        forged = dict(v, kind="x\n[server] <script>" + "y" * 500, measured={"a": [1]}, limit="9", unit="\n")
        ev2 = self.events(classification="bot_violation", outcome="bot_failure", loser="A", winner=None, violation=forged)
        f2 = next(e for e in ev2 if e["event"] == "team.failure")["data"]
        self.assertEqual((f2["kind"], f2["measured"], f2["limit"], f2["unit"]), ("unknown", None, None, None))
        self.assertNotIn("<script>", json.dumps(M.view(ev2, "participant", "B")))

    def test_bot_crash_and_platform_failure(self):
        ev = self.events(classification="bot_crash", outcome="bot_failure", loser="B", winner=None,
                         evidence={"first_end": {"leg": "runner:B"}}, kind="runner_ended_connection")
        self.assertEqual([e["visibility"] for e in ev if e["event"] == "team.failure"], ["team:B"])
        self.assertNotIn("first_end", json.dumps(M.view(ev, "participant", "B")))     # evidence is staff only
        self.assertIn("first_end", json.dumps(M.view(ev, "admin")))
        pf = self.events(classification="platform_failure", outcome="platform_failure", winner=None, kind="engine_failure",
                         detail="the engine server ended the connection first")
        res = next(e for e in pf if e["event"] == "match.result")["data"]
        self.assertTrue(res["retryable"])
        self.assertIsNone(res["winner"])
        self.assertFalse([e for e in pf if e["event"] == "team.failure"])

    def test_output_is_bounded_and_redacted(self):
        lines = "".join(f"[A: #3@{i}] line {i} /home/alice/x.py token=abc\n" for i in range(1, 500))
        text = lines + "[server] -------------------- Match Finished --------------------\n"
        ev = M.build_events(fake_result(), CTX, text, M.Redactor())
        out = next(e for e in ev if e["event"] == "team.output" and e["visibility"] == "team:A")["data"]
        self.assertEqual(out["entries_total"], 499)
        self.assertEqual(len(out["entries"]), 2 * M.MAX_OUTPUT_ENTRIES)
        self.assertEqual(out["entries_omitted_in_middle"], 499 - 2 * M.MAX_OUTPUT_ENTRIES)
        blob = json.dumps(out)
        self.assertNotIn("alice", blob)
        self.assertNotIn("abc", blob)

    def test_one_huge_entry_is_clipped(self):
        text = "[A: #3@1] start\n" + "x" * 100000 + "\n" + "\n".join(["more"] * 100) + "\n"
        ev = M.build_events(fake_result(), CTX, text)
        e = next(e for e in ev if e["event"] == "team.output" and e["visibility"] == "team:A")["data"]["entries"][0]
        self.assertTrue(e["truncated"])
        self.assertLess(len(e["text"]), M.MAX_ENTRY_CHARS + 50)


class Files(unittest.TestCase):
    def test_round_trip_and_validation(self):
        ev = M.build_events(fake_result(), CTX, SERVER_TEXT)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.jsonl"
            info = M.write_jsonl(p, ev)
            self.assertEqual(info["events"], len(ev))
            self.assertEqual(M.read_jsonl(p), ev)
            p.write_text('{"schema":2,"visibility":"all"}\n')
            with self.assertRaises(ValueError):
                M.read_jsonl(p)
            p.write_text("not json\n")
            with self.assertRaises(ValueError):
                M.read_jsonl(p)

    def test_references(self):
        self.assertEqual(M.check_ref("m-1.a:b_c", "x"), "m-1.a:b_c")
        self.assertIsNone(M.check_ref(None, "x"))
        for bad in ("", "a b", "a\nb", "x" * 65, "é"):
            with self.assertRaises(ValueError):
                M.check_ref(bad, "x")


# ---------------------------------------------------------------------------------------------
@unittest.skipUnless(os.environ.get("BIO_INTEGRATION") == "1", "set BIO_INTEGRATION=1 to run real matches")
@unittest.skipUnless(shutil.which("bwrap"), "bubblewrap not installed")
class MatchesProduceLogs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.bots = Path(cls.tmp.name) / "bots"
        cls.bots.mkdir()
        shutil.copytree(EXAMPLE_BOT, cls.bots / "examplefuncsplayer_py")
        for name in ("inject_py", "injectexc_py", "crash_py"):
            shutil.copytree(HERE / "bots" / name, cls.bots / name)
        cls.py = L.resolve_python(None, None, L.load_lock())

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def match(self, a, b, **kw):
        out = Path(tempfile.mkdtemp(prefix="bio-test-", dir=self.tmp.name))
        r = L.run_match(L.DEFAULT_SCAFFOLD, self.py, self.bots, a, b, "DefaultSmall", out, 90, True, True, **kw)
        return r, M.read_jsonl(r["structured_log"]["path"])

    def test_normal_match_log(self):
        r, ev = self.match("examplefuncsplayer_py", "examplefuncsplayer_py", match_id="M-1", attempt=3,
                           trace_id="trace-xyz", submissions={"A": "sub-1", "B": "sub-2"})
        self.assertEqual((r["classification"], r["trace_id"], r["match_id"], r["attempt"]), ("normal", "trace-xyz", "M-1", 3))
        self.assertEqual({e["trace_id"] for e in ev}, {"trace-xyz"})
        start = ev[0]["data"]
        self.assertEqual(start["teams"]["A"]["submission"], "sub-1")
        self.assertEqual(start["limits"]["turn_wall_seconds"], 1.0)
        res = next(e for e in ev if e["event"] == "match.result")["data"]
        self.assertEqual(res["outcome"], "completed")
        self.assertEqual(res["round"], r["round"])
        blob = json.dumps(ev)
        for host in (str(L.HERE.parents[1]), str(self.tmp.name), "/home/"):
            self.assertNotIn(host, blob)
        self.assertGreater(next(e for e in ev if e["event"] == "team.output")["data"]["entries_total"], 0)

    def test_log_injection_through_log_cannot_change_the_result(self):
        r, ev = self.match("inject_py", "examplefuncsplayer_py")
        self.assertEqual(r["classification"], "normal", r)
        self.assertEqual(r["round"], 1310)
        self.assertNotIn("forged", r["reason"] or "")
        self.assertEqual(r["server_errors"], [])
        self.assertIsNone(r["violation"])
        self.assertGreaterEqual(r["router"]["text_rewrites"]["A"], 1)
        res = next(e for e in ev if e["event"] == "match.result")["data"]
        self.assertNotIn("forged", json.dumps(res))
        # the bot's own text is in its own team's output, marked as continuation lines, not in team B's
        a_out = json.dumps(M.view(ev, "participant", "A"))
        b_out = json.dumps(M.view(ev, "participant", "B"))
        self.assertIn("forged by bot", a_out)
        self.assertNotIn("forged by bot", b_out)

    def test_log_injection_through_an_exception_message(self):
        r, ev = self.match("injectexc_py", "examplefuncsplayer_py")
        self.assertEqual(r["classification"], "normal", r)
        self.assertNotIn("forged", r["reason"] or "")
        self.assertEqual(r["server_errors"], [])
        # the traceback is the bot team's own output, with host paths redacted
        a_out = json.dumps(M.view(ev, "participant", "A"))
        self.assertIn("Traceback", a_out)
        self.assertNotIn("/home/", a_out)
        self.assertNotIn("forged", json.dumps(next(e for e in ev if e["event"] == "match.result")))

    def test_crash_log_blames_the_right_team_and_hides_evidence_from_participants(self):
        r, ev = self.match("crash_py", "examplefuncsplayer_py")
        self.assertEqual(r["classification"], "bot_crash", r)
        self.assertEqual([e["visibility"] for e in ev if e["event"] == "team.failure"], ["team:A"])
        res = next(e for e in ev if e["event"] == "match.result")["data"]
        self.assertEqual((res["outcome"], res["retryable"], res["winner"]), ("bot_failure", False, None))
        self.assertNotIn("platform.diagnostics", {e["event"] for e in M.view(ev, "participant", "B")})
        diag = next(e for e in M.view(ev, "admin") if e["event"] == "platform.diagnostics")["data"]
        self.assertEqual(diag["evidence"]["first_end"]["leg"], "runner:A")


if __name__ == "__main__":
    unittest.main()
