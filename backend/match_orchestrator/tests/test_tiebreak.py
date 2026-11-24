# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for tie-break maps and the coin flip (BIO-304, TC-05, PRD 6.4, SCN-03).

Unit tests use a fake run function that answers per game map and always run. The last class plays real
matches and needs `BIO_INTEGRATION=1`.

    python3 -m unittest backend.match_orchestrator.tests.test_tiebreak -v
"""
import os
import tempfile
import threading
import unittest
from pathlib import Path

from backend.match_orchestrator import orchestrator as O
from backend.match_orchestrator import tiebreak as T
from backend.match_orchestrator.store import JsonFileStore

DECISIVE = "The winning team had more points at the end of the game."
BY_ROBOTS = "The winning team won on tiebreakers (more robots alive)."
COIN = T.ENGINE_COIN_FLIP_REASON


def won(side, reason=DECISIVE, round_=300):
    return {"outcome": "completed", "classification": "normal", "ok": True, "winner": side, "round": round_,
            "reason": reason, "replay": f"/x/{side}.bc26", "replay_sha256": "ab" * 32,
            "structured_log": {"path": "/x/l.jsonl", "events": 5}}


def crash(loser):
    return {"outcome": "bot_failure", "classification": "bot_crash", "kind": "runner_ended_connection",
            "loser": loser, "winner_by_forfeit": "B" if loser == "A" else "A", "detail": "ended"}


PLATFORM = {"outcome": "platform_failure", "classification": "platform_failure", "kind": "engine_failure",
            "detail": "engine ended first"}


class Clock:
    t = 1_800_000_000.0

    def __call__(self):
        return self.t


class Coin:
    """A scripted coin that records how often it was used."""

    def __init__(self, *sides):
        self.sides = list(sides)
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.sides.pop(0)


class Base(unittest.TestCase):
    MAPS1 = ["TieMap1"]
    MAPS3 = ["TieMap1", "TieMap2", "TieMap3"]

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = JsonFileStore(Path(self._tmp.name) / "state.json")
        self.clock = Clock()
        self.alerts = []

    def series(self, sid="s1", stage="normal", maps=None, **kw):
        maps = maps or (self.MAPS1 if stage == "normal" else self.MAPS3)
        return T.create_series(self.store, sid, "team-a", "team-b", "DefaultSmall", "sub-a-v3", "sub-b-v1",
                               stage, maps, now=self.clock, **kw)

    def play(self, script, sid="s1", coin=None, **kw):
        """`script` maps a map name to a list of answers, used in order. Returns (result, contexts)."""
        script = {k: list(v) for k, v in script.items()}
        calls = []

        def run_fn(ctx):
            calls.append(ctx)
            item = script[ctx.map].pop(0)
            if isinstance(item, BaseException):
                raise item
            return item
        out = T.run_series_job(self.store, sid, run_fn, owner=kw.pop("owner", "w1"), alert=self.alerts.append,
                               coin=coin, sleep=lambda s: None, now=self.clock, **kw)
        return out, calls

    def get(self, sid="s1"):
        return T.get_series(self.store, sid)


class Creation(Base):
    def test_create_is_idempotent_and_conflicts_are_refused(self):
        a = self.series()
        self.assertEqual(a, self.series())
        self.assertEqual((a["status"], len(a["games"]), a["games"][0]["map"]), ("scheduled", 1, "DefaultSmall"))
        with self.assertRaises(O.ConflictError):
            self.series(maps=["OtherMap"])
        with self.assertRaises(O.ConflictError):
            T.create_series(self.store, "s1", "team-a", "team-b", "DefaultSmall", "sub-a-v3", "sub-b-v1", "final", self.MAPS3)

    def test_the_number_of_tiebreak_maps_is_fixed_by_the_stage(self):
        for stage, maps in (("normal", []), ("normal", self.MAPS3), ("final", self.MAPS1), ("final", ["a", "b"]),
                            ("semi", self.MAPS1), ("normal", ["bad map name!"]), ("normal", "TieMap1"), ("final", None)):
            with self.subTest(stage=stage, maps=maps), self.assertRaises(T.SeriesError):
                T.create_series(self.store, "sx", "team-a", "team-b", "DefaultSmall", "sub-a-v3", "sub-b-v1", stage, maps)

    def test_bad_ids_are_refused_and_nothing_is_stored(self):
        for sid in ("", "x" * 57, "has space", None):
            with self.subTest(sid=sid), self.assertRaises(T.SeriesError):
                T.create_series(self.store, sid, "team-a", "team-b", "DefaultSmall", "sub-a-v3", "sub-b-v1", "normal", self.MAPS1)
        with self.assertRaises(O.OrchestratorError):
            T.create_series(self.store, "sbad", "team a", "team-b", "DefaultSmall", "sub-a-v3", "sub-b-v1", "normal", self.MAPS1)
        snap = self.store.snapshot()
        self.assertEqual((snap["matches"], snap.get("series", {})), ({}, {}))

    def test_a_series_does_not_collide_with_a_standalone_match_of_its_game_id(self):
        O.create_match(self.store, "s1-g0", "team-a", "team-b", "OtherMap", "sub-a-v3", "sub-b-v1")
        with self.assertRaises(O.ConflictError):
            self.series()


class NoTie(Base):
    def test_a_decided_first_game_ends_the_series_without_tiebreak_maps(self):
        self.series()
        out, calls = self.play({"DefaultSmall": [won("B")]})
        self.assertEqual((out["status"], out["ran"], len(calls)), ("completed", 1, 1))
        s = self.get()
        self.assertEqual((s["result"]["result_type"], s["result"]["winner_team"], s["result"]["decided_by_game"]),
                         ("normal", "team-b", 0))
        self.assertIsNone(s["coin_flip"])
        self.assertEqual(len(s["games"]), 1)

    def test_the_engines_own_ordered_tiebreakers_are_a_decision_not_a_tie(self):
        self.series()
        self.play({"DefaultSmall": [won("A", reason=BY_ROBOTS)]})
        self.assertEqual(self.get()["result"]["result_type"], "normal")

    def test_a_bot_failure_in_the_first_game_is_a_forfeit_and_nothing_more_is_played(self):
        self.series(stage="final")
        out, calls = self.play({"DefaultSmall": [crash("B")]})
        s = self.get()
        self.assertEqual((s["result"]["result_type"], s["result"]["winner_team"], len(calls)), ("bot_forfeit", "team-a", 1))
        self.assertEqual(len(s["games"]), 1)


class NormalStageTie(Base):
    def test_one_tiebreak_map_decides_and_the_engines_coin_flip_pick_is_ignored(self):
        self.series()
        coin = Coin()
        # the engine picked B by its unseeded coin flip; the tie-break map says A
        out, calls = self.play({"DefaultSmall": [won("B", COIN)], "TieMap1": [won("A")]}, coin=coin)
        self.assertEqual((out["status"], [c.map for c in calls]), ("completed", ["DefaultSmall", "TieMap1"]))
        s = self.get()
        self.assertEqual((s["result"]["result_type"], s["result"]["winner_team"]), ("tiebreak", "team-a"))
        self.assertEqual((s["games"][0]["outcome"], s["games"][0]["winner_side"], s["games"][0]["engine_pick_ignored"]),
                         (T.TIED, None, "B"))
        self.assertEqual(coin.calls, 0)
        self.assertIsNone(s["coin_flip"])

    def test_still_tied_after_the_one_tiebreak_map_the_coin_flip_decides_once(self):
        self.series()
        coin = Coin("B")
        out, calls = self.play({"DefaultSmall": [won("A", COIN)], "TieMap1": [won("A", COIN)]}, coin=coin)
        s = self.get()
        self.assertEqual((s["result"]["result_type"], s["result"]["winner_team"], coin.calls), ("coin_flip", "team-b", 1))
        cf = s["coin_flip"]
        self.assertEqual((cf["result_side"], cf["result_team"], cf["tied_between"], cf["rerolls_allowed"]),
                         ("B", "team-b", ["team-a", "team-b"], False))
        self.assertEqual(cf["games"], ["s1-g0", "s1-g1"])
        self.assertEqual(s["result"]["coin_flip_id"], cf["id"])
        self.assertIn("coin_flip", [h["event"] for h in s["history"]])

    def test_tiebreak_games_use_the_same_teams_and_submissions(self):
        self.series()
        _, calls = self.play({"DefaultSmall": [won("A", COIN)], "TieMap1": [won("B")]})
        self.assertEqual({(c.team_a, c.team_b, c.submission_a, c.submission_b) for c in calls},
                         {("team-a", "team-b", "sub-a-v3", "sub-b-v1")})
        self.assertEqual([c.match_id for c in calls], ["s1-g0", "s1-g1"])


class FinalStageTie(Base):
    def setUp(self):
        super().setUp()
        self.series(stage="final")

    def test_three_maps_are_played_in_order_and_the_majority_wins(self):
        coin = Coin()
        out, calls = self.play({"DefaultSmall": [won("A", COIN)], "TieMap1": [won("A")], "TieMap2": [won("B")],
                                "TieMap3": [won("A")]}, coin=coin)
        self.assertEqual([c.map for c in calls], ["DefaultSmall", "TieMap1", "TieMap2", "TieMap3"])
        s = self.get()
        self.assertEqual((s["result"]["result_type"], s["result"]["winner_team"], coin.calls), ("tiebreak", "team-a", 0))

    def test_all_three_are_played_even_when_two_already_decide_it(self):
        _, calls = self.play({"DefaultSmall": [won("A", COIN)], "TieMap1": [won("B")], "TieMap2": [won("B")],
                              "TieMap3": [won("A")]})
        self.assertEqual(len(calls), 4)
        self.assertEqual(self.get()["result"]["winner_team"], "team-b")

    def test_a_tied_tiebreak_map_counts_for_nobody(self):
        # A wins one, one map is tied again, B wins none: A has more map wins
        self.play({"DefaultSmall": [won("B", COIN)], "TieMap1": [won("A")], "TieMap2": [won("B", COIN)],
                   "TieMap3": [won("A", COIN)]})
        s = self.get()
        self.assertEqual((s["result"]["result_type"], s["result"]["winner_team"]), ("tiebreak", "team-a"))

    def test_one_win_each_and_a_tied_map_is_still_tied_so_the_coin_flips(self):
        coin = Coin("A")
        self.play({"DefaultSmall": [won("A", COIN)], "TieMap1": [won("A")], "TieMap2": [won("B")],
                   "TieMap3": [won("A", COIN)]}, coin=coin)
        s = self.get()
        self.assertEqual((s["result"]["result_type"], s["coin_flip"]["tiebreak_wins"], coin.calls),
                         ("coin_flip", {"A": 1, "B": 1}, 1))

    def test_every_map_tied_goes_to_the_coin_flip(self):
        coin = Coin("B")
        self.play({m: [won("A", COIN)] for m in ["DefaultSmall"] + self.MAPS3}, coin=coin)
        s = self.get()
        self.assertEqual((s["result"]["result_type"], s["result"]["winner_team"], coin.calls), ("coin_flip", "team-b", 1))
        self.assertEqual(len(s["games"]), 4)

    def test_a_bot_failure_in_a_tiebreak_game_forfeits_the_match_and_skips_the_rest(self):
        _, calls = self.play({"DefaultSmall": [won("A", COIN)], "TieMap1": [won("A")], "TieMap2": [crash("A")],
                              "TieMap3": []})
        s = self.get()
        self.assertEqual([c.map for c in calls], ["DefaultSmall", "TieMap1", "TieMap2"])
        self.assertEqual((s["result"]["result_type"], s["result"]["winner_team"], s["result"]["decided_by_game"]),
                         ("bot_forfeit", "team-b", 2))
        self.assertEqual(len(s["games"]), 3)


class PlatformFailures(Base):
    def test_a_platform_failure_in_a_tiebreak_game_is_retried_with_the_same_map_and_bots(self):
        self.series()
        out, calls = self.play({"DefaultSmall": [won("A", COIN)], "TieMap1": [PLATFORM, PLATFORM, won("B")]})
        self.assertEqual((out["status"], out["ran"]), ("completed", 4))
        tie_calls = [c for c in calls if c.match_id == "s1-g1"]
        self.assertEqual([c.attempt for c in tie_calls], [1, 2, 3])
        self.assertEqual({(c.map, c.submission_a, c.submission_b) for c in tie_calls}, {("TieMap1", "sub-a-v3", "sub-b-v1")})
        self.assertEqual(self.get()["result"]["winner_team"], "team-b")

    def test_the_cap_applies_per_game_and_pauses_the_series_with_an_incident_for_that_game(self):
        self.series(max_attempts=2)
        out, calls = self.play({"DefaultSmall": [PLATFORM, won("A", COIN)], "TieMap1": [PLATFORM, PLATFORM]})
        self.assertEqual(out["status"], "paused")
        s = self.get()
        self.assertEqual(s["status"], "paused")
        self.assertIsNone(s["result"])
        inc = self.store.snapshot()["incidents"]
        self.assertEqual([(i["incident_type"], i["match_id"]) for i in inc], [("retry_cap_reached", "s1-g1")])
        self.assertEqual(len(self.alerts), 1)

    def test_resuming_the_paused_game_lets_the_series_finish(self):
        self.series(max_attempts=1)
        self.play({"DefaultSmall": [won("A", COIN)], "TieMap1": [PLATFORM]})
        self.assertEqual(self.get()["status"], "paused")
        O.resume_paused(self.store, "s1-g1", "admin-1", 1, now=self.clock)
        out, calls = self.play({"TieMap1": [won("A")]})
        self.assertEqual((out["status"], [c.map for c in calls]), ("completed", ["TieMap1"]))
        self.assertEqual(self.get()["result"]["winner_team"], "team-a")

    def test_a_completed_game_without_the_engine_reason_is_retried_not_guessed(self):
        self.series()
        no_reason = won("A")
        del no_reason["reason"]
        out, calls = self.play({"DefaultSmall": [no_reason, won("A")]})
        self.assertEqual((out["status"], out["ran"]), ("completed", 2))
        g0 = O.get_match(self.store, "s1-g0")
        self.assertEqual(g0["attempts"][0]["failure_reason"], "missing_reason")

    def test_a_standalone_match_still_accepts_a_result_without_a_reason(self):
        O.create_match(self.store, "plain", "team-a", "team-b", "DefaultSmall", "sub-a-v3", "sub-b-v1", now=self.clock)
        r = won("A")
        del r["reason"]
        out = O.run_match_job(self.store, "plain", lambda ctx: r, owner="w", sleep=lambda s: None, now=self.clock)
        self.assertEqual(out["status"], "completed")


class ExactlyOnce(Base):
    def test_a_finished_series_is_never_played_again_and_advances_once(self):
        self.series()
        self.play({"DefaultSmall": [won("A", COIN)], "TieMap1": [won("A", COIN)]}, coin=Coin("A"))
        out, calls = self.play({}, owner="w2", coin=Coin())       # an empty script: any game played would raise
        self.assertEqual((out["status"], out["ran"], calls), ("completed", 0, []))
        first = T.take_series_advancement(self.store, "s1", self.clock)
        self.assertEqual(first["winner_team"], "team-a")
        self.assertIsNone(T.take_series_advancement(self.store, "s1", self.clock))

    def test_no_advancement_before_the_series_is_finished(self):
        self.series()
        self.assertIsNone(T.take_series_advancement(self.store, "s1"))
        self.play({"DefaultSmall": [won("A", COIN)], "TieMap1": [PLATFORM] * 10})   # paused at the cap, not finished
        self.assertIsNone(T.take_series_advancement(self.store, "s1"))

    def test_a_game_of_a_series_is_never_handed_to_bracket_advancement_on_its_own(self):
        self.series()
        self.play({"DefaultSmall": [won("A")]})
        self.assertIsNone(O.take_advancement(self.store, "s1-g0"))
        self.assertIsNotNone(T.take_series_advancement(self.store, "s1"))

    def test_the_coin_is_never_drawn_again_by_a_repeat_or_a_second_worker(self):
        self.series()
        coin = Coin("A", "B", "B")
        self.play({"DefaultSmall": [won("A", COIN)], "TieMap1": [won("B", COIN)]}, coin=coin)
        before = self.get()["coin_flip"]
        for _ in range(3):
            T.advance_series(self.store, "s1", coin=coin, now=self.clock)
            self.play({}, coin=coin, owner="w2")
        self.assertEqual((self.get()["coin_flip"], coin.calls), (before, 1))

    def test_two_workers_racing_for_the_decision_draw_one_coin(self):
        self.series()
        # play both games first without letting the series settle: use a coin that must be called once
        coin = Coin("A", "B", "B", "B")
        barrier = threading.Barrier(4)
        results = []

        def go():
            barrier.wait()
            results.append(T.run_series_job(self.store, "s1", lambda ctx: won("A", COIN), owner=threading.current_thread().name,
                                            coin=coin, sleep=lambda s: None, now=self.clock))
        threads = [threading.Thread(target=go, name=f"w{i}") for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        s = self.get()
        self.assertEqual((s["status"], coin.calls), ("completed", 1))
        self.assertEqual(sum(1 for h in s["history"] if h["event"] == "coin_flip"), 1)
        self.assertEqual(s["result"]["winner_side"], s["coin_flip"]["result_side"])

    def test_a_bad_coin_function_records_nothing_and_can_be_retried(self):
        self.series()
        with self.assertRaises(T.SeriesError):
            self.play({"DefaultSmall": [won("A", COIN)], "TieMap1": [won("A", COIN)]}, coin=lambda: "heads")
        s = self.get()
        self.assertIsNone(s["coin_flip"])
        self.assertNotEqual(s["status"], "completed")
        self.play({}, coin=Coin("A"))
        s = self.get()
        self.assertEqual((s["status"], s["result"]["winner_team"]), ("completed", "team-a"))

    def test_the_default_coin_is_fair_enough_and_only_returns_a_or_b(self):
        draws = [T.default_coin() for _ in range(400)]
        self.assertEqual(set(draws), {"A", "B"})
        self.assertTrue(120 < draws.count("A") < 280)     # a loose sanity bound, not a statistical test


class PublicView(Base):
    def test_the_public_view_shows_the_coin_flip_and_no_host_details(self):
        self.series(stage="final")
        self.play({m: [won("A", COIN)] for m in ["DefaultSmall"] + self.MAPS3}, coin=Coin("B"))
        view = T.public_view(self.get())
        self.assertEqual((view["result"]["result_type"], view["result"]["winner_team"]), ("coin_flip", "team-b"))
        self.assertEqual(view["coin_flip"]["result_team"], "team-b")
        self.assertEqual(len(view["games"]), 4)
        text = repr(view)
        for leaked in ("/x/", "sha256", "structured_log", "sub-a-v3", "engine_pick", "ab" * 8):
            self.assertNotIn(leaked, text)
        self.assertTrue(all(g["has_replay"] for g in view["games"]))


@unittest.skipUnless(os.environ.get("BIO_INTEGRATION") == "1", "set BIO_INTEGRATION=1 to play real matches")
class RealSeries(unittest.TestCase):
    def setUp(self):
        import shutil
        from backend.match_runner import launcher as L
        self.L = L
        self.py = L.resolve_python(None, None, L.load_lock())
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.store = JsonFileStore(self.root / "state.json")
        self.bots = self.root / "bots"
        self.bots.mkdir()
        shutil.copytree(L.DEFAULT_SCAFFOLD / "src" / "examplefuncsplayer_py", self.bots / "sub-good-v1")
        shutil.copytree(Path(L.__file__).resolve().parent / "tests" / "bots" / "crash_py", self.bots / "sub-crash-v1")

    def run_fn(self):
        return O.launcher_run_fn(self.L.DEFAULT_SCAFFOLD, self.py, self.bots, self.root / "out", timeout=120,
                                 lock_path=self.root / "host.lock")

    def test_real_series_finishes_with_a_consistent_result(self):
        T.create_series(self.store, "real-s1", "team-a", "team-b", "DefaultSmall", "sub-good-v1", "sub-good-v1",
                        "normal", ["DefaultSmall"])
        out = T.run_series_job(self.store, "real-s1", self.run_fn(), owner="w1", sleep=lambda s: None)
        self.assertEqual(out["status"], "completed")
        s = T.get_series(self.store, "real-s1")
        self.assertIn(s["result"]["result_type"], T.RESULT_TYPES)
        self.assertIn(s["result"]["winner_side"], ("A", "B"))
        for g in s["games"]:
            self.assertIn(g["outcome"], (T.DECIDED, T.TIED))
            self.assertTrue(Path(g["replay"]).exists())
        # the series result follows from the games, whatever the engine did
        if s["games"][0]["outcome"] == T.DECIDED:
            self.assertEqual((s["result"]["result_type"], len(s["games"])), ("normal", 1))
        else:
            self.assertGreaterEqual(len(s["games"]), 2)
        self.assertIsNotNone(T.take_series_advancement(self.store, "real-s1"))

    def test_real_final_with_identical_bots_ties_every_game_and_ends_in_one_coin_flip(self):
        # Observed with the example bot against itself on DefaultSmall: the engine ends in round 1310 by its own
        # coin flip every time (the position is symmetric), so this exercises the whole final-stage path for real.
        T.create_series(self.store, "real-s3", "team-a", "team-b", "DefaultSmall", "sub-good-v1", "sub-good-v1",
                        "final", ["DefaultSmall"] * 3)
        T.run_series_job(self.store, "real-s3", self.run_fn(), owner="w1", sleep=lambda s: None)
        s = T.get_series(self.store, "real-s3")
        self.assertEqual([g["outcome"] for g in s["games"]], [T.TIED] * 4)
        self.assertEqual((s["result"]["result_type"], s["result"]["coin_flip_id"] == s["coin_flip"]["id"]), ("coin_flip", True))
        self.assertEqual(s["result"]["winner_side"], s["coin_flip"]["result_side"])

    def test_real_bot_crash_in_a_series_is_a_forfeit(self):
        T.create_series(self.store, "real-s2", "team-a", "team-b", "DefaultSmall", "sub-good-v1", "sub-crash-v1",
                        "final", ["DefaultSmall", "DefaultSmall", "DefaultSmall"])
        T.run_series_job(self.store, "real-s2", self.run_fn(), owner="w1", sleep=lambda s: None)
        s = T.get_series(self.store, "real-s2")
        self.assertEqual((s["result"]["result_type"], s["result"]["winner_team"], len(s["games"])), ("bot_forfeit", "team-a", 1))


if __name__ == "__main__":
    unittest.main()
