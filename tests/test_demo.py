"""Tests for the operator demo command (#81, sub-issue of #10).

Every test here runs against the fake `docker` CLI
(`tests/fixtures/docker-backend/fake_docker.py`), exactly like
`tests/test_docker_backend.py` - no real daemon is available in this session,
and `skillc/demo.py`'s own module docstring says so plainly: #10 closes only
on the operator's own live run of this command against a real daemon, never
on these tests passing.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from skillc import demo, materialize, reap
from skillc.docker_backend import DAEMON_TIMEOUT
from skillc.verify import Graded

FAKE_DOCKER = Path(__file__).resolve().parent / "fixtures" / "docker-backend" / "fake_docker.py"
#: `materialize.py`'s own fake codex client (#7) - reused here for the
#: in-container discovery listing, never a real ambient `codex` on PATH.
CODEX_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "codex-subject"
#: Issue #122's red-case child: skillc's CLI with the interrupt sweep unscoped.
UNSCOPED_INTERRUPT_CHILD = Path(__file__).resolve().parent / "fixtures" / "demo-control" / "unscoped_interrupt_child.py"
#: Issue #122's red-case child whose exec never marks itself live.
NEVER_LIVE_CHILD = Path(__file__).resolve().parent / "fixtures" / "demo-control" / "never_live_child.py"


def _docker_bin(state_dir: Path) -> list[str]:
    return [sys.executable, str(FAKE_DOCKER), "--state", str(state_dir)]


def _run_owned_container(state_dir: Path, name: str, attempt_id: str) -> None:
    """A container the fake docker CLI reports as skillc-owned, carrying
    `attempt_id`'s own label - the same shape `tests/test_reap.py`'s own
    `_run`/`_owned_labels` build, reused here for the interrupt-sweep
    best-effort-cleanup tests rather than duplicated as a second fixture."""
    from skillc.docker_backend import ATTEMPT_LABEL_KEY, OWNER_LABEL_KEY, OWNER_LABEL_VALUE

    argv = [*_docker_bin(state_dir), "run", "--rm", "-d", "--name", name]
    argv += ["--label", f"{OWNER_LABEL_KEY}={OWNER_LABEL_VALUE}", "--label", f"{ATTEMPT_LABEL_KEY}={attempt_id}"]
    argv += ["--", "fake-image:1", "sleep", "infinity"]
    result = subprocess.run(argv, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


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


def _run_control(base: Path, docker_state: Path, **overrides: object) -> demo.ControlResult:
    """`run_control` with issue #122's two new seeds shortened for the fake
    `docker` - the same seeds, a sub-second limit and a few-second sleep in
    place of the operator's 3s/30s and 60s."""
    kwargs: dict[str, object] = {
        "image": "fake-image:1", "docker_bin": _docker_bin(docker_state), "base": base, "timeout": 5,
        "timeout_limit": 0.5, "timeout_sleep": 5.0, "cancel_sleep": 4.0,
    }
    kwargs.update(overrides)
    return demo.run_control(**kwargs)  # type: ignore[arg-type]


def test_run_control_reports_every_seeded_failure_caught(base: Path, docker_state: Path) -> None:
    result = _run_control(base, docker_state)
    assert result.ok is True


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
    result = _run_control(base, docker_state)
    assert result.ok is False


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
    result = _run_control(base, docker_state)
    assert result.ok is False


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


# --------------------------------------------------------------- subject demo


def _fake_codex(tmp_path: Path, mode: str = "normal", **config: str) -> list[str]:
    """`materialize.py`'s own fake codex client (#7), copied fresh per test -
    reused here for the in-container discovery listing rather than building
    a second fixture."""
    script = tmp_path / "subject-client" / "fake_codex.py"
    script.parent.mkdir(exist_ok=True)
    shutil.copy(CODEX_FIXTURE / "fake_codex.py", script)
    script.with_suffix(".mode").write_text(json.dumps({"mode": mode, **config}), encoding="utf-8")
    return [sys.executable, str(script)]


def _skill_md(name: str) -> str:
    return f"---\nname: {name}\ndescription: A test skill.\n---\nBody text.\n"


def _subject_collection(tmp_path: Path, skills: dict[str, str]) -> Path:
    """A plain directory under `tmp_path` with one `SKILL.md` per entry in
    `skills` (name -> directory) - a snapshot, never a git repository.
    `run_subject_demo` acquires through `materialize.acquire_snapshot`
    (issue #101 cross-model review: the earlier version of this fixture built
    a real git repo via `git init`/`commit`/`rev-parse`, needing a real `git`
    binary that CI's own gate image does not have - Woodpecker pipeline 205
    failed exactly these tests with `FileNotFoundError: 'git'`, undetected
    locally where `git` is always present). The declared `revision` in a
    test subject is cosmetic in snapshot mode - `acquire_snapshot` never
    checks it - so no commit SHA is needed here at all."""
    collection = tmp_path / "subject-collection"
    skills_root = collection / "skills"
    for name, directory in skills.items():
        skill_dir = skills_root / directory
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(_skill_md(name), encoding="utf-8")
    return collection


def _subject(select: object = "all", revision: str = "v1") -> materialize.Subject:
    return materialize.Subject.from_dict({
        "subject_schema": 1, "locator": "test/test", "revision": revision, "surface": "codex-skills",
        "skills_root": "skills", "select": select, "client": {"name": "codex", "version": "9.9.9"},
    })


