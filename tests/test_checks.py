"""Tests for the rules.

The load-bearing one is `test_every_rule_discriminates`: it is the same pairing
`skillc selftest` runs, wired into the suite so a rule cannot go blind without
the test run noticing. `test_selftest_reports_a_blinded_rule` is its negative
control - it blinds a rule on purpose and asserts the harness says so, because a
selftest that cannot fail proves nothing about the rules it blesses.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from skillc import checks, cli
from skillc.spec import FrontmatterError, Skill, discover, parse_frontmatter

CONTROLS = Path(__file__).resolve().parent.parent / "controls"


@pytest.mark.parametrize("rule", checks.RULES, ids=lambda r: r.id)
def test_every_rule_discriminates(rule: checks.Rule) -> None:
    bad_dir, good_dir = CONTROLS / rule.id / "bad", CONTROLS / rule.id / "good"
    assert bad_dir.is_dir(), f"{rule.id} ships no known-bad control"
    assert good_dir.is_dir(), f"{rule.id} ships no known-good control"

    bad = [f for s in discover(bad_dir) for f in checks.run(s, only=rule.id)]
    good = [f for s in discover(good_dir) for f in checks.run(s, only=rule.id)]

    assert bad, f"{rule.id} is blind: silent on its own known-bad input"
    assert not good, f"{rule.id} is noisy: fired on its known-good input ({good})"


def test_selftest_reports_a_blinded_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    blinded = checks.Rule("name-spec", checks.ERROR, "blinded", lambda _s: iter(()))
    monkeypatch.setattr(
        checks,
        "RULES",
        tuple(blinded if r.id == "name-spec" else r for r in checks.RULES),
    )
    rc = cli.cmd_selftest(argparse.Namespace(controls=str(CONTROLS)))
    assert rc == 1, "selftest passed a rule that reports nothing on its known-bad input"


def test_check_on_an_empty_tree_is_not_a_pass(tmp_path: Path) -> None:
    """Silence must not be indistinguishable from a clean run."""
    rc = cli.cmd_check(argparse.Namespace(path=str(tmp_path), rule=None, strict=False))
    assert rc == 2


def test_parse_frontmatter_nested_mapping() -> None:
    fm, body = parse_frontmatter(
        "---\nname: a-skill\ndescription: Use when testing.\nmetadata:\n  version: '1.0'\n---\nbody\n"
    )
    assert fm["name"] == "a-skill"
    assert fm["metadata"] == {"version": "1.0"}
    assert body.strip() == "body"


def test_parse_frontmatter_requires_a_block() -> None:
    with pytest.raises(FrontmatterError):
        parse_frontmatter("# no frontmatter here\n")


def test_unreadable_frontmatter_is_an_error_not_a_pass(tmp_path: Path) -> None:
    path = tmp_path / "broken" / "SKILL.md"
    path.parent.mkdir()
    path.write_text("# no frontmatter\n", encoding="utf-8")
    findings = checks.run(Skill.load(path))
    assert [f.rule for f in findings] == ["frontmatter"]
    assert findings[0].severity == checks.ERROR


def test_trigger_shape_does_not_double_report_a_missing_description(tmp_path: Path) -> None:
    path = tmp_path / "x" / "SKILL.md"
    path.parent.mkdir()
    path.write_text("---\nname: x\ndescription: ''\n---\nbody\n", encoding="utf-8")
    skill = Skill.load(path)
    assert not list(checks._trigger_shape(skill))
    assert list(checks._required_fields(skill))
