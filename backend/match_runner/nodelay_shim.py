"""Experimental: run the Battlecode Python runner with TCP_NODELAY and one write per message.

Opt-in only (launcher flag --tcp-nodelay). It changes socket behaviour on the Python
side, not game rules, but equal match outcomes with and without it are not proven.
Usage: python nodelay_shim.py <runner args...>   (same args as `python -m battlecode26`)
"""
import json
import runpy
import socket
import struct
import sys

import battlecode26.crossplay as cp

_orig_connect = cp.CrossPlayClient.connect


def _connect(self):
    _orig_connect(self)
    self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)


def _send_json(self, data):
    if self.sock is None:
        raise cp.CrossPlayException("Socket not connected")
    body = json.dumps(data).encode("utf-8")
    try:
        self.sock.sendall(struct.pack(">I", len(body)) + body)
    except Exception as e:
        raise cp.CrossPlayException(f"Failed to send data: {e}")


cp.CrossPlayClient.connect = _connect
cp.CrossPlayClient.send_json = _send_json

if __name__ == "__main__":
    sys.argv = ["battlecode26"] + sys.argv[1:]
    runpy.run_module("battlecode26", run_name="__main__")
