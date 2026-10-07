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
import dataclasses
import json
import shutil
import sys
import time
from collections.abc import Iterator, Mapping, Sequence
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
    `attempts` re-derives the seeded order for a smaller schedule - and (#323)
    the approval's own recorded size along with it, since this helper builds
    a fresh, self-consistent, approved-at-THIS-size declaration for test
    speed, never the "edited after approval" case `require_approved` now
    refuses."""
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert isinstance(data["approval"], dict), "the committed declaration is expected to carry its approval"
    if not approved:
        data["approval"] = None
    data["shared"]["image"]["digest"] = _IMAGE_DIGEST
    if attempts is not None:
        names = [a["name"] for a in data["arms"]]
        data["attempts_per_arm"] = attempts
        data["arm_order"]["sequence"] = calibration.derive_arm_order(data["arm_order"]["seed"], names, attempts)
        if isinstance(data["approval"], dict):
            data["approval"]["attempts_per_arm"] = attempts
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
    arm_extra: Mapping[str, Sequence[str]] | None = None,
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
        argv.extend((arm_extra or {}).get(scheduled.arm, ()))
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
        TREATMENT_ARM: {"scheduled": 3, "primary": {"PASS": 3}, "model_ineligible": 0, "opened": 0, "observed": 3},
        calibration.BASELINE_ARM: {"scheduled": 3, "primary": {"PASS": 3}, "model_ineligible": 0, "opened": 0, "observed": 3},
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
        assert {rel: data for rel, data, _ in cc.task_surface(fixture)} == {
            p.relative_to(fixture).as_posix(): p.read_bytes() for p in (fixture / "src").rglob("*") if p.is_file()
        }
    level3 = {rel: data for rel, data, _ in cc.task_surface(TASK / "fixture")}
    assert "expected.json" not in level3
    assert {"ci/verify.py", "pyproject.toml", "slugkit/core.py", "tests/test_core.py"} <= set(level3)
    assert not (TASK / "fixture" / "src").exists()  # old src-only walk was empty


def test_a_treatment_that_installs_nothing_is_refused() -> None:
    acquired = cc.AcquiredCollection(
        subject=argparse.Namespace(locator="test/test"), source=None, files=[], repo=None,  # type: ignore[arg-type]
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
    assert cc.task_surface(_fixture(tmp_path)) == [("pkg/code.py", b"x = 1\n", False)]


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


# ------------------------------------------- three arms, B/N/P (#231, for #203)


def _three_arm_declaration() -> calibration.CalibrationDeclaration:
    """The committed declaration plus a provided-skill arm: the same subject
    as the treatment, told to read `tdd` (the test collection's one skill)."""
    data = _declaration_data(attempts=3)
    arms = data["arms"]
    assert isinstance(arms, list)
    arms.append({"name": "provided", "subject": dict(arms[0]["subject"]), "treatment": "told to read tdd",
                 "instruction": "Before you start, read the `tdd` skill.", "named_skills": ["tdd"]})
    names = [a["name"] for a in arms]
    data["arm_order"]["sequence"] = calibration.derive_arm_order(  # type: ignore[index]
        data["arm_order"]["seed"], names, 3)  # type: ignore[index]
    return calibration.parse_declaration(data)


def test_three_arms_differ_only_by_install_and_the_provided_arm_s_instruction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#231: the provided arm installs exactly what the natural arm does and
    its prompt is goal.md plus the declared instruction; the other two arms
    get goal.md verbatim. Uptake is reported per arm as k/n, and the
    provided arm's named-skill count beside it."""
    seen: list[dict[str, object]] = []
    real = cc.run_level1_agent_attempt

    def spy(**kwargs: object) -> dict[str, object]:
        seen.append(dict(kwargs))
        return real(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(cc, "run_level1_agent_attempt", spy)
    declaration = _three_arm_declaration()
    experiment, outcomes, _, treatment = _run(
        tmp_path, monkeypatch, declaration=declaration, arm_extra={"provided": ["--plant-skill", "tdd"]},
        solve_arms=(TREATMENT_ARM, calibration.BASELINE_ARM, "provided"),
    )

    assert len(seen) == 9
    arm_of = {o.scheduled.attempt_id: o.scheduled.arm for o in outcomes}
    goal = (TASK / "goal.md").read_text(encoding="utf-8")
    for call in seen:
        arm = arm_of[str(call["attempt_id"])]
        if arm == "provided":
            assert call["prompt"] == f"{goal.rstrip()}\n\nBefore you start, read the `tdd` skill.\n"
            assert call["extra_home_files"] == treatment.home_files
        else:
            assert call["prompt"] == goal

    report = cr.build_report(
        experiment, cr.reconcile(experiment, outcomes), declared_model="gpt-6-astra", declared_effort="high",
        named_skills=cr.named_skills_by_arm(declaration),
    )
    arms = report["arms"]
    assert isinstance(arms, dict)
    assert (arms["provided"]["opened"], arms["provided"]["observed"], arms["provided"]["named_opened"]) == (3, 3, 3)
    assert (arms[TREATMENT_ARM]["opened"], arms[TREATMENT_ARM]["observed"]) == (0, 3)
    assert "named_opened" not in arms[TREATMENT_ARM]
    for entry in _entries(report):
        assert entry["skill_opened"] is (entry["arm"] == "provided")
        assert ("named_skill_opened" in entry) is (entry["arm"] == "provided")
    assert "opened=3/3 named_opened=3" in cr.paste_back(report)


def test_a_provided_arm_naming_a_skill_the_install_lacks_is_refused_before_any_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Counter-model review on #231: P told to read a skill the treatment
    does not install would turn its zero uptake into a configuration error."""
    data = json.loads(json.dumps(_three_arm_declaration().data))
    data["arms"][2]["named_skills"] = ["not-installed"]
    data["arms"][2]["instruction"] = "Before you start, read the `not-installed` skill."
    declaration = calibration.parse_declaration(data)
    treatment = _treatment(tmp_path, monkeypatch)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    with pytest.raises(cr.CalibrationRefused, match=r"names \['not-installed'\]"):
        cr.run_calibration(
            declaration, run_dir=run_dir, treatment=treatment, image_digest=_IMAGE_DIGEST,
            backends=lambda: (None, None), argv_for=lambda s: [],
        )
    assert list(run_dir.iterdir()) == []


@pytest.mark.parametrize("obs", [
    {"status": "unknown", "transcript_files_found": 1, "prompt_delivered": True, "skill_invocations": []},
    {"transcript_files_found": 0, "prompt_delivered": False, "skill_invocations": []},
    {"transcript_files_found": 2, "prompt_delivered": False, "skill_invocations": []},
    {"transcript_files_found": 1, "prompt_delivered": False, "skill_invocations": ["tdd"]},  # another attempt's
    {},
])
def test_an_unconfirmed_observation_is_unknown_uptake_never_false(obs: dict[str, object]) -> None:
    """Counter-model review on #231, red before the fix: the reader records
    `skill_invocations=[]` when it found no transcript or several, and that
    read as 'observed, not opened'."""
    assert cr.observation_confirmed(obs) is False
    assert cr._opened(obs.get("skill_invocations"), confirmed=cr.observation_confirmed(obs)) == cr.UNKNOWN
    assert cr._opened(obs.get("skill_invocations"), ("tdd",), confirmed=cr.observation_confirmed(obs)) == cr.UNKNOWN


def test_a_confirmed_observation_with_no_invocation_is_not_opened() -> None:
    obs = {"status": "captured", "transcript_files_found": 1, "prompt_delivered": True, "skill_invocations": []}
    assert cr.observation_confirmed(obs) is True
    assert cr._opened(obs["skill_invocations"], confirmed=True) is False


def test_an_unobserved_attempt_is_neither_opened_nor_not_opened() -> None:
    """The uptake rate's denominator counts only attempts whose invocations
    were recorded: an attempt that never ran is UNKNOWN, never a 'not opened'."""
    assert cr._opened(cr.UNKNOWN) == cr.UNKNOWN
    assert cr._opened(None, ("tdd",)) == cr.UNKNOWN
    assert cr._opened([]) is False
    assert cr._opened(["qa-test"], ("tdd",)) is False
    assert cr._opened(["tdd"], ("tdd",)) is True
    summary = cr.summarize_arms([
        {"arm": "n", "skill_opened": True}, {"arm": "n", "skill_opened": False},
        {"arm": "n", "skill_opened": cr.UNKNOWN},
    ])["n"]
    assert (summary["opened"], summary["observed"], summary["scheduled"]) == (1, 2, 3)



# ----------------------------------------------- expanded-instruction lane (#274)

#: Matches `_treatment`'s real fixture exactly: `skills/tdd/SKILL.md`'s body
#: after frontmatter is literally "Body.\n".
_TDD_BODY = "Body.\n"


def _prose_inventory(tmp_path: Path, subject: Mapping[str, object]) -> Path:
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps({
        "subject": {"locator": subject["locator"], "revision": subject["revision"]},
        "treatment_question": "prose",
        "helper_parity": {"common": [], "treatment": [], "bundled": []},
        "skills": [{"name": "tdd", "body_digest": materialize.sha256_bytes(_TDD_BODY.encode("utf-8"))}],
    }), encoding="utf-8")
    return path


def _expanded_instruction_run_declaration(tmp_path: Path) -> calibration.CalibrationDeclaration:
    """Baseline + S (explicit, names tdd) + E (the SAME body inlined) - the
    same treatment subject `_treatment` installs, so this dry run proves
    scheduling/accounting for the new lane without a second fixture."""
    data = _declaration_data(attempts=3)
    data["lane"] = calibration.EXPANDED_INSTRUCTION_LANE
    arms = data["arms"]
    assert isinstance(arms, list)
    subject = dict(arms[0]["subject"])
    inventory = str(_prose_inventory(tmp_path, subject))
    new_arms: list[object] = [arms[1],  # baseline
                              {"name": "explicit-skill", "subject": subject, "treatment": "told to read tdd",
                               "instruction": "Before you start, read the `tdd` skill.", "named_skills": ["tdd"],
                               "inventory": inventory},
                              {"name": "expanded-instruction", "subject": subject,
                               "treatment": "given tdd's body inline", "instruction": _TDD_BODY,
                               "inventory": inventory}]
    data["arms"] = new_arms
    names = [a["name"] for a in new_arms if isinstance(a, dict)]
    data["arm_order"] = {"seed": 7, "sequence": calibration.derive_arm_order(7, names, 3)}
    return calibration.parse_declaration(data)


def test_expanded_instruction_lane_dry_run_schedules_and_reconciles_all_three_arms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Acceptance item 4: deterministic dry run, no CPP installation (the
    fake client never touches a real one) - seeded ordering, all-attempt
    reconciliation and per-arm accounting work for the new arm shape with
    NO change to run_calibration/build_report, because the prompt-assembly
    code is already generic over any declared `instruction` string."""
    declaration = _expanded_instruction_run_declaration(tmp_path)
    assert declaration.lane == calibration.EXPANDED_INSTRUCTION_LANE
    seen: list[dict[str, object]] = []
    real = cc.run_level1_agent_attempt

    def spy(**kwargs: object) -> dict[str, object]:
        seen.append(dict(kwargs))
        return real(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(cc, "run_level1_agent_attempt", spy)
    experiment, outcomes, _, treatment = _run(
        tmp_path, monkeypatch, declaration=declaration,
        solve_arms=(calibration.BASELINE_ARM, "explicit-skill", "expanded-instruction"),
    )

    assert len(seen) == 9  # 3 arms x 3 attempts, baseline readiness included
    arm_of = {o.scheduled.attempt_id: o.scheduled.arm for o in outcomes}
    goal = (TASK / "goal.md").read_text(encoding="utf-8")
    for call in seen:
        arm = arm_of[str(call["attempt_id"])]
        if arm == "explicit-skill":
            assert call["prompt"] == f"{goal.rstrip()}\n\nBefore you start, read the `tdd` skill.\n"
            assert call["extra_home_files"] == treatment.home_files
        elif arm == "expanded-instruction":
            # The inlined body, byte-identical to what `explicit-skill` would
            # read from the skill itself (checked once already in
            # test_calibration.py; this proves it also reaches the prompt).
            assert call["prompt"] == f"{goal.rstrip()}\n\n{_TDD_BODY}\n"
            assert call["extra_home_files"] == treatment.home_files
        else:
            assert call["prompt"] == goal

    report = cr.build_report(
        experiment, cr.reconcile(experiment, outcomes), declared_model="gpt-6-astra", declared_effort="high",
        named_skills=cr.named_skills_by_arm(declaration),
    )
    arms = report["arms"]
    assert isinstance(arms, dict)
    # Every attempt reconciles: all-attempt accounting, not merely the ones
    # that happened to succeed.
    assert {a: v["scheduled"] for a, v in arms.items()} == {
        calibration.BASELINE_ARM: 3, "explicit-skill": 3, "expanded-instruction": 3,
    }
    # E has `named_skills` absent by design (nothing to name - the content
    # is inline), so it carries no named_opened accounting; S does.
    assert "named_opened" in arms["explicit-skill"]
    assert "named_opened" not in arms["expanded-instruction"]


# --------------------------------------------------- profile-closure fields (#334)


def test_run_calibration_threads_closure_fields_for_the_treated_arm_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """skillc#334: `run_calibration`'s own `run_attempt`
    must thread `Treatment.verify_home_files`/`.preflight_tools`/
    `.gate_entrypoint` into `cc.run_level1_agent_attempt` for a TREATED
    arm, and pass none of them (empty/`None`, exactly like `extra_home_
    files`/`receipt_context` already do) for the baseline - never a
    treatment whose closure is only partially opted in. Captured at the
    SAME spy boundary `test_both_arms_run_one_path_and_differ_only_in_
    what_is_installed` already uses, so this is a wiring test only: the
    treated attempt is free to end up `unavailable` downstream (this
    sentinel closure was never actually validated against a real
    profile), which does not affect what was threaded into the call."""
    seen: list[dict[str, object]] = []
    real = cc.run_level1_agent_attempt

    def spy(**kwargs: object) -> dict[str, object]:
        seen.append(dict(kwargs))
        return real(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(cc, "run_level1_agent_attempt", spy)

    declaration = _declaration(attempts=1)
    treatment = _treatment(tmp_path, monkeypatch)
    sentinel_digest = "sha256:" + "a" * 64
    sentinel_entrypoint = ".codex/skills/tdd/SKILL.md"  # a real delivered path, chosen as a plausible sentinel
    treatment = dataclasses.replace(
        treatment,
        verify_home_files={sentinel_entrypoint: sentinel_digest},
        preflight_tools=({"id": "tool-sentinel", "probes": []},),
        gate_entrypoint=sentinel_entrypoint,
    )
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    docker_state = tmp_path / "docker-state"

    def backends() -> tuple[object, object]:
        make = lambda: d.DockerBackend(
            image=_IMAGE, base_dir=run_dir, docker_bin=_docker_bin(docker_state), daemon_timeout=_FAKE_DAEMON_TIMEOUT,
        )
        return make(), make()

    def argv_for(scheduled: mp.ScheduledAttempt) -> list[str]:
        home = docker_state / f"{d._container_name(scheduled.attempt_id)}.fsroot" / "home" / "candidate"
        return [
            sys.executable, str(FAKE_CLIENT), "--format", "codex-fake", "--home", str(home),
            "--transcript-relpath", f".codex/sessions/2026/01/01/rollout-{scheduled.attempt_id}.jsonl",
        ]

    _, outcomes = cr.run_calibration(
        declaration, run_dir=run_dir, treatment=treatment, image_digest=_IMAGE_DIGEST,
        backends=backends, argv_for=argv_for, credential_explicit_path=_fresh_codex_credential(tmp_path),
    )

    assert len(seen) == 2  # one baseline, one treated - attempts=1
    arm_of = {o.scheduled.attempt_id: o.scheduled.arm for o in outcomes}
    saw_baseline = saw_treated = False
    for call in seen:
        if arm_of[str(call["attempt_id"])] == calibration.BASELINE_ARM:
            saw_baseline = True
            assert call["verify_home_files"] is None
            assert call["preflight_tools"] is None
            assert call["gate_entrypoint"] is None
        else:
            saw_treated = True
            assert call["verify_home_files"] == {sentinel_entrypoint: sentinel_digest}
            assert call["preflight_tools"] == ({"id": "tool-sentinel", "probes": []},)
            assert call["gate_entrypoint"] == sentinel_entrypoint
    assert saw_baseline and saw_treated
