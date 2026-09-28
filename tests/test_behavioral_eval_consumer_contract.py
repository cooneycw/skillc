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
import shutil
import sys
import time
import types
from collections.abc import Sequence
from pathlib import Path

import pytest

from skillc import cli, demo, materialize, trial
from skillc import collection_conformance as cc
from skillc import docker_backend as d

FAKE_DOCKER = Path(__file__).resolve().parent / "fixtures" / "docker-backend" / "fake_docker.py"
FAKE_CLIENT = Path(__file__).resolve().parent / "fixtures" / "agent-trial" / "fake_agent_client.py"
CODEX_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "codex-subject"
GRADER_ROOT = Path(__file__).resolve().parent.parent / "evals" / "level1" / "slug-small-fix"
FINISH_CLOSE_REF_ROOT = Path(__file__).resolve().parent.parent / "evals" / "level1" / "finish-close-ref"
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


_BACKEND_IMAGE = "fake-image:1"
_BACKEND_IMAGE_DIGEST = f"sha256:fake-digest-for-{_BACKEND_IMAGE}"


def _docker_bin(state_dir: Path) -> list[str]:
    return [sys.executable, str(FAKE_DOCKER), "--state", str(state_dir)]


def _backend(base: Path, docker_state: Path) -> d.DockerBackend:
    return d.DockerBackend(image=_BACKEND_IMAGE, base_dir=base, docker_bin=_docker_bin(docker_state))


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


def _fake_codex_listing(tmp_path: Path, mode: str = "normal", **config: str) -> list[str]:
    """`tests/fixtures/codex-subject/fake_codex.py`, copied fresh per test -
    duplicated from `test_collection_conformance.py`'s own helper of the same
    name, per this file's own stated convention (module docstring). A bare
    `"codex"` in `listing_client_argv` would need the real binary on `PATH`,
    which this fixture never provides; this is the scripted stand-in
    #150-D's `InstallationReceiptContext.listing_client_argv` exists for."""
    script = tmp_path / "listing-client" / "fake_codex.py"
    script.parent.mkdir(exist_ok=True)
    shutil.copy(CODEX_FIXTURE / "fake_codex.py", script)
    script.with_suffix(".mode").write_text(json.dumps({"mode": mode, **config}), encoding="utf-8")
    return [sys.executable, str(script)]


def _run_captured_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, pass_task: bool,
    listing_client_argv: Sequence[str] | None = None,
) -> tuple[trial.Experiment, dict[str, object]]:
    """A real, captured, graded `collection_conformance` attempt - PASS when
    `pass_task`, FAIL otherwise (the fake client copies no solution).

    `listing_client_argv` (#150-D): `None` (the default, used by every test
    predating 150-D) leaves the receipt's discovery listing pointed at the
    bare `codex` name, which this sandbox cannot resolve - the receipt is
    still built (the subject is codex-shaped) but its listing comes back
    UNMEASURED, so `installation-ready` stays a mandatory UNKNOWN and the
    consumer reads INCONCLUSIVE whatever `pass_task` says. Passing the fake
    listing client is what actually exercises 150-D's SATISFIED path."""
    base = tmp_path / "work"
    base.mkdir()
    docker_state = tmp_path / "docker-state"
    repo = _fixture_collection(tmp_path, {"tdd": "tdd"})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject(select=["tdd"]))

    acquired = cc.acquire_collection("whatever", base, checkout=repo)
    store = trial.open_store(tmp_path / "store", forbidden=[])
    experiment, attempt_id = cc.plan_collection_attempt(
        "whatever", acquired, store, image_digest=_BACKEND_IMAGE_DIGEST,
    )
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
        listing_client_argv=listing_client_argv,
    )
    assert result.record["disposition"] == "captured"
    return experiment, cc.evidence_envelope(result)


