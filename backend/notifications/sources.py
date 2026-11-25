# SPDX-License-Identifier: AGPL-3.0-only
"""Where notifications come from: the adapters between the events of the other libraries and `notify` (CN-023).

`notifications.notify` creates a notification; nothing used to call it for the events SRD-061 lists. Each
function here turns one event of the platform into the right call, reading everything from the stores (never
from a caller-built text), and every one is safe to repeat: the event key is derived from the event, so a retried
job, a second timer pass or a crash in between creates nothing twice.

    validation_result   a version's check ended (valid -> accepted, invalid -> rejected)
    round_results       a round's decided matches (match result, qualified, eliminated)
    draw_exclusions     the draw left a team out (no active bot) or a claimed place unfinished (email unverified)

Who is told: the *verified* members of the team for team events (a member who only claimed a code has no place
yet; CN-023 D2); everybody who holds a place for the "not registered" notice, because that is what it is about.
A tournament nobody registered for notifies nobody and the call says so (`created` 0), it is not an error.

Not here: the announcement event (an Organizer writes it; it needs the API), and calling these from a running
process: the handlers and the timer take them as optional hooks (`on_decided`, `on_round`, `notifier`).
Standard library only.
"""
from __future__ import annotations

import re
import time
from typing import Callable

from backend.match_orchestrator import bracket as B
from backend.match_orchestrator.store import JsonFileStore
from backend.registration import registration as G
from backend.submission_registry import registry as R

from . import notifications as N

_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")
NO_REASON = "no reason was recorded; see the version history"


def _plain(text, n: int) -> str:
    """One line of text a template accepts: control characters become a space, length is capped."""
    return _CONTROL.sub(" ", text if isinstance(text, str) else "").strip()[:n]


def _sum(total: dict, part: dict) -> dict:
    for k, v in part.items():
        total[k] = total.get(k, 0) + v
    return total


def _empty() -> dict:
    return {"created": 0, "existing": 0, "email_queued": 0}


# ---------------------------------------------------------------------------------------------- validation

def validation_reason(validations: list[dict]) -> str:
    """The reasons of the latest recorded verdict as one line: `CODE: message; CODE: message`."""
    reasons = (validations[-1].get("reasons") if validations else None) or []
    text = "; ".join(f"{_plain(r.get('code'), 40)}: {_plain(r.get('message'), 200)}".strip(": ")
                     for r in reasons if isinstance(r, dict))
    return _plain(text, 500) or NO_REASON


def validation_result(center: N.Notifications, registration: G.Registration, registry: R.Registry,
                      submission_id: str, *, now: Callable[[], float] = time.time) -> dict:
    """Tell the team how the check of one version ended. Only a final outcome is an event: `valid` and `invalid`.
    A valid version that a newer one has already replaced is not announced as "now the active version" (that
    would be false): `{"skipped": "valid_but_not_active"}`. `validating` and `inconclusive` are not the
    participant's news (nobody is blamed for a platform failure) and return `{"skipped": status}`. One event
    per version."""
    rec = registry.store.snapshot()["submissions"].get(submission_id)
    if rec is None:
        raise N.NotFound("no such submission")
    status = rec["validation_status"]
    team, tid = rec["team_id"], rec["tournament_id"]
    key = f"validation:{submission_id}"
    if status == R.VALID:
        if not rec["is_active"]:
            return {"skipped": "valid_but_not_active"}
        return N.notify_audience(center, registration, "validation_accepted", tid,
                                 {"team": team, "version": rec["version"]}, event_key=key, team_id=team,
                                 verified_only=True, now=now)
    if status == R.INVALID:
        return N.notify_audience(center, registration, "validation_rejected", tid,
                                 {"team": team, "reason": validation_reason(rec["validations"])},
                                 event_key=key, team_id=team, verified_only=True, now=now)
    return {"skipped": status}


# ---------------------------------------------------------------------------------------------- rounds

def round_results(center: N.Notifications, registration: G.Registration, store: JsonFileStore, bracket_id: str,
                  round_no: int, *, now: Callable[[], float] = time.time) -> dict:
    """Notify the teams of every *decided* match of a round (so a round that is paused half way still tells the
    games that finished):

      * both teams of a played match: `match_result` (won / lost);
      * the winner of a match before the final, and a team that had a bye: `qualified`;
      * the loser: `eliminated` (single elimination; the loser of the final is eliminated too);
      * the champion gets the `won` result and nothing else.

    A bracket that was not drawn by `flow.open_bracket` has no tournament and nobody to tell (`{"skipped": ...}`).
    Returns the summed `notify` counts."""
    bracket = B.get_bracket(store, bracket_id)
    tid = bracket.get("tournament_id")
    if not tid:
        return {"skipped": "bracket has no tournament"}
    if not isinstance(round_no, int) or isinstance(round_no, bool) or not 1 <= round_no <= len(bracket["rounds"]):
        raise N.Invalid(f"round must be 1 to {len(bracket['rounds'])}")
    final = round_no == len(bracket["rounds"])
    out = _empty()

    def tell(event: str, team: str, params: dict, what: str) -> None:
        key = f"{event}:{bracket_id}:r{round_no}:{what}:{team}"
        _sum(out, N.notify_audience(center, registration, event, tid, {"team": team, **params}, event_key=key,
                                    team_id=team, verified_only=True, now=now))

    for m in bracket["rounds"][round_no - 1]["matches"]:
        winner = m["winner"]
        if winner is None:
            continue
        if m["bye"]:
            if not final:
                tell("qualified", winner, {"round": round_no}, f"m{m['index']}")
            continue
        loser = m["b"] if winner == m["a"] else m["a"]
        mid = f"m{m['index']}"
        series = m.get("series_id") or B.series_id(bracket_id, round_no, m["index"])
        for team, other, result in ((winner, loser, "won"), (loser, winner, "lost")):
            tell("match_result", team, {"opponent": other, "result": result, "round": round_no, "match_id": series}, mid)
        if not final:
            tell("qualified", winner, {"round": round_no}, mid)
        tell("eliminated", loser, {"round": round_no}, mid)
    return out


# ---------------------------------------------------------------------------------------------- the draw

def draw_exclusions(center: N.Notifications, registration: G.Registration, tournament_id: str,
                    excluded_teams: list[str], *, now: Callable[[], float] = time.time) -> dict:
    """After the draw: tell each excluded team (a registered team with no active bot) and every account that
    claimed a place but never finished it (email not verified), who is not in the draw either. The second kind
    is computed from the roster, so it does not depend on what the caller passes. Idempotent per tournament."""
    out = _empty()
    for team in sorted(set(excluded_teams)):
        _sum(out, N.notify_audience(center, registration, "team_excluded", tournament_id, {"team": team},
                                    event_key=f"team_excluded:{tournament_id}:{team}", team_id=team, now=now))
    everyone = set(G.account_ids(registration, tournament_id))
    unfinished = sorted(everyone - set(G.account_ids(registration, tournament_id, verified_only=True)))
    if unfinished:
        _sum(out, N.notify(center, "registration_excluded", tournament_id, unfinished, {},
                           event_key=f"registration_excluded:{tournament_id}", now=now))
    return out
