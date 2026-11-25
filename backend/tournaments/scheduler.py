# SPDX-License-Identifier: AGPL-3.0-only
"""The timer's work: events that happen because a deadline passed (BIO-EPIC-06, SRD-054, SRD-055; CN-019).

`tick` is safe to run every minute from cron, a systemd timer or the worker's idle loop, and safe to run twice
at once or after a crash: every step it takes is either idempotent or refused by a lock in the library below.

  1. A tournament with open registration whose **submission deadline has passed** is drawn: pin the versions,
     draw the bracket from its map pool (`flow.open_bracket`), then mark the tournament `running`. A tick that
     died between the draw and the status change finds the stored draw and finishes the status change.
  2. A `running` tournament whose bracket has a champion becomes `completed`.
  3. `flow.housekeeping` (checks that nobody queued, replays of finished games, interrupted purges).
  4. Open incidents are delivered through `alert`.

What it does NOT do: start rounds. The Organizer starts each round (`flow.start_round`); the PRD gives the
Organizer that control and nothing here takes it away.

A tournament that cannot be drawn is never skipped silently:
  * checks still running            -> `waiting` (the next tick tries again; no incident, this is normal);
  * no map pool, fewer than two teams with an active bot, a bracket that no longer matches its pins, a map pool
    that does not match the engine, any other refusal
                                    -> `blocked` plus one staff incident per tournament and reason (not one per
                                       tick). An Admin can fix it (extend the deadline, set the pool) and the
                                       next tick tries again.
One tournament's trouble never stops the others.
"""
from __future__ import annotations

import time
import uuid
from typing import Callable

from backend.match_orchestrator import bracket as B
from backend.match_orchestrator import orchestrator as O
from backend.match_orchestrator import replays as P
from backend.notifications import notifications as N
from backend.notifications import sources as NS
from backend.registration import registration as G
from backend.submission_registry import registry as R
from backend.tournament_flow import flow as F
from backend.tournaments import tournaments as T


def teams_with_uploads(flow: F.Flow, tournament_id: str) -> list[str]:
    """The fallback list of teams when no registration is given: every team that has uploaded anything to this
    tournament. Nothing here knows a team that never uploaded; such a team would have been excluded anyway ("no
    active bot"), the only difference is that it is not named in the exclusion list. With a registration
    (`tick(registration=...)`) the list is `registration.registered_teams` instead."""
    teams = flow.registry.store.snapshot()["teams"]
    return sorted(t for t, rec in teams.items() if rec["tournament_id"] == tournament_id)


def _incident(flow: F.Flow, tournament_id: str, kind: str, detail: str, t: float) -> bool:
    """Open a staff incident unless one with this kind is already open for the tournament. True when new."""
    with flow.store.transaction() as state:
        for inc in state["incidents"]:
            if inc.get("tournament_id") == tournament_id and inc["incident_type"] == kind and inc["status"] == "open":
                return False
        state["incidents"].append({
            "id": uuid.uuid4().hex, "match_id": None, "tournament_id": tournament_id, "incident_type": kind,
            "attempt_count": None, "status": "open", "alerted_admin_at": None, "alert_error": None,
            "details_redacted": detail[:O.MAX_TEXT], "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t)),
            "resolved_at": None, "resolved_by": None})
        return True


def tick(reg: T.Tournaments, flow: F.Flow, *, catalogue: dict[str, str], engine_version: str,
         vault: P.Vault | None = None, alert: Callable[[dict], None] | None = None,
         teams_of: Callable[[str], list[str]] | None = None, registration: G.Registration | None = None,
         notifications: N.Notifications | None = None, rng=None,
         now: Callable[[], float] = time.time, by: str = "scheduler") -> dict:
    """One pass. Which teams are drawn: `teams_of(tournament_id)` if given, else the teams with a registered
    member in `registration` (the roster is the authority: a registered team without a bot is named in the
    exclusion list, and a team that is not on the roster is never drawn), else the teams that uploaded. Giving
    both `teams_of` and `registration` is a `ValueError`: two sources would silently disagree. With
    `notifications` (which needs `registration`, the audience) the draw tells the excluded teams and the
    unfinished registrations (`sources.draw_exclusions`) **before** the tournament is marked running, so a
    failure to notify leaves the tournament open, blocked with an incident, and the next tick tries again (the
    notices are idempotent). Returns `{"opened": [...], "completed": [...], "waiting": {id: [teams]}, "blocked": {id: reason},
    "housekeeping": {...}, "alerts": n}`. The bracket id is the tournament id (one bracket per tournament)."""
    if teams_of is not None and registration is not None:
        raise ValueError("give teams_of or registration, not both")
    if notifications is not None and registration is None:
        raise ValueError("notifications need a registration: it says who the teams' members are")
    if registration is not None:
        if registration.tournaments is not reg:
            raise ValueError("the registration belongs to another tournament record")
        teams_of = lambda tid: G.registered_teams(registration, tid)      # noqa: E731
    teams_of = teams_of or (lambda tid: teams_with_uploads(flow, tid))
    tell = None
    if notifications is not None:
        tell = lambda tid, excluded: NS.draw_exclusions(notifications, registration, tid, excluded, now=now)  # noqa: E731
    report = {"opened": [], "completed": [], "waiting": {}, "blocked": {}, "excluded": {}}
    t = now()
    for rec in sorted(reg.store.snapshot()["tournaments"].values(), key=lambda r: r["id"]):
        tid = rec["id"]
        try:
            if rec["status"] == T.OPEN and rec["deadlines"][T.SUBMISSION] <= t:
                _open(reg, flow, rec, teams_of, catalogue, engine_version, rng, now, by, report, tell)
            elif rec["status"] == T.RUNNING:
                _finish(reg, flow, rec, now, by, report)
        except Exception as e:                      # one tournament's trouble must not stop the others
            reason = f"{type(e).__name__}: {e}"
            report["blocked"][tid] = reason
            _incident(flow, tid, "tournament_blocked", reason, t)
    out = {**report, "housekeeping": F.housekeeping(flow, vault, now=now), "alerts": O.deliver_alerts(flow.store, alert, now)}
    return out


def _open(reg, flow, rec, teams_of, catalogue, engine_version, rng, now, by, report, tell) -> None:
    tid = rec["id"]
    if not rec["map_pool_id"]:
        raise F.FlowError("the tournament has no map pool; an Admin or its Organizer must set one")
    teams = teams_of(tid)
    if not teams:
        raise F.FlowError("no team to draw (none registered or none uploaded); nothing can be drawn")
    try:
        drawn = F.open_bracket(flow, tid, tid, list(teams), rec["map_pool_id"], catalogue, engine_version,
                               deadline_at=rec["deadlines"][T.SUBMISSION], now=now, rng=rng)
    except R.PendingChecks as e:
        report["waiting"][tid] = list(e.teams)
        return
    if drawn["excluded"]:
        report["excluded"][tid] = list(drawn["excluded"])
    if tell is not None:
        tell(tid, drawn["excluded"])
    T.mark_running(reg, tid, by, now=now)
    report["opened"].append(tid)


def _finish(reg, flow, rec, now, by, report) -> None:
    bracket = B.get_bracket(flow.store, rec["id"])
    if bracket["champion"]:
        T.mark_completed(reg, rec["id"], by, now=now)
        report["completed"].append(rec["id"])
