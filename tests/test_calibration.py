"""Tests for the calibration endpoint and declaration (#204).

SYMMETRIC ELIGIBILITY, end to end through the real verifier: two attempts
produce the same correct candidate. One is graded the way a CPP arm with a
real installation receipt is (`verify._grade_and_store`, the receipt path
`agent_trial.run_one_attempt` takes); the other the way a baseline arm that
installs nothing is (`verify.grade_agent_attempt`, the #139 stand-in). Their
stored verified statuses differ - PASS against INCONCLUSIVE - purely because of
`installation-ready`. The primary endpoint must read PASS for both.

The red case: `test_the_stored_verified_status_is_the_trap` asserts the
asymmetry the endpoint exists to step around, so a future change that makes
the stored status symmetric shows up here too.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

from skillc import calibration, verify
from skillc import trial as t

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
FAKE = HERE / "fixtures" / "trial-subject" / "fake_subject.py"
TASK = ROOT / "evals" / "level1" / "slug-small-fix"
REFERENCE = TASK / "reference" / "src" / "slugify.py"
WRONG = TASK / "wrong" / "no-collapse" / "src" / "slugify.py"
GRADER = verify.GraderDef.load(TASK)
RECEIPT = json.loads((ROOT / "controls" / "installation-receipt" / "good" / "receipt.json")
                     .read_text(encoding="utf-8"))
CONFIRMED = {"status": "observed", "prompt_delivered": True, "canary_satisfied": True, "grading_eligible": True}
MANIFEST = ROOT / "evals" / "calibration-204" / "run-manifest.json"


@pytest.fixture(autouse=True)
def _no_quarantine_leaks() -> object:
    verify.clear_quarantine()
    yield
    verify.clear_quarantine()


def _captured(tmp_path: Path, name: str, source: Path, *, receipt: bool) -> tuple[t.Experiment, str]:
    store = t.open_store(tmp_path / f"store-{name}", forbidden=[])
    experiment = t.plan({"experiment": f"calibration-{name}", "trials": [{
        "label": "slug", "case": {"id": "slug-small-fix", "revision": "1"},
        "grader": GRADER.identity(), "subject": {"digest": "sha256:5a"},
        "client": {"name": "fake", "version": "1"}, "image": {"digest": "sha256:1a"},
        "config": {"model": "fake-1"}, "attempts": 1,
    }]}, store)
    [(_trial, attempt)] = list(experiment.attempts())
    attempt_id = str(attempt["attempt_id"])
    if receipt:
        t.add_receipt(experiment, {**RECEIPT, "attempt_id": attempt_id,
                                   "trial_id": experiment.trial_of(attempt_id)["trial_id"],
                                   "client": {"name": "fake", "version": "1"}})
    base = tmp_path / f"work-{name}"
    base.mkdir()
    workspace = t.allocate_workspace(experiment, attempt_id, base, forbidden=[])
    stop = t.run_attempt(experiment, attempt_id, [sys.executable, str(FAKE), "slug-from", str(source)],
                         cwd=workspace, timeout=20, grace=0.5)
    assert stop["confirmed"] is True
    t.capture(experiment, attempt_id, workspace)
    t.cleanup_workspace(experiment, attempt_id)
    assert t.finalize(experiment, attempt_id)["disposition"] == "captured"
    return experiment, attempt_id


def _attempt(tmp_path: Path, name: str, source: Path, *, arm: str) -> tuple[dict[str, object], dict[str, object]]:
    """(run_one_attempt-shaped record, stored verified result) for one arm."""
    experiment, attempt_id = _captured(tmp_path, name, source, receipt=arm == "treatment")
    grading = tmp_path / f"grade-{name}"
    grading.mkdir()
    if arm == "treatment":
        stored, graded = verify._grade_and_store(experiment, attempt_id, GRADER, grading)
    else:
        stored, graded = verify.grade_agent_attempt(experiment, attempt_id, GRADER, grading, CONFIRMED)
    # The same `graded` shape agent_trial.run_one_attempt builds.
    record: dict[str, object] = {"disposition": "captured", "graded": {
        "status": graded.status, "category": graded.category, "detail": graded.detail,
        "criteria": graded.criteria, "result_id": stored["result_id"], "result_status": stored["status"],
    }}
    return record, stored


def test_a_baseline_attempt_meeting_the_task_criteria_reaches_primary_pass(tmp_path: Path) -> None:
    treatment, treatment_result = _attempt(tmp_path, "t", REFERENCE, arm="treatment")
    baseline, baseline_result = _attempt(tmp_path, "b", REFERENCE, arm="baseline")
    assert calibration.primary_endpoint(baseline)["status"] == "PASS"
    assert calibration.primary_endpoint(treatment)["status"] == "PASS"
    # Readiness is still reported - beside the endpoint, not inside it.
    assert calibration.readiness_beside(baseline_result)["installation_ready"] == "UNKNOWN"
    assert calibration.readiness_beside(baseline_result)["readiness_source"] == verify.AGENT_OBSERVATION_READINESS
    assert calibration.readiness_beside(treatment_result)["installation_ready"] == "SATISFIED"


def test_the_stored_verified_status_is_the_trap(tmp_path: Path) -> None:
    """Red case for the comparison the endpoint replaces: the same correct
    output is PASS for the arm with a receipt and INCONCLUSIVE for the
    baseline. Comparing these statuses manufactures a treatment advantage."""
    treatment, _ = _attempt(tmp_path, "t", REFERENCE, arm="treatment")
    baseline, _ = _attempt(tmp_path, "b", REFERENCE, arm="baseline")
    assert treatment["graded"]["result_status"] == "PASS"  # type: ignore[index]
    assert baseline["graded"]["result_status"] == "INCONCLUSIVE"  # type: ignore[index]


def test_a_baseline_attempt_that_fails_the_task_is_primary_fail(tmp_path: Path) -> None:
    baseline, _ = _attempt(tmp_path, "b", WRONG, arm="baseline")
    assert calibration.primary_endpoint(baseline)["status"] == "FAIL"


def test_a_readiness_criterion_in_the_graded_list_is_excluded_and_named() -> None:
    record = {"graded": {"criteria": [
        {"id": "task", "mandatory": True, "outcome": "SATISFIED"},
        {"id": verify.READINESS_CRITERION, "mandatory": True, "outcome": "UNKNOWN"},
    ]}}
    endpoint = calibration.primary_endpoint(record)
    assert endpoint["status"] == "PASS"
    assert endpoint["excluded"] == [verify.READINESS_CRITERION]


def test_an_ungraded_attempt_is_reported_not_dropped() -> None:
    endpoint = calibration.primary_endpoint({"disposition": "inconclusive", "graded": None,
                                             "grading_blocked_reason": "attempt disposition is 'inconclusive'"})
    assert endpoint["status"] == calibration.NOT_GRADED
    assert "inconclusive" in str(endpoint["reason"])


def test_no_criteria_is_inconclusive_never_pass() -> None:
    assert calibration.primary_endpoint({"graded": {"criteria": []}})["status"] == "INCONCLUSIVE"


def test_readiness_beside_with_no_result_is_unknown() -> None:
    assert calibration.readiness_beside(None)["installation_ready"] == "UNKNOWN"


# ------------------------------------------------------------- declaration


def _manifest() -> dict[str, object]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_the_committed_declaration_validates() -> None:
    declaration = calibration.load_declaration(MANIFEST)
    assert declaration.arms == ("full-cpp", "baseline")
    assert declaration.attempts_per_arm == 4
    assert sorted(declaration.arm_order) == sorted(["full-cpp", "baseline"] * 4)
    assert (ROOT / declaration.task_path / "grader.json").is_file()


def test_the_committed_declaration_is_authorized() -> None:
    """Approved by the owner 2026-09-30, with every identity recorded."""
    calibration.require_approved(calibration.load_declaration(MANIFEST), ROOT)


def test_red_the_same_declaration_without_its_approval_is_refused() -> None:
    """The red case for the green above: remove only the approval."""
    with pytest.raises(calibration.DeclarationRefused, match="not approved"):
        calibration.require_approved(calibration.parse_declaration(_mutated(approval=None)), ROOT)


def _mutated(**changes: object) -> dict[str, object]:
    data = copy.deepcopy(_manifest())
    data.update(changes)
    return data


def _arms(**treatment_extra: object) -> list[object]:
    arms = copy.deepcopy(_manifest()["arms"])
    assert isinstance(arms, list)
    arms[0].update(treatment_extra)
    return arms


@pytest.mark.parametrize(("change", "match"), [
    ({"arms": _arms() + [{"name": "ablation", "subject": {"name": "x"}}]}, "different subjects"),
    ({"arms": _arms() + [{"name": "p"}, {"name": "q"}]}, "two or three arms"),
    ({"arms": _arms(model="another-model")}, "arms may differ only"),
    ({"attempts_per_arm": 9}, "3-8"),
    ({"attempts_per_arm": 2}, "3-8"),
    ({"arm_order": {"seed": 20260930, "sequence": ["full-cpp", "baseline"] * 4}}, "chosen by hand"),
    ({"arm_order": {"seed": 1, "sequence": _manifest()["arm_order"]["sequence"]}},  # type: ignore[index]
     "chosen by hand"),
    ({"retain_transcripts": False}, "retain_transcripts"),
])
def test_a_declaration_that_breaks_the_design_is_refused(change: dict[str, object], match: str) -> None:
    with pytest.raises(calibration.DeclarationRefused, match=match):
        calibration.parse_declaration(_mutated(**change))


def test_a_baseline_that_installs_something_is_refused() -> None:
    arms = copy.deepcopy(_manifest()["arms"])
    assert isinstance(arms, list)
    arms[1]["subject"] = {"name": "cpp-codex"}
    with pytest.raises(calibration.DeclarationRefused, match="installs nothing"):
        calibration.parse_declaration(_mutated(arms=arms))


def test_a_total_cap_that_cannot_cover_the_schedule_is_refused() -> None:
    data = _mutated()
    data["shared"]["total_seconds"] = 1200  # type: ignore[index]
    with pytest.raises(calibration.DeclarationRefused, match="cannot cover"):
        calibration.parse_declaration(data)


def _approved() -> dict[str, object]:
    data = _mutated(approval={"by": "owner", "at": "2026-10-01"})
    data["shared"]["image"]["digest"] = "sha256:" + "ab" * 32  # type: ignore[index]
    return data


def test_an_approved_declaration_with_every_identity_recorded_is_authorized() -> None:
    calibration.require_approved(calibration.parse_declaration(_approved()), ROOT)


def test_approval_with_an_identity_still_unknown_is_refused() -> None:
    data = _approved()
    data["shared"]["image"]["digest"] = "UNKNOWN"  # type: ignore[index]
    with pytest.raises(calibration.DeclarationRefused, match=r"shared\.image\.digest"):
        calibration.require_approved(calibration.parse_declaration(data), ROOT)


def test_approval_of_another_grader_revision_is_refused() -> None:
    data = _approved()
    data["task"]["grader_revision"] = "2"  # type: ignore[index]
    with pytest.raises(calibration.DeclarationRefused, match="not the declared"):
        calibration.require_approved(calibration.parse_declaration(data), ROOT)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize("cap", ["per_attempt_seconds", "total_seconds"])
def test_a_non_finite_cap_is_refused(cap: str, value: float) -> None:
    """Counter-model review, red before the fix: `json` accepts NaN and
    Infinity, and a NaN total also slipped past the schedule-coverage check."""
    data = _mutated()
    data["shared"][cap] = value  # type: ignore[index]
    with pytest.raises(calibration.DeclarationRefused, match="finite"):
        calibration.parse_declaration(data)


@pytest.mark.parametrize(("where", "value"), [
    (("shared", "client"), {}),
    (("shared", "image"), {}),
    (("shared", "model"), None),
    (("shared", "reasoning_effort"), ""),
    (("shared", "tools"), None),
    (("shared", "permissions"), " "),
    (("shared", "public_requirements"), {}),
])
def test_approval_with_an_identity_absent_rather_than_unknown_is_refused(
        where: tuple[str, str], value: object) -> None:
    """Counter-model review, red before the fix: only the literal UNKNOWN was
    refused, so an empty object or a null - no identity at all - passed."""
    data = _approved()
    data[where[0]][where[1]] = value  # type: ignore[index]
    with pytest.raises(calibration.DeclarationRefused, match="not recorded"):
        calibration.require_approved(calibration.parse_declaration(data), ROOT)


def test_approval_with_an_empty_treatment_subject_is_refused() -> None:
    data = _approved()
    data["arms"][0]["subject"] = {}  # type: ignore[index]
    with pytest.raises(calibration.DeclarationRefused, match="treatment.subject"):
        calibration.require_approved(calibration.parse_declaration(data), ROOT)


# ------------------------------------------- three arms, B/N/P (#231, for #203)


_INSTRUCTION = "Before you start, read the `flow-auto` and `flow-check` skills."


def _three_arm(**provided: object) -> dict[str, object]:
    """The committed #204 declaration with a provided-skill arm added: the
    same subject as the treatment, plus an instruction naming skills."""
    data = _mutated()
    arms = data["arms"]
    assert isinstance(arms, list)
    p_arm = {"name": "provided", "subject": copy.deepcopy(arms[0]["subject"]),
             "treatment": "the same install, told to read the named skills first",
             "instruction": _INSTRUCTION, "named_skills": ["flow-auto", "flow-check"]}
    p_arm.update(provided)
    arms.append({k: v for k, v in p_arm.items() if v is not None})
    data["attempts_per_arm"] = 6
    data["shared"]["total_seconds"] = 1200 * 18  # type: ignore[index]
    names = [a["name"] for a in arms]
    data["arm_order"] = {"seed": 7, "sequence": calibration.derive_arm_order(7, names, 6)}
    return data


def test_a_three_arm_declaration_at_six_per_arm_validates() -> None:
    declaration = calibration.parse_declaration(_three_arm())
    assert declaration.arms == ("full-cpp", "baseline", "provided")
    assert declaration.attempts_per_arm == 6
    assert len(declaration.arm_order) == 18
    assert calibration.arm_spec(declaration, "provided")["named_skills"] == ["flow-auto", "flow-check"]


@pytest.mark.parametrize(("provided", "match"), [
    ({"subject": {"name": "another"}}, "different subjects"),  # an ablation, not P
    ({"instruction": None}, "declared together"),
    ({"named_skills": None}, "declared together"),
    ({"instruction": "  "}, "non-empty text"),
    ({"named_skills": []}, "non-empty list"),
    ({"named_skills": ["flow-auto", "flow-auto"]}, "distinct"),
    ({"named_skills": ["flow-auto", "qa-test"]}, r"does not name \['qa-test'\]"),
    # A neighbouring name is not the name (counter-model review).
    ({"instruction": "Read `flow-auto-extra` and `flow-check` first."}, r"does not name \['flow-auto'\]"),
    ({"instruction": None, "named_skills": None}, "exactly one carries"),  # two natural arms
])
def test_a_provided_arm_that_breaks_the_design_is_refused(provided: dict[str, object], match: str) -> None:
    with pytest.raises(calibration.DeclarationRefused, match=match):
        calibration.parse_declaration(_three_arm(**provided))


def test_a_provided_arm_without_a_natural_arm_is_refused() -> None:
    """P alone beside the baseline would confound the skills' value with the
    instruction itself."""
    data = _mutated(arms=_arms(instruction=_INSTRUCTION, named_skills=["flow-auto", "flow-check"]))
    with pytest.raises(calibration.DeclarationRefused, match="natural arm beside it"):
        calibration.parse_declaration(data)


def test_a_baseline_naming_skills_is_refused() -> None:
    data = _three_arm()
    data["arms"][1]["named_skills"] = ["flow-auto"]  # type: ignore[index]
    with pytest.raises(calibration.DeclarationRefused, match="can name no skill"):
        calibration.parse_declaration(data)


def test_a_three_arm_total_cap_is_checked_against_all_three_arms() -> None:
    data = _three_arm()
    data["shared"]["total_seconds"] = 1200 * 12  # type: ignore[index]  # covers two arms, not three
    with pytest.raises(calibration.DeclarationRefused, match="cannot cover 18 attempts"):
        calibration.parse_declaration(data)


# ------------------------------------------- the committed #203 declaration (B/N/P)


MANIFEST_203 = ROOT / "evals" / "calibration-203" / "run-manifest.json"


def test_the_committed_203_declaration_validates_as_b_n_p() -> None:
    declaration = calibration.load_declaration(MANIFEST_203)
    assert declaration.arms == ("natural", "baseline", "provided")
    assert declaration.attempts_per_arm == 6
    assert sorted(declaration.arm_order) == sorted(["natural", "baseline", "provided"] * 6)
    provided = calibration.arm_spec(declaration, "provided")
    assert provided["named_skills"] == ["flow-auto", "flow-check"]
    assert provided["subject"] == calibration.arm_spec(declaration, "natural")["subject"]


def test_the_committed_203_declaration_is_authorized() -> None:
    """Approved by the owner 2026-10-03, with every identity recorded."""
    calibration.require_approved(calibration.load_declaration(MANIFEST_203), ROOT)


def test_red_the_203_declaration_without_its_approval_is_refused() -> None:
    data = json.loads(MANIFEST_203.read_text(encoding="utf-8"))
    data["approval"] = None
    with pytest.raises(calibration.DeclarationRefused, match="not approved"):
        calibration.require_approved(calibration.parse_declaration(data), ROOT)


MANIFEST_203_LOW = ROOT / "evals" / "calibration-203-low" / "run-manifest.json"


def test_the_committed_203_low_effort_declaration_is_authorized() -> None:
    """Step (a) of #203 Q2: the calibration-203 identities at effort low."""
    declaration = calibration.load_declaration(MANIFEST_203_LOW)
    assert declaration.arms == ("natural", "baseline")
    assert declaration.attempts_per_arm == 3
    assert declaration.shared["reasoning_effort"] == "low"
    calibration.require_approved(declaration, ROOT)


