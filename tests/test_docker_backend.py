"""Tests for the Docker backend (#10): skillc's own, closing implementation of
the execution backend seam.

Tested here only against a fake `docker` CLI script - no daemon is available
in this session. This proves argv composition and the state machine, never a
containment boundary; see `describe()`'s own `unobserved` claims and PR1b's
same discipline for the fake host-subprocess backend.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from skillc import docker_backend as d
from skillc import lifecycle
from skillc import trial as t
from skillc.backend import BackendUnavailable, Confirmation, ExecutionBackend, Limits

FAKE_DOCKER = Path(__file__).resolve().parent / "fixtures" / "docker-backend" / "fake_docker.py"
FAKE_CLIENT = Path(__file__).resolve().parent / "fixtures" / "backend-lifecycle" / "fake_client.py"


def _docker_bin(state_dir: Path) -> list[str]:
    return [sys.executable, str(FAKE_DOCKER), "--state", str(state_dir)]


def _argv(mode: str) -> list[str]:
    return [sys.executable, str(FAKE_CLIENT), mode]


@pytest.fixture
def store(tmp_path: Path) -> Path:
    return t.open_store(tmp_path / "store", forbidden=[])


@pytest.fixture
def base(tmp_path: Path) -> Path:
    path = tmp_path / "work"
    path.mkdir()
    return path


@pytest.fixture
def docker_state(tmp_path: Path) -> Path:
    return tmp_path / "docker-state"


def _planned(store: Path) -> tuple[t.Experiment, str]:
    spec: dict[str, object] = {
        "experiment": "docker-lifecycle",
        "trials": [{
            "label": "t", "case": {"id": "c", "revision": "r1"}, "grader": {"id": "g", "revision": "g1"},
            "subject": {"digest": "sha256:00"}, "client": {"name": "fake", "version": "1"},
            "image": {"digest": "sha256:01"}, "config": {}, "attempts": 1,
        }],
    }
    experiment = t.plan(spec, store)
    [(_trial, attempt)] = list(experiment.attempts())
    return experiment, str(attempt["attempt_id"])


def _backend(base: Path, docker_state: Path) -> d.DockerBackend:
    return d.DockerBackend(image="fake-image:1", base_dir=base, docker_bin=_docker_bin(docker_state))


def _sentinel(docker_state: Path, name: str) -> None:
    """Fault injection is FILE-based (see fake_docker.py's own docstring for
    why): a `monkeypatch.setenv` reaches `execute()`'s `docker run` only by
    accident, since `execute()` deliberately launches it with a stripped
    `env={"PATH": ...}`, never the test process's own environment - that IS
    the property under test elsewhere in this file."""
    docker_state.mkdir(parents=True, exist_ok=True)
    (docker_state / name).touch()


# --------------------------------------------------------------------- describe


def test_the_protocol_runtime_check_passes(base: Path, docker_state: Path) -> None:
    assert isinstance(_backend(base, docker_state), ExecutionBackend)


def test_describe_reports_version_and_claims(base: Path, docker_state: Path) -> None:
    description = _backend(base, docker_state).describe()
    assert description.name == "docker"
    assert description.version == "26.0.0-fake"
    assert description.isolation
    assert description.unobserved
    assert any("sandbox" in claim for claim in description.isolation)
    assert any("live daemon boundary" in claim for claim in description.unobserved)


def test_describe_reports_unreachable_when_the_daemon_is_down(base: Path, docker_state: Path) -> None:
    _sentinel(docker_state, ".down")
    description = _backend(base, docker_state).describe()
    assert description.version == "unreachable"


# ------------------------------------------------------------------- prepare()


def test_daemon_unavailable_is_a_refusal(base: Path, docker_state: Path) -> None:
    _sentinel(docker_state, ".down")
    with pytest.raises(BackendUnavailable):
        _backend(base, docker_state).prepare("a-000000000000")


def test_two_attempts_get_separate_empty_private_homes(base: Path, docker_state: Path) -> None:
    """Addendum item 14: a private, EMPTY home per trial, never shared."""
    backend = _backend(base, docker_state)
    h1 = backend.prepare("a-000000000001")
    h2 = backend.prepare("a-000000000002")
    assert isinstance(h1, d._Handle)
    assert isinstance(h2, d._Handle)
    assert h1.home_dir != h2.home_dir
    for home in (h1.home_dir, h2.home_dir):
        assert (home / ".claude").is_dir()
        assert (home / ".codex").is_dir()
        assert list((home / ".claude").iterdir()) == []


def test_a_second_prepare_for_the_same_attempt_refuses_without_destroying_the_first(
    base: Path, docker_state: Path,
) -> None:
    """Regression for a bug found by cross-model review: `prepare()` used to
    treat ANY OSError from its mkdir calls - including the FileExistsError
    from calling it twice for one attempt_id - as this call's own failure,
    and `rmtree`'d the workspace root on the way out. That destroyed the
    FIRST call's already-returned, possibly in-use handle. This fails on the
    pre-fix code: the second `prepare()` there does not raise at all, and the
    first handle's work_dir is gone afterward."""
    backend = _backend(base, docker_state)
    h1 = backend.prepare("a-000000000001")
    assert isinstance(h1, d._Handle)
    (h1.work_dir / "in-progress.txt").write_text("do not delete me\n")
    with pytest.raises(BackendUnavailable):
        backend.prepare("a-000000000001")
    assert h1.work_dir.is_dir()
    assert (h1.work_dir / "in-progress.txt").read_text() == "do not delete me\n"


