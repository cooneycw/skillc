"""The flow-check gate-witness overlay (#332, orchestrator review).

The shim is harness measurement apparatus, never a subject dependency - it
does not belong in a profile declaration (three successive `skillc.profile`
`synthetic`-kind widenings attempted to force it through anyway; each was a
sign the shim was in the wrong layer, so all three are reverted). Instead,
`apply_flow_check_gate_overlay()` runs as the LAST step of a live attempt's
setup, after whatever installed the subject's real `flow-finish-gate.sh`
(skillc#334 tracks closing the separate gap that nothing currently does so
for a live attempt): it moves that real script to a harness-only
destination the agent's own search paths never reach, and places the
forwarding shim at the exact path `reference.md` invokes.

ORDER MATTERS (orchestrator review): calling this before the real script is
installed would have nothing to move; calling anything that re-reads
installed-file digests (a verify-installed step) AFTER this runs would
(correctly) see the shim's digest where it expects the real script's -
this function is deliberately the LAST setup step, never re-run, and its
own `OverlayRecord` is what a later reader consults instead of re-deriving
anything from the container.

BOTH DIGESTS ARE CHECKED BEFORE ANYTHING IS WRITTEN (the orchestrator's own
named red case: "an overlay that places a different shim than the declared
digest is refused"). The REAL script's current content is read back from
the container (never assumed) and checked against `expected_real_digest` -
a mismatch means the subject path does not currently hold what this
overlay was told to expect (a stale pin, a corrupted install, or simply
calling this before installation finished), and is refused before
anything moves. The shim CONTENT handed to this function is checked
against `expected_shim_digest` the same way - a mismatch means the wrong
file was handed to this function as "the shim," and is refused before
anything is written, rather than silently placing it.

Reuses `ExecutionBackend.export()`/`install()` - no new backend primitive
is needed. The "move" is a read via `export()`, two writes via `install()`
(the real content to the harness destination, the shim content to the
subject path) - `install()`'s own tar-based write overwrites an existing
destination cleanly, so no explicit "remove the old file first" step is
needed.
"""

from __future__ import annotations

import hashlib
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .verify import SURFACE_EXECUTABLE_KEY


class OverlayRefused(Exception):
    """Either digest did not match what the caller declared - refused
    before anything is moved or written, never partially applied."""


@dataclass(frozen=True)
class OverlayRecord:
    """What a later reader consults instead of re-deriving anything from
    the container - the overlay runs exactly once, as the last setup step."""

    real_script_destination: str
    real_script_digest: str
    shim_destination: str
    shim_digest: str


class _ExportInstallBackend(Protocol):
    """The narrow slice of `ExecutionBackend` this module actually calls -
    named here so a caller can pass anything structurally compatible
    without importing `skillc.backend`'s full Protocol."""

    def export(self, handle: object, dest: Path) -> None: ...

    def install(self, handle: object, surface: dict[str, object]) -> dict[str, object]: ...


def apply_flow_check_gate_overlay(
    backend: _ExportInstallBackend,
    handle: object,
    *,
    subject_path: str,
    harness_path: str,
    expected_real_digest: str,
    expected_shim_digest: str,
    shim_content: bytes,
) -> OverlayRecord:
    """Moves the real script at `subject_path` to `harness_path`, then
    places `shim_content` at `subject_path` - both paths relative to the
    same root `export()`/`install()` already share (`CONTAINER_WORKSPACE`),
    matching `.claude/scripts/flow-finish-gate.sh`-style relative paths
    elsewhere in this codebase.

    Raises `OverlayRefused` - never partially applies - when:
    - `shim_content`'s own digest does not match `expected_shim_digest`
      (checked FIRST, before the container is even read, since it depends
      on nothing about the container's current state);
    - the real script currently at `subject_path` cannot be read at all,
      or its digest does not match `expected_real_digest`.
    """
    actual_shim_digest = hashlib.sha256(shim_content).hexdigest()
    if actual_shim_digest != expected_shim_digest:
        raise OverlayRefused(
            f"shim content digest {actual_shim_digest} does not match "
            f"the declared expected digest {expected_shim_digest} - refusing before writing anything"
        )

    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp)
        backend.export(handle, dest)
        real_path = dest / subject_path
        try:
            real_bytes = real_path.read_bytes()
        except OSError as exc:
            raise OverlayRefused(f"could not read the real script at {subject_path!r}: {exc}") from exc
    real_digest = hashlib.sha256(real_bytes).hexdigest()
    if real_digest != expected_real_digest:
        raise OverlayRefused(
            f"real script at {subject_path!r} has digest {real_digest}, "
            f"not the declared expected digest {expected_real_digest} - refusing before moving it"
        )

    backend.install(handle, {
        harness_path: real_bytes,
        subject_path: shim_content,
        SURFACE_EXECUTABLE_KEY: [harness_path, subject_path],
    })

    return OverlayRecord(
        real_script_destination=harness_path, real_script_digest=real_digest,
        shim_destination=subject_path, shim_digest=actual_shim_digest,
    )
