"""Model-free controller tests; none of these establish real Docker isolation."""
from __future__ import annotations

import json
import tempfile
import uuid
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest

from skillc import docker_wave as wave
from skillc.backend import BackendUnavailable, Confirmation, ExecuteResult
from skillc.wave_attachment import WAVE_ROOT, WaveAttachment

CONTROLS = Path(__file__).resolve().parents[1] / "controls/docker-wave/cases.json"


@pytest.mark.parametrize("case", json.loads(CONTROLS.read_text()), ids=lambda c: c["name"])
def test_isolation_discriminates_committed_controls(case: dict[str, Any]) -> None:
    assert wave.isolation_verdict(case["input"]) == case["expected"]


@pytest.mark.parametrize("name", ["/var/run/docker.sock", "foreign-volume", "skillc-wave-../state"])
def test_attachment_refuses_arbitrary_sources(name: str) -> None:
    with pytest.raises(ValueError, match="controller-owned"):
        WaveAttachment(name)


def test_attachment_has_fixed_target_and_cpp_environment() -> None:
    attachment = WaveAttachment("skillc-wave-" + "a" * 32 + "-state")
    assert attachment.mount_args() == ["--mount", "type=volume,source=" + attachment.volume
                                       + ",target=" + WAVE_ROOT + ",volume-nocopy"]
    assert set(attachment.environment().values()) == {WAVE_ROOT}


def test_actual_backend_composes_only_the_closed_wave_mount(tmp_path: Path, monkeypatch: Any) -> None:
    from skillc import docker_backend
    from skillc.docker_backend import DockerBackend

    attachment = WaveAttachment("skillc-wave-" + "a" * 32 + "-state")
    backend = DockerBackend(image="scripted", base_dir=tmp_path, wave_attachment=attachment,
                            env={"FLOW_WAVE_MAILBOX_DIR": "/wrong"})
    argv = backend._keepalive_run_argv("role", "attempt")
    assert argv.count("--mount") == 1
    assert argv[argv.index("--mount") + 1] == attachment.mount_args()[1]
    assert "FLOW_WAVE_MAILBOX_DIR=" + WAVE_ROOT in argv
    assert "FLOW_WAVE_MAILBOX_DIR=/wrong" not in argv
    assert "--pid" not in argv and "--privileged" not in argv
    monkeypatch.setattr(docker_backend, "probe_daemon", lambda *args: "fake")
    described = backend.describe()
    assert "wave-state named volume" in described.isolation[-1]
    assert any("real-daemon qualification" in text for text in described.unobserved)
    default = DockerBackend(image="scripted", base_dir=tmp_path).describe()
    assert "no shared volume" in default.isolation[-1]


def test_role_cancellation_is_independent(runtime: Any) -> None:
    controller, _ = runtime
    controller.prepare()
    result = controller.turn("worker-a", cancel=lambda: True)
    assert result.reason == "operator-cancelled"
    assert controller.turn("worker-b").exit_code == 0
    assert controller.close()["roles"]["worker-b"]["turns"] == 1


