"""The live-Docker conformance test for #338's cwd-confinement fix -
`exec_in_attempt()`'s own docstring names the gap this closes: a `cwd`
resolved and root-checked by `GateWitness._confine_requested_cwd()` is
reused, unchanged, by a LATER, SEPARATE `docker exec`, with real
wall-clock time between the two - long enough for the subject, who owns
the whole workspace tree, to swap an ancestor of the resolved path for a
symlink pointing outside the workspace root before that later exec runs.

The fake CLI (`tests/test_docker_backend.py`) already proves the fix's
shell mechanics with a REAL `sh` subprocess (dash, matching the image
below) - the `exec`-builtin special-case, the compound-block fd open,
the `/proc/self/fd/N` magic-symlink read-and-chdir, the auto-close. What
it CANNOT prove is whether that same mechanism behaves identically
inside an ACTUAL container's own mount and pid namespaces (a real,
separate `/proc` mount) rather than a bare host subprocess, and whether
a REAL `docker exec -w` really does follow a swapped symlink the same
way the fake's Python-level `cwd=` simulation did. Both are exercised
here, against a real daemon.

ONE PROPERTY: a cwd resolved once, then swapped for a symlink pointing
outside `workspace_root` before the exec that uses it, must be refused -
never silently followed. `BREAK_MODE` selects whether `confine_root` is
passed for that exec, same shape as `test_gate_witness_live.py`'s own
`SKILLC_GATE_WITNESS_LIVE_BREAK`:

    none                   (default) `confine_root` IS passed for the
                            swapped-cwd exec - the property holds: refused,
                            `reason="launch-failed"`, the sentinel present.
    confine-root-omitted   `confine_root` is NOT passed for the identical
                            swapped-cwd exec - the same property must now
                            FAIL to hold: the real daemon's `-w` follows the
                            swap, landing the gate's cwd outside
                            `workspace_root`, exactly as #338 describes.
                            Proves the vulnerability is real on a genuine
                            daemon, not only in the fake CLI's simulation.

`raises=_PropertyHeld` (same reasoning as #336/#341's other live files):
`AssertionError` alone would also be raised by an unrelated infra/setup
failure (image pull, daemon flake), which must surface as an ordinary
hard FAILURE, never be mistaken for "the break worked".

A happy-path correctness check (an UNSWAPPED, legitimately-resolved cwd
under `confine_root` actually lands the gate there) runs first,
unconditionally, in every mode - this is what proves the `/proc/self/
fd/N` mechanism works for real inside a container's own namespaces, not
only on the bare host `tests/test_docker_backend.py`'s fake CLI runs
against.

Every container this file starts is removed in a `finally`.

LEAK SAFETY: no host path or raw container name is ever printed into an
assertion message; every assertion compares in-memory strings already
known to the test (the expected resolved paths it itself constructed).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from skillc import docker_backend as d
from skillc.backend import Limits

LIVE_TEST_IMAGE = os.environ.get("SKILLC_LIVE_TEST_IMAGE", "python:3.12-slim")
BREAK_MODE = os.environ.get("SKILLC_CWD_CONFINEMENT_LIVE_BREAK", "none")
_VALID_BREAK_MODES = ("none", "confine-root-omitted")

if BREAK_MODE not in _VALID_BREAK_MODES:
    raise RuntimeError(f"SKILLC_CWD_CONFINEMENT_LIVE_BREAK={BREAK_MODE!r} must be one of {_VALID_BREAK_MODES}")


class _PropertyHeld(Exception):
    """Raised when the swap-refusal property held under a mode that is
    supposed to violate it (`confine-root-omitted`) - the only exception
    type the `xfail` marker below matches, so an unrelated infra/setup
    failure stays a plain `AssertionError` and reports as an ordinary
    hard FAILURE rather than being read as "the break worked"."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise _PropertyHeld(message)


