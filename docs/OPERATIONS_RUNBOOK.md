# Interim operations runbook

The current single-host setup uses the Django feature API, PostgreSQL and the
[service runner](../backend/services/README.md) for workers, deadlines, email and
alerts. The web app and the four services share one private state directory.
Use these procedures for the local/reference setup. Record the target host,
release, service account and config path before adopting them on a managed host.

## Triage

1. Record the time in UTC, service role, affected tournament/match/job ID and the
   API request ID when available. Use the protected incident record for logs
   and identifiers. Keep credentials, source, roster records and provider
   payloads out of shared incident messages.
2. Sign in with the platform Admin account and open **Operations** (`/admin`) in the
   competition console. Review worker and delivery counts, open incidents,
   dead jobs and recent feature audit events. The page reads the current
   state. Refresh it after a service intervention.
3. From the repo root and under the service account, run the status and
   web checks. Replace the configuration path with the approved local one.

   ```bash
   BIO_SERVICE_CONFIG=/absolute/path/services.json
   backend/.venvs/py3.15/bin/python -m backend.services.runner \
     --config "$BIO_SERVICE_CONFIG" status
   curl --fail-with-body --silent --show-error \
     http://127.0.0.1:8000/api/v1/health/
   curl --fail-with-body --silent --show-error \
     http://127.0.0.1:8000/api/v1/ready/
   ```

4. Compare queue, `open_incidents`, `unalerted_incidents`,
   `unalerted_failed_emails` and email counts with the previous sample.
   HTTP `200` on health proves process liveness. HTTP `200` on readiness shows
   that the configured connection can reach PostgreSQL, see the Django
   model tables and use the enabled append-only history triggers. A readiness
   `503` leaves liveness available and carries a
   request ID for correlation. Check the target database, applied migrations
   and schema search path using the web process's configuration. Verify
   that the audit and dispute event tables have their history triggers.
   Check a scoped console request and the service logs for worker, engine and
   legacy-store failures. Zero counts
   can mean the wrong data directory. Confirm Django's `BIO_DATA_DIR` matches
   the service config before acting.
5. Where the systemd template is installed, use the actual instance name in
   `systemctl status battle-it-out@worker` and
   `journalctl -u battle-it-out@worker --since "-30 minutes"`. Substitute
   `maintenance`, `emails` or `alerts` for the relevant service. An approved
   restart sends a graceful stop. The worker may take the remainder of a round
   to drain, and an interrupted attempt can keep its lease. Check the owned
   service and engine processes before intervening further.

## Paused match or dead job

| Signal | Check | Recovery handoff |
| --- | --- | --- |
| `retry_cap_reached` and paused match | Read the incident and exact match/attempt IDs. Check the pinned engine, shared host lock, map, pinned submissions, sandbox prerequisites and engine logs. The current default is 10 total attempts; bots that forfeit have a recorded game result. | Preserve the recorded result and pinned versions. Escalate paused matches with the incident and diagnosis. The current console has no authenticated resume action and resume authority is pending. |
| Dead submission-check job | Read the job kind and failure count. Check registry bytes, runtime verification, reference bot and disk space. A queue job failure alone does not determine the submission verdict. | Preserve the submission record. Ask the operator responsible for recovery to inspect the specific job and current state. |
| Dead round job | Inspect the corresponding bracket, round, active leases and results. Check whether there is a paused game or a queue/worker problem. | Fix the diagnosed problem before considering a retry. Completed games and advancement remain recorded. |

The recovery implementation hooks are
`match_orchestrator.resume_paused` and `work_queue.jobs.revive`. Both are
trusted library calls, and queue/rerun authority still needs an authenticated
integration. Preserve leases and the original deduplication key. Avoid deleting
lock files, editing JSON by hand or starting a second worker to force progress.
Confirm any approved recovery against authoritative status, one result per
game and one advancement per winner.

## Email delivery stopped or failed

1. Compare pending/sending/failed counts and inspect the email and alert
   services independently. An unconfigured role reports `configured: false`.
   The dashboard copy still exists. Check whether email was disabled for the
   recipient or the approved account directory lacked an address.
2. For transient failures, correct adapter reachability and wait for backoff.
   The sender rechecks the preference before delivery and currently gives up
   after five attempts, or earlier on permanent failure. A failed delivery or
   missing address remains available to Admin alert processing.
3. Use the incident or notification ID to correlate provider and alert handoff.
   Alerts are retried until accepted. The provider/alert adapter must
   deduplicate by its supplied ID. The platform has no manual resend screen;
   provider remediation belongs to the approved adapter owner. Record whether
   the Admin received the alert and whether dashboard notices stayed readable.

## Deadline change request

1. Record the tournament ID, the deadline type, current and requested times
   with timezone, and the reason. Verify the current state and whether a
   bracket has been drawn. An affected Organizer can request the change.
