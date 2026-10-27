"""Private controller-input evidence: every complete claim has a refused twin."""
from __future__ import annotations

import json
import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from test_agent_trial import _planned
from test_retained_export import inputs as retained_inputs  # noqa: F401 - shared synthetic fixture

from skillc import agent_trial as at
from skillc import matched_pilot
from skillc import trial as t


@pytest.fixture
def attempt(tmp_path: Path) -> tuple[t.Experiment, str]:
    return _planned(t.open_store(tmp_path / "store", []))


def safe(_: bytes) -> list[str]:
    return []


def retain(e: t.Experiment, aid: str, texts: tuple[str, ...] = ("initial\n\u03bb", "resume \U0001f680")) -> None:
    t.begin_prompt_inputs(e, aid, len(texts) - 1)
    for index, text in enumerate(texts, 1):
        t.retain_prompt_input(e, aid, index, text, safe)
    t.finish_prompt_inputs(e, aid, list(range(1, len(texts) + 1)), "declared-complete")


def rewrite(e: t.Experiment, aid: str, mutate: Callable[[list[dict[str, Any]]], None]) -> None:
    events = e.events(aid)
    mutate(events)
    e.journal(aid).write_text("".join(json.dumps(v) + "\n" for v in events))


def entry(events: list[dict[str, Any]]) -> dict[str, Any]:
    return next(v for v in events if v.get("event") == "prompt-input")


def test_exact_bytes_and_measured_sizes_are_independent_of_launch(attempt: tuple[t.Experiment, str]) -> None:
    e, aid = attempt
    retain(e, aid)
    trace = t.read_prompt_inputs(e, aid)
    assert trace.coverage == "complete"
    assert [i.data for i in trace.inputs] == ["initial\n\u03bb".encode(), "resume \U0001f680".encode()]
    assert [i.launched for i in trace.inputs] == [None, None]
    assert [v["size"] for v in e.events(aid) if v.get("event") == "prompt-input"] == [10, 11]


@pytest.mark.parametrize("key,value", [
    ("attempt", "another-attempt"), ("index", True), ("index", 2), ("role", "resume"),
    ("size", True), ("size", -1), ("size", 11), ("ref", "objects/../ledger.json"),
    ("digest", "sha256:bad"), ("unknown", "ignored"), ("coverage", "partial"),
])
def test_wrong_binding_or_schema_refuses_its_healthy_twin(
    attempt: tuple[t.Experiment, str], key: str, value: Any,
) -> None:
    e, aid = attempt
    retain(e, aid)
    assert t.read_prompt_inputs(e, aid).coverage == "complete"
    rewrite(e, aid, lambda rows: entry(rows).update({key: value}))
    with pytest.raises(t.Refused):
        t.read_prompt_inputs(e, aid)


@pytest.mark.parametrize("change", ["missing", "modified", "symlink", "fifo", "oversize", "encoding", "nul"])
def test_actual_descriptor_bytes_must_match(attempt: tuple[t.Experiment, str], change: str, tmp_path: Path) -> None:
    e, aid = attempt
    retain(e, aid)
    assert t.read_prompt_inputs(e, aid).coverage == "complete"
    v = entry(e.events(aid))
    path = e.object_path(v["digest"])
    path.chmod(0o600)
    path.unlink()
    if change == "symlink":
        other = tmp_path / "other"
        other.write_bytes("initial\n\u03bb".encode())
        path.symlink_to(other)
    elif change == "fifo":
        os.mkfifo(path)
    elif change != "missing":
        blob = b"modified!!" if change == "modified" else b"x" * 11
        if change in {"encoding", "nul"}:
            blob = b"\xff" if change == "encoding" else b"\x00"
            digest = t.sha256_bytes(blob)
            path = e.object_path(digest)
            rewrite(e, aid, lambda rows: entry(rows).update(digest=digest, ref=f"objects/{digest[7:]}", size=1))
        path.write_bytes(blob)
    with pytest.raises(t.Refused):
        t.read_prompt_inputs(e, aid)


@pytest.mark.parametrize("change", ["terminal-missing", "terminal-duplicate", "prepared-deleted", "input-deleted"])
def test_terminal_population_loss_is_unknown(attempt: tuple[t.Experiment, str], change: str) -> None:
    e, aid = attempt
    retain(e, aid)
    assert t.read_prompt_inputs(e, aid).coverage == "complete"

    def mutate(rows: list[dict[str, Any]]) -> None:
        terminal = next(v for v in rows if v.get("event") == "prompt-inputs-ended")
        if change == "terminal-missing":
            rows.remove(terminal)
        elif change == "terminal-duplicate":
            rows.append(dict(terminal))
        elif change == "prepared-deleted":
            terminal["prepared"] = [1]
        else:
            rows.remove(next(v for v in rows if v.get("index") == 2))
    rewrite(e, aid, mutate)
    trace = t.read_prompt_inputs(e, aid)
    assert trace.coverage == "unknown"
    assert trace.inputs[0].data == "initial\n\u03bb".encode()


