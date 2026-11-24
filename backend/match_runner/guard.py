# SPDX-License-Identifier: AGPL-3.0-only
"""Resource guard for the Battlecode Python runner (BIO-204).

Why this exists (found by reading and running the engine package, 2026-11-24):
  * Every robot runs in its own thread inside ONE runner process, for both teams.
  * The runner's main thread waits for a robot's turn with `Event.wait()` and no timeout, and the
    bytecode counter only charges game API calls, so a bot with `while True: pass` hangs the whole
    match forever. Bot top-level code (`init_robot`) is exec()d on the main thread itself.
  * Nothing limits memory.

The guard adds, without editing the installed package:
  * a watchdog thread (not an exception, so bot code cannot catch it) that ends the process with a
    structured violation record when one robot's turn or initialisation exceeds the wall-clock
    limit, or when resident memory exceeds the limit while a robot is running;
  * operating-system rlimits as a backstop (address space, CPU time, open files, file size);
  * usage measurements (per team: turns, longest turn, total turn time; process peak memory and
    threads), so the limits can be benchmarked and approved (PRD BIO-NFR-02, DEC-04).

Records leave the process as single lines on stdout (`BIO-GUARD-VIOLATION {json}` and
`BIO-GUARD-USAGE {json}`), which the launcher reads from the runner log. There is deliberately no
writable state directory in the sandbox: stdout is one size-capped file (RLIMIT_FSIZE).

Limits of this design (see docs/TECHNICAL_DOCUMENTATION.md "Bot execution limits"): the guard lives
in the same process as the bots, so a hostile bot that escapes the language-level restrictions can
tamper with it. The operating-system sandbox (`sandbox.py`) protects the host; separating the two
teams into two processes is the open next step.
"""
from __future__ import annotations

import json
import os
import resource
import threading
import time
from dataclasses import dataclass, fields
from pathlib import Path

EXIT_VIOLATION = 70  # runner exit status when a bot limit was breached (record in violation file)
EXIT_PLATFORM = 71  # runner exit status when a limit was breached while no bot was running

POLL_SECONDS = 0.02
PAGE = os.sysconf("SC_PAGE_SIZE")


@dataclass(frozen=True)
class Limits:
    """One platform-wide profile. Every field is required; there are no hidden defaults."""

    turn_wall_seconds: float      # one robot's turn, wall clock (excludes waiting for the server)
    init_wall_seconds: float      # one robot's start-up (bot module top-level code)
    memory_rss_mb: int            # resident memory of the runner process while a robot is running
    address_space_mb: int         # RLIMIT_AS backstop for the runner process
    cpu_seconds: int              # RLIMIT_CPU backstop for the runner process (whole match)
    open_files: int               # RLIMIT_NOFILE
    output_bytes: int             # RLIMIT_FSIZE: largest file/log the runner may write
    max_tasks: int                # RLIMIT_NPROC (processes + threads), only inside the sandbox's user namespace

    @staticmethod
    def from_dict(d: dict) -> "Limits":
        names = [f.name for f in fields(Limits)]
        missing = [n for n in names if n not in d]
        extra = [k for k in d if k not in names]
        if missing or extra:
            raise ValueError(f"limits profile: missing {missing}, unknown {extra}")
        for n in names:
            v = d[n]
            if isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0:
                raise ValueError(f"limits profile: {n} must be a positive number, got {v!r}")
        return Limits(**{n: d[n] for n in names})


