# SPDX-License-Identifier: AGPL-3.0-only
"""The worker loop: take a job, run its handler, record the outcome (BIO-EPIC-03, SRD-007, CN-017).

A worker is a separate process from the web/API process: it only needs the queue file and whatever the
handlers read. While a handler runs, a helper thread renews the job's lease, so a match that takes half an
hour is not mistaken for a dead worker; if the worker really dies, renewal stops and another worker takes
the job over after the lease.

A handler is `fn(payload: dict, ctx: Context) -> dict | None`. It ends in one of four ways:
  * returns            the job is done (the returned dict is kept as its result);
  * raises `Defer`     run it again later, no failure counted (someone else holds the work, host busy);
  * raises `Permanent` retrying cannot help: the job is dead at once, with an incident;
  * raises anything else  a failure: retried with a growing wait, dead with an incident at the cap.
A `KeyboardInterrupt` or `SystemExit` (a shutdown signal) gives the job back at once without a failure.
"""
from __future__ import annotations

import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable

from . import jobs as J


class Defer(Exception):
    def __init__(self, seconds: float, reason: str = ""):
        super().__init__(reason or f"deferred {seconds} s")
        self.seconds, self.reason = seconds, reason


class Permanent(Exception):
    """Retrying cannot help (bad configuration, work that no longer exists)."""


@dataclass
class Context:
    worker: str
    job_id: str
    attempt: int
    lost: threading.Event = field(default_factory=threading.Event)     # set when the lease could not be renewed


Handler = Callable[[dict, Context], "dict | None"]


class Worker:
    def __init__(self, queue: J.JobQueue, handlers: dict[str, Handler], *, name: str | None = None,
                 lease: float = J.DEFAULT_LEASE, renew_every: float | None = None,
                 alert: Callable[[dict], None] | None = None, now: Callable[[], float] = time.time):
        for kind in handlers:
            if kind not in (J.CHECK_SUBMISSION, J.RUN_ROUND):
                raise J.QueueError(f"no such job kind {kind!r}")
        self.queue = queue
        self.handlers = dict(handlers)
        self.name = name or f"w{os.getpid()}-{uuid.uuid4().hex[:6]}"
        self.lease = lease
        self.renew_every = renew_every if renew_every is not None else max(0.5, lease / 3)
        self.alert = alert
        self.now = now

    # one job -------------------------------------------------------------------------------------
    def _renew(self, claim: J.JobClaim, ctx: Context, stop: threading.Event) -> None:
        while not stop.wait(self.renew_every):
            try:
                J.extend(self.queue, claim, lease=self.lease, now=self.now)
            except J.Stale:
                ctx.lost.set()
                return
            except Exception:                    # storage trouble: try again at the next beat, the lease still runs
                continue

    def run_once(self) -> dict | None:
        """Take one due job and run it. Returns {"job", "kind", "outcome": done|queued|dead|stale} or None if nothing was due."""
        claim = J.claim_next(self.queue, self.name, kinds=tuple(self.handlers), lease=self.lease, now=self.now)
        if claim is None:
            return None
        ctx = Context(self.name, claim.job_id, claim.attempt)
        stop = threading.Event()
        beat = threading.Thread(target=self._renew, args=(claim, ctx, stop), name=f"renew-{claim.job_id}", daemon=True)
        beat.start()
        report = {"job": claim.job_id, "kind": claim.kind}
        try:
            try:
                result = self.handlers[claim.kind](claim.payload, ctx)
                outcome = ("done", result)
            except Defer as d:
                outcome = ("deferred", d)
            except Permanent as e:
                outcome = ("dead", e)
            except Exception as e:                # a handler bug or a platform fault is a failure of the job
                outcome = ("failed", e)
            except BaseException:                 # shutdown signal: give the job back, then let it propagate
                stop.set()
                self._settle(lambda: J.defer(self.queue, claim, 0, "worker stopped", now=self.now), report)
                raise
        finally:
            stop.set()
            beat.join(timeout=5)
        kind, value = outcome
        if kind == "done":
            self._settle(lambda: J.complete(self.queue, claim, value, now=self.now), report)
        elif kind == "deferred":
            self._settle(lambda: J.defer(self.queue, claim, value.seconds, value.reason, now=self.now), report)
        else:
            text = f"{type(value).__name__}: {value}"
            self._settle(lambda: J.fail(self.queue, claim, text, permanent=(kind == "dead"), now=self.now), report)
        J.deliver_alerts(self.queue, self.alert, self.now)
        return report

    def _settle(self, action: Callable[[], dict], report: dict) -> None:
        try:
            report["outcome"] = action()["status"]       # done | queued (retry or deferred) | dead
        except J.Stale:
            report["outcome"] = "stale"          # the job was taken over: the newer worker's outcome stands

    # many jobs -----------------------------------------------------------------------------------
    def run_until_idle(self, max_jobs: int = 10_000) -> list[dict]:
        out = []
        while len(out) < max_jobs:
            r = self.run_once()
            if r is None:
                break
            out.append(r)
        return out

    def run_forever(self, stop: threading.Event, idle_sleep: float = 2.0) -> int:
        """Poll until `stop` is set. A job already running finishes first. Returns how many jobs were run."""
        n = 0
        while not stop.is_set():
            if self.run_once() is None:
                stop.wait(idle_sleep)
            else:
                n += 1
        return n
