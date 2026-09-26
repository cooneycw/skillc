"""Frontmatter types, the supported YAML subset, and target-scoped field rules (#3).

Three instruments live here, each with the input that makes it say the other thing:

- the parser is compared against a real YAML loader (PyYAML, a DEV dependency
  only) on every input skillc claims to read, so "inside the subset" means "reads
  it the way YAML does", not "returns something";
- every input skillc refuses is classified the same way, so a refusal that says
  "invalid YAML" is one a real loader also refuses, and one that says "outside the
  subset" is one a real loader accepts;
- `skillc/` is walked for imports, so the stdlib-only runtime is a checked fact.

PyYAML resolves plain scalars by YAML 1.1 (`yes` is a boolean there). The corpus
avoids the handful of spellings where 1.1 and skillc's 1.2 core schema disagree.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

import pytest
import yaml

from skillc import checks, cli
from skillc.spec import (
    CLAUDE_CODE,
    FRONTMATTER_RE,
    FrontmatterError,
    Skill,
    discover,
    parse_frontmatter,
)

ROOT = Path(__file__).resolve().parent.parent
CONTROLS = ROOT / "controls"


def _parse(block: str) -> dict[str, object]:
    return parse_frontmatter(f"---\n{block}---\nbody\n")[0]


def _skill(tmp_path: Path, name: str, block: str) -> Skill:
    path = tmp_path / name / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text(f"---\n{block}---\nbody\n", encoding="utf-8")
    return Skill.load(path)


# --------------------------------------------------- the subset reads like YAML

INSIDE_THE_SUBSET = {
    "folded": "name: a\ndescription: >\n  Use when checking\n  skills.\n",
    "folded-paragraphs": "d: >\n  one\n  two\n\n  three\n",
    "folded-more-indented": "d: >-\n  a\n   indented\n  b\n\n\n",
    "literal": "d: |\n  line one\n    indented\n\n  after blank\n",
    "literal-keep": "d: |+\n  a\n\n\nx: 1\n",
    "literal-strip": "d: |-\n  a\n  b\n",
    "literal-keep-at-end": "d: |+\n  a\n\n",
    "folded-at-end": "d: >\n  a\n  b\n",
    "indent-indicator": "d: >2\n    leading spaces\n  kept\n",
    "block-list": "paths:\n  - '*.py'\n  - \"src/**\"\n  - plain # comment\nname: n\n",
    "block-list-same-indent": "paths:\n- a\n- b\nk: v\n",
    "core-types": "a:\nb: ~\nc: true\nd: 1.5\ne: 0x1F\nf: '12'\ng: -3\nh: null\n",
    "nested": "metadata:\n  version: '1.0'\n  nested:\n    deep: x\n",
    "quoting": "a: 'it''s'\nb: \"tab\\there \\u00e9 \\/\"\nc: C# code # comment\n",
    "colons-without-space": "a: http://x.y/z\nb: e.g. foo:bar\n",
    "comment-only-value": "a: # nothing here\nb: 1\n",
}


@pytest.mark.parametrize("block", INSIDE_THE_SUBSET.values(), ids=INSIDE_THE_SUBSET.keys())
def test_the_subset_reads_what_a_yaml_loader_reads(block: str) -> None:
    # Compare on the block a SKILL.md actually yields: the extraction drops the
    # newline before the closing `---`, which decides a block scalar's last break.
    document = f"---\n{block}---\nbody\n"
    match = FRONTMATTER_RE.match(document)
    assert match
    assert parse_frontmatter(document)[0] == yaml.safe_load(match.group(1))


def _control_blocks() -> list[Path]:
    return sorted(p for p in CONTROLS.rglob("SKILL.md") if FRONTMATTER_RE.match(p.read_text()))


@pytest.mark.parametrize("path", _control_blocks(), ids=lambda p: str(p.relative_to(CONTROLS)))
def test_every_control_skillc_reads_is_read_as_yaml_reads_it(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(text)
    assert match
    try:
        ours: object = parse_frontmatter(text)[0]
    except FrontmatterError:
        pytest.skip("diagnosed; classified by the refusal tests below")
    assert ours == yaml.safe_load(match.group(1))


# ------------------------------------------ refusals say which kind they are

INVALID_YAML = {
    "colon-in-plain": "d: Use when: x\n",
    "unknown-escape": 'a: "x\\q"\n',
    "text-after-quote": "a: 'x' y\n",
    "reserved-indicator": "a: @x\n",
    "tab-indent": "m:\n\tk: v\n",
}
OUTSIDE_THE_SUBSET = {
    "flow-sequence": "t: [a, b]\n",
    "flow-mapping": "t: {a: 1}\n",
    "anchor": "a: &x 1\n",
    "tag": "a: !!str 1\n",
    "multi-line-plain": "a: foo\n  bar\n",
    "list-of-mappings": "k:\n  - a: 1\n",
    "nested-list": "k:\n  - - a\n",
    "multi-line-quoted": "a: 'one\n  two'\n",
}


@pytest.mark.parametrize("block", INVALID_YAML.values(), ids=INVALID_YAML.keys())
def test_what_skillc_calls_invalid_a_yaml_loader_also_rejects(block: str) -> None:
    with pytest.raises(FrontmatterError, match="invalid YAML"):
        _parse(block)
    with pytest.raises(yaml.YAMLError):
        yaml.safe_load(block)


@pytest.mark.parametrize("block", OUTSIDE_THE_SUBSET.values(), ids=OUTSIDE_THE_SUBSET.keys())
def test_what_skillc_cannot_read_is_named_as_outside_the_subset(block: str) -> None:
    """Valid YAML skillc does not read must say so - never 'expected key: value'."""
    yaml.safe_load(block)  # the premise: this IS valid YAML
    with pytest.raises(FrontmatterError, match="outside the YAML subset skillc reads"):
        _parse(block)


def test_an_unreadable_skill_is_still_an_error(tmp_path: Path) -> None:
    """Outside the subset means unchecked, and unchecked must not read as clean."""
    skill = _skill(tmp_path, "x", "name: x\ndescription: Use when x.\nallowed-tools: [Read]\n")
    findings = checks.run(skill)
    assert [(f.rule, f.severity) for f in findings] == [("frontmatter", checks.ERROR)]


def test_the_review_folded_description_is_accepted(tmp_path: Path) -> None:
    """The assessment's first counterexample: rejected as a frontmatter error before #3."""
    skill = _skill(
        tmp_path, "valid-folded", "name: valid-folded\ndescription: >\n  Use when checking skills.\n"
    )
    assert skill.parse_error is None
    assert skill.get("description") == "Use when checking skills."
    assert checks.run(skill) == []