def test_unrequested_suffix_and_legacy_are_not_invented(attempt: tuple[t.Experiment, str]) -> None:
    e, aid = attempt
    assert t.read_prompt_inputs(e, aid).coverage == "not-recorded"
    t.begin_prompt_inputs(e, aid, 3)
    t.retain_prompt_input(e, aid, 1, "only actually prepared text", safe)
    t.finish_prompt_inputs(e, aid, [1], "header-unavailable")
    assert t.read_prompt_inputs(e, aid).coverage == "complete"
    assert len(t.read_prompt_inputs(e, aid).inputs) == 1


@pytest.mark.parametrize("text,reason", [("\ud800", "encoding"), ("unsafe\x00text", "unsafe-text"),
                                          ("sk-" + "f" * 25, "unsafe-text")])
def test_private_text_refusal_never_publishes_a_prefix(
    attempt: tuple[t.Experiment, str], text: str, reason: str,
) -> None:
    e, aid = attempt
    # The same actual scanner must accept safe text and detect the planted token.
    assert at.transcript_leak_findings(b"safe synthetic text") == []
    assert at.transcript_leak_findings(("sk-" + "f" * 25).encode())
    before = set((e.root / t.OBJECTS).iterdir())
    t.begin_prompt_inputs(e, aid, 0)
    t.retain_prompt_input(e, aid, 1, text, at.transcript_leak_findings)
    t.finish_prompt_inputs(e, aid, [1], "lifecycle-ended")
    trace = t.read_prompt_inputs(e, aid)
    assert trace.coverage == "missing" and trace.inputs[0].reason == reason
    assert trace.inputs[0].data is None and set((e.root / t.OBJECTS).iterdir()) == before
    assert text not in e.journal(aid).read_text()


