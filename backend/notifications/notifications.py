# SPDX-License-Identifier: AGPL-3.0-only
"""Dashboard notifications and optional email (BIO-EPIC-06, SRD-060/061, PRD 6.5, NFR-07; CN-022).

Other libraries already *return* notices (a deadline was extended, a setting was overridden); nothing used to
deliver them. This module is where they go:

  * `notify` / `notify_audience` / `notify_notice`
        Create one dashboard notification per recipient for a major event (SRD-061). It always happens, whatever
        the recipient's email preference (SRD-060, NFR-07). Text comes from fixed templates and checked
        parameters, never from a caller-built string. The same `event_key` repeated creates nothing new, so a
        timer or a retried request cannot notify twice.
  * `list_notifications` / `mark_read` / `mark_all_read`
        The recipient's feed (`GET /notifications`, `PATCH /notifications/{id}`). Nobody else can read or touch
        a notification; a foreign or missing id gets the same answer.
  * `update_preferences` / `get_preferences`
        `PATCH /me/notification-preferences`: email can be switched off; the dashboard cannot.
  * `deliver_emails`
        The outbox worker. The email provider is a function the caller passes (DEC-11: none chosen). Attempts,
        failures and retries are recorded; the provider is never called while the store is locked; a failure of
        email never touches the dashboard copy.
  * `purge_tournament`
        Removes the notifications of a deleted tournament.

Privacy: the store holds user ids, not email addresses (the address is looked up at send time), and error
text from a provider is stripped of anything that looks like an address. The webapp supplies the HTTP adapter
(CN-030). Not here: sending a
real email, templates in other languages, mandatory security emails (open decision), account deletion (SRD-065
..067), the database (DEC-11): the state is a JSON file with the lock rules of the other stores. Times are
epoch seconds. Standard library.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from backend.match_orchestrator.store import JsonFileStore
from backend.registration import registration as G
from backend.submission_registry import registry as R
from backend.tournaments import tournaments as T

SCHEMA = 1

MAX_NOTIFICATIONS, MAX_AUDIT, MAX_RECIPIENTS, MAX_PAGE = 500_000, 200_000, 5_000, 200
MAX_ATTEMPTS, LEASE, MAX_BATCH = 5, 300.0, 100
EMAIL_PENDING, EMAIL_SENT, EMAIL_FAILED, EMAIL_DISABLED, EMAIL_NO_ADDRESS = (
    "pending", "sent", "failed", "disabled", "no_address")
_ADDRESS_RE = re.compile(r"[^\s@<>\"']+@[^\s@<>\"']+")


class NotificationError(Exception):
    """Base class; the API maps the subclasses to 400/422, 403, 404 and 409."""


class Invalid(NotificationError):
    """The request itself is wrong (400/422)."""


class Forbidden(NotificationError):
    """No signed-in account, or not allowed (403)."""


class NotFound(NotificationError):
    """No such notification or tournament, or it is not the caller's (404): one answer for both."""


class Conflict(NotificationError):
    """The request contradicts the stored state (409)."""


class Permanent(Exception):
    """Raised by a provider function: this email can never be delivered (bad address, rejected content). It is
    not retried. Any other exception is a temporary failure and is retried with a delay."""


def _empty_state() -> dict:
    return {"schema": SCHEMA, "notifications": {}, "inbox": {}, "preferences": {}, "deliveries": {}, "audit": []}


def _state_ok(state) -> bool:
    return isinstance(state, dict) and state.get("schema") == SCHEMA and all(
        isinstance(state.get(k), dict) for k in ("notifications", "inbox", "preferences", "deliveries")) \
        and isinstance(state.get("audit"), list) and isinstance(state.get("announcement_receipts", {}), dict)


class NotificationStore(JsonFileStore):
    _empty = staticmethod(_empty_state)
    _layout_ok = staticmethod(_state_ok)


@dataclass
class Notifications:
    store: NotificationStore

    @classmethod
    def at(cls, path: Path | str) -> "Notifications":
        return cls(NotificationStore(Path(path)))


# ------------------------------------------------------------------------------------------------ templates

def _utc(t) -> str:
    return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(t))


def _cut(value, n: int = 200) -> str:
    s = "" if value is None else str(value)
    s = "".join(" " if ord(c) < 32 or ord(c) == 127 else c for c in s).strip()
    return s if len(s) <= n else s[:n - 1] + "…"


