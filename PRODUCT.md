# Product

<!-- impeccable:product-schema 1 -->

> Source: derived on 2026-11-24 from `docs/PRD.md` (v1.1), `docs/SRD.md`, `docs/APP_FLOW.md`, `docs/API_CONTRACT.md`, `docs/DATA_MODEL.md`, and `docs/TEST_PLAN.md`, without a separate interview. Statements follow the docs' own labels: **confirmed** (established in project discussions), **proposed** (needs approval), and `[DECIDE]` (unresolved). If a doc and this file disagree, the doc wins; update this file.

## Platform

web

## Stack
Not decided. Proposed in the PRD and awaiting approval (`[DECIDE]` DEC-11): React + TypeScript frontend; Django + Django REST Framework API; PostgreSQL; Celery + Redis background jobs; isolated container workers for bot execution; private S3-compatible file storage; polling for updates (WebSockets only if live updates materially require them); containerized deployment behind a reverse proxy. Hosting, email provider, and object storage are also undecided.

Already in the repo (confirmed): the Battlecode 2026 Java/Python scaffold, vendored at `backend/battlecode26-scaffold/`. Its Python launcher currently requires Python 3.12 exactly; the project target is Python 3.13, not yet verified.

## Users
Three authenticated roles. Anonymous public browsing of tournament results is not assumed.

- **Participant / team member.** Registers with their official roster email plus a single-use invitation code. Submits and replaces one Python file, `bot.py`, before the deadline, and tracks their own team's submissions, validation results, matches, bracket progress, notifications, and replays. Audience ranges from beginners, including people using AI-assisted development, to experienced programmers. Can never see another team's source code.
- **Tournament Organizer.** Works only in assigned tournaments: creates drafts, edits permitted settings before deadlines, imports and corrects the official roster before registration, starts each round, and may view and download assigned teams' source code. Cannot alter submissions, locked participant details, or invitation codes, and cannot publish a tournament without Admin approval.
- **Platform Admin.** Global authority: approves or rejects tournaments (rejection needs a reason), extends deadlines, revokes and replaces compromised codes, performs emergency overrides, restores deleted teams, and permanently deletes tournaments. Watches system health and incident alerts. Every destructive action or override requires a reason.

## Product Purpose
INNOFEST Battle It Out is a Battlecode-style programming competition. Participants submit Python bots that compete automatically in the existing Battlecode 2026 game engine under controlled conditions. The platform manages invitation-based registration, bot submission and validation, sequential single-elimination matches, results, replays, notifications, and an immutable audit history.

Success means: bots run reproducibly and safely; bot failures are told apart from platform failures; tournaments run end to end with correct, traceable outcomes; and the permission, privacy, and deadline rules cannot be bypassed.

Delivery order is confirmed: scaffold modernization and Python 3.13 compatibility first, then safe bot execution and match automation, then backend, then registration/submissions, then tournament operations, then the website. Nothing visual is built until the execution foundation passes its exit gate. The public landing page is explicitly deferred.

## Positioning
The docs describe the mechanism but do not state a positioning claim, so none is invented here (`[DECIDE]`). What is confirmed: participants write a single-file Python bot that plays in the real Battlecode 2026 engine (no replacement engine); matches run in an isolated worker with fixed platform-wide limits; and outcomes are transparent and auditable, including publicly displayed tie-break and coin-flip results.

## Operating Context
- Event: INNOFEST. Entry is invitation-only against an official imported roster; unregistered or unverified participants are excluded at the registration deadline.
- Registration and submission deadlines are independent. Admin can extend either, including after it passes. Deadlines must be shown with their timezone.
- Matches run sequentially. An Organizer starts each round; the system queues matches, records results and replays, and advances winners exactly once.
- Bracket: single elimination, random pairings, automatic byes (human teams get bye priority; house bots may fill gaps but can never advance or win).
- Ties: a normal-stage tie runs one predefined tie-break map; a final tie runs three, in order; a remaining tie is settled by a logged, publicly displayed 50/50 digital coin flip with no rerolls. A qualification-cutoff tie is settled by an automatic random draw.
- Bot crash, timeout, or instruction-limit violation is an automatic loss with no rematch. An engine or platform failure restarts the match with the same map and bot versions and a new seed, up to 10 times, then alerts the Admin.
- Replays are kept until the tournament is archived, then deleted for everyone, Admin included. Results, brackets, standings, and match history remain visible to authenticated users until permanent deletion.
- Dashboard notifications are mandatory. Email is optional per participant.
- Developers work locally from the repository first; the web app comes later.

