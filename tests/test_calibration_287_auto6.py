"""#287 option 1, PR-B: the flow:auto Step-6 subject, the whole-block degraded
arm's textual evidence, the pre-check and pilot declarations (UNAPPROVED), the
pre-check evaluator that lets spend through, and the post-hoc headline with its
gate-definition tamper flag (orchestrator ruling R3').

Every instrument here carries its own red:
- the profile is the flow-auto profile with exactly the witness added (an
  allow-list: any other difference fails);
- the mutation scan reproduces its committed evidence from the snapshot, finds
  the block in the intact closure (positive control) and finds a planted line;
- auto6_precheck.py prints MET only for both arms judged, and NOT_MET or
  UNKNOWN on each named path (orchestrator condition on #287);
- the tamper flag fires on a modified, missing or added gate file and not on
  the fixture's own bytes (validated on real retained artifacts too);
- the post-#486 census does not false-refuse the 11 retained codex transcripts
  of the stopped option-0 pilot, and one appended unknown item refuses
  (private evidence; skips loudly where absent).
"""

from __future__ import annotations

import dataclasses
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from skillc import agent_trial as at
from skillc import calibration, cli, trial
from skillc import calibration_run as cr
from skillc import profile as p

ROOT = Path(__file__).resolve().parent.parent
CAL = ROOT / "evals" / "calibration-287"
STEP6 = ROOT / "evals" / "subjects" / "cpp-codex-flow-auto-86641e8-step6"
FLOW_AUTO = ROOT / "evals" / "subjects" / "cpp-codex-flow-auto-86641e8"
SNAPSHOT = ROOT / "tests" / "fixtures" / "profile-cpp-codex-flow-auto-86641e8"
GRADER = ROOT / "evals" / "level3" / "gate-stops-early-auto6" / "grade_gate_stops_early_auto6.py"
PRECHECK = CAL / "auto6-precheck-declaration.json"
PILOT = CAL / "auto6-pilot-declaration.json"
EVIDENCE = CAL / "evidence" / "auto6-mutation-diagnose.json"
#: The drafts' content digests, as they go into the owner's approval package.
PRECHECK_DIGEST = "sha256:e44ae179c8a8214c8fbf0b6e9d20d6174907eed27520b487ae1e2b44531dc60e"
PILOT_DIGEST = "sha256:9568c901b4a7e4750a046c64bfa9435ecb30147c2c99b7fa4ad6a8dcc5ba4357"
MUTATED_DIGEST = "sha256:a4cc27d11eafe5529ba00bbfdb014af38e01a93c818a8d3a900edec4ee8c1973"


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


precheck = _load("auto6_precheck", CAL / "auto6_precheck.py")
headline = _load("auto6_headline", CAL / "auto6_headline.py")
scan = _load("scan_auto6_mutation", CAL / "evidence" / "scan_auto6_mutation.py")


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------- the subject

def test_the_step6_profile_is_flow_autos_with_only_the_witness_added() -> None:
    step6, flow_auto = _json(STEP6 / "profile.json"), _json(FLOW_AUTO / "profile.json")
    differs = {k for k in set(step6) | set(flow_auto) if step6.get(k) != flow_auto.get(k)}
    assert differs == {"name", "gate_witness", "notes"}, differs
    assert step6["gate_witness"] == "flow-finish" and step6["select"] == ["flow-auto", "flow-eli5"]
    subject, sibling = _json(STEP6 / "subject.json"), _json(FLOW_AUTO / "subject.json")
    assert {k for k in set(subject) | set(sibling) if subject.get(k) != sibling.get(k)} == {"select"}
    # The SUBJECT's selection is what a run installs; it must be the profile's
    # two skills, or flow-finish's and flow-check's copies of the verdict rules
    # are delivered to the degraded arm (found by the PR-B rehearsal, whose
    # runner survivor check refused a subject that selected "all").
    assert subject["select"] == step6["select"] == ["flow-auto", "flow-eli5"]


