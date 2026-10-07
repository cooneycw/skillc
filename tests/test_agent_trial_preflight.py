"""Unit tests for `agent_trial._preflight_in_container` (skillc#334,
orchestrator ruling mailbox 5872 steps 2-3): read back every closure
file's digest from the LIVE container, and preflight every declared
tool-kind dependency inside it - never on the host.

A stub backend (not the fake docker CLI fixture `test_agent_trial.py`
itself uses) is enough here: `_preflight_in_container` only ever calls
`backend.exec_in_attempt(...)` and `backend.export(...)`, so a plain
object providing exactly those two methods tests the function's own
logic directly, without needing a real or fake container at all.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from skillc import agent_trial as at
from skillc.backend import ExecuteResult, Limits

LIMITS = Limits(timeout=5)


class _StubBackend:
    def __init__(self, *, exec_exit_code: int = 0, observations: str = "") -> None:
        self.exec_exit_code = exec_exit_code
        self.observations = observations
        self.exec_calls: list[list[str]] = []
        self.export_calls: list[Path] = []

    def exec_in_attempt(self, handle: object, argv: list[str], limits: Limits) -> ExecuteResult:
        self.exec_calls.append(argv)
        return ExecuteResult(reason="exited", exit_code=self.exec_exit_code)

    def export(self, handle: object, dest: Path) -> None:
        self.export_calls.append(dest)
        (dest / "observations").write_text(self.observations, encoding="utf-8")


def test_empty_inputs_does_nothing() -> None:
    backend: Any = _StubBackend()
    at._preflight_in_container(backend, object(), LIMITS, {}, ())  # type: ignore[arg-type]
    assert backend.exec_calls == []
    assert backend.export_calls == []


def test_a_matching_digest_and_present_tool_pass() -> None:
    observations = (
        "sha256:a" + "a" * 63 + "\n"  # placeholder - replaced below
    )
    digest = "a" * 64
    observations = (
        f"{digest}  /home/candidate/.claude/scripts/flow-finish-gate.sh\n"
        f"{at._TOOLS_MARKER}\n"
        "python3 PRESENT Python 3.12.3\n"
    )
    backend: Any = _StubBackend(observations=observations)
    at._preflight_in_container(
        backend, object(), LIMITS,
        {".claude/scripts/flow-finish-gate.sh": f"sha256:{digest}"},
        [{"id": "python3", "version": ">=3.10"}],
    )
    assert len(backend.exec_calls) == 1
    assert len(backend.export_calls) == 1


def test_a_tool_with_no_version_constraint_only_checks_presence() -> None:
    observations = f"{at._TOOLS_MARKER}\nmake PRESENT\n"
    backend: Any = _StubBackend(observations=observations)
    at._preflight_in_container(backend, object(), LIMITS, {}, [{"id": "make", "version": "any"}])


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


def test_red_case_a_missing_tool_is_refused() -> None:
    observations = f"{at._TOOLS_MARKER}\npython3 ABSENT\n"
    backend: Any = _StubBackend(observations=observations)
    with pytest.raises(at.HomeFileVerificationRefused, match="is not present in the container"):
        at._preflight_in_container(backend, object(), LIMITS, {}, [{"id": "python3", "version": "any"}])


def test_red_case_a_tool_present_but_below_the_version_constraint_is_refused() -> None:
    observations = f"{at._TOOLS_MARKER}\npython3 PRESENT Python 3.8.0\n"
    backend: Any = _StubBackend(observations=observations)
    with pytest.raises(at.HomeFileVerificationRefused, match="does not satisfy"):
        at._preflight_in_container(backend, object(), LIMITS, {}, [{"id": "python3", "version": ">=3.10"}])


def test_red_case_an_unparseable_reported_version_is_refused() -> None:
    observations = f"{at._TOOLS_MARKER}\npython3 PRESENT not-a-version\n"
    backend: Any = _StubBackend(observations=observations)
    with pytest.raises(at.HomeFileVerificationRefused, match="could not be determined"):
        at._preflight_in_container(backend, object(), LIMITS, {}, [{"id": "python3", "version": ">=3.10"}])


def test_red_case_export_failure_is_refused() -> None:
    class _ExportFailsBackend(_StubBackend):
        def export(self, handle: object, dest: Path) -> None:
            raise OSError("export failed")

    backend: Any = _ExportFailsBackend()
    with pytest.raises(at.HomeFileVerificationRefused, match="could not export"):
        at._preflight_in_container(backend, object(), LIMITS, {"x": "sha256:" + "a" * 64}, ())


def test_one_combined_exec_and_export_regardless_of_how_many_files_or_tools() -> None:
    """The whole point of combining both checks into one script: N files
    and M tools still cost exactly one exec_in_attempt and one export."""
    digest = "c" * 64
    observations = (
        f"{digest}  /home/candidate/a\n{digest}  /home/candidate/b\n{digest}  /home/candidate/c\n"
        f"{at._TOOLS_MARKER}\n"
        "tool1 PRESENT v1\ntool2 PRESENT v1\n"
    )
    backend: Any = _StubBackend(observations=observations)
    at._preflight_in_container(
        backend, object(), LIMITS,
        {"a": f"sha256:{digest}", "b": f"sha256:{digest}", "c": f"sha256:{digest}"},
        [{"id": "tool1", "version": "any"}, {"id": "tool2", "version": "any"}],
    )
    assert len(backend.exec_calls) == 1
    assert len(backend.export_calls) == 1
