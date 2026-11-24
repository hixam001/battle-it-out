# SPDX-License-Identifier: AGPL-3.0-only
"""One whole simulated tournament, real engine, real sandbox (TC-05, FLOW-05; CN-015).

Every piece was tested alone (map pool, bracket, series, tie-breaks, replay vault). This plays them together:
five human teams (an odd number, so one bye), four of them the scaffold's example bot and one a bot that
crashes, on a pool made from the real engine jar. It needs `BIO_INTEGRATION=1` and takes a few minutes.

    BIO_INTEGRATION=1 python3 -m unittest backend.match_orchestrator.tests.test_tournament_e2e -v
"""
import copy
import os
import random
import shutil
import tempfile
import unittest
from pathlib import Path

from backend.match_orchestrator import bracket as B
from backend.match_orchestrator import maps as M
from backend.match_orchestrator import orchestrator as O
from backend.match_orchestrator import replays as R
from backend.match_orchestrator import tiebreak as T
from backend.match_orchestrator.store import JsonFileStore

ENGINE = "1.2.6"
ENGINE_JARS = sorted((Path.home() / ".gradle/caches/modules-2/files-2.1/org.battlecode/battlecode26-java/1.2.6")
                     .rglob("battlecode26-java-1.2.6.jar"))
TOURNAMENT = "sim-2026"
CRASHER = "team-05"


def _team(n):
    return {"team": f"team-{n:02d}", "submission": f"sub-{n:02d}-v1"}


@unittest.skipUnless(ENGINE_JARS and os.environ.get("BIO_INTEGRATION") == "1",
                     "set BIO_INTEGRATION=1 (and have the engine jar) to play real matches")