# name -> (kind, limit); kinds: text (length limit), time (epoch seconds), int (0..limit), choice (tuple)
EVENTS: dict[str, dict] = {
    "announcement": {"params": {"headline": ("text", 120), "message": ("text", 2000)},
                     "render": lambda tid, p: (p["headline"], p["message"])},
    "deadline_extended": {
        "params": {"deadline_type": ("choice", ("registration", "submission")), "old": ("time", 0),
                   "new": ("time", 0), "reason": ("text", 500)},
        "render": lambda tid, p: (
            f"The {p['deadline_type']} deadline of {tid} was extended",
            f"The {p['deadline_type']} deadline moved from {_utc(p['old'])} to {_utc(p['new'])}. "
            f"Reason: {p['reason']}")},
    "emergency_override": {
        "params": {"setting": ("text", 40), "old": ("text", 200), "new": ("text", 200), "reason": ("text", 500),
                   "at": ("text", 40), "authorizer": ("text", 128)},
        "render": lambda tid, p: (
            f"A setting of {tid} was changed by an emergency override",
            f"{p['setting']} changed from \"{p['old']}\" to \"{p['new']}\" at {p['at']}, authorized by "
            f"{p['authorizer']}. Reason: {p['reason']}")},
    "validation_accepted": {
        "params": {"team": ("text", 80), "version": ("int", 1_000_000)},
        "render": lambda tid, p: (
            f"Bot version {p['version']} of {p['team']} passed the check",
            f"The upload of {p['team']} for {tid} passed validation and is now the active version.")},
    "validation_rejected": {
        "params": {"team": ("text", 80), "reason": ("text", 500)},
        "render": lambda tid, p: (
            f"An upload of {p['team']} was rejected",
            f"The upload of {p['team']} for {tid} did not pass validation and was not activated. "
            f"Reason: {p['reason']}")},
    "registration_excluded": {
        "params": {},
        "render": lambda tid, p: (
            f"You are not registered for {tid}",
            f"Registration for {tid} closed before your place was complete (an invitation code claimed and the "
            "email verified). You are excluded from the draw. Ask the organizers whether the deadline can be extended.")},
    "team_excluded": {
        "params": {"team": ("text", 80)},
        "render": lambda tid, p: (
            f"{p['team']} is excluded from the draw of {tid}",
            f"{p['team']} had no active bot when the submission deadline passed, so it is not in the bracket.")},
    "match_result": {
        "params": {"team": ("text", 80), "opponent": ("text", 80), "result": ("choice", ("won", "lost")),
                   "round": ("int", 1_000), "match_id": ("text", 128)},
        "render": lambda tid, p: (
            f"{p['team']} {p['result']} round {p['round']} against {p['opponent']}",
            f"Round {p['round']} of {tid}: {p['team']} {p['result']} against {p['opponent']} (match {p['match_id']}).")},
    "qualified": {
        "params": {"team": ("text", 80), "round": ("int", 1_000)},
        "render": lambda tid, p: (
            f"{p['team']} advances in {tid}",
            f"{p['team']} qualified for the round after round {p['round']} of {tid}.")},
    "eliminated": {
        "params": {"team": ("text", 80), "round": ("int", 1_000)},
        "render": lambda tid, p: (
            f"{p['team']} is eliminated from {tid}",
            f"{p['team']} was eliminated in round {p['round']} of {tid}. Results and brackets stay visible.")},
}


def _param(name: str, spec: tuple, value):
    kind, arg = spec
    if kind == "text":
        if not isinstance(value, str) or not value.strip() or len(value) > arg \
                or any(ord(c) < 32 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in value):
            raise Invalid(f"{name} must be non-empty text of at most {arg} characters without control characters")
        return value.strip()
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= arg:
            raise Invalid(f"{name} must be a whole number from 0 to {arg}")
        return value
    if kind == "time":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value < 4_102_444_800:
            raise Invalid(f"{name} must be a time in epoch seconds")
        return float(value)
    if kind == "choice":
        if value not in arg:
            raise Invalid(f"{name} must be one of {', '.join(arg)}")
        return value
    raise AssertionError(kind)


