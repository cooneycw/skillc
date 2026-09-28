"""Issue #150 review (contract test against the real consumer): the export
layout's whole justification is what CPP's `check-behavioral-eval.py`
actually does with it - a description of its behaviour is not evidence that
skillc's output satisfies it. This drives the REAL, vendored reader
(`tests/fixtures/cpp-behavioral-eval-consumer/`, see its own `PROVENANCE.md`)
against real `collection-run --evidence` output.

Every attempt here runs against the fake `docker` CLI and the scripted fake
codex client - `tests/test_collection_evidence_export.py`'s own
`_run_captured_attempt` fixture, DUPLICATED rather than imported cross-file
(no `tests/__init__.py` exists, and every other test module in this
repository - `test_collection_conformance.py`, `test_matched_pilot_run.py` -
duplicates this same small setup rather than importing it).
"""

from __future__ import annotations

import base64
import importlib.util
import json
import sys
import time
import types
from pathlib import Path

import pytest

from skillc import cli, demo, materialize, trial
from skillc import collection_conformance as cc
from skillc import docker_backend as d

FAKE_DOCKER = Path(__file__).resolve().parent / "fixtures" / "docker-backend" / "fake_docker.py"
FAKE_CLIENT = Path(__file__).resolve().parent / "fixtures" / "agent-trial" / "fake_agent_client.py"
GRADER_ROOT = Path(__file__).resolve().parent.parent / "evals" / "level1" / "slug-small-fix"
CONSUMER_PATH = Path(__file__).resolve().parent / "fixtures" / "cpp-behavioral-eval-consumer" / "check-behavioral-eval.py"


def _load_consumer() -> types.ModuleType:
    """Import the vendored script by path - it is not a package skillc ships,
    and importing it under its real repository's module name would collide
    with nothing here, but by path is the honest way to load a file this
    project does not own."""
    spec = importlib.util.spec_from_file_location("cpp_check_behavioral_eval", CONSUMER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


consumer = _load_consumer()


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
    `pass_task`, FAIL otherwise (the fake client copies no solution)."""
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


def test_a_normal_arm_export_is_read_as_inconclusive_pending_150_d(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """This is NOT the intended end state - it is what running the REAL
    consumer against a REAL captured, task-PASS collection-run export
    actually does TODAY, and it is `INCONCLUSIVE`, not `PASS`. #139 (agent-
    path readiness) is CLOSED: the owner's ruling was that
    `installation-ready` stays a mandatory UNKNOWN on the agent-observation
    path, full stop. What turns a normal arm into `PASS` is #150's own
    acceptance item 5, tracked as 150-D (an arm that installs a collection
    gets a real installation receipt from codex's in-container discovery
    listing, not an agent-observation one) - so a mandatory criterion is
    never `SATISFIED` here today, and the consumer's own derivation
    (`derive_status`: any non-SATISFIED mandatory criterion yields
    `INCONCLUSIVE`) can never reach `PASS` through this path until 150-D
    lands. This subject is CODEX-shaped deliberately (`_subject`'s own
    `surface="codex-skills"`): 150-D's design still leaves a Claude Code arm
    reading `INCONCLUSIVE` (no model-free listing), so only a codex arm has
    anything for 150-D to flip. Once 150-D lands, this test's assertion
    should change to `consumer.VERDICTS["pass"]` - leaving it asserting
    `INCONCLUSIVE` past that point would hide the fix rather than prove it."""
    experiment, envelope = _run_captured_attempt(tmp_path, monkeypatch, pass_task=True)
    evidence = tmp_path / "evidence"
    assert cli._export_collection_evidence(experiment, envelope, evidence) == 0

    code = consumer.main(["--dir", str(evidence)])

    assert code == consumer.VERDICTS["inconclusive"]
    assert code != consumer.VERDICTS["pass"]


def test_a_degraded_arm_export_is_read_as_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    experiment, envelope = _run_captured_attempt(tmp_path, monkeypatch, pass_task=False)
    evidence = tmp_path / "evidence"
    assert cli._export_collection_evidence(experiment, envelope, evidence) == 0

    code = consumer.main(["--dir", str(evidence)])

    assert code == consumer.VERDICTS["failure"]
    assert code != 0


def test_a_non_result_file_at_the_top_level_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The red case for "why split" (behavioral-eval-export.md): CPP's own
    reader refuses the FIRST file that does not parse as a `verified-result`,
    in sorted order - so anything but a result at the top level breaks it,
    which is exactly why `bundle/` exists as a separate, non-recursed-into
    directory rather than a flat bundle beside the results."""
    experiment, envelope = _run_captured_attempt(tmp_path, monkeypatch, pass_task=True)
    evidence = tmp_path / "evidence"
    assert cli._export_collection_evidence(experiment, envelope, evidence) == 0
    # A flat, non-result file dropped at the top level, sorted before the
    # real result - exactly what a flat, undifferentiated bundle would have
    # looked like without the split.
    (evidence / "0-ledger.json").write_text('{"kind": "trial-ledger"}', encoding="utf-8")

    code = consumer.main(["--dir", str(evidence)])

    assert code == consumer.VERDICTS["unreadable"]
    assert code not in (consumer.VERDICTS["pass"], consumer.VERDICTS["failure"])


def test_an_absent_directory_is_read_as_absent(tmp_path: Path) -> None:
    code = consumer.main(["--dir", str(tmp_path / "does-not-exist")])
    assert code == consumer.VERDICTS["absent"]
