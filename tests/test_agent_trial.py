"""Tests for skillc/agent_trial.py (#106): the agent trial driver.

Every test here runs against the fake `docker` CLI
(`tests/fixtures/docker-backend/fake_docker.py`) and a scripted fake client
(`tests/fixtures/agent-trial/fake_agent_client.py`) that writes a realistic
transcript for each client format - #106's own acceptance: "Runs end to end
against the fake docker, using a scripted fake client... This is the green
it rests on." No real daemon and no real `claude`/`codex` binary is
available in this session, or reachable from this file at all - see
`test_no_real_agent_binary_named_in_this_file` below.
"""

from __future__ import annotations

import ast
import base64
import json
import sys
import time
from pathlib import Path

import pytest

from skillc import agent_trial as at
from skillc import docker_backend as d
from skillc import trial as t
from skillc import verify
from skillc.backend import Limits
from skillc.credential import CredentialRefused

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


@pytest.fixture
def store(tmp_path: Path) -> Path:
    return t.open_store(tmp_path / "store", forbidden=[])


def _backend(base: Path, docker_state: Path) -> d.DockerBackend:
    return d.DockerBackend(image="fake-image:1", base_dir=base, docker_bin=_docker_bin(docker_state))


def _planned(store: Path) -> tuple[t.Experiment, str]:
    spec: dict[str, object] = {
        "experiment": "agent-trial",
        "trials": [{
            # The grader these attempts are graded by, digest pinned (#139): the
            # verifier stores a result against nothing else.
            "label": "t", "case": {"id": "c", "revision": "r1"}, "grader": verify.GraderDef.load(GRADER_ROOT).identity(),
            "subject": {"digest": "sha256:00"}, "client": {"name": "fake", "version": "1"},
            "image": {"digest": "sha256:01"}, "config": {}, "attempts": 1,
        }],
    }
    experiment = t.plan(spec, store)
    [(_trial, attempt)] = list(experiment.attempts())
    return experiment, str(attempt["attempt_id"])


def _fake_jwt(payload: dict[str, object]) -> str:
    """A syntactically real JWT (three base64url segments) - never signed,
    matching `skillc/credential.py`'s own `_jwt_exp_seconds`, which never
    verifies a signature either (it reads a credential already trusted by
    its presence on disk, never authenticates one)."""
    def seg(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()
    return f"{seg(json.dumps({'alg': 'none'}).encode())}.{seg(json.dumps(payload).encode())}.fake-signature"


def _fresh_credential(tmp_path: Path, client: str) -> Path:
    path = tmp_path / f"{client}-credential.json"
    if client == "claude":
        path.write_text(json.dumps({"claudeAiOauth": {"expiresAt": int((time.time() + 3600) * 1000)}}))
    else:
        token = _fake_jwt({"exp": int(time.time() + 3600)})
        path.write_text(json.dumps({"tokens": {"access_token": token}}))
    return path


def _expired_credential(tmp_path: Path) -> Path:
    path = tmp_path / "claude-credential-expired.json"
    path.write_text(json.dumps({"claudeAiOauth": {"expiresAt": int((time.time() + 10) * 1000)}}))
    return path


def _observation(record: dict[str, object]) -> dict[str, object]:
    obs = record["observation"]
    assert isinstance(obs, dict)
    return obs


def _graded(record: dict[str, object]) -> dict[str, object]:
    graded = record["graded"]
    assert isinstance(graded, dict)
    return graded


def _fake_argv(*, fmt: str, home: Path, transcript_relpath: str, fail_canary: bool = False,
               mismatched_prompt: bool = False, copy_solution: Path | None = None,
               plant_leak: bool = False, plant_skill: list[str] | None = None) -> list[str]:
    """The skill name and nonce are never passed here - the fake client
    reads both out of the prompt text itself (see its own module docstring
    and `main()`), exactly as a real agent would read its own instructions.
    `agent_trial.run_one_attempt` appends the prompt as the LAST argv
    element, so this list is everything BEFORE it.

    `plant_skill` (issue #26): which skill_invocation event(s), if any, the
    fake client writes into the transcript - independent of whatever skill
    (if any) the prompt itself names. Omitted, the fake client's own default
    applies (the prompt's named skill in named-canary mode, none at all in
    skill-free mode)."""
    argv = [
        sys.executable, str(FAKE_CLIENT), "--format", fmt, "--home", str(home),
        "--transcript-relpath", transcript_relpath,
    ]
    if fail_canary:
        argv.append("--fail-canary")
    if mismatched_prompt:
        argv.append("--mismatched-prompt")
    if copy_solution is not None:
        argv.extend(["--copy-solution", str(copy_solution)])
    if plant_leak:
        argv.append("--plant-leak")
    for skill in plant_skill or ():
        argv.extend(["--plant-skill", skill])
    return argv


class _TranscriptCapturingBackend(d.DockerBackend):
    """Wraps `read_home_tree` to CAPTURE what it returned, keyed by
    `container_reldir`, into `captured` - test-only, so the leak-check
    tests below can scan the actual transcript BYTES `agent_trial.py` read,
    rather than trying to re-read them from the container's home directory
    after `destroy()` has already removed it (cross-model review: the
    original version of this test substituted an empty string once the
    directory was gone, which passed the leak scan whether or not anything
    was ever actually scanned)."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.captured: dict[str, dict[str, bytes]] = {}

    def read_home_tree(self, handle: object, container_reldir: str, **kwargs: object) -> dict[str, bytes]:
        tree = super().read_home_tree(handle, container_reldir, **kwargs)  # type: ignore[arg-type]
        self.captured[container_reldir] = tree
        return tree


def _mapped_home(docker_state: Path, attempt_id: str) -> Path:
    """The fake docker CLI's own documented state-mapping convention (the
    same white-box convention `tests/test_docker_backend.py`'s
    `deliver_home_file` tests use) - needed here because the fake CLI runs
    `execute()`'s subject as a REAL host subprocess with no chroot, so the
    scripted fake client must be TOLD exactly where `CONTAINER_HOME` maps to
    on this host; a real client obviously needs no such thing."""
    name = d._container_name(attempt_id)
    return docker_state / f"{name}.fsroot" / "home" / "candidate"


# --------------------------------------------------------------- happy path

def test_end_to_end_happy_path_delivers_credential_confirms_and_grades(
    store: Path, base: Path, docker_state: Path, tmp_path: Path,
) -> None:
    """#106's own acceptance: "Runs end to end against the fake docker,
    using a scripted fake client that writes a realistic transcript... This
    is the green it rests on." Credential delivered, transcript discovered
    and parsed, prompt delivery and canary both confirmed, and the exported
    candidate graded PASS against the real, certified slug-small-fix task."""
    backend = _backend(base, docker_state)
    grading_backend = _backend(base, docker_state)
    experiment, attempt_id = _planned(store)
    cred_path = _fresh_credential(tmp_path, "claude")

    # The fake CLI has no chroot (see _mapped_home's own docstring), so the
    # scripted client is told exactly where CONTAINER_HOME maps to; a real
    # client needs no such thing. `--copy-solution` makes the fake client
    # copy the certified reference solution into its own CWD (/work) DURING
    # execute() - a stand-in for "the agent solved the task", and also what
    # gives lifecycle.py's own workspace-snapshot liveness check a genuine
    # before/after difference to see (a `surface`-installed file would
    # already be present in the "before" snapshot, since install() runs
    # before it is taken, and would show no change at all).
    home = _mapped_home(docker_state, attempt_id)
    reference = GRADER_ROOT / "reference"
    argv = _fake_argv(
        fmt="claude-fake", home=home,
        transcript_relpath=".claude/projects/test/22222222-2222-2222-2222-222222222222.jsonl",
        copy_solution=reference,
    )

    record = at.run_one_attempt(
        backend=backend, experiment=experiment, attempt_id=attempt_id, client="claude",
        base_argv=argv, prompt="Fix the slug helper.", skill_name="demo-skill",
        surface={}, limits=Limits(timeout=5), base=base,
        credential_explicit_path=cred_path,
        grader=verify.GraderDef.load(GRADER_ROOT), grading_backend=grading_backend,
    )

    assert record["disposition"] == "captured"
    observation = _observation(record)
    assert observation["prompt_delivered"] is True
    assert observation["canary_satisfied"] is True
    assert observation["transcript_files_found"] == 1
    assert observation["credential_client"] == "claude"
    assert observation["credential_source"] == "subscription"
    assert record["grading_blocked_reason"] is None
    assert _graded(record)["status"] == "PASS"


# --------------------------------------------------------- prompt mismatch

def test_prompt_delivery_mismatch_is_blocked_not_graded(store: Path, base: Path, docker_state: Path, tmp_path: Path) -> None:
    """#106's own acceptance: "Prompt-delivery mismatch: the attempt is
    BLOCKED, not graded." The attempt still CAPTURES at the lifecycle level
    (something ran and stopped cleanly) - the block is agent_trial.py's own
    grading gate, layered on top."""
    backend = _backend(base, docker_state)
    grading_backend = _backend(base, docker_state)
    experiment, attempt_id = _planned(store)
    cred_path = _fresh_credential(tmp_path, "claude")
    home = _mapped_home(docker_state, attempt_id)
    argv = _fake_argv(
        fmt="claude-fake", home=home,
        transcript_relpath=".claude/projects/test/22222222-2222-2222-2222-222222222222.jsonl",
        mismatched_prompt=True,
    )

    record = at.run_one_attempt(
        backend=backend, experiment=experiment, attempt_id=attempt_id, client="claude",
        base_argv=argv, prompt="Fix the slug helper.", skill_name="demo-skill",
        surface={}, limits=Limits(timeout=5), base=base,
        credential_explicit_path=cred_path,
        grader=verify.GraderDef.load(GRADER_ROOT), grading_backend=grading_backend,
    )

    assert _observation(record)["prompt_delivered"] is False
    assert record["graded"] is None
    assert record["grading_blocked_reason"] is not None
    assert "prompt_delivered=False" in str(record["grading_blocked_reason"])


# ------------------------------------------------------------- canary fail

def test_canary_not_satisfied_is_blocked_not_graded(store: Path, base: Path, docker_state: Path, tmp_path: Path) -> None:
    backend = _backend(base, docker_state)
    grading_backend = _backend(base, docker_state)
    experiment, attempt_id = _planned(store)
    cred_path = _fresh_credential(tmp_path, "claude")
    home = _mapped_home(docker_state, attempt_id)
    argv = _fake_argv(
        fmt="claude-fake", home=home,
        transcript_relpath=".claude/projects/test/22222222-2222-2222-2222-222222222222.jsonl",
        fail_canary=True,
    )

    record = at.run_one_attempt(
        backend=backend, experiment=experiment, attempt_id=attempt_id, client="claude",
        base_argv=argv, prompt="Fix the slug helper.", skill_name="demo-skill",
        surface={}, limits=Limits(timeout=5), base=base,
        credential_explicit_path=cred_path,
        grader=verify.GraderDef.load(GRADER_ROOT), grading_backend=grading_backend,
    )

    assert _observation(record)["prompt_delivered"] is True
    assert _observation(record)["canary_satisfied"] is False
    assert record["graded"] is None
    assert record["grading_blocked_reason"] is not None


# ------------------------------------------------------- zero/multiple files

def test_zero_transcript_files_gives_unknown_never_a_guess(store: Path, base: Path, docker_state: Path, tmp_path: Path) -> None:
    """#106's own acceptance (relayed via the transcript-discovery design):
    zero files gives UNKNOWN, never "assume it worked" or "assume it
    failed"."""
    backend = _backend(base, docker_state)
    experiment, attempt_id = _planned(store)
    cred_path = _fresh_credential(tmp_path, "claude")
    # A script that never writes any transcript at all - argv is just a
    # no-op python invocation.
    argv = [sys.executable, "-c", "pass"]

    record = at.run_one_attempt(
        backend=backend, experiment=experiment, attempt_id=attempt_id, client="claude",
        base_argv=argv, prompt="Fix the slug helper.", skill_name="demo-skill",
        surface={}, limits=Limits(timeout=5), base=base,
        credential_explicit_path=cred_path,
    )

    assert _observation(record)["transcript_files_found"] == 0
    assert _observation(record)["prompt_delivered"] is False
    assert _observation(record)["canary_satisfied"] is False
    assert "expected exactly one" in str(_observation(record)["prompt_delivery_reason"])


