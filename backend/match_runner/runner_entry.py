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

Usage: python runner_entry.py --teamA NAME --teamB NAME --dirA DIR --dirB DIR [--no-socket-tuning]
"""
from __future__ import annotations

import argparse
import dis
import json
import socket
import struct
import sys

_OPCODE_NAMES_NEEDED = [
    "CACHE", "JUMP_FORWARD", "POP_JUMP_IF_FALSE", "POP_JUMP_IF_TRUE", "LOAD_GLOBAL", "COPY",
    "LOAD_FAST", "STORE_FAST", "GET_AWAITABLE", "KW_NAMES", "EXTENDED_ARG", "RESUME",
]


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


def apply_socket_tuning():
    import battlecode26.crossplay as cp

    orig_connect = cp.CrossPlayClient.connect

    def connect(self):
        orig_connect(self)
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
        while len(buf) < n:
            if quickack is not None:
                self.sock.setsockopt(socket.IPPROTO_TCP, quickack, 1)
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise cp.CrossPlayException("Socket connection closed unexpectedly")
            buf += chunk
        if quickack is not None:
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
    a = p.parse_args(argv)
    engine_main = import_engine()
    if not a.no_socket_tuning:
        apply_socket_tuning()
    engine_main.play(team_a=a.teamA, team_b=a.teamB, dir_a=a.dirA, dir_b=a.dirB, debug=a.debug)
    return 0


if __name__ == "__main__":
    sys.exit(main())
