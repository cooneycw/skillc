"""Raw-byte custody controls, not message authenticity or Git validity proofs."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from skillc import wave_capture as capture

CASES = Path(__file__).resolve().parents[1] / "controls/wave-capture/cases.json"


def populate(root: Path) -> None:
    for name in capture.SURFACES:
        (root / name).mkdir(parents=True)
    (root / "shared-state/mailbox").write_bytes(b"uninterpreted acknowledgement\n")
    (root / "shared-state/registry").write_bytes(b"worker-a\n")
    # Deliberately opaque, invalid Git metadata: only byte custody is approved.
    (root / "fixture-remote/config").write_bytes(b"opaque\x00\xff")


def record(root: Path, unavailable: dict[str, str] | None = None) -> str:
    raw = json.dumps(capture.manifest(root, unavailable or {}), sort_keys=True).encode()
    (root / capture.MANIFEST).write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize("case", json.loads(CASES.read_text()), ids=lambda c: c["name"])
def test_committed_integrity_cases(tmp_path: Path, case: dict[str, Any]) -> None:
    populate(tmp_path)
    digest = record(tmp_path)
    assert capture.verify(tmp_path, digest)["status"] == "CAPTURED"
    mutation = case["mutation"]
    if mutation == "rewrite-mail":
        (tmp_path / "shared-state/mailbox").write_bytes(b"forged replacement\n")
    elif mutation == "delete-registry":
        (tmp_path / "shared-state/registry").unlink()
    elif mutation == "rewrite-remote":
        (tmp_path / "fixture-remote/config").write_bytes(b"changed")
    elif mutation == "add-file":
        (tmp_path / "shared-state/added").write_bytes(b"added")
    elif mutation == "delete-surface":
        shutil.rmtree(tmp_path / "shared-state")
    elif mutation == "rewrite-manifest":
        (tmp_path / capture.MANIFEST).write_bytes(b"{}")
    elif mutation == "link-surface":
        (tmp_path / "shared-state").rename(tmp_path / "outside")
        (tmp_path / "shared-state").symlink_to(tmp_path / "outside", target_is_directory=True)
    elif mutation == "wrong-digest":
        digest = "0" * 64
    else:
        assert mutation == "none"
    assert capture.verify(tmp_path, digest)["status"] == case["expected"]


def test_empty_is_distinct_from_absent_and_partial_export(tmp_path: Path) -> None:
    for name in capture.SURFACES:
        (tmp_path / name).mkdir()
    assert capture.verify(tmp_path, record(tmp_path))["status"] == "CAPTURED"
    shutil.rmtree(tmp_path / "shared-state")
    assert capture.verify(tmp_path, record(tmp_path))["status"] == "UNKNOWN"
    (tmp_path / "shared-state").mkdir()
    (tmp_path / "shared-state/partial").write_bytes(b"partial cp output")
    digest = record(tmp_path, {"shared-state": "export-unavailable"})
    document = json.loads((tmp_path / capture.MANIFEST).read_bytes())
    assert document["surfaces"]["fixture-remote"]["status"] == "CAPTURED"
    assert capture.verify(tmp_path, digest)["status"] == "UNKNOWN"


@pytest.mark.parametrize("kind", ["link", "fifo", "bytes", "entries", "depth"])
def test_unsupported_or_bounded_surface_is_unknown(tmp_path: Path, monkeypatch: Any, kind: str) -> None:
    populate(tmp_path)
    if kind == "link":
        (tmp_path / "shared-state/link").symlink_to("/unavailable")
    elif kind == "fifo":
        import os
        os.mkfifo(tmp_path / "shared-state/fifo")
    else:
        if kind == "depth":
            (tmp_path / "shared-state/nested/deeper").mkdir(parents=True)
        monkeypatch.setattr(capture, {"bytes": "MAX_BYTES", "entries": "MAX_ENTRIES",
                                     "depth": "MAX_DEPTH"}[kind], 1)
    assert capture.verify(tmp_path, record(tmp_path))["status"] == "UNKNOWN"


def test_controller_copy_survives_original_rewrite_and_deletion(tmp_path: Path) -> None:
    source, owned = tmp_path / "source", tmp_path / "owned"
    populate(source)
    shutil.copytree(source, owned)
    digest = record(owned)
    (source / "shared-state/mailbox").write_bytes(b"replacement")
    shutil.rmtree(source)
    assert capture.verify(owned, digest)["status"] == "CAPTURED"


def test_entry_mode_and_empty_directory_changes_are_observed(tmp_path: Path) -> None:
    populate(tmp_path)
    digest = record(tmp_path)
    (tmp_path / "shared-state/mailbox").chmod(0o700)
    assert capture.verify(tmp_path, digest)["status"] == "UNKNOWN"
    digest = record(tmp_path)
    (tmp_path / "shared-state/empty").mkdir()
    assert capture.verify(tmp_path, digest)["status"] == "UNKNOWN"
