#!/usr/bin/env python3
"""Freeze, or check, a trimmed claude-power-pack snapshot at one pinned commit.

Every byte comes from git's object store at the named revision (`git ls-tree`
plus `git cat-file blob`), never from a working tree, so a dirty or
checked-out-elsewhere CPP checkout cannot leak into a fixture. The path list
for each fixture is declared here, so a snapshot is reproducible from this
file and any CPP clone that holds the revision (skillc#280).

    python3 scripts/freeze_cpp_fixture.py freeze profile-cpp-codex-cicd-86641e8 --cpp ~/Projects/claude-power-pack
    python3 scripts/freeze_cpp_fixture.py check  profile-cpp-codex-cicd-86641e8 --cpp ~/Projects/claude-power-pack

`freeze` refuses an existing destination. `check` exits 1 naming every file
that is missing, extra or byte-different against the pin.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = ROOT / "tests" / "fixtures"

#: fixture name -> (pinned revision, paths under the CPP root; a directory
#: means every tracked file beneath it).
FIXTURES: dict[str, tuple[str, tuple[str, ...]]] = {
    "profile-cpp-codex-cicd-86641e8": (
        "86641e817711d8a7746270745a5dfa7cacf04b0c",
        (
            "CLAUDE.md",
            "pyproject.toml",
            "uv.lock",
            "lib/cicd",
            "templates/Makefile.example",
            "templates/cicd.yml.example",
            "templates/makefiles",
            "codex/skills/cicd-init",
            "codex/skills/cicd-check",
            "codex/skills/cicd-health",
            "codex/skills/cicd-smoke",
            "codex/skills/cicd-verify",
            "codex/skills/cicd-pipeline",
        ),
    ),
}

#: Generated beside a fixture when a test runs uv/python in it; never source.
GENERATED_PARTS = frozenset({".venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"})


class FreezeError(RuntimeError):
    """The snapshot cannot be produced or checked as declared."""


def _git(cpp: Path, *args: str) -> bytes:
    result = subprocess.run(["git", "-C", str(cpp), *args], capture_output=True, check=False)
    if result.returncode != 0:
        raise FreezeError(f"git {args[0]} failed: {result.stderr.decode(errors='replace').strip()}")
    return result.stdout


def pinned_files(cpp: Path, revision: str, paths: tuple[str, ...]) -> dict[str, tuple[str, bytes]]:
    """`{relpath: (mode, bytes)}` for every tracked blob under `paths` at `revision`."""
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise FreezeError("revision must be a full 40-character commit id")
    if _git(cpp, "cat-file", "-t", revision).strip() != b"commit":
        raise FreezeError(f"{revision} is not a commit in {cpp}")
    files: dict[str, tuple[str, bytes]] = {}
    for path in paths:
        rows = [row for row in _git(cpp, "ls-tree", "-r", "-z", revision, "--", path).split(b"\0") if row]
        if not rows:
            raise FreezeError(f"{path} is not tracked at {revision}")
        for row in rows:
            meta, name = row.split(b"\t", 1)
            mode, kind, blob = meta.decode().split()
            if kind != "blob" or mode not in ("100644", "100755"):
                raise FreezeError(f"{name.decode()} is a {mode} {kind}, not a regular file")
            files[name.decode()] = (mode, _git(cpp, "cat-file", "blob", blob))
    return files


def _on_disk(dest: Path) -> dict[str, bytes]:
    return {
        q.relative_to(dest).as_posix(): q.read_bytes()
        for q in dest.rglob("*")
        if q.is_file() and not GENERATED_PARTS.intersection(q.relative_to(dest).parts)
    }


def freeze(name: str, cpp: Path, dest: Path) -> int:
    revision, paths = FIXTURES[name]
    files = pinned_files(cpp, revision, paths)
    if dest.exists():
        raise FreezeError(f"{dest} already exists; remove it first or use check")
    for relpath, (mode, data) in sorted(files.items()):
        target = dest / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        target.chmod(0o755 if mode == "100755" else 0o644)
    return len(files)


def check(name: str, cpp: Path, dest: Path) -> list[str]:
    revision, paths = FIXTURES[name]
    expected = {k: v for k, (_, v) in pinned_files(cpp, revision, paths).items()}
    actual = _on_disk(dest)
    problems = [f"missing: {k}" for k in sorted(expected.keys() - actual.keys())]
    problems += [f"extra: {k}" for k in sorted(actual.keys() - expected.keys())]
    problems += [f"differs: {k}" for k in sorted(expected.keys() & actual.keys()) if expected[k] != actual[k]]
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=("freeze", "check"))
    parser.add_argument("fixture", choices=sorted(FIXTURES))
    parser.add_argument("--cpp", type=Path, required=True, help="a claude-power-pack clone holding the revision")
    parser.add_argument("--dest", type=Path, help="default: tests/fixtures/<fixture>")
    args = parser.parse_args(argv)
    dest = args.dest or FIXTURES_DIR / args.fixture
    try:
        if args.action == "freeze":
            print(f"froze {freeze(args.fixture, args.cpp, dest)} files into {dest}")
            return 0
        problems = check(args.fixture, args.cpp, dest)
    except FreezeError as exc:
        print(f"freeze_cpp_fixture: {exc}", file=sys.stderr)
        return 2
    for problem in problems:
        print(problem)
    print("snapshot matches the pin" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
