# SPDX-License-Identifier: AGPL-3.0-only
"""Static check of a participant bot against the Battlecode engine's own bot policy (BIO-201).

Standard library only. Runs on any Python 3.12+, but syntax is checked by the interpreter that
runs the validator, so run it with the same Python that will run the bots (the lock's primary).

    python3 backend/bot_validator/validator.py PATH [--fail-on-warning]

PATH is a `bot.py` file or a directory that must contain exactly `bot.py`. Output is JSON; exit
code 0 if there are no errors, 1 otherwise, 2 if the input could not be read.

This is a best-effort early check, not a security boundary. The engine stays authoritative for what
runs, and host-level isolation and time limits are separate work (BIO-203/204, DEC-04).
Errors are things the engine would reject or fail on. Warnings are things the engine allows but
that matter for isolation.
"""
from __future__ import annotations

import ast
import json
import os
import stat
import sys
from pathlib import Path

POLICY_PATH = Path(__file__).resolve().parent / "policy.json"
# Safety ceiling for what the validator will even read (SR-04, CN-008). This is NOT the product's upload
# limit (policy `max_bytes`, still an owner decision, DEC): it only keeps a hostile file from using the
# validator's memory. A policy limit may be lower, never higher.
HARD_READ_LIMIT = 2 << 20


