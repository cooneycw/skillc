"""Gate-time projection of the files final grading can receive (#348).

This deliberately reuses trial's PRIVATE capture policy at this revision.
It is not a finalized capture: no stop, ledger, journal or manifest is claimed.
The projection writes objects only in disposable controller scratch; callers
must supply an owned export, never a live candidate path on the host. Recheck
this seam whenever trial's capture policy changes.
"""
from __future__ import annotations

import hashlib
import tempfile
from collections.abc import Iterable, Sequence
from pathlib import Path

from . import trial

Refused = trial.Refused


def _digest(triples: Iterable[tuple[str, str, str]]) -> str:
    ordered = sorted(triples)
    if not ordered:
        raise Refused("empty witness capture population")
    if len({path for path, _, _ in ordered}) != len(ordered):
        raise Refused("duplicate path in witness capture population")
    digest = hashlib.sha256()
    for path, mode, content_digest in ordered:
        digest.update(f"{path}\0{mode}\0{content_digest}\n".encode())
    return "sha256:" + digest.hexdigest()


def files_digest(files: Sequence[tuple[str, bytes, bool]]) -> str:
    """Identity of the exact validated frozen files passed to grade_files.

    Same byte framing as materialize.tree_digest on their reconstructed tree;
    use the stored OWNER executable bit, not access checks on the host.
    """
    return _digest((path, "x" if executable else "-", trial.sha256_bytes(data))
                   for path, data, executable in files)


def capture_digest(output: Path, *, limits: trial.Limits | None = None) -> str:
    """Project an owned export using final capture's default scope and limits.

    A partial/empty projection, raised IO error, or failed scratch cleanup is
    a refusal. Exclusions remain capture's own exclusions, never a special
    list of bookkeeping names. No objects are written into a real trial.
    """
    if output.is_symlink() or not output.is_dir():
        raise Refused("witness export root is not a regular directory")
    try:
        with tempfile.TemporaryDirectory(prefix="skillc-witness-capture-") as directory:
            root = Path(directory)
            (root / trial.OBJECTS).mkdir(mode=0o700)
            scratch = trial.Experiment(root=root, ledger={})
            captured = trial._export(scratch, output, ("*",), limits or trial.Limits())
            if captured.failures:
                raise Refused("incomplete witness capture projection")
            digest = _digest((str(a["path"]), str(a["mode"]), str(a["digest"])) for a in captured.artifacts)
        # Return only after cleanup succeeds; errors must never certify a tree.
        return digest
    except OSError as exc:
        raise Refused(f"witness capture IO or cleanup failed ({type(exc).__name__})") from exc
