#!/usr/bin/env python3
"""Fold `changelog.d/` fragments into CHANGELOG.md (#439). Run at release.

Each PR adds its release note as its own file, `changelog.d/<issue>.md` or
`changelog.d/<issue>-<slug>.md` (`ci/changelog_check.py` requires one for a
PR touching `skillc/`). Nothing edits CHANGELOG.md between releases, so
nothing conflicts there. This step, part of the #72 release checklist, puts
every fragment at the TOP of `## [Unreleased]` - ordered by issue number,
then by file name, so two fragments for one issue land in a fixed order -
and deletes the fragments. The release then moves Unreleased under the new
version heading as before.

All-or-nothing: every fragment is validated and the new CHANGELOG.md text is
computed before anything is written, so a malformed fragment refuses the run
with no partial result. Existing Unreleased entries are kept, below the new
ones.

Usage: python3 ci/changelog_assemble.py [--check] [repo-root]
  --check  report what would be folded in; write nothing
"""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):  # run as a script: make `ci` importable
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ci.changelog_check import FRAGMENT_DIR, FRAGMENT_RE, fragment_problem

UNRELEASED_HEADING = "## [Unreleased]"


class AssembleError(ValueError):
    """The fragments or CHANGELOG.md cannot be assembled; nothing was written."""


def fragment_order(name: str) -> tuple[int, str]:
    """`changelog.d/<issue>[-slug].md` sorts by issue number, then by name."""
    match = FRAGMENT_RE.fullmatch(f"{FRAGMENT_DIR}/{name}")
    if match is None:
        raise AssembleError(f"{FRAGMENT_DIR}/{name} is not a fragment name")
    return int(match.group(1)), name


def assemble(changelog_text: str, fragments: dict[str, str]) -> str:
    """CHANGELOG.md's new text: every fragment at the top of Unreleased, in
    `fragment_order`, each ending with exactly one newline. Pure."""
    for name in sorted(fragments):
        problem = fragment_problem(fragments[name])
        if problem:
            raise AssembleError(f"{FRAGMENT_DIR}/{name} {problem}")
    lines = changelog_text.splitlines(keepends=True)
    try:
        heading = next(i for i, line in enumerate(lines) if line.rstrip("\n") == UNRELEASED_HEADING)
    except StopIteration:
        raise AssembleError(f"CHANGELOG.md has no '{UNRELEASED_HEADING}' heading") from None
    insert_at = heading + 1
    while insert_at < len(lines) and not lines[insert_at].strip():
        insert_at += 1  # past the blank line(s) under the heading
    block = "".join(fragments[name].strip("\n") + "\n" for name in sorted(fragments, key=fragment_order))
    prefix = "".join(lines[:heading + 1]) + "\n"
    return prefix + block + "".join(lines[insert_at:])


def _fragments(root: Path) -> dict[str, Path]:
    directory = root / FRAGMENT_DIR
    if not directory.is_dir():
        return {}
    return {p.name: p for p in sorted(directory.iterdir())
            if p.is_file() and FRAGMENT_RE.fullmatch(f"{FRAGMENT_DIR}/{p.name}")}


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    check = "--check" in args
    args = [a for a in args if a != "--check"]
    root = Path(args[0]) if args else Path(__file__).resolve().parent.parent
    changelog = root / "CHANGELOG.md"
    if not changelog.is_file():
        # A mistyped root must not read as "nothing to do" (#439 review).
        print(f"changelog-assemble: REFUSED - no CHANGELOG.md at {root}; not a repository root", file=sys.stderr)
        return 2
    paths = _fragments(root)
    if not paths:
        print(f"changelog-assemble: no fragments under {FRAGMENT_DIR}/; nothing to do")
        return 0
    try:
        text = assemble(changelog.read_text(encoding="utf-8"),
                        {name: path.read_text(encoding="utf-8") for name, path in paths.items()})
    except AssembleError as exc:
        print(f"changelog-assemble: REFUSED - {exc}; nothing was written", file=sys.stderr)
        return 1
    ordered = sorted(paths, key=fragment_order)
    if check:
        print(f"changelog-assemble: would fold {len(ordered)} fragment(s): {', '.join(ordered)}")
        return 0
    changelog.write_text(text, encoding="utf-8")
    for name in ordered:
        paths[name].unlink()
    print(f"changelog-assemble: folded {len(ordered)} fragment(s) into CHANGELOG.md: {', '.join(ordered)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