def test_red_the_203_low_effort_declaration_without_its_approval_is_refused() -> None:
    data = json.loads(MANIFEST_203_LOW.read_text(encoding="utf-8"))
    data["approval"] = None
    with pytest.raises(calibration.DeclarationRefused, match="not approved"):
        calibration.require_approved(calibration.parse_declaration(data), ROOT)


MANIFEST_203_C3 = ROOT / "evals" / "calibration-203-c3" / "run-manifest.json"


def test_the_committed_203_candidate_3_declaration_is_pinned_to_the_revision_it_ran_on() -> None:
    """#203 Q2 step (b): B/N/P on helper-different-question, run 2026-10-04 on
    grader revision 1. The task then moved to revision 2 (the owner's
    "option 1": the approval names the step's number), so the declaration
    still validates but no longer authorizes - a run pinned to one task
    revision is never silently re-run against another."""
    declaration = calibration.load_declaration(MANIFEST_203_C3)
    assert declaration.arms == ("natural", "baseline", "provided")
    assert declaration.attempts_per_arm == 6
    assert (declaration.task_path, declaration.grader_revision) == ("evals/level3/helper-different-question", "1")
    with pytest.raises(calibration.DeclarationRefused, match="revision '2', not the declared"):
        calibration.require_approved(declaration, ROOT)


