"""Tests for skillc/collection_conformance.py (issue #11, bullet 2: "the
same client, Level 1 fixture, contract and grader").

Every test here runs against the fake `docker` CLI
(`tests/fixtures/docker-backend/fake_docker.py`), a scripted fake client
(`tests/fixtures/agent-trial/fake_agent_client.py`), and a committed fixture
skill collection (a plain directory, never a real subject's real git remote)
- mirroring `tests/test_agent_trial.py`'s own acceptance: no real daemon and
no real `codex` binary is available in this session, or reachable from this
file at all.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import shlex
import shutil
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from skillc import agent_trial, demo, materialize, reap, trial
from skillc import collection_conformance as cc
from skillc import docker_backend as d

FAKE_DOCKER = Path(__file__).resolve().parent / "fixtures" / "docker-backend" / "fake_docker.py"
FAKE_CLIENT = Path(__file__).resolve().parent / "fixtures" / "agent-trial" / "fake_agent_client.py"
GRADER_ROOT = Path(__file__).resolve().parent.parent / "evals" / "level1" / "slug-small-fix"
#: test_demo.py's own fake codex client (#7) - reused here for #150-D's
#: in-container discovery listing rather than building a second fixture.
CODEX_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "codex-subject"


def _docker_bin(state_dir: Path) -> list[str]:
    return [sys.executable, str(FAKE_DOCKER), "--state", str(state_dir)]


@pytest.fixture
def base(tmp_path: Path) -> Path:
    path = tmp_path / "work"
    path.mkdir()
    return path


@pytest.fixture
def docker_state(tmp_path: Path) -> Path:
    return tmp_path / "docker-state"


#: The fake docker CLI's own deterministic digest for this image tag
#: (`fake_docker.py`'s `cmd_image`/`cmd_inspect`: `sha256:fake-digest-for-<tag>`
#: either way it is queried) - #150-D's receipt path cross-checks a measured
#: image digest against the ledger's PLANNED one, so a test that exercises
#: that path must plan against this, not the "UNKNOWN" `plan_collection_attempt`
#: defaults to when no `image_digest` is given.
_BACKEND_IMAGE = "fake-image:1"
_BACKEND_IMAGE_DIGEST = f"sha256:fake-digest-for-{_BACKEND_IMAGE}"


def _backend(base: Path, docker_state: Path) -> d.DockerBackend:
    return d.DockerBackend(image=_BACKEND_IMAGE, base_dir=base, docker_bin=_docker_bin(docker_state))


def _skill_md(name: str) -> str:
    return f"---\nname: {name}\ndescription: A test skill.\n---\nBody text.\n"


def _fixture_collection(tmp_path: Path, skills: dict[str, str]) -> Path:
    """A plain directory, never a git repository - `materialize.acquire_snapshot`
    never checks the declared revision in snapshot mode, matching
    `tests/test_demo.py`'s own `_subject_collection` fixture (issue #101
    cross-model review: a real `git init` needs a `git` binary CI's gate
    image does not have)."""
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
    """Guards against `demo.DEFAULT_SUBJECT` (a real `evals/subjects/` entry)
    ever being read for real by a test in this file - every test here
    supplies its own subject via `monkeypatch.setattr(demo, "load_demo_subject", ...)`
    and a local `checkout=`, mirroring `tests/test_demo.py`'s own fixture."""
    monkeypatch.setattr(demo, "DEFAULT_SUBJECT", "unused-in-tests")


def _codex_argv(
    *, home: Path, transcript_relpath: str, fail_canary: bool = False,
    copy_solution: Path | None = None, plant_skill: list[str] | None = None,
) -> list[str]:
    argv = [
        sys.executable, str(FAKE_CLIENT), "--format", "codex-fake", "--home", str(home),
        "--transcript-relpath", transcript_relpath,
    ]
    if fail_canary:
        argv.append("--fail-canary")
    if copy_solution is not None:
        argv.extend(["--copy-solution", str(copy_solution)])
    for skill in plant_skill or ():
        argv.extend(["--plant-skill", skill])
    return argv


def _fake_codex_listing(tmp_path: Path, mode: str = "normal", **config: str) -> list[str]:
    """`tests/fixtures/codex-subject/fake_codex.py`, copied fresh per test
    (test_demo.py's own pattern) - a bare `"codex"` in `listing_client_argv`
    would need the real binary on `PATH`, which a real trial image gives it
    but this fixture never does; this is the scripted stand-in
    #150-D's `InstallationReceiptContext.listing_client_argv` exists for."""
    script = tmp_path / "listing-client" / "fake_codex.py"
    script.parent.mkdir(exist_ok=True)
    shutil.copy(CODEX_FIXTURE / "fake_codex.py", script)
    script.with_suffix(".mode").write_text(json.dumps({"mode": mode, **config}), encoding="utf-8")
    return [sys.executable, str(script)]


def _mapped_home(docker_state: Path, attempt_id: str) -> Path:
    name = d._container_name(attempt_id)
    return docker_state / f"{name}.fsroot" / "home" / "candidate"


def _fresh_codex_credential(tmp_path: Path) -> Path:
    def seg(data: bytes) -> str:
        import base64
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()
    token = f"{seg(json.dumps({'alg': 'none'}).encode())}.{seg(json.dumps({'exp': int(time.time() + 3600)}).encode())}.sig"
    path = tmp_path / "codex-credential.json"
    path.write_text(json.dumps({"tokens": {"access_token": token}}))
    return path


# ------------------------------------------------ planned evidence identity


def _planned_digest(experiment: trial.Experiment, attempt_id: str, section: str) -> str:
    planned_trial = experiment.trial_of(attempt_id)
    part = planned_trial[section]
    assert isinstance(part, dict)
    digest = part["digest"]
    assert isinstance(digest, str)
    return digest


def test_plan_records_the_collection_s_real_content_digest_not_a_placeholder(
    tmp_path: Path, base: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Codex review of an earlier version: `subject.digest` was a fixed
    literal (`sha256:00`) regardless of which collection ran, so the planned
    evidence could not identify its own inputs. It must now be the real
    acquired collection's own content digest, and it must DIFFER for two
    different collections."""
    repo_a = _fixture_collection(tmp_path, {"tdd": "tdd"})
    repo_b = _fixture_collection(tmp_path / "b", {"other": "other"})
    base_a = base / "a"
    base_b = base / "b"
    base_a.mkdir()
    base_b.mkdir()
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject(select=["tdd"]))
    acquired_a = cc.acquire_collection("whatever", base_a, checkout=repo_a)
    store_a = trial.open_store(tmp_path / "store-a", forbidden=[])
    experiment_a, attempt_id_a = cc.plan_collection_attempt("whatever", acquired_a, store_a)
    digest_a = _planned_digest(experiment_a, attempt_id_a, "subject")

    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject(select=["other"]))
    acquired_b = cc.acquire_collection("whatever", base_b, checkout=repo_b)
    store_b = trial.open_store(tmp_path / "store-b", forbidden=[])
    experiment_b, attempt_id_b = cc.plan_collection_attempt("whatever", acquired_b, store_b)
    digest_b = _planned_digest(experiment_b, attempt_id_b, "subject")

    assert digest_a == acquired_a.source.digest
    assert digest_a != digest_b
    assert digest_a != "sha256:00"


def test_plan_records_the_resolved_image_digest_and_unknown_when_absent(
    tmp_path: Path, base: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _fixture_collection(tmp_path, {"tdd": "tdd"})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject(select=["tdd"]))
    acquired = cc.acquire_collection("whatever", base, checkout=repo)

    store_known = trial.open_store(tmp_path / "store-known", forbidden=[])
    experiment_known, attempt_known = cc.plan_collection_attempt(
        "whatever", acquired, store_known, image_digest="sha256:realimage",
    )
    assert _planned_digest(experiment_known, attempt_known, "image") == "sha256:realimage"

    store_unknown = trial.open_store(tmp_path / "store-unknown", forbidden=[])
    experiment_unknown, attempt_unknown = cc.plan_collection_attempt("whatever", acquired, store_unknown)
    assert _planned_digest(experiment_unknown, attempt_unknown, "image") == "UNKNOWN"


# --------------------------------------------------------------- happy path


def test_happy_path_installs_the_collection_and_grades(
    tmp_path: Path, base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _fixture_collection(tmp_path, {"tdd": "tdd", "diagnosing-bugs": "diagnosing-bugs"})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject(select=["tdd", "diagnosing-bugs"]))

    acquired = cc.acquire_collection("whatever", base, checkout=repo)
    store = trial.open_store(tmp_path / "store", forbidden=[])
    experiment, attempt_id = cc.plan_collection_attempt("whatever", acquired, store, image_digest=_BACKEND_IMAGE_DIGEST)
    backend = _backend(base, docker_state)
    grading_backend = _backend(base, docker_state)
    home = _mapped_home(docker_state, attempt_id)
    reference = GRADER_ROOT / "reference"
    argv = _codex_argv(
        home=home, transcript_relpath=".codex/sessions/2026/01/01/rollout-cc.jsonl", copy_solution=reference,
    )
    cred_path = _fresh_codex_credential(tmp_path)

    result = cc.run_collection_agent_attempt(
        subject_name="whatever", acquired=acquired, experiment=experiment, attempt_id=attempt_id,
        backend=backend, grading_backend=grading_backend, base=base,
        base_argv=argv, prompt="Fix the slug helper.", timeout=5,
        credential_explicit_path=cred_path,
    )

    assert result.record["disposition"] == "captured"
    observation = result.record["observation"]
    assert isinstance(observation, dict)
    assert observation["prompt_delivered"] is True
    assert observation["canary_satisfied"] is True
    assert observation["skill_invocations"] == []  # skill-free: nothing planted, nothing invoked
    graded = result.record["graded"]
    assert isinstance(graded, dict)
    assert graded["status"] == "PASS"

    # #188: the OBSERVED image digest (read back from the journal's own
    # `backend-identity` event, `install()`'s own measurement of the
    # running container) matches the ledger's planned one here - the fake
    # docker CLI resolves both through the same deterministic function - but
    # the two are DIFFERENT reads, not the same value copied twice; see the
    # mismatch test below for a case where they diverge. The timeout is the
    # controller's own input, verbatim.
    assert result.image_digest == _BACKEND_IMAGE_DIGEST
    assert result.timeout_seconds == 5


def test_image_digest_is_the_observed_value_not_the_merely_planned_one(
    tmp_path: Path, base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#188 review: `result.image_digest` must be what the backend actually
    OBSERVED after starting the container, never an echo of the ledger's
    plan - the two are different reads and this test makes them disagree on
    purpose (the fake docker CLI's own `.image-id-<container>` override
    sentinel, documented in `fake_docker.py`'s `cmd_inspect`, for "a tag
    republished between planning and the run"), so a fix that silently read
    `plan_collection_attempt`'s own `image_digest` argument back instead
    would pass the happy-path test above and fail only here."""
    repo = _fixture_collection(tmp_path, {"tdd": "tdd"})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject(select=["tdd"]))

    acquired = cc.acquire_collection("whatever", base, checkout=repo)
    store = trial.open_store(tmp_path / "store", forbidden=[])
    experiment, attempt_id = cc.plan_collection_attempt("whatever", acquired, store, image_digest=_BACKEND_IMAGE_DIGEST)
    docker_state.mkdir(parents=True, exist_ok=True)
    name = d._container_name(attempt_id)
    observed = "sha256:" + "cc" * 32
    (docker_state / f".image-id-{name}").write_text(observed, encoding="utf-8")
    backend = _backend(base, docker_state)
    grading_backend = _backend(base, docker_state)
    home = _mapped_home(docker_state, attempt_id)
    argv = _codex_argv(home=home, transcript_relpath=".codex/sessions/2026/01/01/rollout-cc.jsonl")
    cred_path = _fresh_codex_credential(tmp_path)

    result = cc.run_collection_agent_attempt(
        subject_name="whatever", acquired=acquired, experiment=experiment, attempt_id=attempt_id,
        backend=backend, grading_backend=grading_backend, base=base,
        base_argv=argv, prompt="Fix the slug helper.", timeout=5, credential_explicit_path=cred_path,
    )

    assert result.image_digest == observed
    assert result.image_digest != _BACKEND_IMAGE_DIGEST


