# SPDX-License-Identifier: AGPL-3.0-only
"""Service boundaries with real stores; one opt-in subprocess/real-engine lifecycle."""
import contextlib
import gzip
import hashlib
import io
import json
import os
import selectors
import signal
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from backend.match_orchestrator import bracket as B, maps as M, orchestrator as O, replays as P
from backend.match_orchestrator.tests.test_maps import REAL_JARS, make_jar, FILES, ENGINE
from backend.notifications import notifications as N
from backend.notifications.tests.test_sources import Sources
from backend.services import runner as S
from backend.submission_registry import registry as R
from backend.tournament_flow import flow as F
from backend.tournament_flow.tests.test_flow import BOT, DEADLINE
from backend.tournaments import tournaments as T
from backend.tournaments.tests.test_scheduler import ADMIN, ORG
from backend.work_queue import jobs as J

REPO = Path(__file__).resolve().parents[3]


class ConfigAndCommands(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / "service.json"
        self.body = {"data_dir": "data", "engine_jar": "engine.jar"}
        self.write()

    def write(self):
        self.path.write_text(json.dumps(self.body))

    def command(self, role, *extra):
        return [sys.executable, "-m", "backend.services.runner", "--config", str(self.path), role, *extra]

    def test_paths_are_relative_to_config_even_from_another_working_directory(self):
        config = S.load_config(self.path)
        self.assertEqual(config.data_dir, self.root / "data")
        self.assertEqual(config.engine_jar, self.root / "engine.jar")
        self.assertEqual(config.python_version, "3.15")

    def test_invalid_config_is_refused_before_writing_data(self):
        for key, value in (("unknown", 1), ("python_version", "3.99"), ("interval_seconds", True),
                           ("interval_seconds", float("nan")), ("interval_seconds", 0),
                           ("interval_seconds", -1), ("data_dir", ""), ("adapter_factory", "no-colon")):
            with self.subTest(key=key, value=value):
                self.body = {"data_dir": "data", "engine_jar": "engine.jar", key: value}
                self.write()
                with self.assertRaises(S.ConfigurationError):
                    S.load_config(self.path)
        self.assertFalse((self.root / "data").exists())

    def test_adapter_pair_is_required_and_unknown_keys_are_refused(self):
        for output in ({"send": lambda msg: None}, {"alert": None}, {"unexpected": lambda: None}):
            with self.subTest(output=output), mock.patch.object(S.importlib, "import_module") as imp:
                imp.return_value.factory.return_value = output
                with self.assertRaises(S.ConfigurationError):
                    S.load_adapters("installed_provider:factory")
        adapters = {"send": lambda msg: None, "address_of": lambda uid: None, "alert": lambda inc: None}
        with mock.patch.object(S.importlib, "import_module") as imp:
            imp.return_value.factory.return_value = adapters
            self.assertEqual(S.load_adapters("installed_provider:factory"), adapters)

    def test_same_role_is_excluded_but_other_roles_are_independent(self):
        root = self.root / "data"
        with S.role_lock(root, "maintenance"), S.role_lock(root, "emails"):
            proc = subprocess.run(self.command("maintenance", "--once"), cwd=REPO, capture_output=True, text=True)
            self.assertEqual(proc.returncode, 2, proc.stderr)
            self.assertIn("ConfigurationError", proc.stderr)
        with S.role_lock(root, "maintenance"):
            pass  # lock released by the earlier owner

    def test_status_does_not_import_adapters_or_need_engine_jar(self):
        self.body["adapter_factory"] = "missing_provider:factory"
        self.write()
        proc = subprocess.run(self.command("status"), cwd=REPO, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["open_incidents"], 0)

    def test_unconfigured_email_command_leaves_outbox_pending(self):
        rt = S.Runtime(S.load_config(self.path))
        N.notify(rt.notifications, "team_excluded", "t1", ["u1"], {"team": "ta"}, event_key="e1")
        before = rt.notifications.store.snapshot()
        proc = subprocess.run(self.command("emails", "--once"), cwd=REPO, capture_output=True, text=True)
        self.assertEqual((proc.returncode, json.loads(proc.stdout)), (0, {"configured": False}))
        self.assertEqual(rt.notifications.store.snapshot(), before)

    def test_sigterm_interrupts_long_idle_wait_and_releases_role(self):
        self.body["interval_seconds"] = 3600
        self.write()
        proc = subprocess.Popen(self.command("emails"), cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout, selectors.EVENT_READ)
            self.assertTrue(selector.select(10), "service did not emit its first pass")
        self.assertEqual(json.loads(proc.stdout.readline()), {"configured": False})
        proc.send_signal(signal.SIGTERM)
        stdout, stderr = proc.communicate(timeout=5)
        self.assertEqual(proc.returncode, 0, stderr)
        with S.role_lock(self.root / "data", "emails"):
            pass

    def test_loop_honors_once_and_an_already_requested_stop(self):
        action = mock.Mock(return_value={"done": True})
        stop = threading.Event()
        with contextlib.redirect_stdout(io.StringIO()):
            S.run_loop(action, stop, 3600, once=True)
            stop.set()
            S.run_loop(action, stop, 3600)
        self.assertEqual(action.call_count, 1)

    def test_adapter_error_text_does_not_reach_journal(self):
        old_umask = os.umask(0o077)
        self.addCleanup(os.umask, old_umask)
        error = io.StringIO()
        with mock.patch.object(S, "load_adapters", side_effect=RuntimeError("provider secret-example")), \
                contextlib.redirect_stderr(error):
            self.assertEqual(S.main(["--config", str(self.path), "emails", "--once"]), 2)
        self.assertNotIn("secret-example", error.getvalue())
        self.assertIn("RuntimeError", error.getvalue())


class ServiceFixture(Sources):
    def setUp(self):
        super().setUp()
        self.jar = make_jar(self.dir / "engine.jar", FILES)
        self.config = S.Config(self.dir, self.jar, "3.15")
        self.runtime = S.Runtime(self.config)
        self.flow = self.runtime.flow
        self.addCleanup(self.unlock_submissions)

    def unlock_submissions(self):
        for folder in (self.dir / "submissions").glob("*"):
            if folder.is_dir():
                folder.chmod(0o700)


class ServiceFlow(ServiceFixture):
    def test_maintenance_draws_roster_excludes_team_without_bot_and_never_starts_round(self):
        self.register(("ta", "tb", "tc"))
        self.upload("ta"), self.upload("tb"), self.up("outsider")
        self.check()
        self.clock.t = DEADLINE
        result = self.runtime.maintenance(now=self.clock)
        self.assertEqual((result["opened"], result["excluded"]), (1, 1))
        bracket = B.get_bracket(self.flow.store, "t1")
        self.assertEqual(sorted(e["team"] for e in bracket["teams"]), ["ta", "tb"])
        self.assertEqual(bracket["rounds"][0]["status"], "ready")
        self.assertEqual(J.list_jobs(self.flow.queue, J.RUNNING), [])
        self.assertEqual(self.kinds("tc"), ["team_excluded"])
        before = self.center.store.snapshot()
        self.assertEqual(self.runtime.maintenance(now=self.clock)["opened"], 0)
        self.assertEqual(self.center.store.snapshot(), before)

    def test_maintenance_recovers_unqueued_upload_and_defers_draw_while_check_pending(self):
        self.register(("ta", "tb"))
        self.upload("ta"), self.upload("tb")
        self.check()
        actor = R.Actor(self.users["ta"], "participant", frozenset({"ta"}), frozenset({"ta"}))
        R.submit(self.flow.registry, actor, "ta", "t1", "bot.py", BOT + b"# next\n",
                 idempotency_key="next", deadline_at=DEADLINE, now=self.clock)
        self.clock.t = DEADLINE
        result = self.runtime.maintenance(now=self.clock)
        self.assertEqual((result["waiting"], result["opened"]), (1, 0))
        self.assertEqual([j["payload"]["submission_id"] for j in J.list_jobs(self.flow.queue, J.QUEUED)], ["ta-v2"])
        self.check()
        self.assertEqual(self.runtime.maintenance(now=self.clock)["opened"], 1)

    def test_maintenance_finishes_interrupted_purge_without_losing_match_history(self):
        source = self.dir / "sample.bc26"
        source.write_bytes(gzip.compress(b"replay fixture"))
        P.register_replay(self.runtime.vault, "t1", "m1", source, hashlib.sha256(source.read_bytes()).hexdigest())
        with mock.patch.object(P, "purge_tournament", side_effect=OSError("interrupted")):
            with self.assertRaises(OSError):
                P.archive_tournament(self.runtime.vault, "t1", "adm")
        history = self.flow.store.snapshot()
        self.runtime.maintenance(now=self.clock)
        self.assertFalse((self.runtime.vault.root / "t1").exists())
        self.assertEqual(P.tournament_state(self.runtime.vault, "t1")["purge"]["status"], P.PURGE_DONE)
        self.assertEqual(self.flow.store.snapshot(), history)

    def test_worker_verifies_runtime_and_enables_notifications(self):
        with mock.patch.object(S.L, "verify", return_value=[]), mock.patch.object(S.W, "build_worker") as build:
            self.runtime.worker()
            build.assert_called_once_with(self.dir, python_version="3.15", notify=True, live_dir=self.dir / "live")
        with mock.patch.object(S.L, "verify", return_value=["bad package"]), mock.patch.object(S.W, "build_worker") as build:
            with self.assertRaises(S.ConfigurationError):
                self.runtime.worker()
            build.assert_not_called()

    def test_configured_email_failure_retries_and_dashboard_survives(self):
        self.register(("ta",))
        self.upload("ta")
        self.check()
        sent = []
        self.runtime.adapters = {"send": mock.Mock(side_effect=OSError("offline")), "address_of": lambda uid: "ta@uni.edu"}
        self.assertEqual(self.runtime.emails(now=self.clock)["retry"], 1)
        self.assertEqual(self.runtime.emails(now=self.clock)["retry"], 0)
        self.clock.t += 61
        self.runtime.adapters["send"] = sent.append
        self.assertEqual(self.runtime.emails(now=self.clock)["sent"], 1)
        self.assertEqual(len(sent), 1)
        self.assertEqual(self.kinds("ta"), ["validation_accepted"])

    def test_alerts_heal_stored_incidents_and_no_channel_acknowledges_nothing(self):
        J.enqueue_check(self.flow.queue, "missing", now=self.clock)
        claim = J.claim_next(self.flow.queue, "dead-worker", now=self.clock)
        J.fail(self.flow.queue, claim, "private@example.org", permanent=True, now=self.clock)
        S.S._incident(self.flow, "t1", "tournament_blocked", "secret-example", self.clock())
        P.register_from_result(self.runtime.vault, "t1", "missing-replay", {"replay": str(self.dir / "absent.bc26")})
        self.assertEqual(self.runtime.alerts(now=self.clock), {"configured": False})
        self.assertEqual(self.runtime.status()["unalerted_incidents"], 3)
        received = []
        self.runtime.adapters = {"alert": received.append}
        self.assertEqual(self.runtime.alerts(now=self.clock)["delivered"], 3)
        self.assertEqual(self.runtime.alerts(now=self.clock)["delivered"], 0)
        self.assertNotIn("secret-example", json.dumps(received))
        self.assertNotIn("private@example.org", json.dumps(received))
        self.assertEqual(self.runtime.status()["unalerted_incidents"], 0)

    def test_failed_alert_remains_pending_without_storing_provider_text(self):
        S.S._incident(self.flow, "t1", "tournament_blocked", "blocked", self.clock())
        self.runtime.adapters = {"alert": mock.Mock(side_effect=OSError("secret-example"))}
        self.assertEqual(self.runtime.alerts(now=self.clock)["delivered"], 0)
        self.assertEqual(self.runtime.status()["unalerted_incidents"], 1)
        self.assertNotIn("secret-example", json.dumps(self.flow.store.snapshot()))
        self.runtime.adapters = {"alert": lambda inc: None}
        self.assertEqual(self.runtime.alerts(now=self.clock)["delivered"], 1)

    def test_failed_email_alert_recovers_after_restart_and_is_receipted_only_on_success(self):
        N.notify(self.center, "team_excluded", "t1", ["u1"], {"team": "ta"}, event_key="e1", now=self.clock)
        self.runtime.adapters = {"send": lambda msg: None, "address_of": lambda uid: None,
                                 "alert": mock.Mock(side_effect=OSError("offline"))}
        self.runtime.emails(now=self.clock)
        self.assertEqual(self.runtime.status()["unalerted_failed_emails"], 1)
        self.assertEqual(self.runtime.alerts(now=self.clock)["email_alert_failures"], 1)
        self.assertEqual(self.runtime.email_alerts.snapshot()["delivered"], {})
        received = []
        restarted = S.Runtime(self.config, {"alert": received.append})
        self.assertEqual(restarted.alerts(now=self.clock)["delivered"], 1)
        self.assertEqual(restarted.status()["unalerted_failed_emails"], 0)
        self.assertEqual(restarted.alerts(now=self.clock)["delivered"], 0)
        self.assertEqual(received[0]["incident_type"], "email_delivery_failed")


@unittest.skipUnless(os.environ.get("BIO_INTEGRATION") == "1" and REAL_JARS,
                     "set BIO_INTEGRATION=1 with the pinned engine jar for real service processes")
class RealServiceLifecycle(ServiceFixture):
    def test_service_processes_from_upload_to_archive(self):
        self.register(("ta", "tb", "tc"))
        real_jar = REAL_JARS[0]
        catalogue = M.load_engine_maps(real_jar)
        M.create_pool(self.flow.store, "real-service", catalogue, ENGINE, play=["DefaultSmall"],
                      tiebreak_normal=["jail"], tiebreak_final=["jail", "pipes", "keepout"])
        T.edit(self.treg, ORG, "t1", {"map_pool_id": "real-service"}, now=self.clock)
        bot = (REPO / "backend/battlecode26-scaffold/src/examplefuncsplayer_py/bot.py").read_bytes()
        for team in ("ta", "tb"):
            actor = R.Actor(self.users[team], "participant", frozenset({team}), frozenset({team}))
            F.upload(self.flow, actor, team, "t1", "bot.py", bot, idempotency_key=team,
                     deadline_at=DEADLINE, now=self.clock)
        config = self.dir / "service.json"
        config.write_text(json.dumps({"data_dir": str(self.dir), "engine_jar": str(real_jar)}))

        def run(role):
            proc = subprocess.run([sys.executable, "-m", "backend.services.runner", "--config", str(config),
                                   role, "--once"], cwd=REPO, capture_output=True, text=True, timeout=240)
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            return json.loads(proc.stdout)

        self.assertEqual(run("worker")["ran"], 2)
        self.assertEqual(self.kinds("ta"), ["validation_accepted"])
        self.assertEqual(run("maintenance")["opened"], 1)
        self.assertEqual(B.get_bracket(self.flow.store, "t1")["rounds"][0]["status"], "ready")
        self.assertEqual(self.kinds("tc"), ["team_excluded"])
        F.start_round(self.flow, "t1", 1, "org1")
        self.assertEqual(run("worker")["ran"], 1)
        self.assertEqual(run("maintenance")["completed"], 1)
        before = self.flow.store.snapshot()
        replay_files = list((self.dir / "replays" / "t1").glob("*.bc26"))
        self.assertGreater(len(replay_files), 0)
        self.assertEqual(run("worker")["ran"], 0)
        run("maintenance")
        self.assertEqual(self.flow.store.snapshot(), before)
        T.archive(self.treg, ADMIN, "t1", self.runtime.vault, confirm=True)
        run("maintenance")
        self.assertFalse((self.dir / "replays" / "t1").exists())
        self.assertFalse(list((self.dir / "live").glob("*.json")))
        self.assertEqual(self.flow.store.snapshot(), before)
