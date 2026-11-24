# Test bot: runs once (first turn of each robot) and logs deterministic "FT:" lines covering
# language features and sandbox probes, so output can be compared across Python versions.
from battlecode26 import *
from random import seed, randint
from math import sqrt, gcd, floor

done = False


def fib(n):
    return n if n < 2 else fib(n - 1) + fib(n - 2)


class Base:
    def __init__(self, x):
        self.x = x

    def double(self):
        return self.x * 2

    def __repr__(self):
        return "Base(" + str(self.x) + ")"


class Child(Base):
    def __init__(self, x, y):
        Base.__init__(self, x)
        self.y = y

    def total(self):
        return self.x + self.y


class Boom(Exception):
    pass


def gen(n):
    for i in range(n):
        yield i * i


def make_counter():
    c = 0

    def inc(step=1):
        nonlocal c
        c += step
        return c
    return inc


def kinds(v):
    match v:
        case [a, b]:
            return "pair" + str(a + b)
        case {"k": val}:
            return "dict" + str(val)
        case int() as i if i > 10:
            return "big"
        case _:
            return "other"


def probe(name, fn):
    try:
        r = fn()
        log("FT:probe." + name + "=allowed(" + r.__class__.__name__ + ")")
    except BaseException as e:
        log("FT:probe." + name + "=blocked(" + e.__class__.__name__ + ")")


def turn():
    global done
    if done:
        return
    done = True
    L = lambda k, v: log("FT:" + k + "=" + str(v))
    tot = 0
    for i in range(1000):
        tot += i * i
    L("arith", (tot, 2 ** 100, 7 // 2, -7 // 2, 7 % 3, round(2.5), round(3.5), divmod(17, 5)))
    L("float", (0.1 + 0.2, 1 / 3, f"{3.14159:.2f}", float("1e3"), int("42") + 1))
    L("str", ("abc".upper(), ",".join([str(i) for i in range(5)]), "hello world"[3:8], "a-b-c".split("-"), "x".center(5, "*")))
    L("coll", (sorted({3: "c", 1: "a", 2: "b"}.items()), sorted({5, 3, 9} | {1}), [x * 2 for x in range(5) if x % 2 == 0], {k: k * k for k in range(4)}))
    L("zip", (list(zip("ab", [1, 2])), list(enumerate("xy", 1)), sorted(["bb", "a", "ccc"], key=lambda s: -len(s))))
    c = Child(3, 4)
    L("class", (c, c.double(), c.total(), isinstance(c, Base)))
    gt = 0
    for v in gen(100):
        gt += v
    L("gen", (list(gen(5)), gt))
    inc = make_counter()
    inc(); inc(5)
    L("closure", inc())
    try:
        try:
            raise Boom("x")
        finally:
            log("FT:finally=ran")
    except Boom as e:
        L("exc", repr(e))
    L("walrus", [y for x in range(5) if (y := x * 3) > 4])
    L("match", (kinds([1, 2]), kinds({"k": 7}), kinds(99), kinds("s")))
    L("fib", fib(20))
    seed(1)
    L("random", [randint(0, 100) for _ in range(5)])
    L("math", (sqrt(144), gcd(84, 36), floor(-2.5)))
    L("args", (lambda *a, **k: (a, sorted(k.items())))(1, 2, z=3, y=4))

    def imp(mod):
        return __import__(mod)
    probe("import_os", lambda: imp("os"))
    probe("import_sys", lambda: imp("sys"))
    probe("import_math", lambda: imp("math"))
    probe("open_is_callable", lambda: open if callable(open) else 1 / 0)
    probe("dunder_class_walk", lambda: ().__class__.__base__.__subclasses__())
    probe("eval", lambda: eval("1+1"))
    probe("exec", lambda: exec("x=1"))
    probe("builtin_sum", lambda: sum([1]))
    probe("builtin_max", lambda: max(1, 2))
    probe("builtin_dict", lambda: dict(a=1))
    probe("builtin_map", lambda: map(str, [1]))
    probe("builtin_super", lambda: super)
    probe("builtin_type", lambda: type(1))
    probe("builtin_print", lambda: print("x"))
    probe("builtin_getattr", lambda: getattr(1, "real"))
    probe("builtin_setattr", lambda: setattr)
