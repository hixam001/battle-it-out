# Battle It Out --- User Guide (Participants and Organizers)

**Version:** 1.0\
**Date:** 2026-11-24\
**Audience:** competitors and tournament organizers. The platform's Admin has a separate guide: [`ADMIN_GUIDE.md`](ADMIN_GUIDE.md).

> **Read this first: the website does not exist yet.** This guide describes how the platform is **planned** to work, based on the requirement documents (`PRD.md`, `SRD.md`, `APP_FLOW.md`, `API_CONTRACT.md`). Screen names, wording and details may change when the website is built. Items marked **`[DECIDE]`** are not decided yet; the guide says what is currently recommended and does not promise it. Section 2.9 is the only part you can try today.

## 1. The competition in one page

- You compete in a team. Your team submits **one Python file named `bot.py`**. The platform runs your bot against other teams' bots in the **Battlecode 2026** game engine.
- The tournament is **single elimination**: lose a match and you are out. Matches run one after another, round by round. An Organizer starts each round.
- If a round has an odd number of teams, someone gets an automatic **bye** (advances without playing). Human teams get bye priority over **house bots** (platform-provided bots that fill gaps; they can never advance past a human team or win the tournament).
- Everyone who is registered can see results, the bracket, and replays (until the tournament is archived). Nobody can see another team's source code.

## 2. For participants

### 2.1 Registering

You can register only if you are on the **official roster** and have an **invitation code**.

1. Open the registration page and enter your **official roster email**, your **invitation code**, and a password.
2. Check your email and **verify** your address.
3. When registration completes, your **email, team assignment, member number, and role are locked** and cannot be changed by you or by an Organizer.

Good to know:

- A wrong email or wrong code **does not use up** your code and does not lock you out. Correct it and try again. The system may slow down repeated failures to prevent abuse.
- Codes are single-use and expire when registration closes. If the Admin extends registration, unused codes stay valid until the new deadline.
- If you do not finish signup, email verification, and code validation by the registration deadline, you are **excluded** from the tournament.
- If your code is lost or compromised, ask the Admin; **only the Admin** can revoke it and issue a replacement. How to contact them is `[DECIDE]` (support route not defined yet).
- Code granularity (one per participant, recommended, or one per team) is `[DECIDE]`.

### 2.2 Your team

Your dashboard shows your team's roster, status (active, eliminated, archived), submissions, matches, and notifications. Whether only a **team captain** can upload the bot, and how teams are sized and captains chosen, is `[DECIDE]` (captain-only upload is recommended; all members can see the history).

### 2.3 Submitting your bot

**The contract** (confirmed):

- Python only. Exactly **one file, named exactly `bot.py`**. No ZIP, no extra files.
- You cannot install packages. All bots run in the same prepared environment.
- Your bot needs a top-level function `turn()` that is called on each of your robot's turns.

**What a bot may import.** With the engine as it behaves today, a bot can import only the **Battlecode module** (`battlecode26`) and `random`, `math`, and `enum`. Other imports fail. The project documents say "standard library and preinstalled libraries", so this rule may change; the final list will be published before the tournament (`[DECIDE]`). Until then, do not assume other libraries work.

**Uploading:**

1. Open your team's submission page and choose `bot.py`.
2. The platform checks the file name, size, and your deadline, then validates the bot (syntax, imports, entry point, and whether it runs).
3. You see the result right away, with a reason if it failed.

**Version states you will see:**

| State | Meaning |
|---|---|
| Uploaded / validating | Received; checks are running |
| Valid / **active** | Passed; this version will be used in matches |
| Invalid | Rejected, with a reason. It stays in your history but never replaces your active version |
| Locked | The submission deadline passed; uploads are closed |

Rules you can rely on:

