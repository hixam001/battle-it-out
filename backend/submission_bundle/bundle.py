# SPDX-License-Identifier: AGPL-3.0-only
"""Bounded flat Python bundles using the engine's native module loader (CN-028)."""
from __future__ import annotations

import ast
import hashlib
import io
import json
import os
import re
import stat
import zipfile
from pathlib import Path

from backend.bot_validator import validator as V

MANIFEST = "bundle.json"
MAX_FILES, MAX_BYTES = 32, 256 * 1024  # interim ceilings, including dependency source
MODULE = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}\.py\Z")
HELPERS = b'''# Platform curated biohelpers 1.0.0; SPDX-License-Identifier: AGPL-3.0-only
def manhattan(a, b):
    return abs(a.x - b.x) + abs(a.y - b.y)
def chebyshev(a, b):
    return max_pair(abs(a.x - b.x), abs(a.y - b.y))
def max_pair(a, b):
    return a if a > b else b
def clamp(value, low, high):
    return low if value < low else high if value > high else value
'''
CATALOGUE = {"biohelpers": {"version": "1.0.0", "sha256": hashlib.sha256(HELPERS).hexdigest(),
                            "description": "Grid distances and numeric clamping", "source": HELPERS}}
RESERVED = {"random.py", "math.py", "enum.py", "battlecode26.py", "biohelpers.py"}


class Invalid(ValueError):
    pass


