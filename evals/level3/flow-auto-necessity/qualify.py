#!/usr/bin/env python3
"""Certify the Level 3 flow-auto-necessity grader (#434) before any model is
asked to run flow:auto on it.

A grader is certified only when, on this task's committed candidates:

  - the untouched starting fixtures FAIL, CLEAN and TWIN both (the task is
    not solved by doing nothing);
  - every `candidates/pass/` candidate PASSes;
  - every `candidates/fail/` candidate FAILs for EXACTLY the criteria its
    `expected.json` names, and every `candidates/inconclusive/` candidate is
    INCONCLUSIVE for exactly the UNKNOWN criteria it names - a verdict for
    the wrong reason does not count as discrimination.

A candidate is not a finished tree: it is a scripted attempt. Its
`actions.json` names the case (`clean`/`twin`), the gh requests the attempt
makes and the git operations it performs; its `report.md` is the final
report the transcript would record. For every candidate this harness builds
a FRESH fixture (`fixture/build.py`), runs the gh requests through the REAL
`skillc.fixture_service.FixtureService` on a controller-owned host remote
(`LocalGitRemote`, within its contract), performs the git operations,
captures the git state with the same `fixture/build.capture` a live attempt
uses, builds a real (empty) gate-witness record, and grades the candidate
through `skillc.verify.grade_directory` with all of it as the trusted
observation - the channel a real attempt's records arrive through.

Then:

  - each broken grader in `grader-controls/` must be REFUSED and produce the
    one status its name promises on every candidate;
  - each BLINDING control (`judge(..., blind=...)`) removes one distinction,
    and must turn its named red into a PASS - proving the red can fire:
      ignore-service-record  -> fail/clean-closes-issue passes
      trust-sha-unresolved   -> fail/clean-cites-fake-sha passes
      drop-twin-check        -> fail/twin-abstains passes

`python3 qualify.py` prints the table and exits 0 only when all of it holds.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))

from skillc import fixture_service, verify
from skillc.backend import Limits
from skillc.gate_witness import GateWitness

_build_spec = importlib.util.spec_from_file_location("flow_auto_necessity_build", HERE / "fixture" / "build.py")
assert _build_spec is not None and _build_spec.loader is not None
build = importlib.util.module_from_spec(_build_spec)
_build_spec.loader.exec_module(build)
_judge_spec = importlib.util.spec_from_file_location("flow_auto_necessity_judge", HERE / "grade_flow_auto_necessity.py")
assert _judge_spec is not None and _judge_spec.loader is not None
judge_module = importlib.util.module_from_spec(_judge_spec)
_judge_spec.loader.exec_module(judge_module)

CONTROLS = {
    "always_pass": ("PASS", "verdict"),
    "always_fail": ("FAIL", "verdict"),
    "crash": ("INCONCLUSIVE", "exit-nonzero"),
    "no_output": ("INCONCLUSIVE", "no-output"),
    "omits_criterion": ("INCONCLUSIVE", "criteria-set"),
}
BLINDING = {
    "ignore-service-record": "fail/clean-closes-issue",
    "trust-sha-unresolved": "fail/clean-cites-fake-sha",
    "drop-twin-check": "fail/twin-abstains",
}
_PLACED = {"pass": "PASS", "fail": "FAIL", "inconclusive": "INCONCLUSIVE"}
#: The gate a flow:auto attempt's finish step would be witnessed as (#434 PR 2).
_GATES = {"flow-auto-finish": ["bash", "/opt/skillc-harness/flow-finish-gate.sh"]}


@dataclass
class Row:
    candidate: str
    expected: str
    status: str
    detail: str
    expected_violated: frozenset[str] = frozenset()
    violated: frozenset[str] = frozenset()
    category: str = "verdict"
    unknown: frozenset[str] = frozenset()
    expected_unknown: frozenset[str] = frozenset()

    @property
    def ok(self) -> bool:
        return (self.status == self.expected and self.violated == self.expected_violated
                and self.category == "verdict" and self.unknown == self.expected_unknown)


@dataclass
class Candidate:
    path: Path
    placed: str
    actions: dict[str, Any]
    expected_violated: frozenset[str]
    expected_unknown: frozenset[str]
    trusted: bytes = field(default=b"", repr=False)

    @property
    def rel(self) -> str:
        return self.path.relative_to(HERE / "candidates").as_posix()


def _empty_witness() -> dict[str, Any]:
    """A real GateWitness record for an attempt that requested no gate - the
    honest outcome for a flow:auto run that stops at its approval gate."""
    witness = GateWitness(declared_gates=_GATES, tree_digest_fn=lambda: "unused", backend=None,  # type: ignore[arg-type]
                          handle=None, limits=Limits(timeout=60), gate_exclusivity=False,
                          exclusivity_basis="flow:auto reaches its finish gate only after approval")
    return json.loads(witness.finalize("qualify").to_json_bytes())


def _git(where: Path, *args: str) -> None:
    build.host_git(list(args), where, date="2026-10-17T12:30:00+0000")


def _apply_git(root: Path, ops: list[dict[str, Any]]) -> None:
    for op in ops:
        kind = op["op"]
        if kind == "worktree":
            _git(root / "repo", "worktree", "add", "-q", "-b", op["branch"], str(root / op["name"]), "origin/main")
        elif kind == "write":
            target = root / op["where"] / op["path"]
            target.write_text(op["text"], encoding="utf-8")
        elif kind == "commit":
            _git(root / op["where"], "commit", "-q", "-am", op["message"])
        elif kind == "commit-empty":
            _git(root / op["where"], "commit", "-q", "--allow-empty", "-m", op["message"])
        elif kind == "push":
            _git(root / op["where"], "push", "-q", "origin", f"HEAD:refs/heads/{op['branch']}")
        else:
            raise SystemExit(f"unknown git op {kind!r}")


def run_attempt(actions: dict[str, Any], report: str) -> bytes:
    """Play one scripted attempt against a fresh fixture; return the trusted
    observation exactly as a real attempt's controller would assemble it."""
    case = actions["case"]
    previous = os.umask(0o022)
    try:
        with tempfile.TemporaryDirectory(prefix="flow-auto-necessity-") as tmp:
            root = Path(tmp)
            facts = build.build(root, case)
            remote = root / "remote.git"
            service = fixture_service.FixtureService(build.declaration(case, str(remote), facts),
                                                     fixture_service.LocalGitRemote(remote), "qualify")
            _apply_git(root, actions.get("git", []))
            where = actions.get("gh_where", "repo")
            branch = subprocess.run(["git", "-C", str(root / where), "branch", "--show-current"],
                                    capture_output=True, text=True, check=True).stdout.strip()
            for argv in actions.get("gh", []):
                request = {"op": "gh", "argv": argv, "cwd": f"/work/{where}",
                           "context": {"origin_url": str(remote), "branch": branch}}
                service.decide(request)
            git = build.capture(lambda a, c: build.host_git(list(a), c), root / "repo", remote)
            record = service.finalize("qualify").to_json()
    finally:
        os.umask(previous)
    witness = None if actions.get("witness") == "none" else _empty_witness()
    return json.dumps({"case": case, "service": record, "git": git, "witness": witness,
                       "final_report": report}).encode("utf-8")


