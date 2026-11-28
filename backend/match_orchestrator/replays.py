# SPDX-License-Identifier: AGPL-3.0-only
"""Replay storage, access and purge at archive (BIO-305, BIO-REQ-08, SRD-070, TC-08, FLOW-06; CN-012).

What the requirements say: every match produces a replay; authenticated tournament users can get it until the
tournament is archived; at archive the files are deleted and nobody can get them back, Admin included;
results, brackets and history stay. What the engine gives us is one `.bc26` file per game (gzip), written to a
worker's output folder. Everything else here is ours.

  * `register_replay`  copy a finished game's replay into the vault, check its hash and that it is a complete
                       gzip, record it. Refused once the tournament is archived (a late worker must not
                       leave a file behind after the purge).
  * `collect_bracket`  register the replay of every finished game of a bracket, once each (safe to repeat).
  * `fetch_replay`     the access rule of the API: safe "not found" without access, "gone" after archive,
                       "unavailable" if the file is missing or damaged (and a staff incident is raised).
  * `open_replay`      return the verified binary stream for private HTTP delivery.
  * `archive_tournament` / `purge_tournament`  mark archived first, then delete the files, verify, record the
                       result. `purge_pending` finishes interrupted purges and checks for restored files.
                       A purge never touches the match, series or bracket records.

The caller derives the `Viewer` from authenticated scope. Backups, object storage (DEC-11), a browser player
(DEC-10) and notification delivery live outside this module.
Standard library only.
"""
from __future__ import annotations

import contextlib
import copy
import fcntl
import gzip
import hashlib
import os
import re
import shutil
import stat
import tempfile
import time
import uuid
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Callable

from . import orchestrator as O
from .store import JsonFileStore

INDEX_SCHEMA = 1
REPLAY_FORMAT = "bc26"                      # the engine's own format (DEC-10 recommendation, interim)
GZIP_MAGIC = b"\x1f\x8b"
# Not a product limit: only a ceiling so a broken worker cannot fill the disk. A real cap needs a benchmark.
SAFETY_MAX_BYTES = 512 * 1024 * 1024
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

AVAILABLE, UNAVAILABLE, PURGED = "available", "unavailable", "purged"
OPEN, ARCHIVED = "open", "archived"
PURGE_NONE, PURGE_RUNNING, PURGE_DONE, PURGE_FAILED = "none", "running", "done", "failed"


class ReplayError(Exception):
    """Base class; the API maps the subclasses to 404, 410, 409 and 503."""


class NotFound(ReplayError):
    """No such replay, or the viewer may not know about it (the same answer on purpose)."""


class Gone(ReplayError):
    """The tournament is archived: the file was deleted and cannot be retrieved by anyone."""


class Unavailable(ReplayError):
    """Should exist but cannot be served (missing or damaged file). A staff incident exists."""


class Refused(ReplayError):
    """Registration refused: unreadable or damaged file, or a conflicting replay."""


class ArchivedRefused(Refused):
    """Registration refused because the tournament is archived."""


@dataclass(frozen=True)
class Viewer:
    """Who is asking. The API layer fills it from the session; this module does not authenticate.

    role: "admin" (all tournaments), "organizer" (only `tournament_ids` = assigned), "participant" (only
    `tournament_ids` = tournaments where the user is on a registered team). Anything else sees nothing."""
    role: str
    tournament_ids: frozenset = frozenset()


def may_view(viewer: Viewer | None, tournament_id: str) -> bool:
    if viewer is None:
        return False
    if viewer.role == "admin":
        return True
    return viewer.role in ("organizer", "participant") and tournament_id in viewer.tournament_ids


@dataclass(frozen=True)
class ReplayHandle:
    match_id: str
    path: Path
    sha256: str
    size: int
    format: str


def _empty_index() -> dict:
    return {"schema": INDEX_SCHEMA, "replays": {}, "tournaments": {}, "incidents": []}


def _index_ok(state) -> bool:
    return isinstance(state, dict) and state.get("schema") == INDEX_SCHEMA \
        and all(isinstance(state.get(k), t) for k, t in (("replays", dict), ("tournaments", dict), ("incidents", list)))


