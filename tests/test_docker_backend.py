"""Tests for the Docker backend (#77, sub-issue of #10): the `DockerBackend`
constructor/config, `describe()`'s claims, the composed `docker run` argv
(`compose_run_argv`, PR #83's interface), and the real lifecycle
(`prepare`, `install`, `execute`, `confirm_stopped`, `export`, `destroy`,
`confirm_absent`) this PR adds.

Tested here only against a fake `docker` CLI script
(`tests/fixtures/docker-backend/fake_docker.py`) - no daemon is available in
this session. This proves the lifecycle state machine, argv composition and
`describe()`'s claims, never a containment boundary; see `describe()`'s own
`unobserved` claims.
"""

from __future__ import annotations

import io
import sys
import tarfile
from pathlib import Path

import pytest

from skillc import docker_backend as d
from skillc import lifecycle as lc
from skillc.backend import BackendUnavailable, Confirmation, ExecutionBackend, Limits

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


# ------------------------------------------------------------------ lifecycle


def test_prepare_raises_when_daemon_unreachable(base: Path, docker_state: Path) -> None:
    _sentinel(docker_state, ".down")
    backend = _backend(base, docker_state)
    with pytest.raises(BackendUnavailable):
        backend.prepare("a-lc-000000000001")


def test_prepare_raises_when_docker_run_itself_fails(base: Path, docker_state: Path) -> None:
    """The daemon is reachable (`version` succeeds) but the actual `docker
    run -d` that starts this attempt's container is refused - prepare() must
    turn that into BackendUnavailable too, never construct a handle for a
    container that was never actually created."""
    _sentinel(docker_state, ".refuse-run")
    backend = _backend(base, docker_state)
    with pytest.raises(BackendUnavailable):
        backend.prepare("a-lc-000000000002")


def test_prepare_raises_when_the_docker_binary_is_missing(base: Path) -> None:
    backend = d.DockerBackend(
        image="fake-image:1", base_dir=base, docker_bin=["/nonexistent/docker-binary-xyz"],
    )
    with pytest.raises(BackendUnavailable):
        backend.prepare("a-lc-000000000003")


def test_install_reports_discovery_canary_violated_when_nothing_is_declared(
    base: Path, docker_state: Path,
) -> None:
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000004")
    readiness = backend.install(handle, {})
    assert readiness["discovery_canary"] == "VIOLATED"
    assert readiness["declared"] == 0
    assert "canary_path" not in readiness
    backend.destroy(handle)


def test_install_counts_a_non_path_surface_value_without_copying_it(
    base: Path, docker_state: Path,
) -> None:
    """Regression for a cross-model review finding (PR #85): `discovery_canary`
    must reflect what was actually COPIED, never merely what was declared - a
    non-path value (or a path that does not exist) is counted in `declared`
    but installs nothing, so readiness must not certify SATISFIED for it.
    This fails on the pre-fix code, which reported SATISFIED here regardless
    of whether anything was actually installed."""
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000005")
    readiness = backend.install(handle, {"meta": {"not": "a host path"}})
    assert readiness["declared"] == 1
    assert readiness["installed"] == 0
    assert readiness["discovery_canary"] == "VIOLATED"
    backend.destroy(handle)


def test_install_reports_installed_and_discovery_canary_satisfied_for_a_real_copy(
    base: Path, docker_state: Path, tmp_path: Path,
) -> None:
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000005b")
    surface_file = tmp_path / "skill.txt"
    surface_file.write_text("skill contents\n")
    readiness = backend.install(handle, {"skill.txt": surface_file})
    assert readiness["declared"] == 1
    assert readiness["installed"] == 1
    assert readiness["discovery_canary"] == "SATISFIED"
    backend.destroy(handle)


def test_install_raises_when_the_container_is_already_gone(
    base: Path, docker_state: Path, tmp_path: Path,
) -> None:
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000006")
    backend.destroy(handle)
    surface_file = tmp_path / "x.txt"
    surface_file.write_text("x")
    with pytest.raises(BackendUnavailable):
        backend.install(handle, {"x.txt": surface_file})


