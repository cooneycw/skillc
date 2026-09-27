"""Tests for the operator demo command (#81, sub-issue of #10).

Every test here runs against the fake `docker` CLI
(`tests/fixtures/docker-backend/fake_docker.py`), exactly like
`tests/test_docker_backend.py` - no real daemon is available in this session,
and `skillc/demo.py`'s own module docstring says so plainly: #10 closes only
on the operator's own live run of this command against a real daemon, never
on these tests passing.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from skillc import demo, reap
from skillc.docker_backend import DAEMON_TIMEOUT
from skillc.verify import Graded

FAKE_DOCKER = Path(__file__).resolve().parent / "fixtures" / "docker-backend" / "fake_docker.py"


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


def _seeded_leak_text() -> str:
    """A planted home-path leak for the tests below. Built from fragments on
    purpose, exactly as `skillc/demo.py`'s own `run_control` does: this file
    is not on the repo-wide `leak-check .` CI gate's exclude list (unlike
    `tests/test_leak.py`, which is), so a single literal here would make this
    test file itself the leak. `leak_check_text` still catches it at runtime
    because it scans the assembled string, not this source line."""
    return "planted host value: " + "/home/" + "exampleuser" + "/leaked\n"


# --------------------------------------------------------------- run_demo


def test_run_demo_happy_path_is_ok_with_every_item_met(base: Path, docker_state: Path) -> None:
    result = demo.run_demo(image="fake-image:1", docker_bin=_docker_bin(docker_state), base=base, timeout=5)
    assert result.ok is True
    assert "NOT MET" not in result.paste_back
    assert result.lifecycle_record["disposition"] == "captured"
    assert result.graded.status == "PASS"
    assert result.reap_report.daemon_reachable is True
    assert result.image_digest == "sha256:fake-digest-for-fake-image:1"


def test_run_demo_records_the_image_digest_that_actually_ran(base: Path, docker_state: Path) -> None:
    """Two different `image` values must produce two different recorded
    digests - proving this reads the daemon's own answer rather than a fixed
    or derived-from-nothing string."""
    result_a = demo.run_demo(image="fake-image:1", docker_bin=_docker_bin(docker_state), base=base, timeout=5)
    result_b = demo.run_demo(image="fake-image:2", docker_bin=_docker_bin(docker_state), base=base, timeout=5)
    assert result_a.image_digest != result_b.image_digest


def test_run_demo_paste_back_is_leak_clean(base: Path, docker_state: Path) -> None:
    """The happy path's own paste-back block must pass its own leak-check -
    printing it via `print_paste_back` must not raise."""
    result = demo.run_demo(image="fake-image:1", docker_bin=_docker_bin(docker_state), base=base, timeout=5)
    demo.print_paste_back(result.paste_back)  # raises PasteBackRefused on failure


# ------------------------------------------------------------- run_control


def test_run_control_reports_every_seeded_failure_caught(base: Path, docker_state: Path) -> None:
    ok = demo.run_control(image="fake-image:1", docker_bin=_docker_bin(docker_state), base=base, timeout=5)
    assert ok is True


def test_run_control_is_not_vacuously_green_when_the_bad_candidate_is_actually_good(
    base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A committed negative control on the control itself (CLAUDE.md's
    Negative Control directive): `--control` must NOT report success purely
    because it always returns True regardless of what it seeds. Point the
    "known-bad" candidate at the actually-good reference solution and confirm
    the overall verdict flips to False - proving the grading-control check is
    load-bearing, not decorative."""
    monkeypatch.setattr(demo, "BAD_CANDIDATE", demo.GOOD_CANDIDATE)
    ok = demo.run_control(image="fake-image:1", docker_bin=_docker_bin(docker_state), base=base, timeout=5)
    assert ok is False


