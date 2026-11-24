# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for the job queue and the worker loop (BIO-EPIC-03, SRD-007; CN-017).

All unit tests use a fake clock. Handler and real-engine tests are in `test_handlers.py`.

    python3 -m unittest backend.work_queue.tests.test_jobs -v
"""
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from backend.match_orchestrator.store import StoreError
from backend.work_queue import jobs as J
from backend.work_queue.worker import Context, Defer, Permanent, Worker


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = float(t)

    def __call__(self):
        return self.t


class Base(unittest.TestCase):
    max_attempts = 3

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.clock = Clock()
        self.q = J.JobQueue(self.dir / "queue.json", max_attempts=self.max_attempts, backoff=lambda n: 10.0 * n)

    def check(self, sid="ta-v1", **kw):
        return J.enqueue_check(self.q, sid, now=self.clock, **kw)

    def take(self, worker="w1", **kw):
        return J.claim_next(self.q, worker, now=self.clock, **kw)

    def job(self, jid):
        return J.get_job(self.q, jid)

    def state(self):
        return self.q.store.snapshot()


class Enqueue(Base):
    def test_a_job_carries_ids_only_and_the_payload_is_checked(self):
        bad = [(J.CHECK_SUBMISSION, {"submission_id": "../x"}), (J.CHECK_SUBMISSION, {"submission_id": "a b"}),
               (J.CHECK_SUBMISSION, {"submission_id": "ta-v1", "path": "/etc/passwd"}),
               (J.CHECK_SUBMISSION, {}), (J.CHECK_SUBMISSION, {"submission_id": 5}), (J.CHECK_SUBMISSION, "x"),
               (J.RUN_ROUND, {"bracket_id": "b1", "round_no": 0}), (J.RUN_ROUND, {"bracket_id": "b1", "round_no": True}),
               (J.RUN_ROUND, {"bracket_id": "b1", "round_no": "1"}), (J.RUN_ROUND, {"bracket_id": "b1"}),
               ("run_code", {"submission_id": "ta-v1"})]
        for kind, payload in bad:
            with self.subTest(kind=kind, payload=payload), self.assertRaises(J.QueueError):
                J.enqueue(self.q, kind, payload, now=self.clock)
        self.assertEqual(J.list_jobs(self.q), [])

    def test_bad_key_priority_and_settings_are_refused(self):
        for kw in ({"key": "a b"}, {"key": ""}, {"priority": 101}, {"priority": True}):
            with self.subTest(kw=kw), self.assertRaises(J.QueueError):
                self.check(**kw)
        for n in (0, 101, True):
            with self.assertRaises(J.QueueError):
                J.JobQueue(self.dir / "x.json", max_attempts=n)

    def test_the_same_work_twice_is_one_live_job(self):
        a = self.check()
        b = self.check()
        self.assertEqual((a["created"], b["created"], a["id"] == b["id"]), (True, False, True))
        self.assertEqual(len(J.list_jobs(self.q)), 1)
        self.assertNotEqual(self.check("ta-v2")["id"], a["id"])
        self.take()                                   # running is still live
        self.assertFalse(self.check()["created"])

    def test_finished_or_dead_work_does_not_block_new_work(self):
        a = self.check()
        c = self.take()
        J.complete(self.q, c, {"ok": 1}, now=self.clock)
        b = self.check()
        self.assertTrue(b["created"])
        self.assertNotEqual(a["id"], b["id"])

    def test_round_jobs_have_their_own_keys(self):
        r1 = J.enqueue_round(self.q, "b1", 1, now=self.clock)
        r2 = J.enqueue_round(self.q, "b1", 2, now=self.clock)
        self.assertNotEqual(r1["id"], r2["id"])
        self.assertFalse(J.enqueue_round(self.q, "b1", 1, now=self.clock)["created"])

    def test_views_never_show_a_claim_token(self):
        self.check()
        c = self.take()
        self.assertNotIn(c.token, json.dumps(J.list_jobs(self.q)))
        self.assertNotIn(c.token, json.dumps(self.job(c.job_id)))
        self.assertIn(c.token, self.q.store.path.read_text())     # but it is stored, to be checked on the way back


class Claim(Base):
    def test_oldest_first_and_priority_first(self):
        a, b, c = self.check("s-a"), self.check("s-b"), self.check("s-c", priority=5)
        self.assertEqual([self.take().job_id for _ in range(3)], [c["id"], a["id"], b["id"]])
        self.assertIsNone(self.take())

    def test_a_job_is_held_by_one_worker_until_the_lease_ends(self):
        self.check()
        c = self.take("w1", lease=60)
        self.assertEqual((c.worker, c.attempt), ("w1", 1))
        self.assertIsNone(self.take("w2"))
        self.clock.t += 59
        self.assertIsNone(self.take("w2"))
        self.clock.t += 2
        again = self.take("w2")
        self.assertEqual((again.job_id, again.worker, again.attempt), (c.job_id, "w2", 2))
        self.assertEqual(self.job(c.job_id)["failures"], 1)          # a lost lease is a failure

    def test_a_replaced_worker_cannot_overwrite_the_new_workers_outcome(self):
        self.check()
        old = self.take("w1", lease=60)
        self.clock.t += 61
        new = self.take("w2")
        for action in (lambda: J.complete(self.q, old, {"x": 1}, now=self.clock),
                       lambda: J.fail(self.q, old, "late", now=self.clock),
                       lambda: J.defer(self.q, old, 5, now=self.clock),
                       lambda: J.extend(self.q, old, now=self.clock)):
            with self.assertRaises(J.Stale):
                action()
        J.complete(self.q, new, {"by": "w2"}, now=self.clock)
        with self.assertRaises(J.Stale):                               # and after it is done
            J.complete(self.q, old, {"by": "w1"}, now=self.clock)
        self.assertEqual(self.job(new.job_id)["result"], {"by": "w2"})

    def test_a_forged_token_is_refused(self):
        self.check()
        c = self.take()
        forged = J.JobClaim(c.job_id, "0" * 32, "w1", c.kind, c.payload, 1)
        with self.assertRaises(J.Stale):
            J.complete(self.q, forged, now=self.clock)
        self.assertEqual(self.job(c.job_id)["status"], J.RUNNING)

    def test_extend_renews_the_lease(self):
        self.check()
        c = self.take(lease=60)
        self.clock.t += 50
        self.assertEqual(J.extend(self.q, c, lease=60, now=self.clock), self.clock.t + 60)
        self.clock.t += 50
        self.assertIsNone(self.take("w2"))             # would have expired without the renewal

    def test_a_worker_that_keeps_dying_ends_in_dead_with_an_incident(self):
        j = self.check()
        for i in range(self.max_attempts):
            c = self.take(f"w{i}", lease=10)
            self.assertIsNotNone(c, i)
            self.clock.t += 11
        self.assertIsNone(self.take("wx"))
        done = self.job(j["id"])
        self.assertEqual((done["status"], done["failures"]), (J.DEAD, self.max_attempts))
        inc = self.state()["incidents"]
        self.assertEqual([(i["incident_type"], i["job_id"], i["status"]) for i in inc], [("job_dead", j["id"], "open")])

    def test_kinds_filter_and_bad_arguments(self):
        self.check()
        self.assertIsNone(self.take(kinds=(J.RUN_ROUND,)))
        self.assertIsNotNone(self.take(kinds=(J.CHECK_SUBMISSION,)))
        for kw in ({"lease": 0}, {"lease": True}, {"lease": 90000}):
            with self.assertRaises(J.QueueError):
                self.take(**kw)
        with self.assertRaises(J.QueueError):
            self.take("bad worker")

    def test_exactly_one_of_many_threads_gets_each_job(self):
        n = 12
        for i in range(n):
            self.check(f"s-{i}")
        got, lock = [], threading.Lock()

        def run(w):
            while (c := J.claim_next(self.q, w, now=self.clock)):
                with lock:
                    got.append(c.job_id)

        ts = [threading.Thread(target=run, args=(f"w{i}",)) for i in range(6)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(sorted(got), sorted(j["id"] for j in J.list_jobs(self.q)))
        self.assertEqual(len(got), len(set(got)), "a job was handed out twice")


class Outcomes(Base):
    def test_failure_retries_after_a_growing_wait_and_then_dies(self):
        self.check()
        c = self.take()
        v = J.fail(self.q, c, "boom", now=self.clock)
        self.assertEqual((v["status"], v["failures"], v["not_before"]), (J.QUEUED, 1, self.clock.t + 10))
        self.assertIsNone(self.take())
        self.clock.t += 10
        c = self.take()
        v = J.fail(self.q, c, "boom", now=self.clock)
        self.assertEqual(v["not_before"], self.clock.t + 20)
        self.clock.t += 20
        c = self.take()
        v = J.fail(self.q, c, "boom", now=self.clock)
        self.assertEqual((v["status"], v["failures"]), (J.DEAD, 3))
        self.assertIn("failed 3 times", self.state()["incidents"][0]["details_redacted"])
        self.assertIsNone(self.take())

    def test_a_permanent_failure_is_dead_at_once(self):
        self.check()
        v = J.fail(self.q, self.take(), "no such round", permanent=True, now=self.clock)
        self.assertEqual((v["status"], v["failures"]), (J.DEAD, 1))
        self.assertEqual(len(self.state()["incidents"]), 1)

    def test_defer_waits_without_counting_a_failure(self):
        self.check()
        v = J.defer(self.q, self.take(), 30, "busy", now=self.clock)
        self.assertEqual((v["status"], v["failures"], v["deferrals"]), (J.QUEUED, 0, 1))
        self.assertIsNone(self.take())
        self.clock.t += 30
        c = self.take()
        self.assertIsNotNone(c)
        with self.assertRaises(J.QueueError):
            J.defer(self.q, c, -1, now=self.clock)

    def test_work_that_waits_for_ever_is_not_silent(self):
        old = J.MAX_DEFERRALS
        J.MAX_DEFERRALS = 3
        try:
            j = self.check()
            for _ in range(3):
                c = self.take()
                v = J.defer(self.q, c, 0, "still busy", now=self.clock)
            self.assertEqual((v["status"], v["deferrals"]), (J.DEAD, 3))
            self.assertEqual(self.state()["incidents"][0]["job_id"], j["id"])
        finally:
            J.MAX_DEFERRALS = old

    def test_history_stays_bounded(self):
        self.check()
        for _ in range(60):
            J.defer(self.q, self.take(), 0, "x", now=self.clock)
        self.assertLessEqual(len(self.state()["jobs"]["j1"]["history"]), 30)

    def test_the_result_is_kept_bounded_and_json_only(self):
        self.check()
        J.complete(self.q, self.take(), {"text": "x" * 5000, "obj": object()}, now=self.clock)
        r = self.job("j1")["result"]
        self.assertEqual((len(r["text"]), r["obj"].startswith("<object")), (J.MAX_TEXT, True))


class Operate(Base):
    def dead_job(self):
        j = self.check()
        J.fail(self.q, self.take(), "bad", permanent=True, now=self.clock)
        return j["id"]

    def test_revive_puts_a_dead_job_back_and_closes_its_incident(self):
        jid = self.dead_job()
        v = J.revive(self.q, jid, "admin-1", now=self.clock)
        self.assertEqual((v["status"], v["failures"]), (J.QUEUED, 0))
        inc = self.state()["incidents"][0]
        self.assertEqual((inc["status"], inc["resolved_by"]), ("resolved", "admin-1"))
        self.assertIsNotNone(self.take())

    def test_revive_refuses_a_job_that_is_not_dead_or_whose_work_is_queued_again(self):
        jid = self.dead_job()
        again = self.check()                           # the same work was queued afresh
        with self.assertRaises(J.QueueError):
            J.revive(self.q, jid, "admin-1", now=self.clock)
        with self.assertRaises(J.QueueError):
            J.revive(self.q, again["id"], "admin-1", now=self.clock)
        with self.assertRaises(J.NotFound):
            J.revive(self.q, "nope", "admin-1", now=self.clock)
        with self.assertRaises(J.QueueError):
            J.revive(self.q, jid, "admin 1", now=self.clock)

    def test_alerts_are_delivered_once_and_a_failed_alert_is_retried(self):
        self.dead_job()
        sent = []

        def flaky(inc):
            if not sent:
                sent.append("fail")
                raise OSError("smtp down")
            sent.append(inc["job_id"])

        self.assertEqual(J.deliver_alerts(self.q, flaky, self.clock), 0)
        self.assertEqual(J.deliver_alerts(self.q, flaky, self.clock), 1)
        self.assertEqual(J.deliver_alerts(self.q, flaky, self.clock), 0)
        self.assertEqual(sent, ["fail", "j1"])

    def test_stats(self):
        self.dead_job()
        self.check("ta-v2")
        self.assertEqual(J.stats(self.q), {"queued": 1, "running": 0, "done": 0, "dead": 1, "open_incidents": 1})

    def test_a_damaged_queue_file_is_not_an_empty_queue(self):
        self.check()
        self.q.store.path.write_text("{ not json")
        with self.assertRaises(StoreError):
            J.list_jobs(self.q)
        with self.assertRaises(StoreError):
            self.check("other")
        self.q.store.path.write_text(json.dumps({"schema": 99, "jobs": {}, "incidents": [], "seq": 0}))
        with self.assertRaises(StoreError):
            J.stats(self.q)


class WorkerLoop(Base):
    def worker(self, handlers, **kw):
        kw.setdefault("renew_every", 3600)        # no renewal thread activity unless a test wants it
        return Worker(self.q, handlers, name="w1", now=self.clock, **kw)

    def test_a_returned_result_completes_the_job(self):
        self.check()
        w = self.worker({J.CHECK_SUBMISSION: lambda p, ctx: {"seen": p["submission_id"], "attempt": ctx.attempt}})
        self.assertEqual(w.run_once()["outcome"], "done")
        self.assertEqual(self.job("j1")["result"], {"seen": "ta-v1", "attempt": 1})
        self.assertIsNone(w.run_once())

    def test_it_only_takes_the_kinds_it_has_handlers_for(self):
        J.enqueue_round(self.q, "b1", 1, now=self.clock)
        w = self.worker({J.CHECK_SUBMISSION: lambda p, c: {}})
        self.assertIsNone(w.run_once())
        self.assertEqual(self.job("j1")["status"], J.QUEUED)
        with self.assertRaises(J.QueueError):
            self.worker({"delete_everything": lambda p, c: {}})

    def test_defer_permanent_and_error_end_differently(self):
        def handler(payload, ctx):
            sid = payload["submission_id"]
            if sid == "s-defer":
                raise Defer(30, "busy")
            if sid == "s-perm":
                raise Permanent("gone")
            raise ValueError("bug")
        for s in ("s-defer", "s-perm", "s-error"):
            self.check(s)
        w = self.worker({J.CHECK_SUBMISSION: handler})
        out = {r["job"]: r for r in w.run_until_idle()}
        self.assertEqual({k: r["outcome"] for k, r in out.items()}, {"j1": "queued", "j2": "dead", "j3": "queued"})
        self.assertEqual((self.job("j1")["failures"], self.job("j1")["deferrals"]), (0, 1))
        self.assertEqual(self.job("j3")["last_error"], "ValueError: bug")
        self.assertEqual(self.job("j2")["last_error"], "Permanent: gone")

    def test_a_job_that_always_errors_is_retried_then_dead_and_staff_are_alerted(self):
        alerts = []
        self.check()
        w = self.worker({J.CHECK_SUBMISSION: lambda p, c: 1 / 0}, alert=alerts.append)
        for _ in range(self.max_attempts):
            self.assertEqual(len(w.run_until_idle()), 1)
            self.clock.t += 100
        self.assertEqual(self.job("j1")["status"], J.DEAD)
        self.assertEqual(w.run_until_idle(), [])
        self.assertEqual([a["job_id"] for a in alerts], ["j1"])

    def test_a_shutdown_signal_gives_the_job_back_without_a_failure(self):
        self.check()

        def handler(p, c):
            raise KeyboardInterrupt
        w = self.worker({J.CHECK_SUBMISSION: handler})
        with self.assertRaises(KeyboardInterrupt):
            w.run_once()
        v = self.job("j1")
        self.assertEqual((v["status"], v["failures"], v["deferrals"]), (J.QUEUED, 0, 1))
        self.assertIsNotNone(self.take("w2"))

    def test_the_lease_is_renewed_while_a_handler_runs(self):
        self.check()
        seen = {}

        def handler(p, ctx):
            self.clock.t += 50                      # the job has now run longer than its first lease
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                exp = self.state()["jobs"]["j1"]["claim"]["expires"]
                if exp >= self.clock.t + 60:
                    break
                time.sleep(0.01)
            seen["expires"] = self.state()["jobs"]["j1"]["claim"]["expires"]
            seen["other_worker"] = self.take("w2")  # nobody may take over a live job
            return {}
        w = self.worker({J.CHECK_SUBMISSION: handler}, lease=60, renew_every=0.02)
        self.assertEqual(w.run_once()["outcome"], "done")
        self.assertGreaterEqual(seen["expires"], self.clock.t + 60 - 1e-6)
        self.assertIsNone(seen["other_worker"])

    def test_a_worker_that_lost_its_job_is_told_and_does_not_overwrite(self):
        self.check()
        seen = {}

        def handler(p, ctx):
            self.clock.t += 500                      # lease long gone, and nobody renewed it
            seen["new"] = self.take("w2", lease=60)  # a second worker takes the job over
            seen["lost_flag_set_by_renewal"] = ctx.lost.wait(0.5)
            return {"by": "w1"}
        w = self.worker({J.CHECK_SUBMISSION: handler}, lease=60, renew_every=0.02)
        self.assertEqual(w.run_once()["outcome"], "stale")
        self.assertTrue(seen["lost_flag_set_by_renewal"])
        self.assertEqual(self.job("j1")["status"], J.RUNNING)                  # still w2's
        J.complete(self.q, seen["new"], {"by": "w2"}, now=self.clock)
        self.assertEqual(self.job("j1")["result"], {"by": "w2"})

    def test_run_forever_stops_when_asked_and_finishes_the_job_it_is_on(self):
        for s in ("s1", "s2"):
            self.check(s)
        stop = threading.Event()

        def handler(p, ctx):
            if p["submission_id"] == "s1":
                stop.set()                              # stop requested during the first job
            return {}
        w = self.worker({J.CHECK_SUBMISSION: handler})
        self.assertEqual(w.run_forever(stop, idle_sleep=0.01), 1)
        self.assertEqual((self.job("j1")["status"], self.job("j2")["status"]), (J.DONE, J.QUEUED))

    def test_run_forever_picks_up_work_that_arrives_later(self):
        stop = threading.Event()
        w = self.worker({J.CHECK_SUBMISSION: lambda p, c: {}})
        t = threading.Thread(target=w.run_forever, args=(stop, 0.01))
        t.start()
        time.sleep(0.05)
        self.check()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and self.job("j1")["status"] != J.DONE:
            time.sleep(0.01)
        stop.set()
        t.join(5)
        self.assertEqual(self.job("j1")["status"], J.DONE)


if __name__ == "__main__":
    unittest.main()
