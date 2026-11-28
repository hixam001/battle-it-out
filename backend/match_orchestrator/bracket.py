# SPDX-License-Identifier: AGPL-3.0-only
"""Single-elimination bracket, automatic byes and the Organizer-started round runner (BIO-302, BIO-303; CN-011).

PRD 6.4 / SRD-020..023, APP_FLOW FLOW-05, TEST_PLAN TC-05. Built on `tiebreak.py` (each pairing is a series
of games, so ties, tie-break maps, the coin flip, platform retry and bot forfeits all work as before).

What it does
  * `create_bracket` draws the bracket ONCE, at random, and records the draw (who meets whom, who has a
    bye). The bracket is a fixed tree of size 2**k: round 1 has `size - N` byes, each in a different pair, so
    no round after the first has a bye and a bye never meets another bye.
  * Byes go to human teams (SRD-021). The last round is the final (3 tie-break maps); earlier rounds are
    normal (1 tie-break map).
  * `start_round` is the Organizer's action: a round starts only when the previous one is complete.
    `run_round` then plays its matches one after another and advances each winner exactly once.
  * A result is read from the finished series, so repeating a job, a second worker or a crash between
    "result recorded" and "winner advanced" cannot advance anyone twice or lose a winner: `settle` is
    idempotent.

NOT here: HOUSE BOTS (SRD-022). The placement algorithm is not defined (DEC-06: "needs approval and
proof-of-concept testing") and inventing one would decide who can win a tournament. A team that is not a
plain human team is refused. Also not here: who may start a round (the API checks that), qualification,
tournament and map storage, notifications.
"""
from __future__ import annotations

import copy
import os
import random
import time
import uuid
from typing import Callable

from backend.match_orchestrator import orchestrator as O
from backend.match_orchestrator import tiebreak as T
from backend.match_orchestrator.orchestrator import OrchestratorError
from backend.match_orchestrator.store import JsonFileStore
from backend.match_runner.match_log import REF_RE

MAX_TEAMS = 1024
MAX_BRACKET_ID = 40                    # series ids are "<bracket>-r<round>-m<index>" and must stay within 56
PENDING, READY, RUNNING, PAUSED, COMPLETED = "pending", "ready", "running", "paused", "completed"
IN_PROGRESS = "in_progress"


class BracketError(OrchestratorError):
    pass


def _size(n: int) -> int:
    size = 2
    while size < n:
        size *= 2
    return size


def series_id(bracket_id: str, round_no: int, index: int) -> str:
    return f"{bracket_id}-r{round_no}-m{index}"


def _get(state: dict, bracket_id: str) -> dict:
    b = state.get("brackets", {}).get(bracket_id)
    if b is None:
        raise BracketError(f"unknown bracket {bracket_id}")
    return b


def _note(b: dict, t: float, event: str, detail: str = "") -> None:
    b["history"].append({"at": O._now_iso(t), "event": event, "detail": detail[:O.MAX_TEXT]})


