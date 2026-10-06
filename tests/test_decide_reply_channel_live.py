"""The live-Docker conformance test for #183 (acceptance item 3's live
half): proves the controller-owned decide-and-reply channel works against
a REAL `docker` daemon, not only the fake CLI every other test in this
module family uses. Everything else in `test_decide_reply_channel.py` and
`test_docker_backend.py` proves the channel's own logic and the composed
argv; this file is the one place that proves the actual kernel-level claim
underneath both: a host-owned Unix socket, bind-mounted into a REAL
container, is reachable from a REAL process inside that container at the
fixed in-container path, and nothing else on the host can reach it.

SKIPPED, NOT FAILED, WHEN NO DOCKER DAEMON IS AVAILABLE - named by reason,
never a silent pass. This was written and reviewed without ever running it
against a real daemon (no `docker` binary in the container these commits
were written in, confirmed and reported upstream); it is correct by
inspection against the same `ExecutionBackend` contract `test_docker_
backend.py`'s own fake-CLI tests already exercise, but "compiles against
the contract" is not "runs against a real daemon," and this docstring says
so rather than implying otherwise.

ONE COMMAND, ONE RECORDED COMMIT, BOTH THE RED AND THE GREEN RUN:

    git checkout 540d6a3   # the commit immediately before #183's first PR A commit
    SKILLC_LIVE_TEST_IMAGE=python:3.12-slim \\
        uv run pytest tests/test_decide_reply_channel_live.py -v
    # -> collection error: skillc.decide_reply_channel does not exist yet.
    #    That IS the red for this file's own claim (the mechanism exists
    #    and works), not a red in the sense test_disruption_channel_
    #    bypass_red_case.py's committed red case already covers (#183's
    #    acceptance item 2) - see that file for the red/green pair that
    #    does not require a daemon or a checkout at all.
    git checkout <this branch's head>
    SKILLC_LIVE_TEST_IMAGE=python:3.12-slim \\
        uv run pytest tests/test_decide_reply_channel_live.py -v
    # -> green, on a host with a reachable docker daemon.

`SKILLC_LIVE_TEST_IMAGE` defaults to `python:3.12-slim` - small, widely
cached, and it ships a working `python3` for the subject script this file
runs. It is NOT the pinned trial image (`kyle-session`/#78's own image is a
different, unrelated concern) - this file tests the channel mechanism
itself, decoupled from PR B's proxy-in-image work, exactly as the design
doc's own landing order keeps them.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Mapping
from pathlib import Path

import pytest

from skillc import docker_backend as d
from skillc.backend import Confirmation, Limits
from skillc.decide_reply_channel import TrustedLog

LIVE_TEST_IMAGE = os.environ.get("SKILLC_LIVE_TEST_IMAGE", "python:3.12-slim")

pytestmark = pytest.mark.skipif(
    shutil.which("docker") is None,
    reason="no docker binary in this environment - this test needs a real Docker daemon; "
           "see this module's own docstring for the recorded command that produces the red and green runs",
)


def _image_available(image: str) -> bool:
    """Bounded, best-effort: tries `docker image inspect` first (never
    pulls implicitly, matching `DockerBackend.prepare()`'s own refusal to
    let `docker run -d` pull mid-trial), then one bounded explicit pull if
    that fails. Returns `False` - never raises - on anything short of the
    image actually being present afterward, so the caller can skip with a
    clear reason instead of failing on an environment it cannot control."""
    inspect = subprocess.run(
        ["docker", "image", "inspect", image], capture_output=True, timeout=10, check=False,
    )
    if inspect.returncode == 0:
        return True
    pull = subprocess.run(["docker", "pull", image], capture_output=True, timeout=120, check=False)
    return pull.returncode == 0


@pytest.fixture
def live_backend() -> d.DockerBackend:
    if not _image_available(LIVE_TEST_IMAGE):
        pytest.skip(f"image {LIVE_TEST_IMAGE!r} is not available locally and could not be pulled")
    base = Path(tempfile.mkdtemp(prefix="sk-live-base-"))
    return d.DockerBackend(
        image=LIVE_TEST_IMAGE, base_dir=base, network="none",
        trigger_decide=_decide, trigger_socket_dir=Path(tempfile.mkdtemp(prefix="sk-live-trig-")),
    )


def _decide(request: Mapping[str, object]) -> Mapping[str, object]:
    return {"decision": "fail" if request.get("seq") == 3 else "pass"}


def test_the_bind_mounted_socket_is_reachable_from_inside_a_real_container(
    live_backend: d.DockerBackend,
) -> None:
    """The core, novel, Docker-dependent claim: a REAL container, started
    by a REAL daemon, with #183's one named mount in its composed argv,
    can `connect()` to the controller's socket at the fixed in-container
    path and get real, correctly-ordered, correctly-decided replies - not
    merely that the fake CLI's own simulated exec can."""
    handle = live_backend.prepare("a-live-conformance-000000001")
    assert isinstance(handle, d._Handle)
    assert handle.trigger_channel is not None
    try:
        script = (
            "import json, socket\n"
            f"path = {d.TRIGGER_SOCKET_PATH!r}\n"
            "decisions = []\n"
            "for i in range(1, 6):\n"
            "    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)\n"
            "    s.settimeout(5.0)\n"
            "    s.connect(path)\n"
            "    s.sendall(json.dumps({'op': 'disruption_check', 'seq': i}).encode() + b'\\n')\n"
            "    s.shutdown(socket.SHUT_WR)\n"
            "    reply = s.recv(65536)\n"
            "    s.close()\n"
            "    decisions.append(json.loads(reply.splitlines()[0])['result']['decision'])\n"
            "print(json.dumps(decisions))\n"
        )
        result = live_backend.execute(handle, ["python3", "-c", script], Limits(timeout=15))
        assert result.reason == "exited", result.error
        assert result.exit_code == 0, result.error
        assert live_backend.confirm_stopped(handle) is Confirmation.CONFIRMED
        log = live_backend.trigger_log(handle)
    finally:
        live_backend.destroy(handle)
        assert live_backend.confirm_absent(handle) is Confirmation.CONFIRMED
    assert log is not None
    assert [entry.result["decision"] for entry in log] == ["pass", "pass", "fail", "pass", "pass"]
    trusted = TrustedLog.witnessed(log)
    assert trusted.status == "witnessed"


