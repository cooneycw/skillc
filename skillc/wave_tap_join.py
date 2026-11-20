"""A DIAGNOSTIC-ONLY join of retained tap operations (#626).

Owner ruling 2026-11-20 (option A, #626 comment 7039734091): the #620 PR-B
task-protocol client journal is the verdict source. The Q15 A helper tap is
kept as a CPP-arm corroboration journal, diagnostic only. So this join takes
no `WaveEvidence` and returns none: it reports what the tap retained BESIDE
the verdict and cannot feed it. Its custody, refusal and UNKNOWN-coverage
rules are unchanged. The caller supplies the digest receipt held by its
controller, not actor data. Refusals stay distinct; they never become
successful acks.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from . import live_wave as lw
from .git_snapshot import SafeTree, Unreadable


#: What this diagnostic does to the primary verdict, stated in every report.
VERDICT_EFFECT = "none (diagnostic only; #626 ruling 7039734091)"


def corroboration(plan: lw.WavePlan, collection: dict[str, Any],
                  journal_root: Path) -> dict[str, Any]:
    """The tap's retained operations and refusals per planned role, and
    whether its coverage is COMPLETE. Never a verdict input."""
    complete = False
    rows: dict[str, list[dict[str, Any]]] = {role.role: [] for role in plan.roles}
    refusal_sequences: set[int] = set()
    expected = {role.role: {"wave_id": plan.wave_id, **{key: value
                for key, value in asdict(role).items() if key != "required_artifacts"}}
                for role in plan.roles}
    try:
        raw, _ = SafeTree(journal_root).read("journal.json", 16 * 1024 * 1024)
        if hashlib.sha256(raw).hexdigest() != collection.get("journal_sha256"):
            raise ValueError("journal receipt mismatch")
        document = json.loads(raw)
        bindings = document["bindings"]
        if (document["version"] != 1 or len(bindings) != len(expected)
                or {b["role"]: b for b in bindings} != expected):
            raise ValueError("tap population binding mismatch")
        complete = collection.get("status") == "COMPLETE" and not document["unknown"]
        for row in document["rows"]:
            role = row["role"]
            base = expected[role]
            if any(type(row[key]) is not type(value) or row[key] != value for key, value in base.items()):
                raise ValueError("journal binding changed")
            if row["kind"] == "operation":
                if row["operation"] not in {"ack", "complete"}:
                    raise ValueError("invalid successful operation")
                rows[role].append({**base, "elapsed": row["elapsed"], "op": row["operation"]})
            elif row["kind"] == "refusal":
                if row["reason"] in {"control-or-unknown-fields", "operation-not-allowed",
                                     "stale-turn", "wrong-assignment-identity"}:
                    # live_wave's existing invalid-operation rule makes this
                    # positive controller-observed refusal FAIL. It neither
                    # alleges a successful helper operation nor task success.
                    rows[role].append({**base, "elapsed": row["elapsed"], "op": "refused-protocol"})
                    refusal_sequences.add(row["seq"])
                else:
                    complete = False
            elif row["kind"] == "unavailable":
                complete = False
    except (OSError, Unreadable, ValueError, KeyError, TypeError):
        complete = False
        rows = {role.role: [] for role in plan.roles}
        refusal_sequences.clear()
    # Positive refusals have independent custody so losing operation coverage
    # does not erase a known protocol violation. Either retained witness can
    # establish the refusal; missing either population still prevents PASS.
    try:
        raw, _ = SafeTree(journal_root).read("refusals.json", 16 * 1024 * 1024)
        if hashlib.sha256(raw).hexdigest() != collection.get("refusal_sha256"):
            raise ValueError("refusal receipt mismatch")
        document = json.loads(raw)
        if (document["version"] != 1 or len(document["bindings"]) != len(expected)
                or {b["role"]: b for b in document["bindings"]} != expected):
            raise ValueError("refusal binding mismatch")
        for row in document["rows"]:
            role = row["role"]
            base = expected[role]
            if row["kind"] != "refusal" or any(row[key] != value for key, value in base.items()):
                raise ValueError("refusal identity changed")
            if row["reason"] in {"control-or-unknown-fields", "operation-not-allowed",
                                 "stale-turn", "wrong-assignment-identity"}:
                if row["seq"] not in refusal_sequences:
                    rows[role].append({**base, "elapsed": row["elapsed"], "op": "refused-protocol"})
            else:
                complete = False
    except (OSError, Unreadable, ValueError, KeyError, TypeError):
        complete = False
    roles: dict[str, dict[str, Any]] = {}
    for role in plan.roles:
        events = sorted(rows[role.role], key=lambda event: event["elapsed"])
        payload = b"".join(json.dumps(event, sort_keys=True).encode() + b"\n" for event in events)
        roles[role.role] = {"ops": [event["op"] for event in events],
                            "sha256": hashlib.sha256(payload).hexdigest()}
    return {"status": "COMPLETE" if complete else "UNKNOWN", "roles": roles,
            "verdict_effect": VERDICT_EFFECT}
