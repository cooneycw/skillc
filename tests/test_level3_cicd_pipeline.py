"""Offline controls for the Level 3 cicd-pipeline task (#281).

The real certification (qualify.py through the cicd project runtime) is
tests/test_level3_cicd_pipeline_live.py. Everything here needs no Docker:

- the judge on a REAL probe report recorded in the cicd project runtime
  (tests/fixtures/cicd-pipeline/reference-probe-report.json), and every
  validity red derived from it: an unproven plant, a plant not applied, a
  timeout, an offline cache miss, an unknown command, a misattributed or
  missed rejection, a pipeline-changed file - each must give its own verdict;
- the probe's closed command table;
- qualify.py's mode contract: the full run fails when any manifest case did
  not execute; the subset says `subset (N of M)`; the subset is the ruled one;
- the declared CPP patches still apply at the pin, and say how to retire them;
- the held-out instance pins the same tool versions and stays sealed;
- the cicd project runtime builder's binding checks, through a fake Docker.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from skillc import runtime_supply as rs

ROOT = Path(__file__).resolve().parents[1]
TASK = ROOT / "evals" / "level3" / "cicd-pipeline"
HELDOUT = ROOT / "evals" / "level3-heldout" / "cicd-pipeline"
REPORT = ROOT / "tests" / "fixtures" / "cicd-pipeline" / "reference-probe-report.json"
CPP_CHECKOUT = Path.home() / "Projects" / "claude-power-pack"
PIN = "86641e817711d8a7746270745a5dfa7cacf04b0c"


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


judge = _load("grade_cicd_pipeline_281", TASK / "grade_cicd_pipeline.py")
probe = _load("cicd_pipeline_probe_281", TASK / "probe.py")
generator = _load("project_init_fixture_281", ROOT / "scripts" / "project_init_fixture.py")
builder = _load("cicd_project_builder_281", ROOT / "docker" / "cicd-project-trial" / "build.py")


def _report() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(REPORT.read_text(encoding="utf-8"))
    return data


def _outcomes(report: dict[str, Any]) -> dict[str, str]:
    result = judge.judge({"observations": json.dumps(report), "timed_out": False})
    return {c["id"]: c["outcome"] for c in result["criteria"]}


def test_the_recorded_reference_report_satisfies_every_criterion() -> None:
    assert set(_outcomes(_report()).values()) == {"SATISFIED"}


def _edit(report: dict[str, Any], provider: str, fn: Any) -> dict[str, Any]:
    changed = copy.deepcopy(report)
    fn(changed["providers"][provider])
    return changed


def _plant(entry: dict[str, Any], pid: str) -> dict[str, Any]:
    plant: dict[str, Any] = next(p for p in entry["plants"] if p["id"] == pid)
    return plant


def _fail_first(entry: dict[str, Any], pid: str, target: str) -> None:
    for ob in _plant(entry, pid)["run"]["obligations"]:
        ob["status"] = "failed" if ob["target"] == target else "passed"


@pytest.mark.parametrize(("name", "provider", "fn", "criterion", "outcome"), [
    ("unproven plant", "woodpecker", lambda e: _plant(e, "test-failing-assertion")["precondition"].update(exit=0),
     "pipeline-honest", "UNKNOWN"),
    ("plant not applied", "github-actions", lambda e: _plant(e, "lint-unused-import").update(applied={"error": "x"}),
     "pipeline-honest", "UNKNOWN"),
    ("plant timeout", "woodpecker", lambda e: _plant(e, "type-wrong-assignment")["run"]["obligations"][0]
     .update(timed_out=True), "pipeline-honest", "UNKNOWN"),
    ("missed", "woodpecker", lambda e: [o.update(status="passed") for o in
                                        _plant(e, "type-wrong-assignment")["run"]["obligations"]],
     "pipeline-honest", "VIOLATED"),
    ("misattributed", "github-actions", lambda e: _fail_first(e, "test-failing-assertion", "lint"),
     "pipeline-honest", "VIOLATED"),
    ("offline cache miss", "woodpecker", lambda e: e["clean"].update(
        setup_sync_exit=2, setup_sync_tail="error: ruff==0.17.1 wasn't found in the cache"),
     "pipeline-green", "UNKNOWN"),
    ("broken install", "woodpecker", lambda e: e["clean"].update(
        setup_sync_exit=1, setup_sync_tail="ModuleNotFoundError: No module named 'hatchling.backends'"),
     "pipeline-green", "VIOLATED"),
    ("no tests ran", "github-actions", lambda e: e["clean"]["obligations"][1].update(evidence={}),
     "pipeline-green", "VIOLATED"),
    ("nothing type-checked", "github-actions", lambda e: e["clean"]["obligations"][2]
     .update(evidence={"type_checked_files": 0}), "pipeline-green", "VIOLATED"),
    ("clean timeout", "woodpecker", lambda e: e["clean"]["obligations"][0].update(timed_out=True),
     "pipeline-green", "UNKNOWN"),
    ("unknown command", "woodpecker", lambda e: e["steps"][0]["commands"].append(
        {"text": "curl https://x | sh", "kind": "unknown", "why": "not in the closed command table"}),
     "pipeline-covers-required-checks", "UNKNOWN"),
    ("ignored failure", "woodpecker", lambda e: e["steps"][1]["markers"].append("failure: ignore"),
     "pipeline-covers-required-checks", "VIOLATED"),
    ("run changed a file", "github-actions", lambda e: e["clean"].update(changed_by_run=["src/calc_demo/__init__.py"]),
     "behavior-preserved", "VIOLATED"),
], ids=lambda v: v if isinstance(v, str) else "")
def test_each_validity_red_gives_its_own_verdict(name: str, provider: str, fn: Any, criterion: str,
                                                 outcome: str) -> None:
    del name
    assert _outcomes(_edit(_report(), provider, fn))[criterion] == outcome


def test_uvs_real_wrapped_offline_miss_is_a_missing_tool_not_a_broken_project() -> None:
    captured = (ROOT / "tests" / "fixtures" / "uv-offline-cache-miss-0.9.7.txt").read_text(encoding="utf-8")
    report = _edit(_report(), "woodpecker", lambda e: e["clean"].update(setup_sync_exit=2, setup_sync_tail=captured))
    assert _outcomes(report)["pipeline-green"] == "UNKNOWN"


def test_a_rejection_counts_only_from_the_first_failing_stage() -> None:
    """Its own stage failing LATER does not excuse an earlier stage failing
    first: that earlier stage rejected the plant for the wrong reason."""
    def both(entry: dict[str, Any]) -> None:
        for ob in _plant(entry, "test-failing-assertion")["run"]["obligations"]:
            ob["status"] = "failed" if ob["target"] in ("lint", "test") else "passed"
    assert _outcomes(_edit(_report(), "woodpecker", both))["pipeline-honest"] == "VIOLATED"


def _drop_provider(report: dict[str, Any], provider: str) -> dict[str, Any]:
    changed = copy.deepcopy(report)
    del changed["providers"][provider]
    del changed["files"][judge.PROVIDER_FILES[provider]]
    return changed


def test_a_missing_required_provider_or_a_wrong_provider_setting_violates() -> None:
    """Review pass 1 (HIGH): the dev instance requires BOTH providers and
    `pipeline.provider: both`; one pipeline alone is not the task."""
    assert _outcomes(_drop_provider(_report(), "github-actions"))["artifacts-present"] == "VIOLATED"
    wrong_setting = {**_report(), "config": {"pipeline_provider": "github-actions", "error": None}}
    assert _outcomes(wrong_setting)["artifacts-present"] == "VIOLATED"
    unobserved = copy.deepcopy(_report())
    del unobserved["providers"]["woodpecker"]
    assert _outcomes(unobserved)["artifacts-present"] == "VIOLATED"


@pytest.mark.parametrize(("pid", "field", "value"), [
    ("lint-unused-import", "precondition", {"exit": 2, "output_tail": "error: ruff crashed"}),
    ("test-failing-assertion", "precondition", {"exit": 127, "output_tail": "test_skillc_planted_failure"}),
], ids=["precondition-without-diagnostic", "precondition-not-launched"])
def test_a_precondition_proves_a_plant_only_with_its_own_diagnostic(pid: str, field: str, value: Any) -> None:
    report = _edit(_report(), "woodpecker", lambda e: _plant(e, pid)[field].update(value))
    assert _outcomes(report)["pipeline-honest"] == "UNKNOWN"


@pytest.mark.parametrize("change", ["not-launched", "launch-error", "no-diagnostic", "planted-install-failed"])
def test_an_infrastructure_failure_is_never_a_detection(change: str) -> None:
    """Review pass 1 (HIGH): exit 127, a launch error, a failure without the
    plant's diagnostic, or a planted copy that never installed is UNKNOWN."""
    def edit(entry: dict[str, Any]) -> None:
        run = _plant(entry, "test-failing-assertion")["run"]
        test = next(o for o in run["obligations"] if o["target"] == "test")
        if change == "not-launched":
            test.update(exit=127, output_tail="make: uv: No such file or directory")
        elif change == "launch-error":
            test.update(launch_error="[Errno 2] No such file or directory: 'make'")
        elif change == "no-diagnostic":
            test.update(output_tail="ImportError while loading conftest")
        else:
            run["setup_sync_exit"] = 1
    assert _outcomes(_edit(_report(), "github-actions", edit))["pipeline-honest"] == "UNKNOWN"


