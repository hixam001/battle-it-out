# SPDX-License-Identifier: AGPL-3.0-only
"""A small durable store for match jobs (BIO-301/306).

The product database is not chosen yet (DEC-11), so the orchestrator only needs three things from a
store: read-modify-write that is atomic across processes, durability across a crash, and a loud failure
when the data is damaged. `JsonFileStore` gives that with one JSON file, an exclusive `flock` and an
atomic rename. Replace it with a database transaction later; nothing else in the package touches files.

A damaged file is NEVER treated as an empty store: that would silently forget finished matches and run
them again.
"""
from __future__ import annotations

import contextlib
import copy
import fcntl
import json
import os
import tempfile
from pathlib import Path

SCHEMA = 1


class StoreError(Exception):
    """The store file is unreadable, damaged or from an unknown schema."""


def empty_state() -> dict:
    return {"schema": SCHEMA, "matches": {}, "incidents": []}


def _layout_ok(state) -> bool:
    return isinstance(state, dict) and state.get("schema") == SCHEMA \
        and isinstance(state.get("matches"), dict) and isinstance(state.get("incidents"), list)


class JsonFileStore:
    # Another kind of store file (the replay index) reuses the lock, atomic write and "never start from a
    # damaged file" rules by replacing these two.
    _empty = staticmethod(empty_state)
    _layout_ok = staticmethod(_layout_ok)

    def __init__(self, path: Path):
        self.path = Path(path)
        self.lock_path = self.path.with_name(self.path.name + ".lock")

    def _load(self) -> dict:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return self._empty()
        try:
            state = json.loads(raw)
        except ValueError as e:
            raise StoreError(f"{self.path} is not valid JSON ({e}); refusing to start from an empty store") from e
        if not self._layout_ok(state):
            raise StoreError(f"{self.path} has an unknown layout or schema (expected schema {SCHEMA})")
        return state

    def _save(self, state: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=self.path.name + ".", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=1, sort_keys=True)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise
        dir_fd = os.open(self.path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)

    @contextlib.contextmanager
    def transaction(self):
        """Yield the state; write it back only if the block ends without an exception.

        The lock is held for the whole block, across processes, so a check and the change that depends
        on it cannot be split by another worker.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.lock_path, "a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                state = self._load()
                before = copy.deepcopy(state)
                yield state
                if state != before:
                    self._save(state)
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def snapshot(self) -> dict:
        with self.transaction() as state:
            return copy.deepcopy(state)
