"""Tests for `skillc/gate_overlay.py` (#332, #332 follow-up): the flow-check
gate-witness overlay - moves the real `flow-finish-gate.sh` to a root-owned,
candidate-unwritable harness destination and places the forwarding shim at
the subject-visible path.

Driven against a REAL `DockerBackend` running the fake `docker` CLI
(`tests/fixtures/docker-backend/fake_docker.py`), same discipline as
`test_docker_backend.py` - no daemon is available in this environment, but
`export()`/`install()`/`write_root_owned_file_in_attempt()`'s own real
behavior is exercised, never a hand-typed mock of any of them.

GENUINE UID-BASED WRITE PROTECTION IS NOT DEMONSTRATED HERE (same
limitation `test_docker_backend.py`'s own new tests state): this fixture
has no real per-uid permission model, so `candidate_can_write_in_attempt`
against the fake CLI reflects whatever the HOST user running the test suite
can write, which is always `True` for an ordinary file that user owns.
Tests below either exercise the REAL (always-refusing-here) behavior
directly, or monkeypatch `candidate_can_write_in_attempt` to return `False`
where a confirmed-unwritable harness needs to be simulated - each site says
which, and why. Real-Docker evidence that candidate-uid write protection
actually holds is owed to the real-Docker runner (#315)."""

from __future__ import annotations

import hashlib
import sys
import tempfile
from pathlib import Path

import pytest

from skillc import docker_backend as d
from skillc.gate_overlay import OverlayRefused, apply_flow_check_gate_overlay

FAKE_DOCKER = Path(__file__).resolve().parent / "fixtures" / "docker-backend" / "fake_docker.py"

SUBJECT_PATH = ".claude/scripts/flow-finish-gate.sh"
HARNESS_PATH = "flow-finish-gate.sh"
#: A path under the fake CLI's already-remapped workspace prefix (never
#: an arbitrary host path like the real `/opt/skillc-harness`) - `exec`
#: in this fixture runs a REAL subprocess, and only `/work`/`/home/
#: candidate` are rewritten into the fsroot sandbox (see `test_docker_
#: backend.py`'s own `write_root_owned_file_in_attempt` tests for the
#: same reasoning).
HARNESS_ROOT = f"{d.CONTAINER_WORKSPACE}/skillc-harness"
REAL_SCRIPT = b"#!/bin/bash\necho real-flow-finish-gate\n"
SHIM_CONTENT = b"#!/usr/bin/env python3\nprint('shim')\n"


@pytest.fixture
def base(tmp_path: Path) -> Path:
    path = tmp_path / "work"
    path.mkdir()
    return path


@pytest.fixture
def docker_state(tmp_path: Path) -> Path:
    return tmp_path / "docker-state"


