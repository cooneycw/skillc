"""Tests for a tool-kind dependency's `probes` (skillc#334, orchestrator
ruling): the explicit, checkable claims a dependency makes,
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


def test_a_command_probe_cannot_declare_uv_project(tmp_path: Path) -> None:
    """`uv_project` only means something for a `python-import` probe - the
    real runner names a `uv run --project` directory, never a command's
    own PATH lookup."""
    path = _profile_with(tmp_path, -1, probes=[{"kind": "command", "name": "x", "uv_project": "lib"}])
    with pytest.raises(p.Refused, match="unknown keys"):
        p.Profile.load(path)


def test_a_python_import_probe_uv_project_must_be_non_empty(tmp_path: Path) -> None:
    path = _profile_with(tmp_path, -1, probes=[{"kind": "python-import", "modules": ["x"], "uv_project": ""}])
    with pytest.raises(p.Refused, match="non-empty string"):
        p.Profile.load(path)


def test_a_python_import_probe_uv_project_cannot_escape(tmp_path: Path) -> None:
    path = _profile_with(
        tmp_path, -1, probes=[{"kind": "python-import", "modules": ["x"], "uv_project": "../../etc"}],
    )
    with pytest.raises(p.Refused, match="safe relative path"):
        p.Profile.load(path)


def test_a_python_import_probe_with_uv_project_round_trips(tmp_path: Path) -> None:
    """The parsed `Probe.uv_project` survives `_probe_record` serialization
    unchanged - the shape `_dep_record` puts into every inventory, and the
    shape `agent_trial`'s in-container preflight reads back out."""
    path = _profile_with(
        tmp_path, -1,
        probes=[{"kind": "python-import", "modules": ["pydantic"], "uv_project": "lib/checkout"}],
    )
    prof = p.Profile.load(path)
    dep = next(d for d in prof.dependencies if d.kind == "tool")
    assert dep.probes[0].uv_project == "lib/checkout"
    record = p._probe_record(dep.probes[0])
    assert record == {"kind": "python-import", "modules": ["pydantic"], "uv_project": "lib/checkout"}


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


def test_red_case_a_matching_version_from_a_failed_command_is_unknown_not_satisfied() -> None:
    """Counter-model review (codex `gpt-6.1-sol`, #334): a version command
    that PRINTS a matching version string but EXITS NONZERO must not be
    read as a confirmed version check - the text could be anything (a
    usage error, a crash) when the command itself reports failure.
    Mutation check: the pre-fix `CommandProbeOutcome` had no
    `version_exit_code` field at all, so this exact input - identical to
    the "meets constraint" case except for the exit code - was
    indistinguishable from a genuine success and reported `satisfied`."""
    outcome = p.CommandProbeOutcome(present=True, version_output="foo 3.12.3\n", version_exit_code=1)
    result = p.evaluate_command_probe({"name": "foo", "constraint": ">=3.10"}, outcome)
    assert result["status"] == "unknown"


def test_evaluate_command_probe_meets_constraint_with_a_confirmed_zero_exit() -> None:
    """Positive control beside the red case above: a matching version
    AND a confirmed exit 0 is still satisfied - the fix narrows what
    counts as confirmed, it does not make the check stricter overall."""
    outcome = p.CommandProbeOutcome(present=True, version_output="foo 3.12.3\n", version_exit_code=0)
    result = p.evaluate_command_probe({"name": "foo", "constraint": ">=3.10"}, outcome)
    assert result == {"status": "satisfied", "version": "3.12.3"}


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


needs_uv = pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not installed")


@needs_uv
def test_check_tool_with_uv_project_satisfied_by_a_stdlib_module(tmp_path: Path) -> None:
    """`json` is stdlib - importable in ANY uv-managed venv regardless of
    declared dependencies - so this proves the `uv run --project` plumbing
    itself works end to end, not merely that the divergence case (below)
    fails for an unrelated reason like `uv` being absent."""
    project = tmp_path / "proj"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        '[project]\nname = "probe-fixture"\nversion = "0.1.0"\nrequires-python = ">=3.9"\ndependencies = []\n',
        encoding="utf-8",
    )
    dep = {"id": "a-tool", "version": "any", "supply": "x",
          "probes": [{"kind": "python-import", "modules": ["json"], "uv_project": "proj"}]}
    result = p._check_tool(dep, tmp_path)
    assert result["status"] == "satisfied"


