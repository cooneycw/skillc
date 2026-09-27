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
import subprocess
import sys
from pathlib import Path

import pytest

from skillc import demo, materialize, reap
from skillc.docker_backend import DAEMON_TIMEOUT
from skillc.verify import Graded

FAKE_DOCKER = Path(__file__).resolve().parent / "fixtures" / "docker-backend" / "fake_docker.py"
#: `materialize.py`'s own fake codex client (#7) - reused here for the
#: in-container discovery listing, never a real ambient `codex` on PATH.
CODEX_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "codex-subject"


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


def _git_subject_repo(tmp_path: Path, skills: dict[str, str]) -> tuple[Path, str]:
    """A tiny git repo under `tmp_path` with one `SKILL.md` per entry in
    `skills` (name -> directory), each committed - real `git` acquisition
    (`materialize.acquire_git`) needs a genuine commit object to archive
    from, never a bare directory. Returns (repo path, commit SHA)."""
    repo = tmp_path / "subject-repo"
    repo.mkdir()
    skills_root = repo / "skills"
    for name, directory in skills.items():
        skill_dir = skills_root / directory
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(_skill_md(name), encoding="utf-8")
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "--quiet", "-m", "subject"], check=True, env=env)
    sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True,
    ).stdout.strip()
    return repo, sha


def _subject(revision: str, select: object = "all") -> materialize.Subject:
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
    repo, sha = _git_subject_repo(tmp_path, {"greet": "greet", "farewell": "farewell"})
    subject = _subject(sha)
    staging = tmp_path / "staging"
    staging.mkdir()
    source = materialize.acquire_git(subject, repo, staging)
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
    repo, sha = _git_subject_repo(tmp_path, {"greet": "greet"})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject(sha, select=["greet", "does-not-exist"]))
    with pytest.raises(demo.SubjectRefused, match="does-not-exist"):
        demo.run_subject_demo(
            subject_name="whatever", image="fake-image:1", docker_bin=_docker_bin(docker_state),
            base=tmp_path / "work", timeout=5, checkout=repo,
        )


def test_run_subject_demo_happy_path_installs_matches_and_discovers(
    tmp_path: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch, base: Path,
) -> None:
    repo, sha = _git_subject_repo(tmp_path, {"greet": "greet", "farewell": "farewell"})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject(sha))
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
    repo, sha = _git_subject_repo(tmp_path, {"greet": "greet"})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject(sha))
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
    repo, sha = _git_subject_repo(tmp_path, {"greet": "greet"})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject(sha))
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
    repo, sha = _git_subject_repo(tmp_path, {"greet": "greet", "farewell": "farewell"})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject(sha))
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
    repo, sha = _git_subject_repo(tmp_path, {"greet": "greet"})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: _subject(sha))
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
