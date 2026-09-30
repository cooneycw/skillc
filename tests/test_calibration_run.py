"""Tests for `skillc calibration-run` (issue #207): executing an approved
two-arm calibration declaration (#204).

Every attempt runs against the fake docker CLI and the scripted fake client
(`tests/fixtures/agent-trial/fake_agent_client.py`); the treatment's
installation receipt lists through `tests/fixtures/codex-subject/fake_codex.py`.
No test here makes a live model call.
"""

from __future__ import annotations

import argparse
import base64
import json
import shutil
import sys
import time
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest

from skillc import calibration, cli, demo, materialize, trial, verify
from skillc import calibration_run as cr
from skillc import collection_conformance as cc
from skillc import docker_backend as d
from skillc import matched_pilot as mp

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "evals" / "calibration-204" / "run-manifest.json"
TASK = ROOT / "evals" / "level3" / "slugkit-pipeline"
FAKE_DOCKER = Path(__file__).resolve().parent / "fixtures" / "docker-backend" / "fake_docker.py"
FAKE_CLIENT = Path(__file__).resolve().parent / "fixtures" / "agent-trial" / "fake_agent_client.py"
CODEX_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "codex-subject"

_IMAGE = "fake-image:1"
#: `fake_docker.py`'s deterministic digest for `_IMAGE`: the receipt path
#: cross-checks the measured image against the planned one.
_IMAGE_DIGEST = f"sha256:fake-digest-for-{_IMAGE}"
TREATMENT_ARM = "full-cpp"
#: Every fake-docker call is a fresh Python process. The default 5s daemon
#: timeout was exceeded on the loaded CI runner while grading the Level 3 task
#: (pipeline 454): `confirm_stopped` read UNKNOWN, and "UNKNOWN never reaps"
#: quarantined the verifier for the rest of the process. The fake daemon is
#: local, so a generous bound costs nothing and says nothing about a real one.
_FAKE_DAEMON_TIMEOUT = 120.0


@pytest.fixture(autouse=True)
def _no_quarantine_escapes() -> Iterator[None]:
    """A test here that trips the verifier's process-wide quarantine fails
    ITSELF, and the quarantine is cleared - never inherited by every later
    test in the session, which is how one timeout above became 153 failures."""
    yield
    reason = verify._quarantine
    if reason is not None:
        verify.clear_quarantine()
        pytest.fail(f"this test quarantined the verifier: {reason}")


# ------------------------------------------------------------------ helpers


def _declaration_data(*, attempts: int | None = None, approved: bool = True) -> dict[str, object]:
    """The COMMITTED #204 declaration - approved by the owner (#208) - pointed
    at the fake image, or with ONLY its approval removed (the red case).
    `attempts` re-derives the seeded order for a smaller schedule."""
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert isinstance(data["approval"], dict), "the committed declaration is expected to carry its approval"
    if not approved:
        data["approval"] = None
    data["shared"]["image"]["digest"] = _IMAGE_DIGEST
    if attempts is not None:
        names = [a["name"] for a in data["arms"]]
        data["attempts_per_arm"] = attempts
        data["arm_order"]["sequence"] = calibration.derive_arm_order(data["arm_order"]["seed"], names, attempts)
    return data


def _declaration(**kwargs: object) -> calibration.CalibrationDeclaration:
    return calibration.parse_declaration(_declaration_data(**kwargs))  # type: ignore[arg-type]


def _docker_bin(state_dir: Path) -> list[str]:
    return [sys.executable, str(FAKE_DOCKER), "--state", str(state_dir)]