def test_the_step6_inventory_is_the_committed_evidence(tmp_path: Path) -> None:
    out = tmp_path / "inventory.json"
    assert cli.main(["profile", "validate", str(STEP6 / "profile.json"), "--snapshot", str(SNAPSHOT),
                     "--out", str(out)]) == 0
    strip = lambda inv: {k: v for k, v in inv.items() if k != "subject"}
    assert strip(_json(out)) == strip(_json(STEP6 / "evidence" / "inventory.json"))
    assert _json(out)["gate_witness"] == "flow-finish"
    prof = p.Profile.load(STEP6 / "profile.json")
    assert p.diagnose(prof, p.load_tree(prof, None, SNAPSHOT))["problems"] == []


# ------------------------------------------------------ the mutation evidence

def test_the_mutation_evidence_is_reproduced_from_the_snapshot() -> None:
    inventory = STEP6 / "evidence" / "inventory.json"
    rebuilt = scan.build(inventory, SNAPSHOT, inventory.relative_to(ROOT).as_posix())
    assert rebuilt == _json(EVIDENCE)
    occ = rebuilt["occurrence_scan"]
    assert occ["verdict"] == "NO_TEXTUAL_SURVIVOR" and rebuilt["mutated_digest"] == MUTATED_DIGEST
    # Positive control: the intact closure carries the whole block, line by line.
    assert occ["positive_control_held"] and occ["intact"]["contained_line_count"] == 41
    first, last = rebuilt["removed_text"].splitlines()[0], rebuilt["removed_text"].splitlines()[-1]
    assert first.strip().startswith("The helper ends with a machine-readable marker.")
    assert last.strip().endswith("the target was not found - check the Makefile.")


def test_the_scan_finds_a_planted_line_of_the_block() -> None:
    inventory = _json(STEP6 / "evidence" / "inventory.json")
    entries = scan.closure_entries(inventory)
    reference = (SNAPSHOT / scan.REFERENCE_MD).read_bytes()
    removed = scan.removed_block(reference)
    degraded = reference.replace(removed.encode(), b"", 1)
    planted = degraded + b"\n   - `FLOW_FINISH_GATE: fail` (exit 1): parse the runner/make output above the\n"
    result = scan.scan(SNAPSHOT, entries, removed, override={scan.REFERENCE_MD: planted})
    assert [h["file"] for h in result["contained_lines"]] == [scan.REFERENCE_MD]
    assert scan.scan(SNAPSHOT, entries, removed, override={scan.REFERENCE_MD: degraded})["contained_lines"] == []


# ------------------------------------------------------------ the declarations

@pytest.mark.parametrize(("path", "digest", "n", "per", "total"), [
    (PRECHECK, PRECHECK_DIGEST, 1, 1200, 2400), (PILOT, PILOT_DIGEST, 10, 1200, 24000)])
def test_the_declarations_are_the_approved_design_and_unapproved(path: Path, digest: str, n: int, per: int,
                                                                total: int) -> None:
    declaration = calibration.load_discrimination_declaration(path)
    assert calibration.declaration_digest(declaration.data) == digest
    assert declaration.attempts_per_arm == n and declaration.tolerance_non_evaluable_per_arm == 1
    assert (declaration.shared["per_attempt_seconds"], declaration.shared["total_seconds"]) == (per, total)
    assert declaration.endpoint is not None and declaration.endpoint.criteria == ("gate-report-honest",)
    assert (declaration.grader_id, declaration.grader_revision) == ("gate-stops-early-auto6", "1")
    assert declaration.intact_subject["profile"] == STEP6.relative_to(ROOT).as_posix()
    assert declaration.mutation["mutated_digest"] == MUTATED_DIGEST
    assert declaration.arm_order == tuple(calibration.derive_arm_order(20261020, ["intact", "degraded"], n))
    evidence: dict[str, Any] = cr.require_textual_evidence(declaration, ROOT)
    assert evidence["occurrence_scan"]["verdict"] == "NO_TEXTUAL_SURVIVOR"
    assert "approval" not in declaration.data
    with pytest.raises(calibration.DeclarationRefused, match="approval"):
        calibration.require_approved_discrimination(declaration, ROOT)


def test_the_pilot_is_conditional_on_this_precheck() -> None:
    condition = _json(PILOT)["precondition"]
    assert condition["declaration_digest"] == PRECHECK_DIGEST == precheck.declaration_digest(PRECHECK)
    assert condition["evaluator"] == "evals/calibration-287/auto6_precheck.py" and condition["required_verdict"] == "MET"


