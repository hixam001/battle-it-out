# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for the notification sources: validation result, round results, draw exclusions (CN-023).

Real tournament record, roster, registry, queue, bracket and notification store; fake checks, fake games, a
fake clock and a fake email provider. The last class runs the whole way from roster to a completed tournament
with the hooks wired into the worker and the timer.

    python3 -m unittest backend.notifications.tests.test_sources -v
"""
import unittest

from backend.match_orchestrator import bracket as B
from backend.match_orchestrator.tests.test_tiebreak import DECISIVE
from backend.notifications import notifications as N
from backend.notifications import sources as S
from backend.registration import registration as G
from backend.submission_registry import registry as R
from backend.tournament_flow import flow as F
from backend.tournament_flow.tests.test_flow import BOT, DEADLINE
from backend.tournaments import tournaments as T
from backend.tournaments.tests import test_scheduler as TS
from backend.work_queue import handlers as H
from backend.work_queue import jobs as J
from backend.work_queue.tests.test_handlers import verdict
from backend.work_queue.tests.test_jobs import Clock

ADMIN = TS.ADMIN


class Sources(TS.SchedBase):
    """A tournament `t1` with a roster; every helper of the scheduler's `Registered` tests is reused."""

    register = TS.Registered.register
    upload = TS.Registered.upload

    def setUp(self):
        super().setUp()
        self.roster = G.Registration.at(self.dir / "registration.json", self.treg)
        self.users = {}
        self.center = N.Notifications.at(self.dir / "notifications.json")
        self.hooks = {"validation": 0, "round": 0}

    # -- wiring a worker the way a deployment would
    def on_decided(self, sid):
        self.hooks["validation"] += 1
        return S.validation_result(self.center, self.roster, self.flow.registry, sid, now=self.clock)

    def on_round(self, bid, rno):
        self.hooks["round"] += 1
        return S.round_results(self.center, self.roster, self.flow.store, bid, rno, now=self.clock)

    def check(self, answers=None, hook=True):
        answers = answers or {}

        def check_fn(folder):
            return verdict((folder / "bot.py").read_bytes(), answers.get(folder.name, "valid"))
        h = H.check_submission_handler(self.flow.registry, check_fn, now=self.clock,
                                       on_decided=self.on_decided if hook else None)
        return self.worker(**{J.CHECK_SUBMISSION: h}).run_until_idle()

    def play_round(self, bid="t1", hook=True):
        def run_fn(ctx):
            side = "A" if ctx.team_a < ctx.team_b else "B"
            return {"outcome": "completed", "classification": "normal", "ok": True, "winner": side, "round": 300,
                    "reason": DECISIVE, "replay": None, "structured_log": {"path": "/x/l.jsonl", "events": 5}}
        h = H.run_round_handler(self.flow.store, run_fn, alert=self.alerts.append, now=self.clock,
                                sleep=lambda s: None, on_round=self.on_round if hook else None)
        return self.worker(**{J.RUN_ROUND: h}).run_until_idle()

    def feed(self, team):
        return N.list_notifications(self.center, R.Actor(self.users[team], "participant"))["items"]

    def kinds(self, team):
        return sorted(n["event_type"] for n in self.feed(team))