def test_image_digest_is_none_when_the_backend_reports_no_identity(
    tmp_path: Path, base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the backend cannot answer the observation at all (the fake
    docker CLI's own `.no-image-id-<container>` sentinel, mirroring a real
    daemon's `docker inspect` failing), `result.image_digest` must be `None`
    - never a guess, and never silently falling back to the planned digest,
    which is exactly the confusion #188 review flagged."""
    repo = _fixture_collection(tmp_path, {"tdd": "tdd"})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject(select=["tdd"]))

    acquired = cc.acquire_collection("whatever", base, checkout=repo)
    store = trial.open_store(tmp_path / "store", forbidden=[])
    experiment, attempt_id = cc.plan_collection_attempt("whatever", acquired, store, image_digest=_BACKEND_IMAGE_DIGEST)
    docker_state.mkdir(parents=True, exist_ok=True)
    name = d._container_name(attempt_id)
    (docker_state / f".no-image-id-{name}").write_text("", encoding="utf-8")
    backend = _backend(base, docker_state)
    grading_backend = _backend(base, docker_state)
    home = _mapped_home(docker_state, attempt_id)
    argv = _codex_argv(home=home, transcript_relpath=".codex/sessions/2026/01/01/rollout-cc.jsonl")
    cred_path = _fresh_codex_credential(tmp_path)

    result = cc.run_collection_agent_attempt(
        subject_name="whatever", acquired=acquired, experiment=experiment, attempt_id=attempt_id,
        backend=backend, grading_backend=grading_backend, base=base,
        base_argv=argv, prompt="Fix the slug helper.", timeout=5, credential_explicit_path=cred_path,
    )

    assert result.image_digest is None
    assert result.record["disposition"] == "captured"  # the attempt itself is unaffected


def test_the_result_revision_is_what_was_acquired_never_the_declared_pin(
    tmp_path: Path, base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#150-B2 review: found while wiring a degraded run's identity that a
    NORMAL run already misreported this - `CollectionAgentResult.revision`
    read `acquired.subject.revision` (the DECLARED pin, `"v1"` here)
    unconditionally, never `acquired.source.revision` (what
    `acquire_collection` actually acquired - a `snapshot:<digest>` label,
    matching `plan_collection_attempt`'s own "never a placeholder" rule for
    `subject.digest`, which reads the same `acquired.source`). Confirmed red
    on the pre-fix line (temporarily reverted, re-run, restored): asserted
    `'snapshot:...' != 'v1'` and got `AssertionError: 'v1' != 'v1'`."""
    repo = _fixture_collection(tmp_path, {"tdd": "tdd"})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject(select=["tdd"]))

    acquired = cc.acquire_collection("whatever", base, checkout=repo)
    store = trial.open_store(tmp_path / "store", forbidden=[])
    experiment, attempt_id = cc.plan_collection_attempt("whatever", acquired, store, image_digest=_BACKEND_IMAGE_DIGEST)
    backend = _backend(base, docker_state)
    grading_backend = _backend(base, docker_state)
    home = _mapped_home(docker_state, attempt_id)
    argv = _codex_argv(home=home, transcript_relpath=".codex/sessions/2026/01/01/rollout-cc.jsonl")
    cred_path = _fresh_codex_credential(tmp_path)

    result = cc.run_collection_agent_attempt(
        subject_name="whatever", acquired=acquired, experiment=experiment, attempt_id=attempt_id,
        backend=backend, grading_backend=grading_backend, base=base,
        base_argv=argv, prompt="Fix the slug helper.", timeout=5, credential_explicit_path=cred_path,
    )

    assert result.revision == acquired.source.revision
    assert result.revision != acquired.subject.revision  # != "v1", the declared pin
    assert result.revision.startswith("snapshot:")


def test_skill_invocations_observes_a_spontaneous_selection(
    tmp_path: Path, base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole point of skill-free mode plus an installed collection
    (issue #26's own early signal, `docs/specs/evaluation-facility/operator-demo.md`):
    an invocation the fake client plants ANYWAY must still be observed,
    exactly as `test_agent_trial.py::test_skill_free_canary_still_observes_a_false_positive_invocation`
    proves at the `agent_trial` layer directly."""
    repo = _fixture_collection(tmp_path, {"tdd": "tdd"})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject(select=["tdd"]))

    acquired = cc.acquire_collection("whatever", base, checkout=repo)
    store = trial.open_store(tmp_path / "store", forbidden=[])
    experiment, attempt_id = cc.plan_collection_attempt("whatever", acquired, store, image_digest=_BACKEND_IMAGE_DIGEST)
    backend = _backend(base, docker_state)
    grading_backend = _backend(base, docker_state)
    home = _mapped_home(docker_state, attempt_id)
    argv = _codex_argv(
        home=home, transcript_relpath=".codex/sessions/2026/01/01/rollout-sel.jsonl", plant_skill=["tdd"],
    )
    cred_path = _fresh_codex_credential(tmp_path)

    result = cc.run_collection_agent_attempt(
        subject_name="whatever", acquired=acquired, experiment=experiment, attempt_id=attempt_id,
        backend=backend, grading_backend=grading_backend, base=base,
        base_argv=argv, prompt="Fix the slug helper.", timeout=5,
        credential_explicit_path=cred_path,
    )

    observation = result.record["observation"]
    assert isinstance(observation, dict)
    assert observation["canary_satisfied"] is True  # skill-free: indifferent to which, if any, skill fired
    assert observation["skill_invocations"] == ["tdd"]
    assert observation["skill_invocation_detection"] == "heuristic"  # codex's own detection, per ClientSpec


def test_missing_credential_blocks_before_launch(
    tmp_path: Path, base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Planned control (`docs/specs/evaluation-facility/operator-demo.md`):
    a run with the credential deliberately absent must report
    `disposition == "unavailable"`, matching `agent_trial.py`'s own existing
    acceptance for a missing credential - no container is ever launched."""
    repo = _fixture_collection(tmp_path, {"tdd": "tdd"})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject(select=["tdd"]))

    acquired = cc.acquire_collection("whatever", base, checkout=repo)
    store = trial.open_store(tmp_path / "store", forbidden=[])
    experiment, attempt_id = cc.plan_collection_attempt("whatever", acquired, store, image_digest=_BACKEND_IMAGE_DIGEST)
    backend = _backend(base, docker_state)
    grading_backend = _backend(base, docker_state)
    missing = tmp_path / "does-not-exist.json"
    argv = [sys.executable, "-c", "import sys; sys.exit(1)"]  # must never run

    result = cc.run_collection_agent_attempt(
        subject_name="whatever", acquired=acquired, experiment=experiment, attempt_id=attempt_id,
        backend=backend, grading_backend=grading_backend, base=base,
        base_argv=argv, prompt="Fix the slug helper.", timeout=5,
        credential_explicit_path=missing,
    )

    assert result.record["disposition"] == "unavailable"
    assert result.record.get("observation") is None


def test_unknown_selected_skill_is_refused_before_any_docker_work(
    tmp_path: Path, base: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _fixture_collection(tmp_path, {"tdd": "tdd"})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject(select=["tdd", "does-not-exist"]))

    with pytest.raises(demo.SubjectRefused, match="does-not-exist"):
        cc.acquire_collection("whatever", base, checkout=repo)


# ------------------------------------------------------------- --task DIR
# (issue #150-B3: the operator's discriminating run needs finish-close-ref
# to actually be runnable, not silently graded as slug-small-fix).

FINISH_CLOSE_REF_ROOT = Path(__file__).resolve().parent.parent / "evals" / "level1" / "finish-close-ref"


def test_resolve_task_root_defaults_to_the_fixed_level1_task() -> None:
    assert cc.resolve_task_root(None) == demo.GRADER_ROOT


def test_resolve_task_root_accepts_another_level1_task_layout() -> None:
    assert cc.resolve_task_root(str(FINISH_CLOSE_REF_ROOT)) == FINISH_CLOSE_REF_ROOT.resolve()


@pytest.mark.parametrize("missing", ["goal.md", "fixture", "grader.json"])
def test_resolve_task_root_refuses_a_directory_missing_the_layout(tmp_path: Path, missing: str) -> None:
    """Red case: a directory carrying every Level 1 file EXCEPT one must be
    refused, before any Docker work, naming the missing piece - not read as a
    task whose grader.json merely happens to be absent from the plan."""
    task_dir = tmp_path / "half-a-task"
    task_dir.mkdir()
    for name in ("goal.md", "grader.json"):
        if name != missing:
            (task_dir / name).write_text("x", encoding="utf-8")
    if missing != "fixture":
        (task_dir / "fixture").mkdir()

    with pytest.raises(demo.SubjectRefused, match=missing):
        cc.resolve_task_root(str(task_dir))


def test_cmd_collection_run_refuses_a_task_dir_missing_the_layout(
    tmp_path: Path, base: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """CLI-level twin of the above: exit 2, no traceback, before `new_run_root`
    creates anything - mirrors `test_a_path_like_subject_is_refused_before_any_scratch_path`."""
    from skillc import cli

    empty = tmp_path / "not-a-task"
    empty.mkdir()
    assert cli.main(["collection-run", "whatever", "--task", str(empty), "--base", str(base)]) == 2
    err = capsys.readouterr().err
    assert "Traceback" not in err
    assert "goal.md" in err
    assert not any(base.iterdir())  # refused before new_run_root created a run root


def test_plan_collection_attempt_with_task_records_that_task_s_case_and_a_different_grader_digest(
    tmp_path: Path, base: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Red case (a): before this fix, EVERY collection's plan carried the
    literal `{"id": "slug-small-fix", "revision": "r1"}` and
    `verify.GraderDef.load(demo.GRADER_ROOT).identity()` regardless of
    `--task` - so the operator's discriminating run against finish-close-ref
    would have been ledgered, and graded, as slug-small-fix. With `task_root`
    threaded through, the case id follows the task, and the grader identity
    (which includes its digest) differs from the default task's."""
    repo = _fixture_collection(tmp_path, {"tdd": "tdd"})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject(select=["tdd"]))
    acquired = cc.acquire_collection("whatever", base, checkout=repo)

    store_default = trial.open_store(tmp_path / "store-default", forbidden=[])
    experiment_default, attempt_default = cc.plan_collection_attempt("whatever", acquired, store_default)
    default_trial = experiment_default.trial_of(attempt_default)
    assert default_trial["case"] == {"id": "slug-small-fix", "revision": "2"}

    store_task = trial.open_store(tmp_path / "store-task", forbidden=[])
    experiment_task, attempt_task = cc.plan_collection_attempt(
        "whatever", acquired, store_task, task_root=FINISH_CLOSE_REF_ROOT,
    )
    task_trial = experiment_task.trial_of(attempt_task)
    assert task_trial["case"] == {"id": "finish-close-ref", "revision": "1"}

    default_grader, task_grader = default_trial["grader"], task_trial["grader"]
    assert isinstance(default_grader, dict) and isinstance(task_grader, dict)
    assert default_grader["digest"] != task_grader["digest"]


def _finish_close_ref_run(
    tmp_path: Path, base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch, *, solution: Path,
) -> cc.CollectionAgentResult:
    repo = _fixture_collection(tmp_path, {"tdd": "tdd"})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject(select=["tdd"]))
    acquired = cc.acquire_collection("whatever", base, checkout=repo)
    store = trial.open_store(tmp_path / "store", forbidden=[])
    experiment, attempt_id = cc.plan_collection_attempt(
        "whatever", acquired, store, task_root=FINISH_CLOSE_REF_ROOT, image_digest=_BACKEND_IMAGE_DIGEST,
    )
    argv = _codex_argv(
        home=_mapped_home(docker_state, attempt_id),
        transcript_relpath=".codex/sessions/2026/01/01/rollout-fcr.jsonl", copy_solution=solution,
    )
    return cc.run_collection_agent_attempt(
        subject_name="whatever", acquired=acquired, experiment=experiment, attempt_id=attempt_id,
        backend=_backend(base, docker_state), grading_backend=_backend(base, docker_state), base=base,
        base_argv=argv, task_root=FINISH_CLOSE_REF_ROOT, timeout=5,
        credential_explicit_path=_fresh_codex_credential(tmp_path),
    )


