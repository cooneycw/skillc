"""End-to-end test for `skillc/configuration_compare.py`'s `from_collection_run`
adapter (issue #13, review finding): unlike `test_configuration_compare.py`
(synthetic fixture records throughout, by design), this file drives TWO REAL
`collection-run` attempts through the fake docker CLI and the scripted fake
agent client (`tests/test_collection_conformance.py`'s own fixtures, reused
rather than duplicated) and adapts their ACTUAL saved output - proving the
adapter agrees with what `collection-run` really produces, not merely with
itself.

`image_digest` and `timeout_seconds` are supplied to the adapter as explicit
keyword arguments in every call below, never read from either real artifact -
see `from_collection_run`'s own docstring for why: neither
`collection_conformance.evidence_envelope()` nor the exported VERIFIED_RESULT
persists them today. That gap is real and reported; it is not filled in with
a default here.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

from skillc import collection_conformance as cc
from skillc import configuration_compare as ccmp
from skillc import demo, trial, verify
from skillc import docker_backend as d
from skillc import outcome_report as orpt

FAKE_DOCKER = Path(__file__).resolve().parent / "fixtures" / "docker-backend" / "fake_docker.py"
FAKE_CLIENT = Path(__file__).resolve().parent / "fixtures" / "agent-trial" / "fake_agent_client.py"
GRADER_ROOT = Path(__file__).resolve().parent.parent / "evals" / "level1" / "slug-small-fix"

_BACKEND_IMAGE = "fake-image:1"
_BACKEND_IMAGE_DIGEST = f"sha256:fake-digest-for-{_BACKEND_IMAGE}"


def _docker_bin(state_dir: Path) -> list[str]:
    return [sys.executable, str(FAKE_DOCKER), "--state", str(state_dir)]


def _backend(base: Path, docker_state: Path) -> d.DockerBackend:
    return d.DockerBackend(image=_BACKEND_IMAGE, base_dir=base, docker_bin=_docker_bin(docker_state))


def _skill_md(name: str) -> str:
    return f"---\nname: {name}\ndescription: A test skill.\n---\nBody text.\n"


def _fixture_collection(tmp_path: Path, name: str) -> Path:
    collection = tmp_path / name
    skill_dir = collection / "skills" / "tdd"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(_skill_md("tdd"), encoding="utf-8")
    return collection


def _codex_argv(*, home: Path, transcript_relpath: str) -> list[str]:
    return [
        sys.executable, str(FAKE_CLIENT), "--format", "codex-fake", "--home", str(home),
        "--transcript-relpath", transcript_relpath, "--copy-solution", str(GRADER_ROOT / "reference"),
        "-m", "gpt-6-astra",
    ]


def _mapped_home(docker_state: Path, attempt_id: str) -> Path:
    name = d._container_name(attempt_id)
    return docker_state / f"{name}.fsroot" / "home" / "candidate"


@pytest.fixture(autouse=True)
def _no_network_subject(monkeypatch: pytest.MonkeyPatch) -> None:
    """Guards against `demo.DEFAULT_SUBJECT` (a real `evals/subjects/` entry)
    ever being read for real - every test here supplies its own subject via
    `monkeypatch.setattr(demo, "load_demo_subject", ...)` and a local
    `checkout=`, mirroring `tests/test_collection_conformance.py`'s own
    fixture of the same name."""
    monkeypatch.setattr(demo, "DEFAULT_SUBJECT", "unused-in-tests")


def _fresh_codex_credential(tmp_path: Path) -> Path:
    import base64

    def seg(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()
    token = f"{seg(json.dumps({'alg': 'none'}).encode())}.{seg(json.dumps({'exp': int(time.time() + 3600)}).encode())}.sig"
    path = tmp_path / "codex-credential.json"
    path.write_text(json.dumps({"tokens": {"access_token": token}}))
    return path


def _run_real_attempt(
    tmp_path: Path, base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
    *, collection_name: str, transcript_relpath: str,
) -> tuple[cc.CollectionAgentResult, trial.Experiment]:
    """A real collection-run attempt, PASS arm (the committed reference
    solution), against Level 1's default task - the same fake-backend
    pattern test_collection_conformance.py's own happy-path test uses."""
    repo = _fixture_collection(tmp_path, collection_name)
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: cc.materialize.Subject.from_dict({
        "subject_schema": 1, "locator": "test/test", "revision": "v1", "surface": "codex-skills",
        "skills_root": "skills", "select": ["tdd"], "client": {"name": "codex", "version": "0.157.1"},
    }))
    acquired = cc.acquire_collection(collection_name, base, checkout=repo)
    store = trial.open_store(tmp_path / f"{collection_name}-store", forbidden=[])
    experiment, attempt_id = cc.plan_collection_attempt(
        collection_name, acquired, store, image_digest=_BACKEND_IMAGE_DIGEST,
    )
    home = _mapped_home(docker_state, attempt_id)
    argv = _codex_argv(home=home, transcript_relpath=transcript_relpath)
    result = cc.run_collection_agent_attempt(
        subject_name=collection_name, acquired=acquired, experiment=experiment, attempt_id=attempt_id,
        backend=_backend(base, docker_state), grading_backend=_backend(base, docker_state), base=base,
        base_argv=argv, prompt="Fix the slug helper.", timeout=5,
        credential_explicit_path=_fresh_codex_credential(tmp_path),
    )
    graded = result.record.get("graded")
    assert isinstance(graded, dict) and graded.get("status") == "PASS", (
        f"the real attempt did not pass grading; nothing to adapt: {graded}"
    )
    return result, experiment


