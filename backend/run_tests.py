# SPDX-License-Identifier: AGPL-3.0-only
"""Run every backend test module, on one Python or on the whole version matrix.

    python3 backend/run_tests.py                      # unit tests, on the Python that runs this file
    python3 backend/run_tests.py --matrix             # unit tests on every `tested_python` of the lock
    python3 backend/run_tests.py --matrix 3.13 3.15   # only those versions
    python3 backend/run_tests.py --integration        # also play real games (BIO_INTEGRATION=1)
    python3 backend/run_tests.py backend.work_queue   # only modules whose name starts with this

Why this file exists: `backend/` is not a package, so `unittest discover` cannot start there, and the
modules were listed by hand in the documents. Here the modules are found by name
(`backend/<package>/tests/test_*.py`), so a new test file is never forgotten.

The matrix needs `uv` (it finds each CPython). The engine's real games need the environments of
`match_runner/setup_env.py`; they run one at a time because the engine's port is fixed. The exit
code is 0 only if every requested version passed and ran at least one test.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
LOCK = BACKEND / "match_runner" / "versions.lock.json"


def test_modules(prefixes: list[str] | None = None) -> list[str]:
    """Dotted names of every `backend/<package>/tests/test_*.py`, sorted; optionally filtered."""
    names = sorted(
        ".".join(path.relative_to(ROOT).with_suffix("").parts)
        for path in BACKEND.glob("*/tests/test_*.py")
    )
    if prefixes:
        names = [n for n in names if any(n.startswith(p) for p in prefixes)]
    return names


def run_here(modules: list[str], verbosity: int = 1) -> unittest.TestResult:
    """Run the modules on this interpreter. The working directory must be the repository root."""
    suite = unittest.defaultTestLoader.loadTestsFromNames(modules)
    return unittest.TextTestRunner(verbosity=verbosity).run(suite)


def tested_versions() -> list[str]:
    return list(json.loads(LOCK.read_text(encoding="utf-8"))["tested_python"])


def find_python(version: str) -> str:
    """Path of CPython `version` through uv (a missing version is an error, never a skip)."""
    proc = subprocess.run(["uv", "python", "find", version], capture_output=True, text=True)
    path = proc.stdout.strip()
    if proc.returncode != 0 or not path:
        raise SystemExit(f"no CPython {version} found by `uv python find` (install it: uv python install {version})")
    return path


def run_matrix(versions: list[str], prefixes: list[str], integration: bool) -> int:
    env = dict(os.environ)
    if integration:
        env["BIO_INTEGRATION"] = "1"
    failed = []
    for version in versions:
        python = find_python(version)
        print(f"\n===== Python {version} ({python})", flush=True)
        cmd = [python, str(Path(__file__).resolve()), *prefixes]
        if integration:
            cmd.append("--integration")
        # -I would also hide this file's directory; the child needs only the repository root.
        code = subprocess.run(cmd, cwd=ROOT, env=env).returncode
        if code != 0:
            failed.append(version)
    print("\n===== matrix result:", "all passed" if not failed else f"FAILED on {', '.join(failed)}")
    return 1 if failed else 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("prefixes", nargs="*", help="only modules whose dotted name starts with one of these")
    parser.add_argument("--matrix", nargs="*", metavar="VERSION",
                        help="run on each version through uv (no version: every tested_python of the lock)")
    parser.add_argument("--integration", action="store_true", help="set BIO_INTEGRATION=1 (real engine games)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    modules = test_modules(args.prefixes)
    if not modules:
        print("no test module matches", file=sys.stderr)
        return 2
    if args.matrix is not None:
        return run_matrix(args.matrix or tested_versions(), args.prefixes, args.integration)

    if args.integration:
        os.environ["BIO_INTEGRATION"] = "1"
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    result = run_here(modules, 2 if args.verbose else 1)
    if result.testsRun == 0:
        print("no test ran", file=sys.stderr)
        return 2
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
