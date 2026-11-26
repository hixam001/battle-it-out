# SPDX-License-Identifier: AGPL-3.0-only
"""Interim single-host service commands (BIO-409, CN-027). See README.md."""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import importlib
import json
import math
import os
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from backend.match_orchestrator import maps as M, orchestrator as O, replays as P
from backend.match_orchestrator.store import JsonFileStore
from backend.match_runner import launcher as L
from backend.notifications import notifications as N
from backend.registration import registration as G
from backend.submission_registry import registry as R
from backend.tournament_flow import flow as F
from backend.tournaments import scheduler as S, tournaments as T
from backend.work_queue import jobs as J, service as W


class ConfigurationError(Exception):
    """Invalid operator configuration; never a participant-supplied file."""


@dataclass(frozen=True)
class Config:
    data_dir: Path
    engine_jar: Path
    python_version: str
    interval_seconds: float = 60.0
    adapter_factory: str | None = None


def load_config(path: Path) -> Config:
    body = json.loads(path.read_text(encoding="utf-8"))
    allowed = {"data_dir", "engine_jar", "python_version", "interval_seconds", "adapter_factory"}
    if not isinstance(body, dict) or set(body) - allowed or not {"data_dir", "engine_jar"} <= set(body):
        raise ConfigurationError("expected data_dir, engine_jar and documented optional keys")
    def location(key):
        value = body[key]
        if not isinstance(value, str) or not value.strip():
            raise ConfigurationError(f"{key} must be a path")
        return (path.resolve().parent / value).resolve()
    version = body.get("python_version", L.load_lock()["primary_python"])
    if version not in L.load_lock()["tested_python"]:
        raise ConfigurationError("python_version must be in versions.lock.json")
    interval = body.get("interval_seconds", 60.0)
    if isinstance(interval, bool) or not isinstance(interval, (float, int)) or not math.isfinite(interval) or interval <= 0:
        raise ConfigurationError("interval_seconds must be finite and positive")
    factory = body.get("adapter_factory")
    if factory is not None and (not isinstance(factory, str) or len(factory.split(":")) != 2
                                or not all(factory.split(":"))):
        raise ConfigurationError("adapter_factory must be module:function or null")
    return Config(location("data_dir"), location("engine_jar"), version, float(interval), factory)


def load_adapters(spec: str | None) -> dict[str, Callable]:
    """Trusted installed factory returns optional send/address_of pair and/or alert callback."""
    if spec is None:
        return {}
    module, name = spec.split(":")
    adapters = getattr(importlib.import_module(module), name)()
    if not isinstance(adapters, dict) or set(adapters) - {"send", "address_of", "alert"} \
            or any(not callable(v) for v in adapters.values()) \
            or (("send" in adapters) != ("address_of" in adapters)):
        raise ConfigurationError("factory must return callable send/address_of together and/or alert")
    return adapters


class EmailAlertStore(JsonFileStore):
    _empty = staticmethod(lambda: {"schema": 1, "delivered": {}})
    _layout_ok = staticmethod(lambda s: isinstance(s, dict) and s.get("schema") == 1
                             and isinstance(s.get("delivered"), dict))