- **The latest valid upload becomes active.** If a newer upload is invalid, your previous valid version **stays active**.
- You can upload again before the deadline (an upload rate limit may apply: the API contract lists `429 RATE_LIMITED`; its value is not defined). Every version and its validation result stays in your history, and you can view and download your own files.
- Each match records the exact version it used. If you upload while a match is starting, that match uses the version that was already active.
- If the validation service itself has a problem, you will see an infrastructure error, not "invalid". Your bot is not at fault; try again.
- The submission deadline is shown **with a timezone**. The Admin may extend it, which reopens uploads and notifies you. If your upload is accepted before the deadline but validation finishes after it, the recommended rule is that the upload time counts (`[DECIDE]`).
- Who can read your code: you, your team, and the Organizers of your tournament (read and download only; they cannot change it). Other teams cannot.

### 2.4 Matches and results

- **Order:** matches run sequentially. You do not start them; an Organizer starts each round.
- **Winning and losing:** the game engine decides the winner.
- **Your bot fails:** if your bot **crashes**, **times out**, or **breaks a resource limit**, it loses automatically and your opponent advances. There is **no rematch**. The numeric limits are fixed for the whole platform and will be published once benchmarked (`[DECIDE]`).
- **The platform fails:** if the engine or the platform breaks, that is **not your loss**. The match restarts from the beginning on the **same map with the same bot versions and a new random seed**, up to a fixed retry cap (10; whether that is 10 total attempts or 10 retries is `[DECIDE]`), then an Admin is alerted.
- **Ties:** a normal match tie is settled by one predefined **tie-break map**. A final that ties plays **three** tie-break maps in order. If it is still tied, a **50/50 digital coin flip** decides; it is shown publicly to registered users and logged. There are no rerolls. If a qualification cutoff is tied, an automatic random draw among the tied teams fills the remaining slots; the tied teams and slots are shown first.
- **Where to look:** the bracket and results page shows scores, tie-break details, and advancement. Each match page links to its replay.

### 2.5 Replays

Every match produces a replay. You can watch or download it while the tournament is active. When the tournament is **archived**, replay files are deleted for everyone, Admins included, and cannot be recovered; results, brackets, standings and match history remain visible to signed-in users. Live viewing during matches is not planned for the first release (`[DECIDE]`).

### 2.6 Notifications

You always get **dashboard notifications** for major events: announcements, deadline changes, validation outcomes, match results, qualification, and elimination. **Email** copies are optional: you can switch email off in account settings; dashboard notifications cannot be switched off.

### 2.7 Deleting your account

You can request deletion in account settings. If your team is still competing, the request is **queued** and carried out after your team is eliminated or the tournament ends; you can **cancel** it until then. After deletion you are removed from historical team rosters entirely (no placeholder), while match results, scores, brackets, and standings stay unchanged. If you were captain, captaincy passes to the next eligible member; what happens when nobody is eligible is `[DECIDE]`.

### 2.8 Troubleshooting

| Problem | What to do |
|---|---|
| "Email not on roster" or invalid code | Check the exact official email and code and try again; your code is not used up. Still failing: contact an Organizer or Admin to correct the roster entry or reissue the code |
| Registration closed | New registrations are blocked after the deadline; ask the Admin about an extension |
| Upload rejected | Read the reason shown. Common causes: file not named `bot.py`, not Python, syntax error, missing `turn()`, import not allowed, file too large (limit is `[DECIDE]`) |
| Upload after the deadline | Closed unless the Admin extends it |
| My newer upload did not become active | It was invalid; your earlier valid version is still active. Check the validation result |
| Replay link unavailable | Either the tournament was archived (permanent), or the replay is still processing, or something failed; staff are alerted if it is missing before archive |
| I cannot see another team's code | By design |

### 2.9 Try your bot locally today (developer view)

Nothing on this page needs the website. If you can run the Battlecode scaffold, you can write and test a bot locally.

