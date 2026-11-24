# Test bot: never returns from turn(). Shows whether the engine limits pure-Python computation.
from battlecode26 import *


def turn():
    n = 0
    while True:
        n += 1