def test_two_transcript_files_gives_unknown_never_pick_the_newest(
    store: Path, base: Path, docker_state: Path, tmp_path: Path,
) -> None:
    experiment, attempt_id = _planned(store)
    cred_path = _fresh_credential(tmp_path, "claude")
    home = _mapped_home(docker_state, attempt_id)
    argv = _fake_argv(fmt="claude-fake", home=home, transcript_relpath=".claude/projects/test/one.jsonl")

    # Deliver a SECOND transcript file alongside the fake client's own -
    # simulating two session files existing under the same directory -
    # #106's own named red case: "two files gives UNKNOWN".
    class _TwoFileBackend(d.DockerBackend):
        def deliver_home_file(self, handle: object, container_relpath: str, data: bytes, *, mode: int = 0o600) -> None:
            super().deliver_home_file(handle, container_relpath, data, mode=mode)
            if container_relpath == ".claude/.credentials.json":
                super().deliver_home_file(handle, ".claude/projects/test/two.jsonl", b'{"type":"user","message":{"role":"user","content":"hi"}}\n')

    two_file_backend = _TwoFileBackend(image="fake-image:1", base_dir=base, docker_bin=_docker_bin(docker_state))

    record = at.run_one_attempt(
        backend=two_file_backend, experiment=experiment, attempt_id=attempt_id, client="claude",
        base_argv=argv, prompt="Fix the slug helper.", skill_name="demo-skill",
        surface={}, limits=Limits(timeout=5), base=base,
        credential_explicit_path=cred_path,
    )

    assert _observation(record)["transcript_files_found"] == 2
    assert _observation(record)["prompt_delivered"] is False
    assert "expected exactly one" in str(_observation(record)["prompt_delivery_reason"])


# -------------------------------------------------- credential below threshold

def test_credential_below_threshold_blocks_before_launch_no_container_remains(
    store: Path, base: Path, docker_state: Path, tmp_path: Path,
) -> None:
    """#106's own acceptance: "Credential below the threshold: the attempt
    is BLOCKED before launch, and no container remains." """
    backend = _backend(base, docker_state)
    experiment, attempt_id = _planned(store)
    cred_path = _expired_credential(tmp_path)
    argv = [sys.executable, "-c", "import sys; sys.exit(1)"]  # must never run

    record = at.run_one_attempt(
        backend=backend, experiment=experiment, attempt_id=attempt_id, client="claude",
        base_argv=argv, prompt="Fix the slug helper.", skill_name="demo-skill",
        surface={}, limits=Limits(timeout=5), base=base,
        credential_explicit_path=cred_path, minimum_credential_seconds=300,
    )

    assert record["disposition"] == "unavailable"
    assert "below the required" in str(record["reason"])
    # backend_teardown == "confirmed" IS "no container remains" - confirm_absent()
    # asks the daemon directly, never trusts destroy()'s own return value alone.
    assert record["backend_teardown"] == "confirmed"
    # "observation" is PRESENT (agent_trial.py always supplies the hook,
    # never omits the argument) but None - observe_before_teardown itself
    # never ran, since before_execute blocked the attempt first.
    assert record.get("observation") is None


def test_no_credential_at_all_blocks_before_launch(store: Path, base: Path, docker_state: Path, tmp_path: Path) -> None:
    """#106's own acceptance: "BLOCKED with no credential." """
    backend = _backend(base, docker_state)
    experiment, attempt_id = _planned(store)
    missing = tmp_path / "does-not-exist.json"
    argv = [sys.executable, "-c", "import sys; sys.exit(1)"]

    record = at.run_one_attempt(
        backend=backend, experiment=experiment, attempt_id=attempt_id, client="claude",
        base_argv=argv, prompt="Fix the slug helper.", skill_name="demo-skill",
        surface={}, limits=Limits(timeout=5), base=base,
        credential_explicit_path=missing,
    )
    assert record["disposition"] == "unavailable"


def test_unknown_client_is_refused(store: Path, base: Path, docker_state: Path) -> None:
    backend = _backend(base, docker_state)
    experiment, attempt_id = _planned(store)
    with pytest.raises(CredentialRefused):
        at.run_one_attempt(
            backend=backend, experiment=experiment, attempt_id=attempt_id, client="not-a-real-client",
            base_argv=[sys.executable, "-c", "pass"], prompt="x", skill_name="x",
            surface={}, limits=Limits(timeout=5), base=base,
        )


