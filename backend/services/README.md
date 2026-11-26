# Interim service runner (BIO-409; CN-027)

Four separate single-host processes now run the existing JSON-store libraries.
This is the stack-neutral slice of BIO-409. Production persistence, deployment,
the pinned worker image and real provider/channel selection still need DEC-11.
No daemon is installed or enabled by this change.

| Role | Work |
|---|---|
| `worker` | Existing queue worker, sandbox enabled, verified bot runtime, notification hooks always on. Trial and tournament games share `host.lock`. |
| `maintenance` | `scheduler.tick` with the official registration store, notifications and replay vault: deadline draw/completion, recover unqueued checks, collect replays and retry interrupted purges. Never starts a round. |
| `emails` | `deliver_emails` through a configured adapter; its existing preference, lease, backoff and retry rules apply. |
| `alerts` | Retry pending match, queue and replay incidents, plus failed/no-address emails through a configured Admin channel. This also recovers incidents after a worker dies. |

Run from the repository root using the project interpreter:

```bash
backend/.venvs/py3.15/bin/python -m backend.services.runner --config /absolute/path/services.json maintenance --once
backend/.venvs/py3.15/bin/python -m backend.services.runner --config /absolute/path/services.json worker --once
backend/.venvs/py3.15/bin/python -m backend.services.runner --config /absolute/path/services.json emails --once
backend/.venvs/py3.15/bin/python -m backend.services.runner --config /absolute/path/services.json alerts --once
backend/.venvs/py3.15/bin/python -m backend.services.runner --config /absolute/path/services.json status
```

Remove `--once` to poll. A worker's one-shot drains jobs currently due; other
roles perform one pass. Recurring maintenance/email/alert passes default to 60
seconds, an **interim operator setting**, not an approved service-level target.
Each pass emits JSON counts; `status` reports queue counts, open/unalerted
incidents and email states without importing adapters. Fatal errors exit 2 and
log only the exception class, since adapter messages may contain credentials.
A one-shot worker exits 1 if any job ends dead or stale. A blocked tournament
remains an incident for the next pass; it does not stop other tournaments.

Copy [config.example.json](config.example.json) to an operator-owned location
and set paths. Paths are absolute or relative to the **configuration file**.
`engine_jar` must be the installed **1.2.6** engine JAR used by the launcher;
the service reads map bytes directly and checks stored map-pool hashes at draw
time. It does not provision or download the JAR or prove its provenance.
`python_version` must be a tested minor in `versions.lock.json` and defaults to
its primary. Worker startup checks the installed packages/scaffold through
`launcher.verify`; each bot still runs under the existing sandbox/limits.
Use the primary project interpreter for the service itself.

All roles must share the same private `data_dir`, owned by their unprivileged
service user. Its layout matches `work_queue.service`: `registry.json`,
`submissions/`, `queue.json`, `matches.json`, `tournaments.json`,
`registration.json`, `notifications.json`, `host.lock`, and `out/`. The vault
uses `replays/` and `replays.json`; successful failed-email alert receipts use
`email-alerts.json`. Use these same vault paths when the application calls
`tournaments.archive`. The CLI creates new state under umask `0077` and makes
new data directories private; existing directory permissions are the operator's
responsibility. Store files are trusted application state, never uploads.

An exclusive role lock prevents a second instance of that role, including
one-shot runs, from sharing the data directory. Other roles remain independent,
so a match, email-provider wait or alert-channel wait does not delay deadline
processing. Do not run the legacy worker CLI alongside the new worker, or run
manual outbox/alert callers concurrently with these services. First SIGTERM or
SIGINT drains the current pass/job and wakes an idle wait; a second signal
interrupts it and the worker hands its queue job back. Interrupted matches still
have the existing attempt-lease and runner-attribution limitations. A graceful
stop may take an entire round; operators should plan shutdowns accordingly.

Provider configuration is executable trusted operator code. An optional
`adapter_factory: "installed_module:build_adapters"` imports a no-argument
factory returning a dictionary of callables:

```python
def build_adapters():
    return {
        "send": provider_send,            # message -> provider ID (or None)
        "address_of": account_address,    # user ID -> address (or None)
        "alert": admin_alert,             # incident summary -> None on successful handoff
    }
```

`send` and `address_of` must appear together; `alert` is optional. The factory
is loaded only by email and alert roles. Supply only the needed callables for a
deployment; keep credentials in its protected environment/secret mechanism,
outside the repository and JSON configuration. Do not choose adapter modules
or recipients from participant input. `registration.official_email` can supply
participant addresses; a production account directory must also cover staff.

The email message contains `to`, `subject`, `text`, `idempotency_key`; raise
`notifications.Permanent` only for a nonretryable failure. Alert summaries
contain incident ID/type and available job/match/tournament IDs and attempt
count. They exclude free-form incident/provider text and addresses. The Admin
recipient/channel is the adapter's responsibility. Treat incident ID (with type
if needed) as its idempotency key. Delivery is **at least once**: a crash after
external handoff but before the receipt can repeat it. Failed alert calls keep
incidents pending; adapter exception text is not persisted by this wrapper.
Failed emails stay discoverable across service restarts until alert handoff
succeeds; dashboard copies survive email failure.

With `adapter_factory: null`, email and alert passes report `configured: false`.
They neither claim deliveries nor acknowledge incidents. This is an explicit
unconfigured state, not evidence of a real email or Admin notification. A real
provider/channel and outage drill remain open; no provider was contacted in
verification of this task.

[battle-it-out@.service](battle-it-out@.service) is a **reviewable systemd
template**, not an installed/deployed unit. Adapt its user/group, repository,
configuration and interpreter paths; provision the existing launcher dependencies
(JDK 21+, bubblewrap, user namespaces, project venvs, Gradle caches and engine)
for that account first. The four instances are `battle-it-out@worker`,
`battle-it-out@maintenance`, `battle-it-out@emails`, and `battle-it-out@alerts`.
`KillMode=mixed` signals only the main process at first; `TimeoutStopSec=infinity`
lets a round drain without systemd killing its bot runners. Forced termination
requires operator judgment. Runtime supervision/restart on an actual target
host has not been validated. No sandbox-affecting systemd hardening is asserted.

```bash
backend/.venvs/py3.15/bin/python backend/run_tests.py backend.services
backend/.venvs/py3.15/bin/python backend/run_tests.py backend.services --integration
```

The integration scenario launches the new CLI as separate processes, checks two
bots with real sandboxed games, excludes a third registered team without a bot,
draws without starting a round, plays the Organizer-started final, stores real
replays, repeats the work without replaying games, and archives with deletion
verified on disk. All state and output stay in temporary directories. This does
not close the execution gates, production deployment or full TC-05/TC-08.