@pytest.fixture(autouse=True)
def _no_network_subject(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test in this file gets its subject from `load_demo_subject`
    monkeypatched by the individual test (via `checkout=`/direct subject
    construction) - this fixture only guards against the DEFAULT subject
    ever being read for real, since `demo.DEFAULT_SUBJECT` names a real
    `evals/subjects/` entry this file's tests must never touch."""
    monkeypatch.setattr(demo, "DEFAULT_SUBJECT", "unused-in-tests")


def test_subject_surface_files_flattens_every_selected_skill(tmp_path: Path) -> None:
    repo = _subject_collection(tmp_path, {"greet": "greet", "farewell": "farewell"})
    subject = _subject()
    staging = tmp_path / "staging"
    staging.mkdir()
    source = materialize.acquire_snapshot(subject, repo, staging)
    entries = materialize.inventory(subject, source)
    files = demo.subject_surface_files(source, entries)
    assert {f.skill for f in files} == {"greet", "farewell"}
    assert all(f.container_relpath.startswith(".codex/skills/") for f in files)


def test_run_subject_demo_refuses_an_unknown_selected_skill(
    tmp_path: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #101's own named red case for "Install": a subject whose
    `select` names a skill absent from the source is refused before any
    Docker work starts - `materialize.inventory`'s own check, translated to
    `SubjectRefused`."""
    repo = _subject_collection(tmp_path, {"greet": "greet"})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject(select=["greet", "does-not-exist"]))
    with pytest.raises(demo.SubjectRefused, match="does-not-exist"):
        demo.run_subject_demo(
            subject_name="whatever", image="fake-image:1", docker_bin=_docker_bin(docker_state),
            base=tmp_path / "work", timeout=5, checkout=repo,
        )


def test_run_subject_demo_happy_path_installs_matches_and_discovers(
    tmp_path: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch, base: Path,
) -> None:
    repo = _subject_collection(tmp_path, {"greet": "greet", "farewell": "farewell"})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject())
    client = _fake_codex(tmp_path, mode="normal")

    result = demo.run_subject_demo(
        subject_name="whatever", image="fake-image:1", docker_bin=_docker_bin(docker_state),
        base=base, timeout=5, checkout=repo, client_argv=client,
    )
    assert result.digest_status == "matched"
    assert result.digest_mismatches == []
    assert result.discovery == {"greet": "discovered", "farewell": "discovered"}
    assert result.discovery_reason is None
    assert set(result.receipt["skills"]) == {"greet", "farewell"}  # type: ignore[call-overload]
    assert result.reap_report.daemon_reachable is True


def test_run_subject_demo_digest_mismatch_names_the_tampered_file(
    tmp_path: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch, base: Path,
) -> None:
    """Issue #101's named red case for "Digest match": a byte of one
    installed file changed in-container after install gives `mismatched`
    naming that file."""
    repo = _subject_collection(tmp_path, {"greet": "greet"})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject())
    client = _fake_codex(tmp_path, mode="normal")

    real_install = demo.install_subject

    def _install_then_tamper(backend, handle, source, files):
        receipt = real_install(backend, handle, source, files)
        target = next(f for f in files if f.skill == "greet")
        backend.deliver_home_file(handle, target.container_relpath, b"tampered bytes")
        return receipt

    monkeypatch.setattr(demo, "install_subject", _install_then_tamper)
    result = demo.run_subject_demo(
        subject_name="whatever", image="fake-image:1", docker_bin=_docker_bin(docker_state),
        base=base, timeout=5, checkout=repo, client_argv=client,
    )
    assert result.digest_status == "mismatched"
    assert any("greet" in m for m in result.digest_mismatches)


def test_run_subject_demo_not_discovered_when_the_listing_omits_a_skill(
    tmp_path: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch, base: Path,
) -> None:
    """Issue #101's named red case for "Discovered": a listing that omits a
    selected skill reports that skill `not-discovered`."""
    repo = _subject_collection(tmp_path, {"greet": "greet"})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject())
    client = _fake_codex(tmp_path, mode="blind")  # lists only the client's own .system skill

    result = demo.run_subject_demo(
        subject_name="whatever", image="fake-image:1", docker_bin=_docker_bin(docker_state),
        base=base, timeout=5, checkout=repo, client_argv=client,
    )
    assert result.discovery == {"greet": "not-discovered"}
    assert result.discovery_reason is None


def test_run_subject_demo_unmeasured_when_the_listing_crashes(
    tmp_path: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch, base: Path,
) -> None:
    """Issue #101's named red case for "UNMEASURED": a listing that fails
    reports every selected skill UNMEASURED with a reason, never dropped."""
    repo = _subject_collection(tmp_path, {"greet": "greet", "farewell": "farewell"})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject())
    client = _fake_codex(tmp_path, mode="crash")

    result = demo.run_subject_demo(
        subject_name="whatever", image="fake-image:1", docker_bin=_docker_bin(docker_state),
        base=base, timeout=5, checkout=repo, client_argv=client,
    )
    assert result.discovery == {"greet": "UNMEASURED", "farewell": "UNMEASURED"}
    assert result.discovery_reason and "crashing on purpose" in result.discovery_reason


def test_run_demo_with_subject_name_adds_a_third_leg_and_can_fail_it(
    tmp_path: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch, base: Path,
) -> None:
    """`run_demo(subject_name=...)` wires the subject leg's acceptance items
    into the overall verdict - a broken subject leg must flip `ok` to False
    even though the lifecycle/grading legs are untouched and still pass."""
    repo = _subject_collection(tmp_path, {"greet": "greet"})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject())
    client = _fake_codex(tmp_path, mode="crash")

    result = demo.run_demo(
        image="fake-image:1", docker_bin=_docker_bin(docker_state), base=base, timeout=5,
        subject_name="whatever", subject_checkout=repo, subject_client=client,
    )
    assert result.ok is False
    assert result.lifecycle_record["disposition"] == "captured"
    assert result.graded.status == "PASS"
    assert "NOT MET" in result.paste_back
    assert "subject: whatever" in result.paste_back
    demo.print_paste_back(result.paste_back)  # still leak-clean; raises on failure


def test_run_demo_without_subject_name_is_unchanged(base: Path, docker_state: Path) -> None:
    """Omitting `subject_name` (the CLI's own default when `--subject` is
    never given) must behave exactly like #97 shipped it - no subject leg,
    no `subject:` line in the paste-back."""
    result = demo.run_demo(image="fake-image:1", docker_bin=_docker_bin(docker_state), base=base, timeout=5)
    assert result.subject_result is None
    assert "subject:" not in result.paste_back


def _ok_subject_result(**overrides: object) -> demo.SubjectResult:
    base_kwargs: dict[str, object] = {
        "subject_name": "whatever",
        "revision": "deadbeef" * 5,
        "receipt": {"skills": ["greet"], "skill_count": 1, "file_count": 1, "files": []},
        "digest_status": "matched",
        "digest_mismatches": [],
        "discovery": {"greet": "discovered"},
        "discovery_reason": None,
        "host_diff": reap.HostPathDiff(changed=(), unresolved=()),
        "reap_report": reap.ReapReport(daemon_reachable=True, outcomes=(reap.ReapOutcome("a1", "reaped"),)),
    }
    base_kwargs.update(overrides)
    return demo.SubjectResult(**base_kwargs)  # type: ignore[arg-type]


def test_subject_acceptance_items_all_met_on_a_clean_result() -> None:
    items = demo._subject_acceptance_items(_ok_subject_result())
    assert all(item.met for item in items)


def test_subject_acceptance_items_flags_a_digest_mismatch_as_not_met() -> None:
    """Direct, mutation-provable counterpart to
    `test_run_subject_demo_digest_mismatch_names_the_tampered_file` -
    confirms `_subject_acceptance_items` itself, not just `SubjectResult`,
    marks a digest mismatch NOT MET."""
    result = _ok_subject_result(digest_status="mismatched", digest_mismatches=[".codex/skills/greet/SKILL.md"])
    items = demo._subject_acceptance_items(result)
    digest_item = next(i for i in items if "digests match" in i.name)
    assert digest_item.met is False


def test_subject_acceptance_items_flags_not_discovered_as_not_met() -> None:
    result = _ok_subject_result(discovery={"greet": "not-discovered"})
    items = demo._subject_acceptance_items(result)
    discovery_item = next(i for i in items if "discovered by the client" in i.name)
    assert discovery_item.met is False


def test_subject_acceptance_items_flags_unmeasured_as_not_met() -> None:
    result = _ok_subject_result(discovery={"greet": "UNMEASURED"}, discovery_reason="the listing crashed")
    items = demo._subject_acceptance_items(result)
    discovery_item = next(i for i in items if "discovered by the client" in i.name)
    assert discovery_item.met is False


def test_subject_acceptance_items_flags_a_reason_alongside_discovered_as_not_met() -> None:
    """`discovery_ok`'s `result.discovery_reason is None` clause is
    redundant given `run_subject_discovery`'s own invariant (a reason is
    set if and only if every entry reads `UNMEASURED`, never alongside
    `discovered`) - so a mutation dropping that clause is invisible to
    `test_subject_acceptance_items_flags_unmeasured_as_not_met` above,
    which only ever exercises the all-`UNMEASURED` shape. `SubjectResult`
    is a plain dataclass with no constructor that enforces that invariant,
    so this directly constructs the combination `run_subject_demo` itself
    never produces and confirms `_subject_acceptance_items` still refuses
    it - defense in depth against a future caller that builds one by hand.
    Confirmed red (all tests green) when `discovery_ok` dropped this clause
    before this test was added."""
    result = _ok_subject_result(discovery={"greet": "discovered"}, discovery_reason="should never coexist")
    items = demo._subject_acceptance_items(result)
    discovery_item = next(i for i in items if "discovered by the client" in i.name)
    assert discovery_item.met is False


def test_subject_acceptance_items_flags_an_install_mismatch_as_not_met() -> None:
    """Red case for "installed skills match its declared selection": a
    receipt naming a different skill set than what discovery observed (e.g.
    a skill that was never actually installed) must not read as met."""
    result = _ok_subject_result(receipt={"skills": ["greet", "phantom"], "skill_count": 2, "file_count": 1, "files": []})
    items = demo._subject_acceptance_items(result)
    install_item = next(i for i in items if "declared selection" in i.name)
    assert install_item.met is False


def test_subject_acceptance_items_flags_changed_host_paths_as_not_met() -> None:
    dirty = _ok_subject_result(host_diff=reap.HostPathDiff(changed=("pyproject.toml",), unresolved=()))
    host_item = next(i for i in demo._subject_acceptance_items(dirty) if "host paths unchanged" in i.name)
    assert host_item.met is False


def test_subject_acceptance_items_flags_unresolved_host_paths_as_not_met() -> None:
    """The other half of `host_ok` - unguarded by the combined test this
    replaced (cross-model review of #97's own identical gap, reproduced
    here): mutating `host_ok` to drop the `unresolved` clause left that
    combined test green, because it only ever exercised `changed`."""
    unresolved = _ok_subject_result(host_diff=reap.HostPathDiff(changed=(), unresolved=("README.md",)))
    host_item = next(i for i in demo._subject_acceptance_items(unresolved) if "host paths unchanged" in i.name)
    assert host_item.met is False


def test_subject_acceptance_items_flags_left_running_as_not_met() -> None:
    left_running = _ok_subject_result(
        reap_report=reap.ReapReport(daemon_reachable=True, outcomes=(reap.ReapOutcome("a1", "left-running"),))
    )
    reap_item = next(i for i in demo._subject_acceptance_items(left_running) if "no owned container left running" in i.name)
    assert reap_item.met is False


def test_subject_acceptance_items_flags_unknown_reap_outcome_as_not_met() -> None:
    unknown = _ok_subject_result(
        reap_report=reap.ReapReport(daemon_reachable=True, outcomes=(reap.ReapOutcome("a1", "unknown"),))
    )
    reap_item = next(i for i in demo._subject_acceptance_items(unknown) if "no owned container left running" in i.name)
    assert reap_item.met is False


def test_build_paste_back_leak_check_still_applies_to_the_subject_block() -> None:
    """Issue #101's own checklist item: the paste-back leak-check (#97's
    existing control) must still cover the per-subject block, not just the
    core acceptance lines - it does, because `build_paste_back` appends the
    subject block to the SAME string `print_paste_back` scans whole. The
    planted value goes in `digest_mismatches`, which `build_subject_paste_back`
    actually renders (unlike `receipt`, which this block only ever summarizes
    as counts, never as file paths)."""
    seeded_identity = "/home/" + "exampleuser" + "/leaked"
    result = _ok_subject_result(digest_status="mismatched", digest_mismatches=[seeded_identity])
    text = demo.build_paste_back([], "fake-image:1", "sha256:deadbeef", reap.ReapReport(True, ()), result)
    assert seeded_identity in text
    with pytest.raises(demo.PasteBackRefused):
        demo.print_paste_back(text)


# ===================================================================
# Issue #118: the operator's own live run found four defects, each
# independent of the docker build failure that exposed them.
# ===================================================================


# --------------- item 1: no unhandled backend/acquisition failure ever
# --------------- reaches the terminal, and nothing unscanned does either


def test_run_subject_demo_reports_backend_unavailable_gracefully_never_raises(
    base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Red case (issue #118, the most serious): an earlier version let
    `BackendUnavailable` from `prepare()` propagate uncaught, and the
    traceback printed the operator's own home directory and username.
    `.down` (the fake docker CLI's own daemon-unreachable sentinel) makes
    `prepare()` raise exactly that - `run_subject_demo` must return a
    NOT-EXERCISED result instead, never raise."""
    docker_state.mkdir(parents=True, exist_ok=True)
    (docker_state / ".down").touch()
    collection = _subject_collection(base, {"greet": "greet"})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject())

    result = demo.run_subject_demo(
        subject_name="whatever", image="fake-image:1", docker_bin=_docker_bin(docker_state),
        base=base / "work", timeout=5, checkout=collection,
    )
    assert result.not_exercised_reason is not None
    assert "backend unavailable" in result.not_exercised_reason
    items = demo._subject_acceptance_items(result)
    assert all(not item.exercised and not item.met for item in items)


