# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for the check and round handlers and the worker program (BIO-EPIC-03, SRD-007; CN-017).

Unit tests use the real registry and the real bracket with fake games and a fake clock. The last class starts
the worker program as a separate process and plays real sandboxed matches; it needs `BIO_INTEGRATION=1`.

    python3 -m unittest backend.work_queue.tests.test_handlers -v
"""
import hashlib
import json
import multiprocessing
import os
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from backend.match_orchestrator import bracket as B, orchestrator as O
from backend.match_orchestrator.store import JsonFileStore
from backend.match_orchestrator.tests.test_bracket import MAPS, lower_wins, teams
from backend.match_orchestrator.tests.test_tiebreak import PLATFORM
from backend.submission_check import trial as T
from backend.submission_registry import registry as R
from backend.work_queue import handlers as H
from backend.work_queue import jobs as J
from backend.work_queue.tests.test_jobs import Clock
from backend.work_queue.worker import Worker

GOOD = b"def turn():\n    pass\n"
DEADLINE = 2_000_000.0
CAPTAIN = R.Actor("cap", "participant", frozenset({"ta"}), frozenset({"ta"}))
REPO = Path(__file__).resolve().parents[3]


def verdict(data, status="valid", **kw):
    v = {"schema": T.SCHEMA, "status": status, "stage": "trial",
         "reasons": [] if status != "rejected" else [{"code": "T-CRASH", "message": "your bot crashed", "line": None}],
         "warnings": [], "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
         "checked_at": "2026-11-24T00:00:00Z", "map": "DefaultSmall", "trials": []}
    v.update(kw)
    return v


def exit_during_game_attempt(data_dir, started_at):
    def exit_worker(_context):
        os._exit(73)

    store = JsonFileStore(data_dir / "matches.json")
    queue = J.JobQueue(data_dir / "queue.json")
    now = Clock(started_at)
    handler = H.run_round_handler(store, exit_worker, now=now, lease_seconds=120)
    Worker(queue, {J.RUN_ROUND: handler}, name="exiting-worker", now=now, lease=60).run_once()


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.clock = Clock(DEADLINE - 100_000)
        self.q = J.JobQueue(self.dir / "queue.json", max_attempts=3, backoff=lambda n: 10.0 * n)
        self.alerts = []

    def tearDown(self):
        for p in (self.dir / "subs").glob("*"):
            if p.is_dir() and not p.is_symlink():
                os.chmod(p, 0o700)

    def worker(self, handlers, **kw):
        return Worker(self.q, handlers, name="w1", now=self.clock, renew_every=3600, alert=self.alerts.append, **kw)

    def job(self, n=1):
        return J.get_job(self.q, f"j{n}")


class CheckJobs(Base):
    def setUp(self):
        super().setUp()
        self.reg = R.Registry(self.dir / "subs", self.dir / "registry.json")
        self.calls = []
        self.answers = []                                # verdict statuses to return, in order
        self.sub = R.submit(self.reg, CAPTAIN, "ta", "t1", "bot.py", GOOD, idempotency_key="k1",
                            deadline_at=DEADLINE, now=self.clock)

    def check_fn(self, folder):
        self.calls.append(folder.name)
        a = self.answers.pop(0) if self.answers else "valid"
        if isinstance(a, Exception):
            raise a
        return verdict(GOOD, a)

    def run_worker(self):
        w = self.worker({J.CHECK_SUBMISSION: H.check_submission_handler(self.reg, self.check_fn, now=self.clock)})
        return w.run_until_idle()

    def status(self):
        rec = self.reg.store.snapshot()["submissions"][self.sub["id"]]
        return rec["validation_status"], rec["is_active"]

    def test_a_queued_check_makes_a_valid_version_active(self):
        J.enqueue_check(self.q, self.sub["id"], now=self.clock)
        self.assertEqual([r["outcome"] for r in self.run_worker()], ["done"])
        self.assertEqual(self.status(), ("valid", True))
        self.assertEqual(self.job()["result"], {"submission_id": "ta-v1", "status": "valid", "active": True, "ran": True})

    def test_a_rejected_bot_is_a_finished_job_not_a_failure(self):
        self.answers = ["rejected"]
        J.enqueue_check(self.q, self.sub["id"], now=self.clock)
        self.assertEqual([r["outcome"] for r in self.run_worker()], ["done"])
        self.assertEqual((self.status(), self.job()["failures"]), (("invalid", False), 0))

    def test_an_inconclusive_check_is_retried_later_and_nobody_is_blamed(self):
        self.answers = ["inconclusive", "valid"]
        J.enqueue_check(self.q, self.sub["id"], now=self.clock)
        self.assertEqual([r["outcome"] for r in self.run_worker()], ["queued"])
        self.assertEqual(self.status(), ("inconclusive", False))
        self.assertEqual(self.run_worker(), [])                    # not yet due
        self.clock.t += 10
        self.assertEqual([r["outcome"] for r in self.run_worker()], ["done"])
        self.assertEqual((self.status(), self.calls), (("valid", True), ["ta-v1", "ta-v1"]))

    def test_a_check_that_stays_inconclusive_ends_dead_with_an_alert_and_never_active(self):
        self.answers = ["inconclusive"] * 5
        J.enqueue_check(self.q, self.sub["id"], now=self.clock)
        for _ in range(3):
            self.run_worker()
            self.clock.t += 100
        self.assertEqual((self.job()["status"], self.status()), (J.DEAD, ("inconclusive", False)))
        self.assertEqual([a["job_id"] for a in self.alerts], ["j1"])

    def test_a_check_that_cannot_run_is_a_job_failure_and_the_claim_is_given_back(self):
        self.answers = [T.CheckError("reference bot missing"), "valid"]
        J.enqueue_check(self.q, self.sub["id"], now=self.clock)
        self.assertEqual([r["outcome"] for r in self.run_worker()], ["queued"])
        self.assertEqual(self.job()["last_error"], "CheckError: reference bot missing")
        self.assertEqual(self.status(), ("validating", False))
        self.clock.t += 10
        self.assertEqual([r["outcome"] for r in self.run_worker()], ["done"])     # claimable again at once
        self.assertEqual(self.status(), ("valid", True))

    def test_an_unknown_version_is_dead_at_once(self):
        J.enqueue_check(self.q, "ghost-v9", now=self.clock)
        self.assertEqual([r["outcome"] for r in self.run_worker()], ["dead"])
        self.assertEqual(self.calls, [])
        self.assertEqual(len(self.alerts), 1)

    def test_a_damaged_stored_file_is_dead_at_once_and_is_never_played(self):
        folder = self.reg.root / self.sub["id"]
        os.chmod(folder, 0o700)
        os.chmod(folder / "bot.py", 0o600)
        (folder / "bot.py").write_bytes(GOOD + b"# changed\n")
        J.enqueue_check(self.q, self.sub["id"], now=self.clock)
        self.assertEqual([r["outcome"] for r in self.run_worker()], ["dead"])
        self.assertEqual(self.calls, [])
        self.assertEqual([i["kind"] for i in self.reg.store.snapshot()["incidents"]], ["submission_file_damaged"])

    def test_a_second_job_for_a_checked_version_does_not_check_again(self):
        J.enqueue_check(self.q, self.sub["id"], now=self.clock)
        self.run_worker()
        J.enqueue_check(self.q, self.sub["id"], now=self.clock)
        self.run_worker()
        self.assertEqual((len(self.calls), self.job(2)["result"]["ran"]), (1, False))
        self.assertEqual(len(self.reg.store.snapshot()["submissions"]["ta-v1"]["validations"]), 2)   # static + trial

    def test_a_version_checked_by_a_live_worker_is_waited_for_not_run_twice(self):
        claim = R.claim_check(self.reg, self.sub["id"], now=self.clock)
        J.enqueue_check(self.q, self.sub["id"], now=self.clock)
        self.assertEqual([r["outcome"] for r in self.run_worker()], ["queued"])
        self.assertEqual((self.calls, self.job()["failures"]), ([], 0))
        R.record_verdict(self.reg, claim, verdict(GOOD), now=self.clock)
        self.clock.t += 61
        self.run_worker()
        self.assertEqual((self.calls, self.status(), self.job()["status"]), ([], ("valid", True), J.DONE))

    def test_a_worker_that_died_mid_check_does_not_leave_the_version_stuck(self):
        R.claim_check(self.reg, self.sub["id"], now=self.clock, lease=30)      # the dead worker's claim
        J.enqueue_check(self.q, self.sub["id"], now=self.clock)
        self.run_worker()
        self.clock.t += 61                                                     # claim and wait are over
        self.assertEqual([r["outcome"] for r in self.run_worker()], ["done"])
        self.assertEqual((self.calls, self.status()), (["ta-v1"], ("valid", True)))


class RoundJobs(Base):
    def setUp(self):
        super().setUp()
        self.store = JsonFileStore(self.dir / "matches.json")
        B.create_bracket(self.store, "b1", teams(4), MAPS, rng=random.Random(1))
        self.games = []

    def run_fn(self, ctx):
        self.games.append(ctx.match_id)
        return lower_wins(ctx)

    def handler(self, run_fn=None):
        return H.run_round_handler(self.store, run_fn or self.run_fn, alert=self.alerts.append, now=self.clock,
                                   sleep=lambda s: None)

    def run_worker(self, run_fn=None):
        return self.worker({J.RUN_ROUND: self.handler(run_fn)}).run_until_idle()

    def test_a_queued_round_is_played_and_winners_advance_once(self):
        B.start_round(self.store, "b1", 1, "org-1", now=self.clock)
        J.enqueue_round(self.q, "b1", 1, now=self.clock)
        self.assertEqual([r["outcome"] for r in self.run_worker()], ["done"])
        self.assertEqual(self.job()["result"]["round_status"], "completed")
        self.assertEqual(len(self.games), 2)
        J.enqueue_round(self.q, "b1", 1, now=self.clock)                       # the same round again
        self.run_worker()
        self.assertEqual(len(self.games), 2)
        self.assertEqual(self.job(2)["result"]["games_run"], 0)

    def test_recovering_a_round_from_an_exited_worker_preserves_one_result(self):
        B.start_round(self.store, "b1", 1, "org-1", now=self.clock)
        J.enqueue_round(self.q, "b1", 1, now=self.clock)
        process = multiprocessing.get_context("spawn").Process(
            target=exit_during_game_attempt, args=(self.dir, self.clock.t),
        )
        process.start()
        try:
            process.join(10)
            self.assertEqual(process.exitcode, 73)
        finally:
            if process.is_alive():
                process.kill()
                process.join()
            process.close()

        job = self.job()
        self.assertEqual(job["status"], J.RUNNING)
        interrupted, = self.store.snapshot()["matches"].values()
        self.assertEqual(interrupted["status"], O.RUNNING)
        self.assertIsNone(interrupted["result"])

        self.clock.t = job["claim"]["expires"] + 1
        self.assertEqual([r["outcome"] for r in self.run_worker()], [J.QUEUED])
        self.assertEqual(self.games, [])
        self.assertEqual(O.get_match(self.store, interrupted["id"]), interrupted)

        self.clock.t = self.job()["not_before"]
        self.assertGreater(self.clock.t, interrupted["lease"]["expires_at"])
        self.assertEqual([r["outcome"] for r in self.run_worker()], [J.DONE])
        recovered = O.get_match(self.store, interrupted["id"])
        self.assertEqual([a["status"] for a in recovered["attempts"]], ["platform_failed", "completed"])
        self.assertEqual(recovered["attempts"][0]["failure_reason"], "worker_lost")
        self.assertEqual(self.job()["failures"], 1)
        for field in ("map", "submission_a", "submission_b"):
            self.assertEqual(recovered[field], interrupted[field])

        bracket = B.get_bracket(self.store, "b1")
        self.assertEqual(bracket["rounds"][0]["status"], B.COMPLETED)
        self.assertEqual(bracket["rounds"][1]["status"], B.READY)
        self.assertEqual(sum(item["event"] == "advanced" for item in bracket["history"]), 2)
        before = self.store.snapshot()
        J.enqueue_round(self.q, "b1", 1, now=self.clock)
        self.assertEqual([r["outcome"] for r in self.run_worker()], [J.DONE])
        self.assertCountEqual(self.games, before["matches"].keys())
        self.assertEqual(self.store.snapshot(), before)

    def test_a_round_nobody_started_is_dead_and_plays_nothing(self):
        J.enqueue_round(self.q, "b1", 1, now=self.clock)
        self.assertEqual([r["outcome"] for r in self.run_worker()], ["dead"])
        self.assertEqual(self.games, [])
        self.assertIn("has not been started", self.job()["last_error"])
        J.enqueue_round(self.q, "ghost", 1, now=self.clock)
        self.assertEqual([r["outcome"] for r in self.run_worker()], ["dead"])

    def test_a_paused_game_finishes_the_job_with_the_round_paused(self):
        B.start_round(self.store, "b1", 1, "org-1", now=self.clock)
        J.enqueue_round(self.q, "b1", 1, now=self.clock)
        self.assertEqual([r["outcome"] for r in self.run_worker(lambda ctx: PLATFORM)], ["done"])
        res = self.job()["result"]
        self.assertEqual((res["round_status"], res["paused"]), ("paused", True))
        self.assertEqual([a["incident_type"] for a in self.alerts], ["retry_cap_reached"])

    def test_a_crash_of_the_game_player_is_a_platform_failure_inside_the_round_not_a_dead_job(self):
        B.start_round(self.store, "b1", 1, "org-1", now=self.clock)
        J.enqueue_round(self.q, "b1", 1, now=self.clock)
        calls = []

        def flaky(ctx):
            calls.append(1)
            if len(calls) == 1:
                raise OSError("disk full")
            return lower_wins(ctx)
        self.assertEqual([r["outcome"] for r in self.run_worker(flaky)], ["done"])
        self.assertEqual(self.job()["result"]["round_status"], "completed")

    def test_two_workers_never_play_the_same_match(self):
        B.start_round(self.store, "b1", 1, "org-1", now=self.clock)
        J.enqueue_round(self.q, "b1", 1, now=self.clock)
        J.enqueue_round(self.q, "b1", 1, key="again", now=self.clock)          # a duplicate that slipped past the key
        self.run_worker()
        self.assertEqual(sorted(self.games), sorted(set(self.games)))
        self.assertEqual(len(self.games), 2)

    def test_a_round_that_another_worker_is_playing_is_waited_for(self):
        B.start_round(self.store, "b1", 1, "org-1", now=self.clock)
        J.enqueue_round(self.q, "b1", 1, now=self.clock)
        entered = {}

        def other_worker_is_midway(ctx):
            # while a game runs, a second worker's job for the same round finds it taken
            if not entered:
                entered["x"] = True
                J.enqueue_round(self.q, "b1", 1, key="second", now=self.clock)
                entered["inner"] = self.worker({J.RUN_ROUND: self.handler(lambda c: self.fail("must not run"))},
                                               ).run_once()
            return lower_wins(ctx)
        self.run_worker(other_worker_is_midway)
        self.assertEqual(entered["inner"]["outcome"], "queued")
        self.assertEqual(J.get_job(self.q, "j2")["failures"], 0)


class Wiring(Base):
    def test_configured_worker_retries_map_drift_without_playing_or_advancing(self):
        from backend.match_orchestrator import maps as M
        from backend.match_orchestrator.tests.test_maps import ENGINE, FILES, GOOD as POOL_MAPS, make_jar
        from backend.work_queue import service as S

        jar = make_jar(self.dir / "engine.jar", FILES)
        store = JsonFileStore(self.dir / "matches.json")
        catalogue = M.load_engine_maps(jar)
        M.create_pool(store, "p1", catalogue, ENGINE, **POOL_MAPS)
        M.create_bracket_from_pool(store, "b1", teams(2), "p1", catalogue, ENGINE)
        B.start_round(store, "b1", 1, "org-1", now=self.clock)
        job = J.enqueue_round(self.q, "b1", 1, now=self.clock)
        played = []

        def play_game(context):
            played.append(context.match_id)
            return lower_wins(context)

        worker = S.build_worker(self.dir, engine_jar=jar, play=self.fail, run_fn=play_game, now=self.clock)
        changed_maps = {**FILES, POOL_MAPS["play"][0]: b"changed"}
        make_jar(jar, changed_maps)
        self.assertEqual(worker.run_once()["outcome"], J.QUEUED)
        self.assertEqual(played, [])
        self.assertEqual(store.snapshot()["matches"], {})
        failed = J.get_job(self.q, job["id"])
        self.assertIn("changed since the pool was made", failed["last_error"])

        make_jar(jar, FILES)
        self.clock.t = failed["not_before"]
        self.assertEqual(worker.run_once()["outcome"], J.DONE)
        self.assertEqual(B.get_bracket(store, "b1")["rounds"][0]["status"], B.COMPLETED)
        make_jar(jar, changed_maps)
        J.enqueue_round(self.q, "b1", 1, now=self.clock)
        self.assertEqual(worker.run_once()["outcome"], J.DONE)
        self.assertEqual(len(played), 1)

    def test_trial_games_and_tournament_games_share_one_host_lock_and_the_registry_is_the_bots_dir(self):
        from unittest import mock
        from backend.work_queue import service as S
        seen = {}

        def fake_play(scaffold, py, out_root, **kw):
            seen["play"] = (Path(out_root), kw["lock_path"], kw["sandbox"])
            return lambda *a: {}

        def fake_run_fn(scaffold, py, bots_dir, out_root, **kw):
            seen["run"] = (Path(bots_dir), Path(out_root), kw["lock_path"], kw["sandbox"])
            return lambda ctx: {}
        with mock.patch.object(S.T, "launcher_play", fake_play), mock.patch.object(S.O, "launcher_run_fn", fake_run_fn):
            w = S.build_worker(self.dir, sandbox=True)
        self.assertEqual(sorted(w.handlers), [J.CHECK_SUBMISSION, J.RUN_ROUND])
        self.assertEqual(seen["play"][1], seen["run"][2])
        self.assertEqual(seen["play"][1], self.dir / "host.lock")
        self.assertEqual(seen["run"][0], self.dir / "submissions")
        self.assertEqual((seen["play"][2], seen["run"][3]), (True, True))
        self.assertNotEqual(seen["play"][0], seen["run"][1])

    def test_no_sandbox_is_only_used_when_asked_for(self):
        from unittest import mock
        from backend.work_queue import service as S
        seen = []
        with mock.patch.object(S.T, "launcher_play", lambda *a, **kw: seen.append(kw["sandbox"]) or (lambda *x: {})), \
                mock.patch.object(S.O, "launcher_run_fn", lambda *a, **kw: seen.append(kw["sandbox"]) or (lambda c: {})):
            S.build_worker(self.dir)
            S.build_worker(self.dir, sandbox=False)
        self.assertEqual(seen, [True, True, False, False])


@unittest.skipUnless(os.environ.get("BIO_INTEGRATION") == "1", "set BIO_INTEGRATION=1 to play real matches")
class WorkerProgram(unittest.TestCase):
    """The worker as its own process: queue and data on disk, real sandboxed games, nothing in memory shared."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data = Path(self._tmp.name) / "data"
        self.addCleanup(self._unlock)

    def _unlock(self):
        for p in (self.data / "submissions").glob("*"):
            if p.is_dir():
                os.chmod(p, 0o700)

    def cli(self, *args, timeout=900):
        return subprocess.run([sys.executable, "-m", "backend.work_queue.service", "--data-dir", str(self.data), *args],
                              cwd=REPO, capture_output=True, text=True, timeout=timeout)

    def test_uploads_are_checked_then_a_tournament_round_is_played_by_separate_worker_runs(self):
        from backend.match_runner import launcher as L
        src = (L.DEFAULT_SCAFFOLD / "src" / "examplefuncsplayer_py" / "bot.py").read_bytes()
        reg = R.Registry(self.data / "submissions", self.data / "registry.json")
        far = 4_000_000_000.0
        for team in ("ta", "tb"):
            who = R.Actor(f"cap-{team}", "participant", frozenset({team}), frozenset({team}))
            R.submit(reg, who, team, "t1", "bot.py", src, idempotency_key="k", deadline_at=far)
            self.assertEqual(self.cli("enqueue-check", f"{team}-v1").returncode, 0)
        out = self.cli("run", "--once")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        subs = reg.store.snapshot()["submissions"]
        self.assertEqual([(s["validation_status"], s["is_active"]) for s in subs.values()], [("valid", True)] * 2)

        store = JsonFileStore(self.data / "matches.json")
        maps = {"play": ["DefaultSmall"], "tiebreak_normal": ["jail"], "tiebreak_final": ["jail", "pipes", "keepout"]}
        B.create_bracket(store, "real", [{"team": t, "submission": f"{t}-v1"} for t in ("ta", "tb")], maps)
        B.start_round(store, "real", 1, "org-1")
        self.assertEqual(self.cli("enqueue-round", "real", "1").returncode, 0)
        out = self.cli("run", "--once")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        b = B.get_bracket(store, "real")
        self.assertEqual(b["status"], "completed")
        self.assertIn(b["champion"], ("ta", "tb"))
        status = json.loads(self.cli("status").stdout)
        self.assertEqual(status["counts"], {"queued": 0, "running": 0, "done": 3, "dead": 0, "open_incidents": 0})


if __name__ == "__main__":
    unittest.main()