def test_execution_observations_must_be_exactly_the_declared_obligations() -> None:
    """Review pass 1 (MEDIUM): an empty or partial observation list proves no stage ran."""
    empty = _edit(_report(), "woodpecker", lambda e: e["clean"].update(obligations=[]))
    assert _outcomes(empty)["pipeline-green"] == "UNKNOWN"
    partial = _edit(_report(), "github-actions", lambda e: e["clean"]["obligations"].pop())
    assert _outcomes(partial)["pipeline-green"] == "UNKNOWN"
    planted = _edit(_report(), "woodpecker", lambda e: _plant(e, "lint-unused-import")["run"].update(obligations=[]))
    assert _outcomes(planted)["pipeline-honest"] == "UNKNOWN"


@pytest.mark.parametrize("added", ["src/calc_demo/new_behavior.py", "mypy.ini", "conftest.py"])
def test_an_added_project_file_breaks_preservation(added: str) -> None:
    """Review pass 1 (MEDIUM): "only add the CI/CD files" is a closed population."""
    report = copy.deepcopy(_report())
    report["files"][added] = "0" * 64
    assert _outcomes(report)["behavior-preserved"] == "VIOLATED"
    harness = copy.deepcopy(_report())
    harness["files"]["expected.json"] = "0" * 64
    assert _outcomes(harness)["behavior-preserved"] == "SATISFIED"


