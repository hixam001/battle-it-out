# SPDX-License-Identifier: AGPL-3.0-only
# HOSTILE TEST BOT (sandbox tests only, SR-03). Sends a well-formed frame with an engine method number that does
# not exist. The Java server crashes on it, which used to be reported as a platform failure (a free replay).
from battlecode26 import *


def get_import():
    for c in ().__class__.__base__.__subclasses__():
        if c.__name__ == "catch_warnings":
            return c()._module.__builtins__["__import__"]


def turn():
    if rc.get_round_num() == 5:
        get_import()("battlecode26").crossplay._client.send_json({"method": 9999, "params": []})
