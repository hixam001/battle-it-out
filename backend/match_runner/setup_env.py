"""Create a pinned, reproducible Python environment for the match launcher.

    python3 backend/match_runner/setup_env.py 3.15          # -> backend/.venvs/py3.15
    python3 backend/match_runner/setup_env.py 3.14 3.13 3.12

What it does (requires `uv`): downloads the engine's Python package from the official release URL
in versions.lock.json (or reuses a cached copy), checks its SHA-256, creates the venv with the
requested CPython, and installs the package with --no-deps plus the pinned dependencies. The engine
package declares Requires-Python >=3.12,<3.13, which is why --no-deps is used; whether it really
works on a newer CPython is shown by the launcher's test matches, not by the installer.
"""
from __future__ import annotations

import subprocess
import sys
import urllib.request
from pathlib import Path

try:
    from backend.match_runner import launcher as L
except ModuleNotFoundError:  # run as a script
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from backend.match_runner import launcher as L

CACHE = L.HERE.parent / ".cache"
VENVS = L.HERE.parent / ".venvs"


def fetch_artifact(lock: dict) -> Path:
    pkg = lock["engine_package"]
    # Keep the upstream file name: uv reads the version from it, and the package metadata (1.2.2)
    # differs from the release number (1.2.6), so a versioned file name would be rejected.
    path = CACHE / f"engine-{lock['engine_version']}" / "battlecode.tar.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or L.sha256_of(path) != pkg["artifact_sha256"]:
        print(f"downloading {pkg['artifact_url']}")
        urllib.request.urlretrieve(pkg["artifact_url"], path)
    got = L.sha256_of(path)
    if got != pkg["artifact_sha256"]:
        path.unlink(missing_ok=True)
        raise SystemExit(f"SHA-256 mismatch for engine package: {got}")
    return path


def make_env(version: str, lock: dict) -> Path:
    artifact = fetch_artifact(lock)
    venv = VENVS / f"py{version}"
    subprocess.run(["uv", "venv", "--quiet", "--allow-existing", "--python", version, str(venv)], check=True)
    py = str(venv / "bin" / "python")
    subprocess.run(["uv", "pip", "install", "--quiet", "--python", py, "--no-deps", str(artifact)], check=True)
    deps = [f"{k}=={v}" for k, v in lock["dependencies"].items()]
    subprocess.run(["uv", "pip", "install", "--quiet", "--python", py, *deps], check=True)
    return venv


def main(argv: list[str]) -> int:
    lock = L.load_lock()
    versions = argv or [lock["primary_python"]]
    for v in versions:
        print(f"creating env for Python {v} ...")
        print(make_env(v, lock))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
