# SPDX-License-Identifier: AGPL-3.0-only
"""A small durable job queue for the worker (BIO-EPIC-03, SRD-007, CN-017).

Standard library only. It stores *what has to be done* (check an upload, play a round), never the data the
work needs: a job carries ids, and the handler looks the rest up in the registry and the bracket. So a job
can be repeated, duplicated or taken over by another worker without anything being decided twice; the
registry and the orchestrator already make their own steps safe to repeat.

What the queue itself guarantees (each is tested):
  * one live job per `key`: enqueueing the same work twice returns the first job;
  * a job is held by one worker at a time through a claim token and a lease; a worker that dies loses it
    when the lease runs out and the next worker takes it over (that counts as a failure);
  * an answer from a worker that lost its claim is refused and never overwrites a newer one;
  * a failing job is retried with a growing wait and at most `max_attempts` times, then it is `dead`, an
    incident is stored and the alert function can be called; nothing is retried forever without anybody
    being told (`MAX_DEFERRALS` for work that keeps waiting);
  * a damaged queue file is never treated as an empty queue (same rules as the match store).
"""
from __future__ import annotations

import copy
import hmac
import re
import secrets
import time
import uuid
from dataclasses import dataclass
from typing import Callable

from backend.match_orchestrator import orchestrator as O
from backend.match_orchestrator.store import JsonFileStore
from backend.match_runner.match_log import REF_RE

SCHEMA = 1
QUEUED, RUNNING, DONE, DEAD = "queued", "running", "done", "dead"
CHECK_SUBMISSION, RUN_ROUND = "check_submission", "run_round"
DEFAULT_LEASE = 120.0           # seconds; the worker renews it while a handler runs
DEFAULT_MAX_ATTEMPTS = 5        # failures (errors and lost leases) before a job is dead. Interim number.
MAX_DEFERRALS = 1000            # a job that keeps waiting is not left silent for ever
MAX_TEXT = 500
ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
KEY_RE = re.compile(r"^[A-Za-z0-9_.:/-]{1,200}$")


class QueueError(Exception):
    pass


class NotFound(QueueError):
    pass


class Stale(QueueError):
    """The caller no longer holds the job (lease lost and taken over, or already finished)."""


@dataclass(frozen=True)
class JobClaim:
    job_id: str
    token: str
    worker: str
    kind: str
    payload: dict
    attempt: int            # how often this job has been handed out, this one included


def _empty() -> dict:
    return {"schema": SCHEMA, "seq": 0, "jobs": {}, "incidents": []}


def _ok(state) -> bool:
    return isinstance(state, dict) and state.get("schema") == SCHEMA and isinstance(state.get("jobs"), dict) \
        and isinstance(state.get("incidents"), list) and isinstance(state.get("seq"), int)


class QueueStore(JsonFileStore):
    _empty = staticmethod(_empty)
    _layout_ok = staticmethod(_ok)


def _payload_check(kind: str, payload) -> dict:
    """Only ids, never paths or code: the handler resolves everything else itself."""
    if not isinstance(payload, dict):
        raise QueueError("payload must be an object")
    if kind == CHECK_SUBMISSION:
        wanted = {"submission_id": str}
    elif kind == RUN_ROUND:
        wanted = {"bracket_id": str, "round_no": int}
    else:
        raise QueueError(f"unknown job kind {kind!r}")
    if set(payload) != set(wanted):
        raise QueueError(f"{kind} needs exactly {sorted(wanted)}")
    for name, typ in wanted.items():
        v = payload[name]
        if not isinstance(v, typ) or isinstance(v, bool):
            raise QueueError(f"{name} must be a {typ.__name__}")
        if typ is str and not ID_RE.match(v):
            raise QueueError(f"{name} must match {ID_RE.pattern}")
        if typ is int and not 1 <= v <= 1000:
            raise QueueError(f"{name} out of range")
    return dict(payload)


def default_key(kind: str, payload: dict) -> str:
    return kind + ":" + ":".join(str(payload[k]) for k in sorted(payload))


def _iso(t: float) -> str:
    return O._now_iso(t)


def _text(value) -> str:
    return str(value)[:MAX_TEXT]


def _view(job: dict) -> dict:
    """What an operator may read: no claim token."""
    out = copy.deepcopy(job)
    if out.get("claim"):
        out["claim"].pop("token", None)
    return out


def _incident(state: dict, job: dict, kind: str, detail: str, t: float) -> None:
    state["incidents"].append({
        "id": uuid.uuid4().hex, "job_id": job["id"], "incident_type": kind, "job_kind": job["kind"],
        "attempt_count": job["failures"], "status": "open", "alerted_admin_at": None, "alert_error": None,
        "details_redacted": _text(detail), "created_at": _iso(t), "resolved_at": None, "resolved_by": None})


