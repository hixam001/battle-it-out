# Battle It Out --- User Guide

**Version:** 1.1\
**Date:** 2026-11-26\
**Audience:** Participants and tournament Organizers. See the [Admin guide](ADMIN_GUIDE.md)
for administrative procedures.

## 1. Sign in and find your tournament

Open **Sign in** from the landing page and enter the username and password
provided through your Organizer. The dashboard opens after you sign in.
The current console uses
operator-provisioned accounts linked to verified roster entries or assigned
Organizer accounts. Ask your Organizer for access, password help or a roster
correction. Public signup, password recovery and account deletion are planned
account features.

Choose your tournament from **Tournament**. You can see only the tournaments
where your registration or assignment grants access. **Dashboard** shows the
tournament status, registration and submission deadlines in your browser's
timezone, and recent personal notices. If the expected tournament is missing,
ask the Organizer to confirm your account and current roster or assignment.

## 2. Submit and validate a bot

1. Open **My team** to see your verified roster and bracket standing for the
   selected tournament. Open **Bot submissions** to view your team's versions.
   The upload form appears for your team captain while submissions are open.
2. Choose a UTF-8 `bot.py` or a flat Python ZIP with `bot.py` as its entry point.
   Define a top-level `turn()` function taking no arguments. Keep any other
   modules at the archive root and use flat imports. The interim ceiling is
   256 KiB expanded and 32 input files for a bundle.
3. For dependencies, use an exact version shown under **Curated dependencies**
   in a root `requirements.json`. The standard engine-derived import policy
   includes `battlecode26`, `random`, `math` and `enum`. The tournament runtime
   uses the approved dependency catalogue. See the [bot policy](BOT_POLICY.md)
   and [bundle contract](../backend/submission_bundle/README.md).
4. Select **Upload for validation** before the deadline. The worker checks the
   exact uploaded version. Select **Refresh submissions** to load the latest
   deadline and verdicts. Expand a version's validation status in
   **Submission history** for specific findings.
5. Your latest valid upload becomes active. A newer rejected or inconclusive
   upload leaves your earlier valid version active. A completed draw pins the
   versions used by tournament games.

Registered team members can read their team's submission history and download its
files. Assigned Organizers and Admins have audited source access. Ask the
Organizer for help with a permission error. Other teams' source stays private.

## 3. Follow games and request review

- **Match room** shows recorded matches and private live numeric boards when
  board data is available. It marks delayed or unavailable board data. Live
  access depends on current tournament scope and ends on archive.
- **Analytics** reports completed matches, team performance, byes, tie-break
  outcomes, version data and platform failures. Authorized users can download
  the team CSV.
- **Match disputes** lets members of a participating team select a recorded
  match, describe what staff should review and follow comments. An assigned
  Organizer or Admin reviews and records a resolution. A resolved dispute
  preserves the recorded game result.
- A bot crash, timeout or resource violation forfeits the game. A platform
  failure retries with the same map and pinned bot versions. A retry cap can
  pause the match. Automatic new engine seeds are an open execution requirement.
- Tournament games run sequentially after the Organizer starts the round in the
  existing operations workflow. Normal ties use one tie-break map. Final ties
  use three, followed by a recorded 50/50 coin flip if the tie persists.

Open **Bracket & results** to see round progression, byes and game win counts.
Expand **Maps and tie-break order** for the recorded main-game maps, the
normal tie-break map and the three final tie-break maps in order.
Open a match for its pinned versions, game order, tie-break maps and recorded
coin flip. From **Replay**, download the native `.bc26` file while it is
available and open it in the Battlecode client. Archive removes the download
and retains match history. Browser playback and raw engine point totals
remain open.

From a selected game, open **Structured match log** to view the latest
available attempt or enter an earlier attempt number. Expand events to
read match metadata or your team's output. Assigned Organizers can see
both teams' output. Authorized viewers can still read retained logs after
archive.

## 4. Notifications and account lifecycle

Open **Notifications** to read personal notices, filter to unread, mark a notice
read or unread, or update your email preference. **Account settings** shows
the same email control. The inbox is available to linked participant accounts
and includes past notices. Dashboard notices stay
available when email is disabled. Email delivery depends on the event's provider
configuration. Self-service account requests and deletion are planned.

## 5. For Organizers

Open **Manage tournaments** to see **Recent approval decisions** for
tournaments you created and still manage. Rejection notices include the
recorded reason and link to the tournament settings. Select **Refresh
decisions** after a new review.

Open **Manage tournaments** to list assigned tournaments or create a draft.
Set the registration and submission deadlines in your browser's timezone.
Submit the draft for Admin review. If it is rejected, open the tournament
to read the reason, save revised settings and resubmit. Use **Refresh
tournament** to pick up a decision or reload after an edit conflict. After
approval, select **Open registration** while the deadline is still open.

Open **Post announcement** for a published, unarchived tournament. Review
the selected tournament, enter a headline and a plain-text message, then
publish to its verified roster. The dashboard and queued-email counts
appear after publication.

From an assigned tournament, open **Manage roster** to view registration
counts and the exclusion report. Import a UTF-8 CSV or a JSON file with a
`rows` array. The import receipt identifies rejected rows. Use **Correct**
on an unlocked entry while the tournament accepts roster changes.
For an approved tournament before registration closes, **Issue first
invitation codes** lists eligible roster entries. Select the recipients,
issue the codes and use the one-time receipt for private handoff.

Open **Manage rounds** to select a stored map pool before the submission
deadline and confirm the draw after it passes. The draw pins bot versions.
Confirm **Start round** separately for a ready round. Refresh the controls
for current round state or open **Bracket & results** to review progression.

Use the account assigned to the tournament. **Match room** and **Analytics**
are scoped to that assignment. Open **View teams** from tournament
management to select an official team, review its verified roster and
submission findings, and download its bot. The server records staff
source reads. Captains upload and activate through validation.

Open **Tournament audit log** from management to browse staff activity and
recorded series events for the assigned tournament. Expand a record to see
its available details.

Use **Match disputes** to review comments and record resolutions for assigned
tournaments. An Admin handles approvals, deadline extensions and emergency
overrides. To archive a completed tournament, open it under **Manage
tournaments**, confirm replay removal and select **Archive tournament**.
The receipt reports the replay vault purge state. Results, brackets,
standings and match history stay available to authorized accounts.
Follow the event's authorized
operator process for actions outside the current console.

## 6. Troubleshooting

| Problem | What to do |
| --- | --- |
| Sign-in failed or tournament missing | Confirm the provisioned account and current scope with your Organizer. |
| Upload rejected | Read the returned reason. Check the entry filename, syntax, imports and limits, then retry before the deadline. |
| Upload deadline passed | Ask the Organizer to raise a deadline request with the Admin. |
| Validation still pending | Refresh submission history. Ask your Organizer to check the worker if it stays pending. |
| A newer upload did not become active | Check its verdict and the current active version under **Submission history**. |
| Match or board unavailable | Confirm scope and tournament state. If the match has stalled, give the Organizer the match ID and time. |

## 7. Try a bot locally

The example bot is in [examplefuncsplayer_py](../backend/battlecode26-scaffold/src/examplefuncsplayer_py/bot.py).
It shows `turn()`, the `rc` controller, `Direction` and `log(...)`. Use the
[project match launcher](../backend/match_runner/README.md) for local Python
matches. It uses the project's pinned engine and sandbox. A local match and
static checks can help you debug before submitting. The tournament worker still
checks the exact uploaded version.

For game rules and the robot API, see the [Battlecode 2026 quick start](https://play.battlecode.org/bc26/quick_start).
