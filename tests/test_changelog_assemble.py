"""Tests for `ci/changelog_assemble.py` (#439): folding `changelog.d/`
fragments into CHANGELOG.md at release.

The point of fragments is that two PRs never edit the same lines, so the one
place they meet - this step - must keep every bullet whole, keep the existing
entries, never drop a fragment (two for one issue included), and write
nothing at all when any fragment is malformed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ci import changelog_assemble as ca
from ci import changelog_check as cc

BASE = (
    "# Changelog\n\nPreamble.\n\n## [Unreleased]\n\n"
    "- **Existing entry** (#1). Already here\n  before fragments existed.\n\n"
    "## [0.4.0] - 2026-09-29\n\n- Old release note.\n"
)
MULTI = "- **Three** (#3). First line\n  second line\n  third line.\n"


def test_fragments_go_to_the_top_of_unreleased_and_existing_entries_stay() -> None:
    out = ca.assemble(BASE, {"3.md": MULTI})
    section = cc.unreleased_section(out)
    assert section.index("**Three**") < section.index("**Existing entry**")
    assert "- **Existing entry** (#1). Already here\n  before fragments existed.\n" in out
    assert out.startswith("# Changelog\n\nPreamble.\n\n## [Unreleased]\n\n- **Three**")
    assert "## [0.4.0] - 2026-09-29\n\n- Old release note.\n" in out


def test_each_multi_line_bullet_stays_contiguous() -> None:
    out = ca.assemble(BASE, {"3.md": MULTI, "20.md": "- **Twenty** (#20).\n  continued.\n"})
    assert MULTI in out
    assert "- **Twenty** (#20).\n  continued.\n" in out


def test_order_is_by_issue_number_not_by_text() -> None:
    out = ca.assemble(BASE, {"20.md": "- twenty (#20)\n", "3.md": "- three (#3)\n", "100.md": "- hundred (#100)\n"})
    assert out.index("- three (#3)") < out.index("- twenty (#20)") < out.index("- hundred (#100)")


def test_two_fragments_for_one_issue_are_both_folded_in_a_fixed_order() -> None:
    """#439 condition 3: the `-<slug>` form exists so a second PR on the same
    issue does not collide with the first. Both land; neither is dropped; the
    order does not depend on dict or directory order."""
    fragments = {"3-follow-up.md": "- three follow-up (#3)\n", "3.md": "- three (#3)\n", "4.md": "- four (#4)\n"}
    out = ca.assemble(BASE, fragments)
    reversed_input = ca.assemble(BASE, dict(reversed(list(fragments.items()))))
    assert out == reversed_input
    assert out.count("- three (#3)\n") == 1 and out.count("- three follow-up (#3)\n") == 1
    assert out.index("- three follow-up (#3)") < out.index("- three (#3)") < out.index("- four (#4)")


@pytest.mark.parametrize("bad", ["", "\n  \n", "Not a bullet.\n",
                                 "- ok (#5)\n\n## [9.9.9]\n\n- smuggled\n", "- one\n- two\n",
                                 "-   Title\n\n  ## [9.9.9]\n\n  x\n", "- \n"])
def test_a_malformed_fragment_refuses_by_name(bad: str) -> None:
    with pytest.raises(ca.AssembleError, match="changelog.d/5.md"):
        ca.assemble(BASE, {"3.md": MULTI, "5.md": bad})


def test_no_unreleased_heading_refuses() -> None:
    with pytest.raises(ca.AssembleError, match="Unreleased"):
        ca.assemble("# Changelog\n\n## [0.4.0]\n\n- x\n", {"3.md": MULTI})


def _repo(tmp_path: Path, fragments: dict[str, str]) -> Path:
    (tmp_path / "CHANGELOG.md").write_text(BASE, encoding="utf-8")
    directory = tmp_path / "changelog.d"
    directory.mkdir()
    (directory / "README.md").write_text("The rule.\n", encoding="utf-8")
    for name, text in fragments.items():
        (directory / name).write_text(text, encoding="utf-8")
    return tmp_path


def test_main_folds_and_deletes_only_fragments(tmp_path: Path) -> None:
    root = _repo(tmp_path, {"3.md": MULTI, "3-b.md": "- three b (#3)\n"})
    assert ca.main([str(root)]) == 0
    text = (root / "CHANGELOG.md").read_text()
    assert MULTI in text and "- three b (#3)\n" in text
    assert sorted(p.name for p in (root / "changelog.d").iterdir()) == ["README.md"]


def test_main_refusal_writes_nothing_and_keeps_every_fragment(tmp_path: Path) -> None:
    root = _repo(tmp_path, {"3.md": MULTI, "5.md": "not a bullet\n"})
    assert ca.main([str(root)]) == 1
    assert (root / "CHANGELOG.md").read_text() == BASE
    assert sorted(p.name for p in (root / "changelog.d").iterdir()) == ["3.md", "5.md", "README.md"]


def test_main_check_writes_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _repo(tmp_path, {"3.md": MULTI})
    assert ca.main(["--check", str(root)]) == 0
    assert "3.md" in capsys.readouterr().out
    assert (root / "CHANGELOG.md").read_text() == BASE
    assert (root / "changelog.d" / "3.md").exists()


def test_main_with_no_fragments_is_a_no_op(tmp_path: Path) -> None:
    root = _repo(tmp_path, {})
    assert ca.main([str(root)]) == 0
    assert (root / "CHANGELOG.md").read_text() == BASE


def test_main_refuses_a_root_without_changelog(tmp_path: Path) -> None:
    """#439 counter-model review: a mistyped root must not read as "nothing to
    do" - the same verdict as a real repository with no pending fragments."""
    assert ca.main(["--check", str(tmp_path / "no-such-root")]) == 2
    assert ca.main([str(tmp_path)]) == 2  # exists, but holds no CHANGELOG.md
