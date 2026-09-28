"""Tests for issue #150 acceptance item 4: exporting a collection-run
attempt's verified-result(s) (plus the bundle a consumer's bundle rules
need) into a named, operator-chosen directory.

Every attempt here runs against the fake `docker` CLI and the scripted fake
codex client - `tests/test_collection_conformance.py`'s own
`test_happy_path_installs_the_collection_and_grades` fixture, reused
verbatim rather than a second convention for building a real captured,
graded `trial.Experiment`.
"""

from __future__ import annotations

import base64
import json
import sys
import time
from pathlib import Path

import pytest
from fixtures.leak_seeds.judge_seeds import HOME_PATH_LEAK

from skillc import cli, demo, materialize, trial
from skillc import collection_conformance as cc
from skillc import docker_backend as d
from skillc import matched_pilot as mp

FAKE_DOCKER = Path(__file__).resolve().parent / "fixtures" / "docker-backend" / "fake_docker.py"
FAKE_CLIENT = Path(__file__).resolve().parent / "fixtures" / "agent-trial" / "fake_agent_client.py"
GRADER_ROOT = Path(__file__).resolve().parent.parent / "evals" / "level1" / "slug-small-fix"


def _docker_bin(state_dir: Path) -> list[str]:
    return [sys.executable, str(FAKE_DOCKER), "--state", str(state_dir)]


def _backend(base: Path, docker_state: Path) -> d.DockerBackend:
    return d.DockerBackend(image="fake-image:1", base_dir=base, docker_bin=_docker_bin(docker_state))


def _skill_md(name: str) -> str:
    return f"---\nname: {name}\ndescription: A test skill.\n---\nBody text.\n"


def _fixture_collection(tmp_path: Path, skills: dict[str, str]) -> Path:
    collection = tmp_path / "subject-collection"
    skills_root = collection / "skills"
    for name, directory in skills.items():
        skill_dir = skills_root / directory
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(_skill_md(name), encoding="utf-8")
    return collection


def _subject(select: object = "all") -> materialize.Subject:
    return materialize.Subject.from_dict({
        "subject_schema": 1, "locator": "test/test", "revision": "v1", "surface": "codex-skills",
        "skills_root": "skills", "select": select, "client": {"name": "codex", "version": "0.157.1"},
    })


@pytest.fixture(autouse=True)
def _no_network_subject(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(demo, "DEFAULT_SUBJECT", "unused-in-tests")


def _mapped_home(docker_state: Path, attempt_id: str) -> Path:
    name = d._container_name(attempt_id)
    return docker_state / f"{name}.fsroot" / "home" / "candidate"


def _fresh_codex_credential(tmp_path: Path) -> Path:
    def seg(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()
    token = f"{seg(json.dumps({'alg': 'none'}).encode())}.{seg(json.dumps({'exp': int(time.time() + 3600)}).encode())}.sig"
    path = tmp_path / "codex-credential.json"
    path.write_text(json.dumps({"tokens": {"access_token": token}}))
    return path


def _codex_argv(*, home: Path, transcript_relpath: str, copy_solution: Path | None = None) -> list[str]:
    argv = [
        sys.executable, str(FAKE_CLIENT), "--format", "codex-fake", "--home", str(home),
        "--transcript-relpath", transcript_relpath,
    ]
    if copy_solution is not None:
        argv.extend(["--copy-solution", str(copy_solution)])
    return argv


def _run_captured_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, pass_task: bool,
) -> tuple[trial.Experiment, dict[str, object]]:
    """A real, captured, graded `collection_conformance` attempt - PASS when
    `pass_task`, FAIL otherwise (the fake client copies no solution) -
    exactly `test_happy_path_installs_the_collection_and_grades`'s own setup.
    Returns `(experiment, envelope)`, the same pair `cmd_collection_run`
    builds before exporting."""
    base = tmp_path / "work"
    base.mkdir()
    docker_state = tmp_path / "docker-state"
    repo = _fixture_collection(tmp_path, {"tdd": "tdd"})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject(select=["tdd"]))

    acquired = cc.acquire_collection("whatever", base, checkout=repo)
    store = trial.open_store(tmp_path / "store", forbidden=[])
    experiment, attempt_id = cc.plan_collection_attempt("whatever", acquired, store)
    backend = _backend(base, docker_state)
    grading_backend = _backend(base, docker_state)
    home = _mapped_home(docker_state, attempt_id)
    argv = _codex_argv(
        home=home, transcript_relpath=".codex/sessions/2026/01/01/rollout-cc.jsonl",
        copy_solution=(GRADER_ROOT / "reference") if pass_task else None,
    )
    cred_path = _fresh_codex_credential(tmp_path)

    result = cc.run_collection_agent_attempt(
        subject_name="whatever", acquired=acquired, experiment=experiment, attempt_id=attempt_id,
        backend=backend, grading_backend=grading_backend, base=base,
        base_argv=argv, prompt="Fix the slug helper.", timeout=5, credential_explicit_path=cred_path,
    )
    assert result.record["disposition"] == "captured"
    return experiment, cc.evidence_envelope(result)


