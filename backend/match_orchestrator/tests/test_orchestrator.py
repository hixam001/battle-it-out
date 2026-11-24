# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for match jobs and platform retry (BIO-301 core, BIO-306, TC-04).

Unit tests use a fake run function and always run. The last class plays real matches through the launcher
and needs `BIO_INTEGRATION=1`, the primary Python environment, Gradle offline, bubblewrap.

    python3 -m unittest backend.match_orchestrator.tests.test_orchestrator -v
    BIO_INTEGRATION=1 python3 -m unittest backend.match_orchestrator.tests.test_orchestrator -v
"""
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path

from backend.match_orchestrator import orchestrator as O
from backend.match_orchestrator.store import JsonFileStore, StoreError

NORMAL_A = {"outcome": "completed", "classification": "normal", "ok": True, "winner": "A", "round": 120,
            "reason": "Reason: destroyed", "replay": "/x/r.bc26", "replay_sha256": "ab" * 32,
            "structured_log": {"path": "/x/l.jsonl", "events": 5}, "gradle_exit": 0}
BOT_CRASH_B = {"outcome": "bot_failure", "classification": "bot_crash", "kind": "runner_ended_connection",
               "loser": "B", "winner_by_forfeit": "A", "detail": "team B's process ended the connection"}
PLATFORM = {"outcome": "platform_failure", "classification": "platform_failure", "kind": "engine_failure",
            "detail": "the engine server ended the connection first"}


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = JsonFileStore(Path(self._tmp.name) / "state.json")
        self.clock = Clock()
        self.alerts = []
        self.sleeps = []

    def create(self, match_id="m1", **kw):
        return O.create_match(self.store, match_id, "team-a", "team-b", "DefaultSmall", "sub-a-v3", "sub-b-v1",
                              now=self.clock, **kw)

    def run_job(self, script, match_id="m1", **kw):
        """Run with a run function that returns/raises the next scripted item; records every context."""
        calls = []
        items = list(script)

        def run_fn(ctx):
            calls.append(ctx)
            item = items.pop(0)
            if isinstance(item, BaseException):
                raise item
            return item
        out = O.run_match_job(self.store, match_id, run_fn, owner=kw.pop("owner", "w1"), alert=self.alerts.append,
                              sleep=self.sleeps.append, now=self.clock, **kw)
        return out, calls

    def match(self, match_id="m1"):
        return O.get_match(self.store, match_id)


class Creation(Base):
    def test_create_is_idempotent_and_conflicts_are_refused(self):
        a = self.create()
        b = self.create()
        self.assertEqual(a, b)
        self.assertEqual(a["status"], "scheduled")
        with self.assertRaises(O.ConflictError):
            O.create_match(self.store, "m1", "team-a", "team-b", "OtherMap", "sub-a-v3", "sub-b-v1")
        with self.assertRaises(O.ConflictError):
            O.create_match(self.store, "m1", "team-a", "team-b", "DefaultSmall", "sub-a-v4", "sub-b-v1")

    def test_bad_input_is_refused(self):
        for kw in ({"match_id": "has space"}, {"team_a": ""}, {"submission_b": "x" * 65}, {"map_name": "a;b"}):
            args = dict(match_id="m", team_a="a", team_b="b", map_name="M", submission_a="s1", submission_b="s2")
            args.update(kw)
            with self.assertRaises(O.OrchestratorError, msg=kw):
                O.create_match(self.store, **args)
        for n in (0, 101, True, "10"):
            with self.assertRaises(O.OrchestratorError, msg=n):
                self.create(max_attempts=n)

    def test_unknown_match(self):
        with self.assertRaises(O.OrchestratorError):
            O.queue_match(self.store, "nope")


class Outcomes(Base):
    def test_normal_result_completes_once_with_the_winning_team(self):
        self.create()
        out, calls = self.run_job([NORMAL_A])
        self.assertEqual(out, {"status": "completed", "ran": 1, "skipped": None})
        m = self.match()
        self.assertEqual(m["result"]["result_type"], "normal")
        self.assertEqual((m["result"]["winner_team"], m["result"]["loser_team"]), ("team-a", "team-b"))
        self.assertEqual(m["result"]["winner_submission"], "sub-a-v3")
        self.assertEqual(m["result"]["round"], 120)
        self.assertEqual(m["result"]["structured_log"], "/x/l.jsonl")
        self.assertEqual([h["to"] for h in m["history"]], ["queued", "running", "completed"])
        self.assertEqual(m["attempts"][0]["status"], "completed")

    def test_bot_failure_is_a_forfeit_and_is_never_retried(self):
        self.create()
        out, calls = self.run_job([BOT_CRASH_B])
        self.assertEqual((out["status"], out["ran"], len(calls)), ("completed", 1, 1))
        m = self.match()
        self.assertEqual(m["result"]["result_type"], "bot_forfeit")
        self.assertEqual((m["result"]["winner_team"], m["result"]["loser_team"]), ("team-a", "team-b"))
        self.assertEqual(m["attempts"][0]["failure_class"], "bot")
        self.assertIn("bot_forfeit", [h["to"] for h in m["history"]])
        self.assertEqual(self.sleeps, [])
        self.assertEqual(self.alerts, [])

    def test_bot_failure_on_side_a_makes_b_win(self):
        self.create()
        r = dict(BOT_CRASH_B, loser="A", winner_by_forfeit="B")
        self.run_job([r])
        self.assertEqual(self.match()["result"]["winner_team"], "team-b")

    def test_a_platform_failure_is_retried_with_the_same_map_and_bot_versions(self):
        self.create()
        out, calls = self.run_job([PLATFORM, PLATFORM, NORMAL_A])
        self.assertEqual((out["status"], out["ran"]), ("completed", 3))
        self.assertEqual([c.attempt for c in calls], [1, 2, 3])
        for field in ("match_id", "team_a", "team_b", "map", "submission_a", "submission_b"):
            self.assertEqual(len({getattr(c, field) for c in calls}), 1, field)
        self.assertEqual((calls[0].map, calls[0].submission_a, calls[0].submission_b), ("DefaultSmall", "sub-a-v3", "sub-b-v1"))
        self.assertEqual(len({c.trace_id for c in calls}), 3)
        m = self.match()
        self.assertEqual([a["status"] for a in m["attempts"]], ["platform_failed", "platform_failed", "completed"])
        self.assertEqual(m["attempts"][0]["failure_reason"], "engine_failure")
        self.assertEqual(m["result"]["attempt"], 3)
        self.assertEqual(self.sleeps, [2.0, 4.0])

    def test_seed_is_new_on_every_attempt_when_a_seed_function_is_given_and_none_otherwise(self):
        self.create("m1")
        _, calls = self.run_job([PLATFORM, NORMAL_A], seed_fn=lambda n: 1000 + n)
        self.assertEqual([c.seed for c in calls], [1001, 1002])
        self.assertEqual([a["seed"] for a in self.match()["attempts"]], [1001, 1002])
        self.create("m2")
        _, calls = self.run_job([PLATFORM, NORMAL_A], match_id="m2")
        self.assertEqual([c.seed for c in calls], [None, None])    # the engine's seed is not controllable (CN-009)

    def test_run_function_exception_is_a_platform_failure_not_a_bot_loss(self):
        self.create()
        out, calls = self.run_job([RuntimeError("disk full"), NORMAL_A])
        m = self.match()
        self.assertEqual(m["attempts"][0]["failure_reason"], "runner_exception")
        self.assertIn("disk full", m["attempts"][0]["detail"])
        self.assertEqual(m["result"]["result_type"], "normal")

    def test_inconsistent_answers_are_platform_failures_and_never_invent_a_winner(self):
        bad = [None, "completed", {}, {"outcome": "weird"},
               {"outcome": "completed", "classification": "normal", "ok": True, "winner": "C"},
               {"outcome": "completed", "classification": "normal", "ok": True},
               {"outcome": "completed", "classification": "bot_crash", "ok": True, "winner": "A"},
               {"outcome": "bot_failure", "classification": "bot_crash", "loser": "B", "winner_by_forfeit": "B"},
               {"outcome": "bot_failure", "classification": "normal", "loser": "B", "winner_by_forfeit": "A"},
               {"outcome": "bot_failure", "classification": "bot_crash", "loser": "Z"}]
        for i, item in enumerate(bad):
            v = O.interpret(item)
            self.assertEqual(v["class"], "platform_failure", item)
            self.assertEqual(v["kind"], "malformed_result", item)

    def test_a_failed_log_write_does_not_lose_the_result(self):
        self.create()
        self.run_job([dict(NORMAL_A, structured_log={"error": "OSError: disk full"})])
        m = self.match()
        self.assertEqual(m["result"]["winner_team"], "team-a")
        self.assertIsNone(m["result"]["structured_log"])

    def test_a_winner_without_a_clean_exit_is_retried(self):
        v = O.interpret(dict(NORMAL_A, ok=False))
        self.assertEqual((v["class"], v["kind"]), ("platform_failure", "unclean_completion"))

    def test_stored_summary_is_bounded_and_json_only(self):
        r = dict(NORMAL_A, reason="x" * 5000, evidence={"a": {"b": {"c": {"d": 1}}}}, usage={"A": object()})
        v = O.interpret(r)
        self.assertEqual(len(v["summary"]["reason"]), O.MAX_TEXT)
        json.dumps(v["summary"])
        self.assertNotIn("gradle_exit", v["summary"])


class RetryCap(Base):
    def test_cap_pauses_the_match_records_an_incident_and_alerts_once(self):
        self.create(max_attempts=3)
        out, calls = self.run_job([PLATFORM] * 3)
        self.assertEqual((out["status"], out["ran"], len(calls)), ("paused", 3, 3))
        m = self.match()
        self.assertIsNone(m["result"])
        self.assertEqual(m["history"][-1]["to"], "paused")
        snap = self.store.snapshot()
        self.assertEqual(len(snap["incidents"]), 1)
        inc = snap["incidents"][0]
        self.assertEqual((inc["match_id"], inc["incident_type"], inc["attempt_count"], inc["status"]),
                         ("m1", "retry_cap_reached", 3, "open"))
        self.assertIsNotNone(inc["alerted_admin_at"])
        self.assertEqual(len(self.alerts), 1)
        self.assertEqual(self.sleeps, [2.0, 4.0])      # no wait after the last failure
        # a repeated job does not run anything and does not alert again
        out, calls = self.run_job([])
        self.assertEqual((out["status"], out["skipped"], len(calls)), ("paused", "paused", 0))
        self.assertEqual(len(self.alerts), 1)

    def test_default_cap_is_ten_attempts_in_total(self):
        self.create()
        out, calls = self.run_job([PLATFORM] * 10)
        self.assertEqual((out["status"], len(calls)), ("paused", 10))

    def test_bot_failures_do_not_count_towards_the_cap(self):
        self.create(max_attempts=2)
        out, _ = self.run_job([PLATFORM, BOT_CRASH_B])
        self.assertEqual(out["status"], "completed")

    def test_failed_alert_keeps_the_incident_and_is_retried_later(self):
        self.create(max_attempts=1)
        sent = []

        def broken(inc):
            raise ConnectionError("smtp down")
        O.run_match_job(self.store, "m1", lambda c: PLATFORM, owner="w1", alert=broken, sleep=self.sleeps.append, now=self.clock)
        inc = self.store.snapshot()["incidents"][0]
        self.assertIsNone(inc["alerted_admin_at"])
        self.assertIn("smtp down", inc["alert_error"])
        self.assertEqual(O.deliver_alerts(self.store, sent.append, self.clock), 1)
        self.assertEqual(len(sent), 1)
        self.assertIsNotNone(self.store.snapshot()["incidents"][0]["alerted_admin_at"])
        self.assertEqual(O.deliver_alerts(self.store, sent.append, self.clock), 0)

    def test_configuration_error_pauses_at_once_without_burning_retries(self):
        self.create()
        out, calls = self.run_job([O.ConfigurationError("bot directory not found: sub-a-v3")])
        self.assertEqual((out["status"], len(calls), self.sleeps), ("paused", 1, []))
        inc = self.store.snapshot()["incidents"][0]
        self.assertEqual(inc["incident_type"], "configuration_error")
        self.assertEqual(len(self.alerts), 1)
        self.assertEqual(self.match()["attempts"][0]["failure_reason"], "configuration_error")

    def test_resume_gives_more_attempts_and_resolves_the_incident(self):
        self.create(max_attempts=2)
        self.run_job([PLATFORM] * 2)
        with self.assertRaises(O.OrchestratorError):
            O.resume_paused(self.store, "m1", "not a valid actor!")
        self.assertEqual(O.resume_paused(self.store, "m1", "admin-1", 3, now=self.clock), "retry_queued")
        inc = self.store.snapshot()["incidents"][0]
        self.assertEqual((inc["status"], inc["resolved_by"]), ("resolved", "admin-1"))
        out, calls = self.run_job([PLATFORM, NORMAL_A])
        self.assertEqual((out["status"], [c.attempt for c in calls]), ("completed", [3, 4]))
        with self.assertRaises(O.OrchestratorError):      # not paused any more
            O.resume_paused(self.store, "m1", "admin-1")


class DuplicateDelivery(Base):
    def test_repeating_a_finished_job_changes_nothing(self):
        self.create()
        self.run_job([NORMAL_A])
        before = self.store.snapshot()
        out, calls = self.run_job([PLATFORM])
        self.assertEqual((out["status"], out["skipped"], calls), ("completed", "already_completed", []))
        self.assertEqual(self.store.snapshot(), before)

    def test_a_job_that_is_running_on_another_worker_is_skipped(self):
        self.create()
        kind, ctx = O.claim(self.store, "m1", "w1", now=self.clock)
        self.assertEqual(kind, "run")
        out, calls = self.run_job([NORMAL_A], owner="w2")
        self.assertEqual((out["skipped"], calls, out["status"]), ("running_elsewhere", [], "running"))
        self.assertEqual(len(self.match()["attempts"]), 1)

    def test_answers_from_the_wrong_worker_or_attempt_or_repeated_are_dropped(self):
        self.create()
        _, ctx = O.claim(self.store, "m1", "w1", now=self.clock)
        self.assertFalse(O.finish(self.store, "m1", ctx.attempt, "intruder", NORMAL_A, now=self.clock)["applied"])
        self.assertFalse(O.finish(self.store, "m1", 2, "w1", NORMAL_A, now=self.clock)["applied"])
        self.assertEqual(self.match()["status"], "running")
        self.assertTrue(O.finish(self.store, "m1", ctx.attempt, "w1", NORMAL_A, now=self.clock)["applied"])
        again = O.finish(self.store, "m1", ctx.attempt, "w1", dict(NORMAL_A, winner="B"), now=self.clock)
        self.assertFalse(again["applied"])
        self.assertEqual(self.match()["result"]["winner_team"], "team-a")

    def test_advancement_can_be_taken_exactly_once(self):
        self.create()
        self.assertIsNone(O.take_advancement(self.store, "m1"))          # not finished
        self.run_job([NORMAL_A])
        first = O.take_advancement(self.store, "m1", self.clock)
        self.assertEqual(first["winner_team"], "team-a")
        self.assertIsNone(O.take_advancement(self.store, "m1"))
        self.assertIsNone(O.take_advancement(self.store, "m1"))

    def test_two_workers_at_once_run_the_match_once_and_advance_once(self):
        self.create()
        calls, gate = [], threading.Event()

        def slow(ctx):
            calls.append(ctx)
            gate.wait(5)
            return NORMAL_A
        outs = []

        def worker(name):
            outs.append(O.run_match_job(self.store, "m1", slow, owner=name, sleep=lambda s: None))
        threads = [threading.Thread(target=worker, args=(f"w{i}",)) for i in range(6)]
        for t in threads:
            t.start()
        time.sleep(0.5)
        gate.set()
        for t in threads:
            t.join(10)
        self.assertEqual(len(calls), 1)
        self.assertEqual(sorted(o["ran"] for o in outs), [0, 0, 0, 0, 0, 1])
        taken = [O.take_advancement(self.store, "m1") for _ in range(5)]
        self.assertEqual(len([t for t in taken if t]), 1)

    def test_a_dead_worker_is_replaced_after_its_lease_and_counts_as_a_platform_failure(self):
        self.create(max_attempts=2)
        O.claim(self.store, "m1", "dead", now=self.clock, lease_seconds=100)
        self.clock.t += 50
        out, _ = self.run_job([NORMAL_A], owner="w2", lease_seconds=100)
        self.assertEqual(out["skipped"], "running_elsewhere")
        self.clock.t += 100
        out, calls = self.run_job([NORMAL_A], owner="w2", lease_seconds=100)
        self.assertEqual((out["status"], [c.attempt for c in calls]), ("completed", [2]))
        m = self.match()
        self.assertEqual((m["attempts"][0]["status"], m["attempts"][0]["failure_reason"]), ("platform_failed", "worker_lost"))
        # the dead worker answers late: ignored
        self.assertFalse(O.finish(self.store, "m1", 1, "dead", dict(NORMAL_A, winner="B"), now=self.clock)["applied"])
        self.assertEqual(self.match()["result"]["winner_team"], "team-a")

    def test_lost_workers_count_towards_the_cap(self):
        self.create(max_attempts=1)
        O.claim(self.store, "m1", "dead", now=self.clock, lease_seconds=10)
        self.clock.t += 11
        out, calls = self.run_job([NORMAL_A], owner="w2")
        self.assertEqual((out["status"], out["skipped"], calls), ("paused", "paused", []))
        self.assertEqual(len(self.store.snapshot()["incidents"]), 1)
        self.assertEqual(len(self.alerts), 1)


class Store(Base):
    def test_a_damaged_file_is_an_error_not_an_empty_store(self):
        self.create()
        self.store.path.write_text("{ not json")
        with self.assertRaises(StoreError):
            self.store.snapshot()
        self.assertEqual(self.store.path.read_text(), "{ not json")      # untouched
        self.store.path.write_text(json.dumps({"schema": 99, "matches": {}, "incidents": []}))
        with self.assertRaises(StoreError):
            self.store.snapshot()

    def test_an_exception_inside_a_transaction_writes_nothing(self):
        self.create()
        before = self.store.path.read_bytes()
        with self.assertRaises(RuntimeError):
            with self.store.transaction() as state:
                state["matches"]["m1"]["status"] = "completed"
                raise RuntimeError("boom")
        self.assertEqual(self.store.path.read_bytes(), before)
        self.assertEqual(self.match()["status"], "scheduled")

    def test_state_survives_a_new_store_object(self):
        self.create()
        self.run_job([PLATFORM, NORMAL_A])
        again = JsonFileStore(self.store.path)
        self.assertEqual(len(O.get_match(again, "m1")["attempts"]), 2)
        self.assertEqual(O.get_match(again, "m1")["status"], "completed")
        self.assertEqual([f.name for f in self.store.path.parent.iterdir() if f.suffix == ".tmp"], [])


class HostLock(unittest.TestCase):
    def test_second_holder_times_out_then_succeeds_after_release(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "host.lock"
            with O.host_lock(p, timeout=1):
                with self.assertRaises(TimeoutError):
                    with O.host_lock(p, timeout=0.2, poll=0.05):
                        pass
            with O.host_lock(p, timeout=1):
                pass


@unittest.skipUnless(os.environ.get("BIO_INTEGRATION") == "1", "set BIO_INTEGRATION=1 to play real matches")
class RealMatches(unittest.TestCase):
    """The orchestrator driving the real launcher, sandbox and engine."""

    def setUp(self):
        from backend.match_runner import launcher as L
        self.L = L
        lock = L.load_lock()
        self.py = L.resolve_python(None, None, lock)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.store = JsonFileStore(self.root / "state.json")
        self.tests_bots = Path(L.__file__).resolve().parent / "tests" / "bots"
        # one folder per submission version, as the orchestrator expects
        self.bots = self.root / "bots"
        self.bots.mkdir()
        import shutil
        shutil.copytree(L.DEFAULT_SCAFFOLD / "src" / "examplefuncsplayer_py", self.bots / "sub-good-v1")
        shutil.copytree(self.tests_bots / "crash_py", self.bots / "sub-crash-v1")

    def run_fn(self):
        return O.launcher_run_fn(self.L.DEFAULT_SCAFFOLD, self.py, self.bots, self.root / "out", timeout=120,
                                 lock_path=self.root / "host.lock")

    def test_real_match_completes_and_a_repeat_does_not_play_again(self):
        O.create_match(self.store, "real-1", "team-a", "team-b", "DefaultSmall", "sub-good-v1", "sub-good-v1")
        out = O.run_match_job(self.store, "real-1", self.run_fn(), owner="w1", sleep=lambda s: None)
        self.assertEqual((out["status"], out["ran"]), ("completed", 1))
        m = O.get_match(self.store, "real-1")
        self.assertIn(m["result"]["winner_side"], ("A", "B"))
        self.assertTrue(Path(m["result"]["replay"]).exists())
        self.assertTrue(Path(m["result"]["structured_log"]).exists())
        again = O.run_match_job(self.store, "real-1", self.run_fn(), owner="w2", sleep=lambda s: None)
        self.assertEqual((again["ran"], again["skipped"]), (0, "already_completed"))
        self.assertIsNotNone(O.take_advancement(self.store, "real-1"))
        self.assertIsNone(O.take_advancement(self.store, "real-1"))

    def test_real_bot_crash_is_a_forfeit_and_not_retried(self):
        O.create_match(self.store, "real-2", "team-a", "team-b", "DefaultSmall", "sub-good-v1", "sub-crash-v1")
        out = O.run_match_job(self.store, "real-2", self.run_fn(), owner="w1", sleep=lambda s: None)
        self.assertEqual((out["status"], out["ran"]), ("completed", 1))
        m = O.get_match(self.store, "real-2")
        self.assertEqual((m["result"]["result_type"], m["result"]["winner_team"]), ("bot_forfeit", "team-a"))

    def test_real_retry_after_a_platform_failure_uses_the_same_bots_and_map(self):
        O.create_match(self.store, "real-3", "team-a", "team-b", "DefaultSmall", "sub-good-v1", "sub-good-v1")
        real = self.run_fn()
        seen = []

        def flaky(ctx):
            seen.append(ctx)
            if ctx.attempt == 1:
                return {"outcome": "platform_failure", "kind": "injected", "detail": "test"}
            return real(ctx)
        out = O.run_match_job(self.store, "real-3", flaky, owner="w1", sleep=lambda s: None)
        self.assertEqual((out["status"], out["ran"]), ("completed", 2))
        self.assertEqual({(c.map, c.submission_a, c.submission_b) for c in seen}, {("DefaultSmall", "sub-good-v1", "sub-good-v1")})
        m = O.get_match(self.store, "real-3")
        self.assertEqual([a["status"] for a in m["attempts"]], ["platform_failed", "completed"])

    def test_missing_bot_folder_pauses_the_match_at_once(self):
        O.create_match(self.store, "real-4", "team-a", "team-b", "DefaultSmall", "sub-good-v1", "sub-missing-v9")
        out = O.run_match_job(self.store, "real-4", self.run_fn(), owner="w1", sleep=lambda s: None)
        self.assertEqual((out["status"], out["ran"]), ("paused", 1))
        self.assertEqual(self.store.snapshot()["incidents"][0]["incident_type"], "configuration_error")


if __name__ == "__main__":
    unittest.main()
