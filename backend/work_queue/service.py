# SPDX-License-Identifier: AGPL-3.0-only
"""The worker as a program: `python3 -m backend.work_queue.service --data-dir DIR <command>` (CN-017).

    run            poll the queue and run jobs until stopped (SIGTERM or one Ctrl-C finishes the current job
                   first; a second Ctrl-C hands the job back at once)
    run --once     run the jobs that are due now, then exit (cron, tests)
    enqueue-check  SUBMISSION_ID          queue the upload check of one version
    enqueue-round  BRACKET_ID ROUND_NO    queue a started round
    status                                counts, dead jobs and open incidents as JSON

Everything lives under `--data-dir`: `queue.json`, `registry.json` with `submissions/` (the bot folders, also
the match runner's bots dir), `matches.json` (the orchestrator store with the brackets), with `--notify` also
`tournaments.json`, `registration.json` and `notifications.json` (the check and round handlers then tell the
teams; `notification_hooks`, CN-023), `host.lock` (one
engine match per host, shared by trial games and tournament games), `out/` (replays and logs). Run it as an
unprivileged user: the match runner puts every bot in its own sandbox, but the worker itself is trusted code.
"""
from __future__ import annotations

import argparse
import json
import signal
import sys
import threading
from pathlib import Path

from backend.match_orchestrator import orchestrator as O
from backend.match_orchestrator.store import JsonFileStore
from backend.match_runner import launcher as L
from backend.notifications import notifications as N
from backend.notifications import sources as NS
from backend.registration import registration as G
from backend.submission_check import trial as T
from backend.submission_registry import registry as R
from backend.tournaments import tournaments as TN

from . import handlers as H
from . import jobs as J
from .worker import Worker


def notification_hooks(data_dir: Path, reg: R.Registry, store: JsonFileStore):
    """`(on_decided, on_round)` for the two handlers: tell the team how a check ended and how a round's games
    ended. They read the roster in `registration.json` (which needs `tournaments.json`) and write
    `notifications.json`, all under `data_dir`. Every call is idempotent (CN-023), so a retried job is safe."""
    data_dir = Path(data_dir)
    roster = G.Registration.at(data_dir / "registration.json", TN.Tournaments.at(data_dir / "tournaments.json"))
    center = N.Notifications.at(data_dir / "notifications.json")
    return (lambda sid: NS.validation_result(center, roster, reg, sid),
            lambda bid, rno: NS.round_results(center, roster, store, bid, rno))


def build_worker(data_dir: Path, *, python_version: str | None = None, python: Path | None = None, name: str | None = None,
                 lease: float = J.DEFAULT_LEASE, alert=None, sandbox: bool = True, play=None, run_fn=None,
                 max_attempts: int = J.DEFAULT_MAX_ATTEMPTS, notify: bool = False, live_dir: Path | None = None, **worker_kw) -> Worker:
    """Wire the real launcher to both handlers. `play` and `run_fn` can be replaced (tests). `notify=True` adds
    the notification hooks (`notification_hooks`); off by default, so a data dir without a roster keeps working."""
    data_dir = Path(data_dir)
    queue = J.JobQueue(data_dir / "queue.json", max_attempts=max_attempts)
    reg = R.Registry(data_dir / "submissions", data_dir / "registry.json")
    store = JsonFileStore(data_dir / "matches.json")
    if play is None or run_fn is None:
        py = L.resolve_python(python_version, python, L.load_lock())
        lock_path = data_dir / "host.lock"
        if play is None:
            play = T.launcher_play(L.DEFAULT_SCAFFOLD, py, data_dir / "out" / "checks", lock_path=lock_path, sandbox=sandbox)
        if run_fn is None:
            run_fn = O.launcher_run_fn(L.DEFAULT_SCAFFOLD, py, reg.root, data_dir / "out" / "matches",
                                       lock_path=lock_path, sandbox=sandbox, live_dir=live_dir)
    on_decided, on_round = notification_hooks(data_dir, reg, store) if notify else (None, None)
    handlers = {
        J.CHECK_SUBMISSION: H.check_submission_handler(reg, lambda folder: T.check_submission(folder, play=play),
                                                       on_decided=on_decided),
        J.RUN_ROUND: H.run_round_handler(store, run_fn, alert=alert, on_round=on_round),
    }
    return Worker(queue, handlers, name=name, lease=lease, alert=alert, **worker_kw)


def _install_signals(stop: threading.Event) -> None:
    def on_signal(signum, _frame):
        if stop.is_set():
            raise KeyboardInterrupt            # second signal: hand the running job back now
        stop.set()
    for s in (signal.SIGTERM, signal.SIGINT):
        signal.signal(s, on_signal)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data-dir", type=Path, required=True)
    p.add_argument("--python-version", help="bot interpreter version (default: primary in the lock)")
    p.add_argument("--notify", action="store_true",
                   help="tell the teams about check and round results (needs tournaments.json and registration.json)")
    p.add_argument("--no-sandbox", action="store_true", help="development only; NOT safe for untrusted bots")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--once", action="store_true")
    r.add_argument("--name")
    r.add_argument("--lease", type=float, default=J.DEFAULT_LEASE)
    c = sub.add_parser("enqueue-check")
    c.add_argument("submission_id")
    rd = sub.add_parser("enqueue-round")
    rd.add_argument("bracket_id")
    rd.add_argument("round_no", type=int)
    sub.add_parser("status")
    args = p.parse_args(argv)
    try:
        if args.cmd in ("enqueue-check", "enqueue-round", "status"):
            q = J.JobQueue(args.data_dir / "queue.json")
            if args.cmd == "enqueue-check":
                out = J.enqueue_check(q, args.submission_id)
            elif args.cmd == "enqueue-round":
                out = J.enqueue_round(q, args.bracket_id, args.round_no)
            else:
                out = {"counts": J.stats(q), "dead": [j["id"] for j in J.list_jobs(q, J.DEAD)]}
            print(json.dumps(out, indent=1, sort_keys=True))
            return 0
        w = build_worker(args.data_dir, python_version=args.python_version, name=args.name, lease=args.lease,
                         sandbox=not args.no_sandbox, notify=args.notify, alert=lambda inc: print(json.dumps({"alert": inc}), flush=True))
        if args.once:
            done = w.run_until_idle()
            print(json.dumps({"ran": done}, indent=1, sort_keys=True))
            return 0 if all(r["outcome"] in ("done", "queued") for r in done) else 1
        stop = threading.Event()
        _install_signals(stop)
        try:
            w.run_forever(stop)
        except KeyboardInterrupt:
            pass
        return 0
    except (J.QueueError, O.OrchestratorError, R.RegistryError, L.LauncherError) as e:
        print(json.dumps({"ok": False, "error": str(e)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