def test_grading_backend_must_be_a_separate_instance(
    store: Path, base: Path, docker_state: Path, tmp_path: Path,
) -> None:
    """Cross-model review: the grading gate must refuse the agent's OWN
    backend passed a second time, not merely accept anything non-`None` -
    interfaces.md's step 8 rule ("a separate backend instance") is
    structural, never merely a naming convention."""
    backend = _backend(base, docker_state)
    experiment, attempt_id = _planned(store)
    cred_path = _fresh_credential(tmp_path, "claude")
    home = _mapped_home(docker_state, attempt_id)
    argv = _fake_argv(fmt="claude-fake", home=home, transcript_relpath=".claude/projects/test/x.jsonl")
    with pytest.raises(ValueError, match="SEPARATE instance"):
        at.run_one_attempt(
            backend=backend, experiment=experiment, attempt_id=attempt_id, client="claude",
            base_argv=argv, prompt="Fix the slug helper.", skill_name="demo-skill",
            surface={}, limits=Limits(timeout=5), base=base,
            credential_explicit_path=cred_path,
            grader=verify.GraderDef.load(GRADER_ROOT), grading_backend=backend,
        )


# ----------------------------------------------------------------- codex

def test_end_to_end_happy_path_for_codex(store: Path, base: Path, docker_state: Path, tmp_path: Path) -> None:
    """PR #113 review: the earlier version of this test never asserted
    `disposition` (or graded) at all - a mutation giving the agent canary
    its OWN nonce, diverging from the one `run_through_backend` actually
    plants, turns the Claude happy-path test red (disposition falls to
    "inconclusive") but left this one green, since nothing here checked
    disposition either way. Mirrors the Claude happy-path test's own
    grading setup so "captured" and "PASS" are both real assertions, not
    merely implied by the absence of an exception."""
    backend = _backend(base, docker_state)
    grading_backend = _backend(base, docker_state)
    experiment, attempt_id = _planned(store)
    cred_path = _fresh_credential(tmp_path, "codex")
    home = _mapped_home(docker_state, attempt_id)
    reference = GRADER_ROOT / "reference"
    argv = _fake_argv(
        fmt="codex-fake", home=home, transcript_relpath=".codex/sessions/2026/01/01/rollout-x.jsonl",
        copy_solution=reference,
    )

    record = at.run_one_attempt(
        backend=backend, experiment=experiment, attempt_id=attempt_id, client="codex",
        base_argv=argv, prompt="Fix the slug helper.", skill_name="demo-skill",
        surface={}, limits=Limits(timeout=5), base=base,
        credential_explicit_path=cred_path,
        grader=verify.GraderDef.load(GRADER_ROOT), grading_backend=grading_backend,
    )

    assert record["disposition"] == "captured"
    assert _observation(record)["prompt_delivered"] is True
    assert _observation(record)["canary_satisfied"] is True
    assert _observation(record)["credential_client"] == "codex"
    assert record["grading_blocked_reason"] is None
    assert _graded(record)["status"] == "PASS"


def test_a_pilot_shaped_baseline_arm_with_an_installation_receipt_context_still_keeps_b1(
    store: Path, base: Path, docker_state: Path, tmp_path: Path,
) -> None:
    """ADR 0005's "yes, narrow B1" ruling names this case explicitly: an
    agent-trial arm that installs NOTHING stays on the B1 stand-in, even on
    a codex client. `test_an_empty_declared_set_never_builds_a_receipt`
    (test_agent_trial_readiness.py) already proves `_build_discovery_receipt`
    returns `None` before touching its `backend` argument at all - but that
    is a pure-function claim against a placeholder backend. This drives the
    SAME empty-declared case through the real, integration-level
    `run_one_attempt`, against a REAL fake-docker backend: a codex arm shaped
    like the matched pilot's own baseline (no `extra_home_files`), but with
    an actual `InstallationReceiptContext` in hand (`declared=frozenset()`) -
    not simply omitting the parameter, which
    `test_a_graded_attempt_stores_a_verified_result_bound_to_its_manifest_and_pin`
    above already covers for a caller that never builds one at all.

    The container count is the integration-level half of the pure-function
    claim: `_build_discovery_receipt`'s early return happens before
    `_measure_discovery` (and so before `backend.prepare`) is ever called,
    so no `-baseline-`/`-discovery-` suffixed container should exist in the
    real fake-docker state directory - not merely "the function returned
    None" but "nothing was ever launched to find that out"."""
    experiment, attempt_id = _planned(store)
    argv = _fake_argv(
        fmt="codex-fake", home=_mapped_home(docker_state, attempt_id),
        transcript_relpath=".codex/sessions/2026/01/01/rollout-baseline.jsonl",
        copy_solution=GRADER_ROOT / "reference",
    )
    receipt_context = at.InstallationReceiptContext(
        declared=frozenset(), tree_digest="sha256:empty-surface", subject_locator="pilot/baseline",
        subject_revision="v1", surface_name="codex-skills", cache={},
    )

    record = at.run_one_attempt(
        backend=_backend(base, docker_state), experiment=experiment, attempt_id=attempt_id, client="codex",
        base_argv=argv, prompt="Fix the slug helper.", skill_name="demo-skill",
        surface={}, limits=Limits(timeout=5), base=base,
        credential_explicit_path=_fresh_credential(tmp_path, "codex"),
        grader=verify.GraderDef.load(GRADER_ROOT), grading_backend=_backend(base, docker_state),
        receipt_context=receipt_context,
    )

    assert record["disposition"] == "captured"
    assert not list(experiment.root.glob("receipt-*.json"))
    [path] = experiment.root.glob("result-*.json")
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["verification"]["readiness_source"] == "agent-observation"
    [readiness] = [c for c in stored["criteria"] if c["id"] == verify.READINESS_CRITERION]
    assert readiness["outcome"] == "UNKNOWN"

    launched = sorted(p.name for p in docker_state.glob("*.json"))
    assert not any("-baseline-" in name or "-discovery-" in name for name in launched), launched


# ------------------------------------------------- skill_invocations (issue #26)


def test_skill_invocations_reports_every_invoked_skill_not_only_the_named_one(
    store: Path, base: Path, docker_state: Path, tmp_path: Path,
) -> None:
    """The transcript can show MORE than the one skill a canary was checked
    against - `observation["skill_invocations"]` must report all of it, in
    order, never collapse to just `skill_name`'s own confirmation."""
    backend = _backend(base, docker_state)
    experiment, attempt_id = _planned(store)
    cred_path = _fresh_credential(tmp_path, "claude")
    home = _mapped_home(docker_state, attempt_id)
    argv = _fake_argv(
        fmt="claude-fake", home=home,
        transcript_relpath=".claude/projects/test/33333333-3333-3333-3333-333333333333.jsonl",
        plant_skill=["security-scan", "security-deep"],
    )

    record = at.run_one_attempt(
        backend=backend, experiment=experiment, attempt_id=attempt_id, client="claude",
        base_argv=argv, prompt="Check for security issues.", skill_name="security-scan",
        surface={}, limits=Limits(timeout=5), base=base, credential_explicit_path=cred_path,
    )

    observation = _observation(record)
    assert observation["skill_invocations"] == ["security-scan", "security-deep"]
    assert observation["skill_invocation_detection"] == "structural"


def test_skill_invocation_detection_is_heuristic_for_codex(
    store: Path, base: Path, docker_state: Path, tmp_path: Path,
) -> None:
    """Issue #26's report must be able to say Codex's own detection is
    best-effort, never present it as the same structural guarantee Claude
    Code's dedicated `Skill` tool call gives (`transcript_adapter.py`'s own
    module docstring: Codex has no `skill_invocation` marker of its own)."""
    backend = _backend(base, docker_state)
    experiment, attempt_id = _planned(store)
    cred_path = _fresh_credential(tmp_path, "codex")
    home = _mapped_home(docker_state, attempt_id)
    argv = _fake_argv(
        fmt="codex-fake", home=home, transcript_relpath=".codex/sessions/2026/01/01/rollout-y.jsonl",
        plant_skill=["qa-test"],
    )

    record = at.run_one_attempt(
        backend=backend, experiment=experiment, attempt_id=attempt_id, client="codex",
        base_argv=argv, prompt="Run the tests.", skill_name="qa-test",
        surface={}, limits=Limits(timeout=5), base=base, credential_explicit_path=cred_path,
    )

    observation = _observation(record)
    assert observation["skill_invocations"] == ["qa-test"]
    assert observation["skill_invocation_detection"] == "heuristic"


