"""#720: the contract-block parser extensions are OPT-IN; SKILL.md frontmatter keeps its subset."""

from __future__ import annotations

import pytest

from skillc.spec import (
    FrontmatterError,
    parse_contract_block,
    parse_frontmatter,
    parse_yaml_document,
)

LIST_OF_MAPPINGS = "---\nname: x\nitems:\n  - id: a\n    test: t\n---\nbody\n"
FLOW_LIST = "---\nname: x\nreaders: [a, b]\n---\nbody\n"


@pytest.mark.parametrize(("doc", "what"), [(LIST_OF_MAPPINGS, "a list of mappings"), (FLOW_LIST, "a flow sequence")])
def test_skill_frontmatter_still_refuses_the_contract_only_shapes(doc: str, what: str) -> None:
    with pytest.raises(FrontmatterError, match=what):
        parse_frontmatter(doc)
    with pytest.raises(FrontmatterError, match=what):
        parse_yaml_document(doc.split("---\n")[1])


def test_the_contract_block_reads_both() -> None:
    assert parse_contract_block(LIST_OF_MAPPINGS)[0]["items"] == [{"id": "a", "test": "t"}]
    assert parse_contract_block(FLOW_LIST)[0]["readers"] == ["a", "b"]


@pytest.mark.parametrize(("doc", "reason"), [
    ("---\nk: [a, [b]]\n---\n", "nested flow collection"),
    ("---\nk: [a, b\n---\n", "continued onto the next line"),
    ("---\nk: [a, , b]\n---\n", "empty item"),
    ("---\nk:\n  - [a, b]\n---\n", "a flow list inside a list"),
    ("---\nk: one\n  two\n---\n", "use a '>' block"),
    ("---\nk:\n  - id: a\n    what: one\n      two\n---\n", "use a '>' block"),
])
def test_unsupported_contract_yaml_is_refused_by_name(doc: str, reason: str) -> None:
    with pytest.raises(FrontmatterError, match=reason):
        parse_contract_block(doc)


def test_a_list_of_mappings_ends_at_the_next_item_and_at_a_dedent() -> None:
    doc = "---\nprovides:\n  - id: a\n    test: x\n  - id: b\n    test: y\nowner: o\n---\n"
    data = parse_contract_block(doc)[0]
    assert data["provides"] == [{"id": "a", "test": "x"}, {"id": "b", "test": "y"}]
    assert data["owner"] == "o"


@pytest.mark.parametrize("levels", [40, 400])
def test_alternating_list_and_mapping_nesting_is_bounded(levels: int) -> None:
    """Counter-model review on #720: every list item restarted the depth at 1, so
    deep `- k:` nesting passed MAX_DEPTH and 400 levels raised RecursionError."""
    lines = ["---"]
    for n in range(levels):
        lines.append("  " * (2 * n) + "k:")
        lines.append("  " * (2 * n + 1) + "- id: x")
    lines.append("---")
    with pytest.raises(FrontmatterError, match="nesting deeper than"):
        parse_contract_block("\n".join(lines) + "\n")


@pytest.mark.parametrize("doc", [
    '---\nk: ["owner"#comment"]\n---\n',     # the comment would consume the closing bracket
    '---\nk: ["a" b]\n---\n',                 # text after a closing quote
    '---\nk: [a, "b]\n---\n',                 # an unterminated quote
    '---\nk: [a] b\n---\n',                   # text after the closing bracket
])
def test_a_flow_list_a_yaml_loader_rejects_is_refused_too(doc: str) -> None:
    """Counter-model review on #720, pass 2: differential against PyYAML (test-only).
    Every input PyYAML refuses, the contract parser must refuse rather than read."""
    yaml = pytest.importorskip("yaml")
    with pytest.raises(yaml.YAMLError):
        yaml.safe_load(doc.split("---\n")[1])
    with pytest.raises(FrontmatterError):
        parse_contract_block(doc)


@pytest.mark.parametrize("doc", [
    "---\nk:\n  -   id: a\n    t: x\n---\n",          # keys two right of the dash, not under `id`
    "---\nk:\n  -  id: a\n      t: x\n  - id: b\n---\n",  # one column past `id`
])
def test_a_mis_aligned_list_mapping_a_yaml_loader_rejects_is_refused_too(doc: str) -> None:
    """#739: the parser assumed a `- key:` item's keys sit two columns right of
    the dash, silently repairing spacing PyYAML rejects."""
    yaml = pytest.importorskip("yaml")
    with pytest.raises(yaml.YAMLError):
        yaml.safe_load(doc.split("---\n")[1])
    with pytest.raises(FrontmatterError):
        parse_contract_block(doc)


def test_a_tab_after_a_list_dash_is_refused_by_name() -> None:
    with pytest.raises(FrontmatterError, match="a tab after a list dash"):
        parse_contract_block("---\nk:\n  - \tid: a\n---\n")


@pytest.mark.parametrize(("doc", "expected"), [
    ("---\nk:\n  -   id: a\n      t: x\n---\n", [{"id": "a", "t": "x"}]),
    ("---\nk:\n  -  id: a\n     t: x\n  - id: b\n    t: y\n---\n", [{"id": "a", "t": "x"}, {"id": "b", "t": "y"}]),
])
def test_an_aligned_wide_dash_list_mapping_both_parsers_accept_reads_the_same(
    doc: str, expected: list[dict[str, str]],
) -> None:
    yaml = pytest.importorskip("yaml")
    assert yaml.safe_load(doc.split("---\n")[1])["k"] == expected
    assert parse_contract_block(doc)[0]["k"] == expected


@pytest.mark.parametrize(("doc", "expected"), [
    ("---\nk: [a, b]  # note\n---\n", ["a", "b"]),
    ('---\nk: ["a", \'b\']\n---\n', ["a", "b"]),
    ("---\nk: []\n---\n", []),
    ("---\nk: ['a, b']\n---\n", ["a, b"]),          # a quoted comma is one item, as YAML reads it
])
def test_a_flow_list_both_parsers_accept_reads_the_same(doc: str, expected: list[str]) -> None:
    yaml = pytest.importorskip("yaml")
    assert yaml.safe_load(doc.split("---\n")[1])["k"] == expected
    assert parse_contract_block(doc)[0]["k"] == expected
