"""Live-Docker tool-probe conformance test for #343: proves the trial
image's declared tool dependencies (`tool-uv`, `tool-make-git-bash` in
`cpp-codex-flow-check-ea6dbfa/profile.json`) actually resolve inside a REAL
built image, against a REAL `docker build`/`docker run` - not only
`docker/trial/check_pins.py`'s or `check_interpreters.py`'s no-daemon text
checks, neither of which covers this surface (`check_interpreters.py` is
deliberately scoped to `skillc.verify.PROBE_INTERPRETER` only; there is no
`check_pins.py`-equivalent that runs a built image's binaries at all).

Tests the probe COMMANDS directly (`uv --version`, `make --version`, ...)
rather than importing or calling any skillc evaluator: skillc#334 ("installs
and verifies the profile closure, then preflights declared tools in-
container") is not merged yet, and that issue's own dependency `id` fields
(`tool-uv`, `tool-make-git-bash`) are not real binary names `shutil.which`
could resolve - confirmed by reading `evals/subjects/cpp-codex-flow-check-
ea6dbfa/profile.json` directly. Switch this file to call #334's evaluator
once it lands, rather than re-deriving the same probe commands twice.

SKIPPED, NOT FAILED, WHEN NO DOCKER DAEMON IS AVAILABLE - same convention as
`test_trial_image_build_live.py`.

ONE TEST FUNCTION PER PROPERTY, SKILLC_TRIAL_IMAGE_BREAK SELECTS THE BUILD
TARGET - same shape as `test_gate_overlay_live.py`'s own `SKILLC_GATE_SHIM_
LIVE_BREAK`: `none` builds the normal `trial` stage; `no-uv` builds the
deliberately broken `no-uv` stage (`docker/trial/Dockerfile`), where the uv
probe must fail.

`_UvPropertyHeld` is a DEDICATED, PROPERTY-SCOPED exception (issue #341's
design, adopted here from the START even though this file targets only one
property today): a future second targeted property (e.g. a pinned `make`/
`bash` version) must get its OWN subtype, so a break that fails to violate
the uv property can never be masked by an unrelated property's failure
satisfying the same `xfail`. The uv-version assertion raises
`_UvPropertyHeld`, never a bare `AssertionError`; every other probe in this
file (python3, make, bash, git presence) is a plain `assert`, which the
`xfail(raises=_UvPropertyHeld)` marker below does NOT match - so an
unrelated infra failure (a Docker flake, a probe command genuinely absent
for a reason unrelated to this break) is reported as an ordinary hard
FAILURE, never masked as "the break worked."

Built under a DISTINCT tag, never `:latest`, same convention as
`test_trial_image_build_live.py`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from skillc.docker_backend import probe_daemon

DOCKERFILE_DIR = Path(__file__).resolve().parent.parent / "docker" / "trial"
TEST_TAG = f"skillc-trial-test:343-tools-check-{int(time.time())}"

BREAK_MODE = os.environ.get("SKILLC_TRIAL_IMAGE_BREAK", "none")
_VALID_BREAK_MODES = ("none", "no-uv")
if BREAK_MODE not in _VALID_BREAK_MODES:
    raise RuntimeError(f"SKILLC_TRIAL_IMAGE_BREAK={BREAK_MODE!r} must be one of {_VALID_BREAK_MODES}")

#: `none` builds the normal, working stage; `no-uv` builds the break mode's
#: own negative control (docker/trial/Dockerfile's deliberately uv-less
#: stage) - mirrors break-lib.sh's own `trialimage:no-uv` mode exactly.
_BUILD_TARGET = "trial" if BREAK_MODE == "none" else "no-uv"

#: Pinned uv version this image installs (docker/trial/pinned-versions.json)
#: - the property under test asserts the EXACT pinned version is what `uv
#: --version` reports inside the built image, never just "some uv exists",
#: so a probe that resolved to an unrelated system uv could not pass by
#: accident.
_PINNED_UV_VERSION = "0.9.7"

# codex:code_review finding (see test_trial_image_build_live.py): a missing
# daemon must report its own distinct message, never the generic
# probe_daemon() one, so the binary check runs first and short-circuits.
_DOCKER_BIN_PRESENT = shutil.which("docker") is not None
pytestmark = [
    pytest.mark.real_docker,
    pytest.mark.skipif(
        not _DOCKER_BIN_PRESENT or probe_daemon(["docker"]) is None,
        reason="no reachable Docker daemon in this environment (binary "
               + ("present" if _DOCKER_BIN_PRESENT else "absent")
               + ") - this test needs a real daemon to build the trial image; "
                 "real-daemon execution is owed to the real-Docker runner (#315)",
    ),
]


@pytest.fixture
def built_image():
    build = subprocess.run(
        ["docker", "build", "--target", _BUILD_TARGET, "-t", TEST_TAG, str(DOCKERFILE_DIR)],
        capture_output=True, text=True, timeout=600, check=False,
    )
    assert build.returncode == 0, f"image build failed:\n{build.stdout}\n{build.stderr}"
    try:
        yield TEST_TAG
    finally:
        subprocess.run(["docker", "rmi", "-f", TEST_TAG], capture_output=True, check=False)


class _UvPropertyHeld(Exception):
    """Raised when the uv-presence/version property still held under a
    break mode that is supposed to violate it - the opposite of what
    `xfail(strict=True)` below expects. Property-scoped by name (#341's
    design): a later second targeted property gets its own dedicated
    subtype rather than sharing this one, so neither can satisfy the
    other's `xfail(raises=...)`."""