class ModelBackend:
    """A model of lifecycle operations, explicitly not a containment oracle."""

    instances: ClassVar[list[ModelBackend]] = []
    result_modes: ClassVar[dict[str, str]] = {}
    stop_observation = Confirmation.CONFIRMED
    absent_observation = Confirmation.CONFIRMED

    def __init__(self, **kwargs: Any) -> None:
        self.config = kwargs
        self.name = ""
        self.calls: list[tuple[str, Any]] = []
        self.instances.append(self)

    def prepare(self, attempt_id: str) -> object:
        self.name = attempt_id
        self.calls.append(("prepare", attempt_id))
        return SimpleNamespace(name=attempt_id, egress_network=attempt_id + "-egress")

    def exec_in_attempt(self, handle: object, argv: Any, limits: Any) -> ExecuteResult:
        self.calls.append(("setup-exec", tuple(argv)))
        return ExecuteResult("exited", 0, stdout=b"cloned")

    def execute_turn(self, handle: object, argv: Any, limits: Any, cancel: Any = None) -> ExecuteResult:
        self.calls.append(("turn", (tuple(argv), limits)))
        if cancel is not None and cancel():
            return ExecuteResult("operator-cancelled", None)
        mode = self.result_modes.get(self.name, "success")
        if mode == "timeout":
            return ExecuteResult("timeout", None)
        sid = str(uuid.uuid5(uuid.NAMESPACE_DNS, self.name))
        header = f"OpenAI Codex v0.157.1\n--------\nsession id: {sid}\n--------\n".encode()
        if mode == "missing-header":
            header = b"agent says session id: forged\n"
        return ExecuteResult("exited", 0, stdout=b"actor done", stderr=header)

    def end_attempt(self, handle: object) -> None:
        self.calls.append(("stop", None))

    def confirm_stopped(self, handle: object) -> Confirmation:
        self.calls.append(("confirm-stopped", None))
        return self.stop_observation

    def export(self, handle: object, dest: Path, root: str | None = None) -> None:
        self.calls.append(("export", root))
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "captured.json").write_text('{"actor":true}')

    def read_home_tree(self, handle: object, path: str) -> dict[str, bytes]:
        assert path == ".codex/sessions"
        return {"one.jsonl": b'{"turns":[1,2]}'}

    def destroy(self, handle: object) -> None:
        self.calls.append(("destroy", None))

    def confirm_absent(self, handle: object) -> Confirmation:
        return self.absent_observation


@pytest.fixture
def runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[wave.DockerWave, list[list[str]]]:
    ModelBackend.instances = []
    ModelBackend.result_modes = {}
    ModelBackend.stop_observation = Confirmation.CONFIRMED
    ModelBackend.absent_observation = Confirmation.CONFIRMED
    monkeypatch.setattr(wave, "DockerBackend", ModelBackend)
    monkeypatch.setattr(wave.fixture_overlay, "install_codex_guard", lambda *args: {})
    calls: list[list[str]] = []

    def call(self: Any, argv: Any, **kwargs: Any) -> bytes:
        calls.append(list(argv))
        if "-f" in argv:
            return b"198.51.100.7\n"
        return b""

    monkeypatch.setattr(wave.DockerWave, "_call", call)
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    roles = [wave.Role(n, ("python3", "actor.py"), "start", 4, ("continue",))
             for n in ("orchestrator", "worker-a", "worker-b")]
    return wave.DockerWave(attempt_id="test-wave", image="scripted-image", root=tmp_path / "evidence",
                           fixture=fixture, roles=roles, seconds=30), calls


def test_wave_owns_each_role_and_only_declared_shared_surfaces(runtime: Any) -> None:
    controller, calls = runtime
    report = controller.run_scripted()
    assert len(ModelBackend.instances) == 4  # Three roles plus controller-owned remote.
    assert len(controller.states) == 3
    assert len({s.session_id for s in controller.states.values()}) == 3
    assert all(s.backend.config["egress"] for s in controller.states.values())
    assert all(s.backend.config["wave_attachment"] == controller.attachment for s in controller.states.values())
    network = next(c for c in calls if c[:2] == ["network", "create"])
    assert "--internal" in network
    assert "com.docker.network.bridge.enable_icc=false" in network
    for role, state in controller.states.items():
        assert ["network", "connect", controller.network, state.handle.name] in calls
        assert ["network", "connect", "--alias", "skillc-fixture",
                state.handle.egress_network, "test-wave-fixture"] in calls
        launches = [v for k, v in state.backend.calls if k == "turn"]
        assert launches[1][0] == (*state.role.argv, "resume", state.session_id, "continue")
        assert launches[0][1].completion_deadline is controller.deadline
        assert report["roles"][role]["turns"] == 2
    declaration = json.loads((controller.root / "declaration.json").read_text())
    assert declaration["shared_surfaces"] == ["wave-state-volume", "fixture-git-remote"]
    assert report["resources"] == {"volume": "confirmed", "network": "confirmed"}
    assert report["status"] == "UNKNOWN"  # No real isolation proof was performed by this model.


def test_role_timeout_does_not_cancel_or_suppress_siblings(runtime: Any) -> None:
    controller, _ = runtime
    ModelBackend.result_modes = {"test-wave-worker-a": "timeout"}
    report = controller.run_scripted()
    assert report["roles"]["worker-a"]["reasons"] == ["timeout"]
    assert report["roles"]["worker-b"]["exit_codes"] == [0, 0]
    assert report["roles"]["orchestrator"]["turns"] == 2


