# SPDX-License-Identifier: AGPL-3.0-only
"""Operating-system sandbox for the bot runner process (BIO-203), using bubblewrap (`bwrap`).

What the sandboxed process gets:
  * its own user, PID, IPC, UTS and network namespaces: no network at all (not even the host's
    loopback), no view of host processes, all capabilities dropped, killed when the launcher dies;
  * a read-only file system holding only what Python needs: /usr, the interpreter, the venv, this
    directory, and the two bot directories (read-only). No home directory, no /etc, no repository;
  * a private /tmp (memory-backed, size capped) and nothing else writable; the root is remounted
    read-only. Results leave through stdout only (see guard.py);
  * one unix socket, bridged on the host to the Java engine server's loopback port. The bridge is the
    only way out, and it forwards bytes unchanged.

What it does NOT give (documented in docs/TECHNICAL_DOCUMENTATION.md): a seccomp syscall filter, a
cgroup memory/PID limit (the in-process guard and rlimits cover memory and time; process count is
checked by test), protection between the two teams (both run in one process), or protection from
a kernel exploit. Linux with unprivileged user namespaces only.
"""
from __future__ import annotations

import os
import shutil
import socket
import threading
import time
from pathlib import Path

BWRAP = "bwrap"
TMP_SIZE_BYTES = 64 << 20


class SandboxUnavailable(Exception):
    pass


def check_available() -> str:
    path = shutil.which(BWRAP)
    if path is None:
        raise SandboxUnavailable("bubblewrap (bwrap) is not installed")
    return path


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


def build_command(py: Path, runner_entry: Path, bots: dict[str, Path], ipc_socket: Path,
                  limits_file: Path, runner_args: list[str]) -> list[str]:
    """Return the full `bwrap ... python runner_entry.py ...` command.

    bots maps "A"/"B" to that team's own bot folder (the one holding bot.py). Only these two folders
    are mounted, read-only, so a bot cannot see other participants' source. The runner is told
    `--teamA <folder name> --dirA /work/A` and likewise for B. runner_args are extra runner arguments.
    """
    check_available()
    venv = py.parent.parent  # <venv>/bin/python -> <venv>
    cmd = [BWRAP,
           "--unshare-user", "--unshare-pid", "--unshare-net", "--unshare-ipc", "--unshare-uts",
           "--unshare-cgroup-try", "--die-with-parent", "--new-session", "--cap-drop", "ALL",
           "--clearenv", "--setenv", "PATH", "/usr/bin", "--setenv", "HOME", "/tmp",
           "--setenv", "PYTHONDONTWRITEBYTECODE", "1", "--hostname", "bio-sandbox",
           "--ro-bind", "/usr", "/usr"]
    for link in ("lib", "lib64", "bin", "sbin"):  # merged-/usr layouts: /lib -> usr/lib etc.
        p = Path("/") / link
        if p.is_symlink():
            cmd += ["--symlink", os.readlink(p), str(p)]
    cmd += ["--proc", "/proc", "--dev", "/dev", "--size", str(TMP_SIZE_BYTES), "--tmpfs", "/tmp"]
    ro_paths = [venv, runner_entry.parent]
    home = _python_home(py)
    if home is not None:
        ro_paths.append(home)
    for p in ro_paths:
        cmd += _ro_mount(p)
    for team, d in bots.items():
        cmd += ["--ro-bind", str(d.resolve()), f"/work/{team}/{d.name}"]
    cmd += ["--ro-bind", str(limits_file.resolve()), "/work/limits.json",
            "--bind", str(ipc_socket.resolve()), "/ipc/engine.sock",
            "--remount-ro", "/",  # the root is a tmpfs; make it read-only (only /tmp stays writable, size capped)
            "--chdir", "/work",
            str(py), "-I", str(runner_entry.resolve()),
            "--teamA", bots["A"].name, "--dirA", "/work/A", "--teamB", bots["B"].name, "--dirB", "/work/B",
            "--limits", "/work/limits.json", "--in-sandbox", "--ipc-socket", "/ipc/engine.sock", *runner_args]
    return cmd


class Bridge:
    """Host-side forwarder: unix socket (sandbox side) <-> TCP 127.0.0.1:port (engine server side).

    Forwards bytes unchanged in both directions and sets TCP_NODELAY on the TCP leg. Accepts one
    connection at a time; the engine opens exactly one.
    """

    def __init__(self, path: Path, port: int, connect_timeout: float = 600.0):
        self.path = Path(path)
        self.port = port
        self.connect_timeout = connect_timeout
        self.bytes_to_engine = 0
        self.bytes_from_engine = 0
        self._srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        if self.path.exists():
            self.path.unlink()
        self._srv.bind(str(self.path))
        os.chmod(self.path, 0o600)
        self._srv.listen(1)
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        t = threading.Thread(target=self._accept_loop, daemon=True, name="bio-bridge")
        t.start()
        self._threads.append(t)

    def _accept_loop(self):
        self._srv.settimeout(0.5)
        while not self._stop.is_set():
            try:
                conn, _ = self._srv.accept()
            except (socket.timeout, TimeoutError):
                continue
            except OSError:
                return
            t = threading.Thread(target=self._serve, args=(conn,), daemon=True)
            t.start()
            self._threads.append(t)

    def _serve(self, conn: socket.socket):
        deadline = time.monotonic() + self.connect_timeout
        up = None
        while not self._stop.is_set() and time.monotonic() < deadline:
            try:
                up = socket.create_connection(("127.0.0.1", self.port), timeout=2)
                up.settimeout(None)
                up.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                break
            except OSError:
                time.sleep(0.1)
        if up is None:
            conn.close()
            return

        quickack = getattr(socket, "TCP_QUICKACK", None)

        def pump(src, dst, attr):
            # The Java server writes each message as two small TCP writes. Without an immediate ACK
            # from us, Nagle plus delayed ACK costs ~40 ms per message (see runner_entry.py).
            ack = quickack is not None and src.family == socket.AF_INET
            try:
                while True:
                    if ack:
                        src.setsockopt(socket.IPPROTO_TCP, quickack, 1)
                    data = src.recv(65536)
                    if not data:
                        break
                    dst.sendall(data)
                    setattr(self, attr, getattr(self, attr) + len(data))
            except OSError:
                pass
            finally:
                for s in (src, dst):
                    try:
                        s.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass

        a = threading.Thread(target=pump, args=(conn, up, "bytes_to_engine"), daemon=True)
        b = threading.Thread(target=pump, args=(up, conn, "bytes_from_engine"), daemon=True)
        a.start()
        b.start()
        a.join()
        b.join()
        conn.close()
        up.close()

    def close(self):
        self._stop.set()
        try:
            self._srv.close()
        except OSError:
            pass
        try:
            self.path.unlink()
        except OSError:
            pass