def test_the_candidate_uid_not_the_controllers_own_uid_is_what_connects(
    live_backend: d.DockerBackend,
) -> None:
    """Design doc §2f(b)'s own reasoning only matters if it is true inside
    a REAL container: the subject runs as the fixed `CANDIDATE_UID`
    (`compose_run_argv`'s `--user`), essentially never this controller
    process's own uid, so granting the socket to "other" (not "owner") is
    what actually lets it connect. Checked directly, not merely asserted:
    the subject reports its own uid AND successfully connects, inside one
    real container."""
    handle = live_backend.prepare("a-live-conformance-000000002")
    assert isinstance(handle, d._Handle)
    try:
        script = (
            "import json, os, socket\n"
            f"path = {d.TRIGGER_SOCKET_PATH!r}\n"
            "s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)\n"
            "s.settimeout(5.0)\n"
            "s.connect(path)\n"
            "s.sendall(json.dumps({'op': 'disruption_check', 'seq': 1}).encode() + b'\\n')\n"
            "s.shutdown(socket.SHUT_WR)\n"
            "reply = s.recv(65536)\n"
            "s.close()\n"
            "print(json.dumps({'uid': os.getuid(), 'ok': json.loads(reply.splitlines()[0])['ok']}))\n"
        )
        result = live_backend.execute(handle, ["python3", "-c", script], Limits(timeout=15))
        assert result.reason == "exited", result.error
        assert result.exit_code == 0, result.error
        assert live_backend.confirm_stopped(handle) is Confirmation.CONFIRMED
        # The subject's own stdout is captured to the workspace as
        # `observations`, not returned inline (`ExecutionBackend.execute()`'s
        # own documented convention) - exported, before `destroy()`, and
        # read back, matching how every other stdout-bearing assertion in
        # this test family works.
        export_dir = Path(tempfile.mkdtemp(prefix="sk-live-export-"))
        live_backend.export(handle, export_dir)
    finally:
        live_backend.destroy(handle)
    reported = json.loads((export_dir / "observations").read_text(encoding="utf-8").strip().splitlines()[-1])
    assert reported["uid"] == d.CANDIDATE_UID
    assert reported["ok"] is True
