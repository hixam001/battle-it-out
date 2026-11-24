# SPDX-License-Identifier: AGPL-3.0-only
"""Match jobs with platform retry (BIO-301 core, BIO-306).

One `run_match_job` call drives ONE match to a final state by running attempts through a caller-supplied
function (normally the launcher in `backend/match_runner`). It implements the rules in PRD, SRD-010/011,
DATA_MODEL "Match" and TEST_PLAN TC-04:

  * a bot failure (crash, timeout, limit breach) is a game result: the other team wins by forfeit and
    the match is NOT retried;
  * a platform failure is retried with the same map and the same bot versions, up to a cap;
  * at the cap the match is paused, an incident is recorded and an alert is delivered;
  * a result is recorded once: a duplicate delivery of the job, a second worker, or a late answer from a
    worker that was replaced changes nothing, and bracket advancement can be taken exactly once.

Not here: bracket and bye rules (BIO-303), tie-break maps and the coin flip (BIO-304: `tiebreak.py`), replay storage
(BIO-305: `replays.py`), the real notification channel for the Admin alert, the web API. See README.md.

States follow DATA_MODEL: scheduled -> queued -> running -> completed, with
running -> platform_failed -> retry_queued -> running for retries. `paused` is OUR name for the state
after the cap (the final name is an open decision, DATA_MODEL "[DECIDE]"). `bot_forfeit` and
`platform_failed` are recorded in the history; the match moves on from them at once.
"""
from __future__ import annotations

import contextlib
import copy
import dataclasses
import fcntl
import os
import re
import time
import uuid
from pathlib import Path
from typing import Callable

from backend.match_orchestrator.store import JsonFileStore
from backend.match_runner import launcher as L
from backend.match_runner.launcher import TEAM_DIR_RE
from backend.match_runner.match_log import REF_RE

MAP_RE = re.compile(r"^[A-Za-z0-9_.,-]{1,200}$")
DEFAULT_MAX_ATTEMPTS = 10        # DEC-05 recommendation: 10 attempts in total. Interim, see CN-009.
DEFAULT_LEASE_SECONDS = 2400     # must exceed the launcher's match timeout (1800 s by default)
MAX_TEXT = 500
OUTCOMES = ("completed", "bot_failure", "platform_failure")

# Match states (DATA_MODEL "Match"); PAUSED is provisional.
SCHEDULED, QUEUED, RUNNING, PLATFORM_FAILED, RETRY_QUEUED, BOT_FORFEIT, COMPLETED, PAUSED = (
    "scheduled", "queued", "running", "platform_failed", "retry_queued", "bot_forfeit", "completed", "paused")

# Parts of the launcher result that are worth keeping. Everything else (host paths of logs, raw
# exit codes, router internals) stays in the structured log the launcher already wrote.
SUMMARY_KEYS = ("classification", "kind", "detail", "loser", "winner", "winning_team", "winner_by_forfeit",
                "round", "reason", "seconds", "python", "replay", "replay_sha256", "replay_bytes",
                "structured_log", "usage", "limits_profile", "evidence", "violation", "ok")


class OrchestratorError(Exception):
    pass


class ConflictError(OrchestratorError):
    """create_match was called again with the same id but different content."""


class ConfigurationError(Exception):
    """Raised by a run function when retrying cannot help (a missing bot folder, a failed version check).

    The match is paused at once instead of burning the whole retry budget on the same mistake.
    """


@dataclasses.dataclass(frozen=True)
class AttemptContext:
    """What a run function gets. Identical in every attempt except `attempt`, `trace_id` and `seed`."""
    match_id: str
    attempt: int
    trace_id: str
    team_a: str
    team_b: str
    map: str
    submission_a: str
    submission_b: str
    seed: int | None


