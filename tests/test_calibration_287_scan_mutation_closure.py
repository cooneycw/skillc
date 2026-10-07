"""Tests for `evals/calibration-287/evidence/scan_mutation_closure.py`: the
occurrence-scan evidence builder for gate-stops-early's degraded-arm
mutation (skillc#287).

The committed red case: a synthetic "degraded" closure that still carries
the removed sentence's phrase in an agent-facing file must turn `claim_holds`
False - built by hand here (never assumed), mirroring the real mutation
check already run by hand against the real closure (see this task's own
`diagnose_evidence` text, skillc#287)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parent.parent / "evals" / "calibration-287" / "evidence" / "scan_mutation_closure.py"
_spec = importlib.util.spec_from_file_location("scan_mutation_closure_287", MODULE_PATH)
assert _spec is not None and _spec.loader is not None
smc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(smc)

#: One real non-agent-facing path from the module's own closed set, and the
#: real agent-facing reference.md path - the classification logic is keyed
#: on exact membership in that set, so a synthetic test must use a REAL
#: member to exercise the non-agent-facing branch at all.
_NON_AGENT_FACING = "codex/skills/flow-check/scripts/flow-finish-gate.sh"
_AGENT_FACING = smc.REFERENCE_MD
_SENTENCE = (
    "A\n  `skipped gates:` name is a SKIP row and a `zero coverage:` or no-tests name is\n"
    "  a WARN row - never a PASS."
)


def _write_inventory(tmp_path: Path, sources: list[str]) -> Path:
    inventory = {"skills": [{"files": [{"source": s} for s in sources]}]}
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps(inventory), encoding="utf-8")
    return path


def _write_tree(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def _write_diagnose_stub(path: Path) -> Path:
    path.write_text(json.dumps({"complete": True, "problem_count": 0}), encoding="utf-8")
    return path


def test_closure_sources_reads_every_file_across_every_skill(tmp_path: Path) -> None:
    inventory_path = tmp_path / "inventory.json"
    inventory_path.write_text(json.dumps({
        "skills": [
            {"files": [{"source": "a.py"}, {"source": "b.py"}]},
            {"files": [{"source": "c.md"}]},
        ],
    }), encoding="utf-8")
    assert smc.closure_sources(inventory_path) == ["a.py", "b.py", "c.md"]


def test_scan_classifies_agent_facing_vs_non_agent_facing_and_the_removed_sentence(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    _write_tree(root, {
        _AGENT_FACING: f"intro\n{_SENTENCE}\ntrailer\n",
        _NON_AGENT_FACING: "# comment mentioning skipped gates in passing\n",
    })
    hits = smc.scan(root, [_AGENT_FACING, _NON_AGENT_FACING])
    removed = [h for h in hits if h["classification"] == "removed sentence itself"]
    assert removed and all(h["file"] == _AGENT_FACING for h in removed)
    non_agent_hits = [h for h in hits if h["file"] == _NON_AGENT_FACING]
    assert non_agent_hits
    assert all(h["agent_facing"] is False for h in non_agent_hits)
    assert all(h["classification"].startswith("non-agent-facing") for h in non_agent_hits)


def test_scan_reports_a_missing_file_rather_than_crashing(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    hits = smc.scan(root, ["absent.md"])
    assert hits == [{"file": "absent.md", "error": "missing"}]


def test_main_end_to_end_claim_holds_when_the_sentence_is_cleanly_removed(tmp_path: Path) -> None:
    inventory_path = _write_inventory(tmp_path, [_AGENT_FACING, _NON_AGENT_FACING])
    intact_root, degraded_root = tmp_path / "intact", tmp_path / "degraded"
    _write_tree(intact_root, {
        _AGENT_FACING: f"intro\n{_SENTENCE}\ntrailer\n", _NON_AGENT_FACING: "# comment: skipped gates\n",
    })
    _write_tree(degraded_root, {
        _AGENT_FACING: "intro\ntrailer\n", _NON_AGENT_FACING: "# comment: skipped gates\n",
    })
    out_path = tmp_path / "evidence.json"
    exit_code = smc.main([
        "--inventory", str(inventory_path), "--intact-root", str(intact_root),
        "--degraded-root", str(degraded_root),
        "--intact-diagnose", str(_write_diagnose_stub(tmp_path / "intact-diag.json")),
        "--degraded-diagnose", str(_write_diagnose_stub(tmp_path / "degraded-diag.json")),
        "--removed-text", _SENTENCE, "--out", str(out_path),
    ])
    assert exit_code == 0
    evidence = json.loads(out_path.read_text(encoding="utf-8"))
    assert evidence["occurrence_scan"]["claim_holds"] is True
    assert evidence["occurrence_scan"]["removed_sentence_confirmed_absent_in_degraded"] is True
    assert evidence["occurrence_scan"]["positive_control_held"] is True
    assert evidence["occurrence_scan"]["new_agent_facing_hits_in_degraded_not_present_in_intact"] == []


def test_red_a_leftover_agent_facing_copy_in_degraded_turns_claim_holds_false(tmp_path: Path) -> None:
    """The committed red case: the degraded closure still carries an
    agent-facing copy of the obligation somewhere intact never had one -
    claim_holds must go False, not silently stay True."""
    inventory_path = _write_inventory(tmp_path, [_AGENT_FACING, _NON_AGENT_FACING])
    intact_root, degraded_root = tmp_path / "intact", tmp_path / "degraded"
    _write_tree(intact_root, {
        _AGENT_FACING: f"intro\n{_SENTENCE}\ntrailer\n", _NON_AGENT_FACING: "# comment: skipped gates\n",
    })
    _write_tree(degraded_root, {
        # removed from reference.md, but a NEW agent-facing leak was planted
        # elsewhere in the same file - the leak this check exists to catch.
        _AGENT_FACING: "intro\ntrailer\nnever a PASS leaked back in\n",
        _NON_AGENT_FACING: "# comment: skipped gates\n",
    })
    out_path = tmp_path / "evidence.json"
    exit_code = smc.main([
        "--inventory", str(inventory_path), "--intact-root", str(intact_root),
        "--degraded-root", str(degraded_root),
        "--intact-diagnose", str(_write_diagnose_stub(tmp_path / "intact-diag.json")),
        "--degraded-diagnose", str(_write_diagnose_stub(tmp_path / "degraded-diag.json")),
        "--removed-text", _SENTENCE, "--out", str(out_path),
    ])
    assert exit_code == 1
    evidence = json.loads(out_path.read_text(encoding="utf-8"))
    assert evidence["occurrence_scan"]["claim_holds"] is False
    assert evidence["occurrence_scan"]["new_agent_facing_hits_in_degraded_not_present_in_intact"]


def test_red_the_removed_sentence_still_present_in_degraded_turns_claim_holds_false(tmp_path: Path) -> None:
    """A second, distinct red case: the mutation never actually removed the
    sentence (a no-op edit). claim_holds must go False via removed_sentence_
    confirmed_absent_in_degraded, not be masked by the other two checks."""
    inventory_path = _write_inventory(tmp_path, [_AGENT_FACING])
    intact_root, degraded_root = tmp_path / "intact", tmp_path / "degraded"
    _write_tree(intact_root, {_AGENT_FACING: f"intro\n{_SENTENCE}\ntrailer\n"})
    _write_tree(degraded_root, {_AGENT_FACING: f"intro\n{_SENTENCE}\ntrailer\n"})
    out_path = tmp_path / "evidence.json"
    exit_code = smc.main([
        "--inventory", str(inventory_path), "--intact-root", str(intact_root),
        "--degraded-root", str(degraded_root),
        "--intact-diagnose", str(_write_diagnose_stub(tmp_path / "intact-diag.json")),
        "--degraded-diagnose", str(_write_diagnose_stub(tmp_path / "degraded-diag.json")),
        "--removed-text", _SENTENCE, "--out", str(out_path),
    ])
    assert exit_code == 1
    evidence = json.loads(out_path.read_text(encoding="utf-8"))
    assert evidence["occurrence_scan"]["claim_holds"] is False
    assert evidence["occurrence_scan"]["removed_sentence_confirmed_absent_in_degraded"] is False
