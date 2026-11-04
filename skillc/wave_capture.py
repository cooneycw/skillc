"""Controller custody of final opaque wave bytes (#623), never Git execution.

Both exported roots are required, including an explicitly empty shared root.
Links and special files are unavailable evidence. The manifest authenticates
retained bytes against a separately retained receipt, not participant claims.
"""
from __future__ import annotations

import hashlib
import json
import stat
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .git_snapshot import SafeTree, Unreadable

SURFACES = ("shared-state", "fixture-remote")
MANIFEST = "final-snapshots.json"
MAX_ENTRIES = 4096
MAX_BYTES = 64 * 1024 * 1024
MAX_DEPTH = 32


def _surface(root: Path) -> dict[str, Any]:
    try:
        tree = SafeTree(root)
        entries: dict[str, Any] = {}

        def walk(path: str, depth: int) -> None:
            if depth > MAX_DEPTH or len(entries) >= MAX_ENTRIES:
                raise Unreadable("capture inventory bound exceeded")
            kind = tree.kind(path)
            if kind == "dir":
                entries[path] = {"kind": "directory"}
                for name, _ in tree.listdir(path):
                    walk(path + "/" + name if path else name, depth + 1)
            elif kind == "file":
                data, mode = tree.read(path, min(8 * 1024 * 1024, MAX_BYTES - tree.bytes_read))
                entries[path] = {"kind": "file", "bytes": len(data),
                                 "mode": stat.S_IMODE(mode),
                                 "sha256": hashlib.sha256(data).hexdigest()}
            else:
                raise Unreadable("capture contains an unsupported entry")

        walk("", 0)
        return {"status": "CAPTURED", "entries": entries}
    except (OSError, Unreadable, ValueError):
        # Exception text can contain participant paths or host identity.
        return {"status": "UNKNOWN", "reason": "surface-unreadable-or-over-bound"}


def manifest(root: Path, unavailable: Mapping[str, str]) -> dict[str, Any]:
    """Inventory only exports whose transfer AND writer stop were confirmed."""
    if set(unavailable) - set(SURFACES):
        raise ValueError("undeclared final capture surface")
    surfaces = {name: ({"status": "UNKNOWN", "reason": unavailable[name]}
                       if name in unavailable else _surface(root / name)) for name in SURFACES}
    return {"version": 1, "scope": "final-raw-bytes-only", "surfaces": surfaces,
            "status": "CAPTURED" if all(row["status"] == "CAPTURED"
                                         for row in surfaces.values()) else "UNKNOWN"}


def verify(root: Path, expected_sha256: str) -> dict[str, Any]:
    """Re-read the manifest and both byte populations; loss never reads clean.

    The caller retains the expected manifest digest independently (DockerWave
    includes it in report.json). A digest alone does not certify Git validity,
    message authenticity, prior revisions, timing, or task success.
    """
    try:
        raw, _ = SafeTree(root).read(MANIFEST, 4 * 1024 * 1024)
        if hashlib.sha256(raw).hexdigest() != expected_sha256:
            raise ValueError("manifest changed")
        recorded = json.loads(raw)
        if (not isinstance(recorded, dict) or recorded.get("version") != 1
                or recorded.get("scope") != "final-raw-bytes-only"
                or recorded.get("status") != "CAPTURED"
                or not isinstance(recorded.get("surfaces"), dict)
                or set(recorded["surfaces"]) != set(SURFACES)):
            raise ValueError("final capture incomplete")
        current = manifest(root, {})
        if current["status"] != "CAPTURED" or recorded != current:
            raise ValueError("retained capture changed")
        return {"status": "CAPTURED", "manifest": MANIFEST, "sha256": expected_sha256}
    except (OSError, Unreadable, ValueError, TypeError, RecursionError):
        return {"status": "UNKNOWN", "manifest": MANIFEST, "sha256": expected_sha256}
