"""`cpp-codex-flow-auto` at claude-power-pack `86641e8` (#434 PR 2b): the
profile closes against its committed snapshot, the snapshot is exactly the
closure with its provenance and upstream licence, and, measured against the
snapshot's own pinned `counter-model-receipt.py`, a nested codex refused by
the D3 guard is READ as a skip (`unparseable`, which reference.md §1c records
as `skipped` / `reviewer-unavailable`) but cannot be WRITTEN as one in a codex
trial: the pinned writer leaves no receipt (orchestrator ruling (a) on
condition 3: the CPP contract is measured, not assumed).

Red cases:
- the contract test's positive control: a well-formed clean transcript must
  parse as `clean`, so `unparseable` is a verdict the parser reached, not the
  only thing it can say;
- the scrubbed-environment control: the same skip write with a leaked
  `CLAUDE_CODE_SESSION_ID` succeeds, so the refusal is a fact of the trial's
  environment, not of the test's;
- a snapshot carrying a file the closure does not reach, or missing one,
  fails `test_the_snapshot_is_exactly_the_closure`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from test_codex_guard import _guard_copy, _real_recorder

from skillc import cli
from skillc import profile as p

ROOT = Path(__file__).resolve().parent.parent
PIN = "86641e817711d8a7746270745a5dfa7cacf04b0c"
SUBJECT_DIR = ROOT / "evals" / "subjects" / "cpp-codex-flow-auto-86641e8"
SNAPSHOT = ROOT / "tests" / "fixtures" / "profile-cpp-codex-flow-auto-86641e8"
RECEIPT = SNAPSHOT / "scripts" / "counter-model-receipt.py"
NOT_CLOSURE = {"README.md", "LICENSE"}


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def test_the_profile_is_clean_against_its_own_pin() -> None:
    prof = p.Profile.load(SUBJECT_DIR / "profile.json")
    report = p.diagnose(prof, p.load_tree(prof, None, SNAPSHOT))
    assert report["complete"] is True and report["problems"] == []
    declared = _json(SUBJECT_DIR / "profile.json")
    assert _json(SUBJECT_DIR / "subject.json")["revision"] == PIN
    assert declared["select"] == ["flow-auto", "flow-eli5"]
    assert declared["gate_entrypoint"] == ".claude/scripts/flow-finish-gate.sh"


def test_the_snapshot_inventory_is_the_committed_evidence(tmp_path: Path) -> None:
    out = tmp_path / "inventory.json"
    assert cli.main(["profile", "validate", str(SUBJECT_DIR / "profile.json"), "--snapshot", str(SNAPSHOT),
                     "--out", str(out)]) == 0
    evidence, snapshot = _json(SUBJECT_DIR / "evidence" / "inventory.json"), _json(out)
    assert evidence["subject"]["revision"] == PIN
    strip = lambda inv: {k: v for k, v in inv.items() if k != "subject"}
    assert strip(snapshot) == strip(evidence)


def _closure_sources() -> set[str]:
    inventory = _json(SUBJECT_DIR / "evidence" / "inventory.json")
    sources = {f["source"] for group in (inventory["skills"], inventory["dependencies"])
               for entry in group for f in entry.get("files") or [] if f.get("source")}
    for pair in [*inventory["mirrors"], *inventory["generated_from"]]:
        sources |= {pair["source"], pair["generated"]}
    return sources | {"CLAUDE.md"}  # the pinned file the synthetic checkout marker replaces


def test_the_snapshot_is_exactly_the_closure() -> None:
    # Tool caches are local, gitignored and never committed: the snapshot holds
    # CPP's own pyproject.toml, so ruff caches beside it.
    caches = {"__pycache__", ".ruff_cache", ".mypy_cache", ".pytest_cache"}
    present = {path.relative_to(SNAPSHOT).as_posix() for path in SNAPSHOT.rglob("*")
               if path.is_file() and not caches & set(path.relative_to(SNAPSHOT).parts)}
    assert present - NOT_CLOSURE == _closure_sources()


def test_the_snapshot_records_its_provenance_and_carries_the_upstream_licence() -> None:
    readme = (SNAPSHOT / "README.md").read_text(encoding="utf-8")
    assert "https://github.com/cooneycw/claude-power-pack" in readme
    assert f"`{PIN}`" in readme and "MIT" in readme
    licence = (SNAPSHOT / "LICENSE").read_text(encoding="utf-8")
    assert licence.startswith("MIT License") and "Copyright (c) 2025 cooneycw" in licence
    assert "permission notice shall be included in all" in licence


# --- D3 condition 3: the pinned receipt writer reads a nested exit 3 as a skip ------

def _receipt(*args: str, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(RECEIPT), *args], capture_output=True, text=True, cwd=cwd,
                          env=env, timeout=60, check=False)


def _refusal_artifacts(tmp_path: Path) -> list[Path]:
    """What a nested review leaves when the guard refuses it: the stderr the
    guard itself wrote, and the empty --output-last-message file."""
    real, _ = _real_recorder(tmp_path)
    copy = _guard_copy(tmp_path, decision="refused-nested", real=real, sock=tmp_path / "no.sock")
    proc = subprocess.run([str(copy), "exec", "--output-last-message", "findings.md", "-"], capture_output=True,
                          text=True, timeout=30, check=False, env={"PATH": "/usr/bin:/bin"})
    assert proc.returncode == 3 and proc.stderr.startswith("CODEX_REVIEW: unavailable")
    (tmp_path / "stderr.md").write_text(proc.stderr)
    (tmp_path / "findings.md").write_text("")
    return [tmp_path / "stderr.md", tmp_path / "findings.md"]


def test_the_pinned_receipt_parser_reads_the_guards_refusal_as_unparseable(tmp_path: Path) -> None:
    for artifact in _refusal_artifacts(tmp_path):
        parsed = _receipt("parse", str(artifact), cwd=tmp_path)
        assert parsed.returncode != 0
        assert "COUNTER_MODEL_REVIEW: unparseable" in parsed.stdout, parsed.stdout


def test_contract_control_a_clean_transcript_parses_as_clean(tmp_path: Path) -> None:
    transcript = tmp_path / "clean.md"
    transcript.write_text("## Findings\n\nNone - no defects found.\n\n## Red cases\n\nNone - no instrument changed.\n")
    parsed = _receipt("parse", str(transcript), cwd=tmp_path)
    assert parsed.returncode == 0 and "COUNTER_MODEL_REVIEW: clean" in parsed.stdout, parsed.stdout


#: A codex trial's environment, EXPLICITLY scrubbed: no CLAUDE_CODE_SESSION_ID.
#: The writer reads that variable to derive the implementer, so a test that
#: inherits the controller's own environment measures the controller, not the
#: trial (#434 PR 2b: the first measurement of this contract did exactly that).
def _trial_env(home: Path) -> dict[str, str]:
    return {"PATH": os.defpath, "HOME": str(home)}


_SKIP = ("write", "--dir", "receipts", "--issue", "1", "--branch", "issue-1-widget", "--status", "skipped",
         "--reason", "reviewer-unavailable", "--at", "2026-10-17T00:00:00Z")


def test_under_this_pin_a_codex_trial_cannot_write_the_skip_receipt(tmp_path: Path) -> None:
    """Orchestrator ruling (a) on condition 3: §1c maps the refusal to skipped /
    reviewer-unavailable, but the pinned writer derives the implementer from a
    Claude session a codex trial does not have, and refuses its codex form for
    a skip. A nested refusal therefore leaves NO counter-model receipt, against
    the skill's own §1d ("a receipt is also written on a skip")."""
    exec_log = tmp_path / "implementer.jsonl"
    exec_log.write_text(json.dumps({"type": "thread.started", "thread_id": "thread-impl"}) + "\n")
    plain = _receipt(*_SKIP, cwd=tmp_path, env=_trial_env(tmp_path))
    assert plain.returncode == 1
    assert "missing implementer session id; supply --implementer-session-id or set CLAUDE_CODE_SESSION_ID" \
        in plain.stderr
    codex_form = _receipt(*_SKIP, "--implementer-exec-log", str(exec_log), cwd=tmp_path, env=_trial_env(tmp_path))
    assert codex_form.returncode == 2
    assert "--implementer-exec-log records a delegated review that happened; it requires --status ran" \
        in codex_form.stderr
    assert not list(tmp_path.glob("receipts/*.json"))