def _run_finish_close_ref_attempt_with_listing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> tuple[trial.Experiment, dict[str, object]]:
    """The 150-D flip, on the task the operator named: finish-close-ref
    (never slug-small-fix - #150's own discriminating task), a codex arm
    that installs a declared collection, a WORKING discovery listing (the
    scripted `fake_codex.py` stand-in, not the bare unresolvable `codex`
    name `_run_captured_attempt`'s other callers accept), and a candidate
    that writes the task's own reference solution so the grade itself is
    PASS too - both halves have to hold for the consumer to read PASS."""
    base = tmp_path / "work"
    base.mkdir()
    docker_state = tmp_path / "docker-state"
    repo = _fixture_collection(tmp_path, {"tdd": "tdd"})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject(select=["tdd"]))

    acquired = cc.acquire_collection("whatever", base, checkout=repo)
    store = trial.open_store(tmp_path / "store", forbidden=[])
    experiment, attempt_id = cc.plan_collection_attempt(
        "whatever", acquired, store, task_root=FINISH_CLOSE_REF_ROOT, image_digest=_BACKEND_IMAGE_DIGEST,
    )
    backend = _backend(base, docker_state)
    grading_backend = _backend(base, docker_state)
    home = _mapped_home(docker_state, attempt_id)
    argv = _codex_argv(
        home=home, transcript_relpath=".codex/sessions/2026/01/01/rollout-fcr.jsonl",
        copy_solution=FINISH_CLOSE_REF_ROOT / "reference",
    )
    cred_path = _fresh_codex_credential(tmp_path)
    listing_client_argv = _fake_codex_listing(tmp_path, mode="normal")

    result = cc.run_collection_agent_attempt(
        subject_name="whatever", acquired=acquired, experiment=experiment, attempt_id=attempt_id,
        backend=backend, grading_backend=grading_backend, base=base,
        base_argv=argv, task_root=FINISH_CLOSE_REF_ROOT, timeout=5, credential_explicit_path=cred_path,
        listing_client_argv=listing_client_argv,
    )
    assert result.record["disposition"] == "captured"
    return experiment, cc.evidence_envelope(result)


def test_a_finish_close_ref_codex_arm_with_a_satisfied_listing_flips_the_consumer_to_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The vendored-consumer flip 150-D exists to deliver: once the discovery
    listing actually runs and comes back SATISFIED (not the UNMEASURED result
    `test_a_normal_arm_export_is_read_as_inconclusive_pending_150_d` gets from
    an unresolvable bare `codex`), `installation-ready` is a real mandatory
    SATISFIED criterion instead of a mandatory UNKNOWN - and CPP's real,
    vendored `check-behavioral-eval.py`, reading nothing but the exported
    verified-result artifact, re-derives PASS from it. This is the read side
    of #150's acceptance item 5; the write side (`readiness_from_discovery_
    listings`, `_build_discovery_receipt`) is covered directly in
    `test_agent_trial_readiness.py` and `test_collection_conformance.py`."""
    experiment, envelope = _run_finish_close_ref_attempt_with_listing(tmp_path, monkeypatch)
    evidence = tmp_path / "evidence"
    assert cli._export_collection_evidence(experiment, envelope, evidence) == 0

    code = consumer.main(["--dir", str(evidence)])

    assert code == consumer.VERDICTS["pass"], consumer.VERDICTS
    assert code == 0


def test_a_normal_arm_export_is_read_as_inconclusive_pending_150_d(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """150-D has landed, and this test's assertion does NOT change to `PASS`
    - it turned out to name the wrong lever. `_run_captured_attempt` here
    passes no `listing_client_argv`, so the receipt's discovery listing is
    pointed at the bare, unresolvable `codex` name: a receipt IS built (the
    subject is codex-shaped) but its listing comes back UNMEASURED, so
    `installation-ready` is a real mandatory criterion now - just an UNKNOWN
    one, not a SATISFIED one - and the consumer still reads `INCONCLUSIVE`.
    That is 150-D behaving correctly on an arm whose listing genuinely could
    not be obtained; it is a *different* fact from #139's closed ruling,
    which this docstring used to conflate it with. The actual flip - a
    working discovery listing, SATISFIED, re-derived to `PASS` - is
    `test_a_finish_close_ref_codex_arm_with_a_satisfied_listing_flips_the_
    consumer_to_pass` above, which supplies `listing_client_argv` and is why
    this one still cannot reach `PASS`: leaving both assertions unchanged
    would say 150-D changed nothing here, and it does - it just changes what
    `INCONCLUSIVE` means, not whether it appears."""
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