def _now_iso(t: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def _clean(value, depth: int = 0):
    """Make a launcher value safe to keep: JSON types only, bounded size and depth."""
    if isinstance(value, str):
        return value[:MAX_TEXT]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if depth >= 3:
        return None
    if isinstance(value, dict):
        return {str(k)[:64]: _clean(v, depth + 1) for k, v in list(value.items())[:40]}
    if isinstance(value, (list, tuple)):
        return [_clean(v, depth + 1) for v in list(value)[:40]]
    return str(value)[:MAX_TEXT]


def _log_path(value) -> str | None:
    """The launcher reports {"path": ..., "events": ...}, or {"error": ...} when writing the log failed."""
    if isinstance(value, dict) and isinstance(value.get("path"), str):
        return value["path"]
    return None


def _other(side: str) -> str:
    return "B" if side == "A" else "A"


def interpret(result, require_reason: bool = False) -> dict:
    """Turn a run function's answer into one of three verdicts, trusting nothing that is not consistent.

    Returns {"class": "completed"|"bot_failure"|"platform_failure", ...}. An answer that is missing a
    field, contradicts itself or is not a dict is a platform failure (`malformed_result`): the platform
    must not invent a winner. With `require_reason` (games of a tie-break series, BIO-304) a completed
    result must also carry the engine's reason line: whether the game was decided or tied depends on it.
    """
    def platform(kind, detail):
        return {"class": "platform_failure", "kind": kind, "detail": str(detail)[:MAX_TEXT]}

    if not isinstance(result, dict):
        return platform("malformed_result", f"run function returned {type(result).__name__}, not a dict")
    outcome = result.get("outcome")
    summary = {k: _clean(result[k]) for k in SUMMARY_KEYS if k in result}
    if outcome == "completed":
        winner = result.get("winner")
        if result.get("classification") != "normal" or winner not in ("A", "B"):
            return platform("malformed_result", "completed without a normal classification and a winner A or B")
        if result.get("ok") is not True:
            # The engine printed a winner but the process did not end cleanly (non-zero exit, timeout):
            # the replay may be incomplete, so do not publish it. Retry.
            return platform("unclean_completion", "the match has a winner but did not end cleanly")
        if require_reason and not (isinstance(result.get("reason"), str) and result["reason"].strip()):
            return platform("missing_reason", "completed without the engine's reason line; cannot tell a win from a tie")
        return {"class": "completed", "winner_side": winner, "summary": summary}
    if outcome == "bot_failure":
        loser = result.get("loser")
        if result.get("classification") not in ("bot_violation", "bot_crash") or loser not in ("A", "B") \
                or result.get("winner_by_forfeit") != _other(loser):
            return platform("malformed_result", "bot_failure without a consistent loser and forfeit winner")
        return {"class": "bot_failure", "winner_side": _other(loser), "loser_side": loser,
                "kind": str(result.get("kind") or result.get("classification"))[:64],
                "detail": str(result.get("detail") or "")[:MAX_TEXT], "summary": summary}
    if outcome == "platform_failure":
        out = platform(str(result.get("kind") or "unknown")[:64], result.get("detail") or "")
        out["summary"] = summary
        return out
    return platform("malformed_result", f"unknown outcome {outcome!r}")


# ------------------------------------------------------------------------------------------
# state changes: each function is one transaction
# ------------------------------------------------------------------------------------------
def _move(match: dict, to: str, now: float, note: str = "") -> None:
    match["history"].append({"at": _now_iso(now), "from": match["status"], "to": to, "note": note[:MAX_TEXT]})
    match["status"] = to


def _validate_new(match_id, team_a, team_b, map_name, submission_a, submission_b, max_attempts) -> dict:
    for what, v in (("match_id", match_id), ("team_a", team_a), ("team_b", team_b),
                    ("submission_a", submission_a), ("submission_b", submission_b)):
        if not isinstance(v, str) or not REF_RE.match(v):
            raise OrchestratorError(f"{what} must match {REF_RE.pattern}")
    if not isinstance(map_name, str) or not MAP_RE.match(map_name):
        raise OrchestratorError(f"map must match {MAP_RE.pattern}")
    if not isinstance(max_attempts, int) or isinstance(max_attempts, bool) or not 1 <= max_attempts <= 100:
        raise OrchestratorError("max_attempts must be an integer from 1 to 100")
    return {"team_a": team_a, "team_b": team_b, "map": map_name,
            "submission_a": submission_a, "submission_b": submission_b}


def _create_in(state: dict, match_id: str, team_a: str, team_b: str, map_name: str, submission_a: str,
               submission_b: str, max_attempts: int, t: float, series_game: bool = False) -> dict:
    """Create a match inside an open transaction (the caller deep-copies what it returns)."""
    identity = _validate_new(match_id, team_a, team_b, map_name, submission_a, submission_b, max_attempts)
    existing = state["matches"].get(match_id)
    if existing is not None:
        if {k: existing[k] for k in identity} != identity:
            raise ConflictError(f"match {match_id} already exists with different teams, map or submissions")
        return existing
    match = {"id": match_id, **identity, "status": SCHEDULED, "max_attempts": max_attempts,
             "created_at": _now_iso(t), "attempts": [], "history": [], "lease": None, "result": None,
             "advancement": {"pending": False, "taken_at": None}}
    if series_game:
        # One game of a tie-break series (tiebreak.py): its result is NOT handed to bracket advancement;
        # only the series result is, once every tie-break game is played.
        match["series_game"] = True
    state["matches"][match_id] = match
    return match


def create_match(store: JsonFileStore, match_id: str, team_a: str, team_b: str, map_name: str,
                 submission_a: str, submission_b: str, *, max_attempts: int = DEFAULT_MAX_ATTEMPTS,
                 now: Callable[[], float] = time.time) -> dict:
    """Create a match in `scheduled`. Calling it again with the same content returns the same match.

    `team_*` and `submission_*` are opaque references; the submission references pin the exact bot
    versions for every attempt. Nothing can change them afterwards.
    """
    with store.transaction() as state:
        return copy.deepcopy(_create_in(state, match_id, team_a, team_b, map_name, submission_a, submission_b,
                                        max_attempts, now()))


def queue_match(store: JsonFileStore, match_id: str, now: Callable[[], float] = time.time) -> str:
    """scheduled -> queued. Already queued or later: no change. Returns the status."""
    with store.transaction() as state:
        match = _get(state, match_id)
        if match["status"] == SCHEDULED:
            _move(match, QUEUED, now())
        return match["status"]


def _get(state: dict, match_id: str) -> dict:
    match = state["matches"].get(match_id)
    if match is None:
        raise OrchestratorError(f"unknown match {match_id}")
    return match


def _platform_failures(match: dict) -> int:
    return sum(1 for a in match["attempts"] if a["status"] == "platform_failed")


def _after_platform_failure(state: dict, match: dict, now: float, kind: str) -> None:
    """The attempt just recorded as platform_failed: retry, or pause and open an incident at the cap."""
    _move(match, PLATFORM_FAILED, now, kind)
    failures = _platform_failures(match)
    if failures >= match["max_attempts"]:
        _pause(state, match, now, "retry_cap_reached", failures, f"last failure: {kind}")
    else:
        _move(match, RETRY_QUEUED, now, f"failure {failures} of {match['max_attempts']}")


def _pause(state: dict, match: dict, now: float, incident_type: str, count: int, detail: str) -> None:
    _move(match, PAUSED, now, incident_type)
    match["lease"] = None
    state["incidents"].append({
        "id": uuid.uuid4().hex, "match_id": match["id"], "incident_type": incident_type,
        "attempt_count": count, "status": "open", "alerted_admin_at": None, "alert_error": None,
        "details_redacted": detail[:MAX_TEXT], "created_at": _now_iso(now), "resolved_at": None,
        "resolved_by": None})


def claim(store: JsonFileStore, match_id: str, owner: str, *, now: Callable[[], float] = time.time,
          lease_seconds: float = DEFAULT_LEASE_SECONDS,
          seed_fn: Callable[[int], int | None] | None = None) -> tuple[str, AttemptContext | str]:
    """Take the match for one attempt. Returns ("run", context) or ("skip", reason).

    Reasons: `already_completed`, `paused`, `running_elsewhere` (another worker holds a lease that has
    not expired: this is a duplicate delivery). A lease that HAS expired means that worker is gone: its
    attempt is recorded as a platform failure (`worker_lost`) and counts towards the cap.
    """
    with store.transaction() as state:
        match = _get(state, match_id)
        t = now()
        if match["status"] == SCHEDULED:
            _move(match, QUEUED, t)
        if match["status"] == COMPLETED:
            return "skip", "already_completed"
        if match["status"] == PAUSED:
            return "skip", "paused"
        if match["status"] == RUNNING:
            lease = match["lease"]
            if lease and lease["expires_at"] > t:
                return "skip", "running_elsewhere"
            current = match["attempts"][-1]
            current.update({"status": "platform_failed", "failure_class": "platform", "failure_reason": "worker_lost",
                            "detail": "the worker's lease expired before it reported a result", "finished_at": _now_iso(t)})
            match["lease"] = None
            _after_platform_failure(state, match, t, "worker_lost")
            if match["status"] == PAUSED:
                return "skip", "paused"
        # QUEUED or RETRY_QUEUED
        number = len(match["attempts"]) + 1
        seed = seed_fn(number) if seed_fn else None
        trace_id = uuid.uuid4().hex
        match["attempts"].append({
            "number": number, "status": "running", "seed": seed, "trace_id": trace_id, "owner": owner,
            "started_at": _now_iso(t), "finished_at": None, "failure_class": None, "failure_reason": None,
            "detail": None, "summary": None})
        match["lease"] = {"owner": owner, "attempt": number, "expires_at": t + lease_seconds}
        _move(match, RUNNING, t, f"attempt {number}")
        return "run", AttemptContext(match["id"], number, trace_id, match["team_a"], match["team_b"], match["map"],
                                     match["submission_a"], match["submission_b"], seed)


def finish(store: JsonFileStore, match_id: str, attempt: int, owner: str, result, *,
           now: Callable[[], float] = time.time) -> dict:
    """Record what attempt `attempt` produced. Returns {"applied": bool, "status": ..., "incident": id|None}.

    Only the worker that holds the lease for the running attempt can change anything. A late answer from
    a worker that was already replaced, or a second answer for the same attempt, is dropped
    (`applied: False`): that is what makes duplicate delivery harmless.
    """
    with store.transaction() as state:
        match = _get(state, match_id)
        lease = match["lease"]
        if match["status"] != RUNNING or not lease or lease["attempt"] != attempt or lease["owner"] != owner:
            return {"applied": False, "status": match["status"], "incident": None}
        verdict = interpret(result, require_reason=bool(match.get("series_game")))
        t = now()
        att = match["attempts"][attempt - 1]
        att["finished_at"] = _now_iso(t)
        att["summary"] = verdict.get("summary")
        incident_before = len(state["incidents"])
        if verdict["class"] == "platform_failure":
            att.update({"status": "platform_failed", "failure_class": "platform",
                        "failure_reason": verdict["kind"], "detail": verdict["detail"]})
            match["lease"] = None
            _after_platform_failure(state, match, t, verdict["kind"])
        else:
            side = verdict["winner_side"]
            winner_team = match["team_a" if side == "A" else "team_b"]
            loser_team = match["team_b" if side == "A" else "team_a"]
            forfeit = verdict["class"] == "bot_failure"
            att.update({"status": "bot_failed" if forfeit else "completed",
                        "failure_class": "bot" if forfeit else None,
                        "failure_reason": verdict.get("kind"), "detail": verdict.get("detail")})
            match["lease"] = None
            if forfeit:
                _move(match, BOT_FORFEIT, t, verdict["kind"])
            summary = verdict["summary"] or {}
            match["result"] = {
                "result_type": "bot_forfeit" if forfeit else "normal", "winner_side": side,
                "winner_team": winner_team, "loser_team": loser_team,
                "winner_submission": match["submission_a" if side == "A" else "submission_b"],
                "round": summary.get("round"), "reason": summary.get("reason"), "attempt": attempt,
                "replay": summary.get("replay"), "replay_sha256": summary.get("replay_sha256"),
                "structured_log": _log_path(summary.get("structured_log"))}
            match["advancement"] = {"pending": not match.get("series_game"), "taken_at": None}
            _move(match, COMPLETED, t, f"{match['result']['result_type']} by {winner_team}")
        incident = state["incidents"][-1]["id"] if len(state["incidents"]) > incident_before else None
        return {"applied": True, "status": match["status"], "incident": incident}


def pause_for_configuration(store: JsonFileStore, match_id: str, attempt: int, owner: str, error: str, *,
                            now: Callable[[], float] = time.time) -> dict:
    """The run function said retrying cannot help: end the attempt and pause the match now."""
    with store.transaction() as state:
        match = _get(state, match_id)
        lease = match["lease"]
        if match["status"] != RUNNING or not lease or lease["attempt"] != attempt or lease["owner"] != owner:
            return {"applied": False, "status": match["status"], "incident": None}
        t = now()
        match["attempts"][attempt - 1].update({
            "status": "platform_failed", "failure_class": "platform", "failure_reason": "configuration_error",
            "detail": error[:MAX_TEXT], "finished_at": _now_iso(t)})
        _move(match, PLATFORM_FAILED, t, "configuration_error")
        _pause(state, match, t, "configuration_error", _platform_failures(match), error)
        return {"applied": True, "status": PAUSED, "incident": state["incidents"][-1]["id"]}


def take_advancement(store: JsonFileStore, match_id: str, now: Callable[[], float] = time.time) -> dict | None:
    """Hand the result to bracket advancement exactly once.

    Returns the result the first time it is called for a completed match and None every time after, so
    two workers or a repeated job cannot advance the same winner twice. (If the caller crashes after
    this returns and before it advances, the claim is lost; BIO-303 must make advancement itself
    idempotent on `match_id`, and this flag is only the first line of defence.)
    """
    with store.transaction() as state:
        match = _get(state, match_id)
        if match["status"] != COMPLETED or not match["advancement"]["pending"]:
            return None
        match["advancement"] = {"pending": False, "taken_at": _now_iso(now())}
        return copy.deepcopy(match["result"])


def resume_paused(store: JsonFileStore, match_id: str, actor: str, extra_attempts: int = DEFAULT_MAX_ATTEMPTS, *,
                  now: Callable[[], float] = time.time) -> str:
    """Operator action: give a paused match more attempts and queue it again. Who may do this is an open decision."""
    if not isinstance(extra_attempts, int) or isinstance(extra_attempts, bool) or not 1 <= extra_attempts <= 100:
        raise OrchestratorError("extra_attempts must be an integer from 1 to 100")
    if not isinstance(actor, str) or not REF_RE.match(actor):
        raise OrchestratorError(f"actor must match {REF_RE.pattern}")
    with store.transaction() as state:
        match = _get(state, match_id)
        if match["status"] != PAUSED:
            raise OrchestratorError(f"match {match_id} is {match['status']}, not paused")
        t = now()
        match["max_attempts"] = _platform_failures(match) + extra_attempts
        for inc in state["incidents"]:
            if inc["match_id"] == match_id and inc["status"] == "open":
                inc.update({"status": "resolved", "resolved_at": _now_iso(t), "resolved_by": actor})
        _move(match, RETRY_QUEUED, t, f"resumed by {actor}")
        return match["status"]


def deliver_alerts(store: JsonFileStore, alert: Callable[[dict], None] | None,
                   now: Callable[[], float] = time.time) -> int:
    """Send every open incident that was not delivered yet. At least once: a crash between the
    incident and this call, or an exception from `alert`, leaves it pending for the next call.
    Returns how many were delivered."""
    with store.transaction() as state:
        pending = [dict(i) for i in state["incidents"] if i["status"] == "open" and i["alerted_admin_at"] is None]
    delivered = 0
    for inc in pending:
        error = None
        try:
            if alert is not None:
                alert(inc)
        except Exception as e:  # the alert channel is outside our control
            error = f"{type(e).__name__}: {e}"[:MAX_TEXT]
        with store.transaction() as state:
            for cur in state["incidents"]:
                if cur["id"] == inc["id"] and cur["alerted_admin_at"] is None:
                    if error is None and alert is not None:
                        cur["alerted_admin_at"] = _now_iso(now())
                        cur["alert_error"] = None
                        delivered += 1
                    elif error is not None:
                        cur["alert_error"] = error
    return delivered


def get_match(store: JsonFileStore, match_id: str) -> dict:
    with store.transaction() as state:
        return copy.deepcopy(_get(state, match_id))


def default_backoff(failures: int) -> float:
    return min(30.0, 2.0 * failures)


def run_match_job(store: JsonFileStore, match_id: str, run_fn: Callable[[AttemptContext], dict], *,
                  owner: str | None = None, alert: Callable[[dict], None] | None = None,
                  lease_seconds: float = DEFAULT_LEASE_SECONDS,
                  backoff: Callable[[int], float] = default_backoff, sleep: Callable[[float], None] = time.sleep,
                  now: Callable[[], float] = time.time,
                  seed_fn: Callable[[int], int | None] | None = None) -> dict:
    """Run attempts until the match is completed or paused, or another worker has it.

    Safe to call again and from several workers at once: only one gets each attempt. Returns
    {"status", "ran": number of attempts this call ran, "skipped": reason or None}.
    """
    owner = owner or f"worker-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    ran = 0
    while True:
        kind, what = claim(store, match_id, owner, now=now, lease_seconds=lease_seconds, seed_fn=seed_fn)
        if kind == "skip":
            deliver_alerts(store, alert, now)
            return {"status": get_match(store, match_id)["status"], "ran": ran, "skipped": what}
        ctx: AttemptContext = what
        ran += 1
        try:
            result = run_fn(ctx)
        except ConfigurationError as e:
            out = pause_for_configuration(store, match_id, ctx.attempt, owner, str(e), now=now)
            deliver_alerts(store, alert, now)
            return {"status": out["status"], "ran": ran, "skipped": None}
        except Exception as e:  # a crash in the run function is not the bots' fault
            result = {"outcome": "platform_failure", "kind": "runner_exception",
                      "detail": f"{type(e).__name__}: {e}"}
        out = finish(store, match_id, ctx.attempt, owner, result, now=now)
        if out["status"] == RETRY_QUEUED and out["applied"]:
            sleep(backoff(_platform_failures(get_match(store, match_id))))
            continue
        deliver_alerts(store, alert, now)
        return {"status": out["status"], "ran": ran, "skipped": None}


# ------------------------------------------------------------------------------------------
# host-level helpers for the real launcher
# ------------------------------------------------------------------------------------------
@contextlib.contextmanager
def host_lock(path: Path, timeout: float = 3600.0, poll: float = 1.0, sleep=time.sleep, clock=time.monotonic):
    """One engine match per host at a time (the engine's port is fixed). Waits up to `timeout` seconds."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+") as f:
        deadline = clock() + timeout
        while True:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if clock() >= deadline:
                    raise TimeoutError(f"another match held {path} for more than {timeout} s")
                sleep(poll)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def launcher_run_fn(scaffold: Path, py: Path, bots_dir: Path, out_root: Path, *, timeout: int = 1800,
                    offline: bool = True, socket_tuning: bool = True, sandbox: bool = True,
                    limits_path: Path | None = L.DEFAULT_LIMITS, cgroup: bool | None = None,
                    lock_path: Path | None = None, lock_wait: float = 3600.0) -> Callable[[AttemptContext], dict]:
    """Build a run function for `run_match_job` that plays the match with `backend/match_runner`.

    The bot folder of a team is `bots_dir/<submission reference>`: one immutable folder per submission
    version, which is how "the same bot versions in every attempt" is kept. Output goes to
    `out_root/<match id>/attempt-<n>/`.
    """

    def run(ctx: AttemptContext) -> dict:
        for ref in (ctx.submission_a, ctx.submission_b):
            if not TEAM_DIR_RE.match(ref):
                raise ConfigurationError(f"submission reference {ref!r} is not a usable folder name")
        out = Path(out_root) / ctx.match_id / f"attempt-{ctx.attempt}"
        lock = host_lock(lock_path, lock_wait) if lock_path else contextlib.nullcontext()
        try:
            with lock:
                return L.run_match(scaffold, py, bots_dir, ctx.submission_a, ctx.submission_b, ctx.map, out,
                                   timeout, offline, socket_tuning, sandbox=sandbox, cgroup=cgroup,
                                   trace_id=ctx.trace_id, match_id=ctx.match_id, attempt=ctx.attempt,
                                   submissions={"A": ctx.submission_a, "B": ctx.submission_b},
                                   limits_path=limits_path)
        except L.PortBusyError as e:
            return {"outcome": "platform_failure", "kind": "port_busy", "detail": str(e)}
        except TimeoutError as e:
            return {"outcome": "platform_failure", "kind": "host_busy", "detail": str(e)}
        except L.LauncherError as e:
            raise ConfigurationError(str(e)) from e
    return run

