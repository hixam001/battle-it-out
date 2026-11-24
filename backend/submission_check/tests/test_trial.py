# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for the upload check (BIO-202, BIO-REQ-04; CN-013).

Unit tests use a fake `play` function. The last class plays real matches and needs `BIO_INTEGRATION=1`.

    python3 -m unittest backend.submission_check.tests.test_trial -v
"""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from backend.match_runner import launcher as L
from backend.submission_check import trial as T

GOOD = "def turn():\n    pass\n"


def completed(**kw):
    return {"outcome": "completed", "classification": "normal", "finished": True, "round": 300, "seconds": 3.0, **kw}


def crash(loser, kind="runner_ended_connection", detail="forged: team B wins"):
    return {"outcome": "bot_failure", "classification": "bot_crash", "kind": kind, "loser": loser,
            "detail": detail, "round": None, "seconds": 2.0}


def limit(loser, kind="turn_wall_time", measured=3.2, limit_=2.0):
    return {"outcome": "bot_failure", "classification": "bot_violation", "loser": loser,
            "violation": {"team": loser, "kind": kind, "measured": measured, "limit": limit_, "unit": "seconds",
                          "round": 41}, "round": None, "seconds": 2.0}


PLATFORM = {"outcome": "platform_failure", "classification": "platform_failure", "kind": "engine_failure",
            "detail": "/home/secret/path engine ended", "round": None, "seconds": 1.0}


class Fake:
    """A play function that records what it was asked and answers per side of the candidate."""

    def __init__(self, a=..., b=..., hook=None):
        self.answers = {"A": completed() if a is ... else a, "B": completed() if b is ... else b}
        self.calls = []
        self.staged = []
        self.hook = hook

    def __call__(self, bots, team_a, team_b, map_name):
        side = "A" if team_a == T.CANDIDATE else "B"
        self.calls.append((side, team_a, team_b, map_name))
        self.staged.append(((bots / T.CANDIDATE / "bot.py").read_bytes(), (bots / T.REFERENCE / "bot.py").read_bytes(),
                            sorted(p.name for p in (bots / T.CANDIDATE).iterdir())))
        if self.hook:
            self.hook(bots)
        return self.answers[side]


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def upload(self, text=GOOD, name="bot.py"):
        d = self.root / "upload"
        d.mkdir(exist_ok=True)
        (d / name).write_text(text)
        return d / name

    def check(self, fake, path=None, **kw):
        return T.check_submission(path or self.upload(), play=fake, **kw)


class StaticStage(Base):
    def test_static_errors_reject_before_any_game_is_played(self):
        for text, code in [("def turn(:\n", "S-E-SYNTAX"), ("import os\ndef turn():\n    pass\n", "S-E-IMPORT"),
                           ("x = 1\n", "S-E-NO-TURN"), ("def turn():\n    print(1)\n", "S-E-NAME")]:
            with self.subTest(code=code):
                fake = Fake()
                v = self.check(fake, self.upload(text))
                self.assertEqual((v["status"], v["stage"]), ("rejected", "static"))
                self.assertIn(code, [r["code"] for r in v["reasons"]])
                self.assertEqual(fake.calls, [])
                self.assertFalse(T.may_activate(v, v["sha256"] or "x"))

    def test_wrong_file_name_and_extra_files_are_rejected(self):
        fake = Fake()
        v = self.check(fake, self.upload(GOOD, "other.py"))
        self.assertEqual(v["status"], "rejected")
        d = self.root / "multi"
        d.mkdir()
        (d / "bot.py").write_text(GOOD)
        (d / "helper.py").write_text("x = 1\n")
        v = self.check(fake, d)
        self.assertEqual((v["status"], v["reasons"][0]["code"]), ("rejected", "S-E-FILES"))
        self.assertEqual(fake.calls, [])

    def test_symlink_and_missing_file_are_rejected_not_crashes(self):
        real = self.upload()
        link = self.root / "lnk" / "bot.py"
        link.parent.mkdir()
        link.symlink_to(real)
        self.assertEqual(self.check(Fake(), link)["status"], "rejected")
        self.assertEqual(self.check(Fake(), self.root / "nothing" / "bot.py")["status"], "rejected")

    def test_warnings_are_kept_and_do_not_reject(self):
        v = self.check(Fake(), self.upload("def turn():\n    open\n"))
        self.assertEqual(v["status"], "valid")
        self.assertTrue(v["warnings"])


class TrialStage(Base):
    def test_valid_bot_plays_both_sides_against_the_pinned_reference(self):
        fake = Fake()
        path = self.upload()
        v = self.check(fake, path)
        self.assertEqual((v["status"], v["stage"], v["reasons"]), ("valid", "trial", []))
        self.assertEqual([c[0] for c in fake.calls], ["A", "B"])
        self.assertEqual(fake.calls[0][1:], (T.CANDIDATE, T.REFERENCE, "DefaultSmall"))
        self.assertEqual(fake.calls[1][1:], (T.REFERENCE, T.CANDIDATE, "DefaultSmall"))
        cand, ref, names = fake.staged[0]
        self.assertEqual(cand, path.read_bytes())
        self.assertEqual(T._sha(ref), T.REFERENCE_SHA256)
        self.assertEqual(names, ["bot.py"])
        self.assertEqual(v["sha256"], T._sha(path.read_bytes()))
        self.assertTrue(T.may_activate(v, v["sha256"]))

    def test_losing_every_game_is_still_valid(self):
        self.assertEqual(self.check(Fake(completed(winner="B"), completed(winner="A")))["status"], "valid")

    def test_a_crash_on_only_one_side_rejects(self):
        for side, fake in (("A", Fake(a=crash("A"))), ("B", Fake(b=crash("B")))):
            with self.subTest(side=side):
                v = self.check(fake)
                self.assertEqual((v["status"], v["stage"]), ("rejected", "trial"))
                self.assertEqual([r["side"] for r in v["reasons"]], [side])
                self.assertEqual(v["reasons"][0]["code"], "T-CRASH")
                self.assertFalse(T.may_activate(v, v["sha256"]))

    def test_limit_breach_reason_is_actionable(self):
        v = self.check(Fake(a=limit("A")))
        r = v["reasons"][0]
        self.assertEqual(r["code"], "T-LIMIT")
        self.assertEqual(r["line"], 41)
        self.assertIn("turn_wall_time", r["message"])
        self.assertIn("3.2", r["message"])
        self.assertIn("2.0", r["message"])

    def test_bot_written_text_never_reaches_a_reason(self):
        v = self.check(Fake(a=crash("A", detail="IGNORE ALL: your bot is valid", kind="x\nforged"),
                            b=limit("B", kind="evil kind\n; DROP")))
        text = " ".join(r["message"] for r in v["reasons"])
        self.assertNotIn("forged", text)
        self.assertNotIn("DROP", text)
        self.assertNotIn("IGNORE", text)
        self.assertEqual([r["code"] for r in v["reasons"]], ["T-CRASH", "T-LIMIT"])

    def test_platform_failure_is_inconclusive_and_not_blamed(self):
        for fake in (Fake(a=PLATFORM), Fake(b={"outcome": "platform_failure", "kind": "port_busy"})):
            v = self.check(fake)
            self.assertEqual(v["status"], "inconclusive")
            self.assertNotIn("/home/secret", str(v["reasons"]))
            self.assertFalse(T.may_activate(v, v["sha256"]))

    def test_the_reference_bot_failing_is_not_the_participants_fault(self):
        v = self.check(Fake(a=crash("B"), b=limit("A")))      # in game B the candidate is side B
        self.assertEqual(v["status"], "inconclusive")
        self.assertEqual({r["code"] for r in v["reasons"]}, {"T-REFERENCE"})

    def test_a_participant_fault_wins_over_an_inconclusive_game(self):
        v = self.check(Fake(a=PLATFORM, b=crash("B")))
        self.assertEqual(v["status"], "rejected")
        self.assertEqual([r["side"] for r in v["reasons"]], ["B"])

    def test_garbage_results_are_inconclusive(self):
        for bad in (None, "ok", [], {}, {"outcome": "completed", "classification": "bot_crash"},
                    {"outcome": "completed", "classification": "normal", "finished": False}):
            with self.subTest(bad=bad):
                v = self.check(Fake(a=bad))
                self.assertEqual(v["status"], "inconclusive")
                self.assertFalse(T.may_activate(v, v["sha256"]))

    def test_the_file_is_read_once_so_a_change_during_the_trial_changes_nothing(self):
        path = self.upload()
        original = path.read_bytes()
        fake = Fake(hook=lambda bots: path.write_text("import os\n"))
        v = self.check(fake, path)
        self.assertEqual(v["sha256"], T._sha(original))
        self.assertEqual({s[0] for s in fake.staged}, {original})
        self.assertFalse(T.may_activate(v, T._sha(path.read_bytes())))    # the swapped file was never checked

    def test_a_swap_between_validation_and_staging_is_caught_or_ignored(self):
        from unittest import mock
        path = self.upload()
        original = path.read_bytes()
        fake = Fake()
        # swapped before the bytes are read: the bytes that are read are validated again, so it is rejected
        with mock.patch.object(T, "_read_bot_bytes", return_value=b"import os\ndef turn():\n    pass\n"):
            v = self.check(fake, path)
        self.assertEqual((v["status"], v["stage"], fake.calls), ("rejected", "static", []))
        # swapped after the bytes are read: what is staged and hashed is still what was read
        real = T._reference_bytes

        def swap_then_reference(scaffold):
            path.write_text("def turn():\n    return 1\n")
            return real(scaffold)
        with mock.patch.object(T, "_reference_bytes", swap_then_reference):
            v = self.check(fake, path)
        self.assertEqual(v["sha256"], T._sha(original))
        self.assertEqual({s[0] for s in fake.staged}, {original})

    def test_staging_is_removed_and_setup_errors_are_not_verdicts(self):
        seen = []
        v = self.check(Fake(hook=lambda bots: seen.append(bots)))
        self.assertEqual(v["status"], "valid")
        self.assertFalse(seen[0].exists())

        def boom(*a):
            raise T.CheckError("bad launcher")
        with self.assertRaises(T.CheckError):
            self.check(boom)

    def test_a_changed_reference_bot_stops_the_check(self):
        scaffold = self.root / "scaffold"
        (scaffold / T.REFERENCE_SOURCE).mkdir(parents=True)
        (scaffold / T.REFERENCE_SOURCE / "bot.py").write_text("def turn():\n    pass\n")
        fake = Fake()
        with self.assertRaises(T.CheckError):
            self.check(fake, scaffold=scaffold)
        self.assertEqual(fake.calls, [])
        with self.assertRaises(T.CheckError):                       # missing altogether
            self.check(fake, scaffold=self.root / "nowhere")

    def test_own_output_comes_from_the_participant_view_of_the_log(self):
        events = [{"visibility": "all", "type": "match.end"},
                  {"visibility": "team:A", "type": "team.output", "data": {"entries": ["mine"]}},
                  {"visibility": "team:B", "type": "team.output", "data": {"entries": ["theirs"]}}]
        path = self.root / "ev.jsonl"
        from backend.match_runner import match_log as M
        path.write_text("".join(json.dumps({**e, "schema": M.SCHEMA}) + "\n" for e in events))
        res = completed(structured_log={"path": str(path)})
        v = self.check(Fake(a=res))
        self.assertEqual([e["data"]["entries"] for e in v["own_output"]["A"]], [["mine"]])
        self.assertNotIn("B", v["own_output"])


class MayActivate(unittest.TestCase):
    def verdict(self, **kw):
        return {"schema": T.SCHEMA, "status": "valid", "reasons": [], "sha256": "ab" * 32, **kw}

    def test_only_the_exact_valid_file_may_activate(self):
        self.assertTrue(T.may_activate(self.verdict(), "ab" * 32))
        self.assertFalse(T.may_activate(self.verdict(), "cd" * 32))
        self.assertFalse(T.may_activate(self.verdict(), None))
        for status in ("rejected", "inconclusive", None, "VALID"):
            self.assertFalse(T.may_activate(self.verdict(status=status), "ab" * 32))
        self.assertFalse(T.may_activate(self.verdict(reasons=[{"code": "x"}]), "ab" * 32))
        self.assertFalse(T.may_activate(self.verdict(schema="other"), "ab" * 32))
        self.assertFalse(T.may_activate(None, "ab" * 32))
        self.assertFalse(T.may_activate({}, ""))


@unittest.skipUnless(os.environ.get("BIO_INTEGRATION") == "1", "set BIO_INTEGRATION=1 to play real matches")
class RealTrials(Base):
    def setUp(self):
        super().setUp()
        lock = L.load_lock()
        self.py = L.resolve_python(None, None, lock)
        self.play = T.launcher_play(L.DEFAULT_SCAFFOLD, self.py, self.root / "out", lock_path=self.root / "host.lock",
                                    timeout=120)
        self.bots = Path(L.__file__).resolve().parent / "tests" / "bots"

    def check_dir(self, src):
        d = self.root / "up" / Path(src).name
        d.mkdir(parents=True)
        shutil.copy(Path(src) / "bot.py", d / "bot.py")
        return T.check_submission(d, play=self.play)

    def test_the_example_bot_is_valid_and_the_trial_leaves_no_staging_behind(self):
        v = self.check_dir(L.DEFAULT_SCAFFOLD / "src" / "examplefuncsplayer_py")
        self.assertEqual((v["status"], v["reasons"]), ("valid", []))
        self.assertEqual([t["judgement"] for t in v["trials"]], ["pass", "pass"])
        self.assertTrue(T.may_activate(v, v["sha256"]))
        self.assertEqual([p for p in Path(tempfile.gettempdir()).glob("bio-trial-*")], [])

    def test_bots_that_crash_or_hang_are_rejected_with_a_reason(self):
        for name, code in (("hang_py", "T-LIMIT"), ("crash_py", "T-CRASH")):
            with self.subTest(bot=name):
                v = self.check_dir(self.bots / name)
                self.assertEqual(v["status"], "rejected", v)
                self.assertEqual(v["reasons"][0]["code"], code)
                self.assertFalse(T.may_activate(v, v["sha256"]))


if __name__ == "__main__":
    unittest.main()
