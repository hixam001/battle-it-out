# SPDX-License-Identifier: AGPL-3.0-only
# Test bot: one huge allocation (far above the address-space limit): expect MemoryError, not a host problem.
from battlecode26 import *


def turn():
    x = [0] * 4000000000
