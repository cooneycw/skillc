"""Tests for the operator demo command (#81, sub-issue of #10).

Every test here runs against the fake `docker` CLI
(`tests/fixtures/docker-backend/fake_docker.py`), exactly like
`tests/test_docker_backend.py` - no real daemon is available in this session,
and `skillc/demo.py`'s own module docstring says so plainly: #10 closes only
on the operator's own live run of this command against a real daemon, never
on these tests passing.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

from skillc import demo, materialize, reap
from skillc.docker_backend import DAEMON_TIMEOUT

FAKE_DOCKER = Path(__file__).resolve().parent / "fixtures" / "docker-backend" / "fake_docker.py"
#: `materialize.py`'s own fixture (`skills_root: "skills"`) - reused rather
#: than building a fresh one for this module alone.
CODEX_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "codex-subject"
SUBJECT_SNAPSHOT = CODEX_FIXTURE / "collection"


def _fake_codex_client(tmp_path: Path) -> list[str]:
    """`materialize.py`'s own fake codex client (#7) - a real, ambient
    `codex` on PATH must never be invoked by this file's tests. Found by
    this PR's own review: `run_demo`'s materialize demo defaults to
    `materialize.find_client(None)`, which searches PATH for a REAL codex -
    present in this sandbox, so the first version of these tests silently
    ran a live client, non-deterministic and certain to behave differently
    wherever `codex` is absent (CI's own `needs_codex` skip convention in
    tests/test_materialize.py exists for exactly this reason)."""
    script = tmp_path / "client" / "fake_codex.py"
    script.parent.mkdir(exist_ok=True)
    shutil.copy(CODEX_FIXTURE / "fake_codex.py", script)
    script.with_suffix(".mode").write_text(json.dumps({"mode": "normal"}), encoding="utf-8")
    return [sys.executable, str(script)]


def _fake_subject() -> materialize.Subject:
    """A `--subject` stand-in that needs no network and no git history -
    `run_demo`'s own tests must never depend on either. `load_demo_subject`
    is monkeypatched to return this instead of reading a real
    `evals/subjects/<name>/subject.json`."""
    return materialize.Subject.from_dict({
        "subject_schema": 1, "locator": "test", "revision": "v1", "surface": "codex-skills",
        "skills_root": "skills", "select": "all", "client": {"name": "codex", "version": "9.9.9"},
    })


@pytest.fixture(autouse=True)
def _no_network_subject(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Every test in this file gets a subject that resolves from a local
    fixture, never a real `evals/subjects/` entry or a git clone, AND a fake
    codex client, never a real ambient one - `demo.py` itself is tested here
    only against the fake docker CLI, and the materialize demo it now also
    runs must be equally offline and deterministic."""
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _fake_subject())
    monkeypatch.setattr(materialize, "find_client", lambda _explicit: _fake_codex_client(tmp_path))


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
    result = demo.run_demo(image="fake-image:1", docker_bin=_docker_bin(docker_state), base=base, timeout=5, subject_source=SUBJECT_SNAPSHOT)
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
    result_a = demo.run_demo(image="fake-image:1", docker_bin=_docker_bin(docker_state), base=base, timeout=5, subject_source=SUBJECT_SNAPSHOT)
    result_b = demo.run_demo(image="fake-image:2", docker_bin=_docker_bin(docker_state), base=base, timeout=5, subject_source=SUBJECT_SNAPSHOT)
    assert result_a.image_digest != result_b.image_digest


def test_run_demo_paste_back_is_leak_clean(base: Path, docker_state: Path) -> None:
    """The happy path's own paste-back block must pass its own leak-check -
    printing it via `print_paste_back` must not raise."""
    result = demo.run_demo(image="fake-image:1", docker_bin=_docker_bin(docker_state), base=base, timeout=5, subject_source=SUBJECT_SNAPSHOT)
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


def test_acceptance_items_flags_unchanged_host_paths_as_not_met() -> None:
    from skillc.verify import Graded

    lifecycle_record: dict[str, object] = {"disposition": "captured"}
    graded_ok = Graded(status="PASS", category="", detail="", criteria=[], containment={})
    reap_report = reap.ReapReport(daemon_reachable=True, outcomes=(reap.ReapOutcome("a1", "reaped"),))

    clean_diff = reap.HostPathDiff(changed=(), unresolved=())
    items_clean = demo._acceptance_items(lifecycle_record, graded_ok, reap_report, clean_diff, "sha256:x", None)
    assert all(item.met for item in items_clean)

    dirty_diff = reap.HostPathDiff(changed=("pyproject.toml",), unresolved=())
    items_dirty = demo._acceptance_items(lifecycle_record, graded_ok, reap_report, dirty_diff, "sha256:x", None)
    host_item = next(i for i in items_dirty if i.name == "declared host paths unchanged")
    assert host_item.met is False
