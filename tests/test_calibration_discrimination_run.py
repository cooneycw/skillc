"""#287 P2: running a discrimination declaration, and rehearsing either kind.

Covers the run-time mutation check, the degraded arm derived from the intact
treatment, the tie to P1's textual evidence, the per-arm tolerance verdict,
and `rehearse=True` accounting for every declared slot through the real
approval/plan/store/schedule path, with its refusal controls. All fixtures are
SYNTHETIC: the committed pilot declarations do not parse until #287 P3 fills
their pins."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from conftest import stamp_approval
from test_calibration_discrimination_declaration import _declaration

from skillc import calibration, trial
from skillc import calibration_run as cr
from skillc import matched_pilot as mp

ROOT = Path(__file__).resolve().parent.parent
REMOVED = "A\n  `skipped gates:` name is a SKIP row - never a PASS.\n"
INTACT_REF = ("# reference\n\n- warn (...) - repeat the qualification verbatim. " + REMOVED + "- other rule\n").encode()
DEGRADED_REF = INTACT_REF.replace(REMOVED.encode(), b"", 1)
MUTATED = trial.sha256_bytes(DEGRADED_REF)
SURFACE = ".codex/skills/flow-check/reference.md"
CLOSURE = "Projects/claude-power-pack/codex/skills/flow-check/reference.md"
PROFILE = "evals/subjects/cpp-codex-flow-check-86641e8"
PROFILE_INVENTORY_DIGEST = "sha256:4ee34823eb9f12c86d35f67d731b97a4c86dcd37ef77f9cada1ba78efe5f695a"
PINS = ({"path": ".codex/skills/flow-check/SKILL.md", "body_digest": "sha256:" + "b" * 64,
         "description_digest": "sha256:" + "c" * 64},)


def _intact(**overrides: Any) -> cr.Treatment:
    files = {".codex/skills/flow-check/SKILL.md": b"---\nname: flow-check\ndescription: d\n---\nbody\n",
             SURFACE: INTACT_REF, CLOSURE: INTACT_REF}
    files.update(overrides)
    return cr.Treatment(home_files=files, digest="sha256:" + "e" * 64, receipt_context=None,
                        verify_home_files={CLOSURE: trial.sha256_bytes(files[CLOSURE])}, skill_digests=PINS)


def _evidence(tmp_path: Path, *, verdict: str = "NO_TEXTUAL_SURVIVOR", digest: str = MUTATED,
              removed: str = REMOVED, closure: str = f"{PROFILE}/evidence/inventory.json") -> Path:
    path = tmp_path / f"diagnose-{abs(hash((verdict, digest, removed, closure)))}.json"
    path.write_text(json.dumps({"mutated_digest": digest, "measured_degraded_reference_digest": digest,
                                "mutated_digest_matches": True, "removed_text": removed, "closure_source": closure,
                                "occurrence_scan": {"verdict": verdict}}))
    return path


def _approved(tmp_path: Path, *, attempts: int = 3, evidence: Path | None = None) -> dict[str, Any]:
    data = _declaration(attempts_per_arm=attempts, mutated_digest=MUTATED)
    for arm in data["arms"]:
        arm["subject"]["profile"] = PROFILE
    data["arms"][1]["mutation"]["removed_text"] = REMOVED
    data["arms"][1]["mutation"]["diagnose_evidence"] = f"{evidence or _evidence(tmp_path)} (synthetic test evidence)"
    data["approval"] = {"by": "owner (test)", "at": "2026-10-17", "attempts_per_arm": attempts, "mutated_digest": MUTATED,
                        "profile_inventory_digest": PROFILE_INVENTORY_DIGEST}
    return stamp_approval(data)


def _parse(data: dict[str, Any]) -> calibration.DiscriminationDeclaration:
    return calibration.parse_discrimination_declaration(data)


# --------------------------------------------------- the run-time mutation check

def test_the_mutation_check_returns_the_approved_degraded_bytes() -> None:
    mutation = {"skill": "flow-check", "path": "reference.md", "removed_text": REMOVED, "mutated_digest": MUTATED}
    assert calibration.require_degraded_mutation(INTACT_REF, mutation) == DEGRADED_REF


@pytest.mark.parametrize("intact, match", [
    (DEGRADED_REF, "occurs 0 time"),
    (INTACT_REF + REMOVED.encode(), "occurs 2 time"),
    (INTACT_REF.replace(b"other rule", b"other rule!"), "hashes to"),
])
def test_the_mutation_check_refuses_bytes_it_does_not_describe(intact: bytes, match: str) -> None:
    mutation = {"skill": "flow-check", "path": "reference.md", "removed_text": REMOVED, "mutated_digest": MUTATED}
    with pytest.raises(calibration.DeclarationRefused, match=match):
        calibration.require_degraded_mutation(intact, mutation)


# ------------------------------------------------ the degraded arm, derived

def test_the_degraded_arm_replaces_every_copy_and_its_recheck_digest(tmp_path: Path) -> None:
    degraded = cr.degraded_treatment(_intact(), _parse(_approved(tmp_path)))
    assert degraded.home_files[SURFACE] == degraded.home_files[CLOSURE] == DEGRADED_REF
    assert degraded.verify_home_files[CLOSURE] == MUTATED
    assert degraded.digest != _intact().digest
    assert degraded.skill_digests == PINS  # reference.md is not SKILL.md: the pins describe unchanged bytes


def test_copies_that_disagree_are_refused(tmp_path: Path) -> None:
    with pytest.raises(cr.CalibrationRefused, match="different bytes"):
        cr.degraded_treatment(_intact(**{CLOSURE: INTACT_REF + b"x"}), _parse(_approved(tmp_path)))


def test_a_missing_target_is_refused(tmp_path: Path) -> None:
    intact = _intact()
    files = {k: v for k, v in intact.home_files.items() if not k.endswith("reference.md")}
    with pytest.raises(cr.CalibrationRefused, match="no skills/flow-check/reference.md"):
        cr.degraded_treatment(cr.Treatment(files, intact.digest, None, skill_digests=PINS), _parse(_approved(tmp_path)))


# ------------------------------------------- the tie to P1's textual evidence

def test_the_textual_evidence_at_the_declared_digest_is_accepted(tmp_path: Path) -> None:
    evidence = cr.require_textual_evidence(_parse(_approved(tmp_path)), ROOT)
    scan = evidence["occurrence_scan"]
    assert isinstance(scan, dict) and scan["verdict"] == "NO_TEXTUAL_SURVIVOR"


def test_textual_evidence_at_another_digest_is_refused(tmp_path: Path) -> None:
    """Orchestrator condition: the runtime and the textual check must describe
    the SAME degraded file."""
    declaration = _parse(_approved(tmp_path, evidence=_evidence(tmp_path, digest="sha256:" + "0" * 64)))
    with pytest.raises(cr.CalibrationRefused, match="describe different degraded files"):
        cr.require_textual_evidence(declaration, ROOT)


@pytest.mark.parametrize("verdict", ["SURVIVES", "NEEDS_REVIEW", "UNKNOWN"])
def test_textual_evidence_without_a_clean_verdict_is_refused(tmp_path: Path, verdict: str) -> None:
    declaration = _parse(_approved(tmp_path, evidence=_evidence(tmp_path, verdict=verdict)))
    with pytest.raises(cr.CalibrationRefused, match="did not report NO_TEXTUAL_SURVIVOR"):
        cr.require_textual_evidence(declaration, ROOT)


def test_the_committed_discrimination_draft_names_p1s_verified_digest() -> None:
    """The committed draft's mutated_digest is the digest P1's scan was run
    at, and verified (it does not parse yet, so read as JSON)."""
    draft = json.loads((ROOT / "evals/calibration-287/pilot-discrimination-declaration.json").read_text())
    mutation = next(a["mutation"] for a in draft["arms"] if a["name"] == "degraded")
    evidence = json.loads((ROOT / mutation["diagnose_evidence"].split()[0]).read_text())
    assert evidence["measured_degraded_reference_digest"] == evidence["mutated_digest"] == mutation["mutated_digest"]
    assert evidence["mutated_digest_matches"] is True
    assert evidence["occurrence_scan"]["verdict"] == "NO_TEXTUAL_SURVIVOR"


# ----------------------------------------------------- the tolerance verdict

def _report(arm_statuses: dict[str, list[str]]) -> dict[str, object]:
    return {"attempts": [{"arm": arm, "primary_endpoint": {"status": s}}
                         for arm, statuses in arm_statuses.items() for s in statuses]}


def test_tolerance_boundary_equal_is_evaluable_one_more_is_unknown() -> None:
    out = cr.apply_tolerance(_report({"intact": ["PASS", "FAIL", "NOT_GRADED"],
                                      "degraded": ["PASS", "INCONCLUSIVE", "NOT_GRADED"]}), tolerance=1)
    assert out["intact"]["verdict_status"] == "EVALUABLE" and out["intact"]["non_evaluable"] == 1
    assert out["degraded"]["verdict_status"] == "UNKNOWN"
    assert "2 non-evaluable attempt(s) exceed the declared tolerance of 1" in str(out["degraded"]["reason"])


# ------------------------------------------------ rehearsal: every slot, real path

def _rehearse(tmp_path: Path, data: dict[str, Any], **kwargs: Any) -> tuple[trial.Experiment, list[mp.AttemptOutcome]]:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    return cr.run_discrimination(_parse(data), run_dir=run_dir, intact=_intact(), image_digest="sha256:" + "d" * 64,
                                 backends=lambda: pytest.fail("a rehearsal must start no backend"),  # type: ignore[arg-type,return-value]
                                 argv_for=lambda _s: ["codex"], rehearse=True, **kwargs)


def test_a_rehearsal_accounts_for_every_declared_slot(tmp_path: Path) -> None:
    data = _approved(tmp_path, attempts=3)
    experiment, outcomes = _rehearse(tmp_path, data)
    declaration = _parse(data)
    accounting = cr.rehearsal_accounting(declaration, outcomes)
    assert accounting["every_slot_accounted"] is True
    assert accounting["slots_declared"] == accounting["slots_accounted"] == 6
    assert accounting["accounted_by_arm"] == {"intact": 3, "degraded": 3}
    assert accounting["worst_case_seconds"] == 6 * 1200
    assert all(o.record["disposition"] == "unavailable" and o.record.get("reason") == cr.REHEARSAL_REASON
               for o in outcomes)
    report = cr.build_discrimination_report(experiment, outcomes, declaration, rehearsal=True)
    assert report["kind"] == cr.DISCRIMINATION_REPORT_KIND and report["rehearsal"] is True
    assert report["declaration_digest"] == calibration.declaration_digest(data)
    evaluability = report["evaluability"]
    assert isinstance(evaluability, dict)
    assert {arm: v["verdict_status"] for arm, v in evaluability.items()} == \
        {"intact": "UNKNOWN", "degraded": "UNKNOWN"}  # every rehearsal attempt is non-evaluable, by construction


def test_each_arm_is_planned_with_its_own_subject_digest(tmp_path: Path) -> None:
    experiment, _ = _rehearse(tmp_path, _approved(tmp_path, attempts=2))
    digests: dict[str, set[object]] = {}
    for planned, _attempt in experiment.attempts():
        arm = "degraded" if "_degraded_" in str(planned["trial_id"]) else "intact"
        digests.setdefault(arm, set()).add(planned["subject"]["digest"])  # type: ignore[index]
    assert digests["intact"] == {_intact().digest}
    assert len(digests["degraded"]) == 1 and digests["degraded"] != digests["intact"]


def test_over_cap_slots_are_not_run_but_still_accounted(tmp_path: Path) -> None:
    now = [0.0]

    def clock() -> float:
        now[0] += 1000.0
        return now[0]

    data = _approved(tmp_path, attempts=3)
    _experiment, outcomes = _rehearse(tmp_path, data, total_seconds=2500.0, clock=clock)
    assert cr.rehearsal_accounting(_parse(data), outcomes)["every_slot_accounted"] is True
    assert any(o.record["disposition"] == "not-run" for o in outcomes)


def test_an_unapproved_declaration_is_refused_before_any_store(tmp_path: Path) -> None:
    data = _approved(tmp_path)
    data["approval"] = None
    with pytest.raises(calibration.DeclarationRefused, match="not approved"):
        _rehearse(tmp_path, data)
    assert not (tmp_path / "run" / "store").exists()


def test_a_stale_approval_digest_is_refused_before_any_store(tmp_path: Path) -> None:
    data = _approved(tmp_path)
    data["approval"]["mutated_digest"] = "sha256:" + "f" * 64
    with pytest.raises(calibration.DeclarationRefused, match="approved for mutation.mutated_digest"):
        _rehearse(tmp_path, data)
    assert not (tmp_path / "run" / "store").exists()


def test_a_mutated_identity_is_refused_before_any_store(tmp_path: Path) -> None:
    """The acquired intact file no longer carries removed_text exactly once."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    with pytest.raises(cr.CalibrationRefused, match="occurs 0 time"):
        cr.run_discrimination(_parse(_approved(tmp_path)), run_dir=run_dir,
                              intact=_intact(**{SURFACE: DEGRADED_REF, CLOSURE: DEGRADED_REF}),
                              image_digest="sha256:" + "d" * 64, backends=lambda: (None, None),
                              argv_for=lambda _s: ["codex"],
                              rehearse=True)
    assert not (run_dir / "store").exists()


