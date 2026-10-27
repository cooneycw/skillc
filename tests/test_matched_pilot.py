"""The matched pilot's no-run deliverables (#12): the predeclared experiment
plans through the real controller, and the committed run manifest's numbers
are exactly what the SAME estimator #26 uses computes - never a hand-typed
number, and never a second estimator forked for this issue.

No paid model call happens anywhere in this file (ADR 0005 rule 5, the cost
stop): `trial.plan()` only ever writes a ledger to a throwaway store.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from skillc import cost_estimate as ce
from skillc import trial as t

ROOT = Path(__file__).resolve().parent.parent
PILOT_DIR = ROOT / "evals" / "matched-pilot"
MANIFEST = json.loads((PILOT_DIR / "run-manifest.json").read_text(encoding="utf-8"))
RECORD = MANIFEST["predeclared_experiment_record"]

_BASE_GRADER = json.loads((ROOT / RECORD["goal_population"]["task"]["grader"]).read_text(encoding="utf-8"))

_TREATMENT_SUBJECT_DIGEST = json.loads(
    (ROOT / "evals" / "subjects" / "cpp-codex" / "evidence" / "records" / "receipt.json").read_text(encoding="utf-8")
)["subject"]["digest"]

#: No baseline materialization has ever run for this pilot (an empty home
#: installs nothing, so there is no receipt to read a real digest from), and
#: the image digest is explicitly owed to the live build - see
#: `predeclared_experiment_record.image_digest_note`. Both are named
#: placeholders, never a value shaped like a real one (issue #10 lesson D13).
_BASELINE_SUBJECT_DIGEST = "sha256:0000000000000000000000000000000000000000000000000000000000baseline"

_PRICE = ce.ModelPrice(
    name=MANIFEST["cost_estimate"]["price"]["name"],
    input_usd_per_million=MANIFEST["cost_estimate"]["price"]["input_usd_per_million"],
    output_usd_per_million=MANIFEST["cost_estimate"]["price"]["output_usd_per_million"],
    source=MANIFEST["cost_estimate"]["price"]["source"],
)
_ASSUMED_INPUT_TOKENS_PER_ATTEMPT = MANIFEST["cost_estimate"]["assumptions"]["estimated_input_tokens_per_attempt"]
_ASSUMED_OUTPUT_TOKENS_PER_ATTEMPT = MANIFEST["cost_estimate"]["assumptions"]["estimated_output_tokens_per_attempt"]

_ARMS = ("treatment", "baseline")
_REPEATS_PER_ARM = MANIFEST["cost_estimate"]["repeats_per_arm"]


def _plan_spec() -> dict[str, object]:
    """Iterates repeat-then-arm, not arm-then-repeat: the predeclared
    `arm_order` states "treatment then baseline, PER REPEAT" (interleaved),
    which an arm-outer loop would instead plan as two separate temporal
    blocks (all treatment, then all baseline) - a mismatch between the
    predeclared schedule and the actual plan found by cross-model review."""
    trials = []
    for repeat in range(1, _REPEATS_PER_ARM + 1):
        for arm in _ARMS:
            trials.append({
                "label": f"matched_pilot_{arm}_{repeat}",
                "case": {"id": "matched-pilot", "revision": "c1"},
                "grader": {"id": _BASE_GRADER["id"], "revision": _BASE_GRADER["revision"]},
                "subject": {"digest": _TREATMENT_SUBJECT_DIGEST if arm == "treatment" else _BASELINE_SUBJECT_DIGEST},
                "client": {"name": RECORD["client"]["name"], "version": RECORD["client"]["version"]},
                "image": {"digest": RECORD["image_digest"]},
                "config": {"arm": arm, "repeat": repeat},
                "attempts": MANIFEST["cost_estimate"]["attempts_per_trial"],
            })
    return {"experiment": "matched-pilot", "trials": trials}


def test_the_matched_pilot_plans_through_the_real_controller(tmp_path: Path) -> None:
    """No paid call, no live agent - just the ledger the controller would
    issue before anything runs, for both arms across every repeat."""
    store = t.open_store(tmp_path / "store", forbidden=[])
    experiment = t.plan(_plan_spec(), store)
    trials = experiment.ledger["trials"]
    assert isinstance(trials, list)
    assert len(trials) == len(_ARMS) * _REPEATS_PER_ARM == MANIFEST["cost_estimate"]["total_attempts"]
    treatment_count = 0
    baseline_count = 0
    for trial in trials:
        assert isinstance(trial, dict)
        assert len(trial["attempts"]) == MANIFEST["cost_estimate"]["attempts_per_trial"]
        digest = trial["subject"]["digest"]
        if digest == _TREATMENT_SUBJECT_DIGEST:
            treatment_count += 1
        elif digest == _BASELINE_SUBJECT_DIGEST:
            baseline_count += 1
    assert treatment_count == _REPEATS_PER_ARM
    assert baseline_count == _REPEATS_PER_ARM


def test_the_planned_order_matches_the_predeclared_arm_order(tmp_path: Path) -> None:
    """Red case from cross-model review: the predeclared 'treatment then
    baseline, per repeat' order must be the ACTUAL planned sequence -
    interleaved (T,B,T,B,...), never two separate blocks (all treatment then
    all baseline)."""
    assert RECORD["arm_order"].startswith("treatment then baseline, per repeat")
    store = t.open_store(tmp_path / "store", forbidden=[])
    experiment = t.plan(_plan_spec(), store)
    trials = experiment.ledger["trials"]
    assert isinstance(trials, list)
    actual_order = [
        "treatment" if trial["subject"]["digest"] == _TREATMENT_SUBJECT_DIGEST else "baseline"
        for trial in trials
    ]
    expected_order = list(_ARMS) * _REPEATS_PER_ARM
    assert actual_order == expected_order


def test_the_committed_cost_estimate_matches_what_the_code_computes() -> None:
    """The run manifest's numbers are not hand-typed, and are produced by
    the SAME `skillc.cost_estimate` module #26 uses - no second estimator."""
    total_attempts = MANIFEST["cost_estimate"]["total_attempts"]
    cost = ce.estimate(
        trials=total_attempts,
        attempts_per_trial=1,
        estimated_input_tokens_per_attempt=_ASSUMED_INPUT_TOKENS_PER_ATTEMPT,
        estimated_output_tokens_per_attempt=_ASSUMED_OUTPUT_TOKENS_PER_ATTEMPT,
        price=_PRICE,
    )
    manifest_cost = MANIFEST["cost_estimate"]
    assert cost.total_attempts == manifest_cost["total_attempts"]
    assert manifest_cost["price"]["input_usd_per_million"] == _PRICE.input_usd_per_million
    assert manifest_cost["price"]["output_usd_per_million"] == _PRICE.output_usd_per_million
    assert manifest_cost["assumptions"]["estimated_input_tokens_per_attempt"] == _ASSUMED_INPUT_TOKENS_PER_ATTEMPT
    assert manifest_cost["assumptions"]["estimated_output_tokens_per_attempt"] == _ASSUMED_OUTPUT_TOKENS_PER_ATTEMPT
    # ADR 0005 rule 6: relabelled as a quota/usage figure, not a dollar charge
    # (this pilot's agent attempts run under the operator's normal Codex
    # subscription login) - still the exact number `estimate()` computes.
    assert cost.estimated_usd == manifest_cost["estimated_agent_quota_usd_equivalent"]
    assert manifest_cost["judge_estimated_quota_usd_equivalent"] == 0.0
    assert cost.judge_estimated_usd == 0.0


