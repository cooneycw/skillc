"""Tests for grading a probe through an `ExecutionBackend` (#10 PR2).

`FakeProbeBackend` runs the probe as an ordinary host subprocess and says so
in `describe()`'s `unobserved` claim - exactly `tests/test_lifecycle.py`'s
`FakeBackend` discipline (issue #10 comment 5848522578, lesson E17): these
tests prove the DRIVER's sequencing and refusal logic (confirm_stopped as
the sole containment authority, BackendUnavailable never falling back to the
bare-subprocess path, teardown always attempted), never a containment
boundary. No concrete backend exists in this repository at this commit; a
real boundary claim is owed to the live run against `skillc/docker_backend.py`
once it exists.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from skillc import trial as t
from skillc import verify
from skillc.backend import (
    BackendDescription,
    BackendUnavailable,
    Confirmation,
    ExecuteResult,
    Limits,
)

HERE = Path(__file__).resolve().parent
FAKE = HERE / "fixtures" / "trial-subject" / "fake_subject.py"
TASK = HERE.parent / "evals" / "level1" / "slug-small-fix"
REFERENCE = TASK / "reference" / "src" / "slugify.py"
WRONG = TASK / "wrong" / "no-collapse" / "src" / "slugify.py"
GRADER = verify.GraderDef.load(TASK)
RECEIPT = json.loads((HERE.parent / "controls" / "installation-receipt" / "good" / "receipt.json")
                     .read_text(encoding="utf-8"))


def _plan(store: Path) -> tuple[t.Experiment, str]:
    """Minimal local copy of `test_verify.py`'s `_plan` - `tests/` has no
    `__init__.py`, so cross-file imports between test modules are not used
    anywhere else in this codebase either."""
    spec: dict[str, object] = {"experiment": "verify-backend", "trials": [{
        "label": "slug",
        "case": {"id": "slug-small-fix", "revision": "1"},
        "grader": GRADER.identity(),
        "subject": {"digest": "sha256:5a"},
        "client": {"name": "fake", "version": "1"},
        "image": {"digest": "sha256:1a"},
        "config": {"model": "fake-1"},
        "attempts": 1,
    }]}
    experiment = t.plan(spec, store)
    [(_trial, attempt)] = list(experiment.attempts())
    return experiment, str(attempt["attempt_id"])


def _captured(store: Path, base: Path, source: Path) -> tuple[t.Experiment, str]:
    experiment, attempt_id = _plan(store)
    t.add_receipt(experiment, {
        **RECEIPT, "attempt_id": attempt_id, "trial_id": experiment.trial_of(attempt_id)["trial_id"],
        "client": {"name": "fake", "version": "1"},
    })
    workspace = t.allocate_workspace(experiment, attempt_id, base, forbidden=[])
    stop = t.run_attempt(experiment, attempt_id, [sys.executable, str(FAKE), "slug-from", str(source)],
                          cwd=workspace, timeout=20, grace=0.5)
    assert stop["confirmed"] is True
    t.capture(experiment, attempt_id, workspace)
    t.cleanup_workspace(experiment, attempt_id)
    assert t.finalize(experiment, attempt_id)["disposition"] == "captured"
    return experiment, attempt_id


@dataclass
class _Handle:
    root: Path
    destroyed: bool = False


@dataclass
class FakeProbeBackend:
    """Runs the probe as a real host subprocess. Proves the SEQUENCING, never
    a containment boundary - see the module docstring."""

    base: Path
    unavailable_at: str | None = None  # "prepare" | "install"
    force_confirm_stopped: Confirmation | None = None
    force_confirm_absent: Confirmation | None = None
    export_fails: bool = False
    prepared: list[_Handle] = field(default_factory=list)

    def describe(self) -> BackendDescription:
        return BackendDescription(
            name="fake-probe-backend", version="0", isolation=(),
            unobserved=(
                "containment - runs as a host subprocess; proves the driver's sequencing, never a boundary",
            ),
        )

    def prepare(self, attempt_id: str) -> object:
        if self.unavailable_at == "prepare":
            raise BackendUnavailable("fake probe backend forced unavailable at prepare()")
        root = self.base / f"probe-{attempt_id}"
        root.mkdir(parents=True)
        handle = _Handle(root=root)
        self.prepared.append(handle)
        return handle

    def install(self, handle: object, surface: Mapping[str, object]) -> dict[str, object]:
        assert isinstance(handle, _Handle)
        if self.unavailable_at == "install":
            raise BackendUnavailable("fake probe backend forced unavailable at install()")
        for rel, data in surface.items():
            if not isinstance(data, bytes):
                continue
            target = handle.root.joinpath(*rel.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        return {}

    def execute(
        self, handle: object, argv: Sequence[str], limits: Limits,
        cancel: Callable[[], bool] | None = None, stdin: bytes | None = None,
    ) -> ExecuteResult:
        assert isinstance(handle, _Handle)
        # Translate the fixed logical root to this fake's real host directory -
        # what any real backend's OWN internals do; verify.py never sees this.
        real_argv = [
            str(handle.root / Path(a).relative_to(verify.PROBE_WORKDIR))
            if a == verify.PROBE_WORKDIR or a.startswith(verify.PROBE_WORKDIR + "/")
            else a
            for a in argv
        ]
        observations = handle.root / "observations"
        with open(observations, "wb") as out:
            proc = subprocess.Popen(
                real_argv, stdout=out, stderr=subprocess.PIPE,
                stdin=subprocess.PIPE if stdin is not None else None,
            )
            try:
                _, err = proc.communicate(stdin, timeout=limits.timeout)
                return ExecuteResult(reason="exited", exit_code=proc.returncode,
                                      error=err.decode("utf-8", "replace") or None)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                return ExecuteResult(reason="timeout", exit_code=None)

    def confirm_stopped(self, handle: object) -> Confirmation:
        return self.force_confirm_stopped or Confirmation.CONFIRMED

    def export(self, handle: object, dest: Path) -> None:
        assert isinstance(handle, _Handle)
        if self.export_fails:
            raise OSError("fake probe backend forced export() failure")
        shutil.copytree(handle.root, dest, dirs_exist_ok=True)

    def destroy(self, handle: object) -> None:
        assert isinstance(handle, _Handle)
        handle.destroyed = True
        shutil.rmtree(handle.root, ignore_errors=True)

    def confirm_absent(self, handle: object) -> Confirmation:
        return self.force_confirm_absent or Confirmation.CONFIRMED


@pytest.fixture(autouse=True)
def _no_quarantine_leaks() -> object:
    verify.clear_quarantine()
    yield
    verify.clear_quarantine()


@pytest.fixture
def backend(tmp_path: Path) -> FakeProbeBackend:
    root = tmp_path / "backend"
    root.mkdir()
    return FakeProbeBackend(base=root)


def _outcomes(result: dict[str, object]) -> dict[str, str]:
    criteria = result["criteria"]
    assert isinstance(criteria, list)
    return {c["id"]: c["outcome"] for c in criteria}


def test_a_correct_candidate_grades_through_the_backend(
    backend: FakeProbeBackend, tmp_path: Path
) -> None:
    files = [("src/slugify.py", REFERENCE.read_bytes(), False)]
    graded = verify.grade_files(GRADER, files, tmp_path / "grading", backend=backend)
    assert graded.status == "PASS"
    assert graded.containment["confirmed"] is True
    backend_identity = graded.containment["backend"]
    assert isinstance(backend_identity, dict)
    assert backend_identity["name"] == "fake-probe-backend"
    assert graded.containment["teardown"] == "confirmed"
    assert all(h.destroyed for h in backend.prepared)


def test_a_wrong_candidate_fails_through_the_backend(
    backend: FakeProbeBackend, tmp_path: Path
) -> None:
    files = [("src/slugify.py", WRONG.read_bytes(), False)]
    graded = verify.grade_files(GRADER, files, tmp_path / "grading", backend=backend)
    assert graded.status == "FAIL"


def test_grade_records_the_deterministic_tier_and_the_backend_identity(
    backend: FakeProbeBackend, tmp_path: Path
) -> None:
    store = t.open_store(tmp_path / "store", forbidden=[])
    experiment, attempt_id = _captured(store, tmp_path / "work", REFERENCE)
    result = verify.grade(experiment, attempt_id, GRADER, tmp_path / "grading2", backend=backend)
    verification = result["verification"]
    assert isinstance(verification, dict)
    assert verification["grading_tier"] == "deterministic"
    probe_backend = verification["probe_backend"]
    assert isinstance(probe_backend, dict)
    assert probe_backend["name"] == "fake-probe-backend"
    prov = verification["provenance"]
    assert isinstance(prov, dict)
    assert prov["skillc_version"]


def test_backend_unavailable_at_prepare_never_falls_back_to_the_host(tmp_path: Path) -> None:
    backend = FakeProbeBackend(base=tmp_path / "backend", unavailable_at="prepare")
    (tmp_path / "backend").mkdir()
    files = [("src/slugify.py", REFERENCE.read_bytes(), False)]
    graded = verify.grade_files(GRADER, files, tmp_path / "grading", backend=backend)
    assert graded.category == "containment"
    assert graded.containment["backend_unavailable"] is True
    assert all(v == "UNKNOWN" for v in _outcomes({"criteria": graded.criteria}).values())
    assert not backend.prepared  # prepare() itself raised; nothing to tear down


def test_backend_unavailable_at_install_never_falls_back_to_the_host(tmp_path: Path) -> None:
    backend = FakeProbeBackend(base=tmp_path / "backend", unavailable_at="install")
    (tmp_path / "backend").mkdir()
    files = [("src/slugify.py", REFERENCE.read_bytes(), False)]
    graded = verify.grade_files(GRADER, files, tmp_path / "grading", backend=backend)
    assert graded.category == "containment"
    assert graded.containment["backend_unavailable"] is True
    assert backend.prepared[0].destroyed  # install() failed AFTER a handle existed; still torn down


def test_an_unconfirmed_stop_is_never_treated_as_contained(tmp_path: Path) -> None:
    backend = FakeProbeBackend(base=tmp_path / "backend", force_confirm_stopped=Confirmation.UNKNOWN)
    (tmp_path / "backend").mkdir()
    files = [("src/slugify.py", REFERENCE.read_bytes(), False)]
    graded = verify.grade_files(GRADER, files, tmp_path / "grading", backend=backend)
    assert graded.category == "containment"
    assert graded.containment["confirmed"] is False
    reason = graded.containment["reason"]
    assert isinstance(reason, str) and "unknown" in reason
    assert all(v == "UNKNOWN" for v in _outcomes({"criteria": graded.criteria}).values())


def test_an_export_failure_is_not_a_confirmed_probe(tmp_path: Path) -> None:
    backend = FakeProbeBackend(base=tmp_path / "backend", export_fails=True)
    (tmp_path / "backend").mkdir()
    files = [("src/slugify.py", REFERENCE.read_bytes(), False)]
    graded = verify.grade_files(GRADER, files, tmp_path / "grading", backend=backend)
    assert graded.category == "containment"
    assert graded.containment["confirmed"] is False
    reason = graded.containment["reason"]
    assert isinstance(reason, str) and "export failed" in reason


def test_teardown_runs_even_when_the_probe_is_not_confirmed(tmp_path: Path) -> None:
    backend = FakeProbeBackend(base=tmp_path / "backend", force_confirm_stopped=Confirmation.NOT_CONFIRMED)
    (tmp_path / "backend").mkdir()
    files = [("src/slugify.py", REFERENCE.read_bytes(), False)]
    verify.grade_files(GRADER, files, tmp_path / "grading", backend=backend)
    assert all(h.destroyed for h in backend.prepared)
