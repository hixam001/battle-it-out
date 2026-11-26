# SPDX-License-Identifier: AGPL-3.0-only
"""Upload check for a bot: the static check, then a trial match on both sides (BIO-202, BIO-REQ-04, CN-013).

Standard library only. A library, not a service: nothing calls it yet, there is no upload endpoint and no
storage. It answers one question for the platform: *may this `bot.py` become active?* (SRD-050, SRD-051)

    from backend.submission_check import trial as T
    verdict = T.check_submission(Path("upload/bot.py"), play=T.launcher_play(scaffold, py, out_root,
                                                                           lock_path=Path("host.lock")))
    verdict["status"]            # "valid" | "rejected" | "inconclusive"
    T.may_activate(verdict, sha256_of_the_file_to_activate)

Three outcomes, on purpose:
  * `valid`        static check passed and the bot played a full game on side A and on side B without a bot
                   failure. Winning is not required; a bot that loses to the reference bot is still valid.
  * `rejected`     the participant must change something: the static check failed, or the bot crashed,
                   hung, broke the protocol or breached a limit in the trial. Reasons are actionable.
  * `inconclusive` the platform could not tell (engine failure, busy host, the reference bot failed). The
                   participant is NOT blamed and the file does not become active; check it again later.
"""
from __future__ import annotations

import hashlib
import tempfile
import time
from pathlib import Path
from typing import Callable

from backend.bot_validator import validator as V
from backend.submission_bundle import bundle as BU
from backend.match_orchestrator import orchestrator as O
from backend.match_runner import launcher as L
from backend.match_runner import match_log as log_mod

SCHEMA = "bio.submission-check.v1"
CANDIDATE = "candidate"     # folder names inside the staging directory
REFERENCE = "reference"
DEFAULT_MAP = "DefaultSmall"
DEFAULT_TIMEOUT = 120
# The reference opponent is the scaffold's own example bot, pinned by hash: a changed opponent would change
# what "valid" means, so a mismatch stops the check instead of being played.
REFERENCE_SOURCE = Path("src") / "examplefuncsplayer_py"
REFERENCE_SHA256 = "b221c06c6517c459467c09abfa9ac35b019701dc33f655871f7f320a2c8fa646"
MAX_LOG_ENTRIES = 40

# Fixed wording per cause. Nothing a bot printed ever becomes a reason line; bot output is attached
# separately, as the participant view of the structured log, and labelled as such.
_CRASH_MESSAGES = {
    "runner_ended_connection": "your bot's process ended before the game finished",
    "runner_unresponsive": "your bot stopped answering the engine for too long",
    "protocol_violation": "your bot sent the engine a message the protocol does not allow at that moment",
}


class CheckError(Exception):
    """The check itself could not be run (bad setup). Not a verdict about the bot."""


Play = Callable[[Path, str, str, str], dict]    # (bots_dir, team_a, team_b, map) -> launcher result


def launcher_play(scaffold: Path, py: Path, out_root: Path, *, timeout: int = DEFAULT_TIMEOUT,
                  lock_path: Path, lock_wait: float = 600.0, sandbox: bool = True,
                  limits_path: Path | None = L.DEFAULT_LIMITS, cgroup: bool | None = None) -> Play:
    """The real thing: `backend/match_runner` in the sandbox, one engine match per host at a time.

    A trial uses the same engine port as a tournament match, so it takes the same host lock.
    """
    counter = iter(range(1, 1 << 30))

    def play(bots_dir: Path, team_a: str, team_b: str, map_name: str) -> dict:
        out = Path(out_root) / f"{time.strftime('%Y%m%d-%H%M%S')}-{next(counter)}"
        try:
            with O.host_lock(lock_path, lock_wait):
                return L.run_match(scaffold, py, bots_dir, team_a, team_b, map_name, out, timeout, True, True,
                                   sandbox=sandbox, cgroup=cgroup, limits_path=limits_path)
        except L.PortBusyError as e:
            return {"outcome": "platform_failure", "kind": "port_busy", "detail": str(e)}
        except TimeoutError as e:
            return {"outcome": "platform_failure", "kind": "host_busy", "detail": str(e)}
        except L.LauncherError as e:
            raise CheckError(str(e)) from e
    return play