class Runtime:
    def __init__(self, config: Config, adapters: dict | None = None):
        self.config, self.adapters = config, adapters or {}
        root = config.data_dir
        self.tournaments = T.Tournaments.at(root / "tournaments.json")
        self.registration = G.Registration.at(root / "registration.json", self.tournaments)
        self.notifications = N.Notifications.at(root / "notifications.json")
        self.flow = F.Flow(R.Registry(root / "submissions", root / "registry.json"),
                           JsonFileStore(root / "matches.json"), J.JobQueue(root / "queue.json"))
        self.vault = P.Vault(root / "replays", P.ReplayIndex(root / "replays.json"))
        self.email_alerts = EmailAlertStore(root / "email-alerts.json")

    def alert(self, incident: dict) -> None:
        """No provider text, source, email address or claim token crosses the alert boundary."""
        # A raised callback leaves the originating incident pending. Never acknowledge an absent channel.
        sink = self.adapters.get("alert")
        if sink is None:
            raise ConfigurationError("no alert adapter configured")
        fields = ("id", "incident_type", "job_id", "match_id", "tournament_id", "attempt_count")
        try:
            sink({k: incident[k] for k in fields if k in incident})
        except Exception:
            raise RuntimeError("alert adapter failed") from None

    def maintenance(self, *, now=time.time) -> dict:
        catalogue = M.load_engine_maps(self.config.engine_jar)
        result = S.tick(self.tournaments, self.flow, catalogue=catalogue,
                        engine_version=L.load_lock()["engine_version"], vault=self.vault,
                        registration=self.registration, notifications=self.notifications, now=now)
        return {key: len(result[key]) for key in ("opened", "completed", "waiting", "blocked", "excluded")}

    def emails(self, *, now=time.time) -> dict:
        if "send" not in self.adapters:
            return {"configured": False}  # leave the outbox untouched, including attempt counters
        report = N.deliver_emails(self.notifications, self.adapters["send"], self.adapters["address_of"], now=now)
        return {"configured": True, **report, "failed": len(report["failed"])}

    def alerts(self, *, now=time.time) -> dict:
        if "alert" not in self.adapters:
            return {"configured": False}
        count = sum(O.deliver_alerts(store, self.alert, now) for store in
                    (self.flow.store, self.flow.queue.store, self.vault.index))
        failed = 0
        delivered = self.email_alerts.snapshot()["delivered"]
        for did, delivery in sorted(self.notifications.store.snapshot()["deliveries"].items()):
            if delivery["status"] != "failed" or did in delivered:
                continue
            try:
                self.alert({"id": did, "incident_type": "email_delivery_failed", "attempt_count": delivery["attempts"]})
            except Exception:
                failed += 1  # no receipt: next pass retries, without persisting adapter exception text
                continue
            with self.email_alerts.transaction() as state:
                state["delivered"][did] = now()
            count += 1
        return {"configured": True, "delivered": count, "email_alert_failures": failed}

    def worker(self):
        py = L.resolve_python(self.config.python_version, None, L.load_lock())
        if L.verify(L.DEFAULT_SCAFFOLD, py, L.load_lock()):
            raise ConfigurationError("worker runtime verification failed; run launcher.py verify")
        # The alerts process owns delivery, including after a worker dies with a stored incident.
        return W.build_worker(self.config.data_dir, python_version=self.config.python_version, notify=True)

    def status(self) -> dict:
        stores = (self.flow.store, self.flow.queue.store, self.vault.index)
        incidents = [i for store in stores for i in store.snapshot()["incidents"] if i["status"] == "open"]
        deliveries = self.notifications.store.snapshot()["deliveries"].values()
        alerted = self.email_alerts.snapshot()["delivered"]
        return {"queue": J.stats(self.flow.queue), "open_incidents": len(incidents),
                "unalerted_incidents": sum(i["alerted_admin_at"] is None for i in incidents),
                "unalerted_failed_emails": sum(d["status"] == "failed" and d["id"] not in alerted for d in deliveries),
                "email": {status: sum(d["status"] == status for d in deliveries)
                          for status in ("pending", "sending", "sent", "failed", "skipped")}}


@contextlib.contextmanager
def role_lock(root: Path, role: str):
    """One process of each service role per data directory, including one-shot invocations."""
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (root / f"service-{role}.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ConfigurationError("this service role is already running") from exc
        yield


def run_loop(action: Callable[[], dict], stop: threading.Event, interval: float, *, once=False) -> None:
    while not stop.is_set():
        print(json.dumps(action(), sort_keys=True), flush=True)
        if once or stop.wait(interval):
            return


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("role", choices=("worker", "maintenance", "emails", "alerts", "status"))
    parser.add_argument("--once", action="store_true", help="one pass; worker drains currently due jobs")
    args = parser.parse_args(argv)
    os.umask(0o077)
    try:
        config = load_config(args.config)
        if args.role == "status":
            print(json.dumps(Runtime(config).status(), sort_keys=True))
            return 0
        with role_lock(config.data_dir, args.role):
            adapters = load_adapters(config.adapter_factory) if args.role in ("emails", "alerts") else {}
            runtime = Runtime(config, adapters)
            stop = threading.Event()
            W._install_signals(stop)
            if args.role == "worker":
                worker = runtime.worker()
                if args.once:
                    results = worker.run_until_idle()
                    print(json.dumps({"ran": len(results), "dead": sum(r["outcome"] == "dead" for r in results)}))
                    return int(any(r["outcome"] in ("dead", "stale") for r in results))
                worker.run_forever(stop)
            else:
                run_loop(getattr(runtime, args.role), stop, config.interval_seconds, once=args.once)
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        # Adapter exceptions can contain credentials. Operators investigate locally; journals keep only types.
        print(json.dumps({"ok": False, "error_type": type(exc).__name__}), file=sys.stderr, flush=True)
        return 2


if __name__ == "__main__":
    sys.exit(main())