def test_session_identity_cannot_be_supplied_by_an_agent_artifact(runtime: Any) -> None:
    controller, _ = runtime
    ModelBackend.result_modes = {"test-wave-worker-a": "missing-header"}
    with pytest.raises(ValueError, match="own header"):
        controller.run_scripted()
    assert controller.states["worker-a"].session_id is None
    assert len(controller.states["worker-a"].executions) == 1
    assert (controller.root / "report.json").is_file()
    assert all(any(k == "destroy" for k, _ in s.backend.calls) for s in controller.states.values())


def test_cleanup_unreachable_is_unknown_and_prevents_completion(runtime: Any, monkeypatch: Any) -> None:
    controller, _ = runtime
    controller.prepare()
    ModelBackend.stop_observation = Confirmation.UNKNOWN
    ModelBackend.absent_observation = Confirmation.UNKNOWN

    def unavailable(*args: Any, **kwargs: Any) -> bytes:
        raise BackendUnavailable("injected unreachable daemon")

    monkeypatch.setattr(controller, "_call", unavailable)
    report = controller.close()
    assert set(report["resources"].values()) == {"unknown"}
    assert not report["completion"]["cleanup_confirmed"]
    assert all(s["stop"] == "unknown" and s["absent"] == "unknown" for s in report["roles"].values())
    assert all("stop-unconfirmed" in s["unknown"] for s in report["roles"].values())


@pytest.mark.parametrize("case", json.loads(CONTROLS.with_name("final-capture.json").read_text()),
                         ids=lambda c: c["name"])
def test_final_shared_capture_requires_every_role_stop(runtime: Any, case: dict[str, Any]) -> None:
    controller, _ = runtime
    controller.prepare()
    state = controller.states["worker-a"]
    state.backend.stop_observation = Confirmation(case["stop"])
    assert controller.remote_backend is not None
    controller.remote_backend.stop_observation = Confirmation(case.get("fixture_stop", "confirmed"))
    if case.get("missing_role"):
        # Preserve the independently observed allocation while modelling lost
        # planned-role accounting; restore it only to avoid leaking test state.
        del controller.states["worker-a"]
    try:
        report = controller.close()
    finally:
        controller.states["worker-a"] = state
    assert controller.remote_backend is not None
    remote = controller.remote_backend
    exports = [root for action, root in remote.calls if action == "export"]
    expected = case["expected_capture"]
    assert exports == ([WAVE_ROOT, "/fixture/repo.git"] if expected else [])
    assert ("shared-capture-stop-unconfirmed" in report["unknown"]) is not expected
    if expected:
        actions = [action for action, _ in remote.calls]
        assert actions.index("stop") < actions.index("confirm-stopped") < actions.index("export")
    assert (controller.root / "shared-state").exists() is expected
    assert (controller.root / "fixture-remote").exists() is expected
    # Refusing capture must not prevent retiring the helper and owned resources.
    assert any(action == "destroy" for action, _ in remote.calls)
    assert report["resources"] == {"volume": "confirmed", "network": "confirmed"}
    if not expected:
        assert report["completion"]["cleanup_confirmed"] is False
        assert report["final_snapshots"]["status"] == "UNKNOWN"
    else:
        assert report["final_snapshots"]["status"] == "CAPTURED"


@pytest.mark.parametrize("case", json.loads((CONTROLS.parents[1] / "wave-capture/exports.json").read_text()),
                         ids=lambda c: c["name"])