# ------------------------------------------------------------------- publish


def test_publishes_a_flat_verified_result_and_a_nested_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    experiment, envelope = _run_captured_attempt(tmp_path, monkeypatch, pass_task=True)
    evidence = tmp_path / "evidence"

    code = cli._export_collection_evidence(experiment, envelope, evidence)

    assert code == 0
    top_level = sorted(p.name for p in evidence.iterdir())
    assert top_level == ["bundle", *sorted(p.name for p in evidence.glob("result-*.json"))]
    [result_path] = list(evidence.glob("result-*.json"))
    record = json.loads(result_path.read_text(encoding="utf-8"))
    assert record["kind"] == "verified-result"
    assert record["producer"] == "assembler"
    # The SAME record is also inside bundle/, beside its ledger.
    assert (evidence / "bundle" / result_path.name).read_text() == result_path.read_text()
    assert (evidence / "bundle" / "ledger.json").is_file()
    unexpected, _known = mp.bundle_findings(evidence / "bundle")
    assert unexpected == []


def test_exports_a_failing_arm_too(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The degraded arm's own expected verdict is FAIL - export must not be
    gated on the run passing."""
    experiment, envelope = _run_captured_attempt(tmp_path, monkeypatch, pass_task=False)
    evidence = tmp_path / "evidence"

    code = cli._export_collection_evidence(experiment, envelope, evidence)

    assert code == 0
    [result_path] = list(evidence.glob("result-*.json"))
    record = json.loads(result_path.read_text(encoding="utf-8"))
    assert record["status"] == "FAIL"


def test_a_flat_glob_over_the_published_directory_sees_only_verified_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exact property CPP's `check-behavioral-eval.py` relies on: a
    non-recursive `glob("*.json")` must never see anything but
    `kind: "verified-result"` records."""
    experiment, envelope = _run_captured_attempt(tmp_path, monkeypatch, pass_task=True)
    evidence = tmp_path / "evidence"
    cli._export_collection_evidence(experiment, envelope, evidence)

    for path in evidence.glob("*.json"):
        assert json.loads(path.read_text(encoding="utf-8"))["kind"] == "verified-result"


def test_a_leak_in_the_report_refuses_the_publish(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    experiment, envelope = _run_captured_attempt(tmp_path, monkeypatch, pass_task=True)
    envelope["leaked"] = f"{HOME_PATH_LEAK}/notes.txt"
    evidence = tmp_path / "evidence"

    code = cli._export_collection_evidence(experiment, envelope, evidence)

    assert code == 1
    assert not evidence.exists()


def test_refuses_to_replace_a_directory_holding_a_foreign_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    experiment, envelope = _run_captured_attempt(tmp_path, monkeypatch, pass_task=True)
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "README.md").write_text("not mine\n", encoding="utf-8")

    code = cli._export_collection_evidence(experiment, envelope, evidence)

    assert code == 2
    assert (evidence / "README.md").is_file()  # untouched


def test_refuses_to_publish_through_a_symlink(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    experiment, envelope = _run_captured_attempt(tmp_path, monkeypatch, pass_task=True)
    real = tmp_path / "real-evidence"
    real.mkdir()
    link = tmp_path / "evidence-link"
    link.symlink_to(real)

    code = cli._export_collection_evidence(experiment, envelope, link)

    assert code == 2
    assert list(real.iterdir()) == []


def test_republishing_the_same_experiment_replaces_cleanly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    experiment, envelope = _run_captured_attempt(tmp_path, monkeypatch, pass_task=True)
    evidence = tmp_path / "evidence"
    assert cli._export_collection_evidence(experiment, envelope, evidence) == 0
    assert cli._export_collection_evidence(experiment, envelope, evidence) == 0
    assert len(list(evidence.glob("result-*.json"))) == 1


# ----------------------------------------------------------------- CLI wiring


def test_cli_collection_run_exports_when_evidence_is_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """`cmd_collection_run` end to end with the acquisition/planning/attempt
    replaced (`tests/test_collection_conformance.py`'s own
    `test_cli_wires_the_agent_timeout_backends_and_run_root` convention) -
    the wiring under test here is that `--evidence` reaches the export, not
    the attempt itself."""
    from types import SimpleNamespace

    from skillc import reap

    base = tmp_path / "base"
    base.mkdir()
    experiment, envelope = _run_captured_attempt(tmp_path, monkeypatch, pass_task=True)

    def fake_acquire(name: str, root: Path) -> object:
        return SimpleNamespace(subject=SimpleNamespace(client="codex"))

    def fake_run(**kwargs: object) -> cc.CollectionAgentResult:
        return cc.CollectionAgentResult(
            str(kwargs["subject_name"]), "v1", "codex", envelope["record"],  # type: ignore[arg-type]
            agent_network="bridge",
        )

    monkeypatch.setattr(cc, "acquire_collection", fake_acquire)
    monkeypatch.setattr(demo, "resolve_image_digest", lambda *a, **k: None)
    monkeypatch.setattr(trial, "open_store", lambda path, forbidden: path)
    monkeypatch.setattr(cc, "plan_collection_attempt", lambda *a, **k: (experiment, "a-1"))
    monkeypatch.setattr(cc, "run_collection_agent_attempt", fake_run)
    monkeypatch.setattr(reap, "snapshot", lambda *a, **k: reap.Snapshot(False, frozenset(), frozenset()))
    monkeypatch.setattr(cc, "attributable_leftovers", lambda *a, **k: [])

    evidence = tmp_path / "evidence"
    argv = ["collection-run", "whatever", "--base", str(base), "--evidence", str(evidence)]
    code = cli.main(argv)

    assert code == 0
    assert list(evidence.glob("result-*.json"))
    assert "published" in capsys.readouterr().out


def test_cli_an_export_refusal_takes_priority_over_the_run_s_own_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An export that cannot be trusted to publish is reported distinctly -
    never silently folded into the run's own pass/fail exit code."""
    from types import SimpleNamespace

    from skillc import reap

    base = tmp_path / "base"
    base.mkdir()
    experiment, envelope = _run_captured_attempt(tmp_path, monkeypatch, pass_task=True)

    def fake_acquire(name: str, root: Path) -> object:
        return SimpleNamespace(subject=SimpleNamespace(client="codex"))

    def fake_run(**kwargs: object) -> cc.CollectionAgentResult:
        return cc.CollectionAgentResult(
            str(kwargs["subject_name"]), "v1", "codex", envelope["record"],  # type: ignore[arg-type]
            agent_network="bridge",
        )

    monkeypatch.setattr(cc, "acquire_collection", fake_acquire)
    monkeypatch.setattr(demo, "resolve_image_digest", lambda *a, **k: None)
    monkeypatch.setattr(trial, "open_store", lambda path, forbidden: path)
    monkeypatch.setattr(cc, "plan_collection_attempt", lambda *a, **k: (experiment, "a-1"))
    monkeypatch.setattr(cc, "run_collection_agent_attempt", fake_run)
    monkeypatch.setattr(reap, "snapshot", lambda *a, **k: reap.Snapshot(False, frozenset(), frozenset()))
    monkeypatch.setattr(cc, "attributable_leftovers", lambda *a, **k: [])

    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "foreign.txt").write_text("not mine\n", encoding="utf-8")
    argv = ["collection-run", "whatever", "--base", str(base), "--evidence", str(evidence)]

    assert cli.main(argv) == 2  # not 0 (the run itself PASSed) and not 1


def test_cli_omits_export_entirely_without_evidence_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from skillc import reap

    base = tmp_path / "base"
    base.mkdir()
    experiment, envelope = _run_captured_attempt(tmp_path, monkeypatch, pass_task=True)

    def fake_acquire(name: str, root: Path) -> object:
        return SimpleNamespace(subject=SimpleNamespace(client="codex"))

    def fake_run(**kwargs: object) -> cc.CollectionAgentResult:
        return cc.CollectionAgentResult(
            str(kwargs["subject_name"]), "v1", "codex", envelope["record"],  # type: ignore[arg-type]
            agent_network="bridge",
        )

    monkeypatch.setattr(cc, "acquire_collection", fake_acquire)
    monkeypatch.setattr(demo, "resolve_image_digest", lambda *a, **k: None)
    monkeypatch.setattr(trial, "open_store", lambda path, forbidden: path)
    monkeypatch.setattr(cc, "plan_collection_attempt", lambda *a, **k: (experiment, "a-1"))
    monkeypatch.setattr(cc, "run_collection_agent_attempt", fake_run)
    monkeypatch.setattr(reap, "snapshot", lambda *a, **k: reap.Snapshot(False, frozenset(), frozenset()))
    monkeypatch.setattr(cc, "attributable_leftovers", lambda *a, **k: [])

    argv = ["collection-run", "whatever", "--base", str(base)]
    assert cli.main(argv) == 0  # unaffected by the export path existing at all
