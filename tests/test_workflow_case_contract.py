"""Format and link checks for the flow-check workflow case contract (#264).

The contract (`evals/workflow-contracts/flow-check/case-contract.json`) is a
specification, not a declaration: #274 owns the validator that a run will go
through. These checks keep the committed example honest in the meantime:
every obligation is fully stated, every case accounts for every obligation,
the Makefile-decided applicability agrees with the fixtures as committed, the
admission rule is applied consistently, and the documents that describe it
link to things that exist. Each structural check has a mutated red case below.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CONTRACT_DIR = ROOT / "evals" / "workflow-contracts" / "flow-check"
CONTRACT = CONTRACT_DIR / "case-contract.json"

VERDICTS = {"SATISFIED", "VIOLATED", "UNKNOWN"}
CLASSES = {"outcome", "adherence", "preservation", "honesty"}
SCOPES = {"common", "treatment"}
LANES = {"explicit-contract", "matched-outcome", "expanded-instruction"}
EXECUTION = {"FC-LINT", "FC-TEST", "FC-TYPECHECK", "FC-SECURITY", "FC-COMPLETENESS"}
#: The execution obligations decided by a fixture's Makefile alone; the other
#: two depend on the declared environment, not on the fixture.
MAKE_TARGETS = {"FC-LINT": "lint", "FC-TEST": "test", "FC-TYPECHECK": "typecheck"}
EXPLICIT_LANES = ("explicit-contract", "expanded-instruction")

DOCS = [
    CONTRACT_DIR / "README.md",
    ROOT / "evals" / "README.md",
    ROOT / "docs" / "specs" / "evaluation-facility" / "protocol.md",
]


def contract_problems(contract: dict, root: Path = ROOT) -> list[str]:
    problems: list[str] = []
    if contract.get("kind") != "workflow-case-contract":
        problems.append("kind is not workflow-case-contract")
    version = contract.get("contract_version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        problems.append("contract_version must be a positive integer")

    for item in contract.get("inventory") or [None]:
        if not isinstance(item, dict) or not re.fullmatch(r"[0-9a-f]{40}", str(item.get("git_blob", ""))):
            problems.append(f"inventory entry without a 40-hex git_blob: {item!r}")
        elif item.get("mode") not in {"100644", "100755"}:
            problems.append(f"inventory entry {item.get('path')} has no file mode")

    ids: list[str] = []
    for ob in contract.get("obligations") or []:
        oid = ob.get("id", "?")
        ids.append(oid)
        if ob.get("class") not in CLASSES:
            problems.append(f"{oid}: class {ob.get('class')!r} not in {sorted(CLASSES)}")
        if ob.get("scope") not in SCOPES:
            problems.append(f"{oid}: scope {ob.get('scope')!r} not in {sorted(SCOPES)}")
        for field in ("source", "applies_when", "evidence"):
            if not str(ob.get(field, "")).strip():
                problems.append(f"{oid}: empty {field}")
        rule = ob.get("rule")
        if not isinstance(rule, dict) or set(rule) != VERDICTS or not all(str(v).strip() for v in rule.values()):
            problems.append(f"{oid}: rule must state exactly SATISFIED, VIOLATED and UNKNOWN")
    if not ids:
        problems.append("no obligations: an empty contract cannot be checked")
    if len(ids) != len(set(ids)):
        problems.append("duplicate obligation ids")
    known = set(ids)

    cases = contract.get("cases") or []
    if not cases:
        problems.append("no cases: an empty matrix cannot be checked")
    for case in cases:
        task = case.get("task", "?")
        na, ap = set(case.get("not_applicable", [])), set(case.get("applicable", []))
        if na & ap:
            problems.append(f"{task}: {sorted(na & ap)} both applicable and not")
        if na | ap != known:
            problems.append(f"{task}: does not account for every obligation exactly ({sorted(known ^ (na | ap))})")
        if set(case.get("lanes", {})) != LANES:
            problems.append(f"{task}: lanes must be exactly {sorted(LANES)}")
        admitted = bool(ap & EXECUTION)
        for lane in EXPLICIT_LANES:
            excluded = str(case.get("lanes", {}).get(lane, "")).startswith("excluded")
            if excluded == admitted:
                problems.append(f"{task}: {lane} disagrees with the admission rule (execution obligations: {sorted(ap & EXECUTION)})")

        task_dir = root / task
        grader = task_dir / "grader.json"
        if not grader.is_file():
            problems.append(f"{task}: no grader.json")
            continue
        if json.loads(grader.read_text()).get("revision") != case.get("grader_revision"):
            problems.append(f"{task}: grader_revision does not match the committed grader")
        makefile = task_dir / "fixture" / "Makefile"
        text = makefile.read_text() if makefile.is_file() else ""
        for oid, target in MAKE_TARGETS.items():
            has = re.search(rf"^{target}:", text, re.MULTILINE) is not None
            if has != (oid in ap):
                problems.append(f"{task}: {oid} classification contradicts the fixture Makefile")
    return problems


def _slug(heading: str) -> str:
    """GitHub's heading anchor: lowercase, punctuation other than '-' dropped, spaces to '-'."""
    text = re.sub(r"[`*_]", "", heading.strip().lower())
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def link_problems(doc: Path) -> list[str]:
    problems = []
    text = re.sub(r"```.*?```", "", doc.read_text(), flags=re.DOTALL)
    for target in re.findall(r"\]\(([^)\s]+)\)", text):
        if re.match(r"[a-z]+:", target):
            continue
        path_part, _, anchor = target.partition("#")
        dest = (doc.parent / path_part).resolve() if path_part else doc
        if not dest.exists():
            problems.append(f"{doc.name}: link to missing {target}")
            continue
        if anchor and dest.suffix == ".md":
            slugs = {_slug(h) for h in re.findall(r"^#+\s+(.*)$", dest.read_text(), re.MULTILINE)}
            if anchor not in slugs:
                problems.append(f"{doc.name}: anchor #{anchor} not a heading in {dest.name}")
    return problems


