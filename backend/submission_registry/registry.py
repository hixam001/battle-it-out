# SPDX-License-Identifier: AGPL-3.0-only
"""Bot submissions: versions, validation history, the active version, deadline lock, access (BIO-EPIC-05,
BIO-REQ-14, SRD-050..058; CN-016).

What the requirements say and what Battlecode gives: nothing here is in the engine. `backend/bot_validator`
and `backend/submission_check` answer "is this file acceptable?"; this module is the state around that
answer.

  * `submit`           a captain uploads a file. Deadline and size are checked, the static check runs at
                       once (SRD-050), the bytes are stored as an immutable version, and the version is
                       `validating` (or `invalid` with the reasons). Same idempotency key = same answer.
  * `claim_check` / `record_verdict` / `run_check`
                       the trial match is done by a worker: take a claim (one worker at a time, with a
                       lease), play, record. `valid` verdict for the exact stored bytes -> `valid`, and the
                       latest valid version becomes active (SRD-051, SRD-052). `rejected` -> `invalid`,
                       the active version is untouched. `inconclusive` -> may be checked again.
  * `history` / `download` / `validation`
                       participants of the team, the assigned Organizer and Admin may read; nobody else can
                       tell that a submission exists (SRD-056..058). Organizer and Admin cannot change.
  * `pin_tournament` / `pinned_folder`
                       once the deadline passed, record which version each team plays with, write-once
                       (SRD-054, SRD-055), and hand out the folder after re-checking the stored bytes.

Not here: the HTTP endpoint, authentication (the caller passes an `Actor`), tournament and deadline storage
(the caller passes the deadline), notifications, rate limiting, deletion and retention of source files, the
database (DEC-11): the state is a JSON file with the same lock rules as the match store. Standard library
only, apart from the repository's own validator and trial modules.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import shutil
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from backend.bot_validator import validator as V
from backend.match_orchestrator.store import JsonFileStore
from backend.submission_check import trial as T
from backend.submission_bundle import bundle as BU

SCHEMA = 1
STORED_NAME = "bot.py"
# Interim, not a product decision (the PRD gives no size): a bot file of this size is already very large.
MAX_UPLOAD_BYTES = 256 * 1024
# Interim cap on versions per team (history is kept forever, so unbounded uploads would be unbounded storage).
MAX_VERSIONS_PER_TEAM = 500
DEFAULT_LEASE = 1800.0                 # seconds a check claim stays valid
TEAM_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$")     # '.' left out: a submission id is a folder name
TOURNAMENT_ID_RE = TEAM_ID_RE
KEY_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
MAX_REASONS, MAX_TEXT = 50, 500

VALIDATING, INVALID, INCONCLUSIVE, VALID = "validating", "invalid", "inconclusive", "valid"
ROLES = ("admin", "organizer", "participant")


class RegistryError(Exception):
    """Base class; the API maps the subclasses to 404, 403, 409, 413 and 503."""


class NotFound(RegistryError):
    """No such submission or team, or the actor may not know about it (the same answer on purpose)."""


class Forbidden(RegistryError):
    """The actor may see the team but not do this (an Organizer uploading, a member who is not the captain)."""


class DeadlineClosed(RegistryError):
    """The submission deadline has passed (409). An Admin extension passes a later deadline."""


class TooLarge(RegistryError):
    """The upload is bigger than the limit (413)."""


class Conflict(RegistryError):
    """The request contradicts the stored state (409): another file under the same idempotency key, a stale
    claim, a verdict for another file, a tournament that does not match, a changed pin."""


class PendingChecks(Conflict):
    """Pinning refused: some teams still have an unfinished check. `teams` lists them."""

    def __init__(self, teams: list[str]):
        super().__init__(f"checks unfinished for teams: {', '.join(teams)}")
        self.teams = teams


class Unavailable(RegistryError):
    """A stored file is missing or no longer matches its hash (503); a staff incident was recorded."""


@dataclass(frozen=True)
class Actor:
    """Who is asking. The API layer fills it from the session; this module does not authenticate.

    admin: reads everything. organizer: reads only `tournament_ids` (assigned), changes nothing.
    participant: reads the teams in `team_ids`; uploads only for the teams in `captain_of` (DEC-02
    recommendation: captain-only upload, every member can read the history)."""
    user_id: str
    role: str
    team_ids: frozenset = frozenset()
    captain_of: frozenset = frozenset()
    tournament_ids: frozenset = frozenset()


@dataclass(frozen=True)
class Claim:
    submission_id: str
    token: str
    folder: Path            # holds exactly bot.py; pass it to `trial.check_submission`
    sha256: str


@dataclass(frozen=True)
class SourceHandle:
    submission_id: str
    path: Path
    sha256: str
    size: int


def _empty_state() -> dict:
    return {"schema": SCHEMA, "submissions": {}, "teams": {}, "idempotency": {}, "pins": {}, "audit": [],
            "incidents": []}


def _state_ok(state) -> bool:
    return isinstance(state, dict) and state.get("schema") == SCHEMA and all(
        isinstance(state.get(k), t) for k, t in (("submissions", dict), ("teams", dict), ("idempotency", dict),
                                                 ("pins", dict), ("audit", list), ("incidents", list)))


class RegistryStore(JsonFileStore):
    """Same lock, atomic write and 'a damaged file is never an empty one' rules as the match store."""
    _empty = staticmethod(_empty_state)
    _layout_ok = staticmethod(_state_ok)


class Registry:
    def __init__(self, root: Path, store_path: Path, *, max_bytes: int = MAX_UPLOAD_BYTES,
                 max_versions: int = MAX_VERSIONS_PER_TEAM):
        """`root` holds one folder per submission (`root/<submission id>/bot.py`), so it can be the
        `bots_dir` of the match runner as it is. Keep it outside the web root and private."""
        self.root = Path(root)
        self.store = RegistryStore(store_path)
        self.max_bytes = max_bytes
        self.max_versions = max_versions
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)


# ---------------------------------------------------------------------------------------------- helpers

def _iso(t: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _check_id(kind: str, value, rx=TEAM_ID_RE) -> str:
    if not isinstance(value, str) or not rx.fullmatch(value):
        raise ValueError(f"{kind} {value!r} is not a safe identifier")
    return value


def _audit(state: dict, t: float, actor: str, action: str, **detail) -> None:
    state["audit"].append({"at": _iso(t), "actor": actor, "action": action, **detail})


def _finding(code: str, message: str, line: int | None = None) -> dict:
    return {"code": code, "message": message, "line": line}


def _can_read(actor: Actor | None, team_id: str, tournament_id: str | None) -> bool:
    if actor is None or actor.role not in ROLES:
        return False
    if actor.role == "admin":
        return True
    if actor.role == "organizer":
        return tournament_id is not None and tournament_id in actor.tournament_ids
    return team_id in actor.team_ids


def _can_upload(actor: Actor | None, team_id: str) -> bool:
    return actor is not None and actor.role == "participant" and team_id in actor.captain_of \
        and team_id in actor.team_ids


def _read_regular(path: Path, limit: int) -> bytes:
    """Read a regular file without following a link, never more than `limit` + 1 bytes."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError("not a regular file")
        with os.fdopen(fd, "rb", closefd=False) as f:
            return f.read(limit + 1)
    finally:
        os.close(fd)


