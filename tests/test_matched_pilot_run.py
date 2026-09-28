"""Tests for skillc/matched_pilot.py (issue #12): the predeclared schedule
runs, every scheduled attempt is reported, the caps are enforced, and
nothing unmeasured is filled in.

Every agent attempt here runs against the fake `docker` CLI
(`tests/fixtures/docker-backend/fake_docker.py`) and the scripted fake client
(`tests/fixtures/agent-trial/fake_agent_client.py`) - no real daemon, no real
`codex`, no model call. The live run is the operator's, recorded under
`evals/matched-pilot/evidence/`.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from collections.abc import Sequence
from pathlib import Path

import pytest
from fixtures.leak_seeds.judge_seeds import HOME_PATH_LEAK

from skillc import cli, trial
from skillc import collection_conformance as cc
from skillc import docker_backend as d
from skillc import matched_pilot as mp
from skillc.lifecycle import RealAgentBlocked

FAKE_DOCKER = Path(__file__).resolve().parent / "fixtures" / "docker-backend" / "fake_docker.py"
FAKE_CLIENT = Path(__file__).resolve().parent / "fixtures" / "agent-trial" / "fake_agent_client.py"
REFERENCE = Path(__file__).resolve().parent.parent / "evals" / "level1" / "slug-small-fix" / "reference"

TREATMENT_FILES = {".codex/skills/tdd/SKILL.md": b"---\nname: tdd\ndescription: A test skill.\n---\nBody.\n"}
TREATMENT_DIGEST = "sha256:" + "ab" * 32


def _docker_bin(state_dir: Path) -> list[str]:
    return [sys.executable, str(FAKE_DOCKER), "--state", str(state_dir)]


def _fresh_codex_credential(tmp_path: Path) -> Path:
    def seg(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()
    token = f"{seg(json.dumps({'alg': 'none'}).encode())}.{seg(json.dumps({'exp': int(time.time() + 3600)}).encode())}.sig"
    path = tmp_path / "codex-credential.json"
    path.write_text(json.dumps({"tokens": {"access_token": token}}))
    return path


def _entries(report: dict[str, object]) -> list[dict[str, object]]:
    attempts = report["attempts"]
    assert isinstance(attempts, list)
    return attempts


def _run_fake_pilot(
    tmp_path: Path, *, solve_arms: Sequence[str] = (mp.TREATMENT,), total_seconds: float | None = None,
    client_extra: Sequence[str] = (),
) -> tuple[trial.Experiment, list[mp.AttemptOutcome], Path]:
    """The whole pilot against the fake docker CLI and the scripted client.
    `run_pilot` appends the declared `-m`/effort to the argv below, and the
    fake client records them in a codex `turn_context` - so the observed
    model is whatever REACHED the client. `client_extra` scripts a client
    that ignores the pin (`--observed-model`) or records none."""
    declaration = mp.load_declaration()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    docker_state = tmp_path / "docker-state"
    credential_path = _fresh_codex_credential(tmp_path)

    def backends() -> tuple[object, object]:
        make = lambda: d.DockerBackend(image="fake-image:1", base_dir=run_dir, docker_bin=_docker_bin(docker_state))
        return make(), make()

    def argv_for(scheduled: mp.ScheduledAttempt) -> list[str]:
        home = docker_state / f"{d._container_name(scheduled.attempt_id)}.fsroot" / "home" / "candidate"
        argv = [
            sys.executable, str(FAKE_CLIENT), "--format", "codex-fake", "--home", str(home),
            "--transcript-relpath", f".codex/sessions/2026/01/01/rollout-{scheduled.attempt_id}.jsonl",
        ]
        if scheduled.arm in solve_arms:
            argv.extend(["--copy-solution", str(REFERENCE)])
        argv.extend(client_extra)
        return argv

    experiment, outcomes = mp.run_pilot(
        declaration, run_dir=run_dir, treatment_home_files=TREATMENT_FILES,
        treatment_digest=TREATMENT_DIGEST, image_digest="sha256:" + "cd" * 32,
        backends=backends, argv_for=argv_for, credential_explicit_path=credential_path,
        total_seconds=total_seconds,
    )
    return experiment, outcomes, run_dir


# ------------------------------------------------------------ the green


def test_the_whole_schedule_runs_interleaved_and_every_attempt_is_reported(tmp_path: Path) -> None:
    experiment, outcomes, run_dir = _run_fake_pilot(tmp_path)

    assert [o.scheduled.arm for o in outcomes] == [mp.TREATMENT, mp.BASELINE] * 3
    assert [o.scheduled.repeat for o in outcomes] == [1, 1, 2, 2, 3, 3]
    assert all(o.record["disposition"] == "captured" for o in outcomes)
    statuses = [mp.graded_status(o.record) for o in outcomes]
    assert statuses == ["PASS", "FAIL"] * 3  # only the treatment's fake client copies the solution

    report = mp.build_report(experiment, outcomes)
    evidence = tmp_path / "evidence"
    mp.export_bundle(experiment, report, evidence)
    unexpected, known = mp.bundle_findings(evidence)
    assert unexpected == []
    assert known == 0  # #139: every captured attempt now stores its verified-result
    assert len(_entries(report)) == 6
    results = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(evidence.glob("result-*.json"))]
    assert len(results) == 6 and len(list(evidence.glob("observation-*.json"))) == 6
    by_attempt = {r["attempt_id"]: r for r in results}
    for outcome in outcomes:
        stored = by_attempt[outcome.scheduled.attempt_id]
        assert stored["verification"]["readiness_source"] == "agent-observation"
        # Readiness is UNKNOWN on the agent path (B1): a task PASS stores as
        # INCONCLUSIVE, a task FAIL still stores as FAIL (VIOLATED wins).
        want = "INCONCLUSIVE" if mp.graded_status(outcome.record) == "PASS" else "FAIL"
        assert stored["status"] == want

    # Resumable from the private record alone, and identical.
    reloaded_experiment, reloaded = mp.read_outcomes(run_dir)
    assert mp.build_report(reloaded_experiment, reloaded) == report


def test_the_known_gap_is_tolerated_only_for_the_pre_fix_run(tmp_path: Path) -> None:
    """#139: the committed #12 bundle predates stored results, and only its own
    experiment keeps the tolerance. The same bundle under any other experiment
    id - a later run that somehow stored no results - refuses publication."""
    committed = mp.EVIDENCE_DIR
    unexpected, known = mp.bundle_findings(committed)
    assert unexpected == [] and known == 6

    copy = tmp_path / "later-run"
    copy.mkdir()
    for source in committed.iterdir():
        (copy / source.name).write_bytes(source.read_bytes())
    ledger = json.loads((copy / "ledger.json").read_text(encoding="utf-8"))
    ledger["experiment_id"] = "matched-pilot-later"
    (copy / "ledger.json").write_text(json.dumps(ledger), encoding="utf-8")
    unexpected, known = mp.bundle_findings(copy)
    assert known == 0
    assert len([u for u in unexpected if mp.KNOWN_GAP_TEXT in u]) == 6


def _copy_committed(into: Path, experiment_id: object = None) -> Path:
    into.mkdir(parents=True)
    for source in mp.EVIDENCE_DIR.iterdir():
        (into / source.name).write_bytes(source.read_bytes())
    if experiment_id is not None:
        ledger = json.loads((into / "ledger.json").read_text(encoding="utf-8"))
        ledger["experiment_id"] = experiment_id
        (into / "ledger.json").write_text(json.dumps(ledger), encoding="utf-8")
    return into


def test_a_clean_neighbouring_bundle_does_not_change_the_pre_fix_reading(tmp_path: Path) -> None:
    """Codex review, red before the fix: the tolerance was decided over every
    bundle at once, so adding a clean later bundle beside the historical one
    turned its six tolerated findings into unexpected ones."""
    _copy_committed(tmp_path / "root" / "historical")
    (tmp_path / "fresh").mkdir()
    experiment, outcomes, _ = _run_fake_pilot(tmp_path / "fresh")
    mp.export_bundle(experiment, mp.build_report(experiment, outcomes), tmp_path / "root" / "later")
    unexpected, known = mp.bundle_findings(tmp_path / "root")
    assert unexpected == [] and known == 6


@pytest.mark.parametrize("experiment_id", [["matched-pilot-6ab82dc6"], {"id": "x"}])
def test_a_malformed_experiment_id_is_a_finding_not_a_crash(experiment_id: object, tmp_path: Path) -> None:
    unexpected, known = mp.bundle_findings(_copy_committed(tmp_path / "bad", experiment_id))
    assert known == 0 and unexpected


def test_time_split_sums_and_agent_time_comes_from_the_journal(tmp_path: Path) -> None:
    experiment, outcomes, _ = _run_fake_pilot(tmp_path)
    report = mp.build_report(experiment, outcomes)
    for entry in _entries(report):
        split = entry["time_seconds"]
        assert isinstance(split, dict)
        assert all(isinstance(split[k], (int, float)) for k in ("setup", "agent", "grading", "total"))
        assert abs(split["setup"] + split["agent"] + split["grading"] - split["total"]) < 1e-6
        assert split["grading"] > 0  # every attempt was graded, and grading was timed


# -------------------------------------------------------- nothing invented


def test_unmeasured_values_are_unknown_never_invented(tmp_path: Path) -> None:
    """The fake client writes no turn_context or token_count, and no claims
    file was given: the report must say UNKNOWN for all of it - never the
    manifest's assumed model, never a zero cost."""
    experiment, outcomes, _ = _run_fake_pilot(tmp_path, client_extra=("--no-turn-context",))
    report = mp.build_report(experiment, outcomes)
    for entry in _entries(report):
        assert entry["model_observed"] == mp.UNKNOWN
        assert entry["tokens"] == mp.UNKNOWN
        cost = entry["cost_usd"]
        assert isinstance(cost, dict)
        assert cost["agent"] == mp.UNKNOWN
        assert cost["total"] == mp.UNKNOWN
        assert entry["claim"] == mp.UNKNOWN
        assert entry["claim_accurate"] == mp.UNKNOWN
    assert report["claims_reviewed"] is False


