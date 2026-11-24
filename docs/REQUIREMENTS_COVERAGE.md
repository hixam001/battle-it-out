# Requirements coverage: what Battlecode provides and what we must develop

**Rule (owner instruction, 2026-11-24):** anything a requirement asks for that Battlecode does not provide is **ours to develop**. Nothing is assumed to come with the engine unless this table says `Provides`, and a requirement is not finished while it is `PARTIAL` or `TODO`. This file lists every requirement of the PRD, the SRD (SRD-001 to SRD-070) and the non-functional requirements with a status taken from the code and tests in this repository, not from intentions.

## What Battlecode actually provides

Read from the scaffold, the engine 1.2.6 sources and the `battlecode26` Python package, and confirmed by running them:

- the game simulation (Java engine server), the map format and a few maps, the win conditions with their own tie-breakers (points, robots alive, cheese, then an unseeded coin flip);
- an official Python client/runner (`battlecode26`) that runs bots as threads of one process, with a bytecode counter that charges game calls only;
- a replay file (`.bc26`) per match and a desktop client to watch it;
- Gradle tasks for local matches and `zipForSubmit` (a multi-file zip for the official Battlecode site, which is not part of the scaffold).

It does **not** provide: users, roles, tournaments, brackets, byes, house bots, registration, invitations, submission storage and versioning, upload validation beyond a text grep, isolation of hostile code, per-team resource limits, failure classification, retries, tie-break maps, an auditable coin flip, replay storage and deletion, notifications, audit logs, deletion and retention rules, a web UI, or a worker service. All of those are ours.

## Summary

| Status | Count | Meaning |
|---|---|---|
| DONE | 14 | built and tested here (library or tool level), nothing material missing |
| PARTIAL | 32 | built in part; the gap column says what is still ours to develop |
| TODO | 40 | not built; no code exists |
| DEFERRED | 5 | P2, not scheduled (PRD section 5) |
| **Total** | **91** | 89 requirements are not wholly provided by Battlecode, so they are ours; 72 of the 91 still need development work |

Reading this honestly: the **execution foundation** (EPIC-00 to EPIC-03: bot validation, sandbox, failure classification, logs, retry, tie-break maps) is largely built and tested, but only as libraries. **Everything that makes it a platform** (backend, auth, registration, submissions, tournament operations, notifications, deletion, website, endpoints around the replay vault) is not built. 'DONE' does not mean accepted by the owner or reviewed independently.

## Coverage matrix

Battlecode column: `Provides` we reuse it; `Partly` it does something related that does not meet the requirement; `None` it has nothing.