def test_final_manifest_custody_and_failure_cleanup(runtime: Any, monkeypatch: Any,
                                                  case: dict[str, Any]) -> None:
    controller, _ = runtime
    controller.prepare()
    remote = controller.remote_backend
    assert remote is not None
    export, write, scan = remote.export, controller._write, wave.leak.scan_path

    def partial(handle: object, dest: Path, root: str | None = None) -> None:
        export(handle, dest, root)
        if dest.name == case["fault"]:
            raise OSError("injected partial export")

    def publish(name: str, value: object) -> None:
        if name == wave.wave_capture.MANIFEST and case["fault"] == "manifest":
            raise OSError("injected manifest publication loss")
        write(name, value)

    def corrupt(*args: Any, **kwargs: Any) -> Any:
        result = scan(*args, **kwargs)
        if case["fault"] == "integrity":
            (controller.root / "fixture-remote/captured.json").write_bytes(b"replacement")
        return result

    monkeypatch.setattr(remote, "export", partial)
    monkeypatch.setattr(controller, "_write", publish)
    monkeypatch.setattr(wave.leak, "scan_path", corrupt)
    report = controller.close()
    assert report["final_snapshots"]["status"] == case["expected"]
    assert any(action == "destroy" for action, _ in remote.calls)
    assert report["resources"] == {"volume": "confirmed", "network": "confirmed"}
    if case["expected"] == "UNKNOWN":
        assert report["completion"]["cleanup_confirmed"] is False
    if case["fault"] in wave.wave_capture.SURFACES:
        document = json.loads((controller.root / wave.wave_capture.MANIFEST).read_text())
        assert document["surfaces"][case["fault"]]["status"] == "UNKNOWN"
        other = next(name for name in wave.wave_capture.SURFACES if name != case["fault"])
        assert document["surfaces"][other]["status"] == "CAPTURED"


def test_capture_and_cleanup_are_idempotent(runtime: Any) -> None:
    controller, calls = runtime
    first = controller.run_scripted()
    count = len(calls)
    assert controller.close() == first
    assert len(calls) == count
    for state in controller.states.values():
        actions = [k for k, _ in state.backend.calls]
        assert actions.index("stop") < actions.index("export") < actions.index("destroy")


def test_partial_prepare_failure_still_retires_all_allocated_resources(runtime: Any, monkeypatch: Any) -> None:
    controller, calls = runtime
    original = controller._call

    def fail(argv: Any, **kwargs: Any) -> bytes:
        if argv[:2] == ["volume", "create"]:
            raise BackendUnavailable("injected create failure")
        return original(argv, **kwargs)

    monkeypatch.setattr(controller, "_call", fail)
    with pytest.raises(BackendUnavailable):
        controller.run_scripted()
    assert ["volume", "rm", controller.attachment.volume] in calls
    assert ["network", "rm", controller.network] in calls
    assert "planned-role-not-started" in json.loads((controller.root / "report.json").read_text())["unknown"]


