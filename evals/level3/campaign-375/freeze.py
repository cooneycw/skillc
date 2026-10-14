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


def expected_for(task: str, candidate: str) -> tuple[dict[str, object], str | None]:
    task_root = ROOT / "evals" / "level3" / task
    criteria_ids = json.loads((task_root / "grader.json").read_text(encoding="utf-8"))["criteria"]
    committed = json.loads((task_root / candidate / "expected.json").read_text(encoding="utf-8"))
    unknown = _qualify(task)._EXPECTED_UNKNOWN.get(candidate, frozenset())
    criteria = {c: "VIOLATED" if c in committed["violated"] else "UNKNOWN" if c in unknown else "SATISFIED"
                for c in criteria_ids}
    if _status(criteria) != committed["status"]:
        raise SystemExit(f"{task}/{candidate}: derived status {_status(criteria)} != committed {committed['status']}")
    delta, why = PRODUCTION_DELTAS.get(candidate, ({}, None))
    criteria.update(delta)
    return {"status": _status(criteria), "criteria": criteria}, why


def manifest() -> dict[str, object]:
    subject_dir = ROOT / SUBJECT_PROFILE
    subject = json.loads((subject_dir / "subject.json").read_text(encoding="utf-8"))
    inventory = json.loads((subject_dir / "evidence" / "inventory.json").read_text(encoding="utf-8"))
    policy = json.loads((ROOT / "skillc" / "runtime-policy.json").read_text(encoding="utf-8"))
    rows = []
    for task, prefix in TASKS.items():
        for candidate, actor in POPULATION:
            expected, why = expected_for(task, candidate)
            row: dict[str, object] = {"id": f"{prefix}.{candidate.replace('/', '.')}", "task": task,
                                      "candidate": candidate, "actor": actor, "expected": expected}
            if why:
                row["production_delta"] = why
            rows.append(row)
    return {
        "kind": lc.KIND, "schema": lc.SCHEMA, "issue": 375,
        "frozen": {
            "skillc_revision": "bound at run time: the run refuses a dirty tree and records HEAD (README)",
            "subject": {"name": subject_dir.name, "profile": SUBJECT_PROFILE, "locator": subject["locator"],
                        "revision": subject["revision"], "inventory_digest": profile.inventory_digest(inventory)},
            "client": {"name": "codex", "version": subject["client"]["version"],
                       "argv": "scripted actor; no model is contacted"},
            "runtime": {k: policy[k] for k in ("runtime_id", "subject_revision", "pyproject_sha256", "lock_sha256")},
            "image": "the runtime-supply receipt's image id, bound at run time (README)",
            "caps": {"per_attempt_seconds": 900, "gate_seconds": lc.GATE_SECONDS, "agent_network": "none",
                     "container": "DockerBackend defaults: --memory 1g --memory-swap 1g --pids-limit 256 --cpus 1.0"},
            "tasks": {task: lc.task_identity(ROOT / "evals" / "level3" / task) for task in TASKS},
            "harness_digest": lc.harness_digest(),
        },
        "rows": rows,
    }


if __name__ == "__main__":
    print(json.dumps(manifest(), indent=1, sort_keys=False))