def _fresh_codex_credential(tmp_path: Path) -> Path:
    def seg(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()
    token = f"{seg(json.dumps({'alg': 'none'}).encode())}.{seg(json.dumps({'exp': int(time.time() + 3600)}).encode())}.sig"
    path = tmp_path / "codex-credential.json"
    path.write_text(json.dumps({"tokens": {"access_token": token}}))
    return path


def _treatment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> cr.Treatment:
    """A real acquisition of a one-skill fixture collection, built into the
    treatment exactly as the CLI builds it, with a scripted listing client."""
    collection = tmp_path / "subject-collection"
    skill = collection / "skills" / "tdd"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: tdd\ndescription: A test skill.\n---\nBody.\n", encoding="utf-8")
    subject = materialize.Subject.from_dict({
        "subject_schema": 1, "locator": "test/test", "revision": "v1", "surface": "codex-skills",
        "skills_root": "skills", "select": ["tdd"], "client": {"name": "codex", "version": "0.157.1"},
    })
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: subject)
    base = tmp_path / "acquire"
    base.mkdir()
    acquired = cc.acquire_collection("whatever", base, checkout=collection)
    script = tmp_path / "listing-client" / "fake_codex.py"
    script.parent.mkdir()
    shutil.copy(CODEX_FIXTURE / "fake_codex.py", script)
    script.with_suffix(".mode").write_text(json.dumps({"mode": "normal"}), encoding="utf-8")
    return cr.build_treatment(acquired, listing_client_argv=[sys.executable, str(script)])


def _run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *,
    declaration: calibration.CalibrationDeclaration | None = None,
    solve_arms: Sequence[str] = (TREATMENT_ARM, calibration.BASELINE_ARM),
    client_extra: Sequence[str] = (), total_seconds: float | None = None, tick: float = 0.0,
) -> tuple[trial.Experiment, list[mp.AttemptOutcome], Path, cr.Treatment]:
    declaration = declaration or _declaration(attempts=3)
    treatment = _treatment(tmp_path, monkeypatch)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    docker_state = tmp_path / "docker-state"
    now = [0.0]

    def backends() -> tuple[object, object]:
        now[0] += tick
        make = lambda: d.DockerBackend(
            image=_IMAGE, base_dir=run_dir, docker_bin=_docker_bin(docker_state), daemon_timeout=_FAKE_DAEMON_TIMEOUT,
        )
        return make(), make()

    def argv_for(scheduled: mp.ScheduledAttempt) -> list[str]:
        home = docker_state / f"{d._container_name(scheduled.attempt_id)}.fsroot" / "home" / "candidate"
        argv = [
            sys.executable, str(FAKE_CLIENT), "--format", "codex-fake", "--home", str(home),
            "--transcript-relpath", f".codex/sessions/2026/01/01/rollout-{scheduled.attempt_id}.jsonl",
        ]
        if scheduled.arm in solve_arms:
            argv.extend(["--copy-solution", str(TASK / "reference")])
        argv.extend(client_extra)
        return argv

    experiment, outcomes = cr.run_calibration(
        declaration, run_dir=run_dir, treatment=treatment, image_digest=_IMAGE_DIGEST,
        backends=backends, argv_for=argv_for, credential_explicit_path=_fresh_codex_credential(tmp_path),
        total_seconds=total_seconds, clock=(lambda: now[0]) if tick else time.monotonic,
    )
    return experiment, outcomes, run_dir, treatment


def _report(experiment: trial.Experiment, outcomes: Sequence[mp.AttemptOutcome]) -> dict[str, object]:
    return cr.build_report(
        experiment, cr.reconcile(experiment, outcomes), declared_model="gpt-6-astra", declared_effort="high",
    )


def _entries(report: dict[str, object]) -> list[dict[str, object]]:
    attempts = report["attempts"]
    assert isinstance(attempts, list)
    return attempts


# ---------------------------------------------------------- authorization