def render(event_type: str, tournament_id: str, params: dict) -> tuple[str, str]:
    """(title, body) for an event. Unknown event types, missing or extra parameters and bad values are `Invalid`."""
    ev = EVENTS.get(event_type) if isinstance(event_type, str) else None
    if ev is None:
        raise Invalid(f"event_type must be one of {', '.join(sorted(EVENTS))}")
    if not isinstance(params, dict):
        raise Invalid("params must be an object")
    missing = sorted(set(ev["params"]) - set(params))
    extra = sorted(str(k) for k in set(params) - set(ev["params"]))
    if missing or extra:
        raise Invalid("params " + "; ".join(x for x in (f"missing: {', '.join(missing)}" if missing else "",
                                                       f"unknown: {', '.join(extra)}" if extra else "") if x))
    clean = {k: _param(k, ev["params"][k], params[k]) for k in ev["params"]}
    title, body = ev["render"](_tid(tournament_id), clean)
    return _cut(title, 160), body


def from_notice(notice) -> tuple[str, str, dict, str]:
    """(event_type, tournament_id, params, event_key) for a notice returned by `tournaments.extend_deadline` or
    `tournaments.emergency_override`. The key is derived from the whole notice, so the same notice repeated is
    the same event."""
    if not isinstance(notice, dict) or notice.get("kind") not in ("deadline_extended", "emergency_override"):
        raise Invalid("not a notice this module knows")
    kind, tid = notice["kind"], notice.get("tournament")
    key = f"{kind}:{tid}:" + hashlib.sha256(json.dumps(notice, sort_keys=True, default=str).encode()).hexdigest()[:32]
    if kind == "deadline_extended":
        params = {"deadline_type": notice.get("deadline_type"), "old": notice.get("old"), "new": notice.get("new"),
                  "reason": _cut(notice.get("reason"), 500) or "-"}
    else:
        params = {"setting": _cut(notice.get("setting"), 40) or "-", "old": _cut(notice.get("old")) or "-",
                  "new": _cut(notice.get("new")) or "-", "reason": _cut(notice.get("reason"), 500) or "-",
                  "at": _cut(notice.get("at"), 40) or "-", "authorizer": _cut(notice.get("authorizer"), 128) or "-"}
    return kind, tid, params, key


# ------------------------------------------------------------------------------------------------ helpers

