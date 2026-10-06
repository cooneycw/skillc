"""The #183 red case (acceptance item 2): a subject that fabricates
requests - writes directly to the subject-writable request log instead of
calling a real tool through the controller's socket - must not move the
controller-recorded disruption point, and must be distinguishable from a
cooperating subject.

RUN AGAINST THE PRE-#183 MECHANISM DIRECTLY, NOT A COMMIT CHECKOUT.
`skillc/disruption_trigger.py` (#14 part c) is #183's own "before": it
existed unmodified before this issue and is unmodified by it - #183's whole
premise is that this module's own docstring states ("the count IS the
claim, and the claim is unenforced end to end"). So the red half of this
file imports and runs that exact pre-#183 code, today, at this commit - no
separate checkout is needed, because the "before" implementation never
changed and is still present in the tree. `test_the_bypass_fools_the_pre_
channel_advisory_mechanism` is the committed red case; it is red (reports a
plausible, fabricated count) on `disruption_trigger.py` as it stands on
`main` today, exactly as it was before #183, and stays red there forever -
that module is deliberately never going to be fixed, because the fix is a
different mechanism entirely (`decide_reply_channel.py`), not a patch to
this one. `test_the_channel_catches_the_same_bypass_as_no_controller_
witness` is the green: the SAME bypass, read through #183's channel
instead, reported as `no-controller-witness`.

Driven against the fake `docker` CLI (`tests/fixtures/docker-backend/
fake_docker.py`) - this red case is about which CONTROLLER-SIDE mechanism
is trusted, not about a real containment boundary, so no daemon is needed
for it. The separate live-Docker conformance test
(`tests/test_decide_reply_channel_live.py`) covers the real bind mount.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from conftest import FAKE_DOCKER_DAEMON_TIMEOUT

from skillc import docker_backend as d
from skillc.backend import Confirmation, Limits
from skillc.decide_reply_channel import DecideFn, TrustedLog
from skillc.disruption_trigger import DEFAULT_REQUEST_LOG, DisruptionTrigger

FAKE_DOCKER = Path(__file__).resolve().parent / "fixtures" / "docker-backend" / "fake_docker.py"


def _docker_bin(state_dir: Path) -> list[str]:
    return [sys.executable, str(FAKE_DOCKER), "--state", str(state_dir)]


#: The fake CLI's `subprocess.run(argv, ..., env=env)` REPLACES the
#: environment wholesale, and `_remap_absolute` substring-matches "/work"
#: anywhere in an argv token to rewrite it into the simulated container
#: fsroot (skillc Nit Store #20) - a real hazard for `sys.executable`
#: specifically when the controller's own checkout happens to live under a
#: directory named "work" (as this one does). A bare `python3`, resolved
#: via an explicit PATH instead of an absolute interpreter path, never
#: matches that substring and needs no fsroot rewrite at all.
_SUBJECT_ENV = {"PATH": "/usr/bin:/bin:/usr/local/bin"}
_PYTHON = "python3"


def _short_trigger_socket_dir() -> Path:
    """Deliberately NOT nested under pytest's own `tmp_path` - that
    prefix is already 60-90+ characters on its own, which overflows
    `DecideReplyChannel.start()`'s AF_UNIX safety margin before any
    socket filename is even added. `tempfile.mkdtemp()` creates a short
    directory directly under the system temp root instead. Not cleaned
    up - a throwaway test directory, same as this file's other temp
    state."""
    return Path(tempfile.mkdtemp(prefix="sk-bypass-"))


def _fixed_decide(fail_at: int) -> DecideFn:
    def decide(request: object) -> dict[str, object]:
        assert isinstance(request, dict)
        return {"decision": "fail" if request.get("seq") == fail_at else "pass"}
    return decide


def _bypass_script(n: int) -> str:
    """The bypass itself: fabricates `n` lines in the exact file
    `DisruptionTrigger` polls, and never connects to any socket at all -
    the whole point being that this is indistinguishable, FROM THE
    SUBJECT'S OWN FILESYSTEM ACTIONS ALONE, from `n` genuine tool calls
    that happened to use the old, subject-writable logging convention."""
    return (
        "import os\n"
        "os.makedirs('.disruption', exist_ok=True)\n"
        f"with open({DEFAULT_REQUEST_LOG!r}, 'a') as f:\n"
        f"    for _ in range({n}):\n"
        "        f.write('request\\n')\n"
    )


def test_the_bypass_fools_the_pre_channel_advisory_mechanism(tmp_path: Path) -> None:
    """THE RED CASE. `DisruptionTrigger` (#14c, unmodified by #183) polls
    the subject-writable log and reports whatever it finds there as an
    advisory count - it cannot tell a fabricated line from a real one, so
    a bypassing subject gets a count that reads exactly like 5 genuine
    tool calls. This is the pre-#183 mechanism's own documented gap
    (`disruption_trigger.py`'s module docstring), exercised here rather
    than merely cited."""
    base = tmp_path / "work"
    base.mkdir()
    docker_state = tmp_path / "docker-state"
    backend = d.DockerBackend(
        image="fake-image:1", base_dir=base, docker_bin=_docker_bin(docker_state),
        daemon_timeout=FAKE_DOCKER_DAEMON_TIMEOUT, env=_SUBJECT_ENV,
    )
    handle = backend.prepare("a-lc-bypass-red-000000001")
    observer = DisruptionTrigger(backend, handle, fail_after=3, interval=0.05)
    observer.start()
    result = backend.execute(handle, [_PYTHON, "-c", _bypass_script(5)], Limits(timeout=10))
    assert result.reason == "exited" and result.exit_code == 0
    assert backend.confirm_stopped(handle) is Confirmation.CONFIRMED
    advisory = observer.stop_and_finalize()
    backend.destroy(handle)
    assert advisory is not None
    data = json.loads(advisory)
    # This is the red: a pure fabrication reads as "5 requests happened,"
    # indistinguishable from 5 genuine ones - exactly the claim #14c's own
    # docstring says this module can never honestly make.
    assert data["requests_received"] == 5


def test_the_channel_catches_the_same_bypass_as_no_controller_witness(tmp_path: Path) -> None:
    """THE GREEN. The identical bypass, read through #183's channel
    instead: the subject never connects to the socket, so the controller
    never receives a request to decide on, and the finalized log is
    empty - `TrustedLog.witnessed([])` reports `no-controller-witness`,
    never a fabricated count and never a guessed `NOT_CONFIRMED`."""
    base = tmp_path / "work"
    base.mkdir()
    docker_state = tmp_path / "docker-state"
    backend = d.DockerBackend(
        image="fake-image:1", base_dir=base, docker_bin=_docker_bin(docker_state),
        daemon_timeout=FAKE_DOCKER_DAEMON_TIMEOUT, env=_SUBJECT_ENV,
        trigger_decide=_fixed_decide(fail_at=3), trigger_socket_dir=_short_trigger_socket_dir(),
    )
    handle = backend.prepare("a-lc-bypass-red-000000002")
    result = backend.execute(handle, [_PYTHON, "-c", _bypass_script(5)], Limits(timeout=10))
    assert result.reason == "exited" and result.exit_code == 0
    assert backend.confirm_stopped(handle) is Confirmation.CONFIRMED
    log = backend.trigger_log(handle)
    backend.destroy(handle)
    assert log == []  # the bypass never reached the channel at all
    trusted = TrustedLog.witnessed(log)
    assert trusted.status == "no-controller-witness"


def test_a_cooperating_subject_is_witnessed_not_mistaken_for_a_bypass(tmp_path: Path) -> None:
    """Sanity check on the pair above: a subject that DOES call through
    the channel is `witnessed`, with the real decisions recorded - so the
    distinction in the two tests above is actually the bypass, not some
    other difference between the two scripts."""
    base = tmp_path / "work"
    base.mkdir()
    docker_state = tmp_path / "docker-state"
    trigger_socket_dir = _short_trigger_socket_dir()
    backend = d.DockerBackend(
        image="fake-image:1", base_dir=base, docker_bin=_docker_bin(docker_state),
        daemon_timeout=FAKE_DOCKER_DAEMON_TIMEOUT, env=_SUBJECT_ENV,
        trigger_decide=_fixed_decide(fail_at=3), trigger_socket_dir=trigger_socket_dir,
    )
    handle = backend.prepare("a-lc-bypass-red-000000003")
    assert isinstance(handle, d._Handle)
    script = (
        "import json, socket\n"
        f"path = {d.TRIGGER_SOCKET_PATH!r}\n"
        "for i in range(1, 6):\n"
        "    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)\n"
        "    s.settimeout(5.0)\n"
        "    s.connect(path)\n"
        "    s.sendall(json.dumps({'op': 'disruption_check', 'seq': i}).encode() + b'\\n')\n"
        "    s.shutdown(socket.SHUT_WR)\n"
        "    s.recv(65536)\n"
        "    s.close()\n"
    )
    # The fake CLI's `execute()` runs the subject as a real local
    # subprocess, which does not share the real Docker mount namespace -
    # TRIGGER_SOCKET_PATH is a container-internal path that only a REAL
    # bind-mounted container would resolve. Reaching the same host-side
    # socket here, from a plain subprocess, requires connecting at its
    # real host path instead, which the live-Docker test (not this one)
    # is the one place a real mount makes those two paths the same thing.
    host_path = d.trigger_socket_host_path_for(trigger_socket_dir, handle.name)
    script = script.replace(repr(d.TRIGGER_SOCKET_PATH), repr(str(host_path)))
    result = backend.execute(handle, [_PYTHON, "-c", script], Limits(timeout=10))
    assert result.reason == "exited" and result.exit_code == 0, result.error
    assert backend.confirm_stopped(handle) is Confirmation.CONFIRMED
    log = backend.trigger_log(handle)
    backend.destroy(handle)
    assert log is not None and len(log) == 5
    trusted = TrustedLog.witnessed(log)
    assert trusted.status == "witnessed"
    assert [d_.result["decision"] for d_ in trusted.decisions] == ["pass", "pass", "fail", "pass", "pass"]
