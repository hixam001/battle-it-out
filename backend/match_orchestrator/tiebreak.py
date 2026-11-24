# SPDX-License-Identifier: AGPL-3.0-only
"""Tie-break maps and the 50/50 coin flip (BIO-304; PRD 6.4, SCN-03, TEST_PLAN TC-05; CN-010).

A tournament match is a *series* of games. Each game is an ordinary match of `orchestrator.py`, so each one
gets the same platform retry, bot-failure forfeit, incident and exactly-once handling. The series adds:

  * game 0 on the scheduled map;
  * if game 0 is TIED: one predefined tie-break map in the normal stage, three in the final, played one
    after the other;
  * if the tie-break map(s) leave it tied: ONE automatic 50/50 coin flip, recorded once, never redrawn;
  * a bot failure in any game ends the series at once: the other team wins (no tie-break, no rematch);
  * the series result is handed to bracket advancement exactly once.

What is a "tie" (CN-010 D1). The engine has no tie result: when points, robots alive and cheese are all
equal it flips an UNSEEDED coin inside the game and still names a winner ("won arbitrarily (coin flip)").
That engine pick is the one thing the platform cannot audit or reproduce, so a game whose engine reason is
that coin flip counts as TIED and the engine's pick is never used. A game decided by the engine's own
ordered tie-breakers (points, robots alive, cheese) is decided.

Not here: where the tie-break maps come from (TournamentMap, BIO-303/EPIC-04), the bracket, replay storage
(BIO-305: `replays.py`), the audit log and the screen that shows the coin flip (this module only provides `public_view`).
"""
from __future__ import annotations

import copy
import os
import secrets
import time
import uuid
from typing import Callable

from backend.match_orchestrator import orchestrator as O
from backend.match_orchestrator.orchestrator import OrchestratorError
from backend.match_orchestrator.store import JsonFileStore
from backend.match_runner.match_log import REF_RE

# The exact line the engine prints for a coin flip (battlecode.server.Server, DominationFactor
# WON_BY_DUBIOUS_REASONS). The launcher keeps only an anchored engine line here (CN-007); a bot cannot forge it.
ENGINE_COIN_FLIP_REASON = "The winning team won arbitrarily (coin flip)."

STAGES = {"normal": 1, "final": 3}          # number of tie-break maps (DATA_MODEL "TournamentMap")
MAX_SERIES_ID = 56                          # children are named "<series id>-g<n>", at most 64 characters in all

SCHEDULED, IN_PROGRESS, PAUSED, COMPLETED = "scheduled", "in_progress", "paused", "completed"
# per-game outcome: decided (a side won on the engine's own rules), tied (engine coin flip), forfeit (bot failure)
DECIDED, TIED, FORFEIT = "decided", "tied", "forfeit"
RESULT_TYPES = ("normal", "tiebreak", "coin_flip", "bot_forfeit")
MAX_STEPS = 20                              # a series needs at most 1 + 3 games; anything more is a bug


class SeriesError(OrchestratorError):
    pass


def default_coin() -> str:
    """A fair 50/50 draw from the operating system's random source (not `random`, not the engine)."""
    return "A" if secrets.randbelow(2) == 0 else "B"


def game_id(series_id: str, index: int) -> str:
    return f"{series_id}-g{index}"


def create_series(store: JsonFileStore, series_id: str, team_a: str, team_b: str, map_name: str,
                  submission_a: str, submission_b: str, stage: str, tiebreak_maps: list[str], *,
                  max_attempts: int = O.DEFAULT_MAX_ATTEMPTS, now: Callable[[], float] = time.time) -> dict:
    """Create a series (and its first game). Calling it again with the same content returns the same series.

    `stage` is "normal" (exactly 1 tie-break map) or "final" (exactly 3). The maps are fixed here, before
    anything is played, so nobody can choose them after seeing the tie.
    """
    if not isinstance(series_id, str) or not REF_RE.match(series_id) or len(series_id) > MAX_SERIES_ID:
        raise SeriesError(f"series_id must match {REF_RE.pattern} and be at most {MAX_SERIES_ID} characters")
    if stage not in STAGES:
        raise SeriesError(f"stage must be one of {sorted(STAGES)}")
    if not isinstance(tiebreak_maps, (list, tuple)) or len(tiebreak_maps) != STAGES[stage] \
            or not all(isinstance(m, str) and O.MAP_RE.match(m) for m in tiebreak_maps):
        raise SeriesError(f"stage {stage!r} needs exactly {STAGES[stage]} tie-break map name(s)")
    maps = list(tiebreak_maps)
    identity = {"team_a": team_a, "team_b": team_b, "map": map_name, "submission_a": submission_a,
                "submission_b": submission_b, "stage": stage, "tiebreak_maps": maps}
    with store.transaction() as state:
        all_series = state.setdefault("series", {})
        existing = all_series.get(series_id)
        if existing is not None:
            if {k: existing[k] for k in identity} != identity:
                raise O.ConflictError(f"series {series_id} already exists with different content")
            return copy.deepcopy(existing)
        t = now()
        # validates the teams, submissions and map the same way a single match does
        first = O._create_in(state, game_id(series_id, 0), team_a, team_b, map_name, submission_a, submission_b,
                             max_attempts, t, series_game=True)
        series = {"id": series_id, **identity, "max_attempts": max_attempts, "status": SCHEDULED,
                  "created_at": O._now_iso(t), "games": [_new_game(0, "primary", map_name, first["id"])],
                  "coin_flip": None, "result": None, "advancement": {"pending": False, "taken_at": None},
                  "history": []}
        all_series[series_id] = series
        _note(series, t, "created", f"stage {stage}")
        return copy.deepcopy(series)