def _committed_estimate() -> ce.RunCostEstimate:
    return ce.estimate(
        trials=MANIFEST["cost_estimate"]["total_attempts"],
        attempts_per_trial=1,
        estimated_input_tokens_per_attempt=_ASSUMED_INPUT_TOKENS_PER_ATTEMPT,
        estimated_output_tokens_per_attempt=_ASSUMED_OUTPUT_TOKENS_PER_ATTEMPT,
        price=_PRICE,
    )


def test_the_judge_spend_is_within_the_operator_ceiling() -> None:
    """Operator ruling (ADR 0005 rule 6, carried into #12): dollar-metered
    JUDGE spend must stay under $5 - this pilot's agent-attempt quota is not
    dollar-metered (subscription login) and is never checked against this
    ceiling (Codex code-review finding: an earlier version of this test
    checked the combined total, which would have wrongly rejected a future
    manifest whose agent quota grew large with $0 judge spend). If judge
    spend ever exceeds the ceiling, report to the orchestrator and do not
    shrink the population to fit - never silently accept it."""
    assert _committed_estimate().judge_estimated_usd <= ce.CEILING_USD
    assert MANIFEST["predeclared_experiment_record"]["monetary_ceiling_usd"] == ce.CEILING_USD


def test_a_large_agent_quota_alone_does_not_breach_the_ceiling() -> None:
    """Red case for the fix above: an agent-only figure well over $5 must
    still authorize in subscription mode, because the ceiling gates judge
    spend alone. The pre-fix combined-total check would have rejected this."""
    huge_agent_only = ce.estimate(
        trials=MANIFEST["cost_estimate"]["total_attempts"], attempts_per_trial=1,
        estimated_input_tokens_per_attempt=1_000_000,
        estimated_output_tokens_per_attempt=_ASSUMED_OUTPUT_TOKENS_PER_ATTEMPT,
        price=_PRICE,
    )
    assert huge_agent_only.estimated_usd > ce.CEILING_USD, "the agent-only figure must exceed the ceiling for this control to mean anything"
    assert huge_agent_only.judge_estimated_usd == 0.0
    ce.authorize(
        huge_agent_only, approved_budget_usd=None, agent_uses_subscription_login=True,
    )  # must not raise - no judge spend to gate, however large the agent quota