def test_task_dir_run_is_graded_by_that_task_s_own_grader_pass_case(
    tmp_path: Path, base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Red case (c), PASS arm: a candidate writing finish-close-ref's own
    reference answer must grade PASS. Before this fix, `run_level1_agent_attempt`
    always read `demo.GRADER_ROOT` (slug-small-fix's goal/fixture/grader), so a
    `--task finish-close-ref` run would have graded the WRONG task's grader
    against inputs that grader does not recognise, never this one."""
    result = _finish_close_ref_run(
        tmp_path, base, docker_state, monkeypatch, solution=FINISH_CLOSE_REF_ROOT / "reference",
    )
    graded = result.record["graded"]
    assert isinstance(graded, dict)
    assert graded["status"] == "PASS"


def test_task_dir_run_is_graded_by_that_task_s_own_grader_fail_case(
    tmp_path: Path, base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Red case (c), FAIL arm: the committed `wrong/negated-close` candidate
    (a negated closing disclaimer that still matches the closing grammar)
    must fail `no-closing-match` - proving `finish-close-ref/grade_ref.py`
    itself ran, not merely that SOME grader returned a verdict."""
    result = _finish_close_ref_run(
        tmp_path, base, docker_state, monkeypatch, solution=FINISH_CLOSE_REF_ROOT / "wrong" / "negated-close",
    )
    graded = result.record["graded"]
    assert isinstance(graded, dict)
    assert graded["status"] == "FAIL"
    assert "no-closing-match" in str(graded["detail"])


# --------------------------------------------------------- fixture surface


def test_fixture_surface_installs_src_only_never_the_answer_key() -> None:
    """`_fixture_surface` must deliver `evals/level1/slug-small-fix/fixture/src/`
    and never the sibling `expected.json` - that file is the grader's own
    ground truth for this fixture ("this candidate should FAIL, violating
    reported-example and R3"), and installing it would hand the agent the
    answer key."""
    surface = cc._fixture_surface(GRADER_ROOT / "fixture")
    assert "src/slugify.py" in surface
    assert all(not path.endswith("expected.json") for path in surface)
    on_disk = (GRADER_ROOT / "fixture" / "src" / "slugify.py").read_bytes()
    assert surface["src/slugify.py"] == on_disk


def test_default_prompt_is_the_task_s_own_goal_text(
    tmp_path: Path, base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`prompt=None` (the default) must read `goal.md` verbatim, never an
    invented string - #5's own "agent-facing request, identical for every
    arm"."""
    repo = _fixture_collection(tmp_path, {"tdd": "tdd"})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject(select=["tdd"]))

    acquired = cc.acquire_collection("whatever", base, checkout=repo)
    store = trial.open_store(tmp_path / "store", forbidden=[])
    experiment, attempt_id = cc.plan_collection_attempt("whatever", acquired, store, image_digest=_BACKEND_IMAGE_DIGEST)
    backend = _backend(base, docker_state)
    grading_backend = _backend(base, docker_state)
    home = _mapped_home(docker_state, attempt_id)
    argv = _codex_argv(home=home, transcript_relpath=".codex/sessions/2026/01/01/rollout-goal.jsonl")
    cred_path = _fresh_codex_credential(tmp_path)

    result = cc.run_collection_agent_attempt(
        subject_name="whatever", acquired=acquired, experiment=experiment, attempt_id=attempt_id,
        backend=backend, grading_backend=grading_backend, base=base,
        base_argv=argv, timeout=5, credential_explicit_path=cred_path,
    )

    observation = result.record["observation"]
    assert isinstance(observation, dict)
    goal_text = (GRADER_ROOT / "goal.md").read_text(encoding="utf-8")
    # The fake client echoes the delivered prompt's own text back into the
    # transcript (see fake_agent_client.py); prompt_delivered=True proves the
    # exact goal.md text (plus the canary instruction agent_trial appends)
    # reached the container.
    assert observation["prompt_delivered"] is True
    assert goal_text  # sanity: the real file is non-empty, not a vacuous match


# --------------------------------------------------------------- paste-back


def test_paste_back_is_leak_clean_and_names_every_planned_field() -> None:
    record: dict[str, object] = {
        "disposition": "captured",
        "observation": {
            "prompt_delivered": True, "canary_satisfied": True,
            "skill_invocations": ["tdd"], "skill_invocation_detection": "heuristic",
            # The record's REAL key (credential.CredentialUsage.to_record_fields).
            "credential_refresh_observed_in_container": False,
            "credential_delivered": True, "credential_source": "subscription",
            "credential_remaining_seconds_at_launch": 7200,
            "transcript_client_version": "0.157.1", "transcript_model": "some-model",
            "transcript_unrecognized_types": [],
        },
        "stop": {"reason": "exited", "exit_code": 0, "confirmed": True},
        "cleanup": {"status": "cleaned", "failures": []},
        "backend_teardown": "confirmed",
        "liveness_method": "canary",
        "graded": {"status": "PASS", "criteria": [{"id": "slug-fixed", "outcome": "SATISFIED"}]},
        "grading_blocked_reason": None,
    }
    state = cc.HostCredentialState(digest="d", remaining_seconds=3600)
    result = cc.CollectionAgentResult(
        "whatever", "v1", "codex", record,
        host_credential=cc.HostCredentialCheck(before=state, after=state),
        daemon_diff=reap.SnapshotDiff(comparable=True, leaked=frozenset(), foreign_vanished=frozenset()),
    )
    text = cc.build_collection_paste_back(result)
    assert demo.leak_check_text(text) == []
    for field in (
        "disposition=captured", "prompt_delivered=True", "canary_satisfied=True",
        "skill_invocations=['tdd']", "detection=heuristic", "refresh_observed_in_container=False",
        "graded.status=PASS", "graded.criteria=slug-fixed=SATISFIED", "liveness_method=canary",
        "credential_delivered=True source=subscription", "remaining_at_launch=120m",
        "host_credential_unchanged=True", "host_remaining_after=60m",
        "stop.reason=exited stop.exit_code=0 stop.confirmed=True",
        "workspace_cleanup(record, at finalize)=cleaned", "backend_teardown=confirmed", "leaked_owned_containers=0",
        "attributable_leftover_containers=None",
        "client_version=0.157.1 model=some-model", "unrecognized_types=[]",
    ):
        assert field in text


def test_paste_back_reports_dimensions_separately_from_the_flat_criteria_line(tmp_path: Path) -> None:
    """Issue #13: `graded.dimensions=` groups by DECLARED dimension, never
    inferred from the id, and reports every bucket - including one with no
    criteria at all (`not-applicable`, never guessed into a PASS/FAIL it
    never earned)."""
    record: dict[str, object] = {
        "disposition": "captured",
        "observation": {"prompt_delivered": True, "canary_satisfied": True, "skill_invocations": []},
        "stop": {"reason": "exited", "exit_code": 0, "confirmed": True},
        "cleanup": {"status": "cleaned", "failures": []},
        "backend_teardown": "confirmed",
        "liveness_method": "canary",
        "graded": {
            "status": "PASS",
            "criteria": [
                {"id": "functional-a", "mandatory": True, "outcome": "SATISFIED"},
                {"id": "integration-b", "mandatory": True, "outcome": "VIOLATED"},
            ],
        },
        "grading_blocked_reason": None,
    }
    result = cc.CollectionAgentResult("whatever", "v1", "codex", record)
    text = cc.build_collection_paste_back(result, dimensions={"functional-a": "functional", "integration-b": "integration"})
    assert demo.leak_check_text(text) == []
    assert "graded.dimensions=functional=PASS, constraint=not-applicable, integration=FAIL, unclassified=not-applicable" in text


def test_paste_back_reports_unclassified_when_no_dimensions_are_declared(tmp_path: Path) -> None:
    """Issue #13: the default (Level 1 today) - no declaration at all means
    every criterion is `unclassified`, never guessed into `functional`."""
    record: dict[str, object] = {
        "disposition": "captured",
        "observation": {"prompt_delivered": True, "canary_satisfied": True, "skill_invocations": []},
        "stop": {"reason": "exited", "exit_code": 0, "confirmed": True},
        "cleanup": {"status": "cleaned", "failures": []},
        "backend_teardown": "confirmed",
        "liveness_method": "canary",
        "graded": {"status": "PASS", "criteria": [{"id": "slug-fixed", "mandatory": True, "outcome": "SATISFIED"}]},
        "grading_blocked_reason": None,
    }
    result = cc.CollectionAgentResult("whatever", "v1", "codex", record)
    text = cc.build_collection_paste_back(result)
    assert "graded.dimensions=functional=not-applicable, constraint=not-applicable, integration=not-applicable, unclassified=PASS" in text


def test_paste_back_reports_unavailable_distinctly_from_unclassified(tmp_path: Path) -> None:
    """Review ruling: a FAILED dimensions lookup must never read the same as
    "the grader declares nothing" - the paste-back must say `unavailable`,
    with a reason, never silently fall back to `unclassified`."""
    record: dict[str, object] = {
        "disposition": "captured",
        "observation": {"prompt_delivered": True, "canary_satisfied": True, "skill_invocations": []},
        "stop": {"reason": "exited", "exit_code": 0, "confirmed": True},
        "cleanup": {"status": "cleaned", "failures": []},
        "backend_teardown": "confirmed",
        "liveness_method": "canary",
        "graded": {"status": "PASS", "criteria": [{"id": "slug-fixed", "mandatory": True, "outcome": "SATISFIED"}]},
        "grading_blocked_reason": None,
    }
    result = cc.CollectionAgentResult("whatever", "v1", "codex", record)
    text = cc.build_collection_paste_back(
        result, dimensions_unavailable_reason="grader load failed (Refused)",
    )
    assert demo.leak_check_text(text) == []
    assert (
        "graded.dimensions=functional=unavailable, constraint=unavailable, integration=unavailable, "
        "unclassified=unavailable (unavailable_reason=grader load failed (Refused))"
    ) in text


def test_paste_back_refresh_line_reads_a_real_driver_record(
    tmp_path: Path, base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Red on #11's paste-back (issue #106): it read `refresh_observed_in_container`
    from the observation while the driver writes
    `credential_refresh_observed_in_container`, so the live paste-back printed
    `None` on every run. The earlier test above hand-built its record with the
    paste-back's OWN wrong key, so it agreed with the bug by construction. This
    one takes the record from a real `run_one_attempt` (fake docker, scripted
    client), where the credential is delivered and read back unchanged."""
    repo = _fixture_collection(tmp_path, {"tdd": "tdd"})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject(select=["tdd"]))
    acquired = cc.acquire_collection("whatever", base, checkout=repo)
    store = trial.open_store(tmp_path / "store", forbidden=[])
    experiment, attempt_id = cc.plan_collection_attempt("whatever", acquired, store, image_digest=_BACKEND_IMAGE_DIGEST)
    argv = _codex_argv(
        home=_mapped_home(docker_state, attempt_id),
        transcript_relpath=".codex/sessions/2026/01/01/rollout-rf.jsonl", copy_solution=GRADER_ROOT / "reference",
    )
    result = cc.run_collection_agent_attempt(
        subject_name="whatever", acquired=acquired, experiment=experiment, attempt_id=attempt_id,
        backend=_backend(base, docker_state), grading_backend=_backend(base, docker_state), base=base,
        base_argv=argv, prompt="Fix the slug helper.", timeout=5,
        credential_explicit_path=_fresh_codex_credential(tmp_path),
    )
    text = cc.build_collection_paste_back(result)
    assert "refresh_observed_in_container=False" in text
    assert "backend_teardown=confirmed" in text
    assert "observation_record=written" in text  # persisted by the driver itself (#106)
    # The journal's own event says what happened; since #127 the record,
    # finalized after cleanup, agrees with it rather than reading "partial".
    assert result.workspace_cleaned == "removed"
    assert "workspace_cleaned(journal)=removed" in text
    assert "workspace_cleanup(record, at finalize)=removed" in text
    remaining = result.record["observation"]["credential_remaining_seconds_at_launch"]  # type: ignore[index]
    assert isinstance(remaining, int) and 3000 <= remaining <= 3600


def test_below_threshold_credential_blocks_before_launch_and_leaves_no_container(
    tmp_path: Path, base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#106 acceptance: a credential below the threshold is BLOCKED before
    launch, and no container remains. The fresh credential has about an hour;
    a threshold of a day refuses it. The client argv would fail loudly if it
    ever ran."""
    repo = _fixture_collection(tmp_path, {"tdd": "tdd"})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject(select=["tdd"]))
    acquired = cc.acquire_collection("whatever", base, checkout=repo)
    store = trial.open_store(tmp_path / "store", forbidden=[])
    experiment, attempt_id = cc.plan_collection_attempt("whatever", acquired, store, image_digest=_BACKEND_IMAGE_DIGEST)
    before = reap.snapshot(_docker_bin(docker_state), timeout=5)
    result = cc.run_collection_agent_attempt(
        subject_name="whatever", acquired=acquired, experiment=experiment, attempt_id=attempt_id,
        backend=_backend(base, docker_state), grading_backend=_backend(base, docker_state), base=base,
        base_argv=[sys.executable, "-c", "raise SystemExit('must never run')"], prompt="x", timeout=5,
        credential_explicit_path=_fresh_codex_credential(tmp_path), minimum_credential_seconds=86400,
    )
    after = reap.snapshot(_docker_bin(docker_state), timeout=5)
    assert result.record["disposition"] == "unavailable"
    assert "below the required" in str(result.record.get("reason", "")) + json.dumps(result.record, default=str)
    assert result.record["backend_teardown"] == "confirmed"
    assert after.reachable and not after.owned
    assert reap.diff(before, after).leaked == frozenset()
    assert result.record["graded"] is None
    # The control's paste-back names its own cause, not only its disposition.
    assert "below the required 86400s" in cc.build_collection_paste_back(result)


def test_host_credential_check_reports_a_changed_file(tmp_path: Path) -> None:
    """Red and green for the host-login evidence: an untouched file compares
    equal; a rewritten one (what an in-container refresh rotating the host's
    token would look like from the host) compares unequal; an unreadable one
    is `None`, never a pass."""
    path = _fresh_codex_credential(tmp_path)
    before = cc.read_host_credential("codex", path)
    assert before.digest is not None and before.remaining_seconds is not None
    assert cc.HostCredentialCheck(before, cc.read_host_credential("codex", path)).unchanged is True
    path.write_text(path.read_text() + " ")
    assert cc.HostCredentialCheck(before, cc.read_host_credential("codex", path)).unchanged is False
    missing = cc.read_host_credential("codex", tmp_path / "absent.json")
    assert missing.digest is None
    assert cc.HostCredentialCheck(before, missing).unchanged is None


def test_paste_back_handles_a_blocked_attempt_with_no_observation() -> None:
    record: dict[str, object] = {
        "disposition": "unavailable", "observation": None, "graded": None, "grading_blocked_reason": None,
    }
    result = cc.CollectionAgentResult("whatever", "v1", "codex", record)
    text = cc.build_collection_paste_back(result)
    assert "disposition=unavailable" in text
    assert "prompt_delivered=None" in text


# --------------------------------------------------------- no real model call


_REAL_AGENT_NAMES = frozenset({"claude", "codex"})


def _find_real_binary_names_in_argv_literals(tree: ast.AST) -> list[ast.expr]:
    offenders: list[ast.expr] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.List, ast.Tuple)):
            continue
        for element in node.elts:
            if not (isinstance(element, ast.Constant) and isinstance(element.value, str)):
                continue
            basename = element.value.rsplit("/", 1)[-1]
            if basename in _REAL_AGENT_NAMES:
                offenders.append(element)
    return offenders


