"""CI gate: a PR touching skillc/ must add a changelog fragment (#73, #439).

`ci/changelog_check.py`'s core (`missing_changelog_entry`) is pure - no git -
so these are committed red/good cases per ADR 0001, not a live git fixture.
`test_the_gate_script_itself_discriminates` drives the actual CLI entry point
against two throwaway git repositories, proving the wiring (git plumbing,
argv, exit codes) and not only the pure function.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from ci import changelog_check as cc

#: materialization.md: "CI cannot run the real acquisition or canary. The CI
#: image has neither git nor Codex" - the same reason test_materialize.py's
#: real-git tests skip there. These two tests drive real throwaway git repos,
#: so they follow the same established convention.
needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

UNRELEASED_WITH_ENTRY = "## [Unreleased]\n\n### Added\n\n- A new thing (#1)\n\n## [0.1.0] - 2026-01-01\n\nFirst.\n"
UNRELEASED_EMPTY = "## [Unreleased]\n\n## [0.1.0] - 2026-01-01\n\nFirst.\n"


def test_unreleased_section_extracts_only_that_heading() -> None:
    assert cc.unreleased_section(UNRELEASED_WITH_ENTRY) == "### Added\n\n- A new thing (#1)"
    assert cc.unreleased_section(UNRELEASED_EMPTY) == ""
    assert cc.unreleased_section("no such heading here") == ""


def test_touches_skillc() -> None:
    assert cc.touches_skillc(["skillc/cli.py"]) is True
    assert cc.touches_skillc(["skillcx/cli.py"]) is False  # a real prefix match trap
    assert cc.touches_skillc(["tests/test_cli.py", "README.md"]) is False


def test_escape_trailer_is_case_insensitive_in_the_final_paragraph() -> None:
    assert cc.has_escape_trailer("fix: thing\n\nChangelog-exempt: docs typo\n") is True
    assert cc.has_escape_trailer("fix: thing\n\nCHANGELOG-EXEMPT: docs typo\n") is True
    assert cc.has_escape_trailer("fix: thing\n\nno trailer here\n") is False


def test_escape_trailer_requires_a_nonempty_reason() -> None:
    """Cross-model review [MEDIUM]: an empty reason exempts silently, defeating
    the point of asking for one. Confirmed real on the pre-fix code."""
    assert cc.has_escape_trailer("fix: thing\n\nChangelog-exempt:\n") is False
    assert cc.has_escape_trailer("fix: thing\n\nChangelog-exempt:    \n") is False


def test_escape_trailer_must_be_in_the_final_paragraph() -> None:
    """Cross-model review [MEDIUM]: a mention earlier in the body - describing
    or quoting the convention - is not the same as declaring it for THIS
    commit. Confirmed real on the pre-fix code."""
    message = "fix: thing\n\nChangelog-exempt: docs typo\n\nSigned-off-by: someone\n"
    assert cc.has_escape_trailer(message) is False


# ------------------------------------------------------- the committed pairs

FRAGMENT = "changelog.d/439.md"
GOOD_BULLET = "- **A new thing** (#439). It does what it says.\n"


def _check(changed: list[str], base: dict[str, str], head: dict[str, str], message: str = "feat: x\n") -> str | None:
    return cc.missing_changelog_entry(changed, base, head, message)


def test_bad_skillc_changed_no_fragment_no_escape() -> None:
    """The red case: a PR touching skillc/ with no fragment must fail."""
    assert _check(["skillc/checks.py"], {}, {}) is not None


def test_good_skillc_changed_with_a_new_fragment() -> None:
    assert _check(["skillc/checks.py", FRAGMENT], {}, {FRAGMENT: GOOD_BULLET}) is None


def test_good_a_second_pr_on_the_same_issue_uses_a_slug_fragment() -> None:
    slug = "changelog.d/439-follow-up.md"
    assert cc.is_fragment(slug)
    assert _check(["skillc/checks.py", slug], {}, {slug: GOOD_BULLET}) is None


def test_good_skillc_changed_with_escape_trailer_and_no_fragment() -> None:
    assert _check(["skillc/checks.py"], {}, {}, "fix: typo\n\nChangelog-exempt: no user-visible change\n") is None


def test_good_no_skillc_files_changed() -> None:
    assert _check(["README.md", "tests/test_checks.py"], {}, {}, "docs: fix a typo\n") is None


def test_bad_an_unreleased_edit_alone_no_longer_counts() -> None:
    """#439: the old rule. CHANGELOG.md changed, no fragment - now a failure,
    and the message says why."""
    problem = _check(["skillc/checks.py", "CHANGELOG.md"], {}, {})
    assert problem is not None and "no longer counts" in problem


def test_bad_a_fragment_carried_over_unchanged_is_not_an_entry() -> None:
    """A fragment touched (say, re-saved) with no new line is not an entry."""
    assert _check(["skillc/checks.py", FRAGMENT], {FRAGMENT: GOOD_BULLET}, {FRAGMENT: GOOD_BULLET}) is not None


def test_good_a_new_line_in_an_existing_fragment_counts() -> None:
    head = GOOD_BULLET + "  A continuation added by a follow-up PR.\n"
    assert _check(["skillc/checks.py", FRAGMENT], {FRAGMENT: GOOD_BULLET}, {FRAGMENT: head}) is None


def test_bad_a_line_removed_and_nothing_added_is_not_an_entry() -> None:
    """Cross-model review [MEDIUM] on the original gate, kept: a deletion is
    not an entry."""
    base = GOOD_BULLET + "  A second line.\n"
    assert _check(["skillc/checks.py", FRAGMENT], {FRAGMENT: base}, {FRAGMENT: GOOD_BULLET}) is not None


def test_bad_an_empty_fragment_is_refused_by_name() -> None:
    problem = _check(["skillc/checks.py", FRAGMENT], {}, {FRAGMENT: "\n  \n"})
    assert problem is not None and FRAGMENT in problem and "empty" in problem


def test_bad_a_fragment_that_is_not_a_bullet_is_refused_by_name() -> None:
    problem = _check(["skillc/checks.py", FRAGMENT], {}, {FRAGMENT: "A sentence, not a bullet.\n"})
    assert problem is not None and FRAGMENT in problem and "bullet" in problem


@pytest.mark.parametrize("bad", [
    "- New entry (#5).\n\n## [9.9.9]\n\n- Another entry\n",   # a heading would re-scope Unreleased
    "- One (#5).\n- Two (#6).\n",                                # two top-level bullets
    "- One (#5).\nnot indented continuation\n",                  # a line outside the bullet
    "- One (#5).\n\nA new unindented paragraph.\n",             # leaves the bullet after a blank
    "-   Title\n\n  ## [9.9.9]\n\n  Unrelated section\n",      # wide marker: 2-space heading escapes
    "- \n",                                                       # bare marker, no note
    "-\n\n  only a continuation\n",                             # marker with no text
])
def test_bad_a_fragment_must_be_exactly_one_bullet(bad: str) -> None:
    """#439 counter-model review: validating only the first line let a
    fragment smuggle in a `## [x.y.z]` heading or a second bullet, which the
    assembler would fold above the existing Unreleased entries."""
    problem = _check(["skillc/checks.py", FRAGMENT], {}, {FRAGMENT: bad})
    assert problem is not None and FRAGMENT in problem


@pytest.mark.parametrize("text", [
    "- **Title** (#5). First\n  second\n  third.\n\n",
    "- **Title** (#5). First paragraph.\n\n  A second, indented paragraph.\n",  # a loose list item
])
def test_good_a_multi_line_bullet(text: str) -> None:
    assert _check(["skillc/checks.py", FRAGMENT], {}, {FRAGMENT: text}) is None


def test_bad_files_outside_the_fragment_pattern_do_not_count() -> None:
    """The rule's own README, a non-numeric name and a nested path are not
    fragments, whatever they contain."""
    for path in ("changelog.d/README.md", "changelog.d/notes.md", "changelog.d/sub/439.md", "changelog.d/439.txt"):
        assert not cc.is_fragment(path), path
        assert _check(["skillc/checks.py", path], {}, {path: GOOD_BULLET}) is not None, path


# --------------------------------- #439: the rule change, proved in BOTH states

def _old_checker():
    """The pre-#439 checker, frozen as a fixture (see its header)."""
    import importlib.util

    path = Path(__file__).parent / "fixtures" / "changelog-check" / "changelog_check_pre439.py"
    spec = importlib.util.spec_from_file_location("changelog_check_pre439", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_an_unreleased_only_note_passed_the_old_checker_and_fails_the_new() -> None:
    old = _old_checker()
    assert old.missing_changelog_entry(
        changed_files=["skillc/checks.py", "CHANGELOG.md"],
        base_changelog=UNRELEASED_EMPTY, head_changelog=UNRELEASED_WITH_ENTRY,
        head_commit_message="feat: x\n",
    ) is None
    assert _check(["skillc/checks.py", "CHANGELOG.md"], {}, {}) is not None


def test_a_fragment_only_note_failed_the_old_checker_and_passes_the_new() -> None:
    old = _old_checker()
    assert old.missing_changelog_entry(
        changed_files=["skillc/checks.py", FRAGMENT],
        base_changelog=UNRELEASED_EMPTY, head_changelog=UNRELEASED_EMPTY,
        head_commit_message="feat: x\n",
    ) is not None
    assert _check(["skillc/checks.py", FRAGMENT], {}, {FRAGMENT: GOOD_BULLET}) is None


# --------------------------------------------------- the gate script itself


def _repo(tmp_path: Path, name: str) -> Path:
    repo = tmp_path / name
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "control@invalid"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "control"], check=True)
    return repo