def _backend(base: Path, docker_state: Path) -> d.DockerBackend:
    docker_bin = [sys.executable, str(FAKE_DOCKER), "--state", str(docker_state)]
    return d.DockerBackend(image="fake-image:1", base_dir=base, docker_bin=docker_bin)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_the_real_script_moves_and_the_shim_lands_at_the_subject_path(
    base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The happy path. `candidate_can_write_in_attempt` is monkeypatched
    to `False` (confirmed unwritable) ONLY here - this fixture's own exec
    has no real uid enforcement to produce that signal genuinely (see
    module docstring); every OTHER assertion (digests, destinations, the
    actual bytes placed) is exercised against the REAL backend, unmocked."""
    backend = _backend(base, docker_state)
    monkeypatch.setattr(d.DockerBackend, "candidate_can_write_in_attempt", lambda *a, **k: False)
    handle = backend.prepare("a-overlay-000000000001")
    backend.install(handle, {SUBJECT_PATH: REAL_SCRIPT})
    try:
        record = apply_flow_check_gate_overlay(
            backend, handle, subject_path=SUBJECT_PATH, harness_path=HARNESS_PATH,
            expected_real_digest=_digest(REAL_SCRIPT), expected_shim_digest=_digest(SHIM_CONTENT),
            shim_content=SHIM_CONTENT, harness_root=HARNESS_ROOT,
        )
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            backend.export(handle, dest)
            assert (dest / SUBJECT_PATH).read_bytes() == SHIM_CONTENT
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            backend.export(handle, dest, root=HARNESS_ROOT)
            assert (dest / HARNESS_PATH).read_bytes() == REAL_SCRIPT
    finally:
        backend.destroy(handle)
    assert record.real_script_destination == f"{HARNESS_ROOT}/{HARNESS_PATH}"
    assert record.real_script_digest == _digest(REAL_SCRIPT)
    assert record.shim_destination == SUBJECT_PATH
    assert record.shim_digest == _digest(SHIM_CONTENT)


def test_a_shim_digest_mismatch_is_refused_before_anything_is_written(base: Path, docker_state: Path) -> None:
    """Orchestrator's own named red case: an overlay that places a
    different shim than the declared digest is refused - checked before
    the container is even read, so nothing moves or is written. No
    monkeypatch needed: this refuses before ever reaching the harness
    write/verify steps."""
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-overlay-000000000002")
    backend.install(handle, {SUBJECT_PATH: REAL_SCRIPT})
    try:
        with pytest.raises(OverlayRefused, match="shim content digest"):
            apply_flow_check_gate_overlay(
                backend, handle, subject_path=SUBJECT_PATH, harness_path=HARNESS_PATH,
                expected_real_digest=_digest(REAL_SCRIPT), expected_shim_digest=_digest(b"wrong declared shim"),
                shim_content=SHIM_CONTENT, harness_root=HARNESS_ROOT,
            )
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            backend.export(handle, dest)
            assert (dest / SUBJECT_PATH).read_bytes() == REAL_SCRIPT  # untouched
        assert isinstance(handle, d._Handle)
        assert not (docker_state / f"{handle.name}.fsroot" / "work" / "skillc-harness").exists()
    finally:
        backend.destroy(handle)


def test_a_real_script_digest_mismatch_is_refused_before_moving_it(base: Path, docker_state: Path) -> None:
    """A stale pin, a corrupted install, or calling this before the real
    install finished - whatever the cause, the subject path does not
    currently hold what the overlay was told to expect, so nothing moves."""
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-overlay-000000000003")
    backend.install(handle, {SUBJECT_PATH: b"an unexpected, different real script"})
    try:
        with pytest.raises(OverlayRefused, match="not the declared expected digest"):
            apply_flow_check_gate_overlay(
                backend, handle, subject_path=SUBJECT_PATH, harness_path=HARNESS_PATH,
                expected_real_digest=_digest(REAL_SCRIPT), expected_shim_digest=_digest(SHIM_CONTENT),
                shim_content=SHIM_CONTENT, harness_root=HARNESS_ROOT,
            )
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            backend.export(handle, dest)
            assert (dest / SUBJECT_PATH).read_bytes() == b"an unexpected, different real script"  # untouched
        assert isinstance(handle, d._Handle)
        assert not (docker_state / f"{handle.name}.fsroot" / "work" / "skillc-harness").exists()
    finally:
        backend.destroy(handle)


def test_a_missing_real_script_is_refused_not_guessed(base: Path, docker_state: Path) -> None:
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-overlay-000000000004")
    try:
        with pytest.raises(OverlayRefused, match="could not read the real script"):
            apply_flow_check_gate_overlay(
                backend, handle, subject_path=SUBJECT_PATH, harness_path=HARNESS_PATH,
                expected_real_digest=_digest(REAL_SCRIPT), expected_shim_digest=_digest(SHIM_CONTENT),
                shim_content=SHIM_CONTENT, harness_root=HARNESS_ROOT,
            )
    finally:
        backend.destroy(handle)


def test_a_writable_harness_destination_is_refused(base: Path, docker_state: Path) -> None:
    """Orchestrator's own named red case, exercised for REAL (no
    monkeypatch): `candidate_can_write_in_attempt` against this fixture's
    fake CLI genuinely returns `True` for an ordinary file (no real uid
    enforcement - see module docstring), so calling the overlay with no
    write-protection override demonstrates the exact refusal path a truly
    candidate-writable harness destination would hit. The shim must stay
    unplaced - the real script untouched at the subject path."""
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-overlay-000000000006")
    backend.install(handle, {SUBJECT_PATH: REAL_SCRIPT})
    try:
        with pytest.raises(OverlayRefused, match="writable by the candidate identity"):
            apply_flow_check_gate_overlay(
                backend, handle, subject_path=SUBJECT_PATH, harness_path=HARNESS_PATH,
                expected_real_digest=_digest(REAL_SCRIPT), expected_shim_digest=_digest(SHIM_CONTENT),
                shim_content=SHIM_CONTENT, harness_root=HARNESS_ROOT,
            )
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            backend.export(handle, dest)
            assert (dest / SUBJECT_PATH).read_bytes() == REAL_SCRIPT  # untouched - shim never placed
    finally:
        backend.destroy(handle)


def test_a_writable_containing_directory_is_refused_even_when_the_file_itself_is_not(
    base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Counter-model review finding: a candidate with no write access to
    the harness FILE can still unlink and replace it if the containing
    DIRECTORY is writable - Unix write permission on a file controls its
    contents, write+execute on the directory controls whether it can be
    removed and recreated. The file-level check alone would wrongly
    accept this; the overlay must check the directory too. Monkeypatched
    so the FILE path reports unwritable while the DIRECTORY reports
    writable - isolating the directory check as the one doing the work."""
    harness_destination = f"{HARNESS_ROOT}/{HARNESS_PATH}"

    def fake_check(self: object, handle: object, path: str) -> bool | None:
        return path != harness_destination

    monkeypatch.setattr(d.DockerBackend, "candidate_can_write_in_attempt", fake_check)
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-overlay-000000000010")
    backend.install(handle, {SUBJECT_PATH: REAL_SCRIPT})
    try:
        with pytest.raises(OverlayRefused, match="writable by the candidate identity"):
            apply_flow_check_gate_overlay(
                backend, handle, subject_path=SUBJECT_PATH, harness_path=HARNESS_PATH,
                expected_real_digest=_digest(REAL_SCRIPT), expected_shim_digest=_digest(SHIM_CONTENT),
                shim_content=SHIM_CONTENT, harness_root=HARNESS_ROOT,
            )
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            backend.export(handle, dest)
            assert (dest / SUBJECT_PATH).read_bytes() == REAL_SCRIPT  # untouched
    finally:
        backend.destroy(handle)