class ReplayIndex(JsonFileStore):
    """The replay index: same lock, atomic write and 'a damaged file is never an empty one' rules as the
    match store, with its own layout. Replace with database tables later (DEC-11)."""
    _empty = staticmethod(_empty_index)
    _layout_ok = staticmethod(_index_ok)


def _check_id(kind: str, value) -> str:
    if not isinstance(value, str) or not ID_RE.fullmatch(value) or value.endswith(".") or ".." in value:
        raise Refused(f"{kind} {value!r} is not a safe identifier")
    return value


class Vault:
    """Files under `root/<tournament>/<match>.bc26`, folders 0700, files 0600, plus the index."""

    def __init__(self, root: Path, index: ReplayIndex):
        self.root = Path(root)
        self.index = index

    def _dir(self, tournament_id: str) -> Path:
        return self.root / _check_id("tournament", tournament_id)

    def _path(self, tournament_id: str, match_id: str) -> Path:
        # both ids are checked against ID_RE (no slash, no '..'), so the path cannot leave the vault
        return self._dir(tournament_id) / f"{_check_id('match', match_id)}.{REPLAY_FORMAT}"


def _iso(t: float) -> str:
    return O._now_iso(t)


def _tournament(state: dict, tournament_id: str, t: float) -> dict:
    rec = state["tournaments"].get(tournament_id)
    if rec is None:
        rec = {"id": tournament_id, "status": OPEN, "archived_at": None, "archived_by": None,
               "purge": {"status": PURGE_NONE, "started_at": None, "finished_at": None, "deleted": 0,
                         "swept": 0, "error": None, "attempts": 0}}
        state["tournaments"][tournament_id] = rec
    return rec


def _incident(state: dict, kind: str, tournament_id: str, match_id: str | None, detail: str, t: float) -> str:
    inc = {"id": uuid.uuid4().hex, "match_id": match_id, "tournament_id": tournament_id, "incident_type": kind,
           "attempt_count": None, "status": "open", "alerted_admin_at": None, "alert_error": None,
           "details_redacted": detail[:O.MAX_TEXT], "created_at": _iso(t), "resolved_at": None, "resolved_by": None}
    state["incidents"].append(inc)
    return inc["id"]


def _open_regular(path: Path | str, *, dir_fd: int | None = None) -> BinaryIO:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dir_fd)
    except OSError as e:
        raise Refused(f"cannot read the replay file ({type(e).__name__})") from e
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise Refused("the replay path is not a regular file")
        return os.fdopen(fd, "rb")
    except BaseException:
        os.close(fd)
        raise


def _hash_replay(f: BinaryIO, limit: int) -> tuple[str, int]:
    size = os.fstat(f.fileno()).st_size
    if size == 0:
        raise Refused("the replay file is empty")
    if size > limit:
        raise Refused(f"the replay file is larger than the safety ceiling ({limit} bytes)")
    digest = hashlib.sha256()
    read = 0
    for chunk in iter(lambda: f.read(1 << 20), b""):
        read += len(chunk)
        if read > limit:
            raise Refused(f"the replay file is larger than the safety ceiling ({limit} bytes)")
        digest.update(chunk)
    if size != read:
        raise Refused("the replay file changed size during verification")
    f.seek(0)
    return digest.hexdigest(), size


def _sha256_and_check(path: Path, limit: int) -> tuple[str, int]:
    """Hash and verify the complete gzip stream before registration."""
    with _open_regular(path) as f:
        digest, size = _hash_replay(f, limit)
        if f.read(2) != GZIP_MAGIC:
            raise Refused("the replay file is not in the engine's gzip format")
        f.seek(0)
        try:
            with gzip.GzipFile(fileobj=f, mode="rb") as g:   # reads to the end: a cut-off file raises EOFError
                while g.read(1 << 20):
                    pass
        except (EOFError, OSError, gzip.BadGzipFile, zlib.error) as e:
            raise Refused(f"the replay is cut off or damaged ({type(e).__name__})") from e
    return digest, size