_DOCKER_BIN_PRESENT = shutil.which("docker") is not None
pytestmark = [
    pytest.mark.real_docker,
    pytest.mark.skipif(
        not _DOCKER_BIN_PRESENT or d.probe_daemon(["docker"]) is None,
        reason="no reachable Docker daemon in this environment (binary "
               + ("present" if _DOCKER_BIN_PRESENT else "absent")
               + ") - this test needs a real daemon for exec_in_attempt()'s own owed "
                 "cwd-confinement evidence (#338); real-daemon execution is owed to "
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


def _exec_setup(backend: d.DockerBackend, handle: d._Handle, shell_command: str) -> None:
    """Direct `docker exec` for test SETUP only - creating/swapping real
    directories inside the live container - never through `exec_in_
    attempt()` itself, which is the thing under test."""
    proc = subprocess.run(
        [*backend.docker_bin, "exec", "--", handle.name, "sh", "-c", shell_command],
        capture_output=True, timeout=backend.daemon_timeout, check=False,
    )
    assert proc.returncode == 0, f"test setup exec failed (exit {proc.returncode})"


@pytest.mark.xfail(
    condition=BREAK_MODE != "none", strict=True, raises=_PropertyHeld,
    reason=f"SKILLC_CWD_CONFINEMENT_LIVE_BREAK={BREAK_MODE} deliberately omits confine_root",
)
def test_a_swapped_cwd_is_refused_against_a_real_daemon() -> None:
    if not _image_available(LIVE_TEST_IMAGE):
        pytest.skip(f"image {LIVE_TEST_IMAGE!r} is not available locally and could not be pulled")

    base = Path(tempfile.mkdtemp(prefix="sk-cwd-live-base-"))
    backend = d.DockerBackend(image=LIVE_TEST_IMAGE, base_dir=base, network="none")
    handle = backend.prepare("a-cwd-live-confinement-0000001")
    assert isinstance(handle, d._Handle)
    backend.install(handle, {})
    try:
        workspace_root = d.CONTAINER_WORKSPACE
        sub = f"{workspace_root}/trial/sub"
        outside = f"{workspace_root}/.outside-root"  # same filesystem, different subtree - still outside workspace_root
        _exec_setup(backend, handle, f"mkdir -p {sub} {outside}")

        # Happy path, UNCONDITIONAL in every mode: a legitimately-resolved,
        # never-swapped cwd under confine_root must land the gate there for
        # real - proof the fd/proc-magic-symlink mechanism works inside an
        # actual container's own namespaces, not only on the bare host.
        resolved_sub = backend.resolve_realpath_in_attempt(handle, sub)
        assert resolved_sub == sub
        happy = backend.exec_in_attempt(
            handle, ["sh", "-c", "readlink -f /proc/self/cwd"], Limits(timeout=5.0),
            cwd=resolved_sub, confine_root=workspace_root,
        )
        assert happy.reason == "exited"
        assert happy.exit_code == 0
        with tempfile.TemporaryDirectory() as tmp:
            backend.export(handle, Path(tmp))
            assert (Path(tmp) / "observations").read_text().strip() == sub

        # The swap: exactly what an earlier, separate `resolve_realpath_in_
        # attempt()` call could not have seen coming, and could not
        # re-observe once it already returned.
        _exec_setup(backend, handle, f"rm -rf {sub} && ln -s {outside} {sub}")

        # `confine_root=None` behaves identically to omitting it entirely
        # (`exec_in_attempt`'s own `confining` check is `cwd is not None
        # and confine_root is not None`), so this is the full break for
        # `confine-root-omitted` with no separate code path to maintain.
        swapped = backend.exec_in_attempt(
            handle, ["sh", "-c", "echo should-not-run-outside-root"], Limits(timeout=5.0),
            cwd=sub, confine_root=None if BREAK_MODE == "confine-root-omitted" else workspace_root,
        )
        # UNCONDITIONAL across both modes - the real property, never a
        # pre-approved different expected value for the break mode.
        _require(
            swapped.reason == "launch-failed" and d.CWD_CONFINEMENT_REFUSED_SENTINEL in (swapped.error or ""),
            "a cwd swapped to outside workspace_root between resolve and exec "
            "must be refused, not silently followed, on a real daemon",
        )
    finally:
        backend.destroy(handle)
