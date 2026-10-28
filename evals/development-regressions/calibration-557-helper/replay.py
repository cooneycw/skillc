#!/usr/bin/env python3
"""Replay the pinned historical distinction using the existing contained verifier."""
from __future__ import annotations

import argparse
import hashlib
import json
import stat
import sys
import tempfile
from pathlib import Path

CASE = Path(__file__).resolve().parent
ROOT = CASE.parents[2]
SOURCE_DIGEST = "sha256:cec60076ac859c63000077b968288da6509da3df75460d27bff2a58ad2a3fed9"
MEMBERS = frozenset({"APPROVED.md", "CHANGES.md", "CONTRIBUTING.md", "approved.diff",
                     "report.json", "tools/verify-change.py", "docs/runbook.md"})


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def regular(path: Path) -> bytes:
    if not stat.S_ISREG(path.lstat().st_mode) or path.stat().st_size > 102400:
        raise ValueError("missing, non-regular, or oversized input")
    return path.read_bytes()


def run(case: Path, grader_root: Path | None, control: str | None) -> dict[str, object]:
    # The repository reader is trusted code; candidate and judge execution retain
    # its normal containment. No alternative execution path is supplied here.
    from skillc import verify

    source_bytes = regular(case / "source.json")
    if digest(source_bytes) != SOURCE_DIGEST:
        raise ValueError("source metadata drift")
    source = json.loads(source_bytes)
    snapshots = {}
    total = len(source_bytes)
    for name in ("bad", "good"):
        candidate = case / name
        if candidate.is_symlink() or not candidate.is_dir():
            raise ValueError("candidate is not a directory")
        population = set()
        for path in candidate.rglob("*"):
            if path.is_symlink() or not (path.is_dir() or path.is_file()):
                raise ValueError("non-regular candidate input")
            if path.is_file():
                population.add(path.relative_to(candidate).as_posix())
        if population != MEMBERS or set(source["files"][name]) != MEMBERS:
            raise ValueError("candidate population drift")
        files = []
        for member in sorted(MEMBERS):
            path = candidate / member
            data = regular(path)
            pin = source["files"][name][member]
            if len(data) != pin["size"] or digest(data) != pin["digest"]:
                raise ValueError("candidate bytes drift")
            executable = pin["mode"] == "x"
            if bool(path.stat().st_mode & stat.S_IXUSR) != executable:
                raise ValueError("candidate packaging mode drift")
            files.append((member, data, executable))
            total += len(data)
        snapshots[name] = files
    if total > source["bounds"]["public_fixture_provenance_bytes_max"]:
        raise ValueError("fixture/provenance size bound exceeded")
    archive = grader_root if grader_root is not None else ROOT / source["grader"]["path"]
    grader = verify.GraderDef.load(archive)
    expected_identity = {key: source["grader"][key] for key in ("id", "revision", "digest")}
    loaded = grader.read()
    identity = {"id": grader.id, "revision": grader.revision, "digest": grader.digest(loaded)}
    if identity != expected_identity:
        raise ValueError("historical grader drift")
    if grader.probe_timeout != 30 or grader.judge_timeout != 30:
        raise ValueError("grader stage bound drift")
    controls = {}
    for name, pin in source["controls"].items():
        controls[name] = regular(archive / pin["path"])
        if digest(controls[name]) != pin["digest"]:
            raise ValueError("control drift")
    if control:
        grader = grader.with_judge(archive / source["controls"][control]["path"])
        loaded = {**loaded, "judge": controls[control]}
    results = {}
    complete = True
    # Exactly two grades, including when the first verdict is unexpected. The
    # verifier freezes these already checked bytes rather than rereading a tree.
    for name in ("bad", "good"):
        graded = verify.grade_files(
            grader, snapshots[name], Path(tempfile.gettempdir()), loaded=loaded,
        )
        complete = complete and (
            graded.category == "verdict"
            and graded.containment.get("confirmed") is True
            and graded.containment.get("cleanup") == "removed"
            and len(graded.criteria) == len(grader.criteria)
            and {c["id"] for c in graded.criteria} == set(grader.criteria)
            and all(c.get("mandatory") is True and c.get("outcome") in
                    {"SATISFIED", "VIOLATED"} for c in graded.criteria)
        )
        results[name] = {"status": graded.status, "violated": sorted(graded.violated)}
    passed = complete and results == source["expected"]
    return {"verdict": "PASS" if passed else "REFUSED", "control": control,
            "source_digest": SOURCE_DIGEST, "grader": expected_identity,
            "active_grader_digest": grader.digest(loaded), "complete": complete,
            "replay_digest": digest(Path(__file__).read_bytes()), "results": results}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", type=Path, default=CASE)
    parser.add_argument("--grader-root", type=Path)
    parser.add_argument("--control", choices=("always-pass", "always-fail"))
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    # Keep source-tree bytecode and any stale bytecode outside the reader's trust
    # boundary; the existing verifier manages its own contained stages.
    with tempfile.TemporaryDirectory(prefix="skillc-28-reader-") as cache:
        sys.pycache_prefix = cache
        from skillc.trial import Refused

        try:
            result = run(args.case, args.grader_root, args.control)
        except (ValueError, OSError, Refused) as exc:
            result = {"verdict": "REFUSED", "reason": type(exc).__name__}
        print(json.dumps(result, sort_keys=True))
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
