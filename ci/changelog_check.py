#!/usr/bin/env python3
"""CI gate (#73): a PR touching `skillc/` must add an `Unreleased` CHANGELOG
entry, or say why not.

The check is pure and testable without git (`missing_changelog_entry` below;
`tests/test_changelog_check.py` holds the committed red/good cases per ADR
0001). `main` is the thin CLI wrapper that gets real inputs from git and is
what CI actually runs.

Escape hatch: a `Changelog-exempt: <reason>` trailer in the PR's HEAD commit
message, with a non-empty reason - an empty `Changelog-exempt:` would exempt
silently, defeating the point of asking for a reason. Checked on HEAD's
message only, not the whole commit range - a shallow clone of the feature
branch is not guaranteed to expose earlier commits, but HEAD's own message
always is. Put the trailer in your last commit.

Diffing anchors on the MERGE-BASE of the target branch and HEAD, found
explicitly via `git merge-base`, then diffs merge-base..HEAD with a plain
two-ref comparison (never the `BASE...HEAD` three-dot form, which computes
the same merge-base internally but gives no way to detect and refuse when it
cannot be found). Diffing against the target branch's current TIP instead -
the first version of this script did - misattributes changes: if main moves
ahead of a not-yet-rebased branch, its diff would show main's own later
changes as if this branch made them (touching skillc/ it never touched), and
a changelog entry that landed on main after this branch forked would let an
unrelated PR's Unreleased edit satisfy this one's requirement. When no
merge-base can be found (a clone too shallow to share history with the
target), this refuses (exit 2) rather than silently comparing the wrong
thing - the same "unscannable is UNKNOWN, never clean" rule `skillc leak-check`
already follows (#63).
"""

from __future__ import annotations

import re
import subprocess
import sys

ESCAPE_TRAILER = "changelog-exempt"

_UNRELEASED_RE = re.compile(r"^## \[Unreleased\]\s*\n(.*?)(?=^## \[|\Z)", re.MULTILINE | re.DOTALL)
_TRAILER_LINE_RE = re.compile(rf"^{ESCAPE_TRAILER}\s*:\s*(.+)$", re.IGNORECASE)


def touches_skillc(changed_files: list[str]) -> bool:
    return any(f == "skillc" or f.startswith("skillc/") for f in changed_files)


def unreleased_section(changelog_text: str) -> str:
    """The text between the `## [Unreleased]` heading and the next `## [` one."""
    match = _UNRELEASED_RE.search(changelog_text)
    return match.group(1).strip() if match else ""


def has_escape_trailer(commit_message: str) -> bool:
    """True only for a `Changelog-exempt: <non-empty reason>` line in the
    message's LAST paragraph (its trailer block), never one merely quoted or
    described earlier in the body, and never an empty reason."""
    paragraphs = re.split(r"\n\s*\n", commit_message.strip())
    if not paragraphs:
        return False
    last = paragraphs[-1]
    return any(_TRAILER_LINE_RE.match(line.strip()) for line in last.splitlines())


def _added_lines(base_section: str, head_section: str) -> set[str]:
    base_lines = {line.strip() for line in base_section.splitlines() if line.strip()}
    head_lines = {line.strip() for line in head_section.splitlines() if line.strip()}
    return head_lines - base_lines


def missing_changelog_entry(
    changed_files: list[str],
    base_changelog: str | None,
    head_changelog: str | None,
    head_commit_message: str,
) -> str | None:
    """None when compliant; otherwise a detail string naming the violation.

    `base_changelog` is the merge-base's CHANGELOG.md content, or None if it
    does not exist there (a repository's first PR touching skillc/).
    `head_changelog` is this branch's own, or None if it was deleted.
    """
    if not touches_skillc(changed_files):
        return None
    if has_escape_trailer(head_commit_message):
        return None
    if head_changelog is None:
        return "skillc/ changed but CHANGELOG.md does not exist on this branch"
    head_section = unreleased_section(head_changelog)
    if not head_section:
        return "skillc/ changed but CHANGELOG.md's [Unreleased] section is empty"
    base_section = unreleased_section(base_changelog) if base_changelog is not None else ""
    if not _added_lines(base_section, head_section):
        return (
            "skillc/ changed but CHANGELOG.md's [Unreleased] section gained no "
            "new line since the merge-base - a deletion or reformat is not an entry"
        )
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


def _merge_base(base_ref: str, head_ref: str = "HEAD") -> str | None:
    result = subprocess.run(
        ["git", "merge-base", base_ref, head_ref], capture_output=True, text=True, check=False
    )
    sha = result.stdout.strip()
    return sha if result.returncode == 0 and sha else None


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    base = args[0] if args else "origin/main"

    merge_base = _merge_base(base)
    if merge_base is None:
        print(
            f"changelog-check: could not find a merge-base between {base!r} and "
            f"HEAD - fetch more history and retry; refusing rather than comparing "
            f"against the wrong thing",
            file=sys.stderr,
        )
        return 2

    changed_files = [
        line for line in _git("diff", "--name-only", merge_base, "HEAD").splitlines() if line
    ]
    base_changelog = _show(merge_base, "CHANGELOG.md")
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