def _new_game(index: int, kind: str, map_name: str, match_id: str) -> dict:
    return {"index": index, "kind": kind, "map": map_name, "match_id": match_id, "outcome": None,
            "winner_side": None, "round": None, "reason": None, "replay": None, "replay_sha256": None,
            "structured_log": None, "engine_pick_ignored": None}


def _note(series: dict, t: float, event: str, detail: str = "") -> None:
    """Append-only history; the coin flip and every game outcome are in here, which is the audit trail."""
    series["history"].append({"at": O._now_iso(t), "event": event, "detail": detail[:O.MAX_TEXT]})


def _get_series(state: dict, series_id: str) -> dict:
    series = state.get("series", {}).get(series_id)
    if series is None:
        raise SeriesError(f"unknown series {series_id}")
    return series


def get_series(store: JsonFileStore, series_id: str) -> dict:
    with store.transaction() as state:
        return copy.deepcopy(_get_series(state, series_id))


def _absorb(series: dict, game: dict, match: dict, t: float) -> None:
    """Read the finished game's result into the series: decided, tied or forfeit."""
    res = match["result"]
    game.update({"winner_side": res["winner_side"], "round": res["round"], "reason": res["reason"],
                 "replay": res["replay"], "replay_sha256": res["replay_sha256"],
                 "structured_log": res["structured_log"]})
    if res["result_type"] == "bot_forfeit":
        game["outcome"] = FORFEIT
    elif isinstance(res["reason"], str) and res["reason"].strip() == ENGINE_COIN_FLIP_REASON:
        # The engine named a winner by its unseeded coin flip. Keep the pick for diagnosis, never use it.
        game.update({"outcome": TIED, "winner_side": None, "engine_pick_ignored": res["winner_side"]})
    else:
        game["outcome"] = DECIDED
    _note(series, t, "game_finished", f"game {game['index']} on {game['map']}: {game['outcome']}"
          + (f" ({game['winner_side']})" if game["winner_side"] else ""))


def _finish(series: dict, t: float, result_type: str, side: str, decided_by: int | None) -> None:
    winner = series["team_a" if side == "A" else "team_b"]
    loser = series["team_b" if side == "A" else "team_a"]
    series["result"] = {
        "result_type": result_type, "winner_side": side, "winner_team": winner, "loser_team": loser,
        "winner_submission": series["submission_a" if side == "A" else "submission_b"],
        "decided_by_game": decided_by, "games_played": len(series["games"]),
        "coin_flip_id": series["coin_flip"]["id"] if series["coin_flip"] else None}
    series["advancement"] = {"pending": True, "taken_at": None}
    series["status"] = COMPLETED
    _note(series, t, "completed", f"{result_type}: {winner}")


def _tally(series: dict) -> dict:
    wins = {"A": 0, "B": 0}
    for g in series["games"][1:]:
        if g["outcome"] == DECIDED:
            wins[g["winner_side"]] += 1
    return wins


def _flip(series: dict, t: float, coin: Callable[[], str]) -> str:
    """Draw the coin flip. Called at most once per series: only when `coin_flip` is still empty, inside the
    same transaction that stores it, so two workers cannot draw twice and nobody can ask again."""
    if series["coin_flip"] is not None:
        raise SeriesError("this series already has its coin flip; there are no rerolls")
    side = coin()
    if side not in ("A", "B"):
        raise SeriesError(f"the coin function returned {side!r}, not 'A' or 'B'; nothing was recorded")
    wins = _tally(series)
    series["coin_flip"] = {
        "id": uuid.uuid4().hex, "drawn_at": O._now_iso(t), "result_side": side,
        "result_team": series["team_a" if side == "A" else "team_b"],
        "tied_between": [series["team_a"], series["team_b"]], "games": [g["match_id"] for g in series["games"]],
        "tiebreak_wins": wins, "probability_each": 0.5, "rerolls_allowed": False,
        "method": "secrets.randbelow(2)" if coin is default_coin else "injected function"}
    _note(series, t, "coin_flip", f"{series['coin_flip']['result_team']} (still tied after {len(series['games'])} game(s))")
    return side