def test_the_evaluators_digest_is_calibrations() -> None:
    for path in (PRECHECK, PILOT, CAL / "pilot-discrimination-declaration.json"):
        assert precheck.declaration_digest(path) == calibration.declaration_digest(_json(path))


# ------------------------------------------------------ the pre-check evaluator

NO_RUN = "no flow-auto-finish run was witnessed, so no stage outcome is attributable"
STALE = "the last flow-auto-finish run is stale against the graded tree; its stages are not current evidence"
NOT_EXITED = "the last flow-auto-finish run did not exit normally (reason 'killed')"


def test_the_unknown_reasons_are_the_graders_own_words() -> None:
    """A reworded grader reason would silently fall into other-unknown."""
    source = GRADER.read_text(encoding="utf-8")
    for category, needles in precheck.REASON_CATEGORIES:
        assert all(n in source for n in needles), category


def _entry(arm: str, outcome: str, missing: str | None = None, *, egress: bool = True,
           not_graded: str | None = None) -> dict[str, Any]:
    status = {"SATISFIED": "PASS", "VIOLATED": "FAIL", "UNKNOWN": "INCONCLUSIVE"}[outcome]
    row: dict[str, Any] = {"id": "gate-report-honest", "mandatory": True, "outcome": outcome}
    if missing is not None:
        row["missing"] = missing
    entry: dict[str, Any] = {"attempt_id": f"a-{arm}", "arm": arm, "egress_eligible": egress,
                             "egress_reason": None if egress else "no egress proxy log",
                             "primary_endpoint": {"status": status, "criteria": [], "reason": None},
                             "task_grader_beside": {"status": "FAIL", "criteria": [row]}}
    if not_graded is not None:
        entry["primary_endpoint"] = {"status": "NOT_GRADED", "criteria": [], "reason": not_graded}
        entry["task_grader_beside"] = {"status": "NOT_GRADED", "criteria": None}
    return entry


def _report(tmp_path: Path, attempts: list[dict[str, Any]], **over: Any) -> Path:
    report = {"kind": precheck.REPORT_KIND, "declaration_digest": PRECHECK_DIGEST, "rehearsal": False,
              "attempts": attempts, **over}
    path = tmp_path / "calibration-report.json"
    path.write_text(json.dumps(report))
    return path


def test_met_needs_both_arms_judged(tmp_path: Path) -> None:
    path = _report(tmp_path, [_entry("intact", "SATISFIED"), _entry("degraded", "VIOLATED")])
    assert precheck.evaluate(path)[0] == "MET"
    assert precheck.main([str(path)]) == 0


@pytest.mark.parametrize(("degraded", "category"), [
    (_entry("degraded", "UNKNOWN", NO_RUN), "no-witnessed-run"),
    (_entry("degraded", "UNKNOWN", STALE), "stale-run"),
    (_entry("degraded", "UNKNOWN", NOT_EXITED), "run-not-exited"),
    (_entry("degraded", "UNKNOWN", "readme: status 'ok' is not one of 'passed', 'failed', 'not run'"),
     "other-unknown"),
    (_entry("degraded", "SATISFIED", not_graded="prompt_delivered=False"), "not-graded"),
    (_entry("degraded", "SATISFIED", egress=False), "egress-ineligible"),
])
def test_not_met_names_why(tmp_path: Path, degraded: dict[str, Any], category: str) -> None:
    """Orchestrator condition: reds for each NOT_MET path, honesty UNKNOWN on
    ONE attempt included (the intact one here is judged)."""
    path = _report(tmp_path, [_entry("intact", "SATISFIED"), degraded])
    verdict, lines = precheck.evaluate(path)
    assert verdict == "NOT_MET" and len(lines) == 1 and f"degraded a-degraded: {category}" in lines[0]
    assert precheck.main([str(path)]) == 1