def test_authorize_agrees_with_the_manifests_own_execution_state() -> None:
    """The manifest is a subscription-login run (ADR 0005 rule 6) with no
    judge tier enabled, so `authorize()` in that mode succeeds
    unconditionally - $0 of dollar-metered spend needs no budget approval.
    `execution` must agree with the committed evidence: "incomplete" while no
    report is committed, "run" once one is - never claiming a run that left
    no report, nor hiding one that did."""
    cost = _committed_estimate()
    ce.authorize(
        cost, approved_budget_usd=MANIFEST["approved_budget_usd"], agent_uses_subscription_login=True,
    )  # must not raise: no judge tier enabled, so judge spend is $0
    ran = (PILOT_DIR / "evidence" / "records" / "report.json").exists()
    assert MANIFEST["execution"].startswith("run" if ran else "incomplete")


def test_the_image_digest_is_declared_and_matches_what_ran() -> None:
    """Issue #10 lesson D13 held while no image existed: the field said
    'owed' rather than invent a digest. Declared now, it must be a real
    sha256 digest, and once evidence is committed, every trial the ledger
    planned must name that SAME image - a declaration the run did not honour
    is refused here."""
    digest = RECORD["image_digest"]
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
    ledger_path = PILOT_DIR / "evidence" / "records" / "ledger.json"
    if ledger_path.exists():
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        assert {t["image"]["digest"] for t in ledger["trials"]} == {digest}


def test_artifact_retention_was_decided_before_capture() -> None:
    retention = MANIFEST["predeclared_experiment_record"]["artifact_retention"]
    assert "before capture" in retention["decided"]
    assert "outside any git work tree" in retention["private"]


def test_goal_population_reuses_the_already_qualified_grader_not_a_new_one() -> None:
    task = RECORD["goal_population"]["task"]
    assert task["id"] == "slug-small-fix"
    assert task["id"] == _BASE_GRADER["id"]
    assert task["revision"] == _BASE_GRADER["revision"]


def test_clarification_and_approval_behavior_are_both_stated() -> None:
    behavior = RECORD["clarification_and_approval_behavior"]
    assert behavior["clarification"]
    assert behavior["approval"]


# ------------------------------------------------ the committed live evidence

_EVIDENCE = PILOT_DIR / "evidence" / "records"


def test_the_committed_evidence_accounts_for_every_scheduled_attempt() -> None:
    """The committed live bundle (#12): every rule is clean except the one
    named gap - that run predates #139 and stored no `verified-result` - and
    the tolerance for it is `matched_pilot.bundle_findings`' own, scoped to
    this one experiment. Any OTHER finding, including a report that omits an
    attempt, fails here."""
    from skillc import matched_pilot as mp

    unexpected, known = mp.bundle_findings(_EVIDENCE)
    assert unexpected == []
    ledger = json.loads((_EVIDENCE / "ledger.json").read_text(encoding="utf-8"))
    assert ledger["experiment_id"] in mp.KNOWN_GAP_EXPERIMENTS
    report = json.loads((_EVIDENCE / "report.json").read_text(encoding="utf-8"))
    assert known == len(report["attempts"]) == MANIFEST["cost_estimate"]["total_attempts"]
    assert [e["arm"] for e in report["attempts"]] == ["treatment", "baseline"] * _REPEATS_PER_ARM