def _commit(repo: Path, message: str) -> None:
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", message], check=True)


@needs_git
def test_the_gate_script_itself_discriminates(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "repo")
    (repo / "CHANGELOG.md").write_text(UNRELEASED_EMPTY, encoding="utf-8")
    (repo / "skillc").mkdir()
    (repo / "skillc" / "x.py").write_text("x = 1\n", encoding="utf-8")
    _commit(repo, "base")
    subprocess.run(["git", "-C", str(repo), "branch", "feature"], check=True)

    # Bad: change skillc/, do not touch CHANGELOG.md, no escape trailer.
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "feature"], check=True)
    (repo / "skillc" / "x.py").write_text("x = 2\n", encoding="utf-8")
    _commit(repo, "feat: change x")
    rc = _run_in(repo, ["main"])
    assert rc == 1, "gate passed a skillc/ change with no changelog entry"

    # Bad since #439: the old way, an Unreleased edit with no fragment.
    (repo / "CHANGELOG.md").write_text(UNRELEASED_WITH_ENTRY, encoding="utf-8")
    _commit(repo, "docs: changelog the old way")
    rc = _run_in(repo, ["main"])
    assert rc == 1, "gate accepted an Unreleased-only edit after #439"

    # Good: add a fragment.
    (repo / "changelog.d").mkdir()
    (repo / FRAGMENT).write_text(GOOD_BULLET, encoding="utf-8")
    _commit(repo, "docs: changelog fragment")
    rc = _run_in(repo, ["main"])
    assert rc == 0, "gate refused a compliant fragment"


