"""Tests for the Docker backend's INTERFACE (#77, sub-issue of #10): the
`DockerBackend` constructor/config, `describe()`'s claims, and the composed
`docker run` argv (`compose_run_argv`). The full lifecycle (`prepare`,
`install`, `execute`, `confirm_stopped`, `export`, `destroy`,
`confirm_absent`) is #77's own follow-up implementation PR, tracked there -
every one of those methods raises `NotImplementedError` here on purpose.

Tested here only against a fake `docker` CLI script - no daemon is available
in this session. This proves argv composition and `describe()`'s claims,
never a containment boundary; see `describe()`'s own `unobserved` claims.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from skillc import docker_backend as d
from skillc.backend import ExecutionBackend, Limits

FAKE_DOCKER = Path(__file__).resolve().parent / "fixtures" / "docker-backend" / "fake_docker.py"


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


def _sentinel(docker_state: Path, name: str) -> None:
    """Fault injection is FILE-based (see fake_docker.py's own docstring for
    why): a `monkeypatch.setenv` reaches a real `docker run` invocation only
    by accident, since the implementation PR deliberately launches it with a
    stripped, explicit environment, never the test process's own."""
    docker_state.mkdir(parents=True, exist_ok=True)
    (docker_state / name).touch()


# ------------------------------------------------------------------ _docker_env


def test_docker_env_forwards_the_declared_connection_vars_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """`_docker_env()` is an ALLOWLIST, never a passthrough of the whole
    ambient environment: only `PATH` and the named `DOCKER_CONNECTION_VARS`
    may reach a docker invocation this backend makes. Named by cross-model
    review as an untested distinction - a real ambient variable that is not
    on the allowlist must never leak through, whatever else is set."""
    monkeypatch.setenv("DOCKER_HOST", "unix:///tmp/test-daemon.sock")
    monkeypatch.setenv("UNDECLARED_SECRET", "sentinel")
    env = d._docker_env()
    assert env.get("DOCKER_HOST") == "unix:///tmp/test-daemon.sock"
    assert "UNDECLARED_SECRET" not in env
    assert "PATH" in env


def test_docker_env_omits_a_connection_var_that_is_not_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    env = d._docker_env()
    assert "DOCKER_CONTEXT" not in env


# --------------------------------------------------------------------- describe


def test_the_protocol_runtime_check_passes(base: Path, docker_state: Path) -> None:
    """Even with every lifecycle method stubbed, `DockerBackend` already
    satisfies the `ExecutionBackend` Protocol structurally - the exact
    signatures are what #78/#79 build against before the implementation PR
    lands."""
    assert isinstance(_backend(base, docker_state), ExecutionBackend)


def test_describe_reports_version_and_claims(base: Path, docker_state: Path) -> None:
    description = _backend(base, docker_state).describe()
    assert description.name == "docker"
    assert description.version == "26.0.0-fake"
    assert description.isolation
    assert description.unobserved
    assert any("sandbox" in claim for claim in description.isolation)
    assert any(d.OWNER_LABEL_KEY in claim for claim in description.isolation)


def test_describe_states_disk_limit_is_unset_by_default(base: Path, docker_state: Path) -> None:
    description = _backend(base, docker_state).describe()
    assert any("disk_limit is None" in claim for claim in description.isolation)
    assert any("storage-opt" in claim for claim in description.unobserved)


def test_describe_states_the_configured_disk_limit(base: Path, docker_state: Path) -> None:
    backend = d.DockerBackend(
        image="fake-image:1", base_dir=base, docker_bin=_docker_bin(docker_state), disk_limit="3g",
    )
    description = backend.describe()
    assert any("size=3g" in claim for claim in description.isolation)


def test_describe_reports_unreachable_when_the_daemon_is_down(base: Path, docker_state: Path) -> None:
    _sentinel(docker_state, ".down")
    description = _backend(base, docker_state).describe()
    assert description.version == "unreachable"


