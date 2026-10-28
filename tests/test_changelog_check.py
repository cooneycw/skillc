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


# #542: exercise the actual local target, including its selected checker mode.
def _local_gate_repo(tmp_path: Path) -> Path:
    repo = _repo(tmp_path, "gate")
    root = Path(__file__).resolve().parents[1]
    (repo / "ci").mkdir()
    for name in ("Makefile", "ci/changelog_check.py"):
        shutil.copyfile(root / name, repo / name)
    (repo / "skillc").mkdir()
    (repo / "skillc/x.py").write_text("x = 1\n")
    _commit(repo, "base")
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "checkout", "-qb", "feature"], check=True)
    return repo


@needs_git
@pytest.mark.parametrize("dirty", [False, True], ids=["clean-healthy", "dirty-regression"])
def test_local_target_refuses_pending_source(tmp_path: Path, dirty: bool) -> None:
    repo = _local_gate_repo(tmp_path)
    if dirty:
        (repo / "skillc/x.py").write_text("x = 2\n")
    _assert_target(repo, dirty)


def _assert_target(repo: Path, dirty: bool) -> None:
    result = subprocess.run(["make", "--no-print-directory", "changelog-check"],
                            cwd=repo, capture_output=True, text=True, check=False)
    assert result.returncode == (2 if dirty else 0), (result.stdout, result.stderr)
    if dirty:
        assert "REFUSED" in result.stderr and "skillc/x.py" in result.stderr


@needs_git
def test_default_cli_preserves_dirty_committed_compatibility(tmp_path: Path) -> None:
    repo = _local_gate_repo(tmp_path)
    (repo / "skillc/x.py").write_text("x = 2\n")
    assert _run_in(repo, ["main"]) == 0


def _git_in(repo: Path, *args: str, input: str | None = None) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], input=input,
                          capture_output=True, text=True, check=True).stdout.strip()


def _guard(repo: Path) -> int:
    return _run_in(repo, ["main", "--require-clean-inputs"])


@needs_git
@pytest.mark.parametrize("kind", [
    "unstaged", "staged", "untracked", "deleted", "staged-deleted", "typechange",
    "conflict", "rename-out", "rename-in", "rename-within", "spaces", "newline",
    "dirty-good-fragment", "fragment-delete", "fragment-rename-out", "fragment-rename-in",
    "staged-then-deleted", "symlink", "exempt-head", "unrelated", "ignored",
])
def test_relevant_pending_inputs_refuse(tmp_path: Path, kind: str) -> None:
    repo = _local_gate_repo(tmp_path)
    fragment = repo / FRAGMENT
    fragment.parent.mkdir()
    fragment.write_text(GOOD_BULLET)
    (repo / "outside.py").write_text("x = 1\n")
    _commit(repo, "fixture inputs")
    source = repo / "skillc/x.py"
    if kind in ("unstaged", "staged", "exempt-head"):
        if kind == "exempt-head":
            _git_in(repo, "commit", "--allow-empty", "-qm", "exempt\n\nChangelog-exempt: old note")
        source.write_text("x = 2\n")
        if kind == "staged":
            _git_in(repo, "add", "skillc/x.py")
    elif kind in ("untracked", "spaces", "newline"):
        (repo / "skillc" / {"untracked": "new.py", "spaces": "a b.py", "newline": "a\nb.py"}[kind]).write_text("x=2\n")
    elif kind in ("deleted", "staged-deleted", "typechange", "symlink"):
        source.unlink()
        if kind == "staged-deleted":
            _git_in(repo, "add", "-u")
        elif kind in ("typechange", "symlink"):
            # A dangling/outside target cannot supply fragment contents.
            source.symlink_to(tmp_path / "never-read")
    elif kind == "conflict":
        blob = _git_in(repo, "rev-parse", "HEAD:skillc/x.py")
        _git_in(repo, "update-index", "--index-info", input="".join(
            f"100644 {blob} {stage}\tskillc/x.py\n" for stage in (1, 2, 3)))
    elif kind.startswith("rename"):
        old, new = {"rename-out": ("skillc/x.py", "out.py"),
                    "rename-in": ("outside.py", "skillc/in.py"),
                    "rename-within": ("skillc/x.py", "skillc/y.py")}[kind]
        _git_in(repo, "mv", old, new)
    elif kind == "dirty-good-fragment":
        fragment.write_text(GOOD_BULLET + "  Another usable line.\n")
    elif kind == "fragment-delete":
        fragment.unlink()
    elif kind in ("fragment-rename-out", "fragment-rename-in"):
        old, new = (FRAGMENT, "note.md") if kind.endswith("out") else ("outside.py", "changelog.d/99.md")
        _git_in(repo, "mv", old, new)
    elif kind == "staged-then-deleted":
        fragment.write_text(GOOD_BULLET + "  New line.\n")
        _git_in(repo, "add", FRAGMENT)
        fragment.unlink()
    elif kind == "ignored":
        (repo / ".gitignore").write_text("skillc/generated/\n")
        (repo / "skillc/generated").mkdir()
        (repo / "skillc/generated/x.py").write_text("ignored\n")
    else:
        for path in ("README.md", "notes.txt", "changelog.d/README.md", "reports/log"):
            target = repo / path
            target.parent.mkdir(exist_ok=True)
            target.write_text("unrelated\n")
    assert _guard(repo) == (0 if kind in ("unrelated", "ignored") else 2)