| ID | Requirement | Battlecode | Status | Built in / planned in | What is still ours to develop |
|---|---|---|---|---|---|
| SRD-001 | Battlecode engine stays the game simulation | Provides | **DONE** | Engine 1.2.6 pinned (`versions.lock.json`) | Java engine declares no licence (CN-003): ask the Battlecode team |
| SRD-002 | Reproducible setup, pinned dependencies, documented commands | Partly (scaffold is unpinned and reinstalls the package every run) | **PARTIAL** | `match_runner/setup_env.py`, `versions.lock.json`, docs | Linux x86_64 only; no worker image or container (DEC-11) |
| SRD-003 | Python 3.13 verified, not assumed | None (engine supports 3.12 only) | **DONE** | Matrix 3.12 to 3.15 via `runner_entry.py` (CN-001) | Engine authors do not support it; owner confirmation of the patch version (DEC-03) |
| SRD-004 | Exactly one `bot.py`, no ZIP or extra files | None (scaffold `zipForSubmit` is multi-file; `run.py verify` only greps for `def turn():`) | **PARTIAL** | `bot_validator` (`E-FILES`); `submission_registry` refuses any other name and stores exactly `bot.py` (CN-016) | No upload endpoint; the 256 KiB size cap is interim |
| SRD-005 | Stdlib and preinstalled libraries only, no installs | Partly (engine allows only `random`, `math`, `enum`, `battlecode26`) | **PARTIAL** | CN-004, `policy.json`, sandbox without network | Narrower than the PRD wording; owner to confirm; no preinstalled third-party libraries exist yet |
| SRD-006 | All bots use the same runtime | None | **PARTIAL** | Pinned interpreter and venv per Python version | No runtime image |
| SRD-007 | Execution outside the web/API process, isolated worker | None (the engine runs both teams as threads of one process) | **PARTIAL** | Per-team bubblewrap sandbox, router, guard (CN-005, CN-008); `work_queue`: queue and a separate worker process with leases, retry and dead-job incidents, tested with real games (CN-017) | No container or image; one host only; no API or scheduler that enqueues work; no independent review (SR-06) |
| SRD-008 | Platform-wide CPU/time, memory, instruction limits | Partly (Java bytecode counter; Python charges game calls only) | **PARTIAL** | `guard.py`, rlimits, seccomp, optional cgroups | Numbers are an interim profile; benchmark outstanding (DEC-04) |
| SRD-009 | Bot crash, timeout or limit breach = automatic loss, no rematch | Partly (an exception kills one robot, not the match) | **DONE** | CN-005, CN-006, `classify` | Uncaught-exception rule is reversible (CN-005 D2) |
| SRD-010 | Platform failure restarts with same map and versions and a NEW seed | None | **PARTIAL** | `match_orchestrator` (CN-009) | New seed impossible: engine tie-break seed is not controllable (TC-04 not met) |
| SRD-011 | Retry up to 10 times, then alert Admin | None | **PARTIAL** | Retry cap, incident, alert function (CN-009) | No real Admin channel; attempt-count reading (DEC-05) interim |
| SRD-012 | Record bot versions, map, engine/runtime version, seed, attempts, result, logs | Partly (replay file only) | **PARTIAL** | Orchestrator match record, JSONL structured logs (CN-007) | JSON-file store is a stand-in (DEC-11); seed is always null |
| SRD-020 | Single elimination, random pairings, automatic byes | None | **DONE** | `bracket.py` (CN-011): one recorded random draw, byes spread so none meets another | Tournament and map storage; the API that creates it |
| SRD-021 | Human teams get bye priority over house bots | None | **PARTIAL** | Byes go to human teams (CN-011) | Meaningful only once house bots exist (DEC-06) |
| SRD-022 | House bots fill gaps but cannot advance or win | None | **TODO** | BIO-303 | Refused on purpose: placement algorithm undecided (DEC-06); house bots do not exist yet |
| SRD-023 | Sequential matches, Organizer starts each round | None | **PARTIAL** | `bracket.start_round` / `run_round` (CN-011), host lock | Organizer trigger, authorization, queue and service (API layer) |
| SRD-024 | Normal tie: one tie-break map | None (engine settles ties itself, then flips an unseeded coin) | **DONE** | `tiebreak.py` (CN-010); `maps.py` map pool: 1 tie-break map, distinct from the played maps, pinned by SHA-256 (CN-014) | Organizer-chosen pool in tournament storage; custom maps |
| SRD-025 | Final tie: three tie-break maps in order | None | **DONE** | `tiebreak.py` (CN-010); `maps.py`: 3 distinct tie-break maps per pool (CN-014) | Reading of 'three maps' (all played, majority of wins) awaits owner confirmation |
| SRD-026 | Still tied: 50/50 coin flip, displayed, logged, no rerolls | None (engine coin flip is unseeded and unauditable) | **PARTIAL** | `tiebreak.py`: one stored `secrets` draw, `public_view` | Screen, Admin audit log, real publishing |
| SRD-027 | Qualification cutoff tie: automatic draw, shown, logged, no reruns | None | **TODO** | - | Draw inputs and audit method undecided (DEC-14) |
| SRD-028 | Results publish automatically to authenticated users | None | **TODO** | BIO-EPIC-04/07 | Needs auth, API, UI |
| SRD-030 | Admin and Organizer create tournament drafts | None | **TODO** | BIO-EPIC-04/06 | - |
| SRD-031 | Organizer tournaments need Admin approval | None | **TODO** | BIO-EPIC-06 | - |
| SRD-032 | Rejection with reason; edit and resubmit | None | **TODO** | BIO-EPIC-06 | - |
| SRD-033 | Assigned Organizer edits approved settings until the deadline | None | **TODO** | BIO-EPIC-06 | Scoped permissions need EPIC-04 |
| SRD-034 | Registration and submission deadlines independent | None | **TODO** | BIO-EPIC-06 | DEC-08 (separate freeze deadline) |
| SRD-035 | Admin extends deadlines, participants notified | None | **TODO** | BIO-EPIC-06 | Email provider (DEC-11) |
| SRD-036 | After a deadline, changes need an Admin extension first | None | **TODO** | BIO-EPIC-06 | - |
| SRD-037 | Emergency override with reason, audit, notifications | None | **TODO** | BIO-EPIC-06 | - |
| SRD-038 | Official roster imported and correctable before registration | None | **TODO** | BIO-EPIC-05 | Roster file format undecided |
| SRD-039 | Register with official email and invitation code | None | **TODO** | BIO-EPIC-05 | DEC-01 (code per participant or team) |
| SRD-040 | Invalid attempts do not consume the code or block retry | None | **TODO** | BIO-EPIC-05 | Rate limiting design |
| SRD-041 | Single-use codes, expire at registration close | None | **TODO** | BIO-EPIC-05 | - |
| SRD-042 | Registration locks email, team, member number, role | None | **TODO** | BIO-EPIC-05 | DEC-12 |
| SRD-043 | Only Admin revokes and replaces codes | None | **TODO** | BIO-EPIC-05 | - |
| SRD-044 | Not fully registered by deadline: excluded | None | **TODO** | BIO-EPIC-05 | - |
| SRD-050 | Invalid upload rejected at once with an actionable reason | None | **PARTIAL** | `bot_validator` error codes with line numbers; `submission_check` adds trial-match reasons (CN-013); `submission_registry.submit` runs the static check at upload and keeps the reasons in the history (CN-016) | Upload endpoint and its error format; the check runs at upload, the trial result arrives later (`validating`) |
| SRD-051 | Only a valid submission may become active | None | **DONE** | `submission_check.may_activate` (valid verdict for the exact sha256; CN-013); `submission_registry.record_verdict` refuses a verdict for another file or a stale claim (CN-016) | Endpoint; the trial runs on the worker, not in the request |
| SRD-052 | Latest valid becomes active; invalid does not displace | None | **DONE** | `submission_registry`: the highest valid version is active, rejected, inconclusive and statically invalid versions never displace it, a late older verdict does not replace a newer active one (CN-016) | Endpoint |
| SRD-053 | History of versions and validation outcomes | None | **DONE** | `submission_registry`: every version kept with each validation entry (static, trial, repeated checks), active and superseded flags, matches pinned in (CN-016) | JSON-file store is a stand-in (DEC-11); the bot's own output text is not stored; no retention rule (DEC-13) |
| SRD-054 | Submissions lock at deadline, extension reopens | None | **PARTIAL** | `submission_registry.submit` refuses at or after the deadline it is given; a later deadline reopens; `pin_tournament` is write-once after the deadline (CN-016) | Deadline storage, extension and emergency override (EPIC-06): the registry trusts the deadline the caller passes |
| SRD-055 | A match references the exact bot version used | None | **DONE** | Submission references pinned per match (CN-009 D6); registry versions are read-only folders re-hashed before use (`pinned_folder`, `verify_pins`, CN-016) | The orchestrator does not call `verify_pins` itself yet |
| SRD-056 | Participant views and downloads own source and history | None | **PARTIAL** | `submission_registry.history` / `download` (team members, bytes re-verified, CN-016) | Endpoint; BIO-NFR-08 private storage beyond file modes |
| SRD-057 | Assigned Organizer views, cannot change | None | **PARTIAL** | `submission_registry`: assigned Organizer and Admin read and download (audited), every write is refused (CN-016) | Endpoint; how an Organizer assignment is known (EPIC-04) |
| SRD-058 | Other teams' source stays private | None | **PARTIAL** | Sandbox mounts only the team's own folder; logs role-scoped; registry answers `NotFound` for anyone outside the team, the assigned Organizer and Admin (CN-016) | Web-level privacy and storage authorization not built |
| SRD-060 | Dashboard notifications mandatory; email can be disabled | None | **TODO** | BIO-EPIC-06 | - |
| SRD-061 | Major events trigger notifications | None | **TODO** | BIO-EPIC-06 | Templates, provider (DEC-11) |
| SRD-062 | Immutable, permanent audit logs | None | **TODO** | BIO-EPIC-04 | Series `history` and incidents are only sources |
| SRD-063 | Role-scoped log visibility | None | **PARTIAL** | Match logs: role views participant/organizer/admin (CN-007) | Audit and notification logs; real authorization |
| SRD-064 | Sensitive personal/admin data hidden | None | **PARTIAL** | Redactor for host paths, emails, IPs, secrets in match logs | Applies only to match logs |
| SRD-065 | Deletion request queued while team competes; cancellable | None | **TODO** | BIO-EPIC-06 | - |
| SRD-066 | Deleted participant removed from rosters; results unchanged | None | **TODO** | BIO-EPIC-06 | - |
| SRD-067 | Captaincy transfers on captain deletion | None | **TODO** | BIO-EPIC-06 | DEC-07 (no successor) |
| SRD-068 | Team deletion after archive; Admin-only restore | None | **TODO** | BIO-EPIC-06 | - |
| SRD-069 | Permanent tournament deletion, Admin only, audit kept | None | **TODO** | BIO-EPIC-06 | - |
| SRD-070 | Archive deletes replays, keeps results and history | None (engine only writes the replay file) | **PARTIAL** | `replays.py`: archive then purge then verify, retry of a failed purge, results untouched (CN-012, 39 tests) | Archive endpoint and who may call it, scheduled `purge_pending`, vault backups and restore drill |
| BIO-REQ-01 | Audit the Battlecode repository and scaffold | None | **DONE** | Docs, handoff, scaffold findings | - |
| BIO-REQ-02 | Reproducible scaffold compatible with the Python target | Partly | **PARTIAL** | See SRD-002, SRD-003 | See SRD-002 |
| BIO-REQ-03 | Execute a single-file Python bot with the engine | Provides (official runner) | **DONE** | Launcher over `runner_entry.py` | - |
| BIO-REQ-04 | Validate entrypoint, syntax, imports, runtime | None | **DONE** | `bot_validator` + `submission_check` trial match on both sides (CN-013) | Wiring into upload and activation is BIO-REQ-14 |
| BIO-REQ-05 | Run two bots in an isolated environment | None | **PARTIAL** | See SRD-007 | See SRD-007 |
| BIO-REQ-06 | Separate bot failure from platform failure | None | **DONE** | CN-006 | - |
| BIO-REQ-07 | Automate sequential matches, results, bracket advancement | None | **PARTIAL** | Orchestrator, series, bracket and round runner | Queue/service around them, house bots (DEC-06) |
| BIO-REQ-08 | Generate replays and keep them until archive, then delete | Partly (engine writes `.bc26`; client can view it) | **PARTIAL** | Replay path and SHA-256 recorded per game; vault with hash and gzip check, access rule, 404/410, purge (CN-012) | Replay endpoint, building a `Viewer` from the session, object storage and short-lived URLs, a player (DEC-10) |
| BIO-REQ-09 | Platform-failure retry policy | None | **PARTIAL** | See SRD-010, SRD-011 | See SRD-010/011 |
| BIO-REQ-10 | Prove the engine path end to end before the web build | None | **PARTIAL** | Real matches, series, failure injection, a real 3-team tournament and a 5-team simulation with byes, forfeit, tie-breaks, replays and archive pass (CN-015) | TC-05 not complete: house bots, qualification draw, replay endpoint and worker hand-off |
| BIO-REQ-11 | Authentication, roles, tournament-scoped permissions | None | **TODO** | BIO-EPIC-04 | DEC-11, auth model |
| BIO-REQ-12 | Tournament creation, approval, deadlines | None | **TODO** | BIO-EPIC-06 | - |
| BIO-REQ-13 | Roster import, email and code validation | None | **TODO** | BIO-EPIC-05 | - |
| BIO-REQ-14 | One-file submissions, validation, versioning | None | **PARTIAL** | `bot_validator`, `submission_check`, `submission_registry` (versions, activation, history, deadline lock, privacy; CN-016) | Upload endpoint, tournament deadlines and extensions, roster and registration link (EPIC-05), notifications |
| BIO-REQ-15 | Admin and Organizer tournament operations | None | **TODO** | BIO-EPIC-06 | - |
| BIO-REQ-16 | Email and dashboard notifications | None | **TODO** | BIO-EPIC-06 | - |
| BIO-REQ-17 | Participant dashboard, bracket and results views, replay access | Partly (desktop replay client only) | **TODO** | BIO-EPIC-07 | - |
| BIO-REQ-18 | Team and account deletion lifecycle and retention | None | **TODO** | BIO-EPIC-06 | - |
| BIO-REQ-19 | Public landing and marketing site | None | **DEFERRED** | P2 / EPIC-07 | - |
| BIO-REQ-20 | Live match viewing (if approved) | Partly (engine streams to its client) | **DEFERRED** | P2 | DEC-09 |
| BIO-REQ-21 | More languages, multi-file submissions, custom dependencies or environments | None | **DEFERRED** | P2 | - |
| BIO-REQ-22 | Advanced analytics | None | **DEFERRED** | P2 | - |
| BIO-REQ-23 | Dispute workflow and extra admin tools | None | **DEFERRED** | P2 | DEC-13 |
| BIO-NFR-01 | Bot execution isolated from host, other bots, user data | None | **PARTIAL** | See SRD-007 | No independent review |
| BIO-NFR-02 | Fixed, consistently enforced limits; numbers benchmarked | Partly | **PARTIAL** | See SRD-008 | Benchmark |
| BIO-NFR-03 | Runtime, engine, dependencies, worker image pinned | None | **PARTIAL** | `versions.lock.json` | Worker image |
| BIO-NFR-04 | Match records: versions, map, engine version, seed, result, attempt | None | **PARTIAL** | See SRD-012 | Database; seed |
| BIO-NFR-05 | Server-side role and scope checks on every operation | None | **TODO** | BIO-EPIC-04 | - |
| BIO-NFR-06 | Append-only audit records, permanent | None | **TODO** | BIO-EPIC-04 | - |
| BIO-NFR-07 | Dashboard notifications even when email is off | None | **TODO** | BIO-EPIC-06 | - |
| BIO-NFR-08 | Submission files private, served only after authorization | None | **TODO** | BIO-EPIC-05 | - |
| BIO-NFR-09 | Backups and tested recovery | None | **TODO** | BIO-EPIC-08 | - |
| BIO-NFR-10 | Logs avoid secrets and minimise personal data | None | **PARTIAL** | Redactor in `match_log.py` | Best effort; only match logs |
| BIO-NFR-11 | Concurrent match capacity from load tests | None | **TODO** | BIO-EPIC-08 | One match per host today (fixed engine port) |
| BIO-NFR-12 | UI communicates deadlines, validation, match state, errors | None | **TODO** | BIO-EPIC-07 | - |

