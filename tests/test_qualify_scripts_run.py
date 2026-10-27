"""Negative control on the certification scripts themselves (orchestrator
direction, 2026-10-07, following the `gate-stops-early`/`claims-outran-
evidence`/`report-outran-evidence` `_WitnessBackend` drift found while
wiring #270): that drift crashed `qualify.py` with a `TypeError` on every
`request=True` call, and went undetected for as long as it did because
NOTHING in the pytest suite ever ran these scripts - a green suite said
nothing about whether any of them still worked. This file runs every eval
task's own `qualify.py` as a real subprocess and asserts `QUALIFY: ok`, so
a future drift like that one reds the normal suite instead of waiting for
someone to run it by hand.

Discovered via `rglob`, never hand-listed - the whole point is that a NEW
qualify.py is covered automatically, not only the ones named here at the
time of writing. `test_every_qualify_script_is_discovered_and_none_
quietly_ignored` floors the discovered count so a broken `rglob` (e.g. a
future refactor that moves `evals/` or renames the pattern) cannot silently
collapse the population to zero and still read as "every task certified."
"""

from __future__ import annotations

import ast
import hashlib
import os
import random
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

EVALS_ROOT = Path(__file__).resolve().parent.parent / "evals"

QUALIFY_SCRIPTS = sorted(EVALS_ROOT.rglob("qualify.py"))

#: CI 735 (#371) exhausted 180s after certifying slugkit-pipeline's
#: candidates and running its broken-grader controls, before its remaining
#: pipeline-validity probes completed. Give this known expensive script a
#: bounded 360s budget under parallel CI; preserve 180s for every other task.
_SLOW_REASON = {
    "slugkit-pipeline": "CI 735 exceeded 180s while executing real pipeline-validity controls",
}


#: #281: scripts that certify through a REAL container runtime (a runtime
#: receipt and a Docker daemon) cannot run as a bare subprocess in this suite.
#: Each names the declared real-Docker floor file that runs it, and
#: `test_runtime_qualified_scripts_are_run_by_a_floored_live_test` checks that
#: claim, so the exclusion is visible and verified, never a quiet one.
_RUNTIME_QUALIFIED = {"cicd-pipeline": "tests.test_level3_cicd_pipeline_live"}


def _task_name(script: Path) -> str:
    return script.parent.name


def _declared_parts(script: Path) -> list[str] | None:
    """A split script's parts, derived from its own `CONTROLS` literal (#446),
    or None for a script that runs whole. Read from source, never by running
    it, so collection spawns nothing; `test_split_scripts_list_exactly_their_
    declared_parts` checks the script's own `--list-parts` says the same."""
    tree = ast.parse(script.read_text(encoding="utf-8"))
    if not any(isinstance(n, ast.FunctionDef) and n.name == "parts" for n in tree.body):
        return None
    controls = next(n.value for n in tree.body if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "CONTROLS" for t in n.targets))
    assert isinstance(controls, ast.Dict)
    keys = [ast.literal_eval(k) for k in controls.keys if k is not None]
    return ["certify", *(f"control:{k}" for k in keys), "validity"]


SPLIT_SCRIPTS = {script: parts for script in QUALIFY_SCRIPTS if (parts := _declared_parts(script))}

#: #446: run as one subprocess, gate-stops-early and verify-stops-early
#: (about 30 candidates graded by the real judge and again by each of five
#: broken-grader controls, then the validity checks) took 71-161 s in CI and
#: hit the 180 s cap on main's push pipeline 869. Neither declares a whole-run
#: budget (grader.json's 90 s / 60 s are per probe and judge call), so the
#: cap is this test's. Each is split into independent parts, every part its
#: own subprocess under the same cap. The order is shuffled with a fixed seed
#: so a serial run never executes them in the order the full run does, and a
#: part that relied on another having run first fails alone.
_PART_ORDER_SEED = 446


def _shuffled_parts(script: Path, parts: list[str]) -> list[str]:
    """`parts` in a fixed per-script order that is never the declared one.
    Seeded by the script's own name, so adding an unrelated task cannot move
    it (#446 counter-model review)."""
    order = list(parts)
    random.Random(f"{_PART_ORDER_SEED}:{_task_name(script)}").shuffle(order)
    return order[1:] + order[:1] if order == parts else order


_PARAMS = [
    *[(script, None) for script in QUALIFY_SCRIPTS
      if script not in SPLIT_SCRIPTS and _task_name(script) not in _RUNTIME_QUALIFIED],
    *[(script, part) for script, parts in SPLIT_SCRIPTS.items() for part in _shuffled_parts(script, parts)],
]