def test_red_the_203_candidate_3_declaration_without_its_approval_is_refused() -> None:
    data = json.loads(MANIFEST_203_C3.read_text(encoding="utf-8"))
    data["task"]["grader_revision"] = "2"  # isolate the approval check from the revision pin
    data["approval"] = None
    with pytest.raises(calibration.DeclarationRefused, match="not approved"):
        calibration.require_approved(calibration.parse_declaration(data), ROOT)



# ----------------------------------------------- expanded-instruction lane (#274)

_SKILL_BODY = "Run the gate, then open a PR. Never skip the tests.\n"


def _inventory(tmp_path: Path, *, name: str = "flow-check", question: str = "prose",
               treatment_scoped: tuple[str, ...] = (), body: str = _SKILL_BODY) -> Path:
    """A hand-written inventory, matching `skillc profile validate`'s real
    output shape (treatment_question, helper_parity.treatment, skills[].
    body_digest) closely enough for `validate_expanded_instruction_lane` to
    read - the producer side (profile.py) has its own tests proving a REAL
    validate() run produces this shape; this is the consumer side's fixture."""
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps({
        "treatment_question": question,
        "helper_parity": {"common": ["gate-script"], "treatment": list(treatment_scoped), "bundled": []},
        "skills": [{"name": name, "body_digest": calibration.m.sha256_bytes(body.encode("utf-8"))}],
    }), encoding="utf-8")
    return path