def test_the_calibration_kind_rehearses_too(tmp_path: Path) -> None:
    from test_calibration_run import _TEST_PINS
    from test_calibration_run import _declaration as calibration_declaration
    declaration = calibration_declaration(attempts=2)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _experiment, outcomes = cr.run_calibration(
        declaration, run_dir=run_dir, treatment=cr.Treatment({}, "sha256:" + "ab" * 32, None, skill_digests=_TEST_PINS),
        image_digest=declaration.shared["image"]["digest"],  # type: ignore[index]
        backends=lambda: pytest.fail("a rehearsal must start no backend"),  # type: ignore[arg-type,return-value]
        argv_for=lambda _s: ["codex"], rehearse=True,
    )
    accounting = cr.rehearsal_accounting(declaration, outcomes)
    assert accounting["every_slot_accounted"] is True and accounting["slots_declared"] == len(declaration.arm_order)
    assert copy.deepcopy(accounting)["accounted_by_arm"] == accounting["slots_by_arm"]


def test_the_accounting_reports_a_missing_slot(tmp_path: Path) -> None:
    """Red case for the rehearsal's own pass/fail: the CLI exits 1 unless
    every slot is accounted, so a dropped outcome must read False."""
    data = _approved(tmp_path, attempts=2)
    _experiment, outcomes = _rehearse(tmp_path, data)
    assert cr.rehearsal_accounting(_parse(data), outcomes[:-1])["every_slot_accounted"] is False