class WholeTournament(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from backend.match_runner import launcher as L
        cls.L = L
        cls._tmp = tempfile.TemporaryDirectory()
        root = cls.root = Path(cls._tmp.name)
        bots = root / "bots"
        bots.mkdir()
        example = L.DEFAULT_SCAFFOLD / "src" / "examplefuncsplayer_py"
        for n in (1, 2, 3, 4):
            shutil.copytree(example, bots / f"sub-{n:02d}-v1")
        shutil.copytree(Path(__file__).resolve().parents[2] / "match_runner" / "tests" / "bots" / "crash_py",
                        bots / "sub-05-v1")
        cls.jars = ENGINE_JARS
        py = L.resolve_python(None, None, L.load_lock())
        cls.store = JsonFileStore(root / "state.json")
        cls.vault = R.Vault(root / "vault", R.ReplayIndex(root / "replays.json"))
        cls.alerts = []
        cls.run_fn = O.launcher_run_fn(L.DEFAULT_SCAFFOLD, py, bots, root / "out", timeout=180, lock_path=root / "host.lock")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_01_everything_together(self):
        cls = type(self)
        engine_version = ENGINE
        catalogue = M.load_engine_maps(ENGINE_JARS[0])
        M.create_pool(cls.store, "sim-pool", catalogue, engine_version, play=["DefaultSmall"],
                      tiebreak_normal=["DefaultMedium"], tiebreak_final=["jail", "pipes", "keepout"])
        bracket = M.create_bracket_from_pool(cls.store, "sim", [_team(n) for n in range(1, 6)], "sim-pool",
                                             catalogue, engine_version, rng=random.Random(11))
        self.assertEqual(sum(1 for m in bracket["rounds"][0]["matches"] if m["bye"]), 3)   # 5 teams -> size 8 -> 3 byes
        rounds = len(bracket["rounds"])
        self.assertEqual(rounds, 3)

        for r in range(1, rounds + 1):
            B.start_round(cls.store, "sim", r, "org-1")
            out = B.run_round(cls.store, "sim", r, cls.run_fn, owner="worker-1", alert=cls.alerts.append,
                              sleep=lambda s: None)
            self.assertEqual(out["status"], "completed", out)
            R.collect_bracket(cls.vault, cls.store, TOURNAMENT, "sim")

        final = B.get_bracket(cls.store, "sim")
        self.assertEqual(final["status"], "completed")
        self.assertIsNotNone(final["champion"])
        self.assertNotEqual(final["champion"], CRASHER)          # a bot that crashes cannot win anything
        self.assertEqual(cls.alerts, [])                          # no platform trouble during the whole run

        # A repeat of the whole thing changes nothing: no new game, no second advancement.
        before = copy.deepcopy(cls.store.snapshot()["series"])
        for r in range(1, rounds + 1):
            self.assertEqual(B.run_round(cls.store, "sim", r, cls.run_fn, owner="worker-2",
                                         sleep=lambda s: None)["status"], "completed")
        self.assertEqual(cls.store.snapshot()["series"], before)

        # What happened to the crashing team.
        real = [(m, rd["number"]) for rd in final["rounds"] for m in rd["matches"] if not m["bye"]]
        crash = [m for m, _ in real if CRASHER in (m["a"], m["b"])]
        self.assertEqual(len(crash), 1)                           # it loses its first real match and is out
        self.assertEqual(crash[0]["result_type"], "bot_forfeit")
        self.assertNotEqual(crash[0]["winner"], CRASHER)

        # The series. Example bot against itself ties every game (the engine decides by its own coin flip), so a
        # normal match must go to the one tie-break map and the final to all three, then to the platform's coin flip.
        series = cls.store.snapshot()["series"]
        forfeit = series[next(m["series_id"] for m, _ in real if CRASHER in (m["a"], m["b"]))]
        self.assertEqual([g["map"] for g in forfeit["games"]], ["DefaultSmall"])       # forfeit ends it at once
        self.assertIsNone(forfeit["coin_flip"])
        decided = [s for s in series.values() if s is not forfeit]
        normal = [s for s in decided if s["stage"] == "normal"]
        finals = [s for s in decided if s["stage"] == "final"]
        self.assertEqual(len(finals), 1)
        self.assertGreaterEqual(len(normal), 1)
        for s in normal:
            self.assertEqual([g["map"] for g in s["games"]], ["DefaultSmall", "DefaultMedium"])
        self.assertEqual([g["map"] for g in finals[0]["games"]], ["DefaultSmall", "jail", "pipes", "keepout"])
        for s in decided:                                    # game 0 is always tied, so a tie-break or a flip decides
            kind = s["result"]["result_type"]
            self.assertIn(kind, ("tiebreak", "coin_flip"))
            self.assertEqual(kind == "coin_flip", s["coin_flip"] is not None)   # a flip is stored exactly when it decided
            if s["coin_flip"] is not None:
                self.assertEqual(s["coin_flip"]["rerolls_allowed"], False)
            self.assertEqual(s["advancement"]["pending"], False)
            self.assertIsNotNone(s["advancement"]["taken_at"])                  # the winner advanced, once
        self.assertEqual(finals[0]["result"]["winner_team"], final["champion"])

        # Replays of the tournament: one stored per finished game with a file; a participant of the tournament
        # can fetch one; a stranger cannot even tell it exists; after the archive nobody can, and the bracket stays.
        index = cls.vault.index.snapshot()
        available = [mid for mid, rec in index["replays"].items() if rec["status"] == "available"]
        self.assertGreaterEqual(len(available), 1)
        self.assertEqual([i for i in index["incidents"]], [])
        mid = available[0]
        R.fetch_replay(cls.vault, mid, R.Viewer("participant", frozenset({TOURNAMENT})))
        with self.assertRaises(R.NotFound):
            R.fetch_replay(cls.vault, mid, R.Viewer("participant", frozenset({"other"})))
        folder = cls.root / "vault" / TOURNAMENT
        on_disk = sorted(p.name for p in folder.iterdir())
        self.assertEqual(on_disk, sorted(f"{m}.bc26" for m in available))        # the files really are there ...
        self.assertTrue(R.archive_tournament(cls.vault, TOURNAMENT, "admin-1")["replays_deleted"])
        self.assertEqual(list(folder.iterdir()) if folder.exists() else [], [])  # ... and really gone afterwards
        with self.assertRaises(R.Gone):
            R.fetch_replay(cls.vault, mid, R.Viewer("admin", frozenset()))
        self.assertEqual(B.get_bracket(cls.store, "sim")["champion"], final["champion"])


if __name__ == "__main__":
    unittest.main()