# ------------------------------------------- required values have string type

@pytest.mark.parametrize("key", ["name", "description"])
@pytest.mark.parametrize(
    ("block_value", "kind"),
    [
        ("\n  nested: value", "a mapping"),
        (" 404", "a number (404)"),
        (" true", "a boolean (True)"),
        ("", "null (no value)"),
        ("\n  - a", "a list"),
    ],
    ids=["mapping", "number", "boolean", "null", "list"],
)
def test_a_required_value_that_is_not_a_string_is_refused_by_its_owner(
    tmp_path: Path, key: str, block_value: str, kind: str
) -> None:
    other = "description: Use when x.\n" if key == "name" else "name: x\n"
    skill = _skill(tmp_path, "x", f"{key}:{block_value}\n{other}")
    assert skill.parse_error is None
    findings = checks.run(skill)
    assert [(f.rule, f.detail) for f in findings] == [
        ("required-fields", f"{key} must be a string, got {kind}")
    ]


def test_the_review_mapping_values_are_refused(tmp_path: Path) -> None:
    """The assessment's second counterexample: zero findings, exit 0, before #3."""
    skill = _skill(tmp_path, "x", "name:\n  nested: value\ndescription:\n  nested: value\n")
    rc = cli.cmd_check(argparse.Namespace(path=str(skill.path), rule=None, strict=False))
    assert rc == 1
    assert {f.detail for f in checks.run(skill)} == {
        "name must be a string, got a mapping",
        "description must be a string, got a mapping",
    }


