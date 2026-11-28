# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for the flow between upload, queue, pins, bracket and round (BIO-EPIC-03; CN-018).

Unit tests use the real registry, queue, bracket and replay vault with fake checks and fake games and a fake
clock. The last class starts the worker program as its own process and plays real sandboxed matches; it needs
`BIO_INTEGRATION=1`.

    python3 -m unittest backend.tournament_flow.tests.test_flow -v
"""
import gzip
import hashlib
import json
import os
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.match_orchestrator import bracket as B
from backend.match_orchestrator import maps as M
from backend.match_orchestrator import orchestrator as O
from backend.match_orchestrator import replays as P
from backend.match_orchestrator.store import JsonFileStore
from backend.match_orchestrator.tests.test_maps import ENGINE, FILES, GOOD as POOL, make_jar
from backend.match_orchestrator.tests.test_tiebreak import DECISIVE
from backend.submission_registry import registry as R
from backend.tournament_flow import flow as F
from backend.work_queue import handlers as H
from backend.work_queue import jobs as J
from backend.work_queue.tests.test_handlers import GOOD as BOT, verdict
from backend.work_queue.tests.test_jobs import Clock
from backend.work_queue.worker import Worker

DEADLINE = 2_000_000.0
REPO = Path(__file__).resolve().parents[3]


def captain(team):
    return R.Actor(f"cap-{team}", "participant", frozenset({team}), frozenset({team}))


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._unlock)
        self.clock = Clock(DEADLINE - 100_000)
        self.flow = F.Flow(R.Registry(self.dir / "subs", self.dir / "registry.json"),
                           JsonFileStore(self.dir / "matches.json"),
                           J.JobQueue(self.dir / "queue.json", max_attempts=2, backoff=lambda n: 10.0))
        self.alerts = []

    def _unlock(self):
        for p in (self.dir / "subs").glob("*"):
            if p.is_dir() and not p.is_symlink():
                os.chmod(p, 0o700)

    def up(self, team, data=BOT, key="k1", name="bot.py", **kw):
        return F.upload(self.flow, captain(team), team, "t1", name, data, idempotency_key=key,
                        deadline_at=DEADLINE, now=self.clock, **kw)

    def worker(self, **handlers):
        return Worker(self.flow.queue, handlers, name="w1", now=self.clock, renew_every=3600, alert=self.alerts.append)

    def check_all(self, answers=None):
        """Run the queued checks with a fake trial; `answers` maps submission id -> verdict status."""
        answers = answers or {}

        def check(folder):
            return verdict((folder / "bot.py").read_bytes(), answers.get(folder.name, "valid"))
        return self.worker(**{J.CHECK_SUBMISSION: H.check_submission_handler(self.flow.registry, check,
                                                                              now=self.clock)}).run_until_idle()

    def snap(self):
        return self.flow.registry.store.snapshot()


class Uploads(Base):
    def test_an_upload_stores_the_version_and_queues_exactly_one_check(self):
        view = self.up("ta")
        self.assertEqual((view["id"], view["validation_status"]), ("ta-v1", "validating"))
        self.assertEqual([(j["kind"], j["payload"], j["status"]) for j in J.list_jobs(self.flow.queue)],
                         [(J.CHECK_SUBMISSION, {"submission_id": "ta-v1"}, "queued")])
        self.assertEqual(view["check_job"], "j1")

    def test_a_repeated_upload_returns_the_same_version_and_the_same_job(self):
        a, b = self.up("ta"), self.up("ta")
        self.assertEqual((a["id"], a["check_job"]), (b["id"], b["check_job"]))
        self.assertEqual(len(J.list_jobs(self.flow.queue)), 1)

    def test_an_upload_that_died_before_queueing_is_queued_by_the_retry(self):
        R.submit(self.flow.registry, captain("ta"), "ta", "t1", "bot.py", BOT, idempotency_key="k1",
                 deadline_at=DEADLINE, now=self.clock)            # the first call stopped here
        self.assertEqual(J.list_jobs(self.flow.queue), [])
        self.assertEqual(self.up("ta")["check_job"], "j1")

    def test_a_version_that_fails_the_static_check_needs_no_job(self):
        view = self.up("ta", b"print('no turn function')\n")
        self.assertEqual((view["validation_status"], view["check_job"]), ("invalid", None))
        self.assertEqual(J.list_jobs(self.flow.queue), [])

    def test_a_refused_upload_queues_nothing(self):
        with self.assertRaises(R.NotFound):
            F.upload(self.flow, captain("tb"), "ta", "t1", "bot.py", BOT, idempotency_key="k", deadline_at=DEADLINE, now=self.clock)
        with self.assertRaises(R.DeadlineClosed):
            F.upload(self.flow, captain("ta"), "ta", "t1", "bot.py", BOT, idempotency_key="k", deadline_at=self.clock(), now=self.clock)
        self.assertEqual(J.list_jobs(self.flow.queue), [])


class Sweep(Base):
    def test_a_version_without_a_job_is_queued_and_one_with_a_job_is_not(self):
        self.up("ta")
        R.submit(self.flow.registry, captain("tb"), "tb", "t1", "bot.py", BOT, idempotency_key="k1",
                 deadline_at=DEADLINE, now=self.clock)            # no job for tb
        out = F.sweep_checks(self.flow, now=self.clock)
        self.assertEqual(len(out["queued"]), 1)
        self.assertEqual(sorted(j["payload"]["submission_id"] for j in J.list_jobs(self.flow.queue)), ["ta-v1", "tb-v1"])
        self.assertEqual(F.sweep_checks(self.flow, now=self.clock), {"queued": [], "left_dead": []})

    def test_a_checked_version_is_left_alone(self):
        self.up("ta")
        self.check_all()
        self.assertEqual(F.sweep_checks(self.flow, now=self.clock), {"queued": [], "left_dead": []})

    def test_a_dead_job_is_not_queued_again_by_the_sweep(self):
        self.up("ta")
        self.check_all({"ta-v1": "inconclusive"})                 # failure 1 of 2
        self.clock.t += 100
        self.check_all({"ta-v1": "inconclusive"})                 # failure 2: dead
        self.assertEqual(J.stats(self.flow.queue)["dead"], 1)
        out = F.sweep_checks(self.flow, now=self.clock)
        self.assertEqual(out, {"queued": [], "left_dead": ["ta-v1"]})
        self.assertEqual(len(J.list_jobs(self.flow.queue)), 1)

    def test_an_inconclusive_version_with_no_job_is_queued(self):
        R.submit(self.flow.registry, captain("ta"), "ta", "t1", "bot.py", BOT, idempotency_key="k1",
                 deadline_at=DEADLINE, now=self.clock)
        claim = R.claim_check(self.flow.registry, "ta-v1", now=self.clock)
        R.record_verdict(self.flow.registry, claim, verdict(BOT, "inconclusive"), now=self.clock)
        self.assertEqual(self.snap()["submissions"]["ta-v1"]["validation_status"], "inconclusive")
        self.assertEqual(len(F.sweep_checks(self.flow, now=self.clock)["queued"]), 1)


class BracketBase(Base):
    def setUp(self):
        super().setUp()
        self.jar = make_jar(self.dir / "engine.jar", FILES)
        self.catalogue = M.load_engine_maps(self.jar)
        M.create_pool(self.flow.store, "pool", self.catalogue, ENGINE, **POOL)

    def open(self, teams=("ta", "tb", "tc"), bracket_id="b1", **kw):
        return F.open_bracket(self.flow, "t1", bracket_id, list(teams), "pool", self.catalogue, ENGINE,
                              deadline_at=DEADLINE, now=self.clock, rng=random.Random(3), **kw)

    def ready(self, teams=("ta", "tb", "tc")):
        for t in teams:
            self.up(t)
        self.check_all()
        self.clock.t = DEADLINE + 1

    def play(self, bracket_id="b1", fail=None):
        games = []

        def run_fn(ctx):
            games.append(ctx.match_id)
            side = "A" if ctx.team_a < ctx.team_b else "B"
            return {"outcome": "completed", "classification": "normal", "ok": True, "winner": side, "round": 300,
                    "reason": DECISIVE, "replay": None, "structured_log": {"path": "/x/l.jsonl", "events": 5}}
        w = self.worker(**{J.RUN_ROUND: H.run_round_handler(self.flow.store, fail or run_fn, alert=self.alerts.append,
                                                           now=self.clock, sleep=lambda s: None)})
        w.run_until_idle()
        return games


class Brackets(BracketBase):
    def test_nothing_is_pinned_or_drawn_before_the_deadline(self):
        self.ready()
        self.clock.t = DEADLINE - 1
        with self.assertRaises(R.Conflict):
            self.open()
        self.assertEqual(self.snap()["pins"], {})
        self.assertEqual(self.flow.store.snapshot().get("brackets", {}), {})

    def test_nothing_is_drawn_while_a_check_is_still_running(self):
        for t in ("ta", "tb"):
            self.up(t)
        self.check_all({})                                        # both valid
        self.up("ta", data=BOT + b"# v2\n", key="k2")             # a new version, not checked yet
        self.clock.t = DEADLINE + 1
        with self.assertRaises(R.PendingChecks):
            self.open(("ta", "tb"))
        self.assertEqual(self.flow.store.snapshot().get("brackets", {}), {})

    def test_the_bracket_is_drawn_with_exactly_the_pinned_versions_and_remembers_its_tournament(self):
        self.ready()
        out = self.open()
        b = out["bracket"]
        self.assertEqual(out["excluded"], [])
        self.assertEqual(b["teams"], [{"team": t, "submission": f"{t}-v1"} for t in ("ta", "tb", "tc")])
        self.assertEqual(b["tournament_id"], "t1")
        self.assertEqual(b["map_pool"], "pool")
        self.assertEqual(B.get_bracket(self.flow.store, "b1")["tournament_id"], "t1")

    def test_a_team_without_a_valid_bot_is_excluded_and_named(self):
        self.up("ta"), self.up("tb"), self.up("tc", b"nothing useful\n")
        self.check_all()
        self.clock.t = DEADLINE + 1
        out = self.open()
        self.assertEqual(out["excluded"], ["tc"])
        self.assertEqual([e["team"] for e in out["bracket"]["teams"]], ["ta", "tb"])

    def test_fewer_than_two_playable_teams_is_refused_and_draws_nothing(self):
        self.up("ta"), self.up("tb", b"nothing useful\n")
        self.check_all()
        self.clock.t = DEADLINE + 1
        with self.assertRaises(F.FlowError) as e:
            self.open(("ta", "tb"))
        self.assertIn("tb", str(e.exception))
        self.assertEqual(self.flow.store.snapshot().get("brackets", {}), {})
        self.assertEqual(self.snap()["pins"], {})                 # refused BEFORE the write-once pin

    def test_a_refused_draw_can_be_recovered_by_an_extension_and_a_new_bot(self):
        """The pin used to be written before the two-team check, so a tournament with one playable team could
        never be drawn again, even after the Admin extended the deadline and the second team uploaded."""
        self.up("ta"), self.up("tb", b"nothing useful\n")
        self.check_all()
        self.clock.t = DEADLINE + 1
        with self.assertRaises(F.FlowError):
            self.open(("ta", "tb"))
        later = DEADLINE + 5_000                                  # an Admin extension: a later deadline
        F.upload(self.flow, captain("tb"), "tb", "t1", "bot.py", BOT, idempotency_key="k2", deadline_at=later, now=self.clock)
        self.check_all()
        self.clock.t = later + 1
        out = F.open_bracket(self.flow, "t1", "b1", ["ta", "tb"], "pool", self.catalogue, ENGINE,
                             deadline_at=later, now=self.clock, rng=random.Random(3))
        self.assertEqual([e["team"] for e in out["bracket"]["teams"]], ["ta", "tb"])

    def test_a_team_whose_only_version_is_unchecked_is_pending_not_missing(self):
        """One active team and one still being checked is 'wait', not 'too few teams': the check may yet pass."""
        self.up("ta")
        self.check_all()
        self.up("tb")                                             # validating, never checked
        self.clock.t = DEADLINE + 1
        with self.assertRaises(R.PendingChecks):
            self.open(("ta", "tb"))
        self.assertEqual(self.snap()["pins"], {})

    def test_an_unfinished_check_is_reported_as_pending_not_as_too_few_teams(self):
        self.up("ta"), self.up("tb")
        self.check_all()
        self.up("tb", b"def turn():\n    z = 3\n", key="k2")      # tb's newest version is unchecked
        self.clock.t = DEADLINE + 1
        with self.assertRaises(R.PendingChecks):
            self.open(("ta", "tb"))

    def test_a_repeated_call_returns_the_same_draw_and_a_later_upload_changes_nothing(self):
        self.ready()
        first = self.open()["bracket"]
        with self.assertRaises(R.DeadlineClosed):                 # the deadline has passed: no new version
            self.up("ta", data=BOT + b"# v2\n", key="k2")
        again = self.open()["bracket"]
        self.assertEqual(first["draw"], again["draw"])
        self.assertEqual(first["teams"], again["teams"])

    def test_the_same_teams_in_another_order_ask_for_the_same_draw(self):
        self.ready()
        first = self.open(("ta", "tb", "tc"))["bracket"]
        again = self.open(("tc", "ta", "tb"))["bracket"]
        self.assertEqual(first["draw"]["id"], again["draw"]["id"])

    def test_a_bracket_cannot_be_taken_over_by_another_tournament(self):
        self.ready()
        self.open()
        with self.flow.store.transaction() as state:
            state["brackets"]["b1"]["tournament_id"] = "other"
        with self.assertRaises(F.FlowError):
            self.open()


class Rounds(BracketBase):
    def test_a_round_is_started_queued_and_played(self):
        self.ready(("ta", "tb"))
        self.open(("ta", "tb"))
        out = F.start_round(self.flow, "b1", 1, "org-1", now=self.clock)
        self.assertEqual(out["round"]["status"], "running")
        self.assertIsNotNone(out["job"])
        self.assertEqual(len(self.play()), 1)
        b = B.get_bracket(self.flow.store, "b1")
        self.assertEqual((b["status"], b["champion"]), ("completed", "ta"))

    def test_starting_a_round_twice_queues_one_job(self):
        self.ready(("ta", "tb"))
        self.open(("ta", "tb"))
        a = F.start_round(self.flow, "b1", 1, "org-1", now=self.clock)
        b = F.start_round(self.flow, "b1", 1, "org-1", now=self.clock)
        self.assertEqual(a["job"], b["job"])
        self.assertEqual(len(J.list_jobs(self.flow.queue, J.QUEUED)), 1)

    def test_a_completed_round_is_not_queued_again(self):
        self.ready(("ta", "tb"))
        self.open(("ta", "tb"))
        F.start_round(self.flow, "b1", 1, "org-1", now=self.clock)
        self.play()
        out = F.start_round(self.flow, "b1", 1, "org-1", now=self.clock)
        self.assertIsNone(out["job"])
        self.assertEqual(J.list_jobs(self.flow.queue, J.QUEUED), [])

    def test_a_bot_file_changed_since_upload_stops_the_round_before_it_starts(self):
        self.ready(("ta", "tb"))
        self.open(("ta", "tb"))
        path = self.dir / "subs" / "tb-v1"
        os.chmod(path, 0o700)
        os.chmod(path / "bot.py", 0o600)
        (path / "bot.py").write_bytes(b"def turn():\n    pass  # changed\n")
        with self.assertRaises(F.FlowError):
            F.start_round(self.flow, "b1", 1, "org-1", now=self.clock)
        self.assertEqual(B.get_bracket(self.flow.store, "b1")["rounds"][0]["status"], "ready")
        self.assertEqual(J.list_jobs(self.flow.queue, J.QUEUED), [])
        self.assertEqual([i["kind"] for i in self.snap()["incidents"]], ["submission_file_damaged"])

    def test_a_bracket_not_drawn_from_pins_is_refused(self):
        B.create_bracket(self.flow.store, "loose", [{"team": "ta", "submission": "ta-v1"}, {"team": "tb", "submission": "tb-v1"}],
                         {"play": ["P"], "tiebreak_normal": ["N"], "tiebreak_final": ["F1", "F2", "F3"]})
        with self.assertRaises(F.FlowError) as e:
            F.start_round(self.flow, "loose", 1, "org-1", now=self.clock)
        self.assertIn("no tournament", str(e.exception))

    def test_a_bracket_that_disagrees_with_the_pins_is_refused(self):
        self.ready(("ta", "tb"))
        self.open(("ta", "tb"))
        with self.flow.store.transaction() as state:
            state["brackets"]["b1"]["teams"][0]["submission"] = "ta-v9"
        with self.assertRaises(F.FlowError) as e:
            F.start_round(self.flow, "b1", 1, "org-1", now=self.clock)
        self.assertIn("ta-v9", str(e.exception))
        self.assertEqual(J.list_jobs(self.flow.queue, J.QUEUED), [])

    def test_a_round_cannot_start_before_the_previous_one_is_complete(self):
        self.ready()
        self.open()
        with self.assertRaises(B.BracketError):
            F.start_round(self.flow, "b1", 2, "org-1", now=self.clock)
        self.assertEqual(J.list_jobs(self.flow.queue, J.QUEUED), [])


class Upkeep(BracketBase):
    def vault(self):
        return P.Vault(self.dir / "vault", P.ReplayIndex(self.dir / "replays.json"))

    def finish_bracket_with_replay(self):
        self.ready(("ta", "tb"))
        self.open(("ta", "tb"))
        F.start_round(self.flow, "b1", 1, "org-1", now=self.clock)
        data = gzip.compress(b"replay bytes")
        src = self.dir / "r.bc26"
        src.write_bytes(data)
        sha = hashlib.sha256(data).hexdigest()

        def run_fn(ctx):
            return {"outcome": "completed", "classification": "normal", "ok": True, "winner": "A", "round": 300,
                    "reason": DECISIVE, "replay": str(src), "replay_sha256": sha,
                    "structured_log": {"path": "/x/l.jsonl", "events": 5}}
        self.play(fail=run_fn)
        return src

    def test_housekeeping_stores_the_replays_of_finished_games_once(self):
        self.finish_bracket_with_replay()
        vault = self.vault()
        first = F.housekeeping(self.flow, vault, now=self.clock)
        self.assertEqual(first["replays"], {"b1": {"stored": 1, "already_known": 0}})
        second = F.housekeeping(self.flow, vault, now=self.clock)
        self.assertEqual(second["replays"], {"b1": {"stored": 0, "already_known": 1}})
        self.assertEqual(second["purged"], [])

    def test_housekeeping_finishes_an_interrupted_archive_and_does_not_collect_into_it(self):
        self.finish_bracket_with_replay()
        vault = self.vault()
        F.housekeeping(self.flow, vault, now=self.clock)
        with vault.index.transaction() as state:                   # a crash right after the archive was marked
            P._tournament(state, "t1", 0).update({"status": "archived", "archived_at": "x", "archived_by": "a"})
        self.assertTrue(any((vault.root / "t1").iterdir()))
        out = F.housekeeping(self.flow, vault, now=self.clock)
        self.assertEqual((out["purged"], out["archived_skipped"], out["replays"]), (["t1"], ["b1"], {}))
        self.assertFalse((vault.root / "t1").exists())

    def test_housekeeping_continues_when_archive_starts_during_collection(self):
        source = self.finish_bracket_with_replay()
        store = self.flow.store
        bracket = B.get_bracket(store, "b1")
        B.create_bracket(store, "b2", bracket["teams"], bracket["maps"])
        with store.transaction() as state:
            state["brackets"]["b2"]["tournament_id"] = "t2"
        vault = self.vault()
        original_check = P._sha256_and_check

        def start_archive_after_read(path, limit):
            result = original_check(path, limit)
            if path == source:
                with vault.index.transaction() as state:
                    P._tournament(state, "t1", self.clock()).update(
                        status=P.ARCHIVED, archived_at=P._iso(self.clock()), archived_by="a",
                    )
            return result

        before = store.snapshot()
        with patch.object(P, "_sha256_and_check", side_effect=start_archive_after_read):
            out = F.housekeeping(self.flow, vault, now=self.clock)
        self.assertEqual(out["archived_skipped"], ["b1"])
        self.assertEqual(out["replays"], {"b2": {"stored": 0, "already_known": 0}})
        self.assertEqual(out["purged"], ["t1"])
        self.assertFalse((vault.root / "t1").exists())
        self.assertEqual(vault.index.snapshot()["incidents"], [])
        self.assertEqual(store.snapshot(), before)

    def test_housekeeping_skips_brackets_without_a_tournament_and_needs_no_vault(self):
        B.create_bracket(self.flow.store, "loose", [{"team": "ta", "submission": "ta-v1"}, {"team": "tb", "submission": "tb-v1"}],
                         {"play": ["P"], "tiebreak_normal": ["N"], "tiebreak_final": ["F1", "F2", "F3"]})
        self.assertEqual(F.housekeeping(self.flow, self.vault(), now=self.clock)["replays"], {})
        self.assertNotIn("replays", F.housekeeping(self.flow, now=self.clock))

    def test_housekeeping_queues_the_unchecked_versions_it_finds(self):
        R.submit(self.flow.registry, captain("ta"), "ta", "t1", "bot.py", BOT, idempotency_key="k1",
                 deadline_at=DEADLINE, now=self.clock)
        self.assertEqual(len(F.housekeeping(self.flow, now=self.clock)["checks"]["queued"]), 1)


@unittest.skipUnless(os.environ.get("BIO_INTEGRATION") == "1", "set BIO_INTEGRATION=1 to play real games")
class RealFlow(unittest.TestCase):
    """The whole path with real files and a separate worker process: upload -> queued check (static + trial
    match) -> activation -> pins -> bracket drawn from the engine's real maps -> queued round -> real games."""

    def test_upload_to_champion(self):
        from backend.match_runner import launcher as L
        from backend.match_orchestrator.tests.test_tournament_e2e import ENGINE_JARS
        if not ENGINE_JARS:
            self.skipTest("engine jar not in the Gradle cache")
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            self.addCleanup(lambda: [os.chmod(p, 0o700) for p in (data / "submissions").glob("*") if p.is_dir()])
            flow = F.Flow(R.Registry(data / "submissions", data / "registry.json"), JsonFileStore(data / "matches.json"),
                          J.JobQueue(data / "queue.json"))
            src = (L.DEFAULT_SCAFFOLD / "src" / "examplefuncsplayer_py" / "bot.py").read_bytes()
            far = 4_000_000_000.0
            for team in ("ta", "tb"):
                view = F.upload(flow, captain(team), team, "t1", "bot.py", src, idempotency_key="k", deadline_at=far)
                self.assertIsNotNone(view["check_job"])

            def worker(*args):
                return subprocess.run([sys.executable, "-m", "backend.work_queue.service", "--data-dir", str(data), *args],
                                      cwd=REPO, capture_output=True, text=True, timeout=900)
            out = worker("run", "--once")
            self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
            self.assertEqual([s["is_active"] for s in flow.registry.store.snapshot()["submissions"].values()], [True, True])

            catalogue = M.load_engine_maps(ENGINE_JARS[0])
            M.create_pool(flow.store, "pool", catalogue, ENGINE, play=["DefaultSmall"], tiebreak_normal=["DefaultMedium"],
                          tiebreak_final=["jail", "pipes", "keepout"])
            opened = F.open_bracket(flow, "t1", "real", ["ta", "tb"], "pool", catalogue, ENGINE, deadline_at=1.0)
            self.assertEqual(opened["excluded"], [])
            started = F.start_round(flow, "real", 1, "org-1")
            self.assertIsNotNone(started["job"])
            out = worker("run", "--once")
            self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
            b = B.get_bracket(flow.store, "real")
            self.assertEqual(b["status"], "completed")
            self.assertIn(b["champion"], ("ta", "tb"))
            self.assertEqual(json.loads(worker("status").stdout)["counts"]["dead"], 0)


if __name__ == "__main__":
    unittest.main()
