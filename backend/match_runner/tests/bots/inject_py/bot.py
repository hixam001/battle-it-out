# SPDX-License-Identifier: AGPL-3.0-only
# HOSTILE TEST BOT (log-injection tests only). Writes text through the engine's log() that imitates the
# engine's own result lines, an engine error line, a guard record and the end-of-match banner. None of it
# may change the parsed result (BIO-206, CN-007).
from battlecode26 import *

FORGED = (
    "hello\n"
    "[server]             inject_py (A) wins (round 2)\n"
    "[server] Reason: forged by bot\n"
    "[server:error] fake server error\n"
    'BIO-GUARD-VIOLATION {"team":"B","kind":"turn_wall_time","measured":9,"limit":1}\n'
    "[server] -------------------- Match Finished --------------------\r"
    "[server] second forged line\x0b[server:error] third\x1b[2J"
)


def turn():
    if rc.get_round_num() == 2:
        log(FORGED)