## Development backlog derived from this table

In the order the roadmap needs them (PROJECT_PLAN section 6); each line is development, none of it exists in Battlecode.

1. **Finish the execution gate (EPIC-02/03):** benchmark and fix the limits (DEC-04); independent sandbox review; engine-side seed or an accepted waiver for TC-04; a worker container or image, a scheduler or API that enqueues work (the worker and queue exist, CN-017) and several hosts; Admin alert channel; house bots in the bracket (needs DEC-06; the human bracket and round runner exist); qualification draw (DEC-14); replay endpoint, object storage and a player (DEC-10; the vault, access rule and purge exist, CN-012); a pool is chosen and stored per tournament (the map pool library exists, CN-014); a full simulated tournament (TC-05): a five-team one on the real engine runs (CN-015), the version with house bots and the qualification draw does not. The upload check itself (static check plus trial match) exists, CN-013; its upload endpoint and activation do not.
2. **Backend foundation (EPIC-04, needs DEC-11):** stack, database, auth and sessions, roles and tournament scope enforced on the server (BIO-NFR-05), append-only audit log, private file storage, API from `API_CONTRACT.md`, plus the missing user/role/organizer assignment endpoints.
3. **Registration and submissions (EPIC-05):** roster import and correction, invitation codes (DEC-01), registration rules and locks, the upload endpoint around `submission_registry` (versions, activation, history, download, privacy and the deadline lock exist as a library, CN-016).
4. **Tournament operations (EPIC-06):** approval and rejection, independent deadlines and extensions, emergency override, notifications (dashboard and email), deletion and retention lifecycle, archive.
5. **Website (EPIC-07) and launch (EPIC-08):** participant, Organizer and Admin screens (including the coin-flip display), usability, backups and recovery drill, load test, pilot tournament, runbooks.

## Keeping this file true

- Change a status only with evidence: a test that passes, or a file that exists. Say what was run.
- When a task closes a requirement, update its row and the counts in the same pull request (the counts are computed from the rows by a script the author keeps outside the repository; recount by hand if you edit rows).
- New requirements in the PRD or SRD get a row on the day they are added; the default status is `TODO` and the default Battlecode answer is `None`.
