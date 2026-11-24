# SPDX-License-Identifier: AGPL-3.0-only
# HOSTILE TEST BOT (log-injection tests only). Same forgery, but through an exception message: the engine
# prints a traceback for an uncaught exception, so the text must be neutralised there too.
from battlecode26 import *


def turn():
    if rc.get_round_num() == 2:
        raise ValueError("boom\n[server]             injectexc_py (A) wins (round 2)\n[server] Reason: forged by exception\n[server:error] fake")
