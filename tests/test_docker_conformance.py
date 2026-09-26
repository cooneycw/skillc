"""Runs interfaces.md's "Conformance cases required before trusting a
backend" table (#80, Refs #10) through the REAL DockerBackend - never an
isolated helper - for every case that is actually a property of the
EXECUTION BACKEND. A case that is fundamentally about the grader or
controller (verify.py / trial.py / records.py), not the backend, is marked
`demonstrated-elsewhere` below and points at its existing test; re-proving it
here through Docker would add a second, weaker copy of an existing control,
not new evidence about the backend.

Tested here only against the fake `docker` CLI (fake_docker.py) - CI's own
Docker-shaped green (orchestrator direction, #80's mailbox assignment). Real
OS-level containment - an actual escaped write, an actual symlink attack,
actual network isolation - is NOT provable against a fake that runs
everything as this same host process; those sub-claims are marked
`owed-to-live-run` explicitly below, never silently assumed proven by a
passing test here. `docs/specs/evaluation-facility/support-matrix.md`
republishes this same table for a reader who is not going to read test code.
"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import pytest

from skillc import docker_backend as d
from skillc import lifecycle
from skillc import trial as t
from skillc.backend import Confirmation, Limits

FAKE_DOCKER = Path(__file__).resolve().parent / "fixtures" / "docker-backend" / "fake_docker.py"
FAKE_CLIENT = Path(__file__).resolve().parent / "fixtures" / "backend-lifecycle" / "fake_client.py"
_SPEC_DIR = Path(__file__).resolve().parent.parent / "docs" / "specs" / "evaluation-facility"
INTERFACES_MD = _SPEC_DIR / "interfaces.md"
SUPPORT_MATRIX_MD = _SPEC_DIR / "support-matrix.md"


def _docker_bin(state_dir: Path) -> list[str]:
    return [sys.executable, str(FAKE_DOCKER), "--state", str(state_dir)]


@pytest.fixture
def base(tmp_path: Path) -> Path:
    path = tmp_path / "work"
    path.mkdir()
    return path


@pytest.fixture
def docker_state(tmp_path: Path) -> Path:
    return tmp_path / "docker-state"


@pytest.fixture
def store(tmp_path: Path) -> Path:
    return t.open_store(tmp_path / "store", forbidden=[])


def _backend(base: Path, docker_state: Path) -> d.DockerBackend:
    return d.DockerBackend(image="fake-image:1", base_dir=base, docker_bin=_docker_bin(docker_state))


def _sentinel(docker_state: Path, name: str) -> None:
    docker_state.mkdir(parents=True, exist_ok=True)
    (docker_state / name).touch()


def _planned(store: Path) -> tuple[t.Experiment, str]:
    spec: dict[str, object] = {
        "experiment": "conformance",
        "trials": [{
            "label": "t", "case": {"id": "c", "revision": "r1"}, "grader": {"id": "g", "revision": "g1"},
            "subject": {"digest": "sha256:00"}, "client": {"name": "fake", "version": "1"},
            "image": {"digest": "sha256:01"}, "config": {}, "attempts": 1,
        }],
    }
    experiment = t.plan(spec, store)
    [(_trial, attempt)] = list(experiment.attempts())
    return experiment, str(attempt["attempt_id"])


def _argv(mode: str) -> list[str]:
    return [sys.executable, str(FAKE_CLIENT), mode]


# ------------------------------------------------------- the conformance table


@dataclasses.dataclass(frozen=True)
class ConformanceCase:
    case: str
    ef_codes: tuple[str, ...]
    status: str  # "demonstrated-here" | "demonstrated-elsewhere" | "owed-to-live-run"
    note: str


CONFORMANCE_CASES: tuple[ConformanceCase, ...] = (
    ConformanceCase(
        case="CPP and a second collection",
        ef_codes=("EF-01",),
        status="demonstrated-elsewhere",
        note=(
            "Not a backend property - the same runner/grader against two "
            "independently-authored collections is skillc materialize's "
            "genericity claim (#7, #11), unrelated to which execution "
            "backend runs a trial. See tests/test_materialize.py::"
            "test_the_subject_guard_sees_a_planted_mattpocock_branch and "
            "::test_the_committed_mattpocock_evidence_is_ready_and_well_formed."
        ),
    ),
    ConformanceCase(
        case="Missing required skill/helper or baseline contamination",
        ef_codes=("EF-03",),
        status="demonstrated-here",
        note=(
            "Narrowly demonstrated (cross-model review, PR #87, caught this "
            "note originally overclaiming the whole row): DockerBackend."
            "install() reports discovery_canary VIOLATED - never SATISFIED - "
            "for the FULLY-EMPTY case, when nothing at all was declared or "
            "copied in. See tests/test_docker_backend.py::"
            "test_install_reports_discovery_canary_violated_when_nothing_is_declared. "
            "NOT demonstrated: detecting ONE missing required helper among "
            "otherwise-successfully-copied files (discovery_canary is "
            "all-or-nothing today, not per-entry) and baseline contamination "
            "(baseline_absence is always reported SATISFIED without "
            "inspecting the image's own contents - describe()'s own "
            "unobserved claim). Whether a controller/verifier turns a "
            "VIOLATED readiness into a hard refusal of the attempt is "
            "trial.py's/verify.py's decision, not this backend's."
        ),
    ),
    ConformanceCase(
        case="Out-of-root write, symlink escape or repeated cleanup",
        ef_codes=("EF-02", "EF-10"),
        status="demonstrated-here",
        note=(
            "Repeated cleanup: destroy()/confirm_absent() are idempotent - "
            "see test_repeated_destroy_and_confirm_absent_are_idempotent "
            "below. Host input immutability: install() only ever READS the "
            "host path it is given (it builds a tar stream in memory; it "
            "never opens the source for writing) - see "
            "test_install_never_modifies_the_host_surface_file below. Actual "
            "out-of-root-write or symlink-escape PREVENTION inside the "
            "container is real OS-level containment the fake CLI cannot "
            "simulate (it runs the subject as this same host process, "
            "unsandboxed) - owed to the live run."
        ),
    ),
    ConformanceCase(
        case="Incorrect output with forged success prose/JSON",
        ef_codes=("EF-04", "EF-08"),
        status="demonstrated-elsewhere",
        note=(
            "Grader-owned, not a backend property - see tests/test_verify.py::"
            "test_forged_success_claims_do_not_change_the_verdict and "
            "::test_a_forged_verdict_on_the_probe_channel_is_not_a_verdict."
        ),
    ),
    ConformanceCase(
        case="Agent replaces local tests, checker or pass file",
        ef_codes=("EF-05", "EF-08"),
        status="demonstrated-elsewhere",
        note=(
            "Grader-owned - see tests/test_verify.py::"
            "test_replaced_local_tests_and_grader_do_not_change_the_verdict."
        ),
    ),
    ConformanceCase(
        case="Candidate code writes verifier outputs",
        ef_codes=("EF-05", "EF-08"),
        status="demonstrated-elsewhere",
        note=(
            "Grader-owned (the verifier's own boundary, not this execution "
            "backend's) - see tests/test_verify.py::"
            "test_a_write_into_the_evidence_store_refuses_the_result, "
            "::test_a_write_to_the_ledger_refuses_the_result, "
            "::test_a_write_to_the_grader_definition_refuses_the_result and "
            "::test_candidate_code_does_not_inherit_the_evaluators_environment. "
            "Whether verify.py's own probe runs through its own "
            "ExecutionBackend instance (interfaces.md step 8, the same "
            "isolation established once) is #10 PR2's join, not this PR's - "
            "this file's test_two_attempts_never_share_container_state shows "
            "the backend-adjacent half that join would rely on: two attempts "
            "never share a container or any copied-in state."
        ),
    ),
    ConformanceCase(
        case="Stale/cross-trial receipt, altered artifact or missing required digest",
        ef_codes=("EF-07", "EF-08"),
        status="demonstrated-elsewhere",
        note=(
            "Controller/records-owned, not a backend property - see "
            "tests/test_verify.py::test_an_attempt_without_a_receipt_is_not_graded, "
            "::test_a_stale_receipt_is_not_graded and "
            "::test_a_modified_artifact_is_not_graded."
        ),
    ),
    ConformanceCase(
        case="Missing events, truncated output or unavailable provider",
        ef_codes=("EF-07",),
        status="demonstrated-here",
        note=(
            "The backend-side half (an unreachable daemon before prepare() "
            "can even dispatch) - see "
            "test_provider_unavailable_through_the_real_backend below, "
            "mirroring tests/test_lifecycle.py::"
            "test_provider_unavailable_before_dispatch_is_unavailable's "
            "scenario against FakeBackend, now against the REAL adapter. The "
            "grader-side half (an unavailable judge) is demonstrated in "
            "tests/test_verify.py::"
            "test_a_judge_that_hangs_or_prints_no_object_is_INCONCLUSIVE."
        ),
    ),
    ConformanceCase(
        case="Always-pass, always-fail, crashed or silent grader",
        ef_codes=("EF-05",),
        status="demonstrated-elsewhere",
        note=(
            "Grader-owned - see tests/test_verify.py::"
            "test_blind_graders_are_the_certification_gates_to_catch and "
            "::test_a_grader_that_gives_no_verdict_stores_INCONCLUSIVE."
        ),
    ),
    ConformanceCase(
        case="Frozen output regraded by the same deterministic grader",
        ef_codes=("EF-05", "EF-08"),
        status="demonstrated-elsewhere",
        note=(
            "Controller/grader-owned - see tests/test_verify.py::"
            "test_a_regrade_repeats_the_outcomes_and_keeps_the_original and "
            "::test_a_regrade_of_nothing_stored_is_refused."
        ),
    ),
)


def test_every_conformance_case_has_a_definite_status_and_a_citation() -> None:
    """A completeness control, not a behavioral one: every row of
    interfaces.md's conformance table must be accounted for here with one of
    the three honest verdicts and a concrete pointer - never left silently
    unaddressed, and never a status with no evidence behind it. Fails if a
    row is ever added to interfaces.md's table without a matching entry here,
    or if a citation is left empty."""
    seen_ef_codes: set[str] = set()
    for case in CONFORMANCE_CASES:
        assert case.status in {"demonstrated-here", "demonstrated-elsewhere", "owed-to-live-run"}
        assert case.note.strip()
        assert case.ef_codes
        seen_ef_codes.update(case.ef_codes)
    # interfaces.md's table cites exactly these codes across its ten rows -
    # a case removed from CONFORMANCE_CASES above would silently narrow this
    # floor, so it is asserted explicitly rather than derived from the list.
    assert seen_ef_codes == {"EF-01", "EF-02", "EF-03", "EF-04", "EF-05", "EF-07", "EF-08", "EF-10"}


def _markdown_table_rows(text: str, heading: str) -> list[list[str]]:
    """Every row (as a list of cell strings) of the FIRST markdown table
    under `heading`, up to the next `## ` heading - skips the header row and
    the `|---|...` separator."""
    _before, _, after = text.partition(heading)
    section, _, _rest = after.partition("\n## ")
    rows: list[list[str]] = []
    seen_header = False
    for line in section.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if not seen_header:
            seen_header = True
            continue  # the header row itself
        if all(set(c) <= {"-"} for c in cells):
            continue  # the |---|---| separator row
        rows.append(cells)
    return rows


def test_every_interfaces_md_conformance_row_has_a_matching_case() -> None:
    """Regression for a cross-model review finding (PR #87): the prior
    completeness check only unioned EF codes, so removing a whole row whose
    codes appear on another row stayed green - dropping the forged-success
    row entirely, for instance, was invisible to it. This reads
    interfaces.md's own table and requires an exact 1:1 name match against
    CONFORMANCE_CASES, catching a removed, renamed or duplicated row.
    Fails on the pre-fix check with that row removed (it would still report
    the same EF code union from the remaining rows)."""
    md_rows = _markdown_table_rows(
        INTERFACES_MD.read_text(encoding="utf-8"),
        "## Conformance cases required before trusting a backend",
    )
    md_case_names = [row[0] for row in md_rows]
    declared_names = [case.case for case in CONFORMANCE_CASES]
    assert set(md_case_names) == set(declared_names)
    assert len(md_case_names) == len(declared_names) == len(CONFORMANCE_CASES)


def test_the_support_matrix_conformance_table_matches_the_declared_cases() -> None:
    """Regression for a cross-model review finding (PR #87): nothing
    previously tied support-matrix.md's own restated table back to
    CONFORMANCE_CASES, despite this file's own module docstring and the
    matrix's own text both claiming they cannot drift apart. Fails on the
    pre-fix state (no such check existed) if the matrix's Status column for
    any case is ever edited to something CONFORMANCE_CASES does not declare."""
    matrix_rows = _markdown_table_rows(
        SUPPORT_MATRIX_MD.read_text(encoding="utf-8"),
        "## Conformance cases (interfaces.md), restated with status",
    )
    matrix_by_case = {row[0]: row[2] for row in matrix_rows}
    declared = {case.case: case.status for case in CONFORMANCE_CASES}
    assert set(matrix_by_case) == set(declared)
    for case_name, declared_status in declared.items():
        # A split case's Status cell combines two statuses in prose (e.g.
        # "demonstrated-here (...) / owed-to-live-run (...)") - a substring
        # match is the honest check here, an exact match would force every
        # split row into a single misleading status instead.
        assert declared_status in matrix_by_case[case_name], (case_name, matrix_by_case[case_name])


# ------------------------------------------------ demonstrated-here, through DockerBackend


def test_full_lifecycle_through_the_real_backend_is_captured_and_torn_down(
    store: Path, base: Path, docker_state: Path,
) -> None:
    """The happy path, through the REAL DockerBackend adapter - not
    FakeBackend. Mirrors tests/test_lifecycle.py::
    test_success_is_captured_and_teardown_confirmed's exact scenario, so the
    two backends can be compared on identical input: FakeBackend proves the
    lifecycle state machine in general, this proves the real adapter plugs
    into it correctly."""
    experiment, attempt_id = _planned(store)
    backend = _backend(base, docker_state)
    record = lifecycle.run_through_backend(
        backend, experiment, attempt_id, _argv("work"), {"skill": "x"}, Limits(timeout=5), base,
    )
    assert record["disposition"] == "captured"
    assert record["backend_teardown"] == "confirmed"
    assert record["liveness_method"] == "canary"


def test_provider_unavailable_through_the_real_backend(
    store: Path, base: Path, docker_state: Path,
) -> None:
    """EF-07's backend-side half: an unreachable daemon must refuse the
    attempt before it is ever dispatched, never fall back to running the
    subject on the host. Mirrors tests/test_lifecycle.py::
    test_provider_unavailable_before_dispatch_is_unavailable's scenario
    against the REAL adapter."""
    _sentinel(docker_state, ".down")
    experiment, attempt_id = _planned(store)
    backend = _backend(base, docker_state)
    record = lifecycle.run_through_backend(
        backend, experiment, attempt_id, _argv("work"), {"skill": "x"}, Limits(timeout=5), base,
    )
    assert record["disposition"] == "unavailable"
    events = [e.get("event") for e in experiment.events(attempt_id)]
    assert "dispatched" not in events


def test_install_never_modifies_the_host_surface_file(
    base: Path, docker_state: Path, tmp_path: Path,
) -> None:
    """EF-02's immutable-inputs half: materializing a declared surface entry
    must never mutate the host file it came from. install() builds an
    in-memory tar stream from it (never opens it for writing), which this
    proves by content and mtime, not merely by not raising."""
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-conformance-000000000001")
    surface_file = tmp_path / "skill.txt"
    surface_file.write_text("original contents\n")
    before_content = surface_file.read_bytes()
    before_mtime = surface_file.stat().st_mtime_ns

    backend.install(handle, {"skill.txt": surface_file})

    assert surface_file.read_bytes() == before_content
    assert surface_file.stat().st_mtime_ns == before_mtime
    backend.destroy(handle)


def test_repeated_destroy_and_confirm_absent_are_idempotent(base: Path, docker_state: Path) -> None:
    """EF-10's repeated-cleanup half: destroy() and confirm_absent() must be
    safe and consistent across more than one call - the Protocol's own
    stated requirement (backend.py: "Both idempotent")."""
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-conformance-000000000002")
    backend.install(handle, {})
    backend.destroy(handle)
    assert backend.confirm_absent(handle) is Confirmation.CONFIRMED
    backend.destroy(handle)  # repeated, on purpose
    assert backend.confirm_absent(handle) is Confirmation.CONFIRMED


def test_two_attempts_never_share_container_state(
    base: Path, docker_state: Path, tmp_path: Path,
) -> None:
    """The backend-adjacent half of "candidate code writes verifier
    outputs"/EF-05, EF-08: two attempts (as an agent's attempt and the
    verifier's own probe would be, per interfaces.md step 8) never share a
    container name or any copied-in state - a file installed into one is
    never visible to the other's export.

    A's own export is checked FIRST and asserted to actually contain the
    file (cross-model review, PR #87): without that positive check, a
    broken install() or export() that silently copies/exports nothing would
    make B's exclusion check pass vacuously - both sides empty proves
    nothing about isolation."""
    backend = _backend(base, docker_state)
    handle_a = backend.prepare("a-conformance-000000000003a")
    handle_b = backend.prepare("a-conformance-000000000003b")
    assert isinstance(handle_a, d._Handle)
    assert isinstance(handle_b, d._Handle)
    assert handle_a.name != handle_b.name

    only_in_a = tmp_path / "only-in-a.txt"
    only_in_a.write_text("secret to a\n")
    readiness_a = backend.install(handle_a, {"only-in-a.txt": only_in_a})
    assert readiness_a["installed"] == 1
    backend.install(handle_b, {})

    dest_a = tmp_path / "export-a"
    backend.export(handle_a, dest_a)
    assert (dest_a / "only-in-a.txt").read_text(encoding="utf-8") == "secret to a\n"

    dest_b = tmp_path / "export-b"
    backend.export(handle_b, dest_b)
    assert not (dest_b / "only-in-a.txt").exists()

    backend.destroy(handle_a)
    backend.destroy(handle_b)