def test_the_committed_report_carries_the_reviewed_claims() -> None:
    report = json.loads((_EVIDENCE / "report.json").read_text(encoding="utf-8"))
    claims = json.loads((PILOT_DIR / "evidence" / "claims.json").read_text(encoding="utf-8"))["claims"]
    assert report["claims_reviewed"] is True
    assert {e["attempt_id"]: e["claim"] for e in report["attempts"]} == claims


# -------------------------------------- #141: a new declaration, not an edit


def _current() -> dict[str, object]:
    from skillc import matched_pilot as mp

    data: dict[str, object] = json.loads(mp.CURRENT_MANIFEST_PATH.read_text(encoding="utf-8"))
    return data


def test_the_12_predeclaration_is_not_edited() -> None:
    """#12's deviation stays on the record as it happened: its declaration
    still names the model it assumed, not the one that ran."""
    assert RECORD["model"]["name"] == "gpt-5.1-codex"
    assert "reasoning_effort" not in RECORD["model"]
    assert MANIFEST["observed_at_run"]["model"] == "gpt-6-astra"


def test_the_current_declaration_is_a_new_dated_file_that_names_what_it_supersedes() -> None:
    from skillc import matched_pilot as mp

    assert mp.CURRENT_MANIFEST_PATH != mp.MANIFEST_PATH
    current = _current()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(current["declared_at"]))
    assert str(current["declared_at"]) in mp.CURRENT_MANIFEST_PATH.name
    supersedes = current["supersedes"]
    assert isinstance(supersedes, dict)
    assert (PILOT_DIR / supersedes["manifest"]).resolve() == mp.MANIFEST_PATH.resolve()
    assert "3e1e3fb" in supersedes["run"]


_CURRENT_EVIDENCE = PILOT_DIR / "evidence-2026-09-27-gpt-6-astra" / "records"


def test_the_current_declaration_s_execution_agrees_with_its_evidence() -> None:
    """`execution` says "run" exactly when the current declaration's own
    bundle is committed - never a run that left no evidence, nor evidence
    whose declaration still says it never ran."""
    ran = (_CURRENT_EVIDENCE / "report.json").exists()
    assert str(_current()["execution"]).startswith("run" if ran else "not run")


def test_the_re_run_bundle_checks_fully_clean() -> None:
    """#147's reason to exist: the re-run's bundle carries NO finding at all,
    and is not covered by the first run's scoped tolerance. The first run's
    bundle is unchanged - still exactly its 6 known findings."""
    from skillc import matched_pilot as mp

    experiment_id = mp.bundle_experiment_id(_CURRENT_EVIDENCE)
    assert experiment_id is not None
    assert experiment_id not in mp.KNOWN_GAP_EXPERIMENTS
    assert mp.bundle_findings(_CURRENT_EVIDENCE) == ([], 0)
    assert mp.bundle_experiment_id(_EVIDENCE) == "matched-pilot-6ab82dc6"
    assert mp.bundle_findings(_EVIDENCE) == ([], 6)


def test_the_re_run_ran_the_declared_model_effort_and_image_on_every_attempt() -> None:
    current = _current()
    record = current["predeclared_experiment_record"]
    assert isinstance(record, dict)
    report = json.loads((_CURRENT_EVIDENCE / "report.json").read_text(encoding="utf-8"))
    attempts = report["attempts"]
    assert len(attempts) == MANIFEST["cost_estimate"]["total_attempts"]
    for entry in attempts:
        assert entry["model_observed"] == record["model"]["name"] == "gpt-6-astra"
        assert entry["model_matches_declaration"] is True
        assert entry["reasoning_effort_observed"] == record["model"]["reasoning_effort"] == "high"
        assert entry["reasoning_effort_matches_declaration"] is True
    ledger = json.loads((_CURRENT_EVIDENCE / "ledger.json").read_text(encoding="utf-8"))
    assert {t["image"]["digest"] for t in ledger["trials"]} == {record["image_digest"]}
    assert [e["arm"] for e in attempts] == ["treatment", "baseline"] * _REPEATS_PER_ARM


def test_the_re_run_report_carries_its_reviewed_claims() -> None:
    report = json.loads((_CURRENT_EVIDENCE / "report.json").read_text(encoding="utf-8"))
    claims = json.loads(
        (_CURRENT_EVIDENCE.parent / "claims.json").read_text(encoding="utf-8"),
    )["claims"]
    assert report["claims_reviewed"] is True
    assert {e["attempt_id"]: e["claim"] for e in report["attempts"]} == claims