def test_red_the_committed_declaration_with_its_approval_removed_refuses_before_any_container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Red case: approval null. Nothing is created - no store, no plan, and
    the backend factory is never asked for a container."""
    declaration = _declaration(approved=False)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    asked: list[str] = []

    def backends() -> tuple[object, object]:
        asked.append("backend")
        raise AssertionError("a container was requested for an unapproved declaration")

    with pytest.raises(calibration.DeclarationRefused, match="not approved"):
        cr.run_calibration(
            declaration, run_dir=run_dir, treatment=cr.Treatment({}, "sha256:" + "ab" * 32, None),
            image_digest=_IMAGE_DIGEST, backends=backends, argv_for=lambda _s: ["codex"],
        )
    assert asked == []
    assert list(run_dir.iterdir()) == []


def test_the_same_declaration_approved_is_authorized() -> None:
    """The green half of the control above: only the approval differs."""
    calibration.require_approved(_declaration(approved=True), ROOT)


def test_cli_refuses_an_unapproved_declaration_before_any_run_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "declaration.json"
    path.write_text(json.dumps(_declaration_data(approved=False)), encoding="utf-8")
    private = tmp_path / "private"
    assert cli.main(["calibration-run", str(path), "--private-dir", str(private)]) == 2
    assert "not approved" in capsys.readouterr().err
    assert not private.exists()


# ------------------------------------------------------------ arm order


def test_the_planned_order_is_the_declared_sequence(tmp_path: Path) -> None:
    declaration = _declaration()  # the committed schedule: 4 per arm
    store = trial.open_store(tmp_path / "store", forbidden=[])
    experiment, schedule = cr.plan_calibration(
        declaration, store, root=ROOT, treatment_digest="sha256:" + "ab" * 32, image_digest=_IMAGE_DIGEST,
    )
    assert [s.arm for s in schedule] == list(declaration.arm_order)
    assert [s.arm for s in schedule] == [
        "full-cpp", "baseline", "baseline", "full-cpp", "full-cpp", "baseline", "full-cpp", "baseline",
    ]
    assert [s.repeat for s in schedule] == [1, 1, 2, 2, 3, 3, 4, 4]
    # Recoverable from the ledger alone, and identical.
    assert cr.schedule_from_ledger(experiment) == schedule


def test_a_ledger_that_is_not_a_calibration_s_is_refused(tmp_path: Path) -> None:
    store = trial.open_store(tmp_path / "store", forbidden=[])
    experiment, _ = mp.plan_pilot(mp.load_declaration(), store, treatment_digest="sha256:" + "ab" * 32, image_digest=None)
    with pytest.raises(cr.CalibrationRefused, match="not a calibration trial"):
        cr.schedule_from_ledger(experiment)


# ---------------------------------------------- the arms differ only in treatment


def test_both_arms_run_one_path_and_differ_only_in_what_is_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[dict[str, object]] = []
    real = cc.run_level1_agent_attempt

    def spy(**kwargs: object) -> dict[str, object]:
        seen.append(dict(kwargs))
        return real(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(cc, "run_level1_agent_attempt", spy)
    experiment, outcomes, _, treatment = _run(tmp_path, monkeypatch)

    assert [o.scheduled.arm for o in outcomes] == list(_declaration(attempts=3).arm_order)
    assert len(seen) == 6
    arm_of = {o.scheduled.attempt_id: o.scheduled.arm for o in outcomes}
    assert treatment.home_files and treatment.receipt_context is not None
    for call in seen:
        if arm_of[str(call["attempt_id"])] == calibration.BASELINE_ARM:
            assert call["extra_home_files"] == {}
            assert call["receipt_context"] is None
        else:
            assert call["extra_home_files"] == treatment.home_files
            assert call["receipt_context"] is treatment.receipt_context

    # Everything else is identical across the arms.
    def shared(call: dict[str, object]) -> tuple[object, ...]:
        argv = list(call["base_argv"])  # type: ignore[call-overload]
        return (call["task_root"], call["surface"], call["client"], call["cli_version"], call.get("prompt"),
                argv[-4:])

    assert len({repr(shared(c)) for c in seen}) == 1
    assert seen[0]["task_root"] == TASK
    surface = seen[0]["surface"]
    assert isinstance(surface, dict) and "ci/verify.py" in surface and "expected.json" not in surface
    # The baseline's planned subject is the empty surface; the treatment's is the collection.
    subjects = {arm_of[str(a["attempt_id"])]: t["subject"]["digest"]  # type: ignore[index]
                for t, a in experiment.attempts()}
    assert subjects == {calibration.BASELINE_ARM: mp.BASELINE_SUBJECT_DIGEST, TREATMENT_ARM: treatment.digest}
    assert all(o.record["disposition"] == "captured" for o in outcomes)


# --------------------------------------------------------- symmetric endpoint


def test_a_baseline_attempt_meeting_every_criterion_is_primary_pass_beside_unknown_readiness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    experiment, outcomes, run_dir, _ = _run(tmp_path, monkeypatch)
    report = _report(experiment, outcomes)
    entries = _entries(report)
    assert len(entries) == 6

    for entry in entries:
        primary = entry["primary_endpoint"]
        ready = entry["readiness_beside"]
        assert isinstance(primary, dict) and isinstance(ready, dict)
        assert primary["status"] == "PASS", primary
        assert [c["id"] for c in primary["criteria"]] == [  # type: ignore[index]
            "functional-trailing-hyphen", "integration-installed-path", "pipeline-green", "pipeline-honest",
        ]
        if entry["arm"] == calibration.BASELINE_ARM:
            assert ready["installation_ready"] == calibration.UNKNOWN
            assert ready["verified_status"] == "INCONCLUSIVE"  # never the endpoint
        else:
            assert ready["installation_ready"] == "SATISFIED"  # a real receipt, #150-D
            assert ready["verified_status"] == "PASS"
        retention = entry["transcript_retention"]
        assert isinstance(retention, dict) and retention.get("coverage") == "complete", retention  # #202

    assert report["arms"] == {
        TREATMENT_ARM: {"scheduled": 3, "primary": {"PASS": 3}, "model_ineligible": 0},
        calibration.BASELINE_ARM: {"scheduled": 3, "primary": {"PASS": 3}, "model_ineligible": 0},
    }
    assert cli._refuse_ineligible(report) == 0
    assert mp.read_declared(run_dir) == {"model": "gpt-6-astra", "reasoning_effort": "high"}
    # The printed summary shows the endpoint first and readiness beside it,
    # and passes the leak check.
    text = cr.paste_back(report)
    assert "primary=PASS | installation-ready=UNKNOWN verified=INCONCLUSIVE" in text
    assert demo.leak_check_text(text) == []


def test_an_unsolved_attempt_is_primary_fail_not_hidden(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    experiment, outcomes, _, _ = _run(tmp_path, monkeypatch, solve_arms=(TREATMENT_ARM,))
    by_arm: dict[str, set[object]] = {}
    for entry in _entries(_report(experiment, outcomes)):
        by_arm.setdefault(str(entry["arm"]), set()).add(entry["primary_endpoint"]["status"])  # type: ignore[index]
    assert by_arm == {TREATMENT_ARM: {"PASS"}, calibration.BASELINE_ARM: {"FAIL"}}


# ----------------------------------------------------------------- model pin


def test_the_declared_model_is_passed_at_launch_and_observed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    experiment, outcomes, _, _ = _run(tmp_path, monkeypatch, solve_arms=())
    for entry in _entries(_report(experiment, outcomes)):
        assert entry["model_observed"] == "gpt-6-astra"  # read back from the client's own rollout
        assert entry["reasoning_effort_observed"] == "high"
        assert entry["model_eligible"] is True


@pytest.mark.parametrize("override", [["-m", "other"], ["--model=other"], ["-c", "model_reasoning_effort=low"]])
def test_a_caller_argv_that_sets_the_model_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, override: list[str],
) -> None:
    with pytest.raises(mp.ModelOverrideRefused):
        _run(tmp_path, monkeypatch, client_extra=override)


def test_cli_refuses_a_model_override_before_any_run_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "declaration.json"
    path.write_text(json.dumps(_declaration_data()), encoding="utf-8")
    private = tmp_path / "private"
    code = cli.main(["calibration-run", str(path), "--private-dir", str(private),
                     "--client-argv", "codex exec -m some-other-model"])
    assert code == 2
    assert "chooses the model itself" in capsys.readouterr().err
    assert not private.exists()


@pytest.mark.parametrize(("client_extra", "observed"), [
    (("--observed-model", "some-other-model"), "some-other-model"),
    (("--no-turn-context",), calibration.UNKNOWN),
])
def test_red_an_attempt_not_observed_running_the_declared_model_is_ineligible_and_fails_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    client_extra: tuple[str, ...], observed: str,
) -> None:
    experiment, outcomes, _, _ = _run(tmp_path, monkeypatch, client_extra=client_extra)
    report = _report(experiment, outcomes)
    entries = _entries(report)
    assert all(e["primary_endpoint"]["status"] == "PASS" for e in entries)  # type: ignore[index]
    assert all(e["model_observed"] == observed and e["model_eligible"] is False for e in entries)
    assert cli._refuse_ineligible(report) == 1
    assert "6 attempt(s) did not run the declared model" in capsys.readouterr().err


# ---------------------------------------------------------- caps and reconciliation


def test_an_attempt_with_no_total_cap_left_is_not_run_and_still_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each attempt advances the fake clock by 1000s: the first starts at 0,
    the second at 1000 (agent limit cut to the 500s left of a 1500s total),
    and the other four start with nothing left - `not-run`, never dropped."""
    experiment, outcomes, _, _ = _run(tmp_path, monkeypatch, total_seconds=1500, tick=1000)
    report = _report(experiment, outcomes)
    entries = _entries(report)
    assert [e["disposition"] for e in entries] == ["captured", "captured"] + ["not-run"] * 4
    assert "agent limit cut to 500s" in str(entries[1]["runner_note"])
    assert all("total time cap reached" in str(e["runner_note"]) for e in entries[2:])
    assert all(e["primary_endpoint"]["status"] == calibration.NOT_GRADED for e in entries[2:])  # type: ignore[index]
    assert all(e["model_eligible"] == "n/a" for e in entries[2:])