@needs_uv
def test_red_case_a_module_present_in_this_interpreter_but_absent_from_the_uv_env_is_refused(tmp_path: Path) -> None:
    """Mailbox 5944 fix 1's own stated red case: a package importable by
    THIS interpreter (`pytest` - self-evidently true, since this test
    runs under it) but absent from a freshly created, dependency-less uv
    project's own ISOLATED venv (uv venvs never inherit site-packages)
    must be refused - proving the probe actually runs the checkout's own
    environment rather than falling back to the interpreter running the
    check itself."""
    import pytest as _pytest_self_check  # noqa: F401 - importability is the point
    project = tmp_path / "proj"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        '[project]\nname = "probe-fixture"\nversion = "0.1.0"\nrequires-python = ">=3.9"\ndependencies = []\n',
        encoding="utf-8",
    )
    dep = {"id": "a-tool", "version": "any", "supply": "x",
          "probes": [{"kind": "python-import", "modules": ["pytest"], "uv_project": "proj"}]}
    result = p._check_tool(dep, tmp_path)
    assert result["status"] == "violated"


#: Issue #365's fixture module: a name no real environment carries, so an
#: import of it succeeds only through the one channel a test plants it in.
_PLANTED = "skillc_probe_fixture_dep_365"


def _empty_uv_project(home: Path) -> dict[str, Any]:
    """A dependency-less uv project at `<home>/proj`, and a tool dependency
    whose probe imports `_PLANTED` inside it."""
    project = home / "proj"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        '[project]\nname = "probe-fixture"\nversion = "0.1.0"\nrequires-python = ">=3.9"\ndependencies = []\n',
        encoding="utf-8",
    )
    return {"id": "a-tool", "version": "any", "supply": "x",
            "probes": [{"kind": "python-import", "modules": [_PLANTED], "uv_project": "proj"}]}