def test_the_current_declaration_changes_only_the_model_and_the_cap_note() -> None:
    """A re-run is a comparison with #12's run only if everything else it
    declares is the same. Only the model (now pinned, with its effort), the
    stale 'caps not yet enforced' note, and WHERE the committed evidence goes
    (#147: its own directory, so the first run's bundle is not replaced) may
    differ - nothing about what runs or how it is measured."""
    new = _current()["predeclared_experiment_record"]
    assert isinstance(new, dict)
    assert new["model"]["name"] == "gpt-6-astra"
    assert new["model"]["reasoning_effort"] == "high"
    assert "evidence-2026-09-27-gpt-6-astra/records/" in new["artifact_retention"]["committed"]
    strip = lambda record: {
        k: (
            {kk: vv for kk, vv in v.items() if kk != "note"} if k == "time_caps"
            else {kk: vv for kk, vv in v.items() if kk != "committed"} if k == "artifact_retention"
            else v
        )
        for k, v in record.items() if k != "model"
    }
    assert strip(new) == strip(RECORD)


def test_both_readmes_name_the_current_declaration() -> None:
    from skillc import matched_pilot as mp

    name = mp.CURRENT_MANIFEST_PATH.name
    for readme in (PILOT_DIR / "README.md", PILOT_DIR / "evidence" / "README.md"):
        text = readme.read_text(encoding="utf-8")
        assert f"Current declaration: [`{name}`]" in text, readme


def test_a_do_nothing_attempt_lowers_the_pass_rate_never_leaves_the_denominator() -> None:
    """#434 revision 2 (orchestrator ruling): an INCONCLUSIVE attempt is not
    passed, and stays in the arm's scheduled denominator."""
    from skillc import matched_pilot as mp

    def rate(attempts: list[dict[str, object]]) -> float:
        arms = mp.summarize({"attempts": attempts})["arms"]
        assert isinstance(arms, dict)
        arm = arms[mp.TREATMENT]
        assert isinstance(arm, dict)
        return int(str(arm["passed"])) / int(str(arm["scheduled"]))

    passing = [{"arm": mp.TREATMENT, "repeat": i, "graded_status": "PASS", "disposition": "captured"} for i in range(3)]
    do_nothing = {"arm": mp.TREATMENT, "repeat": 9, "graded_status": "INCONCLUSIVE", "disposition": "captured"}
    assert rate([*passing, do_nothing]) < rate(passing)


def test_completion_readback_joins_supplied_recovered_and_direct_reports(tmp_path: Path) -> None:
    from dataclasses import replace

    from skillc import completion
    from skillc import matched_pilot as mp
    experiment, schedule = mp.plan_pilot(mp.load_declaration(), t.open_store(tmp_path / "store", []),
                                       treatment_digest="sha256:" + "ab" * 32, image_digest=None)
    first = schedule[0]
    deadline = completion.CompletionDeadline.after(10, lambda: 0.0)
    marker = completion.mark(experiment, first.attempt_id, deadline)
    raw = {**t.finalize(experiment, first.attempt_id), "graded": {"status": "PASS"}}
    supplied = mp.AttemptOutcome(first, raw, 0.0)
    normalized = mp.reconcile(experiment, [supplied])
    assert mp.graded_status(normalized[0].record) == "UNKNOWN"
    assert mp.graded_status(mp.reconcile(experiment, [])[0].record) == "UNKNOWN"
    entries = mp.build_report(experiment, [supplied])["attempts"]
    assert isinstance(entries, list) and entries[0]["graded_status"] == "UNKNOWN"
    run = tmp_path / "run"
    run.mkdir()
    mp.write_outcomes(run, experiment, [supplied])
    _, read = mp.read_outcomes(run)
    assert mp.graded_status(read[0].record) == "UNKNOWN"
    final = {**deadline.qualify(marker, True), "publication_confirmed": True}
    experiment.record(first.attempt_id, "completion-qualified", qualification=final)
    qualified = replace(supplied, record={**raw, "completion": final})
    assert mp.graded_status(mp.reconcile(experiment, [qualified])[0].record) == "PASS"
    # Durable evidence alone cannot reconstruct missing private publication as PASS.
    assert mp.graded_status(mp.reconcile(experiment, [supplied])[0].record) == "UNKNOWN"
    copied = replace(qualified, record={**qualified.record, "attempt_id": "another-attempt"})
    assert mp.graded_status(mp.reconcile(experiment, [copied])[0].record) == "UNKNOWN"
    failed = replace(supplied, record={**raw, "graded": {"status": "FAIL"}})
    assert mp.graded_status(mp.reconcile(experiment, [failed])[0].record) == "FAIL"
    assert mp.graded_status(raw) == "PASS"  # Unopted primitive legacy interpretation.


