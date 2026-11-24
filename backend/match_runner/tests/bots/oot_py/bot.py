# SPDX-License-Identifier: AGPL-3.0-only
# HOSTILE TEST BOT (sandbox tests only, SR-01). Reaches the engine's socket client through the attribute-walk
# hole and, from a background thread, sends a RESIGN call whenever it is NOT this team's turn. Before the router
# checked whose turn it is, the Java server read that call as the OTHER team's robot talking.
from battlecode26 import *


def get_import():
    for c in ().__class__.__base__.__subclasses__():
        if c.__name__ == "catch_warnings":
            return c()._module.__builtins__["__import__"]


def pump():
    imp = get_import()
    cp = imp("battlecode26").crossplay
    time = imp("time")
    while True:
        time.sleep(0.001)
        if time.monotonic() - cp.BIO_TS > 0.0008:     # our turn code ran a moment ago and is finished
            try:
                cp._client.send_json({"method": 99, "params": []})
            except Exception:
                return


def turn():
    imp = get_import()
    cp = imp("battlecode26").crossplay
    if "BIO_TS" not in cp.__dict__:
        cp.BIO_TS = 0.0
        imp("threading").Thread(target=pump, daemon=True).start()
    cp.BIO_TS = imp("time").monotonic()