def _finding(code: str, message: str, line: int | None = None) -> dict:
    return {"code": code, "line": line, "message": message}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_bot_bytes(path: Path) -> bytes | dict:
    """The bytes of `bot.py`, read once, without following links; or a finished refusal."""
    target = path / "bot.py" if path.is_dir() else path
    raw = V._read_regular_file(target)
    return raw


def _reference_bytes(scaffold: Path) -> bytes:
    src = Path(scaffold) / REFERENCE_SOURCE / "bot.py"
    raw = V._read_regular_file(src)
    if isinstance(raw, dict):
        raise CheckError(f"reference bot unreadable: {src}")
    if _sha(raw) != REFERENCE_SHA256:
        raise CheckError("reference bot does not match its pinned hash; refusing to use a different opponent")
    return raw


def _stage(root: Path, name: str, data: bytes) -> None:
    d = root / name
    d.mkdir(mode=0o755)
    f = d / "bot.py"
    f.write_bytes(data)
    f.chmod(0o644)


def _own_output(result: dict, side: str) -> list[dict]:
    """What the participant may read about their own side of a trial game: the redacted structured log."""
    path = result.get("structured_log")
    if not isinstance(path, dict) or not path.get("path"):
        return []
    try:
        events = log_mod.read_jsonl(Path(path["path"]))
        own = [e for e in log_mod.view(events, "participant", team=side) if e.get("visibility") == f"team:{side}"]
    except (OSError, ValueError, KeyError):
        return []
    return own[:MAX_LOG_ENTRIES]


def _judge(result: dict, side: str) -> tuple[str, dict | None]:
    """One trial game -> ("pass" | "reject" | "inconclusive", reason). `side` is the candidate's side."""
    if not isinstance(result, dict):
        return "inconclusive", _finding("T-PLATFORM", "the platform returned no usable result; try again later")
    outcome = result.get("outcome")
    if outcome == "completed":
        if result.get("classification", "normal") != "normal" or not result.get("finished", True):
            return "inconclusive", _finding("T-PLATFORM", "the trial game did not finish cleanly; try again later")
        return "pass", None
    if outcome == "bot_failure":
        loser = result.get("loser")
        if loser != side:                 # the reference bot failed: not the participant's doing
            return "inconclusive", _finding("T-REFERENCE", "the platform's reference bot failed; try again later")
        if result.get("classification") == "bot_violation":
            v = result.get("violation") or {}
            kind = log_mod._ident(v.get("kind"))
            measured, limit = v.get("measured"), v.get("limit")
            extra = f" (measured {measured}, limit {limit} {v.get('unit', '')})".replace(" )", ")") \
                if measured is not None and limit is not None else ""
            return "reject", _finding("T-LIMIT", f"your bot exceeded a resource limit: {kind}{extra}",
                                      v.get("round") if isinstance(v.get("round"), int) else None)
        kind = result.get("kind")
        return "reject", _finding("T-CRASH", _CRASH_MESSAGES.get(kind, _CRASH_MESSAGES["runner_ended_connection"]))
    return "inconclusive", _finding("T-PLATFORM", "the platform could not run the trial game; try again later")


