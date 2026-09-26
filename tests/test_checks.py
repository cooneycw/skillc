"""Tests for the rules.

The load-bearing one is `test_every_rule_discriminates`: it is the same pairing
`skillc selftest` runs, wired into the suite so a rule cannot go blind without
the test run noticing. `test_selftest_reports_a_blinded_rule` is its negative
control - it blinds a rule on purpose and asserts the harness says so, because a
selftest that cannot fail proves nothing about the rules it blesses.
"""

from __future__ import annotations

import argparse
import dataclasses
import shutil
from pathlib import Path

import pytest

from skillc import checks, cli, records
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


# ------------------------------------------------ false certification (#2)
#
# Each case below is an input that made `selftest` or `check` certify something it
# never exercised before #2. Every one of them returned 0 on the pre-fix code.


def _controls_copy(tmp_path: Path) -> Path:
    copy = tmp_path / "controls"
    shutil.copytree(CONTROLS, copy)
    return copy


def _selftest(controls: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    rc = cli.cmd_selftest(argparse.Namespace(controls=str(controls)))
    return rc, capsys.readouterr().out


def _blind(monkeypatch: pytest.MonkeyPatch, rule_id: str) -> None:
    rules = tuple(
        dataclasses.replace(r, check=lambda _s: iter(())) if r.id == rule_id else r
        for r in checks.RULES
    )
    monkeypatch.setattr(checks, "RULES", rules)
    monkeypatch.setattr(checks, "ALL_RULES", rules + checks.RECORD_RULES)


def test_a_healthy_selftest_still_passes(capsys: pytest.CaptureFixture[str]) -> None:
    """The refusals below must not have cost the green they exist to make honest."""
    rc, out = _selftest(CONTROLS, capsys)
    total = len(checks.ALL_RULES)
    assert rc == 0, out
    assert f"skillc selftest: {total}/{total} rule(s) discriminate" in out


@pytest.mark.parametrize("side", ["good", "bad"])
def test_an_empty_population_is_refused(
    tmp_path: Path, side: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """A control directory with nothing in it proves nothing on that side.

    The empty GOOD side was the certifying case: no subject, no finding, `ok`.
    """
    controls = _controls_copy(tmp_path)
    for skill in (controls / "name-spec" / side).rglob("SKILL.md"):
        skill.unlink()
    rc, out = _selftest(controls, capsys)
    assert rc == 1, out
    assert any(
        line.startswith("EMPTY") and "name-spec" in line and f"known-{side}" in line
        for line in out.splitlines()
    ), out


def test_a_parse_failure_cannot_certify_a_blinded_rule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The review's second case: the parser's finding was credited to name-spec."""
    controls = _controls_copy(tmp_path)
    (controls / "name-spec" / "bad" / "code-quality" / "SKILL.md").write_text(
        "# no frontmatter\n", encoding="utf-8"
    )
    _blind(monkeypatch, "name-spec")
    rc, out = _selftest(controls, capsys)
    assert rc == 1, out
    assert not any(line.startswith("ok") and " name-spec " in line for line in out.splitlines())
    assert any(line.startswith("UNPARSED") and "name-spec" in line for line in out.splitlines())


def test_a_blinded_rule_is_blind_even_when_its_bad_case_parses(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _blind(monkeypatch, "name-spec")
    rc, out = _selftest(CONTROLS, capsys)
    assert rc == 1, out
    assert any(line.startswith("BLIND") and "name-spec" in line for line in out.splitlines())


def test_an_unparseable_good_case_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Silence on a file nothing could read is not silence on a good input."""
    controls = _controls_copy(tmp_path)
    (controls / "trigger-shape" / "good" / "rotate-credential" / "SKILL.md").write_text(
        "# no frontmatter\n", encoding="utf-8"
    )
    rc, out = _selftest(controls, capsys)
    assert rc == 1, out
    assert any(
        line.startswith("UNPARSED") and "trigger-shape" in line and "known-good" in line
        for line in out.splitlines()
    ), out


def test_a_parser_rule_must_be_shown_an_unparseable_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The parser rule's explicit expectation: its bad case does NOT parse.

    EVERY bad case is overwritten with parseable input: one left unparseable would
    still satisfy the expectation, which is what makes it the parser rule's own.
    """
    controls = _controls_copy(tmp_path)
    good = controls / "frontmatter" / "good" / "no-frontmatter" / "SKILL.md"
    bad = sorted((controls / "frontmatter" / "bad").rglob("SKILL.md"))
    assert bad, "no frontmatter bad case to overwrite"
    for path in bad:
        shutil.copy(good, path)
    rc, out = _selftest(controls, capsys)
    assert rc == 1, out
    assert any(
        line.startswith("UNPARSED") and "frontmatter" in line for line in out.splitlines()
    ), out


def test_a_bad_case_the_rule_is_silent_on_is_blind(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """One caught bad case must not carry a second one the rule never fires on."""
    controls = _controls_copy(tmp_path)
    shutil.copytree(
        controls / "name-spec" / "good" / "code-quality",
        controls / "name-spec" / "bad" / "extra" / "code-quality",
    )
    rc, out = _selftest(controls, capsys)
    assert rc == 1, out
    assert any(
        line.startswith("BLIND") and "silent on 1 of 2" in line for line in out.splitlines()
    ), out


# Each target is CLEAN, so before #2 the unknown selector read as a clean pass.
# A rule from the OTHER family is unknown to that command too.
SKILLS_CLEAN = CONTROLS / "name-spec" / "good"
RECORDS_CLEAN = CONTROLS / "record-envelope" / "good"
UNKNOWN_SELECTORS = [
    ("check", SKILLS_CLEAN, "typo"),
    ("check", SKILLS_CLEAN, "derived-status"),
    ("check-records", RECORDS_CLEAN, "typo"),
    ("check-records", RECORDS_CLEAN, "name-spec"),
]


@pytest.mark.parametrize(("command", "target", "selector"), UNKNOWN_SELECTORS)
def test_an_unknown_selector_is_refused_before_scanning(
    command: str,
    target: Path,
    selector: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`--rule typo` used to check no rules and exit 0 on a clean-looking summary.

    "Before scanning" is asserted on discovery itself, not on the absence of a
    printed summary: a refusal placed after `discover` would print none either.
    """

    def scanned(*_args: object) -> list[object]:
        raise AssertionError("it scanned before refusing")

    monkeypatch.setattr(cli, "discover", scanned)
    monkeypatch.setattr(records, "discover", scanned)
    rc = cli.main([command, str(target), "--rule", selector])
    out, err = capsys.readouterr()
    assert rc == 2
    assert f"unknown rule {selector!r}" in err
    assert "known rules:" in err
    assert "checked" not in out


def test_a_known_selector_does_scan(monkeypatch: pytest.MonkeyPatch) -> None:
    """The control for the case above: its discovery tripwire can fire."""

    def scanned(*_args: object) -> list[object]:
        raise AssertionError("scanned")

    monkeypatch.setattr(cli, "discover", scanned)
    with pytest.raises(AssertionError, match="scanned"):
        cli.main(["check", str(SKILLS_CLEAN), "--rule", "name-spec"])


def test_run_refuses_an_unknown_selector(tmp_path: Path) -> None:
    skill = discover(CONTROLS / "name-spec" / "good")[0]
    with pytest.raises(ValueError, match="unknown rule"):
        checks.run(skill, only="typo")
    record = records.discover(CONTROLS / "record-envelope" / "good")[0]
    with pytest.raises(ValueError, match="unknown rule"):
        checks.run_record(record, only="name-spec")


def test_check_still_reports_an_unparseable_skill_under_any_selector(tmp_path: Path) -> None:
    """`run`'s other caller: `check --rule name-spec` must still hear the parse failure."""
    path = tmp_path / "broken" / "SKILL.md"
    path.parent.mkdir()
    path.write_text("# no frontmatter\n", encoding="utf-8")
    findings = checks.run(Skill.load(path), only="name-spec")
    assert [f.rule for f in findings] == ["frontmatter"]