def test_red_case_checking_only_the_file_not_the_directory_would_miss_this(
    base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mutation check: a plausible-but-wrong overlay that checks only the
    harness FILE's own write access (the pre-fix shape) would wrongly
    accept the writable-directory case above - the real function's own
    directory check disagrees with that naive version here."""
    harness_destination = f"{HARNESS_ROOT}/{HARNESS_PATH}"

    def fake_check(self: object, handle: object, path: str) -> bool | None:
        return path != harness_destination

    def naive_checks_file_only(path: str) -> bool | None:
        return fake_check(object(), object(), path) if path == harness_destination else None

    monkeypatch.setattr(d.DockerBackend, "candidate_can_write_in_attempt", fake_check)
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-overlay-000000000011")
    backend.install(handle, {SUBJECT_PATH: REAL_SCRIPT})
    try:
        real_refuses = False
        try:
            apply_flow_check_gate_overlay(
                backend, handle, subject_path=SUBJECT_PATH, harness_path=HARNESS_PATH,
                expected_real_digest=_digest(REAL_SCRIPT), expected_shim_digest=_digest(SHIM_CONTENT),
                shim_content=SHIM_CONTENT, harness_root=HARNESS_ROOT,
            )
        except OverlayRefused:
            real_refuses = True
        assert real_refuses, "the real function should refuse a writable containing directory"
        assert naive_checks_file_only(harness_destination) is False, (
            "the naive file-only check should disagree with the real function here - "
            "if it also refuses, this red case is inert"
        )
    finally:
        backend.destroy(handle)


def test_an_unverifiable_harness_destination_is_refused_same_as_writable(
    base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`None` (could not determine) must refuse exactly like `True`
    (confirmed writable) - a harness copy nobody verified is not evidence
    of protection, and must never be treated as an honest `False`."""
    backend = _backend(base, docker_state)
    monkeypatch.setattr(d.DockerBackend, "candidate_can_write_in_attempt", lambda *a, **k: None)
    handle = backend.prepare("a-overlay-000000000007")
    backend.install(handle, {SUBJECT_PATH: REAL_SCRIPT})
    try:
        with pytest.raises(OverlayRefused, match="writable by the candidate identity"):
            apply_flow_check_gate_overlay(
                backend, handle, subject_path=SUBJECT_PATH, harness_path=HARNESS_PATH,
                expected_real_digest=_digest(REAL_SCRIPT), expected_shim_digest=_digest(SHIM_CONTENT),
                shim_content=SHIM_CONTENT, harness_root=HARNESS_ROOT,
            )
    finally:
        backend.destroy(handle)


def test_a_failed_harness_write_is_refused_before_the_shim_moves(
    base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _backend(base, docker_state)
    monkeypatch.setattr(d.DockerBackend, "write_root_owned_file_in_attempt", lambda *a, **k: False)
    handle = backend.prepare("a-overlay-000000000008")
    backend.install(handle, {SUBJECT_PATH: REAL_SCRIPT})
    try:
        with pytest.raises(OverlayRefused, match="could not write the root-owned harness copy"):
            apply_flow_check_gate_overlay(
                backend, handle, subject_path=SUBJECT_PATH, harness_path=HARNESS_PATH,
                expected_real_digest=_digest(REAL_SCRIPT), expected_shim_digest=_digest(SHIM_CONTENT),
                shim_content=SHIM_CONTENT, harness_root=HARNESS_ROOT,
            )
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            backend.export(handle, dest)
            assert (dest / SUBJECT_PATH).read_bytes() == REAL_SCRIPT  # untouched
    finally:
        backend.destroy(handle)


def test_red_case_checking_only_the_shim_content_without_comparing_to_the_declared_digest_would_miss_this(
    base: Path, docker_state: Path,
) -> None:
    """Mutation check: a plausible-but-wrong overlay that computes the
    shim's digest but never compares it against an EXPECTED value (e.g.
    only checks it's valid non-empty bytes) would wrongly accept the
    mismatched-shim case above. This test exists so a future edit that
    drops the comparison is caught by disagreement, not just inspected."""
    def accepts_without_comparing(shim_content: bytes) -> bool:
        return len(shim_content) > 0

    backend = _backend(base, docker_state)
    handle = backend.prepare("a-overlay-000000000005")
    backend.install(handle, {SUBJECT_PATH: REAL_SCRIPT})
    try:
        real_refuses = False
        try:
            apply_flow_check_gate_overlay(
                backend, handle, subject_path=SUBJECT_PATH, harness_path=HARNESS_PATH,
                expected_real_digest=_digest(REAL_SCRIPT), expected_shim_digest=_digest(b"wrong declared shim"),
                shim_content=SHIM_CONTENT, harness_root=HARNESS_ROOT,
            )
        except OverlayRefused:
            real_refuses = True
        assert real_refuses, "the real function should refuse this"
        assert accepts_without_comparing(SHIM_CONTENT) is True, (
            "the naive mutation should disagree with the real function here - "
            "if it also refuses, this red case is inert"
        )
    finally:
        backend.destroy(handle)


def test_red_case_accepting_true_or_none_as_unwritable_would_miss_this(
    base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mutation check for the write-protection verification itself: a
    plausible-but-wrong overlay that treats ANYTHING but a literal `True`
    as "unwritable" (e.g. `if writable is True: refuse`, leaving `None`
    to fall through as accepted) would wrongly accept the unverifiable
    case above. The real function's own check (`if writable is not
    False: refuse`) disagrees with that naive version here."""
    def naive_accepts(writable: bool | None) -> bool:
        return writable is not True  # the wrong check: None falls through as "fine"

    backend = _backend(base, docker_state)
    monkeypatch.setattr(d.DockerBackend, "candidate_can_write_in_attempt", lambda *a, **k: None)
    handle = backend.prepare("a-overlay-000000000009")
    backend.install(handle, {SUBJECT_PATH: REAL_SCRIPT})
    try:
        real_refuses = False
        try:
            apply_flow_check_gate_overlay(
                backend, handle, subject_path=SUBJECT_PATH, harness_path=HARNESS_PATH,
                expected_real_digest=_digest(REAL_SCRIPT), expected_shim_digest=_digest(SHIM_CONTENT),
                shim_content=SHIM_CONTENT, harness_root=HARNESS_ROOT,
            )
        except OverlayRefused:
            real_refuses = True
        assert real_refuses, "the real function should refuse an unverifiable (None) harness destination"
        assert naive_accepts(None) is True, (
            "the naive mutation should disagree with the real function here - "
            "if it also refuses, this red case is inert"
        )
    finally:
        backend.destroy(handle)
