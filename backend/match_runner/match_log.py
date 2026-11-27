# SPDX-License-Identifier: AGPL-3.0-only
"""Structured match logs (BIO-206).

One match attempt produces one list of events. Each event is one JSON object per line in a `.jsonl`
file and carries a **visibility** that says who may read it:

    all       both teams, organizers and admins (the public summary of the match)
    team:A    team A's members, organizers and admins  (that team's own output, usage and failure detail)
    team:B    the same for team B
    staff     admins only (platform diagnostics: exit statuses, router evidence, engine lines)

`view(events, role, team)` is the only place that decides who sees what, so the future API
(`GET /matches/{id}/logs`) calls it and nothing else. Which roles see which visibilities is the
engineer's default under the owner's delegation (docs/CHANGE_NOTICES.md CN-007) and is reversible.

Trust: bot-written text reaches the log only through the engine's own `log(...)` output. The router
rewrites every line break in that text (sandbox.py `sanitise_text`), so a line that starts with
`[A: #3@2] ` is the engine writing for robot 3 of team A and a line that starts with `[server` is the
engine itself. A bot cannot start a line of either kind. That is what `parse_server_log` relies on.

Redaction (`Redactor`) is best effort: known host paths, home directories, e-mail addresses, IP
addresses, bearer/JWT/well-known tokens, `password=...` style pairs and long mixed tokens. It is a
second line of defence for BIO-NFR-10, not a proof that nothing sensitive can appear.

Standard library only.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from pathlib import Path

SCHEMA = 1
VISIBILITIES = ("all", "team:A", "team:B", "staff")
ROLES = ("participant", "organizer", "admin")

# Output caps. Everything a bot can influence is bounded before it is stored.
MAX_OUTPUT_ENTRIES = 40        # first N and last N log entries per team
MAX_ENTRY_CHARS = 500
MAX_ENTRY_LINES = 20
MAX_SERVER_LINES = 60

BOT_LINE = re.compile(r"^\[(A|B): #(\d+)@(\d+)\] ?(.*)$")
SERVER_LINE = re.compile(r"^\[server(?::(?:warning|error))?\]")
FINISHED_LINE = re.compile(r"^\[server\] -+ Match Finished -+\s*$")
REF_RE = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")


def new_trace_id() -> str:
    return uuid.uuid4().hex


def check_ref(value: str | None, what: str) -> str | None:
    """Opaque identifiers from the caller (match, trace, submission): short, no spaces or control characters."""
    if value is None:
        return None
    if not REF_RE.match(value):
        raise ValueError(f"{what} must match {REF_RE.pattern}")
    return value


# ------------------------------------------------------------------------------------------
# redaction
# ------------------------------------------------------------------------------------------
_KEY_VALUE = re.compile(
    r"(?i)\b(pass(?:word|wd)?|pwd|secret|token|api[_-]?key|authorization|auth|cookie|session(?:id)?|credential)"
    r"(\s*[=:]\s*)(\S+)")
_BEARER = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}")
_KNOWN_TOKENS = re.compile(
    r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9_-]{20,}|xox[abprs]-[A-Za-z0-9-]{10,}"
    r"|eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,})\b")
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+\b")
_IPV4 = re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b")
_HOME = re.compile(r"(?:/home|/Users)/[^/\s:'\"]+|/root\b")
_LONG_TOKEN = re.compile(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{40,}(?![A-Za-z0-9_-])")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def _looks_like_secret(token: str) -> bool:
    has_digit = any(c.isdigit() for c in token)
    has_upper = any(c.isupper() for c in token)
    has_lower = any(c.islower() for c in token)
    return has_digit and (has_upper or has_lower)


class Redactor:
    """Replace host details and secret-looking text. `paths` maps a placeholder name to a real path."""

    def __init__(self, paths: dict[str, str | Path] | None = None):
        items = [(name, str(p).rstrip("/")) for name, p in (paths or {}).items() if p and str(p) not in ("", "/")]
        self._paths = sorted(items, key=lambda kv: len(kv[1]), reverse=True)   # longest first

    def __call__(self, text: str) -> str:
        text = _CONTROL.sub("", text)
        for name, real in self._paths:
            text = text.replace(real, f"<{name}>")
        text = _HOME.sub("<home>", text)
        text = _BEARER.sub(lambda m: f"{m.group(1)} <redacted>", text)
        text = _KEY_VALUE.sub(lambda m: f"{m.group(1)}{m.group(2)}<redacted>", text)
        text = _KNOWN_TOKENS.sub("<redacted-token>", text)
        text = _EMAIL.sub("<email>", text)
        text = _IPV4.sub(lambda m: m.group(0) if m.group(0) == "127.0.0.1" else "<ip>", text)
        text = _LONG_TOKEN.sub(lambda m: "<redacted-token>" if _looks_like_secret(m.group(0)) else m.group(0), text)
        return text


def _num(x):
    """A finite number or None. Guard records come from a log a bot can write to: never copy other types."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return x if x == x and x not in (float("inf"), float("-inf")) else None


