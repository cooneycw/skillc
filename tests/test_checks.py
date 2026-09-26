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
import json
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from skillc import checks, cli, records
from skillc.spec import (
    FrontmatterError,
    Manifest,
    ManifestError,
    Skill,
    discover,
    parse_frontmatter,
)

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


def test_ref_depth_reports_every_distinct_chain_in_deterministic_order() -> None:
    """A skill with two independent deep chains must report both, sorted by
    (first-hop, second-hop) - not just the first one found (issue #52)."""
    path = CONTROLS / "ref-depth" / "bad" / "two-deep-chains" / "SKILL.md"
    findings = checks.run(Skill.load(path), only="ref-depth")
    assert [f.detail for f in findings] == [
        ("A.md links on to X.md: references must stay one level deep or the "
         "agent reads only part of the chain"),
        ("B.md links on to Y.md: references must stay one level deep or the "
         "agent reads only part of the chain"),
    ]


def test_ref_depth_output_order_is_independent_of_link_order(tmp_path: Path) -> None:
    """Findings sort by (first-hop, second-hop) even when SKILL.md links the
    second-hop-bearing files in the opposite order. The committed control
    (two-deep-chains) links A before B, so it cannot tell a sorted result from
    a discovery-order-preserving one that happens to match (issue #52 review:
    /codex:code_review)."""
    skill_dir = tmp_path / "reversed-order"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: reversed-order\n"
        "description: Use when link order should not affect the reported order.\n"
        "---\n"
        "See [guide B](B.md) and [guide A](A.md).\n",
        encoding="utf-8",
    )
    (skill_dir / "A.md").write_text("Extra in [the extra](X.md).\n", encoding="utf-8")
    (skill_dir / "B.md").write_text("Extra in [the extra](Y.md).\n", encoding="utf-8")
    (skill_dir / "X.md").write_text("Deep content.\n", encoding="utf-8")
    (skill_dir / "Y.md").write_text("Deep content.\n", encoding="utf-8")

    findings = checks.run(Skill.load(skill_dir / "SKILL.md"), only="ref-depth")
    assert [f.detail for f in findings] == [
        ("A.md links on to X.md: references must stay one level deep or the "
         "agent reads only part of the chain"),
        ("B.md links on to Y.md: references must stay one level deep or the "
         "agent reads only part of the chain"),
    ]


def test_ref_depth_does_not_double_report_a_repeated_first_hop_link(tmp_path: Path) -> None:
    """SKILL.md linking the same first-hop file twice must not double the
    deep-chain finding (issue #52 review: /codex:code_review)."""
    skill_dir = tmp_path / "repeated-link"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: repeated-link\n"
        "description: Use when SKILL.md links the same file twice to test dedup.\n"
        "---\n"
        "See [guide A](A.md) and again [guide A](A.md).\n",
        encoding="utf-8",
    )
    (skill_dir / "A.md").write_text("Extra in [the extra](X.md).\n", encoding="utf-8")
    (skill_dir / "X.md").write_text("Deep content.\n", encoding="utf-8")

    findings = checks.run(Skill.load(skill_dir / "SKILL.md"), only="ref-depth")
    assert len(findings) == 1
    assert findings[0].detail == (
        "A.md links on to X.md: references must stay one level deep or the "
        "agent reads only part of the chain"
    )


def test_ref_depth_ignores_a_back_link_to_skill_md() -> None:
    """A second-hop link that resolves to SKILL.md itself is not a deeper
    chain - it is the entry point (issue #52)."""
    path = CONTROLS / "ref-depth" / "good" / "back-link-skill" / "SKILL.md"
    assert checks.run(Skill.load(path), only="ref-depth") == []


def test_ref_depth_ignores_a_sibling_already_linked_from_skill_md() -> None:
    """A second-hop link that lands on a file SKILL.md already links directly
    is not a deeper chain - the agent reaches it either way (issue #52)."""
    path = CONTROLS / "ref-depth" / "good" / "linked-sibling" / "SKILL.md"
    assert checks.run(Skill.load(path), only="ref-depth") == []


def test_selftest_reports_a_blinded_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    blinded = checks.Rule("name-spec", checks.ERROR, "blinded", lambda _s, _t: iter(()))
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


