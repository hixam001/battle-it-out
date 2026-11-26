# SPDX-License-Identifier: AGPL-3.0-only
"""Tournament lifecycle, approval and deadlines (BIO-EPIC-06, PRD 6.1, API_CONTRACT section 3; CN-019).

Until now every library took "the tournament" and "the deadline" as arguments from a caller that did not exist.
This module is the record behind those arguments and the rules around changing it:

  * `create` / `submit_for_approval` / `approve` / `reject`
        Admin and Organizer create a draft. An Organizer's draft must be submitted and approved by an Admin; an
        Admin's own draft may be approved by that Admin. A rejection needs a reason; the Organizer may edit a
        rejected tournament and submit it again (PRD 6.1).
  * `edit`
        Admin or the Organizer who manages the tournament changes name, description, map pool and the two
        deadlines. Each field is frozen by the deadline it belongs to; after that, ordinary changes need an
        Admin extension first (PRD 6.1). `expected_version` stops two editors overwriting each other.
  * `extend_deadline`
        Admin only, registration or submission, later than now and later than the current value, with a
        reason; every value stays in the deadline history. A submission extension reopens uploads simply
        because `deadline()` now answers a later time.
  * `emergency_override`
        Admin only, after a lock, with a reason; the answer carries the notice (setting, old and new value,
        reason, time, authorizer) that participants must receive. Sending it is the notification module's job.
  * `open_registration`, `mark_running`, `mark_completed`, `archive`, `delete`
        The rest of the state machine `draft -> pending_approval -> approved -> registration_open -> running ->
        completed -> archived -> deleted` (+ `rejected`). Archive purges the replays first and only then marks
        the tournament archived. Delete keeps the record shell and the audit.
  * `get` / `list_visible` / `audit_log`
        What each role may see. Anybody else gets `NotFound`, the same answer as for an unknown id.

Not here: the HTTP API, authentication (the caller passes the same `registry.Actor`), who the Organizer
assignments are (the Actor carries `tournament_ids`; the creating Organizer also counts), registration and
rosters, notifications, the database (DEC-11): the state is a JSON file with the same lock rules as the other
stores. Times are epoch seconds; the API layer converts from and to ISO-8601 UTC. Standard library only.
"""
from __future__ import annotations

import copy
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from backend.match_orchestrator import replays as P
from backend.match_orchestrator.store import JsonFileStore
from backend.submission_registry import registry as R

SCHEMA = 1

DRAFT, PENDING, REJECTED, APPROVED = "draft", "pending_approval", "rejected", "approved"
OPEN, RUNNING, COMPLETED, ARCHIVED, DELETED = "registration_open", "running", "completed", "archived", "deleted"
STATUSES = (DRAFT, PENDING, REJECTED, APPROVED, OPEN, RUNNING, COMPLETED, ARCHIVED, DELETED)

REGISTRATION, SUBMISSION = "registration", "submission"
DEADLINE_TYPES = (REGISTRATION, SUBMISSION)
# Each editable field is frozen by one deadline (PRD 6.1: "after a deadline, normal configuration changes require
# the Admin to extend the relevant deadline first").
FIELD_LOCK = {"registration_deadline": REGISTRATION, "submission_deadline": SUBMISSION, "name": SUBMISSION,
              "description": SUBMISSION, "map_pool_id": SUBMISSION}
OVERRIDABLE = ("name", "description", "map_pool_id")
MAX_NAME, MAX_DESCRIPTION, MAX_REASON = 120, 2000, 500
# Interim: a tournament is a few hundred teams at most, and the audit list must not grow without limit.
MAX_TOURNAMENTS, MAX_AUDIT = 10_000, 100_000


class TournamentError(Exception):
    """Base class; the API maps the subclasses to 400/422, 404, 403 and 409."""


class Invalid(TournamentError):
    """The request itself is wrong (422): empty name, a deadline in the past, reason missing, unknown field."""


class NotFound(TournamentError):
    """No such tournament, or the actor may not know about it (the same answer on purpose)."""


class Forbidden(TournamentError):
    """The actor may see the tournament but not do this (403)."""


class Conflict(TournamentError):
    """The request contradicts the stored state (409): wrong status, stale version, a deadline already passed."""


class DeadlineLocked(Conflict):
    """An ordinary change after its deadline: an Admin extension (or an emergency override) comes first."""