def test_skill_invocations_is_empty_when_no_transcript_was_found(
    store: Path, base: Path, docker_state: Path, tmp_path: Path,
) -> None:
    """The same "could not observe" condition every other observation field
    defaults on (zero or multiple transcript files) - never a guessed list.

    `credential_explicit_path` is an explicit FAKE credential, never `None`
    (PR #117 review): `None` means "no override", which falls through to
    `credential.resolve_path`'s own standard-location default - on a host
    with a real login there, this test would resolve and READ the
    operator's actual subscription credential, exactly what happened when
    an earlier version of this test ran outside CI. The point here is "no
    transcript", not "no credential", so the credential stays valid and
    only the transcript is absent."""
    backend = _backend(base, docker_state)
    experiment, attempt_id = _planned(store)
    cred_path = _fresh_credential(tmp_path, "claude")
    argv = [sys.executable, "-c", "import pathlib; pathlib.Path('agent-touched.txt').write_text('ran')"]

    record = at.run_one_attempt(
        backend=backend, experiment=experiment, attempt_id=attempt_id, client="claude",
        base_argv=argv, prompt="x", skill_name="x", surface={}, limits=Limits(timeout=5), base=base,
        credential_explicit_path=cred_path,
    )

    observation = _observation(record)
    assert observation["skill_invocations"] == []
    assert observation["transcript_files_found"] == 0


# --------------------------------------------------- skill-free canary (issue #26)


def test_skill_free_canary_accepts_an_attempt_that_invokes_no_skill_at_all(
    store: Path, base: Path, docker_state: Path, tmp_path: Path,
) -> None:
    """`skill_name=None` composes a skill-free instruction; the fake client
    (given no `--plant-skill`) writes no skill_invocation event at all - the
    near-miss case's own shape. The canary must still be satisfied on the
    tool-write alone, and `skill_invocations` must observe the true, empty
    result rather than anything derived from `skill_name`."""
    backend = _backend(base, docker_state)
    experiment, attempt_id = _planned(store)
    cred_path = _fresh_credential(tmp_path, "claude")
    home = _mapped_home(docker_state, attempt_id)
    argv = _fake_argv(
        fmt="claude-fake", home=home,
        transcript_relpath=".claude/projects/test/44444444-4444-4444-4444-444444444444.jsonl",
    )

    record = at.run_one_attempt(
        backend=backend, experiment=experiment, attempt_id=attempt_id, client="claude",
        base_argv=argv, prompt="Fix the slug helper.", skill_name=None,
        surface={}, limits=Limits(timeout=5), base=base, credential_explicit_path=cred_path,
    )

    assert record["disposition"] == "captured"
    observation = _observation(record)
    assert observation["canary_satisfied"] is True
    assert observation["skill_invocations"] == []


def test_skill_free_canary_still_observes_a_false_positive_invocation(
    store: Path, base: Path, docker_state: Path, tmp_path: Path,
) -> None:
    """Red case (issue #26's own acceptance): in skill-free mode, an
    invocation the agent made ANYWAY (never asked for, since the prompt
    names no skill) must still be OBSERVED via `skill_invocations`, not
    hidden by the canary's own indifference to it - the canary and the
    measurement are deliberately different concerns now."""
    backend = _backend(base, docker_state)
    experiment, attempt_id = _planned(store)
    cred_path = _fresh_credential(tmp_path, "claude")
    home = _mapped_home(docker_state, attempt_id)
    argv = _fake_argv(
        fmt="claude-fake", home=home,
        transcript_relpath=".claude/projects/test/55555555-5555-5555-5555-555555555555.jsonl",
        plant_skill=["qa-test"],
    )

    record = at.run_one_attempt(
        backend=backend, experiment=experiment, attempt_id=attempt_id, client="claude",
        base_argv=argv, prompt="Fix the slug helper.", skill_name=None,
        surface={}, limits=Limits(timeout=5), base=base, credential_explicit_path=cred_path,
    )

    assert record["disposition"] == "captured"
    observation = _observation(record)
    assert observation["canary_satisfied"] is True  # the canary itself is indifferent to this
    assert observation["skill_invocations"] == ["qa-test"]  # but the observation is not


def test_skill_free_canary_still_refuses_a_failed_tool_call(
    store: Path, base: Path, docker_state: Path, tmp_path: Path,
) -> None:
    """Red case (issue #26's own acceptance: "a failed tool call is still
    not live"), through the real `run_one_attempt` path this time, not just
    the unit-level `check_agent_canary` test in `test_trial_bootstrap.py`."""
    backend = _backend(base, docker_state)
    grading_backend = _backend(base, docker_state)
    experiment, attempt_id = _planned(store)
    cred_path = _fresh_credential(tmp_path, "claude")
    home = _mapped_home(docker_state, attempt_id)
    argv = _fake_argv(
        fmt="claude-fake", home=home,
        transcript_relpath=".claude/projects/test/66666666-6666-6666-6666-666666666666.jsonl",
        fail_canary=True,
    )

    record = at.run_one_attempt(
        backend=backend, experiment=experiment, attempt_id=attempt_id, client="claude",
        base_argv=argv, prompt="Fix the slug helper.", skill_name=None,
        surface={}, limits=Limits(timeout=5), base=base, credential_explicit_path=cred_path,
        grader=verify.GraderDef.load(GRADER_ROOT), grading_backend=grading_backend,
    )

    observation = _observation(record)
    assert observation["canary_satisfied"] is False
    assert record["grading_blocked_reason"] is not None
    assert record["graded"] is None


# ------------------------------------------------ extra_home_files (issue #11)


class _HomeFileCapturingBackend(d.DockerBackend):
    """Records every `deliver_home_file` call - test-only, so a caller-
    supplied `extra_home_files` mapping can be proven to actually reach the
    container (path and bytes both), the same "prove the mechanism wires up"
    discipline `_TranscriptCapturingBackend` above already applies to
    `read_home_tree`. Delivery happens inside `before_execute`, well before
    `destroy()` removes the container `run_one_attempt` itself never lets a
    caller read back from afterward."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.delivered: dict[str, bytes] = {}

    def deliver_home_file(self, handle: object, container_relpath: str, data: bytes, **kwargs: object) -> None:
        super().deliver_home_file(handle, container_relpath, data, **kwargs)  # type: ignore[arg-type]
        self.delivered[container_relpath] = data


def test_extra_home_files_are_delivered_alongside_the_credential_and_seed(
    store: Path, base: Path, docker_state: Path, tmp_path: Path,
) -> None:
    """A declared skill collection's own surface (issue #11) rides through
    the same `before_execute` hook that already delivers the credential and
    the client's own seed - never a second delivery mechanism."""
    backend = _HomeFileCapturingBackend(
        image="fake-image:1", base_dir=base, docker_bin=_docker_bin(docker_state),
    )
    experiment, attempt_id = _planned(store)
    cred_path = _fresh_credential(tmp_path, "codex")
    home = _mapped_home(docker_state, attempt_id)
    argv = _fake_argv(fmt="codex-fake", home=home, transcript_relpath=".codex/sessions/2026/01/01/rollout-x.jsonl")
    extra = {".codex/skills/tdd/SKILL.md": b"---\nname: tdd\n---\nBody.\n"}

    record = at.run_one_attempt(
        backend=backend, experiment=experiment, attempt_id=attempt_id, client="codex",
        base_argv=argv, prompt="Fix the slug helper.", skill_name=None,
        surface={}, limits=Limits(timeout=5), base=base, credential_explicit_path=cred_path,
        extra_home_files=extra,
    )

    assert record["disposition"] == "captured"
    assert backend.delivered[".codex/skills/tdd/SKILL.md"] == extra[".codex/skills/tdd/SKILL.md"]


def test_extra_home_files_default_omits_nothing_delivered_before(
    store: Path, base: Path, docker_state: Path, tmp_path: Path,
) -> None:
    """`extra_home_files=None` (the default) must deliver exactly what a
    caller who never knew this parameter existed already got - no new file,
    no behavior change for #106's own existing callers."""
    backend = _HomeFileCapturingBackend(
        image="fake-image:1", base_dir=base, docker_bin=_docker_bin(docker_state),
    )
    experiment, attempt_id = _planned(store)
    cred_path = _fresh_credential(tmp_path, "codex")
    home = _mapped_home(docker_state, attempt_id)
    argv = _fake_argv(fmt="codex-fake", home=home, transcript_relpath=".codex/sessions/2026/01/01/rollout-y.jsonl")

    record = at.run_one_attempt(
        backend=backend, experiment=experiment, attempt_id=attempt_id, client="codex",
        base_argv=argv, prompt="Fix the slug helper.", skill_name=None,
        surface={}, limits=Limits(timeout=5), base=base, credential_explicit_path=cred_path,
    )

    assert record["disposition"] == "captured"
    assert not any(path.startswith(".codex/skills/") for path in backend.delivered)