def _write_new(folder: Path, data: bytes) -> None:
    """Create `folder/bot.py` read-only in a private folder. An orphan folder from a crashed upload (no
    record points at it: the caller holds the store lock) is removed first."""
    if os.path.lexists(folder):
        if folder.is_symlink() or not folder.is_dir():
            os.unlink(folder)
        else:
            os.chmod(folder, 0o700)             # a finished version is read-only; an orphan must be removable
            shutil.rmtree(folder)
    os.mkdir(folder, 0o700)
    fd = os.open(folder / STORED_NAME, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    os.chmod(folder, 0o500)
    for d in (folder, folder.parent):
        dfd = os.open(d, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)


def _static(file_name, data: bytes) -> tuple[list[dict], list[dict]]:
    """The static check of SRD-050 on the exact bytes: name, encoding, syntax, entry point, imports."""
    if file_name != STORED_NAME:
        shown = file_name if isinstance(file_name, str) and file_name.isprintable() else "?"
        return [_finding("S-E-FILES", f"the file must be named {STORED_NAME}, not {shown[:80]}")], []
    try:
        source = data.decode("utf-8")
    except UnicodeDecodeError:
        return [_finding("S-E-ENCODING", "the file is not valid UTF-8")], []
    res = V.validate_source(source)
    return ([_finding(f"S-{e['code']}", e["message"], e.get("line")) for e in res["errors"]],
            res.get("warnings", []))


def _clean_validation(stage: str, status: str, reasons, warnings, t: float, extra: dict | None = None) -> dict:
    def text(v):
        return v[:MAX_TEXT] if isinstance(v, str) else ""

    out = {"at": _iso(t), "stage": stage, "status": status,
           "reasons": [{"code": text(r.get("code")), "message": text(r.get("message")),
                        "line": r.get("line") if isinstance(r.get("line"), int) else None,
                        **({"side": r["side"]} if r.get("side") in ("A", "B") else {})}
                       for r in (reasons or [])[:MAX_REASONS] if isinstance(r, dict)],
           "warnings": [{"code": text(w.get("code")), "message": text(w.get("message"))}
                        for w in (warnings or [])[:MAX_REASONS] if isinstance(w, dict)]}
    out.update(extra or {})
    return out


def _view(state: dict, rec: dict) -> dict:
    """What a reader may see. Never the claim token, never a storage path."""
    pinned = sorted(t for t, p in state["pins"].items() if p["teams"].get(rec["team_id"]) == rec["id"])
    keep = ("id", "team_id", "tournament_id", "version", "content_hash", "bytes", "uploaded_by", "uploaded_at",
            "validation_status", "is_active", "activated_at", "superseded_by")
    return {**({"format": "python-bundle", "files": rec["bundle_files"]} if "bundle_files" in rec else {}),
            **{k: rec[k] for k in keep}, "validations": [dict(v) for v in rec["validations"]],
            "check_in_progress": rec["claim"] is not None, "pinned_in": pinned}


def _team(state: dict, team_id: str) -> dict | None:
    return state["teams"].get(team_id)


# ---------------------------------------------------------------------------------------------- upload

def submit(reg: Registry, actor: Actor | None, team_id: str, tournament_id: str, file_name: str, data: bytes, *,
           idempotency_key: str, deadline_at: float, now: Callable[[], float] = time.time,
           _bundle: dict[str, bytes] | None = None) -> dict:
    """Store a new version. Returns its view: `validating`, or `invalid` with the reasons (the participant
    sees them at once, and the invalid version stays in the history)."""
    _check_id("team id", team_id)
    _check_id("tournament id", tournament_id, TOURNAMENT_ID_RE)
    if not isinstance(idempotency_key, str) or not KEY_RE.fullmatch(idempotency_key):
        raise ValueError("an idempotency key of 1 to 128 safe characters is required")
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("data must be bytes")
    if not isinstance(deadline_at, (int, float)) or isinstance(deadline_at, bool):
        raise TypeError("deadline_at must be a UTC timestamp")
    data = bytes(data)
    if not _can_upload(actor, team_id):
        # A reader of the team learns "not allowed"; anybody else learns nothing.
        if _can_read(actor, team_id, tournament_id):
            raise Forbidden("only the team captain may upload a bot")
        raise NotFound("no such team")
    t = now()
    key = f"{team_id}\x00{idempotency_key}"
    digest = BU.digest(_bundle) if _bundle is not None else _sha(data)
    size = sum(map(len, _bundle.values())) if _bundle is not None else len(data)
    with reg.store.transaction() as state:
        known = state["idempotency"].get(key)
        if known:                                   # a retry of an earlier request: same answer, always
            if known["hash"] != digest:
                raise Conflict("this idempotency key was used for a different file")
            return _view(state, state["submissions"][known["id"]])
        team = _team(state, team_id)
        if team and team["tournament_id"] != tournament_id:
            raise Conflict("the team belongs to another tournament")
        if t >= deadline_at:
            raise DeadlineClosed("the submission deadline has passed")
        if size > reg.max_bytes:
            raise TooLarge(f"the file is larger than {reg.max_bytes} bytes")
        team = state["teams"].setdefault(team_id, {"tournament_id": tournament_id, "next_version": 1,
                                                   "active": None})
        version = team["next_version"]
        if version > reg.max_versions:
            raise Conflict(f"the team has reached the limit of {reg.max_versions} versions")
        reasons, warnings = _static(file_name, data)
        if _bundle is not None:
            BU.validate(_bundle)
            reasons, warnings = [], []
        sid = f"{team_id}-v{version}"
        _write_new(reg.root / sid, data)
        if _bundle is not None:
            folder = reg.root / sid
            os.chmod(folder, 0o700)
            for name, raw in _bundle.items():
                if name == STORED_NAME:
                    continue
                fd = os.open(folder / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400)
                with os.fdopen(fd, "wb") as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
            os.chmod(folder, 0o500)
            dfd = os.open(folder, os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        status = INVALID if reasons else VALIDATING
        rec = {"id": sid, "team_id": team_id, "tournament_id": tournament_id, "version": version,
               "content_hash": digest, "bytes": size, "uploaded_by": actor.user_id,
               "uploaded_at": _iso(t), "validation_status": status, "is_active": False, "activated_at": None,
               "superseded_by": None, "claim": None, "deadline_seen": float(deadline_at),
               "validations": [_clean_validation("static", "rejected" if reasons else "passed", reasons, warnings, t)]}
        if _bundle is not None:
            rec["bundle_files"] = sorted(_bundle)
        state["submissions"][sid] = rec
        team["next_version"] = version + 1
        state["idempotency"][key] = {"id": sid, "hash": digest}
        _audit(state, t, actor.user_id, "upload", submission_id=sid, status=status)
        return _view(state, rec)


# ---------------------------------------------------------------------------------------------- checks

def _problem(reg: Registry, rec: dict) -> str | None:
    """Why the stored bytes cannot be trusted, or None when the folder holds exactly bot.py with the stored hash."""
    folder = reg.root / rec["id"]
    try:
        st = os.lstat(folder)
        if not stat.S_ISDIR(st.st_mode):
            return "the submission folder is not a plain folder"
        if "bundle_files" in rec:
            files = BU.snapshot(folder)
            if sorted(files) != rec["bundle_files"] or BU.digest(files) != rec["content_hash"]:
                return "the stored bundle no longer matches its hash"
            return None
        if os.listdir(folder) != [STORED_NAME]:
            return "the submission folder holds other files than bot.py"
        if _sha(_read_regular(folder / STORED_NAME, rec["bytes"])) != rec["content_hash"]:
            return "the stored file no longer matches its hash"
    except (OSError, BU.Invalid) as e:
        return f"the stored file cannot be read ({getattr(e, "strerror", None) or type(e).__name__})"
    return None


def _damaged(state: dict, rec: dict, problem: str, t: float) -> str:
    """Record a staff incident inside the open transaction; the caller raises `Unavailable` after leaving it
    (an exception inside would throw the incident away)."""
    state["incidents"].append({"at": _iso(t), "kind": "submission_file_damaged", "submission_id": rec["id"],
                               "detail": problem, "alerted": False})
    return f"submission {rec['id']} cannot be served: {problem}"


def claim_check(reg: Registry, submission_id: str, *, now: Callable[[], float] = time.time,
                lease: float = DEFAULT_LEASE) -> Claim | None:
    """Take the right to check one version. None if it needs no check or another worker holds a live claim.
    A claim older than its lease can be taken over (a worker that died)."""
    t = now()
    damage = None
    with reg.store.transaction() as state:
        rec = state["submissions"].get(submission_id)
        if rec is None:
            raise NotFound("no such submission")
        if rec["validation_status"] not in (VALIDATING, INCONCLUSIVE):
            return None
        if rec["claim"] and t < rec["claim"]["expires"]:
            return None
        problem = _problem(reg, rec)
        if problem:
            damage = _damaged(state, rec, problem, t)
        else:
            token = secrets.token_hex(16)
            rec["claim"] = {"token": token, "at": _iso(t), "expires": t + lease}
            rec["validation_status"] = VALIDATING
            return Claim(submission_id, token, reg.root / submission_id, rec["content_hash"])
    raise Unavailable(damage)


def release_claim(reg: Registry, claim: Claim) -> None:
    """Give a claim back without a verdict (the check itself failed to run); the version can be claimed again."""
    with reg.store.transaction() as state:
        rec = state["submissions"].get(claim.submission_id)
        if rec and rec["claim"] and hmac.compare_digest(rec["claim"]["token"], claim.token):
            rec["claim"] = None


def record_verdict(reg: Registry, claim: Claim, verdict: dict, *, now: Callable[[], float] = time.time) -> dict:
    """Store the outcome of the trial match for the claimed version and apply the activation rule.

    The claim must be the live one (a stale worker cannot overwrite a newer outcome), and the verdict must be
    about exactly the stored file. Only a verdict that `trial.may_activate` accepts makes a version valid.
    """
    t = now()
    if not isinstance(verdict, dict) or verdict.get("schema") != T.SCHEMA:
        raise Conflict("not a submission-check verdict")
    status = verdict.get("status")
    if status not in ("valid", "rejected", "inconclusive"):
        raise Conflict("the verdict has an unknown status")
    with reg.store.transaction() as state:
        rec = state["submissions"].get(claim.submission_id)
        if rec is None:
            raise NotFound("no such submission")
        if not rec["claim"] or not hmac.compare_digest(rec["claim"]["token"], claim.token):
            raise Conflict("this check claim is not the current one")
        if verdict.get("sha256") != rec["content_hash"]:
            raise Conflict("the verdict is about another file than the stored version")
        if status == "valid" and not T.may_activate(verdict, rec["content_hash"]):
            raise Conflict("a valid verdict must have no reasons")
        new = {"valid": VALID, "rejected": INVALID, "inconclusive": INCONCLUSIVE}[status]
        extra = {"trials": [{k: tr.get(k) for k in ("candidate_side", "judgement", "outcome", "classification",
                                                    "round", "seconds") if isinstance(tr, dict)}
                            for tr in (verdict.get("trials") or [])[:4]],
                 "checked_at": verdict.get("checked_at") if isinstance(verdict.get("checked_at"), str) else None}
        rec["validations"].append(_clean_validation(
            str(verdict.get("stage"))[:20], status, verdict.get("reasons"), verdict.get("warnings"), t, extra))
        rec["validation_status"] = new
        rec["claim"] = None
        activated = False
        if new == VALID:
            team = state["teams"][rec["team_id"]]
            current = state["submissions"].get(team["active"]) if team["active"] else None
            if current is None or current["version"] < rec["version"]:     # the latest valid version wins
                if current is not None:
                    current["is_active"], current["superseded_by"] = False, rec["id"]
                rec["is_active"], rec["activated_at"] = True, _iso(t)
                team["active"] = rec["id"]
                activated = True
        _audit(state, t, "system", "verdict", submission_id=rec["id"], status=new, activated=activated)
        return _view(state, rec)


def run_check(reg: Registry, submission_id: str, check: Callable[[Path], dict], *,
              now: Callable[[], float] = time.time, lease: float = DEFAULT_LEASE) -> dict | None:
    """Claim, run `check(folder)` (normally `trial.check_submission` with a game player), record. None if
    nothing was to do. If `check` raises, the claim is given back and the exception goes on: a failure to run
    the check is not a verdict about the bot."""
    claim = claim_check(reg, submission_id, now=now, lease=lease)
    if claim is None:
        return None
    try:
        verdict = check(reg.root / submission_id)
    except BaseException:
        release_claim(reg, claim)
        raise
    return record_verdict(reg, claim, verdict, now=now)


# ---------------------------------------------------------------------------------------------- reading

def _readable(state: dict, actor: Actor | None, submission_id: str) -> dict:
    rec = state["submissions"].get(submission_id) if isinstance(submission_id, str) else None
    if rec is None or not _can_read(actor, rec["team_id"], rec["tournament_id"]):
        raise NotFound("no such submission")
    return rec


def history(reg: Registry, actor: Actor | None, team_id: str) -> list[dict]:
    """Every version of a team, oldest first, with the validation outcomes (SRD-053, SRD-056, SRD-057)."""
    state = reg.store.snapshot()
    team = _team(state, team_id) if isinstance(team_id, str) else None
    if team is None:
        if actor is not None and (actor.role == "admin" or (actor.role == "participant" and team_id in actor.team_ids)):
            return []
        raise NotFound("no such team")
    if not _can_read(actor, team_id, team["tournament_id"]):
        raise NotFound("no such team")
    recs = sorted((r for r in state["submissions"].values() if r["team_id"] == team_id), key=lambda r: r["version"])
    return [_view(state, r) for r in recs]


def validation(reg: Registry, actor: Actor | None, submission_id: str) -> list[dict]:
    state = reg.store.snapshot()
    return _view(state, _readable(state, actor, submission_id))["validations"]


def active_submission(reg: Registry, actor: Actor | None, team_id: str) -> dict | None:
    """The team's active version, or None (no valid version yet)."""
    state = reg.store.snapshot()
    team = _team(state, team_id) if isinstance(team_id, str) else None
    if team is None or not _can_read(actor, team_id, team["tournament_id"]):
        raise NotFound("no such team")
    return _view(state, state["submissions"][team["active"]]) if team["active"] else None


def download(reg: Registry, actor: Actor | None, submission_id: str, *,
             now: Callable[[], float] = time.time) -> SourceHandle:
    """The source file for a reader, after the stored bytes were verified. Reads by anyone outside the team
    (Organizer, Admin) are written to the audit log (SRD-058)."""
    t = now()
    damage = None
    with reg.store.transaction() as state:
        rec = _readable(state, actor, submission_id)
        problem = _problem(reg, rec)
        if problem:
            damage = _damaged(state, rec, problem, t)
        else:
            if actor.role != "participant":
                _audit(state, t, actor.user_id, "download", submission_id=rec["id"], role=actor.role)
            if "bundle_files" in rec:
                raise Conflict("download this submission as a bundle ZIP")
            return SourceHandle(rec["id"], reg.root / rec["id"] / STORED_NAME, rec["content_hash"], rec["bytes"])
    raise Unavailable(damage)


# ---------------------------------------------------------------------------------------------- pins

def _collect_pins(state: dict, tournament_id: str, team_ids: list[str]) -> tuple[dict, list[str]]:
    """`({team: active submission or None}, teams whose newest version is still being checked)`. Reads only."""
    pins, pending = {}, []
    for tid in team_ids:
        team = _team(state, tid)
        if team is not None and team["tournament_id"] != tournament_id:
            raise Conflict(f"team {tid} belongs to another tournament")
        active = team["active"] if team else None
        latest = max((r for r in state["submissions"].values() if r["team_id"] == tid),
                     key=lambda r: r["version"], default=None)
        if latest and latest["validation_status"] in (VALIDATING, INCONCLUSIVE) and (
                active is None or state["submissions"][active]["version"] < latest["version"]):
            pending.append(tid)
        pins[tid] = active
    return pins, pending


def _check_team_ids(tournament_id: str, team_ids) -> None:
    _check_id("tournament id", tournament_id, TOURNAMENT_ID_RE)
    if not isinstance(team_ids, list) or not team_ids or len(set(team_ids)) != len(team_ids):
        raise ValueError("team_ids must be a non-empty list without duplicates")
    for tid in team_ids:
        _check_id("team id", tid)


def preview_pins(reg: Registry, tournament_id: str, team_ids: list[str]) -> dict:
    """What `pin_tournament` would record right now, without recording it (no deadline check, nothing written).
    Returns `{"pinned": bool, "teams": {team: submission id or None}, "pending": [teams still being checked]}`;
    once the tournament is pinned, `teams` is the stored pin and `pending` is empty.

    It exists so a caller can refuse a draw that cannot work (fewer than two playable teams) BEFORE the
    write-once pin is made: a pin made for a tournament that cannot be drawn could never be corrected by a
    deadline extension. An active version is never removed, so what a preview shows as playable stays
    playable when the pin is made a moment later."""
    _check_team_ids(tournament_id, team_ids)
    with reg.store.transaction() as state:
        existing = state["pins"].get(tournament_id)
        if existing:
            return {"pinned": True, "teams": dict(existing["teams"]), "pending": []}
        pins, pending = _collect_pins(state, tournament_id, team_ids)
        return {"pinned": False, "teams": pins, "pending": pending}


def pin_tournament(reg: Registry, tournament_id: str, team_ids: list[str], *, deadline_at: float,
                   now: Callable[[], float] = time.time, allow_unchecked: bool = False) -> dict:
    """Record, once, which version each team plays with (SRD-054, SRD-055). Returns `{team_id: submission id or
    None}`; None = the team has no active version.

    Refused before the deadline, and while some team has a version still being checked (`PendingChecks`)
    unless `allow_unchecked`. Write-once: a second call returns the stored pins and never changes them (a
    later upload or an extension cannot move a bracket that is already drawn).
    """
    _check_team_ids(tournament_id, team_ids)
    t = now()
    with reg.store.transaction() as state:
        existing = state["pins"].get(tournament_id)
        if existing:
            if set(existing["teams"]) != set(team_ids):
                raise Conflict("the tournament was already pinned for another set of teams")
            return dict(existing["teams"])
        if t < deadline_at:
            raise Conflict("submissions are still open")
        pins, pending = _collect_pins(state, tournament_id, team_ids)
        if pending and not allow_unchecked:
            raise PendingChecks(pending)
        state["pins"][tournament_id] = {"pinned_at": _iso(t), "teams": pins}
        _audit(state, t, "system", "pin", tournament_id=tournament_id, teams=len(pins))
        return dict(pins)


def pinned_folder(reg: Registry, tournament_id: str, team_id: str, *, now: Callable[[], float] = time.time) -> Path:
    """The folder name to give the match runner for a team: `reg.root / <id>`, returned only after the stored
    bytes were verified. Raises `NotFound` for an unpinned tournament or a team without a pinned version."""
    t = now()
    damage = None
    with reg.store.transaction() as state:
        pin = state["pins"].get(tournament_id)
        sid = pin["teams"].get(team_id) if pin else None
        if not sid:
            raise NotFound("no pinned submission")
        rec = state["submissions"][sid]
        problem = _problem(reg, rec)
        if problem:
            damage = _damaged(state, rec, problem, t)
        else:
            return reg.root / sid
    raise Unavailable(damage)


def verify_pins(reg: Registry, tournament_id: str, *, now: Callable[[], float] = time.time) -> list[str]:
    """Re-check every pinned folder; returns the submission ids that no longer match (each also raises an
    incident). Run before each round."""
    t = now()
    bad = []
    with reg.store.transaction() as state:
        pin = state["pins"].get(tournament_id)
        if pin is None:
            raise NotFound("no pins for this tournament")
        for sid in sorted({s for s in pin["teams"].values() if s}):
            problem = _problem(reg, state["submissions"][sid])
            if problem:
                _damaged(state, state["submissions"][sid], problem, t)
                bad.append(sid)
    return bad


def submit_bundle(reg, actor, team_id, tournament_id, data, **kwargs):
    """Explicit multi-file upload; existing single-file callers remain unchanged."""
    if not _can_upload(actor, team_id):
        raise NotFound("no such team")
    files = BU.unpack(data)
    return submit(reg, actor, team_id, tournament_id, STORED_NAME, files[STORED_NAME], _bundle=files, **kwargs)


def download_bundle(reg, actor, submission_id, *, now=time.time):
    damage = None
    with reg.store.transaction() as state:
        rec = _readable(state, actor, submission_id)
        if "bundle_files" not in rec:
            raise Conflict("this is a single-file submission")
        problem = _problem(reg, rec)
        if problem:
            damage = _damaged(state, rec, problem, now())
        else:
            files = BU.snapshot(reg.root / rec["id"])
            if BU.digest(files) != rec["content_hash"]:
                damage = _damaged(state, rec, "bundle changed during download", now())
            else:
                if actor.role != "participant":
                    _audit(state, now(), actor.user_id, "download_bundle", submission_id=rec["id"], role=actor.role)
                return BU.export(files)
    raise Unavailable(damage)