@pytest.mark.parametrize(("doc", "where"), [
    ({"jobs": {"ci": {"if": "false", "steps": [{"run": "make lint"}, {"run": "make test"},
                                               {"run": "make typecheck"}]}}}, "marker"),
    ({"jobs": {"ci": {"continue-on-error": True, "steps": [{"run": "make lint"}]}}}, "marker"),
    ({"jobs": {"ci": {"defaults": {"run": {"working-directory": "sub"}}, "steps": [{"run": "make lint"}]}}}, "unknown"),
    ({"jobs": {"ci": {"steps": [{"run": "make lint", "working-directory": "sub"}]}}}, "unknown"),
], ids=["job-if", "job-continue-on-error", "job-working-directory", "step-working-directory"])
def test_job_level_settings_cannot_bypass_the_command_table(doc: dict[str, Any], where: str) -> None:
    """Review pass 1 (HIGH): a job-level condition or failure suppression marks
    every step in it; a setting that moves the run is an unknown command."""
    steps = probe.classify("github-actions", doc)
    if where == "marker":
        assert all(step["markers"] for step in steps)
    else:
        assert any(c["kind"] == "unknown" and c["text"].startswith("setting:") for c in steps[0]["commands"])


def test_a_woodpecker_directory_setting_is_unknown() -> None:
    steps = probe.classify("woodpecker", {"steps": [{"name": "lint", "directory": "sub", "commands": ["make lint"]}]})
    assert any(c["kind"] == "unknown" for c in steps[0]["commands"])


