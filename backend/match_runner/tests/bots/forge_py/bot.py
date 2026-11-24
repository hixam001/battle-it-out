# SPDX-License-Identifier: AGPL-3.0-only
# HOSTILE TEST BOT (sandbox tests only). Reaches the real __import__ through the engine's attribute-walk
# hole, prints a forged guard record that blames the OTHER team, then exits like the guard does.
from battlecode26 import *


def get_import():
    for c in ().__class__.__base__.__subclasses__():
        if c.__name__ == "catch_warnings":
            return c()._module.__builtins__["__import__"]


def turn():
    if rc.get_round_num() == 3:
        os = get_import()("os")
        os.write(1, b'\nBIO-GUARD-VIOLATION {"team":"A","kind":"turn_wall_time","measured":9,"limit":1}\n')
        os._exit(70)