def _adapt(
    result: cc.CollectionAgentResult, experiment: trial.Experiment, tmp_path: Path, name: str,
    *, image_digest: str, timeout_seconds: float,
) -> Path:
    """Reads the REAL VERIFIED_RESULT `collection-run` actually stored (the
    same file a real `--evidence` export would publish as `result-*.json`) -
    for `grader.id`/`grader.revision` ONLY. `outcome_dimensions` is built
    from `record["graded"]["criteria"]` instead (task-only - see
    `from_collection_run`'s own docstring for why `verified_result["criteria"]`
    is the WRONG source: it mixes in the verifier's own `installation-ready`
    criterion, found by running this test against real output and getting a
    real INCONCLUSIVE where the task's own grade is genuinely PASS)."""
    envelope = cc.evidence_envelope(result)
    graded = result.record.get("graded")
    assert isinstance(graded, dict)
    result_id = graded.get("result_id")
    assert isinstance(result_id, str)
    verified_result = json.loads((experiment.root / f"result-{result_id}.json").read_text(encoding="utf-8"))
    assert verified_result.get("kind") == "verified-result", "not the real stored artifact - test setup is wrong"

    dimensions = verify.GraderDef.load(GRADER_ROOT).dimensions  # {} today - Level 1 declares none
    task_criteria = [c for c in graded["criteria"] if isinstance(c, dict)]
    outcome_dimensions = orpt.build(task_criteria, dimensions).as_dict()

    record = ccmp.from_collection_run(
        envelope, verified_result, outcome_dimensions,
        image_digest=image_digest, timeout_seconds=timeout_seconds,
    )
    path = tmp_path / name
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


def test_a_real_matched_pair_compares_and_a_real_mismatched_pair_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_a, docker_state_a = tmp_path / "work-a", tmp_path / "docker-state-a"
    base_a.mkdir()
    base_b, docker_state_b = tmp_path / "work-b", tmp_path / "docker-state-b"
    base_b.mkdir()

    result_a, experiment_a = _run_real_attempt(
        tmp_path, base_a, docker_state_a, monkeypatch,
        collection_name="collection-a", transcript_relpath=".codex/sessions/2026/01/01/rollout-a.jsonl",
    )
    result_b, experiment_b = _run_real_attempt(
        tmp_path, base_b, docker_state_b, monkeypatch,
        collection_name="collection-b", transcript_relpath=".codex/sessions/2026/01/01/rollout-b.jsonl",
    )

    # Same real image digest for both - a genuinely MATCHED pair, varying
    # only `collection` (exactly what the two real runs actually differ on).
    path_a = _adapt(result_a, experiment_a, tmp_path, "a.json", image_digest=_BACKEND_IMAGE_DIGEST, timeout_seconds=5)
    path_b = _adapt(result_b, experiment_b, tmp_path, "b-matched.json", image_digest=_BACKEND_IMAGE_DIGEST, timeout_seconds=5)

    record_a = ccmp.load_record(path_a)
    record_b_matched = ccmp.load_record(path_b)
    assert record_a.task_id == record_b_matched.task_id == "slug-small-fix"
    assert record_a.client == record_b_matched.client == "codex"
    assert record_a.collection == "collection-a"
    assert record_b_matched.collection == "collection-b"

    comparison = ccmp.compare(record_a, record_b_matched, "collection")
    per_dimension = comparison["per_dimension"]
    assert isinstance(per_dimension, dict)
    # Level 1's real grader.json declares no dimensions (PR1's own,
    # deliberate choice) - every criterion is genuinely `unclassified`, not
    # `functional`, and the other three buckets are `not-applicable`
    # (empty), not a guess. This is the REAL behavior of a real Level 1
    # attempt today, not a synthetic assumption.
    assert per_dimension["unclassified"] == {"a": "PASS", "b": "PASS"}
    assert per_dimension["functional"] == {"a": "not-applicable", "b": "not-applicable"}

    # `from_collection_run` marks image_digest/timeout_seconds ASSERTED on
    # both real records (skillc#188: collection-run persists neither today)
    # - the comparison must say so rather than reading as if a real record
    # had proved these two genuinely matched.
    unverified_matched_fields = comparison["unverified_matched_fields"]
    assert isinstance(unverified_matched_fields, list)
    assert sorted(unverified_matched_fields) == ["image_digest", "timeout_seconds"]
    assert "image_digest" in str(comparison["unverified_matched_fields_note"])

    # A DIFFERENT image_digest for b - the identical real attempt, but a
    # genuinely MISMATCHED configuration on a field --vary does not name.
    path_b_mismatched = _adapt(
        result_b, experiment_b, tmp_path, "b-mismatched.json",
        image_digest="sha256:" + "ff" * 32, timeout_seconds=5,
    )
    record_b_mismatched = ccmp.load_record(path_b_mismatched)
    with pytest.raises(trial.Refused, match="image_digest"):
        ccmp.compare(record_a, record_b_mismatched, "collection")