def test_run_subject_demo_reports_a_genuine_acquisition_failure_gracefully_never_raises(
    base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Red case (issue #118, cross-model review): deleting the
    `try/except SubjectRefused` around `acquire_subject_checkout(...)` left
    every OTHER test in this file green, because none of them ever make
    real acquisition raise - every other test either passes an explicit
    `checkout=` (bypassing acquisition entirely) or monkeypatches
    `acquire_subject_checkout` itself away. This test does neither: it lets
    `acquire_subject_checkout` run for real, and makes the `git clone`
    SUBPROCESS CALL underneath it fail (never the function itself mocked
    away), so `SubjectRefused` is raised by the function's own real
    exception-wrapping code, exactly as a real network failure would."""
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject())
    real_run = subprocess.run

    def _failing_clone(
        argv: list[str], *, check: bool = False, timeout: float | None = None, capture_output: bool = False,
    ) -> subprocess.CompletedProcess[bytes]:
        if len(argv) >= 2 and argv[0] == "git" and argv[1] == "clone":
            raise subprocess.CalledProcessError(128, argv, output=b"", stderr=b"fatal: could not resolve host")
        return real_run(argv, check=check, timeout=timeout, capture_output=capture_output)

    monkeypatch.setattr(demo.subprocess, "run", _failing_clone)

    result = demo.run_subject_demo(
        subject_name="whatever", image="fake-image:1", docker_bin=_docker_bin(docker_state),
        base=base, timeout=5,
    )
    assert result.not_exercised_reason is not None
    assert "acquisition failed" in result.not_exercised_reason
    items = demo._subject_acceptance_items(result)
    assert all(not item.exercised and not item.met for item in items)


def test_run_control_orphan_prepare_failure_is_not_caught_never_raises(
    base: Path, docker_state: Path,
) -> None:
    """Red case (issue #118): the SAME `BackendUnavailable`-from-`prepare()`
    shape, in `run_control`'s own seeded orphan step - it must read as a
    seeded failure that was NOT caught (the control cannot certify a
    mechanism it could not even seed), never raise a traceback."""
    docker_state.mkdir(parents=True, exist_ok=True)
    (docker_state / ".down").touch()
    result = _run_control(base, docker_state)
    assert result.ok is False


def test_describe_error_safely_scrubs_a_leaky_message() -> None:
    seeded_identity = "/home/" + "exampleuser" + "/leaked"
    exc = RuntimeError(f"could not clone https://example.com: {seeded_identity}")
    described = demo.describe_error_safely(exc)
    assert seeded_identity not in described
    assert "RuntimeError" in described


def test_describe_error_safely_keeps_a_clean_message() -> None:
    exc = RuntimeError("no subject declaration at evals/subjects/whatever/subject.json")
    described = demo.describe_error_safely(exc)
    assert "no subject declaration" in described


def test_redact_known_host_paths_scrubs_a_non_home_checkout_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Red case (issue #118, cross-model review): `leak_check_text`'s own
    `HOME_PATH_RE` only matches `/home/<user>/...` - a checkout under `/opt`,
    `/srv`, or (as here) an arbitrary `tmp_path` sailed through it completely
    unscrubbed. Reproduced live: an unreadable `subject.json` under a
    non-`/home` checkout printed its own absolute path, twice, via
    `SubjectRefused`'s message. `redact_known_host_paths` must replace a
    KNOWN host path (this checkout's own `REPO_ROOT`, monkeypatched to a
    non-`/home` `tmp_path` here) with `<repo>` even though it never matches
    the leak-check's own pattern at all. Confirmed red (the raw path comes
    through untouched) with the substitution removed."""
    fake_repo_root = tmp_path / "opt" / "skillc-install"
    fake_repo_root.mkdir(parents=True)
    monkeypatch.setattr(demo, "REPO_ROOT", fake_repo_root)

    message = f"could not read {fake_repo_root}/evals/subjects/whatever/subject.json: Permission denied"
    redacted = demo.redact_known_host_paths(message)
    assert str(fake_repo_root) not in redacted
    assert "<repo>/evals/subjects/whatever/subject.json" in redacted


def test_describe_error_safely_scrubs_a_non_home_path_via_redaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same red case, through the actual CLI-facing entry point: even
    though this message NEVER matches `leak_check_text` at all (no `/home/`
    anywhere in it), `describe_error_safely` must still not print the raw
    path - `redact_known_host_paths` runs first, unconditionally, not only
    as a fallback once the leak-check already found something."""
    fake_repo_root = tmp_path / "opt" / "skillc-install"
    fake_repo_root.mkdir(parents=True)
    monkeypatch.setattr(demo, "REPO_ROOT", fake_repo_root)
    assert demo.leak_check_text(str(fake_repo_root)) == [], "test setup: this path must not itself trip the leak-check"

    exc = RuntimeError(f"unreadable: {fake_repo_root}/evals/subjects/whatever/subject.json")
    described = demo.describe_error_safely(exc)
    assert str(fake_repo_root) not in described
    assert "<repo>" in described


def test_redact_known_host_paths_prefers_base_over_a_containing_tmp_prefix(tmp_path: Path) -> None:
    """Longest-first matters: `base` is typically nested UNDER the system
    temp directory (`run_demo`'s own default `--base`) - replacing `<tmp>`
    first would leave `<tmp>/<base's-own-subdirectory-name>` instead of the
    more specific, more useful `<base>`."""
    base = tmp_path / "skillc-run-12345"
    base.mkdir()
    message = f"failed: {base}/subject-checkout"
    redacted = demo.redact_known_host_paths(message, base=base)
    assert redacted == "failed: <base>/subject-checkout"


def test_cmd_demo_scrubs_an_unexpected_exception_never_prints_a_raw_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """Red case (issue #118): the top-level CLI guard, exercised directly.
    Remove the guard (revert `cmd_demo` to a bare call with no
    `except Exception`) and this test fails with the planted home path
    printed to stderr, or an uncaught exception escaping the test itself."""
    from skillc import cli

    seeded_identity = "/home/" + "exampleuser" + "/leaked"

    def _boom(**kwargs: object) -> None:
        raise RuntimeError(f"acquisition failed: could not clone https://x: {seeded_identity}")

    monkeypatch.setattr(demo, "run_demo", _boom)
    parser = cli.build_parser()
    args = parser.parse_args(["demo"])

    exit_code = cli.cmd_demo(args)
    captured = capsys.readouterr()
    assert exit_code == 1
    assert seeded_identity not in captured.out
    assert seeded_identity not in captured.err
    assert "RuntimeError" in captured.err


def test_cmd_demo_paste_back_refusal_never_prints_the_finding_text(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """Red case (issue #118 review): `PasteBackRefused`'s own message is
    built from `leak.scan_text`'s findings, which NAME the leaked value
    found - printing `str(exc)` for this specific exception would be the
    exact leak `print_paste_back` exists to prevent, one level up."""
    from skillc import cli

    seeded_identity = "/home/" + "exampleuser" + "/leaked"

    class _FakeResult:
        paste_back = f"planted: {seeded_identity}\n"
        ok = True

    monkeypatch.setattr(demo, "run_demo", lambda **kwargs: _FakeResult())
    parser = cli.build_parser()
    args = parser.parse_args(["demo"])

    exit_code = cli.cmd_demo(args)
    captured = capsys.readouterr()
    assert exit_code == 2
    assert seeded_identity not in captured.out
    assert seeded_identity not in captured.err


# --------------- item 2: no fixed scratch path


def test_run_subject_demo_does_not_reuse_a_fixed_scratch_path(
    base: Path, docker_state: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Red case (issue #118): `--subject` used to clone into a FIXED
    `base / "subject-checkout"` path - a second run against the same `base`
    (the operator's own scenario: the first crashed before cleanup) then
    collided with the first's leftover directory. Two consecutive calls
    with the SAME `base`, forcing the real auto-acquire branch (no explicit
    `checkout=`), must both succeed - proving each gets its own fresh
    `tempfile.mkdtemp`, never a name the other could already hold. True
    concurrent safety follows from the same guarantee (`tempfile.mkdtemp`'s
    own `O_EXCL`-based atomicity, a stdlib property this test does not need
    to re-prove)."""
    collection = _subject_collection(tmp_path, {"greet": "greet"})

    def _fake_acquire(subject: materialize.Subject, into: Path, timeout: float = 300) -> Path:
        shutil.copytree(collection, into, dirs_exist_ok=True)
        return into

    monkeypatch.setattr(demo, "acquire_subject_checkout", _fake_acquire)
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject())
    client = _fake_codex(tmp_path, mode="normal")

    for _ in range(2):
        result = demo.run_subject_demo(
            subject_name="whatever", image="fake-image:1", docker_bin=_docker_bin(docker_state),
            base=base, timeout=5, client_argv=client,
        )
        assert result.not_exercised_reason is None
        assert result.digest_status == "matched"


def test_run_subject_demo_survives_a_crash_before_cleanup_on_the_prior_run(
    base: Path, docker_state: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The operator's own exact sequence: a PRIOR run crashed hard enough
    that its own `finally` cleanup never ran at all (a killed process, not
    a caught exception - this function's own `finally` block is a courtesy
    for the exceptions IT catches, and cannot help against that), leaving a
    non-empty directory sitting at the OLD fixed scratch path,
    `base / "subject-checkout"`. A run against the SAME `base` afterward
    must never be handed that dirty directory to acquire into - it needs a
    directory of its own, planted content or not. Isolates the
    fixed-path defect specifically from this function's OWN cleanup (a
    different, complementary fix): mutate `owned_checkout` back to the
    fixed path with this test unchanged and the planted assertion inside
    `_acquire` below fails, because the leftover directory this test
    creates BEFORE calling `run_subject_demo` at all is exactly what gets
    handed to it."""
    leftover = base / "subject-checkout"
    leftover.mkdir(parents=True)
    (leftover / "partial-garbage-from-a-killed-process").write_text("never cleaned up")

    collection = _subject_collection(tmp_path, {"greet": "greet"})

    def _acquire(subject: materialize.Subject, into: Path, timeout: float = 300) -> Path:
        assert not any(into.iterdir()), f"{into} was not empty - handed a directory an earlier run had already touched"
        shutil.copytree(collection, into, dirs_exist_ok=True)
        return into

    monkeypatch.setattr(demo, "acquire_subject_checkout", _acquire)
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject())
    client = _fake_codex(tmp_path, mode="normal")

    result = demo.run_subject_demo(
        subject_name="whatever", image="fake-image:1", docker_bin=_docker_bin(docker_state),
        base=base, timeout=5, client_argv=client,
    )
    assert result.not_exercised_reason is None
    # The leftover from the "prior crash" is untouched - this run never
    # wrote into, or cleaned up, a directory that was never its own.
    assert (leftover / "partial-garbage-from-a-killed-process").read_text() == "never cleaned up"


def test_run_subject_demo_cleans_up_its_temp_dirs(
    base: Path, docker_state: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The checkout and staging directories this function creates for
    itself must not persist after it returns - neither on success nor on
    the not-exercised path - or a long-running operator session would leak
    a fresh directory per `--subject` invocation forever."""
    collection = _subject_collection(tmp_path, {"greet": "greet"})
    created: list[Path] = []
    real_mkdtemp = tempfile.mkdtemp

    def _tracking_mkdtemp(suffix: str | None = None, prefix: str | None = None, dir: str | None = None) -> str:
        path = real_mkdtemp(suffix, prefix, dir)
        created.append(Path(path))
        return path

    def _fake_acquire(subject: materialize.Subject, into: Path, timeout: float = 300) -> Path:
        shutil.copytree(collection, into, dirs_exist_ok=True)
        return into

    monkeypatch.setattr(demo.tempfile, "mkdtemp", _tracking_mkdtemp)
    monkeypatch.setattr(demo, "acquire_subject_checkout", _fake_acquire)
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject())
    client = _fake_codex(tmp_path, mode="normal")

    demo.run_subject_demo(
        subject_name="whatever", image="fake-image:1", docker_bin=_docker_bin(docker_state),
        base=base, timeout=5, client_argv=client,
    )
    assert created, "the tracked tempfile.mkdtemp was never called"
    assert all(not p.exists() for p in created)


# --------------- item 3: the exit-code contract


def _demo_args(**overrides: object) -> argparse.Namespace:
    from skillc import cli

    parser = cli.build_parser()
    args = parser.parse_args(["demo"])
    for key, value in overrides.items():
        setattr(args, key, value)
    return args


def test_cmd_demo_exits_0_on_full_success(
    base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from skillc import cli

    monkeypatch.setattr(demo, "DEFAULT_SUBJECT", "unused-in-tests")
    args = _demo_args(image="fake-image:1", docker_bin=" ".join(_docker_bin(docker_state)), base=str(base))
    assert cli.cmd_demo(args) == 0


def test_cmd_demo_exits_1_when_an_item_is_not_met(
    base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from skillc import cli

    monkeypatch.setattr(demo, "GOOD_CANDIDATE", demo.BAD_CANDIDATE)
    args = _demo_args(image="fake-image:1", docker_bin=" ".join(_docker_bin(docker_state)), base=str(base))
    assert cli.cmd_demo(args) == 1


def test_cmd_demo_exits_1_on_subject_refused_never_2(
    base: Path, docker_state: Path,
) -> None:
    """Red case (issue #118's own exit-code fix): a refused subject used to
    exit `2`, which the runbook reserves exclusively for a leak-check
    refusal. `--subject does-not-exist` is a "could not run" failure -
    exit `1`."""
    from skillc import cli

    args = _demo_args(
        image="fake-image:1", docker_bin=" ".join(_docker_bin(docker_state)), base=str(base),
        subject="does-not-exist-at-all",
    )
    assert cli.cmd_demo(args) == 1


def test_cmd_demo_exits_2_only_on_leak_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from skillc import cli

    class _LeakyResult:
        paste_back = "planted: " + "/home/" + "exampleuser" + "/leaked\n"
        ok = True

    monkeypatch.setattr(demo, "run_demo", lambda **kwargs: _LeakyResult())
    args = _demo_args()
    assert cli.cmd_demo(args) == 2


def test_cmd_demo_control_exits_0_when_every_seeded_failure_caught(
    base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from skillc import cli

    monkeypatch.setattr(demo, "run_control", lambda **kwargs: demo.ControlResult(True, "control block\n", ()))
    args = _demo_args(image="fake-image:1", docker_bin=" ".join(_docker_bin(docker_state)), base=str(base), control=True)
    assert cli.cmd_demo(args) == 0


def test_cmd_demo_control_exits_1_when_a_seeded_failure_is_not_caught(
    base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from skillc import cli

    monkeypatch.setattr(demo, "run_control", lambda **kwargs: demo.ControlResult(False, "control block\n", ()))
    args = _demo_args(image="fake-image:1", docker_bin=" ".join(_docker_bin(docker_state)), base=str(base), control=True)
    assert cli.cmd_demo(args) == 1


def test_cmd_demo_control_prints_its_block_through_the_leak_check(
    base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """Issue #122: `--control` prints its per-seed block, and prints it
    through `print_paste_back` - a leaky block is refused (exit 2, nothing
    printed), exactly like the normal demo's."""
    from skillc import cli

    args = _demo_args(image="fake-image:1", docker_bin=" ".join(_docker_bin(docker_state)), base=str(base), control=True)
    monkeypatch.setattr(demo, "run_control", lambda **kwargs: demo.ControlResult(True, "control block\n", ()))
    assert cli.cmd_demo(args) == 0
    assert "control block" in capsys.readouterr().out

    monkeypatch.setattr(demo, "run_control", lambda **kwargs: demo.ControlResult(True, _seeded_leak_text(), ()))
    assert cli.cmd_demo(args) == 2
    captured = capsys.readouterr()
    assert "exampleuser" not in captured.out and "exampleuser" not in captured.err


# ------------------------ issue #122: the timeout and cancellation seeds


def test_run_control_reports_all_six_seeds_in_a_leak_clean_block(base: Path, docker_state: Path) -> None:
    result = _run_control(base, docker_state)
    assert result.ok is True
    assert len(result.seeds) == 6
    assert all(seed.caught for seed in result.seeds)
    assert result.paste_back.count("[CAUGHT]") == 6
    assert "NOT CAUGHT" not in result.paste_back
    assert demo.leak_check_text(result.paste_back) == []


def test_build_control_paste_back_renders_a_not_caught_seed_distinctly() -> None:
    seeds = [demo.ControlSeed("a", True, "e1"), demo.ControlSeed("b", False, "e2")]
    block = demo.build_control_paste_back(seeds, "img:1", None)
    assert "[CAUGHT] a - e1" in block
    assert "[NOT CAUGHT] b - e2" in block
    assert "image_digest=UNKNOWN" in block


def test_timeout_seed_is_caught_with_a_confirmed_timeout_stop(base: Path, docker_state: Path) -> None:
    seed = demo.run_timeout_control(
        image="fake-image:1", docker_bin=_docker_bin(docker_state), base=base, timeout=5, limit=0.5, sleep=5,
    )
    assert seed.caught is True, seed.evidence
    assert "stop reason=timeout confirmed=True" in seed.evidence
    assert "disposition=inconclusive" in seed.evidence


def test_timeout_seed_is_not_caught_when_timeout_enforcement_is_disabled(
    base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Red case (issue #122): disable the timeout enforcement - `execute()`
    is handed a limit longer than the subject's sleep - and the seed must
    report NOT caught. The subject then finishes on its own (`exited`),
    which proves nothing about enforcement."""
    from skillc import docker_backend as dbe
    from skillc.backend import Limits

    real_execute = dbe.DockerBackend.execute

    def _unenforced(self: dbe.DockerBackend, handle: object, argv: object, limits: Limits, *rest: object, **kw: object) -> object:
        return real_execute(self, handle, argv, Limits(timeout=limits.timeout + 60), *rest, **kw)  # type: ignore[arg-type]

    monkeypatch.setattr(dbe.DockerBackend, "execute", _unenforced)
    seed = demo.run_timeout_control(
        image="fake-image:1", docker_bin=_docker_bin(docker_state), base=base, timeout=5, limit=0.3, sleep=1,
    )
    assert seed.caught is False
    assert "stop reason=exited" in seed.evidence


def test_run_control_is_not_ok_when_timeout_enforcement_is_disabled(
    base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same red case, through `run_control`: one seed not caught flips
    the whole `--control` verdict and shows in the block."""
    from skillc import docker_backend as dbe
    from skillc.backend import Limits

    real_execute = dbe.DockerBackend.execute

    def _unenforced(self: dbe.DockerBackend, handle: object, argv: object, limits: Limits, *rest: object, **kw: object) -> object:
        return real_execute(self, handle, argv, Limits(timeout=limits.timeout + 60), *rest, **kw)  # type: ignore[arg-type]

    monkeypatch.setattr(dbe.DockerBackend, "execute", _unenforced)
    result = _run_control(base, docker_state, timeout_limit=0.3, timeout_sleep=1.0)
    assert result.ok is False
    assert "[NOT CAUGHT] timeout" in result.paste_back


def test_cancellation_seed_is_caught_and_leaves_the_foreign_container_untouched(
    base: Path, docker_state: Path,
) -> None:
    """A real SIGINT to a real child `skillc demo --cancel-target` process
    group, mid-exec, against the fake `docker`."""
    seed = demo.run_cancellation_control(
        image="fake-image:1", docker_bin=_docker_bin(docker_state), base=base, timeout=5, sleep=4,
    )
    assert seed.caught is True, seed.evidence
    assert "exec observed live" in seed.evidence
    assert "interrupt_line=present exit=1" in seed.evidence
    assert "independent=already-absent" in seed.evidence
    assert "foreign=running (untouched)" in seed.evidence
    assert "foreign_removed=confirmed" in seed.evidence
    # The seed tears its own foreign container down afterwards.
    assert not reap.snapshot(_docker_bin(docker_state)).owned


def test_cancellation_seed_is_not_caught_when_the_interrupt_sweep_is_unscoped(
    base: Path, docker_state: Path,
) -> None:
    """Red case (issue #122): disable the interrupt handler's scoping - the
    child sweeps every skillc-owned container, #118's pre-fix behaviour -
    and the seed must report NOT caught, because the foreign container is
    gone."""
    seed = demo.run_cancellation_control(
        image="fake-image:1", docker_bin=_docker_bin(docker_state), base=base, timeout=5, sleep=4,
        child_command=[sys.executable, str(UNSCOPED_INTERRUPT_CHILD)],
    )
    assert seed.caught is False
    assert "interrupt_line=present exit=1" in seed.evidence  # the interrupt itself was handled
    assert "foreign=NOT running" in seed.evidence


def test_cancellation_seed_is_not_caught_when_the_child_never_starts_its_exec(
    base: Path, docker_state: Path,
) -> None:
    """A child that never announces its exec gets no SIGINT and cannot
    certify anything - NOT caught, and the wait is bounded, never a hang."""
    seed = demo.run_cancellation_control(
        image="fake-image:1", docker_bin=_docker_bin(docker_state), base=base, timeout=5, sleep=4,
        ready_timeout=1.0, child_command=[sys.executable, "-c", "import time; time.sleep(30)"],
    )
    assert seed.caught is False
    assert "never announced its exec" in seed.evidence
    assert not reap.snapshot(_docker_bin(docker_state)).owned


def test_cancellation_seed_is_not_caught_when_the_exec_is_never_observed_live(
    base: Path, docker_state: Path,
) -> None:
    """Red case (counter-model review of #122): the child announces its
    attempt but its subject never marks itself live. A marker plus a delay
    used to be enough to send SIGINT and certify; now no SIGINT is sent, the
    child is killed, and the container it left is reaped by the seed."""
    seed = demo.run_cancellation_control(
        image="fake-image:1", docker_bin=_docker_bin(docker_state), base=base, timeout=5, sleep=4,
        live_timeout=1.5, child_command=[sys.executable, str(NEVER_LIVE_CHILD)],
    )
    assert seed.caught is False
    assert "never observed live" in seed.evidence
    assert "independent=reaped" in seed.evidence  # the killed child left its container; the seed removed it
    assert not reap.snapshot(_docker_bin(docker_state)).owned


def test_cancellation_seed_is_not_caught_when_the_foreign_teardown_is_unconfirmed(
    base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Red case (counter-model review of #122): the parent's own removal of
    the foreign container is part of the verdict - an unconfirmed removal
    must not read CAUGHT. Only the parent is patched; the child is a separate
    process and never calls this."""
    from skillc import docker_backend as dbe
    from skillc.backend import Confirmation

    monkeypatch.setattr(dbe.DockerBackend, "confirm_absent", lambda self, handle: Confirmation.NOT_CONFIRMED)
    seed = demo.run_cancellation_control(
        image="fake-image:1", docker_bin=_docker_bin(docker_state), base=base, timeout=5, sleep=4,
    )
    assert seed.caught is False
    assert "interrupt_line=present exit=1" in seed.evidence
    assert "foreign_removed=not-confirmed" in seed.evidence


def test_cancellation_seed_interrupted_itself_kills_the_child_and_records_its_attempt(
    base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Counter-model review of #122: an operator interrupting `--control`
    while the seed waits must not orphan the child (it runs in its own
    session, so the terminal's SIGINT never reaches it). The child's attempt
    id must already be in the caller's list, so the caller's scoped sweep
    can reach its container."""
    started: list[subprocess.Popen[str]] = []
    real_popen = subprocess.Popen

    def _tracking_popen(*args: object, **kwargs: object) -> subprocess.Popen[str]:
        proc = real_popen(*args, **kwargs)  # type: ignore[call-overload]
        started.append(proc)
        return proc  # type: ignore[no-any-return]

    def _interrupted(*args: object) -> bool:
        raise KeyboardInterrupt

    monkeypatch.setattr(demo.subprocess, "Popen", _tracking_popen)
    monkeypatch.setattr(demo, "_exec_is_live", _interrupted)
    recorded: list[str] = []
    with pytest.raises(KeyboardInterrupt):
        demo.run_cancellation_control(
            image="fake-image:1", docker_bin=_docker_bin(docker_state), base=base, timeout=5, sleep=4,
            recorded_attempt_ids=recorded,
        )
    monkeypatch.undo()
    child = next(p for p in started if "--cancel-target" in p.args)  # type: ignore[operator]
    assert child.poll() is not None  # killed and waited for, never left running
    child_attempts = [a for a in recorded if a.startswith("a-")]
    assert len(child_attempts) == 1
    report = reap.reap(_docker_bin(docker_state), recorded)
    assert not report.left_running and not report.unknown
    assert not reap.snapshot(_docker_bin(docker_state)).owned


def test_cancellation_seed_is_not_caught_when_the_daemon_is_down(base: Path, docker_state: Path) -> None:
    docker_state.mkdir(parents=True, exist_ok=True)
    (docker_state / ".down").touch()
    seed = demo.run_cancellation_control(
        image="fake-image:1", docker_bin=_docker_bin(docker_state), base=base, timeout=5, sleep=4,
    )
    assert seed.caught is False
    assert "never ran" in seed.evidence


def test_cancel_target_mode_is_hidden_from_help(capsys: pytest.CaptureFixture[str]) -> None:
    from skillc import cli

    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["demo", "--help"])
    assert "--cancel-target" not in capsys.readouterr().out
    assert cli.build_parser().parse_args(["demo", "--cancel-target", "5"]).cancel_target == 5.0


# --------------- item 1 continued: KeyboardInterrupt is a BaseException,
# --------------- not caught by "except Exception" (cross-model review)


def test_cmd_demo_keyboard_interrupt_from_run_demo_never_prints_a_traceback(
    docker_state: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """Red case: `except Exception` alone does not catch `KeyboardInterrupt`
    (a `BaseException`, not an `Exception`) - remove `cmd_demo`'s own
    `except KeyboardInterrupt` clause and this test fails with the
    interrupt escaping `cmd_demo` entirely (pytest reports it as an error,
    not a clean assertion failure) - exactly what let Python's own default
    traceback, naming the installed `skillc` paths, reach the operator's
    terminal on a real Ctrl-C."""
    from skillc import cli

    def _interrupted(**kwargs: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(demo, "run_demo", _interrupted)
    args = _demo_args(image="fake-image:1", docker_bin=" ".join(_docker_bin(docker_state)), base="/tmp")

    exit_code = cli.cmd_demo(args)
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Traceback" not in captured.err
    assert "interrupted" in captured.err
    # Nothing was recorded before the interrupt (the mock never touched
    # `recorded_attempt_ids`), so the scoped sweep must say so rather than
    # calling `reap.reap()` with an empty list (which raises `ValueError`).
    assert "nothing to sweep" in captured.err


def test_cmd_demo_keyboard_interrupt_from_run_control_never_prints_a_traceback(
    docker_state: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    from skillc import cli

    def _interrupted(**kwargs: object) -> bool:
        raise KeyboardInterrupt

    monkeypatch.setattr(demo, "run_control", _interrupted)
    args = _demo_args(
        image="fake-image:1", docker_bin=" ".join(_docker_bin(docker_state)), base="/tmp", control=True,
    )

    exit_code = cli.cmd_demo(args)
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Traceback" not in captured.err
    assert "interrupted" in captured.err


def test_cmd_demo_keyboard_interrupt_sweeps_only_this_runs_recorded_attempt_ids(
    docker_state: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """Red case (issue #118, second review): the first fix's cleanup sweep
    was `reap.reap_all_owned()` - host-global, removing every skillc-owned
    container regardless of which run started it. Reproduced for real under a
    genuine SIGINT: it reaped a FOREIGN container from an unrelated attempt.
    Two owned containers exist here - one carrying an attempt id THIS run
    recorded before the interrupt, one carrying a different, foreign attempt
    id it never saw. After the interrupt, only the recorded one may be
    reaped; the foreign one must survive untouched. This fails on the
    `reap_all_owned()` version: swap the fix's `reap.reap(docker_bin,
    recorded_attempt_ids, ...)` call back to `reap.reap_all_owned(docker_bin,
    ...)` and the foreign container is gone too, since that sweep only checks
    skillc's OWNER label, never a specific attempt id."""
    from skillc import cli

    _run_owned_container(docker_state, "ours-container", "att-ours")
    _run_owned_container(docker_state, "foreign-container", "att-foreign")

    def _interrupted(**kwargs: object) -> None:
        recorded = kwargs["recorded_attempt_ids"]
        assert isinstance(recorded, list)
        recorded.append("att-ours")  # simulates run_demo having recorded its own attempt id before the interrupt
        raise KeyboardInterrupt

    monkeypatch.setattr(demo, "run_demo", _interrupted)
    args = _demo_args(image="fake-image:1", docker_bin=" ".join(_docker_bin(docker_state)), base="/tmp")

    exit_code = cli.cmd_demo(args)
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "best-effort cleanup" in captured.err
    assert "reaped" in captured.err

    docker_bin = _docker_bin(docker_state)
    foreign_ps = subprocess.run(
        [*docker_bin, "ps", "-a", "--filter", "name=foreign-container", "--format", "{{.Names}}"],
        capture_output=True, text=True, check=False,
    )
    assert "foreign-container" in foreign_ps.stdout  # the foreign attempt's container must survive

    ours_ps = subprocess.run(
        [*docker_bin, "ps", "-a", "--filter", "name=ours-container", "--format", "{{.Names}}"],
        capture_output=True, text=True, check=False,
    )
    assert "ours-container" not in ours_ps.stdout  # this run's own attempt's container must be gone


# --------------- item 4: NOT EXERCISED, never a vacuous MET


def test_acceptance_items_flags_cleanup_and_host_paths_not_exercised_when_prepare_never_succeeded() -> None:
    """Red case (issue #118): with `disposition="unavailable"` (prepare()
    itself failed), the reap report and host diff below are BOTH the
    trivially-clean shape (`daemon_reachable=True`, no outcomes, nothing
    changed) - the exact "vacuous MET" the operator's live run hit. Without
    the `prepare_never_succeeded` guard, both would read MET."""
    from skillc.verify import Graded

    lifecycle_record: dict[str, object] = {"disposition": "unavailable"}
    graded = Graded(status="INCONCLUSIVE", category="", detail="", criteria=[], containment={})
    clean_reap = reap.ReapReport(daemon_reachable=True, outcomes=())
    clean_host_diff = reap.HostPathDiff(changed=(), unresolved=())

    items = demo._acceptance_items(lifecycle_record, graded, clean_reap, clean_host_diff, None)
    cleanup_item = next(i for i in items if "cleanup sweep" in i.name)
    host_item = next(i for i in items if "host paths unchanged" in i.name)
    assert cleanup_item.exercised is False and cleanup_item.met is False
    assert host_item.exercised is False and host_item.met is False


def test_acceptance_items_exercises_cleanup_and_host_paths_when_prepare_did_succeed() -> None:
    """The other half: a non-`"unavailable"` disposition (prepare() DID
    succeed, whatever happened after) must NOT be forced NOT EXERCISED -
    these items still report their own real, computed status."""
    from skillc.verify import Graded

    lifecycle_record: dict[str, object] = {"disposition": "captured"}
    graded = Graded(status="PASS", category="", detail="", criteria=[], containment={})
    clean_reap = reap.ReapReport(daemon_reachable=True, outcomes=())
    clean_host_diff = reap.HostPathDiff(changed=(), unresolved=())

    items = demo._acceptance_items(lifecycle_record, graded, clean_reap, clean_host_diff, "sha256:x")
    cleanup_item = next(i for i in items if "cleanup sweep" in i.name)
    host_item = next(i for i in items if "host paths unchanged" in i.name)
    assert cleanup_item.exercised is True and cleanup_item.met is True
    assert host_item.exercised is True and host_item.met is True


def test_subject_acceptance_items_all_not_exercised_when_set() -> None:
    result = _ok_subject_result(not_exercised_reason="backend unavailable: docker daemon unreachable")
    items = demo._subject_acceptance_items(result)
    assert len(items) == 5
    assert all(not item.exercised and not item.met for item in items)
    assert all("backend unavailable" in item.evidence for item in items)


def test_run_demo_with_missing_daemon_reports_not_exercised_for_cleanup_and_host_paths(
    base: Path, docker_state: Path,
) -> None:
    """Integration-level version of the two unit tests above, through the
    real `run_demo` against the fake docker's own `.down` sentinel - the
    operator's actual scenario (no image/daemon reachable at all)."""
    docker_state.mkdir(parents=True, exist_ok=True)
    (docker_state / ".down").touch()
    result = demo.run_demo(image="fake-image:1", docker_bin=_docker_bin(docker_state), base=base, timeout=5)
    assert result.ok is False
    cleanup_item = next(i for i in demo._acceptance_items(
        result.lifecycle_record, result.graded, result.reap_report, result.host_diff, result.image_digest,
    ) if "cleanup sweep" in i.name)
    assert cleanup_item.exercised is False
