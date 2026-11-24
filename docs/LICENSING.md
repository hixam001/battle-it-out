# Licensing

Status: policy adopted 2026-11-24 on the owner's instruction (CN-003 in [`CHANGE_NOTICES.md`](CHANGE_NOTICES.md)): the project uses the same license as the Battlecode scaffold it is built on, and aims to comply with the Battlecode licenses. **This file records facts and obligations as read from the sources; it is not legal advice.** Have someone qualified review it before the platform is published or served.

## 1. What the Battlecode components declare (checked 2026-11-24)

See [`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md) for the full table. Battlecode is **not** under one license:

- The **scaffold** is GNU AGPL v3. Its code is in this repository and has been modified here.
- The **Python engine package** declares MIT in its metadata.
- The **Java engine** (the jar that plays the game) declares **no license at all**: the `battlecode/battlecode26` repository has no license file, and the jar, its POM and the README say nothing. Under default copyright rules, no license means no granted rights beyond what the publisher's terms allow. The project only downloads the official release at build time and does not redistribute it.

So "the same license as Battlecode" can only mean AGPL-3.0, the one Battlecode license that governs code we copy and modify.

## 2. The project license

- **AGPL-3.0-only**, full text in the repository root `LICENSE` (identical to the scaffold's). `-only`, not `-or-later`, because the scaffold states version 3 and does not offer later versions.
- Our own source files carry `# SPDX-License-Identifier: AGPL-3.0-only`.
- **Not decided here:** the copyright holder (the author, INNOFEST, or a university). No copyright line was written into any file. Decide it before first publication.

## 3. What AGPL-3.0 asks of this project (summary of the license text)

| Obligation | What it means here |
|---|---|
| Keep the license on copies (sections 4, 5) | The scaffold's `LICENSE` stays in `backend/battlecode26-scaffold/`; the root `LICENSE` covers the rest |
| Mark modifications, with a date (section 5a) | Local changes to the scaffold are listed with dates in `backend/README.md`; the one edited scaffold file that can carry a comment (`gradle.properties`) says so. Keep this list current when you touch scaffold files |
| Whole combined work under the AGPL (section 5c) | Backend code that is a work based on the scaffold must be AGPL. Whether the platform's separate services count as one work is a legal question; the simplest safe course is to license everything we write under AGPL-3.0, which is what we do |
| **Offer source to network users (section 13)** | If users interact with a modified version over a network (the planned website and API), they must be offered the corresponding source. Plan a visible "Source" link on the website to the repository (or a tagged copy of the deployed version) |
| Provide source with any distribution (section 6) | Applies if the code is shipped as images, archives or installers |

## 4. Participant bots are not our code

A submitted `bot.py` is the participant's work. It is run by the platform; it is not linked into or distributed with it. The platform needs the participant's permission to store, run, replay and show the bot and its replays, and the PRD has no terms for this yet. **Open:** participant terms (ownership, what the platform may do with submissions and replays, retention); see the retention items in the PRD. The AGPL does not license participants' bots and does not require them to be published.

## 5. Open items for the owner

1. **The Java engine has no declared license.** Ask the Battlecode team (the package metadata lists `battlecode@mit.edu`) for written confirmation that using the official release to host a competition platform is permitted, and under what terms. Until then the risk is unresolved.
2. Copyright holder and whether INNOFEST or the institution must approve AGPL.
3. Participant terms (section 4) and who publishes them.
4. Source-offer link on the website and in the API documentation (section 13), to plan with the website phase.
5. If the platform ever bundles the engine package or jar (container images), add their notices and re-check redistribution terms.
6. Before publishing, ask a qualified person to review this file.
