"""Tests for issue #150-B2: `collection-run --degraded DIR` installs from a
persisted degraded subject (`degrade-subject --out DIR`) instead of the
pinned pipeline, re-verifying the digest first and recording the degraded
identity - never the pin - in what the attempt reports.

The end-to-end CLI case runs against the fake `docker` CLI and the scripted
fake codex client, exactly like `tests/test_collection_conformance.py`'s own
`test_happy_path_installs_the_collection_and_grades`.
"""

from __future__ import annotations

import base64
import json
import sys
import time
from pathlib import Path

import pytest

from skillc import collection_conformance as cc
from skillc import degrade, demo, materialize, trial
from skillc import docker_backend as d

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


def _subject(revision: str = "v1", select: object = "all") -> materialize.Subject:
    return materialize.Subject.from_dict({
        "subject_schema": 1, "locator": "test/test", "revision": revision, "surface": "codex-skills",
        "skills_root": "skills", "select": select, "client": {"name": "codex", "version": "0.157.1"},
    })


@pytest.fixture(autouse=True)
def _no_network_subject(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(demo, "DEFAULT_SUBJECT", "unused-in-tests")


def _build_degraded_out(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, skills: dict[str, str], removed: str) -> Path:
    collection = _fixture_collection(tmp_path, skills)
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject(select=list(skills)))
    degraded = degrade.acquire_degraded(
        "whatever", tmp_path / "degrade-base", degrade.Mutation(remove_skills=(removed,)), checkout=collection,
    )
    out = tmp_path / "degraded-out"
    out.mkdir()
    (out / "receipt.json").write_text(
        json.dumps(degrade.receipt(degraded, pinned_revision="v1"), indent=1) + "\n", encoding="utf-8",
    )
    degrade.persist_skills(degraded, out)
    return out


# ---------------------------------------------------------- load_persisted_degraded


def test_load_persisted_degraded_returns_a_never_pinned_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    out = _build_degraded_out(tmp_path, monkeypatch, skills={"tdd": "tdd", "other": "other"}, removed="tdd")
    subject = _subject()

    source = degrade.load_persisted_degraded(out, subject, subject_name="whatever")

    assert source.kind == "degraded"
    assert source.revision != subject.revision
    assert source.revision.startswith("degraded:")
    assert source.locator == subject.locator
    assert not (source.surface_dir / "tdd").exists()
    assert (source.surface_dir / "other").is_dir()


