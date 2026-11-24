# SPDX-License-Identifier: AGPL-3.0-only
# Test bot: keeps allocating ~80 MB per turn and never frees it (resident memory grows without bound).
from battlecode26 import *

hog = []


def turn():
    hog.append([0] * 10000000)
