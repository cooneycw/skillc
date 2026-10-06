"""The live-Docker build conformance test for #183 PR B2's helper
install - proves the trial image actually builds with `skillc-disrupt-
tool` present, executable, and reachable at its installed path, against
a REAL `docker build`/`docker run`, not only `check_helpers.py`'s no-daemon
text check.

SKIPPED, NOT FAILED, WHEN NO DOCKER DAEMON IS AVAILABLE - named by reason,
never a silent no-op. Real-daemon execution of the trial image build is
owed to the docker-ci agent (#315); this file is written and reviewed
without ever running it (no `docker` binary in the container these
commits were written in, confirmed and reported, matching #183's own
live-channel test's documented position). `check_helpers.py`'s no-daemon
text check runs unconditionally in the regular gate step and is NOT
superseded by this file - this is the one place that proves the TEXT
check's claim is also true of a real build, which the text check
structurally cannot see.

Built under a DISTINCT tag, never `:latest` - retagging `:latest` is a
decision for the repo's own normal build path (`make session-image`'s own
convention for the Kyle session image; this project has no equivalent
`make` target yet for the trial image, tracked separately), not something
a test should do as a side effect.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

import pytest

from skillc.docker_backend import probe_daemon

DOCKERFILE_DIR = Path(__file__).resolve().parent.parent / "docker" / "trial"
TEST_TAG = f"skillc-trial-test:b2-helper-check-{int(time.time())}"

# codex:code_review finding: `shutil.which("docker")` alone proves only
# that the CLI binary exists, not that a daemon answers it - on a host
# with the client installed but no reachable daemon, the old skip
# condition let the build fixture run, fail, and report an environmental
# problem as an image-build failure. `probe_daemon()` (the same no-
# daemon-tolerant probe `DockerBackend` itself uses) is called ONLY when
# the binary exists, so a missing binary is still reported by its own
# distinct message rather than probe_daemon's generic unreachable one.
_DOCKER_BIN_PRESENT = shutil.which("docker") is not None
pytestmark = pytest.mark.skipif(
    not _DOCKER_BIN_PRESENT or probe_daemon(["docker"]) is None,
    reason="no reachable Docker daemon in this environment (binary "
           + ("present" if _DOCKER_BIN_PRESENT else "absent")
           + ") - this test needs a real daemon to build the trial image; "
             "real-daemon execution is owed to the docker-ci agent (#315)",
)


@pytest.fixture
def built_image():
    build = subprocess.run(
        ["docker", "build", "-t", TEST_TAG, str(DOCKERFILE_DIR)],
        capture_output=True, text=True, timeout=600, check=False,
    )
    assert build.returncode == 0, f"image build failed:\n{build.stdout}\n{build.stderr}"
    try:
        yield TEST_TAG
    finally:
        subprocess.run(["docker", "rmi", "-f", TEST_TAG], capture_output=True, check=False)


def test_skillc_disrupt_tool_is_installed_executable_and_runs(built_image: str) -> None:
    # Present and executable (mode bits, not merely "a file exists").
    stat_result = subprocess.run(
        ["docker", "run", "--rm", built_image, "sh", "-c", "test -x /usr/local/bin/skillc-disrupt-tool && echo OK"],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert stat_result.returncode == 0 and "OK" in stat_result.stdout, stat_result.stderr

    # Actually runs as the `candidate` user the image's own USER directive
    # switches to - not merely present under a uid it never runs as.
    whoami = subprocess.run(
        ["docker", "run", "--rm", built_image, "whoami"],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert whoami.stdout.strip() == "candidate", whoami.stderr

    # Runs end to end (no channel reachable in this bare `docker run`, so
    # it must report the infrastructure-error bucket, never crash with an
    # import error or a missing-interpreter failure - the two ways a
    # script baked into the WRONG image state could fail silently
    # differently from how it fails when genuinely unreachable).
    run_result = subprocess.run(
        ["docker", "run", "--rm", built_image, "skillc-disrupt-tool"],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert run_result.returncode == 2, run_result.stderr
    assert "channel error" in run_result.stderr