# -------------------------------------------------------------- compose_run_argv


def _compose(**overrides: object) -> list[str]:
    defaults: dict[str, object] = {
        "docker_bin": ["docker"],
        "image": "fake-image:1",
        "name": "skillc-a-000000000000",
        "work_dir": Path("/tmp/work"),
        "home_dir": Path("/tmp/home"),
        "subject_argv": ["echo", "hi"],
        "env": {},
        "network": "none",
        "memory": d.DEFAULT_MEMORY,
        "pids_limit": d.DEFAULT_PIDS_LIMIT,
        "cpus": d.DEFAULT_CPUS,
        "shm_size": d.DEFAULT_SHM_SIZE,
        "container_user": d._container_user(),
    }
    defaults.update(overrides)
    return d.compose_run_argv(**defaults)  # type: ignore[arg-type]


def test_composed_argv_never_mounts_the_docker_socket_or_widens_privilege() -> None:
    """Addendum item C12: never mount the docker socket, never give the
    trial a docker binary. There is no passthrough parameter for extra
    flags, so this is structural, not merely unused."""
    argv = _compose()
    text = " ".join(argv)
    assert "docker.sock" not in text
    assert "--privileged" not in argv
    assert "--cap-add" not in argv
    assert "--pid" not in argv  # never --pid=host


def test_composed_argv_carries_neutral_identity() -> None:
    argv = _compose()
    assert "--user" in argv and argv[argv.index("--user") + 1] == d._container_user()
    assert "--hostname" in argv and argv[argv.index("--hostname") + 1] == d.CONTAINER_HOSTNAME
    assert f"/tmp/work:{d.CONTAINER_WORKSPACE}:rw" in argv
    assert f"/tmp/home:{d.CONTAINER_HOME}:rw" in argv


def test_composed_argv_carries_the_real_host_uid_never_a_fixed_placeholder() -> None:
    """Regression for the fixed-'1000:1000' bug (found by cross-model review):
    `prepare()` creates the bind-mounted directories owned by whoever runs
    this process, so a container started under a DIFFERENT uid could not
    read or write its own mount. `container_user` must reflect the real
    caller, not a constant - this fails on the pre-fix code whenever the
    host uid/gid is not literally 1000:1000."""
    argv = _compose(container_user="4242:4242")
    assert argv[argv.index("--user") + 1] == "4242:4242"


def test_composed_argv_carries_matched_memory_and_swap_and_other_limits() -> None:
    """Addendum item C9: --memory-swap must equal --memory, or swap silently
    doubles the effective bound."""
    argv = _compose(memory="2g")
    assert argv[argv.index("--memory") + 1] == "2g"
    assert argv[argv.index("--memory-swap") + 1] == "2g"
    assert "--pids-limit" in argv
    assert "--cpus" in argv
    assert "--shm-size" in argv