def test_no_real_agent_binary_in_an_argv_literal_in_this_file() -> None:
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"), filename=__file__)
    offenders = _find_real_binary_names_in_argv_literals(tree)
    assert offenders == [], f"a real agent binary name appears in an argv-shaped literal: {[n.lineno for n in offenders]}"


def test_the_binary_name_scan_can_see_a_planted_offender() -> None:
    """Negative control (codex review: this file's copy of the scan had no
    committed proof it could still fire, unlike `test_agent_trial.py`'s own
    copy): the scan actually fires on a bare occurrence inside an
    argv-shaped literal, not only ever passing silently."""
    tree = ast.parse('argv = [sys.executable, "codex", "-p", "hi"]\n', filename="<planted>")
    assert len(_find_real_binary_names_in_argv_literals(tree)) == 1


def test_the_binary_name_scan_catches_an_absolute_path_too() -> None:
    tree = ast.parse('argv = [sys.executable, "/usr/bin/codex", "-p", "hi"]\n', filename="<planted>")
    assert len(_find_real_binary_names_in_argv_literals(tree)) == 1


def test_the_binary_name_scan_does_not_fire_on_a_client_keyword() -> None:
    """Negative control (the other direction, codex review): an unrelated
    list of client names is not an argv - the scan is scoped to
    list/tuple-shaped literals generically, so it cannot distinguish that
    case from a real one; documented here rather than silently accepted."""
    tree = ast.parse('at.run_one_attempt(client="codex")\n', filename="<planted>")
    assert _find_real_binary_names_in_argv_literals(tree) == []


# ------------------------------------------- the live run's three defaults (#11)
#
# The first live `skillc collection-run` found three defaults that fake-docker
# tests could not: codex refused the non-git `/work`, the agent container had
# no network, and one `--timeout` bounded both a docker call and the agent. Each
# test below FAILS on the #121 code these defaults replaced.


def test_default_client_argv_skips_the_git_repo_check() -> None:
    assert "--skip-git-repo-check" in cc.DEFAULT_CLIENT_ARGV


def test_agent_backend_has_egress_and_the_grading_backend_does_not(base: Path, docker_state: Path) -> None:
    agent, grading = cc.agent_backends(
        image="fake-image:1", base=base, docker_bin=_docker_bin(docker_state), daemon_timeout=5,
    )
    assert agent.network == cc.AGENT_NETWORK != "none"
    assert grading.network == "none"


def _describe_text(backend: d.DockerBackend) -> tuple[str, str]:
    description = backend.describe()
    return "\n".join(description.isolation), "\n".join(description.unobserved)


def test_describe_never_claims_blocked_egress_on_an_open_network(base: Path, docker_state: Path) -> None:
    agent, grading = cc.agent_backends(
        image="fake-image:1", base=base, docker_bin=_docker_bin(docker_state), daemon_timeout=5,
    )
    open_isolation, open_unobserved = _describe_text(agent)
    assert "egress OPEN" in open_isolation
    assert "egress actually blocked" not in open_unobserved
    # The control: the contained backend still states its unverified claim.
    closed_isolation, closed_unobserved = _describe_text(grading)
    assert "egress OPEN" not in closed_isolation
    assert "network=none by default" in closed_isolation
    assert "egress actually blocked" in closed_unobserved


