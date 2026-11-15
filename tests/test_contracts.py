"""`skillc contracts`: CHARTER.md contracts checked across a collection (#720)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from skillc import checks, cli, contracts

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "evals/subjects/contracts-example"
CONTROLS = ROOT / "controls"


def _rules(root: Path) -> list[str]:
    return sorted({f.rule for f in checks.run_contracts(contracts.load_collection(root))})


# ---------------------------------------------------------------- the fixture


def test_the_fixture_reports_the_lanes_miss_then_clean_once_fixed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """#720 acceptance: handoff-version BAD at the @2/@3 mismatch, GOOD once fixed."""
    assert cli.main(["contracts", str(FIXTURE)]) == contracts.EXIT_FINDINGS
    out = capsys.readouterr().out
    assert "handoff-version" in out and "consumes 'eli5.section-c@2'" in out and "at @3" in out
    assert _rules(FIXTURE) == ["handoff-version"]

    fixed = tmp_path / "fixed"
    shutil.copytree(FIXTURE, fixed)
    auto = fixed / "flow/auto/CHARTER.md"
    auto.write_text(auto.read_text(encoding="utf-8").replace("eli5.section-c@2", "eli5.section-c@3"), encoding="utf-8")
    assert cli.main(["contracts", str(fixed)]) == contracts.EXIT_CLEAN
    out = capsys.readouterr().out
    assert "CONTRACTS: 3 declared, 0 bad, 3 good; 0 error(s), 0 warning(s)" in out


def test_no_charter_is_none_declared_with_its_own_exit_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "skill").mkdir()
    (tmp_path / "skill/SKILL.md").write_text("---\nname: skill\ndescription: x\n---\n", encoding="utf-8")
    assert cli.main(["contracts", str(tmp_path)]) == contracts.EXIT_NONE_DECLARED == 3
    out = capsys.readouterr().out
    assert "CONTRACTS: none declared" in out and "0 problems" not in out and "0 error" not in out


def test_a_missing_collection_is_a_usage_error(tmp_path: Path) -> None:
    assert cli.main(["contracts", str(tmp_path / "absent")]) == contracts.EXIT_USAGE == 2


def test_warnings_alone_do_not_fail_the_run(tmp_path: Path) -> None:
    shutil.copytree(CONTROLS / "approval-present/bad/intent-string", tmp_path / "c")
    assert _rules(tmp_path / "c") == ["approval-present"]
    assert cli.main(["contracts", str(tmp_path / "c")]) == contracts.EXIT_CLEAN


def test_a_shape_failure_stops_the_hand_off_rules_and_says_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """A provider that does not parse must not be blamed as 'nothing provides it'."""
    case = tmp_path / "c"
    shutil.copytree(CONTROLS / "handoff-bilateral/good/provided", case)
    (case / "alpha/CHARTER.md").write_text("---\ncontract: [alpha\n---\n", encoding="utf-8")
    assert _rules(case) == ["contract-shape"]
    assert cli.main(["contracts", str(case)]) == contracts.EXIT_FINDINGS
    assert "hand-off rules" in capsys.readouterr().out


# ---------------------------------------------------------------- brace expansion


@pytest.mark.parametrize(("test", "paths", "problem"), [
    ("a/b", ["a/b"], None),
    ("a/{bad,good}", ["a/bad", "a/good"], None),
    ("a/{x}/c", ["a/x/c"], None),
    ("{a,b}/{c,d}", [], "2 brace groups"),
    ("a/{b,{c,d}}", [], "unbalanced or nested"),
    ("a/{b,}", [], "empty brace option"),
    ("a/b}", [], "unbalanced or nested"),
])
def test_brace_expansion_is_one_level(test: str, paths: list[str], problem: str | None) -> None:
    got, why = contracts.expand(test)
    assert got == paths
    assert (why is None) if problem is None else (problem in str(why))


def test_any_missing_expansion_makes_the_clause_unbacked_not_partial(tmp_path: Path) -> None:
    case = tmp_path / "c"
    shutil.copytree(CONTROLS / "clause-backed/good/every-test-exists", case)
    assert _rules(case) == []
    shutil.rmtree(case / "checks/alpha-never/bad")
    findings = checks.run_contracts(contracts.load_collection(case), only="clause-backed")
    assert len(findings) == 1 and "alpha-never/bad" in findings[0].detail and "unbacked" in findings[0].detail