def test_full_lifecycle_happy_path_installs_executes_and_exports(
    base: Path, docker_state: Path, tmp_path: Path,
) -> None:
    """The whole seam, end to end, against the fake CLI: prepare() starts one
    persistent container; install() copies a declared surface file and plants
    the liveness canary via `docker cp`; execute() runs a real subprocess via
    `docker exec` that touches the canary and writes its own output;
    confirm_stopped() reports CONFIRMED once the container's own placeholder
    has been stopped too (not just the exec'd process); export() copies
    everything back out via `docker cp`; destroy()+confirm_absent() tear it
    down for real."""
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000007")

    surface_file = tmp_path / "skill.txt"
    surface_file.write_text("skill contents\n")
    nonce = "test-nonce-abc"
    readiness = backend.install(handle, {"skill.txt": surface_file, lc.CANARY_NONCE_KEY: nonce})
    assert readiness["discovery_canary"] == "SATISFIED"
    assert readiness["declared"] == 1
    assert readiness["canary_path"] == d.CANARY_RESULT_FILENAME

    script = (
        "import pathlib;"
        "p = pathlib.Path('.skillc-canary');"
        "n = p.read_text(encoding='utf-8') if p.exists() else '';"
        "pathlib.Path('.skillc-canary-result').write_text(f'touched:{n}', encoding='utf-8');"
        "pathlib.Path('out.txt').write_text('subject output', encoding='utf-8')"
    )
    result = backend.execute(handle, [sys.executable, "-c", script], Limits(timeout=5))
    assert result.reason == "exited"
    assert result.exit_code == 0

    assert backend.confirm_stopped(handle) is Confirmation.CONFIRMED

    dest = tmp_path / "export"
    backend.export(handle, dest)
    assert (dest / "out.txt").read_text(encoding="utf-8") == "subject output"
    assert (dest / d.CANARY_RESULT_FILENAME).read_text(encoding="utf-8") == f"touched:{nonce}"
    assert (dest / "skill.txt").read_text(encoding="utf-8") == "skill contents\n"

    backend.destroy(handle)
    assert backend.confirm_absent(handle) is Confirmation.CONFIRMED


def test_execute_delivers_stdin_like_a_bare_host_process(base: Path, docker_state: Path) -> None:
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000008")
    backend.install(handle, {})
    script = "import sys, pathlib; pathlib.Path('in.txt').write_bytes(sys.stdin.buffer.read())"
    result = backend.execute(
        handle, [sys.executable, "-c", script], Limits(timeout=5), stdin=b"hello from the test",
    )
    assert result.reason == "exited"
    assert result.exit_code == 0
    dest = docker_state.parent / "stdin-export"
    backend.export(handle, dest)
    assert (dest / "in.txt").read_bytes() == b"hello from the test"
    backend.destroy(handle)


def test_execute_timeout_kills_the_container_and_confirm_stopped_agrees(
    base: Path, docker_state: Path,
) -> None:
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000009")
    backend.install(handle, {})
    result = backend.execute(
        handle, [sys.executable, "-c", "import time; time.sleep(60)"],
        Limits(timeout=0.3, grace=1.0),
    )
    assert result.reason == "timeout"
    assert result.signal in ("SIGTERM", "SIGKILL")
    assert backend.confirm_stopped(handle) is Confirmation.CONFIRMED
    backend.destroy(handle)
    assert backend.confirm_absent(handle) is Confirmation.CONFIRMED


def test_execute_cancellation_kills_the_container(base: Path, docker_state: Path) -> None:
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000010")
    backend.install(handle, {})
    result = backend.execute(
        handle, [sys.executable, "-c", "import time; time.sleep(60)"],
        Limits(timeout=30, grace=1.0), cancel=lambda: True,
    )
    assert result.reason == "operator-cancelled"
    assert backend.confirm_stopped(handle) is Confirmation.CONFIRMED
    backend.destroy(handle)


def test_execute_reports_launch_failed_when_the_docker_binary_is_missing(
    base: Path, docker_state: Path,
) -> None:
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000011")
    backend.install(handle, {})
    broken = d.DockerBackend(
        image="fake-image:1", base_dir=base, docker_bin=["/nonexistent/docker-binary-xyz"],
    )
    result = broken.execute(handle, ["true"], Limits(timeout=1))
    assert result.reason == "launch-failed"
    assert result.exit_code is None
    assert result.error is not None
    backend.destroy(handle)


def test_confirm_stopped_is_unknown_when_the_daemon_is_unreachable(
    base: Path, docker_state: Path,
) -> None:
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000012")
    backend.install(handle, {})
    _sentinel(docker_state, ".down")
    assert backend.confirm_stopped(handle) is Confirmation.UNKNOWN
    assert backend.confirm_absent(handle) is Confirmation.UNKNOWN


def test_confirm_absent_is_not_confirmed_when_rm_lies(base: Path, docker_state: Path) -> None:
    """Negative control: fake_docker's `.stuck-NAME` sentinel makes `rm -f`
    report success without actually removing the container - confirm_absent()
    must catch that lie via an independent `inspect`, never trust destroy()'s
    own exit code."""
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000013")
    assert isinstance(handle, d._Handle)
    backend.install(handle, {})
    _sentinel(docker_state, f".stuck-{handle.name}")
    backend.destroy(handle)
    assert backend.confirm_absent(handle) is Confirmation.NOT_CONFIRMED


# ------------------------------------------------------- cross-model review (PR #85)