class Validation(Sources):
    def test_a_valid_version_tells_the_team_it_is_active(self):
        self.register(("ta",))
        self.upload("ta")
        self.check()
        (n,) = self.feed("ta")
        self.assertEqual(n["event_type"], "validation_accepted")
        self.assertIn("Bot version 1 of ta passed the check", n["title"])
        self.assertEqual(self.hooks["validation"], 1)

    def test_a_rejected_version_tells_the_team_why_in_one_line(self):
        self.register(("ta",))
        self.upload("ta")
        self.check({"ta-v1": "rejected"})
        (n,) = self.feed("ta")
        self.assertEqual(n["event_type"], "validation_rejected")
        self.assertIn("T-CRASH: your bot crashed", n["body"])

    def test_only_the_team_hears_about_it(self):
        self.register(("ta", "tb"))
        self.upload("ta")
        self.check()
        self.assertEqual((self.kinds("ta"), self.kinds("tb")), (["validation_accepted"], []))

    def test_an_inconclusive_check_is_nobodys_news_and_the_later_verdict_is(self):
        self.register(("ta",))
        self.upload("ta")
        self.check({"ta-v1": "inconclusive"})
        self.assertEqual(self.feed("ta"), [])
        self.assertEqual(self.hooks["validation"], 0)
        self.clock.t += 100
        self.check()
        self.assertEqual(self.kinds("ta"), ["validation_accepted"])

    def test_the_hook_is_repeated_safely_when_a_retry_finds_the_verdict_stored(self):
        self.register(("ta",))
        self.upload("ta")
        self.check()
        J.enqueue_check(self.flow.queue, "ta-v1", now=self.clock)       # a second job for the same version
        self.check()
        self.assertEqual((len(self.feed("ta")), self.hooks["validation"]), (1, 2))

    def test_a_crash_between_the_verdict_and_the_notice_is_healed_by_the_retry(self):
        self.register(("ta",))
        self.upload("ta")
        self.check(hook=False)                                          # verdict stored, notice never made
        self.assertEqual(self.feed("ta"), [])
        J.enqueue_check(self.flow.queue, "ta-v1", now=self.clock)
        self.check()
        self.assertEqual(self.kinds("ta"), ["validation_accepted"])

    def test_a_failing_hook_fails_the_job_and_the_retry_notifies(self):
        self.register(("ta",))
        self.upload("ta")
        calls = []

        def broken(sid):
            calls.append(sid)
            if len(calls) == 1:
                raise RuntimeError("store down")
            return self.on_decided(sid)
        h = H.check_submission_handler(self.flow.registry, lambda f: verdict(BOT), now=self.clock, on_decided=broken)
        self.assertEqual([r["outcome"] for r in self.worker(**{J.CHECK_SUBMISSION: h}).run_until_idle()], ["queued"])
        self.assertEqual(self.feed("ta"), [])
        self.clock.t += 100
        self.assertEqual([r["outcome"] for r in self.worker(**{J.CHECK_SUBMISSION: h}).run_until_idle()], ["done"])
        self.assertEqual(self.kinds("ta"), ["validation_accepted"])

    def test_each_version_of_a_team_is_its_own_event(self):
        self.register(("ta",))
        self.upload("ta")
        self.check()
        F.upload(self.flow, G.actor_for(self.roster, self.users["ta"]), "ta", "t1", "bot.py", BOT + b"# v2\n",
                 idempotency_key="k2", deadline_at=DEADLINE, now=self.clock)
        self.check({"ta-v2": "rejected"})
        self.assertEqual(self.kinds("ta"), ["validation_accepted", "validation_rejected"])

    def test_a_valid_version_that_a_newer_one_replaced_is_not_announced_as_active(self):
        self.register(("ta",))
        first = self.upload("ta")
        second = F.upload(self.flow, G.actor_for(self.roster, self.users["ta"]), "ta", "t1", "bot.py",
                          BOT + b"# v2\n", idempotency_key="k2", deadline_at=DEADLINE, now=self.clock)
        self.check(hook=False)
        self.assertEqual((first["id"], second["id"]), ("ta-v1", "ta-v2"))
        self.assertEqual(S.validation_result(self.center, self.roster, self.flow.registry, "ta-v1", now=self.clock),
                         {"skipped": "valid_but_not_active"})
        self.assertEqual(S.validation_result(self.center, self.roster, self.flow.registry, "ta-v2",
                                             now=self.clock)["created"], 1)

    def upload_unchecked(self, team):
        R.submit(self.flow.registry, TS.captain(team), team, "t1", "bot.py", BOT, idempotency_key="k1",
                 deadline_at=DEADLINE, now=self.clock)
        claim = R.claim_check(self.flow.registry, f"{team}-v1", now=self.clock)
        R.record_verdict(self.flow.registry, claim, verdict(BOT), now=self.clock)

    def test_an_unverified_claimant_gets_nothing_and_the_call_says_so(self):
        self.register(("ta",), confirm=False)
        self.upload_unchecked("ta")
        out = S.validation_result(self.center, self.roster, self.flow.registry, "ta-v1", now=self.clock)
        self.assertEqual(out["created"], 0)

    def test_an_unknown_version_is_not_found(self):
        with self.assertRaises(N.NotFound):
            S.validation_result(self.center, self.roster, self.flow.registry, "ghost-v1", now=self.clock)

    def test_reasons_with_control_characters_and_a_missing_reason_still_make_a_notice(self):
        self.assertEqual(S.validation_reason([{"reasons": [{"code": "A\nB", "message": "x\ty\x00z"}]}]), "A B: x y z")
        self.assertEqual(S.validation_reason([{"reasons": []}]), S.NO_REASON)
        self.assertEqual(S.validation_reason([]), S.NO_REASON)
        self.assertEqual(len(S.validation_reason([{"reasons": [{"code": "C", "message": "m" * 500}] * 20}])), 500)