def test_load_persisted_degraded_refuses_a_missing_receipt(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(degrade.DegradationRefused, match="no readable receipt"):
        degrade.load_persisted_degraded(out, _subject(), subject_name="whatever")


def test_load_persisted_degraded_refuses_a_tree_built_for_a_different_subject(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Red case (issue #150-B3b review): a degraded tree built for subject A
    (here "whatever"), loaded for subject B (here "someone-else"), must be
    refused - before this check neither `receipt["subject"]` nor
    `receipt["pinned_revision"]` was compared at all, so a degraded tree
    built from one subject installed silently under any other, including a
    different client. `_build_degraded_out` always builds under "whatever"
    (line 68's own `degrade.acquire_degraded("whatever", ...)`), so loading
    it for any other name is exactly this mismatch."""
    out = _build_degraded_out(tmp_path, monkeypatch, skills={"tdd": "tdd", "other": "other"}, removed="tdd")

    with pytest.raises(degrade.DegradationRefused, match="not 'someone-else'"):
        degrade.load_persisted_degraded(out, _subject(), subject_name="someone-else")


def test_load_persisted_degraded_refuses_a_tree_pinned_to_a_different_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Red case (issue #150-B3b review), the other half: the receipt's own
    `pinned_revision` must match the CALLER's `subject.revision` - a
    degraded tree built for the subject's revision "v1" (`_build_degraded_out`
    always writes `pinned_revision="v1"`) must be refused when the subject
    passed in now declares a DIFFERENT pin, e.g. because the subject
    declaration moved on since the degraded tree was built."""
    out = _build_degraded_out(tmp_path, monkeypatch, skills={"tdd": "tdd", "other": "other"}, removed="tdd")

    with pytest.raises(degrade.DegradationRefused, match="does not match"):
        degrade.load_persisted_degraded(out, _subject(revision="v2"), subject_name="whatever")


def test_load_persisted_degraded_refuses_a_tampered_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The red case the orchestrator named directly for 150-B2: a digest
    mismatch between --out DIR/skills and its own receipt is refused."""
    out = _build_degraded_out(tmp_path, monkeypatch, skills={"tdd": "tdd", "other": "other"}, removed="tdd")
    (out / "skills" / "other" / "SKILL.md").write_text(
        (out / "skills" / "other" / "SKILL.md").read_text(encoding="utf-8") + "tampered\n", encoding="utf-8",
    )

    with pytest.raises(degrade.DegradationRefused, match="digest"):
        degrade.load_persisted_degraded(out, _subject(), subject_name="whatever")


def test_load_persisted_degraded_refuses_a_tree_holding_a_skill_the_receipt_never_declared(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Orchestrator review: `load_persisted_degraded` must install exactly
    the skills the receipt says survived, and refuse a persisted tree
    holding one it doesn't list. The digest check already covers this - it
    is over the WHOLE tree, so an ADDED directory changes it exactly as a
    tampered file does - proven directly here rather than merely asserted."""
    out = _build_degraded_out(tmp_path, monkeypatch, skills={"tdd": "tdd", "other": "other"}, removed="tdd")
    # A skill the receipt's own mutation never mentions, added straight into
    # the persisted tree - never through degrade.py at all.
    smuggled = out / "skills" / "smuggled"
    smuggled.mkdir()
    (smuggled / "SKILL.md").write_text(_skill_md("smuggled"), encoding="utf-8")

    with pytest.raises(degrade.DegradationRefused, match="digest"):
        degrade.load_persisted_degraded(out, _subject(), subject_name="whatever")


# ------------------------------------------------------ acquire_degraded_collection


def test_acquire_degraded_collection_installs_what_remains_after_removal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`select` originally names BOTH skills; the degradation removed one.
    Re-applying the original `select` during acquisition would refuse
    (`materialize.inventory` requires every selected name present) - this
    proves it does not: acquisition succeeds and installs only what remains."""
    out = _build_degraded_out(tmp_path, monkeypatch, skills={"tdd": "tdd", "other": "other"}, removed="tdd")

    acquired = cc.acquire_degraded_collection("whatever", out)

    assert acquired.source.revision != acquired.subject.revision
    assert acquired.subject.select == ("tdd", "other")  # the ORIGINAL subject is untouched
    installed_dirs = {f.directory for f in acquired.files}
    assert installed_dirs == {"other"}


# --------------------------------------------------------------------- CLI, end to end


def test_cli_collection_run_degraded_records_the_degraded_identity_never_the_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A source-only degradation (no removal) keeps the one skill installed,
    # so the agent still has something to work with in this end-to-end run.
    collection = _fixture_collection(tmp_path, {"tdd": "tdd"})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject(select=["tdd"]))
    degraded = degrade.acquire_degraded("whatever", tmp_path / "degrade-base", None, checkout=collection)
    out = tmp_path / "degraded-out"
    out.mkdir()
    (out / "receipt.json").write_text(
        json.dumps(degrade.receipt(degraded, pinned_revision="v1"), indent=1) + "\n", encoding="utf-8",
    )
    degrade.persist_skills(degraded, out)

    base = tmp_path / "work"
    base.mkdir()
    docker_state = tmp_path / "docker-state"
    acquired = cc.acquire_degraded_collection("whatever", out)
    store = trial.open_store(tmp_path / "store", forbidden=[])
    experiment, attempt_id = cc.plan_collection_attempt("whatever", acquired, store)
    backend = _backend(base, docker_state)
    grading_backend = _backend(base, docker_state)
    name = d._container_name(attempt_id)
    home = docker_state / f"{name}.fsroot" / "home" / "candidate"
    argv = [
        sys.executable, str(FAKE_CLIENT), "--format", "codex-fake", "--home", str(home),
        "--transcript-relpath", ".codex/sessions/2026/01/01/rollout-cc.jsonl",
        "--copy-solution", str(GRADER_ROOT / "reference"),
    ]

    def seg(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()
    token = f"{seg(json.dumps({'alg': 'none'}).encode())}.{seg(json.dumps({'exp': int(time.time() + 3600)}).encode())}.sig"
    cred_path = tmp_path / "cred.json"
    cred_path.write_text(json.dumps({"tokens": {"access_token": token}}))

    result = cc.run_collection_agent_attempt(
        subject_name="whatever", acquired=acquired, experiment=experiment, attempt_id=attempt_id,
        backend=backend, grading_backend=grading_backend, base=base,
        base_argv=argv, prompt="Fix the slug helper.", timeout=5, credential_explicit_path=cred_path,
    )

    assert result.record["disposition"] == "captured"
    # Equality against the ACTUAL expected value first (orchestrator review:
    # a bare `!= "v1"` fails identically, printing 'v1' != 'v1', whether the
    # wrong field was read or some other field happened to differ - both
    # sides of a failed `!=` between equal strings print the same value, so
    # that alone cannot show WHICH wrong value leaked in. This equality
    # check makes the pre-fix failure read `'v1' == 'degraded:...'` -
    # visibly the pin standing in for the degraded label, not an ambiguous
    # non-match).
    assert result.revision == acquired.source.revision
    assert result.revision != "v1"  # never the pin, named explicitly
    assert result.revision.startswith("degraded:")
    envelope = cc.evidence_envelope(result)
    assert envelope["revision"] == result.revision


def test_cli_collection_run_refuses_a_tampered_degraded_tree_before_any_docker_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The red case named directly for 150-B2: a digest mismatch between
    `--degraded DIR/skills` and its own receipt is refused - reached here at
    the CLI's own acquisition step, before `--docker-bin` is even consulted,
    so a tampered tree never reaches a real daemon."""
    from skillc import cli

    out = _build_degraded_out(tmp_path, monkeypatch, skills={"tdd": "tdd", "other": "other"}, removed="tdd")
    (out / "skills" / "other" / "SKILL.md").write_text(
        (out / "skills" / "other" / "SKILL.md").read_text(encoding="utf-8") + "tampered\n", encoding="utf-8",
    )
    base = tmp_path / "work"
    base.mkdir()

    code = cli.main([
        "collection-run", "whatever", "--degraded", str(out), "--base", str(base),
        "--docker-bin", "/no/such/docker",
    ])

    assert code == 2


# ------------------------------------------------------- --evidence-role, live


def _fresh_codex_credential(path: Path) -> Path:
    def seg(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()
    token = f"{seg(json.dumps({'alg': 'none'}).encode())}.{seg(json.dumps({'exp': int(time.time() + 3600)}).encode())}.sig"
    path.write_text(json.dumps({"tokens": {"access_token": token}}))
    return path


def _real_degraded_attempt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[trial.Experiment, cc.CollectionAgentResult]:
    """A REAL, captured, graded `--degraded` attempt - fake docker, fake
    codex client, `acquire_degraded_collection`/`run_collection_agent_attempt`
    both exercised for real, exactly `test_cli_collection_run_degraded_
    records_the_degraded_identity_never_the_pin`'s own proven setup. This is
    where the revision fix actually runs; the CLI-level test below wires its
    real output into a real `cli.main()` call rather than re-deriving it
    through the CLI's own argv/attempt-id plumbing, which needs no
    docker-state prediction to be reliable."""
    collection = _fixture_collection(tmp_path, {"tdd": "tdd"})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject(select=["tdd"]))
    degraded = degrade.acquire_degraded("whatever", tmp_path / "degrade-base", None, checkout=collection)
    out = tmp_path / "degraded-out"
    out.mkdir()
    (out / "receipt.json").write_text(
        json.dumps(degrade.receipt(degraded, pinned_revision="v1"), indent=1) + "\n", encoding="utf-8",
    )
    degrade.persist_skills(degraded, out)

    base = tmp_path / "work"
    base.mkdir()
    docker_state = tmp_path / "docker-state"
    acquired = cc.acquire_degraded_collection("whatever", out)
    store = trial.open_store(tmp_path / "store", forbidden=[])
    experiment, attempt_id = cc.plan_collection_attempt("whatever", acquired, store)
    backend = _backend(base, docker_state)
    grading_backend = _backend(base, docker_state)
    name = d._container_name(attempt_id)
    home = docker_state / f"{name}.fsroot" / "home" / "candidate"
    argv = [
        sys.executable, str(FAKE_CLIENT), "--format", "codex-fake", "--home", str(home),
        "--transcript-relpath", ".codex/sessions/2026/01/01/rollout-cc.jsonl",
        "--copy-solution", str(GRADER_ROOT / "reference"),
    ]
    cred_path = _fresh_codex_credential(tmp_path / "cred.json")

    result = cc.run_collection_agent_attempt(
        subject_name="whatever", acquired=acquired, experiment=experiment, attempt_id=attempt_id,
        backend=backend, grading_backend=grading_backend, base=base,
        base_argv=argv, prompt="Fix the slug helper.", timeout=5, credential_explicit_path=cred_path,
    )
    assert result.record["disposition"] == "captured"
    graded = result.record.get("graded")
    assert isinstance(graded, dict) and graded.get("status") == "PASS"
    return experiment, result


def _wire_real_result_into_cli(
    monkeypatch: pytest.MonkeyPatch, experiment: trial.Experiment, result: cc.CollectionAgentResult,
) -> None:
    """Wire a REAL, already-run `(experiment, result)` pair into
    `cmd_collection_run`'s own acquisition/planning/attempt calls, so
    `cli.main` exercises its OWN gating and export code for real while
    skipping a second real docker attempt (attempt ids are random -
    `trial._new_attempt_id` - so predicting `--client-argv`'s `--home`
    through a full `cli.main` dispatch is not reliably reproducible; the
    attempt itself is already proven real and correct by
    `_real_degraded_attempt`, which this reuses rather than re-deriving)."""
    from types import SimpleNamespace

    from skillc import reap

    monkeypatch.setattr(cc, "acquire_degraded_collection", lambda *a, **k: SimpleNamespace(subject=SimpleNamespace(client="codex")))
    monkeypatch.setattr(demo, "resolve_image_digest", lambda *a, **k: None)
    monkeypatch.setattr(trial, "open_store", lambda path, forbidden: path)
    monkeypatch.setattr(cc, "plan_collection_attempt", lambda *a, **k: (experiment, "a-1"))
    monkeypatch.setattr(cc, "run_collection_agent_attempt", lambda **k: result)
    monkeypatch.setattr(reap, "snapshot", lambda *a, **k: reap.Snapshot(False, frozenset(), frozenset()))
    monkeypatch.setattr(cc, "attributable_leftovers", lambda *a, **k: [])


def test_cli_degraded_export_is_refused_by_default_role_and_published_with_control(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The interdependency the orchestrator named: #157's `--evidence-role`
    guard recognises a degraded arm by `result.revision` starting with
    `degraded:` - real only once B2's revision fix (which makes that field
    report what was actually acquired, not the pin) and B2's `--degraded`
    (which makes an acquisition degraded at all) both exist. The attempt
    that PRODUCES `result.revision` is real (`_real_degraded_attempt` - fake
    docker, fake codex client, `run_collection_agent_attempt` unmocked, the
    exact function the revision fix touches); `cli.main`'s OWN gating and
    export code then runs unmocked against that real result, through the
    actual `collection-run --degraded --evidence` entry point, twice - once
    per role.

    Confirmed as a red case by temporarily reverting the revision fix
    (`acquired.source.revision` -> `acquired.subject.revision` in
    `run_collection_agent_attempt`) and re-running: the default-role call
    then (wrongly) published instead of being refused - restored afterward.
    See the commit message for the exact before/after."""
    experiment, result = _real_degraded_attempt(tmp_path, monkeypatch)
    assert result.revision.startswith("degraded:")

    from skillc import cli

    # `--degraded` need only be truthy here: `acquire_degraded_collection` is
    # mocked and never reads it, but an empty/absent flag would send
    # `cmd_collection_run` down the OTHER (pinned) acquisition branch instead.
    _wire_real_result_into_cli(monkeypatch, experiment, result)
    default_evidence = tmp_path / "default-evidence"
    default_code = cli.main([
        "collection-run", "whatever", "--degraded", str(tmp_path / "unread-degraded-marker"),
        "--base", str(tmp_path / "default-base"), "--evidence", str(default_evidence),
    ])
    assert default_code == 2
    assert not default_evidence.exists()

    _wire_real_result_into_cli(monkeypatch, experiment, result)
    control_evidence = tmp_path / "control-evidence"
    control_code = cli.main([
        "collection-run", "whatever", "--degraded", str(tmp_path / "unread-degraded-marker"),
        "--base", str(tmp_path / "control-base"), "--evidence", str(control_evidence),
        "--evidence-role", "control",
    ])
    assert control_code == 0
    assert list(control_evidence.glob("result-*.json"))
