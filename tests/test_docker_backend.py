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


def test_composed_argv_carries_neutral_identity() -> None:
    argv = _compose()
    assert "--user" in argv and argv[argv.index("--user") + 1] == d._container_user()
    assert "--hostname" in argv and argv[argv.index("--hostname") + 1] == d.CONTAINER_HOSTNAME
    assert f"/tmp/work:{d.CONTAINER_WORKSPACE}:rw" in argv
    assert f"/tmp/home:{d.CONTAINER_HOME}:rw" in argv


def test_composed_argv_carries_the_real_host_uid_never_a_fixed_placeholder() -> None:
    """Regression for a fixed-'1000:1000' shape: `container_user` must
    reflect the real caller, not a constant, since the implementation PR's
    bind-mounted directories are owned by whoever runs this process."""
    argv = _compose(container_user="4242:4242")
    assert argv[argv.index("--user") + 1] == "4242:4242"


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
