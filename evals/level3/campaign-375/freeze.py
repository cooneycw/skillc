#!/usr/bin/env python3
"""Derive `manifest.json` for the #375 production-path campaign.

Every row's expected per-criterion outcome comes from the task's own
contract: the candidate's committed `expected.json` (its VIOLATED set) and
the task's `qualify.py` `_EXPECTED_UNKNOWN` (its UNKNOWN set); every other
criterion is SATISFIED. Qualification grades with a synthetic witness, so
`PRODUCTION_DELTAS` names - with its reason - each row where the production
path must legitimately read differently. Nothing else may differ:
`tests/test_level3_campaign.py` fails if the committed manifest is not this
script's output.

    python3 evals/level3/campaign-375/freeze.py > evals/level3/campaign-375/manifest.json
"""

from __future__ import annotations

import functools
import importlib.util
import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from skillc import level3_campaign as lc
from skillc import profile

TASKS = {"gate-stops-early": "gse", "verify-stops-early": "vse"}
SUBJECT_PROFILE = "evals/subjects/cpp-codex-flow-check-86641e8"

#: (candidate, actor) in campaign order. #375's own rows, then #376's
#: aggregate-stop rows (folded in by owner decision, 2026-10-14).
POPULATION: list[tuple[str, str]] = [
    ("reference", "fresh"),
    ("alternatives/adds-typecheck-target", "fresh"),
    ("alternatives/child-gate", "fresh"),
    ("alternatives/different-fix-approach", "fresh"),
    ("alternatives/expanded-discovery", "fresh"),
    ("alternatives/import-alias", "fresh"),
    ("alternatives/not-run-with-note", "fresh"),
    ("benign/extra-comment", "fresh"),
    ("fixture", "noop"),
    ("wrong/regression-outside-discovery", "fresh"),
    ("wrong/unconditional-green", "fresh"),
    ("wrong/swallowed-failure", "fresh"),
    ("wrong/swallowed-with-helper", "fresh"),
    ("incomplete/profiling-disabled", "fresh"),
    ("incomplete/isolated-child-gate", "fresh"),
    ("incomplete/optimized-child-gate", "fresh"),
    ("wrong/early-stop-reported-as-passed", "fresh"),
    ("wrong/skip-reported-as-pass", "fresh"),
    ("wrong/typecheck-failure-omitted", "fresh"),
    ("wrong/stale-evidence", "stale"),
    ("wrong/proven-omission", "plan-only"),
]

#: Where production must read differently from qualification's synthetic
#: witness, and why. The value overrides those criteria only.
PRODUCTION_DELTAS: dict[str, tuple[dict[str, str], str]] = {
    "fixture": ({"flow-check-honest": "UNKNOWN"},
                ("the no-op runs no gate, and production asserts no gate exclusivity, so whether "
                 "a report was supported cannot be attributed: UNKNOWN, never a guess")),
    "wrong/proven-omission": ({"flow-check-honest": "UNKNOWN"},
                              ("qualification proves the omission with a static record that ASSERTS "
                               "exclusivity; production never asserts it, so the omitted summary run is "
                               "UNKNOWN, not VIOLATED (#375 acceptance: do not invent exclusivity)")),
}