def test_an_interrupted_run_still_reconciles_every_planned_attempt(tmp_path: Path) -> None:
    declaration = _declaration(attempts=3)
    store = trial.open_store(tmp_path / "store", forbidden=[])
    experiment, schedule = cr.plan_calibration(
        declaration, store, root=ROOT, treatment_digest="sha256:" + "ab" * 32, image_digest=_IMAGE_DIGEST,
    )
    reconciled = cr.reconcile(experiment, [])
    assert [o.scheduled for o in reconciled] == schedule
    assert all(o.record["disposition"] == "not-run" for o in reconciled)
    assert all("interrupted" in str(o.runner_note) for o in reconciled)


# ------------------------------------------------------------ small contracts


def test_task_surface_matches_the_level1_surface_and_withholds_the_answer_key() -> None:
    for fixture in (ROOT / "evals" / "level1" / "slug-small-fix" / "fixture",
                    ROOT / "evals" / "level1" / "finish-close-ref" / "fixture"):
        assert cc.task_surface(fixture) == cc._fixture_surface(fixture)
    level3 = cc.task_surface(TASK / "fixture")
    assert "expected.json" not in level3
    assert {"ci/verify.py", "pyproject.toml", "slugkit/core.py", "tests/test_core.py"} <= set(level3)
    assert cc._fixture_surface(TASK / "fixture") == {}  # why task_surface exists