def _plant(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{_PLANTED}.py").write_text("PLANTED = True\n", encoding="utf-8")


@pytest.fixture
def no_ambient_probe_overrides(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Each #365 case plants exactly one channel; strip any the CI or a
    developer shell already carries, so a pass cannot ride an ambient one."""
    for key in ("UV_PROJECT_ENVIRONMENT", "PYTHONPATH", "PYTHONUSERBASE", "VIRTUAL_ENV", "PYTHONNOUSERSITE"):
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


@needs_uv
def test_red_case_365_an_ambient_UV_PROJECT_ENVIRONMENT_cannot_satisfy_the_probe(
    tmp_path: Path, no_ambient_probe_overrides: pytest.MonkeyPatch,
) -> None:
    """#365: `UV_PROJECT_ENVIRONMENT` pointing at a venv that HAS the module,
    against an installed project that LACKS it. Pre-fix the probe ran inside
    the pointed-at venv and reported `satisfied`. The venv is a throwaway one,
    never this test run's own: the nested `uv run` may reconcile whatever
    environment it is pointed at."""
    import subprocess
    import sys

    dep = _empty_uv_project(tmp_path)
    external = tmp_path / "external-venv"
    subprocess.run(["uv", "venv", "--quiet", "--python", sys.executable, str(external)], check=True)
    site_packages = next(external.glob("lib/python3.*/site-packages"))
    _plant(site_packages)
    # The fixture is real: the external venv's own interpreter imports it.
    assert subprocess.run([str(external / "bin" / "python"), "-c", f"import {_PLANTED}"], check=False).returncode == 0
    no_ambient_probe_overrides.setenv("UV_PROJECT_ENVIRONMENT", str(external))
    assert p._check_tool(dep, tmp_path)["status"] == "violated"


@needs_uv
def test_red_case_365_an_ambient_PYTHONPATH_cannot_satisfy_the_probe(
    tmp_path: Path, no_ambient_probe_overrides: pytest.MonkeyPatch,
) -> None:
    """#365's second channel: the probe used to APPEND the ambient
    `PYTHONPATH` after the project dir, so a dev env's site-packages listed
    there satisfied the import as well as the project's own venv would."""
    dep = _empty_uv_project(tmp_path)
    ambient = tmp_path / "ambient-site"
    _plant(ambient)
    no_ambient_probe_overrides.setenv("PYTHONPATH", str(ambient))
    assert p._check_tool(dep, tmp_path)["status"] == "violated"


@needs_uv
def test_365_a_user_site_module_does_not_satisfy_the_probe(
    tmp_path: Path, no_ambient_probe_overrides: pytest.MonkeyPatch,
) -> None:
    """#365, the orchestrator's third channel: a module only in a
    `PYTHONUSERBASE` site-packages. uv's project venv disables the user site,
    so this holds without the probe scrubbing anything - shown, not assumed:
    the path is asked of the project's own interpreter, and the same placement
    IS importable by that venv's base interpreter (user site enabled), so a
    misplaced module cannot make this pass vacuously."""
    import os
    import subprocess

    dep = _empty_uv_project(tmp_path)
    userbase = tmp_path / "userbase"
    env = {**os.environ, "PYTHONUSERBASE": str(userbase)}
    asked = subprocess.run(
        ["uv", "run", "--quiet", "--project", str(tmp_path / "proj"), "python", "-c",
         "import site, sys; print(site.getusersitepackages()); print(sys._base_executable)"],
        capture_output=True, text=True, check=True, env=env,
    )
    user_site, base_python = asked.stdout.split()
    assert Path(user_site).is_relative_to(userbase)
    _plant(Path(user_site))
    # Positive control: where the user site IS enabled, this placement imports.
    assert subprocess.run([base_python, "-c", f"import {_PLANTED}"], env=env, check=False).returncode == 0
    no_ambient_probe_overrides.setenv("PYTHONUSERBASE", str(userbase))
    assert p._check_tool(dep, tmp_path)["status"] == "violated"


@needs_uv
def test_red_case_365_a_module_in_the_callers_working_directory_cannot_satisfy_the_probe(
    tmp_path: Path, no_ambient_probe_overrides: pytest.MonkeyPatch,
) -> None:
    """#365 counter-model review: `python -c` searches the working directory
    first and `uv run --project` does not change it, so a module sitting only
    in the CALLER's directory satisfied the probe. The probe now runs in the
    project dir."""
    dep = _empty_uv_project(tmp_path)
    caller = tmp_path / "caller-cwd"
    _plant(caller)
    no_ambient_probe_overrides.chdir(caller)
    assert p._check_tool(dep, tmp_path)["status"] == "violated"


@needs_uv
def test_red_case_365_a_broken_module_in_the_callers_directory_cannot_shadow_the_projects(
    tmp_path: Path, no_ambient_probe_overrides: pytest.MonkeyPatch,
) -> None:
    """The other direction of the same channel: a same-named module that
    raises, in the caller's directory, used to shadow the project's valid
    copy and turn real evidence into `violated`."""
    dep = _empty_uv_project(tmp_path)
    _plant(tmp_path / "proj")
    caller = tmp_path / "caller-cwd"
    caller.mkdir()
    (caller / f"{_PLANTED}.py").write_text("raise ImportError('shadow from the caller directory')\n", encoding="utf-8")
    no_ambient_probe_overrides.chdir(caller)
    assert p._check_tool(dep, tmp_path)["status"] == "satisfied"


@needs_uv
def test_365_an_ambient_PYTHONHOME_does_not_reach_the_probe(
    tmp_path: Path, no_ambient_probe_overrides: pytest.MonkeyPatch,
) -> None:
    """`PYTHONHOME` is dropped: forwarded, a bogus one breaks interpreter
    startup and turns genuine project evidence into `violated`."""
    dep = _empty_uv_project(tmp_path)
    _plant(tmp_path / "proj")
    no_ambient_probe_overrides.setenv("PYTHONHOME", str(tmp_path / "no-such-python-home"))
    assert p._check_tool(dep, tmp_path)["status"] == "satisfied"


@needs_uv
def test_365_a_relative_home_still_probes_the_declared_project(
    tmp_path: Path, no_ambient_probe_overrides: pytest.MonkeyPatch,
) -> None:
    """The probe now runs in the project dir, so a RELATIVE home must be made
    absolute first, or `--project <relative>` would resolve against the new
    working directory instead of the caller's."""
    dep = _empty_uv_project(tmp_path)
    _plant(tmp_path / "proj")
    no_ambient_probe_overrides.chdir(tmp_path)
    assert p._check_tool(dep, Path("."))["status"] == "satisfied"


@needs_uv
def test_365_uv_found_through_a_relative_PATH_entry_still_runs_from_the_project_dir(
    tmp_path: Path, no_ambient_probe_overrides: pytest.MonkeyPatch,
) -> None:
    """#365 review, second pass: the probe runs in the project dir, so a `uv`
    that `shutil.which` found through a RELATIVE `PATH` entry must be made
    absolute first, or it no longer resolves and a valid project reads as
    `violated`."""
    import os

    real_uv = shutil.which("uv")
    assert real_uv is not None
    dep = _empty_uv_project(tmp_path)
    _plant(tmp_path / "proj")
    (tmp_path / "relbin").mkdir()
    (tmp_path / "relbin" / "uv").symlink_to(real_uv)
    no_ambient_probe_overrides.chdir(tmp_path)
    no_ambient_probe_overrides.setenv("PATH", f"relbin{os.pathsep}{os.environ['PATH']}")
    assert shutil.which("uv") == os.path.join("relbin", "uv")  # the relative entry wins
    assert p._check_tool(dep, tmp_path)["status"] == "satisfied"


@needs_uv
def test_365_control_a_module_in_the_declared_project_satisfies_the_probe(
    tmp_path: Path, no_ambient_probe_overrides: pytest.MonkeyPatch,
) -> None:
    """Control for the #365 reds: the same module, placed in the declared
    project directory itself, is genuine project evidence and must pass - so
    the reds above fail on the channel they plant, not on the fixture."""
    dep = _empty_uv_project(tmp_path)
    _plant(tmp_path / "proj")
    assert p._check_tool(dep, tmp_path)["status"] == "satisfied"


def test_gather_python_import_probe_host_uv_project_needs_a_home() -> None:
    outcome = p._gather_python_import_probe_host({"modules": ["json"], "uv_project": "proj"}, None)
    assert outcome.succeeded is False
    assert "home" in outcome.error


def test_gather_python_import_probe_host_uv_project_dir_must_exist(tmp_path: Path) -> None:
    outcome = p._gather_python_import_probe_host({"modules": ["json"], "uv_project": "nope"}, tmp_path)
    assert outcome.succeeded is False
    assert "not installed" in outcome.error


def test_gather_command_probe_host_captures_a_real_nonzero_exit(tmp_path: Path) -> None:
    """Counter-model review (codex `gpt-6.1-sol`, #334): a REAL executable
    (not a synthetic outcome) that prints a matching version string and
    exits 1 - `_gather_command_probe_host` must capture that exit code,
    never discard it, so `evaluate_command_probe` can refuse to certify
    a version check the command itself reported failing."""
    script = tmp_path / "fake-tool"
    script.write_text("#!/bin/sh\necho 'fake-tool 9.9.9'\nexit 1\n", encoding="utf-8")
    script.chmod(0o755)
    probe = {"name": str(script), "constraint": ">=1.0", "version_args": ["--version"]}
    outcome = p._gather_command_probe_host(probe)
    assert outcome.present is True
    assert outcome.version_exit_code == 1
    result = p.evaluate_command_probe(probe, outcome)
    assert result["status"] == "unknown"