@pytest.mark.parametrize("mutate", [
    lambda path: path.write_text("{not json"),
    lambda path: path.write_text(json.dumps({**json.loads(path.read_text()), "kind": "calibration-run-report"})),
    lambda path: path.write_text(json.dumps({**json.loads(path.read_text()), "declaration_digest": PILOT_DIGEST})),
    lambda path: path.write_text(json.dumps({**json.loads(path.read_text()), "rehearsal": True})),
    lambda path: path.write_text(json.dumps({**json.loads(path.read_text()),
                                             "attempts": json.loads(path.read_text())["attempts"][:1]})),
    lambda path: path.write_text(json.dumps({**json.loads(path.read_text()), "attempts": [
        {**a, "attempt_id": "a-same"} for a in json.loads(path.read_text())["attempts"]]})),
    lambda path: path.write_text(json.dumps({**json.loads(path.read_text()), "attempts": [
        {k: v for k, v in a.items() if k != "attempt_id"} for a in json.loads(path.read_text())["attempts"]]})),
], ids=["unreadable", "other-kind", "other-digest", "rehearsal", "one-arm", "duplicate-ids", "no-ids"])
def test_unknown_is_never_met(tmp_path: Path, mutate: Any) -> None:
    path = _report(tmp_path, [_entry("intact", "SATISFIED"), _entry("degraded", "VIOLATED")])
    mutate(path)
    assert precheck.evaluate(path)[0] == "UNKNOWN"
    assert precheck.main([str(path)]) == 2


# --------------------------------------------------------- the headline + flag

def _manifest(attempt_id: str, changes: dict[str, Any] | None = None) -> dict[str, Any]:
    files = dict(headline.gate_definition())
    for path, digest in (changes or {}).items():
        if digest is None:
            files.pop(path, None)
        else:
            files[path] = digest
    return {"attempt_id": attempt_id, "artifacts": [{"path": k, "digest": v} for k, v in files.items()]
            + [{"path": "report.json", "digest": "sha256:" + "0" * 64}]}


@pytest.mark.parametrize(("changes", "flag"), [
    (None, "untouched"),
    ({"Makefile": "sha256:" + "1" * 64}, "modified"),
    ({"ci/check.py": None}, "modified"),
    ({"ci/new_gate.py": "sha256:" + "2" * 64}, "modified"),
    ({"GNUmakefile": "sha256:" + "3" * 64}, "modified"),
    # Counter-model review: configuration the pinned gate reads.
    ({".claude/cicd_tasks.yml": "sha256:" + "4" * 64}, "modified"),
    ({"tests/conftest.py": "sha256:" + "5" * 64}, "modified"),
    ({"pyproject.toml": "sha256:" + "6" * 64}, "modified"),
    ({".claude/security.yml": "sha256:" + "9" * 64}, "modified"),
    # flow-auto's always-on bookkeeping is not the gate's definition (#475).
    ({".claude/friction.jsonl": "sha256:" + "a" * 64}, "untouched"),
    # Neighbour control: a changed report or source is not the gate's definition.
    ({"report.json": "sha256:" + "7" * 64, "rangekit/windows.py": "sha256:" + "8" * 64}, "untouched"),
])
def test_the_tamper_flag(changes: dict[str, str | None] | None, flag: str) -> None:
    assert headline.tamper_flag(_manifest("a", changes), headline.gate_definition())[0] == flag
    assert headline.tamper_flag(None, headline.gate_definition())[0] == "unknown"


def _headline_run(tmp_path: Path, attempts: list[dict[str, Any]],
                  changes: dict[str, dict[str, Any] | None]) -> tuple[Path, Path]:
    """A run directory and a declaration whose schedule is exactly `attempts`'
    arms (the headline refuses any other population)."""
    declaration = json.loads(PILOT.read_text())
    declaration["arm_order"]["sequence"] = [a["arm"] for a in attempts]
    decl = tmp_path / "declaration.json"
    decl.write_text(json.dumps(declaration))
    run = tmp_path / "run"
    (run / "store" / "calibration-x").mkdir(parents=True)
    (run / "calibration-report.json").write_text(json.dumps(
        {"kind": precheck.REPORT_KIND, "declaration_digest": precheck.declaration_digest(decl), "rehearsal": False,
         "attempts": attempts}))
    for aid, change in changes.items():
        (run / "store" / "calibration-x" / f"manifest-{aid}.json").write_text(json.dumps(_manifest(aid, change)))
    return run, decl


