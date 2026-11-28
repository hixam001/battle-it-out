# Battle It Out --- Admin Guide

**Version:** 1.1\
**Date:** 2026-11-26\
**Audience:** the platform Admin (global role) and whoever operates the platform. Participants and Organizers: see [`USER_GUIDE.md`](USER_GUIDE.md).

## Current console

Sign in with the provisioned platform Admin account and open **Operations**.
The page shows service counts, current incidents, dead jobs and recent feature
audit events. Use the [interim operations runbook](OPERATIONS_RUNBOOK.md) for
triage, deadline requests, purge checks and a staging recovery rehearsal. The
console is read-only for those operational incidents. Use **Approvals** to
approve or reject Organizer-submitted tournaments. **Match disputes** lets
you review cases in the selected tournament and record a resolution.
**Post announcement** sends a dashboard notice to the verified roster of
the selected tournament and shows how many optional emails were queued.

The rest of this guide describes the planned Admin workflow and the current
library behavior where identified. Deployment and owner decisions are tracked
in [project memory](PROJECT_MEMORY.md).

## 1. What the Admin is responsible for

The Admin has **global** access and is the only role that can:

- approve or reject tournaments;
- extend registration or submission deadlines (even after they pass);
- perform an **emergency override** of a locked setting;
- revoke or replace lost or compromised invitation codes;
- restore a deleted team;
- permanently delete a tournament;
- see all audit logs and system incidents.

**Rules that apply to every Admin action:**

- Destructive actions and overrides need an explicit **confirmation** and a **non-empty reason**. Reasons are stored in the audit log and cannot be edited.
- Every important change writes an **immutable audit event** and, where required, a notification to affected participants.
- Admin power is still limited by the product's privacy rules: the Admin cannot recover deleted replays, and other teams' source code is never exposed to participants.

## 2. Creating and approving tournaments

Open **Manage tournaments** to list tournaments and create an Admin draft
with its own registration and submission deadlines. Open a tournament to
edit available settings, approve an Admin-created draft with confirmation,
or open registration after approval. If another staff member saved a change,
refresh the tournament before retrying. The detail page links to **Deadline
controls** for extensions and locked-setting overrides.

For Organizer submissions, use the approval queue.

1. Open **Approvals** (`/admin/approvals`) and select a pending tournament.
2. Review name, description, deadlines, and configuration.
3. **Approve** (confirmation required) or **Reject** with a reason (mandatory; the Organizer sees it, edits, and resubmits).
4. If the record changed during review, reload the details before deciding.
5. An approval leaves the tournament in `approved`. Opening registration is a separate action.

Tournament states move from draft through review and approval to registration,
running, completed and archived. Rejected drafts can be revised and
resubmitted through **Manage tournaments**. The assigned Organizer can open
registration manually from the approved tournament.

## 3. Deadlines and emergency overrides