def test_aggregate_actual_utf8_cap_and_preencoding_bound(
    attempt: tuple[t.Experiment, str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace
    e, aid = attempt
    monkeypatch.setattr(t, "Limits", lambda: SimpleNamespace(max_stream_bytes=8))
    t.begin_prompt_inputs(e, aid, 2)
    t.retain_prompt_input(e, aid, 1, "\u03bb" * 3, safe)  # six bytes, three chars
    t.retain_prompt_input(e, aid, 2, "ok", safe)  # exactly eight aggregate bytes

    class NoEncode(str):
        def encode(self, *args: Any, **kwargs: Any) -> bytes:
            raise AssertionError("oversize text must be refused before encoding")
    t.retain_prompt_input(e, aid, 3, NoEncode("x"), safe)
    t.finish_prompt_inputs(e, aid, [1, 2, 3], "declared-complete")
    trace = t.read_prompt_inputs(e, aid)
    assert [i.data for i in trace.inputs] == [("\u03bb" * 3).encode(), b"ok", None]
    assert trace.coverage == "missing" and trace.inputs[2].reason == "capacity"


@pytest.mark.parametrize("failure", ["scanner", "storage", "journal"])
def test_failures_cannot_create_complete_binding(attempt: tuple[t.Experiment, str], monkeypatch: pytest.MonkeyPatch,
                                               failure: str) -> None:
    e, aid = attempt
    t.begin_prompt_inputs(e, aid, 0)
    def fail(*args: Any, **kwargs: Any) -> Any:
        raise OSError("unsafe exception text must never be retained")
    if failure == "storage":
        monkeypatch.setattr(t, "_write_new", fail)
    if failure == "journal":
        with monkeypatch.context() as patch:
            patch.setattr(e, "record", fail)
            with pytest.raises(OSError):
                t.retain_prompt_input(e, aid, 1, "orphan bytes", safe)
    else:
        t.retain_prompt_input(e, aid, 1, "safe text", fail if failure == "scanner" else safe)
    t.finish_prompt_inputs(e, aid, [1], "lifecycle-ended")
    assert t.read_prompt_inputs(e, aid).coverage == ("unknown" if failure == "journal" else "missing")
    assert "unsafe exception text" not in e.journal(aid).read_text()


def test_order_and_freezing_have_real_rejections(attempt: tuple[t.Experiment, str]) -> None:
    e, aid = attempt
    t.begin_prompt_inputs(e, aid, 0)
    for index in [True, 0, 2]:
        with pytest.raises(t.Refused):
            t.retain_prompt_input(e, aid, index, "safe", safe)
    t.retain_prompt_input(e, aid, 1, "safe", safe)
    with pytest.raises(t.Refused):
        t.begin_prompt_inputs(e, aid, 0)
    t.finish_prompt_inputs(e, aid, [1], "lifecycle-ended")
    with pytest.raises(t.Refused):
        t.finish_prompt_inputs(e, aid, [1], "lifecycle-ended")
    with pytest.raises(t.Refused):
        t.retain_prompt_input(e, aid, 1, "different", safe)


@pytest.mark.parametrize("operation", ["terminal", "reader"])
def test_terminal_writer_and_reader_take_existing_experiment_lock(
    attempt: tuple[t.Experiment, str], monkeypatch: pytest.MonkeyPatch, operation: str,
) -> None:
    import threading
    e, aid = attempt
    t.begin_prompt_inputs(e, aid, 0)
    t.retain_prompt_input(e, aid, 1, "private exact text", safe)
    entered = threading.Event()
    original = e.events
    def events(*args: Any, **kwargs: Any) -> Any:
        entered.set()
        return original(*args, **kwargs)
    monkeypatch.setattr(e, "events", events)
    started = threading.Event()
    def invoke() -> object:
        started.set()
        return (t.finish_prompt_inputs(e, aid, [1], "lifecycle-ended") if operation == "terminal"
                else t.read_prompt_inputs(e, aid))
    with ThreadPoolExecutor(max_workers=1) as pool:
        with t.experiment_lock(e.root):
            # A bypassing call must trip the observer while this lock is held.
            pool.submit(e.events, aid).result(timeout=2)
            assert entered.is_set()
            entered.clear()
            pending = pool.submit(invoke)
            assert started.wait(2)
            assert not entered.wait(0.03), "prompt operation escaped the verifier's existing lock"
        pending.result(timeout=2)
    assert entered.is_set()
    if operation == "reader":
        t.finish_prompt_inputs(e, aid, [1], "lifecycle-ended")
    assert t.read_prompt_inputs(e, aid).coverage == "complete"


def test_records_export_keeps_prompt_objects_private(attempt: tuple[t.Experiment, str], tmp_path: Path) -> None:
    e, aid = attempt
    retain(e, aid)
    before = t.read_prompt_inputs(e, aid)
    written = matched_pilot.export_bundle(e, {}, tmp_path / "export")
    assert written and not any(p.name in {t.OBJECTS, t.JOURNAL} for p in (tmp_path / "export").iterdir())
    assert all(b"initial" not in p.read_bytes() for p in written)
    assert t.read_prompt_inputs(e, aid) == before


def test_public_retained_export_withholds_new_prompt_bytes_and_rejects_corruption(
    tmp_path: Path, retained_inputs: dict[str, Path],  # noqa: F811 - pytest injects imported fixture
) -> None:
    from skillc import retained_export as export
    # Reuse the existing wholly synthetic source fixture; no historical store.
    source = retained_inputs
    e = t.Experiment.open(source["store"])
    _, planned = next(e.attempts())
    aid = str(planned["attempt_id"])
    lifecycle = e.root / f"lifecycle-{aid}.json"
    old = lifecycle.read_bytes()
    lifecycle.unlink()  # stage new evidence before synthetic finalization
    t.begin_prompt_inputs(e, aid, 0)
    t.retain_prompt_input(e, aid, 1, "synthetic private controller input", safe)
    lifecycle.write_bytes(old)
    t.finish_prompt_inputs(e, aid, [1], "lifecycle-ended")
    before = export._fingerprint(source["run"])
    export.export_retained(source["run"], source["declaration"], source["profile"], source["out"],
                           root=Path(__file__).resolve().parent.parent, snapshot=source["snapshot"])
    assert export._fingerprint(source["run"]) == before
    payload = b"synthetic private controller input"
    digest = t.sha256_bytes(payload)
    files = [f for f in source["out"].rglob("*") if f.is_file()]
    assert files and all(payload not in f.read_bytes() for f in files)
    metadata = json.loads((source["out"] / "metadata/export.json").read_text())
    assert {"digest": digest, "size": len(payload), "exported": False} in metadata["withheld_objects"]
    assert t.read_prompt_inputs(e, aid).inputs[0].data == payload
    bad_public = source["out"] / "private-control"
    bad_public.write_bytes(payload)
    with pytest.raises(AssertionError):
        assert all(payload not in f.read_bytes() for f in [*files, bad_public])
    path = e.object_path(digest)
    path.chmod(0o600)
    path.write_bytes(b"corrupt")
    with pytest.raises((t.Refused, export.ExportRefused)):
        export.export_retained(source["run"], source["declaration"], source["profile"], tmp_path / "bad-export",
                               root=Path(__file__).resolve().parent.parent, snapshot=source["snapshot"])
    assert not (tmp_path / "bad-export").exists()


@pytest.mark.parametrize("state", ["healthy", "missing-dispatch", "conflicting", "suppressed"])
def test_resume_launch_needs_its_own_consistent_journal_join(attempt: tuple[t.Experiment, str], state: str) -> None:
    e, aid = attempt
    retain(e, aid)
    assert t.read_prompt_inputs(e, aid).inputs[1].launched is None
    if state != "missing-dispatch":
        e.record(aid, "controller-turn", index=2, dispatched=True)
    e.record(aid, "controller-turn", index=2, ended="launch-failed" if state == "suppressed" else "exited",
             delivered=state != "suppressed")
    if state == "conflicting":
        e.record(aid, "controller-turn", index=2, delivered=False)
    assert t.read_prompt_inputs(e, aid).inputs[1].launched is {
        "healthy": True, "missing-dispatch": None, "conflicting": None, "suppressed": False,
    }[state]


@pytest.mark.parametrize("change", ["duplicate-marker", "duplicate-input", "reordered", "declared-bool"])
def test_ambiguous_preparation_cannot_claim_complete(attempt: tuple[t.Experiment, str], change: str) -> None:
    e, aid = attempt
    retain(e, aid)
    assert t.read_prompt_inputs(e, aid).coverage == "complete"
    def mutate(rows: list[dict[str, Any]]) -> None:
        marker = next(v for v in rows if v.get("event") == "prompt-inputs")
        first = entry(rows)
        if change == "duplicate-marker":
            rows.append(dict(marker))
        elif change == "duplicate-input":
            rows.insert(rows.index(first), dict(first))
        elif change == "declared-bool":
            marker["declared"] = True
        else:
            second = next(v for v in rows if v.get("index") == 2)
            a, b = rows.index(first), rows.index(second)
            rows[a], rows[b] = rows[b], rows[a]
    rewrite(e, aid, mutate)
    with pytest.raises(t.Refused):
        t.read_prompt_inputs(e, aid)


def test_multibyte_overflow_refuses_after_bounded_encoding(attempt: tuple[t.Experiment, str],
                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace
    e, aid = attempt
    monkeypatch.setattr(t, "Limits", lambda: SimpleNamespace(max_stream_bytes=8))
    t.begin_prompt_inputs(e, aid, 0)
    t.retain_prompt_input(e, aid, 1, "\u03bb" * 5, safe)  # five chars, ten bytes
    t.finish_prompt_inputs(e, aid, [1], "lifecycle-ended")
    trace = t.read_prompt_inputs(e, aid)
    assert trace.coverage == "missing" and trace.inputs[0].reason == "capacity"
    assert not e.object_path(t.sha256_bytes(("\u03bb" * 5).encode())).exists()


@pytest.mark.parametrize("state", ["launched", "not-run", "initial-never-started", "legacy-resume-never-started",
                                   "missing-dispatch", "missing-start", "missing-stop", "conflicting-start"])
def test_initial_launch_requires_consistent_execution_evidence(attempt: tuple[t.Experiment, str], state: str) -> None:
    e, aid = attempt
    retain(e, aid, ("initial", "resume") if state == "legacy-resume-never-started" else ("initial",))
    if state != "not-run":
        e.record(aid, "dispatched")
        e.record(aid, "started")
        e.record(aid, "stopped", reason="launch-failed" if "never-started" in state else "exited",
                 exit_code=None if "never-started" in state else 0, confirmed=True)
        e.record(aid, "stop-confirmed")
    if state == "legacy-resume-never-started":
        e.record(aid, "controller-turn", index=2, dispatched=True)
        e.record(aid, "controller-turn", index=2, ended="launch-failed", delivered=False)
    t.finalize(e, aid)
    raw = (e.root / f"lifecycle-{aid}.json").read_bytes()
    if state.startswith("missing-"):
        event = {"missing-dispatch": "dispatched", "missing-start": "started", "missing-stop": "stopped"}[state]
        rewrite(e, aid, lambda rows: rows.__setitem__(slice(None), [v for v in rows if v["event"] != event]))
    if state == "conflicting-start":
        e.record(aid, "started")
    expected = True if state in {"launched", "legacy-resume-never-started"} else (
        False if state in {"not-run", "initial-never-started"} else None)
    trace = t.read_prompt_inputs(e, aid)
    assert trace.coverage == "complete" and trace.inputs[0].data == b"initial"
    assert trace.inputs[0].launched is expected
    assert (e.root / f"lifecycle-{aid}.json").read_bytes() == raw


def test_prompt_detail_allowlist_refuses_a_typo(attempt: tuple[t.Experiment, str]) -> None:
    e, aid = attempt
    with pytest.raises(ValueError, match="unknown lifecycle event"):
        e.record(aid, "prompt-input-typo")
    retain(e, aid, ("safe",))
    assert t.read_prompt_inputs(e, aid).coverage == "complete"
