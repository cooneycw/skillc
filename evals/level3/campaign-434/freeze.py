#!/usr/bin/env python3
"""Derive `manifest.json` for the #434 production-path campaign (PR 3).

Every PR 1 qualify candidate of `evals/level3/flow-auto-necessity` is a row:

- SCORED when its committed witness state is `no-runs`, the state a live
  attempt reproduces. Its expected per-criterion outcome is the candidate's own
  `expected.json`: its `violated` set VIOLATED, its `unknown` set UNKNOWN, every
  other criterion SATISFIED. No production delta is declared, because none has
  been measured: the 2b wiring test replayed eleven of these through the live
  path and each matched as committed. A mismatch is evidence to investigate,
  never a reason to relabel.
- OBSERVED when its witness state is one a live attempt cannot reproduce from
  qualify's synthetic witness (a gate run's own result, no record at all, or
  asserted exclusivity). Nothing is frozen; the run records what happened
  (orchestrator ruling).

Three GUARD rows replay one passing candidate with only the guard calls
changed, and expect the credit gate's reason.

`tests/test_fixture_campaign.py` fails if the committed manifest is not this
script's output.

    python3 evals/level3/campaign-434/freeze.py > evals/level3/campaign-434/manifest.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from skillc import fixture_campaign as fc
from skillc import level3_campaign as lc
from skillc import profile

TASK_ROOT = ROOT / "evals" / "level3" / fc.TASK
SUBJECT_PROFILE = "evals/subjects/cpp-codex-flow-auto-86641e8"
CRITERIA = json.loads((TASK_ROOT / "grader.json").read_text(encoding="utf-8"))["criteria"]
#: The candidate the guard rows replay: a clean pass with no git operation, so
#: the only difference between the three is the guard calls.
GUARD_CANDIDATE = "pass/clean-cites-commit-only"


def _row_id(candidate: str) -> str:
    placement, name = candidate.split("/")
    return f"{placement[:4]}.{name}"


def _candidates() -> list[str]:
    return sorted(p.relative_to(TASK_ROOT / "candidates").as_posix()
                  for p in (TASK_ROOT / "candidates").glob("*/*") if p.is_dir())


def _digest(candidate: str) -> str:
    row = fc.Row(candidate, "scored", candidate, "top-level", "", None, {}, None)
    return fc.candidate_digest(fc.candidate_files(TASK_ROOT, row))


def _expected(candidate: str) -> dict[str, Any]:
    committed = json.loads((TASK_ROOT / "candidates" / candidate / "expected.json").read_text(encoding="utf-8"))
    criteria = {c: "SATISFIED" for c in CRITERIA}
    criteria.update({c: "VIOLATED" for c in committed["violated"]})
    criteria.update({c: "UNKNOWN" for c in committed["unknown"]})
    return {"status": committed["status"], "criteria": criteria}


def rows() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for candidate in _candidates():
        witness = json.loads((TASK_ROOT / "candidates" / candidate / "actions.json").read_text(
            encoding="utf-8")).get("witness", "no-runs")
        row: dict[str, Any] = {"id": _row_id(candidate), "candidate": candidate, "guard": "top-level",
                               "candidate_digest": _digest(candidate)}
        if witness in fc.OBSERVED_WITNESSES:
            row.update(kind="observed", witness=witness)
        else:
            row.update(kind="scored", expected=_expected(candidate))
        out.append(row)
    for mode in ("nested", "suspected", "none"):
        out.append({"id": f"guard.{mode}", "kind": "guard", "candidate": GUARD_CANDIDATE, "guard": mode,
                    "candidate_digest": _digest(GUARD_CANDIDATE),
                    "expected": {"blocked_reason": fc.GUARD_REASONS[mode]}})
    return out


def manifest() -> dict[str, Any]:
    profile_dir = ROOT / SUBJECT_PROFILE
    inventory = json.loads((profile_dir / "evidence" / "inventory.json").read_text(encoding="utf-8"))
    subject = json.loads((profile_dir / "subject.json").read_text(encoding="utf-8"))
    policy = json.loads((ROOT / "skillc" / "runtime-policy.json").read_text(encoding="utf-8"))
    return {
        "kind": fc.KIND, "schema": fc.SCHEMA, "issue": 434,
        "frozen": {
            "skillc_revision": "bound at run time: the run refuses a dirty tree and records HEAD",
            "subject": {"name": "cpp-codex-flow-auto-86641e8", "profile": SUBJECT_PROFILE,
                        "locator": subject["locator"], "revision": subject["revision"],
                        "inventory_digest": profile.inventory_digest(inventory)},
            "client": {"name": "codex", "version": subject["client"]["version"],
                       "argv": "scripted actor; no model is contacted"},
            "runtime": {k: policy[k] for k in ("runtime_id", "subject_revision", "pyproject_sha256", "lock_sha256")},
            "image": "the runtime-supply receipt's image id, bound at run time",
            "caps": lc.caps(),
            "task": fc.task_identity(TASK_ROOT),
            "harness_digest": fc.harness_digest(),
        },
        "rows": rows(),
    }


if __name__ == "__main__":
    print(json.dumps(manifest(), indent=1))
