"""The live-Docker conformance test for #183 (acceptance item 3's live
half): proves the controller-owned decide-and-reply channel works against
a REAL `docker` daemon, not only the fake CLI every other test in this
module family uses. Everything else in `test_decide_reply_channel.py` and
`test_docker_backend.py` proves the channel's own logic and the composed
argv; this file is the one place that proves the actual kernel-level claim
underneath both: a host-owned Unix socket, bind-mounted into a REAL
container, is reachable from a REAL process inside that container at the
fixed in-container path, correctly identity-scoped, with correctly
round-tripped decisions.

NOT A SCOPE CLAIM: this file proves the CHANNEL works against a real
daemon. It does not show L5's `qualify.py` consumes this channel's output
as `trusted_observation`, or that the old advisory path (`disruption_
trigger.py`) no longer feeds grading - that wiring is owed to a later PR
(tracked as PR C's own remaining acceptance-item-3 work; the fixture
rewiring that makes a real subject call through this channel at all is
PR B's). This file's claim is narrower and already real: the mechanism
works, end to end, against a real daemon.

SKIPPED, NOT FAILED, WHEN NO DOCKER DAEMON IS AVAILABLE - named by reason,
never a silent pass. This was written and reviewed without ever running it
against a real daemon (no `docker` binary in the container these commits
were written in, confirmed and reported upstream); it is correct by
inspection against the same `ExecutionBackend` contract `test_docker_
backend.py`'s own fake-CLI tests already exercise, but "compiles against
the contract" is not "runs against a real daemon," and this docstring says
so rather than implying otherwise.

NOT A BLIND INSTRUMENT: "the module did not exist before #183" is not a red
case - it would be red for ANY new test file, regardless of whether this
one actually discriminates a working channel from a broken one (orchestrator
review of an earlier draft, PR #298 - correctly rejected). Instead, THREE
properties are each deliberately breakable, one at a time, inside this one
file, on the SAME commit, selectable without any checkout:

    SKILLC_LIVE_TEST_BREAK=none            (default) everything correct - green
    SKILLC_LIVE_TEST_BREAK=omit-mount       no --mount at all - connectivity must fail
    SKILLC_LIVE_TEST_BREAK=wrong-uid        container runs as uid 0, not CANDIDATE_UID - the identity check must fail
    SKILLC_LIVE_TEST_BREAK=flip-decision    decide() inverts pass/fail - the decision-content check must fail

ONE COMMAND, FOUR RUNS, ALL ON THIS COMMIT - no checkout needed, because the
instrument's own discriminating power is what is being proven, not merely
that the file is new:

    for mode in none omit-mount wrong-uid flip-decision; do
      echo "=== $mode ==="
      SKILLC_LIVE_TEST_IMAGE=python:3.12-slim SKILLC_LIVE_TEST_BREAK=$mode \\
          uv run pytest tests/test_decide_reply_channel_live.py -v
    done

Expected output, on a host with a reachable docker daemon pulling
`python:3.12-slim` once:

    none:            1 passed
    omit-mount:      1 xfailed (strict) - connectivity assertion raised first
    wrong-uid:       1 xfailed (strict) - identity assertion raised
    flip-decision:   1 xfailed (strict) - decision-content assertion raised

`strict=True` is passed explicitly on this file's own `xfail` mark below
(`pyproject.toml`'s `[tool.pytest.ini_options]` sets no repo-wide
`xfail_strict`, so this does not rely on that) - it turns an UNEXPECTED
pass into a hard failure, so if any of the
three broken modes ever stopped actually breaking anything (the mount
silently worked anyway, say), that run reports `XPASS` as a failure, not a
quiet green. That is what makes this an instrument with a committed
negative control, not three assertions hoping to be exercised.

`SKILLC_LIVE_TEST_IMAGE` defaults to `python:3.12-slim` - small, widely
cached, and it ships a working `python3` for the subject script this file
runs. It is NOT the pinned trial image (#78's own image is a different,
unrelated concern) - this file tests the channel mechanism itself,
decoupled from PR B's proxy-in-image work, exactly as the design doc's own
landing order keeps them.
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

LIVE_TEST_IMAGE = os.environ.get("SKILLC_LIVE_TEST_IMAGE", "python:3.12-slim")
BREAK_MODE = os.environ.get("SKILLC_LIVE_TEST_BREAK", "none")
_VALID_BREAK_MODES = ("none", "omit-mount", "wrong-uid", "flip-decision")

pytestmark = pytest.mark.skipif(
    shutil.which("docker") is None,
    reason="no docker binary in this environment - this test needs a real Docker daemon; "
           "see this module's own docstring for the recorded command that exercises all four modes",
)

if BREAK_MODE not in _VALID_BREAK_MODES:
    raise RuntimeError(f"SKILLC_LIVE_TEST_BREAK={BREAK_MODE!r} must be one of {_VALID_BREAK_MODES}")


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


def _decide(request: Mapping[str, object]) -> Mapping[str, object]:
    """The intended mapping: `fail` exactly at seq 3. `flip-decision`
    inverts this - see `_expected_decisions`."""
    fail = request.get("seq") == 3
    if BREAK_MODE == "flip-decision":
        fail = not fail
    return {"decision": "fail" if fail else "pass"}


def _expected_decisions() -> list[str]:
    """What a CORRECT channel reports for seq 1..5, regardless of
    `BREAK_MODE` - this is the fixed oracle `flip-decision` is checked
    against; it does not itself flip, or the mode would never be caught."""
    return ["pass", "pass", "fail", "pass", "pass"]


@pytest.fixture
def live_backend(monkeypatch: pytest.MonkeyPatch) -> d.DockerBackend:
    if not _image_available(LIVE_TEST_IMAGE):
        pytest.skip(f"image {LIVE_TEST_IMAGE!r} is not available locally and could not be pulled")
    if BREAK_MODE == "wrong-uid":
        # The one property this mode breaks: the container's identity.
        # Everything else about the backend is unchanged, so a failure
        # anywhere else in the round trip would mean this mode broke more
        # than it claims to.
        monkeypatch.setattr(d, "_container_user", lambda: "0:0")
    base = Path(tempfile.mkdtemp(prefix="sk-live-base-"))
    return d.DockerBackend(
        image=LIVE_TEST_IMAGE, base_dir=base, network="none",
        trigger_decide=None if BREAK_MODE == "omit-mount" else _decide,
        trigger_socket_dir=Path(tempfile.mkdtemp(prefix="sk-live-trig-")),
    )


def _subject_script() -> str:
    return (
        "import json, os, socket\n"
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
        "print(json.dumps({'uid': os.getuid(), 'decisions': decisions}))\n"
    )


@pytest.mark.xfail(
    condition=BREAK_MODE != "none", strict=True, reason=f"SKILLC_LIVE_TEST_BREAK={BREAK_MODE} deliberately breaks one property",
)
def test_the_channel_round_trips_correctly_against_a_real_daemon(live_backend: d.DockerBackend) -> None:
    """One test, three independently-breakable properties, documented
    here so a failure under a given `SKILLC_LIVE_TEST_BREAK` is legible
    without reading the fixture:

    - `omit-mount`: no `--mount` reaches the composed argv at all (the
      backend is constructed with `trigger_decide=None`). The subject's
      own `connect()` inside the container fails (nothing is mounted at
      `TRIGGER_SOCKET_PATH`), so the script raises and `execute()` reports
      a nonzero exit - `result.exit_code == 0` is the assertion that
      fails, before anything about uid or decisions is even reached.
    - `wrong-uid`: `_container_user()` is monkeypatched to `"0:0"` - the
      container runs as root, not `CANDIDATE_UID`. Connectivity and
      decisions are UNAFFECTED (the socket is mode `0o666`, open to any
      uid) - only `reported["uid"] == d.CANDIDATE_UID` fails.
    - `flip-decision`: `_decide()` inverts the intended pass/fail mapping.
      Connectivity and identity are unaffected - only `reported["decisions"]
      == _expected_decisions()` fails, against the FIXED oracle in
      `_expected_decisions()`, which never flips.

    `none` (the default): all three hold, and the test passes outright."""
    handle = live_backend.prepare("a-live-conformance-000000001")
    assert isinstance(handle, d._Handle)
    if BREAK_MODE != "omit-mount":
        assert handle.trigger_channel is not None
    try:
        result = live_backend.execute(handle, ["python3", "-c", _subject_script()], Limits(timeout=15))
        assert result.reason == "exited", result.error
        assert result.exit_code == 0, result.error
        assert live_backend.confirm_stopped(handle) is Confirmation.CONFIRMED
        export_dir = Path(tempfile.mkdtemp(prefix="sk-live-export-"))
        live_backend.export(handle, export_dir)
        log = live_backend.trigger_log(handle)
    finally:
        live_backend.destroy(handle)
    # The subject's own stdout is captured to the workspace as
    # `observations`, not returned inline (`ExecutionBackend.execute()`'s
    # own documented convention).
    reported = json.loads((export_dir / "observations").read_text(encoding="utf-8").strip().splitlines()[-1])
    assert reported["uid"] == d.CANDIDATE_UID
    assert reported["decisions"] == _expected_decisions()
    assert log is not None
    assert [entry.result["decision"] for entry in log] == _expected_decisions()
