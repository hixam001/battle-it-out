# SPDX-License-Identifier: AGPL-3.0-only
"""Measure repeated sandboxed control matches without changing the limits profile."""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import statistics
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from backend.match_runner import launcher as L


FIXTURES = {
    "reference": L.DEFAULT_SCAFFOLD / "src" / "examplefuncsplayer_py" / "bot.py",
    "cpu-load": Path(__file__).resolve().parent / "tests" / "bots" / "cpuload_py" / "bot.py",
}
PAIRINGS = {"reference": ("reference", "reference"), "cpu_load": ("reference", "cpu-load")}


def measure(py: Path, repetitions: int, map_name: str) -> dict:
    lock = L.load_lock()
    report = {
        "started_at": datetime.now(UTC).isoformat(),
        "system": {"kernel": platform.release(), "architecture": platform.machine(),
                   "available_cpus": len(os.sched_getaffinity(0))},
        "runtime": {"engine": lock["engine_version"], "engine_python_package": lock["engine_package"]["metadata_version"],
                    "dependencies": lock["dependencies"]},
        "map": map_name,
        "cases": {},
    }
    with tempfile.TemporaryDirectory(prefix="bio-resource-measurement-") as directory:
        root = Path(directory)
        bots = root / "bots"
        limits = root / L.DEFAULT_LIMITS.name
        shutil.copyfile(L.DEFAULT_LIMITS, limits)
        report["limits_sha256"] = L.sha256_of(limits)
        for name, source in FIXTURES.items():
            folder = bots / name
            folder.mkdir(parents=True)
            shutil.copyfile(source, folder / "bot.py")
        report["bot_sha256"] = {name: L.sha256_of(bots / name / "bot.py") for name in FIXTURES}
        for case, pairing in PAIRINGS.items():
            samples = []
            for n in range(repetitions):
                sides = pairing if n % 2 == 0 else pairing[::-1]
                result = L.run_match(L.DEFAULT_SCAFFOLD, py, bots, *sides, map_name,
                                     root / case / str(n + 1), timeout=1800, offline=True,
                                     socket_tuning=True, sandbox=True, limits_path=limits)
                fields = ("outcome", "classification", "python", "round", "seconds", "usage", "cgroup")
                sample = {key: result[key] for key in fields}
                sample["sides"] = dict(zip("AB", sides))
                samples.append(sample)
            completed = [sample for sample in samples if sample["outcome"] == "completed"]
            report["cases"][case] = {
                "samples": samples,
                "completed": len(completed),
                "median_completed_seconds": (
                    round(statistics.median(sample["seconds"] for sample in completed), 3) if completed else None
                ),
            }
    return report


def main(argv: list[str] | None = None) -> int:
    lock = L.load_lock()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python-version", choices=lock["tested_python"], default=lock["primary_python"])
    parser.add_argument("--runs", type=int, default=5, help="repetitions per pairing")
    parser.add_argument("--map", default="DefaultSmall", help="one bundled engine map name")
    args = parser.parse_args(argv)
    if args.runs < 1:
        parser.error("--runs must be positive")
    if not args.map or "," in args.map:
        parser.error("--map must be a single map")
    try:
        py = L.resolve_python(args.python_version, None, lock)
        report = measure(py, args.runs, args.map)
    except L.LauncherError as exc:
        parser.exit(2, f"{exc}\n")
    print(json.dumps(report, indent=2))
    return int(any(case["completed"] != args.runs for case in report["cases"].values()))


if __name__ == "__main__":
    raise SystemExit(main())