def test_composed_argv_refuses_a_bare_env_name() -> None:
    with pytest.raises(TypeError, match="explicit string value"):
        _compose(env={"TOKEN": None})


def test_composed_argv_never_forwards_a_bare_dash_e() -> None:
    argv = _compose(env={"FOO": "bar"})
    assert "-e" in argv
    # every -e's following value must have a "=" - never a bare name
    values = [argv[i + 1] for i, a in enumerate(argv) if a == "-e"]
    assert all("=" in v for v in values)


# ------------------------------------------------------------------ install()


def test_install_resolves_and_records_the_image_digest(base: Path, docker_state: Path) -> None:
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-000000000003")
    readiness = backend.install(handle, {"skill": "x"})
    assert readiness["image_digest"] == "sha256:fake-digest-for-fake-image:1"


def test_install_stamps_provenance_of_the_controller_not_the_candidate(
    base: Path, docker_state: Path,
) -> None:
    """Addendum item E: a verdict that cannot say which skillc produced it is
    not reproducible. This is skillc's OWN checkout's provenance, never the
    experiment's or candidate's."""
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-000000000010")
    readiness = backend.install(handle, {"skill": "x"})
    stamped = readiness["provenance"]
    assert isinstance(stamped, dict)
    assert set(stamped) == {"skillc_version", "source_commit", "dirty"}
    assert stamped["skillc_version"]


def test_install_reports_readiness_facts_as_unknown_never_a_guessed_satisfied(
    base: Path, docker_state: Path,
) -> None:
    """Regression for a bug found by cross-model review: this backend only
    WRITES the declared surface - it never runs `materialize.py`'s own
    discovery/baseline observation against a real client - so claiming
    SATISFIED for `discovery_canary`/`baseline_absence` was a guess, not a
    check result. Fails on the pre-fix code, which reports SATISFIED for any
    non-empty declared surface regardless of what was actually observed."""
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-000000000011")
    readiness = backend.install(handle, {"skill": "x"})
    assert readiness["discovery_canary"] == "UNKNOWN"
    assert readiness["baseline_absence"] == "UNKNOWN"


def test_install_records_none_digest_when_the_image_is_unresolvable(base: Path, docker_state: Path) -> None:
    _sentinel(docker_state, ".no-image")
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-000000000004")
    readiness = backend.install(handle, {"skill": "x"})
    assert readiness["image_digest"] is None


def test_install_generically_materializes_declared_bytes_into_the_workspace(
    base: Path, docker_state: Path,
) -> None:
    """The hook a probe/grader-shaped surface (a different vocabulary than
    this module's own credential/client keys - see PR2, issue #10) uses to
    get real file content into the container's /work without this backend
    needing to know what the files mean: any declared entry whose VALUE is
    bytes is written at that relative path."""
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-materialize-0001")
    assert isinstance(handle, d._Handle)
    backend.install(handle, {"probe.py": b"print('hi')\n", "nested/inputs.json": b"{}"})
    assert (handle.work_dir / "probe.py").read_bytes() == b"print('hi')\n"
    assert (handle.work_dir / "nested" / "inputs.json").read_bytes() == b"{}"


def test_install_refuses_a_materialized_path_that_escapes_the_workspace(
    base: Path, docker_state: Path,
) -> None:
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-materialize-0002")
    with pytest.raises(ValueError, match="escapes the workspace"):
        backend.install(handle, {"../escape.txt": b"nope"})


def test_install_stages_a_credential_fresh_never_in_the_exported_workspace(
    base: Path, docker_state: Path,
) -> None:
    """Addendum item B5: a trial-scoped credential, written fresh into the
    private home - never exported as part of the workspace evidence."""
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-000000000005")
    assert isinstance(handle, d._Handle)
    backend.install(handle, {"skill": "x", "credential": "super-secret-token"})
    cred_path = handle.home_dir / ".skillc-credential"
    assert cred_path.read_text() == "super-secret-token"
    assert oct(cred_path.stat().st_mode)[-3:] == "600"

    dest = base / "exported"
    dest.mkdir()
    backend.export(handle, dest)
    exported_names = {p.name for p in dest.rglob("*")}
    assert ".skillc-credential" not in exported_names


