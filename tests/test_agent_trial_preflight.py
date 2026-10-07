"""Unit tests for `agent_trial._preflight_in_container` (skillc#334,
orchestrator ruling mailbox 5872 steps 2-3, probe design mailbox 5896):
read back every closure file's digest from the LIVE container, and
evaluate every declared tool dependency's own `probes` inside it - never
on the host, and never by treating a dependency's `id` as a real
executable name (confirmed false for the real ea6dbfa profile).

A stub backend (not the fake docker CLI fixture `test_agent_trial.py`
itself uses) is enough here: `_preflight_in_container` only ever calls
`backend.exec_in_attempt(...)`, `backend.export(...)` and (mailbox 5944
fix 2) `backend.remove_file_in_attempt(...)`, so a plain object providing
exactly those three methods tests the function's own logic directly,
without needing a real or fake container at all.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from skillc import agent_trial as at
from skillc.backend import ExecuteResult, Limits

LIMITS = Limits(timeout=5)


class _StubBackend:
    def __init__(self, *, exec_exit_code: int = 0, observations: str = "", remove_result: bool = True) -> None:
        self.exec_exit_code = exec_exit_code
        self.observations = observations
        self.remove_result = remove_result
        self.exec_calls: list[list[str]] = []
        self.export_calls: list[Path] = []
        self.remove_calls: list[str] = []

    def exec_in_attempt(self, handle: object, argv: list[str], limits: Limits) -> ExecuteResult:
        self.exec_calls.append(argv)
        return ExecuteResult(reason="exited", exit_code=self.exec_exit_code)

    def export(self, handle: object, dest: Path) -> None:
        self.export_calls.append(dest)
        (dest / "observations").write_text(self.observations, encoding="utf-8")

    def remove_file_in_attempt(self, handle: object, path: str) -> bool:
        self.remove_calls.append(path)
        return self.remove_result


def _command_tool(dep_id: str, *, name: str, constraint: str | None = None) -> dict[str, Any]:
    probe: dict[str, Any] = {"kind": "command", "name": name}
    if constraint is not None:
        probe["constraint"] = constraint
    return {"id": dep_id, "probes": [probe]}


def _import_tool(dep_id: str, *, modules: list[str]) -> dict[str, Any]:
    return {"id": dep_id, "probes": [{"kind": "python-import", "modules": modules}]}


def test_empty_inputs_does_nothing() -> None:
    backend: Any = _StubBackend()
    at._preflight_in_container(backend, object(), LIMITS, {}, ())
    assert backend.exec_calls == []
    assert backend.export_calls == []
    assert backend.remove_calls == []


def test_a_matching_digest_and_satisfied_command_probe_pass() -> None:
    digest = "a" * 64
    observations = (
        f"{digest}  /home/candidate/.claude/scripts/flow-finish-gate.sh\n"
        f"{at._TOOLS_MARKER}\n"
        "PROBE:0:PRESENT:Python 3.12.3\n"
    )
    backend: Any = _StubBackend(observations=observations)
    at._preflight_in_container(
        backend, object(), LIMITS,
        {".claude/scripts/flow-finish-gate.sh": f"sha256:{digest}"},
        [_command_tool("tool-python", name="python3", constraint=">=3.10")],
    )
    assert len(backend.exec_calls) == 1
    assert len(backend.export_calls) == 1
    # Mailbox 5944 fix 2: the preflight's own observations file is removed
    # from the agent's workspace, not left for the agent or grader to see.
    assert backend.remove_calls == [f"{at.CONTAINER_WORKSPACE}/observations"]


def test_a_command_probe_with_no_constraint_only_checks_presence() -> None:
    observations = f"{at._TOOLS_MARKER}\nPROBE:0:PRESENT:\n"
    backend: Any = _StubBackend(observations=observations)
    at._preflight_in_container(backend, object(), LIMITS, {}, [_command_tool("tool-make", name="make")])


def test_a_satisfied_python_import_probe_passes() -> None:
    observations = f"{at._TOOLS_MARKER}\nPROBE:0:IMPORT_OK\n"
    backend: Any = _StubBackend(observations=observations)
    at._preflight_in_container(
        backend, object(), LIMITS, {}, [_import_tool("tool-pypi-runtime", modules=["pydantic", "yaml"])],
    )


def test_red_case_the_preflight_exec_itself_failing_is_refused() -> None:
    backend: Any = _StubBackend(exec_exit_code=1)
    with pytest.raises(at.HomeFileVerificationRefused, match="preflight script itself failed"):
        at._preflight_in_container(backend, object(), LIMITS, {"x": "sha256:" + "a" * 64}, ())


def test_red_case_a_digest_disagreement_is_refused() -> None:
    observations = f"{'b' * 64}  /home/candidate/x\n{at._TOOLS_MARKER}\n"
    backend: Any = _StubBackend(observations=observations)
    with pytest.raises(at.HomeFileVerificationRefused, match="disagrees with the"):
        at._preflight_in_container(backend, object(), LIMITS, {"x": "sha256:" + "a" * 64}, ())


def test_red_case_a_file_never_read_back_is_refused() -> None:
    observations = f"{at._TOOLS_MARKER}\n"
    backend: Any = _StubBackend(observations=observations)
    with pytest.raises(at.HomeFileVerificationRefused, match="was not read back"):
        at._preflight_in_container(backend, object(), LIMITS, {"x": "sha256:" + "a" * 64}, ())


def test_red_case_a_tool_with_no_probes_is_refused_before_any_exec() -> None:
    """The live-path strictness the orchestrator required (mailbox 5896
    point 3): unlike the host-side receipt's 'unknown, no probes
    declared', a profile-opted live attempt refuses outright - and
    before even building the script, so a probe-less dependency costs
    no exec at all."""
    backend: Any = _StubBackend()
    with pytest.raises(at.HomeFileVerificationRefused, match="declares no probes"):
        at._preflight_in_container(backend, object(), LIMITS, {}, [{"id": "tool-pypi-runtime", "probes": []}])
    assert backend.exec_calls == []


def test_red_case_a_missing_command_is_refused() -> None:
    observations = f"{at._TOOLS_MARKER}\nPROBE:0:ABSENT\n"
    backend: Any = _StubBackend(observations=observations)
    with pytest.raises(at.HomeFileVerificationRefused, match="not satisfied"):
        at._preflight_in_container(backend, object(), LIMITS, {}, [_command_tool("tool-python", name="python3")])


def test_red_case_a_command_below_the_version_constraint_is_refused() -> None:
    observations = f"{at._TOOLS_MARKER}\nPROBE:0:PRESENT:Python 3.8.0\n"
    backend: Any = _StubBackend(observations=observations)
    with pytest.raises(at.HomeFileVerificationRefused, match="not satisfied"):
        at._preflight_in_container(
            backend, object(), LIMITS, {}, [_command_tool("tool-python", name="python3", constraint=">=3.10")],
        )


def test_red_case_a_failed_python_import_is_refused() -> None:
    observations = f"{at._TOOLS_MARKER}\nPROBE:0:IMPORT_FAIL\n"
    backend: Any = _StubBackend(observations=observations)
    with pytest.raises(at.HomeFileVerificationRefused, match="not satisfied"):
        at._preflight_in_container(backend, object(), LIMITS, {}, [_import_tool("tool-pypi-runtime", modules=["pydantic"])])


def test_red_case_an_unknown_probe_kind_is_refused() -> None:
    backend: Any = _StubBackend()
    with pytest.raises(at.HomeFileVerificationRefused, match="unknown probe kind"):
        at._preflight_in_container(
            backend, object(), LIMITS, {}, [{"id": "tool-weird", "probes": [{"kind": "registry-key"}]}],
        )


def test_red_case_export_failure_is_refused() -> None:
    class _ExportFailsBackend(_StubBackend):
        def export(self, handle: object, dest: Path) -> None:
            raise OSError("export failed")

    backend: Any = _ExportFailsBackend()
    with pytest.raises(at.HomeFileVerificationRefused, match="could not export"):
        at._preflight_in_container(backend, object(), LIMITS, {"x": "sha256:" + "a" * 64}, ())


def test_one_combined_exec_and_export_regardless_of_how_many_files_or_tools() -> None:
    """The whole point of combining both checks into one script: N files,
    M tools and however many probes still cost exactly one
    exec_in_attempt and one export."""
    digest = "c" * 64
    observations = (
        f"{digest}  /home/candidate/a\n{digest}  /home/candidate/b\n{digest}  /home/candidate/c\n"
        f"{at._TOOLS_MARKER}\n"
        "PROBE:0:PRESENT:\nPROBE:1:IMPORT_OK\n"
    )
    backend: Any = _StubBackend(observations=observations)
    at._preflight_in_container(
        backend, object(), LIMITS,
        {"a": f"sha256:{digest}", "b": f"sha256:{digest}", "c": f"sha256:{digest}"},
        [_command_tool("tool-make", name="make"), _import_tool("tool-pypi-runtime", modules=["pydantic"])],
    )
    assert len(backend.exec_calls) == 1
    assert len(backend.export_calls) == 1
    assert len(backend.remove_calls) == 1


def test_red_case_the_cleanup_removal_failing_is_refused() -> None:
    """Mailbox 5944 fix 2's own red case: a `remove_file_in_attempt` that
    cannot confirm removal must refuse the attempt, never continue as if
    the workspace were clean when it was never checked."""
    digest = "d" * 64
    observations = f"{digest}  {at.CONTAINER_HOME}/x\n{at._TOOLS_MARKER}\n"
    backend: Any = _StubBackend(observations=observations, remove_result=False)
    with pytest.raises(at.HomeFileVerificationRefused, match="could not remove"):
        at._preflight_in_container(backend, object(), LIMITS, {"x": f"sha256:{digest}"}, ())


def test_a_python_import_probe_with_uv_project_runs_through_uv_run() -> None:
    """Mailbox 5944 fix 1: a probe declaring `uv_project` must be checked
    the way the real runner checks it - `uv run --project
    <CONTAINER_HOME>/<uv_project> python -c ...` - never a bare `python3`,
    which would check the trial image's system interpreter instead of the
    checkout's own isolated venv."""
    observations = f"{at._TOOLS_MARKER}\nPROBE:0:IMPORT_OK\n"
    backend: Any = _StubBackend(observations=observations)
    at._preflight_in_container(
        backend, object(), LIMITS, {},
        [{"id": "tool-pypi-runtime", "probes": [
            {"kind": "python-import", "modules": ["pydantic", "yaml"],
             "uv_project": "Projects/claude-power-pack"},
        ]}],
    )
    script = backend.exec_calls[0][-1]
    assert "uv run --project" in script
    assert f"{at.CONTAINER_HOME}/Projects/claude-power-pack" in script
    assert "python3 -c" not in script