## Capabilities and Constraints
Terms to use consistently: tournament, round, bracket, bye, house bot, team, captain, roster entry, invitation code, submission (version), active submission, validation, match, attempt, replay, tie-break map, coin flip, qualification cutoff draw, archive, audit log.

Confirmed constraints:
- Python only; exactly one file named `bot.py`; no ZIP, extra files, or participant-installed packages. Standard library and preinstalled libraries only; every bot runs in the same runtime image.
- Only a successfully validated submission can become active. The latest valid submission is active; an invalid replacement never displaces it. All versions stay in history and each match records the exact version used.
- Time, memory, and instruction limits are global, not per tournament. Their numeric values come from benchmarking and must not be invented.
- Permissions are enforced on the server for every protected operation, with role and tournament-scope checks. Hiding a button is not authorization.
- Bot code is untrusted: it runs outside the web/API process in an isolated worker.
- Audit logs are append-only and permanent; sensitive data is hidden from unauthorized viewers. Historical results never change when a participant or team is deleted; deleted participants are removed from rosters entirely, with no placeholder.
- Registration locks email, team, member number, and role. Invalid invitation attempts do not consume a code or permanently block a retry.

Explicitly undecided (`[DECIDE]`, do not assume):
- invitation code per participant (recommended) or per team; captain-only upload (recommended) or any member; team size, captain selection, and team-name edits;
- Python 3.13 patch version and OS matrix; numeric resource limits; whether "10 retries" means 10 total attempts (recommended) or 10 after the first; the paused-match state after the retry cap;
- the house-bot bracket algorithm; the qualification-draw inputs and randomness audit; what happens when a deleted captain has no eligible successor;
- replay format and browser player; live match viewing (recommended: defer); roster file format; upload size cap; account recovery, verification resend, and match disputes; manual or scheduled opening of registration; whether a separate configuration-freeze deadline exists; the auth/session model and pagination style.

Out of scope for the first release: additional languages, multi-file submissions, custom environments, public anonymous results, live streaming, advanced analytics, dispute workflow.

## Brand Commitments
The name is "Battle It Out", presented as "INNOFEST Battle It Out" and described as a Battlecode-style competition. No logo, colors, typography, voice, or tone have been defined or approved. Battlecode is a separate project whose engine and scaffold are reused; the docs claim no official affiliation or endorsement, so none should be implied.

## Evidence on Hand
- Specification documents in `docs/` (PRD, SRD, API contract, data model, test plan, app flow), plus `handoff.md` for current project state.
- The Battlecode 2026 Java/Python scaffold with example bots at `backend/battlecode26-scaffold/`.
- Absent, and not to be fabricated: any UI or design, logo or brand assets, testimonials, past participants or results, press, pricing, sponsor details, real tournament dates, real rosters, benchmark numbers, or measured Python 3.13 compatibility.

## Product Principles
1. **Prove the engine before presenting it.** The execution path, failure classification, and limits come first, and nothing claims compatibility, isolation, or reliability without a test that proves it.
2. **Fairness is visible.** Tie-breaks, coin flips, draws, retries, and bot-versus-platform failures are shown and logged openly; a bot loss is never confused with a platform retry.
3. **Least privilege, privacy by default.** Other teams' code stays private; every action is limited by role and tournament scope; destructive actions need a stated reason and an explicit confirmation.
4. **State is always unambiguous.** Participants can tell at a glance whether a submission is uploaded, validating, valid, active, invalid, or locked, and what a deadline means in their timezone.
5. **Approachable for beginners, deep for experts.** One file, one rule set, plain-language onboarding, and useful rejection reasons, without limiting the strategy a strong team can build.

## Accessibility & Inclusion
No formal standard (for example WCAG level) has been chosen (`[DECIDE]`). Product-specific needs stated in the docs: plain-language onboarding that explains the one-file contract, actionable validation and permission errors, deadlines with timezone, clearly distinguished states, and confirmation steps on destructive actions. The audience includes beginners and AI-assisted developers, so explanations must not assume prior Battlecode knowledge.
