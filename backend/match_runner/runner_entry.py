# SPDX-License-Identifier: AGPL-3.0-only
"""Entry point that runs the Battlecode Python runner on any supported CPython (3.12 to 3.15+).

It replaces `python -m battlecode26`, whose `main()` only accepts Python 3.12, and adds
low-latency socket settings. It does not modify the installed engine package.

Compatibility reasons (found by running and reading the engine package, 2026-11-24):
  * `battlecode26.instrument` builds a table of CPython 3.12 opcode names when imported, and
    fails with KeyError on newer versions (e.g. KW_NAMES). `Instrument.instrument()` is never
    called by the package (the runner exec()s bot source directly), so the table is unused;
    we only need the import to succeed. The missing names are added to `dis.opmap` (a copy, swapped in
    for the duration of that import only).
  * `main()` rejects any Python except 3.12; `play()` has no such check, so we call `play()`.

Socket settings (Linux): the engine sends a 4-byte length and the JSON body as two writes and
sets no TCP_NODELAY; the Java server does the same. Nagle's algorithm plus delayed ACKs then
cost about 40 ms per message. We set TCP_NODELAY, send each message with one write, and ask
for immediate ACKs (TCP_QUICKACK) around every receive. Message contents are unchanged.

Resource limits (BIO-204): with --limits FILE the runner applies operating-system rlimits and
installs the guard from `guard.py` (wall-clock and memory limits, violation record). With
--measure it records usage even without limits. With --ipc-socket PATH it connects to
the engine over that unix socket instead of 127.0.0.1:27185 (used inside the network-less sandbox,
see `sandbox.py`).

Usage: python runner_entry.py --teamA NAME --teamB NAME --dirA DIR --dirB DIR [--no-socket-tuning]
           [--limits FILE] [--measure] [--in-sandbox] [--ipc-socket PATH]
"""
from __future__ import annotations

import argparse
import dis
import json
import socket
import struct
import sys
import time
from pathlib import Path

_OPCODE_NAMES_NEEDED = [
    "CACHE", "JUMP_FORWARD", "POP_JUMP_IF_FALSE", "POP_JUMP_IF_TRUE", "LOAD_GLOBAL", "COPY",
    "LOAD_FAST", "STORE_FAST", "GET_AWAITABLE", "KW_NAMES", "EXTENDED_ARG", "RESUME",
]


def _load_sibling(name: str):
    """Load a module that sits next to this file (the runner is started with -I, so no sys.path entry)."""
    import importlib.util

    path = Path(__file__).resolve().with_name(name + ".py")
    spec = importlib.util.spec_from_file_location(f"bio_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def import_engine():
    """Import battlecode26.__main__, tolerating opcode names missing from newer CPython."""
    original = dis.opmap
    missing = {n: -1 for n in _OPCODE_NAMES_NEEDED if n not in original}
    # dis.opmap is a read-only frozendict on CPython 3.15, so swap the attribute, not the contents.
    dis.opmap = {**original, **missing}
    try:
        import battlecode26.__main__ as engine_main
    finally:
        dis.opmap = original
    return engine_main


def apply_unix_socket(path: str):
    """Make the engine client connect to a unix socket (no network access needed)."""
    import battlecode26.crossplay as cp

    def connect(self):
        while True:
            try:
                self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                self.sock.connect(path)
                return
            except (FileNotFoundError, ConnectionRefusedError):
                self.sock.close()
                time.sleep(0.1)
            except Exception as e:
                raise cp.CrossPlayException(f"Failed to connect to engine bridge: {e}")

    cp.CrossPlayClient.connect = connect


def apply_socket_tuning():
    import battlecode26.crossplay as cp

    orig_connect = cp.CrossPlayClient.connect

    def connect(self):
        orig_connect(self)
        if self.sock.family == socket.AF_INET:
            self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    def send_json(self, data):
        if self.sock is None:
            raise cp.CrossPlayException("Socket not connected")
        body = json.dumps(data).encode("utf-8")
        try:
            self.sock.sendall(struct.pack(">I", len(body)) + body)
        except Exception as e:
            raise cp.CrossPlayException(f"Failed to send data: {e}")

    quickack = getattr(socket, "TCP_QUICKACK", None)

    def recv_exactly(self, n):
        if self.sock is None:
            raise cp.CrossPlayException("Socket not connected")
        buf = bytearray()
        use_quickack = quickack is not None and self.sock.family == socket.AF_INET
        while len(buf) < n:
            if use_quickack:
                self.sock.setsockopt(socket.IPPROTO_TCP, quickack, 1)
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise cp.CrossPlayException("Socket connection closed unexpectedly")
            buf += chunk
        if use_quickack:
            self.sock.setsockopt(socket.IPPROTO_TCP, quickack, 1)
        return bytes(buf)

    cp.CrossPlayClient.connect = connect
    cp.CrossPlayClient.send_json = send_json
    cp.CrossPlayClient.recv_exactly = recv_exactly


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--teamA", default="/")
    p.add_argument("--teamB", default="/")
    p.add_argument("--dirA", default="src")
    p.add_argument("--dirB", default="src")
    p.add_argument("--debug", action="store_true")
    p.add_argument("--no-socket-tuning", action="store_true")
    p.add_argument("--limits", type=Path, help="limits profile JSON (see limits.provisional.json)")
    p.add_argument("--measure", action="store_true", help="record usage even without --limits")
    p.add_argument("--in-sandbox", action="store_true", help="running inside sandbox.py's user namespace")
    p.add_argument("--ipc-socket", help="unix socket path for the engine connection")
    a = p.parse_args(argv)
    engine_main = import_engine()
    if a.ipc_socket:
        apply_unix_socket(a.ipc_socket)
    if not a.no_socket_tuning:
        apply_socket_tuning()
    guard = None
    if a.limits or a.measure:
        guard_mod = _load_sibling("guard")
        limits = guard_mod.load_profile(a.limits)[0] if a.limits else None
        guard = guard_mod.Guard(limits)
        guard_mod.install(engine_main, guard)
        if limits is not None:
            guard_mod.apply_rlimits(limits, in_user_namespace=a.in_sandbox)  # after the imports above: they need more address space
        guard.start()
    try:
        engine_main.play(team_a=a.teamA, team_b=a.teamB, dir_a=a.dirA, dir_b=a.dirB, debug=a.debug)
    finally:
        if guard is not None:
            guard.stop()
            guard.emit_usage()
    return 0


if __name__ == "__main__":
    sys.exit(main())
