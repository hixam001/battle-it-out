# SPDX-License-Identifier: AGPL-3.0-only
# HOSTILE TEST BOT (failure-classification tests only). Reaches the real __import__ through the engine's
# attribute-walk hole and ends its whole runner process abruptly in round 5, the way a crashing C extension
# or an operating-system kill would. The engine cannot catch this.
from battlecode26 import *


def get_import():
    for c in ().__class__.__base__.__subclasses__():
        if c.__name__ == "catch_warnings":
            return c()._module.__builtins__["__import__"]


def turn():
    if rc.get_round_num() == 5:
        os = get_import()("os")
        os._exit(3)