def _require_unarchived(state: dict, tournament_id: str) -> None:
    rec = state["tournaments"].get(tournament_id)
    if rec and rec["status"] == ARCHIVED:
        raise ArchivedRefused(f"tournament {tournament_id} is archived; replays are no longer stored")


def register_replay(vault: Vault, tournament_id: str, match_id: str, source: Path | str, expected_sha256: str | None, *,
                    max_bytes: int = SAFETY_MAX_BYTES, now: Callable[[], float] = time.time) -> dict:
    """Copy a finished game's replay into the vault and record it. Idempotent for the same content.

    Refused if the tournament is archived, the file is missing, empty, cut off, not gzip, or its hash differs
    from the one the launcher recorded. A different replay for a game that already has one is refused: a
    result is recorded once. This primitive raises no incident; `register_from_result` does.
    """
    _check_id("tournament", tournament_id)
    _check_id("match", match_id)
    dest = vault._path(tournament_id, match_id)
    with vault.index.transaction() as state:
        _require_unarchived(state, tournament_id)
        existing = state["replays"].get(match_id)
    digest, size = _sha256_and_check(Path(source), max_bytes)
    if expected_sha256 is not None and digest != expected_sha256:
        raise Refused("the replay file does not match the hash the launcher recorded")
    if existing is not None:
        if existing["tournament_id"] != tournament_id or existing["sha256"] not in (None, digest):
            raise Refused(f"game {match_id} already has a different replay")
        if existing["status"] == AVAILABLE and dest.is_file():
            return copy.deepcopy(existing)           # same content again: nothing to do
    folder = dest.parent
    tmp = None
    try:
        with vault.index.transaction() as state:
            # Create the staging file before archive can mark the tournament and sweep its folder.
            _require_unarchived(state, tournament_id)
            vault.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            if folder.is_symlink():
                raise Refused("the replay folder is a link; refusing to write through it")
            folder.mkdir(exist_ok=True, mode=0o700)
            fd, tmp = tempfile.mkstemp(prefix=".incoming-", suffix=".part", dir=folder)
        with os.fdopen(fd, "wb") as out, open(source, "rb") as f:
            shutil.copyfileobj(f, out, 1 << 20)
            out.flush()
            os.fsync(out.fileno())
        os.chmod(tmp, 0o600)
        copied, _ = _sha256_and_check(Path(tmp), max_bytes)
        if copied != digest:
            raise Refused("the copy does not match the source (the source changed while copying)")
        with vault.index.transaction() as state:
            # the purge starts under this same lock, so either it already started (refuse, delete our copy)
            # or it cannot start until this record and file are both in place
            _require_unarchived(state, tournament_id)
            _tournament(state, tournament_id, now())
            os.replace(tmp, dest)
            t = now()
            state["replays"][match_id] = {
                "match_id": match_id, "tournament_id": tournament_id, "status": AVAILABLE,
                "storage_key": f"{tournament_id}/{dest.name}", "format": REPLAY_FORMAT, "sha256": digest,
                "bytes": size, "created_at": _iso(t), "deleted_at": None, "deletion_reason": None}
            return copy.deepcopy(state["replays"][match_id])
    except ArchivedRefused:
        raise
    except (OSError, Refused) as e:
        # The purge can unlink the staged copy while the writer is verifying it.
        with vault.index.transaction() as state:
            _require_unarchived(state, tournament_id)
        if isinstance(e, Refused):
            raise
        raise Refused(f"could not store the replay ({type(e).__name__})") from e
    finally:
        if tmp is not None:
            with contextlib.suppress(OSError):
                os.unlink(tmp)