def _empty_state() -> dict:
    return {"schema": SCHEMA, "tournaments": {}, "idempotency": {}, "audit": []}


def _state_ok(state) -> bool:
    return isinstance(state, dict) and state.get("schema") == SCHEMA and all(
        isinstance(state.get(k), t) for k, t in (("tournaments", dict), ("idempotency", dict), ("audit", list)))


class TournamentStore(JsonFileStore):
    _empty = staticmethod(_empty_state)
    _layout_ok = staticmethod(_state_ok)


@dataclass
class Tournaments:
    store: TournamentStore

    @classmethod
    def at(cls, path: Path | str) -> "Tournaments":
        return cls(TournamentStore(Path(path)))


# ------------------------------------------------------------------------------------------------ helpers

def _iso(t: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def _audit(state: dict, t: float, actor: str, action: str, tournament_id: str, **detail) -> None:
    _check_audit_capacity(state)
    state["audit"].append({"at": _iso(t), "actor": actor, "action": action, "tournament": tournament_id, **detail})


def _check_audit_capacity(state: dict) -> None:
    if len(state["audit"]) >= MAX_AUDIT:
        raise Conflict("the audit list is full; an operator must archive it before anything else changes")


def _id(value) -> str:
    if not isinstance(value, str) or not R.TOURNAMENT_ID_RE.fullmatch(value):
        raise Invalid(f"tournament id {value!r} is not a safe identifier")
    return value


def _text(kind: str, value, limit: int, *, required: bool = True) -> str:
    if not isinstance(value, str) or (required and not value.strip()) or len(value) > limit \
            or any(ord(c) < 32 and c not in "\n\t" for c in value):
        raise Invalid(f"{kind} must be {'non-empty ' if required else ''}text of at most {limit} characters")
    return value.strip()


def _time(kind: str, value) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise Invalid(f"{kind} must be a finite time in seconds since the epoch")
    return float(value)


def _reason(value) -> str:
    return _text("reason", value, MAX_REASON)


def _pool_id(value) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not R.TEAM_ID_RE.fullmatch(value):
        raise Invalid(f"map_pool_id {value!r} is not a safe identifier")
    return value


def _clean(field: str, value):
    if field == "name":
        return _text("name", value, MAX_NAME)
    if field == "description":
        return _text("description", value, MAX_DESCRIPTION, required=False)
    if field == "map_pool_id":
        return _pool_id(value)
    return _time(field, value)


def _who(actor, roles=("admin", "organizer")) -> R.Actor:
    if not isinstance(actor, R.Actor) or actor.role not in roles or not actor.user_id:
        raise Forbidden("this action is not available to this account")
    return actor


def _manages(actor: R.Actor, rec: dict) -> bool:
    """Admin, or an Organizer assigned to the tournament (or who created it: the assignment record does not
    exist yet, and a creator who could not edit their own draft would make the approval flow unusable)."""
    return actor.role == "admin" or (actor.role == "organizer" and (
        rec["id"] in actor.tournament_ids or rec["created_by"] == actor.user_id))


def manages(actor: R.Actor, rec: dict) -> bool:
    """Public form of the managing rule, for the libraries that guard their own staff operations (registration)."""
    return _manages(actor, rec)


def _rec(state: dict, tournament_id) -> dict:
    rec = state["tournaments"].get(tournament_id) if isinstance(tournament_id, str) else None
    if rec is None:
        raise NotFound("no such tournament")
    return rec


def _visible_rec(state: dict, actor, tournament_id) -> dict:
    """The record, or `NotFound` for anybody who may not know it exists. A deleted tournament is only known
    to an Admin; a participant sees only a published one that the API layer lists in `tournament_ids`."""
    rec = _rec(state, tournament_id)
    if not isinstance(actor, R.Actor) or actor.role not in R.ROLES:
        raise NotFound("no such tournament")
    if actor.role == "admin":
        return rec
    if rec["status"] == DELETED:
        raise NotFound("no such tournament")
    if actor.role == "organizer":
        if not _manages(actor, rec):
            raise NotFound("no such tournament")
    elif rec["id"] not in actor.tournament_ids or rec["status"] not in (OPEN, RUNNING, COMPLETED, ARCHIVED):
        raise NotFound("no such tournament")
    return rec


def _managed_rec(state: dict, actor, tournament_id) -> dict:
    """Like `_visible_rec`, for a change: a participant is `Forbidden`, not told more than they already see."""
    rec = _visible_rec(state, actor, tournament_id)
    if not _manages(actor, rec):
        raise Forbidden("only an Admin or the Organizer of this tournament may do this")
    return rec


def _view(rec: dict, actor: R.Actor | None) -> dict:
    out = {k: rec[k] for k in ("id", "name", "description", "status", "version", "map_pool_id")}
    out["registration_deadline"] = rec["deadlines"][REGISTRATION]
    out["submission_deadline"] = rec["deadlines"][SUBMISSION]
    if actor is not None and actor.role in ("admin", "organizer"):
        out.update({k: rec[k] for k in ("created_by", "created_at", "approved_by", "approved_at", "rejection_reason",
                                        "archived_at", "deleted_at")})
    return copy.deepcopy(out)


def _set_deadline(rec: dict, kind: str, value: float, by: str, reason: str | None, t: float) -> None:
    for h in rec["deadline_history"]:
        if h["type"] == kind and h["superseded_at"] is None:
            h["superseded_at"] = _iso(t)
    rec["deadline_history"].append({"type": kind, "deadline_at": value, "changed_by": by, "reason": reason,
                                    "at": _iso(t), "superseded_at": None})
    rec["deadlines"][kind] = value


def _check_order(reg_deadline: float, sub_deadline: float) -> None:
    # Teams must be registered before they can upload, so a submission deadline earlier than registration
    # closing would make the last registrants unable to submit anything (decision D3).
    if reg_deadline > sub_deadline:
        raise Invalid("the registration deadline must not be later than the submission deadline")


def _move(rec: dict, status: str, state: dict, t: float, actor: str, action: str, **detail) -> None:
    before = rec["status"]
    rec["status"] = status
    rec["version"] += 1
    _audit(state, t, actor, action, rec["id"], **{"from": before, "to": status, **detail})


# ------------------------------------------------------------------------------------------ create / approve

def create(reg: Tournaments, actor: R.Actor | None, tournament_id: str, name: str, description: str,
           registration_deadline: float, submission_deadline: float, *, idempotency_key: str,
           now: Callable[[], float] = time.time) -> dict:
    """A new draft (`POST /tournaments`). Repeating the same call (same key and content) returns the same
    tournament; the same key with other content, or an id that exists, is a conflict. Both deadlines must be
    in the future."""
    actor = _who(actor)
    tid = _id(tournament_id)
    if not isinstance(idempotency_key, str) or not R.KEY_RE.fullmatch(idempotency_key):
        raise Invalid("idempotency_key must be 1-128 characters of letters, digits and . _ : -")
    fields = {"name": _text("name", name, MAX_NAME), "description": _text("description", description, MAX_DESCRIPTION, required=False),
              "registration_deadline": _time("registration_deadline", registration_deadline),
              "submission_deadline": _time("submission_deadline", submission_deadline)}
    _check_order(fields["registration_deadline"], fields["submission_deadline"])
    t = now()
    if fields["registration_deadline"] <= t:
        raise Invalid("the registration deadline must be in the future")
    with reg.store.transaction() as state:
        key = f"{actor.user_id}/{idempotency_key}"
        seen = state["idempotency"].get(key)
        if seen is not None:
            if seen["tournament"] != tid or seen["fields"] != fields:
                raise Conflict("this idempotency key was used for a different tournament")
            return _view(state["tournaments"][tid], actor)
        if tid in state["tournaments"]:
            raise Conflict(f"tournament {tid} already exists")
        if len(state["tournaments"]) >= MAX_TOURNAMENTS:
            raise Conflict("too many tournaments")
        rec = {"id": tid, "name": fields["name"], "description": fields["description"], "status": DRAFT, "version": 1,
               "created_by": actor.user_id, "created_by_role": actor.role, "created_at": _iso(t),
               "approved_by": None, "approved_at": None, "rejection_reason": None, "archived_at": None,
               "deleted_at": None, "map_pool_id": None, "deadlines": {}, "deadline_history": [], "approvals": []}
        _set_deadline(rec, REGISTRATION, fields["registration_deadline"], actor.user_id, "created", t)
        _set_deadline(rec, SUBMISSION, fields["submission_deadline"], actor.user_id, "created", t)
        state["tournaments"][tid] = rec
        state["idempotency"][key] = {"tournament": tid, "fields": fields}
        _audit(state, t, actor.user_id, "create", tid, status=DRAFT)
        return _view(rec, actor)


def submit_for_approval(reg: Tournaments, actor: R.Actor | None, tournament_id: str, *,
                        now: Callable[[], float] = time.time) -> dict:
    """The creating Organizer submits a draft or a rejected tournament (`submit-for-approval`). An Admin's own
    draft needs no submission (it is approved directly)."""
    actor = _who(actor, ("organizer",))
    with reg.store.transaction() as state:
        rec = _managed_rec(state, actor, tournament_id)
        if rec["created_by"] != actor.user_id:
            raise Forbidden("only the Organizer who created the tournament may submit it")
        if rec["status"] not in (DRAFT, REJECTED):
            raise Conflict(f"a tournament that is {rec['status']} cannot be submitted for approval")
        if rec["deadlines"][REGISTRATION] <= now():
            raise Conflict("the registration deadline has already passed; move the deadlines first")
        _move(rec, PENDING, state, now(), actor.user_id, "submit_for_approval")
        return _view(rec, actor)


def approve(reg: Tournaments, actor: R.Actor | None, tournament_id: str, *, confirm: bool = False,
            now: Callable[[], float] = time.time) -> dict:
    """Admin approves (`approve`, `{"confirm": true}`). A pending tournament, or a draft that an Admin created.
    An Organizer's draft that was never submitted cannot be approved over their head."""
    actor = _who(actor, ("admin",))
    if confirm is not True:
        raise Invalid("approval needs confirm=true")
    with reg.store.transaction() as state:
        rec = _managed_rec(state, actor, tournament_id)
        if not (rec["status"] == PENDING or (rec["status"] == DRAFT and rec["created_by_role"] == "admin")):
            raise Conflict(f"a tournament that is {rec['status']} cannot be approved")
        t = now()
        if rec["deadlines"][REGISTRATION] <= t:
            raise Conflict("the registration deadline has already passed; move the deadlines before approving")
        rec.update({"approved_by": actor.user_id, "approved_at": _iso(t), "rejection_reason": None})
        rec["approvals"].append({"decision": "approved", "reviewer": actor.user_id, "reason": None, "at": _iso(t)})
        _move(rec, APPROVED, state, t, actor.user_id, "approve")
        return _view(rec, actor)


def reject(reg: Tournaments, actor: R.Actor | None, tournament_id: str, reason: str, *,
           now: Callable[[], float] = time.time) -> dict:
    """Admin rejects a pending tournament with a reason (kept, shown to the Organizer, who may edit and resubmit)."""
    actor = _who(actor, ("admin",))
    reason = _reason(reason)
    with reg.store.transaction() as state:
        rec = _managed_rec(state, actor, tournament_id)
        if rec["status"] != PENDING:
            raise Conflict(f"a tournament that is {rec['status']} cannot be rejected")
        t = now()
        rec["rejection_reason"] = reason
        rec["approvals"].append({"decision": "rejected", "reviewer": actor.user_id, "reason": reason, "at": _iso(t)})
        _move(rec, REJECTED, state, t, actor.user_id, "reject", reason=reason)
        return _view(rec, actor)


# ------------------------------------------------------------------------------------------------ editing

def edit(reg: Tournaments, actor: R.Actor | None, tournament_id: str, changes: dict, *,
         expected_version: int | None = None, now: Callable[[], float] = time.time) -> dict:
    """An ordinary change (`PATCH`). Refused when
    * a field is unknown, or a value is invalid;
    * the tournament is pending approval (the Admin is reviewing a fixed text), running or later;
    * the deadline that freezes a changed field has passed (`DeadlineLocked`: extend it first, or use the
      emergency override);
    * a deadline is moved into the past, or the registration deadline would pass the submission deadline;
    * `expected_version` is not the stored version (someone else edited meanwhile)."""
    actor = _who(actor)
    if not isinstance(changes, dict) or not changes:
        raise Invalid("changes must be a non-empty object")
    unknown = sorted(str(k) for k in changes if k not in FIELD_LOCK)
    if unknown:
        raise Invalid(f"fields that cannot be edited here: {', '.join(unknown)}")
    clean = {k: _clean(k, v) for k, v in changes.items()}
    with reg.store.transaction() as state:
        rec = _managed_rec(state, actor, tournament_id)
        if expected_version is not None and expected_version != rec["version"]:
            raise Conflict(f"the tournament is at version {rec['version']}, not {expected_version}")
        if rec["status"] not in (DRAFT, REJECTED, APPROVED, OPEN):
            raise Conflict(f"a tournament that is {rec['status']} cannot be edited")
        t = now()
        published = rec["status"] in (APPROVED, OPEN)
        for field, value in clean.items():
            # Before approval nothing has been announced, so no deadline has locked anything yet.
            if published and rec["deadlines"][FIELD_LOCK[field]] <= t:
                raise DeadlineLocked(f"the {FIELD_LOCK[field]} deadline has passed; an Admin must extend it first "
                                     f"(or use the emergency override)")
        reg_d = clean.get("registration_deadline", rec["deadlines"][REGISTRATION])
        sub_d = clean.get("submission_deadline", rec["deadlines"][SUBMISSION])
        _check_order(reg_d, sub_d)
        for field in ("registration_deadline", "submission_deadline"):
            if field in clean and clean[field] <= t:
                raise Invalid(f"{field} must be in the future (an Admin extension is the way to reopen a closed deadline)")
        done = {}
        for field, value in clean.items():
            old = rec["deadlines"][FIELD_LOCK[field]] if field.endswith("_deadline") else rec[field]
            if old == value:
                continue
            if field.endswith("_deadline"):
                _set_deadline(rec, FIELD_LOCK[field], value, actor.user_id, "edited", t)
            else:
                rec[field] = value
            done[field] = {"old": old, "new": value}
        if done:
            rec["version"] += 1
            _audit(state, t, actor.user_id, "edit", rec["id"], changes=done)
        return _view(rec, actor)


def extend_deadline(reg: Tournaments, actor: R.Actor | None, tournament_id: str, deadline_type: str,
                    new_deadline: float, reason: str, *, confirm: bool = False,
                    now: Callable[[], float] = time.time) -> dict:
    """Admin extends the registration or the submission deadline, also after it has passed (`extend-deadline`).

    The new time must be later than the current one and than now. Refused once the bracket is drawn
    (`running` or later): the pins are write-once, so reopening uploads would promise something the draw
    cannot keep. Extending registration past the submission deadline is refused (extend that one first).
    Returns the change plus the `notice` that affected participants must receive."""
    actor = _who(actor, ("admin",))
    if confirm is not True:
        raise Invalid("an extension needs confirm=true")
    if deadline_type not in DEADLINE_TYPES:
        raise Invalid(f"deadline_type must be one of {', '.join(DEADLINE_TYPES)}")
    new_deadline = _time("new_deadline", new_deadline)
    reason = _reason(reason)
    with reg.store.transaction() as state:
        rec = _managed_rec(state, actor, tournament_id)
        if rec["status"] not in (APPROVED, OPEN):
            raise Conflict(f"a tournament that is {rec['status']} has no deadline that can be extended")
        t = now()
        old = rec["deadlines"][deadline_type]
        if new_deadline <= old or new_deadline <= t:
            raise Invalid("the new deadline must be later than the current one and than now")
        reg_d = new_deadline if deadline_type == REGISTRATION else rec["deadlines"][REGISTRATION]
        sub_d = new_deadline if deadline_type == SUBMISSION else rec["deadlines"][SUBMISSION]
        _check_order(reg_d, sub_d)
        _set_deadline(rec, deadline_type, new_deadline, actor.user_id, reason, t)
        rec["version"] += 1
        notice = {"kind": "deadline_extended", "tournament": rec["id"], "deadline_type": deadline_type,
                  "old": old, "new": new_deadline, "reason": reason, "at": _iso(t), "authorizer": actor.user_id}
        _audit(state, t, actor.user_id, "extend_deadline", rec["id"], deadline_type=deadline_type, old=old,
               new=new_deadline, reason=reason)
        return {"tournament": _view(rec, actor), "notice": notice}


def emergency_override(reg: Tournaments, actor: R.Actor | None, tournament_id: str, setting: str, value, reason: str,
                       *, confirm: bool = False, now: Callable[[], float] = time.time) -> dict:
    """Admin changes a locked setting without extending the deadline (`emergency-override`).

    Only name, description and the map pool can be overridden (a deadline has its own extension, and every
    change to it is in the history). The map pool cannot change once the bracket is drawn: the bracket stores
    its own maps. Archived and deleted tournaments are closed. The answer carries the notice for participants:
    setting, old and new value, reason, time and authorizer."""
    actor = _who(actor, ("admin",))
    if confirm is not True:
        raise Invalid("an emergency override needs confirm=true")
    if setting not in OVERRIDABLE:
        raise Invalid(f"setting must be one of {', '.join(OVERRIDABLE)}")
    value = _clean(setting, value)
    reason = _reason(reason)
    with reg.store.transaction() as state:
        rec = _managed_rec(state, actor, tournament_id)
        if rec["status"] in (ARCHIVED, DELETED):
            raise Conflict(f"a tournament that is {rec['status']} cannot be changed")
        if setting == "map_pool_id" and rec["status"] in (RUNNING, COMPLETED):
            raise Conflict("the bracket is already drawn; its maps cannot change")
        t = now()
        old = rec[setting]
        rec[setting] = value
        rec["version"] += 1
        notice = {"kind": "emergency_override", "tournament": rec["id"], "setting": setting, "old": old, "new": value,
                  "reason": reason, "at": _iso(t), "authorizer": actor.user_id}
        _audit(state, t, actor.user_id, "emergency_override", rec["id"], setting=setting, old=old, new=value, reason=reason)
        return {"tournament": _view(rec, actor), "notice": notice}


# --------------------------------------------------------------------------------------- the state machine

def open_registration(reg: Tournaments, actor: R.Actor | None, tournament_id: str, *,
                      now: Callable[[], float] = time.time) -> dict:
    """Admin or the managing Organizer opens an approved tournament (decision D4: opening is manual; the PRD
    leaves manual or scheduled open). Refused after the registration deadline."""
    actor = _who(actor)
    with reg.store.transaction() as state:
        rec = _managed_rec(state, actor, tournament_id)
        if rec["status"] != APPROVED:
            raise Conflict(f"a tournament that is {rec['status']} cannot open registration")
        if rec["deadlines"][REGISTRATION] <= now():
            raise DeadlineLocked("the registration deadline has passed; an Admin must extend it first")
        _move(rec, OPEN, state, now(), actor.user_id, "open_registration")
        return _view(rec, actor)


def mark_running(reg: Tournaments, tournament_id: str, by: str, *, now: Callable[[], float] = time.time) -> dict:
    """The system moved the tournament to `running` because its bracket was drawn. Needs the submission
    deadline to have passed (nothing is drawn earlier) and a registered, published tournament. Repeating it
    on a running tournament changes nothing."""
    if not isinstance(by, str) or not by:
        raise Invalid("mark_running needs the acting system or user")
    with reg.store.transaction() as state:
        rec = _rec(state, _id(tournament_id))
        if rec["status"] == RUNNING:
            return _view(rec, None)
        if rec["status"] not in (APPROVED, OPEN):
            raise Conflict(f"a tournament that is {rec['status']} cannot start running")
        if rec["deadlines"][SUBMISSION] > now():
            raise Conflict("the submission deadline has not passed")
        _move(rec, RUNNING, state, now(), by, "mark_running")
        return _view(rec, None)


def mark_completed(reg: Tournaments, tournament_id: str, by: str, *, now: Callable[[], float] = time.time) -> dict:
    """The system moved a running tournament to `completed` (its bracket has a champion). Repeating it is harmless."""
    if not isinstance(by, str) or not by:
        raise Invalid("mark_completed needs the acting system or user")
    with reg.store.transaction() as state:
        rec = _rec(state, _id(tournament_id))
        if rec["status"] == COMPLETED:
            return _view(rec, None)
        if rec["status"] != RUNNING:
            raise Conflict(f"a tournament that is {rec['status']} cannot complete")
        _move(rec, COMPLETED, state, now(), by, "mark_completed")
        return _view(rec, None)


def archive(reg: Tournaments, actor: R.Actor | None, tournament_id: str, vault: P.Vault, *, confirm: bool = False,
            now: Callable[[], float] = time.time) -> dict:
    """Admin or the managing Organizer archives a completed tournament (`archive`): the replays are deleted
    first (`replays.archive_tournament`, which marks, purges and verifies), then the tournament is marked
    archived. If the purge did not finish the answer says `replays_deleted: false`; the tournament is still
    marked archived (nobody can fetch a replay from that moment) and `replays.purge_pending` finishes it.
    Repeating it on an archived tournament returns the same answer."""
    actor = _who(actor)
    if confirm is not True:
        raise Invalid("archiving needs confirm=true")
    with reg.store.transaction() as state:
        rec = _managed_rec(state, actor, tournament_id)
        if rec["status"] not in (COMPLETED, ARCHIVED):
            raise Conflict(f"a tournament that is {rec['status']} cannot be archived (only a completed one)")
        if rec["status"] == COMPLETED:
            _check_audit_capacity(state)
        # Keep the audit slot available until the archive transition commits.
        # A crash leaves the vault archived; another confirmed call can finish.
        out = P.archive_tournament(vault, tournament_id, actor.user_id, now=now)
        if rec["status"] == COMPLETED:
            rec["archived_at"] = _iso(now())
            _move(rec, ARCHIVED, state, now(), actor.user_id, "archive", replays_deleted=out["replays_deleted"])
    return {"status": ARCHIVED, "replays_deleted": out["replays_deleted"]}


def delete(reg: Tournaments, actor: R.Actor | None, tournament_id: str, reason: str, *, confirm: bool = False,
           now: Callable[[], float] = time.time) -> dict:
    """Admin permanently deletes the tournament's operational record (`DELETE`). The audit stays. Refused while
    it is running (finish or stop it first) and while it is completed but not archived (the replays would
    survive the record that owns them). The name and description are erased; the id, the status history and
    the audit remain. Deleting twice returns the same answer."""
    actor = _who(actor, ("admin",))
    if confirm is not True:
        raise Invalid("deleting needs confirm=true")
    reason = _reason(reason)
    with reg.store.transaction() as state:
        rec = _managed_rec(state, actor, tournament_id)
        if rec["status"] == DELETED:
            return {"status": DELETED, "audit_event_id": rec["delete_audit"]}
        if rec["status"] in (RUNNING, COMPLETED):
            raise Conflict(f"a tournament that is {rec['status']} cannot be deleted"
                           + (" until it is archived" if rec["status"] == COMPLETED else ""))
        t = now()
        rec.update({"name": "", "description": "", "map_pool_id": None, "deleted_at": _iso(t),
                    "delete_audit": len(state["audit"])})
        _move(rec, DELETED, state, t, actor.user_id, "delete", reason=reason)
        return {"status": DELETED, "audit_event_id": rec["delete_audit"]}


# ------------------------------------------------------------------------------------------------- reading

def get(reg: Tournaments, actor: R.Actor | None, tournament_id: str) -> dict:
    """Detail for a role (`GET /tournaments/{id}`): staff see the lifecycle fields too."""
    with reg.store.transaction() as state:
        return _view(_visible_rec(state, actor, tournament_id), actor)


def list_visible(reg: Tournaments, actor: R.Actor | None) -> list[dict]:
    """The tournaments this actor may see, by id. Admin: all but deleted ones; the Organizer: the ones they
    manage; a participant: the published ones the API layer put in their `tournament_ids`."""
    if not isinstance(actor, R.Actor) or actor.role not in R.ROLES:
        return []
    out = []
    with reg.store.transaction() as state:
        for tid in sorted(state["tournaments"]):
            try:
                rec = _visible_rec(state, actor, tid)
            except NotFound:
                continue
            if rec["status"] != DELETED:
                out.append(_view(rec, actor))
    return out


def deadline(reg: Tournaments, tournament_id: str, deadline_type: str) -> float:
    """The current deadline, for the code that enforces it (`registry.submit(deadline_at=...)`,
    `flow.open_bracket(deadline_at=...)`). No access check: it is a system call, and nothing but a time leaves."""
    if deadline_type not in DEADLINE_TYPES:
        raise Invalid(f"deadline_type must be one of {', '.join(DEADLINE_TYPES)}")
    with reg.store.transaction() as state:
        return _rec(state, _id(tournament_id))["deadlines"][deadline_type]


def deadline_history(reg: Tournaments, actor: R.Actor | None, tournament_id: str) -> list[dict]:
    """Every deadline value there has been, who changed it and why (Admin and the managing Organizer)."""
    actor = _who(actor)
    with reg.store.transaction() as state:
        return copy.deepcopy(_managed_rec(state, actor, tournament_id)["deadline_history"])


def audit_log(reg: Tournaments, actor: R.Actor | None, tournament_id: str) -> list[dict]:
    """The tournament's audit entries (Admin and the managing Organizer; a participant is told nothing)."""
    actor = _who(actor)
    with reg.store.transaction() as state:
        _managed_rec(state, actor, tournament_id)
        return [copy.deepcopy(a) for a in state["audit"] if a["tournament"] == tournament_id]