def load_policy(path: Path = POLICY_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _finding(code: str, message: str, node: ast.AST | None = None) -> dict:
    return {"code": code, "line": getattr(node, "lineno", None), "message": message}


class _Binder(ast.NodeVisitor):
    """Collects every name the module binds in any scope (an over-approximation, on purpose)."""

    def __init__(self) -> None:
        self.bound: set[str] = set()
        self.star_from_engine = False

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.bound.add(node.id)

    def visit_arg(self, node: ast.arg) -> None:
        self.bound.add(node.arg)

    def _def(self, node) -> None:
        self.bound.add(node.name)
        self.generic_visit(node)

    visit_FunctionDef = visit_AsyncFunctionDef = visit_ClassDef = _def

    def visit_Import(self, node: ast.Import) -> None:
        for a in node.names:
            self.bound.add((a.asname or a.name).split(".")[0])

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for a in node.names:
            if a.name == "*":
                self.star_from_engine = self.star_from_engine or node.module == "battlecode26"
            else:
                self.bound.add(a.asname or a.name)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name:
            self.bound.add(node.name)
        self.generic_visit(node)

    def visit_MatchAs(self, node) -> None:
        if node.name:
            self.bound.add(node.name)
        self.generic_visit(node)

    def visit_MatchStar(self, node) -> None:
        if node.name:
            self.bound.add(node.name)

    def visit_MatchMapping(self, node) -> None:
        if node.rest:
            self.bound.add(node.rest)
        self.generic_visit(node)

    def visit_Global(self, node: ast.Global) -> None:
        self.bound.update(node.names)

    visit_Nonlocal = visit_Global


def validate_source(source: str, policy: dict | None = None, *, require_entry_point: bool = True) -> dict:
    policy = policy or load_policy()
    errors: list[dict] = []
    warnings: list[dict] = []

    max_bytes = policy.get("max_bytes")
    if max_bytes is not None and len(source.encode("utf-8")) > max_bytes:
        errors.append(_finding("E-SIZE", f"source is larger than {max_bytes} bytes"))

    try:
        tree = ast.parse(source, filename=policy["bot_file"])
        compile(tree, policy["bot_file"], "exec")
    except SyntaxError as e:
        errors.append({"code": "E-SYNTAX", "line": e.lineno, "message": f"{e.msg}"})
        return {"ok": False, "errors": errors, "warnings": warnings}
    except (RecursionError, MemoryError, ValueError, OverflowError) as e:   # too deep or NUL bytes: not a crash
        errors.append({"code": "E-SYNTAX", "line": None, "message": f"the source cannot be parsed ({type(e).__name__})"})
        return {"ok": False, "errors": errors, "warnings": warnings}
    try:
        return _check_tree(tree, policy, errors, warnings, require_entry_point=require_entry_point)
    except RecursionError:     # a tree that parses but is too deep for the visitors
        errors.append({"code": "E-SYNTAX", "line": None, "message": "the source is nested too deeply to check"})
        return {"ok": False, "errors": errors, "warnings": warnings}


def _check_tree(tree: ast.AST, policy: dict, errors: list, warnings: list, *, require_entry_point=True) -> dict:

    entry = policy["entry_point"]
    turns = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == entry]
    if require_entry_point and not turns:
        errors.append(_finding("E-NO-TURN", f"no top-level function {entry}()"))
    elif require_entry_point and turns:
        t = turns[-1]
        a = t.args
        if isinstance(t, ast.AsyncFunctionDef):
            errors.append(_finding("E-TURN-SIGNATURE", f"{entry}() must not be async", t))
        if a.posonlyargs or a.args or a.vararg or a.kwonlyargs or a.kwarg:
            errors.append(_finding("E-TURN-SIGNATURE", f"{entry}() must take no parameters", t))

    allowed_imports = set(policy["allowed_imports"])
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name not in allowed_imports:
                    errors.append(_finding("E-IMPORT", f"import of '{alias.name}' is not allowed "
                                           f"(allowed: {', '.join(sorted(allowed_imports))})", node))
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                errors.append(_finding("E-IMPORT", "relative imports are not allowed", node))
            elif node.module not in allowed_imports:
                errors.append(_finding("E-IMPORT", f"import from '{node.module}' is not allowed "
                                       f"(allowed: {', '.join(sorted(allowed_imports))})", node))

    binder = _Binder()
    binder.visit(tree)
    known = set(binder.bound) | set(policy["allowed_builtins"]) | set(policy["engine_globals"]) \
        | set(policy["allowed_dunder_names"]) | set(policy["battlecode26_exports"])
    risky_names = set(policy["risky_names"])
    risky_attrs = set(policy["risky_attributes"])
    seen_names: set[tuple[str, int | None]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            if node.id not in known and (node.id, node.lineno) not in seen_names:
                seen_names.add((node.id, node.lineno))
                errors.append(_finding("E-NAME", f"'{node.id}' is not defined for bots in the engine "
                                       "(it would raise NameError at run time)", node))
            if node.id in risky_names:
                warnings.append(_finding("W-RISKY-NAME", f"'{node.id}' is allowed by the engine but "
                                         "matters for isolation", node))
        elif isinstance(node, ast.Attribute) and node.attr in risky_attrs:
            warnings.append(_finding("W-RISKY-ATTRIBUTE", f"attribute '{node.attr}' is allowed by the "
                                     "engine but is the usual way out of a sandbox", node))
    return {"ok": not errors, "errors": errors, "warnings": warnings}


def validate_path(path: Path, policy: dict | None = None) -> dict:
    policy = policy or load_policy()
    bot_file = policy["bot_file"]
    if path.is_dir():
        entries = sorted(p.name for p in path.iterdir() if not p.name.startswith("."))
        extra = [e for e in entries if e != bot_file]
        problems = []
        if bot_file not in entries:
            problems.append(_finding("E-FILES", f"the directory has no {bot_file}"))
        if extra:
            problems.append(_finding("E-FILES", f"only {bot_file} is allowed; also found: {', '.join(extra)}"))
        if bot_file not in entries:
            return {"ok": False, "errors": problems, "warnings": []}
        if (path / bot_file).is_symlink() or (path / bot_file).is_dir():   # a link or folder named bot.py
            problems.append(_finding("E-FILES", f"{bot_file} must be a regular file, not a link or folder"))
            return {"ok": False, "errors": problems, "warnings": []}
        result = validate_path(path / bot_file, policy)
        result["errors"] = problems + result["errors"]
        result["ok"] = not result["errors"]
        return result
    if path.name != bot_file:
        return {"ok": False, "errors": [_finding("E-FILES", f"the file must be named {bot_file}, not {path.name}")],
                "warnings": []}
    raw = _read_regular_file(path)
    if isinstance(raw, dict):
        return raw
    try:
        source = raw.decode("utf-8")
    except UnicodeDecodeError:
        return {"ok": False, "errors": [_finding("E-ENCODING", "the file is not valid UTF-8")], "warnings": []}
    return validate_source(source, policy)


def _read_regular_file(path: Path) -> bytes | dict:
    """Read at most HARD_READ_LIMIT bytes from a regular file, never following a link and never blocking.

    A symlink (to /dev/zero or a host file), a FIFO or a device would otherwise hang the validator or fill
    its memory. Returns the bytes, or a finished validation result describing the refusal.
    """
    def refuse(code: str, message: str) -> dict:
        return {"ok": False, "errors": [_finding(code, message)], "warnings": []}

    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0))
    except OSError as e:     # ELOOP for a symlink, ENXIO and friends for special files
        return refuse("E-FILES", f"{path.name} must be a regular file, not a link or special file ({e.strerror})")
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return refuse("E-FILES", f"{path.name} must be a regular file")
        data = os.read(fd, HARD_READ_LIMIT + 1)
        while len(data) <= HARD_READ_LIMIT:
            more = os.read(fd, HARD_READ_LIMIT + 1 - len(data))
            if not more:
                break
            data += more
    finally:
        os.close(fd)
    if len(data) > HARD_READ_LIMIT:
        return refuse("E-SIZE", f"the file is larger than the validator's safety ceiling of {HARD_READ_LIMIT} bytes")
    return data


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    strict = "--fail-on-warning" in args
    args = [a for a in args if a != "--fail-on-warning"]
    if len(args) != 1:
        print(__doc__)
        return 2
    path = Path(args[0])
    if not path.exists():
        print(json.dumps({"ok": False, "errors": [_finding("E-FILES", f"{path} does not exist")], "warnings": []}, indent=2))
        return 2
    result = validate_path(path)
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] and not (strict and result["warnings"]) else 1


if __name__ == "__main__":
    sys.exit(main())