def _expanded_instruction_declaration(tmp_path: Path, *, e_instruction: str = _SKILL_BODY,
                                      inventory_path: Path | None = None,
                                      s_overrides: dict[str, object] | None = None,
                                      e_overrides: dict[str, object] | None = None) -> dict[str, object]:
    """Baseline + S (explicit-skill) + E (expanded-instruction), both
    referencing the same inventory - protocol.md 10.1's third lane."""
    data = _mutated(lane=calibration.EXPANDED_INSTRUCTION_LANE)
    arms = data["arms"]
    assert isinstance(arms, list)
    subject = copy.deepcopy(arms[0]["subject"])
    inventory = str(inventory_path or _inventory(tmp_path))
    s_arm = {"name": "explicit-skill", "subject": subject, "instruction": "Use `flow-check` first.",
             "named_skills": ["flow-check"], "inventory": inventory}
    e_arm = {"name": "expanded-instruction", "subject": subject, "instruction": e_instruction,
             "inventory": inventory}
    s_arm.update(s_overrides or {})
    e_arm.update(e_overrides or {})
    new_arms: list[object] = [arms[1], s_arm, e_arm]  # baseline, S, E
    data["arms"] = new_arms
    data["attempts_per_arm"] = 6
    data["shared"]["total_seconds"] = 1200 * 18  # type: ignore[index]
    names = [a["name"] for a in new_arms if isinstance(a, dict)]
    data["arm_order"] = {"seed": 7, "sequence": calibration.derive_arm_order(7, names, 6)}
    return data


