#!/usr/bin/env python3
"""CI gate (#73): a PR touching `skillc/` must add an `Unreleased` CHANGELOG
entry, or say why not.

The check is pure and testable without git (`missing_changelog_entry` below;
`tests/test_changelog_check.py` holds the committed red/good cases per ADR
0001). `main` is the thin CLI wrapper that gets real inputs from git and is
what CI actually runs.

Escape hatch: a `Changelog-exempt: <reason>` trailer in the PR's HEAD commit
message. Checked on HEAD only, not the whole commit range - a shallow clone
of the feature branch is not guaranteed to expose earlier commits, but HEAD's
own message always is. Put the trailer in your last commit.

Diffing uses a two-dot tree comparison (`git diff BASE HEAD`), never
three-dot (`BASE...HEAD`): three-dot needs a merge-base, which a shallow clone
may not have; two-dot compares the two tree snapshots directly and needs
nothing but both trees, which a clone always has for its own HEAD and any ref
it fetched.
"""

from __future__ import annotations

import re
import subprocess
import sys

ESCAPE_TRAILER = "changelog-exempt"

_UNRELEASED_RE = re.compile(r"^## \[Unreleased\]\s*\n(.*?)(?=^## \[|\Z)", re.MULTILINE | re.DOTALL)


def touches_skillc(changed_files: list[str]) -> bool:
    return any(f == "skillc" or f.startswith("skillc/") for f in changed_files)


def unreleased_section(changelog_text: str) -> str:
    """The text between the `## [Unreleased]` heading and the next `## [` one."""
    match = _UNRELEASED_RE.search(changelog_text)
    return match.group(1).strip() if match else ""


def has_escape_trailer(commit_message: str) -> bool:
    return any(
        line.strip().lower().startswith(f"{ESCAPE_TRAILER}:")
        for line in commit_message.splitlines()
    )


def missing_changelog_entry(
    changed_files: list[str],
    base_changelog: str | None,
    head_changelog: str | None,
    head_commit_message: str,
) -> str | None:
    """None when compliant; otherwise a detail string naming the violation.

    `base_changelog` is the target branch's CHANGELOG.md content, or None if
    it does not exist there (a repository's first PR touching skillc/).
    `head_changelog` is this branch's own, or None if it was deleted.
    """
    if not touches_skillc(changed_files):
        return None
    if has_escape_trailer(head_commit_message):
        return None
    if head_changelog is None:
        return "skillc/ changed but CHANGELOG.md does not exist on this branch"
    head_section = unreleased_section(head_changelog)
    if base_changelog is not None and unreleased_section(base_changelog) == head_section:
        return (
            "skillc/ changed but CHANGELOG.md's [Unreleased] section is "
            "unchanged from the target branch"
        )
    if not head_section:
        return "skillc/ changed but CHANGELOG.md's [Unreleased] section is empty"
    return None


def _git(*args: str) -> str:
    result = subprocess.run(["git", *args], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise SystemExit(f"changelog-check: git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def _show(ref: str, path: str) -> str | None:
    result = subprocess.run(
        ["git", "show", f"{ref}:{path}"], capture_output=True, text=True, check=False
    )
    return result.stdout if result.returncode == 0 else None


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    base = args[0] if args else "origin/main"
    changed_files = [line for line in _git("diff", "--name-only", base, "HEAD").splitlines() if line]
    base_changelog = _show(base, "CHANGELOG.md")
    head_changelog = _show("HEAD", "CHANGELOG.md")
    head_commit_message = _git("log", "-1", "--format=%B", "HEAD")

    problem = missing_changelog_entry(changed_files, base_changelog, head_changelog, head_commit_message)
    if problem:
        print(f"changelog-check: FAIL - {problem}", file=sys.stderr)
        print(
            f"changelog-check: add an entry under CHANGELOG.md's [Unreleased] "
            f"section, or add a '{ESCAPE_TRAILER.title()}: <reason>' trailer "
            f"to your last commit",
            file=sys.stderr,
        )
        return 1
    print("changelog-check: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