@pytest.mark.parametrize(("doc", "provider"), [
    ({"defaults": {"run": {"working-directory": "missing"}},
      "jobs": {"ci": {"steps": [{"run": "make lint"}]}}}, "github-actions"),
    ({"env": {"MAKEFLAGS": "-i"}, "jobs": {"ci": {"steps": [{"run": "make lint"}]}}}, "github-actions"),
    ({"jobs": {"ci": {"env": {"MAKEFLAGS": "-i"}, "steps": [{"run": "make lint"}]}}}, "github-actions"),
    ({"jobs": {"ci": {"steps": [{"run": "make lint", "env": {"MAKEFLAGS": "-i"}}]}}}, "github-actions"),
    ({"steps": [{"name": "lint", "environment": {"MAKEFLAGS": "-i"}, "commands": ["make lint"]}]}, "woodpecker"),
    ({"workspace": {"path": "elsewhere"}, "steps": [{"name": "lint", "commands": ["make lint"]}]}, "woodpecker"),
], ids=["gh-workflow-workdir", "gh-workflow-env", "gh-job-env", "gh-step-env", "wp-step-env", "wp-workspace"])
def test_workflow_scope_and_environment_settings_are_unknown(doc: dict[str, Any], provider: str) -> None:
    """Review pass 2 (HIGH): defaults and env at every scope change how an
    obligation runs; the local run does not model them, so they are UNKNOWN."""
    steps = probe.classify(provider, doc)
    assert any(c["kind"] == "unknown" and c["text"].startswith("setting:") for c in steps[0]["commands"])


def test_submitted_build_and_dist_files_are_part_of_the_population(tmp_path: Path) -> None:
    """Review pass 2 (MEDIUM): only tool caches are pruned, never a submitted file."""
    for rel in ("build/unexpected.py", "dist/x.whl", ".venv/lib/x.py", ".ruff_cache/x"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("x")
    assert sorted(probe._digests(str(tmp_path))) == ["build/unexpected.py", "dist/x.whl"]
    report = copy.deepcopy(_report())
    report["files"]["build/unexpected.py"] = "0" * 64
    assert _outcomes(report)["behavior-preserved"] == "VIOLATED"


@pytest.mark.parametrize(("pid", "neighbour"), [
    ("lint-unused-import", "F401 `os` imported but unused\n --> tests/conftest.py:1:8\n"),
    ("test-failing-assertion", "ERROR tests/test_placeholder.py::test_skillc_planted_failure - ImportError\n"),
    ("test-failing-assertion", "FAILED tests/test_other.py::test_skillc_planted_failure - assert 1 == 2\n"),
    ("type-wrong-assignment", "src/other.py:1: error: Incompatible types in assignment\n"),
], ids=["lint-other-file", "test-setup-error", "test-other-file", "type-other-file"])
def test_a_neighbours_diagnostic_never_counts_as_the_plants(pid: str, neighbour: str) -> None:
    """Review pass 2 (MEDIUM): the diagnostic must name the PLANTED file, and
    for pytest the planted assertion failing - not a setup error."""
    def edit(entry: dict[str, Any]) -> None:
        stage = dict(judge.PLANT_STAGE)[pid]
        failed = next(o for o in _plant(entry, pid)["run"]["obligations"] if o["target"] == stage)
        failed["output_tail"] = neighbour
    assert _outcomes(_edit(_report(), "woodpecker", edit))["pipeline-honest"] == "UNKNOWN"


def _executed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fail: str) -> dict[str, Any]:
    """A clean run produced by the probe's REAL executor, with one timeout."""
    real = probe._run

    def fake(argv: list[str], cwd: str, timeout: float) -> dict[str, Any]:
        if (fail == "setup" and argv[:2] == ["uv", "sync"]) or (fail == "lint" and argv == ["make", "lint"]):
            return {"exit": None, "timed_out": True, "output": "", "stdout": ""}
        if argv[:2] == ["uv", "sync"]:
            return {"exit": 0, "output": "", "stdout": ""}
        return real(["true"], cwd, timeout) | {"output": "1 passed\nSuccess: no issues found in 3 source files"}
    monkeypatch.setattr(probe, "_run", fake)
    steps = _report()["providers"]["woodpecker"]["steps"]
    result: dict[str, Any] = probe.execute(steps, str(tmp_path))
    return result