class JobQueue:
    def __init__(self, path, *, max_attempts: int = DEFAULT_MAX_ATTEMPTS,
                 backoff: Callable[[int], float] | None = None):
        if not isinstance(max_attempts, int) or isinstance(max_attempts, bool) or not 1 <= max_attempts <= 100:
            raise QueueError("max_attempts must be 1 to 100")
        self.store = QueueStore(path)
        self.max_attempts = max_attempts
        self.backoff = backoff or default_backoff


def default_backoff(failures: int) -> float:
    """30 s, 60 s, 120 s ... up to one hour."""
    return float(min(3600, 30 * 2 ** max(0, failures - 1)))


# ------------------------------------------------------------------------------------------ producing

def enqueue(q: JobQueue, kind: str, payload: dict, *, key: str | None = None, priority: int = 0,
            now: Callable[[], float] = time.time) -> dict:
    """Add work. If a live (queued or running) job has the same key, that job is returned and `created` is
    False; a finished or dead job does not block new work, so a paused round can be started again."""
    payload = _payload_check(kind, payload)
    key = key if key is not None else default_key(kind, payload)
    if not isinstance(key, str) or not KEY_RE.match(key):
        raise QueueError(f"key must match {KEY_RE.pattern}")
    if not isinstance(priority, int) or isinstance(priority, bool) or not -100 <= priority <= 100:
        raise QueueError("priority must be -100 to 100")
    t = now()
    with q.store.transaction() as state:
        for job in state["jobs"].values():
            if job["key"] == key and job["status"] in (QUEUED, RUNNING):
                return {**_view(job), "created": False}
        state["seq"] += 1
        job = {"id": f"j{state['seq']}", "seq": state["seq"], "kind": kind, "payload": payload, "key": key,
               "priority": priority, "status": QUEUED, "created_at": _iso(t), "not_before": t, "claim": None,
               "attempts": 0, "failures": 0, "deferrals": 0, "last_error": None, "result": None,
               "finished_at": None, "history": [{"at": _iso(t), "event": "queued"}]}
        state["jobs"][job["id"]] = job
        return {**_view(job), "created": True}


def enqueue_check(q: JobQueue, submission_id: str, **kw) -> dict:
    return enqueue(q, CHECK_SUBMISSION, {"submission_id": submission_id}, **kw)


def enqueue_round(q: JobQueue, bracket_id: str, round_no: int, **kw) -> dict:
    return enqueue(q, RUN_ROUND, {"bracket_id": bracket_id, "round_no": round_no}, **kw)


# ------------------------------------------------------------------------------------------ consuming

def _note(job: dict, t: float, event: str, detail: str = "") -> None:
    job["history"].append({"at": _iso(t), "event": event, "detail": _text(detail)} if detail
                          else {"at": _iso(t), "event": event})
    del job["history"][:-30]                    # a job that cycles for days must not grow without bound


def _kill(state: dict, job: dict, t: float, why: str) -> None:
    job.update(status=DEAD, claim=None, finished_at=_iso(t), last_error=_text(why))
    _note(job, t, "dead", why)
    _incident(state, job, "job_dead", why, t)


def claim_next(q: JobQueue, worker: str, *, kinds: tuple[str, ...] | None = None,
               lease: float = DEFAULT_LEASE, now: Callable[[], float] = time.time) -> JobClaim | None:
    """Give the most urgent due job to `worker` (higher priority first, then oldest). A running job whose
    lease ran out is taken over, and that counts as one failure of the job."""
    if not isinstance(worker, str) or not ID_RE.match(worker):
        raise QueueError(f"worker name must match {ID_RE.pattern}")
    if not isinstance(lease, (int, float)) or isinstance(lease, bool) or not 1 <= lease <= 86400:
        raise QueueError("lease must be 1 to 86400 seconds")
    t = now()
    with q.store.transaction() as state:
        while True:
            due = [j for j in state["jobs"].values()
                   if (kinds is None or j["kind"] in kinds)
                   and ((j["status"] == QUEUED and j["not_before"] <= t)
                        or (j["status"] == RUNNING and j["claim"] and j["claim"]["expires"] <= t))]
            if not due:
                return None
            job = min(due, key=lambda j: (-j["priority"], j["seq"]))
            if job["status"] == RUNNING:
                lost = job["claim"]["worker"]
                job["failures"] += 1
                _note(job, t, "lease_expired", f"worker {lost} did not finish or renew in time")
                if job["failures"] >= q.max_attempts:
                    _kill(state, job, t, f"lease expired {job['failures']} times (last worker {lost})")
                    continue
            token = secrets.token_hex(16)
            job.update(status=RUNNING, attempts=job["attempts"] + 1,
                       claim={"token": token, "worker": worker, "at": _iso(t), "expires": t + lease})
            _note(job, t, "claimed", worker)
            return JobClaim(job["id"], token, worker, job["kind"], copy.deepcopy(job["payload"]), job["attempts"])


def _held(state: dict, claim: JobClaim) -> dict:
    job = state["jobs"].get(claim.job_id)
    if job is None:
        raise NotFound("no such job")
    held = job["claim"]
    if job["status"] != RUNNING or not held or not hmac.compare_digest(held["token"], claim.token):
        raise Stale("this worker no longer holds the job")
    return job