def advance_series(store: JsonFileStore, series_id: str, *, coin: Callable[[], str] | None = None,
                   now: Callable[[], float] = time.time) -> dict:
    """Move the series forward as far as it can go without playing a game; in ONE transaction.

    Returns {"action": "play", "match_id"} (that game must be run), {"action": "paused", "match_id"} (that game is
    paused: an operator must resume it) or {"action": "completed"}. Safe to call repeatedly and from many workers.
    """
    coin = coin or default_coin
    with store.transaction() as state:
        series = _get_series(state, series_id)
        t = now()
        for _ in range(MAX_STEPS):
            if series["status"] == COMPLETED:
                return {"action": "completed"}
            game = series["games"][-1]
            match = O._get(state, game["match_id"])
            if game["outcome"] is None:
                if match["status"] == O.COMPLETED:
                    _absorb(series, game, match, t)
                    continue
                if match["status"] == O.PAUSED:
                    if series["status"] != PAUSED:
                        series["status"] = PAUSED
                        _note(series, t, "paused", f"game {game['index']} is paused ({match['id']})")
                    return {"action": "paused", "match_id": match["id"]}
                if series["status"] != IN_PROGRESS:
                    series["status"] = IN_PROGRESS
                    _note(series, t, "in_progress", f"game {game['index']} on {game['map']}")
                return {"action": "play", "match_id": match["id"]}
            if game["outcome"] == FORFEIT:
                _finish(series, t, "bot_forfeit", game["winner_side"], game["index"])
            elif game["index"] == 0 and game["outcome"] == DECIDED:
                _finish(series, t, "normal", game["winner_side"], 0)
            elif len(series["games"]) <= len(series["tiebreak_maps"]):
                # tied so far: the next predefined tie-break map, in order
                nxt = len(series["games"])
                created = O._create_in(state, game_id(series_id, nxt), series["team_a"], series["team_b"],
                                       series["tiebreak_maps"][nxt - 1], series["submission_a"],
                                       series["submission_b"], series["max_attempts"], t, series_game=True)
                series["games"].append(_new_game(nxt, "tiebreak", created["map"], created["id"]))
                _note(series, t, "tiebreak_game", f"game {nxt} on {created['map']}")
            else:
                wins = _tally(series)
                if wins["A"] != wins["B"]:
                    side = "A" if wins["A"] > wins["B"] else "B"
                    _finish(series, t, "tiebreak", side, None)
                else:
                    _finish(series, t, "coin_flip", _flip(series, t, coin), None)
        raise SeriesError(f"series {series_id} did not settle in {MAX_STEPS} steps")  # unreachable unless there is a bug


def run_series_job(store: JsonFileStore, series_id: str, run_fn: Callable[[O.AttemptContext], dict], *,
                   owner: str | None = None, alert: Callable[[dict], None] | None = None,
                   coin: Callable[[], str] | None = None, **job_kwargs) -> dict:
    """Play the series to its end, or until a game is paused or another worker holds it.

    `job_kwargs` go to `run_match_job` (lease_seconds, backoff, sleep, now, seed_fn). Returns
    {"status", "ran": attempts run by this call, "skipped": reason or None}.
    """
    now = job_kwargs.get("now", time.time)
    owner = owner or f"worker-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    ran = 0
    for _ in range(MAX_STEPS):
        step = advance_series(store, series_id, coin=coin, now=now)
        if step["action"] == "completed":
            return {"status": COMPLETED, "ran": ran, "skipped": None}
        if step["action"] == "paused":
            O.deliver_alerts(store, alert, now)
            return {"status": PAUSED, "ran": ran, "skipped": None}
        out = O.run_match_job(store, step["match_id"], run_fn, owner=owner, alert=alert, **job_kwargs)
        ran += out["ran"]
        if out["skipped"] == "running_elsewhere":
            return {"status": IN_PROGRESS, "ran": ran, "skipped": "running_elsewhere"}
    raise SeriesError(f"series {series_id} did not settle in {MAX_STEPS} steps")


def take_series_advancement(store: JsonFileStore, series_id: str, now: Callable[[], float] = time.time) -> dict | None:
    """Hand the series result to bracket advancement exactly once (None every time after, and while unfinished)."""
    with store.transaction() as state:
        series = _get_series(state, series_id)
        if series["status"] != COMPLETED or not series["advancement"]["pending"]:
            return None
        series["advancement"] = {"pending": False, "taken_at": O._now_iso(now())}
        return copy.deepcopy(series["result"])


def public_view(series: dict) -> dict:
    """What authenticated tournament users may be shown: results, maps and the coin flip, but no host paths,
    file hashes, attempt internals or bot failure details (PRD 6.4: the coin flip is publicly displayed, logged,
    never rerolled). The caller still decides who may see it."""
    return {
        "id": series["id"], "stage": series["stage"], "status": series["status"],
        "teams": {"A": series["team_a"], "B": series["team_b"]},
        "games": [{"index": g["index"], "kind": g["kind"], "map": g["map"], "outcome": g["outcome"],
                   "winner_team": series["team_a" if g["winner_side"] == "A" else "team_b"] if g["winner_side"] else None,
                   "round": g["round"], "has_replay": bool(g["replay"])} for g in series["games"]],
        "coin_flip": None if not series["coin_flip"] else {
            k: series["coin_flip"][k] for k in ("drawn_at", "result_team", "tied_between", "probability_each", "rerolls_allowed")},
        "result": None if not series["result"] else {
            k: series["result"][k] for k in ("result_type", "winner_team", "loser_team", "decided_by_game")},
    }
