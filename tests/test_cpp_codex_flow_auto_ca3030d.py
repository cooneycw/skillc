"""`cpp-codex-flow-auto` at claude-power-pack `ca3030d` (#279 re-pin): the
profile closes against its committed snapshot, the snapshot is exactly the
closure with its provenance and upstream licence, and - the reason for the pin
- the pinned `counter-model-receipt.py` now WRITES a Codex trial's skip
(`skipped` / `reviewer-unavailable`) from the Codex thread alone, where the
86641e8 writer refused it (`test_cpp_codex_flow_auto_86641e8.py`).

Red cases:
- the receipt control: the same write with NO implementer identity at all is
  refused - the 86641e8 failure, kept - so the success is the thread id's;
- the refusal the orchestrator required kept after the re-pin: a flow-check
  profile at this pin (whose skill invokes its bundled gate) without the
  bundled witness is refused by `bundled-gate-unwitnessed`.

SCRIPTED, not live: whether codex-cli 0.157.1 exports `CODEX_THREAD_ID` to the
commands it runs is NOT measured here (it needs a model turn). The pinned
binary carries the name beside `exec_command` (#279 record); the first live
attempt on this pin shows it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from skillc import cli
from skillc import profile as p

ROOT = Path(__file__).resolve().parent.parent
PIN = "ca3030dbeba4a145166b61d714861f56e92cd034"
SUBJECT_DIR = ROOT / "evals" / "subjects" / "cpp-codex-flow-auto-ca3030d"
SNAPSHOT = ROOT / "tests" / "fixtures" / "profile-cpp-codex-flow-auto-ca3030d"
RECEIPT = SNAPSHOT / "scripts" / "counter-model-receipt.py"
NOT_CLOSURE = {"README.md", "LICENSE"}
THREAD = "01a165c8-c8cf-7a02-b1c8-84e493c0d6f9"

#: claude-power-pack `ca3030d` (MIT, https://github.com/cooneycw/claude-power-pack,
#: codex/skills/flow-check/reference.md:53-55): flow-check's own bundled call.
FLOW_CHECK_CALL = "an allowlist rule, issue #613):\n\n```bash\nscripts/flow-finish-gate.sh --plan check --evidence flow-check\n```\n"


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
    assert declared["bundled_gate_entrypoints"] == [
        f".codex/skills/{s}/scripts/flow-finish-gate.sh" for s in ("flow-auto", "flow-check", "flow-finish", "flow-merge")]


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
    return sources | {"CLAUDE.md"}


def test_the_snapshot_is_exactly_the_closure() -> None:
    caches = {"__pycache__", ".ruff_cache", ".mypy_cache", ".pytest_cache"}
    present = {path.relative_to(SNAPSHOT).as_posix() for path in SNAPSHOT.rglob("*")
               if path.is_file() and not caches & set(path.relative_to(SNAPSHOT).parts)}
    assert present - NOT_CLOSURE == _closure_sources()


def test_the_snapshot_records_its_provenance_and_carries_the_upstream_licence() -> None:
    readme = (SNAPSHOT / "README.md").read_text(encoding="utf-8")
    assert "https://github.com/cooneycw/claude-power-pack" in readme
    assert f"`{PIN}`" in readme and "MIT" in readme
    licence = (SNAPSHOT / "LICENSE").read_text(encoding="utf-8")
    assert licence.startswith("MIT License") and "permission notice shall be included in all" in licence


def test_the_runtime_metadata_is_86641e8s_byte_for_byte() -> None:
    """Policy B's premise: only the pin moves, never the dependency layer."""
    old = ROOT / "tests" / "fixtures" / "profile-cpp-codex-flow-auto-86641e8"
    for name in ("pyproject.toml", "uv.lock"):
        assert (SNAPSHOT / name).read_bytes() == (old / name).read_bytes()


# --- the pin's reason: a Codex trial's skip receipt is writable ---------------

def _receipt(*args: str, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(RECEIPT), *args], capture_output=True, text=True, cwd=cwd, env=env,
                          timeout=60, check=False)


_SKIP = ("write", "--dir", "receipts", "--issue", "1", "--branch", "issue-1-widget", "--status", "skipped",
         "--reason", "reviewer-unavailable", "--at", "2026-10-22T00:00:00Z")


def _codex_home(tmp_path: Path) -> Path:
    """A trial home as the pinned client lays it out: the thread's rollout,
    with the turn record the writer reads its model from."""
    home = tmp_path / "home"
    rollout = home / ".codex" / "sessions" / "2026" / "10" / "22" / f"rollout-2026-10-22T22-40-00-{THREAD}.jsonl"
    rollout.parent.mkdir(parents=True)
    rollout.write_text(json.dumps({"type": "session_meta", "payload": {"id": THREAD}}) + "\n"
                       + json.dumps({"type": "turn_context", "payload": {"model": "gpt-6-astra"}}) + "\n")
    return home


def test_under_this_pin_a_codex_trial_writes_the_skip_receipt(tmp_path: Path) -> None:
    home = _codex_home(tmp_path)
    env = {"PATH": os.defpath, "HOME": str(home), "CODEX_THREAD_ID": THREAD}  # no CLAUDE_CODE_SESSION_ID
    written = _receipt(*_SKIP, cwd=tmp_path, env=env)
    assert written.returncode == 0, written.stderr
    [receipt] = (tmp_path / "receipts").glob("*.json")
    record = _json(receipt)
    assert (record["status"], record["skip_reason"]) == ("skipped", "reviewer-unavailable")
    assert record["implementer"] == "codex/gpt-6-astra"
    assert record["implementer_evidence"]["thread_id"] == THREAD


def test_control_with_no_implementer_identity_the_write_is_refused(tmp_path: Path) -> None:
    """The 86641e8 failure, kept: without the thread id there is still no
    receipt - so the success above is the thread id's, not the environment's."""
    home = _codex_home(tmp_path)
    refused = _receipt(*_SKIP, cwd=tmp_path, env={"PATH": os.defpath, "HOME": str(home)})
    assert refused.returncode == 1 and "missing implementer identity" in refused.stderr
    assert not list(tmp_path.glob("receipts/*.json"))


# --- the refusal the orchestrator required, kept after the re-pin -------------

def test_red_a_flow_check_profile_at_this_pin_without_the_bundled_witness_is_refused() -> None:
    """The flow-check witness of a bundled gate is deferred (#525), so a
    flow-check treatment at a pin from #1408 on is refused - never silenced.
    flow-check's own call at this pin, through the check every profile runs."""
    files = {".codex/skills/flow-check/reference.md": FLOW_CHECK_CALL.encode(),
             ".codex/skills/flow-check/scripts/flow-finish-gate.sh": b"#!/usr/bin/env bash\n",
             ".claude/scripts/flow-finish-gate.sh": b"#!/usr/bin/env bash\n"}
    problems = p.bundled_gate_problems(files, ".claude/scripts/flow-finish-gate.sh", (), {}, manifest_name=None,
                                       require_consumers_installed=False)
    assert [(c, path) for c, _m, path in problems] == [
        ("bundled-gate-unwitnessed", ".codex/skills/flow-check/scripts/flow-finish-gate.sh")]