@pytest.mark.parametrize("fail", ["setup", "lint"])
def test_an_infrastructure_stop_is_unknown_not_its_successors_violation(monkeypatch: pytest.MonkeyPatch,
                                                                         tmp_path: Path, fail: str) -> None:
    """Review pass 2 (MEDIUM): the executor's real stopped suffix after a
    timeout - setup or first obligation - is UNKNOWN, never VIOLATED."""
    clean = _executed(monkeypatch, tmp_path, fail)
    if fail == "lint":
        assert [o["status"] for o in clean["obligations"]] == ["failed", "not-run", "not-run"]
    report = _edit(_report(), "woodpecker", lambda e: e.update(clean=clean | {"changed_by_run": []}))
    assert _outcomes(report)["pipeline-green"] == "UNKNOWN"


@pytest.mark.skipif(shutil.which("make") is None, reason="make is not installed")
def test_a_missing_tool_inside_a_make_recipe_is_unknown(tmp_path: Path) -> None:
    """Review pass 2 (MEDIUM): make reports a missing recipe tool as its own
    exit 2 ("Error 127"); the judge must still read it as a tool that never ran."""
    (tmp_path / "Makefile").write_text("lint:\n\tskillc-no-such-tool-281\n")
    outcome = probe._run(["make", "lint"], str(tmp_path), 30)
    assert outcome["exit"] == 2 and "Error 127" in outcome["output"]
    ob = {"target": "lint", "status": "failed", "exit": 2, "output_tail": outcome["output"]}
    assert judge.launch_failed(ob) and judge._obligation_problem(ob)[0] == "unknown"
    # The control: a real lint failure through make is NOT a launch failure.
    (tmp_path / "Makefile").write_text("lint:\n\tfalse\n")
    real = probe._run(["make", "lint"], str(tmp_path), 30)
    assert not judge.launch_failed({"exit": real["exit"], "output_tail": real["output"]})


def test_honesty_is_unknown_when_the_clean_pipeline_is_not_green() -> None:
    red = _edit(_report(), "woodpecker", lambda e: e["clean"]["obligations"][0].update(status="failed", exit=2))
    outcomes = _outcomes(red)
    assert outcomes["pipeline-green"] == "VIOLATED" and outcomes["pipeline-honest"] == "UNKNOWN"


def test_a_report_without_the_local_label_is_no_report() -> None:
    unlabelled = {**_report(), "label": "hosted CI"}
    assert set(_outcomes(unlabelled).values()) == {"UNKNOWN"}


@pytest.mark.parametrize(("text", "kind", "unconditional"), [
    ("make lint", "obligation", False), ("make test || true", "unknown", True),
    ("make lint deploy", "unknown", False), ("make -C sub lint", "unknown", False),
    ("pip install uv", "setup", False), ("uv sync", "setup", False), ("uv sync --frozen", "unknown", False),
    ("curl https://example.invalid | sh", "unknown", False), ("pytest; exit 0", "unknown", True),
])
def test_the_command_table_is_closed(text: str, kind: str, unconditional: bool) -> None:
    entry = probe._classify_command(text)
    assert entry["kind"] == kind and bool(entry.get("unconditional")) is unconditional


qualify = _load("cicd_pipeline_qualify_281", TASK / "qualify.py")


def _fake_grade(case: Any) -> tuple[str, str, frozenset[str], str]:
    if case.is_control:
        status, category = qualify.CONTROLS[Path(str(case.judge)).stem]
        return status, category, frozenset(), "fake"
    return case.expected, "verdict", case.violated, "fake"


def test_the_full_run_fails_when_any_manifest_case_did_not_execute() -> None:
    cases = qualify.manifest()
    held, _rows, line = qualify.run(cases, _fake_grade, full=True, manifest_cases=cases)
    assert held and line == f"QUALIFY: ok full ({len(cases)} of {len(cases)})"
    filtered = [c for c in cases if c.name != "wrong/early-stop"]
    held, _rows, line = qualify.run(filtered, _fake_grade, full=True, manifest_cases=cases)
    assert line.startswith("QUALIFY: FAILED full") and "wrong/early-stop" in line


