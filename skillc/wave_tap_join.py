"""Join retained tap operations to the existing independent wave verdict input.

The caller supplies the digest receipt held by its controller, not actor data.
Refusals stay distinct protocol violations; they never become successful acks.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from . import live_wave as lw
from .git_snapshot import SafeTree, Unreadable


def protocol_evidence(plan: lw.WavePlan, evidence: lw.WaveEvidence,
                      collection: dict[str, Any], journal_root: Path) -> lw.WaveEvidence:
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
                or {b["role"]: b for b in bindings} != expected or evidence.wave_id != plan.wave_id):
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
    roles = []
    for role in evidence.roles:
        events = sorted(rows.get(role.role, []), key=lambda event: event["elapsed"])
        payload = b"".join(json.dumps(event, sort_keys=True).encode() + b"\n" for event in events)
        protocol = lw.Blob(payload, hashlib.sha256(payload).hexdigest()) if payload else None
        roles.append(replace(role, protocol=protocol, capture_complete=role.capture_complete and complete))
    return replace(evidence, roles=tuple(roles))
