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

from skillc import checks, cli, records, trial
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


#: The one finding a captured agent-trial attempt still carries: the #106
#: driver grades through `verify.grade_files` and stores no `verified-result`
#: record (that needs an installation receipt the agent path does not write),
#: so `attempt-accounting` correctly says the result is owed. Named here so
#: any OTHER finding still fails these tests.
KNOWN_GAP = "is captured but has no result"


def _entries(report: dict[str, object]) -> list[dict[str, object]]:
    attempts = report["attempts"]
    assert isinstance(attempts, list)
    return attempts


def _unexpected(findings: list[checks.Finding]) -> list[checks.Finding]:
    return [f for f in findings if not (f.rule == "attempt-accounting" and KNOWN_GAP in f.detail)]


def _evidence_findings(root: Path) -> list[checks.Finding]:
    """What `skillc check-records` would report on `root`, errors only."""
    findings: list[checks.Finding] = []
    for record in records.discover(root):
        findings.extend(checks.run_record(record))
    for bundle in records.discover_bundles(root):
        findings.extend(checks.run_bundle(bundle))
    return [f for f in findings if f.severity == checks.ERROR]


def _run_fake_pilot(
    tmp_path: Path, *, solve_arms: Sequence[str] = (mp.TREATMENT,), total_seconds: float | None = None,
) -> tuple[trial.Experiment, list[mp.AttemptOutcome], Path]:
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
    findings = _evidence_findings(evidence)
    assert _unexpected(findings) == []
    assert len(findings) == 6  # exactly the known gap, once per captured attempt
    assert len(_entries(report)) == 6

    # Resumable from the private record alone, and identical.
    reloaded_experiment, reloaded = mp.read_outcomes(run_dir)
    assert mp.build_report(reloaded_experiment, reloaded) == report


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
    experiment, outcomes, _ = _run_fake_pilot(tmp_path)
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

    def run_attempt(scheduled: mp.ScheduledAttempt) -> dict[str, object]:
        now[0] += 1000
        return trial.finalize(experiment, scheduled.attempt_id, disposition="unavailable", reason="fake attempt")

    outcomes = mp.run_schedule(experiment, schedule, run_attempt, total_seconds=1500, clock=lambda: now[0])
    dispositions = [o.record["disposition"] for o in outcomes]
    assert dispositions == ["unavailable", "unavailable", "not-run", "not-run", "not-run", "not-run"]
    assert all("total time cap" in str(o.runner_note) for o in outcomes[2:])

    report = mp.build_report(experiment, outcomes)
    evidence = tmp_path / "evidence"
    mp.export_bundle(experiment, report, evidence)
    assert _evidence_findings(evidence) == []
    for entry in _entries(report)[2:]:
        assert entry["time_seconds"] == {"setup": 0, "agent": 0, "grading": 0, "total": 0}


def test_a_report_that_omits_a_scheduled_attempt_is_refused(tmp_path: Path) -> None:
    """The negative control for the exported bundle: drop one attempt and
    `ledger_binding` must say so - otherwise the green above proves nothing."""
    experiment, schedule = _fake_schedule(tmp_path)
    outcomes = mp.run_schedule(
        experiment, schedule,
        lambda s: trial.finalize(experiment, s.attempt_id, disposition="unavailable", reason="fake"),
        total_seconds=10_000,
    )
    report = mp.build_report(experiment, outcomes[:-1])
    evidence = tmp_path / "evidence"
    mp.export_bundle(experiment, report, evidence)
    findings = _evidence_findings(evidence)
    assert any(f.rule == "ledger-binding" and "omits scheduled attempt" in f.detail for f in findings)


def test_a_crashing_attempt_is_inconclusive_and_the_schedule_continues(tmp_path: Path) -> None:
    experiment, schedule = _fake_schedule(tmp_path)
    calls: list[str] = []

    def run_attempt(scheduled: mp.ScheduledAttempt) -> dict[str, object]:
        calls.append(scheduled.attempt_id)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return trial.finalize(experiment, scheduled.attempt_id, disposition="unavailable", reason="fake")

    outcomes = mp.run_schedule(experiment, schedule, run_attempt, total_seconds=10_000)
    assert len(calls) == 6
    assert outcomes[0].record["disposition"] == "inconclusive"
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
    code = cli.cmd_pilot_report(argparse.Namespace(run_dir=str(run_dir), claims=str(claims_path), evidence=str(evidence)))
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
        lambda s: trial.finalize(experiment, s.attempt_id, disposition="unavailable", reason="fake"),
        total_seconds=10_000,
    )
    report = mp.build_report(experiment, outcomes)
    _entries(report)[0]["uncertainty"] = "read /home/someoperator/.codex/auth.json"
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