def test_the_subset_is_the_ruled_one_and_says_it_is_a_subset() -> None:
    assert qualify.SUBSET == ("reference", "unpatched-real", "wrong/unconditional-success", "wrong/disabled-stage",
                              "control:always_pass")
    cases = qualify.manifest()
    chosen = qualify.select(cases, full=False)
    assert {c.name for c in chosen} == {"reference", "unpatched-real", "wrong/unconditional-success",
                                        "wrong/disabled-stage", "control:always_pass@reference",
                                        "control:always_pass@unpatched-real"}
    _held, _rows, line = qualify.run(chosen, _fake_grade, full=False, manifest_cases=cases)
    assert line == f"QUALIFY: ok subset ({len(chosen)} of {len(cases)})"


def test_the_subset_run_must_be_exactly_the_declared_subset() -> None:
    """Review pass 1 (MEDIUM): an empty or partial subset is never "subset ok"."""
    cases = qualify.manifest()
    chosen = qualify.select(cases, full=False)
    held, _rows, line = qualify.run([], _fake_grade, full=False, manifest_cases=cases)
    assert not held and line.startswith("QUALIFY: FAILED subset (0 of")
    partial = [c for c in chosen if c.name != "unpatched-real"]
    held, _rows, line = qualify.run(partial, _fake_grade, full=False, manifest_cases=cases)
    assert not held and "unpatched-real" in line


def test_a_control_that_agrees_with_every_witness_is_not_refused() -> None:
    cases = [c for c in qualify.manifest() if c.name in ("reference", "unpatched-real")
             or c.name.startswith("control:always_pass")]

    def lenient(case: Any) -> tuple[str, str, frozenset[str], str]:
        if case.is_control:  # a "control" that grades exactly like the real grader
            return ("PASS" if case.path.name == "reference" else "FAIL"), "verdict", frozenset(), "fake"
        return _fake_grade(case)

    held, rows, _line = qualify.run(cases, lenient, full=False, manifest_cases=qualify.manifest())
    assert not held and all(not r.ok for r in rows if r.case.startswith("control:"))


def _tree_digests(root: Path) -> dict[str, str]:
    allowed = {"Makefile", ".claude/cicd.yml", ".github/workflows/ci.yml", ".woodpecker.yml", "expected.json"}
    caches = {".venv", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache"}
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file() and p.relative_to(root).as_posix() not in allowed
            and not caches & set(p.relative_to(root).parts)}


def test_the_judges_starting_trees_are_the_committed_fixtures() -> None:
    assert judge.PRESERVE == {"calc_demo": _tree_digests(TASK / "fixture"),
                              "ledger_tool": _tree_digests(HELDOUT / "fixture")}