def test_describe_reports_the_fixed_candidate_user_regardless_of_the_host_caller(
    base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Design correction (orchestrator review of PR #83, 2026-09-26): an
    earlier draft derived the container's user from the HOST caller's own
    uid/gid, which the container's own `id`, file ownership and transcripts
    would then carry straight into the trial's evidence - a leak `describe()`
    hiding the number could not prevent, since the number was never only in
    `describe()`'s prose. The claim must name the fixed candidate identity
    and must not change with the host caller's uid - this fails on the
    pre-fix code, whose claim (and the composed --user) tracked
    `os.getuid()`/`os.getgid()` directly."""
    monkeypatch.setattr(d.os, "getuid", lambda: 0)
    monkeypatch.setattr(d.os, "getgid", lambda: 0)
    description = _backend(base, docker_state).describe()
    assert any(f"{d.CANDIDATE_UID}:{d.CANDIDATE_GID}" in claim for claim in description.isolation)
    assert any("non-root" in claim for claim in description.isolation)
    assert not any("0:0" in claim for claim in description.isolation)


def test_every_lifecycle_method_is_stubbed_pending_the_implementation_pr(
    base: Path, docker_state: Path,
) -> None:
    """This PR is #77's interface only. Each method beyond `describe()` must
    refuse loudly (NotImplementedError), never silently do nothing or return
    a guessed value - a caller building against this interface before the
    implementation PR lands must see an unmistakable refusal, not a result
    that looks real."""
    backend = _backend(base, docker_state)
    with pytest.raises(NotImplementedError):
        backend.prepare("a-000000000000")
    with pytest.raises(NotImplementedError):
        backend.install(object(), {})
    with pytest.raises(NotImplementedError):
        backend.execute(object(), ["true"], Limits(timeout=1))
    with pytest.raises(NotImplementedError):
        backend.confirm_stopped(object())
    with pytest.raises(NotImplementedError):
        backend.export(object(), Path("/nonexistent"))
    with pytest.raises(NotImplementedError):
        backend.destroy(object())
    with pytest.raises(NotImplementedError):
        backend.confirm_absent(object())


# -------------------------------------------------------------- compose_run_argv


def _compose(**overrides: object) -> list[str]:
    defaults: dict[str, object] = {
        "docker_bin": ["docker"],
        "image": "fake-image:1",
        "name": "skillc-a-000000000000",
        "attempt_id": "a-000000000000",
        "subject_argv": ["echo", "hi"],
        "env": {},
        "network": "none",
        "memory": d.DEFAULT_MEMORY,
        "pids_limit": d.DEFAULT_PIDS_LIMIT,
        "cpus": d.DEFAULT_CPUS,
        "shm_size": d.DEFAULT_SHM_SIZE,
        "container_user": d._container_user(),
        "disk_limit": None,
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


def test_composed_argv_places_image_after_an_end_of_options_marker() -> None:
    """Regression for a bug found by cross-model review: `image` was appended
    as a bare positional with nothing marking where options end. Docker's
    flag parser keeps scanning for recognized flags throughout the argument
    list rather than stopping at the first positional, so an `image` value
    that itself looks like a flag - `--privileged`, say - was not guaranteed
    to be consumed as the IMAGE rather than reinterpreted as an option,
    contradicting the closed-argv guarantee the test above checks. `--` is
    Docker's own end-of-options marker; this fails on the pre-fix code,
    which places `image` with nothing before it to end option parsing."""
    argv = _compose(image="--privileged")
    assert "--" in argv
    dash_dash = argv.index("--")
    assert argv[dash_dash + 1] == "--privileged"
    # the flag-shaped image value must appear only AFTER the "--" boundary,
    # never anywhere in the option region ahead of it
    assert "--privileged" not in argv[:dash_dash]


def test_composed_argv_carries_neutral_identity() -> None:
    argv = _compose()
    assert "--user" in argv and argv[argv.index("--user") + 1] == d._container_user()
    assert "--hostname" in argv and argv[argv.index("--hostname") + 1] == d.CONTAINER_HOSTNAME
    assert "-w" in argv and argv[argv.index("-w") + 1] == d.CONTAINER_WORKSPACE
    home_values = [argv[i + 1] for i, a in enumerate(argv) if a == "-e"]
    assert f"HOME={d.CONTAINER_HOME}" in home_values


def test_composed_argv_never_bind_mounts_the_workspace_or_home() -> None:
    """Design decision (orchestrator review of PR #83, 2026-09-26): no bind
    mount for the workspace or home, ever - a mount matched to the fixed
    candidate uid would need a host directory made writable for that exact
    uid, which is either another uid-matching problem or over-broad write
    access. `docker cp` moves the declared surface in and the exported
    output out instead (the implementation PR's install()/export())."""
    argv = _compose()
    assert "-v" not in argv


def test_container_user_is_fixed_and_never_tracks_the_host_callers_uid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The orchestrator's requested control (PR #83 review, 2026-09-26): the
    composed `--user` must be the fixed candidate identity and must NEVER be
    `os.getuid()`/`os.getgid()`, whatever the host caller's real uid is. This
    fails on the design an earlier draft shipped, where `_container_user()`
    returned `f"{os.getuid()}:{os.getgid()}"` directly."""
    monkeypatch.setattr(d.os, "getuid", lambda: 777777)
    monkeypatch.setattr(d.os, "getgid", lambda: 888888)
    assert d._container_user() == f"{d.CANDIDATE_UID}:{d.CANDIDATE_GID}"
    argv = _compose(container_user=d._container_user())
    assert argv[argv.index("--user") + 1] == f"{d.CANDIDATE_UID}:{d.CANDIDATE_GID}"
    assert "777777:888888" not in argv


def test_composed_argv_carries_ownership_labels() -> None:
    """#77's ownership requirement: every container carries a fixed
    "this belongs to skillc" label plus a per-attempt label - a reaping sweep
    (#79) filters on the fixed label to find every skillc-owned container
    without trusting name matching, and a foreign container sharing a similar
    name but carrying neither label is never touched."""
    argv = _compose(attempt_id="a-abc123")
    labels = [argv[i + 1] for i, a in enumerate(argv) if a == "--label"]
    assert f"{d.OWNER_LABEL_KEY}={d.OWNER_LABEL_VALUE}" in labels
    assert f"{d.ATTEMPT_LABEL_KEY}=a-abc123" in labels


def test_composed_argv_omits_storage_opt_when_no_disk_limit_is_set() -> None:
    argv = _compose(disk_limit=None)
    assert "--storage-opt" not in argv


def test_composed_argv_carries_a_storage_opt_disk_bound_when_set() -> None:
    argv = _compose(disk_limit="2g")
    assert "--storage-opt" in argv
    assert argv[argv.index("--storage-opt") + 1] == "size=2g"


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
