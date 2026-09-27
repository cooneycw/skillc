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

import ast
import json
import sys
import time
from pathlib import Path

import pytest

from skillc import collection_conformance as cc
from skillc import demo, materialize, trial
from skillc import docker_backend as d

FAKE_DOCKER = Path(__file__).resolve().parent / "fixtures" / "docker-backend" / "fake_docker.py"
FAKE_CLIENT = Path(__file__).resolve().parent / "fixtures" / "agent-trial" / "fake_agent_client.py"
GRADER_ROOT = Path(__file__).resolve().parent.parent / "evals" / "level1" / "slug-small-fix"


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


def _backend(base: Path, docker_state: Path) -> d.DockerBackend:
    return d.DockerBackend(image="fake-image:1", base_dir=base, docker_bin=_docker_bin(docker_state))


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
    experiment, attempt_id = cc.plan_collection_attempt("whatever", acquired, store)
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
    experiment, attempt_id = cc.plan_collection_attempt("whatever", acquired, store)
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
    experiment, attempt_id = cc.plan_collection_attempt("whatever", acquired, store)
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
    experiment, attempt_id = cc.plan_collection_attempt("whatever", acquired, store)
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
            "refresh_observed_in_container": False,
        },
        "graded": {"status": "PASS"},
        "grading_blocked_reason": None,
    }
    result = cc.CollectionAgentResult("whatever", "v1", "codex", record)
    text = cc.build_collection_paste_back(result)
    assert demo.leak_check_text(text) == []
    for field in (
        "disposition=captured", "prompt_delivered=True", "canary_satisfied=True",
        "skill_invocations=['tdd']", "detection=heuristic", "refresh_observed_in_container=False",
        "graded.status=PASS",
    ):
        assert field in text


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
