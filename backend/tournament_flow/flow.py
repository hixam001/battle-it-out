# SPDX-License-Identifier: AGPL-3.0-only
"""The steps between the libraries (BIO-EPIC-03, SRD-007, SRD-023, SRD-054, SRD-055; CN-018).

The registry, the queue, the bracket and the replay vault each work on their own. This module is the one
place that joins them, so the API that will sit on top has a single safe call for each step instead of four
calls it could make in the wrong order:

    upload()          store a version AND queue its check (a retry of the same upload queues it again if the
                      first call died between the two steps)
    sweep_checks()    queue the check of every version that is still unchecked and has no job (a crash, a lost
                      queue write); versions whose job is dead are left for an operator (`revive`)
    open_bracket()    after the submission deadline: pin who plays with which version (write-once), then draw the
                      bracket from a map pool with exactly those versions
    start_round()     before the round: every team's pinned file is re-hashed and must be what the bracket
                      was drawn with; only then is the round started by the Organizer and queued for a worker
    housekeeping()    store the replays of finished games, finish interrupted archive purges

It authenticates nobody: `actor` / `Actor` come from the API layer, which decides who may call what.
Standard library only.
"""
from __future__ import annotations

import copy
import time
from dataclasses import dataclass
from typing import Callable

from backend.match_orchestrator import bracket as B
from backend.match_orchestrator import maps as M
from backend.match_orchestrator import orchestrator as O
from backend.match_orchestrator import replays as P
from backend.match_orchestrator.store import JsonFileStore
from backend.submission_registry import registry as R
from backend.work_queue import jobs as J


class FlowError(Exception):
    """A step was refused; the message says why (nothing was changed unless the text says so)."""


@dataclass
class Flow:
    registry: R.Registry
    store: JsonFileStore            # the orchestrator store: matches, brackets, map pools
    queue: J.JobQueue


# ---------------------------------------------------------------------------------------------- uploads

def upload(flow: Flow, actor: R.Actor | None, team_id: str, tournament_id: str, file_name: str, data: bytes, *,
           idempotency_key: str, deadline_at: float, now: Callable[[], float] = time.time,
           bundle: bool = False) -> dict:
    """Store a Python file or explicit bundle and queue the check of the new version.
    Returns the version view plus `check_job`
    (the job id, or None when nothing needs checking: a statically invalid version).

    Retrying with the same idempotency key is safe at every point: the registry returns the same version and
    the queue returns the same live job (or makes one if the first call died before queueing).
    """
    options = {"idempotency_key": idempotency_key, "deadline_at": deadline_at, "now": now}
    if bundle:
        view = R.submit_bundle(flow.registry, actor, team_id, tournament_id, data, **options)
    else:
        view = R.submit(flow.registry, actor, team_id, tournament_id, file_name, data, **options)
    job = None
    if view["validation_status"] == R.VALIDATING:
        job = J.enqueue_check(flow.queue, view["id"], now=now)["id"]
    return {**view, "check_job": job}


def sweep_checks(flow: Flow, *, now: Callable[[], float] = time.time) -> dict:
    """Queue the check of every version that nobody is going to check: `validating` or `inconclusive`, with no
    live job and no dead job. A dead job is an incident for an operator and is not requeued here (or a version
    that can never be checked would cycle for ever). Returns `{"queued": [...], "left_dead": [...]}`."""
    subs = flow.registry.store.snapshot()["submissions"]
    live, dead = set(), set()
    for job in J.list_jobs(flow.queue):
        if job["kind"] != J.CHECK_SUBMISSION:
            continue
        sid = job["payload"]["submission_id"]
        if job["status"] in (J.QUEUED, J.RUNNING):
            live.add(sid)
        elif job["status"] == J.DEAD:
            dead.add(sid)
    queued, left_dead = [], []
    for sid, rec in sorted(subs.items()):
        if rec["validation_status"] not in (R.VALIDATING, R.INCONCLUSIVE) or sid in live:
            continue
        if sid in dead:
            left_dead.append(sid)
            continue
        queued.append(J.enqueue_check(flow.queue, sid, now=now)["id"])
    return {"queued": queued, "left_dead": left_dead}


# ---------------------------------------------------------------------------------------------- brackets

