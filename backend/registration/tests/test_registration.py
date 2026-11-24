# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for the official roster, invitation codes and registration (BIO-EPIC-05, SRD-038..044; CN-020).

All unit tests: a fake clock, JSON files in a temporary folder, a real tournament record and a real submission
registry for the Actor hand-over.

    python3 -m unittest backend.registration.tests.test_registration -v
"""
import json
import tempfile
import threading
import unittest
from pathlib import Path

from backend.match_orchestrator.store import StoreError
from backend.registration import registration as G
from backend.submission_registry import registry as R
from backend.tournaments import tournaments as T

NOW = 1_000_000.0
REG_D, SUB_D = NOW + 1_000, NOW + 2_000


class Clock:
    def __init__(self, t=NOW):
        self.t = float(t)

    def __call__(self):
        return self.t


def actor(user, role, tournaments=()):
    return R.Actor(user, role, frozenset(), frozenset(), frozenset(tournaments))


ADMIN = actor("adm", "admin")
ORG = actor("org1", "organizer")                      # creates t1
ORG_ASSIGNED = actor("org2", "organizer", ("t1",))
ORG_OTHER = actor("org3", "organizer", ("t9",))
PART = R.Actor("p0", "participant")


def row(email, team="alpha", name="Alpha", n=1, role="member"):
    return {"email": email, "team_key": team, "team_name": name, "member_number": n, "role": role}


ROSTER = [row("cap@uni.edu", n=1, role="captain"), row("two@uni.edu", n=2), row("bob@uni.edu", "beta", "Beta", 1, "captain")]


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.clock = Clock()
        self.treg = T.Tournaments.at(self.dir / "tournaments.json")
        self.reg = G.Registration.at(self.dir / "registration.json", self.treg)
        self.n = 0

    def tournament(self, tid="t1", *, open_=True, reg_d=REG_D, sub_d=SUB_D):
        self.n += 1
        T.create(self.treg, ADMIN, tid, "Cup", "d", reg_d, sub_d, idempotency_key=f"k{self.n}", now=self.clock)
        T.approve(self.treg, ADMIN, tid, confirm=True, now=self.clock)
        if open_:
            T.open_registration(self.treg, ADMIN, tid, now=self.clock)

    def imp(self, rows=ROSTER, who=ADMIN, tid="t1"):
        return G.import_roster(self.reg, who, tid, rows, now=self.clock)

    def entries(self, tid="t1"):
        return {e["email"]: e for e in G.list_roster(self.reg, ADMIN, tid)}

    def issue(self, tid="t1", ids=None):
        out = G.issue_codes(self.reg, ADMIN, tid, ids, now=self.clock)
        by = {self._email(i["entry_id"], tid): i["code"] for i in out["issued"]}
        return by

    def _email(self, entry_id, tid="t1"):
        return next(e["email"] for e in G.list_roster(self.reg, ADMIN, tid) if e["id"] == entry_id)

    def claim(self, email, code, user="u1", tid="t1", **kw):
        return G.claim(self.reg, tid, email, code, user, now=self.clock, **kw)

    def state(self):
        return self.reg.store.snapshot()

    def ready(self):
        """Open tournament, ROSTER imported, a code for everybody."""
        self.tournament()
        self.imp()
        return self.issue()


class Email(unittest.TestCase):
    def test_email_is_trimmed_lower_cased_and_must_be_one_plain_ascii_address(self):
        self.assertEqual(G.normalize_email("  Ana.B@Uni.EDU "), "ana.b@uni.edu")
        for bad in ["", "a", "a@b", "a@@b.c", "a b@c.de", "a\n@b.cd", "ａ@b.cd", "é@b.cd", "a@b..cd", ".a@b.cd",
                    "a.@b.cd", "a@-b.cd", "x" * 250 + "@b.cd", None, 5, "a@b.c,d@e.fg", "<a@b.cd>"]:
            with self.subTest(bad=bad), self.assertRaises(G.Invalid):
                G.normalize_email(bad)


class Csv(unittest.TestCase):
    HEAD = "email,team_key,team_name,member_number,role\n"

    def test_a_csv_becomes_rows(self):
        rows = G.parse_csv(self.HEAD + "a@b.cd,alpha,Alpha,1,captain\n")
        self.assertEqual(rows, [{"email": "a@b.cd", "team_key": "alpha", "team_name": "Alpha", "member_number": "1",
                                 "role": "captain"}])

    def test_header_may_be_in_any_order_with_a_bom_and_other_case(self):
        rows = G.parse_csv("﻿Role,Email,team_key,team_name,member_number\ncaptain,a@b.cd,alpha,Alpha,1\n")
        self.assertEqual(rows[0]["email"], "a@b.cd")

    def test_wrong_header_extra_cells_missing_cells_nul_and_size_are_refused(self):
        for bad in ["email,team_key\na,b\n", self.HEAD + "a@b.cd,alpha,Alpha,1,captain,extra\n",
                    self.HEAD + "a@b.cd,alpha,Alpha\n", self.HEAD + "a@b.cd,alpha,Al\x00pha,1,captain\n",
                    self.HEAD + "x" * (G.MAX_CSV_BYTES + 1), "", self.HEAD + 'a@b.cd,"alpha,Alpha,1,captain\n', 5]:
            with self.subTest(bad=str(bad)[:30]), self.assertRaises(G.Invalid):
                G.parse_csv(bad)

    def test_too_many_rows_are_refused(self):
        text = self.HEAD + "a@b.cd,alpha,Alpha,1,captain\n" * (G.MAX_ENTRIES + 1)
        with self.assertRaises(G.Invalid):
            G.parse_csv(text)


class Import(Base):
    def test_rows_are_created_with_a_summary_and_a_batch_without_personal_data(self):
        self.tournament()
        out = self.imp()
        self.assertEqual((len(out["rejected"]), out["created"], out["updated"], out["unchanged"]), (0, 3, 0, 0))
        self.assertEqual(sorted(self.entries()), ["bob@uni.edu", "cap@uni.edu", "two@uni.edu"])
        batch = self.state()["tournaments"]["t1"]["batches"][0]
        self.assertEqual(batch["summary"], {"created": 3, "updated": 0, "unchanged": 0, "rejected": 0})
        self.assertNotIn("uni.edu", json.dumps(self.state()["audit"]))

    def test_importing_the_same_file_again_changes_nothing(self):
        self.tournament()
        self.imp()
        before = self.entries()
        out = self.imp()
        self.assertEqual((out["created"], out["updated"], out["unchanged"]), (0, 0, 3))
        self.assertEqual(self.entries(), before)

    def test_a_changed_row_updates_the_unregistered_entry_and_bumps_its_version(self):
        self.tournament()
        self.imp()
        out = self.imp([row("two@uni.edu", n=3)])
        self.assertEqual((out["updated"], out["created"]), (1, 0))
        e = self.entries()["two@uni.edu"]
        self.assertEqual((e["member_number"], e["version"]), (3, 2))

    def test_bad_rows_are_rejected_one_by_one_and_the_rest_applies(self):
        self.tournament()
        out = self.imp([row("ok@uni.edu", n=1, role="captain"), row("bad email"), row("dup@uni.edu", n=1),
                        {"email": "x@uni.edu"}, "not a row", row("ok@uni.edu", n=2),
                        {**row("z@uni.edu"), "extra": 1}, row("n@uni.edu", n=100), row("r@uni.edu", role="boss"),
                        row("k@uni.edu", team="bad key!"), row("c@uni.edu", n=5, role="captain")])
        # row 6 updates the first entry (a file is authoritative for an unregistered entry), which also frees the
        # captain seat, so row 11 is accepted
        self.assertEqual((out["created"], out["updated"]), (2, 1))
        self.assertEqual([r["row"] for r in out["rejected"]], [2, 3, 4, 5, 7, 8, 9, 10])
        self.assertEqual(sorted(self.entries()), ["c@uni.edu", "ok@uni.edu"])
        self.assertEqual(out["rejected"][2]["reason"], "missing: team_key, team_name, member_number, role_label")
        self.assertNotIn("uni.edu", json.dumps(out["rejected"]))

    def test_layout_rules_hold_member_number_captain_team_name_and_size(self):
        self.tournament()
        out = self.imp([row("a@uni.edu", n=1, role="captain"), row("b@uni.edu", n=1), row("c@uni.edu", n=2, role="captain"),
                        row("d@uni.edu", n=3, name="Other")])
        reasons = [r["reason"] for r in out["rejected"]]
        self.assertEqual(out["created"], 1)
        self.assertEqual(reasons, ["this member number is already used in the team", "the team already has a captain",
                                   "the team name differs from the other members of the team"])
        big = [row(f"m{i}@uni.edu", "big", "Big", i + 1) for i in range(G.MAX_TEAM_SIZE + 1)]
        out = self.imp(big)
        self.assertEqual((out["created"], len(out["rejected"])), (G.MAX_TEAM_SIZE, 1))

    def test_a_team_key_of_another_tournament_is_refused(self):
        self.tournament()
        self.tournament("t2")
        self.imp([row("a@uni.edu", role="captain")])
        out = G.import_roster(self.reg, ADMIN, "t2", [row("z@uni.edu", role="captain")], now=self.clock)
        self.assertEqual(out["rejected"][0]["reason"], "this team key belongs to another tournament")

    def test_whole_file_problems_raise(self):
        self.tournament()
        for rows in ([], "x", None, [row("a@uni.edu")] * (G.MAX_ENTRIES + 1)):
            with self.subTest(rows=str(rows)[:20]), self.assertRaises(G.Invalid):
                self.imp(rows)
        with self.assertRaises(G.Invalid):
            G.import_roster(self.reg, ADMIN, "t1", [row("a@uni.edu")], source_filename="", now=self.clock)

    def test_a_roster_larger_than_the_limit_rejects_the_rows_that_do_not_fit(self):
        self.tournament()
        old = G.MAX_ENTRIES
        G.MAX_ENTRIES = 2
        self.addCleanup(setattr, G, "MAX_ENTRIES", old)
        self.imp([row("p0@uni.edu", "t0", "T0")])
        out = self.imp([row(f"p{i}@uni.edu", f"t{i}", f"T{i}") for i in range(1, 3)])
        self.assertEqual(out["created"], 1)
        self.assertIn("at most 2 entries", out["rejected"][0]["reason"])

    def test_csv_rows_with_string_numbers_work_end_to_end(self):
        self.tournament()
        rows = G.parse_csv(Csv.HEAD + "A@Uni.edu,alpha,Alpha,1,Captain\nb@uni.edu,alpha,Alpha,2,member\n")
        out = self.imp(rows)
        self.assertEqual((out["created"], out["rejected"]), (2, []))
        self.assertEqual(self.entries()["a@uni.edu"]["role_label"], "captain")


class Authority(Base):
    def test_who_may_import(self):
        self.tournament()
        T.create(self.treg, ORG, "t1o", "Mine", "d", REG_D, SUB_D, idempotency_key="ko", now=self.clock)
        self.imp(who=ADMIN)
        self.imp(who=ORG_ASSIGNED)
        for who, exc in ((PART, G.Forbidden), (None, G.Forbidden), (ORG_OTHER, G.NotFound)):
            with self.subTest(who=who), self.assertRaises(exc):
                self.imp(who=who)
        G.import_roster(self.reg, ORG, "t1o", [row("a@uni.edu")], now=self.clock)       # the creating Organizer

    def test_unknown_or_unsafe_tournament_ids(self):
        with self.assertRaises(G.NotFound):
            self.imp(tid="nope")
        with self.assertRaises(G.Invalid):
            self.imp(tid="../x")

    def test_import_needs_an_editable_tournament_and_an_open_registration_window(self):
        self.tournament(open_=False)
        self.imp()                                                    # approved, registration not yet open: roster prep
        self.clock.t = REG_D
        with self.assertRaises(G.DeadlineLocked):
            self.imp()
        T.extend_deadline(self.treg, ADMIN, "t1", "registration", REG_D + 500, "more time", confirm=True, now=self.clock)
        self.imp()
        T.extend_deadline(self.treg, ADMIN, "t1", "submission", SUB_D + 500, "x", confirm=True, now=self.clock)

    def test_a_draft_roster_is_not_locked_by_a_deadline(self):
        T.create(self.treg, ADMIN, "t1", "Cup", "d", REG_D, SUB_D, idempotency_key="k", now=self.clock)
        self.clock.t = REG_D + 1
        self.imp()

    def test_a_running_or_deleted_tournament_takes_no_roster(self):
        self.tournament()
        self.clock.t = SUB_D
        T.mark_running(self.treg, "t1", "x", now=self.clock)
        with self.assertRaises(G.Conflict):
            self.imp()


class Correct(Base):
    def setUp(self):
        super().setUp()
        self.tournament()
        self.imp()

    def patch(self, email, changes, **kw):
        return G.correct_entry(self.reg, ADMIN, "t1", self.entries()[email]["id"], changes, now=self.clock, **kw)

    def test_an_unregistered_entry_can_be_corrected(self):
        self.assertEqual(self.patch("two@uni.edu", {"email": "Fixed@Uni.edu", "member_number": 5})["email"], "fixed@uni.edu")
        self.assertIn("fixed@uni.edu", self.entries())

    def test_nothing_changes_for_the_same_values(self):
        e = self.patch("two@uni.edu", {"member_number": 2})
        self.assertEqual(e["version"], 1)

    def test_expected_version(self):
        self.patch("two@uni.edu", {"member_number": 5})
        with self.assertRaises(G.Conflict):
            self.patch("two@uni.edu", {"member_number": 6}, expected_version=1)
        self.patch("two@uni.edu", {"member_number": 6}, expected_version=2)

    def test_conflicts_with_other_entries_are_refused(self):
        for changes in ({"email": "cap@uni.edu"}, {"member_number": 1}, {"role_label": "captain"},
                        {"team_key": "beta", "role_label": "captain", "member_number": 2},
                        {"team_key": "beta", "member_number": 1}, {"team_key": "beta"}):
            with self.subTest(changes=changes), self.assertRaises(G.Conflict):
                self.patch("two@uni.edu", changes)

    def test_moving_to_another_team_needs_that_teams_name(self):
        self.patch("two@uni.edu", {"team_key": "beta", "team_name": "Beta", "member_number": 2})
        self.assertEqual(self.entries()["two@uni.edu"]["team_key"], "beta")

    def test_renaming_a_team_renames_every_unregistered_member(self):
        self.patch("two@uni.edu", {"team_name": "Renamed"})
        e = self.entries()
        self.assertEqual((e["two@uni.edu"]["team_name"], e["cap@uni.edu"]["team_name"], e["bob@uni.edu"]["team_name"]),
                         ("Renamed", "Renamed", "Beta"))
        self.assertEqual(e["cap@uni.edu"]["version"], 2)

    def test_bad_changes(self):
        for changes in ({}, None, {"user_id": "x"}, {"email": "bad"}, {"member_number": 0}, {"role_label": "x"}):
            with self.subTest(changes=changes), self.assertRaises(G.Invalid):
                self.patch("two@uni.edu", changes)
        with self.assertRaises(G.NotFound):
            G.correct_entry(self.reg, ADMIN, "t1", "e-nope", {"member_number": 4}, now=self.clock)
        with self.assertRaises(G.NotFound):
            G.correct_entry(self.reg, ADMIN, "t1", None, {"member_number": 4}, now=self.clock)

    def test_authority_and_deadline(self):
        eid = self.entries()["two@uni.edu"]["id"]
        for who, exc in ((PART, G.Forbidden), (ORG_OTHER, G.NotFound)):
            with self.subTest(who=who), self.assertRaises(exc):
                G.correct_entry(self.reg, who, "t1", eid, {"member_number": 4}, now=self.clock)
        G.correct_entry(self.reg, ORG_ASSIGNED, "t1", eid, {"member_number": 4}, now=self.clock)
        self.clock.t = REG_D
        with self.assertRaises(G.DeadlineLocked):
            G.correct_entry(self.reg, ADMIN, "t1", eid, {"member_number": 5}, now=self.clock)


class Codes(Base):
    def test_one_code_per_entry_is_returned_once_and_stored_only_as_a_hash(self):
        self.tournament()
        self.imp()
        out = G.issue_codes(self.reg, ADMIN, "t1", now=self.clock)
        self.assertEqual(len(out["issued"]), 3)
        codes = [i["code"] for i in out["issued"]]
        self.assertEqual(len(set(codes)), 3)
        for c in codes:
            self.assertRegex(c, r"^[A-HJ-NP-Z2-9]{5}(-[A-HJ-NP-Z2-9]{5}){3}$")
        raw = json.dumps(self.state())
        for c in codes:
            self.assertNotIn(c, raw)
            self.assertNotIn(c.replace("-", ""), raw)
        for c in G.list_codes(self.reg, ADMIN, "t1", now=self.clock):
            self.assertNotIn("code_hash", c)
            self.assertEqual(c["status"], "issued")

    def test_issuing_again_skips_entries_that_have_a_code(self):
        self.tournament()
        self.imp()
        G.issue_codes(self.reg, ADMIN, "t1", now=self.clock)
        self.assertEqual(G.issue_codes(self.reg, ADMIN, "t1", now=self.clock), {"issued": [], "skipped": []})
        eid = self.entries()["cap@uni.edu"]["id"]
        out = G.issue_codes(self.reg, ADMIN, "t1", [eid, "e-nope"], now=self.clock)
        self.assertEqual([s["reason"] for s in out["skipped"]],
                         ["a code was already issued; an Admin replaces it", "no such roster entry"])

    def test_a_new_entry_gets_its_code_later(self):
        self.tournament()
        self.imp()
        G.issue_codes(self.reg, ADMIN, "t1", now=self.clock)
        self.imp([row("late@uni.edu", n=3)])
        out = G.issue_codes(self.reg, ADMIN, "t1", now=self.clock)
        self.assertEqual(len(out["issued"]), 1)

    def test_codes_are_not_issued_to_registered_entries(self):
        codes = self.ready()
        self.claim("cap@uni.edu", codes["cap@uni.edu"])
        out = G.issue_codes(self.reg, ADMIN, "t1", [self.entries()["cap@uni.edu"]["id"]], now=self.clock)
        self.assertEqual(out["skipped"][0]["reason"], "already registered")

    def test_authority_and_state(self):
        self.tournament(open_=False)
        self.imp()
        for who, exc in ((PART, G.Forbidden), (ORG_OTHER, G.NotFound)):
            with self.subTest(who=who), self.assertRaises(exc):
                G.issue_codes(self.reg, who, "t1", now=self.clock)
        G.issue_codes(self.reg, ORG_ASSIGNED, "t1", now=self.clock)
        for bad in ("x", [1], ["e"] * (G.MAX_ENTRIES + 1)):
            with self.assertRaises(G.Invalid):
                G.issue_codes(self.reg, ADMIN, "t1", bad, now=self.clock)
        T.create(self.treg, ADMIN, "d1", "Draft", "d", REG_D, SUB_D, idempotency_key="kd", now=self.clock)
        with self.assertRaises(G.Conflict):                     # codes are for a published tournament
            G.issue_codes(self.reg, ADMIN, "d1", now=self.clock)
        self.clock.t = REG_D
        with self.assertRaises(G.DeadlineLocked):
            G.issue_codes(self.reg, ADMIN, "t1", now=self.clock)

    def test_only_an_admin_revokes_or_replaces(self):
        codes = self.ready()
        cid = G.list_codes(self.reg, ADMIN, "t1", now=self.clock)[0]["id"]
        for who, exc in ((ORG_ASSIGNED, G.Forbidden), (PART, G.Forbidden), (ORG_OTHER, G.NotFound)):
            for fn in (G.revoke_code, G.replace_code):
                with self.subTest(who=who, fn=fn.__name__), self.assertRaises(exc):
                    fn(self.reg, who, "t1", cid, "lost", confirm=True, now=self.clock)
        for fn in (G.revoke_code, G.replace_code):
            with self.assertRaises(G.Invalid):
                fn(self.reg, ADMIN, "t1", cid, "lost", now=self.clock)               # no confirm
            with self.assertRaises(G.Invalid):
                fn(self.reg, ADMIN, "t1", cid, "  ", confirm=True, now=self.clock)  # no reason
        self.assertEqual(len(codes), 3)

    def test_a_revoked_code_does_not_register_and_says_so_only_to_the_right_pair(self):
        codes = self.ready()
        entry_id = self.entries()["cap@uni.edu"]["id"]
        cid = next(c["id"] for c in G.list_codes(self.reg, ADMIN, "t1", now=self.clock) if c["entry_id"] == entry_id)
        out = G.revoke_code(self.reg, ADMIN, "t1", cid, "compromised", confirm=True, now=self.clock)
        self.assertEqual(out["status"], "revoked")
        G.revoke_code(self.reg, ADMIN, "t1", cid, "again", confirm=True, now=self.clock)     # repeat: no change
        self.assertEqual(sum(1 for a in self.state()["audit"] if a["action"] == "code_revoke"), 1)
        with self.assertRaises(G.CodeUnavailable):
            self.claim("cap@uni.edu", codes["cap@uni.edu"])
        with self.assertRaises(G.Mismatch):
            self.claim("cap@uni.edu", "AAAAA-AAAAA-AAAAA-AAAAA")

    def test_replacement_issues_a_new_code_and_the_old_one_stays_dead(self):
        codes = self.ready()
        entry_id = self.entries()["cap@uni.edu"]["id"]
        cid = next(c["id"] for c in G.list_codes(self.reg, ADMIN, "t1", now=self.clock) if c["entry_id"] == entry_id)
        new = G.replace_code(self.reg, ADMIN, "t1", cid, "lost the mail", confirm=True, now=self.clock)
        self.assertEqual(new["replaces"], cid)
        self.assertNotEqual(new["code"], codes["cap@uni.edu"])
        with self.assertRaises(G.CodeUnavailable):
            self.claim("cap@uni.edu", codes["cap@uni.edu"])
        self.assertEqual(self.claim("cap@uni.edu", new["code"])["registration_status"], "pending_verification")
        listed = {c["id"]: c for c in G.list_codes(self.reg, ADMIN, "t1", now=self.clock)}
        self.assertEqual((listed[cid]["status"], listed[cid]["replaced_by"], listed[new["code_id"]]["status"]),
                         ("revoked", new["code_id"], "consumed"))

    def test_replacing_twice_or_after_registration_is_refused_and_a_revoked_code_can_be_replaced(self):
        codes = self.ready()
        entry_id = self.entries()["two@uni.edu"]["id"]
        cid = next(c["id"] for c in G.list_codes(self.reg, ADMIN, "t1", now=self.clock) if c["entry_id"] == entry_id)
        G.revoke_code(self.reg, ADMIN, "t1", cid, "x", confirm=True, now=self.clock)
        G.replace_code(self.reg, ADMIN, "t1", cid, "x", confirm=True, now=self.clock)
        with self.assertRaises(G.Conflict):
            G.replace_code(self.reg, ADMIN, "t1", cid, "x", confirm=True, now=self.clock)
        self.claim("cap@uni.edu", codes["cap@uni.edu"])
        ccid = next(c["id"] for c in G.list_codes(self.reg, ADMIN, "t1", now=self.clock)
                    if c["entry_id"] == self.entries()["cap@uni.edu"]["id"])
        with self.assertRaises(G.Conflict):
            G.replace_code(self.reg, ADMIN, "t1", ccid, "x", confirm=True, now=self.clock)
        with self.assertRaises(G.Conflict):
            G.revoke_code(self.reg, ADMIN, "t1", ccid, "x", confirm=True, now=self.clock)
        with self.assertRaises(G.NotFound):
            G.revoke_code(self.reg, ADMIN, "t1", "c-nope", "x", confirm=True, now=self.clock)

    def test_unused_codes_expire_with_registration_and_an_extension_revives_them(self):
        codes = self.ready()
        self.clock.t = REG_D
        self.assertEqual({c["status"] for c in G.list_codes(self.reg, ADMIN, "t1", now=self.clock)}, {"expired"})
        with self.assertRaises(G.Closed):
            self.claim("cap@uni.edu", codes["cap@uni.edu"])
        self.clock.t = REG_D - 1
        T.extend_deadline(self.treg, ADMIN, "t1", "registration", REG_D + 300, "x", confirm=True, now=self.clock)
        self.clock.t = REG_D + 10
        self.assertEqual({c["status"] for c in G.list_codes(self.reg, ADMIN, "t1", now=self.clock)}, {"issued"})
        self.assertEqual(self.claim("cap@uni.edu", codes["cap@uni.edu"])["registration_status"], "pending_verification")


class Claim(Base):
    def test_the_right_pair_registers_consumes_the_code_and_locks_the_entry(self):
        codes = self.ready()
        out = self.claim("  CAP@uni.edu ", codes["cap@uni.edu"].lower().replace("-", " "))
        self.assertEqual((out["team_id"], out["member_number"], out["is_captain"], out["registration_status"], out["tournament_id"]),
                         ("alpha", 1, True, "pending_verification", "t1"))
        e = self.entries()["cap@uni.edu"]
        self.assertEqual(e["status"], "pending_verification")
        self.assertIsNotNone(e["locked_at"])
        with self.assertRaises(G.Locked):
            G.correct_entry(self.reg, ADMIN, "t1", e["id"], {"member_number": 7}, now=self.clock)
        listed = [c for c in G.list_codes(self.reg, ADMIN, "t1", now=self.clock) if c["entry_id"] == e["id"]]
        self.assertEqual(listed[0]["status"], "consumed")

    def test_a_locked_entry_is_unchanged_by_import_unless_the_data_is_identical(self):
        codes = self.ready()
        self.claim("two@uni.edu", codes["two@uni.edu"])
        out = self.imp([row("two@uni.edu", n=2), row("two@uni.edu", n=9)])
        self.assertEqual((out["unchanged"], len(out["rejected"])), (1, 1))
        self.assertIn("locked", out["rejected"][0]["reason"])
        self.assertEqual(self.entries()["two@uni.edu"]["member_number"], 2)

    def test_the_team_name_is_locked_once_a_member_registered(self):
        codes = self.ready()
        self.claim("two@uni.edu", codes["two@uni.edu"])
        with self.assertRaises(G.Locked):
            G.correct_entry(self.reg, ADMIN, "t1", self.entries()["cap@uni.edu"]["id"], {"team_name": "New"}, now=self.clock)

    def test_wrong_attempts_consume_nothing_and_all_look_alike(self):
        codes = self.ready()
        wrong = ["AAAAA-AAAAA-AAAAA-AAAAA", "short", "", None, 5, "!" * 20, codes["bob@uni.edu"], codes["cap@uni.edu"][:-1]]
        for c in wrong:
            with self.subTest(code=c), self.assertRaises(G.Mismatch) as cm:
                self.claim("cap@uni.edu", c)
            self.assertEqual(str(cm.exception), "the email and the invitation code do not match the roster")
        with self.assertRaises(G.Mismatch) as cm:
            self.claim("nobody@uni.edu", codes["cap@uni.edu"])
        self.assertEqual(str(cm.exception), "the email and the invitation code do not match the roster")
        self.assertEqual({c["status"] for c in G.list_codes(self.reg, ADMIN, "t1", now=self.clock)}, {"issued"})
        self.assertEqual(self.claim("cap@uni.edu", codes["cap@uni.edu"])["registration_status"], "pending_verification")

    def test_a_malformed_email_or_user_is_invalid_and_is_not_counted(self):
        codes = self.ready()
        for _ in range(30):
            with self.assertRaises(G.Invalid):
                self.claim("not an email", codes["cap@uni.edu"])
            with self.assertRaises(G.Invalid):
                self.claim("cap@uni.edu", codes["cap@uni.edu"], user="bad user!")
        self.assertEqual(self.state()["attempts"], [])

    def test_the_same_account_may_repeat_a_successful_claim(self):
        codes = self.ready()
        first = self.claim("cap@uni.edu", codes["cap@uni.edu"])
        self.assertEqual(self.claim("cap@uni.edu", codes["cap@uni.edu"]), first)
        self.assertEqual(sum(1 for a in self.state()["audit"] if a["action"] == "register_claim"), 1)

    def test_another_account_with_a_used_code_is_told_it_was_used(self):
        codes = self.ready()
        self.claim("cap@uni.edu", codes["cap@uni.edu"])
        with self.assertRaises(G.AlreadyRegistered):
            self.claim("cap@uni.edu", codes["cap@uni.edu"], user="u2")

    def test_one_account_cannot_take_two_places_in_a_tournament(self):
        codes = self.ready()
        self.claim("cap@uni.edu", codes["cap@uni.edu"])
        with self.assertRaises(G.AlreadyRegistered):
            self.claim("two@uni.edu", codes["two@uni.edu"])
        self.assertEqual(self.entries()["two@uni.edu"]["status"], "unregistered")
        self.assertEqual({c["status"] for c in G.list_codes(self.reg, ADMIN, "t1", now=self.clock)
                          if c["entry_id"] == self.entries()["two@uni.edu"]["id"]}, {"issued"})

    def test_the_whole_hash_is_compared_not_a_prefix(self):
        # two different codes whose SHA-256 starts with the same 32 bits: the second must not open the first's entry
        seen, a, b = {}, None, None
        for i in range(500_000):
            key = "".join(G.CODE_ALPHABET[(i * 2654435761 >> (5 * j)) & 31] for j in range(G.CODE_LENGTH))
            h = G._hash(key)[:8]
            if h in seen and seen[h] != key:
                a, b = seen[h], key
                break
            seen[h] = key
        self.assertIsNotNone(a, "no 32-bit collision found; widen the search")
        self.tournament()
        self.imp()
        eid = self.entries()["cap@uni.edu"]["id"]
        with self.reg.store.transaction() as st:
            c = G._issue(st["tournaments"]["t1"], st["tournaments"]["t1"]["entries"][eid], "adm", NOW)[0]
            c["code_hash"] = G._hash(a)
        with self.assertRaises(G.Mismatch):
            self.claim("cap@uni.edu", b)
        self.assertEqual(self.claim("cap@uni.edu", a)["registration_status"], "pending_verification")

    def test_a_code_of_one_participant_does_not_open_anothers_entry(self):
        codes = self.ready()
        with self.assertRaises(G.Mismatch):
            self.claim("two@uni.edu", codes["cap@uni.edu"])

    def test_registration_must_be_open(self):
        self.tournament(open_=False)
        self.imp()
        with self.assertRaises(G.Closed):
            self.claim("cap@uni.edu", "AAAAA-AAAAA-AAAAA-AAAAA")
        with self.assertRaises(G.Closed):
            self.claim("cap@uni.edu", "AAAAA-AAAAA-AAAAA-AAAAA", tid="nope")
        with self.assertRaises(G.Invalid):
            self.claim("cap@uni.edu", "x", tid="../x")

    def test_the_deadline_closes_it_at_the_exact_second(self):
        codes = self.ready()
        self.clock.t = REG_D - 0.001
        self.claim("cap@uni.edu", codes["cap@uni.edu"])
        self.clock.t = REG_D
        with self.assertRaises(G.Closed):
            self.claim("two@uni.edu", codes["two@uni.edu"], user="u2")

    def test_two_accounts_racing_for_one_code_one_wins(self):
        codes = self.ready()
        results = []
        barrier = threading.Barrier(2)

        def go(user):
            barrier.wait()
            try:
                results.append(self.claim("cap@uni.edu", codes["cap@uni.edu"], user=user))
            except G.AlreadyRegistered:
                results.append("lost")

        ts = [threading.Thread(target=go, args=(u,)) for u in ("u1", "u2")]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(sorted(r if isinstance(r, str) else "won" for r in results), ["lost", "won"])


class Limiter(Base):
    def test_failures_for_one_email_pause_that_email_and_then_expire(self):
        codes = self.ready()
        for _ in range(G.MAX_FAILS_PER_EMAIL):
            with self.assertRaises(G.Mismatch):
                self.claim("cap@uni.edu", "AAAAA-AAAAA-AAAAA-AAAAA")
        with self.assertRaises(G.RateLimited) as cm:
            self.claim("cap@uni.edu", codes["cap@uni.edu"])
        self.assertEqual(int(cm.exception.retry_after), int(G.ATTEMPT_WINDOW))
        self.clock.t += G.ATTEMPT_WINDOW - 1
        with self.assertRaises(G.RateLimited):
            self.claim("cap@uni.edu", codes["cap@uni.edu"])
        self.clock.t += 2
        self.assertEqual(self.claim("cap@uni.edu", codes["cap@uni.edu"])["registration_status"], "pending_verification")

    def test_the_pause_of_one_email_does_not_stop_the_others(self):
        codes = self.ready()
        for _ in range(G.MAX_FAILS_PER_EMAIL):
            with self.assertRaises(G.Mismatch):
                self.claim("cap@uni.edu", "AAAAA-AAAAA-AAAAA-AAAAA")
        self.claim("bob@uni.edu", codes["bob@uni.edu"], user="u2")

    def test_one_source_is_paused_across_emails(self):
        codes = self.ready()
        for i in range(G.MAX_FAILS_PER_SOURCE):
            with self.assertRaises(G.Mismatch):
                self.claim(f"x{i}@uni.edu", "AAAAA-AAAAA-AAAAA-AAAAA", source="1.2.3.4")
        with self.assertRaises(G.RateLimited):
            self.claim("cap@uni.edu", codes["cap@uni.edu"], source="1.2.3.4")
        self.claim("cap@uni.edu", codes["cap@uni.edu"], source="5.6.7.8")

    def test_attempt_records_hold_hashes_not_emails_and_are_pruned(self):
        self.ready()
        with self.assertRaises(G.Mismatch):
            self.claim("cap@uni.edu", "AAAAA-AAAAA-AAAAA-AAAAA")
        self.assertNotIn("cap@uni", json.dumps(self.state()["attempts"]))
        self.clock.t += G.ATTEMPT_WINDOW + 1
        with self.assertRaises(G.Mismatch):
            self.claim("bob@uni.edu", "AAAAA-AAAAA-AAAAA-AAAAA")
        self.assertEqual(len(self.state()["attempts"]), 1)

    def test_a_full_attempt_list_fails_closed_for_one_window_only(self):
        codes = self.ready()
        old = G.MAX_ATTEMPT_RECORDS
        G.MAX_ATTEMPT_RECORDS = 3
        self.addCleanup(setattr, G, "MAX_ATTEMPT_RECORDS", old)
        for i in range(3):
            with self.assertRaises(G.Mismatch):
                self.claim(f"x{i}@uni.edu", "AAAAA-AAAAA-AAAAA-AAAAA", source=f"s{i}")
        with self.assertRaises(G.RateLimited):
            self.claim("cap@uni.edu", codes["cap@uni.edu"])
        self.clock.t += G.ATTEMPT_WINDOW + 1
        self.claim("cap@uni.edu", codes["cap@uni.edu"])

    def test_a_right_pair_is_never_counted(self):
        codes = self.ready()
        self.claim("cap@uni.edu", codes["cap@uni.edu"])
        self.assertEqual(self.state()["attempts"], [])


class Verification(Base):
    def test_only_a_verified_member_is_registered_and_gets_access(self):
        codes = self.ready()
        self.claim("cap@uni.edu", codes["cap@uni.edu"])
        a = G.actor_for(self.reg, "u1")
        self.assertEqual((a.team_ids, a.captain_of, a.tournament_ids, a.role), (frozenset(), frozenset(), frozenset(), "participant"))
        self.assertEqual(G.registered_teams(self.reg, "t1"), [])
        out = G.confirm_email(self.reg, "t1", "u1", now=self.clock)
        self.assertEqual(out["registration_status"], "registered")
        a = G.actor_for(self.reg, "u1")
        self.assertEqual((a.team_ids, a.captain_of, a.tournament_ids), (frozenset({"alpha"}), frozenset({"alpha"}), frozenset({"t1"})))
        self.assertEqual(G.registered_teams(self.reg, "t1"), ["alpha"])

    def test_a_member_who_is_not_captain_cannot_upload_but_the_captain_can(self):
        codes = self.ready()
        self.claim("cap@uni.edu", codes["cap@uni.edu"], user="u1")
        self.claim("two@uni.edu", codes["two@uni.edu"], user="u2")
        G.confirm_email(self.reg, "t1", "u1", now=self.clock)
        G.confirm_email(self.reg, "t1", "u2", now=self.clock)
        subs = R.Registry(self.dir / "subs", self.dir / "subs.json")
        self.addCleanup(lambda: [__import__("os").chmod(p, 0o700) for p in (self.dir / "subs").glob("*")])
        good = b"def turn():\n    pass\n"
        v = R.submit(subs, G.actor_for(self.reg, "u1"), "alpha", "t1", "bot.py", good, idempotency_key="a",
                     deadline_at=SUB_D, now=self.clock)
        self.assertEqual(v["validation_status"], "validating")
        with self.assertRaises(Exception) as cm:
            R.submit(subs, G.actor_for(self.reg, "u2"), "alpha", "t1", "bot.py", good, idempotency_key="b",
                     deadline_at=SUB_D, now=self.clock)
        self.assertIsInstance(cm.exception, R.Forbidden)

    def test_verification_after_the_deadline_is_refused_and_the_member_is_excluded(self):
        codes = self.ready()
        self.claim("cap@uni.edu", codes["cap@uni.edu"])
        self.clock.t = REG_D
        with self.assertRaises(G.Closed):
            G.confirm_email(self.reg, "t1", "u1", now=self.clock)
        rep = G.report(self.reg, ADMIN, "t1", now=self.clock)
        self.assertEqual(rep["counts"], {"unregistered": 2, "pending_verification": 1, "registered": 0})
        self.assertEqual(len(rep["excluded"]), 3)
        self.assertEqual(G.registered_teams(self.reg, "t1"), [])
        T.extend_deadline(self.treg, ADMIN, "t1", "registration", REG_D + 100, "x", confirm=True, now=self.clock)
        self.assertEqual(G.confirm_email(self.reg, "t1", "u1", now=self.clock)["registration_status"], "registered")

    def test_confirming_twice_is_safe_and_an_unknown_account_is_not_found(self):
        codes = self.ready()
        self.claim("cap@uni.edu", codes["cap@uni.edu"])
        a = G.confirm_email(self.reg, "t1", "u1", now=self.clock)
        self.clock.t = REG_D + 5
        self.assertEqual(G.confirm_email(self.reg, "t1", "u1", now=self.clock), a)       # already registered stays so
        with self.assertRaises(G.NotFound):
            G.confirm_email(self.reg, "t1", "u9", now=self.clock)
        with self.assertRaises(G.NotFound):
            G.confirm_email(self.reg, "nope", "u1", now=self.clock)

    def test_memberships_and_actor_for_an_unknown_account(self):
        self.ready()
        self.assertEqual(G.memberships(self.reg, "ghost"), [])
        a = G.actor_for(self.reg, "ghost")
        self.assertEqual((a.team_ids, a.tournament_ids), (frozenset(), frozenset()))
        with self.assertRaises(G.Invalid):
            G.actor_for(self.reg, "bad id")


class Views(Base):
    def registered(self):
        codes = self.ready()
        for email, user in (("cap@uni.edu", "u1"), ("two@uni.edu", "u2")):
            self.claim(email, codes[email], user=user)
            G.confirm_email(self.reg, "t1", user, now=self.clock)

    def test_a_team_member_sees_the_team_without_emails_or_unregistered_members(self):
        self.registered()
        v = G.team_view(self.reg, G.actor_for(self.reg, "u2"), "t1", "alpha")
        self.assertEqual(v["name"], "Alpha")
        self.assertEqual([(m["member_number"], m["is_captain"]) for m in v["members"]], [(1, True), (2, False)])
        self.assertNotIn("uni.edu", json.dumps(v))

    def test_everybody_else_is_told_there_is_no_such_team(self):
        self.registered()
        other = R.Actor("x", "participant", frozenset({"beta"}), frozenset(), frozenset({"t1"}))
        for who in (other, PART, ORG_OTHER, None, G.actor_for(self.reg, "ghost")):
            with self.subTest(who=who), self.assertRaises(G.NotFound):
                G.team_view(self.reg, who, "t1", "alpha")
        for who, tid, team in ((ADMIN, "t1", "nope"), (ADMIN, "t1", None)):
            with self.assertRaises(G.NotFound):
                G.team_view(self.reg, who, tid, team)
        self.assertEqual(G.team_view(self.reg, ORG_ASSIGNED, "t1", "alpha")["id"], "alpha")
        self.assertEqual(G.team_view(self.reg, ADMIN, "t1", "alpha")["id"], "alpha")

    def test_roster_and_codes_are_staff_only(self):
        self.registered()
        for fn in (G.list_roster, G.list_codes, G.report):
            for who, exc in ((PART, G.Forbidden), (G.actor_for(self.reg, "u1"), G.Forbidden), (ORG_OTHER, G.NotFound), (None, G.Forbidden)):
                with self.subTest(fn=fn.__name__, who=who), self.assertRaises(exc):
                    fn(self.reg, who, "t1")
            fn(self.reg, ORG_ASSIGNED, "t1")

    def test_the_report_names_teams_that_cannot_upload(self):
        self.tournament()
        self.imp([row("a@uni.edu", "nocap", "No Captain", 1), row("b@uni.edu", "cap", "Cap", 1, "captain")])
        rep = G.report(self.reg, ADMIN, "t1", now=self.clock)
        self.assertEqual((rep["teams_without_captain_on_roster"], rep["teams_without_registered_captain"], rep["closed"],
                          rep["excluded"]), (["nocap"], ["cap"], False, []))

    def test_registered_teams_are_sorted_and_per_tournament(self):
        self.registered()
        self.assertEqual(G.registered_teams(self.reg, "t1"), ["alpha"])
        self.assertEqual(G.registered_teams(self.reg, "nope"), [])


class Purge(Base):
    def test_purge_refuses_unless_confirmed_admin_and_deleted(self):
        codes = self.ready()
        self.claim("cap@uni.edu", codes["cap@uni.edu"])
        with self.assertRaises(G.Conflict):
            G.purge_tournament(self.reg, ADMIN, "t1", confirm=True, now=self.clock)
        with self.assertRaises(G.Invalid):
            G.purge_tournament(self.reg, ADMIN, "t1", now=self.clock)
        with self.assertRaises(G.Forbidden):
            G.purge_tournament(self.reg, ORG_ASSIGNED, "t1", confirm=True, now=self.clock)
        self.assertEqual(len(self.entries()), 3)

    def test_purge_after_delete(self):
        codes = self.ready()
        self.claim("cap@uni.edu", codes["cap@uni.edu"])
        self._delete("t1")
        out = G.purge_tournament(self.reg, ADMIN, "t1", confirm=True, now=self.clock)
        self.assertEqual(out, {"entries": 3, "codes": 3})
        raw = json.dumps(self.state())
        self.assertNotIn("uni.edu", raw)
        self.assertIn("purge", raw)
        self.assertEqual(G.purge_tournament(self.reg, ADMIN, "t1", confirm=True, now=self.clock), {"entries": 0, "codes": 0})
        with self.assertRaises(G.NotFound):
            G.list_roster(self.reg, ORG_ASSIGNED, "t1")

    def _delete(self, tid):
        # a tournament that never ran can be deleted straight from the approved/open states only through the
        # state machine's own path; set the record the way `delete` leaves it
        with self.treg.store.transaction() as s:
            s["tournaments"][tid]["status"] = T.DELETED


class Damage(Base):
    def test_a_damaged_store_is_never_treated_as_empty(self):
        self.tournament()
        self.imp()
        (self.dir / "registration.json").write_text("{not json")
        with self.assertRaises(StoreError):
            G.list_roster(self.reg, ADMIN, "t1")
        (self.dir / "registration.json").write_text(json.dumps({"schema": 99}))
        with self.assertRaises(StoreError):
            self.imp()


if __name__ == "__main__":
    unittest.main()