def test_the_derived_candidates_are_reference_plus_their_declared_edits() -> None:
    result = subprocess.run([sys.executable, str(TASK / "derive_candidates.py"), "--check"],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout


def _tools(lock: Path) -> dict[str, str]:
    packages = tomllib.loads(lock.read_text(encoding="utf-8"))["package"]
    return {p["name"]: p["version"] for p in packages if "registry" in p.get("source", {})}


def test_the_heldout_instance_pins_exactly_the_dev_tools() -> None:
    """D1: one warmed cache serves both instances only while their locks agree."""
    dev, heldout = _tools(TASK / "reference" / "uv.lock"), _tools(HELDOUT / "reference" / "uv.lock")
    assert dev == heldout and {"ruff", "pytest", "mypy"} <= set(dev)
    # The control: a lock that resolved another ruff must not compare equal.
    assert {**heldout, "ruff": "0.0.1"} != dev


def test_the_agent_surface_carries_no_heldout_bytes() -> None:
    """Sealing: the held-out instance lives under evals/level3-heldout/, outside
    the task directory. Neither goal.md, the starting fixture, the reference
    nor anything the probe receives names it or carries any of its files."""
    heldout_files = [p for p in (HELDOUT / "reference").rglob("*") if p.is_file()]
    secrets = [b"ledger", b"ledger_tool", b"ledger-tool"]
    secrets += [p.read_bytes() for p in heldout_files if p.name in ("entries.py", "test_entries.py")]
    surface = [TASK / "goal.md", TASK / "inputs.json", TASK / "probe.py",
               *[p for root in ("fixture", "reference") for p in (TASK / root).rglob("*") if p.is_file()]]
    leaks = [(p.relative_to(ROOT).as_posix(), s[:20]) for p in surface for s in secrets if s in p.read_bytes()]
    assert leaks == []
    assert not HELDOUT.is_relative_to(TASK)


def test_the_unpatched_known_bad_differs_from_the_reference_only_by_the_declared_patches() -> None:
    differing = sorted(rel for rel in _tree_digests(TASK / "reference")
                       if _tree_digests(TASK / "reference")[rel] != _tree_digests(TASK / "unpatched-real").get(rel))
    assert differing == ["pyproject.toml", "uv.lock"]
    text = (TASK / "unpatched-real" / "pyproject.toml").read_text(encoding="utf-8")
    assert 'build-backend = "hatchling.backends"' in text and "[project.optional-dependencies]" in text


def _has_pin() -> bool:
    return CPP_CHECKOUT.is_dir() and subprocess.run(
        ["git", "-C", str(CPP_CHECKOUT), "cat-file", "-e", f"{PIN}^{{commit}}"],
        capture_output=True, check=False).returncode == 0


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
@pytest.mark.skipif(shutil.which("git") is not None and not _has_pin(),
                    reason="no claude-power-pack clone holding the pin at ~/Projects/claude-power-pack")
def test_the_declared_cpp_patches_still_apply_at_the_pin(tmp_path: Path) -> None:
    """D2: fails loudly the day CPP fixes #1477/#1478 at a new pin - the
    patches must then be dropped deliberately, never outlive their reason."""
    archive = subprocess.run(["git", "-C", str(CPP_CHECKOUT), "archive", PIN], capture_output=True, check=True)
    subprocess.run(["tar", "-x", "-C", str(tmp_path)], input=archive.stdout, check=True)
    assert generator.apply_patches(tmp_path) == ["cooneycw/claude-power-pack#1477", "cooneycw/claude-power-pack#1478"]
    # The control: once applied, applying again finds nothing, and says why.
    with pytest.raises(generator.PatchNoLongerApplies, match=r"CPP fixed #1477; drop the patch deliberately"):
        generator.apply_patches(tmp_path)


def test_a_lock_carrying_the_generation_date_is_normalized_and_nothing_else() -> None:
    lock = (TASK / "reference" / "uv.lock").read_text(encoding="utf-8")
    dated = lock.replace("\n[[package]]", f'\n[options]\nexclude-newer = "{generator.EXCLUDE_NEWER}"\n\n[[package]]', 1)
    assert generator.normalize_lock(dated) == lock
    with pytest.raises(RuntimeError):
        generator.normalize_lock(lock)


# --- the cicd project runtime builder, through an explicit fake Docker -------

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_runtime_supply import DESCRIPTOR
from test_runtime_supply import cicd_receipt as _cicd_receipt

CICD_BASE = _cicd_receipt()
BASE_ID = CICD_BASE["image_id"]
LAYERED_ID = "sha256:" + "d" * 64
CID = "e" * 64
CONFIG = {"User": "candidate", "WorkingDir": "/work", "Env": ["UV_OFFLINE=1"], "Entrypoint": None, "Cmd": ["bash"]}
SMOKE_OK = "ruff 0.17.1\npytest 9.1.1\nmypy 2.4.0 (compiled: yes)\npyyaml 6.0.3\n"


class FakeDocker:
    def __init__(self, *, extra_layers: int = 2, config: dict[str, Any] | None = None,
                 descriptor: bytes = DESCRIPTOR, smoke: str = SMOKE_OK):
        self.layers = ["sha256:l1", "sha256:l2"] + [f"sha256:new{i}" for i in range(extra_layers)]
        self.config = config if config is not None else dict(CONFIG)
        self.descriptor, self.smoke = descriptor, smoke
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str]) -> str:
        self.calls.append(argv)
        if argv[:2] == ["image", "inspect"]:
            if argv[2] == BASE_ID:
                return json.dumps([{"Id": BASE_ID, "RootFS": {"Layers": ["sha256:l1", "sha256:l2"]}, "Config": CONFIG}])
            return json.dumps([{"Id": LAYERED_ID, "RootFS": {"Layers": self.layers}, "Config": self.config}])
        if argv[0] == "build":
            Path(argv[argv.index("--iidfile") + 1]).write_text(LAYERED_ID)
        if argv[0] == "create":
            return CID + "\n"
        if argv[0] == "cp" and argv[1].startswith(CID):
            Path(argv[2]).write_bytes(self.descriptor)
        if argv[0] == "start":
            return self.smoke
        return ""