# --------------------------------------------------------- no real model call

#: A `frozenset` literal (`{...}`), deliberately NOT a list/tuple literal -
#: `_find_real_binary_names_in_argv_literals` only ever inspects list/tuple
#: elements, so its own comparison values here can never self-match when it
#: scans this file's own source (a real, found self-match with an earlier
#: `in ("claude", "codex")` tuple literal - the same lines the scanner exists
#: to catch, in the scanner's own code).
_REAL_AGENT_NAMES = frozenset({"claude", "codex"})


def _find_real_binary_names_in_argv_literals(tree: ast.AST) -> list[ast.expr]:
    """#106's own acceptance, mirroring #69's judge test: no real model call
    anywhere in this suite. Scoped to argv-SHAPED list/tuple literals
    specifically (never a bare keyword like `client="claude"`, which names
    which `ClientSpec` to use, not a process to launch) - a real argv is
    always constructed as exactly this shape, `[sys.executable, ...]` or a
    bare list of tokens, so this is the actual population a real launch
    would come from.

    Matches by BASENAME (the last `/`-separated segment), not exact
    equality (cross-model review: an earlier version matched only the bare
    literal `"claude"`/`"codex"`, so `["/usr/bin/claude", ...]` - a real,
    absolute-path launch - silently passed). This is a DOCUMENTATION-level
    check on this one test file's own literals, not the actual safety
    boundary: `lifecycle.py`'s own `_refuse_real_agent` is what actually
    enforces this at runtime for every real call, basename-matched the same
    way, and is exercised directly by its own extensive test suite. An
    unrelated list literal that happens to contain the bare word "claude" or
    "codex" as DATA (never seen in this file today) would still
    false-positive here - accepted, since the real enforcement does not
    depend on this scan at all."""
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
    """Negative control: the scan actually fires on a bare occurrence inside
    an argv-shaped literal, not only ever passing silently."""
    tree = ast.parse('argv = [sys.executable, "claude", "-p", "hi"]\n', filename="<planted>")
    assert len(_find_real_binary_names_in_argv_literals(tree)) == 1


def test_the_binary_name_scan_catches_an_absolute_path_too() -> None:
    """Negative control (cross-model review): an absolute-path launch, not
    only a bare basename, must still fire."""
    tree = ast.parse('argv = [sys.executable, "/usr/bin/claude", "-p", "hi"]\n', filename="<planted>")
    assert len(_find_real_binary_names_in_argv_literals(tree)) == 1


def test_the_binary_name_scan_does_not_fire_on_a_client_keyword() -> None:
    """Negative control (the other direction): `client="claude"` is a bare
    keyword value, never inside a list/tuple literal, and must stay silent -
    proving the scan is scoped to argv shapes, not any string constant."""
    tree = ast.parse('at.run_one_attempt(client="claude")\n', filename="<planted>")
    assert _find_real_binary_names_in_argv_literals(tree) == []



# ------------------------------------------------------ leak check (#106)

def test_the_record_and_transcript_carry_no_credential_token(
    store: Path, base: Path, docker_state: Path, tmp_path: Path,
) -> None:
    """#106's own acceptance: "Leak check on the exported record and
    transcript, including the credential-token class from #105." Runs the
    real happy-path attempt, then scans BOTH the returned record (JSON) and
    the ACTUAL transcript bytes `agent_trial.py` itself read back (captured
    during the run, via `_TranscriptCapturingBackend` - cross-model review:
    reading the transcript file from disk AFTER the run falls back to an
    empty string once `destroy()` has removed it, which passes the scan
    whether or not anything was ever actually scanned; asserting the
    capture is non-empty is what rules that out)."""
    from skillc import leak

    backend = _TranscriptCapturingBackend(image="fake-image:1", base_dir=base, docker_bin=_docker_bin(docker_state))
    experiment, attempt_id = _planned(store)
    cred_path = _fresh_credential(tmp_path, "claude")
    home = _mapped_home(docker_state, attempt_id)
    transcript_relpath = ".claude/projects/test/22222222-2222-2222-2222-222222222222.jsonl"
    argv = _fake_argv(fmt="claude-fake", home=home, transcript_relpath=transcript_relpath)

    record = at.run_one_attempt(
        backend=backend, experiment=experiment, attempt_id=attempt_id, client="claude",
        base_argv=argv, prompt="Fix the slug helper.", skill_name="demo-skill",
        surface={}, limits=Limits(timeout=5), base=base,
        credential_explicit_path=cred_path,
    )
    record_text = json.dumps(record, default=str)
    findings = list(leak.scan_text(record_text, frozenset()))
    assert not findings, f"the record itself carries a leak: {findings}"

    tree = backend.captured.get(".claude/projects")
    assert tree, "the transcript was never actually captured - this proves nothing about a leak"
    (transcript_bytes,) = tree.values()
    assert transcript_bytes, "the captured transcript was empty - this proves nothing about a leak"
    findings = list(leak.scan_text(transcript_bytes.decode("utf-8"), frozenset()))
    assert not findings, f"the transcript carries a leak: {findings}"


def test_leak_check_catches_a_planted_credential_in_the_actual_transcript(
    store: Path, base: Path, docker_state: Path, tmp_path: Path,
) -> None:
    """Negative control for the test above (#106's own acceptance): the
    fake client plants a real, obviously-fake credential-shaped value INTO
    its own transcript (`--plant-leak`); the SAME capture-and-scan path
    used above must catch it, proving that check is not vacuous."""
    from skillc import leak

    backend = _TranscriptCapturingBackend(image="fake-image:1", base_dir=base, docker_bin=_docker_bin(docker_state))
    experiment, attempt_id = _planned(store)
    cred_path = _fresh_credential(tmp_path, "claude")
    home = _mapped_home(docker_state, attempt_id)
    transcript_relpath = ".claude/projects/test/22222222-2222-2222-2222-222222222222.jsonl"
    argv = _fake_argv(fmt="claude-fake", home=home, transcript_relpath=transcript_relpath, plant_leak=True)

    at.run_one_attempt(
        backend=backend, experiment=experiment, attempt_id=attempt_id, client="claude",
        base_argv=argv, prompt="Fix the slug helper.", skill_name="demo-skill",
        surface={}, limits=Limits(timeout=5), base=base,
        credential_explicit_path=cred_path,
    )

    tree = backend.captured.get(".claude/projects")
    assert tree
    (transcript_bytes,) = tree.values()
    findings = list(leak.scan_text(transcript_bytes.decode("utf-8"), frozenset()))
    assert findings, "leak-check is blind on its own planted credential value in a real captured transcript"
    assert {kind for _lineno, kind, _detail in findings} == {"credential-token"}


def test_leak_check_would_catch_a_planted_credential_value_in_the_record(store: Path) -> None:
    """Negative control (#106's own acceptance): a real leak of credential
    material into a record-shaped string IS caught - proving the check
    above is not vacuous."""
    from skillc import leak

    # Plain text, not JSON-wrapped: a JSON-escaped '\"access_token\": ...'
    # (what json.dumps would produce for this same value) does not match the
    # detector's unescaped-quote pattern - the exact bug #98's own planted
    # fixture found and fixed (skillc/leak.py's own module docstring).
    #
    # Built from fragments on purpose, exactly as skillc/demo.py's own
    # _seeded_leak_text does: this file is not on the repo-wide
    # `leak-check .` CI gate's exclude list, so a single literal here would
    # make this test file itself the leak. leak.scan_text still catches it
    # at runtime because it scans the assembled string, not this source line.
    planted = "record dump: " + '"access_token"' + ": " + '"planted-fake-oauth-token-value-0000"'
    findings = list(leak.scan_text(planted, frozenset()))
    assert findings, "leak-check is blind on its own planted credential value"
    assert {kind for _lineno, kind, _detail in findings} == {"credential-token"}


# ------------------------------------------------- transcript format census (#106)

_CODEX_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "transcripts" / "codex"
_CLAUDE_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "transcripts" / "claude-code"


def test_census_of_the_committed_codex_fixture_shows_no_drift() -> None:
    census = at.transcript_census("codex", (_CODEX_FIXTURES / "live-canary.jsonl").read_text())
    assert census["transcript_unrecognized_types"] == []
    line_types = census["transcript_line_types"]
    assert isinstance(line_types, dict) and line_types.get("response_item/custom_tool_call", 0) >= 1