def digest(files: dict[str, bytes]) -> str:
    hashes = {name: hashlib.sha256(raw).hexdigest() for name, raw in sorted(files.items())}
    return hashlib.sha256(json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def unpack(raw: bytes) -> dict[str, bytes]:
    """Never extract an archive onto disk or install participant dependencies."""
    if len(raw) > MAX_BYTES:
        raise Invalid("ZIP exceeds the interim 256 KiB limit")
    files = {}
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            if not 1 <= len(entries) <= MAX_FILES:
                raise Invalid("a bundle needs 1–32 files")
            for item in entries:
                name = item.filename
                kind = (item.external_attr >> 16) & 0o170000
                if item.is_dir() or kind not in (0, stat.S_IFREG) or item.flag_bits & 1 \
                        or name in files or not (MODULE.fullmatch(name) or name == "requirements.json") \
                        or name in RESERVED:
                    raise Invalid("use unique flat Python modules; links, reserved names and paths are forbidden")
                if item.file_size > MAX_BYTES or sum(map(len, files.values())) + item.file_size > MAX_BYTES:
                    raise Invalid("expanded bundle exceeds the interim 256 KiB limit")
                with archive.open(item) as stream:
                    data = stream.read(MAX_BYTES + 1)
                if len(data) != item.file_size or len(data) > MAX_BYTES:
                    raise Invalid("invalid or oversized ZIP member")
                files[name] = data
    except (zipfile.BadZipFile, RuntimeError, OSError, NotImplementedError) as exc:
        raise Invalid("invalid or unsupported ZIP archive") from exc
    if "bot.py" not in files:
        raise Invalid("the bundle needs bot.py with turn()")
    try:
        requirements = json.loads(files.pop("requirements.json", b"{}"))
    except (ValueError, UnicodeError) as exc:
        raise Invalid("requirements.json must map curated names to exact versions") from exc
    if not isinstance(requirements, dict):
        raise Invalid("requirements.json must be an object")
    for name, version in requirements.items():
        if name not in CATALOGUE or version != CATALOGUE[name]["version"]:
            raise Invalid("only exact versions from the published curated catalogue are allowed")
        files[name + ".py"] = CATALOGUE[name]["source"]
    files[MANIFEST] = json.dumps({"schema": 1, "dependencies": requirements,
                                 "files": sorted(files)}, sort_keys=True, separators=(",", ":")).encode()
    validate(files)
    return files


def validate(files: dict[str, bytes]) -> None:
    if not 2 <= len(files) <= MAX_FILES + 2 or sum(map(len, files.values())) > MAX_BYTES:
        raise Invalid("bundle exceeds interim file/byte ceilings")
    try:
        manifest = json.loads(files[MANIFEST])
        modules = {name[:-3] for name in files if MODULE.fullmatch(name)}
        if manifest.get("schema") != 1 or set(manifest) != {"schema", "dependencies", "files"} \
                or set(manifest["files"]) != set(files) - {MANIFEST} or "bot.py" not in files \
                or any(name != MANIFEST and not MODULE.fullmatch(name) for name in files):
            raise Invalid("bundle manifest does not match its files")
        dependencies = manifest["dependencies"]
        if not isinstance(dependencies, dict):
            raise Invalid("invalid dependencies")
        for name in RESERVED:
            if name in files:
                info = CATALOGUE.get(name[:-3])
                if not info or dependencies.get(name[:-3]) != info["version"] or files[name] != info["source"]:
                    raise Invalid("reserved module or changed curated dependency")
        for name, version in dependencies.items():
            if name not in CATALOGUE or version != CATALOGUE[name]["version"] or name + ".py" not in files:
                raise Invalid("unknown or missing curated dependency")
        graph = {}
        for name, raw in files.items():
            if name == MANIFEST:
                continue
            source = raw.decode("utf-8")
            policy = {**V.load_policy(), "allowed_imports": sorted(set(V.load_policy()["allowed_imports"]) | modules)}
            checked = V.validate_source(source, policy, require_entry_point=(name == "bot.py"))
            if not checked["ok"]:
                raise Invalid(name + ": " + "; ".join(e["message"] for e in checked["errors"])[:1000])
            imports = set()
            for node in ast.walk(ast.parse(source)):
                if isinstance(node, ast.Import):
                    imports.update(a.name for a in node.names)
                elif isinstance(node, ast.ImportFrom):
                    imports.add(node.module)
            graph[name[:-3]] = imports & modules
        def visit(name, visiting, visited):
            if name in visiting:
                raise Invalid("cyclic local imports are not supported by the engine")
            if name in visited:
                return
            for child in graph[name]:
                visit(child, visiting | {name}, visited)
            visited.add(name)
        visited = set()
        for name in graph:
            visit(name, set(), visited)
    except (ValueError, UnicodeError, KeyError, TypeError, RecursionError, SyntaxError) as exc:
        if isinstance(exc, Invalid):
            raise
        raise Invalid("invalid bundle metadata or Python source") from exc


def snapshot(folder: Path) -> dict[str, bytes]:
    """Read bounded regular files once; no links or extra unmanifested bytes."""
    if not stat.S_ISDIR(folder.lstat().st_mode):
        raise Invalid("bundle folder must be a real directory")
    names = os.listdir(folder)
    if len(names) > MAX_FILES + 2:
        raise Invalid("too many files")
    files = {}
    for name in sorted(names):
        if name != MANIFEST and not MODULE.fullmatch(name):
            raise Invalid("unexpected file in stored bundle")
        fd = os.open(folder / name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise Invalid("bundle members must be regular files")
            with os.fdopen(fd, "rb", closefd=False) as stream:
                files[name] = stream.read(MAX_BYTES + 1)
        finally:
            os.close(fd)
        if sum(map(len, files.values())) > MAX_BYTES:
            raise Invalid("stored bundle exceeds byte ceiling")
    validate(files)
    return files


def export(files: dict[str, bytes]) -> bytes:
    """Recreate the upload members with stable ordering and ZIP metadata."""
    dependencies = json.loads(files[MANIFEST])["dependencies"]
    members = {name: raw for name, raw in files.items()
               if name != MANIFEST and name[:-3] not in dependencies}
    if dependencies:
        members["requirements.json"] = json.dumps(
            dependencies, sort_keys=True, separators=(",", ":")
        ).encode()

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, raw in sorted(members.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3  # Unix permissions, independent of the exporting host.
            info.external_attr = (stat.S_IFREG | 0o600) << 16
            archive.writestr(info, raw, compress_type=zipfile.ZIP_DEFLATED)
    return output.getvalue()