def register_from_result(vault: Vault, tournament_id: str, match_id: str, result: dict | None, *,
                         now: Callable[[], float] = time.time) -> dict | None:
    """Register the replay a game's result points to. A result without a replay (a forfeit before the first
    round can leave none) raises no error and returns None; a missing or damaged file is an incident."""
    if not result or not result.get("replay"):
        return None
    try:
        return register_replay(vault, tournament_id, match_id, result["replay"], result.get("replay_sha256"), now=now)
    except ArchivedRefused:
        raise
    except Refused as e:
        with vault.index.transaction() as state:
            _require_unarchived(state, tournament_id)
            rec = state["replays"].get(match_id)
            t = now()
            if rec is None:
                state["replays"][match_id] = {
                    "match_id": match_id, "tournament_id": tournament_id, "status": UNAVAILABLE,
                    "storage_key": None, "format": REPLAY_FORMAT, "sha256": None, "bytes": None,
                    "created_at": _iso(t), "deleted_at": None, "deletion_reason": f"not stored: {e}"[:O.MAX_TEXT]}
            if not any(i["match_id"] == match_id and i["incident_type"] == "replay_unavailable" and i["status"] == "open"
                       for i in state["incidents"]):
                _incident(state, "replay_unavailable", tournament_id, match_id, str(e), t)
        return None


def _bracket_games(store: JsonFileStore, bracket_id: str) -> list[tuple[str, dict]]:
    """(game match id, its result) for every finished game of the bracket's series."""
    out = []
    with store.transaction() as state:
        b = state.get("brackets", {}).get(bracket_id)
        if b is None:
            raise ReplayError(f"unknown bracket {bracket_id}")
        for rd in b["rounds"]:
            for m in rd["matches"]:
                s = state.get("series", {}).get(m.get("series_id") or "")
                if not s:
                    continue
                for g in s["games"]:
                    game = state["matches"].get(g["match_id"])
                    if game and game.get("result"):
                        out.append((g["match_id"], copy.deepcopy(game["result"])))
    return out


def collect_bracket(vault: Vault, store: JsonFileStore, tournament_id: str, bracket_id: str, *,
                    now: Callable[[], float] = time.time) -> dict:
    """Register the replay of every finished game of the bracket that has none stored yet. Safe to call
    after every round and again later; returns counts."""
    stored = skipped = 0
    for match_id, result in _bracket_games(store, bracket_id):
        with vault.index.transaction() as state:
            have = state["replays"].get(match_id)
        if have and have["status"] in (AVAILABLE, UNAVAILABLE, PURGED):
            skipped += 1
            continue
        if register_from_result(vault, tournament_id, match_id, result, now=now) is not None:
            stored += 1
    return {"stored": stored, "already_known": skipped}


def _visible_replay(state: dict, match_id: str, viewer: Viewer | None) -> dict:
    if not isinstance(match_id, str) or not ID_RE.fullmatch(match_id):
        raise NotFound("no such replay")
    rep = state["replays"].get(match_id)
    if rep is None or not may_view(viewer, rep["tournament_id"]):
        raise NotFound("no such replay")
    return rep


def replay_tournament(vault: Vault, match_id: str, viewer: Viewer | None) -> str:
    """Resolve a visible replay's owner without opening the file or exposing its status."""
    with vault.index.transaction() as state:
        return _visible_replay(state, match_id, viewer)["tournament_id"]


def _available_replay(state: dict, match_id: str, viewer: Viewer | None, tournament_id: str | None) -> dict:
    rep = _visible_replay(state, match_id, viewer)
    tid = rep["tournament_id"]
    if tournament_id is not None and tournament_id != tid:
        raise NotFound("no such replay")
    trn = state["tournaments"].get(tid)
    if rep["status"] == PURGED or (trn and trn["status"] == ARCHIVED):
        raise Gone("the tournament is archived and its replays were deleted")
    if rep["status"] != AVAILABLE:
        raise Unavailable("the replay is not available")
    return rep


def _open_vault_file(vault: Vault, tid: str, match_id: str) -> BinaryIO:
    name = vault._path(tid, match_id).name
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    root_fd = os.open(vault.root, flags)
    try:
        folder_fd = os.open(tid, flags, dir_fd=root_fd)
        try:
            return _open_regular(name, dir_fd=folder_fd)
        finally:
            os.close(folder_fd)
    finally:
        os.close(root_fd)


