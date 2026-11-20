"""The #620 PR-B journal custody (skillc/task_protocol_journal.py, B2).

controls/task-protocol-custody/healthy.jsonl was generated without running the
module; the writer must reproduce it byte for byte. The committed mutations
must each verify as declared, and blind verifiers must disagree with them."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from skillc import task_protocol_journal as tj
from skillc.task_protocol_journal import CapacityExceeded, Context, Journal, JournalUnavailable

CONTROLS = Path(__file__).resolve().parent.parent / "controls" / "task-protocol-custody"
HEALTHY = (CONTROLS / "healthy.jsonl").read_bytes()
INPUTS = json.loads((CONTROLS / "inputs.json").read_text())
CASES = json.loads((CONTROLS / "cases.json").read_text())


def _context(**changes: Any) -> Context:
    fields = {**INPUTS["context"], **changes}
    return Context(**{**fields, "principals": tuple(fields["principals"]),
                      "limits": dict(fields["limits"])})


CONTEXT = _context()


def _clock(origin: int, step: int) -> Callable[[], int]:
    ticks: Iterator[int] = iter(range(origin, origin + step * 100000, step))
    return lambda: next(ticks)


def _store(root: Path, raw: bytes, mode: int = 0o400, *, records: int | None = None,
           as_name: bytes | None = None) -> tj.Reference:
    """Store `raw` content-addressed, or under `as_name`'s address to model an
    object altered in place after its reference was taken."""
    (root / "objects").mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(raw).hexdigest()
    path = root / "objects" / hashlib.sha256(as_name if as_name is not None else raw).hexdigest()
    path.write_bytes(raw)
    os.chmod(path, mode)
    return tj.Reference(1, CONTEXT.digest, "sha256:" + digest, len(raw),
                        records if records is not None else raw.count(b"\n"))


def _rows(raw: bytes = HEALTHY) -> list[dict[str, Any]]:
    return [json.loads(line) for line in raw.splitlines()]


def _encode(rows: list[dict[str, Any]], *, rechain: bool = True, fix_seal: bool = True,
            loose: int | None = None) -> bytes:
    """Re-chain mutated rows: sequence, previous hashes and seal totals, so
    only the structural checks can refuse them."""
    out, previous = [], "0" * 64
    for index, row in enumerate(rows):
        if rechain:
            row = {**row, "seq": index + 1, "prev_hash": previous}
            if row["kind"] == "capture-seal" and fix_seal:
                row.update(records=len(rows) - 2, last_hash=previous)
        separators = (", ", ": ") if index == loose else (",", ":")
        line = json.dumps(row, sort_keys=True, separators=separators).encode() + b"\n"
        out.append(line)
        previous = hashlib.sha256(line).hexdigest()
    return b"".join(out)


def _mutate(name: str, root: Path) -> tuple[tj.Reference, Context]:
    rows = _rows()
    held = tj.Reference(1, CONTEXT.digest, "sha256:" + hashlib.sha256(HEALTHY).hexdigest(),
                        len(HEALTHY), HEALTHY.count(b"\n"))
    if name == "none":
        return _store(root, HEALTHY), CONTEXT
    if name == "other-context":
        return _store(root, HEALTHY), _context(attempt_id="attempt-2")
    if name == "other-limits":
        return _store(root, HEALTHY), _context(limits={**INPUTS["context"]["limits"],
                                                       "decisions_per_principal": 255})
    if name == "flip-byte":
        _store(root, HEALTHY.replace(b'"offered"', b'"offerex"', 1), as_name=HEALTHY)
        return held, CONTEXT
    if name == "truncate":
        _store(root, b"".join(HEALTHY.splitlines(keepends=True)[:-1]), as_name=HEALTHY)
        return held, CONTEXT
    if name == "drop-record-rechained-held":
        _store(root, _encode(rows[:6] + rows[7:]), as_name=HEALTHY)
        return held, CONTEXT
    if name == "writable":
        return _store(root, HEALTHY, mode=0o600), CONTEXT
    if name == "missing":
        return held, CONTEXT
    if name == "flip-byte-rehashed":
        return _store(root, HEALTHY.replace(b'"offered"', b'"offerex"', 1)), CONTEXT
    if name == "swap-rehashed":
        lines = HEALTHY.splitlines(keepends=True)
        lines[4], lines[5] = lines[5], lines[4]
        return _store(root, b"".join(lines)), CONTEXT
    if name == "drop-seal-rehashed":
        return _store(root, b"".join(HEALTHY.splitlines(keepends=True)[:-1])), CONTEXT
    if name == "noncanonical-rechained":
        return _store(root, _encode(rows, loose=4)), CONTEXT
    if name == "unfence-rechained":
        return _store(root, _encode([r for r in rows if r["kind"] != "fence"])), CONTEXT
    if name == "decision-after-fence-rechained":
        fence = next(i for i, r in enumerate(rows) if r["kind"] == "fence")
        late = {**rows[4], "request": 3, "elapsed_ns": rows[fence]["elapsed_ns"]}
        return _store(root, _encode(rows[:fence + 1] + [late] + rows[fence + 1:])), CONTEXT
    if name == "time-backwards-rechained":
        rows[5]["elapsed_ns"] = rows[4]["elapsed_ns"] - 1
        return _store(root, _encode(rows)), CONTEXT
    if name == "retry-mismatch-rechained":
        retry = next(r for r in rows if r["kind"] == "retry")
        retry["request_digest"] = "sha256:" + "9" * 64
        return _store(root, _encode(rows)), CONTEXT
    if name == "unplanned-principal-rechained":
        rows[1]["principal"] = "role-z"
        return _store(root, _encode(rows)), CONTEXT
    if name == "outcome-lie-rechained":
        rows[-1]["coverage"]["role-a"] = "unknown"
        return _store(root, _encode(rows)), CONTEXT
    if name == "capacity-closed-rechained":
        fence = next(i for i, r in enumerate(rows) if r["kind"] == "fence")
        capacity = {"seq": 0, "prev_hash": "0" * 64, "kind": "capacity",
                    "elapsed_ns": rows[fence - 1]["elapsed_ns"], "principal": None,
                    "scope": "records"}
        return _store(root, _encode(rows[:fence] + [capacity] + rows[fence:])), CONTEXT
    if name == "unknown-coverage-rechained":
        rows[-1]["coverage"]["role-c"] = "unknown"
        rows[-1]["outcome"] = "UNKNOWN"
        return _store(root, _encode(rows)), CONTEXT
    if name == "extra-field-rechained":
        rows[4]["note"] = "x"
        return _store(root, _encode(rows)), CONTEXT
    if name == "seal-count-rechained":
        raw = _encode(rows)
        fixed = _rows(raw)
        fixed[-1]["records"] += 1
        return _store(root, _encode(fixed, rechain=False)), CONTEXT
    raise AssertionError(name)


def _status(verifier: Callable[..., dict[str, Any]], case: dict[str, Any], root: Path) -> str:
    reference, context = _mutate(case["mutation"], root)
    return verifier(root, reference, context)["status"]


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["name"])
def test_each_committed_mutation_verifies_as_declared(case: dict[str, Any], tmp_path: Path) -> None:
    assert _status(tj.verify, case, tmp_path) == case["expect"]


def _hash_only(root: Path, reference: tj.Reference, _expected: Context) -> dict[str, Any]:
    try:
        tj._read(root, reference)
    except (OSError, ValueError):
        return {"status": "UNKNOWN"}
    return {"status": "CAPTURED"}


@pytest.mark.parametrize("blind,must_miss", [
    (lambda *_a: {"status": "CAPTURED"}, "flip-byte-held-reference"),
    (lambda *_a: {"status": "UNKNOWN"}, "healthy"),
    (_hash_only, "unfenced-seal-rechained"),
    (_hash_only, "outcome-lies-about-coverage-rechained"),
    (_hash_only, "retry-mismatch-rechained"),
], ids=["always-captured", "always-unknown", "hash-only-fence", "hash-only-outcome",
        "hash-only-retry"])
def test_a_blind_verifier_disagrees(blind: Callable[..., dict[str, Any]], must_miss: str,
                                    tmp_path: Path) -> None:
    case = next(c for c in CASES if c["name"] == must_miss)
    assert _status(blind, case, tmp_path) != case["expect"]


def _write(root: Path, context: Context = CONTEXT, **kwargs: Any) -> Journal:
    clock = kwargs.pop("clock_ns", _clock(INPUTS["origin_ns"], INPUTS["clock_step_ns"]))
    return Journal(root, context, INPUTS["origin_ns"], clock_ns=clock, **kwargs)


def test_the_writer_reproduces_the_committed_journal(tmp_path: Path) -> None:
    journal = _write(tmp_path / "j")
    for entry in INPUTS["appends"]:
        journal.append(entry["kind"], **entry["fields"])
    reference = journal.seal(INPUTS["coverage"])
    assert (tmp_path / "j" / "objects" / reference.digest[7:]).read_bytes() == HEALTHY
    assert reference.records == HEALTHY.count(b"\n") and reference.size == len(HEALTHY)
    assert not (tmp_path / "j" / "journal.tmp").exists()
    result = tj.verify(tmp_path / "j", reference, CONTEXT)
    assert result["status"] == "CAPTURED" and result["outcome"] == "CLOSED"
    assert [r["kind"] for r in result["records"]] == [e["kind"] for e in INPUTS["appends"]]


def test_append_returns_the_controller_sequence_and_elapsed(tmp_path: Path) -> None:
    journal = _write(tmp_path / "j")
    assert journal.append("fence", reason="closure") == (2, INPUTS["clock_step_ns"])


class _FailingFs:
    def __init__(self, *, fsync_at: int | None = None, short_at: int | None = None) -> None:
        self.fsyncs = self.writes = 0
        self.fsync_at, self.short_at = fsync_at, short_at

    def write(self, fd: int, data: bytes) -> int:
        self.writes += 1
        if self.writes == self.short_at:
            return os.write(fd, bytes(data)[:-1])
        return os.write(fd, data)

    def fsync(self, fd: int) -> None:
        self.fsyncs += 1
        if self.fsyncs == self.fsync_at:
            raise OSError("injected fsync failure")
        os.fsync(fd)


@pytest.mark.parametrize("fs", [_FailingFs(fsync_at=3), _FailingFs(short_at=2)],
                         ids=["fsync-failure", "short-write"])
def test_a_write_or_fsync_failure_poisons_the_journal(fs: _FailingFs, tmp_path: Path) -> None:
    journal = _write(tmp_path / "j", fs=fs)
    with pytest.raises(OSError):
        journal.append("binding", principal="role-a", evidence_digest="sha256:" + "d" * 64)
    with pytest.raises(JournalUnavailable, match="poisoned"):
        journal.append("fence", reason="closure")
    with pytest.raises(JournalUnavailable):
        journal.seal(dict.fromkeys(CONTEXT.principals, "complete"))
    assert not list((tmp_path / "j" / "objects").iterdir())


def test_a_failure_while_opening_leaves_no_journal(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        _write(tmp_path / "j", fs=_FailingFs(fsync_at=1))


def _limits(**changes: int) -> dict[str, int]:
    return {**tj.DEFAULT_LIMITS, **changes}


def test_record_capacity_refuses_without_poisoning_and_keeps_the_reserve(tmp_path: Path) -> None:
    journal = _write(tmp_path / "j", _context(limits=_limits(max_records=8,
                                                             closure_reserve_records=3)))
    for _ in range(4):
        journal.append("rejection", principal=None, reason="unavailable", length=1,
                       content_digest="sha256:" + "3" * 64)
    with pytest.raises(CapacityExceeded, match="records"):
        journal.append("rejection", principal=None, reason="unavailable", length=1,
                       content_digest="sha256:" + "3" * 64)
    journal.append("capacity", principal=None, scope="records")
    journal.append("fence", reason="capacity")
    reference = journal.seal(dict.fromkeys(CONTEXT.principals, "complete"))
    result = tj.verify(tmp_path / "j", reference,
                       _context(limits=_limits(max_records=8, closure_reserve_records=3)))
    assert result["status"] == "CAPTURED" and result["outcome"] == "UNKNOWN"


def test_the_per_principal_decision_bound(tmp_path: Path) -> None:
    journal = _write(tmp_path / "j", _context(limits=_limits(decisions_per_principal=2)))
    row = {"op": "offer", "offer_id": "o-1", "request_digest": "sha256:" + "1" * 64,
           "decision": "offered", "reason": None}
    journal.append("decision", principal="role-a", request=1, **row)
    journal.append("decision", principal="role-a", request=2, **row)
    with pytest.raises(CapacityExceeded, match="principal"):
        journal.append("decision", principal="role-a", request=3, **row)
    journal.append("decision", principal="role-b", request=1, **row)


def test_the_byte_bound(tmp_path: Path) -> None:
    journal = _write(tmp_path / "j", _context(limits=_limits(max_bytes=6000,
                                                             closure_reserve_bytes=2000)))
    with pytest.raises(CapacityExceeded, match="bytes"):
        for _ in range(100):
            journal.append("rejection", principal=None, reason="unavailable", length=1,
                           content_digest="sha256:" + "3" * 64)
    journal.append("capacity", principal=None, scope="bytes")


def test_after_the_fence_only_closure_and_rejections_are_written(tmp_path: Path) -> None:
    journal = _write(tmp_path / "j")
    journal.append("fence", reason="deadline")
    with pytest.raises(JournalUnavailable, match="fenced"):
        journal.append("decision", principal="role-a", request=1, op="offer", offer_id="o-1",
                       request_digest="sha256:" + "1" * 64, decision="offered", reason=None)
    journal.append("rejection", principal="role-a", reason="fenced", length=3,
                   content_digest="sha256:" + "3" * 64)


def test_a_seal_without_a_fence_is_refused_without_poisoning(tmp_path: Path) -> None:
    journal = _write(tmp_path / "j")
    coverage = dict.fromkeys(CONTEXT.principals, "complete")
    with pytest.raises(JournalUnavailable, match="fence"):
        journal.seal(coverage)
    journal.append("fence", reason="closure")
    with pytest.raises(JournalUnavailable, match="coverage"):
        journal.seal({"role-a": "complete"})
    assert tj.verify(tmp_path / "j", journal.seal(coverage), CONTEXT)["status"] == "CAPTURED"


@pytest.mark.parametrize("kind,fields", [
    ("binding", {"principal": "role-z", "evidence_digest": "sha256:" + "d" * 64}),
    ("binding", {"principal": "role-a", "evidence_digest": "d" * 64}),
    ("binding", {"principal": "role-a", "evidence_digest": "sha256:" + "d" * 64, "x": 1}),
    ("capacity", {"principal": None, "scope": "tokens"}),
    ("fence", {"reason": "Free text"}),
    ("capture-seal", {"records": 0, "last_hash": "0" * 64, "coverage": {}, "outcome": "CLOSED"}),
    ("capture-start", {"version": 1, "context": {}}),
    ("telemetry", {}),
])
def test_a_malformed_append_is_refused_and_writes_nothing(kind: str, fields: dict[str, Any],
                                                          tmp_path: Path) -> None:
    journal = _write(tmp_path / "j")
    with pytest.raises(JournalUnavailable):
        journal.append(kind, **fields)
    assert journal.append("fence", reason="closure")[0] == 2


def test_the_clock_cannot_go_backwards_or_start_in_the_future(tmp_path: Path) -> None:
    values = iter([1000, 1100, 1050])
    journal = _write(tmp_path / "j", clock_ns=lambda: next(values))
    journal.append("fence", reason="closure")
    with pytest.raises(JournalUnavailable, match="backwards"):
        journal.append("fence", reason="closure")
    with pytest.raises(JournalUnavailable):
        Journal(tmp_path / "k", CONTEXT, 5000, clock_ns=lambda: 1000)


def test_concurrent_appends_stay_contiguous(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "j", CONTEXT, 0)

    def worker() -> None:
        for _ in range(25):
            journal.append("rejection", principal=None, reason="unavailable", length=1,
                           content_digest="sha256:" + "3" * 64)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    journal.append("fence", reason="closure")
    result = tj.verify(tmp_path / "j", journal.seal(dict.fromkeys(CONTEXT.principals, "complete")),
                       CONTEXT)
    assert result["status"] == "CAPTURED" and len(result["records"]) == 8 * 25 + 1


def test_close_keeps_a_sealed_object_and_abandons_an_unsealed_one(tmp_path: Path) -> None:
    sealed = _write(tmp_path / "a")
    sealed.append("fence", reason="closure")
    reference = sealed.seal(dict.fromkeys(CONTEXT.principals, "complete"))
    sealed.close()
    assert tj.verify(tmp_path / "a", reference, CONTEXT)["status"] == "CAPTURED"
    abandoned = _write(tmp_path / "b")
    abandoned.close()
    with pytest.raises(JournalUnavailable):
        abandoned.append("fence", reason="closure")
    assert tj.verify(tmp_path / "b", reference, CONTEXT)["status"] == "UNKNOWN"


def test_a_journal_root_is_never_reused(tmp_path: Path) -> None:
    (tmp_path / "j").mkdir()
    with pytest.raises(FileExistsError):
        _write(tmp_path / "j")


@pytest.mark.parametrize("changes", [
    {"principals": ("role-a", "role-a")},
    {"principals": ()},
    {"declaration_digest": "a" * 64},
    {"producer_version": ""},
    {"clock": "wall"},
    {"limits": {"max_records": 10}},
    {"limits": _limits(closure_reserve_records=32768)},
    {"limits": _limits(request_bytes=0)},
])
def test_a_context_outside_the_contract_is_refused(changes: dict[str, Any]) -> None:
    with pytest.raises(JournalUnavailable):
        _context(**changes)


def test_verify_refuses_bindings_not_held_by_the_caller(tmp_path: Path) -> None:
    reference = _store(tmp_path, HEALTHY)
    assert tj.verify(str(tmp_path), reference, CONTEXT)["status"] == "UNKNOWN"
    assert tj.verify(tmp_path, {}, CONTEXT)["status"] == "UNKNOWN"
    assert tj.verify(tmp_path, reference, CONTEXT.fields())["status"] == "UNKNOWN"