_IDENT = re.compile(r"^[a-z][a-z0-9_]{0,39}$")


def _ident(x, default: str = "unknown") -> str:
    return x if isinstance(x, str) and _IDENT.match(x) else default


def _clip(text: str, limit: int = MAX_ENTRY_CHARS) -> str:
    return text if len(text) <= limit else text[:limit] + "...[truncated]"


# ------------------------------------------------------------------------------------------
# reading the engine's log
# ------------------------------------------------------------------------------------------
def parse_server_log(text: str) -> dict:
    """Split the engine's console output into per-team bot entries and engine lines.

    Only the part up to the engine's end-of-match banner is read (what follows is Gradle's own output).
    A line that is not an entry start continues the previous entry; this is safe because bot text cannot
    begin a line (see the module docstring).
    """
    teams: dict[str, list[dict]] = {"A": [], "B": []}
    server: list[str] = []
    current: dict | None = None        # {"kind": "bot"|"server", ...}
    for line in text.splitlines():
        m = BOT_LINE.match(line)
        if m:
            current = {"kind": "bot", "team": m.group(1), "robot": int(m.group(2)),
                       "round": int(m.group(3)), "lines": [m.group(4)]}
            teams[m.group(1)].append(current)
            continue
        if SERVER_LINE.match(line):
            current = {"kind": "server", "lines": [line]}
            server.append(current)
            if FINISHED_LINE.match(line):
                break
            continue
        if current is not None and len(current["lines"]) <= MAX_ENTRY_LINES:   # keeps one extra: "truncated"
            current["lines"].append(line)
    return {
        "teams": {t: [{"robot": e["robot"], "round": e["round"], "lines": e["lines"]} for e in es]
                  for t, es in teams.items()},
        "server_lines": ["\n".join(e["lines"]) for e in server],
    }


def _entry_text(entry: dict, redact: Redactor) -> dict:
    lines = [redact(ln) for ln in entry["lines"][:MAX_ENTRY_LINES]]
    text = _clip("\n".join(lines))
    return {"round": entry["round"], "robot": entry["robot"], "text": text,
            "truncated": len(entry["lines"]) > MAX_ENTRY_LINES or text.endswith("[truncated]")}


def _team_output(entries: list[dict], redact: Redactor) -> dict:
    total = len(entries)
    if total <= 2 * MAX_OUTPUT_ENTRIES:
        shown = entries
        omitted = 0
    else:
        shown = entries[:MAX_OUTPUT_ENTRIES] + entries[-MAX_OUTPUT_ENTRIES:]
        omitted = total - len(shown)
    return {"entries_total": total, "entries_omitted_in_middle": omitted,
            "entries": [_entry_text(e, redact) for e in shown],
            "note": "text written by your bot (and engine error messages about it); the middle is omitted when long"}