def test_baseline_installs_nothing_and_treatment_installs_the_collection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Red case for the arms being the SAME path: the only difference
    between them must be what is installed."""
    seen: list[tuple[str, dict[str, bytes]]] = []
    real = cc.run_level1_agent_attempt

    def spy(**kwargs: object) -> dict[str, object]:
        seen.append((str(kwargs["attempt_id"]), dict(kwargs["extra_home_files"])))  # type: ignore[call-overload]
        return real(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(cc, "run_level1_agent_attempt", spy)
    _, outcomes, _ = _run_fake_pilot(tmp_path)
    by_id = {o.scheduled.attempt_id: o.scheduled.arm for o in outcomes}
    assert len(seen) == 6
    for attempt_id, files in seen:
        assert files == (TREATMENT_FILES if by_id[attempt_id] == mp.TREATMENT else {})


# ----------------------------------------------------------- caps and faults


def _fake_schedule(tmp_path: Path) -> tuple[trial.Experiment, list[mp.ScheduledAttempt]]:
    store = trial.open_store(tmp_path / "store", forbidden=[])
    return mp.plan_pilot(mp.load_declaration(), store, treatment_digest=TREATMENT_DIGEST, image_digest=None)


def test_total_cap_cuts_later_attempts_to_not_run_and_still_reports_them(tmp_path: Path) -> None:
    experiment, schedule = _fake_schedule(tmp_path)
    now = [0.0]

    def run_attempt(scheduled: mp.ScheduledAttempt, budget: float) -> dict[str, object]:
        now[0] += 1000
        return trial.finalize(experiment, scheduled.attempt_id, disposition="unavailable", reason="fake attempt")

    outcomes = mp.run_schedule(experiment, schedule, run_attempt, total_seconds=1500, per_attempt_seconds=900, clock=lambda: now[0])
    dispositions = [o.record["disposition"] for o in outcomes]
    assert dispositions == ["unavailable", "unavailable", "not-run", "not-run", "not-run", "not-run"]
    assert all("total time cap" in str(o.runner_note) for o in outcomes[2:])

    report = mp.build_report(experiment, outcomes)
    evidence = tmp_path / "evidence"
    mp.export_bundle(experiment, report, evidence)
    assert mp.bundle_findings(evidence) == ([], 0)
    for entry in _entries(report)[2:]:
        assert entry["time_seconds"] == {"setup": 0, "agent": 0, "grading": 0, "total": 0}


def test_a_report_that_omits_a_scheduled_attempt_is_refused(tmp_path: Path) -> None:
    """The negative control for the exported bundle: drop one attempt and
    `ledger_binding` must say so - otherwise the green above proves nothing."""
    experiment, schedule = _fake_schedule(tmp_path)
    outcomes = mp.run_schedule(
        experiment, schedule,
        lambda s, _b: trial.finalize(experiment, s.attempt_id, disposition="unavailable", reason="fake"),
        total_seconds=10_000, per_attempt_seconds=900,
    )
    report = mp.build_report(experiment, outcomes[:-1])
    evidence = tmp_path / "evidence"
    mp.export_bundle(experiment, report, evidence)
    unexpected, _ = mp.bundle_findings(evidence)
    assert any(f.startswith("ledger-binding") and "omits scheduled attempt" in f for f in unexpected)


def test_a_crashing_attempt_is_inconclusive_and_the_schedule_continues(tmp_path: Path) -> None:
    experiment, schedule = _fake_schedule(tmp_path)
    calls: list[str] = []

    def run_attempt(scheduled: mp.ScheduledAttempt, budget: float) -> dict[str, object]:
        calls.append(scheduled.attempt_id)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return trial.finalize(experiment, scheduled.attempt_id, disposition="unavailable", reason="fake")

    outcomes = mp.run_schedule(experiment, schedule, run_attempt, total_seconds=10_000, per_attempt_seconds=900)
    assert len(calls) == 6
    # Raised before dispatch: a never-started attempt may only be `unavailable`.
    assert outcomes[0].record["disposition"] == "unavailable"
    assert "RuntimeError: boom" in str(outcomes[0].record["reason"])
    assert "RuntimeError: boom" in str(outcomes[0].runner_note)


def test_no_real_agent_without_the_opt_in_aborts_the_whole_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real `codex` argv without SKILLC_ALLOW_REAL_AGENT=1 must abort -
    never six 'inconclusive' attempts that read like a pilot."""
    monkeypatch.delenv("SKILLC_ALLOW_REAL_AGENT", raising=False)
    declaration = mp.load_declaration()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    docker_state = tmp_path / "docker-state"

    def backends() -> tuple[object, object]:
        make = lambda: d.DockerBackend(image="fake-image:1", base_dir=run_dir, docker_bin=_docker_bin(docker_state))
        return make(), make()

    with pytest.raises(RealAgentBlocked):
        mp.run_pilot(
            declaration, run_dir=run_dir, treatment_home_files={}, treatment_digest=TREATMENT_DIGEST,
            image_digest=None, backends=backends, argv_for=lambda _s: list(cc.DEFAULT_CLIENT_ARGV),
        )


