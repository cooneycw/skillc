"""Tests for `skillc/gate_overlay.py` (#332): the flow-check gate-witness
overlay - moves the real `flow-finish-gate.sh` to a harness-only
destination and places the forwarding shim at the subject-visible path.

Driven against a REAL `DockerBackend` running the fake `docker` CLI
(`tests/fixtures/docker-backend/fake_docker.py`), same discipline as
`test_docker_backend.py` - no daemon is available in this environment, but
`export()`/`install()`'s own real behavior is exercised, never a hand-typed
mock of either."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

from skillc import docker_backend as d
from skillc.gate_overlay import OverlayRefused, apply_flow_check_gate_overlay

FAKE_DOCKER = Path(__file__).resolve().parent / "fixtures" / "docker-backend" / "fake_docker.py"

SUBJECT_PATH = ".claude/scripts/flow-finish-gate.sh"
HARNESS_PATH = ".skillc-harness/flow-finish-gate.sh"
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


def test_the_real_script_moves_and_the_shim_lands_at_the_subject_path(base: Path, docker_state: Path) -> None:
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-overlay-000000000001")
    backend.install(handle, {SUBJECT_PATH: REAL_SCRIPT})
    try:
        record = apply_flow_check_gate_overlay(
            backend, handle, subject_path=SUBJECT_PATH, harness_path=HARNESS_PATH,
            expected_real_digest=_digest(REAL_SCRIPT), expected_shim_digest=_digest(SHIM_CONTENT),
            shim_content=SHIM_CONTENT,
        )
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            backend.export(handle, dest)
            assert (dest / HARNESS_PATH).read_bytes() == REAL_SCRIPT
            assert (dest / SUBJECT_PATH).read_bytes() == SHIM_CONTENT
    finally:
        backend.destroy(handle)
    assert record.real_script_destination == HARNESS_PATH
    assert record.real_script_digest == _digest(REAL_SCRIPT)
    assert record.shim_destination == SUBJECT_PATH
    assert record.shim_digest == _digest(SHIM_CONTENT)


def test_a_shim_digest_mismatch_is_refused_before_anything_is_written(base: Path, docker_state: Path) -> None:
    """Orchestrator's own named red case: an overlay that places a
    different shim than the declared digest is refused - checked before
    the container is even read, so nothing moves or is written."""
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-overlay-000000000002")
    backend.install(handle, {SUBJECT_PATH: REAL_SCRIPT})
    try:
        with pytest.raises(OverlayRefused, match="shim content digest"):
            apply_flow_check_gate_overlay(
                backend, handle, subject_path=SUBJECT_PATH, harness_path=HARNESS_PATH,
                expected_real_digest=_digest(REAL_SCRIPT), expected_shim_digest=_digest(b"wrong declared shim"),
                shim_content=SHIM_CONTENT,
            )
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            backend.export(handle, dest)
            assert (dest / SUBJECT_PATH).read_bytes() == REAL_SCRIPT  # untouched
            assert not (dest / HARNESS_PATH).exists()
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
                shim_content=SHIM_CONTENT,
            )
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            backend.export(handle, dest)
            assert (dest / SUBJECT_PATH).read_bytes() == b"an unexpected, different real script"  # untouched
            assert not (dest / HARNESS_PATH).exists()
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
                shim_content=SHIM_CONTENT,
            )
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
                shim_content=SHIM_CONTENT,
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