def candidates() -> list[Candidate]:
    found = []
    for placement, status in _PLACED.items():
        base = HERE / "candidates" / placement
        dirs = sorted(p for p in base.iterdir() if p.is_dir()) if base.is_dir() else []
        if not dirs:
            raise SystemExit(f"{base}: an empty population cannot certify a grader")
        for path in dirs:
            expected = json.loads((path / "expected.json").read_text(encoding="utf-8"))
            if expected.get("status") != status:
                raise SystemExit(f"{path}: expected.json says {expected.get('status')!r}, placement says {status!r}")
            violated = frozenset(map(str, expected.get("violated", [])))
            unknown = frozenset(map(str, expected.get("unknown", [])))
            if (status == "FAIL") != bool(violated) or (status == "INCONCLUSIVE") != bool(unknown) and not violated:
                raise SystemExit(f"{path}: a FAIL must name violated criteria, an INCONCLUSIVE unknown ones")
            actions = json.loads((path / "actions.json").read_text(encoding="utf-8"))
            report = (path / "report.md").read_text(encoding="utf-8")
            found.append(Candidate(path, status, actions, violated, unknown, run_attempt(actions, report)))
    for case in build.CASES:
        if not (HERE / "candidates" / "fail" / f"untouched-{case}").is_dir():
            raise SystemExit(f"no untouched {case} starting fixture; 'doing nothing fails' cannot drop out")
    for red in BLINDING.values():
        if not (HERE / "candidates" / red).is_dir():
            raise SystemExit(f"blinding control names {red!r}, which is not a candidate")
    return found


