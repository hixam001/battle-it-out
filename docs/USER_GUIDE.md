# Battle It Out --- User Guide

**Version:** 1.1\
**Date:** 2026-11-26\
**Audience:** Participants and tournament Organizers. See the [Admin guide](ADMIN_GUIDE.md)
for administrative procedures.

## 1. Sign in and find your tournament

Open **Competition console** from the landing page. Sign in with the username
and password provided through your Organizer. The current console uses
operator-provisioned accounts linked to verified roster entries or assigned
Organizer accounts. Ask your Organizer for access, password help or a roster
correction. Public signup, password recovery and account deletion are planned
account features.

Choose your tournament from **Tournament**. You can see only the tournaments
where your registration or assignment grants access. The console displays the
submission deadline with the browser timezone. If the expected tournament is
missing, ask the Organizer to confirm your account and current roster or
assignment.

## 2. Submit and validate a bot

1. Open **Bot submissions**, confirm the tournament and enter your registered
   **Team ID**. Under the current captain-only rule, your team captain uploads.
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
   exact uploaded version. Reopen **Bot submissions** or refresh the page to
   read the result in **Submission history**. Rejected and inconclusive
   attempts remain in history.
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

Stored replay files are purged at archive. A browser replay player, a complete
bracket and a match-history screen are still planned console features.

## 4. Notifications and account lifecycle

Dashboard notifications are independent of optional email. The current
[notification API](API_CONTRACT.md)
supports personal notices, read/unread and email preferences for an explicitly
linked participant account. Email delivery depends on the event's provider
configuration. Contact the Organizer for notices in the current event workflow.
Self-service account requests and deletion are planned.

## 5. For Organizers

Use the account assigned to the tournament. **Match room** and **Analytics** are
scoped to that assignment. In **Bot submissions**, use the team's registered
ID to review its versions or download its submission. Captains upload and
activate through validation. Organizer source access is read-only.

Use **Match disputes** to review comments and record resolutions for assigned
tournaments. An Admin handles approvals, deadline extensions and emergency
overrides. Roster import and corrections, invitation issuance, round starts
and archive are available through the underlying tournament workflow. Dedicated
Organizer screens for these operations are planned. Follow the event's
authorized operator process for actions outside the current console.

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