def _param_id(script: Path, part: str | None) -> str:
    return _task_name(script) if part is None else f"{_task_name(script)}--{part}"


def _task_tree_digest(task_dir: Path) -> str:
    """Every file under the task directory except compiled bytecode
    (`__pycache__/*.pyc`); any other file, under `__pycache__` or not,
    counts (#446 counter-model review)."""
    digest = hashlib.sha256()
    for path in sorted(task_dir.rglob("*")):
        if path.is_file() and not (path.parent.name == "__pycache__" and path.suffix == ".pyc"):
            digest.update(path.relative_to(task_dir).as_posix().encode() + b"\0" + path.read_bytes())
    return digest.hexdigest()


@pytest.mark.parametrize("script,part,timeout_seconds", [
    pytest.param(script, part, 360 if _task_name(script) in _SLOW_REASON else 180,
                 id=_param_id(script, part),
                 marks=pytest.mark.timeout(380 if _task_name(script) in _SLOW_REASON else 200))
    for script, part in _PARAMS
])
def test_qualify_script_certifies(script: Path, part: str | None, timeout_seconds: float,
                                  tmp_path: Path) -> None:
    if part is not None:
        # Each part runs in its OWN copy of the task directory (#446 counter-
        # model review): parts run concurrently under xdist, and a shared
        # directory would let one part's write fail its neighbour's check.
        task_copy = tmp_path / script.parent.name
        shutil.copytree(script.parent, task_copy, ignore=shutil.ignore_patterns("__pycache__"))
        script = task_copy / script.name
    before = _task_tree_digest(script.parent) if part is not None else ""
    proc = subprocess.run(
        [sys.executable, str(script), *(["--part", part] if part is not None else [])],
        capture_output=True, text=True,
        timeout=timeout_seconds, check=False, cwd=script.parent,
        env={**os.environ, "SKILLC_QUALIFY_SOURCE_ROOT": str(EVALS_ROOT.parent)},
    )
    tail = "\n".join(proc.stdout.strip().splitlines()[-8:])
    name = _param_id(script, part)
    slow_note = f" ({_SLOW_REASON[_task_name(script)]})" if _task_name(script) in _SLOW_REASON else ""
    assert proc.returncode == 0, (
        f"{name}: qualify.py exited {proc.returncode}{slow_note}\n"
        f"stdout tail:\n{tail}\nstderr:\n{proc.stderr}"
    )
    if part is None:
        assert "QUALIFY: ok" in proc.stdout, f"{name}: no 'QUALIFY: ok' in output:\n{tail}"
    else:
        assert f"QUALIFY: ok part={part}" in proc.stdout.splitlines(), (
            f"{name}: no 'QUALIFY: ok part={part}' line in output:\n{tail}")
    if part is not None:
        # Independence (#446): a part may not leave state in the task
        # directory for another part to read.
        assert _task_tree_digest(script.parent) == before, f"{name}: the part changed files in {script.parent}"


def test_task_tree_digest_ignores_only_bytecode(tmp_path: Path) -> None:
    """The independence check's own controls: a state file a part leaves
    behind changes the digest wherever it sits, `__pycache__` included;
    compiled bytecode does not."""
    (tmp_path / "qualify.py").write_text("print('x')\n", encoding="utf-8")
    (tmp_path / "__pycache__").mkdir()
    base = _task_tree_digest(tmp_path)
    (tmp_path / "__pycache__" / "qualify.cpython-312.pyc").write_bytes(b"bytecode")
    assert _task_tree_digest(tmp_path) == base
    (tmp_path / "__pycache__" / "part-state.json").write_text("{}", encoding="utf-8")
    hidden = _task_tree_digest(tmp_path)
    assert hidden != base
    (tmp_path / "part-state.json").write_text("{}", encoding="utf-8")
    assert _task_tree_digest(tmp_path) != hidden