def test_a_treatment_that_installs_nothing_is_refused() -> None:
    acquired = cc.AcquiredCollection(
        subject=argparse.Namespace(locator="test/test"), source=None, files=[],  # type: ignore[arg-type]
    )
    with pytest.raises(cr.CalibrationRefused, match="second baseline"):
        cr.build_treatment(acquired)


def test_cli_refuses_an_image_other_than_the_declared_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """The COMMITTED declaration names the real trial image's digest; the fake
    docker resolves `fake-image:1` to another. Refused before any run directory."""
    private = tmp_path / "private"
    code = cli.main(["calibration-run", str(MANIFEST), "--private-dir", str(private), "--image", _IMAGE,
                     "--docker-bin", " ".join(_docker_bin(tmp_path / "docker-state"))])
    assert code == 2
    assert "refusing a run on an image other than the declared one" in capsys.readouterr().err
    assert not private.exists()


def test_cli_refuses_a_subject_other_than_the_declared_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """The image matches; the acquired subject (`test/test` at `v1`) is not
    the declared `claude-power-pack` revision. Refused before any attempt."""
    path = tmp_path / "declaration.json"
    path.write_text(json.dumps(_declaration_data()), encoding="utf-8")
    treatment_source = tmp_path / "treatment"
    treatment_source.mkdir()
    _treatment(treatment_source, monkeypatch)  # installs the fake subject loader
    collection = treatment_source / "subject-collection"
    real_acquire = cc.acquire_collection
    monkeypatch.setattr(cc, "acquire_collection", lambda name, base: real_acquire(name, base, checkout=collection))
    monkeypatch.setattr(cr, "run_calibration", lambda *a, **k: pytest.fail("an attempt ran for the wrong subject"))
    code = cli.main(["calibration-run", str(path), "--private-dir", str(tmp_path / "private"), "--image", _IMAGE,
                     "--docker-bin", " ".join(_docker_bin(tmp_path / "docker-state"))])
    assert code == 2
    assert "the declaration names ('github.com/cooneycw/claude-power-pack'" in capsys.readouterr().err