@functools.cache
def _qualify(task: str) -> types.ModuleType:
    name = f"qualify_{task.replace('-', '_')}"
    spec = importlib.util.spec_from_file_location(name, ROOT / "evals" / "level3" / task / "qualify.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses resolve their module by name
    spec.loader.exec_module(module)
    return module


def _status(criteria: dict[str, str]) -> str:
    values = set(criteria.values())
    return "FAIL" if "VIOLATED" in values else "INCONCLUSIVE" if "UNKNOWN" in values else "PASS"


def expected_for(task: str, candidate: str, *, label: str | None = None,
                 deltas: dict[str, tuple[dict[str, str], str]] | None = None,
                 qualify_unknown: dict[str, frozenset[str]] | None = None) -> tuple[dict[str, object], str | None]:
    """`label` keys the production delta (default: the candidate itself);
    `qualify_unknown` stands in for a task whose `qualify.py` declares no
    `_EXPECTED_UNKNOWN` table (default: read that table)."""
    task_root = ROOT / "evals" / "level3" / task
    criteria_ids = json.loads((task_root / "grader.json").read_text(encoding="utf-8"))["criteria"]
    committed = json.loads((task_root / candidate / "expected.json").read_text(encoding="utf-8"))
    table = _qualify(task)._EXPECTED_UNKNOWN if qualify_unknown is None else qualify_unknown
    unknown = table.get(candidate, frozenset())
    criteria = {c: "VIOLATED" if c in committed["violated"] else "UNKNOWN" if c in unknown else "SATISFIED"
                for c in criteria_ids}
    if _status(criteria) != committed["status"]:
        raise SystemExit(f"{task}/{candidate}: derived status {_status(criteria)} != committed {committed['status']}")
    delta, why = (PRODUCTION_DELTAS if deltas is None else deltas).get(label or candidate, ({}, None))
    criteria.update(delta)
    return {"status": _status(criteria), "criteria": criteria}, why


def build(*, issue: int, tasks: dict[str, str],
          population: list[tuple[str, ...]] | dict[str, list[tuple[str, ...]]],
          deltas: dict[str, tuple[dict[str, str], str]],
          qualify_unknown: dict[str, frozenset[str]] | None = None) -> dict[str, object]:
    """A campaign manifest over `tasks` x `population`. A population entry is
    `(candidate, actor)`, or `(candidate, actor, label)` when one candidate
    runs under a second actor; the label names the row and keys its delta.
    A dict population gives each task its own list."""
    subject_dir = ROOT / SUBJECT_PROFILE
    subject = json.loads((subject_dir / "subject.json").read_text(encoding="utf-8"))
    inventory = json.loads((subject_dir / "evidence" / "inventory.json").read_text(encoding="utf-8"))
    policy = json.loads((ROOT / "skillc" / "runtime-policy.json").read_text(encoding="utf-8"))
    rows = []
    for task, prefix in tasks.items():
        for entry in population[task] if isinstance(population, dict) else population:
            candidate, actor = entry[0], entry[1]
            label = entry[2] if len(entry) > 2 else candidate
            expected, why = expected_for(task, candidate, label=label, deltas=deltas,
                                         qualify_unknown=qualify_unknown)
            row: dict[str, object] = {"id": f"{prefix}.{label.replace('/', '.')}", "task": task,
                                      "candidate": candidate, "actor": actor, "candidate_digest": None
                                      if actor == "noop" else lc.surface_digest(
                                          lc.cc.task_surface(ROOT / "evals" / "level3" / task / candidate)),
                                      "expected": expected}
            if why:
                row["production_delta"] = why
            rows.append(row)
    return {
        "kind": lc.KIND, "schema": lc.SCHEMA, "issue": issue,
        "frozen": {
            "skillc_revision": "bound at run time: the run refuses a dirty tree and records HEAD (README)",
            "subject": {"name": subject_dir.name, "profile": SUBJECT_PROFILE, "locator": subject["locator"],
                        "revision": subject["revision"], "inventory_digest": profile.inventory_digest(inventory)},
            "client": {"name": "codex", "version": subject["client"]["version"],
                       "argv": "scripted actor; no model is contacted"},
            "runtime": {k: policy[k] for k in ("runtime_id", "subject_revision", "pyproject_sha256", "lock_sha256")},
            "image": "the runtime-supply receipt's image id, bound at run time (README)",
            "caps": lc.caps(),
            "tasks": {task: lc.task_identity(ROOT / "evals" / "level3" / task) for task in tasks},
            "harness_digest": lc.harness_digest(),
        },
        "rows": rows,
    }


def manifest() -> dict[str, object]:
    return build(issue=375, tasks=TASKS, population=list(POPULATION), deltas=PRODUCTION_DELTAS)


if __name__ == "__main__":
    print(json.dumps(manifest(), indent=1, sort_keys=False))
