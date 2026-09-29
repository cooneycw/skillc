"""End-to-end test for `skillc/configuration_compare.py`'s `from_collection_run`
adapter (issue #13, review finding): unlike `test_configuration_compare.py`
(synthetic fixture records throughout, by design), this file drives TWO REAL
`collection-run` attempts through the fake docker CLI and the scripted fake
agent client (`tests/test_collection_conformance.py`'s own fixtures, reused
rather than duplicated) and adapts their ACTUAL saved output - proving the
adapter agrees with what `collection-run` really produces, not merely with
itself.

`image_digest`/`timeout_seconds` (skillc#188): the normal path below reads
both from `collection_conformance.evidence_envelope()`'s own new fields -
`image_digest` OBSERVED post-run (`install()`'s own measurement of the
running container, `tests/test_collection_conformance.py`'s own
`test_image_digest_is_the_observed_value_...` proves this end to end at
the source), `timeout_seconds` the controller's own input - and marks both
`RECORDED`. The explicit-keyword-argument path this file used before #188
closed the gap is kept for the two red cases at the bottom: a record that
predates the fix (the envelope's own fields stripped) still resolves
through a caller-supplied kwarg, marked `ASSERTED`; and a caller-supplied
kwarg that DISAGREES with what a real record carries is refused, naming
both, never silently preferred either way.
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
    *, image_digest: str | None = None, timeout_seconds: float | None = None,
    strip_envelope_fields: bool = False,
) -> Path:
    """Reads the REAL VERIFIED_RESULT `collection-run` actually stored (the
    same file a real `--evidence` export would publish as `result-*.json`) -
    for `grader.id`/`grader.revision` ONLY. `outcome_dimensions` is built
    from `record["graded"]["criteria"]` instead (task-only - see
    `from_collection_run`'s own docstring for why `verified_result["criteria"]`
    is the WRONG source: it mixes in the verifier's own `installation-ready`
    criterion, found by running this test against real output and getting a
    real INCONCLUSIVE where the task's own grade is genuinely PASS).

    `image_digest`/`timeout_seconds` are normally omitted - the real
    envelope already carries both (skillc#188) and `from_collection_run`
    reads them from there. `strip_envelope_fields=True` simulates a
    pre-#188 record (the envelope's own fields deleted) so the two kwargs
    below become this call's only source, exactly as every call in this
    file had to work before the fix."""
    envelope = cc.evidence_envelope(result)
    if strip_envelope_fields:
        envelope = {k: v for k, v in envelope.items() if k not in ("image_digest", "timeout_seconds")}
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


def test_a_real_matched_pair_compares_fully_recorded(
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

    # No image_digest/timeout_seconds kwargs - both real envelopes already
    # carry them (skillc#188), so this is the normal path now.
    path_a = _adapt(result_a, experiment_a, tmp_path, "a.json")
    path_b = _adapt(result_b, experiment_b, tmp_path, "b-matched.json")

    record_a = ccmp.load_record(path_a)
    record_b_matched = ccmp.load_record(path_b)
    assert record_a.task_id == record_b_matched.task_id == "slug-small-fix"
    assert record_a.client == record_b_matched.client == "codex"
    assert record_a.collection == "collection-a"
    assert record_b_matched.collection == "collection-b"
    # Both real attempts ran the same fake image and were given the same
    # timeout, so both fields genuinely match here too.
    assert record_a.image_digest == record_b_matched.image_digest == _BACKEND_IMAGE_DIGEST
    assert record_a.timeout_seconds == record_b_matched.timeout_seconds == 5
    assert record_a.provenance["image_digest"] == ccmp.RECORDED
    assert record_a.provenance["timeout_seconds"] == ccmp.RECORDED

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

    # #188 closed: both real records now carry image_digest/timeout_seconds
    # as RECORDED, so this comparison must not read as if either were only
    # asserted - the key is absent entirely, not an empty list.
    assert "unverified_matched_fields" not in comparison
    assert "unverified_matched_fields_note" not in comparison


def test_a_real_mismatched_observed_digest_refuses_the_comparison(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The mismatch is REAL this time, not a differing kwarg: `collection-b`'s
    container reports a different OBSERVED digest (the fake docker CLI's
    own `.image-id-<container>` override, exactly
    `tests/test_collection_conformance.py`'s own
    `test_image_digest_is_the_observed_value_...` uses), so the adapted
    record genuinely disagrees with `collection-a`'s - `compare()` must
    still refuse and name `image_digest`, now over two RECORDED values."""
    base_a, docker_state_a = tmp_path / "work-a", tmp_path / "docker-state-a"
    base_a.mkdir()
    base_b, docker_state_b = tmp_path / "work-b", tmp_path / "docker-state-b"
    base_b.mkdir()

    result_a, experiment_a = _run_real_attempt(
        tmp_path, base_a, docker_state_a, monkeypatch,
        collection_name="collection-a", transcript_relpath=".codex/sessions/2026/01/01/rollout-a.jsonl",
    )

    repo = _fixture_collection(tmp_path, "collection-b")
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: cc.materialize.Subject.from_dict({
        "subject_schema": 1, "locator": "test/test", "revision": "v1", "surface": "codex-skills",
        "skills_root": "skills", "select": ["tdd"], "client": {"name": "codex", "version": "0.157.1"},
    }))
    acquired = cc.acquire_collection("collection-b", base_b, checkout=repo)
    store = trial.open_store(tmp_path / "collection-b-store", forbidden=[])
    experiment_b, attempt_id_b = cc.plan_collection_attempt(
        "collection-b", acquired, store, image_digest=_BACKEND_IMAGE_DIGEST,
    )
    docker_state_b.mkdir(parents=True, exist_ok=True)
    container_name = d._container_name(attempt_id_b)
    (docker_state_b / f".image-id-{container_name}").write_text("sha256:" + "ff" * 32, encoding="utf-8")
    home = _mapped_home(docker_state_b, attempt_id_b)
    result_b = cc.run_collection_agent_attempt(
        subject_name="collection-b", acquired=acquired, experiment=experiment_b, attempt_id=attempt_id_b,
        backend=_backend(base_b, docker_state_b), grading_backend=_backend(base_b, docker_state_b), base=base_b,
        base_argv=_codex_argv(home=home, transcript_relpath=".codex/sessions/2026/01/01/rollout-b.jsonl"),
        prompt="Fix the slug helper.", timeout=5, credential_explicit_path=_fresh_codex_credential(tmp_path),
    )
    graded_b = result_b.record.get("graded")
    assert isinstance(graded_b, dict) and graded_b.get("status") == "PASS"
    assert result_b.image_digest == "sha256:" + "ff" * 32  # the override, not the plan

    path_a = _adapt(result_a, experiment_a, tmp_path, "a.json")
    path_b = _adapt(result_b, experiment_b, tmp_path, "b-mismatched.json")
    record_a = ccmp.load_record(path_a)
    record_b = ccmp.load_record(path_b)
    assert record_a.provenance["image_digest"] == record_b.provenance["image_digest"] == ccmp.RECORDED

    with pytest.raises(trial.Refused, match="image_digest"):
        ccmp.compare(record_a, record_b, "collection")


def test_a_pre_188_record_falls_back_to_the_caller_and_stays_asserted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Red case (#188 acceptance): a record produced BEFORE this change -
    simulated by stripping the envelope's own `image_digest`/
    `timeout_seconds` keys, exactly what a pre-#188 `collection-run` record
    looked like - falls back to the caller-supplied keyword arguments and
    stays `asserted`, never silently upgraded."""
    base_a, docker_state_a = tmp_path / "work-a", tmp_path / "docker-state-a"
    base_a.mkdir()
    result_a, experiment_a = _run_real_attempt(
        tmp_path, base_a, docker_state_a, monkeypatch,
        collection_name="collection-a", transcript_relpath=".codex/sessions/2026/01/01/rollout-a.jsonl",
    )

    path = _adapt(
        result_a, experiment_a, tmp_path, "pre-188.json", strip_envelope_fields=True,
        image_digest=_BACKEND_IMAGE_DIGEST, timeout_seconds=5,
    )
    record = ccmp.load_record(path)
    assert record.image_digest == _BACKEND_IMAGE_DIGEST
    assert record.timeout_seconds == 5
    assert record.provenance["image_digest"] == ccmp.ASSERTED
    assert record.provenance["timeout_seconds"] == ccmp.ASSERTED


def test_a_caller_asserted_value_disagreeing_with_the_record_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review requirement (condition 2): a record CARRIES a value and the
    caller ALSO supplies one, and they differ - `from_collection_run` must
    refuse and name both, never silently prefer either."""
    base_a, docker_state_a = tmp_path / "work-a", tmp_path / "docker-state-a"
    base_a.mkdir()
    result_a, experiment_a = _run_real_attempt(
        tmp_path, base_a, docker_state_a, monkeypatch,
        collection_name="collection-a", transcript_relpath=".codex/sessions/2026/01/01/rollout-a.jsonl",
    )

    envelope = cc.evidence_envelope(result_a)
    graded = result_a.record.get("graded")
    assert isinstance(graded, dict)
    result_id = graded.get("result_id")
    assert isinstance(result_id, str)
    verified_result = json.loads((experiment_a.root / f"result-{result_id}.json").read_text(encoding="utf-8"))
    dimensions = verify.GraderDef.load(GRADER_ROOT).dimensions
    task_criteria = [c for c in graded["criteria"] if isinstance(c, dict)]
    outcome_dimensions = orpt.build(task_criteria, dimensions).as_dict()

    with pytest.raises(trial.Refused, match="image_digest"):
        ccmp.from_collection_run(
            envelope, verified_result, outcome_dimensions,
            image_digest="sha256:" + "ee" * 32,  # disagrees with the real observed digest
        )
    with pytest.raises(trial.Refused, match="timeout_seconds"):
        ccmp.from_collection_run(
            envelope, verified_result, outcome_dimensions,
            timeout_seconds=999,  # disagrees with the real timeout (5)
        )