def _require_uv(condition: bool, message: str) -> None:
    """Confirmed directly, no pytest or Docker needed: `_require_uv(True,
    ...)` returns; `_require_uv(False, ...)` raises `_UvPropertyHeld`, which
    is not a subclass of `AssertionError`."""
    if not condition:
        raise _UvPropertyHeld(message)


@pytest.mark.xfail(
    condition=BREAK_MODE != "none", strict=True, raises=_UvPropertyHeld,
    reason=f"SKILLC_TRIAL_IMAGE_BREAK={BREAK_MODE} deliberately removes uv from the built image",
)
def test_uv_is_present_at_the_pinned_version(built_image: str) -> None:
    uv_version = subprocess.run(
        ["docker", "run", "--rm", built_image, "uv", "--version"],
        capture_output=True, text=True, timeout=30, check=False,
    )
    _require_uv(uv_version.returncode == 0, f"uv --version failed (exit {uv_version.returncode}): {uv_version.stderr!r}")
    _require_uv(
        _PINNED_UV_VERSION in uv_version.stdout,
        f"uv --version reported {uv_version.stdout!r}, expected the pinned {_PINNED_UV_VERSION}",
    )


def test_python3_satisfies_the_profiles_version_floor(built_image: str) -> None:
    """Plain `assert`, not the targeted property for any declared break
    mode - python3 is unaffected by `trialimage:no-uv` (it is installed on
    the shared `base` stage, before the uv/no-uv split), so an unrelated
    failure here must surface as an ordinary hard FAILURE rather than
    interact with the xfail marker above."""
    result = subprocess.run(
        ["docker", "run", "--rm", built_image, "python3", "-c",
         "import sys; print('OK' if sys.version_info >= (3, 11) else 'TOO_OLD')"],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK", f"python3 version too old: {result.stdout!r}"


@pytest.mark.parametrize("tool", ["make", "bash", "git"])
def test_declared_tool_dependency_is_present(built_image: str, tool: str) -> None:
    """`cpp-codex-flow-check-ea6dbfa/profile.json`'s own `tool-make-git-
    bash` dependency, by probe command - plain `assert`, same reasoning as
    the python3 check above: none of these three is the targeted property
    of `trialimage:no-uv`, and all three are installed on the shared `base`
    stage before the uv/no-uv split."""
    result = subprocess.run(
        ["docker", "run", "--rm", built_image, tool, "--version"],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, f"{tool} --version failed: {result.stderr!r}"