- The example Python bot is at `backend/battlecode26-scaffold/src/examplefuncsplayer_py/bot.py`. It shows the `turn()` function, the `rc` robot controller, `Direction`, and `log(...)`.
- `run.py verify --p1 <team>` only checks that `src/<team>/bot.py` exists and contains `def turn():`. It does **not** check syntax or imports, so it does not predict whether the platform will accept your bot.
- Running a **Python-bot match** locally was **not reproducible** in testing on 2026-11-24, so it is not described here as working. The verified local run is Java versus Java. Details and current status are in [`TECHNICAL_DOCUMENTATION.md`](TECHNICAL_DOCUMENTATION.md) section 3.
- For game rules and the full robot API, use the official Battlecode 2026 documentation: `https://play.battlecode.org/bc26/quick_start`.

## 3. For organizers

An Organizer works **only in assigned tournaments**. Anything not listed here is an Admin action.

### 3.1 Create and get a tournament approved

1. Create a **draft**: name, description, and **independent registration and submission deadlines**.
2. **Submit for approval.** An Organizer's tournament cannot be published or open for registration until the Admin approves it.
3. If **rejected**, read the reason (the Admin must give one), edit the draft, and resubmit.
4. Once approved, you can edit permitted settings **until the relevant deadline** without another approval. After a deadline passes, ordinary changes need the Admin to extend that deadline first; an Admin can also make an emergency override with a recorded reason.
5. Whether registration opens manually or on a schedule is `[DECIDE]`.

### 3.2 Roster and invitation codes

- Import the official roster (file format `[DECIDE]`), review the import summary, and correct rows **before** those participants register. After a participant registers, their email, team, member number and role are locked.
- Issue invitation codes for eligible roster entries. Code values are shown only when issued, so deliver them securely.
- You **cannot** revoke or replace a code. If one is lost or compromised, ask the Admin.

### 3.3 Run the tournament

1. Generate the bracket (single elimination, random pairings, automatic byes; house-bot placement rules are `[DECIDE]`).
2. Check round readiness: eligible teams, active bot versions, maps. If something is missing, the round will not start and tells you why.
3. **Start the round.** Matches then run in order, results record automatically, and winners advance. Pressing start twice does not duplicate matches.
4. When every match in the round is done, review the summary and start the next round.
5. If a match is stuck after repeated platform failures, the Admin is alerted and the match pauses. What you can do at that point is `[DECIDE]`.

### 3.4 Source code and teams

- You can **view and download** the source of teams in your tournament, for example to investigate a dispute. You **cannot** upload, edit, delete, or activate a team's submission.
- After the tournament is **archived**, you can delete a team with a confirmation and a **mandatory reason**; only the Admin can restore a deleted team.
- You can view the **audit log** for your tournaments (sensitive personal data is hidden).

### 3.5 What an Organizer cannot do

Approve or reject tournaments, extend a deadline, perform an emergency override, revoke or replace invitation codes, change a registered participant's locked details, change submissions, restore deleted teams, permanently delete a tournament, or open another Organizer's tournament.

## 4. Glossary

| Term | Meaning |
|---|---|
| Active submission | The valid `bot.py` version the platform will use in matches |
| Bye | A free advance when a round has an odd number of teams |
| House bot | A platform bot that fills bracket gaps; never advances past a human team or wins |
| Bot failure | Your bot crashed, timed out, or exceeded a limit: automatic loss, no rematch |
| Platform failure | Engine or infrastructure problem: the match is restarted with the same map and bots and a new seed |
| Tie-break map | A predefined map used to settle a tie: one for normal matches, three for finals |
| Coin flip | Final automatic 50/50 decision, public and logged, no rerolls |
| Archive | Closing a finished tournament: replays are deleted, results stay |
| Seed | The random number that starts a match; a new one is used on platform retries |

## 5. Getting help

A support contact, a status page, and an account-recovery flow are not defined yet (`[DECIDE]`, DEC-13). Until they exist, contact the tournament Organizer or the project owner.
