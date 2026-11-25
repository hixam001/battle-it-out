# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for dashboard notifications and optional email (BIO-EPIC-06, SRD-060/061, NFR-07; CN-022).

All unit tests: a fake clock, JSON files in a temporary folder, a real tournament record and roster, and a
fake email provider.

    python3 -m unittest backend.notifications.tests.test_notifications -v
"""
import json
import tempfile
import threading
import unittest
from pathlib import Path

from backend.match_orchestrator.store import StoreError
from backend.notifications import notifications as N
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


def user(uid, role="participant"):
    return R.Actor(uid, role)


ADMIN, ORG = user("adm", "admin"), user("org1", "organizer")
U1, U2, U3 = user("u1"), user("u2"), user("u3")
PARAMS = {"headline": "Welcome", "message": "The cup starts soon."}


class Provider:
    """A fake email provider: records messages, can fail in chosen ways."""

    def __init__(self):
        self.sent, self.calls, self.fail = [], 0, None
        self.lock = threading.Lock()

    def __call__(self, msg):
        with self.lock:
            self.calls += 1
            if self.fail is not None:
                raise self.fail
            self.sent.append(msg)
            return f"mid-{len(self.sent)}"


ADDR = {"u1": "one@uni.edu", "u2": "two@uni.edu", "u3": "three@uni.edu"}


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.clock = Clock()
        self.c = N.Notifications.at(self.dir / "notifications.json")
        self.provider = Provider()

    def notify(self, users=("u1", "u2"), event="announcement", params=PARAMS, key="k1", tid="t1"):
        return N.notify(self.c, event, tid, users, params, event_key=key, now=self.clock)

    def feed(self, who=U1, **kw):
        return N.list_notifications(self.c, who, **kw)

    def deliver(self, **kw):
        kw.setdefault("now", self.clock)
        return N.deliver_emails(self.c, self.provider, ADDR.get, **kw)

    def state(self):
        return self.c.store.snapshot()


class CreatingTests(Base):
    def test_dashboard_copy_per_recipient(self):
        r = self.notify()
        self.assertEqual(r, {"created": 2, "existing": 0, "email_queued": 2})
        for who in (U1, U2):
            f = self.feed(who)
            self.assertEqual((f["total"], f["unread"]), (1, 1))
            n = f["items"][0]
            self.assertEqual((n["title"], n["body"], n["read"], n["tournament_id"]),
                             ("Welcome", "The cup starts soon.", False, "t1"))
        self.assertEqual(self.feed(U3)["total"], 0)

    def test_same_event_key_creates_nothing_twice(self):
        self.notify()
        r = self.notify()
        self.assertEqual(r, {"created": 0, "existing": 2, "email_queued": 0})
        self.assertEqual(self.feed()["total"], 1)
        self.assertEqual(len(self.state()["deliveries"]), 2)

    def test_repeat_does_not_reset_read_state(self):
        self.notify()
        nid = self.feed()["items"][0]["id"]
        N.mark_read(self.c, U1, nid, now=self.clock)
        self.notify()
        self.assertTrue(self.feed()["items"][0]["read"])

    def test_new_recipient_on_same_key_is_added(self):
        self.notify(users=("u1",))
        r = self.notify(users=("u1", "u2"))
        self.assertEqual((r["created"], r["existing"]), (1, 1))

    def test_duplicate_recipients_in_one_call_count_once(self):
        self.assertEqual(self.notify(users=["u1", "u1", "u1"]), {"created": 1, "existing": 0, "email_queued": 1})

    def test_different_keys_make_different_notifications(self):
        self.notify(key="a")
        self.notify(key="b")
        self.assertEqual(self.feed()["total"], 2)

    def test_empty_recipient_list_is_fine(self):
        self.assertEqual(self.notify(users=[]), {"created": 0, "existing": 0, "email_queued": 0})

    def test_bad_inputs_create_nothing(self):
        bad = [dict(users="u1"), dict(users=[""]), dict(users=["a b"]), dict(users=[5]), dict(key=""),
               dict(key="a b"), dict(key=None), dict(tid="../x"), dict(tid=""), dict(event="nope"),
               dict(event=None), dict(params=[]), dict(params={}), dict(params={**PARAMS, "extra": "x"}),
               dict(params={"headline": "", "message": "m"}), dict(params={"headline": "a\nb", "message": "m"}),
               dict(params={"headline": "x" * 121, "message": "m"}), dict(params={"headline": 5, "message": "m"})]
        for kw in bad:
            with self.subTest(kw=kw), self.assertRaises(N.Invalid):
                self.notify(**kw)
        self.assertEqual(self.state()["notifications"], {})

    def test_too_many_recipients(self):
        with self.assertRaises(N.Invalid):
            self.notify(users=[f"u{i}" for i in range(N.MAX_RECIPIENTS + 1)])

    def test_store_full_is_refused_not_dropped(self):
        old = N.MAX_NOTIFICATIONS
        N.MAX_NOTIFICATIONS = 1
        self.addCleanup(setattr, N, "MAX_NOTIFICATIONS", old)
        self.notify(users=["u1"])
        with self.assertRaises(N.Conflict):
            self.notify(users=["u2"], key="k2")
        self.assertEqual(self.feed(U2)["total"], 0)

    def test_audit_has_ids_and_counts_only(self):
        self.notify()
        a = self.state()["audit"]
        self.assertEqual([x["action"] for x in a], ["notify"])
        self.assertEqual((a[0]["created"], a[0]["event_type"]), (2, "announcement"))
        self.assertNotIn("The cup", json.dumps(a))


class TemplateTests(Base):
    CASES = {
        "announcement": PARAMS,
        "deadline_extended": {"deadline_type": "submission", "old": NOW, "new": NOW + 3600, "reason": "server outage"},
        "emergency_override": {"setting": "name", "old": "A", "new": "B", "reason": "typo", "at": "2026-01-01T00:00:00Z",
                               "authorizer": "adm"},
        "validation_accepted": {"team": "alpha", "version": 3},
        "validation_rejected": {"team": "alpha", "reason": "imports os"},
        "registration_excluded": {},
        "team_excluded": {"team": "alpha"},
        "match_result": {"team": "alpha", "opponent": "beta", "result": "won", "round": 2, "match_id": "m1"},
        "qualified": {"team": "alpha", "round": 2},
        "eliminated": {"team": "alpha", "round": 3},
    }

    def test_every_event_type_renders(self):
        self.assertEqual(set(self.CASES), set(N.EVENTS))
        for ev, params in self.CASES.items():
            with self.subTest(ev=ev):
                title, body = N.render(ev, "t1", params)
                self.assertTrue(title and body)
                self.assertLessEqual(len(title), 160)
                self.assertNotIn("\n", title)

    def test_every_required_parameter_is_required_and_extra_refused(self):
        for ev, params in self.CASES.items():
            for k in params:
                with self.subTest(ev=ev, missing=k), self.assertRaises(N.Invalid):
                    N.render(ev, "t1", {p: v for p, v in params.items() if p != k})
            with self.subTest(ev=ev, extra=True), self.assertRaises(N.Invalid):
                N.render(ev, "t1", {**params, "zzz": "x"})

    def test_deadline_text_shows_old_and_new_time(self):
        _, body = N.render("deadline_extended", "t1", self.CASES["deadline_extended"])
        self.assertIn("1970-01-12 13:46 UTC", body)
        self.assertIn("1970-01-12 14:46 UTC", body)

    def test_value_kinds_are_checked(self):
        bad = [("deadline_extended", {**self.CASES["deadline_extended"], "deadline_type": "other"}),
               ("deadline_extended", {**self.CASES["deadline_extended"], "new": "tomorrow"}),
               ("deadline_extended", {**self.CASES["deadline_extended"], "new": True}),
               ("deadline_extended", {**self.CASES["deadline_extended"], "new": -1}),
               ("match_result", {**self.CASES["match_result"], "result": "drew"}),
               ("match_result", {**self.CASES["match_result"], "round": -1}),
               ("match_result", {**self.CASES["match_result"], "round": True}),
               ("match_result", {**self.CASES["match_result"], "round": 1.5}),
               ("qualified", {"team": "a", "round": 10 ** 9})]
        for ev, p in bad:
            with self.subTest(ev=ev, p=p), self.assertRaises(N.Invalid):
                N.render(ev, "t1", p)

    def test_text_is_not_a_format_string(self):
        t, b = N.render("announcement", "t1", {"headline": "{0} {x}", "message": "%s {__class__}"})
        self.assertEqual((t, b), ("{0} {x}", "%s {__class__}"))

    def test_long_title_is_cut_without_control_characters(self):
        t, _ = N.render("validation_rejected", "t1", {"team": "x" * 80, "reason": "r"})
        self.assertLessEqual(len(t), 160)


class NoticeTests(Base):
    def setUp(self):
        super().setUp()
        self.treg = T.Tournaments.at(self.dir / "tournaments.json")
        self.reg = G.Registration.at(self.dir / "registration.json", self.treg)
        T.create(self.treg, ADMIN, "t1", "Cup", "d", REG_D, SUB_D, idempotency_key="k", now=self.clock)
        T.approve(self.treg, ADMIN, "t1", confirm=True, now=self.clock)
        T.open_registration(self.treg, ADMIN, "t1", now=self.clock)
        rows = [{"email": "one@uni.edu", "team_key": "alpha", "team_name": "Alpha", "member_number": 1, "role": "captain"},
                {"email": "two@uni.edu", "team_key": "alpha", "team_name": "Alpha", "member_number": 2, "role": "member"},
                {"email": "three@uni.edu", "team_key": "beta", "team_name": "Beta", "member_number": 1, "role": "captain"},
                {"email": "four@uni.edu", "team_key": "beta", "team_name": "Beta", "member_number": 2, "role": "member"}]
        G.import_roster(self.reg, ADMIN, "t1", rows, now=self.clock)
        codes = {}
        for i in G.issue_codes(self.reg, ADMIN, "t1", None, now=self.clock)["issued"]:
            codes[next(e["email"] for e in G.list_roster(self.reg, ADMIN, "t1") if e["id"] == i["entry_id"])] = i["code"]
        for email, uid, verify in (("one@uni.edu", "u1", True), ("two@uni.edu", "u2", False), ("three@uni.edu", "u3", True)):
            G.claim(self.reg, "t1", email, codes[email], uid, now=self.clock)
            if verify:
                G.confirm_email(self.reg, "t1", uid, now=self.clock)

    def test_audience_is_accounts_with_a_place(self):
        self.assertEqual(G.account_ids(self.reg, "t1"), ["u1", "u2", "u3"])
        self.assertEqual(G.account_ids(self.reg, "t1", verified_only=True), ["u1", "u3"])
        self.assertEqual(G.account_ids(self.reg, "t1", "alpha"), ["u1", "u2"])
        self.assertEqual(G.account_ids(self.reg, "t1", "nobody"), [])
        self.assertEqual(G.account_ids(self.reg, "t9"), [])

    def test_official_email(self):
        self.assertEqual(G.official_email(self.reg, "u1"), "one@uni.edu")
        self.assertIsNone(G.official_email(self.reg, "ghost"))

    def test_extension_notice_reaches_the_tournament(self):
        out = T.extend_deadline(self.treg, ADMIN, "t1", "submission", SUB_D + 500, "outage", confirm=True, now=self.clock)
        r = N.notify_notice(self.c, self.reg, out["notice"], now=self.clock)
        self.assertEqual(r["created"], 3)
        n = self.feed(U2)["items"][0]
        self.assertEqual(n["event_type"], "deadline_extended")
        self.assertIn("outage", n["body"])
        self.assertEqual(self.feed(user("ghost"))["total"], 0)

    def test_same_notice_twice_is_one_notification(self):
        out = T.extend_deadline(self.treg, ADMIN, "t1", "registration", REG_D + 100, "why", confirm=True, now=self.clock)
        N.notify_notice(self.c, self.reg, out["notice"], now=self.clock)
        r = N.notify_notice(self.c, self.reg, out["notice"], now=self.clock)
        self.assertEqual((r["created"], r["existing"]), (0, 3))

    def test_two_extensions_are_two_notifications(self):
        for i in (1, 2):
            out = T.extend_deadline(self.treg, ADMIN, "t1", "submission", SUB_D + 500 * i, "again", confirm=True, now=self.clock)
            N.notify_notice(self.c, self.reg, out["notice"], now=self.clock)
        self.assertEqual(self.feed(U1)["total"], 2)

    def test_override_notice_has_setting_old_new_reason_time_authorizer(self):
        out = T.emergency_override(self.treg, ADMIN, "t1", "name", "Cup 2", "typo\nin name", confirm=True, now=self.clock)
        N.notify_notice(self.c, self.reg, out["notice"], now=self.clock)
        n = self.feed(U1)["items"][0]
        for part in ("name", "Cup", "Cup 2", "typo in name", "adm", "1970-01-12T13:46:40Z"):
            self.assertIn(part, n["body"])

    def test_override_with_long_description_still_notifies(self):
        out = T.emergency_override(self.treg, ADMIN, "t1", "description", "d" * 2000, "r" * 500, confirm=True, now=self.clock)
        self.assertEqual(N.notify_notice(self.c, self.reg, out["notice"], now=self.clock)["created"], 3)

    def test_unknown_notice_is_refused(self):
        for bad in (None, {}, {"kind": "other"}, "x"):
            with self.subTest(bad=bad), self.assertRaises(N.Invalid):
                N.from_notice(bad)

    def test_team_audience(self):
        r = N.notify_audience(self.c, self.reg, "eliminated", "t1", {"team": "Alpha", "round": 1}, event_key="e1",
                              team_id="alpha", now=self.clock)
        self.assertEqual(r["created"], 2)
        self.assertEqual(self.feed(U3)["total"], 0)

    def test_verified_only_audience(self):
        r = N.notify_audience(self.c, self.reg, "qualified", "t1", {"team": "Alpha", "round": 1}, event_key="q1",
                              verified_only=True, now=self.clock)
        self.assertEqual(r["created"], 2)
        self.assertEqual(self.feed(U2)["total"], 0)

    def test_nobody_registered_notifies_nobody(self):
        T.create(self.treg, ADMIN, "t2", "Cup2", "d", REG_D, SUB_D, idempotency_key="k2", now=self.clock)
        r = N.notify_audience(self.c, self.reg, "announcement", "t2", PARAMS, event_key="x", now=self.clock)
        self.assertEqual(r["created"], 0)


class FeedTests(Base):
    def test_newest_first_and_paging(self):
        for i in range(5):
            self.clock.t += 1
            self.notify(users=["u1"], key=f"k{i}", params={"headline": f"h{i}", "message": "m"})
        f = self.feed(limit=2)
        self.assertEqual([n["title"] for n in f["items"]], ["h4", "h3"])
        self.assertEqual((f["total"], f["unread"]), (5, 5))
        self.assertEqual([n["title"] for n in self.feed(limit=2, offset=4)["items"]], ["h0"])

    def test_unread_filter_and_counts(self):
        self.notify(users=["u1"], key="a")
        self.clock.t += 1
        self.notify(users=["u1"], key="b")
        first = self.feed()["items"][1]["id"]
        N.mark_read(self.c, U1, first, now=self.clock)
        f = self.feed(unread_only=True)
        self.assertEqual((len(f["items"]), f["total"], f["unread"]), (1, 1, 1))
        self.assertEqual(self.feed()["unread"], 1)

    def test_tournament_filter(self):
        self.notify(users=["u1"], key="a", tid="t1")
        self.notify(users=["u1"], key="b", tid="t2")
        self.assertEqual(self.feed(tournament_id="t2")["total"], 1)

    def test_mark_read_and_unread(self):
        self.notify()
        nid = self.feed()["items"][0]["id"]
        self.assertTrue(N.mark_read(self.c, U1, nid, now=self.clock)["read"])
        self.assertTrue(N.mark_read(self.c, U1, nid, now=self.clock)["read"])
        self.assertFalse(N.mark_read(self.c, U1, nid, read=False, now=self.clock)["read"])
        self.assertEqual(self.feed()["unread"], 1)

    def test_nobody_else_can_read_or_mark(self):
        self.notify(users=["u1"])
        nid = self.feed()["items"][0]["id"]
        for who in (U2, ADMIN, ORG):
            with self.subTest(who=who.user_id):
                with self.assertRaises(N.NotFound):
                    N.mark_read(self.c, who, nid, now=self.clock)
                self.assertEqual(self.feed(who)["total"], 0)
        self.assertFalse(self.feed()["items"][0]["read"])

    def test_missing_and_foreign_look_alike(self):
        self.notify(users=["u1"])
        nid = self.feed()["items"][0]["id"]
        msgs = set()
        for who, i in ((U2, nid), (U2, "n-nope"), (U1, "n-nope")):
            with self.assertRaises(N.NotFound) as cm:
                N.mark_read(self.c, who, i, now=self.clock)
            msgs.add(str(cm.exception))
        self.assertEqual(len(msgs), 1)
        for bad in (None, 5, ["x"], ""):
            with self.assertRaises(N.NotFound):
                N.mark_read(self.c, U1, bad, now=self.clock)

    def test_mark_read_value_must_be_bool(self):
        self.notify()
        nid = self.feed()["items"][0]["id"]
        for bad in ("yes", 1, None):
            with self.assertRaises(N.Invalid):
                N.mark_read(self.c, U1, nid, read=bad, now=self.clock)

    def test_mark_all_read(self):
        self.notify(users=["u1"], key="a", tid="t1")
        self.notify(users=["u1"], key="b", tid="t2")
        self.notify(users=["u2"], key="c", tid="t1")
        self.assertEqual(N.mark_all_read(self.c, U1, tournament_id="t1", now=self.clock), {"changed": 1})
        self.assertEqual(N.mark_all_read(self.c, U1, now=self.clock), {"changed": 1})
        self.assertEqual(N.mark_all_read(self.c, U1, now=self.clock), {"changed": 0})
        self.assertEqual(self.feed(U2)["unread"], 1)

    def test_no_account_no_feed(self):
        for who in (None, "u1", R.Actor("", "participant"), R.Actor("u1", "root"), R.Actor("a b", "participant")):
            with self.subTest(who=who), self.assertRaises(N.Forbidden):
                N.list_notifications(self.c, who)
            with self.assertRaises(N.Forbidden):
                N.mark_read(self.c, who, "n-x")

    def test_bad_paging(self):
        for kw in ({"limit": 0}, {"limit": 201}, {"limit": True}, {"limit": "5"}, {"offset": -1}, {"offset": 1.5},
                   {"tournament_id": "../x"}):
            with self.subTest(kw=kw), self.assertRaises(N.Invalid):
                self.feed(**kw)

    def test_feed_view_has_no_recipient_or_key(self):
        self.notify(users=["u1"])
        self.assertEqual(set(self.feed()["items"][0]),
                         {"id", "tournament_id", "event_type", "title", "body", "created_at", "read", "read_at",
                          "email_status"})


class PreferenceTests(Base):
    def test_default_is_email_on_dashboard_on(self):
        self.assertEqual(N.get_preferences(self.c, U1), {"email_enabled": True, "dashboard_enabled": True})

    def test_email_off_still_creates_dashboard_and_no_delivery(self):
        N.update_preferences(self.c, U1, {"email_enabled": False}, now=self.clock)
        r = self.notify()
        self.assertEqual((r["created"], r["email_queued"]), (2, 1))
        self.assertEqual(self.feed(U1)["items"][0]["email_status"], "disabled")
        self.assertEqual(self.feed(U1)["total"], 1)
        self.assertEqual(self.deliver()["sent"], 1)
        self.assertEqual([m["to"] for m in self.provider.sent], ["two@uni.edu"])

    def test_dashboard_cannot_be_switched_off(self):
        for body in ({"dashboard_enabled": False}, {"email_enabled": False, "dashboard_enabled": False}, {}, [],
                     {"email_enabled": "no"}, {"email_enabled": None}, {"email_enabled": 0}, None):
            with self.subTest(body=body), self.assertRaises(N.Invalid):
                N.update_preferences(self.c, U1, body, now=self.clock)
        self.assertTrue(N.get_preferences(self.c, U1)["email_enabled"])
        self.notify(users=["u1"])
        self.assertEqual(self.feed()["total"], 1)

    def test_switching_off_stops_emails_already_queued(self):
        self.notify(users=["u1"])
        N.update_preferences(self.c, U1, {"email_enabled": False}, now=self.clock)
        r = self.deliver()
        self.assertEqual((r["sent"], r["skipped"]), (0, 1))
        self.assertEqual(self.provider.calls, 0)
        self.assertEqual(self.feed()["items"][0]["email_status"], "disabled")

    def test_switching_back_on_applies_to_new_events_only(self):
        N.update_preferences(self.c, U1, {"email_enabled": False}, now=self.clock)
        self.notify(users=["u1"], key="a")
        N.update_preferences(self.c, U1, {"email_enabled": True}, now=self.clock)
        self.notify(users=["u1"], key="b")
        self.assertEqual(self.deliver()["sent"], 1)

    def test_preference_is_per_account_and_audited_once_per_change(self):
        N.update_preferences(self.c, U1, {"email_enabled": False}, now=self.clock)
        N.update_preferences(self.c, U1, {"email_enabled": False}, now=self.clock)
        self.assertTrue(N.get_preferences(self.c, U2)["email_enabled"])
        self.assertEqual([a["action"] for a in self.state()["audit"]], ["set_email_preference"])

    def test_needs_an_account(self):
        with self.assertRaises(N.Forbidden):
            N.update_preferences(self.c, None, {"email_enabled": False})
        with self.assertRaises(N.Forbidden):
            N.get_preferences(self.c, None)


class DeliveryTests(Base):
    def test_sent_once_and_recorded(self):
        self.notify(users=["u1"])
        r = self.deliver()
        self.assertEqual(r, {"sent": 1, "retry": 0, "skipped": 0, "failed": []})
        m = self.provider.sent[0]
        self.assertEqual((m["to"], m["subject"], m["text"]), ("one@uni.edu", "Welcome", "The cup starts soon."))
        nid = self.feed()["items"][0]["id"]
        self.assertEqual(m["idempotency_key"], nid)
        self.assertEqual(self.feed()["items"][0]["email_status"], "sent")
        self.assertEqual(self.deliver()["sent"], 0)
        self.assertEqual(self.provider.calls, 1)
        d = N.delivery_status(self.c, ADMIN, nid)
        self.assertEqual((d["status"], d["attempts"], d["provider_message_id"]), ("sent", 1, "mid-1"))

    def test_nothing_is_stored_with_the_address(self):
        self.notify(users=["u1"])
        self.deliver()
        self.assertNotIn("one@uni.edu", json.dumps(self.state()))

    def test_provider_failure_keeps_dashboard_and_retries_with_backoff(self):
        self.notify(users=["u1"])
        self.provider.fail = ConnectionError("down")
        r = self.deliver()
        self.assertEqual((r["sent"], r["retry"], r["failed"]), (0, 1, []))
        self.assertEqual(self.feed()["total"], 1)
        self.assertEqual(self.feed()["items"][0]["email_status"], "pending")
        self.assertEqual(self.deliver()["retry"], 0)                  # not due yet
        self.assertEqual(self.provider.calls, 1)
        self.clock.t += N.default_backoff(1)
        self.provider.fail = None
        self.assertEqual(self.deliver()["sent"], 1)
        nid = self.feed()["items"][0]["id"]
        self.assertEqual(N.delivery_status(self.c, ADMIN, nid)["attempts"], 2)

    def test_backoff_grows_and_gives_up_at_the_cap(self):
        self.notify(users=["u1"])
        self.provider.fail = TimeoutError("slow")
        for attempt in range(1, N.MAX_ATTEMPTS):
            self.assertEqual(self.deliver()["retry"], 1)
            self.clock.t += N.default_backoff(attempt)
        r = self.deliver()
        nid = self.feed()["items"][0]["id"]
        self.assertEqual((r["retry"], r["failed"]), (0, [nid]))
        self.assertEqual(self.provider.calls, N.MAX_ATTEMPTS)
        self.assertEqual(self.feed()["items"][0]["email_status"], "failed")
        self.assertEqual(self.feed()["total"], 1)
        self.clock.t += 10 ** 6
        self.assertEqual(self.deliver(), {"sent": 0, "retry": 0, "skipped": 0, "failed": []})
        self.assertEqual(self.provider.calls, N.MAX_ATTEMPTS)
        self.assertIn("email_failed", [a["action"] for a in self.state()["audit"]])

    def test_backoff_values(self):
        self.assertEqual([N.default_backoff(i) for i in (1, 2, 3, 4)], [60.0, 240.0, 960.0, 3840.0])
        self.assertEqual(N.default_backoff(50), 6 * 3600.0)

    def test_permanent_failure_is_not_retried(self):
        self.notify(users=["u1"])
        self.provider.fail = N.Permanent("mailbox does not exist")
        r = self.deliver()
        self.assertEqual(len(r["failed"]), 1)
        self.clock.t += 10 ** 6
        self.deliver()
        self.assertEqual(self.provider.calls, 1)

    def test_no_address_ends_without_calling_the_provider(self):
        self.notify(users=["ghost"])
        r = self.deliver()
        self.assertEqual(len(r["failed"]), 1)
        self.assertEqual(self.provider.calls, 0)
        self.assertEqual(self.feed(user("ghost"))["items"][0]["email_status"], "no_address")

    def test_unusable_address_ends_without_calling_the_provider(self):
        self.notify(users=["u1"])
        for bad in ("not an email", "a@b", "x\r\nBcc: evil@x.com@y.com", ""):
            self.setUp()
            self.notify(users=["u1"])
            N.deliver_emails(self.c, self.provider, lambda u, b=bad: b, now=self.clock)
            self.assertEqual(self.provider.calls, 0, bad)
            self.assertEqual(self.feed()["items"][0]["email_status"], "no_address", bad)

    def test_address_lookup_failure_is_retried(self):
        self.notify(users=["u1"])
        def boom(u):
            raise RuntimeError("account service down")
        r = N.deliver_emails(self.c, self.provider, boom, now=self.clock)
        self.assertEqual((r["retry"], self.provider.calls), (1, 0))

    def test_provider_error_text_is_stripped_of_addresses(self):
        self.notify(users=["u1"])
        self.provider.fail = RuntimeError("550 rejected one@uni.edu for policy\nsecond line")
        self.deliver()
        nid = self.feed()["items"][0]["id"]
        err = N.delivery_status(self.c, ADMIN, nid)["last_error"]
        self.assertNotIn("one@uni.edu", err)
        self.assertNotIn("\n", err)
        self.assertIn("RuntimeError", err)
        self.assertNotIn("one@uni.edu", json.dumps(self.state()))

    def test_provider_never_runs_while_the_store_is_locked(self):
        self.notify(users=["u1"])
        seen = []

        def send(msg):
            # a second writer must get the lock while a send is in flight
            done = threading.Event()
            threading.Thread(target=lambda: (self.notify(users=["u2"], key="other"), done.set())).start()
            seen.append(done.wait(5))
            return "m"
        N.deliver_emails(self.c, send, ADDR.get, now=self.clock)
        self.assertEqual(seen, [True])

    def test_crash_after_claim_resends_after_the_lease(self):
        self.notify(users=["u1"])
        class Crash(BaseException):
            pass
        def die(msg):
            raise Crash()
        with self.assertRaises(Crash):
            N.deliver_emails(self.c, die, ADDR.get, now=self.clock)
        self.assertEqual(self.deliver()["sent"], 0)                   # lease still running
        self.clock.t += N.LEASE + 1
        self.assertEqual(self.deliver()["sent"], 1)
        self.assertEqual(self.provider.sent[0]["idempotency_key"], self.feed()["items"][0]["id"])

    def test_repeated_crashes_give_up_instead_of_looping(self):
        self.notify(users=["u1"])
        class Crash(BaseException):
            pass
        def die(msg):
            raise Crash()
        for _ in range(N.MAX_ATTEMPTS):
            with self.assertRaises(Crash):
                N.deliver_emails(self.c, die, ADDR.get, now=self.clock)
            self.clock.t += N.LEASE + 1
        r = self.deliver()
        self.assertEqual((len(r["failed"]), self.provider.calls), (1, 0))

    def test_batch_limit(self):
        self.notify(users=["u1", "u2", "u3"])
        self.assertEqual(self.deliver(limit=2)["sent"], 2)
        self.assertEqual(self.deliver(limit=2)["sent"], 1)
        for bad in (0, 101, True, "5"):
            with self.assertRaises(N.Invalid):
                self.deliver(limit=bad)

    def test_two_workers_never_send_the_same_email(self):
        self.notify(users=["u1", "u2", "u3"])
        reports = []
        ts = [threading.Thread(target=lambda: reports.append(self.deliver())) for _ in range(4)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(sum(r["sent"] for r in reports), 3)
        self.assertEqual(sorted(m["to"] for m in self.provider.sent), sorted(ADDR.values()))

    def test_oldest_due_first(self):
        self.notify(users=["u1"], key="a")
        self.clock.t += 5
        self.notify(users=["u2"], key="b")
        self.deliver(limit=1)
        self.assertEqual(self.provider.sent[0]["to"], "one@uni.edu")

    def test_purged_notification_drops_its_delivery(self):
        self.notify(users=["u1"])
        s = self.state()
        nid = next(iter(s["notifications"]))
        with self.c.store.transaction() as st:
            del st["notifications"][nid]
        self.assertEqual(self.deliver()["sent"], 0)
        self.assertEqual(self.state()["deliveries"], {})

    def test_delivery_status_is_admin_only(self):
        self.notify(users=["u1"])
        nid = self.feed()["items"][0]["id"]
        for who in (U1, ORG):
            with self.assertRaises(N.Forbidden):
                N.delivery_status(self.c, who, nid)
        with self.assertRaises(N.NotFound):
            N.delivery_status(self.c, ADMIN, "n-none")
        self.assertNotIn("to", N.delivery_status(self.c, ADMIN, nid))


class PurgeTests(Base):
    def setUp(self):
        super().setUp()
        self.treg = T.Tournaments.at(self.dir / "tournaments.json")
        self.reg = G.Registration.at(self.dir / "registration.json", self.treg)
        T.create(self.treg, ADMIN, "t1", "Cup", "d", REG_D, SUB_D, idempotency_key="k", now=self.clock)

    def test_purge_after_delete_only(self):
        self.notify(tid="t1")
        self.notify(tid="t2", key="k2")
        with self.assertRaises(N.Conflict):
            N.purge_tournament(self.c, self.reg, ADMIN, "t1", confirm=True, now=self.clock)
        T.delete(self.treg, ADMIN, "t1", "done", confirm=True, now=self.clock)
        self.assertEqual(N.purge_tournament(self.c, self.reg, ADMIN, "t1", confirm=True, now=self.clock), {"notifications": 2})
        self.assertEqual(self.feed()["total"], 1)
        s = self.state()
        self.assertEqual(len(s["notifications"]), len(s["deliveries"]))
        self.assertEqual(N.purge_tournament(self.c, self.reg, ADMIN, "t1", confirm=True, now=self.clock), {"notifications": 0})
        self.assertEqual(s["audit"][-1]["action"], "purge")

    def test_purge_guards(self):
        T.delete(self.treg, ADMIN, "t1", "done", confirm=True, now=self.clock)
        with self.assertRaises(N.Forbidden):
            N.purge_tournament(self.c, self.reg, ORG, "t1", confirm=True)
        with self.assertRaises(N.Invalid):
            N.purge_tournament(self.c, self.reg, ADMIN, "t1")
        with self.assertRaises(N.NotFound):
            N.purge_tournament(self.c, self.reg, ADMIN, "t9", confirm=True)

    def test_purged_inbox_entries_vanish(self):
        self.notify(users=["u1"])
        T.delete(self.treg, ADMIN, "t1", "done", confirm=True, now=self.clock)
        N.purge_tournament(self.c, self.reg, ADMIN, "t1", confirm=True, now=self.clock)
        self.assertEqual(self.state()["inbox"], {})


class StoreTests(Base):
    def test_damaged_file_is_refused_not_emptied(self):
        self.notify()
        (self.dir / "notifications.json").write_text("{not json")
        with self.assertRaises(StoreError):
            self.feed()
        with self.assertRaises(StoreError):
            self.notify(key="k2")
        self.assertEqual((self.dir / "notifications.json").read_text(), "{not json")

    def test_unknown_layout_is_refused(self):
        (self.dir / "notifications.json").write_text(json.dumps({"schema": 1, "notifications": []}))
        with self.assertRaises(StoreError):
            self.feed()

    def test_survives_a_new_handle(self):
        self.notify()
        again = N.Notifications.at(self.dir / "notifications.json")
        self.assertEqual(N.list_notifications(again, U1)["total"], 1)

    def test_concurrent_notifies_of_one_key_create_one(self):
        ts = [threading.Thread(target=self.notify) for _ in range(6)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(self.feed()["total"], 1)
        self.assertEqual(len(self.state()["deliveries"]), 2)


if __name__ == "__main__":
    unittest.main()
