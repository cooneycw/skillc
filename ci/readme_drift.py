#!/usr/bin/env python3
"""README drift checks (#73): commands, version, and status vs. milestones.

Each check compares README.md against something ELSE that can go stale
independently of it - the real argparse parser, the package's own version,
and a committed milestones file - never against itself. `tests/
test_readme_drift.py` holds the committed red/good cases per ADR 0001.

No GitHub network access: the status check reads `docs/milestones.json`,
which an operator updates by hand when a milestone issue closes (#72's
release checklist), never a live `gh`/API call.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _marked_block(text: str, name: str) -> str | None:
    """Text between `<!-- {name}:start ... -->` and `<!-- {name}:end -->`."""
    pattern = re.compile(
        rf"<!--\s*{re.escape(name)}:start.*?-->\n(.*?)\n<!--\s*{re.escape(name)}:end\s*-->",
        re.DOTALL,
    )
    match = pattern.search(text)
    return match.group(1) if match else None


# --------------------------------------------------------------- commands


def real_commands(parser: argparse.ArgumentParser) -> set[str]:
    """The subcommand names the real CLI actually registers."""
    # argparse exposes no public API for "the registered subparsers"; walking
    # _actions for a _SubParsersAction is the well-known, stable way every
    # introspecting CLI tool does this.
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return set(action.choices)
    return set()


def readme_commands(readme_text: str) -> set[str] | None:
    """The subcommand names named in the marked `commands` block, or None if
    the block is missing entirely (a different failure from an empty list)."""
    block = _marked_block(readme_text, "commands")
    if block is None:
        return None
    return {
        m.group(1) for line in block.splitlines()
        if (m := re.match(r"^skillc ([a-z][a-z-]*)\b", line.strip()))
    }


def command_drift(readme_text: str, real: set[str]) -> list[str]:
    if not real:
        # Never actually empty (skillc always registers subcommands), but a
        # comparison against an empty population proves nothing either way -
        # refuse rather than let it read as a match (cross-model review).
        return ["no real commands were discovered from the argparse parser"]
    documented = readme_commands(readme_text)
    if documented is None:
        return ["README has no <!-- commands:start --> ... <!-- commands:end --> block"]
    if not documented:
        return ["README's commands block names no commands - an empty block cannot match"]
    problems = []
    missing = sorted(real - documented)
    if missing:
        problems.append(f"README omits real command(s): {missing}")
    extra = sorted(documented - real)
    if extra:
        problems.append(f"README lists command(s) that do not exist: {extra}")
    return problems


# ----------------------------------------------------------------- version


_VERSION_LINE_RE = re.compile(r"\*\*Version:\*\*\s*`([^`]+)`")


def readme_version(readme_text: str) -> str | None:
    match = _VERSION_LINE_RE.search(readme_text)
    return match.group(1) if match else None


def version_drift(readme_text: str, package_version: str) -> list[str]:
    """[] when README states no version at all (nothing to contradict) or a
    matching one; a problem when it states a DIFFERENT one."""
    stated = readme_version(readme_text)
    if stated is None or stated == package_version:
        return []
    return [f"README states version {stated!r}, package is {package_version!r}"]


# ------------------------------------------------------------------ status


def readme_milestones(readme_text: str) -> dict[str, str] | None:
    """{row text (everything before the state column) -> state}, from the
    marked `milestones` table, or None if the block is missing."""
    block = _marked_block(readme_text, "milestones")
    if block is None:
        return None
    rows: dict[str, str] = {}
    for line in block.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 2 or cells[0] in ("Milestone", "---") or set(cells[0]) <= {"-"}:
            continue
        rows[cells[0]] = cells[1]
    return rows


def status_drift(readme_text: str, milestones_data: dict[str, object]) -> list[str]:
    rows = readme_milestones(readme_text)
    if rows is None:
        return ["README has no <!-- milestones:start --> ... <!-- milestones:end --> block"]
    if not rows:
        return ["README's milestones table has no rows - an empty table cannot match"]
    entries = milestones_data.get("milestones")
    if not isinstance(entries, list) or not entries:
        # A malformed-only list (see below) is caught separately, so this is
        # specifically "no list, or a list with nothing in it at all" -
        # cross-model review: an empty population must not read as a match.
        return ["docs/milestones.json has no non-empty 'milestones' list"]
    problems = []
    file_by_label: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            problems.append(f"docs/milestones.json has a non-object milestone entry: {entry!r}")
            continue
        label = f"{entry.get('version')} - {entry.get('label')}"
        file_by_label[label] = str(entry.get("state"))
    if not file_by_label:
        problems.append("docs/milestones.json's 'milestones' list has no usable entries")
    for label, file_state in file_by_label.items():
        readme_state = rows.get(label)
        if readme_state is None:
            problems.append(f"docs/milestones.json has {label!r}, missing from README's table")
        elif readme_state != file_state:
            problems.append(
                f"README says {label!r} is {readme_state!r}, "
                f"docs/milestones.json says {file_state!r}"
            )
    for label in rows:
        if label not in file_by_label:
            problems.append(f"README's table has {label!r}, missing from docs/milestones.json")
    return problems


# --------------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    root = Path(args[0]) if args else ROOT

    from skillc import __version__
    from skillc.cli import build_parser

    readme_text = (root / "README.md").read_text(encoding="utf-8")
    milestones_data = json.loads((root / "docs" / "milestones.json").read_text(encoding="utf-8"))
    pyproject_version = tomllib.loads(
        (root / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]["version"]

    problems = [
        *command_drift(readme_text, real_commands(build_parser())),
        *version_drift(readme_text, __version__),
        *status_drift(readme_text, milestones_data),
    ]
    if pyproject_version != __version__:
        # Not this script's job to re-litigate #73's own version check (tests/
        # test_version.py), but a silently stale __version__ would make the
        # version_drift check above compare README against the wrong thing.
        problems.append(
            f"skillc.__version__ ({__version__!r}) differs from pyproject.toml "
            f"({pyproject_version!r}); fix that before trusting this check's version drift"
        )
    if problems:
        print("readme-drift: FAIL", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("readme-drift: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
