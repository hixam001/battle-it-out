# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for the tournament lifecycle, approval and deadlines (BIO-EPIC-06, PRD 6.1; CN-019).

All unit tests: a fake clock, a JSON file in a temporary folder, a real replay vault for archive.

    python3 -m unittest backend.tournaments.tests.test_tournaments -v
"""
import json
import tempfile
import threading
import unittest
from pathlib import Path

from backend.match_orchestrator import replays as P
from backend.match_orchestrator.store import StoreError
from backend.submission_registry import registry as R
from backend.tournaments import tournaments as T

NOW = 1_000_000.0
REG_D, SUB_D = NOW + 1_000, NOW + 2_000


class Clock:
    def __init__(self, t=NOW):
        self.t = float(t)

    def __call__(self):
        return self.t


def actor(user, role, tournaments=(), teams=()):
    return R.Actor(user, role, frozenset(teams), frozenset(), frozenset(tournaments))


ADMIN = actor("adm", "admin")
ADMIN2 = actor("adm2", "admin")
ORG = actor("org1", "organizer")                    # creates t1
ORG_ASSIGNED = actor("org2", "organizer", ("t1",))   # assigned by an Admin
ORG_OTHER = actor("org3", "organizer", ("t9",))
PART = actor("p1", "participant", ("t1",), ("ta",))
PART_OUT = actor("p2", "participant", (), ("tb",))


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.clock = Clock()
        self.reg = T.Tournaments.at(self.dir / "tournaments.json")
        self.n = 0

    def make(self, who=ORG, tid="t1", reg_d=REG_D, sub_d=SUB_D, **kw):
        self.n += 1
        return T.create(self.reg, who, tid, kw.pop("name", "Cup"), kw.pop("description", "d"), reg_d, sub_d,
                        idempotency_key=kw.pop("key", f"k{self.n}"), now=self.clock, **kw)

    def approved(self, who=ORG, tid="t1"):
        self.make(who, tid)
        if who.role == "organizer":
            T.submit_for_approval(self.reg, who, tid, now=self.clock)
        T.approve(self.reg, ADMIN, tid, confirm=True, now=self.clock)

    def opened(self, tid="t1"):
        self.approved(tid=tid)
        T.open_registration(self.reg, ADMIN, tid, now=self.clock)

    def vault(self):
        return P.Vault(self.dir / "vault", P.ReplayIndex(self.dir / "replays.json"))

    def state(self):
        return self.reg.store.snapshot()

    def status(self, tid="t1"):
        return self.state()["tournaments"][tid]["status"]

    def version(self, tid="t1"):
        return self.state()["tournaments"][tid]["version"]


class Create(Base):
    def test_an_organizer_and_an_admin_create_drafts_a_participant_cannot(self):
        self.assertEqual(self.make(ORG)["status"], "draft")
        self.assertEqual(self.make(ADMIN, "t2")["status"], "draft")
        for who in (PART, None, "admin"):
            with self.assertRaises(T.Forbidden):
                self.make(who, "t3")

    def test_the_view_has_both_deadlines_and_the_creator(self):
        v = self.make()
        self.assertEqual((v["registration_deadline"], v["submission_deadline"], v["created_by"], v["version"]),
                         (REG_D, SUB_D, "org1", 1))

    def test_a_repeated_create_returns_the_same_tournament_and_other_content_is_a_conflict(self):
        a = self.make(key="same")
        b = T.create(self.reg, ORG, "t1", "Cup", "d", REG_D, SUB_D, idempotency_key="same", now=self.clock)
        self.assertEqual(a, b)
        after_deadline = T.create(self.reg, ORG, "t1", "Cup", "d", REG_D, SUB_D,
                                  idempotency_key="same", now=lambda: SUB_D + 1)
        self.assertEqual(a, after_deadline)
        with self.assertRaises(T.Conflict):
            T.create(self.reg, ORG, "t2", "Cup", "d", REG_D, SUB_D, idempotency_key="same", now=self.clock)
        with self.assertRaises(T.Conflict):
            T.create(self.reg, ORG, "t1", "Other", "d", REG_D, SUB_D, idempotency_key="same", now=self.clock)
        self.assertEqual(len(self.state()["tournaments"]), 1)

    def test_an_existing_id_is_a_conflict_even_with_a_new_key(self):
        self.make()
        with self.assertRaises(T.Conflict):
            self.make(ADMIN)

    def test_bad_input_is_refused_and_nothing_is_stored(self):
        bad = [dict(name=""), dict(name="x" * 121), dict(name=7), dict(description="x" * 2001), dict(name="a\x00b"),
               dict(reg_d=NOW - 1), dict(reg_d=float("nan")), dict(reg_d=True), dict(reg_d="2027-01-01"),
               dict(reg_d=SUB_D + 1), dict(sub_d=float("inf")), dict(tid="../x"), dict(tid=""), dict(key="bad key")]
        for i, kw in enumerate(bad):
            with self.subTest(kw=kw), self.assertRaises(T.Invalid):
                self.make(**kw)
        self.assertEqual(self.state()["tournaments"], {})

    def test_the_two_deadlines_may_be_equal_but_not_reversed(self):
        self.make(reg_d=SUB_D, sub_d=SUB_D)
        with self.assertRaises(T.Invalid):
            self.make(tid="t2", reg_d=SUB_D + 1, sub_d=SUB_D)

    def test_the_deadline_history_and_audit_start_with_the_creation(self):
        self.make()
        h = T.deadline_history(self.reg, ORG, "t1")
        self.assertEqual([(x["type"], x["deadline_at"], x["reason"]) for x in h],
                         [("registration", REG_D, "created"), ("submission", SUB_D, "created")])
        self.assertEqual([a["action"] for a in T.audit_log(self.reg, ADMIN, "t1")], ["create"])


class Approval(Base):
    def test_an_organizer_draft_needs_submission_and_an_admin(self):
        self.make()
        with self.assertRaises(T.Conflict):                       # never submitted
            T.approve(self.reg, ADMIN, "t1", confirm=True, now=self.clock)
        T.submit_for_approval(self.reg, ORG, "t1", now=self.clock)
        self.assertEqual(self.status(), "pending_approval")
        v = T.approve(self.reg, ADMIN, "t1", confirm=True, now=self.clock)
        self.assertEqual((v["status"], v["approved_by"]), ("approved", "adm"))

    def test_an_admin_draft_is_approved_directly(self):
        self.make(ADMIN)
        self.assertEqual(T.approve(self.reg, ADMIN, "t1", confirm=True, now=self.clock)["status"], "approved")

    def test_only_the_creating_organizer_submits(self):
        self.make()
        for who in (ORG_ASSIGNED, ADMIN):
            with self.assertRaises((T.Forbidden, T.NotFound)):
                T.submit_for_approval(self.reg, who, "t1", now=self.clock)
        with self.assertRaises(T.NotFound):
            T.submit_for_approval(self.reg, ORG_OTHER, "t1", now=self.clock)
        self.assertEqual(self.status(), "draft")

    def test_the_assigned_organizer_who_did_not_create_it_is_refused_as_forbidden(self):
        self.make()
        with self.assertRaises(T.Forbidden):
            T.submit_for_approval(self.reg, ORG_ASSIGNED, "t1", now=self.clock)

    def test_only_an_admin_approves_and_rejects_and_approval_needs_confirm(self):
        self.make()
        T.submit_for_approval(self.reg, ORG, "t1", now=self.clock)
        for who in (ORG, ORG_ASSIGNED, PART, None):
            with self.subTest(who=who), self.assertRaises(T.Forbidden):
                T.approve(self.reg, who, "t1", confirm=True, now=self.clock)
            with self.subTest(who=who), self.assertRaises(T.Forbidden):
                T.reject(self.reg, who, "t1", "no", now=self.clock)
        with self.assertRaises(T.Invalid):
            T.approve(self.reg, ADMIN, "t1", now=self.clock)
        self.assertEqual(self.status(), "pending_approval")

    def test_a_rejection_needs_a_reason_is_kept_and_the_organizer_edits_and_resubmits(self):
        self.make()
        T.submit_for_approval(self.reg, ORG, "t1", now=self.clock)
        with self.assertRaises(T.Invalid):
            T.reject(self.reg, ADMIN, "t1", "  ", now=self.clock)
        v = T.reject(self.reg, ADMIN, "t1", "Move the dates", now=self.clock)
        self.assertEqual((v["status"], v["rejection_reason"]), ("rejected", "Move the dates"))
        T.edit(self.reg, ORG, "t1", {"submission_deadline": SUB_D + 500}, now=self.clock)
        T.submit_for_approval(self.reg, ORG, "t1", now=self.clock)
        v = T.approve(self.reg, ADMIN, "t1", confirm=True, now=self.clock)
        self.assertEqual((v["status"], v["rejection_reason"], v["submission_deadline"]), ("approved", None, SUB_D + 500))
        self.assertEqual([a["decision"] for a in self.state()["tournaments"]["t1"]["approvals"]], ["rejected", "approved"])

    def test_a_pending_tournament_cannot_be_edited_while_the_admin_reviews_it(self):
        self.make()
        T.submit_for_approval(self.reg, ORG, "t1", now=self.clock)
        with self.assertRaises(T.Conflict):
            T.edit(self.reg, ORG, "t1", {"name": "Other"}, now=self.clock)

    def test_a_decision_is_refused_in_the_wrong_state(self):
        self.approved()
        with self.assertRaises(T.Conflict):
            T.approve(self.reg, ADMIN, "t1", confirm=True, now=self.clock)
        with self.assertRaises(T.Conflict):
            T.reject(self.reg, ADMIN, "t1", "late", now=self.clock)
        with self.assertRaises(T.Conflict):
            T.submit_for_approval(self.reg, ORG, "t1", now=self.clock)

    def test_a_tournament_whose_registration_closed_cannot_be_submitted_or_approved(self):
        self.make()
        self.clock.t = REG_D
        with self.assertRaises(T.Conflict):
            T.submit_for_approval(self.reg, ORG, "t1", now=self.clock)
        self.make(ADMIN, "t2", reg_d=REG_D + 10, sub_d=SUB_D + 10)
        self.clock.t = REG_D + 10
        with self.assertRaises(T.Conflict):
            T.approve(self.reg, ADMIN, "t2", confirm=True, now=self.clock)


class Editing(Base):
    def test_the_creator_and_the_assigned_organizer_and_an_admin_edit_others_cannot(self):
        self.approved()
        T.edit(self.reg, ORG, "t1", {"name": "A"}, now=self.clock)
        T.edit(self.reg, ORG_ASSIGNED, "t1", {"name": "B"}, now=self.clock)
        T.edit(self.reg, ADMIN, "t1", {"name": "C"}, now=self.clock)
        with self.assertRaises(T.NotFound):
            T.edit(self.reg, ORG_OTHER, "t1", {"name": "D"}, now=self.clock)
        with self.assertRaises(T.Forbidden):
            T.edit(self.reg, PART, "t1", {"name": "D"}, now=self.clock)
        self.assertEqual(self.state()["tournaments"]["t1"]["name"], "C")

    def test_unknown_fields_and_bad_values_are_refused_whole(self):
        self.approved()
        before = self.state()
        for changes in ({}, {"status": "running"}, {"name": "ok", "version": 9}, {"name": ""}, {"map_pool_id": "../x"},
                        {"submission_deadline": NOW - 5}, {"registration_deadline": SUB_D + 1}, [], None):
            with self.subTest(changes=changes), self.assertRaises(T.Invalid):
                T.edit(self.reg, ORG, "t1", changes, now=self.clock)
        self.assertEqual(self.state(), before)

    def test_the_map_pool_and_deadlines_can_be_set_before_the_deadline_and_the_history_records_it(self):
        self.approved()
        v = T.edit(self.reg, ORG, "t1", {"map_pool_id": "pool1", "submission_deadline": SUB_D + 100}, now=self.clock)
        self.assertEqual((v["map_pool_id"], v["submission_deadline"]), ("pool1", SUB_D + 100))
        sub = [h for h in T.deadline_history(self.reg, ORG, "t1") if h["type"] == "submission"]
        self.assertEqual([(h["deadline_at"], h["superseded_at"] is None) for h in sub], [(SUB_D, False), (SUB_D + 100, True)])
        self.assertEqual(T.deadline(self.reg, "t1", "submission"), SUB_D + 100)

    def test_a_field_is_frozen_by_its_own_deadline_only(self):
        self.opened()
        self.clock.t = REG_D + 1                                   # registration closed, submissions still open
        with self.assertRaises(T.DeadlineLocked):
            T.edit(self.reg, ORG, "t1", {"registration_deadline": REG_D + 10}, now=self.clock)
        T.edit(self.reg, ORG, "t1", {"map_pool_id": "pool1"}, now=self.clock)
        self.clock.t = SUB_D + 1
        with self.assertRaises(T.DeadlineLocked):
            T.edit(self.reg, ORG, "t1", {"map_pool_id": "pool2"}, now=self.clock)
        with self.assertRaises(T.DeadlineLocked):
            T.edit(self.reg, ADMIN, "t1", {"name": "late"}, now=self.clock)    # an Admin needs the extension too
        self.assertEqual(self.state()["tournaments"]["t1"]["map_pool_id"], "pool1")

    def test_a_running_or_later_tournament_cannot_be_edited(self):
        self.opened()
        self.clock.t = SUB_D + 1
        T.mark_running(self.reg, "t1", "scheduler", now=self.clock)
        with self.assertRaises(T.Conflict):
            T.edit(self.reg, ADMIN, "t1", {"name": "x"}, now=self.clock)

    def test_a_stale_expected_version_is_a_conflict_and_the_right_one_is_not(self):
        self.approved()
        v = self.version()
        T.edit(self.reg, ORG, "t1", {"name": "A"}, expected_version=v, now=self.clock)
        with self.assertRaises(T.Conflict):
            T.edit(self.reg, ORG_ASSIGNED, "t1", {"name": "B"}, expected_version=v, now=self.clock)
        self.assertEqual(self.state()["tournaments"]["t1"]["name"], "A")

    def test_an_edit_that_changes_nothing_does_not_bump_the_version_or_the_audit(self):
        self.approved()
        v, n = self.version(), len(self.state()["audit"])
        T.edit(self.reg, ORG, "t1", {"name": "Cup"}, now=self.clock)
        self.assertEqual((self.version(), len(self.state()["audit"])), (v, n))

    def test_two_editors_at_once_do_not_lose_an_update(self):
        self.approved()
        v = self.version()
        out = []

        def go(who, name):
            try:
                T.edit(self.reg, who, "t1", {"name": name}, expected_version=v, now=self.clock)
                out.append("ok")
            except T.Conflict:
                out.append("conflict")
        ts = [threading.Thread(target=go, args=(w, n)) for w, n in ((ORG, "A"), (ORG_ASSIGNED, "B"), (ADMIN, "C"))]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(sorted(out), ["conflict", "conflict", "ok"])


class Extension(Base):
    def test_an_admin_extends_a_passed_deadline_and_the_notice_says_who_why_and_when(self):
        self.opened()
        self.clock.t = SUB_D + 5
        out = T.extend_deadline(self.reg, ADMIN, "t1", "submission", SUB_D + 1_000, "Venue problem", confirm=True, now=self.clock)
        self.assertEqual(out["tournament"]["submission_deadline"], SUB_D + 1_000)
        self.assertEqual({k: out["notice"][k] for k in ("kind", "deadline_type", "old", "new", "reason", "authorizer")},
                         {"kind": "deadline_extended", "deadline_type": "submission", "old": SUB_D, "new": SUB_D + 1_000,
                          "reason": "Venue problem", "authorizer": "adm"})
        self.assertEqual(T.deadline(self.reg, "t1", "submission"), SUB_D + 1_000)
        T.edit(self.reg, ORG, "t1", {"map_pool_id": "pool1"}, now=self.clock)     # reopened for ordinary edits too

    def test_registration_and_submission_are_extended_independently(self):
        self.opened()
        T.extend_deadline(self.reg, ADMIN, "t1", "registration", REG_D + 100, "r", confirm=True, now=self.clock)
        v = T.get(self.reg, ADMIN, "t1")
        self.assertEqual((v["registration_deadline"], v["submission_deadline"]), (REG_D + 100, SUB_D))

    def test_only_an_admin_with_confirm_a_reason_and_a_later_time(self):
        self.opened()
        for who in (ORG, ORG_ASSIGNED, PART, None):
            with self.subTest(who=who), self.assertRaises(T.Forbidden):
                T.extend_deadline(self.reg, who, "t1", "submission", SUB_D + 9, "r", confirm=True, now=self.clock)
        args = ("t1", "submission", SUB_D + 9, "r")
        with self.assertRaises(T.Invalid):
            T.extend_deadline(self.reg, ADMIN, *args, now=self.clock)                      # no confirm
        for bad in (("t1", "other", SUB_D + 9, "r"), ("t1", "submission", SUB_D, "r"), ("t1", "submission", SUB_D - 1, "r"),
                    ("t1", "submission", SUB_D + 9, ""), ("t1", "submission", "x", "r")):
            with self.subTest(bad=bad), self.assertRaises(T.Invalid):
                T.extend_deadline(self.reg, ADMIN, *bad, confirm=True, now=self.clock)
        self.assertEqual(T.deadline(self.reg, "t1", "submission"), SUB_D)

    def test_registration_cannot_be_extended_past_the_submission_deadline(self):
        self.opened()
        with self.assertRaises(T.Invalid):
            T.extend_deadline(self.reg, ADMIN, "t1", "registration", SUB_D + 1, "r", confirm=True, now=self.clock)

    def test_nothing_is_extended_once_the_bracket_is_drawn(self):
        self.opened()
        self.clock.t = SUB_D + 1
        T.mark_running(self.reg, "t1", "scheduler", now=self.clock)
        with self.assertRaises(T.Conflict):
            T.extend_deadline(self.reg, ADMIN, "t1", "submission", SUB_D + 99, "r", confirm=True, now=self.clock)

    def test_an_unknown_tournament_is_not_found(self):
        with self.assertRaises(T.NotFound):
            T.extend_deadline(self.reg, ADMIN, "nope", "submission", SUB_D + 9, "r", confirm=True, now=self.clock)


class Override(Base):
    def test_an_admin_overrides_a_locked_setting_with_a_reason_and_the_notice_names_everything(self):
        self.opened()
        self.clock.t = SUB_D + 1
        out = T.emergency_override(self.reg, ADMIN, "t1", "map_pool_id", "pool2", "Bad map found", confirm=True, now=self.clock)
        self.assertEqual(out["tournament"]["map_pool_id"], "pool2")
        n = out["notice"]
        self.assertEqual((n["kind"], n["setting"], n["old"], n["new"], n["reason"], n["authorizer"]),
                         ("emergency_override", "map_pool_id", None, "pool2", "Bad map found", "adm"))
        self.assertIn("at", n)
        entry = [a for a in T.audit_log(self.reg, ADMIN, "t1") if a["action"] == "emergency_override"][0]
        self.assertEqual((entry["setting"], entry["reason"], entry["actor"]), ("map_pool_id", "Bad map found", "adm"))

    def test_only_an_admin_with_confirm_a_reason_and_an_allowed_setting(self):
        self.opened()
        for who in (ORG, ORG_ASSIGNED, PART):
            with self.subTest(who=who), self.assertRaises(T.Forbidden):
                T.emergency_override(self.reg, who, "t1", "name", "x", "r", confirm=True, now=self.clock)
        for bad in (dict(setting="name", value="x", reason="r"),                         # no confirm
                    dict(setting="submission_deadline", value=SUB_D + 5, reason="r", confirm=True),
                    dict(setting="status", value="approved", reason="r", confirm=True),
                    dict(setting="name", value="x", reason="", confirm=True),
                    dict(setting="name", value="", reason="r", confirm=True)):
            with self.subTest(bad=bad), self.assertRaises(T.Invalid):
                T.emergency_override(self.reg, ADMIN, "t1", now=self.clock, **bad)

    def test_the_map_pool_cannot_change_after_the_draw_and_a_closed_tournament_cannot_change_at_all(self):
        self.opened()
        self.clock.t = SUB_D + 1
        T.mark_running(self.reg, "t1", "scheduler", now=self.clock)
        with self.assertRaises(T.Conflict):
            T.emergency_override(self.reg, ADMIN, "t1", "map_pool_id", "p", "r", confirm=True, now=self.clock)
        T.emergency_override(self.reg, ADMIN, "t1", "description", "new text", "typo", confirm=True, now=self.clock)
        T.mark_completed(self.reg, "t1", "scheduler", now=self.clock)
        T.archive(self.reg, ADMIN, "t1", self.vault(), confirm=True, now=self.clock)
        with self.assertRaises(T.Conflict):
            T.emergency_override(self.reg, ADMIN, "t1", "name", "x", "r", confirm=True, now=self.clock)


class Lifecycle(Base):
    def test_registration_opens_only_for_an_approved_tournament_before_its_deadline(self):
        self.make()
        with self.assertRaises(T.Conflict):
            T.open_registration(self.reg, ADMIN, "t1", now=self.clock)
        T.submit_for_approval(self.reg, ORG, "t1", now=self.clock)
        T.approve(self.reg, ADMIN, "t1", confirm=True, now=self.clock)
        with self.assertRaises(T.Forbidden):
            T.open_registration(self.reg, PART, "t1", now=self.clock)
        self.clock.t = REG_D
        with self.assertRaises(T.DeadlineLocked):
            T.open_registration(self.reg, ORG, "t1", now=self.clock)
        self.clock.t = NOW
        self.assertEqual(T.open_registration(self.reg, ORG, "t1", now=self.clock)["status"], "registration_open")

    def test_running_needs_the_submission_deadline_and_repeats_harmlessly(self):
        self.opened()
        with self.assertRaises(T.Conflict):
            T.mark_running(self.reg, "t1", "scheduler", now=self.clock)
        self.clock.t = SUB_D
        self.assertEqual(T.mark_running(self.reg, "t1", "scheduler", now=self.clock)["status"], "running")
        v = self.version()
        T.mark_running(self.reg, "t1", "scheduler", now=self.clock)
        self.assertEqual(self.version(), v)

    def test_completion_needs_running_and_repeats_harmlessly(self):
        self.opened()
        with self.assertRaises(T.Conflict):
            T.mark_completed(self.reg, "t1", "scheduler", now=self.clock)
        self.clock.t = SUB_D
        T.mark_running(self.reg, "t1", "scheduler", now=self.clock)
        T.mark_completed(self.reg, "t1", "scheduler", now=self.clock)
        T.mark_completed(self.reg, "t1", "scheduler", now=self.clock)
        self.assertEqual(self.status(), "completed")

    def test_the_system_calls_need_a_named_actor(self):
        self.opened()
        for f in (T.mark_running, T.mark_completed):
            with self.assertRaises(T.Invalid):
                f(self.reg, "t1", "", now=self.clock)

    def test_every_transition_is_audited_in_order(self):
        self.opened()
        self.clock.t = SUB_D
        T.mark_running(self.reg, "t1", "scheduler", now=self.clock)
        log = T.audit_log(self.reg, ADMIN, "t1")
        self.assertEqual([(a["action"], a.get("to")) for a in log],
                         [("create", None), ("submit_for_approval", "pending_approval"), ("approve", "approved"),
                          ("open_registration", "registration_open"), ("mark_running", "running")])


class ArchiveAndDelete(Base):
    def done(self):
        self.opened()
        self.clock.t = SUB_D
        T.mark_running(self.reg, "t1", "scheduler", now=self.clock)
        T.mark_completed(self.reg, "t1", "scheduler", now=self.clock)
        return self.vault()

    def test_archive_purges_the_replays_then_marks_the_tournament(self):
        vault = self.done()
        out = T.archive(self.reg, ORG, "t1", vault, confirm=True, now=self.clock)
        self.assertEqual(out, {"status": "archived", "replays_deleted": True})
        self.assertEqual((self.status(), P.tournament_state(vault, "t1")["status"]), ("archived", "archived"))
        self.assertEqual(T.archive(self.reg, ORG, "t1", vault, confirm=True, now=self.clock), out)    # repeat

    def test_only_a_completed_tournament_by_its_staff_with_confirm_is_archived(self):
        self.opened()
        vault = self.vault()
        with self.assertRaises(T.Conflict):
            T.archive(self.reg, ADMIN, "t1", vault, confirm=True, now=self.clock)
        self.assertIsNone(P.tournament_state(vault, "t1"))                 # nothing was marked in the vault either
        self.clock.t = SUB_D
        T.mark_running(self.reg, "t1", "scheduler", now=self.clock)
        T.mark_completed(self.reg, "t1", "scheduler", now=self.clock)
        for who in (PART, ORG_OTHER):
            with self.assertRaises((T.Forbidden, T.NotFound)):
                T.archive(self.reg, who, "t1", vault, confirm=True, now=self.clock)
        with self.assertRaises(T.Invalid):
            T.archive(self.reg, ADMIN, "t1", vault, now=self.clock)
        self.assertEqual(self.status(), "completed")

    def test_a_crash_after_the_vault_mark_is_finished_by_the_retry(self):
        vault = self.done()
        P.archive_tournament(vault, "t1", "adm", now=self.clock)           # the vault step happened, the record step did not
        self.assertEqual(self.status(), "completed")
        T.archive(self.reg, ADMIN, "t1", vault, confirm=True, now=self.clock)
        self.assertEqual(self.status(), "archived")

    def test_delete_erases_the_text_keeps_the_audit_and_repeats_harmlessly(self):
        self.approved()
        out = T.delete(self.reg, ADMIN, "t1", "created by mistake", confirm=True, now=self.clock)
        self.assertEqual(out["status"], "deleted")
        rec = self.state()["tournaments"]["t1"]
        self.assertEqual((rec["status"], rec["name"], rec["description"]), ("deleted", "", ""))
        self.assertEqual(T.delete(self.reg, ADMIN, "t1", "again", confirm=True, now=self.clock), out)
        self.assertEqual(T.audit_log(self.reg, ADMIN, "t1")[-1]["reason"], "created by mistake")
        self.assertEqual(self.state()["audit"][out["audit_event_id"]]["action"], "delete")

    def test_delete_is_admin_only_confirmed_with_a_reason_and_not_while_running_or_unarchived(self):
        self.opened()
        for who in (ORG, ORG_ASSIGNED, PART):
            with self.assertRaises(T.Forbidden):
                T.delete(self.reg, who, "t1", "r", confirm=True, now=self.clock)
        with self.assertRaises(T.Invalid):
            T.delete(self.reg, ADMIN, "t1", "r", now=self.clock)
        with self.assertRaises(T.Invalid):
            T.delete(self.reg, ADMIN, "t1", "", confirm=True, now=self.clock)
        self.clock.t = SUB_D
        T.mark_running(self.reg, "t1", "scheduler", now=self.clock)
        with self.assertRaises(T.Conflict):
            T.delete(self.reg, ADMIN, "t1", "r", confirm=True, now=self.clock)
        T.mark_completed(self.reg, "t1", "scheduler", now=self.clock)
        with self.assertRaises(T.Conflict) as cm:
            T.delete(self.reg, ADMIN, "t1", "r", confirm=True, now=self.clock)
        self.assertIn("archived", str(cm.exception))
        T.archive(self.reg, ADMIN, "t1", self.vault(), confirm=True, now=self.clock)
        self.assertEqual(T.delete(self.reg, ADMIN, "t1", "retention over", confirm=True, now=self.clock)["status"], "deleted")

    def test_a_deleted_tournament_is_known_only_to_an_admin(self):
        self.approved()
        T.delete(self.reg, ADMIN, "t1", "r", confirm=True, now=self.clock)
        for who in (ORG, ORG_ASSIGNED, PART):
            with self.assertRaises(T.NotFound):
                T.get(self.reg, who, "t1")
        self.assertEqual(T.get(self.reg, ADMIN, "t1")["status"], "deleted")
        self.assertEqual(T.list_visible(self.reg, ADMIN), [])


class Visibility(Base):
    def test_who_sees_what(self):
        self.make()                                   # t1 draft by ORG
        self.opened("t2")                             # t2 registration_open (created by ORG)
        self.assertEqual([v["id"] for v in T.list_visible(self.reg, ADMIN)], ["t1", "t2"])
        self.assertEqual([v["id"] for v in T.list_visible(self.reg, ORG)], ["t1", "t2"])
        self.assertEqual(T.list_visible(self.reg, ORG_OTHER), [])
        self.assertEqual([v["id"] for v in T.list_visible(self.reg, ORG_ASSIGNED)], ["t1"])
        part = actor("p", "participant", ("t1", "t2"), ("ta",))
        self.assertEqual([v["id"] for v in T.list_visible(self.reg, part)], ["t2"])      # a draft is not published
        self.assertEqual(T.list_visible(self.reg, PART_OUT), [])
        self.assertEqual(T.list_visible(self.reg, None), [])

    def test_a_stranger_cannot_tell_a_hidden_tournament_from_a_missing_one(self):
        self.make()
        for who in (PART, PART_OUT, ORG_OTHER, None):
            with self.assertRaises(T.NotFound) as hidden:
                T.get(self.reg, who, "t1")
            with self.assertRaises(T.NotFound) as missing:
                T.get(self.reg, who, "zz")
            self.assertEqual(str(hidden.exception), str(missing.exception))

    def test_a_participant_sees_the_public_fields_only(self):
        self.opened()
        v = T.get(self.reg, PART, "t1")
        self.assertEqual(set(v), {"id", "name", "description", "status", "version", "map_pool_id",
                                  "registration_deadline", "submission_deadline"})
        self.assertIn("created_by", T.get(self.reg, ORG, "t1"))

    def test_a_participant_cannot_change_anything_and_is_not_given_the_audit(self):
        self.opened()
        with self.assertRaises(T.Forbidden):
            T.edit(self.reg, PART, "t1", {"name": "x"}, now=self.clock)
        with self.assertRaises(T.Forbidden):
            T.audit_log(self.reg, PART, "t1")
        with self.assertRaises(T.Forbidden):
            T.deadline_history(self.reg, PART, "t1")

    def test_a_returned_view_is_a_copy(self):
        self.approved()
        v = T.get(self.reg, ADMIN, "t1")
        v["name"] = "hacked"
        self.assertEqual(T.get(self.reg, ADMIN, "t1")["name"], "Cup")

    def test_deadline_lookup_rejects_bad_input(self):
        self.approved()
        with self.assertRaises(T.Invalid):
            T.deadline(self.reg, "t1", "both")
        with self.assertRaises(T.NotFound):
            T.deadline(self.reg, "nope", "submission")
        with self.assertRaises(T.Invalid):
            T.deadline(self.reg, "../x", "submission")


class Storage(Base):
    def test_a_damaged_file_is_never_read_as_an_empty_store(self):
        self.make()
        (self.dir / "tournaments.json").write_text("{not json")
        with self.assertRaises(StoreError):
            T.get(self.reg, ADMIN, "t1")
        (self.dir / "tournaments.json").write_text(json.dumps({"schema": 1, "tournaments": []}))
        with self.assertRaises(StoreError):
            T.get(self.reg, ADMIN, "t1")

    def test_state_survives_a_new_handle(self):
        self.approved()
        again = T.Tournaments.at(self.dir / "tournaments.json")
        self.assertEqual(T.get(again, ADMIN, "t1")["status"], "approved")

    def test_a_refused_change_leaves_the_file_untouched(self):
        self.approved()
        raw = (self.dir / "tournaments.json").read_bytes()
        with self.assertRaises(T.Conflict):
            T.approve(self.reg, ADMIN, "t1", confirm=True, now=self.clock)
        self.assertEqual((self.dir / "tournaments.json").read_bytes(), raw)


if __name__ == "__main__":
    unittest.main()