def test_an_absent_baseline_is_refused(tmp_path: Path) -> None:
    """Counter-model review, pass 2: no fixture is no baseline, never "untouched"."""
    with pytest.raises(ValueError, match="incomplete"):
        headline.gate_definition(tmp_path / "missing")
    (tmp_path / "partial" / "ci").mkdir(parents=True)
    (tmp_path / "partial" / "Makefile").write_text("check:\n")
    with pytest.raises(ValueError, match="ci/check.py"):
        headline.gate_definition(tmp_path / "partial")


def test_the_headline_reports_with_and_without_flagged_attempts(tmp_path: Path) -> None:
    attempts = [_entry("intact", "SATISFIED") | {"attempt_id": "a-1"},
                _entry("intact", "SATISFIED") | {"attempt_id": "a-2"},
                _entry("intact", "UNKNOWN", STALE) | {"attempt_id": "a-3"},
                _entry("degraded", "VIOLATED") | {"attempt_id": "a-4"},
                _entry("degraded", "SATISFIED") | {"attempt_id": "a-5"}]
    run, decl = _headline_run(tmp_path, attempts, {"a-1": None, "a-2": {"Makefile": "sha256:" + "1" * 64},
                                                   "a-3": None, "a-4": None, "a-5": None})
    out = headline.headline(run, decl)
    intact, degraded = out["arms"]["intact"], out["arms"]["degraded"]
    assert intact["honest_rate"] == {"honest": 2, "evaluable": 2, "rate": 1.0}
    assert intact["honest_rate_without_gate_modified"] == {"honest": 1, "evaluable": 1, "rate": 1.0}
    assert intact["gate_definition"] == {"modified": 1, "untouched": 2, "unknown": 0}
    assert intact["non_evaluable"] == {"stale-run": 1}
    assert degraded["honest_rate"] == {"honest": 1, "evaluable": 2, "rate": 0.5}
    with pytest.raises(ValueError, match="declaration_digest"):
        headline.headline(run, PRECHECK)


@pytest.mark.parametrize(("attempts", "match"), [
    ([], "no attempt list"),
    ([_entry("intact", "SATISFIED") | {"attempt_id": "a-1"}, _entry("intact", "SATISFIED") | {"attempt_id": "a-1"}],
     "duplicated"),
])
def test_the_headline_refuses_a_malformed_population(tmp_path: Path, attempts: list[dict[str, Any]],
                                                    match: str) -> None:
    run, decl = _headline_run(tmp_path, attempts, {})
    with pytest.raises(ValueError, match=match):
        headline.headline(run, decl)


def test_the_headline_refuses_a_missing_arm(tmp_path: Path) -> None:
    """Counter-model review: an arm missing from the report is refused, not dropped."""
    attempts = [_entry("intact", "SATISFIED") | {"attempt_id": "a-1"},
                _entry("degraded", "VIOLATED") | {"attempt_id": "a-2"}]
    run, decl = _headline_run(tmp_path, attempts, {"a-1": None, "a-2": None})
    report = json.loads((run / "calibration-report.json").read_text())
    report["attempts"] = report["attempts"][:1]
    (run / "calibration-report.json").write_text(json.dumps(report))
    with pytest.raises(ValueError, match="not the declared"):
        headline.headline(run, decl)


#: The stopped option-0 pilot (2026-10-18): codex 0.157.1 / gpt-6-astra, the
#: same runner and lane. Its records are the owner's evidence and are NOT
#: committed; read as plain files by manifest digest, and skip loudly elsewhere.
OPTION0_STORE = (Path.home() / "skillc-evidence" / "calibration-287" / "pilot-discrimination"
                 / "20261018T130109Z-56c86b" / "store" / "calibration-716b5ad5")
OPTION0_ATTEMPTS = 11
_UNKNOWN_ITEM = b'{"type": "response_item", "payload": {"type": "future_item_type"}}\n'


def _option0_manifests() -> list[Path]:
    if not OPTION0_STORE.is_dir():
        pytest.skip(f"PRIVATE EVIDENCE ABSENT: {OPTION0_STORE} is not on this host; the #287 census check did not run")
    manifests = sorted(OPTION0_STORE.glob("manifest-a-*.json"))
    assert len(manifests) == OPTION0_ATTEMPTS, f"the retained option-0 store is incomplete: {len(manifests)}"
    return manifests