class Rounds(Sources):
    def drawn(self, teams=("ta", "tb", "tc", "td")):
        self.register(teams)
        for t in teams:
            self.upload(t)
        self.check()
        self.clock.t = DEADLINE
        self.tick(registration=self.roster)
        F.start_round(self.flow, "t1", 1, "org-1", now=self.clock)

    def test_every_decided_match_tells_both_teams_and_the_right_next_step(self):
        self.drawn()
        self.play_round()
        # sorted pairing: the lower id wins (fake game): ta beats tb or tc... read the real bracket
        rd = B.get_bracket(self.flow.store, "t1")["rounds"][0]
        self.assertEqual(rd["status"], "completed")
        for m in rd["matches"]:
            self.assertIn("match_result", self.kinds(m["winner"]))
            loser = m["b"] if m["winner"] == m["a"] else m["a"]
            self.assertEqual(sorted(k for k in self.kinds(loser) if k != "validation_accepted"),
                             ["eliminated", "match_result"])
            self.assertEqual(sorted(k for k in self.kinds(m["winner"]) if k != "validation_accepted"),
                             ["match_result", "qualified"])

    def test_the_wording_says_who_won_against_whom(self):
        self.drawn()
        self.play_round()
        m = B.get_bracket(self.flow.store, "t1")["rounds"][0]["matches"][0]
        loser = m["b"] if m["winner"] == m["a"] else m["a"]
        won = next(n for n in self.feed(m["winner"]) if n["event_type"] == "match_result")
        self.assertIn(f"{m['winner']} won round 1 against {loser}", won["title"])
        self.assertIn("t1-r1-m", won["body"])

    def test_repeating_the_round_hook_creates_nothing_more(self):
        self.drawn()
        self.play_round()
        before = {t: len(self.feed(t)) for t in self.users}
        again = S.round_results(self.center, self.roster, self.flow.store, "t1", 1, now=self.clock)
        self.assertEqual(again["created"], 0)
        self.assertEqual(before, {t: len(self.feed(t)) for t in self.users})

    def test_the_final_has_a_champion_and_a_runner_up_but_nobody_qualifies(self):
        self.drawn()
        self.play_round()
        F.start_round(self.flow, "t1", 2, "org-1", now=self.clock)
        self.play_round()
        b = B.get_bracket(self.flow.store, "t1")
        champ = b["champion"]
        final = b["rounds"][1]["matches"][0]
        runner = final["b"] if final["winner"] == final["a"] else final["a"]
        self.assertEqual(sorted(k for k in self.kinds(champ) if k != "validation_accepted"),
                         ["match_result", "match_result", "qualified"])          # won round 1 and the final
        self.assertEqual(sorted(k for k in self.kinds(runner) if k != "validation_accepted"),
                         ["eliminated", "match_result", "match_result", "qualified"])

    def test_a_team_with_a_bye_qualifies_and_no_result_is_made_up_for_it(self):
        self.drawn(("ta", "tb", "tc"))
        self.play_round()
        bye = next(m for m in B.get_bracket(self.flow.store, "t1")["rounds"][0]["matches"] if m["bye"])
        kinds = [k for k in self.kinds(bye["winner"]) if k != "validation_accepted"]
        self.assertEqual(kinds, ["qualified"])

    def test_a_paused_round_still_tells_the_games_that_finished(self):
        self.drawn()
        done = []

        def run_fn(ctx):
            if done:
                raise RuntimeError("platform failure")
            done.append(ctx.match_id)
            return {"outcome": "completed", "classification": "normal", "ok": True, "winner": "A", "round": 300,
                    "reason": DECISIVE, "replay": None, "structured_log": {"path": "/x/l.jsonl", "events": 5}}
        h = H.run_round_handler(self.flow.store, run_fn, alert=self.alerts.append, now=self.clock,
                                sleep=lambda s: None, on_round=self.on_round)
        outcomes = [r["outcome"] for r in self.worker(**{J.RUN_ROUND: h}).run_until_idle()]
        self.assertEqual(outcomes, ["done"])                  # a paused game is the operator's, not a failed job
        rd = B.get_bracket(self.flow.store, "t1")["rounds"][0]
        self.assertEqual([m["winner"] is not None for m in rd["matches"]], [True, False])
        first = rd["matches"][0]
        self.assertIn("match_result", self.kinds(first["a"]))
        second = rd["matches"][1]
        self.assertNotIn("match_result", self.kinds(second["a"]))

    def test_a_bad_round_is_refused(self):
        self.drawn()
        with self.assertRaises(N.Invalid):
            S.round_results(self.center, self.roster, self.flow.store, "t1", 9, now=self.clock)
        with self.assertRaises(N.Invalid):
            S.round_results(self.center, self.roster, self.flow.store, "t1", True, now=self.clock)