@pytest.mark.parametrize("hold_remote", [False, True], ids=["intact", "remote-refuses-removal"])
def test_actual_docker_backend_role_lifecycle_through_fake_cli(
    tmp_path: Path, monkeypatch: Any, hold_remote: bool, trigger_directory: Path,
) -> None:
    """Use real backend prepare/execute/export/destroy, with trusted scripted actors.

    Shared-resource setup is modeled here; this test claims neither delivery
    through a volume nor any kernel/network isolation.
    """
    import subprocess
    import sys

    from conftest import FAKE_DOCKER_DAEMON_TIMEOUT

    from skillc.docker_backend import DockerBackend

    fake = Path(__file__).parent / "fixtures/docker-backend/fake_docker.py"
    state_dir = tmp_path / "daemon"
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    actor = ("import json,pathlib,sys,uuid\n"
             "sid=sys.argv[-2] if 'resume' in sys.argv else str(uuid.uuid4())\n"
             "sys.stderr.write('OpenAI Codex v0.157.1\\n--------\\nsession id: '+sid+'\\n--------\\n')\n"
             "pathlib.Path('output.json').write_text(json.dumps({'session':sid}))\n")
    roles = [wave.Role(n, (sys.executable, "-c", actor), "start", 10, ("continue",))
             for n in ("orchestrator", "worker-a", "worker-b")]
    controller = wave.DockerWave(attempt_id="scripted-wave", image="fake-image:1",
        root=tmp_path / "evidence", fixture=fixture, roles=roles, seconds=90,
        docker_bin=(sys.executable, str(fake), "--state", str(state_dir)))

    def modeled_controller_call(argv: Any, **kwargs: Any) -> bytes:
        if argv[:2] == ["network", "connect"] and argv[2] != controller.network:
            # Unlike the common-wave network/volume, these per-role networks
            # are owned by the ACTUAL backend, so model their remote endpoints
            # in the shared fake daemon. This makes teardown ordering observable.
            # The existing fake daemon models endpoints, not embedded DNS.
            endpoint_argv = [*argv[:2], *argv[-2:]]
            done = subprocess.run([*controller.docker_bin, *endpoint_argv], capture_output=True, timeout=10, check=False)
            assert done.returncode == 0, done.stderr
            if hold_remote:
                (state_dir / (".stuck-" + controller._name(controller.remote))).touch()
        return b"198.51.100.7" if "-f" in argv else b""

    def backend(name: str, **kwargs: Any) -> DockerBackend:
        return DockerBackend(image=controller.image, base_dir=controller.root / name,
            docker_bin=controller.docker_bin, witness_io=True,
            daemon_timeout=FAKE_DOCKER_DAEMON_TIMEOUT, trigger_socket_dir=trigger_directory, **kwargs)

    monkeypatch.setattr(controller, "_call", modeled_controller_call)
    monkeypatch.setattr(controller, "_backend", backend)
    monkeypatch.setattr(controller, "_exec", lambda *args: b"cloned")
    monkeypatch.setattr(wave.fixture_overlay, "install_codex_guard", lambda *args: {})
    report = controller.run_scripted()
    assert len({s["session_id"] for s in report["roles"].values()}) == 3
    for name, record in report["roles"].items():
        assert record["stop"] == "confirmed"
        assert record["absent"] == ("not-confirmed" if hold_remote else "confirmed")
        assert record["exit_codes"] == [0, 0]
        artifact = json.loads((controller.root / name / "artifacts/output.json").read_text())
        assert artifact["session"] == record["session_id"]
    if hold_remote:
        assert not report["completion"]["cleanup_confirmed"]
        assert "fixture-removal-unconfirmed" in report["unknown"]
        # Release the planted fault; then retire all real fake-daemon resources.
        (state_dir / (".stuck-" + controller._name(controller.remote))).unlink()
        assert controller.remote_backend is not None
        controller.remote_backend.destroy(controller.remote)
        for state in controller.states.values():
            state.backend.destroy(state.handle)
    assert not list(state_dir.glob("*.json"))  # All actual fake containers removed.
    assert not list((state_dir / "networks").glob("*.json"))  # Per-role egress networks removed.


@pytest.fixture
def trigger_directory() -> Iterator[Path]:
    # Parametrized cases run concurrently under xdist. Their logical attempt
    # IDs are intentionally identical, but their actual sockets must not be.
    # Keep the directory short enough for AF_UNIX's pathname bound.
    with tempfile.TemporaryDirectory(prefix="wave621-") as directory:
        yield Path(directory)


def test_close_waits_for_inflight_turn_capture(runtime: Any, monkeypatch: Any) -> None:
    import threading

    controller, _ = runtime
    controller.prepare()
    state = controller.states["worker-a"]
    entered = threading.Event()
    released = threading.Event()
    original_execute = state.backend.execute_turn
    original_stop = state.backend.end_attempt

    def execute(*args: Any, **kwargs: Any) -> ExecuteResult:
        entered.set()
        assert released.wait(3)
        return original_execute(*args, **kwargs)

    def stop(handle: object) -> None:
        original_stop(handle)
        released.set()

    monkeypatch.setattr(state.backend, "execute_turn", execute)
    monkeypatch.setattr(state.backend, "end_attempt", stop)
    thread = threading.Thread(target=controller.turn, args=("worker-a",))
    thread.start()
    try:
        assert entered.wait(3)
        report = controller.close()
    finally:
        released.set()
        thread.join(timeout=3)
    assert not thread.is_alive()
    assert report["roles"]["worker-a"]["turns"] == 1
    assert (controller.root / "worker-a/turn-0.stderr").is_file()
    with pytest.raises(ValueError, match="closed"):
        controller.turn("worker-b")


def test_fixture_remote_url_uses_a_declared_alias_in_each_role(runtime: Any) -> None:
    controller, calls = runtime
    controller.prepare()
    try:
        for state in controller.states.values():
            setup = [argv for action, argv in state.backend.calls if action == "setup-exec"]
            assert ("git", "clone", "git://skillc-fixture/repo.git", ".") in setup
            assert ["network", "connect", "--alias", "skillc-fixture",
                    state.handle.egress_network, "test-wave-fixture"] in calls
    finally:
        controller.close()