Open **Deadline controls** and select the tournament. Review its dates,
choose an extension or locked-setting override, enter a reason and confirm
the change. The console shows the affected-account count and whether the
dashboard notices have been published or are pending automatic retry.
[Admin API contract](API_CONTRACT.md#post-tournamentsidextend-deadline).

| Situation | What to do | What happens |
|---|---|---|
| Registration or submission needs more time | **Extend** the relevant deadline (reason and confirmation required) | Affected accounts get dashboard notices and eligible email enters the delivery queue. Unused invitation codes follow the registration deadline. Extension reopens submissions before entry versions are pinned |
| A setting must change after a deadline | Normally: extend the deadline first, then change the setting | The Organizer can then edit permitted settings |
| An urgent change cannot wait for a deadline extension | **Emergency override** (reason and confirmation required) | The change applies without extending the deadline. Participants are notified with the changed setting, the reason, the time, and who authorized it. Fully audited |

**Recommended:** prefer a deadline extension to an override; use overrides only for real emergencies. Whether a separate configuration-freeze deadline exists is `[DECIDE]` (DEC-08; avoiding one is recommended).

## 4. Invitation codes and roster issues

From an Admin tournament's settings, open **Manage roster** to import CSV
or JSON, correct unlocked rows and view the registration report. Open **View
teams** for verified team profiles, bracket standing, validation history
and audited source downloads.

- On **Invitation codes**, select eligible roster participants and choose
  **Issue selected codes**. The receipt pairs each new code with its official
  email. Share those codes privately. Assigned Organizers can also issue
  initial codes. **Only an Admin** can revoke or replace a code.
- **Lost or compromised code:** open **Invitation codes**, select the
  tournament and manage the matching code ID. Revoke the code to disable it,
  or replace it while the roster entry is eligible. Either action needs a
  reason and confirmation. Replacement revokes the old code and displays the
  new value until dismissed or the page changes. Share it privately with the
  roster participant.
- Invalid registration attempts do not consume codes. If a legitimate participant is stuck, check the roster entry (email spelling, normalization) with the Organizer before reissuing.
- After a participant registers, their email, team, member number, and role are locked. A correction after registration is not allowed through the normal roster tool; any exception policy is `[DECIDE]`.
- Code granularity (per participant, recommended, or per team) is `[DECIDE]`.

## 5. Operating a tournament and handling incidents

Open **Operations** (`/admin`) to see open incidents and dead jobs.
Incident rows show the affected reference, attempt count when recorded,
and alert timestamp or pending state. Dead jobs show the job ID, type
and failure count. Select **Refresh operations** after checking the
service state.

### 5.1 Before each round (Recommended checklist)

1. Every eligible team has an active, valid bot version; the bracket is generated; maps and the execution profile are set.
2. Worker health is green and the worker image matches the approved one (`/admin`, system incidents and worker health).
3. The Organizer starts the round. Starting is idempotent, so repeated clicks do not duplicate matches.

### 5.2 Failure classes

| What happened | Meaning | System behavior | Admin action |
|---|---|---|---|
| Bot crash, timeout, or limit violation | A game result | Bot loses; opponent advances; no rematch | None; explain if asked |
| Engine or worker failure | A platform incident | Retry with the same map and pinned bot versions. Engine seed control is open | Watch for the cap |
| Retry cap reached (current default 10 total attempts) | Operational problem | Automatic retry stops, you are alerted, the match pauses | Follow the incident runbook. Resume authority and the authenticated mutation route remain open |
| Replay missing before archive | Processing failure | Participants see "unavailable"; staff incident created | Check storage and worker logs |

### 5.3 Ties

You do not decide ties. Normal ties use one tie-break map, finals use three in order, then a public 50/50 coin flip with no rerolls; qualification-cutoff ties use an automatic random draw after scores and slots are final. All are logged and shown. The qualification draw's exact inputs and randomness audit are `[DECIDE]` (DEC-14), and the house-bot placement algorithm is `[DECIDE]` (DEC-06).

## 6. Archive, deletion and restore

Open a completed tournament from **Manage tournaments** and review
**Tournament archive**. Confirm replay removal and select **Archive
tournament**. The receipt reports whether the vault purge finished or
maintenance will retry it. After archiving, you can check the purge or open
the retained results from the same panel.

| Action | Who | Requires | Effect | Reversible? |
|---|---|---|---|---|
| **Archive** a tournament | Admin or assigned Organizer | Confirmation | **Replay files are deleted** for everyone, you included. Results, brackets, standings, and match history remain visible to signed-in users | **No** (replays cannot be recovered) |
| **Delete a team** (after archive) | Admin or assigned Organizer | Confirmation and reason | Removes active team profile and management access; history and audit stay | **Yes**, by an Admin, while the tournament still exists |
| **Restore a team** | Admin | Confirmation | Restores the team | n/a. Not possible after permanent tournament deletion |
| **Permanently delete a tournament** | Admin only | Confirmation and reason | Removes operational tournament and team data. **Audit logs stay permanently** | **No** |
| Participant account deletion | Participant request | Queued while the team is competing | Participant removed from historical rosters; results unchanged | Cancelable only before it runs |

**Recommended:** before archiving, confirm the results and bracket are final and that nobody still needs replays; before permanent deletion, confirm there is no pending dispute. Source-code retention after deletion is `[DECIDE]`.

## 7. Audit, notifications and privacy

- **Audit logs:** open **Audit log** for the global feed, or filter by an
  exact tournament ID to find retained records, including deleted tournaments.
  For a current tournament, open **Tournament audit log** from its settings.
  Expand an event for the audit fields available to your role.
  [Audit API contract](API_CONTRACT.md#get-tournamentsidaudit-logs-and-get-adminaudit-logs).
- **Notifications:** dashboard notifications are mandatory and independent of email. Email delivery attempts and failures are recorded and retried. Email provider, templates, and which security emails are mandatory are `[DECIDE]`.
- **Privacy:** other teams' source code stays private throughout. An Organizer assigned to a tournament may view and download that tournament's source; you may too.
- **Roles and assignments:** the navigation map lists a screen for user, role, and Organizer assignment, but **`API_CONTRACT.md` currently defines no endpoints for it**. This is a gap to close before the backend epic (BIO-EPIC-04). Whether a user may hold several roles is `[DECIDE]`.
- **Account recovery and verification resend** remain open (DEC-13). Private dispute review is available in the feature console; appeal and outcome-correction policy remain open.

## 8. Working with the repository today

These scaffold commands are historical engine checks from 2026-11-24. Use the current [Python launcher](../backend/match_runner/README.md) for local bot matches.

| Task | Command (from `backend/battlecode26-scaffold/`) | Notes |
|---|---|---|
| List what you can run | `./gradlew tasks --group battlecode --offline` | Verified |
| See configured versions | `./gradlew version --offline` | Prints engine and client versions (engine 1.2.6, client 1.0.6 at time of writing) |
| Run a baseline Java match | `./gradlew runLocal --offline -Preplay=/path/out.bc26` | Verified: finishes in about 2 seconds with a replay. Use `-Preplay` so an existing replay in `matches/` is not overwritten |
| Check for a newer engine or client | `./gradlew checkNewVersion` | The build already reports client 1.0.7 available; needs network |
| Update engine/client versions | `./gradlew update` | **Recommended:** do this deliberately, in its own pull request, and re-run the baseline; it rewrites `engine_version.txt` and `client_version.txt`, and the Python package must then match |

Cautions:

- The scaffold's `run.py` accepts only **Python 3.12**; use the match launcher instead, which runs on 3.12 to 3.15 (`backend/match_runner/README.md`).
- The Python engine package reports itself as `1.2.2` while the engine is `1.2.6`. This is not drift: the official 1.2.6 release artifact contains package 1.2.2 (checked by hash on 2026-11-24). The versions and artifact hash are pinned in `backend/match_runner/versions.lock.json` and checked on every launch.
- Running Python bots through Gradle does not work as shipped on Linux. Use `backend/match_runner/launcher.py` instead (see `TECHNICAL_DOCUMENTATION.md` section 3.2). A full Python match of the example bot takes about 3 seconds. The project launcher supplies per-team sandboxing and interim execution limits. Benchmark approval remains DEC-04.
- A hung run can leave a stray `python -m battlecode26` process; stop only your own process by PID, because editors and Gradle daemons also run Java.

## 9. Decisions an Admin should help close before launch

Highest impact first: Python patch version and OS matrix (DEC-03, tested: 3.15.2 on Linux, CN-001); numeric time, memory and instruction limits from benchmarks (DEC-04); retry-cap meaning and the paused-match procedure (DEC-05); house-bot bracket algorithm (DEC-06); invitation code granularity (DEC-01) and who may upload (DEC-02); hosting, email provider and storage (DEC-11); support route and account recovery (DEC-13); the project license given the AGPL-3.0 scaffold. The full register is in `PRD.md` §11 and `PROJECT_PLAN.md` §7.

## 10. Quick reference: Admin screens (planned)

`/admin` global status and incidents · `/admin/approvals` approval queue · `/admin/tournaments/{id}` deadline extensions and locked-setting overrides · `/admin/invitations` revoke and replace invitation codes · `/admin/audit` global audit log. Team restore, permanent deletion, and user/role assignment appear in the navigation map but have no route in the inventory yet.