def create_bracket(store: JsonFileStore, bracket_id: str, teams: list[dict], maps: dict, *,
                   rng=None, max_attempts: int = O.DEFAULT_MAX_ATTEMPTS, now: Callable[[], float] = time.time) -> dict:
    """Draw and store a bracket. Calling it again with the same content returns the stored one (no new draw).

    `teams`: [{"team": ref, "submission": ref}] (human teams only; `submission` pins the bot version for every match).
    `maps`: {"play": [map, ...], "tiebreak_normal": [1 map], "tiebreak_final": [3 maps]}. Match `i` of round `r`
    is played on `play[(i + r - 1) % len(play)]`. `rng` needs `shuffle` and `sample` (default: the OS random source).
    """
    if not isinstance(bracket_id, str) or not REF_RE.match(bracket_id) or len(bracket_id) > MAX_BRACKET_ID:
        raise BracketError(f"bracket_id must match {REF_RE.pattern} and be at most {MAX_BRACKET_ID} characters")
    if not isinstance(teams, list) or not 2 <= len(teams) <= MAX_TEAMS:
        raise BracketError(f"a bracket needs 2 to {MAX_TEAMS} teams")
    entries = []
    for t in teams:
        if not isinstance(t, dict) or set(t) - {"team", "submission", "kind"}:
            raise BracketError("each team is {'team': ref, 'submission': ref}")
        if t.get("kind", "human") != "human":
            raise BracketError("house bots are not supported yet: their placement algorithm is undecided (DEC-06)")
        for k in ("team", "submission"):
            if not isinstance(t.get(k), str) or not REF_RE.match(t[k]):
                raise BracketError(f"{k} must match {REF_RE.pattern}")
        entries.append({"team": t["team"], "submission": t["submission"]})
    if len({e["team"] for e in entries}) != len(entries):
        raise BracketError("a team appears twice")
    if not isinstance(maps, dict) or set(maps) != {"play", "tiebreak_normal", "tiebreak_final"}:
        raise BracketError("maps needs exactly: play, tiebreak_normal, tiebreak_final")
    for key, want in (("play", None), ("tiebreak_normal", 1), ("tiebreak_final", 3)):
        v = maps[key]
        if not isinstance(v, list) or not v or (want and len(v) != want) \
                or not all(isinstance(m, str) and O.MAP_RE.match(m) for m in v):
            raise BracketError(f"maps[{key!r}] must be a list of map names" + (f" with exactly {want}" if want else ""))
    maps = {k: list(v) for k, v in maps.items()}
    identity = {"teams": entries, "maps": maps}
    rng = rng or random.SystemRandom()
    with store.transaction() as state:
        existing = state.get("brackets", {}).get(bracket_id)
        if existing is not None:
            if {k: existing[k] for k in identity} != identity:
                raise O.ConflictError(f"bracket {bracket_id} already exists with different teams or maps")
            return copy.deepcopy(existing)
        t = now()
        n = len(entries)
        size = _size(n)
        pairs = size // 2
        byes = size - n
        order = [e["team"] for e in entries]
        rng.shuffle(order)
        bye_pairs = set(rng.sample(range(pairs), byes))
        it = iter(order)
        round1 = []
        for i in range(pairs):
            a = next(it)
            b = None if i in bye_pairs else next(it)
            round1.append({"index": i, "a": a, "b": b, "bye": b is None, "series_id": None,
                           "winner": a if b is None else None, "loser": None, "result_type": "bye" if b is None else None})
        rounds = [{"number": 1, "status": READY, "started_by": None, "started_at": None, "completed_at": None,
                   "matches": round1}]
        count = pairs
        number = 1
        while count > 1:
            count //= 2
            number += 1
            rounds.append({"number": number, "status": PENDING, "started_by": None, "started_at": None,
                           "completed_at": None,
                           "matches": [{"index": i, "a": None, "b": None, "bye": False, "series_id": None,
                                        "winner": None, "loser": None, "result_type": None} for i in range(count)]})
        bracket = {
            "id": bracket_id, **identity, "max_attempts": max_attempts, "size": size, "status": IN_PROGRESS,
            "created_at": O._now_iso(t), "rounds": rounds, "champion": None,
            "draw": {"id": uuid.uuid4().hex, "drawn_at": O._now_iso(t), "teams": n, "size": size, "byes": byes,
                     "pairings": [[m["a"], m["b"]] for m in round1], "rerolls_allowed": False,
                     "method": "random.SystemRandom shuffle" if isinstance(rng, random.SystemRandom) else "injected rng"},
            "history": []}
        state.setdefault("brackets", {})[bracket_id] = bracket
        _note(bracket, t, "drawn", f"{n} teams, size {size}, {byes} bye(s)")
        return copy.deepcopy(bracket)


def get_bracket(store: JsonFileStore, bracket_id: str) -> dict:
    with store.transaction() as state:
        return copy.deepcopy(_get(state, bracket_id))


def _settle_in(state: dict, b: dict, t: float) -> None:
    """Read finished series into the bracket and advance winners. Idempotent: a match gets its winner once."""
    for rd in b["rounds"]:
        if rd["status"] not in (RUNNING, PAUSED):
            continue
        paused = False
        for m in rd["matches"]:
            if m["winner"] is not None or not m["series_id"]:
                continue
            s = state.get("series", {}).get(m["series_id"])
            if s is None:
                continue
            if s["status"] == T.COMPLETED:
                res = s["result"]
                if {res["winner_team"], res["loser_team"]} != {m["a"], m["b"]}:
                    raise BracketError(f"series {s['id']} finished with teams that are not the pairing")
                m.update({"winner": res["winner_team"], "loser": res["loser_team"], "result_type": res["result_type"]})
                if s["advancement"]["pending"]:
                    s["advancement"] = {"pending": False, "taken_at": O._now_iso(t)}   # the bracket took it, once
                _note(b, t, "advanced", f"round {rd['number']} match {m['index']}: {m['winner']} ({res['result_type']})")
            elif s["status"] == T.PAUSED:
                paused = True
        if all(m["winner"] is not None for m in rd["matches"]):
            rd["status"] = COMPLETED
            rd["completed_at"] = O._now_iso(t)
            _note(b, t, "round_completed", f"round {rd['number']}")
            nxt = b["rounds"][rd["number"]] if rd["number"] < len(b["rounds"]) else None
            if nxt is None:
                b["champion"] = rd["matches"][0]["winner"]
                b["status"] = COMPLETED
                _note(b, t, "champion", b["champion"])
            else:
                for j, m in enumerate(nxt["matches"]):
                    m["a"] = rd["matches"][2 * j]["winner"]
                    m["b"] = rd["matches"][2 * j + 1]["winner"]
                nxt["status"] = READY
        else:
            rd["status"] = PAUSED if paused else RUNNING


def settle(store: JsonFileStore, bracket_id: str, now: Callable[[], float] = time.time) -> dict:
    """Bring the bracket up to date with the series results. Safe to call at any time, from any worker."""
    with store.transaction() as state:
        b = _get(state, bracket_id)
        _settle_in(state, b, now())
        return copy.deepcopy(b)