class Draw(Sources):
    def test_the_draw_tells_a_registered_team_without_a_bot_and_an_unfinished_registration(self):
        self.register(("ta", "tb", "tc"))
        self.upload("ta")
        self.upload("tb")
        self.register_unverified("td")
        self.check()
        self.clock.t = DEADLINE
        out = self.tick(registration=self.roster, notifications=self.center)
        self.assertEqual((out["opened"], out["blocked"], out["excluded"]), (["t1"], {}, {"t1": ["tc"]}))
        self.assertEqual(self.kinds("tc"), ["team_excluded"])
        self.assertEqual(self.kinds("td"), ["registration_excluded"])
        self.assertEqual((self.kinds("ta"), self.kinds("tb")), (["validation_accepted"], ["validation_accepted"]))

    def register_unverified(self, team):
        G.import_roster(self.roster, ADMIN, "t1", [TS._row(f"{team}@uni.edu", team, 1, "captain")], now=self.clock)
        entry = next(e for e in G.list_roster(self.roster, ADMIN, "t1") if e["email"] == f"{team}@uni.edu")
        code = G.issue_codes(self.roster, ADMIN, "t1", [entry["id"]], now=self.clock)["issued"][0]["code"]
        G.claim(self.roster, "t1", f"{team}@uni.edu", code, f"user-{team}", now=self.clock)    # not confirmed
        self.users[team] = f"user-{team}"

    def test_a_second_tick_and_a_retried_draw_do_not_notify_twice(self):
        self.register(("ta", "tb", "tc"))
        self.upload("ta")
        self.upload("tb")
        self.check()
        self.clock.t = DEADLINE
        self.tick(registration=self.roster, notifications=self.center)
        self.tick(registration=self.roster, notifications=self.center)
        self.assertEqual(len(self.feed("tc")), 1)
        S.draw_exclusions(self.center, self.roster, "t1", ["tc", "tc"], now=self.clock)
        self.assertEqual(len(self.feed("tc")), 1)

    def test_a_failing_notification_store_leaves_the_tournament_open_and_the_next_tick_finishes(self):
        self.register(("ta", "tb", "tc"))
        self.upload("ta")
        self.upload("tb")
        self.check()
        self.clock.t = DEADLINE
        real, calls = S.draw_exclusions, []

        def flaky(*a, **kw):
            calls.append(1)
            if len(calls) == 1:
                raise N.Conflict("the notification store is full")
            return real(*a, **kw)
        S.draw_exclusions = flaky
        self.addCleanup(setattr, S, "draw_exclusions", real)
        out = self.tick(registration=self.roster, notifications=self.center)
        self.assertEqual((out["opened"], list(out["blocked"]), self.status()), ([], ["t1"], "registration_open"))
        self.assertEqual(len(self.incidents()), 1)
        out = self.tick(registration=self.roster, notifications=self.center)
        self.assertEqual((out["opened"], self.status()), (["t1"], "running"))
        self.assertEqual(self.kinds("tc"), ["team_excluded"])

    def test_notifications_without_a_registration_are_refused(self):
        with self.assertRaises(ValueError):
            self.tick(notifications=self.center)

    def test_without_notifications_the_draw_is_as_before_and_still_reports_the_excluded(self):
        self.register(("ta", "tb", "tc"))
        self.upload("ta")
        self.upload("tb")
        self.check(hook=False)
        self.clock.t = DEADLINE
        out = self.tick(registration=self.roster)
        self.assertEqual((out["opened"], out["excluded"]), (["t1"], {"t1": ["tc"]}))
        self.assertEqual(self.center.store.snapshot()["notifications"], {})

    def test_a_team_with_no_exclusion_makes_no_excluded_entry(self):
        self.register(("ta", "tb"))
        self.upload("ta")
        self.upload("tb")
        self.check()
        self.clock.t = DEADLINE
        self.assertEqual(self.tick(registration=self.roster, notifications=self.center)["excluded"], {})


