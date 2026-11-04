"""Fixture-specific safe snapshot adapter, independent of actor claims/logs."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from skillc import git_snapshot as gs
from skillc import verify


def grade(snapshot: Path, seed: str, base: Path) -> dict[str, Any]:
    try:
        remote = gs.GitDir(gs.SafeTree(snapshot), "")
        remote.check_plain()
        original = remote.commit_files(seed)
        refs = remote.refs()
        delivered = refs.get("refs/heads/delivered")
        if delivered is None:
            return {"status": "FAIL", "reason": "delivered-ref-absent", "oracle_executed": False}
        files = remote.commit_files(delivered)
        history = remote.reachable([delivered])
        workers = [refs.get("refs/heads/" + role) for role in ("worker-a", "worker-b")]
        # Cherry-picks preserve worker content, not the second worker's commit
        # identity. Bind each worker's changed source bytes to the final tree.
        correct = seed in history and set(files) == set(original)
        paths = ("src/subtotal.py", "src/tax.py")
        for worker, path in zip(workers, paths, strict=True):
            if worker is None:
                correct = False
                continue
            output = remote.commit_files(worker)
            correct = (correct and seed in remote.reachable([worker])
                       and output.get(path) == files.get(path))
        correct = correct and all(files[path] == original[path] for path in original if path not in paths)
        selected = [(path, data, False) for path, (mode, data) in files.items()
                    if path in (*paths, "src/quote.py") and mode == "100644"]
        correct = correct and len(selected) == 3
        if not selected:
            return {"status": "FAIL", "reason": "delivered-source-absent", "oracle_executed": False}
        grader = verify.GraderDef.load(Path(__file__).resolve().parent)
        result = verify.grade_files(grader, selected, base, trusted_observation=json.dumps({
            "task": "wave-rehearsal-quote:1", "delivery": "SATISFIED" if correct else "VIOLATED"
        }).encode())
        return {"status": result.status, "oracle_executed": True, "containment": result.containment}
    except (gs.Unreadable, OSError, verify.Refused):
        return {"status": "UNKNOWN", "reason": "delivery-observation-unavailable", "oracle_executed": False}