def extend(q: JobQueue, claim: JobClaim, *, lease: float = DEFAULT_LEASE,
           now: Callable[[], float] = time.time) -> float:
    """Renew the lease of a job that is still running; returns the new expiry. `Stale` if it was lost."""
    t = now()
    with q.store.transaction() as state:
        job = _held(state, claim)
        job["claim"]["expires"] = t + lease
        return job["claim"]["expires"]


def complete(q: JobQueue, claim: JobClaim, result: dict | None = None, *,
             now: Callable[[], float] = time.time) -> dict:
    t = now()
    with q.store.transaction() as state:
        job = _held(state, claim)
        job.update(status=DONE, claim=None, finished_at=_iso(t),
                   result=O._clean(result) if result is not None else None)
        _note(job, t, "done")
        return _view(job)


def fail(q: JobQueue, claim: JobClaim, error: str, *, permanent: bool = False,
         now: Callable[[], float] = time.time) -> dict:
    """The work failed. Retried after a growing wait until `max_attempts` failures, then dead with an
    incident; `permanent` means retrying cannot help (dead at once)."""
    t = now()
    with q.store.transaction() as state:
        job = _held(state, claim)
        job["failures"] += 1
        job["last_error"] = _text(error)
        _note(job, t, "failed", error)
        if permanent or job["failures"] >= q.max_attempts:
            _kill(state, job, t, error if permanent else f"failed {job['failures']} times: {error}")
        else:
            wait = q.backoff(job["failures"])
            job.update(status=QUEUED, claim=None, not_before=t + wait)
        return _view(job)


def defer(q: JobQueue, claim: JobClaim, seconds: float, reason: str = "", *,
          now: Callable[[], float] = time.time) -> dict:
    """Put the job back to run later without counting a failure (another worker holds the match, the host
    is busy, a worker is shutting down). After `MAX_DEFERRALS` it is declared dead so it cannot wait silently."""
    if not isinstance(seconds, (int, float)) or isinstance(seconds, bool) or not 0 <= seconds <= 86400:
        raise QueueError("seconds must be 0 to 86400")
    t = now()
    with q.store.transaction() as state:
        job = _held(state, claim)
        job["deferrals"] += 1
        _note(job, t, "deferred", reason)
        if job["deferrals"] >= MAX_DEFERRALS:
            _kill(state, job, t, f"deferred {job['deferrals']} times: {reason}")
        else:
            job.update(status=QUEUED, claim=None, not_before=t + seconds)
        return _view(job)


# ------------------------------------------------------------------------------------------ operating

def get_job(q: JobQueue, job_id: str) -> dict:
    with q.store.transaction() as state:
        job = state["jobs"].get(job_id)
        if job is None:
            raise NotFound("no such job")
        return _view(job)


def list_jobs(q: JobQueue, status: str | None = None) -> list[dict]:
    with q.store.transaction() as state:
        return [_view(j) for j in sorted(state["jobs"].values(), key=lambda j: j["seq"])
                if status is None or j["status"] == status]


def stats(q: JobQueue) -> dict:
    out = {QUEUED: 0, RUNNING: 0, DONE: 0, DEAD: 0, "open_incidents": 0}
    with q.store.transaction() as state:
        for j in state["jobs"].values():
            out[j["status"]] += 1
        out["open_incidents"] = sum(1 for i in state["incidents"] if i["status"] == "open")
    return out


def revive(q: JobQueue, job_id: str, actor: str, *, now: Callable[[], float] = time.time) -> dict:
    """An operator puts a dead job back in the queue with a fresh failure count (after fixing the cause).
    Who may call this is the API's decision; the actor is recorded."""
    if not isinstance(actor, str) or not REF_RE.match(actor):
        raise QueueError(f"actor must match {REF_RE.pattern}")
    t = now()
    with q.store.transaction() as state:
        job = state["jobs"].get(job_id)
        if job is None:
            raise NotFound("no such job")
        if job["status"] != DEAD:
            raise QueueError(f"job {job_id} is {job['status']}, not dead")
        for other in state["jobs"].values():
            if other is not job and other["key"] == job["key"] and other["status"] in (QUEUED, RUNNING):
                raise QueueError(f"job {other['id']} already does this work")
        job.update(status=QUEUED, failures=0, deferrals=0, not_before=t, claim=None, finished_at=None)
        _note(job, t, "revived", actor)
        for inc in state["incidents"]:
            if inc["job_id"] == job_id and inc["status"] == "open":
                inc.update(status="resolved", resolved_at=_iso(t), resolved_by=actor)
        return _view(job)


def deliver_alerts(q: JobQueue, alert: Callable[[dict], None] | None, now: Callable[[], float] = time.time) -> int:
    """Send every open incident that was not delivered (at least once); same behaviour as the match store."""
    return O.deliver_alerts(q.store, alert, now)
