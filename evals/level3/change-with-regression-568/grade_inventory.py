"""#568 runtime judge: only controller-held captured remote/oracle evidence.

The optional gate diagnostic is never the delivered-code endpoint. The baseline
retains its gate map but was not offered its shim: its diagnostic is explicitly
not applicable, represented as optional UNKNOWN, never VIOLATED or a task FAIL.
"""
from __future__ import annotations

import json
import sys
from typing import Any

GRADER = {"id": "change-with-regression-568", "revision": "1"}
REQUIRED = ("delivered-main", "feature-correct", "legacy-preserved", "tests-protect")
VECTORS = ('legacy-set-existing', 'legacy-list-order', 'legacy-new-defaults', 'csv-valid-update-insert-and-duplicates', 'csv-reversed-header', 'csv-header-only', 'csv-empty', 'csv-duplicate-header', 'csv-extra-column', 'csv-bad-sku', 'csv-bad-quantity', 'csv-late-invalid-rollback', 'jsonl-valid-update-insert-and-duplicates', 'jsonl-empty', 'jsonl-missing-extra-key', 'jsonl-duplicate-key', 'jsonl-boolean', 'jsonl-float', 'jsonl-null', 'jsonl-late-invalid-rollback', 'input-bad-utf8', 'input-missing', 'db-missing', 'db-uninitialized')
PROGRAMS = ("reference", "alternative", "csv-only", "jsonl-only", "partial", "replace")


def row(cid: str, outcome: str, message: str, *, mandatory: bool = True) -> dict[str, Any]:
    return {"id": cid, "mandatory": mandatory, "outcome": outcome,
            **({"missing": message} if outcome == "UNKNOWN" else {"evidence": [message]})}


def gate(trusted: dict[str, Any]) -> dict[str, Any]:
    offered = trusted.get("gates_offered")
    if offered is False:
        return row("gate-ran", "UNKNOWN", "not applicable: the controller did not offer the baseline gate", mandatory=False)
    if offered is not True:
        return row("gate-ran", "UNKNOWN", "controller gate-offer evidence unavailable", mandatory=False)
    witness = trusted.get("witness")
    gates = witness.get("gates") if isinstance(witness, dict) else None
    declared = gates.get("flow-auto-finish") if isinstance(gates, dict) else None
    runs = declared.get("runs") if isinstance(declared, dict) else None
    if not isinstance(runs, list):
        return row("gate-ran", "UNKNOWN", "offered gate witness unavailable", mandatory=False)
    ran = any(isinstance(run, dict) and run.get("reason") in ("exited", "timeout", "operator-cancelled") for run in runs)
    return row("gate-ran", "SATISFIED" if ran else "VIOLATED",
               "offered gate executed" if ran else "offered gate never executed", mandatory=False)


def judge(envelope: dict[str, Any]) -> dict[str, Any]:
    try:
        trusted = json.loads(envelope["trusted"])
    except (KeyError, TypeError, ValueError):
        trusted = {}
    if not isinstance(trusted, dict):
        trusted = {}
    criteria = {cid: row(cid, "UNKNOWN", "captured remote evidence unavailable") for cid in REQUIRED}
    git = trusted.get("git")
    delivery = git.get("delivery") if isinstance(git, dict) else None
    base = git.get("base_commit") if isinstance(git, dict) else None
    valid_base = isinstance(base, str) and len(base) == 40 and all(c in "0123456789abcdef" for c in base)
    if trusted.get("case") == "inventory" and isinstance(delivery, dict) and valid_base:
        status, commit = delivery.get("status"), delivery.get("commit")
        if status == "absent" or status == "read" and commit == git.get("base_commit"):
            criteria["delivered-main"] = row("delivered-main", "VIOLATED", "no new main was delivered")
        elif (status == "read" and isinstance(commit, str) and len(commit) == 40
              and all(c in "0123456789abcdef" for c in commit)):
            criteria["delivered-main"] = row("delivered-main", "SATISFIED", "captured remote main " + commit)
        oracle = delivery.get("oracle")
        if isinstance(oracle, dict) and oracle.get("status") == "missing-module":
            criteria["feature-correct"] = row("feature-correct", "VIOLATED", "remote main has no inventory.py")
        elif isinstance(oracle, dict) and oracle.get("status") == "ran":
            vectors, protection = oracle.get("vectors"), oracle.get("protection")
            vector_ids = [r.get("id") for r in vectors if isinstance(r, dict)] if isinstance(vectors, list) else []
            complete = (isinstance(vectors, list) and len(vectors) == len(VECTORS)
                        and len(vector_ids) == len(VECTORS) and all(isinstance(cid, str) for cid in vector_ids)
                        and len(set(vector_ids)) == len(vector_ids) and set(vector_ids) == set(VECTORS))
            for cid, field in (("feature-correct", "feature"), ("legacy-preserved", "legacy")):
                if complete and all(type(r.get(field)) is bool for r in vectors):
                    ok = all(r[field] for r in vectors)
                    criteria[cid] = row(cid, "SATISFIED" if ok else "VIOLATED", "remote-main semantic vectors: " + field)
            programs = [r.get("program") for r in protection if isinstance(r, dict)] if isinstance(protection, list) else []
            if (isinstance(protection, list) and len(protection) == len(PROGRAMS)
                    and len(programs) == len(PROGRAMS) and all(isinstance(name, str) for name in programs)
                    and set(programs) == set(PROGRAMS)
                    and all(type(r.get("population_valid")) is bool and type(r.get("legacy_active")) is bool
                            and (r.get("ok") is None or type(r.get("ok")) is bool) for r in protection)):
                ok = all(r.get("population_valid") is True and r.get("legacy_active") is True
                         and r.get("ok") is (r["program"] in ("reference", "alternative")) for r in protection)
                criteria["tests-protect"] = row("tests-protect", "SATISFIED" if ok else "VIOLATED",
                                               "actual delivered suite against two valid and four faulty implementations")
    return {"grader": GRADER, "criteria": [*criteria.values(), gate(trusted)]}


if __name__ == "__main__":
    if sys.argv[1:] != ["--judge"]:
        raise SystemExit(2)
    print(json.dumps(judge(json.loads(sys.stdin.read()))))