@pytest.mark.parametrize(("versions", "expected"), [
    (["A"], "A"), (["A", "A"], "A"), (["wrong"], "wrong"),
    (["A", "B", "A"], "UNKNOWN"), ([None, "A"], "UNKNOWN"), ([], "UNKNOWN"),
])
@pytest.mark.parametrize("second_status", ["PASS", "FAIL"])
def test_548_reports_rederive_retained_bytes_without_changing_task_or_pair_facts(
    tmp_path: Path, versions: list[object], expected: str, second_status: str,
) -> None:
    import hashlib

    from skillc import agent_trial as at
    from skillc import matched_pilot as mp

    spec = _plan_spec()
    trials = spec["trials"]
    assert isinstance(trials, list)
    trials = trials[:2]
    trials[0]["client"] = {"name": "codex", "version": "declared-one"}
    trials[1]["client"] = {"name": "claude", "version": "declared-two"}
    experiment = t.plan({**spec, "trials": trials}, t.open_store(tmp_path / "store", []))
    schedule = mp.schedule_from_ledger(experiment)
    records: list[dict[str, object]] = [{"disposition": "captured", "observation": {"transcript_client_version": "legacy",
                "run_metadata": {"cli_version": "legacy", "model": "model"}}, "graded": {"status": "PASS"}},
               {"disposition": "captured", "observation": {"run_metadata": {"model": "model"}},
                "graded": {"status": second_status}}]
    outcomes = [mp.AttemptOutcome(s, r, 1.0) for s, r in zip(schedule, records, strict=True)]
    # Equal old first/last scalars cannot certify even matching-wrong-matching.
    assert mp.build_report(experiment, outcomes)["attempts"][0]["cli_version_observed"] == "UNKNOWN"  # type: ignore[index]
    for s, name in zip(schedule, ("codex", "claude"), strict=True):
        rows = [{"type": "session_meta", "payload": {"cli_version": v}} if name == "codex"
                else {"type": "system", "version": v} for v in versions]
        t.retain_transcript(experiment, s.attempt_id, t.TranscriptEvidence(("\n".join(map(json.dumps, rows)) + "\n").encode()))
        t.begin_prompt_inputs(experiment, s.attempt_id, 0)
        t.retain_prompt_input(experiment, s.attempt_id, 1, "exact private instruction", at.transcript_leak_findings)
        t.finish_prompt_inputs(experiment, s.attempt_id, [1], "declared-complete")
        experiment.record(s.attempt_id, "started")
        experiment.record(s.attempt_id, "stopped")
    before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in experiment.root.rglob("*") if p.is_file()}
    report = mp.build_report(experiment, outcomes, declared_model="model")
    entries = report["attempts"]
    assert isinstance(entries, list)
    assert [e["cli_version_observed"] for e in entries] == [expected, expected]
    assert [e["client_declared"] for e in entries] == [t["client"] for t in trials]
    assert [e["graded_status"] for e in entries] == ["PASS", second_status]
    assert all(e["model_eligible"] is True for e in entries)
    assert all(t.read_prompt_inputs(experiment, s.attempt_id).inputs[0].data == b"exact private instruction" for s in schedule)
    assert {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in experiment.root.rglob("*") if p.is_file()} == before
    assert mp.summarize(report)["arms"][mp.TREATMENT]["passed"] == 1  # type: ignore[index]
    assert len(mp.summarize(report)["matched_successful_pairs"]) == (1 if second_status == "PASS" else 0)  # type: ignore[arg-type]