def open_bracket(flow: Flow, tournament_id: str, bracket_id: str, team_ids: list[str], pool_id: str,
                 catalogue: dict[str, str], engine_version: str, *, deadline_at: float,
                 now: Callable[[], float] = time.time, **bracket_kw) -> dict:
    """Pin the versions, then draw the bracket with them. Returns `{"bracket", "excluded"}`.

    * `registry.pin_tournament` refuses before the deadline and while a version is still being checked
      (`PendingChecks`: the caller waits for the queue; nothing is drawn).
    * A team with no active version is **excluded** and listed (it has no bot that may play); fewer than two
      playable teams is refused. Excluding is not a penalty decision about the team: whether a team without
      a valid bot may be replaced or counted as a loss is an owner decision (PRD 6.1 names byes and house
      bots, DEC-06, not this case).
    * The bracket entries are `{team, submission}` in sorted team order, so a repeated call asks for the same
      draw and gets the stored one back. The bracket remembers its tournament.
    * Pins are write-once: a repeated call after a later upload or extension changes nothing.
    """
    pool = M.get_pool(flow.store, pool_id)
    problems = M.verify_pool(pool, catalogue, engine_version)
    if problems:
        raise M.MapError("map pool does not match the engine: " + "; ".join(problems))
    # Refuse a draw that cannot work BEFORE the write-once pin: a pin made for a tournament with fewer than two
    # playable teams could never be corrected by an Admin extension (the pins would stay). Unfinished checks
    # and the deadline are left to `pin_tournament`, which raises its own errors first.
    preview = R.preview_pins(flow.registry, tournament_id, team_ids)
    if not preview["pinned"] and not preview["pending"] and now() >= deadline_at:
        have = sorted(t for t, sid in preview["teams"].items() if sid)
        if len(have) < 2:
            without = sorted(t for t, sid in preview["teams"].items() if not sid)
            raise FlowError(f"only {len(have)} team(s) have an active bot; a bracket needs at least 2"
                            + (f" (without one: {', '.join(without)})" if without else "")
                            + "; nothing was pinned")
    pins = R.pin_tournament(flow.registry, tournament_id, team_ids, deadline_at=deadline_at, now=now)
    playable = sorted(t for t, sid in pins.items() if sid)
    excluded = sorted(t for t, sid in pins.items() if not sid)
    if len(playable) < 2:
        raise FlowError(f"only {len(playable)} team(s) have an active bot; a bracket needs at least 2"
                        + (f" (without one: {', '.join(excluded)})" if excluded else ""))
    teams = [{"team": t, "submission": pins[t]} for t in playable]
    bracket = M.create_bracket_from_pool(flow.store, bracket_id, teams, pool_id, catalogue, engine_version, **bracket_kw)
    with flow.store.transaction() as state:
        stored = state["brackets"][bracket_id]
        if stored.get("tournament_id") not in (None, tournament_id):
            raise FlowError(f"bracket {bracket_id} belongs to tournament {stored['tournament_id']}")
        stored["tournament_id"] = tournament_id
        bracket = copy.deepcopy(stored)
    return {"bracket": bracket, "excluded": excluded}


def start_round(flow: Flow, bracket_id: str, round_no: int, actor: str, *,
                enqueue_paused: bool = True, now: Callable[[], float] = time.time) -> dict:
    """The Organizer starts a round: verify, start, queue. Returns `{"round", "job"}` (`job` is None when the
    round is already complete).

    Refused, before anything is started, when
    * the bracket has no tournament (it was not made by `open_bracket`);
    * a team's pinned version is not the one the bracket was drawn with;
    * a pinned bot file no longer matches its stored hash (`pinned_folder` re-hashes it and stores a staff
      incident; every pinned version belongs to a bracket team, so this covers what `verify_pins` would).
    Starting or queueing twice does nothing the second time. The HTTP round-start caller can refuse to
    enqueue a paused round; the trusted library recovery path retains the existing default.
    """
    bracket = B.get_bracket(flow.store, bracket_id)
    tournament_id = bracket.get("tournament_id")
    if not tournament_id:
        raise FlowError(f"bracket {bracket_id} was not drawn from pinned submissions (no tournament)")
    for entry in bracket["teams"]:
        try:
            folder = R.pinned_folder(flow.registry, tournament_id, entry["team"], now=now)
        except (R.NotFound, R.Unavailable) as e:
            raise FlowError(f"team {entry['team']}: {e}") from e
        if folder.name != entry["submission"]:
            raise FlowError(f"team {entry['team']} is pinned to {folder.name}, the bracket was drawn with {entry['submission']}")
    rd = B.start_round(flow.store, bracket_id, round_no, actor, now=now)
    if rd["status"] == B.COMPLETED or (rd["status"] == B.PAUSED and not enqueue_paused):
        return {"round": rd, "job": None}
    job = J.enqueue_round(flow.queue, bracket_id, round_no, now=now)
    return {"round": rd, "job": job["id"]}


# ---------------------------------------------------------------------------------------------- upkeep

def housekeeping(flow: Flow, vault: P.Vault | None = None, *, now: Callable[[], float] = time.time) -> dict:
    """Work that nothing else triggers; safe to run on a timer and to repeat.

    * `sweep_checks`;
    * with a vault: store the replays of every finished game of every bracket that has a tournament (a tournament
      that is archived is skipped and listed), then finish interrupted purges and sweep any replay files
      restored to archived tournaments.
    """
    out = {"checks": sweep_checks(flow, now=now)}
    if vault is not None:
        brackets = flow.store.snapshot().get("brackets", {})
        out["replays"], out["archived_skipped"] = {}, []
        for bid, b in sorted(brackets.items()):
            tid = b.get("tournament_id")
            if not tid:
                continue
            state = P.tournament_state(vault, tid)
            if state is not None and state["status"] == P.ARCHIVED:
                out["archived_skipped"].append(bid)
                continue
            out["replays"][bid] = P.collect_bracket(vault, flow.store, tid, bid, now=now)
        out["purged"] = P.purge_pending(vault, now=now)
    return out
