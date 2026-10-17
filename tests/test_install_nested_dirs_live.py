"""The live-Docker regression control for #393: every directory
`DockerBackend.install()` creates under its root must belong to the
candidate, so the candidate can CREATE files there - not merely edit the
ones that were installed.

Before the fix, a bytes-backed surface entry was delivered as a one-file
tar stream with no directory entries, so `docker cp - NAME:/work`
created a missing parent such as `tests/` itself, owned by root
(`root:root 0755`). The installed file was candidate-owned; its parent was
not, and `touch /work/tests/new.py` as the candidate failed with
`Permission denied` (#375's smoke run: the reference candidate for
`gate-stops-early` could not add `tests/test_windows_regression.py`). A
path-backed entry under a nested key (`tools/kit`) had the same hole one
level up: its own tree was candidate-owned, `tools/` was not.

The fake CLI (`tests/test_docker_backend.py`) proves the mechanism - one
candidate-identity `mkdir -p` before any copy - but cannot prove what a
real daemon's `docker cp` does with a missing parent, which is the whole
defect. That is only observable here.

TWO PROPERTIES:

1. Checked as the candidate itself (`docker exec -u CANDIDATE_UID`),
   never as root: after installing nested bytes and path entries, the
   candidate can create a new file in each installed parent directory.
   FAILS on the pre-fix code with `Permission denied` (verified on Docker
   29.8.2 when #393 was fixed).
2. A directory that ALREADY existed keeps its owner and mode. A real
   daemon rewrites an existing directory's metadata when a tar directory
   entry lands on it, so a fix that sent an entry for every ancestor would
   hand the candidate a root-owned 0700 directory. FAILS when
   `_absent_parents` is made to report every ancestor absent (verified when
   #393 was fixed).

The default image's `/work` is root-owned, unlike the trial image's: the
fix must work whoever owns the install root, and this is where that shows.

Every container this file starts is removed in a `finally`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
from conftest import LIVE_DOCKER_DAEMON_TIMEOUT

from skillc import docker_backend as d

LIVE_TEST_IMAGE = os.environ.get("SKILLC_LIVE_TEST_IMAGE", "python:3.12-slim")

_DOCKER_BIN_PRESENT = shutil.which("docker") is not None
pytestmark = [
    pytest.mark.real_docker,
    pytest.mark.skipif(
        not _DOCKER_BIN_PRESENT or d.probe_daemon(["docker"]) is None,
        reason="no reachable Docker daemon in this environment (binary "
               + ("present" if _DOCKER_BIN_PRESENT else "absent")
               + ") - this test needs a real daemon for install()'s own owed "
                 "nested-directory ownership evidence (#393); real-daemon execution is owed to "
                 "the real-Docker runner (#315)",
    ),
]


def _image_available(image: str) -> bool:
    """Bounded, best-effort - matches every sibling live file's own helper."""
    inspect = subprocess.run(
        ["docker", "image", "inspect", image], capture_output=True, timeout=10, check=False,
    )
    if inspect.returncode == 0:
        return True
    pull = subprocess.run(["docker", "pull", image], capture_output=True, timeout=120, check=False)
    return pull.returncode == 0


def _as_candidate(backend: d.DockerBackend, handle: d._Handle, shell_command: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [*backend.docker_bin, "exec", "-u", f"{d.CANDIDATE_UID}:{d.CANDIDATE_GID}", "--", handle.name,
         "sh", "-c", shell_command],
        capture_output=True, timeout=backend.daemon_timeout, check=False,
    )


def test_the_candidate_can_create_files_in_installed_nested_directories() -> None:
    if not _image_available(LIVE_TEST_IMAGE):
        pytest.skip(f"image {LIVE_TEST_IMAGE!r} is not available locally and could not be pulled")

    base = Path(tempfile.mkdtemp(prefix="sk-nested-live-base-"))
    backend = d.DockerBackend(image=LIVE_TEST_IMAGE, base_dir=base, network="none",
                              daemon_timeout=LIVE_DOCKER_DAEMON_TIMEOUT)
    handle = backend.prepare("a-nested-dirs-live-0000001")
    assert isinstance(handle, d._Handle)
    try:
        preexisting = f"{d.CONTAINER_WORKSPACE}/pre"
        made = subprocess.run(
            [*backend.docker_bin, "exec", "-u", "0", "--", handle.name, "sh", "-c",
             f"mkdir -m 0700 {preexisting} && chown 0:0 {preexisting}"],
            capture_output=True, timeout=backend.daemon_timeout, check=False,
        )
        assert made.returncode == 0, "test setup: could not create the pre-existing root directory"
        with tempfile.TemporaryDirectory() as surface:
            (Path(surface) / "helper.sh").write_text("true\n")
            readiness = backend.install(handle, {
                "tests/test_windows.py": b"def test_x():\n    pass\n",
                "ci/deep/gate.sh": b"true\n",
                "tools/kit": Path(surface),
                "pre/owned-by-root-dir.txt": b"x",
            })
        assert readiness["entries"] == {
            "tests/test_windows.py": "installed", "ci/deep/gate.sh": "installed", "tools/kit": "installed",
            "pre/owned-by-root-dir.txt": "installed",
        }
        kept = subprocess.run(
            [*backend.docker_bin, "exec", "-u", "0", "--", handle.name, "stat", "-c", "%u:%g %a", preexisting],
            capture_output=True, timeout=backend.daemon_timeout, check=False,
        )
        assert kept.stdout.decode().strip() == "0:0 700", (
            f"install rewrote a pre-existing directory's owner/mode: {kept.stdout.decode().strip()!r}"
        )
        for directory in ("tests", "ci", "ci/deep", "tools", "tools/kit"):
            path = f"{d.CONTAINER_WORKSPACE}/{directory}"
            created = _as_candidate(backend, handle, f"touch {path}/candidate-new && test -f {path}/candidate-new")
            assert created.returncode == 0, (
                f"the candidate could not create a file in installed directory {directory!r}: "
                f"{created.stderr.decode('utf-8', errors='replace').strip()}"
            )
            owner = _as_candidate(backend, handle, f"stat -c %u:%g {path}")
            assert owner.stdout.decode().strip() == f"{d.CANDIDATE_UID}:{d.CANDIDATE_GID}", directory
    finally:
        backend.destroy(handle)