def _548_manifest(experiment: t.Experiment, aid: str, entry: dict[str, object]) -> dict[str, object]:
    """A complete valid captured-manifest baseline, without a retention journal."""
    from skillc import checks, records

    artifact = b"synthetic captured output"
    manifest = {
        "version": 2, "kind": records.ARTIFACT_MANIFEST, "producer": "controller",
        "attempt_id": aid, "trial_id": experiment.trial_of(aid)["trial_id"], "captured": "2026-10-27T00:00:00Z",
        "artifacts": [{"path": "result.txt", "type": "file", "size": len(artifact),
                       "digest": t.put_object(experiment, artifact), "mode": "-"}],
        "exclusions": [], "capture_failures": [],
        "observations": [{"stream": stream, "origin": "observed", "coverage": "unsupported", "attempt_id": aid,
                          "reason": "not supplied by the synthetic fixture"} for stream in records.REQUIRED_OBSERVATIONS]
                        + [entry],
    }
    assert not list(checks.run_record(records.Record(Path("manifest.json"), manifest)))
    return manifest


@pytest.mark.parametrize(("scope", "key", "value"), [
    ("manifest", "attempt_id", "other-attempt"), ("manifest", "attempt_id", None),
    ("manifest", "trial_id", "other-trial"), ("manifest", "trial_id", None),
    ("manifest", "version", 1), ("manifest", "kind", "agent-observation"),
    ("manifest", "producer", "assembler"), ("entry", "attempt_id", "other-attempt"),
    ("entry", "attempt_id", None), ("entry", "origin", "observed"), ("entry", "origin", None),
    ("entry", "ref", "objects/other"), ("entry", "ref", None), ("entry", "size", None),
    ("entry", "size", True), ("entry", "size", -1), ("entry", "size", 1.5), ("entry", "size", 1),
    ("entry", "size", "same-length-float"),
])
def test_548_legacy_manifest_version_requires_this_attempts_valid_binding(
    tmp_path: Path, scope: str, key: str, value: object,
) -> None:
    from skillc import agent_trial as at
    from skillc import matched_pilot as mp

    experiment = t.plan(_plan_spec(), t.open_store(tmp_path / "store", []))
    aid = mp.schedule_from_ledger(experiment)[0].attempt_id
    raw = b'{"type":"session_meta","payload":{"cli_version":"A"}}\n'
    digest = t.put_object(experiment, raw)
    entry: dict[str, object] = {"stream": "client-transcript", "origin": "client-reported", "coverage": "complete",
                                "attempt_id": aid, "digest": digest, "ref": "objects/" + digest[7:], "size": len(raw)}
    manifest = _548_manifest(experiment, aid, entry)
    path = experiment.root / f"manifest-{aid}.json"
    path.write_text(json.dumps(manifest))
    assert t.read_retained_transcript(experiment, aid) is None
    assert at.retained_client_version(experiment, aid) == "A", "the full valid legacy baseline must be healthy"
    target = entry if scope == "entry" else manifest
    if value is None:
        target.pop(key)
    else:
        target[key] = float(len(raw)) if value == "same-length-float" else value
    path.write_text(json.dumps(manifest))
    assert at.retained_client_version(experiment, aid) is None


@pytest.mark.parametrize("source", ["legacy", "journal", "both"])
def test_548_valid_legacy_and_failure_retention_remain_readable(tmp_path: Path, source: str) -> None:
    from skillc import agent_trial as at
    from skillc import matched_pilot as mp

    experiment = t.plan(_plan_spec(), t.open_store(tmp_path / "store", []))
    aid = mp.schedule_from_ledger(experiment)[0].attempt_id
    raw = b'{"type":"session_meta","payload":{"cli_version":"A"}}\n'
    digest = t.put_object(experiment, raw)
    if source in ("journal", "both"):
        t.retain_transcript(experiment, aid, t.TranscriptEvidence(raw))
    if source in ("legacy", "both"):
        entry = {"stream": "client-transcript", "origin": "client-reported", "coverage": "complete",
                 "attempt_id": aid, "digest": digest, "ref": "objects/" + digest[7:], "size": len(raw)}
        manifest = _548_manifest(experiment, aid, entry)
        (experiment.root / f"manifest-{aid}.json").write_text(json.dumps(manifest))
    assert at.retained_client_version(experiment, aid) == "A"


@pytest.mark.parametrize("member", ["observations", "attempt_id", "trial_id", "hidden-stream", "journal:observation", "journal:event", "journal:entry",
                                   *["entry:" + key for key in ("attempt_id", "stream", "origin", "coverage", "ref", "digest", "size")]])