@needs_git
def test_the_gate_uses_the_merge_base_not_the_moving_target_tip(tmp_path: Path) -> None:
    """Cross-model review [MEDIUM]: diffing against the target branch's
    current tip - rather than the fork point - misattributes changes. A
    docs-only branch that never touched skillc/ must not be flagged just
    because main moved on and touched skillc/ (and even added its own
    changelog fragment) after the branch forked. Confirmed real on the pre-fix
    code, which diffed against origin/main's tip directly."""
    repo = _repo(tmp_path, "repo")
    (repo / "CHANGELOG.md").write_text(UNRELEASED_EMPTY, encoding="utf-8")
    (repo / "skillc").mkdir()
    (repo / "skillc" / "x.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "README.md").write_text("original\n", encoding="utf-8")
    _commit(repo, "base")
    subprocess.run(["git", "-C", str(repo), "branch", "feature"], check=True)

    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "feature"], check=True)
    (repo / "README.md").write_text("docs change\n", encoding="utf-8")
    _commit(repo, "docs: unrelated, never touches skillc/")

    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "main"], check=True)
    (repo / "skillc" / "x.py").write_text("x = 2\n", encoding="utf-8")
    (repo / "changelog.d").mkdir()
    (repo / "changelog.d" / "1.md").write_text(GOOD_BULLET, encoding="utf-8")
    _commit(repo, "feat: main's own unrelated change, with its own changelog fragment")

    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "feature"], check=True)
    rc = _run_in(repo, ["main"])
    assert rc == 0, "a docs-only branch was flagged for a change only main made after the fork"


def _run_in(repo: Path, args: list[str]) -> int:
    import os

    old = os.getcwd()
    os.chdir(repo)
    try:
        return cc.main(args)
    except SystemExit as exc:
        return int(exc.code or 0)
    finally:
        os.chdir(old)