def test_an_expanded_instruction_declaration_validates(tmp_path: Path) -> None:
    declaration = calibration.parse_declaration(_expanded_instruction_declaration(tmp_path))
    assert declaration.lane == calibration.EXPANDED_INSTRUCTION_LANE
    assert declaration.arms == ("baseline", "explicit-skill", "expanded-instruction")
    calibration.validate_expanded_instruction_lane(declaration, ROOT)


def test_a_declaration_with_no_lane_defaults_to_matched_outcome() -> None:
    """Every pre-#274 declaration - the committed #204/#203 manifests
    included - is silently the matched-outcome lane; #274 names what was
    already true rather than changing it."""
    declaration = calibration.load_declaration(MANIFEST)
    assert declaration.lane == calibration.DEFAULT_LANE == "matched-outcome"
    calibration.validate_expanded_instruction_lane(declaration, ROOT)  # a no-op on this lane


def test_an_invalid_lane_is_refused() -> None:
    with pytest.raises(calibration.DeclarationRefused, match="lane must be one of"):
        calibration.parse_declaration(_mutated(lane="not-a-real-lane"))


def test_expanded_instruction_needs_both_treated_arms(tmp_path: Path) -> None:
    """One arm alone - even a valid S - cannot be the S-vs-E contrast."""
    data = _mutated(lane=calibration.EXPANDED_INSTRUCTION_LANE,
                    arms=_arms(instruction="Use `flow-check` first.", named_skills=["flow-check"],
                              inventory=str(_inventory(tmp_path))))
    with pytest.raises(calibration.DeclarationRefused, match="needs both treated arms"):
        calibration.parse_declaration(data)


