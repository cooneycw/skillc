"""Real-daemon proof for #414: the real-Docker runner's cleanup leaves a
`build.py` image alone, and still removes the runner's own leftovers.

The runner used to end every run with a host-wide `docker image prune -f`.
`build.py` built its campaign image untagged and receipts named it only by
ID, so the first runner run after a build deleted the image from under every
receipt (#375 refused 42/42 rows). Two changes, proved here against a real
daemon: `build.py` tags its output, and the runner's cleanup removes only
dangling skillc images and stopped skillc containers created during its own
run (`ci/real-docker/cleanup-lib.sh`).

The no-daemon contract tests are `tests/test_real_docker_cleanup.py` (the
cleanup's scoping) and `tests/test_profile_trial_image.py` (the tag, and
`release_build` never removing a pre-existing tag).
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

import pytest

from skillc.docker_backend import probe_daemon

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "ci" / "real-docker" / "cleanup-lib.sh"
CONTROL_BASE = "python:3.12-slim"  # already on the runner (its preflight image)

_DOCKER_BIN_PRESENT = shutil.which("docker") is not None
#: The snapshot rule ("not there before means this run's") is sound only while
#: nothing else creates skillc artifacts in the window. `run-real-docker` holds
#: run.lock and says so with this variable; on any other daemon - a shared dev
#: host's ordinary pytest - these tests could remove a neighbour's artifacts,
#: so they run only under the runner (#414 review). The real-Docker floor
#: turns an all-skipped file on the runner into FAILURE, so a runner that stops
#: setting it is loud, not silent.
_RUN_LOCK_HELD = os.environ.get("SKILLC_REAL_DOCKER_RUN_LOCK_HELD") == "1"
pytestmark = [
    pytest.mark.real_docker,
    pytest.mark.skipif(
        not _RUN_LOCK_HELD,
        reason="runs only under run-real-docker, which holds run.lock "
               "(SKILLC_REAL_DOCKER_RUN_LOCK_HELD=1): its snapshot-based cleanup "
               "would otherwise risk a neighbour's artifacts on a shared daemon",
    ),
    pytest.mark.skipif(
        not _DOCKER_BIN_PRESENT or probe_daemon(["docker"]) is None,
        reason="no reachable Docker daemon in this environment (binary "
               + ("present" if _DOCKER_BIN_PRESENT else "absent")
               + ") - real-daemon execution is owed to the real-Docker runner (#315)",
    ),
]


def _builder() -> Any:
    spec = importlib.util.spec_from_file_location("profile_runtime_builder_414", ROOT / "docker/profile-trial/build.py")
    assert spec is not None and spec.loader is not None
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    return builder


def _cleanup(function: str, snapshot: Path) -> None:
    result = subprocess.run(
        ["bash", "-c", f'source "$1"; {function} "$2"', "_", str(LIB), str(snapshot)],
        capture_output=True, text=True, timeout=300, check=False,
    )
    assert result.returncode == 0, result.stderr


def _resolves(reference: str) -> bool:
    return subprocess.run(["docker", "image", "inspect", reference], capture_output=True, check=False).returncode == 0


@pytest.mark.timeout(1800)  # a real build.py build, like the closure live test
def test_a_build_py_image_survives_the_runner_cleanup(tmp_path: Path) -> None:
    """#414's red case. On the pre-fix runner this image was untagged and the
    cleanup's host-wide prune deleted it, so the receipt's ID no longer
    resolved. Now it is tagged, and the cleanup touches only its own run's
    dangling images."""
    builder = _builder()
    snapshot = tmp_path / "snapshot"
    _cleanup("snapshot_runner_artifacts", snapshot)
    before = builder.image_inventory()
    with tempfile.TemporaryDirectory(prefix="sk-414-receipt-") as temp:
        receipt = builder.build_image(ROOT, Path(temp) / "receipt.json")
    tag = builder.image_tag(receipt)
    try:
        _cleanup("remove_runner_artifacts", snapshot)
        assert _resolves(receipt["image_id"]), "the cleanup removed the receipt's image"
        assert _resolves(tag), "the cleanup removed the build's tag"
    finally:
        builder.release_build(receipt, before)
    # Releasing undoes only what this build added: a tag that existed before
    # it still resolves afterwards, on the image it named then.
    if tag in before["tags"]:
        assert _resolves(tag)
        inspected = subprocess.run(["docker", "image", "inspect", "--format", "{{.Id}}", tag],
                                   capture_output=True, text=True, check=True)
        assert inspected.stdout.strip() == before["tags"][tag]


@pytest.mark.timeout(600)
def test_the_runner_cleanup_still_removes_its_own_dangling_image(tmp_path: Path) -> None:
    """Control: scoping must not turn into "removes nothing". A skillc-labelled
    untagged image made after the snapshot is this run's, and goes. The uuid
    label makes its ID new, never one already on the host."""
    snapshot = tmp_path / "snapshot"
    _cleanup("snapshot_runner_artifacts", snapshot)
    marker = uuid.uuid4().hex
    built = subprocess.run(
        ["docker", "build", "-q", "--label", "org.skillc.image=cleanup-control-414",
         "--label", f"skillc.cleanup-control={marker}", "-"],
        input=f"FROM {CONTROL_BASE}\n", capture_output=True, text=True, timeout=300, check=True,
    )
    image_id = built.stdout.strip()
    try:
        assert _resolves(image_id)
        dangling = subprocess.run(
            ["docker", "images", "-q", "--no-trunc", "--filter", "dangling=true",
             "--filter", f"label=skillc.cleanup-control={marker}"],
            capture_output=True, text=True, check=True,
        ).stdout.split()
        assert dangling == [image_id], "the control image is not the dangling, labelled kind the cleanup targets"
        _cleanup("remove_runner_artifacts", snapshot)
        assert not _resolves(image_id), "the cleanup left this run's own dangling skillc image"
    finally:
        subprocess.run(["docker", "image", "rm", image_id], capture_output=True, check=False)
