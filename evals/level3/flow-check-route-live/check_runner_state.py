#!/usr/bin/env python3
"""The per-subject preflight for #530's resumable-state guard (orchestrator
condition): the guard is sufficient only because the pinned CPP runner
DELETES its resume state on success (measured at 652c0118). This re-measures
that at whatever pin the declaration uses, so a re-pin cannot silently break it.

On a scratch build of the flow-check-route fixture, with the PINNED gate:
  1. `--plan check --evidence flow-check`, then `--check-summary`: each exits
     0 with a `FLOW_FINISH_GATE: ok` verdict, and `<state path>` is EMPTY after
     each (an honest sequence leaves nothing a later run could inherit);
  2. the CONTROL: one failing test added, a plan run exits 1 with
     `FLOW_FINISH_GATE: fail` and DOES leave state - so the check can see state.
Any other result exits 1 and prints why; the question goes back to the
orchestrator.

Usage: check_runner_state.py CPP_CHECKOUT GATE_SCRIPT
  CPP_CHECKOUT  the subject checkout at the declared pin (FLOW_GATE_CPP_DIR)
  GATE_SCRIPT   that checkout's bundled flow-check gate (the copy the agent runs)
"""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASK = HERE.parent / "flow-check-route"
PLAN = ["--plan", "check", "--evidence", "flow-check"]
SUMMARY = ["--check-summary"]
FAILING_TEST = "\n\ndef test_forced_failure_for_the_runner_state_control():\n    assert False\n"
VERDICT = re.compile(r"FLOW_FINISH_GATE: (\w+)")


def _builder():
    spec = importlib.util.spec_from_file_location("flow_check_route_builder_for_preflight",
                                                  TASK / "builder" / "build.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def state_entries(repo: Path, state_paths: tuple[str, ...]) -> list[str]:
    found = []
    for rel in state_paths:
        path = repo / rel
        if path.is_dir():
            found += [f"{rel}/{name}" for name in sorted(os.listdir(path))]
        elif path.exists() or path.is_symlink():
            found.append(rel)
    return found


def run_gate(gate: Path, cpp: Path, repo: Path, args: list[str]) -> tuple[int, str | None]:
    env = {**os.environ, "FLOW_GATE_CPP_DIR": str(cpp)}
    done = subprocess.run(["bash", str(gate), *args], cwd=repo, env=env, capture_output=True, text=True,
                          timeout=900, check=False)
    verdicts = VERDICT.findall(done.stdout + done.stderr)
    return done.returncode, (verdicts[-1] if verdicts else None)


def check(cpp: Path, gate: Path, build: object = None) -> list[str]:
    build = build or _builder()
    paths = tuple(build.GATE_STATE_PATHS)  # type: ignore[attr-defined]
    problems: list[str] = []
    with tempfile.TemporaryDirectory(prefix="flow-check-route-runner-state-") as tmp:
        root = Path(tmp) / "case"
        root.mkdir()
        build.build(root, build.CASES[0])  # type: ignore[attr-defined]
        repo = root / "repo"
        for label, args in (("plan", PLAN), ("summary", SUMMARY)):
            code, verdict = run_gate(gate, cpp, repo, args)
            left = state_entries(repo, paths)
            print(f"{label}: exit {code}, verdict {verdict}, state {left}")
            if code != 0 or verdict != "ok":
                problems.append(f"{label}: expected exit 0 and verdict ok, got exit {code} and {verdict}")
            if left:
                problems.append(f"{label}: an honest successful run LEFT resumable state {left} - the guard "
                                "would make the next honest run unattributable; back to the orchestrator")
        control = Path(tmp) / "control"
        shutil.copytree(repo, control, symlinks=True)
        tests = sorted((control / "tests").glob("test_*.py"))
        tests[0].write_text(tests[0].read_text(encoding="utf-8") + FAILING_TEST, encoding="utf-8")
        code, verdict = run_gate(gate, cpp, control, PLAN)
        left = state_entries(control, paths)
        print(f"control (failing test): exit {code}, verdict {verdict}, state {left}")
        if code != 1 or verdict != "fail" or not left:
            problems.append(f"control: a failing run must exit 1, say fail and LEAVE state; got exit {code}, "
                            f"{verdict}, state {left} - the check cannot see state")
    return problems


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__.split("Usage:")[1].strip(), file=sys.stderr)
        return 2
    problems = check(Path(argv[1]).resolve(), Path(argv[2]).resolve())
    for problem in problems:
        print("MISMATCH:", problem)
    print("RUNNER STATE:", "ALL PASS" if not problems else f"FAIL ({len(problems)})")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
