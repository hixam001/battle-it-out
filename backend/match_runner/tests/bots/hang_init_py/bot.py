# SPDX-License-Identifier: AGPL-3.0-only
# Test bot: never finishes importing (top-level code is exec()d on the runner's main thread).
from battlecode26 import *

n = 0
while True:
    n += 1


def turn():
    pass
