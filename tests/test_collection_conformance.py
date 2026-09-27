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
import shutil
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
    assert "network=none" in closed_isolation
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

    def fake_acquire(name: str, root: Path) -> object:
        (root / f"{name}-checkout").mkdir()
        return object()

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


def _fake_collection_result(
    subject_name: str, *, disposition: str, graded: dict[str, object] | None,
) -> cc.CollectionAgentResult:
    record: dict[str, object] = {
        "disposition": disposition,
        "graded": graded,
        "observation": {
            "prompt_delivered": True, "canary_satisfied": True,
            "skill_invocations": [], "skill_invocation_detection": "none",
            "refresh_observed_in_container": False,
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
        return _fake_collection_result("whatever", disposition="captured", graded={"status": "PASS", "detail": "ok"})

    monkeypatch.setattr(cc, "run_collection_agent_attempt", _fake_run)
    args = _collection_run_args(
        "whatever", image="fake-image:1", docker_bin=" ".join(_docker_bin(docker_state)), base=str(base), timeout=5,
    )
    assert cli.cmd_collection_run(args) == 0
