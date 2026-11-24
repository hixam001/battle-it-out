# SPDX-License-Identifier: AGPL-3.0-only
"""Handlers that connect queue jobs to the registry check and the round runner (CN-017).

Each handler is thin on purpose: the registry and the orchestrator already make their steps safe to repeat,
so a repeated or taken-over job cannot check a version twice, play a game twice or advance a winner twice.
The handler only decides what a result means for the *job*: done, wait, retry, or give up.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from backend.match_orchestrator import bracket as B
from backend.match_orchestrator import orchestrator as O
from backend.match_orchestrator.store import JsonFileStore
from backend.submission_registry import registry as R

from .worker import Context, Defer, Permanent

CHECK_RETRY_WAIT = 60.0          # a claim held by a live worker, or a round another worker is playing


def check_submission_handler(reg: R.Registry, check: Callable[[Path], dict], *,
                             now: Callable[[], float] = time.time) -> Callable[[dict, Context], dict]:
    """Run the upload check for one version (`check` is normally `trial.check_submission` with a game player).

    * valid / rejected: done (the registry has recorded it and applied the activation rule).
    * inconclusive: the platform could not tell, so the job FAILS and is retried later; the participant is
      not blamed and nothing becomes active. After the cap the job is dead and staff get an incident.
    * a version nobody can serve (missing, damaged) is permanent: the registry already stored the incident.
    * the check could not run at all (`CheckError`, a crash) is a failure of the job, retried up to the cap.
    """
    def handle(payload: dict, ctx: Context) -> dict:
        sid = payload["submission_id"]
        try:
            view = R.run_check(reg, sid, check, now=now)
        except (R.NotFound, R.Unavailable) as e:
            raise Permanent(str(e)) from e
        if view is None:
            # Nothing to do: already decided, or another worker holds a live claim. In the second case
            # look again after a while, so a worker that dies mid-check does not leave the version stuck.
            rec = reg.store.snapshot()["submissions"].get(sid)
            if rec is not None and rec["validation_status"] == R.VALIDATING:
                raise Defer(CHECK_RETRY_WAIT, "another worker holds the check")
            return {"submission_id": sid, "status": rec["validation_status"] if rec else "unknown", "ran": False}
        if view["validation_status"] == R.INCONCLUSIVE:
            raise RuntimeError("the check was inconclusive (the platform could not tell); trying again later")
        return {"submission_id": sid, "status": view["validation_status"], "active": view["is_active"], "ran": True}
    return handle


def run_round_handler(store: JsonFileStore, run_fn: Callable[[O.AttemptContext], dict], *,
                      alert: Callable[[dict], None] | None = None, now: Callable[[], float] = time.time,
                      **job_kwargs) -> Callable[[dict, Context], dict]:
    """Play a started round (`bracket.run_round`).

    * round completed: done.
    * a game is paused (retry cap or configuration error): the job is done, because the orchestrator holds
      the incident and an operator must resume the game; they then enqueue the round again.
    * another worker is playing a match of the round: wait and look again.
    * the round was never started, or the bracket is unknown: permanent.
    """
    def handle(payload: dict, ctx: Context) -> dict:
        try:
            out = B.run_round(store, payload["bracket_id"], payload["round_no"], run_fn, owner=ctx.worker,
                              alert=alert, now=now, **job_kwargs)
        except B.BracketError as e:
            raise Permanent(str(e)) from e
        if out["skipped"] == "running_elsewhere":
            raise Defer(CHECK_RETRY_WAIT, "another worker is playing a match of this round")
        return {"bracket_id": payload["bracket_id"], "round_no": payload["round_no"], "round_status": out["status"],
                "games_run": out["ran"], "paused": out["status"] == B.PAUSED}
    return handle