def test_paste_back_states_the_agent_network() -> None:
    record: dict[str, object] = {"disposition": "unavailable", "observation": None, "graded": None}
    stated = cc.build_collection_paste_back(cc.CollectionAgentResult("s", "v1", "c", record, agent_network="bridge"))
    unknown = cc.build_collection_paste_back(cc.CollectionAgentResult("s", "v1", "c", record))
    assert "agent_network=bridge" in stated
    assert "agent_network=None" in unknown


def test_each_run_gets_its_own_root_and_drops_its_acquisition(base: Path) -> None:
    first = cc.new_run_root(base, "subject-a")
    second = cc.new_run_root(base, "subject-a")
    assert first != second and first.parent == second.parent == base
    for suffix in ("checkout", "staging", "store"):
        (first / f"subject-a-{suffix}").mkdir()
    cc.discard_acquisition(first, "subject-a")
    assert not (first / "subject-a-checkout").exists()
    assert not (first / "subject-a-staging").exists()
    assert (first / "subject-a-store").is_dir()  # the evidence stays


def test_cli_wires_the_agent_timeout_backends_and_run_root(
    base: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """`cmd_collection_run` end to end with the acquisition, planning and the
    attempt itself replaced - the wiring is what is under test: the agent's
    wall-clock limit is NOT `--timeout`, the agent backend has egress while
    the grader does not, and a second run of the same subject on the same
    base does not collide with the first."""
    from skillc import cli

    seen: list[dict[str, object]] = []
    client = {"name": "codex"}

    def fake_acquire(name: str, root: Path) -> object:
        (root / f"{name}-checkout").mkdir()
        return SimpleNamespace(subject=SimpleNamespace(client=client["name"]))

    def fake_run(**kwargs: object) -> cc.CollectionAgentResult:
        seen.append(kwargs)
        backend = kwargs["backend"]
        assert isinstance(backend, d.DockerBackend)
        return cc.CollectionAgentResult(
            str(kwargs["subject_name"]), "v1", "codex", {"disposition": "unavailable"}, agent_network=backend.network,
        )

    monkeypatch.setattr(cc, "acquire_collection", fake_acquire)
    monkeypatch.setattr(demo, "resolve_image_digest", lambda *a, **k: None)
    monkeypatch.setattr(trial, "open_store", lambda path, forbidden: path)
    monkeypatch.setattr(cc, "plan_collection_attempt", lambda *a, **k: (object(), "a-1"))
    monkeypatch.setattr(cc, "run_collection_agent_attempt", fake_run)
    # Never the host's real daemon from a unit test.
    monkeypatch.setattr(reap, "snapshot", lambda *a, **k: reap.Snapshot(False, frozenset(), frozenset()))

    argv = ["collection-run", "subject-a", "--base", str(base), "--timeout", "7"]
    assert cli.main(argv) == 1  # not captured, not PASS
    assert cli.main(argv) == 1  # the same subject again: no fixed-path collision

    first, second = seen
    assert first["timeout"] == cc.DEFAULT_AGENT_TIMEOUT != 7
    assert list(first["base_argv"]) == list(cc.DEFAULT_CLIENT_ARGV)  # type: ignore[call-overload]
    agent, grading = first["backend"], first["grading_backend"]
    assert isinstance(agent, d.DockerBackend) and isinstance(grading, d.DockerBackend)
    assert agent.network == cc.AGENT_NETWORK and grading.network == "none"
    assert first["base"] != second["base"]
    for run in (first, second):
        run_root = run["base"]
        assert isinstance(run_root, Path) and run_root.parent == base
        assert not (run_root / "subject-a-checkout").exists()
    assert "agent_network=bridge" in capsys.readouterr().out

    seen.clear()
    assert cli.main([*argv, "--agent-timeout", "42"]) == 1
    assert seen[0]["timeout"] == 42

    # Issue #124: the default argv follows the client the SUBJECT declares,
    # never a codex default applied to every subject.
    seen.clear()
    client["name"] = "claude"
    assert cli.main(argv) == 1
    assert list(seen[0]["base_argv"]) == list(cc.DEFAULT_CLIENT_ARGVS["claude"])  # type: ignore[call-overload]
    assert list(seen[0]["base_argv"]) != list(cc.DEFAULT_CLIENT_ARGV)  # type: ignore[call-overload]


# ------------------------------------------------- cmd_collection_run's own gate


def _collection_run_args(subject: str, **overrides: object) -> argparse.Namespace:
    from skillc import cli

    parser = cli.build_parser()
    args = parser.parse_args(["collection-run", subject])
    for key, value in overrides.items():
        setattr(args, key, value)
    return args


def _stub_acquisition(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Lets `cli.cmd_collection_run` run its own real `cc.acquire_collection`
    and `cc.plan_collection_attempt` against a committed fixture collection,
    without a real git clone - mirrors `tests/test_demo.py`'s own
    `_fake_acquire` convention. Only `cc.run_collection_agent_attempt` itself
    (the real-agent leg) is mocked by the tests below."""
    collection = _fixture_collection(tmp_path, {"greet": "greet"})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject())

    def _fake_acquire(subject: materialize.Subject, into: Path, timeout: float = 300) -> Path:
        shutil.copytree(collection, into, dirs_exist_ok=True)
        return into

    monkeypatch.setattr(demo, "acquire_subject_checkout", _fake_acquire)


def _prepared(kwargs: dict[str, object]) -> None:
    """What a real attempt does to the tracking backends: prepare one attempt
    each. Nothing exists on the fake daemon under these ids, so the
    attributable-leftover check has real ids to ask about and finds none."""
    for key, attempt_id in (("backend", "a-fake"), ("grading_backend", "probe-fake")):
        backend = kwargs[key]
        assert isinstance(backend, cc.TrackingDockerBackend)
        backend.prepared_ids.append(attempt_id)


def _fake_collection_result(
    subject_name: str, *, disposition: str, graded: dict[str, object] | None,
    backend_teardown: str = "confirmed",
) -> cc.CollectionAgentResult:
    record: dict[str, object] = {
        "disposition": disposition,
        "backend_teardown": backend_teardown,
        "graded": graded,
        "observation": {
            "prompt_delivered": True, "canary_satisfied": True,
            "skill_invocations": [], "skill_invocation_detection": "none",
            "credential_refresh_observed_in_container": False,
        },
        "grading_blocked_reason": None if graded is not None else "canary not satisfied",
    }
    return cc.CollectionAgentResult(subject_name=subject_name, revision="r1", client="codex", record=record)


def test_cmd_collection_run_exits_1_when_grading_is_blocked(
    tmp_path: Path, base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Red case (issue #120's review of #121, HIGH): reverting `cli.py`'s
    `graded_ok` gate back to `return 0 if disposition == "captured" else 1`
    (the shape a cross-model review already flagged once) leaves the full
    suite green with no guard. `graded=None` is the grading-BLOCKED shape
    (`run_collection_agent_attempt`'s own `grading_blocked_reason`) - a
    captured-but-ungraded attempt must never read as CLI success."""
    from skillc import cli

    _stub_acquisition(tmp_path, monkeypatch)

    def _fake_run(**kwargs: object) -> cc.CollectionAgentResult:
        _prepared(kwargs)
        return _fake_collection_result("whatever", disposition="captured", graded=None)

    monkeypatch.setattr(cc, "run_collection_agent_attempt", _fake_run)
    args = _collection_run_args(
        "whatever", image="fake-image:1", docker_bin=" ".join(_docker_bin(docker_state)), base=str(base), timeout=5,
    )
    assert cli.cmd_collection_run(args) == 1


def test_cmd_collection_run_exits_1_when_grading_failed(
    tmp_path: Path, base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Red case (issue #120's review of #121, HIGH), the other shape: `graded`
    IS a dict, but its status is `FAIL`, not `PASS`."""
    from skillc import cli

    _stub_acquisition(tmp_path, monkeypatch)

    def _fake_run(**kwargs: object) -> cc.CollectionAgentResult:
        _prepared(kwargs)
        return _fake_collection_result(
            "whatever", disposition="captured", graded={"status": "FAIL", "detail": "wrong output"},
        )

    monkeypatch.setattr(cc, "run_collection_agent_attempt", _fake_run)
    args = _collection_run_args(
        "whatever", image="fake-image:1", docker_bin=" ".join(_docker_bin(docker_state)), base=str(base), timeout=5,
    )
    assert cli.cmd_collection_run(args) == 1


def test_cmd_collection_run_exits_0_on_full_success(
    tmp_path: Path, base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other side of the same gate: `disposition="captured"` AND an
    actual PASS verdict is the only case that exits 0."""
    from skillc import cli

    _stub_acquisition(tmp_path, monkeypatch)

    def _fake_run(**kwargs: object) -> cc.CollectionAgentResult:
        _prepared(kwargs)
        return _fake_collection_result("whatever", disposition="captured", graded={"status": "PASS", "detail": "ok"})

    monkeypatch.setattr(cc, "run_collection_agent_attempt", _fake_run)
    args = _collection_run_args(
        "whatever", image="fake-image:1", docker_bin=" ".join(_docker_bin(docker_state)), base=str(base), timeout=5,
    )
    assert cli.cmd_collection_run(args) == 0


@pytest.mark.parametrize("name", ["missing/collection", "../subjects/cpp-codex", "..", ""])
def test_a_path_like_subject_is_refused_before_any_scratch_path(
    name: str, base: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """Codex review of #11: the per-run root is built from the subject name,
    so a name carrying a path separator reached `mkdtemp`'s prefix before the
    subject was validated and died with a host-path traceback - #118's defect
    class - instead of the controlled `SubjectRefused`, exit 2."""
    from skillc import cli

    with pytest.raises(demo.SubjectRefused):
        cc.new_run_root(base, name)
    assert cli.main(["collection-run", name, "--base", str(base)]) == 2
    assert "Traceback" not in capsys.readouterr().err
    assert list(base.iterdir()) == []


def test_cmd_collection_run_exits_1_when_teardown_is_not_confirmed(
    tmp_path: Path, base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #106: a PASS whose container teardown could not be confirmed is
    not a clean run. Red against the pre-#106 gate, which read only the
    disposition and the grade."""
    from skillc import cli

    _stub_acquisition(tmp_path, monkeypatch)

    def _fake_run(**kwargs: object) -> cc.CollectionAgentResult:
        _prepared(kwargs)
        return _fake_collection_result(
            "whatever", disposition="captured", graded={"status": "PASS"}, backend_teardown="unknown",
        )

    monkeypatch.setattr(cc, "run_collection_agent_attempt", _fake_run)
    args = _collection_run_args(
        "whatever", image="fake-image:1", docker_bin=" ".join(_docker_bin(docker_state)), base=str(base), timeout=5,
    )
    assert cli.cmd_collection_run(args) == 1


def test_cmd_collection_run_exits_1_on_a_container_left_by_this_run(
    tmp_path: Path, base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Issue #106: a container still labelled with one of THIS run's attempt
    ids fails the run, even on PASS."""
    from skillc import cli

    _stub_acquisition(tmp_path, monkeypatch)
    asked: list[list[str]] = []

    def _leftovers(docker_bin: object, attempt_ids: list[str], timeout: float) -> list[str]:
        asked.append(list(attempt_ids))
        return ["skillc-a-fake"]

    monkeypatch.setattr(cc, "attributable_leftovers", _leftovers)

    def _fake_run(**kwargs: object) -> cc.CollectionAgentResult:
        _prepared(kwargs)
        return _fake_collection_result("whatever", disposition="captured", graded={"status": "PASS"})

    monkeypatch.setattr(cc, "run_collection_agent_attempt", _fake_run)
    args = _collection_run_args(
        "whatever", image="fake-image:1", docker_bin=" ".join(_docker_bin(docker_state)), base=str(base), timeout=5,
    )
    assert cli.cmd_collection_run(args) == 1
    assert asked == [["a-fake", "probe-fake"]]  # the agent's id AND the grading probe's
    assert "attributable_leftover_containers=1 (attempts_checked=2)" in capsys.readouterr().out


def test_a_concurrent_run_s_container_does_not_fail_a_clean_run(
    tmp_path: Path, base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Codex review: the daemon-wide diff cannot attribute. A skillc-owned
    container a NEIGHBOUR started during this run is reported as context,
    and does not flip a clean run's verdict."""
    from skillc import cli

    _stub_acquisition(tmp_path, monkeypatch)
    snaps = iter([
        reap.Snapshot(True, frozenset(), frozenset()),
        reap.Snapshot(True, frozenset({"skillc-someone-else"}), frozenset()),
    ])
    monkeypatch.setattr(reap, "snapshot", lambda *a, **k: next(snaps))

    def _fake_run(**kwargs: object) -> cc.CollectionAgentResult:
        _prepared(kwargs)
        return _fake_collection_result("whatever", disposition="captured", graded={"status": "PASS"})

    monkeypatch.setattr(cc, "run_collection_agent_attempt", _fake_run)
    args = _collection_run_args(
        "whatever", image="fake-image:1", docker_bin=" ".join(_docker_bin(docker_state)), base=str(base), timeout=5,
    )
    assert cli.cmd_collection_run(args) == 0
    out = capsys.readouterr().out
    assert "attributable_leftover_containers=0 (attempts_checked=2)" in out
    assert "context: daemon_comparable=True leaked_owned_containers=1" in out


def test_no_prepared_attempt_is_not_a_clean_cleanup(docker_state: Path) -> None:
    """An empty id list means nothing was checked: `None`, never `[]`."""
    assert cc.attributable_leftovers(_docker_bin(docker_state), [], 5) is None
    assert cc.attributable_leftovers(_docker_bin(docker_state), ["a-none"], 5) == []


def test_attributable_leftovers_finds_a_real_container_on_the_fake_daemon(
    base: Path, docker_state: Path,
) -> None:
    """The check against a daemon that really holds the container: prepared
    and never destroyed, it is found by its attempt label."""
    backend = cc.TrackingDockerBackend(image="fake-image:1", base_dir=base, docker_bin=_docker_bin(docker_state))
    handle = backend.prepare("a-kept")
    try:
        found = cc.attributable_leftovers(_docker_bin(docker_state), backend.prepared_ids, 5)
        assert found is not None and len(found) == 1
    finally:
        backend.destroy(handle)
    assert cc.attributable_leftovers(_docker_bin(docker_state), backend.prepared_ids, 5) == []


def test_an_oauth_token_embedded_in_a_record_string_blocks_the_record_file(
    tmp_path: Path, base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Codex review, red on the serialized-text-only check: `json.dumps`
    escapes the quotes inside a string value, so OAuth-shaped JSON embedded
    in a grader's detail stopped matching the token pattern. The record file
    must not be written; the paste-back says `record_written=False`."""
    from skillc import cli

    _stub_acquisition(tmp_path, monkeypatch)
    token_json = json.dumps({"access_token": "Zq7" + "x" * 37})

    def _fake_run(**kwargs: object) -> cc.CollectionAgentResult:
        _prepared(kwargs)
        return _fake_collection_result(
            "whatever", disposition="captured", graded={"status": "PASS", "detail": token_json},
        )

    monkeypatch.setattr(cc, "run_collection_agent_attempt", _fake_run)
    args = _collection_run_args(
        "whatever", image="fake-image:1", docker_bin=" ".join(_docker_bin(docker_state)), base=str(base), timeout=5,
    )
    cli.cmd_collection_run(args)
    assert "record_written=False" in capsys.readouterr().out
    assert not list(base.glob("skillc-collection-run-whatever-*/whatever-store/collection-run-record.json"))


def test_cmd_collection_run_reports_a_host_credential_the_run_changed(
    tmp_path: Path, base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The host-login evidence end to end through the CLI: the attempt (here a
    stand-in) rewrites the operator's credential file, and the paste-back
    says so. Also: the full record is written into the kept store."""
    from skillc import cli

    _stub_acquisition(tmp_path, monkeypatch)
    cred = _fresh_codex_credential(tmp_path)

    def _fake_run(**kwargs: object) -> cc.CollectionAgentResult:
        assert kwargs["minimum_credential_seconds"] == 5
        _prepared(kwargs)
        cred.write_text(cred.read_text() + " ")
        return _fake_collection_result("whatever", disposition="captured", graded={"status": "PASS"})

    monkeypatch.setattr(cc, "run_collection_agent_attempt", _fake_run)
    args = _collection_run_args(
        "whatever", image="fake-image:1", docker_bin=" ".join(_docker_bin(docker_state)), base=str(base), timeout=5,
        credential=str(cred), minimum_credential_seconds=5,
    )
    cli.cmd_collection_run(args)
    out = capsys.readouterr().out
    assert "host_credential_unchanged=False" in out
    assert "record_written=True" in out
    [record_file] = list(base.glob("skillc-collection-run-whatever-*/whatever-store/collection-run-record.json"))
    saved = json.loads(record_file.read_text())
    # The envelope, not the bare record (codex review): what the paste-back
    # states about the host and the cleanup is saved too - never the digest.
    assert saved["record"]["disposition"] == "captured"
    assert saved["host_credential"]["unchanged"] is False
    assert saved["attributable_leftovers"] == [] and saved["attempts_checked"] == 2
    assert "digest" not in json.dumps(saved["host_credential"])


# ------------------------------------------------ the Claude Code arm (#124)


def _claude_subject(select: object = "all") -> materialize.Subject:
    return materialize.Subject.from_dict({
        "subject_schema": 1, "locator": "test/test", "revision": "v1", "surface": "claude-code-skills",
        "skills_root": "skills", "select": select, "client": {"name": "claude", "version": "2.1.283"},
    })


def _fresh_claude_credential(tmp_path: Path) -> Path:
    path = tmp_path / "claude-credential.json"
    path.write_text(json.dumps({"claudeAiOauth": {"expiresAt": int((time.time() + 3600) * 1000)}}))
    return path


def _claude_run(
    tmp_path: Path, base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
    *, extra: list[str] | None = None, drop_skill: str | None = None,
) -> cc.CollectionAgentResult:
    """One scripted Claude Code collection attempt with `tdd` and
    `diagnosing-bugs` selected. The fake client lists whatever is installed
    under `<home>/.claude/skills/` (`fake_agent_client.py`), so `drop_skill`
    - withholding one skill's files from the container - is a genuinely
    uninstalled skill, not a told-to-omit one."""
    repo = _fixture_collection(tmp_path, {"tdd": "tdd", "diagnosing-bugs": "diagnosing-bugs"})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _claude_subject(select=["tdd", "diagnosing-bugs"]))
    if drop_skill is not None:
        real = cc._collection_home_files

        def _withheld(source: materialize.Source, files: list[demo.SubjectFile]) -> dict[str, bytes]:
            return real(source, [f for f in files if f.skill != drop_skill])

        monkeypatch.setattr(cc, "_collection_home_files", _withheld)

    acquired = cc.acquire_collection("whatever", base, checkout=repo)
    store = trial.open_store(tmp_path / "store", forbidden=[])
    experiment, attempt_id = cc.plan_collection_attempt("whatever", acquired, store, image_digest=_BACKEND_IMAGE_DIGEST)
    home = _mapped_home(docker_state, attempt_id)
    argv = [
        sys.executable, str(FAKE_CLIENT), "--format", "claude-fake", "--home", str(home),
        "--transcript-relpath", ".claude/projects/-work/77777777-7777-7777-7777-777777777777.jsonl",
        "--copy-solution", str(GRADER_ROOT / "reference"), *(extra or []),
    ]
    return cc.run_collection_agent_attempt(
        subject_name="whatever", acquired=acquired, experiment=experiment, attempt_id=attempt_id,
        backend=_backend(base, docker_state), grading_backend=_backend(base, docker_state), base=base,
        base_argv=argv, prompt="Fix the slug helper.", timeout=5,
        credential_explicit_path=_fresh_claude_credential(tmp_path),
    )


def test_claude_subject_installs_under_claude_skills_and_every_skill_is_listed(
    tmp_path: Path, base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _claude_run(tmp_path, base, docker_state, monkeypatch)

    assert result.client == "claude"
    assert result.record["disposition"] == "captured"
    graded = result.record["graded"]
    assert isinstance(graded, dict) and graded["status"] == "PASS"
    observation = result.record["observation"]
    assert isinstance(observation, dict)
    assert observation["skill_invocation_detection"] == "structural"  # claude's ClientSpec, not codex's
    assert observation["skills_listed_source"] == "transcript skill_listing attachment"
    assert result.discovery == {"tdd": "listed", "diagnosing-bugs": "listed"}
    assert result.discovery_reason is None and not result.discovery_failed
    paste = cc.build_collection_paste_back(result)
    assert "client=claude" in paste
    assert "discovery={'diagnosing-bugs': 'listed', 'tdd': 'listed'} (source=transcript skill_listing)" in paste


def test_a_skill_that_was_not_installed_turns_discovery_red(
    tmp_path: Path, base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR 0001's red case for the new check (issue #124's own wording: "a
    skill not installed must turn the install/discovery check red")."""
    result = _claude_run(tmp_path, base, docker_state, monkeypatch, drop_skill="tdd")

    assert result.discovery == {"tdd": "not-listed", "diagnosing-bugs": "listed"}
    assert result.discovery_failed


def test_a_skill_the_client_did_not_list_turns_discovery_red(
    tmp_path: Path, base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other shape: installed, but the client's own listing leaves it out."""
    result = _claude_run(tmp_path, base, docker_state, monkeypatch, extra=["--omit-listed", "diagnosing-bugs"])

    assert result.discovery == {"tdd": "listed", "diagnosing-bugs": "not-listed"}
    assert result.discovery_failed


def test_no_listing_in_the_transcript_is_unmeasured_never_a_pass_or_a_fail(
    tmp_path: Path, base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _claude_run(tmp_path, base, docker_state, monkeypatch, extra=["--no-skill-listing"])

    assert result.discovery == {"tdd": "UNMEASURED", "diagnosing-bugs": "UNMEASURED"}
    assert result.discovery_reason is not None and "no skill_listing attachment" in result.discovery_reason
    assert not result.discovery_failed
    assert "discovery=UNMEASURED (" in cc.build_collection_paste_back(result)


def test_a_codex_run_reports_discovery_unmeasured_not_borrowed(
    tmp_path: Path, base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Codex's transcript carries no listing this adapter reads: its
    collection-run discovery is UNMEASURED, and says so."""
    repo = _fixture_collection(tmp_path, {"tdd": "tdd"})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject(select=["tdd"]))
    acquired = cc.acquire_collection("whatever", base, checkout=repo)
    store = trial.open_store(tmp_path / "store", forbidden=[])
    experiment, attempt_id = cc.plan_collection_attempt("whatever", acquired, store, image_digest=_BACKEND_IMAGE_DIGEST)
    argv = _codex_argv(
        home=_mapped_home(docker_state, attempt_id), transcript_relpath=".codex/sessions/2026/01/01/rollout-d.jsonl",
    )
    result = cc.run_collection_agent_attempt(
        subject_name="whatever", acquired=acquired, experiment=experiment, attempt_id=attempt_id,
        backend=_backend(base, docker_state), grading_backend=_backend(base, docker_state), base=base,
        base_argv=argv, prompt="Fix the slug helper.", timeout=5,
        credential_explicit_path=_fresh_codex_credential(tmp_path),
    )
    assert result.discovery == {"tdd": "UNMEASURED"}
    assert result.discovery_reason is not None and "carries no skill listing" in result.discovery_reason


def test_missing_claude_credential_blocks_before_launch(
    tmp_path: Path, base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The planned control, on the Claude arm: no credential, `unavailable`."""
    repo = _fixture_collection(tmp_path, {"tdd": "tdd"})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _claude_subject(select=["tdd"]))
    acquired = cc.acquire_collection("whatever", base, checkout=repo)
    store = trial.open_store(tmp_path / "store", forbidden=[])
    experiment, attempt_id = cc.plan_collection_attempt("whatever", acquired, store, image_digest=_BACKEND_IMAGE_DIGEST)
    result = cc.run_collection_agent_attempt(
        subject_name="whatever", acquired=acquired, experiment=experiment, attempt_id=attempt_id,
        backend=_backend(base, docker_state), grading_backend=_backend(base, docker_state), base=base,
        base_argv=[sys.executable, "-c", "import sys; sys.exit(1)"], prompt="Fix the slug helper.", timeout=5,
        credential_explicit_path=tmp_path / "does-not-exist.json",
    )
    assert result.record["disposition"] == "unavailable"
    assert result.discovery == {"tdd": "UNMEASURED"}


@pytest.mark.parametrize(("discovery", "expected"), [
    ({"greet": "listed"}, 0),
    ({"greet": "not-listed"}, 1),  # the red case: a PASS does not excuse an unlisted skill
    ({"greet": "UNMEASURED"}, 0),  # stated in the paste-back, not failed
])
def test_cmd_collection_run_exit_follows_measured_discovery(
    tmp_path: Path, base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
    discovery: dict[str, str], expected: int,
) -> None:
    from skillc import cli

    _stub_acquisition(tmp_path, monkeypatch)

    def _fake_run(**kwargs: object) -> cc.CollectionAgentResult:
        _prepared(kwargs)  # a clean teardown, so discovery is the only variable
        passed = _fake_collection_result("whatever", disposition="captured", graded={"status": "PASS", "detail": "ok"})
        reason = "stated" if "UNMEASURED" in discovery.values() else None
        return cc.CollectionAgentResult(
            passed.subject_name, passed.revision, "claude", passed.record, discovery=discovery, discovery_reason=reason,
        )

    monkeypatch.setattr(cc, "run_collection_agent_attempt", _fake_run)
    args = _collection_run_args(
        "whatever", image="fake-image:1", docker_bin=" ".join(_docker_bin(docker_state)), base=str(base), timeout=5,
    )
    assert cli.cmd_collection_run(args) == expected


# --------------------------------------------------------- #150-D: a real installation receipt


def _receipt_run(
    tmp_path: Path, base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
    *, listing_mode: str, skills: dict[str, str] | None = None,
) -> tuple[cc.CollectionAgentResult, trial.Experiment, str]:
    repo = _fixture_collection(tmp_path, skills if skills is not None else {"tdd": "tdd"})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject(select=list((skills or {"tdd": "tdd"}).keys())))
    listing_client = _fake_codex_listing(tmp_path, mode=listing_mode)

    acquired = cc.acquire_collection("whatever", base, checkout=repo)
    store = trial.open_store(tmp_path / "store", forbidden=[])
    experiment, attempt_id = cc.plan_collection_attempt(
        "whatever", acquired, store, image_digest=_BACKEND_IMAGE_DIGEST,
    )
    argv = _codex_argv(
        home=_mapped_home(docker_state, attempt_id),
        transcript_relpath=".codex/sessions/2026/01/01/rollout-receipt.jsonl",
        copy_solution=GRADER_ROOT / "reference",
    )
    result = cc.run_collection_agent_attempt(
        subject_name="whatever", acquired=acquired, experiment=experiment, attempt_id=attempt_id,
        backend=_backend(base, docker_state), grading_backend=_backend(base, docker_state), base=base,
        base_argv=argv, prompt="Fix the slug helper.", timeout=5,
        credential_explicit_path=_fresh_codex_credential(tmp_path),
        listing_client_argv=listing_client,
    )
    return result, experiment, attempt_id


def test_receipt_discovery_satisfied_reaches_pass(
    tmp_path: Path, base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The happy path: a codex arm that installs a declared collection and
    whose listing correctly discovers it writes a real installation
    receipt, and the STORED result (not merely the task grade) reaches
    PASS - #139's B1 no longer applies to this arm."""
    result, experiment, attempt_id = _receipt_run(tmp_path, base, docker_state, monkeypatch, listing_mode="normal")
    assert result.record["disposition"] == "captured"
    graded = result.record["graded"]
    assert isinstance(graded, dict), result.record.get("grading_blocked_reason")
    assert graded["result_status"] == "PASS", graded

    receipt_path = experiment.root / f"receipt-{attempt_id}.json"
    assert receipt_path.is_file()
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["readiness"]["discovery_canary"] == "SATISFIED", receipt["readiness"]
    assert receipt["readiness"]["baseline_absence"] == "SATISFIED", receipt["readiness"]
    assert receipt["readiness"]["evidence"] == agent_trial._DISCOVERY_RECEIPT_CLAIM


def test_ruling_red_1_a_canary_failing_installing_arm_is_not_pass(
    tmp_path: Path, base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR 0005's ruling, red case 1: an installing arm whose listing omits
    the declared skill ("blind" mode: `fake_codex.py` lists only its own
    `.system` skill) must not reach PASS - a real receipt now backs this
    arm, and it reads VIOLATED, not SATISFIED."""
    result, experiment, attempt_id = _receipt_run(tmp_path, base, docker_state, monkeypatch, listing_mode="blind")
    graded = result.record["graded"]
    assert isinstance(graded, dict), result.record.get("grading_blocked_reason")
    assert graded["result_status"] != "PASS", graded

    receipt = json.loads((experiment.root / f"receipt-{attempt_id}.json").read_text(encoding="utf-8"))
    assert receipt["readiness"]["discovery_canary"] == "VIOLATED", receipt["readiness"]


def test_ruling_red_3_an_unobtainable_listing_is_unknown_not_pass(
    tmp_path: Path, base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR 0005's ruling, red case 3: a listing container whose client
    crashes must read UNKNOWN, never SATISFIED, and the stored result must
    not reach PASS on it."""
    result, experiment, attempt_id = _receipt_run(tmp_path, base, docker_state, monkeypatch, listing_mode="crash")
    graded = result.record["graded"]
    assert isinstance(graded, dict), result.record.get("grading_blocked_reason")
    assert graded["result_status"] != "PASS", graded

    receipt = json.loads((experiment.root / f"receipt-{attempt_id}.json").read_text(encoding="utf-8"))
    assert receipt["readiness"]["discovery_canary"] == "UNKNOWN", receipt["readiness"]


def test_receipt_refused_when_the_measured_image_digest_does_not_match_the_ledger(
    tmp_path: Path, base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """verify.py's #150-D image-digest cross-check: a receipt measured
    against one image must be refused for an attempt whose ledger plans a
    DIFFERENT image - grading raises rather than silently trusting a stale
    receipt."""
    repo = _fixture_collection(tmp_path, {"tdd": "tdd"})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject(select=["tdd"]))
    listing_client = _fake_codex_listing(tmp_path, mode="normal")

    acquired = cc.acquire_collection("whatever", base, checkout=repo)
    store = trial.open_store(tmp_path / "store", forbidden=[])
    # A DIFFERENT planned image digest than the one the backend/listing
    # containers will actually measure (_BACKEND_IMAGE_DIGEST) - simulating
    # a tag that moved between planning and this run.
    experiment, attempt_id = cc.plan_collection_attempt(
        "whatever", acquired, store, image_digest="sha256:some-other-image-entirely",
    )
    argv = _codex_argv(
        home=_mapped_home(docker_state, attempt_id),
        transcript_relpath=".codex/sessions/2026/01/01/rollout-mismatch.jsonl",
    )
    with pytest.raises(trial.Refused, match="image"):
        cc.run_collection_agent_attempt(
            subject_name="whatever", acquired=acquired, experiment=experiment, attempt_id=attempt_id,
            backend=_backend(base, docker_state), grading_backend=_backend(base, docker_state), base=base,
            base_argv=argv, prompt="Fix the slug helper.", timeout=5,
            credential_explicit_path=_fresh_codex_credential(tmp_path),
            listing_client_argv=listing_client,
        )


def test_cli_collection_run_resolves_its_own_image_digest_and_reaches_pass(
    tmp_path: Path, base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every other test in this file hands `plan_collection_attempt` an
    `image_digest=` by hand. That proves the RECEIPT and VERIFIER agree with
    each other; it says nothing about whether the real CLI path ever
    actually supplies one. `cmd_collection_run` (skillc/cli.py) resolves a
    digest itself, before planning: `demo.resolve_image_digest(docker_bin,
    image, None, args.timeout)`, threaded straight into
    `plan_collection_attempt(..., image_digest=image_digest, ...)`. This
    test drives `cli.main(["collection-run", ...])` directly - the real
    entry point, with NO test-supplied digest anywhere - and if that
    production wiring were actually returning `None` (rendered as the
    planned `"UNKNOWN"` marker `plan_collection_attempt`'s own docstring
    describes), the #150-D image cross-check would refuse the receipt as an
    uncaught `trial.Refused`, not a quiet FAIL; this test would show that
    directly, the same way the pre-existing-regression tests did before
    they threaded a digest in by hand.

    Discovery listing is also exercised as production actually calls it:
    `cmd_collection_run` passes no `listing_client_argv` (that parameter has
    no CLI flag), so the receipt's listing runs the bare client name
    (`codex`) exactly as a real container resolves it via `PATH` - never
    `_fake_codex_listing`'s own explicit-argv convention, which production
    has no flag to request. A scripted `codex` executable (still
    `fake_codex.py`'s own logic, just reachable under its real name instead
    of via `sys.executable <path>`) is put on `PATH` for this one test, the
    same way a real trial image's installed binary already is."""
    from skillc import cli

    repo = _fixture_collection(tmp_path, {"tdd": "tdd"})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject(select=["tdd"]))

    def fake_checkout(subject: object, into: Path, timeout: float = 300) -> Path:
        shutil.copytree(repo, into)
        return into

    monkeypatch.setattr(demo, "acquire_subject_checkout", fake_checkout)

    # cli.main gives no way to learn a randomly-generated attempt_id before
    # --client-argv must be built (unlike this file's other tests, which
    # call plan_collection_attempt themselves first) - pinned so --home can
    # be computed ahead of time, exactly as trial._new_attempt_id already
    # documents itself as the one place a real attempt id comes from.
    fixed_attempt_id = "a-cliflipprod"
    monkeypatch.setattr(trial, "_new_attempt_id", lambda: fixed_attempt_id)

    codex_dir = tmp_path / "fake-path-bin"
    codex_dir.mkdir()
    codex_impl = codex_dir / "_fake_codex_impl.py"
    shutil.copy(CODEX_FIXTURE / "fake_codex.py", codex_impl)
    codex_impl.with_suffix(".mode").write_text(json.dumps({"mode": "normal"}), encoding="utf-8")
    codex_wrapper = codex_dir / "codex"
    codex_wrapper.write_text(
        f"#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(codex_impl))} \"$@\"\n",
        encoding="utf-8",
    )
    codex_wrapper.chmod(0o755)
    monkeypatch.setenv("PATH", f"{codex_dir}{os.pathsep}{os.environ.get('PATH', '')}")

    home = _mapped_home(docker_state, fixed_attempt_id)
    client_argv = _codex_argv(
        home=home, transcript_relpath=".codex/sessions/2026/01/01/rollout-cli-flip.jsonl",
        copy_solution=GRADER_ROOT / "reference",
    )
    argv = [
        "collection-run", "whatever",
        "--base", str(base),
        "--image", _BACKEND_IMAGE,
        "--docker-bin", " ".join(_docker_bin(docker_state)),
        "--client-argv", " ".join(client_argv),
        "--credential", str(_fresh_codex_credential(tmp_path)),
        "--timeout", "5",
    ]

    code = cli.main(argv)

    assert code == 0, "the real CLI path did not reach PASS - receipt refused or discovery not SATISFIED"


# ------------------------------------------------ transcript retention (#202)


def _run_codex_attempt(
    tmp_path: Path, base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch, *,
    transcript_relpath: str = ".codex/sessions/2026/01/01/rollout-tr.jsonl",
    plant_skill: list[str] | None = None, plant_leak: bool = False,
) -> tuple[trial.Experiment, str, cc.CollectionAgentResult]:
    repo = _fixture_collection(tmp_path, {"tdd": "tdd"})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject(select=["tdd"]))
    acquired = cc.acquire_collection("whatever", base, checkout=repo)
    store = trial.open_store(tmp_path / "store", forbidden=[])
    experiment, attempt_id = cc.plan_collection_attempt("whatever", acquired, store, image_digest=_BACKEND_IMAGE_DIGEST)
    argv = _codex_argv(
        home=_mapped_home(docker_state, attempt_id), transcript_relpath=transcript_relpath,
        copy_solution=GRADER_ROOT / "reference", plant_skill=plant_skill,
    )
    if plant_leak:
        argv.append("--plant-leak")
    result = cc.run_collection_agent_attempt(
        subject_name="whatever", acquired=acquired, experiment=experiment, attempt_id=attempt_id,
        backend=_backend(base, docker_state), grading_backend=_backend(base, docker_state), base=base,
        base_argv=argv, prompt="Fix the slug helper.", timeout=5,
        credential_explicit_path=_fresh_codex_credential(tmp_path),
    )
    return experiment, attempt_id, result


def _transcript_entry(experiment: trial.Experiment, attempt_id: str) -> dict[str, object]:
    manifest = json.loads((experiment.root / f"manifest-{attempt_id}.json").read_text(encoding="utf-8"))
    entries = [o for o in manifest["observations"] if o.get("stream") == "client-transcript"]
    assert len(entries) == 1, f"expected one client-transcript observation, got {manifest['observations']!r}"
    entry = entries[0]
    assert isinstance(entry, dict)
    return entry


def test_a_codex_attempt_s_store_retains_its_transcript_referenced_from_the_manifest(
    tmp_path: Path, base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#202 regression: before the fix the manifest held only client-events,
    client-stderr and process-lifecycle, and no object in the store was the
    agent's transcript."""
    experiment, attempt_id, result = _run_codex_attempt(tmp_path, base, docker_state, monkeypatch)
    assert result.record["disposition"] == "captured"
    entry = _transcript_entry(experiment, attempt_id)
    assert entry["coverage"] == "complete"
    assert entry["origin"] == "client-reported"
    data = trial._read_object(experiment.root, str(entry["digest"]))
    assert data and len(data) == entry["size"]
    assert b"session_meta" in data or b"response_item" in data  # the rollout itself, not a spool file
    retention = result.record["transcript_retention"]
    assert isinstance(retention, dict)
    assert retention["coverage"] == "complete" and retention["digest"] == entry["digest"]


def test_an_attempt_with_no_transcript_records_coverage_missing_never_silence(
    tmp_path: Path, base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Negative control: the client wrote its transcript outside the sessions
    directory, so none was found - the store says `missing` with a reason,
    and the paste-back says so too."""
    experiment, attempt_id, result = _run_codex_attempt(
        tmp_path, base, docker_state, monkeypatch, transcript_relpath="elsewhere/rollout.jsonl",
    )
    assert result.record["disposition"] == "captured"
    entry = _transcript_entry(experiment, attempt_id)
    assert entry["coverage"] == "missing"
    assert "ref" not in entry and "digest" not in entry
    assert "found 0" in str(entry["reason"])
    paste_back = cc.build_collection_paste_back(result)
    assert "transcript_coverage=missing" in paste_back


def test_a_planted_leak_in_a_transcript_refuses_retention_and_names_only_its_class(
    tmp_path: Path, base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    experiment, attempt_id, result = _run_codex_attempt(tmp_path, base, docker_state, monkeypatch, plant_leak=True)
    entry = _transcript_entry(experiment, attempt_id)
    assert entry["coverage"] == "missing"
    reason = str(entry["reason"])
    assert "credential-token" in reason and "retention refused" in reason
    assert "sk-" not in reason  # the class, never the matched value
    # The planted value reached no object in the store.
    for obj in (experiment.root / trial.OBJECTS).iterdir():
        assert b"sk-" not in obj.read_bytes(), obj.name
    assert result.record["transcript_retention"] == {
        "coverage": "missing", "digest": None, "size": None, "reason": entry["reason"],
    }


def test_skill_invocations_recompute_from_the_retained_transcript(
    tmp_path: Path, base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    experiment, attempt_id, result = _run_codex_attempt(
        tmp_path, base, docker_state, monkeypatch, plant_skill=["tdd"],
    )
    observation = result.record["observation"]
    assert isinstance(observation, dict)
    assert observation["skill_invocations"] == ["tdd"]
    assert agent_trial.recompute_skill_invocations(experiment, attempt_id, "codex") == ("tdd",)


def test_recompute_refuses_when_no_transcript_was_retained(
    tmp_path: Path, base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    experiment, attempt_id, _result = _run_codex_attempt(
        tmp_path, base, docker_state, monkeypatch, transcript_relpath="elsewhere/rollout.jsonl",
    )
    with pytest.raises(trial.Refused, match="no retained transcript"):
        agent_trial.recompute_skill_invocations(experiment, attempt_id, "codex")


def test_evidence_transcript_without_evidence_is_refused_before_anything_runs(
    base: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    from skillc import cli

    assert cli.main(["collection-run", "whatever", "--evidence-transcript", "--base", str(base)]) == 2
    assert "--evidence-transcript needs --evidence" in capsys.readouterr().err
    assert not any(base.iterdir())


def _tool_result_line(output: str) -> bytes:
    """A realistic codex rollout line: the agent's tool output is a JSON
    string, so any quotes in it arrive escaped."""
    return (json.dumps({
        "type": "response_item",
        "payload": {"type": "function_call_output", "call_id": "c1", "output": output},
    }) + "\n").encode("utf-8")


def test_an_oauth_token_escaped_inside_a_tool_result_is_still_refused() -> None:
    """Counter-model review: the raw JSONL escapes the quotes the OAuth
    pattern keys on. Built at runtime so no scanner reads a token here."""
    credential_file = json.dumps({"tokens": {"access_token": "T" * 32}})
    raw = _tool_result_line(credential_file)
    evidence = agent_trial.retainable_transcript(raw)
    assert evidence.data is None
    assert "credential-token at line 1" in str(evidence.reason)
    assert "T" * 32 not in str(evidence.reason)


def test_a_secret_capture_excludes_is_refused_from_a_transcript_too() -> None:
    raw = _tool_result_line("token: " + "gh" + "p_" + "A" * 36)
    evidence = agent_trial.retainable_transcript(raw)
    assert evidence.data is None
    assert "GitHub token" in str(evidence.reason)
    assert "A" * 36 not in str(evidence.reason)


def test_a_clean_transcript_is_retained_byte_for_byte() -> None:
    raw = _tool_result_line("tests passed")
    assert agent_trial.retainable_transcript(raw) == trial.TranscriptEvidence(raw)


def test_recompute_refuses_a_partial_transcript(
    tmp_path: Path, base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    experiment, attempt_id, _result = _run_codex_attempt(tmp_path, base, docker_state, monkeypatch)
    entry = {**_transcript_entry(experiment, attempt_id), "coverage": "partial"}
    monkeypatch.setattr(agent_trial, "_stored_transcript_entry", lambda _e, _a: entry)
    with pytest.raises(trial.Refused, match="only a partial transcript"):
        agent_trial.recompute_skill_invocations(experiment, attempt_id, "codex")
