# SPDX-License-Identifier: AGPL-3.0-only
"""Tournament map pools: which maps are played and which are the tie-break maps (BIO-303/304; CN-014).

PRD 6.4 / SRD-024..025, DATA_MODEL "TournamentMap" (map files are immutable by version; normal tie-break
count = 1, final = 3), TEST_PLAN TC-05 ("predefined tie-breaker maps"). `tiebreak.py` and `bracket.py` take
plain map names; this module is where those names come from and where they are checked.

What it does
  * `load_engine_maps` reads the maps that ship inside the pinned engine jar (names and SHA-256 of each
    `.map26` file). The jar is only read as a zip: nothing is extracted or run.
  * `create_pool` stores a named pool: the maps played in the rounds, one tie-break map for a normal tie and
    three for a final tie. Every name must exist in the catalogue; the engine version and each map's SHA-256
    are pinned in the pool. A pool is never edited: a different map set is a different pool id, so a match
    always names the exact map version it was played on (SRD-012). Same content again returns the stored
    pool; different content under the same id is a conflict.
  * `verify_pool` compares a pool with a catalogue (map missing, file changed, engine version changed) and
    returns the problems; it changes nothing.
  * `create_bracket_from_pool` verifies the pool and then draws the bracket with its maps.

Rules chosen here (CN-014): the maps played and the tie-break maps must be different maps (a tie that is
"broken" on a map the two teams already played is not a new test); the three final tie-break maps are
distinct; names in one list do not repeat.

NOT here: custom maps uploaded by an Organizer (their file would be hostile input: size, format and
validation are not designed), who may choose a pool (the API checks that), tournament storage, a map preview.
"""
from __future__ import annotations

import copy
import hashlib
import re
import time
import zipfile
from pathlib import Path
from typing import Callable

from backend.match_orchestrator import bracket as B
from backend.match_orchestrator import orchestrator as O
from backend.match_orchestrator.orchestrator import OrchestratorError
from backend.match_orchestrator.store import JsonFileStore
from backend.match_runner.match_log import REF_RE

RESOURCE_DIR = "battlecode/world/resources/"
SUFFIX = ".map26"
# The engine takes a comma-separated list of map names, so a name must never contain a comma.
NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
MAX_MAP_BYTES = 5 * 1024 * 1024
MAX_MAPS = 500
MAX_PLAY_MAPS = 50
MAX_POOL_ID = 40
ENGINE_VERSION_RE = re.compile(r"^[A-Za-z0-9._-]{1,40}$")


class MapError(OrchestratorError):
    pass


def load_engine_maps(jar: Path) -> dict[str, str]:
    """{map name: sha256 of the .map26 file} for the maps inside the engine jar.

    Entries with an unusable name are skipped; an entry larger than MAX_MAP_BYTES (declared or actual) or more
    than MAX_MAPS maps is an error, not a silent truncation.
    """
    catalogue: dict[str, str] = {}
    try:
        zf = zipfile.ZipFile(jar)
    except (OSError, zipfile.BadZipFile) as e:
        raise MapError(f"cannot read the engine jar: {e}") from e
    with zf:
        for info in zf.infolist():
            name = info.filename
            if not name.startswith(RESOURCE_DIR) or not name.endswith(SUFFIX) or info.is_dir():
                continue
            stem = name[len(RESOURCE_DIR):-len(SUFFIX)]
            if not NAME_RE.match(stem):
                continue                      # also drops nested folders (a "/" is not allowed)
            if info.file_size > MAX_MAP_BYTES:
                raise MapError(f"engine map {stem} is larger than {MAX_MAP_BYTES} bytes")
            with zf.open(info) as f:
                data = f.read(MAX_MAP_BYTES + 1)
            if len(data) > MAX_MAP_BYTES:
                raise MapError(f"engine map {stem} is larger than {MAX_MAP_BYTES} bytes")
            if stem in catalogue:
                raise MapError(f"engine jar holds map {stem} twice")
            catalogue[stem] = hashlib.sha256(data).hexdigest()
            if len(catalogue) > MAX_MAPS:
                raise MapError(f"engine jar holds more than {MAX_MAPS} maps")
    return catalogue