def test_control_a_leaked_claude_session_id_changes_the_outcome(tmp_path: Path) -> None:
    """The red that keeps the test above honest: the SAME call, with a Claude
    session id leaked into the environment (as the controller's own shell had
    it), writes a receipt. If the scrub ever stops working, the refusal test
    above turns into this one."""
    projects = tmp_path / "projects" / "-work"
    projects.mkdir(parents=True)
    (projects / "leaked-session.jsonl").write_text(
        json.dumps({"type": "assistant", "message": {"model": "claude-host-session"}}) + "\n")
    env = {**_trial_env(tmp_path), "CLAUDE_CODE_SESSION_ID": "leaked-session"}
    written = _receipt(*_SKIP, "--claude-projects-dir", str(tmp_path / "projects"), cwd=tmp_path, env=env)
    assert written.returncode == 0, written.stderr
    [receipt] = (tmp_path / "receipts").glob("*.json")
    record = _json(receipt)
    assert (record["status"], record["skip_reason"]) == ("skipped", "reviewer-unavailable")
    assert record["implementer"] == "claude/claude-host-session"  # the HOST's identity, not the trial's


@pytest.mark.parametrize("reason", ["codex-absent", "reviewer-unavailable"])
def test_the_pinned_skip_vocabulary_is_unchanged(tmp_path: Path, reason: str) -> None:
    """If the pin read a nested refusal some other way, this vocabulary is
    where it would show first."""
    listed = _receipt("skip-reasons", cwd=tmp_path)
    assert listed.returncode == 0 and reason in listed.stdout.split()