def test_a_test_path_outside_the_collection_is_unbacked(tmp_path: Path) -> None:
    case = tmp_path / "c"
    shutil.copytree(CONTROLS / "clause-backed/good/every-test-exists", case)
    charter = case / "alpha/CHARTER.md"
    charter.write_text(charter.read_text(encoding="utf-8").replace(
        "checks/alpha-out/{bad,good}", "../outside"), encoding="utf-8")
    (tmp_path / "outside").mkdir()
    details = [f.detail for f in checks.run_contracts(contracts.load_collection(case), only="clause-backed")]
    assert any("outside the collection" in d for d in details)


# ---------------------------------------------------------------- the other rules' edges


def test_reader_resolves_a_full_clause_id_too(tmp_path: Path) -> None:
    """`flow-plan-record.approve` resolves to a clause named `approve`, AND to a
    clause whose id is the whole dotted string."""
    case = tmp_path / "c"
    shutil.copytree(CONTROLS / "reader-exists/good/owner-contract-and-clause", case)
    beta = case / "beta/CHARTER.md"
    beta.write_text(beta.read_text(encoding="utf-8").replace("- id: approve", "- id: beta.approve"), encoding="utf-8")
    assert _rules(case) == []


def test_negative_backed_needs_a_whole_bad_segment(tmp_path: Path) -> None:
    case = tmp_path / "c"
    shutil.copytree(CONTROLS / "negative-backed/good/bad-case-named", case)
    charter = case / "alpha/CHARTER.md"
    charter.write_text(charter.read_text(encoding="utf-8").replace(
        "checks/alpha-never/{bad,good}", "checks/alpha-never/badly"), encoding="utf-8")
    (case / "checks/alpha-never/badly").mkdir()
    assert "negative-backed" in _rules(case)


def test_a_contract_name_declared_twice_is_a_shape_error(tmp_path: Path) -> None:
    case = tmp_path / "c"
    shutil.copytree(CONTROLS / "contract-shape/good/valid", case)
    shutil.copytree(case / "alpha", case / "alpha-copy")
    assert _rules(case) == ["contract-shape"]


def test_clause_ids_must_be_unique_within_a_contract(tmp_path: Path) -> None:
    case = tmp_path / "c"
    shutil.copytree(CONTROLS / "contract-shape/good/valid", case)
    charter = case / "alpha/CHARTER.md"
    charter.write_text(charter.read_text(encoding="utf-8").replace("id: alpha.never", "id: alpha.out"), encoding="utf-8")
    details = [f.detail for f in checks.run_contracts(contracts.load_collection(case), only="contract-shape")]
    assert any("declared 2 times" in d for d in details)


@pytest.mark.parametrize("bad_version", ["0", "true", "two"])
def test_version_must_be_a_positive_integer(tmp_path: Path, bad_version: str) -> None:
    case = tmp_path / "c"
    shutil.copytree(CONTROLS / "contract-shape/good/valid", case)
    charter = case / "alpha/CHARTER.md"
    charter.write_text(charter.read_text(encoding="utf-8").replace("version: 1", f"version: {bad_version}"), encoding="utf-8")
    assert _rules(case) == ["contract-shape"]


def test_a_malformed_consumes_entry_is_a_shape_error(tmp_path: Path) -> None:
    case = tmp_path / "c"
    shutil.copytree(CONTROLS / "handoff-bilateral/good/provided", case)
    beta = case / "beta/CHARTER.md"
    beta.write_text(beta.read_text(encoding="utf-8").replace("alpha.out@1", "alpha.out"), encoding="utf-8")
    assert _rules(case) == ["contract-shape"]


# ---------------------------------------------------------------- counter-model review, pass 1


def test_a_clause_provided_twice_is_a_shape_error_and_stops_the_hand_off_rules(tmp_path: Path) -> None:
    """File order must never pick which provider's version a consumer is judged against."""
    assert _rules(CONTROLS / "contract-shape/bad/duplicate-provider") == ["contract-shape"]
    details = [f.detail for f in checks.run_contracts(
        contracts.load_collection(CONTROLS / "contract-shape/bad/duplicate-provider"), only="contract-shape")]
    assert any("provided by 2 contracts" in d for d in details)