def open_replay(vault: Vault, match_id: str, viewer: Viewer | None, *, tournament_id: str | None = None,
                now: Callable[[], float] = time.time) -> tuple[ReplayHandle, BinaryIO]:
    """Open and verify a visible replay. The caller owns the stream on success.

    A matching digest binds the stream to the gzip validated at registration.
    Check archive state again before handing the opened descriptor to the caller.
    """
    with vault.index.transaction() as state:
        rep = _available_replay(state, match_id, viewer, tournament_id)
    tid = rep["tournament_id"]
    stream = None
    try:
        stream = _open_vault_file(vault, tid, match_id)
        digest, size = _hash_replay(stream, SAFETY_MAX_BYTES)
        if digest != rep["sha256"] or size != rep["bytes"]:
            raise Refused("recorded replay digest or size differs")
        with vault.index.transaction() as state:
            current = _available_replay(state, match_id, viewer, tid)
            if current["sha256"] != digest:
                raise Unavailable("the replay changed while it was being opened")
        handle = ReplayHandle(match_id, vault._path(tid, match_id), digest, size, rep["format"])
        opened, stream = stream, None
        return handle, opened
    except (Refused, OSError) as e:
        with vault.index.transaction() as state:
            cur = _available_replay(state, match_id, viewer, tid)
            if cur["sha256"] == rep["sha256"]:
                cur["status"] = UNAVAILABLE
                cur["deletion_reason"] = f"file problem: {type(e).__name__}"
                _incident(state, "replay_file_damaged", tid, match_id, f"{type(e).__name__}: {e}", now())
        raise Unavailable("the replay is not available") from e
    finally:
        if stream is not None:
            stream.close()


def fetch_replay(vault: Vault, match_id: str, viewer: Viewer | None, *, now: Callable[[], float] = time.time) -> ReplayHandle:
    """Return the verified replay metadata for existing local callers."""
    handle, stream = open_replay(vault, match_id, viewer, now=now)
    stream.close()
    return handle


def _purge_files(vault: Vault, tournament_id: str) -> tuple[int, int, str | None]:
    """Delete every file under the tournament's folder, then check. Returns (recorded files deleted,
    unrecorded files swept, error)."""
    if vault.root.is_symlink():
        return 0, 0, "the replay vault root is a link; not touching it"
    folder = vault._dir(tournament_id)
    deleted = swept = 0
    try:
        mode = folder.lstat().st_mode
    except FileNotFoundError:
        return 0, 0, None
    except OSError as exc:
        return 0, 0, f"inspect folder: {type(exc).__name__}"
    if not stat.S_ISDIR(mode):
        return 0, 0, "the replay folder is not a plain folder; not touching it"
    with vault.index.transaction() as state:
        known = {Path(r["storage_key"]).name for r in state["replays"].values()
                 if r["tournament_id"] == tournament_id and r["storage_key"]}
    try:
        entries = sorted(folder.iterdir())
    except FileNotFoundError:
        return 0, 0, None
    except OSError as exc:
        return 0, 0, f"list folder: {type(exc).__name__}"
    errors = []
    for entry in entries:
        try:
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry)
                swept += 1
            else:
                entry.unlink()
                if entry.name in known:
                    deleted += 1
                else:
                    swept += 1
        except OSError as e:
            errors.append(f"{entry.name}: {type(e).__name__}")
    if not errors:
        try:
            folder.rmdir()
        except FileNotFoundError:
            pass
        except OSError as e:
            errors.append(f"folder: {type(e).__name__}")
    if not errors and folder.exists():
        errors.append("folder still exists")
    return deleted, swept, ("; ".join(errors)[:O.MAX_TEXT] if errors else None)