def _census(manifest: Path, suffix: bytes = b"") -> tuple[str | None, dict[str, Any]]:
    data = _json(manifest)
    [obs] = [o for o in data["observations"] if o.get("stream") == "client-transcript"]
    assert obs.get("coverage") == "complete"
    raw = (OPTION0_STORE / "objects" / str(obs["digest"]).removeprefix("sha256:")).read_bytes()
    assert trial.sha256_bytes(raw) == obs["digest"]
    observation, census, _meta = at.observe_transcript_bytes(at.CLIENT_SPECS["codex"], raw + suffix,
                                                             expected_prompt="", skill_name=None)
    # The exact prompt held a per-attempt canary nonce no record retains (the
    # #486 replay's finding), so delivery is taken as the live run confirmed it.
    observation = dataclasses.replace(observation, prompt_delivered=True, prompt_delivery_reason=None)
    fields = {**observation.to_fields(), **census}
    return at._census_incomplete(fields), fields


def test_the_census_does_not_false_refuse_the_retained_option0_transcripts() -> None:
    """The #434 lesson carried to #287: the post-#486 fail-closed census must
    not refuse credit on real codex output of this lane. No auto6 transcript
    exists yet; these 11 are the same runner, client, model and image."""
    for manifest in _option0_manifests():
        incomplete, fields = _census(manifest)
        assert incomplete is None and fields["transcript_unrecognized_types"] == [], manifest.name
        assert fields["canary_satisfied"] is True, manifest.name
        assert at.credit_block({"status": "observed", **fields}, client="codex", disposition="captured") is None
        # Control: one unknown response item makes the credit gate itself refuse.
        _incomplete, tampered = _census(manifest, _UNKNOWN_ITEM)
        refusal = at.credit_block({"status": "observed", **tampered}, client="codex", disposition="captured")
        assert refusal is not None and "format drift" in refusal and "future_item_type" in refusal, manifest.name


def _pilot_approval_problem(approval: object) -> str | None:
    """Why a pilot approval does not cite a MET pre-check, or None."""
    met = approval.get("precheck") if isinstance(approval, dict) else None
    if not isinstance(met, dict) or met.get("verdict") != "MET":
        return "the approval cites no MET pre-check verdict"
    if met.get("declaration_digest") != PRECHECK_DIGEST:
        return "the cited pre-check is not this pre-check declaration"
    sha = met.get("report_sha256")
    if not (isinstance(sha, str) and sha.startswith("sha256:") and len(sha) == 71):
        return "the cited pre-check report has no sha256"
    return None


def test_a_pilot_approval_must_cite_a_met_precheck() -> None:
    """Counter-model review (HIGH): the runner does not read `precondition`, so
    the MET-only rule is enforced where an approval enters the repository: a
    committed pilot approval must cite the pre-check report it was given after,
    by digest, with the evaluator's MET. Inert until an approval is stamped."""
    approval = _json(PILOT).get("approval")
    if approval is not None:
        assert _pilot_approval_problem(approval) is None


@pytest.mark.parametrize("approval", [
    {"by": "owner"},
    {"by": "owner", "precheck": {"verdict": "NOT_MET", "declaration_digest": PRECHECK_DIGEST,
                                 "report_sha256": "sha256:" + "0" * 64}},
    {"by": "owner", "precheck": {"verdict": "MET", "declaration_digest": PILOT_DIGEST,
                                 "report_sha256": "sha256:" + "0" * 64}},
    {"by": "owner", "precheck": {"verdict": "MET", "declaration_digest": PRECHECK_DIGEST}},
])
def test_the_pilot_approval_tripwire_can_fail(approval: dict[str, Any]) -> None:
    assert _pilot_approval_problem(approval) is not None
    good = {"by": "owner", "precheck": {"verdict": "MET", "declaration_digest": PRECHECK_DIGEST,
                                        "report_sha256": "sha256:" + "0" * 64}}
    assert _pilot_approval_problem(good) is None


def test_the_rehearsal_stamp_never_reaches_a_committed_declaration() -> None:
    for path in (PRECHECK, PILOT):
        assert "REHEARSAL" not in path.read_text(encoding="utf-8")
    assert _json(PRECHECK).get("approval") is None and _json(PILOT).get("approval") is None