def load_profile(path: Path) -> tuple[Limits, dict]:
    """Return (limits, whole profile document)."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    return Limits.from_dict(doc["limits"]), doc


def rss_bytes() -> int:
    with open("/proc/self/statm", "rb") as f:
        return int(f.read().split()[1]) * PAGE


def apply_rlimits(limits: Limits, in_user_namespace: bool = False) -> None:
    """Apply the operating-system backstops to this process.

    RLIMIT_NPROC counts every process and thread of this user. It is only meaningful inside the
    sandbox's private user namespace (counts start at zero there); on the host it would count all of
    the user's processes, so it is applied only when `in_user_namespace` is true.
    """
    mb = 1 << 20
    if in_user_namespace:
        resource.setrlimit(resource.RLIMIT_NPROC, (int(limits.max_tasks),) * 2)
    resource.setrlimit(resource.RLIMIT_AS, (int(limits.address_space_mb) * mb,) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (int(limits.cpu_seconds),) * 2)
    resource.setrlimit(resource.RLIMIT_NOFILE, (int(limits.open_files),) * 2)
    resource.setrlimit(resource.RLIMIT_FSIZE, (int(limits.output_bytes),) * 2)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


class Guard:
    def __init__(self, limits: Limits | None, emit_violation: bool = True):
        self.limits = limits
        self.peak_threads = 0
        self.lock = threading.Lock()
        self.active: tuple | None = None   # (team, kind, start_monotonic, serial)
        self.last_team = "?"               # team of the most recent robot activity
        self.serial = 0
        self.last_msg: dict = {}
        self.code_labels: list[tuple[int, str]] = []   # id(code dict) -> "A"/"B"
        self._get_code_calls = 0
        self.stats: dict[str, dict] = {}
        self.peak_rss = 0
        self.started = time.monotonic()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ---- team attribution -------------------------------------------------------------
    def register_code(self, code) -> None:
        """Called once per `get_code()`; the engine loads team A first, then team B."""
        label = "AB"[self._get_code_calls] if self._get_code_calls < 2 else "?"
        self._get_code_calls += 1
        if code is not None:
            self.code_labels.append((id(code), label))

    def team_of(self, code) -> str:
        for ident, label in self.code_labels:
            if ident == id(code):
                return label
        return "?"

    # ---- activity tracking (called from the main thread) ------------------------------
    def begin(self, team: str, kind: str) -> None:
        with self.lock:
            self.serial += 1
            self.last_team = team
            self.active = (team, kind, time.monotonic(), self.serial)

    def end(self) -> None:
        with self.lock:
            a, self.active = self.active, None
        if a is None:
            return
        team, kind, t0, _ = a
        dt = time.monotonic() - t0
        s = self._team_stats(team)
        if kind == "turn":
            s["turns"] += 1
            s["total_turn_seconds"] += dt
            s["max_turn_seconds"] = max(s["max_turn_seconds"], dt)
        else:
            s["inits"] += 1
            s["max_init_seconds"] = max(s["max_init_seconds"], dt)
        # A short allocation can finish between two watchdog polls, so also check when the activity ends:
        # memory that crossed the limit during this turn is charged to this team.
        rss = rss_bytes()
        self.peak_rss = max(self.peak_rss, rss)
        if self.limits is not None and rss > self.limits.memory_rss_mb * (1 << 20):
            self.violate(team, "memory", measured=round(rss / (1 << 20), 1), limit=self.limits.memory_rss_mb,
                         unit="MiB")

    def _team_stats(self, team: str) -> dict:
        return self.stats.setdefault(team, {"turns": 0, "inits": 0, "max_turn_seconds": 0.0,
                                            "total_turn_seconds": 0.0, "max_init_seconds": 0.0,
                                            "exceptions": 0, "game_action_exceptions": 0})

    def count_exception(self, game_action: bool) -> None:
        """A robot raised an uncaught exception; the engine kills that robot and the match goes on."""
        self._team_stats(self.last_team)["game_action_exceptions" if game_action else "exceptions"] += 1

    # ---- watchdog ---------------------------------------------------------------------
    def start(self) -> None:
        self._thread = threading.Thread(target=self._watch, name="bio-guard", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _watch(self) -> None:
        lim = self.limits
        idle_over_since = None
        while not self._stop.wait(POLL_SECONDS):
            with self.lock:           # read the active robot BEFORE the memory, so a turn that ends in
                a = self.active       # between is still the one blamed
            rss = rss_bytes()
            if rss > self.peak_rss:
                self.peak_rss = rss
            self.peak_threads = max(self.peak_threads, threading.active_count())
            if lim is None:
                continue
            if a is not None:
                team, kind, t0, _ = a
                elapsed = time.monotonic() - t0
                cap = lim.turn_wall_seconds if kind == "turn" else lim.init_wall_seconds
                if elapsed > cap:
                    self.violate(team, f"{kind}_wall_time", measured=round(elapsed, 3), limit=cap, unit="seconds")
            over = rss > lim.memory_rss_mb * (1 << 20)
            if over and a is not None:
                self.violate(a[0], "memory", measured=round(rss / (1 << 20), 1), limit=lim.memory_rss_mb, unit="MiB")
            # Memory only grows while some robot runs, and end() charges that robot. Over the limit with no
            # robot running for a while therefore means the engine itself grew: a platform fault, not a bot's.
            if over and a is None:
                idle_over_since = idle_over_since or time.monotonic()
                if time.monotonic() - idle_over_since > 2.0:
                    self.violate(None, "memory", measured=round(rss / (1 << 20), 1), limit=lim.memory_rss_mb,
                                 unit="MiB")
            else:
                idle_over_since = None

    # ---- outcomes ---------------------------------------------------------------------
    def usage(self) -> dict:
        return {
            "peak_rss_mib": round(self.peak_rss / (1 << 20), 1),
            "peak_vm_mib": _vm_peak_mib(),
            "peak_threads": self.peak_threads,
            "cpu_seconds": round(time.process_time(), 2),
            "wall_seconds": round(time.monotonic() - self.started, 2),
            "teams": self.stats,
        }

    def emit_usage(self) -> None:
        _emit("BIO-GUARD-USAGE", self.usage())

    def violate(self, team, kind: str, **detail) -> None:
        """Record the violation and end the process now. Never returns."""
        record = {"team": team, "kind": kind, **detail, "round": self.last_msg.get("round"),
                  "robot_id": self.last_msg.get("id"), "usage": self.usage()}
        _emit("BIO-GUARD-VIOLATION", record)
        self.emit_usage()
        os._exit(EXIT_VIOLATION if team in ("A", "B") else EXIT_PLATFORM)


def _vm_peak_mib() -> float | None:
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmPeak:"):
                    return round(int(line.split()[1]) / 1024, 1)
    except OSError:
        pass
    return None


def _emit(tag: str, doc: dict) -> None:
    """One line on the original stdout (fd 1), written with a single os.write so lines do not interleave."""
    try:
        os.write(1, (f"\n{tag} " + json.dumps(doc, separators=(",", ":")) + "\n").encode())
    except OSError:
        pass  # output cap reached or stdout closed: nothing more we can do


def install(engine_main, guard: Guard) -> None:
    """Patch the imported `battlecode26.__main__` module so every robot is guarded."""
    from battlecode26.runner import RobotRunner

    class GuardedRobotRunner(RobotRunner):
        def __init__(self, code, *args, **kwargs):
            self._bio_team = guard.team_of(code)
            super().__init__(code, *args, **kwargs)

        def init_robot(self):
            guard.begin(self._bio_team, "init")
            try:
                super().init_robot()
            finally:
                guard.end()

        def run(self):
            guard.begin(self._bio_team, "turn")
            try:
                super().run()
            finally:
                guard.end()

    orig_get_code = engine_main.get_code
    orig_receive = engine_main.receive

    def get_code(bot_name, bot_dir):
        code = orig_get_code(bot_name, bot_dir)
        guard.register_code(code)
        return code

    def receive():
        msg = orig_receive()
        if isinstance(msg, dict):
            guard.last_msg = msg
        return msg

    orig_send = engine_main.send
    method = engine_main.CrossPlayMethod

    def send(m, params=None):
        if m == method.THROW_EXCEPTION:
            guard.count_exception(False)
        elif m == method.THROW_GAME_ACTION_EXCEPTION:
            guard.count_exception(True)
        return orig_send(m, params)

    engine_main.send = send
    engine_main.RobotRunner = GuardedRobotRunner
    engine_main.get_code = get_code
    engine_main.receive = receive