2. With a current Admin session, submit the later time, reason and explicit
   confirmation through the [deadline API](API_CONTRACT.md#post-tournamentsidextend-deadline).
   Keep registration at or before submission. If both must move past the
   current submission deadline, extend submission first.
3. Record the audit event ID, affected count and notification status from the
   response. If publication is pending, check the next maintenance pass for
   `deadline_notices_pending`. Retrying the same request with its original key
   can also finish publication. Eligible email delivery runs separately.
4. Confirm the stored deadline and event timezone with an authorized
   participant and verify whether the registration or upload window reopened.
   A drawn bracket locks pins. Escalate a request that arrives after the draw.

## Replay purge incident

1. Confirm tournament archive state and the open `purge_failed` incident using
   **Operations** and the vault record. Check that maintenance and web use the
   same private data directory. Resolve the diagnosed filesystem/permission
   failure with the service owner.
2. Let the next maintenance pass retry the purge. In a prepared local/staging
   copy, run a one-shot only with the recurring maintenance service stopped.
   This performs all due maintenance tasks, including deadline processing.

   ```bash
   backend/.venvs/py3.15/bin/python -m backend.services.runner \
     --config "$BIO_SERVICE_CONFIG" maintenance --once
   ```

3. Verify the vault purge is `done` and the tournament folder contains no
   replay binaries. Verify match/bracket history separately. Check that the
   private live board is refused after archive. Keep worker output and
   restored copies private until the artifact retention review is complete.
   Maintenance checks archived folders even when a purge is marked `done`.
   If a restore brought a file back, verify that the next purge removes it.
   If archive starts during replay collection, maintenance skips that
   bracket and continues the remaining work in the same pass.

## Backup and restore rehearsal

Use a disposable, isolated staging target and the same application source and
schema version as the snapshot. Leave worker, maintenance, email and alert
services stopped during verification. Give staging its own database, state
directory and secrets. Leave `adapter_factory` null. Restoration is a staging
rehearsal until BIO-803 establishes retention, recovery objectives and a
reviewed cutover.

1. At the source rehearsal fixture, stop request writers and gracefully drain
   all four services before recording the snapshot time. Keep them quiescent
   through both captures. Choose a new private backup directory outside the
   state tree. Configure `pg_dump` and `pg_restore` connection settings for the
   appropriate environment via the approved PostgreSQL client configuration.
2. Capture PostgreSQL and all shared service state, including registry,
   submissions, queue, roster, tournaments, matches, notifications, email-alert
   receipts and the replay vault/index. The archive also holds any private
   worker output present at capture. Keep backups and output restricted.

   ```bash
   umask 077
   pg_dump --format=custom --file "$BIO_BACKUP_DIR/web.pgdump" \
     --dbname "$BIO_PGDATABASE"
   tar --exclude='./host.lock' --exclude='./service-*.lock' --exclude='./*.json.lock' \
     -C "$BIO_DATA_DIR" -cpf "$BIO_BACKUP_DIR/service-state.tar" .
   (cd "$BIO_BACKUP_DIR" && sha256sum web.pgdump service-state.tar > SHA256SUMS)
   ```

3. Check checksums and inspect the archive listing. Restore into a new empty
   PostgreSQL database and a new empty private directory using the staging
   credentials. The application is still stopped during this step.

   ```bash
   (cd "$BIO_BACKUP_DIR" && sha256sum -c SHA256SUMS)
   pg_restore --exit-on-error --no-owner --no-privileges \
     --dbname "$BIO_RESTORE_DATABASE" "$BIO_BACKUP_DIR/web.pgdump"
   tar -C "$BIO_RESTORE_DATA_DIR" -xpf "$BIO_BACKUP_DIR/service-state.tar"
   ```

4. Point staging Django and the service config to the restored database and
   directory. Validate account scope, schema, queue counts, pinned submission
   hashes, match and bracket references, notification preferences and the
   vault index. Compare archive/deletion records recorded after the snapshot.
   Once the archive records are reconciled, run the purge reconciliation
   against staging. For a replay-only check without advancing deadlines,
   use the following command with `BIO_RESTORE_DATA_DIR` pointing to the new
   private state directory.

   ```bash
   BIO_DATA_DIR="$BIO_RESTORE_DATA_DIR" backend/.venvs/py3.15/bin/python - <<'PY'
   import os
   from pathlib import Path
   from backend.match_orchestrator.replays import ReplayIndex, Vault, purge_pending

   root = Path(os.environ['BIO_DATA_DIR'])
   print(purge_pending(Vault(root / 'replays', ReplayIndex(root / 'replays.json'))))
   PY
   ```

   Verify that archived vault folders are absent and authorized replay requests
   return `410`. An empty list can also mean a purge failed. Check for open
   `purge_failed` incidents and compare archived folders against the restored
   index. Keep artifact access disabled until state and retention reconcile.
   Reconcile deliveries already handed off since the snapshot before enabling
   a sender.
5. Record elapsed recovery time, snapshot age, what was lost and the results
   of the checks. Preserve failed staging state for diagnosis. Rehearse from
   a fresh isolated target after a failure.

## Key rotation rehearsal

- **Web signing key.** Change `BIO_WEB_SECRET_KEY` in the protected web-process
  configuration and coordinate restart of all web processes with the new value.
  Expect existing signed-in sessions to require fresh login. Check web liveness,
  exercise fresh login with CSRF and confirm an old session cannot read a
  protected view. Record the rotation time and affected processes. Keep the
  former secret out of logs, commits and backup notes. Use a second fresh secret
  if the replacement must be changed during incident recovery.
- **Adapter credentials.** The authorized provider owner provisions and tests
  a replacement credential. Update the affected process environment and
  restart the email/alert role with its normal supervision. Confirm acceptance
  with a disposable destination, record the handoff, and revoke the old
  credential using the provider's process. Reconcile pending deliveries and
  avoid repeating handoffs. The current local fixture has no real provider.

Rehearsal evidence belongs in the test record. The local procedures leave
target-host restart, production backup/restore, approved provider drills and
runbook sign-off open.