class ServiceWiring(unittest.TestCase):
    """The worker program: `--notify` adds the hooks, and the files are where the docs say they are."""

    def setUp(self):
        import tempfile
        from pathlib import Path
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def build(self, **kw):
        from unittest import mock
        from backend.work_queue import service as SV
        seen = {}

        def capture(name):
            real = getattr(H, name)

            def wrapper(*a, **k):
                seen[name] = k
                return real(*a, **k)
            return wrapper
        with mock.patch.object(SV.H, "check_submission_handler", capture("check_submission_handler")), \
                mock.patch.object(SV.H, "run_round_handler", capture("run_round_handler")):
            SV.build_worker(self.dir, play=lambda *a: {}, run_fn=lambda c: {}, **kw)
        return seen

    def test_the_hooks_are_off_unless_asked_for(self):
        seen = self.build()
        self.assertIsNone(seen["check_submission_handler"]["on_decided"])
        self.assertIsNone(seen["run_round_handler"]["on_round"])

    def test_with_notify_both_handlers_get_a_hook(self):
        seen = self.build(notify=True)
        self.assertTrue(callable(seen["check_submission_handler"]["on_decided"]))
        self.assertTrue(callable(seen["run_round_handler"]["on_round"]))

    def test_the_command_line_flag_reaches_build_worker(self):
        from unittest import mock
        from backend.work_queue import service as SV
        for argv, want in ((["--notify"], True), ([], False)):
            fake = mock.Mock()
            fake.return_value.run_until_idle.return_value = []
            with mock.patch.object(SV, "build_worker", fake), mock.patch("builtins.print"):
                SV.main(["--data-dir", str(self.dir), *argv, "run", "--once"])
            self.assertEqual(fake.call_args.kwargs["notify"], want)

    def test_the_hook_writes_to_notifications_json_for_the_roster_in_the_data_dir(self):
        from backend.work_queue import service as SV
        from backend.match_orchestrator.store import JsonFileStore
        clock = Clock(DEADLINE - 100_000)
        treg = T.Tournaments.at(self.dir / "tournaments.json")
        T.create(treg, TS.ORG, "t1", "Cup", "", DEADLINE - 50_000, DEADLINE, idempotency_key="k", now=clock)
        T.submit_for_approval(treg, TS.ORG, "t1", now=clock)
        T.approve(treg, ADMIN, "t1", confirm=True, now=clock)
        T.open_registration(treg, TS.ORG, "t1", now=clock)
        roster = G.Registration.at(self.dir / "registration.json", treg)
        G.import_roster(roster, ADMIN, "t1", [TS._row("ta@uni.edu", "ta", 1, "captain")], now=clock)
        code = G.issue_codes(roster, ADMIN, "t1", now=clock)["issued"][0]["code"]
        G.claim(roster, "t1", "ta@uni.edu", code, "user-ta", now=clock)
        G.confirm_email(roster, "t1", "user-ta", now=clock)
        reg = R.Registry(self.dir / "submissions", self.dir / "registry.json")
        R.submit(reg, G.actor_for(roster, "user-ta"), "ta", "t1", "bot.py", BOT, idempotency_key="k1",
                 deadline_at=DEADLINE, now=clock)
        claim = R.claim_check(reg, "ta-v1", now=clock)
        R.record_verdict(reg, claim, verdict(BOT), now=clock)
        on_decided, on_round = SV.notification_hooks(self.dir, reg, JsonFileStore(self.dir / "matches.json"))
        on_decided("ta-v1")
        feed = N.list_notifications(N.Notifications.at(self.dir / "notifications.json"),
                                    R.Actor("user-ta", "participant"))["items"]
        self.assertEqual([n["event_type"] for n in feed], ["validation_accepted"])
        with self.assertRaises(B.BracketError):
            on_round("no-such-bracket", 1)


class WholeWay(Sources):
    def test_roster_to_champion_with_every_hook_and_the_email_outbox(self):
        self.register(("ta", "tb", "tc", "td"))
        for t in ("ta", "tb", "tc", "td"):
            self.upload(t)
        self.check()
        self.clock.t = DEADLINE
        self.assertEqual(self.tick(registration=self.roster, notifications=self.center)["opened"], ["t1"])
        for rno in (1, 2):
            F.start_round(self.flow, "t1", rno, "org-1", now=self.clock)
            self.play_round()
        self.assertEqual(self.tick(registration=self.roster, notifications=self.center)["completed"], ["t1"])
        champ = B.get_bracket(self.flow.store, "t1")["champion"]
        self.assertIn("match_result", self.kinds(champ))
        self.assertEqual(sum(k == "eliminated" for t in self.users for k in self.kinds(t)), 3)
        self.assertEqual(sum(k == "qualified" for t in self.users for k in self.kinds(t)), 2)    # the final qualifies nobody
        # the outbox has one email per notification and each address comes from the roster
        sent = []
        report = N.deliver_emails(self.center, lambda msg: sent.append(msg) or f"m{len(sent)}",
                                  lambda uid: G.official_email(self.roster, uid), now=self.clock)
        total = len(self.center.store.snapshot()["notifications"])
        self.assertEqual((len(sent), report["sent"], report["failed"]), (total, total, []))
        self.assertGreater(total, 10)


if __name__ == "__main__":
    unittest.main()