def test_install_seeds_a_claude_onboarding_placeholder_when_declared(
    base: Path, docker_state: Path,
) -> None:
    """Addendum item A1: seed ~/.claude.json per trial inside the private
    home. This backend's demo never runs a real Claude Code client, so this
    proves the mechanism writes the documented shape - a real client's exact
    seed keys are version-measured, not guessed, per the module docstring."""
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-000000000006")
    assert isinstance(handle, d._Handle)
    readiness = backend.install(handle, {"skill": "x", "client": "claude", "client_version": "2.1.281"})
    seed_text = (handle.home_dir / ".claude.json").read_text()
    # Regression for a bug found by cross-model review: the hand-built seed
    # string had 5 literal closing braces against 3 opened, since it was not
    # an f-string and no `{{` escaping applied there - `json.loads` fails on
    # the pre-fix code, which is exactly why the earlier substring-only
    # assertions never caught it.
    seed = json.loads(seed_text)
    assert seed["hasCompletedOnboarding"] is True
    assert seed["projects"][d.CONTAINER_WORKSPACE]["hasTrustDialogAccepted"] is True
    assert readiness["client_version"] == "2.1.281"


def test_docker_backend_passes_a_consistent_env_to_every_docker_invocation(
    base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression for a bug found by cross-model review: `execute()` used to
    launch its `docker run` subprocess with a stripped `env={"PATH": ...}`
    while `probe_daemon`/`container_state`/`force_remove`/
    `_resolve_image_digest` all inherited the full ambient environment - so a
    `DOCKER_HOST` set in the environment could have `execute()` target the
    default daemon while confirmation/teardown queried a DIFFERENT one,
    falsely confirming teardown of a container still running elsewhere on
    the daemon `execute()` actually used. Fails on the pre-fix code: the env
    recorded for `execute()`'s own `Popen` call there carries no
    `DOCKER_HOST` key at all, while every other captured call's env does."""
    monkeypatch.setenv("DOCKER_HOST", "tcp://example-marker:2375")
    seen_envs: list[object] = []
    real_run: Any = subprocess.run
    real_popen: Any = subprocess.Popen

    def _is_docker_argv(args: tuple[Any, ...]) -> bool:
        # Scopes this check to the DOCKER CLI invocations this backend makes
        # - never `provenance.py`'s own `git` calls, which legitimately
        # inherit the ambient environment and have nothing to do with which
        # daemon a docker command reaches.
        return bool(args) and "fake_docker.py" in " ".join(str(a) for a in args[0])

    def _record_run(*args: Any, **kwargs: Any) -> Any:
        if _is_docker_argv(args):
            seen_envs.append(kwargs.get("env"))
        return real_run(*args, **kwargs)

    def _record_popen(*args: Any, **kwargs: Any) -> Any:
        if _is_docker_argv(args):
            seen_envs.append(kwargs.get("env"))
        return real_popen(*args, **kwargs)

    monkeypatch.setattr(d.subprocess, "run", _record_run)
    monkeypatch.setattr(d.subprocess, "Popen", _record_popen)

    backend = _backend(base, docker_state)
    handle = backend.prepare("a-envcheck-000001")
    assert isinstance(handle, d._Handle)
    backend.install(handle, {"skill": "x"})
    result = backend.execute(handle, _argv("work"), Limits(timeout=5))
    backend.confirm_stopped(handle)
    backend.destroy(handle)
    backend.confirm_absent(handle)

    assert result.reason == "exited"
    # Every call this backend made - prepare's probe, install's digest
    # resolution, execute's own docker run, and both confirmation queries -
    # must carry the identical connection env, never each inheriting the
    # ambient environment independently.
    assert len(seen_envs) >= 5
    for env in seen_envs:
        assert isinstance(env, dict)
        assert env.get("DOCKER_HOST") == "tcp://example-marker:2375"


def test_execute_delivers_stdin_to_the_subject(base: Path, docker_state: Path) -> None:
    """Found by w3 wiring PR2's probe driver: a grader's probe reads its
    held-out inputs from stdin. `-i` in compose_run_argv is what makes docker
    actually attach it; execute() writes it via a file, never a pipe it
    could deadlock the poll loop on."""
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-stdin-000001")
    assert isinstance(handle, d._Handle)
    backend.install(handle, {"skill": "x"})
    echo_script = "import sys, pathlib; pathlib.Path('echoed.txt').write_bytes(sys.stdin.buffer.read())"
    result = backend.execute(
        handle, [sys.executable, "-c", echo_script], Limits(timeout=5), stdin=b"hello-stdin",
    )
    assert result.reason == "exited"
    assert result.exit_code == 0
    assert (handle.work_dir / "echoed.txt").read_bytes() == b"hello-stdin"


def test_execute_without_stdin_behaves_exactly_as_before(base: Path, docker_state: Path) -> None:
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-stdin-000002")
    assert isinstance(handle, d._Handle)
    backend.install(handle, {"skill": "x"})
    result = backend.execute(handle, _argv("work"), Limits(timeout=5))
    assert result.reason == "exited"
    assert result.exit_code == 0


# -------------------------------------------------------- full lifecycle (fake docker)


def test_success_through_the_real_lifecycle_driver(store: Path, base: Path, docker_state: Path) -> None:
    experiment, attempt_id = _planned(store)
    backend = _backend(base, docker_state)
    record = lifecycle.run_through_backend(
        backend, experiment, attempt_id, _argv("work"), {"skill": "x"}, Limits(timeout=5), base,
    )
    assert record["disposition"] == "captured"
    assert record["backend_teardown"] == "confirmed"
    assert record["liveness_method"] == "canary"


def test_reply_only_is_caught_by_the_canary_through_the_docker_backend(
    store: Path, base: Path, docker_state: Path,
) -> None:
    """Addendum item 2 (msg 1333): the closing backend MUST implement the
    canary - the demo's negative control must fail on the reply-only client
    through THIS backend, not only the fake host-subprocess one from PR1b."""
    experiment, attempt_id = _planned(store)
    backend = _backend(base, docker_state)
    record = lifecycle.run_through_backend(
        backend, experiment, attempt_id, _argv("reply-only"), {"skill": "x"}, Limits(timeout=5), base,
    )
    assert record["disposition"] == "inconclusive"
    assert "liveness" in str(record["reason"])


def test_teardown_not_confirmed_when_the_daemon_lies_about_removal(
    store: Path, base: Path, docker_state: Path,
) -> None:
    """The fake docker's own negative control: `rm -f` reporting success
    while the container is still there must never read as a confirmed
    teardown."""
    experiment, attempt_id = _planned(store)
    _sentinel(docker_state, f".stuck-skillc-{attempt_id}")
    backend = _backend(base, docker_state)
    record = lifecycle.run_through_backend(
        backend, experiment, attempt_id, _argv("work"), {"skill": "x"}, Limits(timeout=5), base,
    )
    assert record["backend_teardown"] == "not-confirmed"


def test_confirm_stopped_and_confirm_absent_directly(base: Path, docker_state: Path) -> None:
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-000000000007")
    backend.install(handle, {"skill": "x"})
    # Nothing has been executed yet, so the daemon has never heard of this
    # container name - confirm_stopped must read that as CONFIRMED (nothing
    # running), never UNKNOWN or NOT_CONFIRMED.
    assert backend.confirm_stopped(handle) is Confirmation.CONFIRMED
    backend.destroy(handle)
    assert backend.confirm_absent(handle) is Confirmation.CONFIRMED


def test_confirm_stopped_is_unknown_when_the_daemon_cannot_be_asked(base: Path, docker_state: Path) -> None:
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-000000000008")
    backend.install(handle, {"skill": "x"})
    broken = d.DockerBackend(image="fake-image:1", base_dir=base, docker_bin=["this-does-not-exist-xyz"])
    assert broken.confirm_stopped(handle) is Confirmation.UNKNOWN
