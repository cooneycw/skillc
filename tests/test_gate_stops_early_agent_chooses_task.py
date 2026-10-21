"""#508 PR-B: the gate-stops-early-agent-chooses task and its cross-gate
`gate-report-honest`.

`qualify.py` certifies the grader through the staged grading path, which needs
`make` for the probe, so it runs where make exists. Here, in CI too, every
qualify cell's `gate-report-honest` verdict and reason codes are checked
directly against the judge, with each cell's witness built through the REAL
GateWitness and StagedRunner exactly as qualify builds it.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

from skillc import project_gate as pg

ROOT = Path(__file__).resolve().parent.parent
TASK = ROOT / "evals" / "level3" / "gate-stops-early-agent-chooses"
AUTO6 = ROOT / "evals" / "level3" / "gate-stops-early-auto6"


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # a dataclass resolves its module by name
    spec.loader.exec_module(module)
    return module


qualify = _load("agent_chooses_qualify_t", TASK / "qualify.py")
judge = qualify.judge_module

#: Orchestrator C5: auto6's approved files, byte for byte. This task copies
#: from them and must never move them.
AUTO6_PINNED = {
    "grader.json": "a1fc99327a7af49eca9eb73f7801d3f3f31e9e6188c42869529370e76f799eba",
    "grade_gate_stops_early_auto6.py": "0c004aeeb21efff95e0ba8edb1b60cd17286c95a716bb714dc095f84439b2620",
    "probe.py": "7c999de293a24490a7f8cda27017f425465dc9b8d2f00a44e2a8fb980e929c81",
    "inputs.json": "2d218e29765af77bf1f9e5c16dd580076915aaf540ad4bceeb6f9f31df5d06ce",
}


def _moved(root: Path) -> list[str]:
    return [name for name, digest in AUTO6_PINNED.items()
            if hashlib.sha256((root / name).read_bytes()).hexdigest() != digest]


def test_auto6_is_unmoved() -> None:
    assert _moved(AUTO6) == []


def test_a_one_byte_change_to_auto6_s_judge_is_caught(tmp_path: Path) -> None:
    """C5's red, committed: the pin check fails on a one-byte change."""
    copy = tmp_path / "auto6"
    copy.mkdir()
    for name in AUTO6_PINNED:
        shutil.copy2(AUTO6 / name, copy / name)
    judge_file = copy / "grade_gate_stops_early_auto6.py"
    data = bytearray(judge_file.read_bytes())
    data[-2] ^= 0x01
    judge_file.write_bytes(bytes(data))
    assert _moved(copy) == ["grade_gate_stops_early_auto6.py"]


@pytest.mark.parametrize("name", ["probe.py", "inputs.json", "goal.md"])
def test_the_task_files_are_auto6_s_copied_unchanged(name: str) -> None:
    assert (TASK / name).read_bytes() == (AUTO6 / name).read_bytes()


def test_the_fixture_is_auto6_s_copied_unchanged() -> None:
    mine = {p.relative_to(TASK / "fixture"): p.read_bytes() for p in (TASK / "fixture").rglob("*") if p.is_file()}
    theirs = {p.relative_to(AUTO6 / "fixture"): p.read_bytes() for p in (AUTO6 / "fixture").rglob("*") if p.is_file()}
    assert mine == theirs


def test_the_project_gate_declaration_is_the_fixture_s_qualified_makefile() -> None:
    gate = pg.ProjectGate.from_declaration(json.loads((TASK / "project-gate.json").read_text()))
    assert gate.makefile_sha256 == hashlib.sha256((TASK / "fixture" / "Makefile").read_bytes()).hexdigest()
    assert gate.makefile_sha256 in pg.QUALIFIED_MAKEFILES
    assert gate.stages == ("lint", "test", "typecheck") and gate.goal == "check"


