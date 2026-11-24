# Third-party notices

The project's own code is licensed under the **GNU Affero General Public License v3.0 only** (`LICENSE`, SPDX `AGPL-3.0-only`). This file lists the third-party components it uses and the license each one declares. It reports what each component states about itself (checked 2026-11-24); it is not legal advice. Policy and open questions: [`docs/LICENSING.md`](docs/LICENSING.md).

| Component | Where | License as declared | In this repository? |
|---|---|---|---|
| Battlecode 2026 scaffold (`battlecode/battlecode26-scaffold`, commit `f69e2ab`) | `backend/battlecode26-scaffold/` | GNU AGPL v3 (`backend/battlecode26-scaffold/LICENSE`; GitHub reports `AGPL-3.0`) | Yes, vendored and modified (changes listed in `backend/README.md`) |
| Battlecode 2026 engine, Java (`org.battlecode:battlecode26-java` 1.2.6) | downloaded by Gradle into its cache | **No license declared**: no `LICENSE` file in `battlecode/battlecode26`, none in the jar, POM or README | No |
| Battlecode 2026 engine, Python package (`battlecode26` 1.2.2, the contents of the official 1.2.6 release) | installed into `backend/.venvs/` by `setup_env.py` (SHA-256 checked); cached in `backend/.cache/` | MIT (package metadata, author "Battlecode") | No (git-ignored) |
| Battlecode desktop client | downloaded by `./gradlew build` into `backend/battlecode26-scaffold/client/` | Not checked (no public repository found under `battlecode/battlecode26-client`) | No (git-ignored) |
| RestrictedPython 8.1 | `backend/.venvs/` | ZPL-2.1 | No |
| flatbuffers 24.3.25 | `backend/.venvs/` | Apache-2.0 | No |
| Gradle wrapper (`gradle-wrapper.jar`, Gradle 8.10) | `backend/battlecode26-scaffold/gradle/wrapper/` | Apache-2.0 (Gradle's published license; not re-verified from the file) | Yes (part of the vendored scaffold) |
| bubblewrap (`bwrap`) 0.13.1 | Run as an external program by `backend/match_runner/sandbox.py`; installed from the OS package manager | LGPL-2.1-or-later (package metadata on the development machine) | No (not bundled; if it is ever shipped in an image, follow its license) |
| Libraries shaded into the engine jar (for example Jackson, FastDoubleParser, Java-WebSocket) | inside the engine jar | Their own licenses, shipped inside the jar under `META-INF/` | No |

The MIT license requires its copyright and permission notice to accompany copies of the package. The project does not redistribute the package: it is downloaded from the official release URL at setup time. If it is ever bundled (for example in a container image), include the package's notice.