def test_split_scripts_list_exactly_their_declared_parts() -> None:
    """Membership guard (#446): splitting must not drop work. Each split
    script's own `--list-parts` must be exactly certify, one part per
    `CONTROLS` key, and validity - so a parts list that forgot a control, or
    a control added without a part, fails here rather than going unrun."""
    assert set(SPLIT_SCRIPTS) >= {
        EVALS_ROOT / "level3" / "gate-stops-early" / "qualify.py",
        EVALS_ROOT / "level3" / "verify-stops-early" / "qualify.py",
    }, "a split script stopped being detected, so it would silently run whole again or not at all"
    for script, declared in SPLIT_SCRIPTS.items():
        proc = subprocess.run([sys.executable, str(script), "--list-parts"], capture_output=True,
                              text=True, timeout=60, check=False, cwd=script.parent)
        assert proc.returncode == 0, f"{script}: --list-parts exited {proc.returncode}: {proc.stderr}"
        assert proc.stdout.split() == declared, (
            f"{_task_name(script)}: --list-parts says {proc.stdout.split()}, CONTROLS declares {declared}")


def test_part_order_is_not_the_full_run_order() -> None:
    """The shuffle is what makes a serial run catch a part that depends on an
    earlier one; pin that it actually reorders each split script's parts,
    including when the seeded shuffle alone would return the declared order."""
    assert _shuffled_parts(Path("x/qualify.py"), ["only"]) == ["only"]
    for parts in (["a", "b"], ["certify", "control:x", "validity"]):
        assert _shuffled_parts(Path("t/qualify.py"), parts) != parts
    for script, declared in SPLIT_SCRIPTS.items():
        order = [part for s, part in _PARAMS if s == script and part is not None]
        assert sorted(order) == sorted(declared) and order != declared, (
            f"{_task_name(script)}: parts run in {order}")


@pytest.mark.timeout(5)
def test_hung_qualify_script_is_rejected(tmp_path: Path) -> None:
    """A larger budget still refuses a script that never completes."""
    script = tmp_path / "qualify.py"
    script.write_text("import time\nprint('QUALIFY: ok', flush=True)\ntime.sleep(60)\n", encoding="utf-8")
    with pytest.raises(subprocess.TimeoutExpired):
        test_qualify_script_certifies(script, None, timeout_seconds=0.1, tmp_path=tmp_path)


def test_every_qualify_script_is_discovered_and_none_quietly_ignored() -> None:
    """Membership floor: pins that discovery found a non-trivial, known
    population today, so a collection failure (e.g. `rglob` silently
    returning nothing after a future `evals/` reorganization) cannot pass
    as "every task certified" over an empty population - the same failure
    class `tests/test_private_citations.py`'s own empty-population check
    exists to catch, applied here."""
    assert len(QUALIFY_SCRIPTS) >= 13, (
        f"expected at least 13 qualify.py scripts (the count at the time this test was "
        f"written), found {len(QUALIFY_SCRIPTS)}: {[str(p) for p in QUALIFY_SCRIPTS]}"
    )


def runtime_qualified_problems(table: dict[str, str], floor: tuple[str, ...],
                               scripts: list[Path] = QUALIFY_SCRIPTS) -> list[str]:
    """Why a runtime-qualified exclusion is not backed by a floored live run."""
    problems = []
    root = EVALS_ROOT.parent
    for task, module in table.items():
        matches = [script for script in scripts if _task_name(script) == task]
        if len(matches) != 1:
            problems.append(f"{task}: {len(matches)} discovered qualify.py, not exactly one")
            continue
        if module not in floor:
            problems.append(f"{task}: {module} is not in the real-Docker floor")
        path = root / Path(*module.split(".")).with_suffix(".py")
        source = path.read_text(encoding="utf-8") if path.is_file() else ""
        rel = matches[0].relative_to(root).as_posix()
        if rel not in source or "qualify.main(" not in source:
            problems.append(f"{task}: {module} does not run {rel}")
    return problems


def test_runtime_qualified_scripts_are_run_by_a_floored_live_test() -> None:
    sys.path.insert(0, str(EVALS_ROOT.parent))
    from ci.check_real_docker_ran import DECLARED_REAL_DOCKER_FILES

    assert runtime_qualified_problems(_RUNTIME_QUALIFIED, DECLARED_REAL_DOCKER_FILES) == []
    # Negative controls: each claim the exclusion rests on can fail.
    off_floor = tuple(f for f in DECLARED_REAL_DOCKER_FILES if f != "tests.test_level3_cicd_pipeline_live")
    assert runtime_qualified_problems(_RUNTIME_QUALIFIED, off_floor)
    assert runtime_qualified_problems({"cicd-pipeline": "tests.test_cicd_profile_live"},
                                      DECLARED_REAL_DOCKER_FILES)
    assert runtime_qualified_problems({"no-such-task": "tests.test_level3_cicd_pipeline_live"},
                                      DECLARED_REAL_DOCKER_FILES)