def test_the_cli_dispatches_on_kind_and_refuses_an_unapproved_discrimination(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    from skillc import cli
    data = _approved(tmp_path)
    data["approval"] = None
    path = tmp_path / "decl.json"
    path.write_text(json.dumps(data))
    private = tmp_path / "private"
    code = cli.main(["calibration-run", str(path), "--rehearse", "--private-dir", str(private)])
    assert code == 2
    assert "not approved" in capsys.readouterr().err
    assert not private.exists()



@pytest.mark.parametrize("statuses", [["NOT_GRADED"], ["NOT_GRADED", "INCONCLUSIVE"]])
def test_an_arm_with_no_evaluable_attempt_is_unknown_even_within_tolerance(statuses: list[str]) -> None:
    """Counter-model finding: tolerance covering the whole arm read EVALUABLE
    with nothing evaluable at all."""
    out = cr.apply_tolerance(_report({"intact": statuses}), tolerance=len(statuses))
    assert out["intact"]["verdict_status"] == "UNKNOWN"
    assert out["intact"]["reason"] == "no evaluable attempt: nothing to compare"


def test_a_report_with_a_changed_declaration_is_refused(tmp_path: Path) -> None:
    """Counter-model finding: a report scored against a replacement
    declaration (here, a raised tolerance) instead of the launch-bound one."""
    data = _approved(tmp_path, attempts=2)
    experiment, outcomes = _rehearse(tmp_path, data)
    changed = copy.deepcopy(data)
    changed["tolerance"]["non_evaluable_per_arm"] = 99
    stamp_approval(changed)
    with pytest.raises(cr.CalibrationRefused, match="differs from the one this run launched with"):
        cr.build_discrimination_report(experiment, outcomes, _parse(changed), rehearsal=True)
    report = cr.build_discrimination_report(experiment, outcomes, _parse(data), rehearsal=True)
    assert report["declaration_digest"] == calibration.declaration_digest(data)



def test_evidence_about_a_different_removed_sentence_is_refused(tmp_path: Path) -> None:
    """Counter-model finding (pass 2): different removals can yield the same
    degraded bytes; evidence about sentence A must not vouch for sentence B."""
    declaration = _parse(_approved(tmp_path, evidence=_evidence(tmp_path, removed="some other sentence")))
    with pytest.raises(cr.CalibrationRefused, match="different removed_text"):
        cr.require_textual_evidence(declaration, ROOT)


def test_evidence_from_another_closure_is_refused(tmp_path: Path) -> None:
    declaration = _parse(_approved(tmp_path, evidence=_evidence(tmp_path, closure="evals/subjects/other/evidence/inventory.json")))
    with pytest.raises(cr.CalibrationRefused, match="scanned closure"):
        cr.require_textual_evidence(declaration, ROOT)


def test_a_subject_without_a_profile_cannot_bind_the_scanned_closure(tmp_path: Path) -> None:
    data = _approved(tmp_path)
    for arm in data["arms"]:
        del arm["subject"]["profile"]
    del data["approval"]["profile_inventory_digest"]
    stamp_approval(data)
    with pytest.raises(cr.CalibrationRefused, match="declares no profile"):
        cr.require_textual_evidence(_parse(data), ROOT)


def test_a_report_over_an_unapproved_stored_snapshot_is_refused(tmp_path: Path) -> None:
    """Counter-model finding (pass 2): planning does not check approval, so a
    ledger planned from an unapproved declaration must not report clean."""
    data = _approved(tmp_path, attempts=1)
    data["approval"] = None
    declaration = _parse(data)
    store = trial.open_store(tmp_path / "store", forbidden=[])
    experiment, schedule = cr.plan_discrimination(
        declaration, store, root=ROOT, treatments={"intact": _intact(), "degraded": _intact()}, image_digest=None)
    outcomes = [mp.AttemptOutcome(s, trial.finalize(experiment, s.attempt_id, disposition="unavailable", reason="t"), None)
                for s in schedule]
    with pytest.raises(cr.CalibrationRefused, match="not an approved one"):
        cr.build_discrimination_report(experiment, outcomes, declaration)



def test_another_delivered_skill_still_carrying_the_sentence_is_refused(tmp_path: Path) -> None:
    """Counter-model finding (pass 3): the subject installs every skill while
    P1's scan covered only the profile closure; a copy of the removed sentence
    in ANOTHER delivered skill must refuse the run."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    intact = _intact(**{".codex/skills/flow-auto/notes.md": b"Remember: " + REMOVED.encode()})
    with pytest.raises(cr.CalibrationRefused, match="still delivers the removed sentence"):
        cr.run_discrimination(_parse(_approved(tmp_path)), run_dir=run_dir, intact=intact,
                              image_digest="sha256:" + "d" * 64, backends=lambda: (None, None),
                              argv_for=lambda _s: ["codex"], rehearse=True)
    assert not (run_dir / "store").exists()


def test_a_wrapped_piece_in_another_delivered_skill_is_refused(tmp_path: Path) -> None:
    intact = _intact(**{".codex/skills/flow-auto/notes.md": b"`skipped gates:` name is a SKIP row - never a PASS.\n"})
    with pytest.raises(cr.CalibrationRefused, match="piece of it"):
        cr.require_no_delivered_survivor(cr.degraded_treatment(intact, _parse(_approved(tmp_path))), REMOVED)


def test_a_run_on_an_unapproved_image_is_refused_before_any_store(tmp_path: Path) -> None:
    """Counter-model finding (pass 3): the runner accepted an image digest
    other than the approved one."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    with pytest.raises(cr.CalibrationRefused, match="image digest differs"):
        cr.run_discrimination(_parse(_approved(tmp_path)), run_dir=run_dir, intact=_intact(),
                              image_digest="sha256:" + "9" * 64, backends=lambda: (None, None),
                              argv_for=lambda _s: ["codex"], rehearse=True)
    assert not (run_dir / "store").exists()


def test_a_report_over_a_ledger_with_another_image_is_refused(tmp_path: Path) -> None:
    """The report checks every trial's runtime identity against the stored,
    approved declaration: an approved snapshot planned on another image."""
    data = _approved(tmp_path, attempts=1)
    declaration = _parse(data)
    store = trial.open_store(tmp_path / "store", forbidden=[])
    degraded = cr.degraded_treatment(_intact(), declaration)
    experiment, schedule = cr.plan_discrimination(
        declaration, store, root=ROOT, treatments={"intact": _intact(), "degraded": degraded},
        image_digest="sha256:" + "9" * 64)
    outcomes = [mp.AttemptOutcome(s, trial.finalize(experiment, s.attempt_id, disposition="unavailable", reason="t"), None)
                for s in schedule]
    with pytest.raises(cr.CalibrationRefused, match="runtime identity disagree"):
        cr.build_discrimination_report(experiment, outcomes, declaration)


def test_640_discrimination_refuses_a_fixture_builder_before_any_store(tmp_path: Path) -> None:
    data = _approved(tmp_path, attempts=1)
    data["task"].update({"path": "evals/level3/flow-auto-necessity", "grader_id": "flow-auto-necessity",
                         "grader_revision": "5", "fixture": "builder", "fixture_case": "clean"})
    data["approval"]["task_fixture"] = "builder"
    declaration = _parse(stamp_approval(data))
    # Establish that approval itself passes, so the refusal exercises dispatch.
    calibration.require_approved_discrimination(declaration, ROOT)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    with pytest.raises(cr.CalibrationRefused, match="fixture dispatch.*calibration-only"):
        cr.run_discrimination(declaration, run_dir=run_dir, intact=_intact(), image_digest="sha256:" + "d" * 64,
                              backends=lambda: pytest.fail("no backend"), argv_for=lambda _: pytest.fail("no argv"))
    assert not (run_dir / "store").exists()
