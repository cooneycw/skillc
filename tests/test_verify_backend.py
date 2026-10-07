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

import contextlib
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
    destroy_raises: bool = False
    confirm_absent_raises: bool = False
    #: Simulates issue #186's DockerBackend write-back failure at the
    #: reader's end: "missing" never writes `observations` at all (the
    #: subject exited fine, but the capture never landed); "directory"
    #: writes a directory there instead (what a dereferenced or otherwise-
    #: failed write-back could leave in an exported copy). Neither is what
    #: THIS fake's own `execute()` naturally produces - real
    #: `DockerBackend.execute()` never leaves either state reachably by a
    #: caller before #186, since it never reported the failure at all.
    observations_missing_as: str | None = None  # "missing" | "directory"
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

    def install(self, handle: object, surface: Mapping[str, object], root: str | None = None) -> dict[str, object]:
        assert isinstance(handle, _Handle)
        if self.unavailable_at == "install":
            raise BackendUnavailable("fake probe backend forced unavailable at install()")
        for rel, data in surface.items():
            if not isinstance(data, bytes):
                continue
            target = handle.root.joinpath(*rel.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        # Demonstrates verify.SURFACE_EXECUTABLE_KEY end to end (codex review:
        # the bytes-only convention otherwise drops the executable bit).
        executable = surface.get(verify.SURFACE_EXECUTABLE_KEY)
        if isinstance(executable, list):
            for rel in executable:
                assert isinstance(rel, str)
                handle.root.joinpath(*rel.split("/")).chmod(0o700)
        return {}

    def exec_in_attempt(
        self, handle: object, argv: Sequence[str], limits: Limits,
        cancel: Callable[[], bool] | None = None, stdin: bytes | None = None,
        cwd: str | None = None, env: object = None,
    ) -> ExecuteResult:
        """#269 added this to the `ExecutionBackend` Protocol; verify.py's
        probe path never calls it - unsupported here, same as
        `ManagedBackend`'s own answer, satisfied only for structural typing."""
        del handle, argv, limits, cancel, stdin, cwd, env
        return ExecuteResult(reason="unsupported", exit_code=None)

    def resolve_realpath_in_attempt(self, handle: object, path: str, timeout: float = 2.0) -> str | None:
        """#332 added this to the Protocol; verify.py's probe path never
        calls it - `None` unconditionally, satisfied only for structural
        typing."""
        del handle, path, timeout
        return None

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
        if self.observations_missing_as == "directory":
            observations.mkdir()
        with contextlib.ExitStack() as stack:
            out_file = (
                None if self.observations_missing_as is not None
                else stack.enter_context(open(observations, "wb"))
            )
            proc = subprocess.Popen(
                real_argv, stdout=(subprocess.DEVNULL if out_file is None else out_file),
                stderr=subprocess.PIPE, stdin=subprocess.PIPE if stdin is not None else None,
            )
            # "directory" mirrors the real #186 failure mode (the write-back
            # itself fails); "missing" is a reader-robustness case with no
            # real `DockerBackend` equivalent (it always attempts a write),
            # so it is left unreported here, exactly like every OTHER fake
            # in this module that does not model `observations_capture` at
            # all - `ExecuteResult`'s own default (`None`).
            if self.observations_missing_as == "directory":
                observations_capture = "failed"
            elif self.observations_missing_as is None:
                observations_capture = "written"
            else:
                observations_capture = None
            try:
                _, err = proc.communicate(stdin, timeout=limits.timeout)
                return ExecuteResult(reason="exited", exit_code=proc.returncode,
                                      error=err.decode("utf-8", "replace") or None,
                                      observations_capture=observations_capture)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                return ExecuteResult(reason="timeout", exit_code=None)

    def confirm_stopped(self, handle: object) -> Confirmation:
        return self.force_confirm_stopped or Confirmation.CONFIRMED

    def export(self, handle: object, dest: Path, root: str | None = None) -> None:
        assert isinstance(handle, _Handle)
        if self.export_fails:
            raise OSError("fake probe backend forced export() failure")
        shutil.copytree(handle.root, dest, dirs_exist_ok=True)

    def destroy(self, handle: object) -> None:
        assert isinstance(handle, _Handle)
        if self.destroy_raises:
            raise RuntimeError("fake probe backend forced destroy() failure")
        handle.destroyed = True
        shutil.rmtree(handle.root, ignore_errors=True)

    def confirm_absent(self, handle: object) -> Confirmation:
        if self.confirm_absent_raises:
            raise RuntimeError("fake probe backend forced confirm_absent() failure")
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


def test_a_missing_observations_never_grades_pass(backend: FakeProbeBackend, tmp_path: Path) -> None:
    """Acceptance item for issue #186 (reader half): a missing
    `observations`, with no `observations_capture` reported at all (no real
    `DockerBackend` path leaves it unreported like this - every OTHER fake
    in this module already does, and this is exactly that same convention),
    still cannot grade PASS: `verify._read_observations` reads it as an
    empty report, and `grade_slug.py`'s own `read_report` turns that into
    `{"import_error": "the probe produced no report"}`, which the
    functional-correctness criterion never satisfies. This is the pre-#186
    safety net alone - `observations_capture` plays no part here."""
    backend.observations_missing_as = "missing"
    files = [("src/slugify.py", REFERENCE.read_bytes(), False)]  # otherwise-correct candidate
    graded = verify.grade_files(GRADER, files, tmp_path / "grading", backend=backend)
    assert graded.status != "PASS"


def test_a_failed_observations_capture_refuses_before_any_judge_runs(
    backend: FakeProbeBackend, tmp_path: Path,
) -> None:
    """Red case (issue #186, orchestrator review): reporting
    `observations_capture` was not enough - acceptance item 3 says UNKNOWN,
    and nothing consumed the field to make that happen structurally. Before
    this fix, a failed capture read as an empty report and graded FAIL
    (`report-present`/`task-complete` VIOLATED) - a measurement that did not
    complete asserting the candidate did something wrong, which #9's own
    "derive status, never copy a claim" discipline never intended to permit
    for the INVERSE case (deriving a violation from an absence of
    measurement). Fixed in ONE place, `grade_files` itself: `"failed"`
    is treated the way lost containment already is - `category` becomes
    `"capture"`, every criterion UNKNOWN, `status` INCONCLUSIVE, the judge
    never runs at all. Structural: covers every grader, including ones not
    yet written, no judge change needed. Fails on `2ebb855` (currently
    FAIL, from the empty-report path, not INCONCLUSIVE)."""
    backend.observations_missing_as = "directory"
    files = [("src/slugify.py", REFERENCE.read_bytes(), False)]  # otherwise-correct candidate
    graded = verify.grade_files(GRADER, files, tmp_path / "grading", backend=backend)
    assert graded.category == "capture"
    assert graded.status == "INCONCLUSIVE"


def test_grade_records_the_deterministic_tier_and_the_backend_identity(
    backend: FakeProbeBackend, tmp_path: Path
) -> None:
    store = t.open_store(tmp_path / "store", forbidden=[])
    experiment, attempt_id = _captured(store, tmp_path / "work", REFERENCE)
    result = verify.grade(experiment, attempt_id, GRADER, tmp_path / "grading2", backend=backend)
    verification = result["verification"]
    assert isinstance(verification, dict)
    assert verification["tiers_enabled"] == ["deterministic"]
    verdicts = verification["verdicts"]
    assert isinstance(verdicts, dict)
    assert set(verdicts) == {"deterministic"}
    deterministic = verdicts["deterministic"]
    assert deterministic["status"] == result["status"]
    assert deterministic["criteria"] == result["criteria"]
    probe_backend = deterministic["backend"]
    assert isinstance(probe_backend, dict)
    assert probe_backend["name"] == "fake-probe-backend"
    disagreement = verification["disagreement"]
    assert disagreement == {"available": False, "reason": "fewer than two judge tiers"}
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


def test_an_unconfirmed_stop_quarantines_the_next_grading_run(tmp_path: Path) -> None:
    """codex review: a lost backend containment must quarantine, exactly as
    the bare-subprocess path's unswept-descendant case already does."""
    backend = FakeProbeBackend(base=tmp_path / "backend", force_confirm_stopped=Confirmation.UNKNOWN)
    (tmp_path / "backend").mkdir()
    files = [("src/slugify.py", REFERENCE.read_bytes(), False)]
    verify.grade_files(GRADER, files, tmp_path / "grading", backend=backend)

    clean_backend = FakeProbeBackend(base=tmp_path / "backend2")
    (tmp_path / "backend2").mkdir()
    with pytest.raises(verify.Refused, match="quarantined"):
        verify.grade_files(GRADER, files, tmp_path / "grading2", backend=clean_backend)


def test_an_unconfirmed_teardown_quarantines_the_next_grading_run(tmp_path: Path) -> None:
    backend = FakeProbeBackend(base=tmp_path / "backend", force_confirm_absent=Confirmation.NOT_CONFIRMED)
    (tmp_path / "backend").mkdir()
    files = [("src/slugify.py", REFERENCE.read_bytes(), False)]
    verify.grade_files(GRADER, files, tmp_path / "grading", backend=backend)

    clean_backend = FakeProbeBackend(base=tmp_path / "backend2")
    (tmp_path / "backend2").mkdir()
    with pytest.raises(verify.Refused, match="quarantined"):
        verify.grade_files(GRADER, files, tmp_path / "grading2", backend=clean_backend)


def test_a_destroy_exception_still_quarantines_and_propagates(tmp_path: Path) -> None:
    """codex review: teardown itself must not be able to skip quarantine. The
    ORIGINAL exception still propagates - a raised destroy() is a real
    infrastructure failure this grading run legitimately fails on - but every
    LATER grading run must refuse until an operator clears it, since nothing
    established the candidate-controlled process/resources are gone."""
    backend = FakeProbeBackend(base=tmp_path / "backend", destroy_raises=True)
    (tmp_path / "backend").mkdir()
    files = [("src/slugify.py", REFERENCE.read_bytes(), False)]
    with pytest.raises(RuntimeError, match="destroy"):
        verify.grade_files(GRADER, files, tmp_path / "grading", backend=backend)

    clean_backend = FakeProbeBackend(base=tmp_path / "backend2")
    (tmp_path / "backend2").mkdir()
    with pytest.raises(verify.Refused, match="quarantined"):
        verify.grade_files(GRADER, files, tmp_path / "grading2", backend=clean_backend)


def test_a_confirm_absent_exception_still_quarantines_and_propagates(tmp_path: Path) -> None:
    backend = FakeProbeBackend(base=tmp_path / "backend", confirm_absent_raises=True)
    (tmp_path / "backend").mkdir()
    files = [("src/slugify.py", REFERENCE.read_bytes(), False)]
    with pytest.raises(RuntimeError, match="confirm_absent"):
        verify.grade_files(GRADER, files, tmp_path / "grading", backend=backend)

    clean_backend = FakeProbeBackend(base=tmp_path / "backend2")
    (tmp_path / "backend2").mkdir()
    with pytest.raises(verify.Refused, match="quarantined"):
        verify.grade_files(GRADER, files, tmp_path / "grading2", backend=clean_backend)


def test_the_probe_surface_names_which_candidate_paths_need_the_executable_bit() -> None:
    files = [("src/slugify.py", b"data", False), ("bin/run.sh", b"#!/bin/sh\n", True)]
    surface = verify._probe_surface(GRADER, GRADER.read(), files)
    assert surface[verify.SURFACE_EXECUTABLE_KEY] == ["candidate/bin/run.sh"]
    assert surface["candidate/src/slugify.py"] == b"data"
    assert surface["candidate/bin/run.sh"] == b"#!/bin/sh\n"


def test_the_probe_argv_uses_a_portable_interpreter_name_not_a_host_path() -> None:
    """codex review: `sys.executable` is the VERIFIER's own interpreter path
    (e.g. under this host's .venv), which a real backend's isolation has no
    reason to contain."""
    assert verify.PROBE_INTERPRETER == "python3"
    assert "/" not in verify.PROBE_INTERPRETER
