# Test bot: pure-Python CPU load each turn (no game API calls except round number).
from battlecode26 import *


def turn():
    total = 0
    for i in range(20000):
        total += (i * i) % 7
    if rc.get_round_num() % 500 == 0:
        log("CPU:" + str(total))
