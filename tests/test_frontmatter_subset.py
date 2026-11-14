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
    ("---\nk: ['a, b']\n---\n", "quoted flow-list item containing a comma"),
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
