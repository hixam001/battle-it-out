# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for tournament map pools and tie-break map sources (BIO-303/304, TC-05; CN-014).

Unit tests build a small engine jar in a temporary folder. One test reads the real pinned engine jar from the
Gradle cache and is skipped when it is not there.

    python3 -m unittest backend.match_orchestrator.tests.test_maps -v
"""
import hashlib
import os
import random
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path

from backend.match_orchestrator import bracket as B
from backend.match_orchestrator import maps as M
from backend.match_orchestrator import orchestrator as O
from backend.match_orchestrator.store import JsonFileStore

FILES = {f"Map{c}": f"content of map {c}".encode() for c in "ABCDEFGHI"}
ENGINE = "1.2.6"
GOOD = dict(play=["MapA", "MapB"], tiebreak_normal=["MapC"], tiebreak_final=["MapD", "MapE", "MapF"])


def make_jar(path: Path, files: dict, extra: dict | None = None) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        for name, data in files.items():
            z.writestr(f"{M.RESOURCE_DIR}{name}{M.SUFFIX}", data)
        for name, data in (extra or {}).items():
            z.writestr(name, data)
    return path


def teams(n):
    return [{"team": f"team-{i:02d}", "submission": f"sub-{i:02d}-v1"} for i in range(1, n + 1)]


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.store = JsonFileStore(self.dir / "state.json")
        self.jar = make_jar(self.dir / "engine.jar", FILES)
        self.cat = M.load_engine_maps(self.jar)

    def pool(self, pid="pool-1", **kw):
        args = {**GOOD, **kw}
        return M.create_pool(self.store, pid, self.cat, ENGINE, **args)


class TestCatalogue(Base):
    def test_names_and_hashes(self):
        self.assertEqual(set(self.cat), set(FILES))
        self.assertEqual(self.cat["MapA"], hashlib.sha256(FILES["MapA"]).hexdigest())

    def test_other_files_and_odd_names_are_ignored(self):
        jar = make_jar(self.dir / "e2.jar", {"Good": b"x", "a,b": b"x", "sub/dir": b"x", "bad name": b"x"},
                       {"other/Thing.map26": b"x", f"{M.RESOURCE_DIR}notes.txt": b"x"})
        self.assertEqual(set(M.load_engine_maps(jar)), {"Good"})

    def test_oversize_map_is_an_error_not_a_skip(self):
        jar = make_jar(self.dir / "big.jar", {"Big": b"0" * (M.MAX_MAP_BYTES + 1)})
        with self.assertRaises(M.MapError):
            M.load_engine_maps(jar)

    def test_too_many_maps(self):
        jar = make_jar(self.dir / "many.jar", {f"m{i}": b"x" for i in range(M.MAX_MAPS + 1)})
        with self.assertRaises(M.MapError):
            M.load_engine_maps(jar)

    def test_bad_jar(self):
        (self.dir / "x.jar").write_bytes(b"not a zip")
        with self.assertRaises(M.MapError):
            M.load_engine_maps(self.dir / "x.jar")
        with self.assertRaises(M.MapError):
            M.load_engine_maps(self.dir / "missing.jar")

    def test_the_jar_is_not_extracted(self):
        before = sorted(p.name for p in self.dir.iterdir())
        M.load_engine_maps(self.jar)
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), before)


class TestCreatePool(Base):
    def test_stored_with_pins(self):
        p = self.pool()
        self.assertEqual(p["maps"]["play"], ["MapA", "MapB"])
        self.assertEqual(p["engine_version"], ENGINE)
        self.assertEqual(set(p["sha256"]), {"MapA", "MapB", "MapC", "MapD", "MapE", "MapF"})
        self.assertEqual(p["sha256"]["MapC"], self.cat["MapC"])
        self.assertEqual(M.get_pool(self.store, "pool-1")["maps"], p["maps"])

    def test_same_content_again_is_the_stored_pool(self):
        a = self.pool()
        b = self.pool()
        self.assertEqual(a, b)

    def test_different_content_same_id_conflicts(self):
        self.pool()
        with self.assertRaises(O.ConflictError):
            self.pool(play=["MapA", "MapG"])
        with self.assertRaises(O.ConflictError):          # even only the order of the tie-break maps
            self.pool(tiebreak_final=["MapE", "MapD", "MapF"])
        self.assertEqual(M.get_pool(self.store, "pool-1")["maps"]["play"], ["MapA", "MapB"])

    def test_unknown_map_refused(self):
        for key in ("play", "tiebreak_normal", "tiebreak_final"):
            bad = {"play": ["Nope", "MapB"], "tiebreak_normal": ["Nope"], "tiebreak_final": ["MapD", "MapE", "Nope"]}[key]
            with self.subTest(key), self.assertRaises(M.MapError):
                self.pool(**{key: bad})

    def test_counts(self):
        for kw in ({"tiebreak_normal": ["MapC", "MapG"]}, {"tiebreak_normal": []},
                   {"tiebreak_final": ["MapD", "MapE"]}, {"tiebreak_final": ["MapD", "MapE", "MapF", "MapG"]},
                   {"play": []}, {"play": [f"m{i}" for i in range(M.MAX_PLAY_MAPS + 1)]}):
            with self.subTest(kw), self.assertRaises(M.MapError):
                self.pool(**kw)

    def test_repeats_refused(self):
        for kw in ({"play": ["MapA", "MapA"]}, {"tiebreak_final": ["MapD", "MapD", "MapF"]}):
            with self.subTest(kw), self.assertRaises(M.MapError):
                self.pool(**kw)

    def test_tiebreak_map_must_not_be_a_played_map(self):
        with self.assertRaises(M.MapError):
            self.pool(tiebreak_normal=["MapA"])
        with self.assertRaises(M.MapError):
            self.pool(tiebreak_final=["MapD", "MapB", "MapF"])

    def test_normal_and_final_tiebreak_may_share_a_map(self):
        self.pool(tiebreak_normal=["MapD"])

    def test_bad_types_and_ids(self):
        for kw in ({"play": "MapA"}, {"play": [1]}, {"tiebreak_normal": "MapC"}, {"play": ["MapA,MapB"]}):
            with self.subTest(kw), self.assertRaises(M.MapError):
                self.pool(**kw)
        for pid in ("", "../x", "a b", "x" * (M.MAX_POOL_ID + 1), None, 5):
            with self.subTest(pid), self.assertRaises(M.MapError):
                M.create_pool(self.store, pid, self.cat, ENGINE, **GOOD)
        for ev in ("", "1 2", None, "x" * 41):
            with self.subTest(ev), self.assertRaises(M.MapError):
                M.create_pool(self.store, "p2", self.cat, ev, **GOOD)

    def test_nothing_stored_after_a_refusal(self):
        with self.assertRaises(M.MapError):
            self.pool(play=["Nope"])
        self.assertNotIn("p", self.store.snapshot().get("map_pools", {}))
        self.assertEqual(self.store.snapshot().get("map_pools", {}), {})

    def test_unknown_pool(self):
        with self.assertRaises(M.MapError):
            M.get_pool(self.store, "nope")

    def test_two_threads_same_pool(self):
        out = []
        ts = [threading.Thread(target=lambda: out.append(self.pool("race"))) for _ in range(6)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(len(out), 6)
        self.assertTrue(all(o == out[0] for o in out))

    def test_pool_maps_is_a_copy(self):
        p = self.pool()
        m = M.pool_maps(p)
        m["play"].append("X")
        self.assertEqual(M.pool_maps(p)["play"], ["MapA", "MapB"])


class TestVerify(Base):
    def test_clean(self):
        self.assertEqual(M.verify_pool(self.pool(), self.cat, ENGINE), [])

    def test_changed_file(self):
        p = self.pool()
        files = {**FILES, "MapC": b"edited"}
        cat = M.load_engine_maps(make_jar(self.dir / "e3.jar", files))
        problems = M.verify_pool(p, cat, ENGINE)
        self.assertEqual(len(problems), 1)
        self.assertIn("MapC changed", problems[0])

    def test_missing_file(self):
        p = self.pool()
        cat = {k: v for k, v in self.cat.items() if k != "MapA"}
        self.assertTrue(any("MapA is missing" in x for x in M.verify_pool(p, cat, ENGINE)))

    def test_engine_version_change(self):
        self.assertTrue(any("engine" in x for x in M.verify_pool(self.pool(), self.cat, "1.2.7")))

    def test_an_unused_map_changing_is_not_a_problem(self):
        p = self.pool()
        cat = {**self.cat, "MapI": "0" * 64}
        self.assertEqual(M.verify_pool(p, cat, ENGINE), [])


class TestBracketFromPool(Base):
    def make(self, n=5, bid="b1", pid="pool-1"):
        return M.create_bracket_from_pool(self.store, bid, teams(n), pid, self.cat, ENGINE, rng=random.Random(1))

    def test_bracket_gets_the_pool_maps_and_id(self):
        self.pool()
        b = self.make()
        self.assertEqual(b["maps"], {"play": ["MapA", "MapB"], "tiebreak_normal": ["MapC"],
                                     "tiebreak_final": ["MapD", "MapE", "MapF"]})
        self.assertEqual(b["map_pool"], "pool-1")
        self.assertEqual(B.get_bracket(self.store, "b1")["map_pool"], "pool-1")

    def test_repeat_is_the_same_bracket(self):
        self.pool()
        a = self.make()
        b = self.make()
        self.assertEqual(a, b)

    def test_unknown_pool(self):
        with self.assertRaises(M.MapError):
            self.make()
        self.assertNotIn("b1", self.store.snapshot().get("brackets", {}))

    def test_changed_map_file_blocks_the_bracket(self):
        self.pool()
        cat = M.load_engine_maps(make_jar(self.dir / "e4.jar", {**FILES, "MapD": b"edited"}))
        with self.assertRaises(M.MapError):
            M.create_bracket_from_pool(self.store, "b1", teams(4), "pool-1", cat, ENGINE)
        self.assertNotIn("b1", self.store.snapshot().get("brackets", {}))

    def test_engine_change_blocks_the_bracket(self):
        self.pool()
        with self.assertRaises(M.MapError):
            M.create_bracket_from_pool(self.store, "b1", teams(4), "pool-1", self.cat, "9.9.9")

    def test_another_pool_for_the_same_bracket_conflicts(self):
        self.pool()
        self.pool("pool-2", play=["MapG", "MapH"])
        self.make()
        with self.assertRaises(O.ConflictError):
            self.make(pid="pool-2")
        self.assertEqual(B.get_bracket(self.store, "b1")["map_pool"], "pool-1")

    def test_a_second_pool_with_the_same_maps_still_conflicts(self):
        # the map lists match, so only the pool id tells the two brackets apart
        self.pool()
        self.pool("pool-2")
        self.make()
        with self.assertRaises(O.ConflictError):
            self.make(pid="pool-2")
        self.assertEqual(B.get_bracket(self.store, "b1")["map_pool"], "pool-1")

    def test_pool_is_unchanged_by_use(self):
        p = self.pool()
        self.make()
        self.assertEqual(M.get_pool(self.store, "pool-1"), p)


REAL_JARS = sorted((Path.home() / ".gradle/caches/modules-2/files-2.1/org.battlecode/battlecode26-java/1.2.6")
                   .glob("*/battlecode26-java-1.2.6.jar"))


@unittest.skipUnless(REAL_JARS, "pinned engine jar not in the Gradle cache")
class TestRealEngineJar(unittest.TestCase):
    def test_catalogue_of_the_pinned_engine(self):
        cat = M.load_engine_maps(REAL_JARS[0])
        for name in ("DefaultSmall", "DefaultMedium", "DefaultLarge"):
            self.assertIn(name, cat)
        self.assertGreaterEqual(len(cat), 20)
        self.assertTrue(all(len(v) == 64 for v in cat.values()))
        with tempfile.TemporaryDirectory() as d:
            store = JsonFileStore(Path(d) / "s.json")
            names = sorted(cat)
            pool = M.create_pool(store, "real", cat, ENGINE, play=names[:3], tiebreak_normal=names[3:4],
                                 tiebreak_final=names[4:7])
            self.assertEqual(M.verify_pool(pool, cat, ENGINE), [])


@unittest.skipUnless(REAL_JARS and os.environ.get("BIO_INTEGRATION") == "1",
                     "set BIO_INTEGRATION=1 (and have the engine jar) to play real matches")
class RealMatchesOnPoolMaps(unittest.TestCase):
    def test_final_series_plays_on_the_pools_own_maps(self):
        import shutil
        from backend.match_runner import launcher as L
        py = L.resolve_python(None, None, L.load_lock())
        cat = M.load_engine_maps(REAL_JARS[0])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bots = root / "bots"
            bots.mkdir()
            for n in (1, 2):
                shutil.copytree(L.DEFAULT_SCAFFOLD / "src" / "examplefuncsplayer_py", bots / f"sub-{n:02d}-v1")
            store = JsonFileStore(root / "state.json")
            M.create_pool(store, "real", cat, ENGINE, play=["DefaultSmall"], tiebreak_normal=["DefaultMedium"],
                          tiebreak_final=["jail", "pipes", "keepout"])
            B_ = M.create_bracket_from_pool(store, "rb", teams(2), "real", cat, ENGINE, rng=random.Random(3))
            self.assertEqual(len(B_["rounds"]), 1)                 # two teams: the only round is the final
            run_fn = O.launcher_run_fn(L.DEFAULT_SCAFFOLD, py, bots, root / "out", timeout=180,
                                       lock_path=root / "host.lock")
            B.start_round(store, "rb", 1, "org-1")
            self.assertEqual(B.run_round(store, "rb", 1, run_fn, owner="w", sleep=lambda s: None)["status"], "completed")
            series = store.snapshot()["series"]
            self.assertEqual(len(series), 1)
            games = next(iter(series.values()))["games"]
            order = ["DefaultSmall", "jail", "pipes", "keepout"]
            self.assertEqual([g["map"] for g in games], order[:len(games)])
            self.assertEqual(B.get_bracket(store, "rb")["status"], "completed")


if __name__ == "__main__":
    unittest.main()
