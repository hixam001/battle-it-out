# SPDX-License-Identifier: AGPL-3.0-only
"""Operating-system sandbox for the bot runner processes (BIO-203), using bubblewrap (`bwrap`).

One runner process per team, each in its own sandbox, joined to the Java engine server by a
`Router` (the engine allows exactly one client connection, so something must sit in front of it).

What each sandboxed process gets:
  * its own user, PID, IPC, UTS and network namespaces: no network at all (not even the host's
    loopback), no view of host processes, all capabilities dropped, killed when the launcher dies;
  * a read-only file system holding only what Python needs: /usr, the interpreter, the venv, this
    directory, and **its own team's bot folder** (read-only). No home directory, no /etc, no
    repository, and not the other team's code (they are different processes now);
  * a private /tmp (memory-backed, size capped) and nothing else writable;
  * a seccomp filter (`seccomp_program`) that denies kernel-attack-surface system calls
    (ptrace, mount, bpf, io_uring, keyctl, userfaultfd, namespace creation, kexec, module loading...);
  * optionally kernel cgroup limits (memory, tasks) via a transient `systemd-run --user --scope`;
  * one unix socket to the router. The router is the only way out.

What it does NOT give (docs/TECHNICAL_DOCUMENTATION.md section 3.6): protection from a kernel or
bubblewrap vulnerability, per-robot memory accounting inside one team (all of a team's robots share
the team's process), or anything on kernels without unprivileged user namespaces. Linux x86_64 only.
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import socket
import struct
import subprocess
import threading
import time
from pathlib import Path

BWRAP = "bwrap"
TMP_SIZE_BYTES = 64 << 20
MAX_FRAME_BYTES = 8 << 20  # a runner-side frame larger than this ends the match connection
CONTINUATION = "  | "      # starts every line after the first of any text a runner sends (BIO-206, CN-007)
# The engine's method numbers (battlecode26.crossplay.CrossPlayMethod): 0 is INVALID, the last is
# RC_GET_NUMBER_CAT_TRAPS = 107. The Java server crashes on any other number, which would be reported as
# a platform failure (SR-03, CN-008), so the router refuses them. A test compares this with the installed engine.
MIN_METHOD, MAX_METHOD = 1, 107


class SandboxUnavailable(Exception):
    pass


def check_available() -> str:
    path = shutil.which(BWRAP)
    if path is None:
        raise SandboxUnavailable("bubblewrap (bwrap) is not installed")
    if platform.machine() != "x86_64":
        raise SandboxUnavailable(f"the seccomp filter is written for x86_64, this is {platform.machine()}")
    return path


# ------------------------------------------------------------------------------------------
# seccomp: a small hand-assembled classic-BPF denylist (no libseccomp needed)
# ------------------------------------------------------------------------------------------
AUDIT_ARCH_X86_64 = 0xC000003E
SECCOMP_RET_ALLOW = 0x7FFF0000
SECCOMP_RET_KILL_PROCESS = 0x80000000
SECCOMP_RET_ERRNO = 0x00050000
EPERM, ENOSYS = 1, 38
X32_BIT = 0x40000000
# x86_64 system call numbers (linux/arch/x86/entry/syscalls/syscall_64.tbl)
DENIED_SYSCALLS = {
    "ptrace": 101, "mount": 165, "umount2": 166, "pivot_root": 155, "chroot": 161, "swapon": 167,
    "swapoff": 168, "reboot": 169, "init_module": 175, "delete_module": 176, "kexec_load": 246,
    "add_key": 248, "request_key": 249, "keyctl": 250, "unshare": 272, "perf_event_open": 298,
    "setns": 308, "process_vm_readv": 310, "process_vm_writev": 311, "finit_module": 313,
    "kexec_file_load": 320, "bpf": 321, "userfaultfd": 323, "open_by_handle_at": 304,
    "io_uring_setup": 425, "io_uring_enter": 426, "io_uring_register": 427, "open_tree": 428,
    "move_mount": 429, "fsopen": 430, "fsconfig": 431, "fsmount": 432, "fspick": 433, "mount_setattr": 442,
}
SYS_CLONE, SYS_CLONE3 = 56, 435
CLONE_NEW_MASK = 0x7E020000  # CLONE_NEWNS|NEWCGROUP|NEWUTS|NEWIPC|NEWUSER|NEWPID|NEWNET
_LD_W_ABS, _JEQ_K, _JSET_K, _RET_K = 0x20, 0x15, 0x45, 0x06


def _assemble(program: list[tuple]) -> bytes:
    """Tiny assembler. Items: ("label", name) | ("ld", offset) | ("ret", value) |
    ("jeq"|"jset", k, true_label_or_None, false_label_or_None); None means "the next instruction"."""
    labels, insns = {}, []
    for item in program:
        if item[0] == "label":
            labels[item[1]] = len(insns)
        else:
            insns.append(item)
    out = []
    for i, ins in enumerate(insns):
        op = ins[0]
        if op == "ld":
            out.append(struct.pack("<HBBI", _LD_W_ABS, 0, 0, ins[1]))
        elif op == "ret":
            out.append(struct.pack("<HBBI", _RET_K, 0, 0, ins[1]))
        else:
            jt = 0 if ins[2] is None else labels[ins[2]] - i - 1
            jf = 0 if ins[3] is None else labels[ins[3]] - i - 1
            if not (0 <= jt < 256 and 0 <= jf < 256):
                raise ValueError("BPF jump out of range")
            out.append(struct.pack("<HBBI", _JEQ_K if op == "jeq" else _JSET_K, jt, jf, ins[1]))
    return b"".join(out)


def seccomp_program() -> bytes:
    """Compile the denylist to a `struct sock_filter` array (what `bwrap --seccomp FD` reads).

    Wrong architecture: kill. x32 calls and each listed call: EPERM. `clone3` fails with ENOSYS (glibc
    then falls back to `clone`, whose flags can be inspected). `clone` with any namespace flag: EPERM.
    Everything else is allowed.
    """
    prog: list[tuple] = [
        ("ld", 4), ("jeq", AUDIT_ARCH_X86_64, "arch_ok", None), ("ret", SECCOMP_RET_KILL_PROCESS),
        ("label", "arch_ok"), ("ld", 0), ("jset", X32_BIT, "deny", None),
    ]
    for nr in sorted(DENIED_SYSCALLS.values()):
        prog.append(("jeq", nr, "deny", None))
    prog += [
        ("jeq", SYS_CLONE3, "nosys", None),
        ("jeq", SYS_CLONE, "clone", "allow"),
        ("label", "clone"), ("ld", 16), ("jset", CLONE_NEW_MASK, "deny", "allow"),
        ("label", "deny"), ("ret", SECCOMP_RET_ERRNO | EPERM),
        ("label", "nosys"), ("ret", SECCOMP_RET_ERRNO | ENOSYS),
        ("label", "allow"), ("ret", SECCOMP_RET_ALLOW),
    ]
    return _assemble(prog)


def seccomp_pipe() -> int:
    """Return a read end holding the filter (the program is far below the pipe buffer size)."""
    r, w = os.pipe()
    os.write(w, seccomp_program())
    os.close(w)
    return r


# ------------------------------------------------------------------------------------------
# command construction
# ------------------------------------------------------------------------------------------
def _python_home(py: Path) -> Path | None:
    """Directory holding the interpreter the venv uses: parent of the venv's `home =` directory.

    Returned unresolved on purpose: uv names it `cpython-3.15-...`, a symlink to `cpython-3.15.2-...`.
    """
    cfg = py.parent.parent / "pyvenv.cfg"
    if cfg.exists():
        for line in cfg.read_text().splitlines():
            if line.startswith("home"):
                return Path(line.split("=", 1)[1].strip()).parent
    return None


def _ro_mount(path: Path) -> list[str]:
    """Read-only mount of `path` at its real location, plus a symlink at the name used if it differs."""
    real = path.resolve()
    args = ["--ro-bind", str(real), str(real)]
    if real != path:
        args += ["--symlink", str(real), str(path)]
    return args


def base_args(py: Path, runner_dir: Path, seccomp_fd: int | None) -> list[str]:
    """Namespaces, read-only system and interpreter mounts, hardening. Ends before bot/ipc mounts."""
    check_available()
    venv = py.parent.parent  # <venv>/bin/python -> <venv>
    cmd = [BWRAP,
           "--unshare-user", "--unshare-pid", "--unshare-net", "--unshare-ipc", "--unshare-uts",
           "--unshare-cgroup-try", "--die-with-parent", "--new-session", "--cap-drop", "ALL",
           "--clearenv", "--setenv", "PATH", "/usr/bin", "--setenv", "HOME", "/tmp",
           "--setenv", "PYTHONDONTWRITEBYTECODE", "1", "--hostname", "bio-sandbox",
           "--ro-bind", "/usr", "/usr"]
    if seccomp_fd is not None:
        cmd += ["--seccomp", str(seccomp_fd)]
    for link in ("lib", "lib64", "bin", "sbin"):  # merged-/usr layouts: /lib -> usr/lib etc.
        p = Path("/") / link
        if p.is_symlink():
            cmd += ["--symlink", os.readlink(p), str(p)]
    cmd += ["--proc", "/proc", "--dev", "/dev", "--size", str(TMP_SIZE_BYTES), "--tmpfs", "/tmp"]
    ro_paths = [venv, runner_dir]
    home = _python_home(py)
    if home is not None:
        ro_paths.append(home)
    for p in ro_paths:
        cmd += _ro_mount(p)
    return cmd


def build_command(py: Path, runner_entry: Path, team: str, bot_dir: Path, ipc_socket: Path,
                  limits_file: Path, runner_args: list[str], seccomp_fd: int | None = None) -> list[str]:
    """Return the `bwrap ... python runner_entry.py ...` command for ONE team's runner process.

    `team` is "A" or "B"; `bot_dir` is that team's own bot folder (the one holding bot.py). Only that
    folder is mounted, read-only, at /work/<team>/<name>, so the process cannot see other
    participants' source, including the opposing team's.
    """
    if team not in ("A", "B"):
        raise ValueError(team)
    cmd = base_args(py, runner_entry.resolve().parent, seccomp_fd)
    cmd += ["--ro-bind", str(bot_dir.resolve()), f"/work/{team}/{bot_dir.name}",
            "--ro-bind", str(limits_file.resolve()), "/work/limits.json",
            "--bind", str(ipc_socket.resolve()), "/ipc/engine.sock",
            "--remount-ro", "/",  # the root is a tmpfs; make it read-only (only /tmp stays writable, size capped)
            "--chdir", "/work",
            str(py), "-I", str(runner_entry.resolve()),
            f"--team{team}", bot_dir.name, f"--dir{team}", f"/work/{team}",
            "--limits", "/work/limits.json", "--in-sandbox", "--ipc-socket", "/ipc/engine.sock", *runner_args]
    return cmd


def build_probe_command(py: Path, code: str, seccomp_fd: int | None = None) -> list[str]:
    """Run a Python snippet in the same sandbox (used by tests to probe the filter and mounts)."""
    cmd = base_args(py, Path(__file__).resolve().parent, seccomp_fd)
    cmd += ["--remount-ro", "/", "--chdir", "/tmp", str(py), "-I", "-c", code]
    return cmd


# ------------------------------------------------------------------------------------------
# kernel cgroup limits (optional layer)
# ------------------------------------------------------------------------------------------
_cgroup_ok: bool | None = None


def cgroup_prefix(memory_mb: int, tasks: int) -> list[str]:
    return ["systemd-run", "--user", "--scope", "--quiet", "-p", f"MemoryMax={int(memory_mb)}M",
            "-p", "MemorySwapMax=0", "-p", f"TasksMax={int(tasks)}", "--"]


def cgroup_available() -> bool:
    """True if a transient user scope with memory and task limits can be created."""
    global _cgroup_ok
    if _cgroup_ok is None:
        if shutil.which("systemd-run") is None:
            _cgroup_ok = False
        else:
            try:
                r = subprocess.run(cgroup_prefix(64, 64) + ["true"], capture_output=True, timeout=15)
                _cgroup_ok = r.returncode == 0
            except (OSError, subprocess.TimeoutExpired):
                _cgroup_ok = False
    return _cgroup_ok


# ------------------------------------------------------------------------------------------
# the router
# ------------------------------------------------------------------------------------------
def _read_exact(sock: socket.socket, n: int, quickack: bool = False) -> bytes | None:
    """Read exactly n bytes; None on EOF. `quickack` asks for an immediate ACK before each receive."""
    buf = bytearray()
    ack = getattr(socket, "TCP_QUICKACK", None) if quickack else None
    while len(buf) < n:
        if ack is not None:
            sock.setsockopt(socket.IPPROTO_TCP, ack, 1)
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return bytes(buf)


def _read_frame(sock: socket.socket, quickack: bool = False) -> bytes | None:
    """One engine message: 4-byte big-endian length then that many bytes. Returns the body."""
    head = _read_exact(sock, 4, quickack)
    if head is None:
        return None
    (n,) = struct.unpack(">I", head)
    if n > MAX_FRAME_BYTES:
        raise ValueError(f"frame of {n} bytes exceeds the {MAX_FRAME_BYTES} byte cap")
    return _read_exact(sock, n, quickack) if n else b""


class MalformedFrame(ValueError):
    """A runner sent something that is not an engine message."""


class ProtocolViolation(MalformedFrame):
    """A runner sent a well-formed frame at a time the engine protocol does not allow it (SR-01, CN-008)."""


_CONTROL = re.compile(r"[\x00-\x08\x0e-\x1f\x7f]")


def sanitise_text(text: str) -> str:
    """Make a runner-supplied string safe to print into the engine's log.

    The Java server prints bot `log(...)` text after a `[A: #3@1]` prefix and does not escape line
    breaks, so a bot could start a line with `[server] ...` and forge the engine's own output. Every
    line break kind (`str.splitlines`: \\n \\r \\v \\f FS GS RS NEL LS PS) becomes a newline plus
    `CONTINUATION`, so no bot-controlled line can begin like an engine line; other control characters
    (including ESC) are dropped. A tab is kept.
    """
    lines = text.splitlines()
    if len(lines) <= 1 and not _CONTROL.search(text):
        return lines[0] if lines else ""
    return ("\n" + CONTINUATION).join(_CONTROL.sub("", ln) for ln in lines)


def _reject_constant(name: str):
    raise MalformedFrame(f"non-standard JSON constant {name}")


def _clean(value, counter: list):
    if isinstance(value, str):
        out = sanitise_text(value)
        if out != value:
            counter[0] += 1
        return out
    if isinstance(value, list):
        return [_clean(v, counter) for v in value]
    if isinstance(value, dict):
        return {_clean(k, counter): _clean(v, counter) for k, v in value.items()}   # JSON keys are strings
    return value


def canonical_runner_frame(body: bytes) -> tuple[bytes, int]:
    """Parse one runner frame and rebuild it. Returns (frame to forward, number of strings rewritten).

    The server must see exactly what this function parsed. Forwarding the original bytes would let a
    bot send JSON that Python reads one way and the Java server another (duplicate keys, comments,
    lenient syntax). A frame is either JSON `null` (an answer to a notice) or an object with an integer
    `method` and a list `params`; extra keys are dropped; anything else is `MalformedFrame` and ends that
    runner's connection.
    """
    try:
        msg = json.loads(body.decode("utf-8"), parse_constant=_reject_constant)
    except (UnicodeDecodeError, RecursionError) as e:
        raise MalformedFrame(f"frame is not valid JSON text ({type(e).__name__})")
    except json.JSONDecodeError as e:
        raise MalformedFrame(f"frame is not valid JSON ({e.msg})")
    if msg is None:
        return b"null", 0
    method = msg.get("method") if isinstance(msg, dict) else None
    params = msg.get("params") if isinstance(msg, dict) else None
    if not isinstance(method, int) or isinstance(method, bool) or not isinstance(params, list):
        raise MalformedFrame("frame is neither null nor {method: int, params: list}")
    if not MIN_METHOD <= method <= MAX_METHOD:
        raise ProtocolViolation(f"protocol violation: unknown engine method {method}")
    counter = [0]
    try:
        clean = {"method": method, "params": _clean(params, counter)}
        return json.dumps(clean).encode("utf-8"), counter[0]
    except RecursionError:
        raise MalformedFrame("frame is nested too deeply")


def check_turn(team: str, is_null: bool, current: str, pending_null: dict) -> str | None:
    """Is a frame from `team` allowed now? Returns the reason it is not, or None (SR-01, CN-008).

    The Java server has ONE connection for both teams and cannot tell the runners apart, so the router must.
    The server only ever talks to one robot at a time:
      * a call (anything but null) comes from the runner whose turn it is (`current`);
      * a null is the answer to a notice the router forwarded to that runner (`spawn_bot`, `destroy_bot`),
        which may be the other team's runner (a robot of the idle team can be destroyed in the middle of a turn).
    Anything else would be read by the server as the current robot's own message.
    """
    if is_null:
        return None if pending_null.get(team, 0) > 0 else "protocol violation: null reply that was not asked for"
    return None if team == current else "protocol violation: frame sent out of turn"


def route_for(msg, owner: dict, current: str) -> tuple[list[str], str]:
    """Decide which runner(s) get a server message. Returns (targets, new current runner).

    The engine multiplexes both teams over one connection in lock step:
      * `spawn_bot` (carries the team) and `start_turn` (carries the robot id) start work for one
        team: that runner becomes current;
      * `destroy_bot` goes to the team that owns the robot WITHOUT changing the current runner: it is
        either a top-level notice or a notice nested inside the current runner's call; the owner
        answers with a null that is forwarded to the server like any other client message;
      * `end_game` goes to everyone;
      * anything else is the reply to the current runner's call.
    """
    kind = msg.get("type") if isinstance(msg, dict) else None
    if kind == "spawn_bot":
        team = "AB"[msg["team"]] if msg.get("team") in (0, 1) else current
        owner[msg["id"]] = team
        return [team], team
    if kind == "start_turn":
        team = owner.get(msg.get("id"), current)
        return [team], team
    if kind == "destroy_bot":
        return [owner.get(msg.get("id"), current)], current
    if kind == "end_game":
        return ["A", "B"], current
    return [current], current


class Router:
    """Host-side connector: two unix sockets (one per team's runner) <-> TCP 127.0.0.1:port (engine).

    Messages from a runner are parsed and rebuilt (`canonical_runner_frame`: validated shape, line breaks
    in text neutralised) before they go to the server, one whole frame at a time. Messages from the
    server go to the runner chosen by `route_for`. A runner frame above MAX_FRAME_BYTES ends the
    match connection. Waits for both runners before it connects to the server.
    """

    def __init__(self, directory: Path, port: int, connect_timeout: float = 600.0,
                 turn_deadline: float | None = None):
        self.dir = Path(directory)
        self.turn_deadline = turn_deadline   # seconds a runner may stay silent after the router handed it work
        self.paths = {"A": self.dir / "a.sock", "B": self.dir / "b.sock"}
        self.port = port
        self.connect_timeout = connect_timeout
        self.stats = {"frames_to_server": 0, "frames_to_runners": 0, "error": None,
                      "connected": [], "first_end": None, "text_rewrites": {"A": 0, "B": 0}}
        self._end_lock = threading.Lock()
        self._t0 = time.monotonic()
        self._listeners: dict[str, socket.socket] = {}
        self._conns: dict[str, socket.socket] = {}
        self._up: socket.socket | None = None
        self._up_lock = threading.Lock()
        self._stop = threading.Event()
        self._owner: dict[int, str] = {}
        self._state = threading.Lock()      # guards _current, _pending_null, _waiting
        self._current = "A"
        self._pending_null = {"A": 0, "B": 0}
        self._waiting: dict[str, float] = {}   # runner -> when the router last gave it something to answer
        for team, path in self.paths.items():
            srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            if path.exists():
                path.unlink()
            srv.bind(str(path))
            os.chmod(path, 0o600)
            srv.listen(1)
            self._listeners[team] = srv
        self._thread = threading.Thread(target=self._run, daemon=True, name="bio-router")
        self._thread.start()

    def _note_end(self, leg: str, how: str) -> None:
        """Remember which leg of the connection ended first (BIO-205). Only the first call counts.

        This is evidence a bot cannot forge: the router sits outside every sandbox and sees the sockets
        close, whatever the bot prints. `leg` is "runner:A", "runner:B" or "server".
        """
        with self._end_lock:
            if self.stats["first_end"] is None:
                self.stats["first_end"] = {"leg": leg, "how": how,
                                           "after_seconds": round(time.monotonic() - self._t0, 3)}

    # -- connection set-up -------------------------------------------------------------
    def _accept(self, team: str) -> None:
        srv = self._listeners[team]
        srv.settimeout(0.5)
        deadline = time.monotonic() + self.connect_timeout
        while not self._stop.is_set() and time.monotonic() < deadline:
            try:
                self._conns[team], _ = srv.accept()
                self.stats["connected"].append(team)
                return
            except (socket.timeout, TimeoutError):
                continue
            except OSError:
                return

    def _connect_upstream(self) -> socket.socket | None:
        deadline = time.monotonic() + self.connect_timeout
        while not self._stop.is_set() and time.monotonic() < deadline:
            try:
                up = socket.create_connection(("127.0.0.1", self.port), timeout=2)
                up.settimeout(None)
                up.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                return up
            except OSError:
                time.sleep(0.1)
        return None

    def _run(self):
        waiters = [threading.Thread(target=self._accept, args=(t,), daemon=True) for t in ("A", "B")]
        for w in waiters:
            w.start()
        for w in waiters:
            w.join()
        if len(self._conns) < 2:
            self.stats["error"] = self.stats["error"] or "a runner never connected"
            self._shutdown()
            return
        self._up = self._connect_upstream()
        if self._up is None:
            self.stats["error"] = self.stats["error"] or "engine server never accepted"
            self._shutdown()
            return
        for team in ("A", "B"):
            threading.Thread(target=self._from_runner, args=(team,), daemon=True).start()
        if self.turn_deadline:
            threading.Thread(target=self._watchdog, daemon=True, name="bio-router-deadline").start()
        self._from_server()

    def _watchdog(self) -> None:
        """Host-side response deadline (SR-02, CN-008). The guard inside a runner can be frozen by the bot it
        watches (SIGSTOP on itself, a C call that keeps the GIL), so a runner that stays silent too long after
        being handed work is ended from here, outside every sandbox, and charged to its team."""
        while not self._stop.wait(0.1):
            now = time.monotonic()
            with self._state:
                late = sorted(t for t, t0 in self._waiting.items() if now - t0 > self.turn_deadline)
            if late:
                team = late[0]
                how = f"deadline: no frame within {self.turn_deadline:g}s"
                self._note_end(f"runner:{team}", how)
                self.stats["error"] = self.stats["error"] or f"runner {team}: {how}"
                self._shutdown()
                return

    # -- forwarding --------------------------------------------------------------------
    def _from_runner(self, team: str):
        conn = self._conns[team]
        try:
            while True:
                body = _read_frame(conn)
                if body is None:
                    break
                body, rewrites = canonical_runner_frame(body)   # raises MalformedFrame (a ValueError)
                with self._state:
                    self._waiting.pop(team, None)
                    reason = check_turn(team, body == b"null", self._current, self._pending_null)
                    if reason is None and body == b"null" and self._pending_null[team] > 0:
                        self._pending_null[team] -= 1
                if reason:
                    raise ProtocolViolation(reason)
                if rewrites:
                    self.stats["text_rewrites"][team] += rewrites
                with self._up_lock:
                    self._up.sendall(struct.pack(">I", len(body)) + body)
                self.stats["frames_to_server"] += 1
        except (OSError, ValueError) as e:
            self._note_end(f"runner:{team}", f"error: {e}")
            self.stats["error"] = self.stats["error"] or f"runner {team}: {e}"
        else:
            self._note_end(f"runner:{team}", "closed")
        finally:
            self._shutdown()

    def _from_server(self):
        current = "A"
        try:
            while True:
                body = _read_frame(self._up, quickack=True)
                if body is None:
                    break
                try:
                    msg = json.loads(body) if body else None
                except ValueError:
                    msg = None
                targets, current = route_for(msg, self._owner, current)
                kind = msg.get("type") if isinstance(msg, dict) else None
                with self._state:
                    self._current = current
                    if kind == "end_game":
                        self._waiting.clear()
                    else:
                        now = time.monotonic()
                        for t in targets:
                            self._waiting[t] = now
                            if kind in ("spawn_bot", "destroy_bot"):
                                self._pending_null[t] += 1     # the runner answers these with null
                data = struct.pack(">I", len(body)) + body
                for t in targets:
                    try:
                        self._conns[t].sendall(data)
                    except OSError:
                        pass  # that runner is gone; the launcher sees its exit status
                self.stats["frames_to_runners"] += 1
        except (OSError, ValueError) as e:
            self._note_end("server", f"error: {e}")
            self.stats["error"] = self.stats["error"] or f"server: {e}"
        else:
            self._note_end("server", "closed")
        finally:
            self._shutdown()

    def _shutdown(self):
        for s in list(self._conns.values()) + ([self._up] if self._up else []):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def close(self):
        self._stop.set()
        self._shutdown()
        for s in list(self._listeners.values()) + list(self._conns.values()) + ([self._up] if self._up else []):
            try:
                s.close()
            except OSError:
                pass
        for p in self.paths.values():
            try:
                p.unlink()
            except OSError:
                pass
