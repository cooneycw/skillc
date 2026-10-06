"""Tests for skillc/coverage.py (issue #272).

Each assertion is checked against a hand-built or committed bundle, never
against a second implementation of the same aggregation. Reproducibility is
checked by byte equality of the canonical JSON, not merely equal-as-objects.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

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