def _check_list(label: str, names, want: int | None, catalogue: dict) -> list[str]:
    if not isinstance(names, (list, tuple)) or not names or (want is not None and len(names) != want) \
            or (want is None and len(names) > MAX_PLAY_MAPS):
        raise MapError(f"{label} needs " + (f"exactly {want}" if want else f"1 to {MAX_PLAY_MAPS}") + " map name(s)")
    for n in names:
        if not isinstance(n, str) or not NAME_RE.match(n):
            raise MapError(f"{label}: map names must match {NAME_RE.pattern}")
        if n not in catalogue:
            raise MapError(f"{label}: map {n!r} is not in the engine's map catalogue")
    if len(set(names)) != len(names):
        raise MapError(f"{label}: a map is listed twice")
    return list(names)


def create_pool(store: JsonFileStore, pool_id: str, catalogue: dict[str, str], engine_version: str, *,
                play: list[str], tiebreak_normal: list[str], tiebreak_final: list[str],
                now: Callable[[], float] = time.time) -> dict:
    """Store a map pool (never edited afterwards). Same content again returns it; different content is a conflict."""
    if not isinstance(pool_id, str) or not REF_RE.match(pool_id) or len(pool_id) > MAX_POOL_ID:
        raise MapError(f"pool_id must match {REF_RE.pattern} and be at most {MAX_POOL_ID} characters")
    if not isinstance(engine_version, str) or not ENGINE_VERSION_RE.match(engine_version):
        raise MapError(f"engine_version must match {ENGINE_VERSION_RE.pattern}")
    maps = {
        "play": _check_list("play", play, None, catalogue),
        "tiebreak_normal": _check_list("tiebreak_normal", tiebreak_normal, 1, catalogue),
        "tiebreak_final": _check_list("tiebreak_final", tiebreak_final, 3, catalogue),
    }
    overlap = set(maps["play"]) & (set(maps["tiebreak_normal"]) | set(maps["tiebreak_final"]))
    if overlap:
        raise MapError("a tie-break map must not also be a played map: " + ", ".join(sorted(overlap)))
    pins = {n: catalogue[n] for lst in maps.values() for n in lst}
    identity = {"engine_version": engine_version, "maps": maps, "sha256": pins}
    with store.transaction() as state:
        pools = state.setdefault("map_pools", {})
        existing = pools.get(pool_id)
        if existing is not None:
            if {k: existing[k] for k in identity} != identity:
                raise O.ConflictError(f"map pool {pool_id} already exists with different maps; use a new pool id")
            return copy.deepcopy(existing)
        pool = {"id": pool_id, **identity, "created_at": O._now_iso(now())}
        pools[pool_id] = pool
        return copy.deepcopy(pool)


def get_pool(store: JsonFileStore, pool_id: str) -> dict:
    pool = store.snapshot().get("map_pools", {}).get(pool_id)
    if pool is None:
        raise MapError(f"unknown map pool {pool_id}")
    return pool


def pool_maps(pool: dict) -> dict:
    """The `maps` argument of `bracket.create_bracket`."""
    return copy.deepcopy(pool["maps"])


def verify_pool(pool: dict, catalogue: dict[str, str], engine_version: str) -> list[str]:
    """Problems found comparing the pool with the catalogue of the engine that will play it (empty = fine)."""
    problems = []
    if pool["engine_version"] != engine_version:
        problems.append(f"pool was made for engine {pool['engine_version']}, running engine is {engine_version}")
    for name, digest in sorted(pool["sha256"].items()):
        have = catalogue.get(name)
        if have is None:
            problems.append(f"map {name} is missing from the engine")
        elif have != digest:
            problems.append(f"map {name} changed since the pool was made")
    return problems


def create_bracket_from_pool(store: JsonFileStore, bracket_id: str, teams: list[dict], pool_id: str,
                             catalogue: dict[str, str], engine_version: str, **kw) -> dict:
    """Verify the pool against the running engine, then draw the bracket with its maps.

    The bracket stores the map names and the pool id, so the exact map files can be found again.
    """
    pool = verified_pool(store, pool_id, catalogue, engine_version)
    bracket = B.create_bracket(store, bracket_id, teams, pool_maps(pool), **kw)
    with store.transaction() as state:
        stored = state["brackets"][bracket_id]
        if stored.get("map_pool") not in (None, pool_id):
            raise O.ConflictError(f"bracket {bracket_id} was made with map pool {stored['map_pool']}")
        stored["map_pool"] = pool_id
        bracket = copy.deepcopy(stored)
    return bracket


def verified_pool(store: JsonFileStore, pool_id: str, catalogue: dict[str, str], engine_version: str) -> dict:
    """Return the immutable pool when every pinned map matches the current engine."""
    pool = get_pool(store, pool_id)
    problems = verify_pool(pool, catalogue, engine_version)
    if problems:
        raise MapError("map pool does not match the engine: " + "; ".join(problems))
    return pool
