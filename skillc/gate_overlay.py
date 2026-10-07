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

TWO ROOTS, NOT ONE (#332 follow-up, orchestrator review: "turning the
witness into a laundering channel"). `subject_root` is where the agent's
own files live (`CONTAINER_HOME` for a live attempt, matching where #334
delivers the real script) - the shim lands there, and a subject editing or
replacing the SHIM at its own path is fine: that is a bypass, reads as
`not-observed`, and is already handled by the witness's own coverage
semantics. `harness_root` is DIFFERENT and REQUIRED (no default): a
directory the candidate identity cannot write. If the harness copy of the
REAL script sat under the candidate's own home, the subject could edit the
real script itself, and the controller would faithfully execute the edited
version and record it as a genuine gate run - the witness would be
laundering a subject-controlled result as controller-executed evidence,
exactly the class of bug #269's own design exists to prevent one layer up.

So the harness copy is placed via `write_root_owned_file_in_attempt()`
(root-owned, mode 0o755) - NEVER through `install()`'s own candidate-owned
tar convention (`_owned_tarinfo`), which exists specifically so a declared
skill surface is usable BY the candidate, the opposite of what is needed
here. After placement, `candidate_can_write_in_attempt()` independently
VERIFIES both the real script AND its containing directory are unwritable
by the candidate uid before this function returns - BOTH, never the file
alone (counter-model review finding): Unix write permission on a FILE
controls modifying its contents in place, but write+execute permission on
the DIRECTORY controls whether it can be unlinked and replaced entirely,
regardless of the file's own mode - a candidate with no access to the
file itself can still delete and recreate it if the directory is theirs
to write. Never assumed from mode bits, and never from trusting the write
call's own success. Only a confirmed `False` on BOTH checks is accepted;
`True` (writable) or `None` (unverifiable) on EITHER one refuses, since a
harness copy nobody has confirmed is protected - at the file level or the
directory level - is not evidence of protection.

Reuses `ExecutionBackend.export()`/`install()` for the subject-root halves
(the real-script read, the shim placement) - no new primitive needed
there. The harness-root write uses `DockerBackend`'s own two new, narrow
primitives instead (not part of the general `ExecutionBackend` Protocol,
since nothing else needs them): `write_root_owned_file_in_attempt()` and
`candidate_can_write_in_attempt()`.
"""

from __future__ import annotations

import hashlib
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol

from .verify import SURFACE_EXECUTABLE_KEY


class OverlayRefused(Exception):
    """A digest mismatch, an unwritable-harness verification failure, or a
    failed write - refused before anything is moved or written beyond that
    point, never partially applied."""


@dataclass(frozen=True)
class OverlayRecord:
    """What a later reader consults instead of re-deriving anything from
    the container - the overlay runs exactly once, as the last setup step."""

    real_script_destination: str
    real_script_digest: str
    shim_destination: str
    shim_digest: str


class _OverlayBackend(Protocol):
    """The narrow slice of backend operations this module actually calls -
    named here so a caller can pass anything structurally compatible
    without importing `skillc.backend`'s full Protocol. The last two are
    `DockerBackend`-specific primitives (#332 follow-up), never added to
    the general `ExecutionBackend` Protocol since nothing else needs them."""

    def export(self, handle: object, dest: Path, root: str | None = None) -> None: ...

    def install(self, handle: object, surface: dict[str, object], root: str | None = None) -> dict[str, object]: ...

    def write_root_owned_file_in_attempt(
        self, handle: object, path: str, content: bytes, mode: int = 0o755,
    ) -> bool: ...

    def candidate_can_write_in_attempt(self, handle: object, path: str) -> bool | None: ...


def apply_flow_check_gate_overlay(
    backend: _OverlayBackend,
    handle: object,
    *,
    subject_path: str,
    harness_path: str,
    expected_real_digest: str,
    expected_shim_digest: str,
    shim_content: bytes,
    subject_root: str | None = None,
    harness_root: str,
) -> OverlayRecord:
    """Moves the real script at `{subject_root}/{subject_path}` to
    `{harness_root}/{harness_path}` (root-owned, verified unwritable by
    the candidate), then places `shim_content` at `{subject_root}/
    {subject_path}`. `subject_path`/`harness_path` are relative; `subject_
    root` defaults like `export()`/`install()` do (`None` -> the backend's
    own default workspace root - unchanged for every #332-era caller that
    predates this parameter). `harness_root` has NO default: a caller must
    say explicitly where the candidate-unwritable copy goes.

    Raises `OverlayRefused` - never partially applies - when:
    - `shim_content`'s own digest does not match `expected_shim_digest`
      (checked FIRST, before the container is even read, since it depends
      on nothing about the container's current state);
    - the real script currently at `subject_path` cannot be read at all,
      or its digest does not match `expected_real_digest`;
    - the root-owned write to `harness_root` fails;
    - `candidate_can_write_in_attempt()` against the harness destination
      OR its containing directory does not return a confirmed `False` -
      `True` or `None` on either one refuses.

    The shim is placed at `subject_path` only AFTER the harness copy is
    written and independently confirmed unwritable - a refusal at any
    earlier step leaves the real script exactly where it was, never
    replaced by a shim pointing at an unverified or insecure harness copy.
    """
    actual_shim_digest = hashlib.sha256(shim_content).hexdigest()
    if actual_shim_digest != expected_shim_digest:
        raise OverlayRefused(
            f"shim content digest {actual_shim_digest} does not match "
            f"the declared expected digest {expected_shim_digest} - refusing before writing anything"
        )

    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp)
        backend.export(handle, dest, root=subject_root)
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

    harness_destination = f"{harness_root}/{harness_path}"
    if not backend.write_root_owned_file_in_attempt(handle, harness_destination, real_bytes, mode=0o755):
        raise OverlayRefused(f"could not write the root-owned harness copy at {harness_destination!r}")

    # BOTH the file and its containing directory must be confirmed
    # unwritable (counter-model review finding): Unix write permission on
    # the FILE controls modifying its contents in place, but write+execute
    # on the DIRECTORY is what actually controls whether it can be
    # unlinked and replaced entirely - a candidate with no access to the
    # file itself can still delete and recreate it if the directory is
    # theirs to write. `write_root_owned_file_in_attempt` already creates
    # that directory root-owned mode 0755, but this is independently
    # VERIFIED, never assumed from how it was created, the same posture
    # as the file check itself.
    harness_dir = str(PurePosixPath(harness_destination).parent)
    for target in (harness_destination, harness_dir):
        writable = backend.candidate_can_write_in_attempt(handle, target)
        if writable is not False:
            raise OverlayRefused(
                f"{target!r} is writable by the candidate identity "
                f"(or this could not be verified: candidate_can_write_in_attempt returned {writable!r}) - "
                "refusing to trust a gate-witness copy the subject could edit or replace"
            )

    backend.install(handle, {
        subject_path: shim_content,
        SURFACE_EXECUTABLE_KEY: [subject_path],
    }, root=subject_root)

    return OverlayRecord(
        real_script_destination=harness_destination, real_script_digest=real_digest,
        shim_destination=subject_path, shim_digest=actual_shim_digest,
    )
