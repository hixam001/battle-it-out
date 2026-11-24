# SPDX-License-Identifier: AGPL-3.0-only
"""Helper shared by tests and manual runs: stage the hostile escape bot with real values filled in."""
from __future__ import annotations

import socket
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent


class HostListener:
    """A TCP listener on the host's loopback. A sandboxed bot must never reach it."""

    def __init__(self):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(5)
        self.port = self.sock.getsockname()[1]
        self.hits = 0
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while True:
            try:
                c, _ = self.sock.accept()
            except OSError:
                return
            self.hits += 1
            c.close()

    def close(self):
        self.sock.close()


def stage_escape_bot(bots_dir: Path, canary: Path, port: int, forks: int, repo: Path) -> None:
    dest = bots_dir / "escape_py"
    dest.mkdir(parents=True, exist_ok=True)
    text = (HERE / "bots" / "escape_py" / "bot.py").read_text()
    for key, value in (("__CANARY__", str(canary)), ("__PORT__", str(port)), ("__FORKS__", str(forks)),
                       ("__REPO__", str(repo))):
        text = text.replace(key, value)
    (dest / "bot.py").write_text(text)


def probe_lines(server_log: Path) -> dict[str, str]:
    out = {}
    for line in server_log.read_text(errors="replace").splitlines():
        if "PROBE " in line:
            body = line.split("PROBE ", 1)[1]
            name, _, rest = body.partition(" ")
            out[name] = rest
    return out