def _write_skill(path: Path, name: str) -> None:
    path.mkdir(parents=True)
    (path / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Use when testing manifest scoping.\n---\nBody.\n",
        encoding="utf-8",
    )


def _write_manifest(plugin_root: Path, skills: list[str]) -> Path:
    manifest_dir = plugin_root / ".claude-plugin"
    manifest_dir.mkdir(parents=True)
    manifest_path = manifest_dir / "plugin.json"
    manifest_path.write_text(json.dumps({"name": "fixture", "skills": skills}), encoding="utf-8")
    return manifest_path


def test_check_manifest_dangling_entry_is_an_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A manifest entry with no SKILL.md must never read as a clean skill."""
    _write_skill(tmp_path / "skills" / "present", "present")
    manifest_path = _write_manifest(tmp_path, ["./skills/present", "./skills/missing"])
    rc = cli.cmd_check(
        argparse.Namespace(
            path=str(tmp_path), rule=None, strict=False, manifest=str(manifest_path)
        )
    )
    assert rc == 1
    out = capsys.readouterr().out
    assert "manifest-entry" in out
    assert "skills/missing" in out
    assert "1 declared, 0 checked" not in out  # sanity: the valid entry still checked
    assert "2 declared, 1 checked, 0 undeclared" in out


def test_check_manifest_clean_is_green(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Every manifest entry resolving to a real skill is an ordinary clean run."""
    _write_skill(tmp_path / "skills" / "present", "present")
    manifest_path = _write_manifest(tmp_path, ["./skills/present"])
    rc = cli.cmd_check(
        argparse.Namespace(
            path=str(tmp_path), rule=None, strict=False, manifest=str(manifest_path)
        )
    )
    assert rc == 0
    assert "1 declared, 1 checked, 0 undeclared, 0 error(s)" in capsys.readouterr().out