def _load() -> dict:
    return json.loads(CONTRACT.read_text())


def test_committed_contract_has_no_problems() -> None:
    assert contract_problems(_load()) == []


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: str(p.relative_to(ROOT)))
def test_relative_links_resolve(doc: Path) -> None:
    assert link_problems(doc) == []


def _mutations() -> dict:
    def drop_unknown_rule(c):
        del c["obligations"][0]["rule"]["UNKNOWN"]

    def bad_class(c):
        c["obligations"][0]["class"] = "convenience"

    def both_lists(c):
        c["cases"][0]["applicable"].append(c["cases"][0]["not_applicable"][0])

    def missing_obligation(c):
        c["cases"][0]["applicable"].remove("FC-READONLY")

    def wrong_revision(c):
        c["cases"][0]["grader_revision"] = "99"

    def admitted_without_execution(c):
        c["cases"][0]["lanes"]["explicit-contract"] = "applicable"

    def lint_claimed_applicable(c):
        c["cases"][0]["not_applicable"].remove("FC-LINT")
        c["cases"][0]["applicable"].append("FC-LINT")

    def empty_matrix(c):
        c["cases"] = []

    def blob_missing(c):
        c["inventory"][0]["git_blob"] = "HEAD"

    return {f.__name__: f for f in (
        drop_unknown_rule, bad_class, both_lists, missing_obligation, wrong_revision,
        admitted_without_execution, lint_claimed_applicable, empty_matrix, blob_missing,
    )}


@pytest.mark.parametrize("name", sorted(_mutations()))
def test_each_mutation_is_refused(name: str) -> None:
    mutated = copy.deepcopy(_load())
    _mutations()[name](mutated)
    assert contract_problems(mutated), f"mutation {name} was not detected"


def test_fixture_with_a_test_target_contradicts_a_not_applicable_entry(tmp_path: Path) -> None:
    """The Makefile check reads the fixture, not the contract: a fixture that
    gains a `test:` target makes the committed N/A entry wrong."""
    contract = _load()
    case = contract["cases"][0]
    src = ROOT / case["task"]
    dst = tmp_path / case["task"]
    (dst / "fixture").mkdir(parents=True)
    (dst / "grader.json").write_text((src / "grader.json").read_text())
    (dst / "fixture" / "Makefile").write_text("check:\n\tpython3 ci/check.py\ntest:\n\tpytest\n")
    contract["cases"] = [case]
    assert any("FC-TEST classification contradicts" in p for p in contract_problems(contract, root=tmp_path))


def test_a_broken_link_is_reported(tmp_path: Path) -> None:
    (tmp_path / "target.md").write_text("# Real heading\n")
    doc = tmp_path / "doc.md"
    doc.write_text("[ok](target.md#real-heading) [gone](missing.md) [bad](target.md#no-such)\n")
    problems = link_problems(doc)
    assert len(problems) == 2, problems
