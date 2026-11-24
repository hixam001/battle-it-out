# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for the submission registry (BIO-EPIC-05, SRD-050..058; CN-016).

Unit tests use a fake clock and hand-made verdicts. The last class plays real trial matches and a real
tournament match from stored versions and needs `BIO_INTEGRATION=1`.

    python3 -m unittest backend.submission_registry.tests.test_registry -v
"""
import hashlib
import os
import shutil
import stat
import tempfile
import threading
import unittest
from pathlib import Path

from backend.match_runner import launcher as L
from backend.match_orchestrator.store import StoreError
from backend.submission_check import trial as T
from backend.submission_registry import registry as R

GOOD = b"def turn():\n    pass\n"
GOOD2 = b"def turn():\n    x = 1\n"
GOOD3 = b"def turn():\n    y = 2\n"
DEADLINE = 1_000_000.0


class Clock:
    def __init__(self, t=DEADLINE - 10_000):
        self.t = float(t)

    def __call__(self):
        return self.t


def sha(b):
    return hashlib.sha256(b).hexdigest()


def verdict(data, status="valid", reasons=None, stage="trial", **kw):
    v = {"schema": T.SCHEMA, "status": status, "stage": stage, "reasons": reasons or [], "warnings": [],
         "sha256": sha(data), "bytes": len(data), "checked_at": "2026-11-24T00:00:00Z", "map": "DefaultSmall",
         "trials": [{"candidate_side": "A", "judgement": "pass", "outcome": "completed",
                     "classification": "normal", "round": 300, "seconds": 3.0}]}
    v.update(kw)
    return v


def actor(user="u1", role="participant", teams=("ta",), captain=("ta",), tournaments=()):
    return R.Actor(user, role, frozenset(teams), frozenset(captain), frozenset(tournaments))


CAPTAIN = actor("cap")
MEMBER = actor("mem", captain=())
ORG = actor("org", "organizer", teams=(), captain=(), tournaments=("t1",))
OTHER_ORG = actor("org2", "organizer", teams=(), captain=(), tournaments=("t2",))
ADMIN = actor("adm", "admin", teams=(), captain=())
OTHER_TEAM = actor("cap-b", teams=("tb",), captain=("tb",))


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.clock = Clock()
        self.reg = R.Registry(self.dir / "subs", self.dir / "registry.json")
        self.n = 0

    def tearDown(self):
        # folders are read-only on purpose; make them removable for the temp-dir cleanup
        for p in (self.dir / "subs").glob("*"):
            if p.is_dir() and not p.is_symlink():
                os.chmod(p, 0o700)

    def up(self, data=GOOD, *, who=CAPTAIN, team="ta", tournament="t1", name="bot.py", key=None, deadline=DEADLINE):
        self.n += 1
        return R.submit(self.reg, who, team, tournament, name, data, idempotency_key=key or f"k{self.n}",
                        deadline_at=deadline, now=self.clock)

    def check(self, sub, data, status="valid", **kw):
        claim = R.claim_check(self.reg, sub["id"], now=self.clock)
        self.assertIsNotNone(claim)
        return R.record_verdict(self.reg, claim, verdict(data, status, **kw), now=self.clock)

    def state(self):
        return self.reg.store.snapshot()


class Upload(Base):
    def test_a_captain_upload_is_stored_as_an_immutable_read_only_version(self):
        v = self.up()
        self.assertEqual((v["id"], v["version"], v["validation_status"], v["is_active"]), ("ta-v1", 1, "validating", False))
        self.assertEqual(v["content_hash"], sha(GOOD))
        f = self.reg.root / "ta-v1" / "bot.py"
        self.assertEqual(f.read_bytes(), GOOD)
        self.assertEqual(stat.S_IMODE(f.stat().st_mode), 0o400)
        self.assertEqual(stat.S_IMODE(f.parent.stat().st_mode), 0o500)
        self.assertEqual(os.listdir(f.parent), ["bot.py"])

    def test_versions_count_up_per_team(self):
        self.assertEqual([self.up(GOOD + b"#%d\n" % i)["version"] for i in range(3)], [1, 2, 3])
        self.assertEqual(self.up(who=OTHER_TEAM, team="tb")["id"], "tb-v1")

    def test_static_problems_are_reported_at_once_and_stay_in_the_history(self):
        cases = [(b"def turn(:\n", "bot.py", "S-E-SYNTAX"), (b"x = 1\n", "bot.py", "S-E-NO-TURN"),
                 (b"import os\ndef turn():\n    pass\n", "bot.py", "S-E-IMPORT"),
                 (GOOD, "bot2.py", "S-E-FILES"), (b"\xff\xfe\x00", "bot.py", "S-E-ENCODING"),
                 (b"def turn():\n    pass\x00\n", "bot.py", "S-E-SYNTAX")]
        for data, name, code in cases:
            with self.subTest(code=code, name=name):
                v = self.up(data, name=name)
                self.assertEqual(v["validation_status"], "invalid")
                self.assertEqual(v["validations"][0]["stage"], "static")
                self.assertIn(code, [r["code"] for r in v["validations"][0]["reasons"]])
                self.assertFalse(v["is_active"])
        self.assertEqual(len(R.history(self.reg, CAPTAIN, "ta")), len(cases))

    def test_a_syntax_error_reports_its_line(self):
        v = self.up(b"def turn():\n    pass\n  x = (\n")
        self.assertTrue(any(r["line"] for r in v["validations"][0]["reasons"]))

    def test_only_the_captain_may_upload(self):
        for who, exc in ((MEMBER, R.Forbidden), (ORG, R.Forbidden), (ADMIN, R.Forbidden),
                         (OTHER_TEAM, R.NotFound), (OTHER_ORG, R.NotFound), (None, R.NotFound),
                         (actor("x", "intruder"), R.NotFound)):
            with self.subTest(who=who and who.user_id):
                with self.assertRaises(exc):
                    self.up(who=who)
        self.assertEqual(self.state()["submissions"], {})
        self.assertEqual(os.listdir(self.reg.root), [])

    def test_a_captain_flag_without_membership_is_not_enough(self):
        with self.assertRaises(R.NotFound):
            self.up(who=actor("x", teams=(), captain=("ta",)))

    def test_nothing_is_stored_after_the_deadline_and_an_extension_reopens(self):
        self.clock.t = DEADLINE
        with self.assertRaises(R.DeadlineClosed):
            self.up()
        self.assertEqual((self.state()["submissions"], os.listdir(self.reg.root)), ({}, []))
        v = self.up(deadline=DEADLINE + 3600)               # Admin extended it
        self.assertEqual(v["version"], 1)                   # the refused upload used no version number

    def test_the_last_second_before_the_deadline_is_open(self):
        self.clock.t = DEADLINE - 1
        self.assertEqual(self.up()["validation_status"], "validating")

    def test_a_retry_of_a_successful_upload_returns_the_same_answer_even_after_the_deadline(self):
        first = self.up(key="same")
        self.clock.t = DEADLINE + 5
        again = R.submit(self.reg, CAPTAIN, "ta", "t1", "bot.py", GOOD, idempotency_key="same",
                         deadline_at=DEADLINE, now=self.clock)
        self.assertEqual(first["id"], again["id"])
        self.assertEqual(len(self.state()["submissions"]), 1)

    def test_one_key_cannot_carry_two_files(self):
        self.up(GOOD, key="same")
        with self.assertRaises(R.Conflict):
            self.up(GOOD2, key="same")
        self.assertEqual(len(self.state()["submissions"]), 1)

    def test_the_same_key_for_another_team_is_independent(self):
        self.up(key="same")
        self.assertEqual(self.up(who=OTHER_TEAM, team="tb", key="same")["id"], "tb-v1")

    def test_too_large_is_refused_and_stores_nothing(self):
        reg = R.Registry(self.dir / "small", self.dir / "small.json", max_bytes=10)
        with self.assertRaises(R.TooLarge):
            R.submit(reg, CAPTAIN, "ta", "t1", "bot.py", GOOD, idempotency_key="k", deadline_at=DEADLINE, now=self.clock)
        self.assertEqual((reg.store.snapshot()["submissions"], os.listdir(reg.root)), ({}, []))

    def test_a_file_exactly_at_the_limit_is_accepted(self):
        reg = R.Registry(self.dir / "lim", self.dir / "lim.json", max_bytes=len(GOOD))
        v = R.submit(reg, CAPTAIN, "ta", "t1", "bot.py", GOOD, idempotency_key="k", deadline_at=DEADLINE, now=self.clock)
        self.assertEqual(v["bytes"], len(GOOD))

    def test_a_team_cannot_move_to_another_tournament(self):
        self.up()
        with self.assertRaises(R.Conflict):
            self.up(tournament="t9")

    def test_the_version_cap_stops_unbounded_history(self):
        reg = R.Registry(self.dir / "cap", self.dir / "cap.json", max_versions=2)
        for i in range(2):
            R.submit(reg, CAPTAIN, "ta", "t1", "bot.py", GOOD + b"#%d\n" % i, idempotency_key=f"k{i}",
                     deadline_at=DEADLINE, now=self.clock)
        with self.assertRaises(R.Conflict):
            R.submit(reg, CAPTAIN, "ta", "t1", "bot.py", GOOD2, idempotency_key="k9", deadline_at=DEADLINE, now=self.clock)

    def test_unsafe_identifiers_and_keys_are_rejected(self):
        for team in ("../x", "a/b", "", "a" * 41, "a.b", ".hidden"):
            with self.subTest(team=team), self.assertRaises(ValueError):
                self.up(team=team)
        with self.assertRaises(ValueError):
            self.up(key="bad key\n")
        with self.assertRaises(TypeError):
            R.submit(self.reg, CAPTAIN, "ta", "t1", "bot.py", "text", idempotency_key="k", deadline_at=DEADLINE)

    def test_an_orphan_folder_from_a_crashed_upload_is_replaced(self):
        orphan = self.reg.root / "ta-v1"
        orphan.mkdir()
        (orphan / "bot.py").write_bytes(b"EVIL")
        (orphan / "extra.txt").write_bytes(b"x")
        os.chmod(orphan, 0o500)
        v = self.up()
        self.assertEqual(os.listdir(orphan), ["bot.py"])
        self.assertEqual((orphan / "bot.py").read_bytes(), GOOD)
        self.assertEqual(v["version"], 1)

    def test_a_link_where_a_folder_will_go_is_not_followed(self):
        target = self.dir / "elsewhere"
        target.mkdir()
        os.symlink(target, self.reg.root / "ta-v1")
        self.up()
        self.assertEqual(os.listdir(target), [])

    def test_parallel_uploads_get_distinct_versions(self):
        out, errs = [], []

        def work(i):
            try:
                out.append(R.submit(self.reg, CAPTAIN, "ta", "t1", "bot.py", GOOD + b"#%d\n" % i,
                                    idempotency_key=f"p{i}", deadline_at=DEADLINE, now=self.clock)["version"])
            except Exception as e:      # pragma: no cover
                errs.append(e)
        ts = [threading.Thread(target=work, args=(i,)) for i in range(8)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual((errs, sorted(out)), ([], list(range(1, 9))))

    def test_a_damaged_state_file_is_never_treated_as_empty(self):
        self.up()
        (self.dir / "registry.json").write_text("{not json")
        with self.assertRaises(StoreError):
            self.up(GOOD2)


class Activation(Base):
    def test_a_valid_verdict_makes_the_version_active(self):
        s = self.up()
        v = self.check(s, GOOD)
        self.assertEqual((v["validation_status"], v["is_active"]), ("valid", True))
        self.assertEqual(R.active_submission(self.reg, CAPTAIN, "ta")["id"], "ta-v1")
        self.assertEqual(v["validations"][-1]["status"], "valid")

    def test_a_newer_valid_version_replaces_the_active_one_and_keeps_the_old_in_history(self):
        a = self.check(self.up(GOOD), GOOD)
        b = self.check(self.up(GOOD2), GOOD2)
        h = {x["id"]: x for x in R.history(self.reg, CAPTAIN, "ta")}
        self.assertEqual((h["ta-v1"]["is_active"], h["ta-v1"]["superseded_by"], h["ta-v1"]["validation_status"]),
                         (False, "ta-v2", "valid"))
        self.assertEqual((h["ta-v2"]["is_active"], b["is_active"]), (True, True))
        self.assertEqual(sum(x["is_active"] for x in h.values()), 1)
        self.assertTrue(a["is_active"])         # the view returned at that time

    def test_a_rejected_replacement_does_not_displace_the_active_version(self):
        self.check(self.up(GOOD), GOOD)
        bad = self.check(self.up(GOOD2), GOOD2, "rejected",
                         reasons=[{"code": "T-CRASH", "message": "the bot crashed", "line": None, "side": "A"}])
        self.assertEqual((bad["validation_status"], bad["is_active"]), ("invalid", False))
        self.assertEqual(R.active_submission(self.reg, CAPTAIN, "ta")["id"], "ta-v1")
        self.assertEqual(bad["validations"][-1]["reasons"][0]["code"], "T-CRASH")

    def test_a_statically_invalid_replacement_does_not_displace_it_either(self):
        self.check(self.up(GOOD), GOOD)
        self.up(b"def turn(:\n")
        self.assertEqual(R.active_submission(self.reg, CAPTAIN, "ta")["id"], "ta-v1")

    def test_an_older_check_finishing_late_does_not_replace_a_newer_active_version(self):
        s2, s3 = self.up(GOOD2), self.up(GOOD3)         # ta-v1 and ta-v2
        c2 = R.claim_check(self.reg, s2["id"], now=self.clock)
        self.check(s3, GOOD3)
        late = R.record_verdict(self.reg, c2, verdict(GOOD2), now=self.clock)
        self.assertEqual((late["validation_status"], late["is_active"]), ("valid", False))
        self.assertEqual(R.active_submission(self.reg, CAPTAIN, "ta")["id"], "ta-v2")

    def test_inconclusive_is_neither_valid_nor_a_rejection_and_can_be_checked_again(self):
        s = self.up()
        v = self.check(s, GOOD, "inconclusive", reasons=[{"code": "T-PLATFORM", "message": "try again", "line": None}])
        self.assertEqual((v["validation_status"], v["is_active"]), ("inconclusive", False))
        self.assertIsNone(R.active_submission(self.reg, CAPTAIN, "ta"))
        v = self.check(s, GOOD)
        self.assertEqual((v["validation_status"], v["is_active"], len(v["validations"])), ("valid", True, 3))

    def test_a_finished_version_needs_no_further_check(self):
        s = self.up()
        self.check(s, GOOD)
        self.assertIsNone(R.claim_check(self.reg, s["id"], now=self.clock))
        bad = self.up(b"def turn(:\n")
        self.assertIsNone(R.claim_check(self.reg, bad["id"], now=self.clock))

    def test_a_verdict_about_another_file_is_refused(self):
        s = self.up()
        claim = R.claim_check(self.reg, s["id"], now=self.clock)
        with self.assertRaises(R.Conflict):
            R.record_verdict(self.reg, claim, verdict(GOOD2), now=self.clock)
        self.assertEqual(self.state()["submissions"]["ta-v1"]["validation_status"], "validating")

    def test_a_rejection_or_inconclusive_verdict_about_another_file_is_refused_too(self):
        # `valid` is also stopped by `may_activate`; the other two statuses rely on the hash check alone.
        s = self.up()
        claim = R.claim_check(self.reg, s["id"], now=self.clock)
        reason = [{"code": "T-CRASH", "message": "the bot crashed"}]
        for status in ("rejected", "inconclusive"):
            with self.subTest(status=status), self.assertRaises(R.Conflict):
                R.record_verdict(self.reg, claim, verdict(GOOD2, status, reasons=reason), now=self.clock)
        with self.assertRaises(R.Conflict):                  # a verdict that names no file at all
            R.record_verdict(self.reg, claim, verdict(GOOD, "rejected", reasons=reason, sha256=None), now=self.clock)
        self.assertEqual(self.state()["submissions"]["ta-v1"]["validations"][-1]["stage"], "static")

    def test_a_valid_verdict_with_reasons_or_a_foreign_schema_is_refused(self):
        s = self.up()
        claim = R.claim_check(self.reg, s["id"], now=self.clock)
        for bad in (verdict(GOOD, reasons=[{"code": "x", "message": "y"}]), {**verdict(GOOD), "schema": "other"},
                    {**verdict(GOOD), "status": "great"}, "valid", None):
            with self.subTest(bad=str(bad)[:40]), self.assertRaises(R.Conflict):
                R.record_verdict(self.reg, claim, bad, now=self.clock)
        self.assertFalse(self.state()["submissions"]["ta-v1"]["is_active"])

    def test_one_worker_at_a_time_and_a_dead_worker_is_replaced_after_the_lease(self):
        s = self.up()
        first = R.claim_check(self.reg, s["id"], now=self.clock, lease=100)
        self.assertIsNone(R.claim_check(self.reg, s["id"], now=self.clock, lease=100))
        self.clock.t += 101
        second = R.claim_check(self.reg, s["id"], now=self.clock, lease=100)
        self.assertNotEqual(first.token, second.token)
        with self.assertRaises(R.Conflict):                  # the slow first worker cannot write any more
            R.record_verdict(self.reg, first, verdict(GOOD), now=self.clock)
        self.assertTrue(R.record_verdict(self.reg, second, verdict(GOOD), now=self.clock)["is_active"])

    def test_a_verdict_cannot_be_recorded_twice(self):
        s = self.up()
        claim = R.claim_check(self.reg, s["id"], now=self.clock)
        R.record_verdict(self.reg, claim, verdict(GOOD), now=self.clock)
        with self.assertRaises(R.Conflict):
            R.record_verdict(self.reg, claim, verdict(GOOD, "rejected", reasons=[{"code": "T", "message": "m"}]),
                             now=self.clock)
        self.assertEqual(self.state()["submissions"]["ta-v1"]["validation_status"], "valid")

    def test_a_check_that_cannot_run_gives_its_claim_back(self):
        s = self.up()

        def boom(folder):
            raise T.CheckError("no engine")
        with self.assertRaises(T.CheckError):
            R.run_check(self.reg, s["id"], boom, now=self.clock)
        self.assertEqual(self.state()["submissions"]["ta-v1"]["validation_status"], "validating")
        out = R.run_check(self.reg, s["id"], lambda folder: verdict(GOOD), now=self.clock)
        self.assertEqual(out["validation_status"], "valid")

    def test_run_check_hands_the_stored_folder_to_the_checker(self):
        s = self.up()
        seen = {}

        def check(folder):
            seen["names"] = sorted(os.listdir(folder))
            seen["data"] = (Path(folder) / "bot.py").read_bytes()
            return verdict(GOOD)
        R.run_check(self.reg, s["id"], check, now=self.clock)
        self.assertEqual(seen, {"names": ["bot.py"], "data": GOOD})

    def test_a_worker_gets_a_stored_file_only_if_it_still_matches_its_hash(self):
        s = self.up()
        f = self.reg.root / s["id"] / "bot.py"
        os.chmod(f.parent, 0o700)
        os.chmod(f, 0o600)
        f.write_bytes(b"def turn():\n    import os\n")
        with self.assertRaises(R.Unavailable):
            R.claim_check(self.reg, s["id"], now=self.clock)
        self.assertEqual(self.state()["incidents"][0]["kind"], "submission_file_damaged")
        self.assertEqual(self.state()["submissions"][s["id"]]["claim"], None)

    def test_the_claim_token_is_never_in_a_view(self):
        s = self.up()
        claim = R.claim_check(self.reg, s["id"], now=self.clock)
        for v in (R.history(self.reg, CAPTAIN, "ta")[0], R.history(self.reg, ADMIN, "ta")[0]):
            self.assertNotIn(claim.token, repr(v))
            self.assertTrue(v["check_in_progress"])
            for secret in ("claim", "deadline_seen", "storage"):
                self.assertNotIn(secret, v)

    def test_verdict_text_is_clipped_and_untrusted_fields_are_dropped(self):
        s = self.up()
        v = self.check(s, GOOD, "rejected", reasons=[{"code": "T-CRASH", "message": "m" * 5000, "line": "7; DROP", "side": "Z",
                                                      "evil": "x"}] * 80, own_output={"A": [{"text": "forged"}]})
        got = v["validations"][-1]
        self.assertEqual((len(got["reasons"]), len(got["reasons"][0]["message"])), (R.MAX_REASONS, R.MAX_TEXT))
        self.assertEqual((got["reasons"][0]["line"], "side" in got["reasons"][0], "evil" in got["reasons"][0]), (None, False, False))
        self.assertNotIn("own_output", got)


class Reading(Base):
    def setUp(self):
        super().setUp()
        self.s1 = self.up(GOOD)
        self.check(self.s1, GOOD)
        self.s2 = self.up(b"def turn(:\n")

    def test_who_may_read_the_history(self):
        for who in (CAPTAIN, MEMBER, ORG, ADMIN):
            with self.subTest(who=who.user_id):
                self.assertEqual([h["version"] for h in R.history(self.reg, who, "ta")], [1, 2])
        for who in (OTHER_TEAM, OTHER_ORG, None):
            with self.subTest(who=who and who.user_id), self.assertRaises(R.NotFound):
                R.history(self.reg, who, "ta")

    def test_history_shows_outcomes_and_the_active_flag(self):
        h = R.history(self.reg, MEMBER, "ta")
        self.assertEqual([(x["validation_status"], x["is_active"]) for x in h], [("valid", True), ("invalid", False)])
        self.assertEqual(h[1]["validations"][0]["reasons"][0]["code"], "S-E-SYNTAX")

    def test_an_unknown_team_looks_like_a_team_the_actor_may_not_see(self):
        with self.assertRaises(R.NotFound):
            R.history(self.reg, OTHER_TEAM, "nobody")
        self.assertEqual(R.history(self.reg, actor("n", teams=("new",), captain=()), "new"), [])

    def test_validation_and_active_follow_the_same_rule(self):
        self.assertEqual(R.validation(self.reg, ORG, "ta-v2")[0]["status"], "rejected")
        for who in (OTHER_TEAM, OTHER_ORG, None):
            with self.subTest(who=who and who.user_id):
                with self.assertRaises(R.NotFound):
                    R.validation(self.reg, who, "ta-v1")
                with self.assertRaises(R.NotFound):
                    R.active_submission(self.reg, who, "ta")
        with self.assertRaises(R.NotFound):
            R.validation(self.reg, ADMIN, "ta-v9")

    def test_download_returns_the_exact_bytes_and_audits_staff_reads(self):
        h = R.download(self.reg, CAPTAIN, "ta-v1", now=self.clock)
        self.assertEqual((h.path.read_bytes(), h.sha256), (GOOD, sha(GOOD)))
        R.download(self.reg, MEMBER, "ta-v1", now=self.clock)
        self.assertEqual([a for a in self.state()["audit"] if a["action"] == "download"], [])
        R.download(self.reg, ORG, "ta-v1", now=self.clock)
        R.download(self.reg, ADMIN, "ta-v2", now=self.clock)
        self.assertEqual([(a["actor"], a["role"]) for a in self.state()["audit"] if a["action"] == "download"],
                         [("org", "organizer"), ("adm", "admin")])

    def test_other_teams_source_stays_private(self):
        for who in (OTHER_TEAM, OTHER_ORG, None, actor("x", "intruder")):
            with self.subTest(who=who and who.user_id), self.assertRaises(R.NotFound):
                R.download(self.reg, who, "ta-v1", now=self.clock)
        self.assertEqual([a for a in self.state()["audit"] if a["action"] == "download"], [])

    def test_download_refuses_a_file_that_changed_and_raises_an_incident(self):
        f = self.reg.root / "ta-v1" / "bot.py"
        os.chmod(f.parent, 0o700)
        os.chmod(f, 0o600)
        f.write_bytes(GOOD2)
        with self.assertRaises(R.Unavailable):
            R.download(self.reg, CAPTAIN, "ta-v1", now=self.clock)
        self.assertEqual(len(self.state()["incidents"]), 1)

    def test_an_extra_file_or_a_replaced_folder_is_detected(self):
        os.chmod(self.reg.root / "ta-v1", 0o700)
        (self.reg.root / "ta-v1" / "extra.py").write_text("x")
        with self.assertRaises(R.Unavailable):
            R.download(self.reg, CAPTAIN, "ta-v1", now=self.clock)
        shutil.rmtree(self.reg.root / "ta-v1")
        os.symlink(self.dir, self.reg.root / "ta-v1")
        with self.assertRaises(R.Unavailable):
            R.download(self.reg, CAPTAIN, "ta-v1", now=self.clock)


class Pins(Base):
    def setUp(self):
        super().setUp()
        self.a = self.up(GOOD)
        self.check(self.a, GOOD)
        self.b = self.up(GOOD2, who=OTHER_TEAM, team="tb")
        self.check(self.b, GOOD2)

    def pin(self, teams=("ta", "tb"), **kw):
        return R.pin_tournament(self.reg, "t1", list(teams), deadline_at=DEADLINE, now=self.clock, **kw)

    def test_pinning_waits_for_the_deadline(self):
        with self.assertRaises(R.Conflict):
            self.pin()
        self.clock.t = DEADLINE
        self.assertEqual(self.pin(), {"ta": "ta-v1", "tb": "tb-v1"})

    def test_pins_are_write_once_and_later_uploads_cannot_move_them(self):
        self.clock.t = DEADLINE
        first = self.pin()
        self.clock.t = DEADLINE - 1                      # an extension: the caller passes a later deadline
        c = self.up(GOOD3, deadline=DEADLINE + 100)
        self.check(c, GOOD3)
        self.clock.t = DEADLINE + 200
        self.assertEqual(self.pin(), first)
        self.assertEqual(R.pinned_folder(self.reg, "t1", "ta", now=self.clock), self.reg.root / "ta-v1")
        self.assertEqual(R.active_submission(self.reg, CAPTAIN, "ta")["id"], "ta-v2")
        self.assertEqual(R.history(self.reg, CAPTAIN, "ta")[0]["pinned_in"], ["t1"])

    def test_another_set_of_teams_cannot_be_pinned_over_the_first(self):
        self.clock.t = DEADLINE
        self.pin()
        with self.assertRaises(R.Conflict):
            self.pin(teams=("ta",))

    def test_a_team_still_being_checked_blocks_the_pin_unless_allowed(self):
        self.up(GOOD3)                                       # ta-v2 validating, ta-v1 is active
        self.clock.t = DEADLINE
        with self.assertRaises(R.PendingChecks) as cm:
            self.pin()
        self.assertEqual(cm.exception.teams, ["ta"])
        self.assertEqual(self.state()["pins"], {})
        self.assertEqual(self.pin(allow_unchecked=True)["ta"], "ta-v1")

    def test_a_preview_shows_the_pins_without_writing_anything_or_waiting_for_the_deadline(self):
        before = self.state()
        out = R.preview_pins(self.reg, "t1", ["ta", "tb", "tz"])
        self.assertEqual(out, {"pinned": False, "teams": {"ta": "ta-v1", "tb": "tb-v1", "tz": None}, "pending": []})
        self.assertEqual(self.state(), before)               # nothing written, although the deadline has not passed

    def test_a_preview_names_the_teams_still_being_checked(self):
        self.up(GOOD3)
        out = R.preview_pins(self.reg, "t1", ["ta", "tb"])
        self.assertEqual((out["pinned"], out["pending"]), (False, ["ta"]))

    def test_a_preview_of_a_pinned_tournament_is_the_stored_pin_whatever_teams_are_asked_for(self):
        self.clock.t = DEADLINE
        self.pin()
        self.up(GOOD3, deadline=DEADLINE + 100)
        out = R.preview_pins(self.reg, "t1", ["ta"])
        self.assertEqual(out, {"pinned": True, "teams": {"ta": "ta-v1", "tb": "tb-v1"}, "pending": []})

    def test_a_preview_of_a_team_from_another_tournament_is_refused(self):
        with self.assertRaises(R.Conflict):
            R.preview_pins(self.reg, "t2", ["ta"])

    def test_an_old_inconclusive_version_does_not_block_when_a_newer_one_is_active(self):
        s = self.up(GOOD3)
        self.check(s, GOOD3, "inconclusive", reasons=[{"code": "T-PLATFORM", "message": "again"}])
        v4 = self.up(GOOD3 + b"#\n")
        self.check(v4, GOOD3 + b"#\n")
        self.clock.t = DEADLINE
        self.assertEqual(self.pin()["ta"], "ta-v3")

    def test_a_team_without_a_valid_version_is_pinned_as_none(self):
        self.up(b"def turn(:\n", who=actor("c", teams=("tc",), captain=("tc",)), team="tc")
        self.clock.t = DEADLINE
        pins = self.pin(teams=("ta", "tb", "tc"))
        self.assertIsNone(pins["tc"])
        with self.assertRaises(R.NotFound):
            R.pinned_folder(self.reg, "t1", "tc", now=self.clock)

    def test_a_team_that_never_uploaded_is_pinned_as_none(self):
        self.clock.t = DEADLINE
        self.assertIsNone(self.pin(teams=("ta", "tz"))["tz"])

    def test_a_team_of_another_tournament_cannot_be_pinned(self):
        self.clock.t = DEADLINE
        with self.assertRaises(R.Conflict):
            R.pin_tournament(self.reg, "t2", ["ta"], deadline_at=DEADLINE, now=self.clock)

    def test_a_changed_pinned_file_is_refused_and_reported(self):
        self.clock.t = DEADLINE
        self.pin()
        self.assertEqual(R.verify_pins(self.reg, "t1", now=self.clock), [])
        f = self.reg.root / "tb-v1" / "bot.py"
        os.chmod(f.parent, 0o700)
        os.chmod(f, 0o600)
        f.write_bytes(b"def turn():\n    pass  # changed\n")
        self.assertEqual(R.verify_pins(self.reg, "t1", now=self.clock), ["tb-v1"])
        with self.assertRaises(R.Unavailable):
            R.pinned_folder(self.reg, "t1", "tb", now=self.clock)
        self.assertEqual(R.pinned_folder(self.reg, "t1", "ta", now=self.clock), self.reg.root / "ta-v1")
        self.assertTrue(self.state()["incidents"])

    def test_bad_arguments(self):
        for teams in ([], ["ta", "ta"], ["../x"], "ta"):
            with self.subTest(teams=teams), self.assertRaises(ValueError):
                R.pin_tournament(self.reg, "t1", teams, deadline_at=0, now=self.clock)
        with self.assertRaises(R.NotFound):
            R.verify_pins(self.reg, "t1")


@unittest.skipUnless(os.environ.get("BIO_INTEGRATION") == "1", "set BIO_INTEGRATION=1 to play real matches")
class RealMatches(Base):
    def setUp(self):
        super().setUp()
        lock = L.load_lock()
        self.py = L.resolve_python(None, None, lock)
        self.play = T.launcher_play(L.DEFAULT_SCAFFOLD, self.py, self.dir / "out", lock_path=self.dir / "host.lock", timeout=120)
        self.src = L.DEFAULT_SCAFFOLD / "src" / "examplefuncsplayer_py" / "bot.py"
        self.bots = Path(L.__file__).resolve().parent / "tests" / "bots"

    def real_check(self, folder):
        return T.check_submission(folder, play=self.play)

    def test_a_stored_version_is_checked_activated_pinned_and_played_by_the_match_runner(self):
        data = self.src.read_bytes()
        a = self.up(data)
        b = self.up(data, who=OTHER_TEAM, team="tb")
        for s in (a, b):
            v = R.run_check(self.reg, s["id"], self.real_check, now=self.clock)
            self.assertEqual((v["validation_status"], v["is_active"]), ("valid", True), v)
        self.clock.t = DEADLINE
        pins = R.pin_tournament(self.reg, "t1", ["ta", "tb"], deadline_at=DEADLINE, now=self.clock)
        refs = {t: R.pinned_folder(self.reg, "t1", t, now=self.clock).name for t in pins}
        out = L.run_match(L.DEFAULT_SCAFFOLD, self.py, self.reg.root, refs["ta"], refs["tb"], "DefaultSmall",
                          self.dir / "match", 120, True, True)
        self.assertEqual((out["outcome"], out.get("classification")), ("completed", "normal"), out)

    def test_a_real_crashing_bot_is_rejected_and_the_active_version_stays(self):
        good = self.up(self.src.read_bytes())
        R.run_check(self.reg, good["id"], self.real_check, now=self.clock)
        bad = self.up((self.bots / "crash_py" / "bot.py").read_bytes())
        v = R.run_check(self.reg, bad["id"], self.real_check, now=self.clock)
        self.assertEqual((v["validation_status"], v["is_active"]), ("invalid", False), v)
        self.assertEqual(v["validations"][-1]["reasons"][0]["code"], "T-CRASH")
        self.assertEqual(R.active_submission(self.reg, CAPTAIN, "ta")["id"], good["id"])


if __name__ == "__main__":
    unittest.main()
