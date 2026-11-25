# SPDX-License-Identifier: AGPL-3.0-only
"""Official roster, invitation codes and registration (BIO-EPIC-05, SRD-038..044, PRD 6.2; CN-020).

Until now a team was just a string that an upload carried. This module is where a team and its members come
from, and who may upload for it:

  * `import_roster` / `parse_csv` / `correct_entry`
        Admin or the assigned Organizer imports the official roster (rows of email, team, member number, role)
        and corrects entries that nobody has registered yet. A row that cannot be applied is rejected on its
        own and listed; the rest of the file is applied. Importing the same file again changes nothing.
  * `issue_codes` / `revoke_code` / `replace_code`
        One single-use code per participant (DEC-01 recommendation). The secret is returned once, to the
        issuer, and only its SHA-256 is stored. Only an Admin revokes or replaces a code.
  * `claim`
        A participant enters the official email and a code. The tournament must be open for registration and
        before its registration deadline. A wrong pair never consumes anything and never reveals which half was
        wrong; failed attempts are counted per email and per source, and a limit only waits (it expires), it
        never locks anybody out for good. A right pair consumes the code, creates the membership, and **locks**
        email, team, member number and role (SRD-042).
  * `confirm_email`
        Called by the account layer when the participant's email is verified. Only a verified member counts as
        registered; one still unverified at the deadline is excluded (SRD-044).
  * `actor_for`, `registered_teams`, `team_view`, `list_roster`, `report`, `list_codes`
        What the other libraries and the API need: the `registry.Actor` of a user (teams, captain-of,
        tournaments), the teams the bracket draw may use, the member list a team may see (no emails), the staff
        views, and the list of excluded participants.
  * `purge_tournament`
        Removes the personal data of a deleted tournament (the audit keeps only ids).

Not here: the HTTP API, passwords and sessions (the caller creates the account and passes its `user_id`),
sending codes or email (the issuer gets the plaintext back), captaincy transfer and account deletion (SRD-065..
067), any correction of a locked entry (an Admin exception is an open decision), the database (DEC-11): the
state is a JSON file with the same lock rules as the other stores. Times are epoch seconds. Standard library.
"""
from __future__ import annotations

import copy
import csv
import hashlib
import hmac
import io
import re
import secrets
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from backend.match_orchestrator.store import JsonFileStore
from backend.submission_registry import registry as R
from backend.tournaments import tournaments as T

SCHEMA = 1

UNREGISTERED, PENDING, REGISTERED = "unregistered", "pending_verification", "registered"
CAPTAIN, MEMBER = "captain", "member"
ROLE_LABELS = (CAPTAIN, MEMBER)
ISSUED, CONSUMED, REVOKED = "issued", "consumed", "revoked"

# Interim numbers (the PRD sets none): a tournament is a few hundred teams; DEC-12 (team size) is open.
MAX_ENTRIES, MAX_TEAM_SIZE, MAX_MEMBER_NUMBER = 2_000, 10, 99
MAX_TEAM_NAME, MAX_EMAIL, MAX_REASON, MAX_FILENAME, MAX_CSV_BYTES = 80, 254, 500, 100, 1_048_576
MAX_AUDIT, MAX_BATCHES = 200_000, 1_000
# Failed-attempt limiter: the window forgets, so a legitimate participant waits at most this long.
ATTEMPT_WINDOW, MAX_FAILS_PER_EMAIL, MAX_FAILS_PER_SOURCE, MAX_ATTEMPT_RECORDS = 900.0, 10, 40, 20_000
EDITABLE_STATUSES = (T.DRAFT, T.REJECTED, T.APPROVED, T.OPEN)
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"        # no 0/O/1/I: the code is read aloud and typed
CODE_LENGTH = 20                                           # 5 bits each: 100 bits, not guessable
_EMAIL_RE = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
                       r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$")
CSV_COLUMNS = ("email", "team_key", "team_name", "member_number", "role")


class RegistrationError(Exception):
    """Base class; the API maps the subclasses to 400/422, 403, 404, 409, 410 and 429."""


class Invalid(RegistrationError):
    """The request itself is wrong (400/422): a bad id, email, reason or field."""


class Mismatch(RegistrationError):
    """Email and code do not match the roster (422). Deliberately says nothing about which half is wrong."""


class NotFound(RegistrationError):
    """No such tournament, entry, code or team, or the actor may not know about it (the same answer)."""


class Forbidden(RegistrationError):
    """The actor may see the tournament but not do this (403)."""


class Conflict(RegistrationError):
    """The request contradicts the stored state (409)."""


class Locked(Conflict):
    """The entry is registered: its email, team, member number and role no longer change (SRD-042)."""


class DeadlineLocked(Conflict):
    """An ordinary roster change after the registration deadline: an Admin extension comes first."""


class AlreadyRegistered(Conflict):
    """The code was consumed by somebody else, or this account already belongs to the tournament (409)."""


class CodeUnavailable(Conflict):
    """The right email and code, but the code was revoked: ask the Organizer or Admin (409)."""