# ------------------------------------------------------------------ claims


@pytest.mark.parametrize(("claim", "status", "expected"), [
    ("claimed-success", "PASS", True),
    ("claimed-success", "FAIL", False),
    ("claimed-failure", "FAIL", True),
    ("claimed-failure", "PASS", False),
    ("no-claim", "PASS", "n/a"),
    ("claimed-success", None, mp.UNKNOWN),
    (mp.UNKNOWN, "PASS", mp.UNKNOWN),
])
def test_claim_accuracy(claim: str, status: str | None, expected: object) -> None:
    assert mp.claim_accuracy(claim, status) == expected


def test_load_claims_refuses_an_unknown_value(tmp_path: Path) -> None:
    path = tmp_path / "claims.json"
    path.write_text(json.dumps({"claims": {"a-1": "probably-fine"}}))
    with pytest.raises(ValueError, match="probably-fine"):
        mp.load_claims(path)


def test_pilot_report_merges_reviewed_claims(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _, outcomes, run_dir = _run_fake_pilot(tmp_path)
    claims = {o.scheduled.attempt_id: "claimed-success" for o in outcomes}
    claims_path = tmp_path / "claims.json"
    claims_path.write_text(json.dumps({"claims": claims}))
    evidence = tmp_path / "evidence"
    code = cli.cmd_pilot_report(argparse.Namespace(
        run_dir=str(run_dir), claims=str(claims_path), evidence=str(evidence), manifest=None,
    ))
    assert code == 0
    report = json.loads((evidence / "report.json").read_text())
    assert report["claims_reviewed"] is True
    # claimed success everywhere: right on the treatment's PASSes, wrong on the baseline's FAILs
    assert [e["claim_accurate"] for e in report["attempts"]] == [True, False] * 3
    summary = json.loads(capsys.readouterr().out.split("\n", 1)[1])
    assert summary["arms"]["treatment"]["passed"] == 3
    assert summary["arms"]["baseline"]["passed"] == 0
    assert summary["matched_successful_pairs"] == []  # no repeat where both arms passed
    assert summary["median_agent_seconds_difference_treatment_minus_baseline"] == mp.UNKNOWN


def test_matched_pairs_compare_only_repeats_where_both_arms_passed(tmp_path: Path) -> None:
    experiment, outcomes, _ = _run_fake_pilot(tmp_path, solve_arms=(mp.TREATMENT, mp.BASELINE))
    summary = mp.summarize(mp.build_report(experiment, outcomes))
    pairs = summary["matched_successful_pairs"]
    assert isinstance(pairs, list)
    assert [p["repeat"] for p in pairs] == [1, 2, 3]
    assert summary["median_agent_seconds_difference_treatment_minus_baseline"] != mp.UNKNOWN


# ------------------------------------------------------- export and manifest


def test_a_leaking_bundle_is_removed_not_left_in_place(tmp_path: Path) -> None:
    experiment, schedule = _fake_schedule(tmp_path)
    outcomes = mp.run_schedule(
        experiment, schedule,
        lambda s, _b: trial.finalize(experiment, s.attempt_id, disposition="unavailable", reason="fake"),
        total_seconds=10_000, per_attempt_seconds=900,
    )
    report = mp.build_report(experiment, outcomes)
    _entries(report)[0]["uncertainty"] = f"read {HOME_PATH_LEAK}/.codex/auth.json"
    evidence = tmp_path / "evidence"
    assert cli._export_pilot_evidence(experiment, report, evidence) == 1
    assert not evidence.exists() or not any(evidence.iterdir())

    clean = mp.build_report(experiment, outcomes)
    assert cli._export_pilot_evidence(experiment, clean, evidence) == 0
    assert (evidence / "report.json").exists()


def test_a_manifest_whose_order_this_runner_does_not_implement_is_refused(tmp_path: Path) -> None:
    manifest = json.loads(mp.MANIFEST_PATH.read_text(encoding="utf-8"))
    manifest["predeclared_experiment_record"]["arm_order"] = "all treatment, then all baseline"
    path = tmp_path / "run-manifest.json"
    path.write_text(json.dumps(manifest))
    with pytest.raises(mp.ManifestRefused, match="arm_order"):
        mp.load_declaration(path)
    assert mp.load_declaration().repeats_per_arm == 3  # the committed one is runnable


def test_baseline_digest_is_the_empty_surface() -> None:
    assert mp.BASELINE_SUBJECT_DIGEST == "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


# ------------------------------------------- counter-model review red cases


def _manifest_with(tmp_path: Path, **record_overrides: object) -> Path:
    manifest = json.loads(mp.CURRENT_MANIFEST_PATH.read_text(encoding="utf-8"))
    record = manifest["predeclared_experiment_record"]
    for dotted, value in record_overrides.items():
        target = record
        *parents, leaf = dotted.split("__")
        for key in parents:
            target = target[key]
        target[leaf] = value
    path = tmp_path / "run-manifest.json"
    path.write_text(json.dumps(manifest))
    return path


@pytest.mark.parametrize("value", [float("nan"), float("inf"), 0, -1, "5400", True])
def test_a_non_finite_or_non_positive_cap_is_refused(tmp_path: Path, value: object) -> None:
    """Review finding: NaN made every `elapsed >= total` comparison false, so
    the total cap silently never fired."""
    path = _manifest_with(tmp_path, time_caps__total_seconds=value)
    with pytest.raises(mp.ManifestRefused, match="total_seconds"):
        mp.load_declaration(path)


def test_a_task_the_runner_does_not_execute_is_refused(tmp_path: Path) -> None:
    """Review finding: a manifest naming another grader was recorded in the
    ledger while the Level 1 fixture actually ran."""
    path = _manifest_with(tmp_path, goal_population__task__grader="evals/other-task/grader.json")
    with pytest.raises(mp.ManifestRefused, match="not the task this runner executes"):
        mp.load_declaration(path)


def test_an_undeclared_image_digest_is_refused(tmp_path: Path) -> None:
    path = _manifest_with(tmp_path, image_digest="owed-to-the-live-build")
    with pytest.raises(mp.ManifestRefused, match="image_digest"):
        mp.load_declaration(path)


def _pilot_run_args(tmp_path: Path, **overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "manifest": None, "image": None, "docker_bin": f"{sys.executable} {FAKE_DOCKER} --state {tmp_path / 'ds'}",
        "timeout": 5, "credential": None, "client_argv": None,
        "private_dir": str(tmp_path / "private"), "evidence": str(tmp_path / "evidence"),
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_pilot_run_refuses_an_image_other_than_the_declared_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """Review finding: any resolvable image used to pass. The fake docker
    resolves every image to a digest the manifest does not declare."""
    (tmp_path / "ds").mkdir()
    assert cli.cmd_pilot_run(_pilot_run_args(tmp_path)) == 2
    assert "refusing a run on an image other than the declared one" in capsys.readouterr().err
    assert not (tmp_path / "private").exists()  # refused before any run directory was made


def test_pilot_run_accepts_the_declared_image_and_proceeds(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The green half of the image guard: the declared digest passes it, and
    the run proceeds to acquisition (stopped there by a refused subject)."""
    from skillc import demo

    declared = mp.load_declaration().image_digest
    monkeypatch.setattr(demo, "resolve_image_digest", lambda *a, **k: declared)

    def refuse(*_a: object, **_k: object) -> None:
        raise demo.SubjectRefused("stopped here by the test")

    monkeypatch.setattr(cc, "acquire_collection", refuse)
    assert cli.cmd_pilot_run(_pilot_run_args(tmp_path)) == 2
    err = capsys.readouterr().err
    assert "stopped here by the test" in err
    assert "other than the declared one" not in err


def test_the_last_attempt_s_agent_limit_is_cut_to_the_remaining_budget(tmp_path: Path) -> None:
    """Review finding: an attempt starting just before the total cap used to
    get the full per-attempt limit, so agent execution overshot the total."""
    experiment, schedule = _fake_schedule(tmp_path)
    now = [0.0]
    budgets: list[float] = []

    def run_attempt(scheduled: mp.ScheduledAttempt, budget: float) -> dict[str, object]:
        budgets.append(budget)
        now[0] += 900
        return trial.finalize(experiment, scheduled.attempt_id, disposition="unavailable", reason="fake")

    outcomes = mp.run_schedule(
        experiment, schedule, run_attempt, total_seconds=2000, per_attempt_seconds=900, clock=lambda: now[0],
    )
    assert budgets == [900, 900, 200]  # the third starts at 1800s with 200s left
    assert "cut to 200s" in str(outcomes[2].runner_note)
    assert [o.record["disposition"] for o in outcomes[3:]] == ["not-run"] * 3


def test_an_error_after_capture_keeps_the_captured_record(tmp_path: Path) -> None:
    """Review finding: a raise AFTER finalize (in grading, say) used to
    replace a `captured` lifecycle with an invented `inconclusive` one."""
    experiment, schedule = _fake_schedule(tmp_path)

    def run_attempt(scheduled: mp.ScheduledAttempt, _budget: float) -> dict[str, object]:
        trial.finalize(experiment, scheduled.attempt_id, disposition="unavailable", reason="finalized first")
        raise RuntimeError("grading blew up")

    outcomes = mp.run_schedule(experiment, schedule, run_attempt, total_seconds=10_000, per_attempt_seconds=900)
    assert outcomes[0].record["disposition"] == "unavailable"
    assert outcomes[0].record["reason"] == "finalized first"
    assert "grading blew up" in str(outcomes[0].runner_note)


def test_an_interrupted_run_still_reports_every_scheduled_attempt(tmp_path: Path) -> None:
    """Review finding: `pilot-report` used to export only the outcomes an
    interrupted run had recorded. Reconciliation restores the ledger's
    population and the bundle checks clean."""
    experiment, schedule = _fake_schedule(tmp_path)
    outcomes = mp.run_schedule(
        experiment, schedule[:2],
        lambda s, _b: trial.finalize(experiment, s.attempt_id, disposition="unavailable", reason="fake"),
        total_seconds=10_000, per_attempt_seconds=900,
    )
    reconciled = mp.reconcile(experiment, outcomes)
    assert [o.scheduled.attempt_id for o in reconciled] == [s.attempt_id for s in schedule]
    assert [o.record["disposition"] for o in reconciled[2:]] == ["not-run"] * 4
    evidence = tmp_path / "evidence"
    mp.export_bundle(experiment, mp.build_report(experiment, reconciled), evidence)
    assert mp.bundle_findings(evidence) == ([], 0)


def test_an_outcome_the_ledger_never_planned_is_refused(tmp_path: Path) -> None:
    experiment, _ = _fake_schedule(tmp_path)
    stray = mp.AttemptOutcome(mp.ScheduledAttempt("a-stray", "t-x", mp.TREATMENT, 1), {}, 0.0)
    with pytest.raises(mp.ManifestRefused, match="never planned"):
        mp.reconcile(experiment, [stray])


def _unavailable_outcomes(tmp_path: Path) -> tuple[trial.Experiment, list[mp.AttemptOutcome]]:
    experiment, schedule = _fake_schedule(tmp_path)
    outcomes = mp.run_schedule(
        experiment, schedule,
        lambda s, _b: trial.finalize(experiment, s.attempt_id, disposition="unavailable", reason="fake"),
        total_seconds=10_000, per_attempt_seconds=900,
    )
    return experiment, outcomes


def test_a_failed_export_leaves_the_previous_bundle_and_a_rerun_replaces_it_whole(tmp_path: Path) -> None:
    """Review finding (#12): exports used to write into the destination in
    place, so a re-export left stale records beside the new ledger. A
    re-export of the SAME experiment replaces the bundle whole; a failed one
    leaves the previous bundle untouched."""
    evidence = tmp_path / "evidence"
    experiment, outcomes = _unavailable_outcomes(tmp_path)
    good = mp.build_report(experiment, outcomes)
    assert cli._export_pilot_evidence(experiment, good, evidence) == 0
    (evidence / "lifecycle-a-stale.json").write_text("{}")  # left over from an earlier export

    bad = mp.build_report(experiment, outcomes)
    _entries(bad)[0]["uncertainty"] = f"read {HOME_PATH_LEAK}/.codex/auth.json"
    assert cli._export_pilot_evidence(experiment, bad, evidence) == 1
    assert (evidence / "lifecycle-a-stale.json").exists()  # previous bundle untouched

    assert cli._export_pilot_evidence(experiment, good, evidence) == 0
    assert not (evidence / "lifecycle-a-stale.json").exists()  # replaced whole, no mixing
    assert mp.bundle_findings(evidence) == ([], 0)
    assert not list(tmp_path.glob(".evidence.staging-*"))


def _snapshot(directory: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(directory.iterdir())}


def test_export_refuses_to_replace_another_experiment_s_bundle(tmp_path: Path) -> None:
    """#147: `pilot-run`'s default destination held #12's first-run bundle, and
    a default re-run would have replaced it wholesale. Another experiment's
    published bundle is refused and left byte-identical."""
    evidence = tmp_path / "evidence"
    first, first_outcomes = _unavailable_outcomes(tmp_path / "first")
    assert cli._export_pilot_evidence(first, mp.build_report(first, first_outcomes), evidence) == 0
    before = _snapshot(evidence)

    second, second_outcomes = _unavailable_outcomes(tmp_path / "second")
    assert second.id != first.id
    assert cli._export_pilot_evidence(second, mp.build_report(second, second_outcomes), evidence) == 2
    assert _snapshot(evidence) == before
    assert mp.bundle_experiment_id(evidence) == first.id

    other = tmp_path / "other-evidence"  # its own directory: published normally
    assert cli._export_pilot_evidence(second, mp.build_report(second, second_outcomes), other) == 0
    assert mp.bundle_experiment_id(other) == second.id


@pytest.mark.parametrize("ledger", [None, "not json", '{"experiment_id": 7}', '["a list"]'])
def test_export_refuses_a_bundle_whose_owner_cannot_be_read(tmp_path: Path, ledger: str | None) -> None:
    """A bundle-shaped directory that cannot say which experiment it records
    is never assumed to be ours."""
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "report.json").write_text("{}")
    if ledger is not None:
        (evidence / "ledger.json").write_text(ledger)
    before = _snapshot(evidence)
    experiment, outcomes = _unavailable_outcomes(tmp_path)
    assert cli._export_pilot_evidence(experiment, mp.build_report(experiment, outcomes), evidence) == 2
    assert _snapshot(evidence) == before


def test_export_may_write_into_an_empty_existing_directory(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    experiment, outcomes = _unavailable_outcomes(tmp_path)
    assert cli._export_pilot_evidence(experiment, mp.build_report(experiment, outcomes), evidence) == 0


@pytest.mark.parametrize("foreign", ["README.md", "claims.json", "notes.txt"])
def test_export_refuses_to_replace_a_destination_holding_files_it_does_not_own(
    tmp_path: Path, foreign: str,
) -> None:
    """Second review finding: replacing the destination deleted it whole, so
    `--evidence evals/matched-pilot/evidence` would have taken the README and
    the reviewed claims with it."""
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / foreign).write_text("not the exporter's")
    experiment, outcomes = _unavailable_outcomes(tmp_path)
    assert cli._export_pilot_evidence(experiment, mp.build_report(experiment, outcomes), evidence) == 2
    assert (evidence / foreign).read_text() == "not the exporter's"


def test_export_refuses_a_symlinked_destination(tmp_path: Path) -> None:
    """Bundle-shaped contents only, so the ownership check alone would let
    this through: only the symlink refusal stops publishing into (and
    deleting) the link's target."""
    real = tmp_path / "real"
    real.mkdir()
    (real / "ledger.json").write_text("{}")
    link = tmp_path / "evidence"
    link.symlink_to(real)
    experiment, outcomes = _unavailable_outcomes(tmp_path)
    assert cli._export_pilot_evidence(experiment, mp.build_report(experiment, outcomes), link) == 2
    assert (real / "ledger.json").read_text() == "{}"


def test_a_goal_the_runner_does_not_execute_is_refused(tmp_path: Path) -> None:
    path = _manifest_with(tmp_path, goal_population__task__goal="evals/other-task/goal.md")
    with pytest.raises(mp.ManifestRefused, match="not the goal this runner executes"):
        mp.load_declaration(path)


def test_an_interruption_during_the_first_attempt_is_still_reconcilable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Second review finding: `outcomes.json` was first written after an
    attempt returned, so dying inside the first attempt left nothing for
    `pilot-report` to read."""
    def die(**_kwargs: object) -> dict[str, object]:
        raise KeyboardInterrupt

    monkeypatch.setattr(cc, "run_level1_agent_attempt", die)
    declaration = mp.load_declaration()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    with pytest.raises(KeyboardInterrupt):
        mp.run_pilot(
            declaration, run_dir=run_dir, treatment_home_files={}, treatment_digest=TREATMENT_DIGEST,
            image_digest=None, backends=lambda: (object(), object()), argv_for=lambda _s: [],
        )
    experiment, outcomes = mp.read_outcomes(run_dir)
    assert outcomes == []
    reconciled = mp.reconcile(experiment, outcomes)
    assert len(reconciled) == 6
    evidence = tmp_path / "evidence"
    mp.export_bundle(experiment, mp.build_report(experiment, reconciled), evidence)
    assert mp.bundle_findings(evidence) == ([], 0)


def test_recovered_attempts_report_unknown_timings_never_zero(tmp_path: Path) -> None:
    """Second review finding: a reconciled attempt got wall time 0.0, which
    published invented zeros for setup and grading."""
    experiment, schedule = _fake_schedule(tmp_path)
    dispatched = schedule[0].attempt_id
    experiment.record(dispatched, "dispatched")
    experiment.record(dispatched, "started")
    reconciled = mp.reconcile(experiment, [])
    entries = _entries(mp.build_report(experiment, reconciled))
    assert entries[0]["disposition"] == "inconclusive"
    assert entries[0]["time_seconds"] == {"setup": "UNKNOWN", "agent": "UNKNOWN", "grading": "UNKNOWN", "total": "UNKNOWN"}
    # Never dispatched: confirmed non-execution, so zero is the true value.
    assert entries[1]["time_seconds"] == {"setup": 0, "agent": 0, "grading": 0, "total": 0}


def test_export_refuses_a_bundle_that_fails_check_records(tmp_path: Path) -> None:
    """Review finding: export used to check only leaks, so a report omitting
    a scheduled attempt was published."""
    experiment, schedule = _fake_schedule(tmp_path)
    outcomes = mp.run_schedule(
        experiment, schedule,
        lambda s, _b: trial.finalize(experiment, s.attempt_id, disposition="unavailable", reason="fake"),
        total_seconds=10_000, per_attempt_seconds=900,
    )
    evidence = tmp_path / "evidence"
    assert cli._export_pilot_evidence(experiment, mp.build_report(experiment, outcomes[:-1]), evidence) == 1
    assert not evidence.exists()


@pytest.mark.parametrize("status", ["INCONCLUSIVE", "UNAVAILABLE", "NOT_RUN"])
def test_claim_accuracy_is_unknown_when_the_grade_is_neither_pass_nor_fail(status: str) -> None:
    assert mp.claim_accuracy("claimed-success", status) == mp.UNKNOWN
    assert mp.claim_accuracy("claimed-failure", status) == mp.UNKNOWN


def test_a_reviewed_clarification_request_counts_as_an_intervention(tmp_path: Path) -> None:
    experiment, schedule = _fake_schedule(tmp_path)
    outcomes = mp.run_schedule(
        experiment, schedule,
        lambda s, _b: trial.finalize(experiment, s.attempt_id, disposition="unavailable", reason="fake"),
        total_seconds=10_000, per_attempt_seconds=900,
    )
    first = schedule[0].attempt_id
    entries = _entries(mp.build_report(experiment, outcomes, {first: "asked-clarification"}))
    assert entries[0]["interventions"] == 1
    assert "clarifying question" in str(entries[0]["uncertainty"])
    assert entries[0]["claim_accurate"] == "n/a"
    assert all(e["interventions"] == 0 for e in entries[1:])


def test_a_model_other_than_the_declared_one_is_a_reported_deviation(tmp_path: Path) -> None:
    experiment, schedule = _fake_schedule(tmp_path)
    outcomes = mp.run_schedule(
        experiment, schedule,
        lambda s, _b: trial.finalize(experiment, s.attempt_id, disposition="unavailable", reason="fake"),
        total_seconds=10_000, per_attempt_seconds=900,
    )
    outcomes[0].record["observation"] = {"run_metadata": {"model": "some-other-model"}}
    report = mp.build_report(experiment, outcomes, declared_model="declared-model")
    assert _entries(report)[0]["model_matches_declaration"] is False
    assert _entries(report)[1]["model_matches_declaration"] == mp.UNKNOWN  # unobserved, not assumed
    assert mp.summarize(report)["protocol_deviations"] == [
        f"{schedule[0].attempt_id}: ran model 'some-other-model', declared 'declared-model'",
    ]


# ------------------------------------------- #141: the declared model, pinned


DECLARED = mp.load_declaration()


def test_the_current_declaration_pins_the_ruled_model_and_effort() -> None:
    assert (DECLARED.model, DECLARED.reasoning_effort) == ("gpt-6-astra", "high")


def test_the_launch_argv_is_built_from_the_declaration(tmp_path: Path) -> None:
    assert mp.launch_argv(DECLARED, cc.DEFAULT_CLIENT_ARGV) == [
        *cc.DEFAULT_CLIENT_ARGV, "-m", "gpt-6-astra", "-c", 'model_reasoning_effort="high"',
    ]
    # Never hardcoded: a different declaration produces a different launch.
    other = mp.load_declaration(_manifest_with(tmp_path, model__name="some-next-model", model__reasoning_effort="low"))
    assert mp.launch_argv(other, ["codex", "exec"])[-4:] == ["-m", "some-next-model", "-c", 'model_reasoning_effort="low"']


@pytest.mark.parametrize("override", [
    ["-m", "other"], ["-mother"], ["--model", "other"], ["--model=other"],
    ["-c", "model=other"], ["-c", 'model_reasoning_effort="low"'], ["--config", "model_provider=oss"],
    ["--config=model=other"], ["-cmodel=other"], ["-c", "profiles.fast.model=other"],
    ["-p", "fast"], ["--profile=fast"], ["--oss"], ["--local-provider", "ollama"],
])
def test_a_client_argv_that_chooses_its_own_model_is_refused(override: list[str]) -> None:
    with pytest.raises(mp.ModelOverrideRefused, match="chooses the model itself"):
        mp.launch_argv(DECLARED, [*cc.DEFAULT_CLIENT_ARGV, *override])


@pytest.mark.parametrize("harmless", [
    ["-c", "sandbox_mode=read-only"], ["--config=shell_environment_policy.inherit=all"],
    # Counter-model finding: a neighbour's key that merely ENDS in `model`.
    ["-c", "mcp_servers.helper.env.model=tool-model"],
])
def test_config_that_does_not_touch_the_model_is_not_refused(harmless: list[str]) -> None:
    """The green half: the refusal is by key, not by `-c` itself."""
    assert mp.launch_argv(DECLARED, [*cc.DEFAULT_CLIENT_ARGV, *harmless])[-4:-2] == ["-m", "gpt-6-astra"]


def test_a_declaration_with_no_effort_to_pin_is_refused_before_anything_is_planned(tmp_path: Path) -> None:
    """#12's own predeclaration names no effort - it predates launch pinning."""
    old = mp.load_declaration(mp.MANIFEST_PATH)
    assert old.reasoning_effort is None
    with pytest.raises(mp.ModelOverrideRefused, match="predates launch pinning"):
        mp.launch_argv(old, cc.DEFAULT_CLIENT_ARGV)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    with pytest.raises(mp.ModelOverrideRefused):
        mp.run_pilot(
            old, run_dir=run_dir, treatment_home_files={}, treatment_digest=TREATMENT_DIGEST,
            image_digest=None, backends=lambda: (object(), object()), argv_for=lambda _s: [],
        )
    assert not (run_dir / "store").exists()


def test_pilot_run_refuses_a_model_override_before_any_run_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    code = cli.cmd_pilot_run(_pilot_run_args(tmp_path, client_argv="codex exec -m other-model"))
    assert code == 2
    assert "chooses the model itself (-m)" in capsys.readouterr().err
    assert not (tmp_path / "private").exists()


def test_the_declared_model_reaches_the_client_and_every_attempt_is_eligible(tmp_path: Path) -> None:
    experiment, outcomes, run_dir = _run_fake_pilot(tmp_path, solve_arms=(mp.TREATMENT, mp.BASELINE))
    report = mp.build_report(experiment, outcomes, declared_model=DECLARED.model, declared_effort=DECLARED.reasoning_effort)
    for entry in _entries(report):
        assert entry["model_observed"] == "gpt-6-astra"  # read back from the client's own rollout
        assert entry["model_eligible"] is True
        assert entry["reasoning_effort_observed"] == "high"
        assert entry["reasoning_effort_matches_declaration"] is True
    summary = mp.summarize(report)
    assert summary["model_ineligible"] == []
    assert summary["protocol_deviations"] == []
    assert [p["repeat"] for p in summary["matched_successful_pairs"]] == [1, 2, 3]  # type: ignore[attr-defined]
    assert cli._refuse_ineligible(report) == 0
    assert mp.read_declared(run_dir) == {"model": "gpt-6-astra", "reasoning_effort": "high"}


@pytest.mark.parametrize(("client_extra", "why"), [
    (("--observed-model", "some-other-model"), "ran model 'some-other-model', declared 'gpt-6-astra'"),
    (("--no-turn-context",), "no model observed in the client's rollout"),
])
def test_an_attempt_not_observed_running_the_declared_model_is_ineligible_and_fails_the_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], client_extra: tuple[str, ...], why: str,
) -> None:
    """Red cases (#141): a client that ignored the pin, and one whose rollout
    names no model. Both arms passed, so without the check every repeat
    would be a matched pair."""
    experiment, outcomes, _ = _run_fake_pilot(
        tmp_path, solve_arms=(mp.TREATMENT, mp.BASELINE), client_extra=client_extra,
    )
    report = mp.build_report(experiment, outcomes, declared_model=DECLARED.model, declared_effort=DECLARED.reasoning_effort)
    entries = _entries(report)
    assert all(e["graded_status"] == "PASS" for e in entries)
    assert all(e["model_eligible"] is False for e in entries)
    assert all(why in str(e["uncertainty"]) for e in entries)  # recorded, never silent
    summary = mp.summarize(report)
    assert summary["matched_successful_pairs"] == []
    assert summary["median_agent_seconds_difference_treatment_minus_baseline"] == mp.UNKNOWN
    assert summary["model_ineligible"] == [o.scheduled.attempt_id for o in outcomes]
    assert len(summary["protocol_deviations"]) == 6  # type: ignore[arg-type]
    assert cli._refuse_ineligible(report) == 1
    assert "6 attempt(s) did not run the declared model" in capsys.readouterr().err


def test_an_attempt_that_never_launched_is_not_held_to_a_model() -> None:
    assert mp.model_eligibility("not-run", mp.UNKNOWN, "gpt-6-astra") == "n/a"
    assert mp.model_eligibility("unavailable", mp.UNKNOWN, "gpt-6-astra") == "n/a"
    assert mp.model_eligibility("inconclusive", mp.UNKNOWN, "gpt-6-astra") is False


def test_pilot_report_scores_a_run_against_the_declaration_it_launched_with(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    _, _, run_dir = _run_fake_pilot(tmp_path)
    evidence = tmp_path / "evidence"
    args = {"run_dir": str(run_dir), "claims": None, "evidence": str(evidence)}

    # A --manifest that disagrees with what the run recorded is refused.
    other = _manifest_with(tmp_path, model__name="some-next-model")
    assert cli.cmd_pilot_report(argparse.Namespace(**args, manifest=str(other))) == 2
    assert "declared model 'gpt-6-astra'" in capsys.readouterr().err

    # A run from before #141 recorded nothing: the current declaration is
    # never assumed for it.
    outcomes_path = run_dir / mp.OUTCOMES_FILENAME
    data = json.loads(outcomes_path.read_text())
    del data["declared"]
    outcomes_path.write_text(json.dumps(data))
    assert cli.cmd_pilot_report(argparse.Namespace(**args, manifest=None)) == 2
    assert "predates #141" in capsys.readouterr().err

    # Named explicitly (#12's own), it is scored against THAT declaration.
    assert cli.cmd_pilot_report(argparse.Namespace(**args, manifest=str(mp.MANIFEST_PATH))) == 0
    report = json.loads((evidence / "report.json").read_text())
    assert {e["model_declared"] for e in report["attempts"]} == {"gpt-5.1-codex"}
    assert {e["model_matches_declaration"] for e in report["attempts"]} == {False}


def test_a_run_with_no_attempt_observed_on_the_declared_model_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """Counter-model red case: six unavailable attempts are all `n/a`, so no
    attempt is INeligible - but nothing was checked, and that is not a pass."""
    experiment, schedule = _fake_schedule(tmp_path)
    outcomes = mp.run_schedule(
        experiment, schedule,
        lambda s, _b: trial.finalize(experiment, s.attempt_id, disposition="unavailable", reason="fake"),
        total_seconds=10_000, per_attempt_seconds=900,
    )
    report = mp.build_report(experiment, outcomes, declared_model=DECLARED.model)
    assert mp.ineligible_attempts(report) == []
    assert cli._refuse_ineligible(report) == 1
    assert "nothing was compared" in capsys.readouterr().err


@pytest.mark.parametrize("declared", [{}, {"model": "gpt-6-astra"}, {"model": "", "reasoning_effort": "high"}, None])
def test_a_malformed_recorded_declaration_is_refused_not_read_as_absent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], declared: object,
) -> None:
    """Counter-model red case: `"declared": {}` used to be accepted, leaving
    the report with no model to compare - the check silently off."""
    _, _, run_dir = _run_fake_pilot(tmp_path)
    outcomes_path = run_dir / mp.OUTCOMES_FILENAME
    data = json.loads(outcomes_path.read_text())
    data["declared"] = declared
    outcomes_path.write_text(json.dumps(data))
    code = cli.cmd_pilot_report(argparse.Namespace(
        run_dir=str(run_dir), claims=None, evidence=str(tmp_path / "evidence"), manifest=None,
    ))
    assert code == 2
    assert "names no model and effort" in capsys.readouterr().err


def test_an_override_from_the_per_attempt_argv_aborts_the_run_not_one_attempt(tmp_path: Path) -> None:
    """Counter-model red case: `run_pilot` repeats the refusal per attempt,
    and it must abort the schedule like a missing opt-in - never be recorded
    as six ordinary `inconclusive` attempts."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    with pytest.raises(mp.ModelOverrideRefused):
        mp.run_pilot(
            DECLARED, run_dir=run_dir, treatment_home_files={}, treatment_digest=TREATMENT_DIGEST,
            image_digest=None, backends=lambda: (object(), object()),
            argv_for=lambda _s: ["codex", "exec", "-m", "other"],
        )
    _, outcomes = mp.read_outcomes(run_dir)
    assert outcomes == []