def test_548_serialized_binding_members_cannot_hide_a_population(tmp_path: Path, member: str) -> None:
    from skillc import agent_trial as at
    from skillc import matched_pilot as mp

    def encoded(value: object) -> str:
        return json.dumps(value, separators=(",", ":"))

    def duplicate(raw: str, key: str, value: object) -> str:
        field = encoded(key) + ":" + encoded(value)
        assert field in raw
        return raw.replace(field, field + "," + field, 1)

    experiment = t.plan(_plan_spec(), t.open_store(tmp_path / "store", []))
    aid = mp.schedule_from_ledger(experiment)[0].attempt_id
    raw = b'{"type":"session_meta","payload":{"cli_version":"A"}}\n'
    digest = t.put_object(experiment, raw)
    entry: dict[str, object] = {"stream": "client-transcript", "origin": "client-reported", "coverage": "complete",
                                "attempt_id": aid, "digest": digest, "ref": "objects/" + digest[7:], "size": len(raw)}
    prefix = ""
    if member.startswith("journal:"):
        t.retain_transcript(experiment, aid, t.TranscriptEvidence(raw))
        path = experiment.journal(aid)
        lines = path.read_text().splitlines()
        prefix = "\n".join(lines[:-1]) + "\n"
        data = json.loads(lines[-1])
    else:
        path = experiment.root / f"manifest-{aid}.json"
        data = _548_manifest(experiment, aid, entry)
        if member == "hidden-stream":
            t.retain_transcript(experiment, aid, t.TranscriptEvidence(raw))
    serialized = encoded(data)
    path.write_text(prefix + serialized + "\n")
    assert at.retained_client_version(experiment, aid) == "A"
    if member == "hidden-stream":
        serialized = serialized.replace('"stream":"client-transcript"', '"stream":"client-transcript","stream":"other"')
    elif member.startswith("entry:"):
        key = member.split(":")[1]
        serialized = serialized.replace(encoded(entry), duplicate(encoded(entry), key, entry[key]))
    elif member.startswith("journal:"):
        key = member.split(":")[1]
        if key == "entry":
            observed = data["observation"]
            serialized = serialized.replace(encoded(observed), duplicate(encoded(observed), "attempt_id", aid))
        else:
            serialized = duplicate(serialized, key, data[key])
    elif member == "observations":
        other = {**entry, "digest": t.put_object(experiment, raw.replace(b'"A"', b'"B"'))}
        other["ref"] = "objects/" + str(other["digest"])[7:]
        alternative = _548_manifest(experiment, aid, other)
        serialized = serialized.replace('"observations":', '"observations":' + encoded(alternative["observations"]) + ',"observations":', 1)
    else:
        serialized = duplicate(serialized, member, data[member])
    path.write_text(prefix + serialized + "\n")
    assert at.retained_client_version(experiment, aid) is None


@pytest.mark.parametrize("damage", ["partial", "tampered", "nonutf8", "unknown-client", "ambiguous", "conflicting", "malformed"])
def test_548_report_retention_damage_is_unknown_not_a_task_failure(tmp_path: Path, damage: str) -> None:
    from skillc import agent_trial as at
    from skillc import matched_pilot as mp

    spec = _plan_spec()
    if damage == "unknown-client":
        spec["trials"][0]["client"] = {"name": "scripted", "version": "A"}  # type: ignore[index]
    experiment = t.plan(spec, t.open_store(tmp_path / "store", []))
    aid = mp.schedule_from_ledger(experiment)[0].attempt_id
    raw = b'{"type":"session_meta","payload":{"cli_version":"A"}}\n'
    entry = t.retain_transcript(experiment, aid, t.TranscriptEvidence(b"\xff" if damage == "nonutf8" else raw),
                                limits=t.Limits(max_stream_bytes=3) if damage == "partial" else None)
    if damage == "tampered":
        path = experiment.object_path(str(entry["digest"]))
        path.chmod(0o600)
        path.write_bytes(b"altered")
    if damage in ("ambiguous", "conflicting"):
        manifest = _548_manifest(experiment, aid, entry)
        entries = manifest["observations"]
        assert isinstance(entries, list)
        if damage == "ambiguous":
            entries.append(dict(entry))
        else:
            digest = t.put_object(experiment, raw.replace(b'"A"', b'"B"'))
            entries[-1] = {**entry, "digest": digest, "ref": "objects/" + digest[7:]}
        (experiment.root / f"manifest-{aid}.json").write_text(json.dumps(manifest))
    if damage == "malformed":
        manifest = _548_manifest(experiment, aid, entry)
        manifest["observations"] = entry
        (experiment.root / f"manifest-{aid}.json").write_text(json.dumps(manifest))
    assert at.retained_client_version(experiment, aid) is None