def test_owned_tar_sets_the_fixed_candidate_ownership_on_every_member(tmp_path: Path) -> None:
    """Regression for a cross-model review finding (PR #85): a plain `docker
    cp HOST_PATH NAME:DEST` preserves the SOURCE's own uid/gid, which could
    be anything on the controller's host - not the fixed candidate identity.
    `install()` instead builds its own tar stream so every member's ownership
    is set explicitly, regardless of the host file's real ownership."""
    surface_dir = tmp_path / "surface"
    surface_dir.mkdir()
    (surface_dir / "a.txt").write_text("a")
    (surface_dir / "sub").mkdir()
    (surface_dir / "sub" / "b.txt").write_text("b")

    payload = d._owned_tar(surface_dir, "skill")
    with tarfile.open(fileobj=io.BytesIO(payload)) as tar:
        members = tar.getmembers()
        assert members
        for member in members:
            assert member.uid == d.CANDIDATE_UID
            assert member.gid == d.CANDIDATE_GID


def test_owned_tar_bytes_sets_the_fixed_candidate_ownership(tmp_path: Path) -> None:
    payload = d._owned_tar_bytes("canary", b"hello")
    with tarfile.open(fileobj=io.BytesIO(payload)) as tar:
        member = tar.getmembers()[0]
        assert member.uid == d.CANDIDATE_UID
        assert member.gid == d.CANDIDATE_GID
        extracted = tar.extractfile(member)
        assert extracted is not None
        assert extracted.read() == b"hello"


def test_handle_env_is_captured_once_at_prepare_time(
    base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression for a cross-model review finding (PR #85): prepare() must
    capture the resolved docker connection environment ONCE and every later
    call must reuse it - never re-read `os.environ` per call - so an ambient
    DOCKER_HOST change mid-attempt cannot point confirm_stopped()/export()/
    destroy() at a different daemon than the one prepare() actually used.
    Fails on the pre-fix code, which had no captured env at all (every call
    recomputed `_docker_env()` fresh)."""
    monkeypatch.setenv("DOCKER_HOST", "unix:///original.sock")
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000016")
    assert isinstance(handle, d._Handle)
    assert handle.env.get("DOCKER_HOST") == "unix:///original.sock"
    monkeypatch.setenv("DOCKER_HOST", "unix:///changed-after-prepare.sock")
    assert handle.env.get("DOCKER_HOST") == "unix:///original.sock"
    backend.destroy(handle)


def test_handle_repr_never_leaks_the_connection_environment(
    base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DOCKER_HOST", "unix:///should-not-appear-in-repr.sock")
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000017")
    assert isinstance(handle, d._Handle)
    assert "should-not-appear-in-repr" not in repr(handle)
    backend.destroy(handle)


def test_confirm_stopped_is_unknown_on_an_unrecognized_inspect_error(
    base: Path, docker_state: Path,
) -> None:
    """Regression for a cross-model review finding (PR #85): docker's own CLI
    uses the SAME non-zero exit code for "no such object" and for other
    daemon-side errors (permission denial, TLS failure, ...) - only an
    explicit "no such" message may be trusted as a confirmed absence. Fails
    on the pre-fix code, which treated any non-zero exit other than "cannot
    connect" as a confirmed absence."""
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000018")
    assert isinstance(handle, d._Handle)
    backend.install(handle, {})
    _sentinel(docker_state, f".inspect-error-{handle.name}")
    assert backend.confirm_stopped(handle) is Confirmation.UNKNOWN
    assert backend.confirm_absent(handle) is Confirmation.UNKNOWN


def test_prepare_cleans_up_a_container_that_was_created_but_failed_to_start(
    base: Path, docker_state: Path,
) -> None:
    """Regression for a cross-model review finding (PR #85): backend.py's own
    Protocol requires a raising prepare() to own cleanup of whatever it
    already allocated. Docker creates a container before starting it, so a
    start failure can leave one behind now that --rm is dropped from this
    call. Fails on the pre-fix code, which left the orphaned state file in
    place after raising."""
    _sentinel(docker_state, ".refuse-start")
    backend = _backend(base, docker_state)
    with pytest.raises(BackendUnavailable):
        backend.prepare("a-lc-000000000019")
    name = d._container_name("a-lc-000000000019")
    assert not (docker_state / f"{name}.json").exists()


def test_execute_stop_escalation_falls_back_to_killing_the_local_client(
    base: Path, docker_state: Path,
) -> None:
    """Regression for a cross-model review finding (PR #85): if even the
    second `docker kill` leaves the subject running (a stuck daemon, or - as
    simulated here via `.stuck-NAME` - a container that lies about being
    killed), `_stop()` must still reap ITS OWN local docker-exec client
    process directly (SIGKILL, which cannot be blocked or ignored) rather
    than returning with it still running. Fails on the pre-fix code, which
    could leave that local process alive after two TimeoutExpired escalations
    (this test would otherwise hang for the full sleep duration)."""
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000020")
    assert isinstance(handle, d._Handle)
    backend.install(handle, {})
    _sentinel(docker_state, f".stuck-{handle.name}")
    result = backend.execute(
        handle, [sys.executable, "-c", "import time; time.sleep(5)"],
        Limits(timeout=0.3, grace=0.3),
    )
    assert result.reason == "timeout"
    assert result.signal == "SIGKILL"
    backend.destroy(handle)