@pytest.mark.parametrize(("s_over", "e_over", "match"), [
    ({"inventory": None}, {}, "non-empty 'inventory' path"),
    ({}, {"inventory": None}, "non-empty 'inventory' path"),
    ({"named_skills": ["flow-check", "flow-auto"]}, {}, "exactly one skill"),
])
def test_an_expanded_instruction_arm_that_breaks_the_design_is_refused(
    tmp_path: Path, s_over: dict[str, object], e_over: dict[str, object], match: str,
) -> None:
    data = _expanded_instruction_declaration(tmp_path, s_overrides=s_over, e_overrides=e_over)
    with pytest.raises(calibration.DeclarationRefused, match=match):
        calibration.parse_declaration(data)


def test_expanded_instruction_arms_cannot_differ_in_subject(tmp_path: Path) -> None:
    """Evidence for #274 acceptance item 2 ('equal project obligations'),
    demonstrated rather than merely asserted (orchestrator review).
    `task` and `shared` are single declaration-level fields - one value for
    every arm - so S and E cannot differ in the task, model, client,
    image, tools, permissions or budget at all; there is nothing to test
    there, because the schema gives them no field through which to differ.
    The ONE per-arm field that could smuggle in a different obligation is
    `subject` (what gets installed) - already refused by the existing,
    lane-independent check this proves still fires for this pair."""
    data = _expanded_instruction_declaration(tmp_path, e_overrides={"subject": {"name": "a-different-subject"}})
    with pytest.raises(calibration.DeclarationRefused, match="different subjects"):
        calibration.parse_declaration(data)


