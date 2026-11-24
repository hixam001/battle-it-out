# registration — official roster, invitation codes, teams (BIO-EPIC-05, CN-020)

A library, no HTTP layer. It answers: who is on the roster, who may register, and which teams and captains exist for
the other libraries (`submission_registry`, `tournament_flow`, `tournaments`). Standard library only; state in one
JSON file with the same lock rules as the other stores (`JsonFileStore`; replace with the database, DEC-11).

```python
from backend.tournaments import tournaments as T
from backend.registration import registration as G

treg = T.Tournaments.at("data/tournaments.json")
reg  = G.Registration.at("data/registration.json", treg)

G.import_roster(reg, admin, "cup1", G.parse_csv(text))        # per-row result, idempotent
codes = G.issue_codes(reg, organizer, "cup1")                 # plaintext codes are returned once; deliver them now
G.claim(reg, "cup1", email, code, user_id, source=client_ip)  # right pair: consumes the code, locks the entry
G.confirm_email(reg, "cup1", user_id)                         # after the email is verified: registered
actor = G.actor_for(reg, user_id)                             # registry.Actor with teams, captain_of, tournaments
G.registered_teams(reg, "cup1")                               # for scheduler.tick(teams_of=...)
```

| Function | Who | What |
|---|---|---|
| `parse_csv`, `import_roster`, `correct_entry`, `list_roster` | Admin, assigned Organizer | roster rows; a registered entry is locked |
| `issue_codes` | Admin, assigned Organizer | first code per entry; plaintext returned once, hash stored |
| `revoke_code`, `replace_code` | Admin only | `confirm` + reason + audit |
| `claim`, `confirm_email` | the participant (via the account layer) | wrong pair consumes nothing; failures are limited per email and source and only wait |
| `actor_for`, `memberships`, `registered_teams`, `team_view` | other libraries, the team, staff | no emails in `team_view` |
| `report`, `list_codes` | staff | counts, teams that cannot upload, excluded entries, code states (never secrets) |
| `purge_tournament` | Admin | personal data of a deleted tournament |

Errors: `Invalid` (400/422), `Mismatch` (422, same text for every wrong pair), `NotFound` (404), `Forbidden` (403),
`Conflict` / `Locked` / `DeadlineLocked` / `AlreadyRegistered` / `CodeUnavailable` (409), `Closed` (410),
`RateLimited` (429, `retry_after`).

Decisions and limits: `docs/CHANGE_NOTICES.md` CN-020. Interim numbers: 2000 entries, 10 members per team, 10 failures
per email and 40 per source per 15 minutes. Not built: API, account and email layer, delivery of codes, notifications,
captain transfer and account deletion, an Admin exception for a locked entry.

    python3 -m unittest backend.registration.tests.test_registration -v
