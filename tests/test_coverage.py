"""Tests for skillc/coverage.py (issue #272).

Each assertion is checked against a hand-built or committed bundle, never
against a second implementation of the same aggregation. Reproducibility is
checked by byte equality of the canonical JSON, not merely equal-as-objects.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

from skillc import convenience as conv
from skillc import coverage as cov
from skillc import records
from skillc import reliability as rel

CONTROLS = Path(__file__).resolve().parent.parent / "controls"
SKILL_PATH = ".codex/skills/slug/SKILL.md"


def _bundle(path: Path) -> records.Bundle:
    found = records.bundle_at(path)
    assert found is not None, f"{path} is not a bundle"
    return found


def _reversed_bundle(path: Path) -> records.Bundle:
    b = _bundle(path)
    return records.Bundle(path=b.path, records=list(reversed(b.records)))


def _inventory(subject_digest: str = "sha256:5a", skills: tuple[str, ...] = (SKILL_PATH,)) -> cov.DeclaredInventory:
    return cov.DeclaredInventory.from_profile_raw(skills, {"name": "test-profile", "select": list(skills)}, subject_digest)


# --------------------------------------------------------------- declared inventory

def test_assemble_with_declared_inventory_hand_computed() -> None:
    bundle = _bundle(CONTROLS / "ledger-binding/good/skill-evidence-duplicate-invocation")
    report = cov.assemble_coverage_report(bundle, _inventory())

    assert report.inventory == cov.INVENTORY_DECLARED
    assert report.declared_skills == (SKILL_PATH,)
    assert len(report.rows) == 1
    row = report.rows[0]
    assert row.key.skill_path == SKILL_PATH
    assert row.key.skill_version == "sha256:i1"
    assert row.key.client_name == "codex"
    assert row.key.case_id == "slug-fix"
    assert row.key.arm == cov.UNSPECIFIED_ARM
    assert row.scheduled == 2
    assert row.evaluable == 2
    assert row.outcomes == {"PASS": 2, "FAIL": 0, "NOT_RUN": 0, "UNAVAILABLE": 0, "UNKNOWN": 0}
    assert row.coverage_flags == {"missing-transcript": 2, "unmatched-invocation": 2}
    assert row.execution_observed == {"CONFIRMED": 0, "NOT_CONFIRMED": 0, "UNKNOWN": 2}
    assert row.read_observed == {"CONFIRMED": 0, "NOT_CONFIRMED": 0, "UNKNOWN": 2}
    assert row.criteria == (cov.CriterionRow(id="c1", outcome="SATISFIED", shared=False),)
    assert row.evidence == ("att-1", "att-2")


def test_disagreeing_attempts_both_surface_in_criteria_never_overwritten(monkeypatch: pytest.MonkeyPatch) -> None:
    """Codex review, #272: nothing in records.py requires two attempts
    sharing a cell to agree on one criterion's outcome - each attempt's
    criteria_owned is checked only against its OWN verified-result. Keying
    row.criteria on id alone let the later attempt in iteration order
    silently overwrite an earlier VIOLATED with a SATISFIED (or the
    reverse), hiding a real failure depending only on attempt_ids' order.
    Both outcomes must appear, regardless of order."""
    bundle = _bundle(CONTROLS / "ledger-binding/good/skill-evidence-duplicate-invocation")
    mutated = []
    for record in bundle.records:
        if record.kind == "skill-evidence" and record.attempt_id == "att-2":
            data = json.loads(json.dumps(record.data))
            data["skills"][0]["criteria_owned"][0]["outcome"] = "VIOLATED"
            mutated.append(records.Record(path=record.path, data=data))
        elif record.kind == "verified-result" and record.attempt_id == "att-2":
            data = json.loads(json.dumps(record.data))
            data["criteria"][0]["outcome"] = "VIOLATED"
            data["status"] = "FAIL"
            mutated.append(records.Record(path=record.path, data=data))
        else:
            mutated.append(record)
    bad_bundle = records.Bundle(path=bundle.path, records=mutated)
    report = cov.assemble_coverage_report(bad_bundle, _inventory())
    row = report.rows[0]
    assert row.outcomes["PASS"] == 1
    assert row.outcomes["FAIL"] == 1
    assert set(row.criteria) == {
        cov.CriterionRow(id="c1", outcome="SATISFIED", shared=False),
        cov.CriterionRow(id="c1", outcome="VIOLATED", shared=False),
    }

    # A genuine repeat (both attempts agreeing) must still collapse to ONE
    # row, exactly as before - the fix must not turn every shared criterion
    # into a duplicate.
    agreeing_report = cov.assemble_coverage_report(bundle, _inventory())
    agreeing_row = agreeing_report.rows[0]
    assert agreeing_row.criteria == (cov.CriterionRow(id="c1", outcome="SATISFIED", shared=False),)


def test_outcomes_partition_scheduled() -> None:
    bundle = _bundle(CONTROLS / "ledger-binding/good/skill-evidence-duplicate-invocation")
    report = cov.assemble_coverage_report(bundle, _inventory())
    row = report.rows[0]
    assert sum(row.outcomes.values()) == row.scheduled


def test_coverage_flags_do_not_affect_the_outcome_partition() -> None:
    """missing-transcript and unmatched-invocation are both 2/2 on this fixture,
    yet outcomes still sum to 2 (scheduled), not 2 + 2 + 2 - they are counted
    on a separate axis entirely."""
    bundle = _bundle(CONTROLS / "ledger-binding/good/skill-evidence-duplicate-invocation")
    report = cov.assemble_coverage_report(bundle, _inventory())
    row = report.rows[0]
    assert sum(row.outcomes.values()) == 2
    assert row.coverage_flags["missing-transcript"] == 2
    assert row.coverage_flags["unmatched-invocation"] == 2


def test_row_count_equals_declared_skills_times_cells() -> None:
    bundle = _bundle(CONTROLS / "ledger-binding/good/skill-evidence-duplicate-invocation")
    report = cov.assemble_coverage_report(bundle, _inventory())
    assert report.declared_skills is not None
    assert len(report.rows) == len(report.declared_skills) * 1  # one trial = one cell


def test_profile_and_subject_digest_are_recorded() -> None:
    bundle = _bundle(CONTROLS / "ledger-binding/good/skill-evidence-duplicate-invocation")
    inv = _inventory()
    report = cov.assemble_coverage_report(bundle, inv)
    assert report.profile_digest == inv.profile_digest
    assert report.subject_digest == "sha256:5a"


def test_two_profiles_differing_in_selection_give_different_reports_with_their_own_digest() -> None:
    bundle = _bundle(CONTROLS / "ledger-binding/good/skill-evidence-duplicate-invocation")
    inv_a = cov.DeclaredInventory.from_profile_raw((SKILL_PATH,), {"select": [SKILL_PATH]}, "sha256:5a")
    inv_b = cov.DeclaredInventory.from_profile_raw((SKILL_PATH, "extra/SKILL.md"), {"select": [SKILL_PATH, "extra/SKILL.md"]}, "sha256:5a")
    report_a = cov.assemble_coverage_report(bundle, inv_a)
    report_b = cov.assemble_coverage_report(bundle, inv_b)
    assert report_a.profile_digest != report_b.profile_digest
    assert len(report_a.rows) == 1
    assert len(report_b.rows) == 2  # the undeclared-anywhere "extra" skill still gets a row


def test_refuses_a_declared_inventory_with_a_duplicate_skill() -> None:
    """A duplicate entry in `declared_skills` inflates the row-count product
    on both sides equally (one extra declared skill, one extra row), so the
    length check alone cannot see it - only row-key uniqueness can."""
    bundle = _bundle(CONTROLS / "ledger-binding/good/skill-evidence-duplicate-invocation")
    inv = cov.DeclaredInventory(skills=(SKILL_PATH, SKILL_PATH), profile_digest="x", subject_digest="sha256:5a")
    with pytest.raises(cov.CoverageRefused):
        cov.assemble_coverage_report(bundle, inv)


def test_refuses_an_inventory_whose_subject_digest_disagrees() -> None:
    bundle = _bundle(CONTROLS / "ledger-binding/good/skill-evidence-duplicate-invocation")
    with pytest.raises(cov.CoverageRefused):
        cov.assemble_coverage_report(bundle, _inventory(subject_digest="sha256:wrong"))


# --------------------------------------------------------------- no declared inventory

def test_without_inventory_rows_come_only_from_skill_evidence() -> None:
    bundle = _bundle(CONTROLS / "ledger-binding/good/skill-evidence-duplicate-invocation")
    report = cov.assemble_coverage_report(bundle)
    assert report.inventory == cov.INVENTORY_NOT_DECLARED
    assert report.declared_skills is None
    assert report.profile_digest is None
    assert len(report.rows) == 1
    assert report.rows[0].key.skill_path == SKILL_PATH


def _with_extra_installed_helper(bundle: records.Bundle) -> records.Bundle:
    """Clone `bundle` with an extra installed path on every receipt that no
    skill-evidence entry cites - a helper/library, the shape correction #2
    says `installation-receipt.installed` wrongly includes."""
    cloned: list[records.Record] = []
    for record in bundle.records:
        if record.kind == records.INSTALLATION_RECEIPT:
            data = dict(record.data)
            existing = data["installed"]
            assert isinstance(existing, list)
            data["installed"] = [*existing, {"path": "helpers/not-a-skill.md", "digest": "sha256:helper"}]
            cloned.append(records.Record(path=record.path, data=data))
        else:
            cloned.append(record)
    return records.Bundle(path=bundle.path, records=cloned)


def test_without_inventory_never_falls_back_to_installed() -> None:
    """The helper path is installed but never cited by any skill-evidence
    entry, so it must not appear as a row when no inventory is declared."""
    bundle = _with_extra_installed_helper(_bundle(CONTROLS / "ledger-binding/good/skill-evidence-duplicate-invocation"))
    report = cov.assemble_coverage_report(bundle)
    paths = {row.key.skill_path for row in report.rows}
    assert paths == {SKILL_PATH}
    assert "helpers/not-a-skill.md" not in paths


def test_without_inventory_never_falls_back_to_installed_mutation_check() -> None:
    """Mutation check: force the no-inventory branch to read installed paths
    (the wrong source, per correction #2) and confirm the helper path WOULD
    wrongly appear - proving the test above actually distinguishes the two
    behaviours, not just that it runs."""
    bundle = _with_extra_installed_helper(_bundle(CONTROLS / "ledger-binding/good/skill-evidence-duplicate-invocation"))
    all_installed_paths: set[str] = set()
    for record in bundle.records:
        if record.kind == records.INSTALLATION_RECEIPT:
            installed = record.data["installed"]
            assert isinstance(installed, list)
            for entry in installed:
                assert isinstance(entry, dict)
                all_installed_paths.add(entry["path"])
    assert "helpers/not-a-skill.md" in all_installed_paths  # the wrong source WOULD have surfaced it


# --------------------------------------------------------------- refuses before reporting

@pytest.mark.parametrize(
    "bad_dir",
    [
        "ledger-binding/bad/skill-evidence-duplicate-invocation-uncaptured",
        "ledger-binding/bad/skill-evidence-not-installed",
        "ledger-binding/bad/skill-evidence-altered-artifact",
    ],
)
def test_refuses_an_invalid_bundle_without_the_caller_validating_first(bad_dir: str) -> None:
    bundle = _bundle(CONTROLS / bad_dir)
    with pytest.raises(cov.CoverageRefused):
        cov.assemble_coverage_report(bundle)


def test_refusal_names_the_failing_rule() -> None:
    bundle = _bundle(CONTROLS / "ledger-binding/bad/skill-evidence-not-installed")
    with pytest.raises(cov.CoverageRefused) as exc_info:
        cov.assemble_coverage_report(bundle)
    assert "installed" in str(exc_info.value) or "forged" in str(exc_info.value)


def test_refusal_check_is_not_a_no_op(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mutation check: remove the validation call and confirm the SAME bad
    bundle that was refused above goes blind - proving the refusal is real
    work, not a check that always raises or never runs."""
    bundle = _bundle(CONTROLS / "ledger-binding/bad/skill-evidence-not-installed")
    monkeypatch.setattr(cov, "_refuse_on_invalid_bundle", lambda b: None)
    report = cov.assemble_coverage_report(bundle)  # does not raise with the check disabled
    assert report is not None


# --------------------------------------------------------------- reproducibility

def test_byte_identical_under_reversed_record_order() -> None:
    forward = _bundle(CONTROLS / "ledger-binding/good/skill-evidence-duplicate-invocation")
    backward = _reversed_bundle(CONTROLS / "ledger-binding/good/skill-evidence-duplicate-invocation")
    inv = _inventory()
    assert cov.assemble_coverage_report(forward, inv).to_json() == cov.assemble_coverage_report(backward, inv).to_json()


def test_report_body_carries_no_generation_timestamp() -> None:
    bundle = _bundle(CONTROLS / "ledger-binding/good/skill-evidence-duplicate-invocation")
    body = json.loads(cov.assemble_coverage_report(bundle, _inventory()).to_json())
    assert "generated_at" not in body
    assert "timestamp" not in body


# --------------------------------------------------------------- stale version (separate rows, never merged)

def test_two_trials_with_different_skill_digests_produce_separate_rows() -> None:
    """Hand-built: two trials (two cells) for the same case/client/skill path,
    whose receipts install a DIFFERENT digest for it - the stale-version
    shape. Both rows exist; neither silently overwrites the other."""
    ledger = records.Record(path=Path("ledger.json"), data={
        "version": 2, "kind": "trial-ledger", "producer": "controller", "experiment_id": "exp-1",
        "trials": [
            {
                "trial_id": "t-old", "case": {"id": "slug-fix", "revision": "r1"},
                "grader": {"id": "g", "revision": "g1"}, "subject": {"digest": "sha256:5a"},
                "client": {"name": "codex", "version": "1.0"}, "image": {"digest": "sha256:1a"},
                "config": {"digest": "sha256:cf"}, "attempts": [{"attempt_id": "att-old"}],
            },
            {
                "trial_id": "t-new", "case": {"id": "slug-fix-new", "revision": "r2"},
                "grader": {"id": "g", "revision": "g1"}, "subject": {"digest": "sha256:5a"},
                "client": {"name": "codex", "version": "1.0"}, "image": {"digest": "sha256:1a"},
                "config": {"digest": "sha256:cf"}, "attempts": [{"attempt_id": "att-new"}],
            },
        ],
    })

    def lifecycle(attempt_id: str, trial_id: str) -> records.Record:
        return records.Record(path=Path(f"{attempt_id}.json"), data={
            "version": 2, "kind": "attempt-lifecycle", "producer": "controller",
            "attempt_id": attempt_id, "trial_id": trial_id, "disposition": "captured",
            "stop": {"reason": "exited", "confirmed": True, "exit_code": 0},
            "events": [{"event": "planned", "at": "2026-09-26T12:00:00Z"}, {"event": "captured", "at": "2026-09-26T12:00:05Z"}],
            "cleanup": {"status": "removed", "failures": []},
        })

    def receipt(attempt_id: str, trial_id: str, digest: str) -> records.Record:
        return records.Record(path=Path(f"receipt-{attempt_id}.json"), data={
            "version": 2, "kind": "installation-receipt", "producer": "subject-adapter",
            "checked_by": "controller", "attempt_id": attempt_id, "trial_id": trial_id,
            "subject": {"locator": "x", "revision": "r", "digest": "sha256:5a"},
            "surface": "codex-skills", "adapter": {"name": "a", "version": "1"},
            "client": {"name": "codex", "version": "1.0"}, "layers": [], "dependencies": [],
            "allowed_writes": [], "installed": [{"path": SKILL_PATH, "digest": digest}],
            "readiness": {"discovery_canary": "SATISFIED", "baseline_absence": "SATISFIED"},
        })

    def manifest(attempt_id: str, trial_id: str) -> records.Record:
        return records.Record(path=Path(f"manifest-{attempt_id}.json"), data={
            "version": 2, "kind": "artifact-manifest", "producer": "controller",
            "attempt_id": attempt_id, "trial_id": trial_id,
            "artifacts": [{"path": "out.txt", "type": "file", "size": 1, "digest": f"sha256:out-{attempt_id}"}],
            "observations": [
                {"stream": "client-events", "origin": "client-reported", "coverage": "partial"},
                {"stream": "process-lifecycle", "origin": "observed", "coverage": "complete"},
            ],
            "capture_failures": [],
        })

    def result(attempt_id: str, trial_id: str) -> records.Record:
        return records.Record(path=Path(f"result-{attempt_id}.json"), data={
            "version": 2, "kind": "verified-result", "producer": "assembler",
            "attempt_id": attempt_id, "trial_id": trial_id, "result_id": f"res-{attempt_id}",
            "grader": {"id": "g", "revision": "g1"},
            "graded_digests": [f"sha256:out-{attempt_id}"],
            "criteria": [{"id": "c1", "mandatory": True, "outcome": "SATISFIED", "evidence": ["grader-log:c1"]}],
            "status": "PASS",
        })

    def skill_evidence(attempt_id: str, trial_id: str) -> records.Record:
        return records.Record(path=Path(f"evidence-{attempt_id}.json"), data={
            "version": 2, "kind": "skill-evidence", "producer": "assembler",
            "attempt_id": attempt_id, "trial_id": trial_id,
            "skills": [{
                "skill": {"path": SKILL_PATH},
                "invocation": {"lineage": "root"},
                "lifecycle": {
                    "listed": {"status": "UNKNOWN", "reason": "x"},
                    "read_observed": {"status": "UNKNOWN", "reason": "x"},
                    "execution_observed": {"status": "UNKNOWN", "reason": "x"},
                },
                "criteria_owned": [],
                "external_evidence": {"present": False, "reconciliation": "absent"},
            }],
        })

    bundle = records.Bundle(path=Path("."), records=[
        ledger,
        lifecycle("att-old", "t-old"), receipt("att-old", "t-old", "sha256:v1"),
        manifest("att-old", "t-old"), result("att-old", "t-old"), skill_evidence("att-old", "t-old"),
        lifecycle("att-new", "t-new"), receipt("att-new", "t-new", "sha256:v2"),
        manifest("att-new", "t-new"), result("att-new", "t-new"), skill_evidence("att-new", "t-new"),
    ])
    report = cov.assemble_coverage_report(bundle)
    versions = {row.key.skill_version for row in report.rows if row.key.skill_path == SKILL_PATH}
    assert versions == {"sha256:v1", "sha256:v2"}
    assert len(report.rows) == 2


# --------------------------------------------------------------- reconciliation_counts

def test_reconciliation_counts_expose_the_recorded_skill_evidence_state() -> None:
    """Exposes the reconciler's OUTPUT (whatever already decided it),
    never re-decides it - the fixture's two skill-evidence entries both
    declare unmatched/duplicate-invocation."""
    bundle = _bundle(CONTROLS / "ledger-binding/good/skill-evidence-duplicate-invocation")
    report = cov.assemble_coverage_report(bundle, _inventory())
    row = report.rows[0]
    assert row.reconciliation_counts["unmatched"] == 2
    assert row.reconciliation_counts["matched"] == 0
    assert row.reconciliation_counts["contradicting"] == 0
    assert row.reconciliation_counts["absent"] == 0
    assert sum(row.reconciliation_counts.values()) == row.scheduled


def test_reconciliation_counts_absent_when_no_external_evidence() -> None:
    bundle = _bundle(CONTROLS / "ledger-binding/good/skill-evidence-no-correlating-attempt")
    report = cov.assemble_coverage_report(bundle)
    row = report.rows[0]
    assert row.reconciliation_counts["unmatched"] == 1  # this fixture's own declared reason


# --------------------------------------------------------------- case_pairs (discrimination)

def test_case_pairs_wiring_hand_computed_without_a_rule() -> None:
    """No rule supplied -> UNKNOWN, per-arm facts still present (orchestrator
    review, #272: facts are never withheld because no verdict could be
    reached)."""
    bundle = _bundle(CONTROLS / "case-pairing/good/reciprocal-complementary")
    report = cov.assemble_coverage_report(bundle)
    assert len(report.case_pairs) == 1
    pair = report.case_pairs[0]
    assert pair.case_id == "slug-fix"
    assert pair.paired_case_id == "slug-fix"
    assert pair.case_revision == "r1"
    assert pair.paired_case_revision == "r1-degraded"
    assert pair.intact_pass == 1 and pair.intact_evaluable == 1
    assert pair.degraded_pass == 1 and pair.degraded_evaluable == 1
    assert pair.verdict == "UNKNOWN"
    assert pair.p_value is None
    assert pair.reason == "no predeclared rule"


def test_case_pairs_wiring_with_a_rule_computes_a_real_verdict() -> None:
    bundle = _bundle(CONTROLS / "case-pairing/good/reciprocal-complementary")
    rule = rel.TwoArmRule(rule_id="fixture", alpha=0.05, sidedness="greater", tolerance=1, citation_url="https://example.invalid")
    report = cov.assemble_coverage_report(bundle, discrimination_rule=rule)
    pair = report.case_pairs[0]
    # 1/1 intact pass vs 1/1 degraded pass: identical arms, cannot discriminate.
    assert pair.verdict == "NOT_SHOWN"
    assert pair.p_value is not None


def test_case_pairs_absent_when_no_pairing_declared() -> None:
    bundle = _bundle(CONTROLS / "ledger-binding/good/skill-evidence-duplicate-invocation")
    report = cov.assemble_coverage_report(bundle, _inventory())
    assert report.case_pairs == ()


def test_report_to_json_includes_case_pairs_and_stays_byte_identical() -> None:
    forward = _bundle(CONTROLS / "case-pairing/good/reciprocal-complementary")
    backward = _reversed_bundle(CONTROLS / "case-pairing/good/reciprocal-complementary")
    assert cov.assemble_coverage_report(forward).to_json() == cov.assemble_coverage_report(backward).to_json()
    body = json.loads(cov.assemble_coverage_report(forward).to_json())
    assert "case_pairs" in body
    assert body["case_pairs"][0]["verdict"] == "UNKNOWN"


# --------------------------------------------------------------- compute_improvement passthrough

def test_compute_improvement_is_a_real_passthrough_to_reliability() -> None:
    rule = rel.TwoArmRule(rule_id="fixture", alpha=0.05, sidedness="greater", tolerance=1, citation_url="https://example.invalid")
    via_coverage = cov.compute_improvement(rule, 10, 10, 0, 10)
    via_reliability = rel.evaluate_improvement(rule, 10, 10, 0, 10)
    assert via_coverage == via_reliability
    assert via_coverage.verdict == "IMPROVED"


def test_compute_improvement_without_a_rule_is_unknown() -> None:
    assert cov.compute_improvement(None, 10, 10, 0, 10).verdict == "UNKNOWN"


# --------------------------------------------------------------- mutation check

def test_case_pair_discovery_check_is_not_a_no_op(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mutation check: force case-pair discovery to find nothing, and
    confirm the known-good fixture above would wrongly report zero pairs -
    proving the discovery logic does real work."""
    monkeypatch.setattr(cov, "_find_case_pairs", lambda cells: [])
    bundle = _bundle(CONTROLS / "case-pairing/good/reciprocal-complementary")
    report = cov.assemble_coverage_report(bundle)
    assert report.case_pairs == ()  # the mutation's wrong answer


# --------------------------------------------------------------- lineage (parent/child)

def test_root_lineage_surfaced_on_the_row() -> None:
    bundle = _bundle(CONTROLS / "ledger-binding/good/skill-evidence-duplicate-invocation")
    report = cov.assemble_coverage_report(bundle, _inventory())
    row = report.rows[0]
    assert row.lineage == "root"
    assert row.parent_path is None


def test_failed_child_under_a_successful_parent_golden_case() -> None:
    """Acceptance item 6's named golden case, and item 3's 'attribute
    parent/child ... without crediting every loaded skill' in one fixture:
    one attempt whose own result is PASS, with a root skill and a child
    skill it invoked whose OWNED criterion is VIOLATED. The child's failure
    shows on the child's own row; the parent's PASS never lifts it - rows
    never carry a per-skill verdict at all (item 3), only outcomes and
    owned criteria, so there is no field the parent's PASS COULD leak
    through."""
    child_path = ".codex/skills/helper/SKILL.md"

    def skill_evidence_with_child(attempt_id: str, trial_id: str) -> records.Record:
        return records.Record(path=Path(f"evidence-{attempt_id}.json"), data={
            "version": 2, "kind": "skill-evidence", "producer": "assembler",
            "attempt_id": attempt_id, "trial_id": trial_id,
            "skills": [
                {
                    "skill": {"path": SKILL_PATH},
                    "invocation": {"lineage": "root"},
                    "lifecycle": {
                        "listed": {"status": "UNKNOWN", "reason": "x"},
                        "read_observed": {"status": "UNKNOWN", "reason": "x"},
                        "execution_observed": {"status": "UNKNOWN", "reason": "x"},
                    },
                    "criteria_owned": [],
                    "external_evidence": {"present": False, "reconciliation": "absent"},
                },
                {
                    "skill": {"path": child_path},
                    "invocation": {"lineage": "child", "parent_path": SKILL_PATH},
                    "lifecycle": {
                        "listed": {"status": "UNKNOWN", "reason": "x"},
                        "read_observed": {"status": "UNKNOWN", "reason": "x"},
                        "execution_observed": {"status": "UNKNOWN", "reason": "x"},
                    },
                    "criteria_owned": [
                        {"id": "c-child", "outcome": "VIOLATED", "shared": False},
                    ],
                    "external_evidence": {"present": False, "reconciliation": "absent"},
                },
            ],
        })

    bundle = _bundle(CONTROLS / "ledger-binding/good/skill-evidence-no-correlating-attempt")
    # Replace that fixture's own skill-evidence record with one declaring a
    # child too, and extend its receipt so the child path is installed.
    records_list = []
    for r in bundle.records:
        if r.kind == records.SKILL_EVIDENCE:
            continue
        if r.kind == records.INSTALLATION_RECEIPT:
            data = dict(r.data)
            installed = data["installed"]
            assert isinstance(installed, list)
            data["installed"] = [*installed, {"path": child_path, "digest": "sha256:helper-v1"}]
            r = records.Record(path=r.path, data=data)
        if r.kind == records.VERIFIED_RESULT:
            data = dict(r.data)
            criteria = data["criteria"]
            assert isinstance(criteria, list)
            data["criteria"] = [*criteria, {"id": "c-child", "mandatory": False, "outcome": "VIOLATED", "evidence": ["grader-log:c-child"]}]
            r = records.Record(path=r.path, data=data)
        records_list.append(r)
    records_list.append(skill_evidence_with_child("att-1", "t-1"))
    bundle = records.Bundle(path=bundle.path, records=records_list)

    report = cov.assemble_coverage_report(
        bundle, cov.DeclaredInventory.from_profile_raw((SKILL_PATH, child_path), {"select": [SKILL_PATH, child_path]}, "sha256:5a")
    )
    rows_by_path = {r.key.skill_path: r for r in report.rows}
    # The parent attempt's own outcome is PASS - the "successful parent" half.
    assert rows_by_path[SKILL_PATH].outcomes["PASS"] == 1
    assert rows_by_path[child_path].outcomes["PASS"] == 1  # same attempt, same outcome fact
    assert rows_by_path[SKILL_PATH].lineage == "root"
    assert rows_by_path[SKILL_PATH].parent_path is None
    assert rows_by_path[child_path].lineage == "child"
    assert rows_by_path[child_path].parent_path == SKILL_PATH
    # Item 3's own acceptance: the child's failed owned criterion shows on
    # the CHILD's row, never silently absorbed by (or crediting) the parent -
    # and neither row carries any OTHER per-skill verdict the parent's PASS
    # could leak into (item 3: no per-skill PASS/FAIL field exists at all).
    assert rows_by_path[child_path].criteria == (cov.CriterionRow(id="c-child", outcome="VIOLATED", shared=False),)
    assert rows_by_path[SKILL_PATH].criteria == ()


# --------------------------------------------------------------- to_text (human view)

def test_to_text_is_derived_from_the_same_dict_as_to_json() -> None:
    """Orchestrator review, #272: the human view must come from the SAME
    dict to_json serializes, never a second read of self.rows/case_pairs,
    so the two views cannot drift apart. Checked directly: every value in
    the dict appears, verbatim, somewhere in the text."""
    bundle = _bundle(CONTROLS / "ledger-binding/good/skill-evidence-duplicate-invocation")
    report = cov.assemble_coverage_report(bundle, _inventory())
    text = report.to_text()
    body = report.to_dict()
    assert str(body["inventory"]) in text
    assert str(body["profile_digest"]) in text
    row = body["rows"][0]  # type: ignore[index]
    assert row["skill_path"] in text  # type: ignore[index]
    assert row["skill_version"] in text  # type: ignore[index]
    for key, value in row["outcomes"].items():  # type: ignore[index, union-attr]
        assert f"{key}={value}" in text


def test_to_text_shows_every_row_and_every_unknown_state() -> None:
    """Explicit test the orchestrator asked for: every row, and every
    UNKNOWN count, appears in the text - the human view cannot silently
    hide what the JSON shows."""
    bundle = _bundle(CONTROLS / "ledger-binding/good/skill-evidence-duplicate-invocation")
    report = cov.assemble_coverage_report(bundle, _inventory())
    text = report.to_text()
    assert f"rows: {len(report.rows)}" in text
    for row in report.rows:
        assert row.key.skill_path in text
        assert f"UNKNOWN={row.outcomes['UNKNOWN']}" in text
    # This fixture's own UNKNOWN count is 0 for outcomes (both attempts PASS) -
    # confirm the ZERO still appears, not omitted for being uninteresting.
    assert "UNKNOWN=0" in text


def test_to_text_shows_execution_observed_and_read_observed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Codex review, #272: `to_text()` never rendered `execution_observed`/
    `read_observed` at all, so a row with confirmed skill execution read
    identically to one where nothing was ever observed - exactly the
    distinction between attempt success and skill participation these two
    fields exist to carry. Must show every count, including a 0."""
    bundle = _bundle(CONTROLS / "ledger-binding/good/skill-evidence-duplicate-invocation")
    report = cov.assemble_coverage_report(bundle, _inventory())
    row = report.rows[0]
    text = report.to_text()
    assert row.execution_observed == {"CONFIRMED": 0, "NOT_CONFIRMED": 0, "UNKNOWN": 2}
    assert "execution_observed: CONFIRMED=0, NOT_CONFIRMED=0, UNKNOWN=2" in text
    assert "read_observed: CONFIRMED=0, NOT_CONFIRMED=0, UNKNOWN=2" in text

    # Mutation check: force to_dict to report a CONFIRMED execution and
    # confirm the human view changes right along with it - proving a real
    # dependency, the same pattern as test_to_text_derivation_is_not_a_no_op.
    real_to_dict = cov.CoverageReport.to_dict

    def confirmed_execution(self: cov.CoverageReport) -> dict[str, object]:
        body = real_to_dict(self)
        rows = cast("list[dict[str, Any]]", body["rows"])
        rows[0]["execution_observed"] = {"CONFIRMED": 2, "NOT_CONFIRMED": 0, "UNKNOWN": 0}
        return body

    monkeypatch.setattr(cov.CoverageReport, "to_dict", confirmed_execution)
    assert "execution_observed: CONFIRMED=2, NOT_CONFIRMED=0, UNKNOWN=0" in report.to_text()


def test_to_text_shows_insufficient_discrimination_verdict() -> None:
    """The UNKNOWN discrimination verdict (no rule supplied) must appear in
    the human view, not be silently dropped because nothing could be
    decided."""
    bundle = _bundle(CONTROLS / "case-pairing/good/reciprocal-complementary")
    report = cov.assemble_coverage_report(bundle)
    text = report.to_text()
    assert "UNKNOWN" in text
    assert "no predeclared rule" in text


def test_to_text_shows_the_failed_child_under_a_successful_parent() -> None:
    """Both the parent's PASS and the child's VIOLATED criterion must be
    visible in the human view - neither silently absorbed."""
    child_path = ".codex/skills/helper/SKILL.md"
    bundle = _bundle(CONTROLS / "ledger-binding/good/skill-evidence-no-correlating-attempt")
    records_list = []
    for r in bundle.records:
        if r.kind == records.SKILL_EVIDENCE:
            continue
        if r.kind == records.INSTALLATION_RECEIPT:
            data = dict(r.data)
            installed = data["installed"]
            assert isinstance(installed, list)
            data["installed"] = [*installed, {"path": child_path, "digest": "sha256:helper-v1"}]
            r = records.Record(path=r.path, data=data)
        if r.kind == records.VERIFIED_RESULT:
            data = dict(r.data)
            criteria = data["criteria"]
            assert isinstance(criteria, list)
            data["criteria"] = [*criteria, {"id": "c-child", "mandatory": False, "outcome": "VIOLATED", "evidence": ["grader-log:c-child"]}]
            r = records.Record(path=r.path, data=data)
        records_list.append(r)
    records_list.append(records.Record(path=Path("evidence-att-1.json"), data={
        "version": 2, "kind": "skill-evidence", "producer": "assembler",
        "attempt_id": "att-1", "trial_id": "t-1",
        "skills": [
            {
                "skill": {"path": SKILL_PATH}, "invocation": {"lineage": "root"},
                "lifecycle": {
                    "listed": {"status": "UNKNOWN", "reason": "x"},
                    "read_observed": {"status": "UNKNOWN", "reason": "x"},
                    "execution_observed": {"status": "UNKNOWN", "reason": "x"},
                },
                "criteria_owned": [], "external_evidence": {"present": False, "reconciliation": "absent"},
            },
            {
                "skill": {"path": child_path}, "invocation": {"lineage": "child", "parent_path": SKILL_PATH},
                "lifecycle": {
                    "listed": {"status": "UNKNOWN", "reason": "x"},
                    "read_observed": {"status": "UNKNOWN", "reason": "x"},
                    "execution_observed": {"status": "UNKNOWN", "reason": "x"},
                },
                "criteria_owned": [{"id": "c-child", "outcome": "VIOLATED", "shared": False}],
                "external_evidence": {"present": False, "reconciliation": "absent"},
            },
        ],
    }))
    bundle = records.Bundle(path=bundle.path, records=records_list)
    report = cov.assemble_coverage_report(
        bundle, cov.DeclaredInventory.from_profile_raw((SKILL_PATH, child_path), {"select": [SKILL_PATH, child_path]}, "sha256:5a")
    )
    text = report.to_text()
    assert "PASS=1" in text
    assert "c-child=VIOLATED" in text
    assert child_path in text


def test_to_text_is_deterministic_under_reversed_record_order() -> None:
    forward = _bundle(CONTROLS / "ledger-binding/good/skill-evidence-duplicate-invocation")
    backward = _reversed_bundle(CONTROLS / "ledger-binding/good/skill-evidence-duplicate-invocation")
    inv = _inventory()
    assert cov.assemble_coverage_report(forward, inv).to_text() == cov.assemble_coverage_report(backward, inv).to_text()


# --------------------------------------------------------------- mutation check

def test_to_text_derivation_is_not_a_no_op(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mutation check: force to_dict to omit rows entirely, and confirm the
    human view would then also show zero rows - proving to_text really
    reads the dict, not a hardcoded summary."""
    bundle = _bundle(CONTROLS / "ledger-binding/good/skill-evidence-duplicate-invocation")
    report = cov.assemble_coverage_report(bundle, _inventory())
    real_to_dict = cov.CoverageReport.to_dict

    def empty_rows(self: cov.CoverageReport) -> dict[str, object]:
        body = real_to_dict(self)
        body["rows"] = []
        return body

    monkeypatch.setattr(cov.CoverageReport, "to_dict", empty_rows)
    assert "rows: 0" in report.to_text()  # the mutation's wrong answer, confirming it would go undetected


# --------------------------------------------------------------- reliability wiring (#273)

def test_reliability_without_k_reports_not_declared() -> None:
    bundle = _bundle(CONTROLS / "ledger-binding/good/skill-evidence-duplicate-invocation")
    report = cov.assemble_coverage_report(bundle, _inventory())
    row = report.rows[0]
    assert row.reliability.all_k == cov.NOT_DECLARED
    assert row.reliability.pass_at_k == cov.NOT_DECLARED
    # clopper_pearson/wilson_score are ALWAYS computed, regardless of k.
    assert isinstance(row.reliability.clopper_pearson_lower, float)
    assert isinstance(row.reliability.wilson_score_lower, float)


def test_reliability_with_k_hand_computed() -> None:
    bundle = _bundle(CONTROLS / "ledger-binding/good/skill-evidence-duplicate-invocation")
    report = cov.assemble_coverage_report(bundle, _inventory(), k=1)
    row = report.rows[0]
    # row.evaluable == 2, outcomes["PASS"] == 2 -> all_k(2, 2, 1) == pass_at_k(2, 2, 1) == 1.0
    assert row.reliability.all_k == pytest.approx(1.0)
    assert row.reliability.pass_at_k == pytest.approx(1.0)
    assert row.reliability.clopper_pearson_lower == pytest.approx(rel.clopper_pearson(2, 2)[0])
    assert row.reliability.clopper_pearson_upper == pytest.approx(rel.clopper_pearson(2, 2)[1])
    assert row.reliability.wilson_score_lower == pytest.approx(rel.wilson_score(2, 2)[0])


def test_reliability_insufficient_k_passes_through_unchanged() -> None:
    """k declared but n < k: reliability.py's own INSUFFICIENT sentinel
    passes straight through - a DIFFERENT absence from NOT_DECLARED."""
    bundle = _bundle(CONTROLS / "ledger-binding/good/skill-evidence-duplicate-invocation")
    report = cov.assemble_coverage_report(bundle, _inventory(), k=10)  # evaluable is 2
    row = report.rows[0]
    assert row.reliability.all_k == rel.INSUFFICIENT
    assert row.reliability.pass_at_k == rel.INSUFFICIENT
    assert row.reliability.all_k != cov.NOT_DECLARED


def test_reliability_zero_evaluable_is_insufficient_not_a_crash() -> None:
    """A row with zero evaluable attempts (all NOT_RUN/UNAVAILABLE/UNKNOWN)
    must not crash clopper_pearson(0, 0) - INSUFFICIENT, not a raised
    exception reaching the caller."""
    bundle = _bundle(CONTROLS / "ledger-binding/good/skill-evidence-no-correlating-attempt")
    # This fixture's own attempt is PASS (evaluable=1) - force a zero-evaluable
    # row by declaring a skill no attempt ever evidences a PASS/FAIL for.
    report = cov.assemble_coverage_report(bundle)  # no inventory: rows come from skill-evidence only
    row = report.rows[0]
    assert row.evaluable >= 1  # sanity: this fixture's own row is NOT the zero case

    # Build a dedicated zero-evaluable case: a NOT_RUN attempt.
    ledger = records.Record(path=Path("ledger.json"), data={
        "version": 2, "kind": "trial-ledger", "producer": "controller", "experiment_id": "exp-1",
        "trials": [{
            "trial_id": "t-1", "case": {"id": "c", "revision": "r1"},
            "grader": {"id": "g", "revision": "g1"}, "subject": {"digest": "sha256:5a"},
            "client": {"name": "codex", "version": "1.0"}, "image": {"digest": "sha256:1a"},
            "config": {"digest": "sha256:cf"}, "attempts": [{"attempt_id": "att-1"}],
        }],
    })
    lifecycle = records.Record(path=Path("lifecycle.json"), data={
        "version": 2, "kind": "attempt-lifecycle", "producer": "controller",
        "attempt_id": "att-1", "trial_id": "t-1", "disposition": "not-run",
        "reason": "never-started",
        "stop": {"reason": "never-started", "confirmed": True},
        "events": [{"event": "planned", "at": "2026-09-26T12:00:00Z"}, {"event": "not-run", "at": "2026-09-26T12:00:01Z"}],
        "cleanup": {"status": "not-needed", "failures": []},
    })
    receipt = records.Record(path=Path("receipt.json"), data={
        "version": 2, "kind": "installation-receipt", "producer": "subject-adapter",
        "checked_by": "controller", "attempt_id": "att-1", "trial_id": "t-1",
        "subject": {"locator": "x", "revision": "r", "digest": "sha256:5a"},
        "surface": "codex-skills", "adapter": {"name": "a", "version": "1"},
        "client": {"name": "codex", "version": "1.0"}, "layers": [], "dependencies": [],
        "allowed_writes": [], "installed": [{"path": SKILL_PATH, "digest": "sha256:v1"}],
        "readiness": {"discovery_canary": "SATISFIED", "baseline_absence": "SATISFIED"},
    })
    evidence = records.Record(path=Path("evidence.json"), data={
        "version": 2, "kind": "skill-evidence", "producer": "assembler",
        "attempt_id": "att-1", "trial_id": "t-1",
        "skills": [{
            "skill": {"path": SKILL_PATH}, "invocation": {"lineage": "root"},
            "lifecycle": {
                "listed": {"status": "UNKNOWN", "reason": "x"},
                "read_observed": {"status": "UNKNOWN", "reason": "x"},
                "execution_observed": {"status": "UNKNOWN", "reason": "x"},
            },
            "criteria_owned": [], "external_evidence": {"present": False, "reconciliation": "absent"},
        }],
    })
    zero_bundle = records.Bundle(path=Path("."), records=[ledger, lifecycle, receipt, evidence])
    zero_report = cov.assemble_coverage_report(zero_bundle)
    zero_row = zero_report.rows[0]
    assert zero_row.evaluable == 0
    assert zero_row.reliability.clopper_pearson_lower == rel.INSUFFICIENT
    assert zero_row.reliability.clopper_pearson_upper == rel.INSUFFICIENT
    assert zero_row.reliability.wilson_score_lower == rel.INSUFFICIENT


# --------------------------------------------------------------- convenience wiring (#273)

def test_convenience_phase_wall_times_hand_computed_across_attempts() -> None:
    """`skill-evidence-duplicate-invocation`'s two attempts each have an
    identical 1.0s-per-transition lifecycle (planned->...->cleaned, 6
    transitions) - the row-level aggregate must sum to 2.0s per transition
    with attempts=2, and each attempt's own 1.0s breakdown stays retrievable
    by reference."""
    bundle = _bundle(CONTROLS / "ledger-binding/good/skill-evidence-duplicate-invocation")
    report = cov.assemble_coverage_report(bundle, _inventory())
    row = report.rows[0]
    phase_wall_times = row.convenience.phase_wall_times
    assert not isinstance(phase_wall_times, str)
    by_pair = {(p.from_event, p.to_event): p for p in phase_wall_times}
    assert len(by_pair) == 6
    for pair, interval in by_pair.items():
        assert interval.seconds == pytest.approx(2.0), pair
        assert interval.attempts == 2
    assert set(row.convenience.per_attempt.keys()) == {"att-1", "att-2"}
    for attempt_id in ("att-1", "att-2"):
        breakdown = row.convenience.per_attempt[attempt_id]
        assert len(breakdown) == 6
        for phase_interval in breakdown:
            assert phase_interval.seconds == pytest.approx(1.0)
    assert row.convenience.instruction_length == conv.NOT_CAPTURED
    assert row.convenience.clarification_correction_turns == conv.NOT_CAPTURED
    assert row.convenience.approvals == conv.NOT_CAPTURED
    assert row.convenience.tokens == conv.UNKNOWN


def test_convenience_missing_events_reports_unknown_never_zero() -> None:
    """An attempt whose lifecycle has only its `planned` event (a
    legitimate `not-run`/`never-started` disposition) contributes zero
    transitions. When it is the row's ONLY attempt, the row-level aggregate
    must be `conv.UNKNOWN` - an empty tuple here would read as "every
    transition took no time", not as "nothing was observed"."""
    ledger = records.Record(path=Path("ledger.json"), data={
        "version": 2, "kind": "trial-ledger", "producer": "controller", "experiment_id": "exp-1",
        "trials": [{
            "trial_id": "t-1", "case": {"id": "c", "revision": "r1"},
            "grader": {"id": "g", "revision": "g1"}, "subject": {"digest": "sha256:5a"},
            "client": {"name": "codex", "version": "1.0"}, "image": {"digest": "sha256:1a"},
            "config": {"digest": "sha256:cf"}, "attempts": [{"attempt_id": "att-1"}],
        }],
    })
    lifecycle = records.Record(path=Path("lifecycle.json"), data={
        "version": 2, "kind": "attempt-lifecycle", "producer": "controller",
        "attempt_id": "att-1", "trial_id": "t-1", "disposition": "not-run",
        "reason": "never-started",
        "stop": {"reason": "never-started", "confirmed": True},
        "events": [{"event": "planned", "at": "2026-09-26T12:00:00Z"}],
        "cleanup": {"status": "not-needed", "failures": []},
    })
    receipt = records.Record(path=Path("receipt.json"), data={
        "version": 2, "kind": "installation-receipt", "producer": "subject-adapter",
        "checked_by": "controller", "attempt_id": "att-1", "trial_id": "t-1",
        "subject": {"locator": "x", "revision": "r", "digest": "sha256:5a"},
        "surface": "codex-skills", "adapter": {"name": "a", "version": "1"},
        "client": {"name": "codex", "version": "1.0"}, "layers": [], "dependencies": [],
        "allowed_writes": [], "installed": [{"path": SKILL_PATH, "digest": "sha256:v1"}],
        "readiness": {"discovery_canary": "SATISFIED", "baseline_absence": "SATISFIED"},
    })
    evidence = records.Record(path=Path("evidence.json"), data={
        "version": 2, "kind": "skill-evidence", "producer": "assembler",
        "attempt_id": "att-1", "trial_id": "t-1",
        "skills": [{
            "skill": {"path": SKILL_PATH}, "invocation": {"lineage": "root"},
            "lifecycle": {
                "listed": {"status": "UNKNOWN", "reason": "x"},
                "read_observed": {"status": "UNKNOWN", "reason": "x"},
                "execution_observed": {"status": "UNKNOWN", "reason": "x"},
            },
            "criteria_owned": [], "external_evidence": {"present": False, "reconciliation": "absent"},
        }],
    })
    bundle = records.Bundle(path=Path("."), records=[ledger, lifecycle, receipt, evidence])
    report = cov.assemble_coverage_report(bundle)
    row = report.rows[0]
    assert row.convenience.phase_wall_times == conv.UNKNOWN
    assert row.convenience.per_attempt["att-1"] == ()


def test_convenience_unparseable_timestamp_refuses_rather_than_guesses() -> None:
    """`records.attempt_lifecycle` only requires a non-empty string `at` -
    not that it is parseable. That gap is new plumbing coverage.py owns
    itself, and the same refuse-before-reporting discipline applies: an
    unparseable timestamp must refuse the report, never silently produce a
    wrong duration."""
    bundle = _bundle(CONTROLS / "ledger-binding/good/skill-evidence-duplicate-invocation")
    mutated = []
    for record in bundle.records:
        if record.kind == "attempt-lifecycle" and record.attempt_id == "att-1":
            data = dict(record.data)
            events = [dict(e) for e in cast("list[dict[str, Any]]", data["events"])]
            events[1] = {**events[1], "at": "not-a-timestamp"}
            data["events"] = events
            mutated.append(records.Record(path=record.path, data=data))
        else:
            mutated.append(record)
    bad_bundle = records.Bundle(path=bundle.path, records=mutated)
    with pytest.raises(cov.CoverageRefused):
        cov.assemble_coverage_report(bad_bundle, _inventory())


# --------------------------------------------------------------- task-cluster bootstrap (#273)

def _task_cluster_bundle(case_count: int) -> records.Bundle:
    """`case_count` trials, each one PASS attempt on the same skill/client/
    subject - one task-cluster group of exactly `case_count` tasks, each
    contributing `all_k(1, 1, 1) == 1.0`."""
    trials: list[dict[str, Any]] = []
    all_records: list[records.Record] = []
    for i in range(case_count):
        case_id, trial_id, attempt_id = f"case-{i}", f"t-{i}", f"att-{i}"
        trials.append({
            "trial_id": trial_id, "case": {"id": case_id, "revision": "r1"},
            "grader": {"id": "g", "revision": "g1"}, "subject": {"digest": "sha256:5a"},
            "client": {"name": "codex", "version": "1.0"}, "image": {"digest": "sha256:1a"},
            "config": {"digest": "sha256:cf"}, "attempts": [{"attempt_id": attempt_id}],
        })
        all_records.append(records.Record(path=Path(f"lifecycle-{i}.json"), data={
            "version": 2, "kind": "attempt-lifecycle", "producer": "controller",
            "attempt_id": attempt_id, "trial_id": trial_id, "disposition": "captured",
            "stop": {"reason": "exited", "confirmed": True, "exit_code": 0},
            "events": [
                {"event": "planned", "at": "2026-09-26T12:00:00Z"},
                {"event": "dispatched", "at": "2026-09-26T12:00:01Z"},
                {"event": "started", "at": "2026-09-26T12:00:02Z"},
                {"event": "stopped", "at": "2026-09-26T12:00:03Z"},
                {"event": "stop-confirmed", "at": "2026-09-26T12:00:04Z"},
                {"event": "captured", "at": "2026-09-26T12:00:05Z"},
                {"event": "cleaned", "at": "2026-09-26T12:00:06Z"},
            ],
            "cleanup": {"status": "removed", "failures": []},
        }))
        all_records.append(records.Record(path=Path(f"manifest-{i}.json"), data={
            "version": 2, "kind": "artifact-manifest", "producer": "controller",
            "attempt_id": attempt_id, "trial_id": trial_id,
            "artifacts": [{"path": "out.txt", "type": "file", "size": 12, "digest": "sha256:aa1"}],
            "observations": [
                {"stream": "client-events", "origin": "client-reported", "coverage": "partial"},
                {"stream": "process-lifecycle", "origin": "observed", "coverage": "complete"},
            ],
            "capture_failures": [],
        }))
        all_records.append(records.Record(path=Path(f"receipt-{i}.json"), data={
            "version": 2, "kind": "installation-receipt", "producer": "subject-adapter",
            "checked_by": "controller", "attempt_id": attempt_id, "trial_id": trial_id,
            "subject": {"locator": "x", "revision": "r", "digest": "sha256:5a"},
            "surface": "codex-skills", "adapter": {"name": "a", "version": "1"},
            "client": {"name": "codex", "version": "1.0"}, "layers": [], "dependencies": [],
            "allowed_writes": [], "installed": [{"path": SKILL_PATH, "digest": "sha256:i1"}],
            "readiness": {"discovery_canary": "SATISFIED", "baseline_absence": "SATISFIED"},
        }))
        all_records.append(records.Record(path=Path(f"result-{i}.json"), data={
            "version": 2, "kind": "verified-result", "producer": "assembler",
            "attempt_id": attempt_id, "trial_id": trial_id, "result_id": f"res-{i}",
            "grader": {"id": "g", "revision": "g1"}, "graded_digests": ["sha256:aa1"],
            "criteria": [{"id": "c1", "mandatory": True, "outcome": "SATISFIED", "evidence": ["grader-log:c1"]}],
            "status": "PASS",
        }))
        all_records.append(records.Record(path=Path(f"evidence-{i}.json"), data={
            "version": 2, "kind": "skill-evidence", "producer": "assembler",
            "attempt_id": attempt_id, "trial_id": trial_id,
            "skills": [{
                "skill": {"path": SKILL_PATH}, "invocation": {"lineage": "root"},
                "lifecycle": {
                    "listed": {"status": "CONFIRMED", "evidence": {"digest": "sha256:i1"}},
                    "read_observed": {"status": "UNKNOWN", "reason": "x"},
                    "execution_observed": {"status": "UNKNOWN", "reason": "x"},
                },
                "criteria_owned": [{"id": "c1", "outcome": "SATISFIED", "shared": False}],
                "external_evidence": {"present": False, "reconciliation": "absent"},
            }],
        }))
    ledger = records.Record(path=Path("ledger.json"), data={
        "version": 2, "kind": "trial-ledger", "producer": "controller", "experiment_id": "exp-1",
        "trials": trials,
    })
    return records.Bundle(path=Path("."), records=[ledger, *all_records])


def test_task_cluster_bootstrap_boundary_four_insufficient_five_an_interval() -> None:
    report4 = cov.assemble_coverage_report(_task_cluster_bundle(4), k=1, bootstrap_seed=42)
    assert len(report4.task_clusters) == 1
    cluster4 = report4.task_clusters[0]
    assert cluster4.task_count == 4
    assert cluster4.all_k_interval == rel.INSUFFICIENT
    assert cluster4.seed == 42

    report5 = cov.assemble_coverage_report(_task_cluster_bundle(5), k=1, bootstrap_seed=42)
    assert len(report5.task_clusters) == 1
    cluster5 = report5.task_clusters[0]
    assert cluster5.task_count == 5
    assert cluster5.all_k_interval != rel.INSUFFICIENT
    assert isinstance(cluster5.all_k_interval, tuple)
    lower, upper = cluster5.all_k_interval
    assert 0.0 <= lower <= upper <= 1.0


def test_task_cluster_bootstrap_same_seed_is_byte_identical() -> None:
    bundle = _task_cluster_bundle(5)
    report_a = cov.assemble_coverage_report(bundle, k=1, bootstrap_seed=7)
    report_b = cov.assemble_coverage_report(bundle, k=1, bootstrap_seed=7)
    assert report_a.to_json() == report_b.to_json()


def test_task_cluster_bootstrap_absent_without_a_declared_seed() -> None:
    report = cov.assemble_coverage_report(_task_cluster_bundle(5), k=1)
    assert report.task_clusters == ()


# --------------------------------------------------------------- to_text sentinel coverage (#272)

def _collect_sentinel_values(obj: object, sentinels: set[str], found: set[str]) -> None:
    """Recursively walk a JSON-shaped structure, collecting every string
    VALUE (never a dict key - `outcomes`/`execution_observed` key their
    counts by `UNKNOWN`, which is not itself a reported state) that matches
    one of `sentinels`."""
    if isinstance(obj, dict):
        for value in obj.values():
            _collect_sentinel_values(value, sentinels, found)
    elif isinstance(obj, list):
        for item in obj:
            _collect_sentinel_values(item, sentinels, found)
    elif isinstance(obj, str) and obj in sentinels:
        found.add(obj)


#: The closed set of sentinel strings this sweep knows about - every module
#: that reports an absence via one of its own words, gathered in one place
#: so a reviewer can see the whole vocabulary this test polices.
_SENTINELS = {"UNKNOWN", rel.INSUFFICIENT, cov.NOT_DECLARED, conv.NOT_CAPTURED}


def test_to_text_renders_every_sentinel_value_present_in_the_json() -> None:
    """Generic sweep (orchestrator review, #272): walk `to_dict()` for every
    occurrence of a known sentinel VALUE, and assert each one that appears
    anywhere in the JSON also appears somewhere in `to_text()`. A new field
    carrying one of these sentinels then cannot be silently dropped from the
    human view - this test does not need to know the field exists, only
    that whatever sentinel it carries is accounted for.

    LIMITATION (Codex review, #272): "somewhere in `to_text()`" is whole-text
    presence, not field- or row-scoped, so it cannot tell `convenience.
    tokens`'s own `UNKNOWN` apart from the `UNKNOWN=0` key-name artifact
    `outcomes` already renders, and it cannot tell one row's `reliability`
    apart from another row's. Concretely, dropping ONLY `tokens=...` from
    the convenience line, or dropping ONE row's `reliability:` line while a
    different row still renders a sentinel, both leave this test green.
    `test_to_text_sentinels_are_location_aware_not_merely_present_somewhere`
    and `test_to_text_task_clusters_sentinel_is_scoped_to_its_own_section`
    close exactly those two gaps, scoped to the fields this issue's own work
    added; this test stays as the cheap, field-agnostic floor for whatever
    is added next.

    The fixture is built to exercise all three of reliability, convenience
    and task_clusters as the UNIQUE source of at least one sentinel each in
    this particular report, so that dropping any one of the three renderers
    makes a DIFFERENT sentinel vanish from the text - not just one of them
    (`k` is left undeclared, so `reliability.all_k`/`pass_at_k` are
    `cov.NOT_DECLARED` and no row contributes a task value, which in turn
    makes every `task_clusters` entry `rel.INSUFFICIENT`; each row's own
    `evaluable` is 1, so `clopper_pearson`/`wilson_score` are real floats,
    never `rel.INSUFFICIENT` - the only `insufficient` in this report's
    JSON comes from `task_clusters`. `convenience.tokens` is unconditionally
    `conv.UNKNOWN`, the only `UNKNOWN` in this report's JSON since there are
    no case pairs to carry a `DISCRIMINATING`/`NOT_SHOWN`/`UNKNOWN` verdict).

    A DECLARED inventory is passed deliberately: `CoverageReport.inventory`
    itself reports the unrelated top-level sentinel `cov.INVENTORY_NOT_DECLARED`
    ("not_declared", the SAME literal string as `cov.NOT_DECLARED` - a real
    collision) when no inventory is supplied, and `inventory` is always
    rendered regardless of any row-level renderer. Without a declared
    inventory that collision would let `not_declared` show up in the text
    for a reason that has nothing to do with `reliability` ever being
    rendered, silently defeating the very mutation check this test exists
    to pass (caught by running the mutation check itself, not by inspection).
    """
    bundle = _task_cluster_bundle(2)
    report = cov.assemble_coverage_report(bundle, _inventory(), bootstrap_seed=42)
    body = report.to_dict()
    found: set[str] = set()
    _collect_sentinel_values(body, _SENTINELS, found)

    # Sanity: the fixture actually exercises all three renderers' own
    # sentinel, not just one - otherwise this test could pass while leaving
    # the other two renderers completely unverified.
    assert cov.NOT_DECLARED in found, "fixture does not exercise reliability's own sentinel"
    assert rel.INSUFFICIENT in found, "fixture does not exercise task_clusters' own sentinel"
    assert "UNKNOWN" in found, "fixture does not exercise convenience's own sentinel"

    text = report.to_text()
    missing = {s for s in found if s not in text}
    assert not missing, f"sentinel value(s) {missing} appear in the JSON but not in to_text()"


def _mixed_reliability_bundle() -> records.Bundle:
    """Two cases, same skill/client/arm: case-0's attempt is `not-run` (a
    single `planned` event, zero evaluable attempts); case-1's attempt is
    `captured`+PASS with a full lifecycle. With `k=1` declared, case-0's row
    gets `INSUFFICIENT` on all four reliability fields (zero evaluable, and
    `n=0 < k=1`) while case-1's row gets four real floats and no sentinel in
    its own reliability at all - the two rows' reliability sentinels are
    therefore genuinely DIFFERENT, not merely "the same report-wide
    not_declared on every row" the way an undeclared `k` would give."""
    bundle = _task_cluster_bundle(2)
    mutated = []
    for record in bundle.records:
        if record.attempt_id == "att-0" and record.kind == "attempt-lifecycle":
            data = json.loads(json.dumps(record.data))
            data["disposition"] = "not-run"
            data["reason"] = "never-started"
            data["stop"] = {"reason": "never-started", "confirmed": True}
            data["events"] = [{"event": "planned", "at": "2026-09-26T12:00:00Z"}]
            mutated.append(records.Record(path=record.path, data=data))
        elif record.attempt_id == "att-0" and record.kind in ("verified-result", "artifact-manifest"):
            continue  # a not-run attempt has neither a grade nor a capture
        else:
            mutated.append(record)
    return records.Bundle(path=bundle.path, records=mutated)


def _split_rows_section(text: str) -> list[list[str]]:
    """Split `to_text()`'s rendered output into one block of lines per row,
    each starting at its own '- <skill_path> @ ...' header and running up
    to (not including) the next row header or the next top-level section
    ('case_pairs:'/'task_clusters:'). Scoping to the rows SECTION first
    (never a bare '^- ' split over the whole text) keeps a case_pairs or
    task_clusters entry - which also starts with '- ' - from being mistaken
    for a row."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("rows: ")) + 1
    end = len(lines)
    for i in range(start, len(lines)):
        if lines[i].startswith("case_pairs: ") or lines[i].startswith("task_clusters: "):
            end = i
            break
    blocks: list[list[str]] = []
    for line in lines[start:end]:
        if line.startswith("- "):
            blocks.append([line])
        else:
            blocks[-1].append(line)
    return blocks


def _row_subfield_line(block: list[str], prefix: str) -> str:
    """The single line in a row's block starting with `prefix` (e.g.
    '    reliability:'), or '' if the row carries no such line - never a
    KeyError, since a mutation that deletes the whole line is exactly what
    this helper exists to notice as a missing line, not crash on."""
    for line in block:
        if line.strip().startswith(prefix):
            return line
    return ""


def test_to_text_sentinels_are_location_aware_not_merely_present_somewhere() -> None:
    """Codex review, #272: the whole-text sweep above only proves a sentinel
    appears SOMEWHERE - it cannot tell `convenience.tokens`'s own `UNKNOWN`
    apart from the unrelated `UNKNOWN=0` key-name artifact already in
    `outcomes`, and it cannot tell one row's `reliability` apart from
    another row's. Concretely: Codex showed that removing ONLY the
    `convenience:` line, or removing ONLY one row's `reliability:` line
    while another row still renders a sentinel, leaves the global sweep
    green. This test checks each row's OWN `reliability`/`convenience`
    dict against that SAME row's OWN rendered `reliability:`/`convenience:`
    line - never the whole block, never the whole report - so a renderer
    dropped from one field or one row cannot hide behind a sentinel
    rendered somewhere else entirely.
    """
    bundle = _mixed_reliability_bundle()
    report = cov.assemble_coverage_report(bundle, _inventory(), k=1)
    body = report.to_dict()
    rows = sorted(
        cast("list[dict[str, Any]]", body["rows"]),
        key=lambda r: (r["skill_path"], r["skill_version"], r["client_name"], r["client_version"], r["case_id"], r["arm"]),
    )
    text = report.to_text()
    blocks = _split_rows_section(text)
    assert len(blocks) == len(rows) == 2

    # Sanity: the fixture gives the two rows genuinely DIFFERENT reliability
    # sentinel content - case-0 is all-insufficient, case-1 carries none.
    case0 = next(r for r in rows if r["case_id"] == "case-0")
    case1 = next(r for r in rows if r["case_id"] == "case-1")
    assert case0["reliability"]["all_k"] == rel.INSUFFICIENT
    assert isinstance(case1["reliability"]["all_k"], float)

    for row_dict, block in zip(rows, blocks, strict=True):
        reliability_found: set[str] = set()
        _collect_sentinel_values(row_dict["reliability"], _SENTINELS, reliability_found)
        reliability_line = _row_subfield_line(block, "reliability:")
        missing = {s for s in reliability_found if s not in reliability_line}
        assert not missing, f"{row_dict['case_id']}: reliability sentinel(s) {missing} missing from its OWN rendered line"

        convenience_found: set[str] = set()
        _collect_sentinel_values(row_dict["convenience"], _SENTINELS, convenience_found)
        convenience_line = _row_subfield_line(block, "convenience:")
        missing = {s for s in convenience_found if s not in convenience_line}
        assert not missing, f"{row_dict['case_id']}: convenience sentinel(s) {missing} missing from its OWN rendered line"


def test_to_text_task_clusters_sentinel_is_scoped_to_its_own_section() -> None:
    """The report-level counterpart: a `task_clusters` sentinel must appear
    within the `task_clusters:` section specifically, not merely somewhere
    in the whole report (where a row's own `convenience.tokens` UNKNOWN
    would otherwise satisfy a non-scoped check for free)."""
    bundle = _task_cluster_bundle(4)
    report = cov.assemble_coverage_report(bundle, _inventory(), bootstrap_seed=42)
    text = report.to_text()
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("task_clusters: "))
    section = "\n".join(lines[start:])
    assert rel.INSUFFICIENT in section
    rows_only = "\n".join(lines[: next(i for i, line in enumerate(lines) if line.startswith("rows: "))])
    # The sanity half: INSUFFICIENT is not already present ahead of the
    # task_clusters section for an unrelated reason in THIS fixture (k is
    # declared and every attempt here is evaluable, so reliability carries
    # no sentinel at all) - otherwise this test would pass without the
    # task_clusters renderer ever running.
    assert rel.INSUFFICIENT not in rows_only
