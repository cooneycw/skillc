"""#271's production-path campaign manifest (`evals/level3/campaign-271/`).

It runs through the same harness as #375's (`skillc/level3_campaign.py`,
covered by `tests/test_level3_campaign.py`); these tests hold only what is
specific to #271's rows:

- the committed manifest is exactly the freeze script's derivation;
- every committed candidate of both tasks is a row, so a new candidate
  cannot silently stay out of the campaign;
- expectations differ from each candidate's committed contract only where a
  production delta is declared, and the stale-gate row is the one red case
  for gate freshness;
- every frozen identity holds on this tree, and a moved task identity is
  reported.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
import types
from pathlib import Path
from typing import Any

from skillc import level3_campaign as lc

ROOT = Path(__file__).resolve().parent.parent
CAMPAIGN = ROOT / "evals" / "level3" / "campaign-271"
MANIFEST = CAMPAIGN / "manifest.json"
GROUPS = ("alternatives", "benign", "wrong", "incomplete")


def _module(path: Path, name: str) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


FREEZE = _module(CAMPAIGN / "freeze.py", "campaign_271_freeze")


def _committed() -> dict[str, Any]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _candidates_on_disk(task: str, root: Path = ROOT) -> set[str]:
    task_root = root / "evals" / "level3" / task
    found = {"reference", "fixture"}
    for group in GROUPS:
        found |= {f"{group}/{p.name}" for p in (task_root / group).iterdir() if p.is_dir()}
    return found


def test_the_committed_manifest_is_the_freeze_scripts_output() -> None:
    derived = FREEZE.manifest()
    assert _committed() == derived
    # Red case: one flipped expectation is no longer the derivation.
    tampered = copy.deepcopy(derived)
    tampered["rows"][0]["expected"]["criteria"]["gate-claim-honest"] = "VIOLATED"
    assert tampered != derived


def test_every_committed_candidate_of_both_tasks_is_a_row() -> None:
    manifest = lc.load_manifest(MANIFEST)
    assert set(FREEZE.TASKS) == {r.task for r in manifest.rows}
    for task in FREEZE.TASKS:
        rows = [r for r in manifest.rows if r.task == task]
        assert {r.candidate for r in rows} == _candidates_on_disk(task), task
        # Each candidate once under its own name, plus the one stale-gate row.
        assert len(rows) == len(_candidates_on_disk(task)) + 1, task
        assert [r.actor for r in rows if r.candidate == "reference"] == ["fresh", "stale"], task


def test_red_case_a_candidate_added_on_disk_is_not_covered(tmp_path: Path) -> None:
    # The same scan over a tree that gained one candidate directory the
    # population does not list: coverage must no longer hold.
    task = next(iter(FREEZE.TASKS))
    for group in GROUPS:
        for p in (ROOT / "evals" / "level3" / task / group).iterdir():
            if p.is_dir():
                (tmp_path / "evals" / "level3" / task / group / p.name).mkdir(parents=True)
    (tmp_path / "evals" / "level3" / task / "wrong" / "added-later").mkdir()
    listed = {r.candidate for r in lc.load_manifest(MANIFEST).rows if r.task == task}
    assert listed == _candidates_on_disk(task)
    assert _candidates_on_disk(task, tmp_path) - listed == {"wrong/added-later"}


def test_expectations_differ_from_the_contract_only_where_a_delta_is_declared() -> None:
    for row in _committed()["rows"]:
        task_root = ROOT / "evals" / "level3" / row["task"]
        committed = json.loads((task_root / row["candidate"] / "expected.json").read_text(encoding="utf-8"))
        unknown = FREEZE.QUALIFY_UNKNOWN.get(row["candidate"], frozenset())
        contract = {c: "VIOLATED" if c in committed["violated"] else "UNKNOWN" if c in unknown else "SATISFIED"
                    for c in row["expected"]["criteria"]}
        changed = {c for c, v in row["expected"]["criteria"].items() if contract[c] != v}
        label = row["id"].split(".", 1)[1]
        key = next((k for k in FREEZE.PRODUCTION_DELTAS if k.replace("/", ".") == label), None)
        delta = FREEZE.PRODUCTION_DELTAS[key][0] if key else {}
        assert changed == set(delta), row["id"]
        assert ("production_delta" in row) == bool(delta), row["id"]


def test_the_stale_gate_row_is_the_only_row_expecting_a_stale_violation() -> None:
    stale = [r for r in _committed()["rows"] if r["actor"] == "stale"]
    assert [r["id"] for r in stale] == ["coe.reference-stale-gate", "roe.reference-stale-gate"]
    for row in stale:
        assert row["expected"]["status"] == "FAIL"
        assert {c for c, v in row["expected"]["criteria"].items() if v != "SATISFIED"} == {"gate-claim-honest"}


def test_frozen_identities_hold_on_this_tree() -> None:
    assert lc.check_frozen(lc.load_manifest(MANIFEST), ROOT) == []


def test_red_case_a_moved_task_identity_is_reported(tmp_path: Path) -> None:
    data = _committed()
    data["frozen"]["tasks"]["claims-outran-evidence"]["grader_digest"] = "sha256:00"
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    problems = lc.check_frozen(lc.load_manifest(path), ROOT)
    assert any("task claims-outran-evidence" in p for p in problems), problems