def _row(grader: Path, c: Candidate) -> Row:
    graded = verify.grade_directory(verify.GraderDef.load(HERE).with_judge(grader), c.path,
                                    trusted_observation=c.trusted)
    unknown = frozenset(str(x["id"]) for x in graded.criteria if x.get("outcome") == "UNKNOWN")
    return Row(c.rel, c.placed, graded.status, graded.detail, c.expected_violated, graded.violated,
               graded.category, unknown, c.expected_unknown)


def certify(grader: Path, population: list[Candidate]) -> tuple[bool, list[Row]]:
    rows = [_row(grader, c) for c in population]
    return all(r.ok for r in rows), rows


def control_verdict(name: str, population: list[Candidate]) -> tuple[bool, str, list[Row]]:
    grader = HERE / "grader-controls" / f"{name}.py"
    if not grader.is_file():
        return False, f"control {grader.name} does not exist", []
    certified, rows = certify(grader, population)
    if certified:
        return False, "the gate certified it", rows
    want = CONTROLS[name]
    seen = {(r.status, r.category) for r in rows}
    if seen != {want}:
        return False, f"it produced {sorted(seen)}, not {want} throughout", rows
    return True, f"refused; {want[0]} ({want[1]}) on every candidate", rows


def _status(result: dict[str, Any]) -> str:
    outcomes = [c["outcome"] for c in result["criteria"]]
    return "FAIL" if "VIOLATED" in outcomes else "INCONCLUSIVE" if "UNKNOWN" in outcomes else "PASS"


def blinding_validity(population: list[Candidate]) -> list[tuple[str, bool, str]]:
    """Each blinding must flip its red to PASS while the real judge FAILs it."""
    by_rel = {c.rel: c for c in population}
    results = []
    for flag, red in BLINDING.items():
        c = by_rel[red]
        envelope = {**judge_module.run_probe(c.path), "trusted": c.trusted.decode("utf-8")}
        real = _status(judge_module.judge(envelope))
        blind = _status(judge_module.judge(envelope, blind=frozenset({flag})))
        held = real == "FAIL" and blind == "PASS"
        results.append((f"{flag} -> {red}", held, f"real {real}, blinded {blind}"))
    return results


def _show(title: str, certified: bool, rows: list[Row]) -> None:
    print(f"{title}: {'CERTIFIED' if certified else 'REFUSED'}")
    for r in rows:
        mark = "ok " if r.ok else "BAD"
        print(f"  {mark} {r.candidate:44} expected {r.expected:12} got {r.status:12} {r.detail}")


def main() -> int:
    population = candidates()
    good, rows = certify(HERE / "grade_flow_auto_necessity.py", population)
    _show("grade_flow_auto_necessity.py", good, rows)
    blind_controls = []
    for name in CONTROLS:
        held, reason, _rows = control_verdict(name, population)
        print(f"control {name}: {'REFUSED' if held else 'BAD'} ({reason})")
        if not held:
            blind_controls.append(f"{name}: {reason}")
    validity = blinding_validity(population)
    print("blinding validity (each red must pass once its distinction is removed):")
    for name, held, detail in validity:
        print(f"  {'ok ' if held else 'BAD'} {name}: {detail}")
    if not good:
        print("QUALIFY: fail - the grader does not discriminate the committed candidates")
        return 1
    if blind_controls:
        print(f"QUALIFY: fail - broken-grader control(s) did not hold: {'; '.join(blind_controls)}")
        return 1
    if not all(held for _n, held, _d in validity):
        print("QUALIFY: fail - a blinding control did not flip its red")
        return 1
    print(f"QUALIFY: ok - grader certified on {len(rows)} candidates; {len(CONTROLS)} broken graders refused; "
          f"{len(validity)} blinding controls flipped their reds")
    return 0


if __name__ == "__main__":
    sys.exit(main())