@needs_git
def test_pending_guard_discrimination_survives_only_with_real_enumeration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _local_gate_repo(tmp_path)
    source = repo / "skillc/x.py"
    assert _guard(repo) == 0
    source.write_text("x = 2\n")
    def discriminate() -> None:
        assert _guard(repo) == 2, "dirty-input control was blinded"
    discriminate()
    monkeypatch.setattr(cc, "_pending_inputs", list)
    with pytest.raises(AssertionError, match="control was blinded"):
        discriminate()


@needs_git
@pytest.mark.parametrize("stdout,stderr,code", [
    (b" M skillc/x.py", b"", 0), (b"bad\0", b"", 0),
    (b"?? ../escape\0", b"", 0), (b"", b"warning: cannot read directory", 0),
    (b"", b"fatal: status unavailable", 128),
])
def test_incomplete_status_is_refusal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                      stdout: bytes, stderr: bytes, code: int) -> None:
    repo = _local_gate_repo(tmp_path)
    real = subprocess.run
    def observed(argv, *args, **kwargs):
        if argv[:2] == ["git", "status"]:
            return subprocess.CompletedProcess(argv, code, stdout, stderr)
        return real(argv, *args, **kwargs)
    monkeypatch.setattr(cc.subprocess, "run", observed)
    assert _guard(repo) == 2


@needs_git
@pytest.mark.parametrize("changed", ["pending", "head"])
def test_guard_rechecks_before_green(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changed: str) -> None:
    repo = _local_gate_repo(tmp_path)
    real = cc.missing_changelog_entry
    def during(*args):
        if changed == "pending":
            (repo / "skillc/x.py").write_text("x = 2\n")
        else:
            _git_in(repo, "commit", "--allow-empty", "-qm", "moved HEAD")
        return real(*args)
    monkeypatch.setattr(cc, "missing_changelog_entry", during)
    assert _guard(repo) == 2


@needs_git
@pytest.mark.parametrize("note", [None, "", GOOD_BULLET, "- Other\n- Invalid\n", "carried", "delete"])
def test_guard_preserves_committed_policy(tmp_path: Path, note: str | None) -> None:
    repo = _local_gate_repo(tmp_path)
    if note in ("carried", "delete"):
        (repo / FRAGMENT).parent.mkdir()
        (repo / FRAGMENT).write_text(GOOD_BULLET)
        _commit(repo, "base fragment")
        _git_in(repo, "branch", "-f", "main", "HEAD")
        if note == "delete":
            (repo / FRAGMENT).unlink()
    (repo / "skillc/x.py").write_text("x = 2\n")
    if note is not None and note not in ("carried", "delete"):
        (repo / FRAGMENT).parent.mkdir()
        (repo / FRAGMENT).write_text(note)
    _commit(repo, "changed product")
    assert _guard(repo) == (0 if note == GOOD_BULLET else 1)


@needs_git
def test_actual_target_wiring_control(tmp_path: Path) -> None:
    repo = _local_gate_repo(tmp_path)
    (repo / "skillc/x.py").write_text("x = 2\n")
    _assert_target(repo, True)
    makefile = repo / "Makefile"
    text = makefile.read_text()
    assert text.count(" --require-clean-inputs") == 1
    makefile.write_text(text.replace(" --require-clean-inputs", ""))
    with pytest.raises(AssertionError):
        _assert_target(repo, True)


@needs_git
def test_pending_fragment_symlink_never_reads_target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _local_gate_repo(tmp_path)
    (repo / FRAGMENT).parent.mkdir()
    (repo / FRAGMENT).symlink_to(tmp_path / "unreadable-or-absent")
    def forbidden(*args):
        pytest.fail("pending fragment content was read")
    monkeypatch.setattr(cc, "_show", forbidden)
    assert _guard(repo) == 2


@needs_git
@pytest.mark.parametrize("fault", ["status-launch", "initial-head", "recheck-head", "no-merge-base"])
def test_guarded_git_failures_refuse(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str) -> None:
    repo = _local_gate_repo(tmp_path)
    real = subprocess.run
    heads = 0
    def observed(argv, *args, **kwargs):
        nonlocal heads
        if fault == "status-launch" and argv[:2] == ["git", "status"]:
            raise OSError("controlled status launch failure")
        if argv[:2] == ["git", "rev-parse"] and fault in ("initial-head", "recheck-head"):
            heads += 1
            if heads == (1 if fault == "initial-head" else 2):
                return subprocess.CompletedProcess(argv, 128, "", "controlled HEAD refusal")
        return real(argv, *args, **kwargs)
    if fault == "no-merge-base":
        monkeypatch.setattr(cc, "_merge_base", lambda *args: None)
    else:
        monkeypatch.setattr(cc.subprocess, "run", observed)
    assert _guard(repo) == 2