class Closed(RegistrationError):
    """Registration is not open, or its deadline has passed (410)."""


class RateLimited(RegistrationError):
    """Too many failed attempts in the window (429). `retry_after` is when the oldest one is forgotten."""

    def __init__(self, retry_after: float):
        super().__init__(f"too many failed attempts; try again in {int(retry_after) + 1} seconds")
        self.retry_after = retry_after


def _empty_state() -> dict:
    return {"schema": SCHEMA, "tournaments": {}, "attempts": [], "audit": []}


def _state_ok(state) -> bool:
    return isinstance(state, dict) and state.get("schema") == SCHEMA and all(
        isinstance(state.get(k), t) for k, t in (("tournaments", dict), ("attempts", list), ("audit", list)))


class RosterStore(JsonFileStore):
    _empty = staticmethod(_empty_state)
    _layout_ok = staticmethod(_state_ok)


@dataclass
class Registration:
    store: RosterStore
    tournaments: T.Tournaments

    @classmethod
    def at(cls, path: Path | str, tournaments: T.Tournaments) -> "Registration":
        return cls(RosterStore(Path(path)), tournaments)


# ------------------------------------------------------------------------------------------------ helpers

def _iso(t: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def _audit(state: dict, t: float, actor: str, action: str, tournament_id: str, **detail) -> None:
    if len(state["audit"]) >= MAX_AUDIT:
        raise Conflict("the audit list is full; an operator must archive it before anything else changes")
    state["audit"].append({"at": _iso(t), "actor": actor, "action": action, "tournament": tournament_id, **detail})


def _tid(value) -> str:
    if not isinstance(value, str) or not R.TOURNAMENT_ID_RE.fullmatch(value):
        raise Invalid(f"tournament id {value!r} is not a safe identifier")
    return value


def _text(kind: str, value, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit \
            or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise Invalid(f"{kind} must be non-empty text of at most {limit} characters without control characters")
    return value.strip()


def normalize_email(value) -> str:
    """The comparison form of an email: trimmed, lower case, ASCII only (an interim rule: non-ASCII names invite
    look-alike addresses). Raises `Invalid` for anything that is not one plain address."""
    if not isinstance(value, str):
        raise Invalid("email must be text")
    v = value.strip().lower()
    if len(v) > MAX_EMAIL or not v.isascii() or not _EMAIL_RE.fullmatch(v) or ".." in v \
            or v.startswith(".") or v.split("@")[0].endswith("."):
        raise Invalid("not a valid email address")
    return v


def _row(raw) -> dict:
    """One roster row, validated and normalized; raises `Invalid` with a reason that names the field, never the value."""
    if not isinstance(raw, dict):
        raise Invalid("a row must be an object")
    unknown = sorted(str(k) for k in raw if k not in ("email", "team_key", "team_name", "member_number", "role", "role_label"))
    if unknown:
        raise Invalid(f"unknown fields: {', '.join(unknown)}")
    fields = {k: v for k, v in raw.items() if k != "role"}
    if "role" in raw or "role_label" in raw:
        fields["role_label"] = raw.get("role_label", raw.get("role"))
    return _fields(fields)


def _fields(raw: dict) -> dict:
    out = {}
    if "email" in raw:
        out["email"] = normalize_email(raw["email"])
    if "team_key" in raw:
        k = raw["team_key"]
        if not isinstance(k, str) or not R.TEAM_ID_RE.fullmatch(k):
            raise Invalid("team_key must be 1-40 letters, digits, '_' or '-' and start with a letter or digit")
        out["team_key"] = k
    if "team_name" in raw:
        out["team_name"] = _text("team_name", raw["team_name"], MAX_TEAM_NAME)
    if "member_number" in raw:
        n = raw["member_number"]
        if isinstance(n, str) and n.strip().isascii() and n.strip().isdigit():
            n = int(n.strip())
        if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= MAX_MEMBER_NUMBER:
            raise Invalid(f"member_number must be a whole number from 1 to {MAX_MEMBER_NUMBER}")
        out["member_number"] = n
    if "role_label" in raw:
        r = raw["role_label"]
        r = r.strip().lower() if isinstance(r, str) else r
        if r not in ROLE_LABELS:
            raise Invalid(f"role must be one of {', '.join(ROLE_LABELS)}")
        out["role_label"] = r
    return out


def _complete(fields: dict) -> dict:
    missing = [k for k in ("email", "team_key", "team_name", "member_number", "role_label") if k not in fields]
    if missing:
        raise Invalid(f"missing: {', '.join(missing)}")
    return fields


def _tournament_rec(reg: Registration, tournament_id) -> dict:
    rec = reg.tournaments.store.snapshot()["tournaments"].get(tournament_id)
    if rec is None:
        raise NotFound("no such tournament")
    return rec


def _staff(reg: Registration, actor, tournament_id, *, admin_only: bool = False) -> dict:
    """The tournament record for a staff action. A participant is `Forbidden`; an Organizer who does not manage
    the tournament, and anybody for a deleted one (except an Admin reading), is told it does not exist."""
    tid = _tid(tournament_id)
    if not isinstance(actor, R.Actor) or actor.role not in ("admin", "organizer") or not actor.user_id:
        raise Forbidden("this action is not available to this account")
    rec = _tournament_rec(reg, tid)
    if not T.manages(actor, rec) or (rec["status"] == T.DELETED and actor.role != "admin"):
        raise NotFound("no such tournament")
    if admin_only and actor.role != "admin":
        raise Forbidden("only an Admin may do this")
    return rec


def _bucket(state: dict, tid: str) -> dict:
    return state["tournaments"].setdefault(tid, {"entries": {}, "codes": {}, "batches": []})


def _editable(rec: dict, now: float, *, published_only: bool = False) -> None:
    allowed = (T.APPROVED, T.OPEN) if published_only else EDITABLE_STATUSES
    if rec["status"] not in allowed:
        raise Conflict(f"a tournament that is {rec['status']} does not accept this")
    # Before approval nothing has been announced, so the registration deadline has locked nothing yet.
    if rec["status"] in (T.APPROVED, T.OPEN) and rec["deadlines"][T.REGISTRATION] <= now:
        raise DeadlineLocked("the registration deadline has passed; an Admin must extend it first")


def _team_keys_elsewhere(state: dict, tid: str) -> set:
    # Submission folders are named after the team id inside one registry, so a team key must be unique across
    # tournaments: two tournaments sharing "alpha" would share one team's uploads.
    return {e["team_key"] for other, b in state["tournaments"].items() if other != tid for e in b["entries"].values()}


def _problem(entries: dict, e: dict, elsewhere: set) -> str | None:
    """Why `e` cannot be on the roster next to the others, or None. `e` is already in `entries` (tentatively)."""
    team = []
    for o in entries.values():
        if o["id"] == e["id"]:
            continue
        if o["email"] == e["email"]:
            return "this email is already on the roster"
        if o["team_key"] == e["team_key"]:
            team.append(o)
    if e["team_key"] in elsewhere:
        return "this team key belongs to another tournament"
    if any(o["team_name"] != e["team_name"] for o in team):
        return "the team name differs from the other members of the team"
    if any(o["member_number"] == e["member_number"] for o in team):
        return "this member number is already used in the team"
    if len(team) + 1 > MAX_TEAM_SIZE:
        return f"a team has at most {MAX_TEAM_SIZE} members"
    if e["role_label"] == CAPTAIN and any(o["role_label"] == CAPTAIN for o in team):
        return "the team already has a captain"
    return None


def _entry_view(e: dict) -> dict:
    return {k: copy.deepcopy(e[k]) for k in ("id", "email", "team_key", "team_name", "member_number", "role_label",
                                             "status", "version", "locked_at", "verified_at")}


def _new_entry(fields: dict, batch: str, t: float) -> dict:
    return {"id": "e-" + uuid.uuid4().hex[:16], **fields, "status": UNREGISTERED, "user_id": None, "version": 1,
            "batch": batch, "created_at": _iso(t), "locked_at": None, "verified_at": None, "code_id": None}


# ------------------------------------------------------------------------------------------------ roster

def parse_csv(text: str) -> list[dict]:
    """The rows of a roster CSV file (header: email, team_key, team_name, member_number, role). Any other column,
    a missing one, a row with extra cells, or a file over 1 MiB is refused as a whole."""
    if not isinstance(text, str) or "\x00" in text or len(text.encode("utf-8", "replace")) > MAX_CSV_BYTES:
        raise Invalid(f"the roster must be text of at most {MAX_CSV_BYTES} bytes")
    try:
        reader = csv.DictReader(io.StringIO(text.lstrip("﻿"), newline=""), strict=True)
        header = [h.strip().lower() if isinstance(h, str) else h for h in (reader.fieldnames or [])]
        if sorted(header) != sorted(CSV_COLUMNS):
            raise Invalid(f"the header must be exactly: {', '.join(CSV_COLUMNS)}")
        reader.fieldnames = header
        rows = []
        for r in reader:
            if None in r or None in r.values():
                raise Invalid(f"row {len(rows) + 1} has the wrong number of cells")
            rows.append(dict(r))
            if len(rows) > MAX_ENTRIES:
                raise Invalid(f"a roster has at most {MAX_ENTRIES} rows")
        return rows
    except csv.Error as e:
        raise Invalid(f"the CSV file is damaged: {e}") from e


def import_roster(reg: Registration, actor: R.Actor | None, tournament_id: str, rows: list, *,
                  source_filename: str = "roster", now: Callable[[], float] = time.time) -> dict:
    """Apply roster rows (`POST roster/import`). Every row is judged alone: created, updated (an unregistered
    entry with that email), unchanged, or rejected with a reason (`{"row": n, "reason": ...}`, 1-based, no
    personal data). A registered entry is never changed: the same data is `unchanged`, other data is rejected as
    locked. The original file is not kept; the batch keeps only its counts."""
    rec = _staff(reg, actor, tournament_id)
    if not isinstance(rows, list) or not rows or len(rows) > MAX_ENTRIES:
        raise Invalid(f"rows must be a list of 1 to {MAX_ENTRIES} objects")
    name = _text("source_filename", source_filename, MAX_FILENAME)
    t = now()
    _editable(rec, t)
    summary = {"created": 0, "updated": 0, "unchanged": 0, "rejected": []}
    with reg.store.transaction() as state:
        b = _bucket(state, rec["id"])
        entries = b["entries"]
        elsewhere = _team_keys_elsewhere(state, rec["id"])
        by_email = {e["email"]: e for e in entries.values()}
        batch_id = "b-" + uuid.uuid4().hex[:12]
        for i, raw in enumerate(rows, 1):
            try:
                fields = _complete(_row(raw))
                old = by_email.get(fields["email"])
                if old is not None and all(old[k] == fields[k] for k in fields):
                    summary["unchanged"] += 1
                    continue
                if old is not None and (old["status"] != UNREGISTERED or old["locked_at"]):
                    raise Locked("this participant has registered; the entry is locked")
                if old is None:
                    if len(entries) >= MAX_ENTRIES:
                        raise Conflict(f"a roster has at most {MAX_ENTRIES} entries")
                    e = _new_entry(fields, batch_id, t)
                else:
                    e = {**old, **fields, "version": old["version"] + 1}
                trial = {**entries, e["id"]: e}
                why = _problem(trial, e, elsewhere)
                if why:
                    raise Conflict(why)
            except RegistrationError as err:
                summary["rejected"].append({"row": i, "reason": str(err)})
                continue
            if old is None:
                summary["created"] += 1
            else:
                summary["updated"] += 1
            entries[e["id"]] = e
            by_email[e["email"]] = e
        if len(b["batches"]) >= MAX_BATCHES:
            raise Conflict("too many roster imports for this tournament")
        counts = {"created": summary["created"], "updated": summary["updated"], "unchanged": summary["unchanged"],
                  "rejected": len(summary["rejected"])}
        b["batches"].append({"id": batch_id, "uploaded_by": actor.user_id, "source_filename": name,
                             "created_at": _iso(t), "summary": counts})
        _audit(state, t, actor.user_id, "roster_import", rec["id"], batch=batch_id, **counts)
        return {"batch_id": batch_id, **summary}


def correct_entry(reg: Registration, actor: R.Actor | None, tournament_id: str, entry_id: str, changes: dict, *,
                  expected_version: int | None = None, now: Callable[[], float] = time.time) -> dict:
    """Correct an unregistered entry (`PATCH roster/{entry_id}`): email, team_key, team_name, member_number, role.
    A registered entry is `Locked`. Renaming a team changes every member of it, so it needs the whole team
    unregistered. Moving an entry to another team needs the same name as that team (or a new team)."""
    rec = _staff(reg, actor, tournament_id)
    if not isinstance(changes, dict) or not changes:
        raise Invalid("changes must be a non-empty object")
    unknown = sorted(str(k) for k in changes if k not in ("email", "team_key", "team_name", "member_number", "role_label"))
    if unknown:
        raise Invalid(f"fields that cannot be corrected: {', '.join(unknown)}")
    clean = _fields(changes)
    t = now()
    _editable(rec, t)
    with reg.store.transaction() as state:
        b = _bucket(state, rec["id"])
        e = b["entries"].get(entry_id) if isinstance(entry_id, str) else None
        if e is None:
            raise NotFound("no such roster entry")
        if expected_version is not None and expected_version != e["version"]:
            raise Conflict(f"the entry is at version {e['version']}, not {expected_version}")
        if e["status"] != UNREGISTERED or e["locked_at"]:
            raise Locked("this participant has registered; email, team, member number and role are locked")
        new = {**e, **clean}
        if all(e[k] == new[k] for k in clean):
            return _entry_view(e)
        new["version"] = e["version"] + 1
        entries = b["entries"]
        rename = "team_name" in clean and clean["team_name"] != e["team_name"] and clean.get("team_key", e["team_key"]) == e["team_key"]
        mates = [o for o in entries.values() if o["team_key"] == e["team_key"] and o["id"] != e["id"]]
        if rename:
            if any(o["status"] != UNREGISTERED for o in mates):
                raise Locked("a member of this team has registered; the team name is locked")
        trial = {**entries, e["id"]: new}
        if rename:
            for o in mates:
                trial[o["id"]] = {**o, "team_name": clean["team_name"], "version": o["version"] + 1}
        elsewhere = _team_keys_elsewhere(state, rec["id"])
        for o in ([new] + (mates if rename else [])):
            why = _problem(trial, trial[o["id"]], elsewhere)
            if why:
                raise Conflict(why)
        entries.update({k: v for k, v in trial.items() if v is not entries.get(k)})
        _audit(state, t, actor.user_id, "roster_correct", rec["id"], entry=e["id"], fields=sorted(clean),
               renamed_team=bool(rename))
        return _entry_view(entries[e["id"]])


def list_roster(reg: Registration, actor: R.Actor | None, tournament_id: str) -> list[dict]:
    """Every roster entry with emails (`GET roster`): Admin and the managing Organizer only (SRD-064)."""
    rec = _staff(reg, actor, tournament_id)
    b = reg.store.snapshot()["tournaments"].get(rec["id"], {"entries": {}})
    return sorted((_entry_view(e) for e in b["entries"].values()), key=lambda e: (e["team_key"], e["member_number"]))


# ------------------------------------------------------------------------------------------------ codes

def _new_code() -> str:
    raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
    return "-".join(raw[i:i + 5] for i in range(0, CODE_LENGTH, 5))


def _code_key(value) -> str | None:
    """The comparison form of a typed code (upper case, no spaces or dashes), or None when it cannot be one."""
    if not isinstance(value, str) or len(value) > 64:
        return None
    k = re.sub(r"[\s-]", "", value).upper()
    return k if len(k) == CODE_LENGTH and all(c in CODE_ALPHABET for c in k) else None


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode("ascii")).hexdigest()


def _issue(b: dict, entry: dict, by: str, t: float, *, replaces: str | None = None) -> tuple[dict, str]:
    secret = _new_code()
    rec = {"id": "c-" + uuid.uuid4().hex[:16], "entry_id": entry["id"], "code_hash": _hash(_code_key(secret)),
           "status": ISSUED, "issued_by": by, "issued_at": _iso(t), "consumed_at": None, "revoked_at": None,
           "revoked_by": None, "reason": None, "replaces": replaces, "replaced_by": None}
    b["codes"][rec["id"]] = rec
    entry["code_id"] = rec["id"]
    return rec, secret


def issue_codes(reg: Registration, actor: R.Actor | None, tournament_id: str, entry_ids: list | None = None, *,
                now: Callable[[], float] = time.time) -> dict:
    """Issue the first code of each entry (`POST invitation-codes`; `entry_ids=None` means every entry that has
    none yet). Returns `{"issued": [{"entry_id", "code_id", "code"}], "skipped": [{"entry_id", "reason"}]}`: the
    plaintext codes appear here and nowhere else, so the caller delivers them now. An entry that has had a
    code, live or not, is skipped: a lost or compromised code is an Admin's `replace_code`."""
    rec = _staff(reg, actor, tournament_id)
    if entry_ids is not None and (not isinstance(entry_ids, list) or len(entry_ids) > MAX_ENTRIES
                                  or not all(isinstance(i, str) for i in entry_ids)):
        raise Invalid("entry_ids must be a list of entry ids")
    t = now()
    _editable(rec, t, published_only=True)
    out = {"issued": [], "skipped": []}
    with reg.store.transaction() as state:
        b = _bucket(state, rec["id"])
        wanted = sorted(b["entries"]) if entry_ids is None else list(dict.fromkeys(entry_ids))
        for eid in wanted:
            e = b["entries"].get(eid)
            if e is None:
                out["skipped"].append({"entry_id": eid, "reason": "no such roster entry"})
            elif e["status"] != UNREGISTERED:
                out["skipped"].append({"entry_id": eid, "reason": "already registered"})
            elif e["code_id"] is not None:
                if entry_ids is not None:
                    out["skipped"].append({"entry_id": eid, "reason": "a code was already issued; an Admin replaces it"})
            else:
                c, secret = _issue(b, e, actor.user_id, t)
                out["issued"].append({"entry_id": eid, "code_id": c["id"], "code": secret})
        if out["issued"]:
            _audit(state, t, actor.user_id, "codes_issue", rec["id"], count=len(out["issued"]),
                   codes=[i["code_id"] for i in out["issued"]])
        return out


def _code(b: dict, code_id) -> dict:
    c = b["codes"].get(code_id) if isinstance(code_id, str) else None
    if c is None:
        raise NotFound("no such invitation code")
    return c


def revoke_code(reg: Registration, actor: R.Actor | None, tournament_id: str, code_id: str, reason: str, *,
                confirm: bool = False, now: Callable[[], float] = time.time) -> dict:
    """Admin only: a lost or compromised code stops working (`revoke`). A consumed code cannot be revoked (its
    owner is registered). Repeating the call changes nothing."""
    rec = _staff(reg, actor, tournament_id, admin_only=True)
    reason = _text("reason", reason, MAX_REASON)
    if confirm is not True:
        raise Invalid("revoking a code needs confirm=true")
    t = now()
    with reg.store.transaction() as state:
        b = _bucket(state, rec["id"])
        c = _code(b, code_id)
        if c["status"] == CONSUMED:
            raise Conflict("this code has been used; the participant is registered")
        if c["status"] == ISSUED:
            c.update({"status": REVOKED, "revoked_at": _iso(t), "revoked_by": actor.user_id, "reason": reason})
            _audit(state, t, actor.user_id, "code_revoke", rec["id"], code=c["id"], entry=c["entry_id"], reason=reason)
        return _code_view(c, rec, t)


def replace_code(reg: Registration, actor: R.Actor | None, tournament_id: str, code_id: str, reason: str, *,
                 confirm: bool = False, now: Callable[[], float] = time.time) -> dict:
    """Admin only: revoke the code (if it is still live) and issue a new one for the same entry (`replace`).
    Returns `{"code_id", "replaces", "code"}`; the old one stays unusable. A code that was already replaced, or
    was consumed, cannot be replaced again."""
    rec = _staff(reg, actor, tournament_id, admin_only=True)
    reason = _text("reason", reason, MAX_REASON)
    if confirm is not True:
        raise Invalid("replacing a code needs confirm=true")
    t = now()
    _editable(rec, t, published_only=True)
    with reg.store.transaction() as state:
        b = _bucket(state, rec["id"])
        old = _code(b, code_id)
        e = b["entries"][old["entry_id"]]
        if old["status"] == CONSUMED or e["status"] != UNREGISTERED:
            raise Conflict("this participant has registered; there is nothing to replace")
        if old["replaced_by"]:
            raise Conflict("this code has already been replaced")
        if old["status"] == ISSUED:
            old.update({"status": REVOKED, "revoked_at": _iso(t), "revoked_by": actor.user_id, "reason": reason})
        c, secret = _issue(b, e, actor.user_id, t, replaces=old["id"])
        old["replaced_by"] = c["id"]
        _audit(state, t, actor.user_id, "code_replace", rec["id"], old=old["id"], new=c["id"], entry=e["id"], reason=reason)
        return {"code_id": c["id"], "replaces": old["id"], "code": secret}


def _code_view(c: dict, rec: dict, t: float) -> dict:
    # An unused code is `expired` once registration closed; a later extension makes it live again because the
    # state is computed from the deadline, never stored (SRD-041).
    status = c["status"]
    if status == ISSUED and rec["deadlines"][T.REGISTRATION] <= t:
        status = "expired"
    return {"id": c["id"], "entry_id": c["entry_id"], "status": status, "issued_by": c["issued_by"],
            "issued_at": c["issued_at"], "consumed_at": c["consumed_at"], "revoked_at": c["revoked_at"],
            "reason": c["reason"], "replaces": c["replaces"], "replaced_by": c["replaced_by"]}


def list_codes(reg: Registration, actor: R.Actor | None, tournament_id: str, *,
               now: Callable[[], float] = time.time) -> list[dict]:
    """Code records for staff, never the secret or its hash (`GET invitation-codes`)."""
    rec = _staff(reg, actor, tournament_id)
    b = reg.store.snapshot()["tournaments"].get(rec["id"], {"codes": {}})
    t = now()
    return [_code_view(c, rec, t) for c in sorted(b["codes"].values(), key=lambda c: (c["issued_at"], c["id"]))]


# ------------------------------------------------------------------------------------------------ claiming

def _blocked(state: dict, email_key: str, source: str, t: float) -> float | None:
    """Seconds until a failed attempt for this email or source is forgotten, if either limit is reached."""
    state["attempts"][:] = [a for a in state["attempts"] if a["at"] > t - ATTEMPT_WINDOW]
    mine = [a["at"] for a in state["attempts"] if a["email"] == email_key]
    theirs = [a["at"] for a in state["attempts"] if source and a["source"] == source]
    waits = []
    if len(mine) >= MAX_FAILS_PER_EMAIL:
        waits.append(min(mine) + ATTEMPT_WINDOW - t)
    if len(theirs) >= MAX_FAILS_PER_SOURCE:
        waits.append(min(theirs) + ATTEMPT_WINDOW - t)
    if len(state["attempts"]) >= MAX_ATTEMPT_RECORDS:      # fail closed, for at most one window
        waits.append(min(a["at"] for a in state["attempts"]) + ATTEMPT_WINDOW - t)
    return max(waits) if waits else None


def _failed(state: dict, email_key: str, source: str, t: float) -> None:
    if len(state["attempts"]) < MAX_ATTEMPT_RECORDS:
        state["attempts"].append({"at": t, "email": email_key, "source": source})


def _user(value) -> str:
    if not isinstance(value, str) or not R.KEY_RE.fullmatch(value):
        raise Invalid("user_id must be 1-128 characters of letters, digits and . _ : -")
    return value


def _membership(entry: dict) -> dict:
    return {"tournament_id": None, "team_id": entry["team_key"], "entry_id": entry["id"], "user_id": entry["user_id"],
            "member_number": entry["member_number"], "role_label": entry["role_label"],
            "is_captain": entry["role_label"] == CAPTAIN, "registration_status": entry["status"]}


def claim(reg: Registration, tournament_id: str, email: str, code: str, user_id: str, *, source: str | None = None,
          now: Callable[[], float] = time.time) -> dict:
    """Register with the official email and a code (`POST /auth/register`, the roster half). `user_id` is the
    account the caller has just created (or will create: retrying with the same user is safe).

    Order: well-formed input (`Invalid`, not counted) -> registration open and before its deadline (`Closed`) ->
    attempt limit (`RateLimited`) -> the pair. A pair that does not match is `Mismatch`, counted, and consumes
    nothing; it is the same answer for an unknown email, a wrong code, a code of somebody else and a malformed
    code. Only the right pair gets a different answer: a revoked code is `CodeUnavailable`, a code used by
    another account `AlreadyRegistered`. The same account repeating a successful claim gets the same result.
    A success consumes the code, binds the account to the entry, and locks the entry; the member counts as
    registered after `confirm_email`."""
    tid = _tid(tournament_id)
    email = normalize_email(email)
    user = _user(user_id)
    src = source if isinstance(source, str) else ""
    src = src[:128]
    t = now()
    rec = reg.tournaments.store.snapshot()["tournaments"].get(tid)
    if rec is None or rec["status"] != T.OPEN or rec["deadlines"][T.REGISTRATION] <= t:
        raise Closed("registration is not open")
    email_key = hashlib.sha256(email.encode("ascii")).hexdigest()[:24]
    refusal: RegistrationError | None = None
    with reg.store.transaction() as state:
        wait = _blocked(state, email_key, src, t)
        if wait is not None:
            raise RateLimited(max(wait, 0.0))
        bucket = _bucket(state, tid)
        entry = next((e for e in bucket["entries"].values() if e["email"] == email), None)
        key = _code_key(code)
        match = None
        if entry is not None and key is not None:
            digest = _hash(key)
            for c in bucket["codes"].values():     # compare every hash of the entry; no early exit
                if c["entry_id"] == entry["id"] and hmac.compare_digest(c["code_hash"], digest):
                    match = c
        # An exception inside the block would discard the state, so a refusal that must be recorded (the failed
        # attempt) is raised after the block has been written.
        if match is None:
            _failed(state, email_key, src, t)
            refusal = Mismatch("the email and the invitation code do not match the roster")
        elif match["status"] == REVOKED:
            refusal = CodeUnavailable("this code is no longer valid; ask the Organizer or an Admin")
        elif match["status"] == CONSUMED:
            if entry["user_id"] == user:
                return {**_membership(entry), "tournament_id": tid}
            refusal = AlreadyRegistered("this code has already been used")
        elif any(o["user_id"] == user for o in bucket["entries"].values()):
            refusal = AlreadyRegistered("this account already belongs to this tournament")
        else:
            match.update({"status": CONSUMED, "consumed_at": _iso(t)})
            entry.update({"status": PENDING, "user_id": user, "locked_at": _iso(t), "version": entry["version"] + 1})
            _audit(state, t, user, "register_claim", tid, entry=entry["id"], code=match["id"], team=entry["team_key"])
            return {**_membership(entry), "tournament_id": tid}
    raise refusal


def confirm_email(reg: Registration, tournament_id: str, user_id: str, *, now: Callable[[], float] = time.time) -> dict:
    """The account layer calls this when the participant has verified the email. Complete registration happens
    only while registration is open and before its deadline (SRD-044): later, the entry stays pending and the
    participant is excluded until an Admin extends the deadline. Repeating the call is safe."""
    tid, user = _tid(tournament_id), _user(user_id)
    t = now()
    rec = _tournament_rec(reg, tid)
    with reg.store.transaction() as state:
        b = _bucket(state, tid)
        entry = next((e for e in b["entries"].values() if e["user_id"] == user), None)
        if entry is None:
            raise NotFound("this account has not claimed a place in this tournament")
        if entry["status"] == REGISTERED:
            return {**_membership(entry), "tournament_id": tid}
        if rec["status"] != T.OPEN or rec["deadlines"][T.REGISTRATION] <= t:
            raise Closed("registration closed before the email was verified")
        entry.update({"status": REGISTERED, "verified_at": _iso(t), "version": entry["version"] + 1})
        _audit(state, t, user, "register_verified", tid, entry=entry["id"], team=entry["team_key"])
        return {**_membership(entry), "tournament_id": tid}


# ------------------------------------------------------------------------------------------------ what others read

def memberships(reg: Registration, user_id: str) -> list[dict]:
    """Every place this account holds, any status, by tournament."""
    user = _user(user_id)
    out = []
    for tid, b in sorted(reg.store.snapshot()["tournaments"].items()):
        for e in b["entries"].values():
            if e["user_id"] == user:
                out.append({**_membership(e), "tournament_id": tid})
    return out


def actor_for(reg: Registration, user_id: str) -> R.Actor:
    """The participant `Actor` for the other libraries: the teams and tournaments where the account is fully
    registered (an unverified claim gives no access), and the teams it captains (the only uploaders, DEC-02).
    An account without any registration gets an Actor that can do nothing."""
    user = _user(user_id)
    full = [m for m in memberships(reg, user) if m["registration_status"] == REGISTERED]
    return R.Actor(user, "participant", frozenset(m["team_id"] for m in full),
                   frozenset(m["team_id"] for m in full if m["is_captain"]),
                   frozenset(m["tournament_id"] for m in full))


def registered_teams(reg: Registration, tournament_id: str) -> list[str]:
    """Teams with at least one fully registered member, sorted: the list the bracket draw starts from
    (`scheduler.tick(teams_of=...)`). A team with no registered captain is listed too; it cannot upload, so the
    draw reports it as having no active bot."""
    tid = _tid(tournament_id)
    b = reg.store.snapshot()["tournaments"].get(tid, {"entries": {}})
    return sorted({e["team_key"] for e in b["entries"].values() if e["status"] == REGISTERED})


def account_ids(reg: Registration, tournament_id: str, team_id: str | None = None, *,
                verified_only: bool = False) -> list[str]:
    """The accounts that hold a place in the tournament (optionally in one team), sorted: who a notice about the
    tournament or the team goes to. By default an account that claimed a place but has not verified its email
    is included (a deadline change concerns it too); `verified_only=True` lists registered members only."""
    tid = _tid(tournament_id)
    b = reg.store.snapshot()["tournaments"].get(tid, {"entries": {}})
    ok = (REGISTERED,) if verified_only else (PENDING, REGISTERED)
    return sorted({e["user_id"] for e in b["entries"].values()
                   if e["status"] in ok and e["user_id"] and (team_id is None or e["team_key"] == team_id)})


def official_email(reg: Registration, user_id: str) -> str | None:
    """The official roster email of an account, or None. A stand-in for the account layer (EPIC-04), which will
    own the address a participant verified; used only to address email notifications, never stored elsewhere."""
    user = _user(user_id)
    for b in reg.store.snapshot()["tournaments"].values():
        for e in b["entries"].values():
            if e["user_id"] == user:
                return e["email"]
    return None


def team_view(reg: Registration, actor: R.Actor | None, tournament_id: str, team_id: str) -> dict:
    """The team and its registered members (`GET /teams/{id}`): no emails, no codes. A member of the team and
    the staff of the tournament see it; anybody else is told there is no such team."""
    tid = _tid(tournament_id)
    if not isinstance(actor, R.Actor) or actor.role not in R.ROLES or not isinstance(team_id, str):
        raise NotFound("no such team")
    rec = _tournament_rec(reg, tid)
    staff = actor.role in ("admin", "organizer") and T.manages(actor, rec)
    if not staff and not (actor.role == "participant" and team_id in actor.team_ids and tid in actor.tournament_ids):
        raise NotFound("no such team")
    b = reg.store.snapshot()["tournaments"].get(tid, {"entries": {}})
    members = sorted((e for e in b["entries"].values() if e["team_key"] == team_id and e["status"] == REGISTERED),
                     key=lambda e: e["member_number"])
    allm = [e for e in b["entries"].values() if e["team_key"] == team_id]
    if not allm:
        raise NotFound("no such team")
    return {"id": team_id, "tournament_id": tid, "name": allm[0]["team_name"],
            "members": [{"member_number": e["member_number"], "role_label": e["role_label"],
                         "is_captain": e["role_label"] == CAPTAIN} for e in members]}


def report(reg: Registration, actor: R.Actor | None, tournament_id: str, *,
           now: Callable[[], float] = time.time) -> dict:
    """The staff's view of how registration stands (SRD-044): counts per status, the teams that cannot upload
    (no captain on the roster, or no registered captain), and after the deadline the participants who are
    excluded (not fully registered), by entry id."""
    rec = _staff(reg, actor, tournament_id)
    b = reg.store.snapshot()["tournaments"].get(rec["id"], {"entries": {}})
    entries = list(b["entries"].values())
    counts = {s: sum(1 for e in entries if e["status"] == s) for s in (UNREGISTERED, PENDING, REGISTERED)}
    teams = sorted({e["team_key"] for e in entries})
    no_captain = [k for k in teams if not any(e["team_key"] == k and e["role_label"] == CAPTAIN for e in entries)]
    unregistered_captain = [k for k in teams if k not in no_captain and not any(
        e["team_key"] == k and e["role_label"] == CAPTAIN and e["status"] == REGISTERED for e in entries)]
    closed = rec["deadlines"][T.REGISTRATION] <= now()
    return {"entries": len(entries), "teams": len(teams), "counts": counts, "closed": closed,
            "teams_without_captain_on_roster": no_captain, "teams_without_registered_captain": unregistered_captain,
            "excluded": sorted(e["id"] for e in entries if e["status"] != REGISTERED) if closed else []}


def purge_tournament(reg: Registration, actor: R.Actor | None, tournament_id: str, *, confirm: bool = False,
                     now: Callable[[], float] = time.time) -> dict:
    """Admin only, after the tournament was deleted: remove the roster, the codes and the import records (the
    personal data). The audit stays and holds only ids. Repeating the call finds nothing and returns zeros."""
    rec = _staff(reg, actor, tournament_id, admin_only=True)
    if confirm is not True:
        raise Invalid("purging needs confirm=true")
    if rec["status"] != T.DELETED:
        raise Conflict("only the data of a deleted tournament is purged")
    with reg.store.transaction() as state:
        b = state["tournaments"].pop(rec["id"], None)
        out = {"entries": len(b["entries"]) if b else 0, "codes": len(b["codes"]) if b else 0}
        if b:
            _audit(state, now(), actor.user_id, "purge", rec["id"], **out)
        return out