def _iso(t: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def _tid(value) -> str:
    if not isinstance(value, str) or not R.TOURNAMENT_ID_RE.fullmatch(value):
        raise Invalid(f"tournament id {value!r} is not a safe identifier")
    return value


def _user(value) -> str:
    if not isinstance(value, str) or not R.KEY_RE.fullmatch(value):
        raise Invalid("user_id must be 1-128 characters of letters, digits and . _ : -")
    return value


def _key(value) -> str:
    if not isinstance(value, str) or not R.KEY_RE.fullmatch(value):
        raise Invalid("event_key must be 1-128 characters of letters, digits and . _ : -")
    return value


def _audit(state: dict, t: float, actor: str, action: str, **detail) -> None:
    if len(state["audit"]) >= MAX_AUDIT:
        raise Conflict("the audit list is full; an operator must archive it before anything else changes")
    state["audit"].append({"at": _iso(t), "actor": actor, "action": action, **detail})


def _me(actor) -> R.Actor:
    if not isinstance(actor, R.Actor) or actor.role not in R.ROLES or not isinstance(actor.user_id, str) \
            or not R.KEY_RE.fullmatch(actor.user_id):
        raise Forbidden("sign in to see notifications")
    return actor


def _email_on(state: dict, user: str) -> bool:
    return state["preferences"].get(user, {}).get("email_enabled", True) is True


def notification_id(event_key: str, user: str) -> str:
    """Stable identifier for a saved event and one recipient."""
    return "n-" + hashlib.sha256(f"{event_key}\0{user}".encode()).hexdigest()[:24]


def _view(n: dict) -> dict:
    return {"id": n["id"], "tournament_id": n["tournament_id"], "event_type": n["event_type"], "title": n["title"],
            "body": n["body"], "created_at": _iso(n["created_at"]), "read": n["read_at"] is not None,
            "read_at": None if n["read_at"] is None else _iso(n["read_at"]), "email_status": n["email_status"]}


def _safe_error(exc: BaseException) -> str:
    """What a failure log may keep: the class and a short message with addresses and control characters removed."""
    return _cut(_ADDRESS_RE.sub("<address>", f"{type(exc).__name__}: {exc}"), 200)


# ------------------------------------------------------------------------------------------------ creating

def notify(center: Notifications, event_type: str, tournament_id: str, recipients, params: dict, *, event_key: str,
           now: Callable[[], float] = time.time) -> dict:
    """Create the dashboard notification for each recipient (user ids). The dashboard copy is created in all
    cases; the email delivery is queued only when the recipient has not switched email off. Repeating the same
    `event_key` for the same recipient creates nothing. Returns `{"created", "existing", "email_queued"}`.
    Called by the system (the timer, the API after an Admin action), never by a participant."""
    title, body = render(event_type, tournament_id, params)
    tid, key = _tid(tournament_id), _key(event_key)
    if isinstance(recipients, (str, bytes)) or not hasattr(recipients, "__iter__"):
        raise Invalid("recipients must be a list of user ids")
    users = sorted({_user(u) for u in recipients})
    if len(users) > MAX_RECIPIENTS:
        raise Invalid(f"at most {MAX_RECIPIENTS} recipients per event")
    with center.store.transaction() as state:
        at = now()
        result = _create_notifications(state, event_type, tid, key, users, title, body, at)
        if result["created"]:
            _audit(state, at, "system", "notify", event_type=event_type, tournament=tid, event_key=key,
                   created=result["created"])
    return result


def _create_notifications(state, event_type, tid, key, users, title, body, at):
    created = existing = queued = 0
    for user in users:
        nid = notification_id(key, user)
        if nid in state["notifications"]:
            existing += 1
            continue
        if len(state["notifications"]) >= MAX_NOTIFICATIONS:
            raise Conflict("the notification store is full; an operator must clean it before anything else changes")
        email = _email_on(state, user)
        state["notifications"][nid] = {
            "id": nid, "recipient": user, "tournament_id": tid, "event_type": event_type, "event_key": key,
            "title": title, "body": body, "created_at": at, "read_at": None,
            "email_status": EMAIL_PENDING if email else EMAIL_DISABLED}
        state["inbox"].setdefault(user, []).append(nid)
        if email:
            state["deliveries"][nid] = {"id": nid, "recipient": user, "status": "pending", "attempts": 0,
                                        "next_at": at, "last_error": None, "provider_message_id": None,
                                        "updated_at": at}
            queued += 1
        created += 1
    return {"created": created, "existing": existing, "email_queued": queued}


def publish_announcement(center: Notifications, reg: G.Registration, actor: R.Actor, tournament_id: str,
                         params: dict, *, idempotency_key: str, now: Callable[[], float] = time.time) -> dict:
    """Publish once to the tournament's verified roster and store an author-attributed audit."""
    me, tid = _me(actor), _tid(tournament_id)
    if me.role != "admin" and (me.role != "organizer" or tid not in me.tournament_ids):
        raise Forbidden("only tournament staff may publish an announcement")
    title, body = render("announcement", tid, params)
    key = _key(idempotency_key)
    event_id = "announcement-" + hashlib.sha256(f"{me.user_id}\0{tid}\0{key}".encode()).hexdigest()
    fingerprint = hashlib.sha256(json.dumps([title, body]).encode()).hexdigest()
    # Serialize publication with lifecycle changes, then commit the result, audit
    # and outbox together. Never call a provider while holding either lock.
    with reg.tournaments.store.transaction() as tournaments:
        record = tournaments["tournaments"].get(tid)
        if record is None or record["status"] == T.DELETED:
            raise NotFound("no such tournament")
        if record["status"] not in (T.APPROVED, T.OPEN, T.RUNNING, T.COMPLETED):
            raise Conflict("announcements require a published, unarchived tournament")
        users = G.account_ids(reg, tid, verified_only=True)
        with center.store.transaction() as state:
            receipts = state.setdefault("announcement_receipts", {})
            if event_id in receipts:
                receipt = receipts[event_id]
                if receipt["fingerprint"] != fingerprint:
                    raise Conflict("key already used for a different announcement")
                return receipt["response"]
            if len(users) > MAX_RECIPIENTS:
                raise Conflict("the tournament exceeds the announcement audience limit")
            at = now()
            result = _create_notifications(state, "announcement", tid, event_id, users, title, body, at)
            response = {"id": event_id, "recipients": result["created"], "email_queued": result["email_queued"]}
            _audit(state, at, me.user_id, "announcement_published", tournament=tid, event_type="announcement",
                   announcement_id=event_id, created=result["created"], email_queued=result["email_queued"])
            receipts[event_id] = {"tournament_id": tid, "fingerprint": fingerprint, "response": response}
            return response


def notify_audience(center: Notifications, reg: G.Registration, event_type: str, tournament_id: str, params: dict, *,
                    event_key: str, team_id: str | None = None, verified_only: bool = False,
                    now: Callable[[], float] = time.time) -> dict:
    """`notify` to the accounts that hold a place in the tournament (or in one team). A tournament nobody has
    registered for notifies nobody and says so (`created` 0)."""
    users = G.account_ids(reg, tournament_id, team_id, verified_only=verified_only)
    return notify(center, event_type, tournament_id, users, params, event_key=event_key, now=now)


def notify_notice(center: Notifications, reg: G.Registration, notice: dict, *,
                  recipients: list[str] | None = None,
                  now: Callable[[], float] = time.time) -> dict:
    """Deliver the notice an Admin action returned (`extend_deadline`, `emergency_override`) to everybody who holds
    a place in that tournament (SRD-035, SRD-037, SRD-061).
    A durable delivery can supply the audience recorded with the action."""
    event_type, tid, params, key = from_notice(notice)
    if recipients is None:
        recipients = G.account_ids(reg, tid)
    return notify(center, event_type, tid, recipients, params, event_key=key, now=now)


# ------------------------------------------------------------------------------------------------ reading

def list_notifications(center: Notifications, actor: R.Actor | None, *, unread_only: bool = False,
                       tournament_id: str | None = None, limit: int = 50, offset: int = 0) -> dict:
    """The caller's own feed, newest first (`GET /notifications`): `{"items", "total", "unread"}`. `total` and
    `unread` count what matches the filter before paging."""
    me = _me(actor)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_PAGE:
        raise Invalid(f"limit must be a whole number from 1 to {MAX_PAGE}")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise Invalid("offset must be a whole number, 0 or more")
    tid = None if tournament_id is None else _tid(tournament_id)
    state = center.store.snapshot()
    mine = [state["notifications"][i] for i in state["inbox"].get(me.user_id, []) if i in state["notifications"]]
    if tid is not None:
        mine = [n for n in mine if n["tournament_id"] == tid]
    unread = sum(1 for n in mine if n["read_at"] is None)
    if unread_only:
        mine = [n for n in mine if n["read_at"] is None]
    mine.sort(key=lambda n: (-n["created_at"], n["id"]))
    return {"items": [_view(n) for n in mine[offset:offset + limit]], "total": len(mine), "unread": unread}


def mark_read(center: Notifications, actor: R.Actor | None, notification_id: str, *, read: bool = True,
              now: Callable[[], float] = time.time) -> dict:
    """Mark one of the caller's notifications read or unread (`PATCH /notifications/{id}`). Somebody else's
    notification and a missing one are the same `NotFound`."""
    me = _me(actor)
    if not isinstance(read, bool):
        raise Invalid("read must be true or false")
    with center.store.transaction() as state:
        n = state["notifications"].get(notification_id) if isinstance(notification_id, str) else None
        if n is None or n["recipient"] != me.user_id:
            raise NotFound("no such notification")
        if (n["read_at"] is not None) != read:
            n["read_at"] = now() if read else None
        return _view(n)


def mark_all_read(center: Notifications, actor: R.Actor | None, *, tournament_id: str | None = None,
                  now: Callable[[], float] = time.time) -> dict:
    """Mark every unread notification of the caller (of one tournament, if given) read. Returns how many changed."""
    me = _me(actor)
    tid = None if tournament_id is None else _tid(tournament_id)
    t, changed = now(), 0
    with center.store.transaction() as state:
        for i in state["inbox"].get(me.user_id, []):
            n = state["notifications"].get(i)
            if n and n["read_at"] is None and (tid is None or n["tournament_id"] == tid):
                n["read_at"] = t
                changed += 1
    return {"changed": changed}


# ------------------------------------------------------------------------------------------------ preferences

def get_preferences(center: Notifications, actor: R.Actor | None) -> dict:
    me = _me(actor)
    p = center.store.snapshot()["preferences"].get(me.user_id, {})
    return {"email_enabled": p.get("email_enabled", True) is True, "dashboard_enabled": True}


def update_preferences(center: Notifications, actor: R.Actor | None, body: dict, *,
                       now: Callable[[], float] = time.time) -> dict:
    """`PATCH /me/notification-preferences` with `{"email_enabled": false}`. Only that field exists: asking to
    switch the dashboard off (or sending anything else) is `Invalid`, and nothing changes. Switching email off
    also stops the emails already queued (checked again when they are sent)."""
    me = _me(actor)
    if not isinstance(body, dict) or set(body) != {"email_enabled"} or not isinstance(body["email_enabled"], bool):
        raise Invalid("send exactly {\"email_enabled\": true|false}; dashboard notifications cannot be disabled")
    value, t = body["email_enabled"], now()
    with center.store.transaction() as state:
        old = state["preferences"].get(me.user_id, {}).get("email_enabled", True)
        if old is not value:
            state["preferences"][me.user_id] = {"email_enabled": value, "updated_at": t}
            _audit(state, t, me.user_id, "set_email_preference", email_enabled=value)
    return {"email_enabled": value, "dashboard_enabled": True}


# ------------------------------------------------------------------------------------------------ the outbox

def default_backoff(attempts: int) -> float:
    """Seconds to wait after the n-th failed attempt: 1, 4, 16, 64 minutes."""
    return min(60.0 * 4 ** max(attempts - 1, 0), 6 * 3600.0)


def deliver_emails(center: Notifications, send: Callable[[dict], str | None],
                   address_of: Callable[[str], str | None], *, limit: int = MAX_BATCH,
                   max_attempts: int = MAX_ATTEMPTS, lease: float = LEASE,
                   backoff: Callable[[int], float] = default_backoff,
                   now: Callable[[], float] = time.time) -> dict:
    """Send the queued emails that are due. `send(message)` is the provider (message: `to`, `subject`, `text`,
    `idempotency_key`; returns its message id) and `address_of(user_id)` gives the address (or None).

    The provider is never called while the store is locked. An email is claimed with a lease first: a crash
    between sending and recording makes it due again after `lease` seconds, so the delivery is at-least-once and
    the provider can drop a repeated `idempotency_key`. The preference is read again at send time. A provider
    `Permanent` failure, or no usable address, ends the delivery at once; any other exception is retried after
    `backoff(attempts)` until `max_attempts`. The dashboard notification is never touched.
    Returns `{"sent", "retry", "skipped", "failed": [notification ids that gave up now]}`."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_BATCH:
        raise Invalid(f"limit must be a whole number from 1 to {MAX_BATCH}")
    report = {"sent": 0, "retry": 0, "skipped": 0, "failed": []}
    t = now()
    jobs = []
    with center.store.transaction() as state:
        due = sorted((d for d in state["deliveries"].values()
                      if d["status"] in ("pending", "sending") and d["next_at"] <= t),
                     key=lambda d: (d["next_at"], d["id"]))
        for d in due:
            if len(jobs) >= limit:
                break
            n = state["notifications"].get(d["id"])
            if n is None:                                          # purged meanwhile
                del state["deliveries"][d["id"]]
            elif not _email_on(state, d["recipient"]):
                _finish(state, d, n, "skipped", EMAIL_DISABLED, t)
                report["skipped"] += 1
            elif d["attempts"] >= max_attempts:                    # claimed max_attempts times and never recorded
                _give_up(state, d, n, "gave up: no recorded outcome after the last attempt", t, report)
            else:
                d.update({"status": "sending", "attempts": d["attempts"] + 1, "next_at": t + lease, "updated_at": t})
                jobs.append((d["id"], d["recipient"], n["title"], n["body"], d["attempts"]))
    for did, user, title, body, attempt in jobs:
        outcome = _attempt(send, address_of, did, user, title, body)
        with center.store.transaction() as state:
            d, n = state["deliveries"].get(did), state["notifications"].get(did)
            if d is None or n is None or d["status"] != "sending":
                continue
            kind, detail, t = outcome[0], outcome[1], now()
            if kind == "sent":
                d["provider_message_id"] = detail
                _finish(state, d, n, "sent", EMAIL_SENT, t)
                report["sent"] += 1
            elif kind == "no_address":
                _finish(state, d, n, "failed", EMAIL_NO_ADDRESS, t, error=detail)
                _audit(state, t, "system", "email_undeliverable", notification=did, reason=EMAIL_NO_ADDRESS)
                report["failed"].append(did)
            elif kind == "permanent" or attempt >= max_attempts:
                _give_up(state, d, n, detail, t, report)
            else:
                d.update({"status": "pending", "next_at": t + backoff(attempt), "last_error": detail, "updated_at": t})
                report["retry"] += 1
    return report


def _attempt(send, address_of, did: str, user: str, title: str, body: str) -> tuple[str, str | None]:
    try:
        address = address_of(user)
    except Exception as e:
        return "retry", _safe_error(e)
    if address is None:
        return "no_address", "no email address for this account"
    try:
        address = G.normalize_email(address)
    except G.Invalid:
        return "no_address", "the email address is not valid"
    try:
        mid = send({"to": address, "subject": title, "text": body, "idempotency_key": did})
    except Permanent as e:
        return "permanent", _safe_error(e)
    except Exception as e:
        return "retry", _safe_error(e)
    return "sent", mid if isinstance(mid, str) and len(mid) <= 200 else None


def _finish(state: dict, d: dict, n: dict, status: str, email_status: str, t: float, *, error: str | None = None) -> None:
    d.update({"status": status, "updated_at": t, "next_at": None})
    if error is not None:
        d["last_error"] = error
    n["email_status"] = email_status


def _give_up(state: dict, d: dict, n: dict, error: str | None, t: float, report: dict) -> None:
    _finish(state, d, n, "failed", EMAIL_FAILED, t, error=error)
    _audit(state, t, "system", "email_failed", notification=d["id"], attempts=d["attempts"])
    report["failed"].append(d["id"])


def delivery_status(center: Notifications, actor: R.Actor | None, notification_id: str) -> dict:
    """Admin: the delivery record of one notification (attempts, last error). Nobody else, and no address."""
    me = _me(actor)
    if me.role != "admin":
        raise Forbidden("only an Admin may read delivery records")
    d = center.store.snapshot()["deliveries"].get(notification_id) if isinstance(notification_id, str) else None
    if d is None:
        raise NotFound("no delivery for this notification")
    return {"notification_id": d["id"], "status": d["status"], "attempts": d["attempts"],
            "last_error": d["last_error"], "provider_message_id": d["provider_message_id"],
            "next_attempt_at": None if d["next_at"] is None else _iso(d["next_at"])}


# ------------------------------------------------------------------------------------------------ deletion

def purge_tournament(center: Notifications, reg: G.Registration, actor: R.Actor | None, tournament_id: str, *,
                     confirm: bool = False, now: Callable[[], float] = time.time) -> dict:
    """Admin only, after the tournament was deleted: remove its notifications and their delivery records. The
    audit stays (ids and counts only). Repeating the call finds nothing and returns zeros."""
    me = _me(actor)
    tid = _tid(tournament_id)
    if me.role != "admin":
        raise Forbidden("only an Admin may purge")
    if confirm is not True:
        raise Invalid("purging needs confirm=true")
    rec = reg.tournaments.store.snapshot()["tournaments"].get(tid)
    if rec is None:
        raise NotFound("no such tournament")
    if rec["status"] != T.DELETED:
        raise Conflict("only the data of a deleted tournament is purged")
    with center.store.transaction() as state:
        gone = [i for i, n in state["notifications"].items() if n["tournament_id"] == tid]
        for i in gone:
            del state["notifications"][i]
            state["deliveries"].pop(i, None)
        for user in list(state["inbox"]):
            state["inbox"][user] = [i for i in state["inbox"][user] if i in state["notifications"]]
            if not state["inbox"][user]:
                del state["inbox"][user]
        receipts = state.get("announcement_receipts", {})
        for event_id in [key for key, receipt in receipts.items() if receipt["tournament_id"] == tid]:
            del receipts[event_id]
        if gone:
            _audit(state, now(), me.user_id, "purge", tournament=tid, notifications=len(gone))
        return {"notifications": len(gone)}