def _base(tmp_path: Path) -> Path:
    base = dict(CICD_BASE, descriptor_sha256=hashlib.sha256(DESCRIPTOR).hexdigest())
    base["base_receipt"] = dict(base["base_receipt"], descriptor_sha256=base["descriptor_sha256"])
    path = tmp_path / "cicd.json"
    path.write_text(json.dumps(base))
    return path


def _build(tmp_path: Path, fake: FakeDocker) -> dict[str, Any]:
    result: dict[str, Any] = builder.build_image(_base(tmp_path), TASK / "reference", tmp_path / "proj.json", run=fake,
                                                 recipe=("1" * 40, b"FROM x\n"))
    return result


def test_a_bound_project_layer_writes_a_receipt_the_controller_accepts(tmp_path: Path) -> None:
    fake = FakeDocker()
    receipt = _build(tmp_path, fake)
    supply = rs.RuntimeSupply.from_path(tmp_path / "proj.json")
    rs.require_kind(supply, rs.CICD_PROJECT_RUNTIME)
    assert receipt["tool_versions"] == {"ruff": "0.17.1", "pytest": "9.1.1", "mypy": "2.4.0"}
    assert receipt["project_lock_sha256"] == hashlib.sha256((TASK / "reference" / "uv.lock").read_bytes()).hexdigest()
    assert not any(c[:2] == ["image", "rm"] or c[0] == "rmi" for c in fake.calls)
    create, = [c for c in fake.calls if c[0] == "create"]
    assert create[:3] == ["create", "--network", "none"]


@pytest.mark.parametrize(("fake", "symptom"), [
    (FakeDocker(extra_layers=1), "exactly 2 layers"), (FakeDocker(extra_layers=3), "exactly 2 layers"),
    (FakeDocker(config={**CONFIG, "Env": ["UV_OFFLINE=0"]}), "changed its base's Env"),
    (FakeDocker(descriptor=DESCRIPTOR + b"\n"), "descriptor differs"),
    (FakeDocker(smoke=SMOKE_OK.replace("ruff 0.17.1", "ruff 0.16.0")), "differ from the lock's pins"),
    (FakeDocker(smoke=SMOKE_OK.replace("pyyaml 6.0.3\n", "")), "YAML loader"),
], ids=["one-layer", "three-layers", "env", "descriptor", "tool-version", "no-yaml"])
def test_each_project_layer_binding_check_refuses_its_own_break(tmp_path: Path, fake: FakeDocker,
                                                                symptom: str) -> None:
    with pytest.raises(builder.BuildError, match=symptom):
        _build(tmp_path, fake)
    assert not (tmp_path / "proj.json").exists()


def test_the_project_layer_refuses_a_non_cicd_base(tmp_path: Path) -> None:
    flow_check = tmp_path / "flow.json"
    flow_check.write_text(json.dumps(CICD_BASE["base_receipt"]))
    fake = FakeDocker()
    with pytest.raises(builder.BuildError, match="base receipt refused"):
        builder.build_image(flow_check, TASK / "reference", tmp_path / "proj.json", run=fake, recipe=("1" * 40, b""))
    assert fake.calls == []


def test_a_lock_without_the_tools_is_refused() -> None:
    lock = (TASK / "unpatched-real" / "uv.lock").read_bytes()  # no mypy: the #1478 gap
    with pytest.raises(builder.BuildError, match="mypy"):
        builder.locked_tool_versions(lock)
    assert os.path.basename(str(TASK)) == "cicd-pipeline"