def start_round(store: JsonFileStore, bracket_id: str, round_no: int, actor: str, *,
                now: Callable[[], float] = time.time) -> dict:
    """The Organizer starts a round. Allowed only when every earlier round is complete.

    Starting a round that is already running, paused or complete changes nothing. Who may call this is the
    API's decision (the assigned Organizer); this function records `actor`.
    """
    if not isinstance(actor, str) or not REF_RE.match(actor):
        raise BracketError(f"actor must match {REF_RE.pattern}")
    with store.transaction() as state:
        b = _get(state, bracket_id)
        _settle_in(state, b, now())
        if not isinstance(round_no, int) or isinstance(round_no, bool) or not 1 <= round_no <= len(b["rounds"]):
            raise BracketError(f"round must be 1 to {len(b['rounds'])}")
        rd = b["rounds"][round_no - 1]
        if rd["status"] == PENDING:
            raise BracketError(f"round {round_no} cannot start: round {round_no - 1} is not complete")
        if rd["status"] == READY:
            t = now()
            rd.update({"status": RUNNING, "started_by": actor, "started_at": O._now_iso(t)})
            _note(b, t, "round_started", f"round {round_no} by {actor}")
        return copy.deepcopy(rd)


def _stage(b: dict, round_no: int) -> tuple[str, list[str]]:
    final = round_no == len(b["rounds"])
    return ("final", b["maps"]["tiebreak_final"]) if final else ("normal", b["maps"]["tiebreak_normal"])


def run_round(store: JsonFileStore, bracket_id: str, round_no: int, run_fn: Callable[[O.AttemptContext], dict], *,
              owner: str | None = None, alert: Callable[[dict], None] | None = None,
              coin: Callable[[], str] | None = None, verify_map_pool: Callable[[str], None] | None = None,
              **job_kwargs) -> dict:
    """Play the matches of a started round one after another and advance each winner once.

    Returns {"status": round status, "ran": attempts run by this call, "skipped": reason or None}. Safe to call
    again or from several workers: finished matches are not replayed, and a match another worker holds is
    skipped (`running_elsewhere`). Stops when a game is paused (an operator must resume it, then call again).
    A configured worker verifies the pinned pool before running a round.
    """
    now = job_kwargs.get("now", time.time)
    owner = owner or f"worker-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    ran = 0
    with store.transaction() as state:
        b = _get(state, bracket_id)
        if not isinstance(round_no, int) or isinstance(round_no, bool) or not 1 <= round_no <= len(b["rounds"]):
            raise BracketError(f"round must be 1 to {len(b['rounds'])}")
        _settle_in(state, b, now())
        status = b["rounds"][round_no - 1]["status"]
        if status in (PENDING, READY):
            raise BracketError(f"round {round_no} has not been started by an Organizer")
        pool_id = b.get("map_pool")
    if status == RUNNING and pool_id is not None and verify_map_pool is not None:
        verify_map_pool(pool_id)
    skipped = None
    index = 0
    while True:
        with store.transaction() as state:
            b = _get(state, bracket_id)
            rd = b["rounds"][round_no - 1]
            todo = [m for m in rd["matches"] if m["winner"] is None]
            if rd["status"] == COMPLETED or not todo:
                break
            m = todo[0]
            stage, tb = _stage(b, round_no)
            entry = {e["team"]: e["submission"] for e in b["teams"]}
            args = (series_id(bracket_id, round_no, m["index"]), m["a"], m["b"],
                    b["maps"]["play"][(m["index"] + round_no - 1) % len(b["maps"]["play"])],
                    entry[m["a"]], entry[m["b"]], stage, tb)
            max_attempts = b["max_attempts"]
        T.create_series(store, *args, max_attempts=max_attempts, now=now)
        with store.transaction() as state:
            mm = _get(state, bracket_id)["rounds"][round_no - 1]["matches"][m["index"]]
            if mm["series_id"] is None:
                mm["series_id"] = args[0]
        out = T.run_series_job(store, args[0], run_fn, owner=owner, alert=alert, coin=coin, **job_kwargs)
        ran += out["ran"]
        settle(store, bracket_id, now)
        if out["status"] == T.PAUSED:
            break
        if out["skipped"] == "running_elsewhere":
            skipped = "running_elsewhere"
            break
        index += 1
        if index > MAX_TEAMS:
            raise BracketError("round did not settle")      # unreachable unless there is a bug
    final = get_bracket(store, bracket_id)["rounds"][round_no - 1]["status"]
    return {"status": final, "ran": ran, "skipped": skipped}


def public_view(bracket: dict) -> dict:
    """What authenticated tournament users may see: pairings, byes, winners and the champion. No host details."""
    return {
        "id": bracket["id"], "status": bracket["status"], "teams": [e["team"] for e in bracket["teams"]],
        "draw": {k: bracket["draw"][k] for k in ("drawn_at", "teams", "size", "byes", "rerolls_allowed")},
        "champion": bracket["champion"],
        "rounds": [{"number": r["number"], "status": r["status"],
                    "final": r["number"] == len(bracket["rounds"]),
                    "matches": [{"index": m["index"], "a": m["a"], "b": m["b"], "bye": m["bye"], "winner": m["winner"],
                                 "result_type": m["result_type"]} for m in r["matches"]]} for r in bracket["rounds"]]}