def test_expanded_instruction_content_identity_is_what_rules_out_a_smuggled_obligation(tmp_path: Path) -> None:
    """The remaining way an obligation could differ between S and E:
    `instruction` is per-arm text, and a changed word there could add a
    requirement the skill itself does not state. `validate_expanded_
    instruction_lane`'s content-identity check (also proven in
    `test_red_a_changed_word_in_the_inlined_instruction_is_refused` above)
    is this case's answer - restated here as the named evidence for #274
    acceptance item 2's 'equal obligations' claim, not a new mechanism."""
    declaration = calibration.parse_declaration(
        _expanded_instruction_declaration(tmp_path, e_instruction=_SKILL_BODY + "Also: ship on Fridays.\n"))
    with pytest.raises(calibration.DeclarationRefused, match="does not match"):
        calibration.validate_expanded_instruction_lane(declaration, ROOT)


def test_expanded_instruction_arms_must_share_one_inventory(tmp_path: Path) -> None:
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    other = _inventory(other_dir)
    data = _expanded_instruction_declaration(tmp_path, e_overrides={"inventory": str(other)})
    with pytest.raises(calibration.DeclarationRefused, match="must reference the SAME"):
        calibration.parse_declaration(data)


def test_matched_outcome_arm_cannot_carry_inventory(tmp_path: Path) -> None:
    """`inventory` is the expanded-instruction lane's own field - a B/N/P
    arm declaring one is refused, not silently ignored."""
    data = _mutated(arms=_arms(inventory=str(_inventory(tmp_path))))
    with pytest.raises(calibration.DeclarationRefused, match="belongs to the expanded-instruction lane"):
        calibration.parse_declaration(data)


def test_baseline_cannot_carry_inventory(tmp_path: Path) -> None:
    data = _expanded_instruction_declaration(tmp_path)
    data["arms"][0]["inventory"] = str(_inventory(tmp_path))  # type: ignore[index]
    with pytest.raises(calibration.DeclarationRefused, match="no inventory to declare"):
        calibration.parse_declaration(data)


def test_red_a_product_question_inventory_is_refused(tmp_path: Path) -> None:
    """Check 1 (orchestrator review): a 'product' question permits
    treatment-scoped helpers the E arm would lack - exactly the confound
    helper parity exists to rule out. Mutation-check: this must go red on
    'product' and stay green on 'prose' (the positive test above)."""
    bad = _inventory(tmp_path, question="product")
    declaration = calibration.parse_declaration(_expanded_instruction_declaration(tmp_path, inventory_path=bad))
    with pytest.raises(calibration.DeclarationRefused, match="not 'prose'"):
        calibration.validate_expanded_instruction_lane(declaration, ROOT)


def test_red_a_stale_prose_inventory_with_a_treatment_scoped_helper_is_refused(tmp_path: Path) -> None:
    """A second, independent path to the same confound: the question says
    'prose' but a treatment-scoped helper is present anyway (profile.py's
    own refusal was bypassed or the file is stale)."""
    bad = _inventory(tmp_path, treatment_scoped=("sneaky-helper",))
    declaration = calibration.parse_declaration(_expanded_instruction_declaration(tmp_path, inventory_path=bad))
    with pytest.raises(calibration.DeclarationRefused, match="treatment-scoped helper"):
        calibration.validate_expanded_instruction_lane(declaration, ROOT)


def test_red_a_changed_word_in_the_inlined_instruction_is_refused(tmp_path: Path) -> None:
    """Check 2 (orchestrator review): one word changed from the skill's real
    body must be caught, not just a wholly different text."""
    declaration = calibration.parse_declaration(
        _expanded_instruction_declaration(tmp_path, e_instruction=_SKILL_BODY.replace("Never", "Rarely")))
    with pytest.raises(calibration.DeclarationRefused, match="does not match"):
        calibration.validate_expanded_instruction_lane(declaration, ROOT)


def test_red_an_unknown_skill_name_is_refused(tmp_path: Path) -> None:
    declaration = calibration.parse_declaration(
        _expanded_instruction_declaration(
            tmp_path, s_overrides={"instruction": "Use `no-such-skill` first.", "named_skills": ["no-such-skill"]}))
    with pytest.raises(calibration.DeclarationRefused, match="no skill named"):
        calibration.validate_expanded_instruction_lane(declaration, ROOT)
