"""CI gate: a PR touching skillc/ must add an Unreleased CHANGELOG entry (#73).

`ci/changelog_check.py`'s core (`missing_changelog_entry`) is pure - no git -
so these are committed red/good cases per ADR 0001, not a live git fixture.
`test_the_gate_script_itself_discriminates` drives the actual CLI entry point
against two throwaway git repositories, proving the wiring (git plumbing,
argv, exit codes) and not only the pure function.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from ci import changelog_check as cc

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


def test_escape_trailer_is_case_and_position_insensitive_within_the_message() -> None:
    assert cc.has_escape_trailer("fix: thing\n\nChangelog-exempt: docs typo\n") is True
    assert cc.has_escape_trailer("fix: thing\n\nCHANGELOG-EXEMPT: docs typo\n") is True
    assert cc.has_escape_trailer("fix: thing\n\nno trailer here\n") is False


# ------------------------------------------------------- the committed pairs


def test_bad_skillc_changed_no_entry_no_escape() -> None:
    """The red case: a PR-shaped diff touching skillc/ with no entry must fail."""
    problem = cc.missing_changelog_entry(
        changed_files=["skillc/checks.py"],
        base_changelog=UNRELEASED_EMPTY,
        head_changelog=UNRELEASED_EMPTY,
        head_commit_message="feat: add a rule\n",
    )
    assert problem is not None


def test_bad_skillc_changed_changelog_file_missing() -> None:
    problem = cc.missing_changelog_entry(
        changed_files=["skillc/checks.py"],
        base_changelog=UNRELEASED_EMPTY,
        head_changelog=None,
        head_commit_message="feat: add a rule\n",
    )
    assert problem is not None


def test_good_skillc_changed_with_a_new_entry() -> None:
    problem = cc.missing_changelog_entry(
        changed_files=["skillc/checks.py"],
        base_changelog=UNRELEASED_EMPTY,
        head_changelog=UNRELEASED_WITH_ENTRY,
        head_commit_message="feat: add a rule\n",
    )
    assert problem is None


def test_good_skillc_changed_with_escape_trailer_and_no_entry() -> None:
    problem = cc.missing_changelog_entry(
        changed_files=["skillc/checks.py"],
        base_changelog=UNRELEASED_EMPTY,
        head_changelog=UNRELEASED_EMPTY,
        head_commit_message="fix: typo\n\nChangelog-exempt: no user-visible change\n",
    )
    assert problem is None


def test_good_no_skillc_files_changed() -> None:
    problem = cc.missing_changelog_entry(
        changed_files=["README.md", "tests/test_checks.py"],
        base_changelog=UNRELEASED_EMPTY,
        head_changelog=UNRELEASED_EMPTY,
        head_commit_message="docs: fix a typo\n",
    )
    assert problem is None


def test_bad_entry_present_but_identical_to_base() -> None:
    """A stale Unreleased section carried over unchanged - not a new entry,
    even though it is non-empty."""
    problem = cc.missing_changelog_entry(
        changed_files=["skillc/checks.py"],
        base_changelog=UNRELEASED_WITH_ENTRY,
        head_changelog=UNRELEASED_WITH_ENTRY,
        head_commit_message="feat: add a rule\n",
    )
    assert problem is not None


def test_good_no_base_changelog_and_a_populated_unreleased_section() -> None:
    """The repository's first PR touching skillc/: there is no base to diff
    against, so a non-empty Unreleased section on HEAD is enough."""
    problem = cc.missing_changelog_entry(
        changed_files=["skillc/checks.py"],
        base_changelog=None,
        head_changelog=UNRELEASED_WITH_ENTRY,
        head_commit_message="feat: add a rule\n",
    )
    assert problem is None


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

    # Good: add an Unreleased entry.
    (repo / "CHANGELOG.md").write_text(UNRELEASED_WITH_ENTRY, encoding="utf-8")
    _commit(repo, "docs: changelog")
    rc = _run_in(repo, ["main"])
    assert rc == 0, "gate refused a compliant changelog update"


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