def check_submission(candidate: Path, *, play: Play, scaffold: Path = L.DEFAULT_SCAFFOLD,
                     map_name: str = DEFAULT_MAP, policy: dict | None = None) -> dict:
    """Check one upload. `candidate` is a `bot.py` file or a folder holding only `bot.py`.

    Raises `CheckError` for bad setup (reference bot missing or changed, unusable launcher); never for a bad
    bot. The file is read once: the bytes that were validated are the bytes that were played and hashed.
    """
    candidate = Path(candidate)
    checked_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    verdict: dict = {"schema": SCHEMA, "status": None, "stage": None, "reasons": [], "warnings": [],
                     "sha256": None, "bytes": None, "checked_at": checked_at, "map": map_name,
                     "reference_sha256": REFERENCE_SHA256, "trials": []}

    def done(status: str, stage: str, reasons: list[dict]) -> dict:
        verdict.update(status=status, stage=stage, reasons=reasons)
        return verdict

    bundle_files = None
    if candidate.is_dir() and (candidate / BU.MANIFEST).exists():
        try:
            bundle_files = BU.snapshot(candidate)
        except (BU.Invalid, OSError) as exc:
            return done("rejected", "static", [_finding("S-E-BUNDLE", str(exc))])
        verdict["sha256"], verdict["bytes"] = BU.digest(bundle_files), sum(map(len, bundle_files.values()))
        raw = bundle_files["bot.py"]
    else:
        # 1. static check of the structure, then of the exact bytes we will play
        structure = V.validate_path(candidate, policy)
        verdict["warnings"] = structure.get("warnings", [])
        if not structure["ok"]:
            return done("rejected", "static", [_finding(f"S-{e['code']}", e["message"], e.get("line"))
                                               for e in structure["errors"]])
        raw = _read_bot_bytes(candidate)
        if isinstance(raw, dict):
            return done("rejected", "static", [_finding(f"S-{e['code']}", e["message"]) for e in raw["errors"]])
        verdict["sha256"], verdict["bytes"] = _sha(raw), len(raw)
        try:
            source = raw.decode("utf-8")
        except UnicodeDecodeError:
            return done("rejected", "static", [_finding("S-E-ENCODING", "the file is not valid UTF-8")])
        content = V.validate_source(source, policy)
        verdict["warnings"] = content.get("warnings", [])
        if not content["ok"]:
            return done("rejected", "static", [_finding(f"S-{e['code']}", e["message"], e.get("line"))
                                               for e in content["errors"]])

    # 2. trial games, candidate on side A and then on side B, against the pinned reference bot
    reference = _reference_bytes(scaffold)
    reasons: list[dict] = []
    inconclusive: list[dict] = []
    own_output: dict[str, list[dict]] = {}
    with tempfile.TemporaryDirectory(prefix="bio-trial-") as tmp:
        bots = Path(tmp) / "bots"
        bots.mkdir(mode=0o755)
        _stage(bots, CANDIDATE, raw)
        if bundle_files is not None:
            for name, content in bundle_files.items():
                if name != "bot.py":
                    (bots / CANDIDATE / name).write_bytes(content)
        _stage(bots, REFERENCE, reference)
        for side in ("A", "B"):
            names = (CANDIDATE, REFERENCE) if side == "A" else (REFERENCE, CANDIDATE)
            result = play(bots, names[0], names[1], map_name)
            judgement, reason = _judge(result, side)
            row = {"candidate_side": side, "judgement": judgement}
            if isinstance(result, dict):
                row.update({k: result.get(k) for k in ("outcome", "classification", "round", "seconds")})
            verdict["trials"].append(row)
            if judgement != "pass":
                (reasons if judgement == "reject" else inconclusive).append({**reason, "side": side})
            out = _own_output(result, side) if isinstance(result, dict) else []
            if out:
                own_output[side] = out
    verdict["own_output"] = own_output
    if reasons:                       # a participant fault is reported even if the other game was inconclusive
        return done("rejected", "trial", reasons)
    if inconclusive:
        return done("inconclusive", "trial", inconclusive)
    return done("valid", "trial", [])


def may_activate(verdict: dict, sha256: str) -> bool:
    """SRD-051: only a valid submission may become active, and only the exact file that was checked."""
    return (isinstance(verdict, dict) and verdict.get("schema") == SCHEMA and verdict.get("status") == "valid"
            and not verdict.get("reasons") and isinstance(sha256, str) and sha256 == verdict.get("sha256"))
