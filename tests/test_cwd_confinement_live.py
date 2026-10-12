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

The OUTSIDE target is genuinely outside: under `/tmp` (present and
candidate-writable in every image, unlike the candidate's home, which a
plain image need not have), not anywhere beneath `workspace_root` (#338
correction: an earlier draft of this file used `/work/.outside-root`,
which is inside `/work` and so could never have been refused). The
workspace tree is installed through `backend.install()` as a host
DIRECTORY, so its directories are candidate-owned - exactly what a
subject's installed surface gives it (a bytes entry alone would leave its
parent directories root-owned, and the candidate could not swap
anything). Every setup step after that - creating the outside target,
the swap itself - is a plain `docker exec` running as the container's
own (candidate) user, never root: the subject's own power, nothing
more. Every setup step is checked and a
setup failure is a plain hard failure, never the `xfail` this file
reserves for the break mode.

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
    """Direct `docker exec` for test SETUP only - as the container's own
    candidate user, i.e. with exactly the subject's power - never through
    `exec_in_attempt()` itself, which is the thing under test. A failure is
    a hard `AssertionError`, never `_PropertyHeld`."""
    proc = subprocess.run(
        [*backend.docker_bin, "exec", "--", handle.name, "sh", "-c", shell_command],
        capture_output=True, timeout=backend.daemon_timeout, check=False,
    )
    assert proc.returncode == 0, f"test setup exec failed (exit {proc.returncode})"


def _gate_cwd(backend: d.DockerBackend, handle: d._Handle, cwd: str, confine_root: str | None) -> tuple[str, int | None, str | None, str]:
    """Runs a gate that reports its own real cwd; returns (reason,
    exit_code, error, reported cwd from `observations`)."""
    result = backend.exec_in_attempt(
        handle, ["sh", "-c", "readlink /proc/self/cwd"], Limits(timeout=10.0),
        cwd=cwd, confine_root=confine_root,
    )
    with tempfile.TemporaryDirectory() as tmp:
        backend.export(handle, Path(tmp))
        observations = Path(tmp) / "observations"
        reported = observations.read_text().strip() if observations.is_file() else ""
    return result.reason, result.exit_code, result.error, reported


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
        outside_parent = "/tmp"
        outside = f"{outside_parent}/outside-root"
        # Hard preconditions on the test itself, not the property.
        assert outside != workspace_root and not outside.startswith(workspace_root + "/")
        with tempfile.TemporaryDirectory() as surface:
            (Path(surface) / "sub").mkdir()
            backend.install(handle, {"trial": Path(surface)})
        _exec_setup(backend, handle, f"mkdir {outside} && test -w {sub} && test -w {workspace_root}/trial")

        # Happy path, UNCONDITIONAL in every mode: a legitimately-resolved,
        # never-swapped cwd under confine_root must land the gate there for
        # real - proof the fd/proc-magic-symlink mechanism works inside an
        # actual container's own namespaces, not only on the bare host.
        resolved_sub = backend.resolve_realpath_in_attempt(handle, sub)
        assert resolved_sub == sub
        assert _gate_cwd(backend, handle, resolved_sub, workspace_root) == ("exited", 0, None, sub)

        # The swap, as the candidate: exactly what an earlier, separate
        # `resolve_realpath_in_attempt()` call could not have seen coming.
        _exec_setup(backend, handle, f"mv {sub} {sub}.orig && ln -s {outside} {sub} && test -L {sub}")
        assert backend.resolve_realpath_in_attempt(handle, sub) == outside, \
            "the swap must really point outside workspace_root, or this test proves nothing"

        # `confine_root=None` behaves identically to omitting it entirely,
        # so this is the full break for `confine-root-omitted`.
        reason, exit_code, error, reported = _gate_cwd(
            backend, handle, sub, None if BREAK_MODE == "confine-root-omitted" else workspace_root,
        )
        if BREAK_MODE == "confine-root-omitted":
            # The vulnerability, shown on a real daemon: `-w` followed the
            # swap. Checked as a hard assertion first, so the xfail below
            # can only come from the real property failing for this reason.
            assert (reason, exit_code, reported) == ("exited", 0, outside)
        # UNCONDITIONAL across both modes - the real property, never a
        # pre-approved different expected value for the break mode.
        _require(
            reason == "launch-failed" and error == d.CWD_CONFINEMENT_REFUSED_SENTINEL,
            "a cwd swapped to outside workspace_root between resolve and exec "
            "must be refused, not silently followed, on a real daemon",
        )
    finally:
        backend.destroy(handle)