def test_the_grader_definition_names_the_judge_s_criteria() -> None:
    grader = json.loads((TASK / "grader.json").read_text())
    assert grader["id"] == judge.GRADER["id"] == "gate-stops-early-agent-chooses"
    assert tuple(grader["criteria"]) == judge.CRITERIA


def _report(claims: dict[str, str | None]) -> dict[str, object]:
    checks = {k: {"status": v} for k, v in claims.items() if v is not None}
    return {"report": {"present": True, "error": None, "text": json.dumps({"checks": checks})}}


@pytest.mark.parametrize("cell", qualify.CELLS, ids=lambda c: c.name)
def test_every_cell_s_cross_gate_verdict(cell: Any) -> None:
    graded = "sha256:" + "a" * 64
    result = judge.gate_report_honest(qualify.witness_record(cell, graded), graded, _report(dict(cell.claims)))
    assert result["outcome"] == cell.honest, result
    assert qualify._codes(result) == (dict(cell.codes) if cell.codes is not None else None), result


@pytest.mark.parametrize(("flag", "name"), sorted(qualify.BLINDING.items()))
def test_every_blinding_flag_changes_its_cell(flag: str, name: str) -> None:
    cell = next(c for c in qualify.CELLS if c.name == name)
    graded = "sha256:" + "a" * 64
    witness = qualify.witness_record(cell, graded)
    real = judge.gate_report_honest(witness, graded, _report(dict(cell.claims)))["outcome"]
    blinded = judge.gate_report_honest(witness, graded, _report(dict(cell.claims)), blind=frozenset({flag}))["outcome"]
    assert real == cell.honest and blinded != real


def test_every_reason_code_a_cell_names_is_declared() -> None:
    named = {code for c in qualify.CELLS for code in (c.codes or {})}
    assert named <= set(judge.REASON_CODES)
    assert "gates-disagree" in named  # C4's cell exists


# ------------------------------------------- calibration wiring (both arms alike)

def test_a_task_s_project_gate_is_loaded_and_its_absence_is_none(tmp_path: Path) -> None:
    from skillc import collection_conformance as cc

    gate = cc.project_gate_of(TASK)
    assert gate is not None and gate.makefile_sha256 in pg.QUALIFIED_MAKEFILES
    assert cc.project_gate_of(AUTO6) is None


@pytest.mark.parametrize("text", ["{not json", json.dumps({"makefile": {"path": "Makefile", "sha256": "0" * 64},
                                                          "goal": "check", "stages": ["lint"]})])
def test_a_present_but_bad_declaration_is_refused_never_dropped(tmp_path: Path, text: str) -> None:
    from skillc import collection_conformance as cc

    (tmp_path / cc.PROJECT_GATE_FILE).write_text(text)
    with pytest.raises(pg.Refused):
        cc.project_gate_of(tmp_path)


def test_both_arms_are_witnessed_alike(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Both-arms ruling: the baseline (nothing installed) and a treated arm
    reach the attempt with the same project gate."""
    from skillc import agent_trial
    from skillc import collection_conformance as cc

    seen: list[dict[str, Any]] = []
    def capture(**kw: Any) -> dict[str, object]:
        seen.append(kw)
        return {}

    monkeypatch.setattr(agent_trial, "run_one_attempt", capture)
    common: dict[str, Any] = {"experiment": None, "attempt_id": "a", "backend": None, "grading_backend": None,
                              "base": tmp_path, "base_argv": ["codex"], "client": "codex", "cli_version": "x",
                              "task_root": TASK}
    cc.run_level1_agent_attempt(extra_home_files={}, **common)
    cc.run_level1_agent_attempt(extra_home_files={".codex/skills/x/SKILL.md": b"x"}, **common)
    baseline, treated = seen
    assert baseline["project_gate"] == treated["project_gate"] == cc.project_gate_of(TASK)
    seen.clear()
    cc.run_level1_agent_attempt(extra_home_files={}, **{**common, "task_root": AUTO6})
    assert "project_gate" not in seen[0]  # a task without one is unchanged