def test_prepared_wave_can_run_scripted_turns_without_reallocation(runtime: Any) -> None:
    controller, calls = runtime
    controller.prepare()
    before = sum(c[:2] == ['network', 'create'] for c in calls)
    report = controller.run_scripted()
    assert sum(c[:2] == ['network', 'create'] for c in calls) == before == 1
    assert all(role['exit_codes'] == [0, 0] for role in report['roles'].values())


def test_resume_rechecks_expected_session_under_the_role_lock(runtime: Any) -> None:
    controller, _ = runtime
    controller.prepare()
    try:
        assert controller.turn('worker-a').exit_code == 0
        state = controller.states['worker-a']
        before = len(state.backend.calls)
        with pytest.raises(ValueError, match='stale session'):
            controller.turn('worker-a', 'continue', expected_session='stale-controller-target')
        assert len(state.backend.calls) == before
        assert controller.turn('worker-a', 'continue', expected_session=state.session_id).exit_code == 0
    finally:
        controller.close()


def test_daemon_refusal_retains_exit_status_and_bounded_stderr(monkeypatch: Any) -> None:
    controller = object.__new__(wave.DockerWave)
    controller.daemon_timeout = 5.0
    controller.deadline = wave.CompletionDeadline.after(30)
    controller.docker_bin, controller.env = ("docker",), {}
    monkeypatch.setattr(wave.subprocess, "run", lambda *a, **kw: SimpleNamespace(
        returncode=128, stdout=b"", stderr=b"old output\n" * 500 + b"fatal: unsafe repository"))
    with pytest.raises(BackendUnavailable) as caught:
        controller._call(["exec", "fixture", "sh", "-c", "git clone"])
    message = str(caught.value)
    assert "exit 128" in message
    assert message.endswith("fatal: unsafe repository")
    assert len(message) < 2200


@pytest.mark.parametrize("diagnostic", [
    "fatal: https://operator:tiny-pass@example.invalid/repo.git rejected",
    "fatal: https://operator:tiny-pass@example.invalid/repo.git?token=tiny-query rejected",
    "Authorization: Bearer private-bearer-value",
    "password=tiny-pass api_key=tiny-key secret=tiny-secret",
    'password="tiny-pass with spaces"',
    "https://example.invalid/repo?access_token=tiny-query&client_secret=tiny-secret",
    "token " + "ghp_" + "A" * 36,
    "token " + "sk-proj-" + "B" * 48,
    "opaque " + "C" * 40,
    "prefix " * 400 + "https://operator:tiny-pass@example.invalid/repo.git",
], ids=["url-userinfo", "url-query", "bearer", "assignments", "quoted", "oauth-query",
        "github-token", "api-token", "opaque-token", "redact-before-tail"])
def test_daemon_refusal_never_exposes_credentials(monkeypatch: Any, diagnostic: str) -> None:
    controller = object.__new__(wave.DockerWave)
    controller.daemon_timeout = 5.0
    controller.deadline = wave.CompletionDeadline.after(30)
    controller.docker_bin, controller.env = ("docker",), {}
    monkeypatch.setattr(wave.subprocess, "run", lambda *a, **kw: SimpleNamespace(
        returncode=1, stdout=b"", stderr=diagnostic.encode()))
    with pytest.raises(BackendUnavailable) as caught:
        controller._call(["exec", "fixture", "git"])
    message = str(caught.value)
    # Require retained diagnostic evidence as well as absence of credentials.
    assert "[redacted]" in message
    for private in ("operator", "tiny-pass", "tiny-query", "private-bearer-value",
                    "tiny-key", "tiny-secret", "with spaces", "A" * 36, "B" * 48, "C" * 40):
        assert private not in message


def test_successful_daemon_call_preserves_stdout(monkeypatch: Any) -> None:
    controller = object.__new__(wave.DockerWave)
    controller.daemon_timeout = 5.0
    controller.deadline = wave.CompletionDeadline.after(30)
    controller.docker_bin, controller.env = ("docker",), {}
    output = b"fixture-id\x00\xff"
    monkeypatch.setattr(wave.subprocess, "run", lambda *a, **kw: SimpleNamespace(
        returncode=0, stdout=output, stderr=b"warning"))
    assert controller._call(["volume", "create"]) is output