def test_check_manifest_reports_the_undeclared_remainder(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A skill in the tree but not in the manifest counts as undeclared, not
    silently ignored."""
    _write_skill(tmp_path / "skills" / "declared", "declared")
    _write_skill(tmp_path / "skills" / "extra", "extra")
    manifest_path = _write_manifest(tmp_path, ["./skills/declared"])
    rc = cli.cmd_check(
        argparse.Namespace(
            path=str(tmp_path), rule=None, strict=False, manifest=str(manifest_path)
        )
    )
    assert rc == 0
    assert "1 declared, 1 checked, 1 undeclared" in capsys.readouterr().out


def test_check_manifest_matching_zero_skills_is_refused(tmp_path: Path) -> None:
    """A manifest declaring nothing is as empty a population as a tree with no
    SKILL.md, not a silent no-op."""
    manifest_path = _write_manifest(tmp_path, [])
    rc = cli.cmd_check(
        argparse.Namespace(
            path=str(tmp_path), rule=None, strict=False, manifest=str(manifest_path)
        )
    )
    assert rc == 2


@pytest.mark.parametrize(
    "content",
    [
        "not json at all",
        json.dumps({"name": "x"}),  # no 'skills' key
        json.dumps({"skills": "not-a-list"}),
        json.dumps({"skills": [""]}),  # empty string entry
        json.dumps(["not", "an", "object"]),
    ],
)
def test_check_manifest_malformed_is_refused_not_silently_ignored(
    tmp_path: Path, content: str
) -> None:
    """A malformed manifest must be refused (exit 2), never silently fall back
    to checking the whole tree as though no manifest were given."""
    _write_skill(tmp_path / "skills" / "present", "present")
    manifest_dir = tmp_path / ".claude-plugin"
    manifest_dir.mkdir()
    manifest_path = manifest_dir / "plugin.json"
    manifest_path.write_text(content, encoding="utf-8")
    rc = cli.cmd_check(
        argparse.Namespace(
            path=str(tmp_path), rule=None, strict=False, manifest=str(manifest_path)
        )
    )
    assert rc == 2


def test_check_manifest_missing_file_is_refused(tmp_path: Path) -> None:
    rc = cli.cmd_check(
        argparse.Namespace(
            path=str(tmp_path),
            rule=None,
            strict=False,
            manifest=str(tmp_path / "no-such-manifest.json"),
        )
    )
    assert rc == 2


def test_manifest_resolves_entries_against_the_plugin_root(tmp_path: Path) -> None:
    """`.claude-plugin/plugin.json` entries are relative to the PLUGIN root
    (the manifest's grandparent), not the manifest's own directory."""
    _write_skill(tmp_path / "skills" / "engineering" / "foo", "foo")
    manifest_path = _write_manifest(tmp_path, ["./skills/engineering/foo"])
    manifest = Manifest.load(manifest_path)
    assert manifest.plugin_root == tmp_path.resolve()
    assert manifest.declared == ((tmp_path / "skills" / "engineering" / "foo").resolve(),)


def test_manifest_deduplicates_repeated_entries(tmp_path: Path) -> None:
    _write_skill(tmp_path / "skills" / "foo", "foo")
    manifest_path = _write_manifest(tmp_path, ["./skills/foo", "./skills/foo"])
    manifest = Manifest.load(manifest_path)
    assert manifest.declared == ((tmp_path / "skills" / "foo").resolve(),)


def test_manifest_unreadable_raises(tmp_path: Path) -> None:
    with pytest.raises(ManifestError):
        Manifest.load(tmp_path / "absent.json")


def test_manifest_invalid_utf8_is_refused_not_a_traceback(tmp_path: Path) -> None:
    """`UnicodeDecodeError` is a `ValueError`, not an `OSError` - a decode
    failure must not escape past the read that is supposed to catch it
    (issue #53 review: /codex:code_review)."""
    manifest_dir = tmp_path / ".claude-plugin"
    manifest_dir.mkdir()
    manifest_path = manifest_dir / "plugin.json"
    manifest_path.write_bytes(b"\xff\xfe not valid utf-8")
    with pytest.raises(ManifestError):
        Manifest.load(manifest_path)


@pytest.mark.parametrize(
    "entry",
    ["../escaped", "../../etc/passwd", "/etc/passwd"],
)
def test_manifest_entry_escaping_the_plugin_root_is_refused(
    tmp_path: Path, entry: str
) -> None:
    """Claude Code itself refuses a manifest component outside the plugin
    root ('Path escapes plugin directory'); a scoping check that accepted one
    could report a clean run over a skill the real plugin loader would never
    have loaded (issue #53 review: /codex:code_review)."""
    _write_skill(tmp_path / "skills" / "present", "present")
    manifest_path = _write_manifest(tmp_path, [entry])
    with pytest.raises(ManifestError):
        Manifest.load(manifest_path)


def test_check_manifest_control_dangling_entry_reds() -> None:
    """The committed bad/dangling-entry control must still fire (issue #53
    review: /codex:code_review found the committed controls unreferenced by
    any test)."""
    fixture = CONTROLS / "check-manifest" / "bad" / "dangling-entry"
    manifest_path = fixture / ".claude-plugin" / "plugin.json"
    rc = cli.cmd_check(
        argparse.Namespace(
            path=str(fixture), rule=None, strict=False, manifest=str(manifest_path)
        )
    )
    assert rc == 1


def test_check_manifest_control_clean_is_green() -> None:
    """The committed good/clean control must stay green."""
    fixture = CONTROLS / "check-manifest" / "good" / "clean"
    manifest_path = fixture / ".claude-plugin" / "plugin.json"
    rc = cli.cmd_check(
        argparse.Namespace(
            path=str(fixture), rule=None, strict=False, manifest=str(manifest_path)
        )
    )
    assert rc == 0


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
    assert not list(checks._trigger_shape(skill, "portable"))
    assert list(checks._required_fields(skill, "portable"))


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
        dataclasses.replace(r, check=lambda _s, _t: iter(())) if r.id == rule_id else r
        for r in checks.RULES
    )
    monkeypatch.setattr(checks, "RULES", rules)
    monkeypatch.setattr(checks, "ALL_RULES", rules + checks.RECORD_RULES + checks.BUNDLE_RULES)


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


# --------------------------------- target-scoped selftest cases (#51 rework)
#
# `trigger-shape` behaves differently under `claude-code` than under `portable`
# on the same input, yet the base bad/good pair alone cannot see that: it
# always runs at the default target (`_population`'s default), so it stays
# green whichever way the target-dependent branch breaks. These commit the
# instrument's own redcase: selftest must go red when that branch regresses,
# and must go red when the committed target cases it depends on disappear.


def test_a_healthy_selftest_reports_the_trigger_shape_target_cases(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc, out = _selftest(CONTROLS, capsys)
    assert rc == 0, out
    lines = out.splitlines()
    assert any(
        line.startswith("ok") and "trigger-shape[claude-code]" in line and "good" in line
        for line in lines
    ), out
    assert any(
        line.startswith("ok") and "trigger-shape[portable]" in line and "bad" in line
        for line in lines
    ), out


def test_selftest_goes_red_if_the_claude_code_suppression_stops_checking_the_target(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The regression named in review: drop the `target == "claude-code"` guard
    so the suppression fires under every target. The base pair (run at the
    default target, `portable`) cannot see this - it never asked for
    `claude-code` and the model-invoked bad case has nothing to suppress. Only
    the committed `targets/portable/bad` case (a user-invoked skill that must
    still fire under `portable`) goes silent and catches it."""

    def regressed(skill: Skill, target: str) -> Iterator[str]:
        description = skill.get("description")
        if not description or not description.strip():
            return
        if checks.TRIGGER_RE.search(description):
            return
        if skill.frontmatter.get("disable-model-invocation") is True:
            return  # the dropped guard: no `target ==` check at all
        yield (
            "description states a capability but no triggering condition - "
            "the model reads this to decide whether to fire the skill"
        )

    monkeypatch.setattr(
        checks, "RULES",
        tuple(dataclasses.replace(r, check=regressed) if r.id == "trigger-shape" else r
              for r in checks.RULES),
    )
    rc, out = _selftest(CONTROLS, capsys)
    assert rc == 1, out
    lines = out.splitlines()
    assert any(line.startswith("ok") and line.split()[1] == "trigger-shape" for line in lines), (
        "the base pair should stay green - it cannot see this regression, which is the point"
    )
    assert any(
        line.startswith("BLIND") and "trigger-shape[portable]" in line for line in lines
    ), out


def test_selftest_refuses_an_emptied_target_case(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Emptying a committed target side (dir present, no subject in it) must be
    EMPTY, not silently absent - the same discipline the base pair already has."""
    controls = _controls_copy(tmp_path)
    bad_dir = controls / "trigger-shape" / "targets" / "portable" / "bad" / "rotate-credential"
    (bad_dir / "SKILL.md").unlink()
    bad_dir.rmdir()
    rc, out = _selftest(controls, capsys)
    assert rc == 1, out
    assert any(
        line.startswith("EMPTY") and "trigger-shape[portable]" in line for line in out.splitlines()
    ), out


def test_selftest_refuses_a_deleted_target_case(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Deleting a committed side entirely, leaving neither bad/ nor good/ under
    that target, is MALFORMED - it must not silently read as "no case here"."""
    controls = _controls_copy(tmp_path)
    shutil.rmtree(controls / "trigger-shape" / "targets" / "portable" / "bad")
    rc, out = _selftest(controls, capsys)
    assert rc == 1, out
    assert any(
        line.startswith("MALFORMED") and "trigger-shape" in line and "targets/portable" in line
        for line in out.splitlines()
    ), out


def test_an_unknown_target_directory_name_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    controls = _controls_copy(tmp_path)
    bogus = controls / "trigger-shape" / "targets" / "every-harness" / "good"
    shutil.copytree(controls / "trigger-shape" / "good", bogus)
    rc, out = _selftest(controls, capsys)
    assert rc == 1, out
    assert any(
        line.startswith("MALFORMED") and "unknown target" in line for line in out.splitlines()
    ), out


def test_an_empty_declared_targets_directory_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Cross-model review (round 2): `targets/` present but every case under it
    removed used to read as "no target case here", the same as never having
    committed one - silently dropping coverage rather than flagging the gap."""
    controls = _controls_copy(tmp_path)
    shutil.rmtree(controls / "trigger-shape" / "targets" / "claude-code")
    shutil.rmtree(controls / "trigger-shape" / "targets" / "portable")
    rc, out = _selftest(controls, capsys)
    assert rc == 1, out
    assert any(
        line.startswith("MALFORMED") and "trigger-shape" in line and "declares no target case" in line
        for line in out.splitlines()
    ), out


@pytest.mark.parametrize("side", ["good", "bad"])
def test_an_unparseable_target_control_is_refused_not_certified(
    tmp_path: Path, side: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """Cross-model review (round 2): `_target_case` read finding counts without
    checking `parse_error` first. An unparseable good control has nothing that
    could have fired trigger-shape - `own == 0` looked exactly like a passing
    silence. An unparseable bad control's one finding is the PARSER's, attributed
    to trigger-shape by the same blind count - looked exactly like a correct
    fire. Both must be UNPARSED, mirroring the base pair's existing discipline."""
    controls = _controls_copy(tmp_path)
    target = "claude-code" if side == "good" else "portable"
    fixture = controls / "trigger-shape" / "targets" / target / side / "rotate-credential" / "SKILL.md"
    fixture.write_text("# no frontmatter\n", encoding="utf-8")
    rc, out = _selftest(controls, capsys)
    assert rc == 1, out
    assert any(
        line.startswith("UNPARSED") and f"trigger-shape[{target}]" in line for line in out.splitlines()
    ), out


# ------------------------------------------ invocation-consistency (#50)


def _skill_with_openai_yaml(
    tmp_path: Path, name: str, skill_block: str, openai_yaml: str | None
) -> Skill:
    d = tmp_path / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"---\n{skill_block}---\nbody\n", encoding="utf-8")
    if openai_yaml is not None:
        agents = d / "agents"
        agents.mkdir()
        (agents / "openai.yaml").write_text(openai_yaml, encoding="utf-8")
    return Skill.load(d / "SKILL.md")


def test_invocation_consistency_is_silent_without_agents_openai_yaml(tmp_path: Path) -> None:
    """The file is an upstream convention, not a specification requirement - its
    absence says nothing about a second client to compare against."""
    skill = _skill_with_openai_yaml(
        tmp_path, "x", "name: x\ndescription: Use when x.\ndisable-model-invocation: true\n", None
    )
    assert checks.run(skill, only="invocation-consistency", target="claude-code") == []


def test_invocation_consistency_reports_an_unparseable_openai_yaml(tmp_path: Path) -> None:
    """A file skillc cannot read must not read as agreement - it is reported."""
    skill = _skill_with_openai_yaml(
        tmp_path, "x",
        "name: x\ndescription: Use when x.\ndisable-model-invocation: true\n",
        "policy: {allow_implicit_invocation: false}\n",  # a flow mapping: outside the subset
    )
    findings = checks.run(skill, only="invocation-consistency", target="claude-code")
    assert findings, "an unparseable agents/openai.yaml must not silently read as agreement"
    assert "openai.yaml" in findings[0].detail


def test_invocation_consistency_reports_a_non_mapping_policy(tmp_path: Path) -> None:
    skill = _skill_with_openai_yaml(
        tmp_path, "x",
        "name: x\ndescription: Use when x.\ndisable-model-invocation: true\n",
        "policy: true\n",
    )
    findings = checks.run(skill, only="invocation-consistency", target="claude-code")
    assert findings and "not a mapping" in findings[0].detail


def test_invocation_consistency_reports_a_non_boolean_allow_implicit_invocation(tmp_path: Path) -> None:
    skill = _skill_with_openai_yaml(
        tmp_path, "x",
        "name: x\ndescription: Use when x.\ndisable-model-invocation: true\n",
        'policy:\n  allow_implicit_invocation: "false"\n',  # a quoted string, not a boolean
    )
    findings = checks.run(skill, only="invocation-consistency", target="claude-code")
    assert findings and "not a boolean" in findings[0].detail


def test_invocation_consistency_is_scoped_to_claude_code(tmp_path: Path) -> None:
    """The claim - do these two client-specific declarations agree - has no
    portable-specification stake, exactly like `claude-code-field`."""
    skill = _skill_with_openai_yaml(
        tmp_path, "x",
        "name: x\ndescription: Use when x.\ndisable-model-invocation: true\n",
        "policy:\n  allow_implicit_invocation: true\n",  # disagrees
    )
    assert checks.run(skill, target="claude-code") != []
    assert [f for f in checks.run(skill, target="portable") if f.rule == "invocation-consistency"] == []