def purge_tournament(vault: Vault, tournament_id: str, *, now: Callable[[], float] = time.time) -> dict:
    """Delete the replay files of an ARCHIVED tournament, verify, and record the outcome. Idempotent and safe to
    repeat: it always sweeps the folder again, so files that came back (a restored backup, a stray copy) go too.
    Raises ReplayError if the tournament is not archived."""
    _check_id("tournament", tournament_id)
    # An archive request and scheduled maintenance can purge the same folder.
    # Serialize only that folder, keeping the index and other tournaments usable.
    lock_path = vault.index.path.with_name(f".{vault.index.path.name}.{tournament_id}.purge.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _purge_archived_tournament(vault, tournament_id, now)


def _purge_archived_tournament(vault: Vault, tournament_id: str, now: Callable[[], float]) -> dict:
    with vault.index.transaction() as state:
        rec = state["tournaments"].get(tournament_id)
        if rec is None or rec["status"] != ARCHIVED:
            raise ReplayError(f"tournament {tournament_id} is not archived; replays are only purged at archive")
        rec["purge"]["status"] = PURGE_RUNNING
        rec["purge"]["attempts"] += 1
        rec["purge"]["started_at"] = rec["purge"]["started_at"] or _iso(now())
    deleted, swept, error = _purge_files(vault, tournament_id)
    with vault.index.transaction() as state:
        rec = state["tournaments"][tournament_id]
        t = now()
        p = rec["purge"]
        p["deleted"] += deleted
        p["swept"] += swept
        p["error"] = error
        if error is None:
            p["status"] = PURGE_DONE
            p["finished_at"] = _iso(t)
            for r in state["replays"].values():
                if r["tournament_id"] == tournament_id and r["status"] != PURGED:
                    r.update({"status": PURGED, "storage_key": None, "deleted_at": _iso(t),
                              "deletion_reason": "tournament_archived"})
            for inc in state["incidents"]:       # a damaged file's incident has nothing left to look at
                if inc["tournament_id"] == tournament_id and inc["incident_type"] == "purge_failed" and inc["status"] == "open":
                    inc.update({"status": "resolved", "resolved_at": _iso(t), "resolved_by": "purge_tournament"})
        else:
            p["status"] = PURGE_FAILED
            if not any(i["tournament_id"] == tournament_id and i["incident_type"] == "purge_failed" and i["status"] == "open"
                       for i in state["incidents"]):
                _incident(state, "purge_failed", tournament_id, None, error, t)
        return copy.deepcopy(p)


def archive_tournament(vault: Vault, tournament_id: str, actor: str, *, now: Callable[[], float] = time.time) -> dict:
    """Mark the tournament archived (no replay is served or stored from this moment), then purge. Returns the
    API answer: `{"status": "archived", "replays_deleted": bool, ...}`. `replays_deleted` is true only after
    the folder was checked empty. If it is false the purge is retried by `purge_pending`."""
    _check_id("tournament", tournament_id)
    if not isinstance(actor, str) or not actor:
        raise ReplayError("archive needs the acting user")
    with vault.index.transaction() as state:
        rec = _tournament(state, tournament_id, now())
        if rec["status"] != ARCHIVED:
            rec.update({"status": ARCHIVED, "archived_at": _iso(now()), "archived_by": actor})
    purge = purge_tournament(vault, tournament_id, now=now)
    return {"status": "archived", "replays_deleted": purge["status"] == PURGE_DONE, "purge": purge}


def purge_pending(vault: Vault, *, now: Callable[[], float] = time.time) -> list[str]:
    """Finish interrupted purges and sweep files restored to archived tournaments.

    Returns the tournaments whose purge completed in this pass.
    """
    with vault.index.transaction() as state:
        archived = [(tid, r["purge"]["status"]) for tid, r in state["tournaments"].items()
                    if r["status"] == ARCHIVED]
    done = []
    for tid, status in archived:
        if status == PURGE_DONE:
            try:
                vault._dir(tid).lstat()
            except FileNotFoundError:
                continue
            except OSError:
                # The purge records an incident if the folder still cannot be inspected.
                pass
        if purge_tournament(vault, tid, now=now)["status"] == PURGE_DONE:
            done.append(tid)
    return done


def tournament_state(vault: Vault, tournament_id: str) -> dict | None:
    with vault.index.transaction() as state:
        return copy.deepcopy(state["tournaments"].get(tournament_id))


def replay_status(vault: Vault, match_id: str, viewer: Viewer | None, *, tournament_id: str | None = None) -> dict:
    """What a results page needs without serving the file: `available`, `unavailable` or `purged`.
    Same safe not-found rule as `fetch_replay`."""
    with vault.index.transaction() as state:
        rep = _visible_replay(state, match_id, viewer)
        if tournament_id is not None and rep["tournament_id"] != tournament_id:
            raise NotFound("no such replay")
        return {"match_id": match_id, "status": rep["status"], "format": rep["format"], "bytes": rep["bytes"]}