# ------------------------------------------------------------------------------------------
# building the events
# ------------------------------------------------------------------------------------------
_CRASH_PUBLIC = {   # fixed wording per kind: nothing a bot wrote ever reaches these lines
    "runner_ended_connection": "ended during the match",
    "runner_unresponsive": "stopped responding during the match",
    "protocol_violation": "sent the engine a message the protocol does not allow",
}
_CRASH_OWN = {
    "runner_ended_connection": "ended the connection to the engine before the match finished",
    "runner_unresponsive": "stopped responding to the engine for too long",
    "protocol_violation": "sent the engine a message that the protocol does not allow at that moment",
}


def _public_reason(result: dict, names: dict) -> str:
    """Text for the match summary that every reader sees. Never contains bot-written text."""
    c = result.get("classification")
    if c == "normal":
        return result.get("reason") or "match finished"
    if c == "bot_violation":
        v = result.get("violation") or {}
        kind = _ident(v.get("kind"))
        return f"team {v.get('team')} ({names.get(v.get('team'), '?')}) forfeited: resource limit exceeded ({kind})"
    if c == "bot_crash":
        what = _CRASH_PUBLIC.get(result.get("kind"), _CRASH_PUBLIC["runner_ended_connection"])
        return f"team {result.get('loser')} ({names.get(result.get('loser'), '?')}) forfeited: its bot process {what}"
    return "platform failure: the match did not complete because of a platform fault; no result"


def build_events(result: dict, ctx: dict, server_log_text: str, redact: Redactor | None = None) -> list[dict]:
    """Turn one finished attempt into the list of log events.

    `ctx`: trace_id, match_id (or None), attempt, teams {A,B names}, submissions {A,B refs or None}, map,
    engine_version, started_at, finished_at, limits (dict or None), limits_profile (name or None).
    `result`: the launcher's result dictionary.
    """
    redact = redact or Redactor()
    names = ctx["teams"]
    events: list[dict] = []

    def add(event: str, visibility: str, data: dict, ts: str | None = None) -> None:
        assert visibility in VISIBILITIES
        e = {"schema": SCHEMA, "seq": len(events), "trace_id": ctx["trace_id"], "match_id": ctx.get("match_id"),
             "attempt": ctx["attempt"], "event": event, "visibility": visibility}
        if ts:
            e["ts"] = ts
        e["data"] = data
        events.append(e)

    parsed = parse_server_log(server_log_text)
    classification = result.get("classification")

    add("match.start", "all", {
        "map": ctx["map"],
        "teams": {s: {"name": names[s], "submission": (ctx.get("submissions") or {}).get(s)} for s in "AB"},
        "engine_version": ctx["engine_version"],
        "runtime": {"python": result.get("python")},
        "seed": None,
        "seed_note": "the engine's tie-break seed cannot be set or read (docs/TECHNICAL_DOCUMENTATION.md section 3.6)",
        "limits": ctx.get("limits"),
        "limits_profile": {"name": ctx.get("limits_profile"), "approved": False},
    }, ts=ctx["started_at"])

    teams_usage = ((result.get("usage") or {}).get("teams")) or {}
    for side in "AB":
        u = teams_usage.get(side)
        if u:
            add("team.usage", f"team:{side}", {
                "team": side, "turns": _num(u.get("turns")), "inits": _num(u.get("inits")),
                "longest_turn_ms": round(1000 * (_num(u.get("max_turn_seconds")) or 0), 2),
                "longest_init_ms": round(1000 * (_num(u.get("max_init_seconds")) or 0), 2),
                "total_turn_ms": round(1000 * (_num(u.get("total_turn_seconds")) or 0), 1),
                "uncaught_exceptions": _num(u.get("exceptions")),
                "game_action_exceptions": _num(u.get("game_action_exceptions")),
            })
        add("team.output", f"team:{side}", {"team": side, **_team_output(parsed["teams"][side], redact)})

    loser = result.get("loser")
    if classification == "bot_violation":
        v = result.get("violation") or {}
        add("team.failure", f"team:{loser}", {
            "team": loser, "cause": "limit_exceeded", "kind": _ident(v.get("kind")),
            "measured": _num(v.get("measured")), "limit": _num(v.get("limit")),
            "unit": _ident(v.get("unit"), "") or None, "round": _num(v.get("round")),
        })
    elif classification == "bot_crash":
        add("team.failure", f"team:{loser}", {
            "team": loser, "cause": "process_ended",
            "detail": "your bot's process " + _CRASH_OWN.get(result.get("kind"), _CRASH_OWN["runner_ended_connection"]),
        })

    winner = result.get("winner")
    add("match.result", "all", {
        "outcome": result.get("outcome"),
        "classification": classification,
        "winner": {"side": winner, "name": names.get(winner)} if winner else None,
        "loser": {"side": loser, "name": names.get(loser)} if loser else None,
        "round": result.get("round"),
        "reason": _public_reason(result, names),
        "retryable": classification == "platform_failure",
        "replay_available": bool(result.get("replay")),
    })

    ev = result.get("evidence") or {}
    add("platform.diagnostics", "staff", {
        "classification_kind": result.get("kind"),
        "classification_detail": redact(str(result.get("detail") or "")),
        "evidence": ev,
        "gradle_exit": result.get("gradle_exit"),
        "runner_exit": result.get("runner_exit"),
        "runner_exit_early": result.get("runner_exit_early"),
        "timed_out": result.get("timed_out"),
        "router": result.get("router"),
        "sandbox": result.get("sandbox"),
        "cgroup": result.get("cgroup"),
        "process_usage": {s: {k: _num(v) for k, v in (u or {}).items() if k != "teams" and _num(v) is not None}
                          for s, u in ((result.get("usage") or {}).get("processes") or {}).items()},
        "seconds": result.get("seconds"),
        "rounds_per_second": result.get("rounds_per_second"),
        "replay": {"bytes": result.get("replay_bytes"), "sha256": result.get("replay_sha256")},
        "server_errors": [_clip(redact(e)) for e in (result.get("server_errors") or [])][:20],
        "engine_lines": [_clip(redact(ln)) for ln in parsed["server_lines"][:MAX_SERVER_LINES]],
        "rewritten_texts": ((result.get("router") or {}).get("text_rewrites")),
    })

    add("match.end", "all", {"events": len(events) + 1}, ts=ctx["finished_at"])
    return events