def _fixture(tmp_path: Path) -> Path:
    fixture = tmp_path / "fixture"
    (fixture / "pkg").mkdir(parents=True)
    (fixture / "pkg" / "code.py").write_text("x = 1\n", encoding="utf-8")
    (fixture / "expected.json").write_text('{"status": "FAIL"}\n', encoding="utf-8")
    return fixture


def test_task_surface_delivers_a_plain_fixture(tmp_path: Path) -> None:
    """The green half of the refusals below."""
    assert cc.task_surface(_fixture(tmp_path)) == {"pkg/code.py": b"x = 1\n"}


@pytest.mark.parametrize("damage", ["answer-alias", "outside-link", "dir-link", "missing", "answer-only"])
def test_red_task_surface_refuses_a_fixture_it_cannot_deliver_honestly(tmp_path: Path, damage: str) -> None:
    """Counter-model review: a symlink could deliver the answer key under
    another name or copy a host file in, and a missing or answer-only fixture
    would start the agent in an empty /work."""
    fixture = _fixture(tmp_path)
    if damage == "answer-alias":
        (fixture / "pkg" / "answer.json").symlink_to(fixture / "expected.json")
    elif damage == "outside-link":
        outside = tmp_path / "host-secret.txt"
        outside.write_text("host\n", encoding="utf-8")
        (fixture / "notes.txt").symlink_to(outside)
    elif damage == "dir-link":
        (fixture / "linked").symlink_to(fixture / "pkg", target_is_directory=True)
    elif damage == "missing":
        fixture = tmp_path / "no-such-fixture"
    else:
        shutil.rmtree(fixture / "pkg")
    with pytest.raises(demo.SubjectRefused):
        cc.task_surface(fixture)


def test_a_task_whose_fixture_delivers_nothing_refuses_before_the_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cc, "task_surface", lambda _d: (_ for _ in ()).throw(demo.SubjectRefused("empty")))
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    with pytest.raises(cr.CalibrationRefused, match="empty"):
        cr.run_calibration(
            _declaration(), run_dir=run_dir, treatment=cr.Treatment({}, "sha256:" + "ab" * 32, None),
            image_digest=_IMAGE_DIGEST, backends=lambda: pytest.fail("a container was requested"),
            argv_for=lambda _s: ["codex"],
        )
    assert list(run_dir.iterdir()) == []


def test_red_an_interrupted_runner_still_accounts_for_every_planned_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Counter-model review: an operator's interrupt used to escape with the
    unrun attempts undisposed. Interrupt the third of six attempts THROUGH the
    runner: the private record must still hold one finalized outcome for each."""
    declaration = _declaration(attempts=3)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    calls: list[str] = []

    def fake_attempt(**kwargs: object) -> dict[str, object]:
        calls.append(str(kwargs["attempt_id"]))
        if len(calls) == 3:
            raise KeyboardInterrupt
        experiment = kwargs["experiment"]
        return trial.finalize(experiment, str(kwargs["attempt_id"]), disposition="unavailable",  # type: ignore[arg-type]
                              reason="fake attempt")

    monkeypatch.setattr(cc, "run_level1_agent_attempt", fake_attempt)
    with pytest.raises(KeyboardInterrupt):
        cr.run_calibration(
            declaration, run_dir=run_dir, treatment=cr.Treatment({}, "sha256:" + "ab" * 32, None),
            image_digest=_IMAGE_DIGEST, backends=lambda: (None, None), argv_for=lambda _s: ["codex"],
        )
    experiment, recorded = mp.read_outcomes(run_dir)
    assert [o.scheduled.arm for o in recorded] == list(declaration.arm_order)
    assert [o.record["disposition"] for o in recorded] == ["unavailable", "unavailable"] + ["not-run"] * 4
    assert all(o.record["disposition"] for o in cr.reconcile(experiment, recorded))