def test_run_control_is_not_vacuously_green_when_the_orphan_is_reachable_by_confirm_absent(
    base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second committed negative control on the control: break the
    left-running seed itself (call `destroy()` on the orphan immediately, as
    a real teardown would) and confirm the overall verdict flips to False -
    proving the reap-catches-an-orphan check is load-bearing too, not a
    check that would pass no matter what `reap()` reports."""
    from skillc import docker_backend as dbe

    real_prepare = dbe.DockerBackend.prepare

    def _prepare_and_immediately_destroy(self: dbe.DockerBackend, attempt_id: str) -> object:
        handle = real_prepare(self, attempt_id)
        self.destroy(handle)
        return handle

    monkeypatch.setattr(dbe.DockerBackend, "prepare", _prepare_and_immediately_destroy)
    ok = demo.run_control(image="fake-image:1", docker_bin=_docker_bin(docker_state), base=base, timeout=5)
    assert ok is False


# --------------------------------------------------------------- leak-check


def test_leak_check_text_is_clean_on_an_ordinary_block() -> None:
    assert demo.leak_check_text("skillc operator demo\nacceptance: all met\n") == []


def test_leak_check_text_catches_a_seeded_home_path() -> None:
    findings = demo.leak_check_text(_seeded_leak_text())
    assert findings
    assert any("home-path" in f for f in findings)


def test_print_paste_back_refuses_a_leaky_block_and_prints_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(demo.PasteBackRefused):
        demo.print_paste_back(_seeded_leak_text())
    assert capsys.readouterr().out == ""


def test_print_paste_back_prints_a_clean_block(capsys: pytest.CaptureFixture[str]) -> None:
    demo.print_paste_back("all clear\n")
    assert capsys.readouterr().out == "all clear\n\n"


# ---------------------------------------------------------- resolve_image_digest


def test_resolve_image_digest_differs_by_image(docker_state: Path) -> None:
    a = demo.resolve_image_digest(_docker_bin(docker_state), "image-a:1", None, DAEMON_TIMEOUT)
    b = demo.resolve_image_digest(_docker_bin(docker_state), "image-b:1", None, DAEMON_TIMEOUT)
    assert a is not None
    assert b is not None
    assert a != b


def test_resolve_image_digest_is_none_when_the_daemon_is_unreachable(docker_state: Path) -> None:
    docker_state.mkdir(parents=True, exist_ok=True)
    (docker_state / ".down").touch()
    digest = demo.resolve_image_digest(_docker_bin(docker_state), "image-a:1", None, DAEMON_TIMEOUT)
    assert digest is None


# --------------------------------------------------------------- build_paste_back


def test_build_paste_back_renders_all_four_reap_outcomes_distinctly() -> None:
    """`REAP_OUTCOMES` names four distinct values - this proves the paste-back
    text actually distinguishes them rather than collapsing any pair into the
    same rendered line."""
    report = reap.ReapReport(
        daemon_reachable=True,
        outcomes=(
            reap.ReapOutcome("a1", "reaped"),
            reap.ReapOutcome("a2", "already-absent"),
            reap.ReapOutcome("a3", "left-running"),
            reap.ReapOutcome("a4", "unknown"),
        ),
    )
    text = demo.build_paste_back([], "fake-image:1", "sha256:deadbeef", report)
    assert "a1: reaped" in text
    assert "a2: already-absent" in text
    assert "a3: left-running" in text
    assert "a4: unknown" in text


def test_build_paste_back_reports_unknown_digest_explicitly() -> None:
    report = reap.ReapReport(daemon_reachable=False, outcomes=())
    text = demo.build_paste_back([], "fake-image:1", None, report)
    assert "image_digest=UNKNOWN" in text


# --------------------------------------------------------------- acceptance items


def _ok_lifecycle_record() -> dict[str, object]:
    return {"disposition": "captured"}


def _ok_graded() -> Graded:
    return Graded(status="PASS", category="", detail="", criteria=[], containment={})


def _ok_reap_report() -> reap.ReapReport:
    return reap.ReapReport(daemon_reachable=True, outcomes=(reap.ReapOutcome("a1", "reaped"),))


def _ok_host_diff() -> reap.HostPathDiff:
    return reap.HostPathDiff(changed=(), unresolved=())


def test_acceptance_items_flags_unchanged_host_paths_as_not_met() -> None:
    lifecycle_record = _ok_lifecycle_record()
    graded_ok = _ok_graded()
    reap_report = _ok_reap_report()

    clean_diff = _ok_host_diff()
    items_clean = demo._acceptance_items(lifecycle_record, graded_ok, reap_report, clean_diff, "sha256:x")
    assert all(item.met for item in items_clean)

    dirty_diff = reap.HostPathDiff(changed=("pyproject.toml",), unresolved=())
    items_dirty = demo._acceptance_items(lifecycle_record, graded_ok, reap_report, dirty_diff, "sha256:x")
    host_item = next(i for i in items_dirty if i.name == "declared host paths unchanged")
    assert host_item.met is False


def test_acceptance_items_flags_unresolved_host_paths_as_not_met() -> None:
    """The other half of `host_ok` (`reap.HostPathDiff.unresolved`, e.g. a
    path that could not be read for comparison) - a path this demo could not
    even check is not evidence the path is unchanged, and this half was
    unguarded by any test until now (cross-model review, PR #97): mutating
    `host_ok` to drop the `unresolved` clause left every existing demo test
    green. Confirmed red on that exact mutation before adding this test."""
    unresolved_diff = reap.HostPathDiff(changed=(), unresolved=("README.md",))
    items = demo._acceptance_items(
        _ok_lifecycle_record(), _ok_graded(), _ok_reap_report(), unresolved_diff, "sha256:x",
    )
    host_item = next(i for i in items if i.name == "declared host paths unchanged")
    assert host_item.met is False


def test_acceptance_items_flags_an_unknown_reap_outcome_as_not_met() -> None:
    """`reap_ok`'s `not reap_report.unknown` clause - unguarded until now
    (cross-model review, PR #97): dropping that clause left every existing
    demo test green, because none of them ever produced an `unknown` reap
    outcome. Confirmed red on that exact mutation before adding this test."""
    unknown_report = reap.ReapReport(daemon_reachable=True, outcomes=(reap.ReapOutcome("a1", "unknown"),))
    items = demo._acceptance_items(
        _ok_lifecycle_record(), _ok_graded(), unknown_report, _ok_host_diff(), "sha256:x",
    )
    cleanup_item = next(i for i in items if i.name == "cleanup sweep confirms no owned container left running")
    assert cleanup_item.met is False


def test_acceptance_items_flags_a_missing_image_digest_as_not_met() -> None:
    """`digest_ok = image_digest is not None` - unguarded until now
    (cross-model review, PR #97): replacing it with `True` left every existing
    demo test green, because none of them ever passed a `None` digest to
    `_acceptance_items` directly. Confirmed red on that exact mutation before
    adding this test. The paste-back's own `image_digest=UNKNOWN` rendering
    for a `None` digest is already covered separately by
    `test_build_paste_back_reports_unknown_digest_explicitly`."""
    items = demo._acceptance_items(
        _ok_lifecycle_record(), _ok_graded(), _ok_reap_report(), _ok_host_diff(), None,
    )
    digest_item = next(i for i in items if i.name == "image digest recorded")
    assert digest_item.met is False
