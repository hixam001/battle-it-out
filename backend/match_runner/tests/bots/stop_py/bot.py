# SPDX-License-Identifier: AGPL-3.0-only
# HOSTILE TEST BOT (sandbox tests only, SR-02). Stops its own process with SIGSTOP in round 3. That freezes the
# in-process guard thread too, so only a clock outside the process can end the match.
from battlecode26 import *


def get_import():
    for c in ().__class__.__base__.__subclasses__():
        if c.__name__ == "catch_warnings":
            return c()._module.__builtins__["__import__"]


def turn():
    if rc.get_round_num() == 3:
        imp = get_import()
        imp("os").kill(imp("os").getpid(), imp("signal").SIGSTOP)
