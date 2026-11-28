# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for the replay lifecycle (BIO-305, BIO-REQ-08, SRD-070, TC-08, FLOW-06; CN-012).

Unit tests write small real gzip files as stand-in replays. The last class plays a real match and needs
`BIO_INTEGRATION=1`.

    python3 -m unittest backend.match_orchestrator.tests.test_replays -v
"""
import fcntl
import gzip
import hashlib
import os
import random
import shutil
import stat
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.match_orchestrator import bracket as B
from backend.match_orchestrator import orchestrator as O
from backend.match_orchestrator import replays as R
from backend.match_orchestrator.store import JsonFileStore, StoreError
from backend.match_orchestrator.tests.test_bracket import MAPS, teams
from backend.match_orchestrator.tests.test_tiebreak import COIN, DECISIVE, won

ADMIN = R.Viewer("admin")
ORG = R.Viewer("organizer", frozenset({"t1"}))
PART = R.Viewer("participant", frozenset({"t1"}))
OTHER_PART = R.Viewer("participant", frozenset({"t2"}))
OTHER_ORG = R.Viewer("organizer", frozenset({"t2"}))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.out = self.root / "worker-out"
        self.out.mkdir()
        self.vault = R.Vault(self.root / "vault", R.ReplayIndex(self.root / "replays.json"))
        self.n = 0

    def make(self, body=None, name=None) -> Path:
        """A real gzip file standing in for a replay."""
        self.n += 1
        p = self.out / (name or f"game-{self.n}.bc26")
        p.write_bytes(gzip.compress(body or (f"replay {self.n} ".encode() * 500)))
        return p

    def put(self, mid, tid="t1", **kw):
        p = self.make()
        return R.register_replay(self.vault, tid, mid, p, sha(p), **kw), p

    def snap(self):
        return self.vault.index.snapshot()

    def files(self, tid="t1"):
        d = self.vault.root / tid
        return sorted(x.name for x in d.iterdir()) if d.exists() else []


class Register(Base):
    def test_stores_a_copy_with_private_permissions_and_a_record(self):
        rec, src = self.put("g1")
        self.assertEqual(rec["status"], "available")
        self.assertEqual(rec["sha256"], sha(src))
        self.assertEqual(rec["bytes"], src.stat().st_size)
        self.assertEqual(rec["format"], "bc26")
        dest = self.vault.root / "t1" / "g1.bc26"
        self.assertEqual(sha(dest), sha(src))
        self.assertEqual(stat.S_IMODE(dest.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(dest.parent.stat().st_mode), 0o700)
        self.assertEqual(self.files(), ["g1.bc26"])          # no temporary leftovers

    def test_same_content_twice_is_a_no_op(self):
        rec, src = self.put("g1")
        again = R.register_replay(self.vault, "t1", "g1", src, sha(src))
        self.assertEqual(again, rec)

    def test_a_different_replay_for_the_same_game_is_refused(self):
        self.put("g1")
        other = self.make(b"something else entirely")
        with self.assertRaises(R.Refused):
            R.register_replay(self.vault, "t1", "g1", other, sha(other))
        self.assertEqual(self.files(), ["g1.bc26"])

    def test_the_same_game_id_in_another_tournament_is_refused(self):
        _, src = self.put("g1")
        with self.assertRaises(R.Refused):
            R.register_replay(self.vault, "t2", "g1", src, sha(src))

    def test_hash_mismatch_is_refused_and_nothing_is_stored(self):
        p = self.make()
        with self.assertRaises(R.Refused):
            R.register_replay(self.vault, "t1", "g1", p, "00" * 32)
        self.assertEqual(self.files(), [])
        self.assertEqual(self.snap()["replays"], {})

    def test_bad_files_are_refused(self):
        cases = {}
        empty = self.out / "empty"
        empty.write_bytes(b"")
        cases["empty"] = empty
        plain = self.out / "plain"
        plain.write_bytes(b"not gzip at all")
        cases["not gzip"] = plain
        good = gzip.compress(os.urandom(200_000))
        cut = self.out / "cut"
        cut.write_bytes(good[: len(good) // 2])
        cases["cut off"] = cut
        d = self.out / "dir"
        d.mkdir()
        cases["directory"] = d
        link = self.out / "link"
        link.symlink_to(self.make())
        cases["symlink"] = link
        cases["missing"] = self.out / "nothing-here"
        fifo = self.out / "fifo"
        os.mkfifo(fifo)
        cases["fifo"] = fifo
        for name, p in cases.items():
            with self.subTest(name):
                with self.assertRaises(R.Refused):
                    R.register_replay(self.vault, "t1", "g1", p, None)
        self.assertEqual(self.files(), [])

    def test_size_ceiling(self):
        p = self.make()
        with self.assertRaises(R.Refused):
            R.register_replay(self.vault, "t1", "g1", p, None, max_bytes=10)

    def test_unsafe_ids_are_refused_and_cannot_leave_the_vault(self):
        p = self.make()
        for tid, mid in (("../x", "g"), ("t1", "../../etc/passwd"), ("t1", "a/b"), ("", "g"), ("t1", ".."),
                         ("t1", "g\n1"), ("t1", "g1\n"), ("t1\n", "g"), (None, "g"), ("t1", 5)):
            with self.subTest(tid=tid, mid=mid):
                with self.assertRaises(R.Refused):
                    R.register_replay(self.vault, tid, mid, p, None)
        self.assertFalse(any(self.root.glob("**/etc")))
        self.assertEqual(sorted(x.name for x in self.vault.root.iterdir()) if self.vault.root.exists() else [], [])

    def test_a_link_in_place_of_the_tournament_folder_is_not_followed(self):
        self.vault.root.mkdir()
        target = self.root / "elsewhere"
        target.mkdir()
        (self.vault.root / "t1").symlink_to(target)
        p = self.make()
        with self.assertRaises(R.Refused):
            R.register_replay(self.vault, "t1", "g1", p, None)
        self.assertEqual(list(target.iterdir()), [])

    def test_source_changing_while_copied_is_caught_by_the_hash_check(self):
        # the hash recorded by the launcher is the contract: a file that no longer matches is not stored
        p = self.make()
        h = sha(p)
        p.write_bytes(gzip.compress(b"swapped after the launcher hashed it"))
        with self.assertRaises(R.Refused):
            R.register_replay(self.vault, "t1", "g1", p, h)

    def test_damaged_index_is_never_an_empty_one(self):
        self.put("g1")
        (self.root / "replays.json").write_text("{not json")
        with self.assertRaises(StoreError):
            self.snap()
        (self.root / "replays.json").write_text('{"schema": 1, "matches": {}, "incidents": []}')   # the match store layout
        with self.assertRaises(StoreError):
            self.snap()


class FromResult(Base):
    def test_result_without_a_replay_is_not_an_error(self):
        self.assertIsNone(R.register_from_result(self.vault, "t1", "g1", None))
        self.assertIsNone(R.register_from_result(self.vault, "t1", "g1", {"replay": None}))
        self.assertEqual(self.snap()["incidents"], [])

    def test_missing_file_is_an_incident_and_an_unavailable_marker(self):
        res = {"replay": str(self.out / "gone.bc26"), "replay_sha256": "ab" * 32}
        self.assertIsNone(R.register_from_result(self.vault, "t1", "g1", res))
        s = self.snap()
        self.assertEqual(s["replays"]["g1"]["status"], "unavailable")
        self.assertEqual([i["incident_type"] for i in s["incidents"]], ["replay_unavailable"])
        # asking again does not pile up incidents
        R.register_from_result(self.vault, "t1", "g1", res)
        self.assertEqual(len(self.snap()["incidents"]), 1)
        with self.assertRaises(R.Unavailable):
            R.fetch_replay(self.vault, "g1", ADMIN)

    def test_incidents_reach_the_alert_function(self):
        R.register_from_result(self.vault, "t1", "g1", {"replay": str(self.out / "gone"), "replay_sha256": None})
        seen = []
        self.assertEqual(O.deliver_alerts(self.vault.index, seen.append), 1)
        self.assertEqual(seen[0]["incident_type"], "replay_unavailable")
        self.assertEqual(O.deliver_alerts(self.vault.index, seen.append), 0)

    def test_a_missing_replay_can_be_stored_later(self):
        p = self.make()
        R.register_from_result(self.vault, "t1", "g1", {"replay": str(self.out / "late"), "replay_sha256": None})
        rec = R.register_replay(self.vault, "t1", "g1", p, sha(p))
        self.assertEqual(rec["status"], "available")
        self.assertEqual(R.fetch_replay(self.vault, "g1", PART).sha256, sha(p))


class Access(Base):
    def setUp(self):
        super().setUp()
        self.put("g1")
        self.put("g2", tid="t2")

    def test_who_may_get_the_replay(self):
        for viewer in (ADMIN, ORG, PART):
            with self.subTest(viewer=viewer.role):
                h = R.fetch_replay(self.vault, "g1", viewer)
                self.assertEqual(h.path, self.vault.root / "t1" / "g1.bc26")
                self.assertEqual(h.sha256, sha(h.path))

    def test_everyone_else_gets_the_same_not_found_as_an_unknown_game(self):
        for viewer in (None, OTHER_PART, OTHER_ORG, R.Viewer("participant"), R.Viewer("organizer"),
                       R.Viewer("guest", frozenset({"t1"})), R.Viewer("", frozenset({"t1"}))):
            with self.subTest(viewer=viewer):
                with self.assertRaises(R.NotFound) as a:
                    R.fetch_replay(self.vault, "g1", viewer)
                with self.assertRaises(R.NotFound) as b:
                    R.fetch_replay(self.vault, "no-such-game", viewer)
                self.assertEqual(str(a.exception), str(b.exception))
        for bad in ("../g1", "", None, 7, "g1/../g2", "g1\n"):
            with self.assertRaises(R.NotFound):
                R.fetch_replay(self.vault, bad, ADMIN)

    def test_status_follows_the_same_rule(self):
        self.assertEqual(R.replay_status(self.vault, "g1", PART)["status"], "available")
        with self.assertRaises(R.NotFound):
            R.replay_status(self.vault, "g1", OTHER_PART)

    def test_damaged_file_is_unavailable_and_a_staff_incident_exists(self):
        path = self.vault.root / "t1" / "g1.bc26"
        data = bytearray(path.read_bytes())
        data[len(data) // 2] ^= 0xFF
        path.write_bytes(bytes(data))
        with self.assertRaises(R.Unavailable):
            R.fetch_replay(self.vault, "g1", PART)
        s = self.snap()
        self.assertEqual(s["replays"]["g1"]["status"], "unavailable")
        self.assertEqual([i["incident_type"] for i in s["incidents"]], ["replay_file_damaged"])
        with self.assertRaises(R.Unavailable):                       # and it stays that way
            R.fetch_replay(self.vault, "g1", PART)
        self.assertEqual(len(self.snap()["incidents"]), 1)

    def test_replaced_file_with_valid_gzip_is_still_caught_by_the_stored_hash(self):
        path = self.vault.root / "t1" / "g1.bc26"
        path.write_bytes(gzip.compress(b"a different but valid replay"))
        with self.assertRaises(R.Unavailable):
            R.fetch_replay(self.vault, "g1", PART)

    def test_deleted_file_is_unavailable(self):
        (self.vault.root / "t1" / "g1.bc26").unlink()
        with self.assertRaises(R.Unavailable):
            R.fetch_replay(self.vault, "g1", ADMIN)
        self.assertEqual(self.snap()["incidents"][0]["incident_type"], "replay_file_damaged")


class Archive(Base):
    def setUp(self):
        super().setUp()
        for m in ("g1", "g2", "g3"):
            self.put(m)
        self.put("h1", tid="t2")

    def test_archive_deletes_files_and_nobody_can_get_them_back(self):
        out = R.archive_tournament(self.vault, "t1", "admin-1")
        self.assertEqual(out["status"], "archived")
        self.assertTrue(out["replays_deleted"])
        self.assertFalse((self.vault.root / "t1").exists())
        for viewer in (ADMIN, ORG, PART):
            with self.subTest(viewer=viewer.role):
                with self.assertRaises(R.Gone):
                    R.fetch_replay(self.vault, "g1", viewer)
        with self.assertRaises(R.NotFound):                          # no access: still the safe answer
            R.fetch_replay(self.vault, "g1", OTHER_PART)
        s = self.snap()
        self.assertEqual({r["status"] for m, r in s["replays"].items() if r["tournament_id"] == "t1"}, {"purged"})
        self.assertTrue(all(r["storage_key"] is None and r["deleted_at"] for m, r in s["replays"].items() if m != "h1"))
        self.assertEqual(s["tournaments"]["t1"]["purge"]["deleted"], 3)
        self.assertEqual(s["tournaments"]["t1"]["archived_by"], "admin-1")

    def test_other_tournaments_are_untouched(self):
        R.archive_tournament(self.vault, "t1", "admin-1")
        self.assertEqual(R.fetch_replay(self.vault, "h1", R.Viewer("participant", frozenset({"t2"}))).match_id, "h1")
        self.assertEqual(self.files("t2"), ["h1.bc26"])

    def test_archive_holds_the_tournament_purge_lock_during_file_removal(self):
        real_purge = R._purge_files

        def purge(vault, tid):
            lock_path = vault.index.path.with_name(f".{vault.index.path.name}.{tid}.purge.lock")
            with lock_path.open("a+") as competing_lock:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(competing_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return real_purge(vault, tid)

        with patch.object(R, "_purge_files", side_effect=purge):
            self.assertTrue(R.archive_tournament(self.vault, "t1", "admin-1")["replays_deleted"])
        self.assertEqual(R.purge_pending(self.vault), [])
        self.assertEqual(self.files("t2"), ["h1.bc26"])

    def test_archive_twice_is_harmless_and_sweeps_again(self):
        R.archive_tournament(self.vault, "t1", "admin-1")
        first = self.snap()["tournaments"]["t1"]
        (self.vault.root / "t1").mkdir()                            # a restored backup brings a file back
        (self.vault.root / "t1" / "g1.bc26").write_bytes(gzip.compress(b"back from the dead"))
        out = R.archive_tournament(self.vault, "t1", "someone-else")
        self.assertTrue(out["replays_deleted"])
        self.assertFalse((self.vault.root / "t1").exists())
        after = self.snap()["tournaments"]["t1"]
        self.assertEqual(after["archived_by"], first["archived_by"])    # who archived is not rewritten
        self.assertEqual(after["archived_at"], first["archived_at"])
        with self.assertRaises(R.Gone):
            R.fetch_replay(self.vault, "g1", ADMIN)

    def test_maintenance_purges_files_restored_after_a_completed_archive(self):
        folder = self.vault.root / "t1"
        backup = self.root / "backup"
        shutil.copytree(folder, backup)
        self.assertTrue(R.archive_tournament(self.vault, "t1", "a")["replays_deleted"])
        before = self.snap()
        shutil.copytree(backup, folder)

        with self.assertRaises(R.Gone):
            R.fetch_replay(self.vault, "g1", ADMIN)
        self.assertEqual(R.purge_pending(self.vault), ["t1"])
        self.assertFalse(folder.exists())
        self.assertEqual(self.files("t2"), ["h1.bc26"])
        after = self.snap()
        self.assertEqual(after["replays"], before["replays"])
        purge = after["tournaments"]["t1"]["purge"]
        self.assertEqual(purge["status"], R.PURGE_DONE)
        self.assertEqual(purge["swept"], 3)
        self.assertEqual(R.purge_pending(self.vault), [])
        self.assertEqual(self.snap(), after)

    def test_maintenance_records_a_restored_dangling_link_as_a_failure(self):
        R.archive_tournament(self.vault, "t1", "a")
        folder = self.vault.root / "t1"
        folder.symlink_to(self.root / "missing")

        self.assertEqual(R.purge_pending(self.vault), [])
        self.assertTrue(folder.is_symlink())
        state = self.snap()
        self.assertEqual(state["tournaments"]["t1"]["purge"]["status"], R.PURGE_FAILED)
        self.assertEqual([i["incident_type"] for i in state["incidents"]], ["purge_failed"])

    def test_unrecorded_files_in_the_folder_are_swept_too(self):
        (self.vault.root / "t1" / ".incoming-x.part").write_bytes(b"left by a crashed copy")
        (self.vault.root / "t1" / "notes").mkdir()
        (self.vault.root / "t1" / "notes" / "x").write_bytes(b"?")
        out = R.archive_tournament(self.vault, "t1", "a")
        self.assertTrue(out["replays_deleted"])
        self.assertEqual(out["purge"]["swept"], 2)
        self.assertFalse((self.vault.root / "t1").exists())

    def test_nothing_new_is_stored_after_archive(self):
        R.archive_tournament(self.vault, "t1", "a")
        p = self.make()
        with self.assertRaises(R.ArchivedRefused):
            R.register_replay(self.vault, "t1", "late", p, sha(p))
        self.assertFalse((self.vault.root / "t1").exists())
        self.assertNotIn("late", self.snap()["replays"])
        # a worker that finishes late through the result path gets the same refusal, not a quiet incident
        with self.assertRaises(R.ArchivedRefused):
            R.register_from_result(self.vault, "t1", "late2", {"replay": str(p), "replay_sha256": sha(p)})

    def test_archive_of_a_tournament_with_no_replays(self):
        out = R.archive_tournament(self.vault, "empty-one", "a")
        self.assertTrue(out["replays_deleted"])

    def test_purge_requires_archive(self):
        with self.assertRaises(R.ReplayError):
            R.purge_tournament(self.vault, "t1")
        self.assertEqual(self.files(), ["g1.bc26", "g2.bc26", "g3.bc26"])
        with self.assertRaises(R.ReplayError):
            R.archive_tournament(self.vault, "t1", "")

    def test_a_crash_between_marking_and_deleting_is_finished_by_purge_pending(self):
        with self.vault.index.transaction() as state:               # what a crash after step 1 leaves behind
            rec = R._tournament(state, "t1", 0)
            rec.update({"status": "archived", "archived_at": "x", "archived_by": "a"})
        for viewer in (ADMIN, PART):                                # already not served
            with self.assertRaises(R.Gone):
                R.fetch_replay(self.vault, "g1", viewer)
        self.assertEqual(self.files(), ["g1.bc26", "g2.bc26", "g3.bc26"])
        self.assertEqual(R.purge_pending(self.vault), ["t1"])
        self.assertFalse((self.vault.root / "t1").exists())
        self.assertEqual(R.purge_pending(self.vault), [])

    @unittest.skipIf(os.geteuid() == 0, "root ignores directory permissions")
    def test_a_failed_delete_is_reported_not_claimed_and_retried(self):
        folder = self.vault.root / "t1"
        os.chmod(folder, 0o500)                                      # files cannot be removed
        try:
            out = R.archive_tournament(self.vault, "t1", "a")
            self.assertFalse(out["replays_deleted"])
            self.assertEqual(out["purge"]["status"], "failed")
            s = self.snap()
            self.assertEqual([i["incident_type"] for i in s["incidents"]], ["purge_failed"])
            with self.assertRaises(R.Gone):                          # never served, even though the file is there
                R.fetch_replay(self.vault, "g1", ADMIN)
            self.assertEqual(R.purge_pending(self.vault), [])        # still failing: no false completion
            self.assertEqual(len(self.snap()["incidents"]), 1)       # and no pile of incidents
        finally:
            os.chmod(folder, 0o700)
        self.assertEqual(R.purge_pending(self.vault), ["t1"])
        self.assertFalse(folder.exists())
        s = self.snap()
        self.assertEqual(s["tournaments"]["t1"]["purge"]["status"], "done")
        self.assertEqual(s["incidents"][0]["status"], "resolved")

    def test_a_link_in_place_of_the_folder_is_not_followed_by_the_purge(self):
        shutil.rmtree(self.vault.root / "t1")
        precious = self.root / "precious"
        precious.mkdir()
        (precious / "keep.txt").write_text("keep")
        (self.vault.root / "t1").symlink_to(precious)
        out = R.archive_tournament(self.vault, "t1", "a")
        self.assertFalse(out["replays_deleted"])
        self.assertEqual((precious / "keep.txt").read_text(), "keep")

    def test_archive_between_the_copy_and_the_record_refuses_and_leaves_nothing(self):
        """Deterministic version of the race: the archive lands after the copy was made and checked."""
        p = self.make()
        real = R._sha256_and_check
        fired = []

        def hooked(path, limit):
            out = real(path, limit)
            if Path(path).name.startswith(".incoming-") and not fired:
                fired.append(True)
                R.archive_tournament(self.vault, "t3", "a")          # the copy exists; the archive purges
            return out

        R._sha256_and_check = hooked
        try:
            with self.assertRaises(R.ArchivedRefused):
                R.register_replay(self.vault, "t3", "late", p, sha(p))
        finally:
            R._sha256_and_check = real
        self.assertTrue(fired)
        self.assertFalse((self.vault.root / "t3").exists())
        self.assertNotIn("late", self.snap()["replays"])

    def test_registering_while_archiving_never_leaves_a_file(self):
        """The two steps meet under one lock: either a replay is stored and then deleted, or it is refused."""
        for round_ in range(8):
            tid = f"race{round_}"
            sources = [self.make() for _ in range(12)]
            errors = []

            def worker(i):
                try:
                    R.register_replay(self.vault, tid, f"{tid}-m{i}", sources[i], None)
                except R.ArchivedRefused:
                    pass
                except Exception as e:                               # anything else is a bug
                    errors.append(repr(e))

            threads = [threading.Thread(target=worker, args=(i,)) for i in range(12)]
            for t in threads[:6]:
                t.start()
            archiver = threading.Thread(target=lambda: R.archive_tournament(self.vault, tid, "a"))
            archiver.start()
            for t in threads[6:]:
                t.start()
            for t in threads + [archiver]:
                t.join()
            self.assertEqual(errors, [])
            R.purge_pending(self.vault)
            self.assertFalse((self.vault.root / tid).exists(), f"round {round_}")
            self.assertFalse([r for r in self.snap()["replays"].values()
                              if r["tournament_id"] == tid and r["status"] != "purged"], f"round {round_}")


class WithTheBracket(Base):
    """The replays of a whole tournament, and what an archive must not touch."""

    def fake_run(self, ctx):
        side = "A" if ctx.team_a < ctx.team_b else "B"
        p = self.out / f"{ctx.match_id}.bc26"
        p.write_bytes(gzip.compress(ctx.match_id.encode() * 300))
        res = won(side)
        res.update({"replay": str(p), "replay_sha256": sha(p)})
        return res

    def play(self, n=4):
        store = JsonFileStore(self.root / "state.json")
        B.create_bracket(store, "b1", teams(n), MAPS, rng=random.Random(3))
        for r in range(1, len(B.get_bracket(store, "b1")["rounds"]) + 1):
            B.start_round(store, "b1", r, "org")
            B.run_round(store, "b1", r, self.fake_run, owner="w", sleep=lambda s: None)
        return store

    def test_collect_registers_every_game_once(self):
        store = self.play(4)
        out = R.collect_bracket(self.vault, store, "t1", "b1")
        self.assertEqual(out, {"stored": 3, "already_known": 0})
        self.assertEqual(R.collect_bracket(self.vault, store, "t1", "b1"), {"stored": 0, "already_known": 3})
        self.assertEqual(len(self.files()), 3)

    def test_games_of_a_tied_series_each_get_their_replay(self):
        store = JsonFileStore(self.root / "state.json")
        B.create_bracket(store, "b2", teams(2), MAPS, rng=random.Random(1))
        n = {"i": 0}

        def run(ctx):
            n["i"] += 1
            p = self.out / f"{ctx.match_id}.bc26"
            p.write_bytes(gzip.compress(ctx.match_id.encode() * 300))
            res = won("A", COIN if ctx.match_id.endswith("-g0") else DECISIVE)
            res.update({"replay": str(p), "replay_sha256": sha(p)})
            return res

        B.start_round(store, "b2", 1, "org")
        B.run_round(store, "b2", 1, run, owner="w", sleep=lambda s: None, coin=lambda: "A")
        out = R.collect_bracket(self.vault, store, "t1", "b2")
        self.assertEqual(out["stored"], 4)                           # the game plus three final tie-break games
        self.assertEqual(len(self.files()), 4)

    def test_archive_removes_replays_and_leaves_results_brackets_and_history(self):
        store = self.play(4)
        R.collect_bracket(self.vault, store, "t1", "b1")
        before = store.snapshot()
        R.archive_tournament(self.vault, "t1", "admin")
        self.assertEqual(store.snapshot(), before)                   # match store byte for byte the same
        b = B.get_bracket(store, "b1")
        self.assertEqual(b["status"], "completed")
        self.assertIn(b["champion"], [t["team"] for t in teams(4)])
        self.assertEqual(self.files(), [])
        with self.assertRaises(R.Gone):
            R.fetch_replay(self.vault, "b1-r1-m0-g0", ADMIN)

    def test_one_missing_replay_does_not_stop_the_others(self):
        store = self.play(4)
        first = next(iter(sorted(self.out.glob("b1-r1-*.bc26"))))
        first.unlink()
        out = R.collect_bracket(self.vault, store, "t1", "b1")
        self.assertEqual(out["stored"], 2)
        s = self.snap()
        self.assertEqual(sorted(r["status"] for r in s["replays"].values()), ["available", "available", "unavailable"])
        self.assertEqual([i["incident_type"] for i in s["incidents"]], ["replay_unavailable"])

    def test_unknown_bracket(self):
        store = self.play(2)
        with self.assertRaises(R.ReplayError):
            R.collect_bracket(self.vault, store, "t1", "nope")


@unittest.skipUnless(os.environ.get("BIO_INTEGRATION") == "1", "set BIO_INTEGRATION=1 to play a real match")
class RealReplay(unittest.TestCase):
    def test_real_engine_replay_is_stored_served_and_purged(self):
        from backend.match_runner import launcher as L
        py = L.resolve_python(None, None, L.load_lock())
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bots = root / "bots"
            bots.mkdir()
            for n in (1, 2):
                shutil.copytree(L.DEFAULT_SCAFFOLD / "src" / "examplefuncsplayer_py", bots / f"sub-{n:02d}-v1")
            store = JsonFileStore(root / "state.json")
            vault = R.Vault(root / "vault", R.ReplayIndex(root / "replays.json"))
            B.create_bracket(store, "real", teams(2), {"play": ["DefaultSmall"], "tiebreak_normal": ["DefaultSmall"],
                                                       "tiebreak_final": ["DefaultSmall"] * 3}, rng=random.Random(5))
            run_fn = O.launcher_run_fn(L.DEFAULT_SCAFFOLD, py, bots, root / "out", timeout=180, lock_path=root / "host.lock")
            B.start_round(store, "real", 1, "org-1")
            self.assertEqual(B.run_round(store, "real", 1, run_fn, owner="w", sleep=lambda s: None)["status"], "completed")
            out = R.collect_bracket(vault, store, "t1", "real")
            self.assertGreaterEqual(out["stored"], 1)
            self.assertEqual(sorted(vault.index.snapshot()["incidents"], key=str), [])
            mid = next(iter(vault.index.snapshot()["replays"]))
            h = R.fetch_replay(vault, mid, R.Viewer("participant", frozenset({"t1"})))
            with gzip.open(h.path, "rb") as g:                      # the engine's file really is gzip, to the end
                self.assertGreater(len(g.read()), 1000)
            self.assertTrue(R.archive_tournament(vault, "t1", "admin")["replays_deleted"])
            with self.assertRaises(R.Gone):
                R.fetch_replay(vault, mid, ADMIN)
            self.assertEqual(B.get_bracket(store, "real")["status"], "completed")


if __name__ == "__main__":
    unittest.main()
