# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for the deadline scheduler (BIO-EPIC-06; CN-019).

Real tournament store, registry, queue, bracket and replay vault; fake checks, fake games and a fake clock.

    python3 -m unittest backend.tournaments.tests.test_scheduler -v
"""
import random
import unittest

from backend.match_orchestrator import bracket as B
from backend.match_orchestrator import replays as P
from backend.submission_registry import registry as R
from backend.tournament_flow import flow as F
from backend.tournament_flow.tests.test_flow import BOT, DEADLINE, ENGINE, BracketBase, captain
from backend.tournaments import scheduler as S
from backend.tournaments import tournaments as T
from backend.work_queue import jobs as J

ADMIN = R.Actor("adm", "admin", frozenset(), frozenset(), frozenset())
ORG = R.Actor("org1", "organizer", frozenset(), frozenset(), frozenset())
REG_D = DEADLINE - 50_000


class SchedBase(BracketBase):
    def setUp(self):
        super().setUp()
        self.treg = T.Tournaments.at(self.dir / "tournaments.json")
        self.make("t1")

    def make(self, tid, pool="pool", open_=True):
        T.create(self.treg, ORG, tid, f"Cup {tid}", "", REG_D, DEADLINE, idempotency_key=f"k-{tid}", now=self.clock)
        T.submit_for_approval(self.treg, ORG, tid, now=self.clock)
        T.approve(self.treg, ADMIN, tid, confirm=True, now=self.clock)
        if pool:
            T.edit(self.treg, ORG, tid, {"map_pool_id": pool}, now=self.clock)
        if open_:
            T.open_registration(self.treg, ORG, tid, now=self.clock)

    def tick(self, **kw):
        return S.tick(self.treg, self.flow, catalogue=self.catalogue, engine_version=ENGINE, alert=self.alerts.append,
                      rng=random.Random(3), now=self.clock, **kw)

    def status(self, tid="t1"):
        return T.get(self.treg, ADMIN, tid)["status"]

    def incidents(self):
        return [i for i in self.flow.store.snapshot()["incidents"] if i["incident_type"] == "tournament_blocked"]

    def up_to(self, tid, team, data=BOT, key="k1"):
        return F.upload(self.flow, captain(team), team, tid, "bot.py", data, idempotency_key=key,
                        deadline_at=DEADLINE, now=self.clock)


class Opening(SchedBase):
    def test_nothing_happens_before_the_submission_deadline(self):
        self.ready(("ta", "tb"))
        self.clock.t = DEADLINE - 1
        out = self.tick()
        self.assertEqual((out["opened"], out["blocked"], out["waiting"]), ([], {}, {}))
        self.assertEqual((self.status(), self.snap()["pins"]), ("registration_open", {}))

    def test_at_the_deadline_the_bracket_is_drawn_and_the_tournament_runs(self):
        self.ready()
        self.clock.t = DEADLINE
        out = self.tick()
        self.assertEqual((out["opened"], out["blocked"], out["waiting"]), (["t1"], {}, {}))
        self.assertEqual(self.status(), "running")
        b = B.get_bracket(self.flow.store, "t1")
        self.assertEqual((b["tournament_id"], b["map_pool"], len(b["teams"])), ("t1", "pool", 3))
        self.assertEqual(sorted(self.snap()["pins"]["t1"]["teams"]), ["ta", "tb", "tc"])

    def test_a_second_tick_changes_nothing(self):
        self.ready()
        self.clock.t = DEADLINE
        self.tick()
        before = (self.flow.store.snapshot()["brackets"], self.snap()["pins"], T.audit_log(self.treg, ADMIN, "t1"))
        out = self.tick()
        self.assertEqual((out["opened"], out["completed"], out["blocked"]), ([], [], {}))
        self.assertEqual((self.flow.store.snapshot()["brackets"], self.snap()["pins"], T.audit_log(self.treg, ADMIN, "t1")), before)

    def test_a_tick_that_died_after_the_draw_finishes_the_status_change(self):
        self.ready(("ta", "tb"))
        self.clock.t = DEADLINE
        self.open(("ta", "tb"), bracket_id="t1")                  # the draw happened, `mark_running` did not
        self.assertEqual(self.status(), "registration_open")
        self.assertEqual(self.tick()["opened"], ["t1"])
        self.assertEqual(self.status(), "running")
        self.assertEqual(len(self.flow.store.snapshot()["brackets"]), 1)

    def test_a_tournament_whose_registration_was_never_opened_is_left_alone(self):
        self.make("t2", open_=False)
        self.ready(("ta", "tb"))
        self.clock.t = DEADLINE
        self.tick()
        self.assertEqual(self.status("t2"), "approved")
        self.assertEqual(self.incidents(), [])

    def test_a_tournament_that_is_running_or_later_is_not_drawn_again(self):
        self.ready(("ta", "tb"))
        self.clock.t = DEADLINE
        self.tick()
        self.tick()
        self.assertEqual(self.status(), "running")

    def test_teams_come_from_the_uploads_unless_the_caller_names_them(self):
        self.ready(("ta", "tb", "tc"))
        self.assertEqual(S.teams_with_uploads(self.flow, "t1"), ["ta", "tb", "tc"])
        self.assertEqual(S.teams_with_uploads(self.flow, "t2"), [])
        self.clock.t = DEADLINE
        self.tick(teams_of=lambda tid: ["ta", "tb"])
        self.assertEqual([e["team"] for e in B.get_bracket(self.flow.store, "t1")["teams"]], ["ta", "tb"])


class Waiting(SchedBase):
    def test_an_unfinished_check_makes_the_tick_wait_without_an_incident_then_open(self):
        self.up("ta"), self.up("tb")
        self.check_all()
        self.up("ta", data=BOT + b"# v2\n", key="k2")             # newest version unchecked
        self.clock.t = DEADLINE
        out = self.tick()
        self.assertEqual((out["opened"], out["waiting"], out["blocked"]), ([], {"t1": ["ta"]}, {}))
        self.assertEqual((self.status(), self.snap()["pins"], self.incidents()), ("registration_open", {}, []))
        self.check_all()
        self.assertEqual(self.tick()["opened"], ["t1"])

    def test_the_tick_queues_the_check_that_nobody_queued(self):
        self.up("ta"), self.up("tb")
        self.check_all()
        R.submit(self.flow.registry, captain("ta"), "ta", "t1", "bot.py", BOT + b"# v2\n", idempotency_key="k2",
                 deadline_at=DEADLINE, now=self.clock)            # stored, no job
        self.assertEqual(J.list_jobs(self.flow.queue, J.QUEUED), [])
        self.clock.t = DEADLINE
        out = self.tick()
        self.assertEqual(len(out["housekeeping"]["checks"]["queued"]), 1)
        self.assertEqual([j["payload"] for j in J.list_jobs(self.flow.queue, J.QUEUED)], [{"submission_id": "ta-v2"}])
        self.assertEqual(out["waiting"], {"t1": ["ta"]})


class Blocked(SchedBase):
    def test_no_map_pool_blocks_with_one_incident_however_often_it_ticks(self):
        self.make("t2", pool=None)
        self.up("ta"), self.up("tb")                              # t1 is fine
        for t in ("tx", "ty"):
            self.up_to("t2", t)
        self.check_all()
        self.clock.t = DEADLINE
        out = self.tick()
        self.assertIn("map pool", out["blocked"]["t2"])
        self.tick(), self.tick()
        incs = self.incidents()
        self.assertEqual([(i["tournament_id"], i["status"]) for i in incs], [("t2", "open")])
        self.assertEqual(self.status("t2"), "registration_open")

    def test_the_incident_is_delivered_to_the_alert_channel_once(self):
        self.make("t2", pool=None)
        self.up("ta"), self.up("tb")                              # t1 is fine
        self.up_to("t2", "tx")
        self.check_all()
        self.clock.t = DEADLINE
        self.assertEqual(self.tick()["alerts"], 1)
        self.assertEqual(self.tick()["alerts"], 0)
        self.assertEqual([a["incident_type"] for a in self.alerts], ["tournament_blocked"])

    def test_nobody_uploaded_anything_blocks(self):
        self.clock.t = DEADLINE
        self.assertIn("no team", self.tick()["blocked"]["t1"])

    def test_fewer_than_two_playable_teams_blocks_without_pinning_and_the_extension_recovers(self):
        self.up("ta"), self.up("tb", b"nothing useful\n")
        self.check_all()
        self.clock.t = DEADLINE
        out = self.tick()
        self.assertIn("at least 2", out["blocked"]["t1"])
        self.assertEqual((self.snap()["pins"], self.flow.store.snapshot().get("brackets", {})), ({}, {}))
        self.assertEqual(len(self.incidents()), 1)
        # An Admin extends; the second team uploads a good bot; the next ticks draw the bracket.
        T.extend_deadline(self.treg, ADMIN, "t1", "submission", DEADLINE + 5_000, "second team had a typo", confirm=True, now=self.clock)
        F.upload(self.flow, captain("tb"), "tb", "t1", "bot.py", BOT, idempotency_key="k9",
                 deadline_at=T.deadline(self.treg, "t1", "submission"), now=self.clock)
        self.assertEqual(self.tick()["opened"], [])               # deadline not reached again yet
        self.check_all()
        self.clock.t = DEADLINE + 5_000
        self.assertEqual(self.tick()["opened"], ["t1"])
        self.assertEqual(self.status(), "running")

    def test_a_bad_pool_blocks_that_tournament_and_not_the_others(self):
        self.make("t2", pool="no-such-pool")
        for t in ("ta", "tb"):
            self.up_to("t1", t)
        for t in ("tx", "ty"):
            self.up_to("t2", t)
        self.check_all()
        self.clock.t = DEADLINE
        out = self.tick()
        self.assertEqual(out["opened"], ["t1"])
        self.assertEqual(list(out["blocked"]), ["t2"])
        self.assertEqual([i["tournament_id"] for i in self.incidents()], ["t2"])

    def test_a_running_tournament_without_a_bracket_is_reported_not_ignored(self):
        self.clock.t = DEADLINE
        T.mark_running(self.treg, "t1", "scheduler", now=self.clock)
        out = self.tick()
        self.assertIn("t1", out["blocked"])
        self.assertEqual(len(self.incidents()), 1)


class Finishing(SchedBase):
    def start(self):
        self.ready(("ta", "tb"))
        self.clock.t = DEADLINE
        self.tick()

    def test_a_running_tournament_with_a_champion_completes(self):
        self.start()
        F.start_round(self.flow, "t1", 1, "org-1", now=self.clock)
        self.assertEqual(self.tick()["completed"], [])            # games not played yet
        self.play("t1")
        out = self.tick()
        self.assertEqual((out["completed"], self.status()), (["t1"], "completed"))
        self.assertEqual(self.tick()["completed"], [])            # once

    def test_the_replays_of_finished_games_are_stored_by_the_tick_when_a_vault_is_given(self):
        self.start()
        F.start_round(self.flow, "t1", 1, "org-1", now=self.clock)
        self.play("t1")
        vault = P.Vault(self.dir / "vault", P.ReplayIndex(self.dir / "replays.json"))
        out = self.tick(vault=vault)
        self.assertIn("t1", out["housekeeping"]["replays"])
        self.assertEqual(out["housekeeping"]["archived_skipped"], [])

    def test_a_tick_does_not_start_rounds(self):
        self.start()
        self.tick()
        self.assertEqual(B.get_bracket(self.flow.store, "t1")["rounds"][0]["status"], "ready")
        self.assertEqual(J.list_jobs(self.flow.queue, J.QUEUED), [])


if __name__ == "__main__":
    unittest.main()
