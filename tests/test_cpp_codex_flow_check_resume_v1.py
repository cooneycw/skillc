"""The new fixture profile closes against its immutable producer snapshot."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from skillc import gate_state, profile

ROOT = Path(__file__).resolve().parents[1]
SUBJECT = ROOT / "evals/subjects/cpp-codex-flow-check-resume-v1"
SNAPSHOT = ROOT / "tests/fixtures/profile-cpp-codex-flow-check-resume-v1"
PIN = "dd988219e056ddf23fb7ef5ba55e93979c07b61a"


def test_snapshot_closes_to_same_inventory_and_protocol() -> None:
    prof = profile.Profile.load(SUBJECT / "profile.json")
    actual = profile.validate(prof, profile.load_tree(prof, None, SNAPSHOT))
    committed = json.loads((SUBJECT / "evidence/inventory.json").read_text())
    assert committed["subject"]["revision"] == PIN
    assert {k: v for k, v in actual.items() if k != "subject"} == {
        k: v for k, v in committed.items() if k != "subject"}
    proto = gate_state.Protocol.from_inventory(committed)
    assert proto.producer_revision == PIN
    assert dict(proto.operations) == {"flow-check-plan": "runner", "flow-check-summary": "inspection"}
    assert proto.inventory_digest == profile.inventory_digest(committed)


def test_snapshot_population_modes_and_licence_are_exactly_declared() -> None:
    inventory = json.loads((SUBJECT / "evidence/inventory.json").read_text())
    records = [r for group in (inventory["skills"], inventory["dependencies"])
               for item in group for r in item.get("files") or [] if r.get("source")]
    for record in records:
        path = SNAPSHOT / record["source"]
        assert path.is_file() and not path.is_symlink()
        assert "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest() == record["digest"]
        assert (path.stat().st_mode & 0o111 != 0) == (record["mode"] == "100755")
    sources = {r["source"] for r in records}
    for pair in [*inventory["mirrors"], *inventory["generated_from"]]:
        sources |= {pair["source"], pair["generated"]}
    caches = {"__pycache__", ".ruff_cache", ".mypy_cache", ".pytest_cache"}
    present = {p.relative_to(SNAPSHOT).as_posix() for p in SNAPSHOT.rglob("*") if p.is_file()
               and not caches.intersection(p.relative_to(SNAPSHOT).parts)}
    assert present == sources | {"README.md", "LICENSE", "CLAUDE.md"}
    assert hashlib.sha256((SNAPSHOT / "LICENSE").read_bytes()).hexdigest() == (
        "c6c2630fa5d672358d322509c5c073f87fa89f59157a93fe0b4067edd0260c60")


# Fault injection in a separate interpreter around ACTUAL pinned Path I/O. These
# are contract controls, not regressions or claims that normal producer emits faults.
PRODUCER_FAULT_HOOK = r'''
import atexit, hashlib, json, os
from pathlib import Path
cfg_path = os.environ.get("SKILLC_TEST_FAULT_FILE")
if cfg_path:
    cfg = json.loads(Path(cfg_path).read_text())
    mode = cfg.get("mode")
    audit_path = Path(cfg["audit"])
    original_read, original_write, original_unlink = Path.read_bytes, Path.write_bytes, Path.unlink
    events, writes, loaded = [], 0, False
    last_write = None
    def digest(raw):
        return "sha256:" + hashlib.sha256(raw).hexdigest()
    def event(kind, raw=b""):
        events.append({"kind": kind, "sha256": digest(raw), "bytes": len(raw)})
        original_write(audit_path, json.dumps(events).encode())
    def selected(path):
        return path.parent.name == "cpp-runs" and path.parent.parent.name == ".git" and path.name.startswith("check-")
    def read_bytes(path):
        global loaded
        raw = original_read(path)
        if selected(path) and not loaded:
            loaded = True
            if mode == "load-swap-restored":
                swapped = b" " + raw
                original_write(path, swapped)
                observed = original_read(path)
                original_write(path, raw)
                event("loaded-swapped-restored", observed)
                return observed
            event("loaded", raw)
            if mode == "after-load-disk":
                original_write(path, raw + b" ")
                event("disk-after-load", raw + b" ")
        return raw
    def write_bytes(path, raw):
        global writes, last_write
        if not selected(path):
            return original_write(path, raw)
        writes += 1
        if mode == "save-failed" or (mode == "save-later-failed" and writes >= 2):
            event("save-failed", raw)
            raise OSError("injected actual state write failure")
        if mode == "save-short":
            count = original_write(path, raw[:-1])
            event("save-short", raw[:-1])
            return count
        count = original_write(path, raw)
        last_write = (path, raw)
        event("saved", raw)
        if mode == "save-replaced":
            original_write(path, raw + b" ")
            event("disk-after-save", raw + b" ")
        return count
    def unlink(path, *args, **kwargs):
        if not selected(path):
            return original_unlink(path, *args, **kwargs)
        if mode == "cleanup-failed":
            event("cleanup-failed")
            raise OSError("injected actual cleanup failure")
        result = original_unlink(path, *args, **kwargs)
        event("cleanup")
        if mode == "cleanup-recreated":
            def recreate():
                assert last_write is not None
                target, raw = last_write
                original_write(target, raw + b" ")
                event("recreated-after-report", raw + b" ")
            atexit.register(recreate)
        return result
    Path.read_bytes, Path.write_bytes, Path.unlink = read_bytes, write_bytes, unlink
'''
