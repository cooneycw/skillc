#!/usr/bin/env python3
"""CI gate (#73, #439): a PR touching `skillc/` must add a changelog
FRAGMENT, `changelog.d/<issue>.md` (or `changelog.d/<issue>-<slug>.md`), or
say why not.

#439: the gate used to require a new line in CHANGELOG.md's single
`## [Unreleased]` section. Every PR then edited the same top lines, so after
each merge every queued branch conflicted there, and resolving by "keep both
sides" (or `merge=union`) can silently splice two bullets that share a first or
last line. A fragment is a file only its own PR writes, so it cannot conflict
or splice; `ci/changelog_assemble.py` folds the fragments into CHANGELOG.md at
release. An edit to the Unreleased section no longer satisfies this gate.

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

import argparse
import os
import re
import subprocess
import sys
from collections.abc import Mapping

ESCAPE_TRAILER = "changelog-exempt"
FRAGMENT_DIR = "changelog.d"
#: `changelog.d/<issue>.md`, or `<issue>-<slug>.md` for a second PR on the
#: same issue. `changelog.d/README.md` (the rule itself) never matches.
FRAGMENT_RE = re.compile(r"^changelog\.d/([0-9]+)(-[a-z0-9-]+)?\.md$")
# git-status(1) porcelain-v1 table: ordinary index/worktree states plus seven
# unmerged pairs and untracked. --no-renames excludes R/C; ignored is not asked for.
_STATUS_PAIRS = {
    b" M", b" T", b" A", b" D", b"D ", b"??",
    b"DD", b"AU", b"UD", b"UA", b"DU", b"AA", b"UU",
    *(bytes((index, worktree)) for index in b"MTA" for worktree in b" MTD"),
}

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


def is_fragment(path: str) -> bool:
    return FRAGMENT_RE.fullmatch(path) is not None


def fragment_problem(text: str) -> str | None:
    """None for a usable fragment: EXACTLY one Markdown bullet - a `- ` first
    line, then every non-blank line indented by two spaces (blank lines
    between indented paragraphs are fine; several existing entries use them).
    The whole shape is checked, not just the first line: a fragment that
    slipped a `## [x.y.z]` heading or a second top-level bullet past the gate
    would be folded above the existing Unreleased entries at release (#439
    counter-model review). Surrounding blank lines are ignored."""
    lines = text.strip("\n").splitlines()
    if not any(line.strip() for line in lines):
        return "is empty"
    # Exactly "- " then text: a wider marker ("-   x") moves the item's content
    # column to 4, so a two-space-indented "## [x.y.z]" would escape the list
    # and become a real section heading; a bare "- " is no note at all (#439
    # counter-model review, pass 2). With a 2-column marker, the two-space
    # continuation rule below is exactly CommonMark's.
    if not re.match(r"- \S", lines[0]):
        return f"must start with '- ' followed directly by the note, not {lines[0][:40]!r}"
    for number, line in enumerate(lines[1:], start=2):
        if line.strip() and not line.startswith("  "):
            return f"line {number} is not a two-space continuation of the one bullet: {line[:40]!r}"
    return None


def _new_lines(base: str, head: str) -> set[str]:
    base_lines = {line.strip() for line in base.splitlines() if line.strip()}
    head_lines = {line.strip() for line in head.splitlines() if line.strip()}
    return head_lines - base_lines


def missing_changelog_entry(
    changed_files: list[str],
    base_fragments: Mapping[str, str],
    head_fragments: Mapping[str, str],
    head_commit_message: str,
) -> str | None:
    """None when compliant; otherwise a detail string naming the violation.

    `head_fragments` maps each changed fragment path that exists on this
    branch to its content; `base_fragments` maps the same paths to their
    merge-base content where one existed (a new fragment is absent there).
    A fragment counts when it is well formed and carries a non-blank line its
    merge-base version did not - a deletion or reformat is not an entry.
    """
    if not touches_skillc(changed_files):
        return None
    if has_escape_trailer(head_commit_message):
        return None
    problems: list[str] = []
    for path in sorted(head_fragments):
        if not is_fragment(path):
            continue
        problem = fragment_problem(head_fragments[path])
        if problem:
            problems.append(f"{path} {problem}")
            continue
        if _new_lines(base_fragments.get(path, ""), head_fragments[path]):
            return None
    if problems:
        return "skillc/ changed but its changelog fragment is malformed: " + "; ".join(problems)
    return (
        f"skillc/ changed but no {FRAGMENT_DIR}/<issue>.md fragment was added or extended - "
        f"an edit to CHANGELOG.md's [Unreleased] section no longer counts (#439)"
    )


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


def _pending_inputs() -> list[str]:
    """Git's nonignored pending inputs, never filesystem fragment contents.

    No rename collapsing: both ends must remain visible, even across scope.
    Warnings may mean incomplete enumeration, so they are not a clean result.
    """
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all",
         "--no-renames", "--", "skillc", FRAGMENT_DIR], capture_output=True, check=False,
    )
    if result.returncode or result.stderr:
        raise ValueError(f"incomplete git status: {result.stderr!r} (exit {result.returncode})")
    raw = result.stdout
    if raw and not raw.endswith(b"\0"):
        raise ValueError("truncated git status")
    pending = []
    for entry in raw.split(b"\0")[:-1]:
        if len(entry) < 4 or entry[2:3] != b" " or entry[:2] not in _STATUS_PAIRS:
            raise ValueError(f"malformed git status: {entry!r}")
        path = os.fsdecode(entry[3:])
        if any(part in ("", ".", "..") for part in path.split("/")):
            raise ValueError(f"malformed git path: {path!r}")
        if not (touches_skillc([path]) or path == FRAGMENT_DIR or path.startswith(FRAGMENT_DIR + "/")):
            raise ValueError(f"unexpected git status path: {path!r}")
        if touches_skillc([path]) or is_fragment(path):
            pending.append(f"{entry[:2].decode('ascii')} {path!r}")
    return pending


def _clean_input_problem(head: str) -> str | None:
    try:
        pending = _pending_inputs()
        current = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
        if current.returncode or current.stderr or current.stdout.strip() != head:
            return "HEAD changed or could not be read"
    except (OSError, ValueError) as exc:
        return str(exc)
    return "pending committed-check inputs: " + ", ".join(pending) if pending else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base", nargs="?", default="origin/main")
    parser.add_argument("--require-clean-inputs", action="store_true",
                        help="refuse relevant pending Git inputs; does not evaluate their contents")
    args = parser.parse_args(argv)
    base = args.base
    try:
        head_sha = _git("rev-parse", "HEAD").strip()
    except (OSError, SystemExit) as exc:
        if not args.require_clean_inputs:
            raise
        print(f"changelog-check: REFUSED - committed HEAD unavailable: {exc}", file=sys.stderr)
        return 2

    def refused() -> bool:
        problem = _clean_input_problem(head_sha)
        if problem:
            print(f"changelog-check: REFUSED - {problem}; checkpoint relevant changes first",
                  file=sys.stderr)
        return problem is not None

    print(f"changelog-check: source=committed HEAD={head_sha} base={base!r} "
          f"require-clean-inputs={args.require_clean_inputs}")
    if args.require_clean_inputs and refused():
        return 2

    merge_base = _merge_base(base)
    if merge_base is None:
        print(
            f"changelog-check: could not find a merge-base between {base!r} and "
            f"HEAD - fetch more history and retry; refusing rather than comparing "
            f"against the wrong thing",
            file=sys.stderr,
        )
        return 2
    print(f"changelog-check: merge-base={merge_base}")

    changed_files = [
        line for line in _git("diff", "--name-only", merge_base, "HEAD").splitlines() if line
    ]
    base_fragments: dict[str, str] = {}
    head_fragments: dict[str, str] = {}
    for path in changed_files:
        if not is_fragment(path):
            continue
        head = _show("HEAD", path)
        if head is None:
            continue  # deleted on this branch: not an entry
        head_fragments[path] = head
        base_text = _show(merge_base, path)
        if base_text is not None:
            base_fragments[path] = base_text
    head_commit_message = _git("log", "-1", "--format=%B", "HEAD")

    problem = missing_changelog_entry(changed_files, base_fragments, head_fragments, head_commit_message)
    if problem:
        print(f"changelog-check: FAIL - {problem}", file=sys.stderr)
        print(
            f"changelog-check: add {FRAGMENT_DIR}/<issue>.md with one '- ' bullet "
            f"(see {FRAGMENT_DIR}/README.md), or add a '{ESCAPE_TRAILER.title()}: <reason>' "
            f"trailer to your last commit",
            file=sys.stderr,
        )
        return 1
    if args.require_clean_inputs and refused():
        return 2
    print("changelog-check: ok (committed inputs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