def test_a_duplicate_contract_name_stops_the_hand_off_rules(tmp_path: Path) -> None:
    case = tmp_path / "c"
    shutil.copytree(CONTROLS / "reader-exists/good/owner-contract-and-clause", case)
    # A second "beta" WITHOUT the approve clause: before the fix it could shadow
    # the real one and make reader-exists blame alpha's valid reader.
    (case / "zz-beta").mkdir()
    (case / "zz-beta/CHARTER.md").write_text(
        (case / "beta/CHARTER.md").read_text(encoding="utf-8").replace("- id: approve", "- id: other"),
        encoding="utf-8")
    assert _rules(case) == ["contract-shape"]


def test_a_symlink_out_of_the_collection_does_not_back_a_clause(tmp_path: Path) -> None:
    case = tmp_path / "c"
    shutil.copytree(CONTROLS / "clause-backed/good/every-test-exists", case)
    outside = tmp_path / "outside"
    (outside / "bad").mkdir(parents=True)
    (outside / "good").mkdir()
    charter = case / "alpha/CHARTER.md"
    charter.write_text(charter.read_text(encoding="utf-8").replace(
        "checks/alpha-out/{bad,good}", "checks/external/{bad,good}"), encoding="utf-8")
    (case / "checks/external").symlink_to(outside, target_is_directory=True)
    details = [f.detail for f in checks.run_contracts(contracts.load_collection(case), only="clause-backed")]
    assert details and all("outside the collection" in d for d in details)


def test_a_brace_option_is_a_literal_path_fragment_not_a_regex_escape() -> None:
    assert contracts.expand("checks/{bad,\\q}")[0] == ["checks/bad", "checks/\\q"]
    assert contracts.expand("a/{x,\\1}/b")[0] == ["a/x/b", "a/\\1/b"]


def test_an_oversized_consumed_version_is_a_shape_finding_not_a_crash(tmp_path: Path) -> None:
    case = tmp_path / "c"
    shutil.copytree(CONTROLS / "handoff-bilateral/good/provided", case)
    beta = case / "beta/CHARTER.md"
    beta.write_text(beta.read_text(encoding="utf-8").replace("alpha.out@1", "alpha.out@" + "9" * 4400),
                    encoding="utf-8")
    assert _rules(case) == ["contract-shape"]


# ---------------------------------------------------------------- counter-model review, pass 2


def test_an_unreadable_subtree_refuses_certification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """A contract in a subtree discovery could not read must not drop out and
    leave a clean verdict behind (it read `1 declared, 0 bad`, exit 0)."""
    import os

    case = tmp_path / "c"
    shutil.copytree(CONTROLS / "reader-exists/bad/clause-typo", case)
    real_scandir = os.scandir

    def scandir(path: Path) -> object:
        if str(path).endswith(os.sep + "alpha"):
            raise PermissionError(13, "Permission denied", str(path))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", scandir)
    collection = contracts.load_collection(case)
    assert collection.unreadable
    assert "contract-shape" in _rules(case)
    assert cli.main(["contracts", str(case)]) == contracts.EXIT_FINDINGS
    assert "could not be read" in capsys.readouterr().out


@pytest.mark.parametrize("value", ['"\\0"', '"\\udc80"'])
def test_an_unusable_filesystem_path_is_a_finding_not_a_crash(tmp_path: Path, value: str) -> None:
    case = tmp_path / "c"
    shutil.copytree(CONTROLS / "clause-backed/good/every-test-exists", case)
    charter = case / "alpha/CHARTER.md"
    charter.write_text(charter.read_text(encoding="utf-8").replace(
        "test: checks/alpha-out/{bad,good}", f"test: {value}"), encoding="utf-8")
    details = [f.detail for f in checks.run_contracts(contracts.load_collection(case), only="clause-backed")]
    # An attributed clause-backed finding and a completed run - never a traceback.
    assert any("unbacked" in d and "alpha.out" in d for d in details)
    assert cli.main(["contracts", str(case)]) == contracts.EXIT_FINDINGS


def test_every_run_says_a_bad_segment_proves_presence_not_failure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """#720 gate: a green `skillc contracts` must never read as "this clause's test
    can fail". Every run that examined contracts prints the limit, and the spec
    states it under the same words."""
    cli.main(["contracts", str(FIXTURE)])
    out = capsys.readouterr().out
    assert "shows a negative case is present, not that it can fail" in out
    spec = (Path(__file__).resolve().parents[1] / "docs/specs/contracts.md").read_text(encoding="utf-8")
    assert "It proves a negative case is PRESENT,\nnot that it can fail." in spec