def test_census_names_a_drifted_codex_response_item_type() -> None:
    """Red case: a tool call arriving as a payload type the adapter does not
    know (the adapter skips it silently, so the canary would read "no tool
    use" on a live run) must be named, not absorbed into a clean census."""
    raw = (_CODEX_FIXTURES / "live-canary.jsonl").read_text() + json.dumps(
        {"type": "response_item", "payload": {"type": "function_call", "name": "shell", "call_id": "x"}},
    ) + "\n"
    assert at.transcript_census("codex", raw)["transcript_unrecognized_types"] == ["function_call"]


def test_census_reads_version_and_model_and_copies_no_account_ids() -> None:
    raw = "\n".join(json.dumps(line) for line in (
        {"type": "session_meta", "payload": {
            "cli_version": "0.157.1", "creator_account_id": "acct-SHOULD-NOT-APPEAR",
            "creator_user_id": "user-SHOULD-NOT-APPEAR",
        }},
        {"type": "turn_context", "payload": {"model": "model-x"}},
        {"type": "event_msg", "payload": {"type": "task_started"}},
    ))
    census = at.transcript_census("codex", raw)
    assert census["transcript_client_version"] == "0.157.1"
    assert census["transcript_model"] == "model-x"
    assert "SHOULD-NOT-APPEAR" not in json.dumps(census)


def test_census_does_not_assess_claude_drift() -> None:
    census = at.transcript_census("claude", (_CLAUDE_FIXTURES / "live-canary.jsonl").read_text())
    assert census["transcript_unrecognized_types"] is None  # not assessed, never "no drift"


@pytest.mark.parametrize("raw", ["", "not json\n", '{"type": "session_meta", "payload": {"cli_version": "0.157.1"}}\n'])
def test_census_with_no_response_items_is_not_assessed(raw: str) -> None:
    """Codex review, red on the first census: an empty, malformed or
    item-less transcript reported `[]` - indistinguishable from a transcript
    whose every response item was recognized."""
    census = at.transcript_census("codex", raw)
    assert census["transcript_response_items_inspected"] == 0
    assert census["transcript_unrecognized_types"] is None


@pytest.mark.parametrize("bad_type", [[], {}])
def test_census_names_a_non_string_response_item_type_instead_of_crashing(bad_type: object) -> None:
    """Codex review pass 2, red on the first fix: an unhashable payload type
    raised TypeError, and the observation hook's catch-all then replaced the
    WHOLE observation - prompt, canary, credential - with status=unknown."""
    raw = (_CODEX_FIXTURES / "live-canary.jsonl").read_text() + json.dumps(
        {"type": "response_item", "payload": {"type": bad_type}},
    ) + "\n"
    census = at.transcript_census("codex", raw)
    assert census["transcript_unrecognized_types"] == [f"<non-string:{type(bad_type).__name__}>"]


# ------------------------------------------ the persisted observation (#106)


def _check_records(path: Path, rule: str | None = None) -> int:
    import argparse

    from skillc import cli

    return cli.cmd_check_records(argparse.Namespace(path=str(path), rule=rule))


#: What `attempt-accounting` says about a captured attempt with no stored
#: result. Since #139 a GRADED agent attempt stores one, so this is owed only
#: where grading was blocked - which is exactly what it should still say.
_GRADING_OWED = "is captured but has no result; grading is still owed"


def _store_is_clean(path: Path, capsys: pytest.CaptureFixture[str], *, grading_owed: bool = False) -> None:
    """Every evidence rule passes on the store, OR (issue #131 item 2)
    correctly refuses because this store genuinely has no record of that
    rule's own kind yet - e.g. a blocked-before-install attempt has no
    installation-receipt record at all. That is a different fact from "ran
    and found errors", so it is accepted here too - but only when the
    refusal's own message says so, never a blanket "exit 2 is fine", which
    would also silently swallow a real "no such path" or "unknown rule"
    bug. `attempt-accounting` is clean too, unless `grading_owed` - a
    captured attempt whose grading was blocked - in which case its ONLY
    finding is that grading is still owed."""
    from skillc import checks

    capsys.readouterr()
    for rule in checks.evidence_rules():
        if rule.id == "attempt-accounting":
            continue
        code = _check_records(path, rule.id)
        out = capsys.readouterr().out
        if code == 2:
            assert "checked nothing" in out, (rule.id, out)
            continue
        assert code == 0, rule.id
    capsys.readouterr()
    code = _check_records(path, "attempt-accounting")
    errors = [line for line in capsys.readouterr().out.splitlines() if line.startswith("error")]
    if grading_owed:
        assert code == 1 and len(errors) == 1 and _GRADING_OWED in errors[0], errors
    else:
        assert code == 0 and errors == [], errors


def _saved_observation(experiment: t.Experiment, attempt_id: str) -> dict[str, object]:
    path = experiment.root / at.observation_record_name(attempt_id)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _graded_codex_attempt(
    store: Path, base: Path, docker_state: Path, tmp_path: Path,
) -> tuple[t.Experiment, str, dict[str, object]]:
    experiment, attempt_id = _planned(store)
    argv = _fake_argv(
        fmt="codex-fake", home=_mapped_home(docker_state, attempt_id),
        transcript_relpath=".codex/sessions/2026/01/01/rollout-obs.jsonl", copy_solution=GRADER_ROOT / "reference",
    )
    record = at.run_one_attempt(
        backend=_backend(base, docker_state), experiment=experiment, attempt_id=attempt_id, client="codex",
        base_argv=argv, prompt="Fix the slug helper.", skill_name="demo-skill",
        surface={}, limits=Limits(timeout=5), base=base,
        credential_explicit_path=_fresh_credential(tmp_path, "codex"),
        grader=verify.GraderDef.load(GRADER_ROOT), grading_backend=_backend(base, docker_state),
    )
    return experiment, attempt_id, record


