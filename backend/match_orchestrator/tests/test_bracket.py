# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for the bracket, byes and the round runner (BIO-302/303, TC-05, FLOW-05; CN-011).

Unit tests use a fake run function (the lower team name always wins unless a test says otherwise).
The last class plays real matches and needs `BIO_INTEGRATION=1`.

    python3 -m unittest backend.match_orchestrator.tests.test_bracket -v
"""
import os
import random
import tempfile
import threading
import unittest
from pathlib import Path

from backend.match_orchestrator import bracket as B
from backend.match_orchestrator import orchestrator as O
from backend.match_orchestrator import tiebreak as T
from backend.match_orchestrator.store import JsonFileStore
from backend.match_orchestrator.tests.test_tiebreak import COIN, DECISIVE, PLATFORM, crash, won

MAPS = {"play": ["PlayA", "PlayB"], "tiebreak_normal": ["TieN"], "tiebreak_final": ["TieF1", "TieF2", "TieF3"]}


def teams(n):
    return [{"team": f"team-{i:02d}", "submission": f"sub-{i:02d}-v1"} for i in range(1, n + 1)]


def lower_wins(ctx):
    return won("A" if ctx.team_a < ctx.team_b else "B")


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = JsonFileStore(Path(self._tmp.name) / "state.json")
        self.alerts = []

    def make(self, n, bid="b1", seed=1, **kw):
        return B.create_bracket(self.store, bid, teams(n), MAPS, rng=random.Random(seed), **kw)

    def play_all(self, bid="b1", run_fn=lower_wins, coin=None, **kw):
        b = B.get_bracket(self.store, bid)
        for r in range(1, len(b["rounds"]) + 1):
            B.start_round(self.store, bid, r, "org-1")
            out = B.run_round(self.store, bid, r, run_fn, owner="w1", alert=self.alerts.append, coin=coin,
                              sleep=lambda s: None, **kw)
            if out["status"] != "completed":
                return out
        return B.get_bracket(self.store, bid)

    def get(self, bid="b1"):
        return B.get_bracket(self.store, bid)


class Draw(Base):
    def test_shape_for_many_sizes(self):
        for n in (2, 3, 4, 5, 6, 7, 8, 9, 13, 16, 17, 31, 33):
            with self.subTest(n=n):
                b = self.make(n, bid=f"b{n}")
                size = 1
                while size < n:
                    size *= 2
                self.assertEqual((b["size"], b["draw"]["byes"]), (size, size - n))
                r1 = b["rounds"][0]["matches"]
                self.assertEqual(len(r1), size // 2)
                self.assertEqual(sum(m["bye"] for m in r1), size - n)
                # no pair of byes, nobody twice, everybody once
                self.assertTrue(all(m["a"] is not None for m in r1))
                seen = [t for m in r1 for t in (m["a"], m["b"]) if t]
                self.assertEqual(sorted(seen), sorted(t["team"] for t in teams(n)))
                self.assertEqual([len(r["matches"]) for r in b["rounds"]], [size // 2 // (2 ** i) for i in range(len(b["rounds"]))])
                self.assertEqual(b["rounds"][0]["status"], "ready")
                self.assertTrue(all(r["status"] == "pending" for r in b["rounds"][1:]))
                for r in b["rounds"][1:]:
                    self.assertFalse(any(m["bye"] for m in r["matches"]))

    def test_byes_go_to_human_teams_only_in_round_one_and_are_already_advanced(self):
        b = self.make(5)
        byes = [m for m in b["rounds"][0]["matches"] if m["bye"]]
        self.assertEqual(len(byes), 3)
        self.assertTrue(all(m["winner"] == m["a"] and m["result_type"] == "bye" and m["series_id"] is None for m in byes))

    def test_bye_places_and_pairings_vary_with_the_draw(self):
        places = set()
        firsts = set()
        for seed in range(30):
            b = B.create_bracket(self.store, f"v{seed}", teams(5), MAPS, rng=random.Random(seed))
            places.add(tuple(m["bye"] for m in b["rounds"][0]["matches"]))
            firsts.add(b["rounds"][0]["matches"][0]["a"])
        self.assertGreater(len(places), 3)
        self.assertGreater(len(firsts), 3)

    def test_the_draw_is_random_but_recorded_once_and_a_repeat_does_not_redraw(self):
        a = B.create_bracket(self.store, "bd", teams(8), MAPS, rng=random.Random(1))
        again = B.create_bracket(self.store, "bd", teams(8), MAPS, rng=random.Random(2))
        self.assertEqual(a, again)
        self.assertFalse(again["draw"]["rerolls_allowed"])
        other = B.create_bracket(self.store, "be", teams(8), MAPS, rng=random.Random(2))
        self.assertNotEqual(a["draw"]["pairings"], other["draw"]["pairings"])
        sys_rng = B.create_bracket(self.store, "bf", teams(8), MAPS)
        self.assertEqual(sys_rng["draw"]["method"], "random.SystemRandom shuffle")

    def test_conflicting_recreate_is_refused(self):
        self.make(4)
        with self.assertRaises(O.ConflictError):
            B.create_bracket(self.store, "b1", teams(5), MAPS)
        with self.assertRaises(O.ConflictError):
            B.create_bracket(self.store, "b1", teams(4), {**MAPS, "play": ["Other"]})

    def test_bad_input_is_refused_and_nothing_is_stored(self):
        bad = [
            ("b", [], MAPS), ("b", teams(1), MAPS), ("b" * 41, teams(4), MAPS), ("has space", teams(4), MAPS),
            ("b", teams(2) + teams(2), MAPS),                                  # duplicate teams
            ("b", [{"team": "x"}] + teams(3), MAPS), ("b", [{"team": "x y", "submission": "s"}] + teams(3), MAPS),
            ("b", teams(4), {"play": ["A"]}), ("b", teams(4), {**MAPS, "tiebreak_normal": ["A", "B"]}),
            ("b", teams(4), {**MAPS, "tiebreak_final": ["A"]}), ("b", teams(4), {**MAPS, "play": []}),
            ("b", teams(4), {**MAPS, "play": ["bad name!"]}), ("b", "not a list", MAPS)]
        for bid, ts, maps in bad:
            with self.subTest(bid=bid[:8], n=len(ts) if isinstance(ts, list) else ts), self.assertRaises(B.BracketError):
                B.create_bracket(self.store, bid, ts, maps)
        self.assertEqual(self.store.snapshot().get("brackets", {}), {})

    def test_house_bots_are_refused_because_their_rule_is_undecided(self):
        ts = teams(3) + [{"team": "house-1", "submission": "sub-h-v1", "kind": "house_bot"}]
        with self.assertRaisesRegex(B.BracketError, "DEC-06"):
            B.create_bracket(self.store, "b", ts, MAPS)


class Rounds(Base):
    def test_a_round_cannot_start_before_the_previous_one_is_complete(self):
        self.make(8)
        with self.assertRaisesRegex(B.BracketError, "not complete"):
            B.start_round(self.store, "b1", 2, "org-1")
        with self.assertRaises(B.BracketError):
            B.start_round(self.store, "b1", 9, "org-1")
        with self.assertRaises(B.BracketError):
            B.start_round(self.store, "b1", 1, "bad actor")

    def test_a_round_cannot_run_until_an_organizer_starts_it(self):
        self.make(4)
        with self.assertRaisesRegex(B.BracketError, "not been started"):
            B.run_round(self.store, "b1", 1, lower_wins)

    def test_starting_twice_changes_nothing(self):
        self.make(4)
        a = B.start_round(self.store, "b1", 1, "org-1")
        b = B.start_round(self.store, "b1", 1, "org-2")
        self.assertEqual((a["started_by"], b["started_by"], b["status"]), ("org-1", "org-1", "running"))

    def test_the_next_round_waits_for_the_organizer_after_a_round_completes(self):
        self.make(8)
        B.start_round(self.store, "b1", 1, "org-1")
        B.run_round(self.store, "b1", 1, lower_wins, owner="w", sleep=lambda s: None)
        b = self.get()
        self.assertEqual([r["status"] for r in b["rounds"]], ["completed", "ready", "pending"])
        r1 = b["rounds"][0]["matches"]
        for j, m in enumerate(b["rounds"][1]["matches"]):
            self.assertEqual((m["a"], m["b"]), (r1[2 * j]["winner"], r1[2 * j + 1]["winner"]))


class FullTournaments(Base):
    def test_every_size_ends_with_one_champion_and_the_right_number_of_matches(self):
        for n in (2, 3, 4, 5, 6, 7, 8, 9, 12, 16, 17):
            with self.subTest(n=n):
                self.make(n, bid=f"t{n}", seed=n)
                b = self.play_all(f"t{n}")
                self.assertEqual((b["status"], b["champion"]), ("completed", "team-01"))   # the lowest name always wins
                real = [m for r in b["rounds"] for m in r["matches"] if not m["bye"]]
                self.assertEqual(len(real), n - 1)
                losers = [m["loser"] for m in real]
                self.assertEqual(sorted(losers + [b["champion"]]), sorted(t["team"] for t in teams(n)))
                self.assertEqual(len(set(losers)), n - 1)           # each team loses exactly once

    def test_stages_follow_the_round_and_each_game_uses_the_pinned_submissions(self):
        self.make(4)
        seen = []

        def fn(ctx):
            seen.append((ctx.match_id, ctx.map, ctx.submission_a, ctx.submission_b))
            if ctx.match_id.endswith("-g0"):
                return won("A", COIN)             # every first game is tied: the tie-break maps decide
            return lower_wins(ctx)
        self.play_all(run_fn=fn)
        by_series = {}
        for mid, mp, _, _ in seen:
            by_series.setdefault(mid.rsplit("-g", 1)[0], []).append(mp)
        semis = [k for k in by_series if "-r1-" in k]
        final = [k for k in by_series if "-r2-" in k]
        self.assertEqual((len(semis), len(final)), (2, 1))
        for k in semis:
            self.assertEqual(by_series[k][1:], ["TieN"])                              # normal stage: one tie-break map
        for k in final:
            self.assertEqual(by_series[k][1:], ["TieF1", "TieF2", "TieF3"])           # final: three, in order
        self.assertTrue({s for _, _, sa, sb in seen for s in (sa, sb)} <= {t["submission"] for t in teams(4)})

    def test_play_maps_rotate_by_round_and_match(self):
        self.make(4)
        maps = {}

        def fn(ctx):
            if ctx.match_id.endswith("g0"):
                maps[ctx.match_id] = ctx.map
            return lower_wins(ctx)
        self.play_all(run_fn=fn)
        self.assertEqual(maps, {"b1-r1-m0-g0": "PlayA", "b1-r1-m1-g0": "PlayB", "b1-r2-m0-g0": "PlayB"})

    def test_a_tie_in_the_final_goes_through_three_maps_and_the_coin(self):
        self.make(2)

        def fn(ctx):
            return won("A", COIN)
        coin_calls = []
        b = self.play_all(run_fn=fn, coin=lambda: coin_calls.append(1) or "B")
        s = T.get_series(self.store, "b1-r1-m0")
        self.assertEqual((s["stage"], len(s["games"]), s["result"]["result_type"], len(coin_calls)), ("final", 4, "coin_flip", 1))
        self.assertEqual(b["champion"], s["result"]["winner_team"])

    def test_a_bot_forfeit_advances_the_opponent(self):
        self.make(2)
        b = self.play_all(run_fn=lambda ctx: crash("A"))
        m = b["rounds"][0]["matches"][0]
        self.assertEqual((b["champion"], m["result_type"]), (m["b"], "bot_forfeit"))      # side A crashed: side B advances


class ExactlyOnce(Base):
    def test_a_finished_round_is_never_played_again_and_each_winner_advances_once(self):
        self.make(8)
        B.start_round(self.store, "b1", 1, "org-1")
        B.run_round(self.store, "b1", 1, lower_wins, owner="w1", sleep=lambda s: None)
        before = self.get()
        out = B.run_round(self.store, "b1", 1, lambda ctx: self.fail("a game was replayed"), owner="w2", sleep=lambda s: None)
        self.assertEqual((out["status"], out["ran"]), ("completed", 0))
        self.assertEqual(self.get(), before)
        adv = [h for h in before["history"] if h["event"] == "advanced"]
        self.assertEqual(len(adv), 4)

    def test_the_series_advancement_flag_is_consumed_by_the_bracket(self):
        self.make(2)
        self.play_all()
        self.assertIsNone(T.take_series_advancement(self.store, "b1-r1-m0"))

    def test_a_crash_between_series_result_and_advancing_loses_nothing(self):
        self.make(4)
        B.start_round(self.store, "b1", 1, "org-1")
        # play the first match's series by hand, as if the worker died before the bracket noticed
        b = self.get()
        m = b["rounds"][0]["matches"][0]
        args = (B.series_id("b1", 1, 0), m["a"], m["b"], "PlayA", f"sub-{m['a'][-2:]}-v1", f"sub-{m['b'][-2:]}-v1", "normal", ["TieN"])
        T.create_series(self.store, *args)
        T.run_series_job(self.store, args[0], lower_wins, owner="w1", sleep=lambda s: None)
        self.assertIsNone(self.get()["rounds"][0]["matches"][0]["winner"])
        out = B.run_round(self.store, "b1", 1, lower_wins, owner="w2", sleep=lambda s: None)
        self.assertEqual(out["status"], "completed")
        self.assertIsNotNone(self.get()["rounds"][0]["matches"][0]["winner"])

    def test_two_workers_on_one_round_never_play_a_match_twice(self):
        self.make(8)
        B.start_round(self.store, "b1", 1, "org-1")
        played = []
        lock = threading.Lock()

        def fn(ctx):
            with lock:
                played.append((ctx.match_id, ctx.attempt))
            return lower_wins(ctx)
        barrier = threading.Barrier(3)

        def go(name):
            barrier.wait()
            B.run_round(self.store, "b1", 1, fn, owner=name, sleep=lambda s: None)
        ts = [threading.Thread(target=go, args=(f"w{i}",)) for i in range(3)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        B.run_round(self.store, "b1", 1, fn, owner="w9", sleep=lambda s: None)      # finishes anything a skipped worker left
        self.assertEqual(len(played), len(set(played)))
        self.assertEqual(len(played), 4)                                            # four real matches, one game each
        self.assertEqual(self.get()["rounds"][0]["status"], "completed")


class Failures(Base):
    def test_a_paused_game_pauses_the_round_and_resuming_it_finishes(self):
        self.make(4, max_attempts=1)
        B.start_round(self.store, "b1", 1, "org-1")
        healed = {"yes": False}

        def fn(ctx):
            if ctx.match_id == "b1-r1-m1-g0" and not healed["yes"]:
                return PLATFORM
            return lower_wins(ctx)
        out = B.run_round(self.store, "b1", 1, fn, owner="w1", alert=self.alerts.append, sleep=lambda s: None)
        self.assertEqual(out["status"], "paused")
        b = self.get()
        self.assertEqual(b["rounds"][0]["status"], "paused")
        self.assertIsNotNone(b["rounds"][0]["matches"][0]["winner"])      # the first match was not undone
        self.assertIsNone(b["rounds"][0]["matches"][1]["winner"])
        self.assertEqual(len(self.alerts), 1)
        with self.assertRaises(B.BracketError):
            B.start_round(self.store, "b1", 2, "org-1")                 # the next round stays locked
        healed["yes"] = True
        O.resume_paused(self.store, "b1-r1-m1-g0", "admin-1", 1)
        out = B.run_round(self.store, "b1", 1, fn, owner="w1", sleep=lambda s: None)
        self.assertEqual(out["status"], "completed")
        self.assertEqual(self.get()["rounds"][1]["status"], "ready")


class PublicView(Base):
    def test_public_view_shows_pairings_winners_and_champion_only(self):
        self.make(3)
        self.play_all()
        v = B.public_view(self.get())
        self.assertEqual((v["champion"], v["status"], v["draw"]["byes"], len(v["rounds"])), ("team-01", "completed", 1, 2))
        text = repr(v)
        for leaked in ("sub-", "series_id", "history", "PlayA", "started_by"):
            self.assertNotIn(leaked, text)
        self.assertTrue(v["rounds"][-1]["final"])


@unittest.skipUnless(os.environ.get("BIO_INTEGRATION") == "1", "set BIO_INTEGRATION=1 to play real matches")
class RealTournament(unittest.TestCase):
    def test_three_real_teams_play_to_a_champion(self):
        import shutil
        from backend.match_runner import launcher as L
        py = L.resolve_python(None, None, L.load_lock())
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bots = root / "bots"
            bots.mkdir()
            for n in (1, 2, 3):
                shutil.copytree(L.DEFAULT_SCAFFOLD / "src" / "examplefuncsplayer_py", bots / f"sub-{n:02d}-v1")
            store = JsonFileStore(root / "state.json")
            B.create_bracket(store, "real", teams(3), {"play": ["DefaultSmall"], "tiebreak_normal": ["DefaultSmall"],
                                                       "tiebreak_final": ["DefaultSmall"] * 3}, rng=random.Random(5))
            run_fn = O.launcher_run_fn(L.DEFAULT_SCAFFOLD, py, bots, root / "out", timeout=120, lock_path=root / "host.lock")
            for r in (1, 2):
                B.start_round(store, "real", r, "org-1")
                self.assertEqual(B.run_round(store, "real", r, run_fn, owner="w", sleep=lambda s: None)["status"], "completed")
            b = B.get_bracket(store, "real")
            self.assertEqual(b["status"], "completed")
            self.assertIn(b["champion"], [t["team"] for t in teams(3)])
            real = [m for r in b["rounds"] for m in r["matches"] if not m["bye"]]
            self.assertEqual(len(real), 2)
            self.assertEqual(sum(1 for r in b["rounds"][0]["matches"] if r["bye"]), 1)


if __name__ == "__main__":
    unittest.main()
