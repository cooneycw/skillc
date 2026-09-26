"""Tests for the demo command (#10): `skillc trial-demo --docker`.

Tested here only against a fake `docker` CLI - no daemon is available in this
session. See `docker_backend`'s own tests and `demo.py`'s module docstring for
what this proves and what is owed to the live run.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from skillc import demo, leak

FAKE_DOCKER = Path(__file__).resolve().parent / "fixtures" / "docker-backend" / "fake_docker.py"


def _docker_bin(state_dir: Path) -> list[str]:
    return [sys.executable, str(FAKE_DOCKER), "--state", str(state_dir)]


def _sentinel(docker_state: Path, name: str) -> None:
    docker_state.mkdir(parents=True, exist_ok=True)
    (docker_state / name).touch()


@pytest.fixture
def docker_state(tmp_path: Path) -> Path:
    return tmp_path / "docker-state"


@pytest.fixture
def base(tmp_path: Path) -> Path:
    path = tmp_path / "demo-run"
    path.mkdir()
    return path


def test_docker_unavailable_prints_setup_and_refuses(
    docker_state: Path, base: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    _sentinel(docker_state, ".down")
    exit_code = demo.run(base=base, docker_bin=_docker_bin(docker_state), image="fake-image:1")
    assert exit_code == 2
    err = capsys.readouterr().err
    assert "docker daemon unreachable" in err
    assert "uv sync" in err  # the setup lines, so the operator can act on the refusal
    assert "evaluation VM" not in err  # operator correction: no VM framing anywhere


def test_demo_succeeds_through_the_real_backend(
    docker_state: Path, base: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = demo.run(base=base, docker_bin=_docker_bin(docker_state), image="fake-image:1")
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "disposition: captured" in out
    assert "liveness_method: canary" in out
    assert "backend_teardown: confirmed" in out
    assert "skillc_version:" in out
    assert "source_commit:" in out


def test_control_correctly_goes_red(docker_state: Path, base: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The demo's own committed negative control: a client that answers
    plausibly without touching the canary must be refused, never captured -
    proving THIS instrument (the demo) can report the other verdict."""
    exit_code = demo.run(control=True, base=base, docker_bin=_docker_bin(docker_state), image="fake-image:1")
    assert exit_code == 0  # 0 means the control correctly went red
    out = capsys.readouterr().out
    assert "disposition: inconclusive" in out
    assert "mode: control" in out


def test_control_reports_failure_if_it_does_not_go_red(
    docker_state: Path, base: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The redcase for the redcase: if the liveness check were broken and the
    reply-only client were wrongly captured, --control must exit non-zero,
    naming the failure - never silently report success on a control that
    did not do its job."""

    def _always_captured(*args: object, **kwargs: object) -> dict[str, object]:
        return {
            "disposition": "captured", "liveness_method": "canary",
            "backend_teardown": "confirmed", "readiness": {}, "signal": None,
        }

    monkeypatch.setattr(demo.lifecycle, "run_through_backend", _always_captured)
    exit_code = demo.run(control=True, base=base, docker_bin=_docker_bin(docker_state), image="fake-image:1")
    assert exit_code == 1


def test_paste_back_block_never_leaks(base: Path) -> None:
    block = demo._paste_back_block(
        "captured", "canary", "confirmed", {"image_digest": "sha256:abc"}, [], control=False,
    )
    findings = list(leak.scan_text(block, leak.load_denylist(None)))
    assert findings == []


def test_host_state_report_detects_a_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    watched = tmp_path / "watched-home"
    watched.mkdir()
    monkeypatch.setattr(demo, "WATCHED_HOST_PATHS", (watched,))
    before = demo._watched_snapshot()
    (watched / "new-file.txt").write_text("surprise\n")
    after = demo._watched_snapshot()
    changes = demo._host_state_report(before, after)
    assert changes == [str(watched)]


def test_host_state_report_is_empty_when_nothing_changed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    watched = tmp_path / "watched-home"
    watched.mkdir()
    monkeypatch.setattr(demo, "WATCHED_HOST_PATHS", (watched,))
    before = demo._watched_snapshot()
    after = demo._watched_snapshot()
    assert demo._host_state_report(before, after) == []
