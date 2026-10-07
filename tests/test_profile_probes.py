"""Tests for a tool-kind dependency's `probes` (skillc#334, orchestrator
ruling mailbox 5896): the explicit, checkable claims a dependency makes,
replacing the pre-#334 assumption that `dep["id"]` doubles as a real
executable name - confirmed false for the real `cpp-codex-flow-check-
ea6dbfa` profile, whose tool ids (`tool-python`, `tool-uv`, `tool-pypi-
runtime`, `tool-make-git-bash`) are labels, not commands.

Covers: `_probe`'s own parse-time refusals, the shared decision functions
(`evaluate_command_probe`/`evaluate_python_import_probe`/
`aggregate_probe_results` - used by both `profile._check_tool` and
`agent_trial`'s in-container preflight, never duplicated), and
`_check_tool`'s own probe-driven behavior including the new
`python-import` kind (not exercised by any pre-#334 fixture).
"""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from skillc import profile as p

FIXTURE = Path(__file__).parent / "fixtures" / "profile-install"


# ------------------------------------------------------------------- _probe


def _profile_with(tmp_path: Path, dep_index: int, **changes: Any) -> Path:
    """A fresh copy of the `profile-install` fixture with `changes` merged
    into `dependencies[dep_index]` - `-1` is always the `python3` tool
    dependency."""
    source = tmp_path / "source"
    shutil.copytree(FIXTURE, source)
    data: dict[str, Any] = copy.deepcopy(p.Profile.load(source / "profile.json").raw)
    deps: list[dict[str, Any]] = data["dependencies"]
    deps[dep_index] = {**deps[dep_index], **changes}
    (source / "profile.json").write_text(json.dumps(data), encoding="utf-8")
    return source / "profile.json"


def test_a_non_tool_dependency_cannot_declare_probes(tmp_path: Path) -> None:
    path = _profile_with(tmp_path, 0, probes=[{"kind": "command", "name": "x"}])
    with pytest.raises(p.Refused, match="probes is tool-only"):
        p.Profile.load(path)


def test_an_unknown_probe_kind_is_refused(tmp_path: Path) -> None:
    path = _profile_with(tmp_path, -1, probes=[{"kind": "registry-key", "name": "x"}])
    with pytest.raises(p.Refused, match="probe kind must be one of"):
        p.Profile.load(path)


def test_a_command_probe_needs_a_non_empty_name(tmp_path: Path) -> None:
    path = _profile_with(tmp_path, -1, probes=[{"kind": "command", "name": ""}])
    with pytest.raises(p.Refused, match="non-empty name"):
        p.Profile.load(path)


def test_a_python_import_probe_needs_non_empty_modules(tmp_path: Path) -> None:
    path = _profile_with(tmp_path, -1, probes=[{"kind": "python-import", "modules": []}])
    with pytest.raises(p.Refused, match="non-empty list of module names"):
        p.Profile.load(path)


# ------------------------------------------------- shared evaluate functions


def test_evaluate_command_probe_absent_is_violated() -> None:
    result = p.evaluate_command_probe({"name": "foo"}, p.CommandProbeOutcome(present=False))
    assert result == {"status": "violated", "reason": "command 'foo' not found"}


def test_evaluate_command_probe_present_no_constraint_is_satisfied() -> None:
    result = p.evaluate_command_probe({"name": "foo", "constraint": None}, p.CommandProbeOutcome(present=True))
    assert result == {"status": "satisfied"}


def test_evaluate_command_probe_meets_constraint() -> None:
    outcome = p.CommandProbeOutcome(present=True, version_output="foo 3.12.3\n")
    result = p.evaluate_command_probe({"name": "foo", "constraint": ">=3.10"}, outcome)
    assert result == {"status": "satisfied", "version": "3.12.3"}


def test_evaluate_command_probe_below_constraint_is_violated() -> None:
    outcome = p.CommandProbeOutcome(present=True, version_output="foo 3.8.0\n")
    result = p.evaluate_command_probe({"name": "foo", "constraint": ">=3.10"}, outcome)
    assert result["status"] == "violated"


def test_evaluate_command_probe_unparseable_version_is_unknown() -> None:
    outcome = p.CommandProbeOutcome(present=True, version_output="not a version")
    result = p.evaluate_command_probe({"name": "foo", "constraint": ">=3.10"}, outcome)
    assert result["status"] == "unknown"


def test_evaluate_command_probe_missing_version_output_is_unknown() -> None:
    outcome = p.CommandProbeOutcome(present=True, version_output=None)
    result = p.evaluate_command_probe({"name": "foo", "constraint": ">=3.10"}, outcome)
    assert result["status"] == "unknown"


def test_evaluate_python_import_probe() -> None:
    assert p.evaluate_python_import_probe(
        {"modules": ["pydantic"]}, p.PythonImportProbeOutcome(succeeded=True),
    ) == {"status": "satisfied"}
    violated = p.evaluate_python_import_probe(
        {"modules": ["pydantic"]}, p.PythonImportProbeOutcome(succeeded=False, error="ModuleNotFoundError"),
    )
    assert violated["status"] == "violated"


def test_aggregate_no_probes_is_unknown_no_probes_declared() -> None:
    assert p.aggregate_probe_results([]) == {"status": "unknown", "reason": "no probes declared"}


def test_aggregate_violated_beats_unknown_beats_satisfied() -> None:
    assert p.aggregate_probe_results([{"status": "satisfied"}])["status"] == "satisfied"
    assert p.aggregate_probe_results([{"status": "satisfied"}, {"status": "unknown", "reason": "x"}])["status"] \
        == "unknown"
    assert p.aggregate_probe_results(
        [{"status": "satisfied"}, {"status": "unknown", "reason": "x"}, {"status": "violated", "reason": "y"}],
    )["status"] == "violated"


# ------------------------------------------------------------- _check_tool


def test_check_tool_with_a_python_import_probe() -> None:
    dep = {"id": "a-tool", "version": "any", "supply": "x",
          "probes": [{"kind": "python-import", "modules": ["this_module_does_not_exist_xyz"]}]}
    result = p._check_tool(dep)
    assert result["status"] == "violated"


def test_check_tool_with_a_real_python_import_probe() -> None:
    dep = {"id": "a-tool", "version": "any", "supply": "x",
          "probes": [{"kind": "python-import", "modules": ["json"]}]}
    result = p._check_tool(dep)
    assert result["status"] == "satisfied"


def test_check_tool_refuses_an_unknown_probe_kind_defensively() -> None:
    """Parse-time (`_probe`) already refuses this - `_check_tool` refuses
    it too, defensively, rather than silently skipping an impossible
    inventory entry (e.g. a hand-built dict bypassing Profile.load)."""
    dep = {"id": "a-tool", "version": "any", "supply": "x", "probes": [{"kind": "registry-key"}]}
    with pytest.raises(p.Refused, match="unknown probe kind"):
        p._check_tool(dep)