# ------------------------------------------------------------------------------------------
# who sees what
# ------------------------------------------------------------------------------------------
def visibilities_for(role: str, team: str | None = None) -> set[str]:
    """Participant: the summary plus their own team. Organizer: summary plus both teams. Admin: everything."""
    if role == "participant":
        if team not in ("A", "B"):
            raise ValueError("a participant view needs the reader's team (A or B)")
        return {"all", f"team:{team}"}
    if role == "organizer":
        return {"all", "team:A", "team:B"}
    if role == "admin":
        return set(VISIBILITIES)
    raise ValueError(f"unknown role {role!r}; expected one of {ROLES}")


def view(events: list[dict], role: str, team: str | None = None) -> list[dict]:
    allowed = visibilities_for(role, team)
    return [e for e in events if e["visibility"] in allowed]


# ------------------------------------------------------------------------------------------
# files
# ------------------------------------------------------------------------------------------
def write_jsonl(path: Path, events: list[dict]) -> dict:
    body = "".join(json.dumps(e, sort_keys=False, separators=(",", ":")) + "\n" for e in events).encode("utf-8")
    Path(path).write_bytes(body)
    return {"path": str(path), "schema": SCHEMA, "events": len(events), "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest()}


def parse_jsonl(text: str, *, source: str = "match log") -> list[dict]:
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            e = json.loads(line)
        except ValueError as exc:
            raise ValueError(f"{source}:{n}: not JSON ({exc})") from exc
        if not isinstance(e, dict) or e.get("schema") != SCHEMA or e.get("visibility") not in VISIBILITIES:
            raise ValueError(f"{source}:{n}: not a schema-{SCHEMA} log event")
        out.append(e)
    return out


def read_jsonl(path: Path) -> list[dict]:
    return parse_jsonl(Path(path).read_text(encoding="utf-8"), source=str(path))