def test_an_empty_string_name_is_refused(tmp_path: Path) -> None:
    skill = _skill(tmp_path, "x", "name: ''\ndescription: Use when x.\n")
    assert [f.detail for f in checks.run(skill, only="required-fields")] == ["name is empty"]


# ---------------------------------------------------- target-scoped field rules


EXTENSION = "name: x\ndescription: Use when x.\nuser-invocable: false\n"
INERT = "name: x\ndescription: Use when x.\ntrigger: secrets\n"


def test_an_extension_field_is_non_portable_but_known_to_its_target(tmp_path: Path) -> None:
    skill = _skill(tmp_path, "x", EXTENSION)
    portable = checks.run(skill, target="portable")
    assert [f.rule for f in portable] == ["unknown-field"]
    assert "Claude Code extension" in portable[0].detail
    assert "any harness" not in portable[0].detail
    assert checks.run(skill, target="claude-code") == []


def test_an_inert_field_is_reported_under_every_target(tmp_path: Path) -> None:
    skill = _skill(tmp_path, "x", INERT)
    assert [f.rule for f in checks.run(skill, target="portable")] == ["unknown-field"]
    claude = checks.run(skill, target="claude-code")
    assert [f.rule for f in claude] == ["claude-code-field"]
    assert CLAUDE_CODE.verified in claude[0].detail and CLAUDE_CODE.source in claude[0].detail


def test_the_claude_code_profile_matches_its_documentation_snapshot() -> None:
    """Pinned to the 2026-09-25 reading of the source. Changing it means re-reading it."""
    assert CLAUDE_CODE.verified == "2026-09-25"
    assert sorted(CLAUDE_CODE.extensions) == sorted({
        "when_to_use", "argument-hint", "arguments", "disable-model-invocation",
        "user-invocable", "disallowed-tools", "model", "effort", "context", "agent",
        "background", "hooks", "paths", "shell",
    })
    doc = (ROOT / "docs" / "frontmatter.md").read_text(encoding="utf-8")
    for name in CLAUDE_CODE.extensions:
        assert f"`{name}`" in doc, f"{name} is enforced but not documented"


def test_check_names_its_target_and_refuses_an_unknown_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    skill = _skill(tmp_path, "x", EXTENSION)
    assert cli.main(["check", str(skill.path)]) == 0
    assert "field rules checked against target 'portable'" in capsys.readouterr().out
    assert cli.main(["check", str(skill.path), "--target", "claude-code"]) == 0
    assert "target 'claude-code'" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        cli.main(["check", str(skill.path), "--target", "every-harness"])
    with pytest.raises(ValueError, match="unknown target"):
        checks.run(skill, target="every-harness")


def test_a_rule_and_a_target_that_disagree_are_refused(tmp_path: Path) -> None:
    skill = _skill(tmp_path, "x", EXTENSION)
    argv = ["check", str(skill.path), "--rule", "claude-code-field", "--target", "portable"]
    assert cli.main(argv) == 2


# --------------------------------------------------------------- stdlib only


def _third_party(sources: list[str]) -> tuple[set[str], list[str]]:
    """Every top-level module the sources import, and those outside the stdlib."""
    imported: set[str] = set()
    for source in sources:
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imported.add(node.module.split(".")[0])
    return imported, sorted(imported - set(sys.stdlib_module_names) - {"skillc", "__future__"})


def test_the_runtime_imports_only_the_standard_library() -> None:
    sources = [p.read_text(encoding="utf-8") for p in (ROOT / "skillc").glob("*.py")]
    imported, third_party = _third_party(sources)
    assert imported, "the import walk found nothing - it is blind, not clean"
    assert third_party == [], f"skillc/ must stay stdlib-only: {third_party}"


def test_the_stdlib_walk_can_see_a_third_party_import() -> None:
    """Negative control for the walk above: a planted import is caught."""
    sources = [p.read_text(encoding="utf-8") for p in (ROOT / "skillc").glob("*.py")]
    planted = "import yaml\nfrom pydantic.fields import Field\nfrom . import spec\n"
    assert _third_party([*sources, planted])[1] == ["pydantic", "yaml"]


def test_discovery_still_loads_every_control() -> None:
    assert discover(CONTROLS), "no control skill discovered"