def test_a_graded_attempt_persists_its_observation_and_check_records_accepts_the_store(
    store: Path, base: Path, docker_state: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """#106's folded-in item: the observation used to live only in the
    returned dict. The value #124 lost - the in-container credential refresh -
    must now be readable from the store alone, after the dict is gone."""
    experiment, attempt_id, record = _graded_codex_attempt(store, base, docker_state, tmp_path)
    assert record["observation_record"] == "written"
    del record
    saved = _saved_observation(experiment, attempt_id)
    assert saved["kind"] == "agent-observation" and saved["status"] == "observed"
    transcript = saved["transcript"]
    assert isinstance(transcript, dict)
    assert transcript["prompt_delivered"] is True and transcript["canary_satisfied"] is True
    assert saved["credential"] == {
        "delivered": True, "source": "subscription",
        "remaining_seconds_at_launch": saved["credential"]["remaining_seconds_at_launch"],  # type: ignore[index]
        "refresh_observed_in_container": False,
    }
    grading = saved["grading"]
    assert isinstance(grading, dict) and grading["graded_status"] == "PASS" and grading["eligible"] is True
    _store_is_clean(experiment.root, capsys)


def test_a_graded_attempt_stores_a_verified_result_bound_to_its_manifest_and_pin(
    store: Path, base: Path, docker_state: Path, tmp_path: Path,
) -> None:
    """#139: the grade used to live only in the returned dict. Now the attempt
    stores a `verified-result`, graded over exactly the bytes its manifest
    captured, under the grader the ledger pinned. The observation stands in for
    the receipt, and readiness stays UNKNOWN (owner decision B1), so a task
    PASS is stored as INCONCLUSIVE - never a PASS no receipt readied."""
    experiment, attempt_id, record = _graded_codex_attempt(store, base, docker_state, tmp_path)
    [path] = experiment.root.glob("result-*.json")
    stored = json.loads(path.read_text(encoding="utf-8"))
    graded = record["graded"]
    assert isinstance(graded, dict)
    assert graded["status"] == "PASS" and graded["result_id"] == stored["result_id"]
    assert graded["result_status"] == stored["status"] == "INCONCLUSIVE"
    assert stored["attempt_id"] == attempt_id and stored["producer"] == "assembler"
    assert stored["grader"] == experiment.trial_of(attempt_id)["grader"]
    manifest = json.loads((experiment.root / f"manifest-{attempt_id}.json").read_text(encoding="utf-8"))
    assert stored["graded_digests"] == sorted({a["digest"] for a in manifest["artifacts"]})
    assert stored["verification"]["readiness_source"] == "agent-observation"
    [readiness] = [c for c in stored["criteria"] if c["id"] == verify.READINESS_CRITERION]
    assert readiness["outcome"] == "UNKNOWN"
    assert at.observation_record_name(attempt_id) in readiness["missing"]
    assert not list(experiment.root.glob("receipt-*.json"))


def test_an_agent_result_regrades_through_a_backend_on_its_own_observation(
    store: Path, base: Path, docker_state: Path, tmp_path: Path,
) -> None:
    """#139: a regrade reads the stored observation - valid, and bound to THIS
    attempt and trial (codex review) - and runs through a grading backend."""
    experiment, attempt_id, _record = _graded_codex_attempt(store, base, docker_state, tmp_path)
    [path] = experiment.root.glob("result-*.json")
    original = json.loads(path.read_text(encoding="utf-8"))
    grader = verify.GraderDef.load(GRADER_ROOT)
    observation = experiment.root / at.observation_record_name(attempt_id)
    good = observation.read_text(encoding="utf-8")

    swapped = {**json.loads(good), "attempt_id": "a-someone-else"}
    observation.write_text(json.dumps(swapped), encoding="utf-8")
    with pytest.raises(verify.Refused, match="another attempt"):
        verify.regrade(experiment, original["result_id"], grader, base, backend=_backend(base, docker_state))
    observation.write_text(json.dumps({**json.loads(good), "status": "bogus"}), encoding="utf-8")
    with pytest.raises(verify.Refused, match="not valid"):
        verify.regrade(experiment, original["result_id"], grader, base, backend=_backend(base, docker_state))

    observation.write_text(good, encoding="utf-8")
    again = verify.regrade(experiment, original["result_id"], grader, base, backend=_backend(base, docker_state))
    assert again["regrade_of"] == original["result_id"]
    assert again["verification"]["readiness_source"] == "agent-observation"  # type: ignore[index]
    assert again["criteria"] == original["criteria"]


def test_the_stored_stand_in_needs_its_observation(
    store: Path, base: Path, docker_state: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """Negative control for the stand-in on a real store: without the
    observation record, the receiptless result is graded without its receipt."""
    experiment, attempt_id, _record = _graded_codex_attempt(store, base, docker_state, tmp_path)
    (experiment.root / at.observation_record_name(attempt_id)).unlink()
    capsys.readouterr()
    assert _check_records(experiment.root, "attempt-accounting") == 1
    assert "holds no agent-observation" in capsys.readouterr().out


def test_a_blocked_grade_is_persisted_with_its_reason(
    store: Path, base: Path, docker_state: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    experiment, attempt_id = _planned(store)
    argv = _fake_argv(
        fmt="claude-fake", home=_mapped_home(docker_state, attempt_id),
        transcript_relpath=".claude/projects/test/22222222-2222-2222-2222-222222222222.jsonl",
        mismatched_prompt=True,
    )
    record = at.run_one_attempt(
        backend=_backend(base, docker_state), experiment=experiment, attempt_id=attempt_id, client="claude",
        base_argv=argv, prompt="Fix the slug helper.", skill_name="demo-skill",
        surface={}, limits=Limits(timeout=5), base=base,
        credential_explicit_path=_fresh_credential(tmp_path, "claude"),
        grader=verify.GraderDef.load(GRADER_ROOT), grading_backend=_backend(base, docker_state),
    )
    assert record["observation_record"] == "written"
    saved = _saved_observation(experiment, attempt_id)
    grading = saved["grading"]
    assert isinstance(grading, dict)
    assert grading["eligible"] is False and grading["graded_status"] is None
    assert "prompt_delivered=False" in str(grading["blocked_reason"])
    # #139's red case: an attempt captured but never graded still owes its grade.
    assert not list(experiment.root.glob("result-*.json"))
    _store_is_clean(experiment.root, capsys, grading_owed=True)


def test_an_attempt_blocked_before_launch_persists_a_not_observed_record(
    store: Path, base: Path, docker_state: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    experiment, attempt_id = _planned(store)
    record = at.run_one_attempt(
        backend=_backend(base, docker_state), experiment=experiment, attempt_id=attempt_id, client="claude",
        base_argv=[sys.executable, "-c", "import sys; sys.exit(1)"], prompt="Fix the slug helper.",
        skill_name="demo-skill", surface={}, limits=Limits(timeout=5), base=base,
        credential_explicit_path=_expired_credential(tmp_path), minimum_credential_seconds=300,
    )
    assert record["observation_record"] == "written"
    saved = _saved_observation(experiment, attempt_id)
    assert saved["status"] == "not-observed" and saved["transcript"] is None
    assert "below the required" in str(saved["reason"])
    assert saved["grading"] == {
        "grader_supplied": False, "eligible": False, "blocked_reason": None,
        "graded_status": None, "category": None, "criteria": None,
    }
    _store_is_clean(experiment.root, capsys)


def test_check_records_reads_the_persisted_observation_in_the_store(
    store: Path, base: Path, docker_state: Path, tmp_path: Path,
) -> None:
    """Negative controls for the store check itself: a green above could come
    from `check-records` never reading the file. A contradiction planted in the
    saved record, and a second observation for the same attempt, both turn it
    red."""
    experiment, attempt_id, _record = _graded_codex_attempt(store, base, docker_state, tmp_path)
    path = experiment.root / at.observation_record_name(attempt_id)
    good = path.read_text(encoding="utf-8")

    saved = json.loads(good)
    assert _check_records(experiment.root, "agent-observation") == 0
    assert _check_records(experiment.root, "unique-ids") == 0
    saved["transcript"]["canary_satisfied"] = False
    path.write_text(json.dumps(saved), encoding="utf-8")
    assert _check_records(experiment.root, "agent-observation") == 1

    saved = json.loads(good)
    saved["trial_id"] = "t-someone-else"
    path.write_text(json.dumps(saved), encoding="utf-8")
    assert _check_records(experiment.root, "ledger-binding") == 1  # bound to its attempt's trial

    path.write_text(good, encoding="utf-8")
    assert _check_records(experiment.root, "ledger-binding") == 0
    (experiment.root / "observation-duplicate.json").write_text(good, encoding="utf-8")
    assert _check_records(experiment.root, "unique-ids") == 1


def test_an_observation_carrying_a_token_is_refused_not_written(
    store: Path, base: Path, docker_state: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The leak gate on the record: an OAuth-shaped value embedded in a
    string (where `json.dumps` escaping would hide it from a text-only scan)
    means nothing is written, and the returned record says so."""
    real_build = at.build_observation_record

    def _poisoned(record: dict[str, object], **kwargs: object) -> dict[str, object]:
        data = real_build(record, **kwargs)  # type: ignore[arg-type]
        data["reason"] = json.dumps({"access_token": "Zq7" + "x" * 37})
        return data

    monkeypatch.setattr(at, "build_observation_record", _poisoned)
    experiment, attempt_id, record = _graded_codex_attempt(store, base, docker_state, tmp_path)
    assert record["observation_record"] == "refused-leak"
    assert not (experiment.root / at.observation_record_name(attempt_id)).exists()


def test_a_reason_naming_the_home_credential_path_is_redacted_and_written(
    store: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A blocked attempt's reason usually names the credential path, which
    sits under the operator's home - the leak scan refuses a home path, so
    without redaction the very record a blocked attempt most needs would be
    refused. `Path.home()` is pinned so this holds on any host (CI runs as
    root). The fake home is joined at run time so this file itself carries
    no home-shaped path for the repository's own leak-check step to flag."""
    fake_home = Path("/home") / "ci-user"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    experiment, attempt_id = _planned(store)
    data = at.build_observation_record(
        {"attempt_id": attempt_id, "trial_id": "t", "disposition": "unavailable",
         "reason": f"no codex credential at {fake_home}/.codex/auth.json", "observation": None},
        client="codex", grader_supplied=False,
    )
    assert at.write_observation_record(experiment, attempt_id, data) == "written"
    saved = _saved_observation(experiment, attempt_id)
    assert saved["reason"] == "no codex credential at <home>/.codex/auth.json"


def test_a_grading_failure_still_persists_the_observation(
    store: Path, base: Path, docker_state: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Codex review, red before the fix: persistence ran only after grading,
    so a verifier refusal (here: quarantined) propagated out and the observed
    attempt's observation was never written - the loss this record exists to
    prevent. The failure still propagates; the observation survives it."""
    def _quarantined(*args: object, **kwargs: object) -> object:
        raise verify.Refused("this verifier is quarantined: test")

    monkeypatch.setattr(verify, "grade_files", _quarantined)
    experiment, attempt_id = _planned(store)
    with pytest.raises(verify.Refused):
        argv = _fake_argv(
            fmt="codex-fake", home=_mapped_home(docker_state, attempt_id),
            transcript_relpath=".codex/sessions/2026/01/01/rollout-q.jsonl", copy_solution=GRADER_ROOT / "reference",
        )
        at.run_one_attempt(
            backend=_backend(base, docker_state), experiment=experiment, attempt_id=attempt_id, client="codex",
            base_argv=argv, prompt="Fix the slug helper.", skill_name="demo-skill",
            surface={}, limits=Limits(timeout=5), base=base,
            credential_explicit_path=_fresh_credential(tmp_path, "codex"),
            grader=verify.GraderDef.load(GRADER_ROOT), grading_backend=_backend(base, docker_state),
        )
    saved = _saved_observation(experiment, attempt_id)
    assert saved["status"] == "observed"
    grading = saved["grading"]
    assert isinstance(grading, dict) and grading["graded_status"] is None
    assert "grading raised Refused" in str(grading["blocked_reason"])
    assert _check_records(experiment.root, "agent-observation") == 0


def test_an_unwritable_store_reports_write_failed(store: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    experiment, attempt_id = _planned(store)
    data = at.build_observation_record(
        {"attempt_id": attempt_id, "trial_id": "t", "disposition": "unavailable", "reason": "x", "observation": None},
        client="codex", grader_supplied=False,
    )

    def _refuse(self: Path, *args: object, **kwargs: object) -> int:
        raise OSError("read-only store")

    monkeypatch.setattr(Path, "write_text", _refuse)
    assert at.write_observation_record(experiment, attempt_id, data) == "write-failed"


@pytest.mark.parametrize("which", ["missing", "reused"])
def test_a_grading_backend_refusal_still_persists_the_observation(
    which: str, store: Path, base: Path, docker_state: Path, tmp_path: Path,
) -> None:
    """Codex review pass 2, red before the fix: both grading-backend guards
    raised BEFORE the persistence-protected block, so a missing or reused
    grading backend discarded an observed attempt's observation."""
    backend = _backend(base, docker_state)
    experiment, attempt_id = _planned(store)
    argv = _fake_argv(
        fmt="codex-fake", home=_mapped_home(docker_state, attempt_id),
        transcript_relpath=".codex/sessions/2026/01/01/rollout-gb.jsonl", copy_solution=GRADER_ROOT / "reference",
    )
    with pytest.raises(ValueError):
        at.run_one_attempt(
            backend=backend, experiment=experiment, attempt_id=attempt_id, client="codex",
            base_argv=argv, prompt="Fix the slug helper.", skill_name="demo-skill",
            surface={}, limits=Limits(timeout=5), base=base,
            credential_explicit_path=_fresh_credential(tmp_path, "codex"),
            grader=verify.GraderDef.load(GRADER_ROOT), grading_backend=None if which == "missing" else backend,
        )
    grading = _saved_observation(experiment, attempt_id)["grading"]
    assert isinstance(grading, dict) and "grading raised ValueError" in str(grading["blocked_reason"])
    assert _check_records(experiment.root, "agent-observation") == 0


# ------------------------------------------- account identifiers at retention (#225)


@pytest.mark.parametrize(("line", "kind"), [
    # Each survives the serialized-text redaction; the decoded passes refuse it
    # (counter-model review). No case is a plain `"key": "value"` literal, which
    # the repo-wide `leak-check .` gate would flag in this file.
    (b'{"creator_\\u0075ser_id":"user-Example123"}', "account-id"),  # an escaped key
    (b'{"creator_user_id":123456789}', "account-id"),  # a non-string value
    (b'{"creator_account_id":["acct-Example123"]}', "account-id"),
    (b'{"message":"{\\"encrypted_content\\":\\"opaque-example\\"}"}', "encrypted-content"),
    (b'{"text":"see \\"encrypted_content\\": \\"opaque\\" here"}', "encrypted-content"),
])
def test_a_protected_field_redaction_cannot_reach_refuses_retention(line: bytes, kind: str) -> None:
    kept = at.redact_transcript_identities(line + b"\n")
    assert at.transcript_leak_findings(kept) == [f"{kind} at line 1"]
    assert at.retainable_transcript(kept).data is None


@pytest.mark.parametrize("template", [
    # #227: each keeps a populated rate_limits past the redaction. The key is
    # spliced in, so this file holds no literal of the field with a value for
    # the repo-wide `leak-check .` gate to flag.
    '{"payload":{"KEY":{"plan_type":"x"}} truncated',  # a line that does not parse
    '{"text":"{\\"KEY\\":{\\"plan_type\\":\\"x\\"}}"}',  # JSON printed inside a string
    '{"text":"saw \\"KEY\\": {\\"plan\\": 1} here"}',  # a fragment inside a string
    '{"rate_\\u006cimits":{"plan_type":"x"}}',  # an escaped key: KEY is not used
])
def test_rate_limits_the_redaction_cannot_reach_refuse_retention(template: str) -> None:
    line = template.replace("KEY", "rate_" + "limits").encode("utf-8")
    kept = at.redact_transcript_identities(line + b"\n")
    assert at.transcript_leak_findings(kept) == ["account-usage at line 1"]
    assert at.retainable_transcript(kept).data is None


def test_a_rewritten_line_keeps_its_escapes() -> None:
    """Counter-model review on #227: re-serializing a rate_limits line wrote
    a decoded U+2028 back raw, splitting the record under `splitlines()` so
    the response_id beside it scanned clean; a lone surrogate crashed the
    rewrite. Both now stay escaped."""
    rate_limits, response_id = "rate_" + "limits", "response_" + "id"
    separator = (
        '{"' + rate_limits + '":{"plan_type":"x"},"text":"\\u2028 {\\"' + response_id + '\\":\\"resp_fake\\"}"}\n'
    ).encode("ascii")
    kept = at.redact_transcript_identities(separator)
    assert len(kept.splitlines()) == 1
    assert at.transcript_leak_findings(kept) == ["response-id at line 1"]

    surrogate = ('{"' + rate_limits + '":{"plan_type":"x"},"name":"bad\\udcff.txt"}\n').encode("ascii")
    kept = at.redact_transcript_identities(surrogate)
    assert json.loads(kept)["name"] == "bad\udcff.txt"
    assert at.transcript_leak_findings(kept) == []


def test_redaction_replaces_rate_limits_and_response_id_and_nothing_else() -> None:
    """#227: a token_count's rate_limits object and a token_usage_record's
    response_id are redacted; untouched lines stay byte-identical."""
    rate_limits, response_id = "rate_" + "limits", "response_" + "id"
    lines = [
        '{"type":"event_msg","payload":{"type":"token_count","info":{"total_token_usage":{"input_tokens":5}},'
        '"' + rate_limits + '":{"plan_type":"planfake","credits":{"balance":"9999"},"primary":{"resets_at":17}}}}',
        '{"type":"token_usage_record","payload":{"' + response_id + '":"resp_fake01","usage":{"input_tokens":5}}}',
        '{"type":"response_item","payload":{"type":"message","role":"assistant","content":"done \u2019"}}',
    ]
    raw = ("\n".join(lines) + "\n").encode("utf-8")
    kept = at.redact_transcript_identities(raw)
    out = kept.splitlines()
    assert out[2] == raw.splitlines()[2]
    for value in (b"planfake", b"9999", b"resp_fake01"):
        assert value not in kept
    token_count = json.loads(out[0])["payload"]
    assert token_count[rate_limits] == "<redacted>"
    assert token_count["info"] == {"total_token_usage": {"input_tokens": 5}}  # evidence survives
    assert json.loads(out[1])["payload"]["usage"] == {"input_tokens": 5}
    assert at.transcript_leak_findings(kept) == []
    assert at.transcript_leak_findings(raw) == ["account-usage at line 1", "response-id at line 2"]


def test_redaction_replaces_only_the_protected_values() -> None:
    key = "creator_" + "user_id"  # built, so this file is no leak-check literal
    line = ('{"type":"session_meta","payload":{"' + key + '":"user-Example123","cli_version":"0.157.1"}}\n'
            '{"type":"response_item","payload":{"type":"reasoning","encrypted_content":"gAAAAopaque"}}\n'
            '{"type":"event_msg","payload":{"type":"task_started"}}\n').encode("utf-8")
    kept = at.redact_transcript_identities(line)
    assert kept.splitlines()[2] == line.splitlines()[2]  # an untouched line is byte-identical
    assert b"user-Example123" not in kept and b"gAAAAopaque" not in kept
    assert json.loads(kept.splitlines()[0])["payload"]["cli_version"] == "0.157.1"
    assert at.transcript_leak_findings(kept) == []
    assert at.transcript_leak_findings(line) != []  # the unredacted input is refused

