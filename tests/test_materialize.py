"""Tests for `skillc materialize` (#7).

Every readiness fact is tested from BOTH sides: a case that makes it SATISFIED
and a case that makes it report the other verdict. A fact that cannot be driven
to VIOLATED or UNKNOWN by some input is not evidence, and the cases below are
what show it can.

Most tests use `fixtures/codex-subject/fake_codex.py`, because CI has no Codex.
The fake answers in the shape codex-cli 0.157.1 was observed to use; the one
test that runs the real client (`test_the_real_client_...`) is skipped where
Codex is not installed, and SAYS it is skipped - it is not evidence in CI. The
committed CPP evidence under `evals/subjects/cpp-codex/evidence/` is what the
real client produced on the host that ran it.

Git acquisition needs a git binary, which CI also lacks. Those tests skip there
for the same reason and are run on the host before merge.
"""

from __future__ import annotations

import ast
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from skillc import checks, cli, records
from skillc import materialize as m

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "codex-subject"
REPO = Path(__file__).resolve().parent.parent
EVIDENCE = REPO / "evals" / "subjects" / "cpp-codex" / "evidence"
RECEIPT = EVIDENCE / "records" / "receipt.json"
MATTPOCOCK_EVIDENCE = REPO / "evals" / "subjects" / "mattpocock-skills" / "evidence"
MATTPOCOCK_RECEIPT = MATTPOCOCK_EVIDENCE / "records" / "receipt.json"

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
needs_codex = pytest.mark.skipif(shutil.which("codex") is None, reason="codex is not installed")


# ------------------------------------------------------------------ helpers


def _subject(**changes: object) -> m.Subject:
    data = json.loads((FIXTURE / "subject.json").read_text(encoding="utf-8"))
    data.update(changes)
    return m.Subject.from_dict(data)


def _snapshot(tmp_path: Path) -> Path:
    snap = tmp_path / "snapshot"
    if not snap.exists():
        shutil.copytree(FIXTURE / "collection", snap)
    return snap


def _fake(tmp_path: Path, mode: str = "normal", **config: str) -> list[str]:
    script = tmp_path / "client" / "fake_codex.py"
    script.parent.mkdir(exist_ok=True)
    shutil.copy(FIXTURE / "fake_codex.py", script)
    script.with_suffix(".mode").write_text(json.dumps({"mode": mode, **config}), encoding="utf-8")
    return [sys.executable, str(script)]


def _host(tmp_path: Path) -> Path:
    host = tmp_path / "host-codex"
    (host / "skills" / "existing").mkdir(parents=True)
    (host / "skills" / "existing" / "SKILL.md").write_text("host skill\n", encoding="utf-8")
    (host / "config.toml").write_text("model = 'x'\n", encoding="utf-8")
    return host


def _run(tmp_path: Path, client: list[str] | None, subject: m.Subject | None = None,
         snapshot: Path | None = None, **kw: object) -> m.Result:
    if "host_codex" not in kw:
        kw["host_codex"] = _host(tmp_path)
    return m.materialize(
        subject or _subject(),
        attempt_id="att-1",
        trial_id="t-1",
        base=tmp_path / "base",
        snapshot=snapshot or _snapshot(tmp_path),
        client=client,
        **kw,  # type: ignore[arg-type]
    )


def _installed(receipt: dict[str, object] | None) -> dict[str, str]:
    assert receipt is not None
    entries = receipt["installed"]
    assert isinstance(entries, list)
    return {str(i["path"]): str(i["digest"]) for i in entries}


def _facts(result: m.Result) -> dict[str, str]:
    readiness = result.report["readiness"]
    assert isinstance(readiness, dict)
    return {k: readiness[k] for k in m.READINESS_FACTS if k in readiness}


def _leftovers(tmp_path: Path) -> list[Path]:
    base = tmp_path / "base"
    return sorted(base.iterdir()) if base.exists() else []


# ------------------------------------------------------------- the good run


def test_a_sound_install_is_ready_on_every_fact(tmp_path: Path) -> None:
    result = _run(tmp_path, _fake(tmp_path))
    assert "refused" not in result.report, result.report.get("refused")
    assert _facts(result) == dict.fromkeys(m.READINESS_FACTS, m.SATISFIED)
    assert result.ready
    assert result.report["cleanup"] == {"status": "removed", "errors": []}
    assert _leftovers(tmp_path) == [], "the disposable root outlived the run"


def test_the_receipt_passes_every_record_rule(tmp_path: Path) -> None:
    receipt = _run(tmp_path, _fake(tmp_path)).receipt
    assert receipt is not None
    findings = checks.run_record(records.Record(path=Path("receipt.json"), data=receipt))
    assert findings == []
    assert receipt["treatment"] == "native-install"


def test_four_observations_stay_distinct(tmp_path: Path) -> None:
    """Installed and available are observed; invoked and outcome are not claimed."""
    observations = _run(tmp_path, _fake(tmp_path)).report["observations"]
    assert observations == {
        "installed": "5 file(s) in 2 skill(s)",
        "available": m.SATISFIED,
        "invoked": "NOT_OBSERVED",
        "task_outcome": "NOT_APPLICABLE",
    }


def test_the_closure_is_recorded_and_the_non_skill_entry_is_named(tmp_path: Path) -> None:
    result = _run(tmp_path, _fake(tmp_path))
    receipt = result.receipt
    assert receipt is not None
    assert receipt["dependencies"] == [{
        "skill": "greet", "reference": "~/.fixture/helpers/stamp.sh", "in": "reference.md",
        "status": "external-not-materialized", "meaning": "host-only fixture helper",
    }]
    inventory = result.report["inventory"]
    assert isinstance(inventory, dict)
    assert inventory["not_installed_entries"] == ["README.md"]
    by_name = {s["name"]: s for s in inventory["skills"]}
    assert by_name["greet"]["checksums"] == "verified"
    assert by_name["tidy"]["checksums"] == "absent"
    assert by_name["greet"]["required_refs"] == ["reference.md", "scripts/hello.sh"]


# ------------------------------------------------- readiness: the other verdicts


def test_no_client_is_UNKNOWN_however_clean_the_static_scan(tmp_path: Path) -> None:
    """Static checks all pass here, and still nothing is ready: they are not readiness."""
    result = _run(tmp_path, None)
    facts = _facts(result)
    assert facts["discovery_canary"] == m.UNKNOWN
    assert facts["baseline_absence"] == m.UNKNOWN
    assert facts["ordinary_parity"] == m.UNKNOWN
    assert not result.ready


def test_an_installed_skill_the_client_does_not_list_is_VIOLATED(tmp_path: Path) -> None:
    result = _run(tmp_path, _fake(tmp_path, "blind"))
    facts = _facts(result)
    assert facts["discovery_canary"] == m.VIOLATED
    # The planted control was not listed either, so absence proves nothing.
    assert facts["baseline_absence"] == m.UNKNOWN
    readiness = result.report["readiness"]
    assert isinstance(readiness, dict)
    assert "negative control failed" in readiness["reasons"]["baseline_absence"]


@pytest.mark.parametrize(("mode", "why"), [
    ("noblock", "no skills listing"),
    ("crash", "exited 3"),
    ("version", "is not the declared"),
])
def test_an_unusable_client_answer_is_UNKNOWN_never_a_verdict(
    tmp_path: Path, mode: str, why: str
) -> None:
    result = _run(tmp_path, _fake(tmp_path, mode))
    facts = _facts(result)
    assert facts["discovery_canary"] == m.UNKNOWN
    readiness = result.report["readiness"]
    assert isinstance(readiness, dict)
    assert why in readiness["reasons"]["discovery_canary"]
    assert not result.ready


def test_a_hung_client_is_stopped_and_UNKNOWN(tmp_path: Path) -> None:
    result = _run(tmp_path, _fake(tmp_path, "hang"), timeout=2)
    assert _facts(result)["discovery_canary"] == m.UNKNOWN
    assert result.report["cleanup"] == {"status": "removed", "errors": []}


def test_a_baseline_that_sees_a_foreign_skill_is_VIOLATED(tmp_path: Path) -> None:
    """A leak under a name no treatment skill has: parity alone would pass it."""
    leak = tmp_path / "leak"
    shutil.copytree(FIXTURE / "collection" / "skills" / "tidy", leak / "neighbor")
    text = (leak / "neighbor" / "SKILL.md").read_text().replace("name: tidy", "name: neighbor")
    (leak / "neighbor" / "SKILL.md").write_text(text)
    facts = _facts(_run(tmp_path, _fake(tmp_path, "leak", dir=str(leak))))
    assert facts["baseline_absence"] == m.VIOLATED


def test_an_unknown_listing_row_is_UNKNOWN_not_an_empty_listing(tmp_path: Path) -> None:
    result = _run(tmp_path, _fake(tmp_path, "badrow"))
    assert _facts(result)["baseline_absence"] == m.UNKNOWN
    readiness = result.report["readiness"]
    assert isinstance(readiness, dict)
    assert "unparseable skill row" in readiness["reasons"]["baseline_absence"]


@pytest.mark.parametrize("mode", ["second-block", "star-row"])
def test_a_listing_the_parser_cannot_fully_read_is_UNKNOWN(tmp_path: Path, mode: str) -> None:
    """A leaked skill in a shape the parser skipped would otherwise pass absence."""
    facts = _facts(_run(tmp_path, _fake(tmp_path, mode)))
    assert facts["baseline_absence"] == m.UNKNOWN
    assert facts["discovery_canary"] == m.UNKNOWN


def test_an_effective_CODEX_HOME_is_fingerprinted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Changing the client home actually in use must not read as an unchanged host."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    custom = _host(tmp_path)
    monkeypatch.setenv("CODEX_HOME", str(custom))
    assert custom.resolve() in m.host_homes()
    assert custom.resolve() in m.forbidden_roots(None)
    client = _fake(tmp_path, "write-host", path=str(custom / "config.toml"))
    result = m.materialize(_subject(), attempt_id="a", trial_id="t", base=tmp_path / "base",
                           snapshot=_snapshot(tmp_path), client=client)
    assert _facts(result)["host_unchanged"] == m.VIOLATED


def test_an_unreadable_host_after_the_run_is_UNKNOWN_and_still_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = m.fingerprint_host
    calls = {"n": 0}

    def flaky(home: Path) -> dict[str, object]:
        calls["n"] += 1
        if calls["n"] > 1:
            raise PermissionError("unreadable now")
        return real(home)

    monkeypatch.setattr(m, "fingerprint_host", flaky)
    result = _run(tmp_path, _fake(tmp_path))
    assert _facts(result)["host_unchanged"] == m.UNKNOWN
    assert result.report["cleanup"] == {"status": "removed", "errors": []}
    assert not result.ready


def test_a_missing_client_executable_is_UNKNOWN_not_a_crash(tmp_path: Path) -> None:
    assert m.find_client(str(tmp_path / "no-such-codex")) is None
    result = _run(tmp_path, [str(tmp_path / "no-such-codex")])
    assert _facts(result)["discovery_canary"] == m.UNKNOWN
    assert result.report["cleanup"] == {"status": "removed", "errors": []}


def test_a_baseline_that_sees_the_treatment_is_VIOLATED(tmp_path: Path) -> None:
    leak = tmp_path / "leak"
    shutil.copytree(FIXTURE / "collection" / "skills" / "greet", leak / "greet")
    facts = _facts(_run(tmp_path, _fake(tmp_path, "leak", dir=str(leak))))
    assert facts["baseline_absence"] == m.VIOLATED


@pytest.mark.parametrize("mode", ["skew", "context", "block-extra", "desc"])
def test_arms_that_differ_outside_the_treatment_are_VIOLATED(tmp_path: Path, mode: str) -> None:
    facts = _facts(_run(tmp_path, _fake(tmp_path, mode)))
    assert facts["ordinary_parity"] == m.VIOLATED
    assert facts["discovery_canary"] == m.SATISFIED


def test_a_client_that_alters_the_install_is_refused(tmp_path: Path) -> None:
    result = _run(tmp_path, _fake(tmp_path, "mutate"))
    assert result.receipt is None
    assert "client altered an installed file" in str(result.report["refused"])


def test_a_changed_host_is_VIOLATED(tmp_path: Path) -> None:
    host = _host(tmp_path)
    result = _run(tmp_path, _fake(tmp_path, "write-host", path=str(host / "config.toml")),
                  host_codex=host)
    assert _facts(result)["host_unchanged"] == m.VIOLATED
    assert not result.ready


def test_a_changed_source_is_VIOLATED(tmp_path: Path) -> None:
    snap = _snapshot(tmp_path)
    target = snap / "skills" / "tidy" / "SKILL.md"
    result = _run(tmp_path, _fake(tmp_path, "write-host", path=str(target)), snapshot=snap)
    assert _facts(result)["source_unchanged"] == m.VIOLATED


# ---------------------------------------------------------- named refusals


def _refused(tmp_path: Path, snap: Path, subject: m.Subject | None = None) -> str:
    client = _fake(tmp_path)
    result = _run(tmp_path, client, subject=subject, snapshot=snap)
    assert result.receipt is None
    # Setup failure cleans the root it made, and the client was never asked:
    # nothing falls back to pasting instructions into a prompt.
    assert result.report["cleanup"] == {"status": "removed", "errors": []}
    assert _leftovers(tmp_path) == []
    assert "canary" not in result.report
    return str(result.report["refused"])


def test_an_empty_surface_is_refused(tmp_path: Path) -> None:
    snap = tmp_path / "empty"
    (snap / "skills").mkdir(parents=True)
    assert "empty discovery" in _refused(tmp_path, snap)


def test_a_missing_skills_root_is_refused(tmp_path: Path) -> None:
    (tmp_path / "nothing").mkdir()
    assert "absent" in _refused(tmp_path, tmp_path / "nothing")


def test_a_missing_required_reference_is_refused(tmp_path: Path) -> None:
    snap = _snapshot(tmp_path)
    (snap / "skills" / "greet" / "reference.md").unlink()
    assert "references missing file(s) ['reference.md']" in _refused(tmp_path, snap)


def test_a_missing_link_target_is_refused(tmp_path: Path) -> None:
    snap = _snapshot(tmp_path)
    tidy = snap / "skills" / "tidy" / "SKILL.md"
    tidy.write_text(tidy.read_text() + "\nSee [notes](notes.md).\n", encoding="utf-8")
    assert "['notes.md']" in _refused(tmp_path, snap)


def test_a_bundled_script_calling_a_host_helper_is_a_recorded_dependency(tmp_path: Path) -> None:
    snap = _snapshot(tmp_path)
    helper = snap / "skills" / "tidy" / "run.sh"
    helper.write_text("#!/bin/sh\n~/.fixture/helpers/strip.sh \"$1\"\n")
    receipt = _run(tmp_path, _fake(tmp_path), snapshot=snap).receipt
    assert receipt is not None
    dependencies = receipt["dependencies"]
    assert isinstance(dependencies, list)
    assert {"skill": "tidy", "reference": "~/.fixture/helpers/strip.sh", "in": "run.sh",
            "status": "external-not-materialized",
            "meaning": "host-only fixture helper"} in dependencies


def test_a_mentioned_path_is_a_static_finding_not_a_refusal(tmp_path: Path) -> None:
    """A path merely MENTIONED is not a declared requirement; refusing it would be a guess."""
    snap = _snapshot(tmp_path)
    tidy = snap / "skills" / "tidy" / "SKILL.md"
    tidy.write_text(tidy.read_text() + "\nThe repo keeps `docs/style.md` for this.\n",
                    encoding="utf-8")
    result = _run(tmp_path, _fake(tmp_path), snapshot=snap)
    assert result.ready
    findings = result.report["static_findings"]
    assert isinstance(findings, dict)
    assert any("docs/style.md" in f for f in findings["unresolved_mentions"])


def test_an_equivalent_link_spelling_is_accepted(tmp_path: Path) -> None:
    snap = _snapshot(tmp_path)
    greet = snap / "skills" / "greet" / "SKILL.md"
    greet.write_text(greet.read_text().replace("(scripts/hello.sh)", "(./scripts/hello.sh)"))
    assert _run(tmp_path, _fake(tmp_path), snapshot=snap).ready


def test_a_required_reference_outside_the_skill_is_refused(tmp_path: Path) -> None:
    snap = _snapshot(tmp_path)
    greet = snap / "skills" / "greet" / "SKILL.md"
    greet.write_text(greet.read_text().replace("(scripts/hello.sh)", "(../tidy/SKILL.md)"))
    assert "outside the skill" in _refused(tmp_path, snap)


def test_a_checksum_entry_outside_the_skill_is_refused(tmp_path: Path) -> None:
    snap = _snapshot(tmp_path)
    tidy = snap / "skills" / "tidy" / "SKILL.md"
    digest = m.sha256_file(tidy).removeprefix("sha256:")
    manifest = snap / "skills" / "greet" / "scripts" / "SHA256SUMS"
    manifest.write_text(manifest.read_text() + f"{digest}  ../../tidy/SKILL.md\n")
    assert "outside the skill" in _refused(tmp_path, snap)


def test_an_unreadable_entry_point_is_refused_not_raised(tmp_path: Path) -> None:
    snap = _snapshot(tmp_path)
    (snap / "skills" / "tidy" / "SKILL.md").write_bytes(b"---\nname: \xff\xfe\n---\n")
    assert "operational failure" in _refused(tmp_path, snap)


def test_a_missing_workspace_fixture_is_refused_not_raised(tmp_path: Path) -> None:
    result = _run(tmp_path, _fake(tmp_path), workspace_fixture=tmp_path / "absent")
    assert result.receipt is None
    assert "operational failure" in str(result.report["refused"])
    assert _leftovers(tmp_path) == []


def test_a_checksum_mismatch_is_refused(tmp_path: Path) -> None:
    snap = _snapshot(tmp_path)
    (snap / "skills" / "greet" / "scripts" / "hello.sh").write_text("echo changed\n")
    assert "checksum mismatch" in _refused(tmp_path, snap)


def test_a_symlinked_skills_root_is_refused(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    shutil.copytree(FIXTURE / "collection" / "skills", outside)
    snap = tmp_path / "linked"
    snap.mkdir()
    (snap / "skills").symlink_to(outside)
    assert "symlink in the path to the skills root" in _refused(tmp_path, snap)


def test_a_symlink_is_refused(tmp_path: Path) -> None:
    snap = _snapshot(tmp_path)
    (snap / "skills" / "tidy" / "escape.md").symlink_to("/etc/hostname")
    assert "symlink" in _refused(tmp_path, snap)


def test_a_name_collision_is_refused(tmp_path: Path) -> None:
    snap = _snapshot(tmp_path)
    shutil.copytree(snap / "skills" / "tidy", snap / "skills" / "tidy-copy")
    assert "name collision" in _refused(tmp_path, snap)


def test_a_case_folded_target_collision_is_refused(tmp_path: Path) -> None:
    snap = _snapshot(tmp_path)
    shutil.copytree(snap / "skills" / "tidy", snap / "skills" / "Greet")
    text = (snap / "skills" / "Greet" / "SKILL.md").read_text().replace("name: tidy", "name: other")
    (snap / "skills" / "Greet" / "SKILL.md").write_text(text)
    assert "target collision" in _refused(tmp_path, snap)


def test_a_skill_named_like_the_client_system_dir_is_refused(tmp_path: Path) -> None:
    snap = _snapshot(tmp_path)
    shutil.copytree(snap / "skills" / "tidy", snap / "skills" / ".system")
    text = (snap / "skills" / ".system" / "SKILL.md").read_text().replace("name: tidy", "name: x")
    (snap / "skills" / ".system" / "SKILL.md").write_text(text)
    assert "target collision" in _refused(tmp_path, snap)


@pytest.mark.parametrize(("layout", "why"), [
    ("root", "SKILL.md at the skills root"),
    ("nested", "nested skill"),
])
def test_unsupported_layouts_are_refused_by_name(tmp_path: Path, layout: str, why: str) -> None:
    snap = _snapshot(tmp_path)
    if layout == "root":
        shutil.copy(snap / "skills" / "tidy" / "SKILL.md", snap / "skills" / "SKILL.md")
    else:
        (snap / "skills" / "group" / "inner").mkdir(parents=True)
        shutil.copy(snap / "skills" / "tidy" / "SKILL.md", snap / "skills" / "group" / "inner")
    refused = _refused(tmp_path, snap)
    assert refused.startswith("unsupported layout:")
    assert why in refused


@pytest.mark.parametrize(("text", "why"), [
    ("no frontmatter\n", "frontmatter does not parse"),
    ("---\ndescription: nameless\n---\n", "declares no name"),
])
def test_an_unlistable_skill_is_refused(tmp_path: Path, text: str, why: str) -> None:
    snap = _snapshot(tmp_path)
    (snap / "skills" / "tidy" / "SKILL.md").write_text(text)
    assert why in _refused(tmp_path, snap)


def test_an_unknown_selected_skill_is_refused(tmp_path: Path) -> None:
    subject = _subject(select=["greet", "absent-skill"])
    assert "not in the surface" in _refused(tmp_path, _snapshot(tmp_path), subject)


def test_a_broken_unselected_neighbour_does_not_block_the_selection(tmp_path: Path) -> None:
    snap = _snapshot(tmp_path)
    (snap / "skills" / "greet" / "scripts" / "hello.sh").write_text("echo changed\n")
    (snap / "skills" / "greet" / "reference.md").unlink()
    result = _run(tmp_path, _fake(tmp_path), subject=_subject(select=["tidy"]), snapshot=snap)
    assert result.ready, result.report.get("refused")


def test_a_selection_installs_only_what_it_names(tmp_path: Path) -> None:
    result = _run(tmp_path, _fake(tmp_path), subject=_subject(select=["tidy"]))
    assert result.ready
    assert {path.split("/")[2] for path in _installed(result.receipt)} == {"tidy"}


# ------------------------------------------------------ subject declarations


@pytest.mark.parametrize(("change", "why"), [
    ({"surprise": 1}, "unknown keys"),
    ({"surface": "claude-plugin"}, "unsupported surface"),
    ({"client": {"name": "other", "version": "1"}}, "unsupported client"),
    ({"client": {"name": "codex"}}, "pins no client version"),
    ({"skills_root": "../outside"}, "escapes the subject"),
    ({"checksum_manifest": "../SHA256SUMS"}, "inside a skill"),
    ({"checksum_manifest": "/etc/SHA256SUMS"}, "inside a skill"),
    ({"required_references": [{"pattern": "no group"}]}, "capture group"),
    ({"external_references": [{"pattern": "(grouped)"}]}, "capture group"),
    ({"select": []}, "select must be"),
    # Issue #124: a surface is bound to ONE client - neither half of a pair
    # may be borrowed by the other.
    ({"surface": "claude-code-skills"}, "native to 'claude' only"),
    ({"client": {"name": "claude", "version": "2.1.283"}}, "native to 'codex' only"),
])
def test_a_malformed_subject_declaration_is_refused(change: dict[str, object], why: str) -> None:
    with pytest.raises(m.Refused, match=why):
        _subject(**change)


def test_each_surface_names_its_own_client_and_home_skills_dir() -> None:
    """Issue #124: the two declarable surfaces, as data - the install target
    is the surface's own client home, never a codex default for both."""
    codex = _subject()
    claude = _subject(surface="claude-code-skills", client={"name": "claude", "version": "2.1.283"})
    assert (codex.surface, codex.client, codex.surface_spec.home_skills_relpath) == (
        "codex-skills", "codex", ".codex/skills")
    assert (claude.surface, claude.client, claude.surface_spec.home_skills_relpath) == (
        "claude-code-skills", "claude", ".claude/skills")
    assert codex.surface_spec.model_free_listing and not claude.surface_spec.model_free_listing


def test_host_materialize_refuses_a_surface_with_no_model_free_listing(tmp_path: Path) -> None:
    """Issue #124: the host-local run's availability fact IS Codex's listing.
    A Claude Code subject is refused by name - never measured with a codex
    canary and reported as if Claude Code had listed anything."""
    claude = _subject(surface="claude-code-skills", client={"name": "claude", "version": "2.1.283"})
    result = _run(tmp_path, _fake(tmp_path), subject=claude)
    assert result.receipt is None
    assert "no model-free listing" in str(result.report["refused"])
    # The control: the SAME collection declared on codex is not refused here.
    assert _run(tmp_path / "control", _fake(tmp_path), subject=_subject()).receipt is not None


# ---------------------------------------------------------- git acquisition


def test_an_unpinned_revision_is_refused_before_git_is_asked(tmp_path: Path) -> None:
    result = m.materialize(_subject(revision="main"), attempt_id="a", trial_id="t",
                           base=tmp_path / "base", repo=tmp_path / "repo", client=None,
                           host_codex=_host(tmp_path))
    assert "not a full commit SHA" in str(result.report["refused"])


def _git_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE / "collection", repo)

    def git(*args: str) -> str:
        return subprocess.run(["git", "-C", str(repo), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    git("init", "-q")
    git("add", "-A")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "fixture")
    return repo, git("rev-parse", "HEAD")


@needs_git
def test_git_acquisition_installs_the_commit_not_the_dirty_tree(tmp_path: Path) -> None:
    repo, sha = _git_repo(tmp_path)
    tidy = repo / "skills" / "tidy" / "SKILL.md"
    committed = m.sha256_file(tidy)
    tidy.write_text(tidy.read_text() + "\nuncommitted\n")
    result = m.materialize(_subject(revision=sha), attempt_id="a", trial_id="t",
                           base=tmp_path / "base", repo=repo, client=_fake(tmp_path),
                           host_codex=_host(tmp_path))
    assert result.ready, result.report.get("refused")
    receipt = result.receipt
    assert receipt is not None
    assert receipt["subject"]["revision"] == sha  # type: ignore[index]
    assert _installed(receipt)[".codex/skills/tidy/SKILL.md"] == committed


@needs_git
def test_a_second_edit_to_an_already_dirty_source_file_is_VIOLATED(tmp_path: Path) -> None:
    """`git status` reads ` M` before and after; only the contents can tell."""
    repo, sha = _git_repo(tmp_path)
    dirty = repo / "skills" / "tidy" / "SKILL.md"
    dirty.write_text(dirty.read_text() + "\nalready dirty\n")
    client = _fake(tmp_path, "write-host", path=str(dirty))
    result = m.materialize(_subject(revision=sha), attempt_id="a", trial_id="t",
                           base=tmp_path / "base", repo=repo, client=client,
                           host_codex=_host(tmp_path))
    assert _facts(result)["source_unchanged"] == m.VIOLATED


@needs_git
def test_a_retargeted_dirty_symlink_is_VIOLATED(tmp_path: Path) -> None:
    repo, sha = _git_repo(tmp_path)
    (tmp_path / "a.txt").write_text("a\n")
    (tmp_path / "b.txt").write_text("b\n")
    link = repo / "untracked-link"
    link.symlink_to(tmp_path / "a.txt")
    client = _fake(tmp_path, "relink", path=str(link), target=str(tmp_path / "b.txt"))
    result = m.materialize(_subject(revision=sha), attempt_id="a", trial_id="t",
                           base=tmp_path / "base", repo=repo, client=client,
                           host_codex=_host(tmp_path))
    assert _facts(result)["source_unchanged"] == m.VIOLATED


@needs_git
@pytest.mark.parametrize("layout", ["dot", "dot-slash"])
def test_equivalent_skills_root_spellings_acquire_from_git(tmp_path: Path, layout: str) -> None:
    if layout == "dot":
        repo = tmp_path / "repo"
        shutil.copytree(FIXTURE / "collection" / "skills", repo)
        (repo / "README.md").unlink()
        for args in (["init", "-q"], ["add", "-A"],
                     ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "x"]):
            subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
        sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True,
                             capture_output=True, text=True).stdout.strip()
        subject = _subject(revision=sha, skills_root=".")
    else:
        repo, sha = _git_repo(tmp_path)
        subject = _subject(revision=sha, skills_root="./skills")
    result = m.materialize(subject, attempt_id="a", trial_id="t", base=tmp_path / "base",
                           repo=repo, client=_fake(tmp_path), host_codex=_host(tmp_path))
    assert result.ready, result.report.get("refused")
    assert len(_installed(result.receipt)) == 5


@needs_git
def test_an_unresolvable_revision_is_refused(tmp_path: Path) -> None:
    repo, _ = _git_repo(tmp_path)
    result = m.materialize(_subject(revision="1" * 40), attempt_id="a", trial_id="t",
                           base=tmp_path / "base", repo=repo, client=None,
                           host_codex=_host(tmp_path))
    assert "does not resolve" in str(result.report["refused"])


# ---------------------------------------------------------------- owned roots


def test_a_root_inside_a_forbidden_place_is_refused(tmp_path: Path) -> None:
    forbidden = tmp_path / "host-home" / ".codex"
    forbidden.mkdir(parents=True)
    with pytest.raises(m.Refused, match="not trial-owned"):
        m.create_root(forbidden / "skills", [forbidden.resolve()])


def test_the_run_refuses_to_root_inside_the_source(tmp_path: Path) -> None:
    snap = _snapshot(tmp_path)
    with pytest.raises(m.Refused, match="not trial-owned"):
        m.materialize(_subject(), attempt_id="a", trial_id="t", base=snap / "work",
                      snapshot=snap, client=None, host_codex=_host(tmp_path))


def test_cleanup_is_repeatable_and_refuses_what_it_does_not_own(tmp_path: Path) -> None:
    root, nonce = m.create_root(tmp_path / "base", [])
    assert m.cleanup(root, nonce)["status"] == "removed"
    assert m.cleanup(root, nonce)["status"] == "already-absent"

    stranger = tmp_path / "stranger"
    stranger.mkdir()
    (stranger / "keep.txt").write_text("mine\n")
    assert m.cleanup(stranger, nonce)["status"] == "refused-not-owned"
    assert (stranger / "keep.txt").exists()

    other, _ = m.create_root(tmp_path / "base", [])
    assert m.cleanup(other, "wrong-nonce")["status"] == "refused-not-owned"
    assert other.exists()


def test_keep_leaves_the_root_for_inspection(tmp_path: Path) -> None:
    result = _run(tmp_path, _fake(tmp_path), keep=True)
    assert result.report["cleanup"] == {"status": "kept", "errors": []}
    (root,) = _leftovers(tmp_path)
    assert (root / "treatment" / "home" / ".codex" / "skills" / "greet" / "SKILL.md").is_file()


# ----------------------------------------------------------------------- CLI


def _cli(tmp_path: Path, client: list[str], out: Path) -> int:
    script = client[1]
    return cli.main([
        "materialize", str(FIXTURE / "subject.json"), "--snapshot", str(_snapshot(tmp_path)),
        "--out", str(out), "--attempt-id", "att-1", "--trial-id", "t-1",
        "--client", script, "--base", str(tmp_path / "base"),
    ])


def test_cli_refuses_to_write_evidence_into_the_source(tmp_path: Path) -> None:
    snap = _snapshot(tmp_path)
    alias = tmp_path / "alias"
    alias.symlink_to(snap)
    for out in (snap / "evidence", alias / "evidence"):
        code = cli.main([
            "materialize", str(FIXTURE / "subject.json"), "--snapshot", str(snap),
            "--out", str(out), "--attempt-id", "a", "--trial-id", "t",
            "--base", str(tmp_path / "base"),
        ])
        assert code == 2
        assert not (snap / "evidence").exists()


def test_cli_exit_follows_readiness_and_never_overwrites_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The CLI takes one executable; make the fake one directly runnable.
    client = _fake(tmp_path)
    Path(client[1]).chmod(0o755)
    monkeypatch.setattr(m, "find_client", lambda _explicit: client)
    out = tmp_path / "out"
    assert _cli(tmp_path, client, out) == 0
    assert "READY" in capsys.readouterr().out
    assert cli.main(["check-records", str(out / "records")]) == 0
    assert _cli(tmp_path, client, out) == 2, "an existing receipt was overwritten"

    blind = _fake(tmp_path, "blind")
    monkeypatch.setattr(m, "find_client", lambda _explicit: blind)
    assert _cli(tmp_path, blind, tmp_path / "out-blind") == 1
    assert "NOT READY" in capsys.readouterr().out


# ------------------------------------------------ nothing here names a subject


#: Words that belong to one subject's conventions. They may appear in the
#: subject's declaration, never in the generic adapter or the core runner/
#: verifier modules (#11: a second, independently-authored subject is the
#: proof that no branch crept in for the first one).
SUBJECT_WORDS = ("power-pack", "cpp", "sha256sums", ".claude/scripts", "codex/skills",
                 "claude_plugin_root", "reference.md", "mattpocock")

#: A module named here is excused from the "no project-name branch" guard,
#: with a stated reason - never silently. Empty today: every `skillc/*.py`
#: module (#11's full re-check, 2026-09-26, orchestrator review of PR #94)
#: is already clean of any `SUBJECT_WORDS` literal. An entry is justified
#: only for a module whose actual job is to hold a subject-facing DEFAULT
#: (a bare command's fallback subject, say) - and even then, prefer reading
#: that default from a declared `evals/subjects/*/subject.json` over a
#: literal, so the exemption is never needed at all. A heads-up was given
#: (#81's `demo.py` is imminent and will be scanned the moment it lands)
#: precisely so this stays empty rather than growing by surprise.
GENERICITY_EXEMPT: dict[str, str] = {}


def _core_modules() -> list[str]:
    """Every `skillc/*.py` module, minus `GENERICITY_EXEMPT` - an OPEN set,
    not a closed allowlist (#11, orchestrator review of PR #94: the
    previous `CORE_MODULES` tuple left every module added after it was
    written unguarded by default, with no one having to forget to add the
    next one for that gap to exist). A new module under `skillc/` is
    covered by this guard the moment it exists.
    """
    return sorted(
        p.name for p in (REPO / "skillc").glob("*.py")
        if p.name not in GENERICITY_EXEMPT
    )


CORE_MODULES = _core_modules()


def _subject_literals(source: str) -> list[str]:
    """String literals that name a subject. Docstrings and comments cannot trigger it."""
    tree = ast.parse(source)
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef))
        and node.body and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    return [
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and id(node) not in docstrings
        and any(word in node.value.lower() for word in SUBJECT_WORDS)
    ]


@pytest.mark.parametrize("module", CORE_MODULES)
def test_the_core_names_no_subject(module: str) -> None:
    source = (REPO / "skillc" / module).read_text(encoding="utf-8")
    assert _subject_literals(source) == []


@pytest.mark.parametrize("module", CORE_MODULES)
def test_the_subject_guard_sees_a_planted_literal(module: str) -> None:
    """The negative control (#11): plant a project-name branch and require the
    guard to see it, in EVERY core module it claims to cover - a guard proven
    only on materialize.py could go blind on the other three without any test
    noticing."""
    source = (REPO / "skillc" / module).read_text(encoding="utf-8")
    planted = source + '\nMANIFEST = "scripts/SHA256SUMS"\n'
    assert _subject_literals(planted) == ["scripts/SHA256SUMS"]


def test_the_subject_guard_sees_a_planted_mattpocock_branch() -> None:
    """#11's own second subject: a literal name branch for it must be as
    visible to the guard as CPP's ever was."""
    source = (REPO / "skillc" / "materialize.py").read_text(encoding="utf-8")
    planted = source + '\nif locator == "mattpocock": pass\n'
    assert _subject_literals(planted) == ["mattpocock"]


def _stale_exempt_names(exempt: dict[str, str]) -> list[str]:
    return [name for name in exempt if not (REPO / "skillc" / name).is_file()]


def test_genericity_exempt_names_only_real_files() -> None:
    """Orchestrator review of PR #94: an exemption naming a module that no
    longer exists (renamed, deleted) would silently stop meaning anything -
    checked here so `GENERICITY_EXEMPT` can't go stale unnoticed. Passes
    vacuously while the dict is empty, which is the correct state, not a
    gap: the negative control below is what proves this check can fail."""
    assert _stale_exempt_names(GENERICITY_EXEMPT) == []


def test_the_exempt_staleness_check_catches_a_stale_name() -> None:
    """The negative control for the test above (ADR 0001): a `GENERICITY_EXEMPT`
    naming a file that does not exist must be caught, not merely trusted to
    be caught because the real dict happens to be empty today."""
    assert _stale_exempt_names({"does_not_exist.py": "planted for this test"}) == [
        "does_not_exist.py"
    ]


# ----------------------------------------------------------- the real client


@needs_codex
def test_the_real_client_discriminates_on_the_fixture(tmp_path: Path) -> None:
    """Runs where Codex is installed. Skipped in CI, which has no Codex - see module doc."""
    codex = m.find_client(None)
    assert codex is not None
    probe = tmp_path / "probe"
    probe.mkdir()
    version = m.client_version(codex, probe, probe / ".codex", probe)
    subject = _subject(client={"name": "codex", "version": version})
    result = _run(tmp_path, codex, subject=subject, keep=True)
    assert _facts(result) == dict.fromkeys(m.READINESS_FACTS, m.SATISFIED), result.report

    # The red side with the SAME client and parser: an arm with nothing installed,
    # read as if it were the treatment, must not be called discovered.
    (root,) = _leftovers(tmp_path)
    baseline = m.Arm("baseline", root / "baseline")
    listing = m.canary(codex, baseline, 120)
    entries = m.inventory(subject, m.acquire_snapshot(subject, _snapshot(tmp_path / "again"),
                                                      tmp_path / "staging"))
    readiness = m.derive_readiness(subject, version, entries, baseline, listing,
                                   baseline, listing, baseline, listing)
    assert readiness.discovery_canary == m.VIOLATED


# ---------------------------------------------------------- committed evidence


def test_the_committed_cpp_evidence_is_ready_and_well_formed() -> None:
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    report = json.loads((EVIDENCE / "report.json").read_text(encoding="utf-8"))
    subject = json.loads((EVIDENCE.parent / "subject.json").read_text(encoding="utf-8"))
    assert checks.run_record(records.Record(path=Path("receipt.json"), data=receipt)) == []
    assert receipt["subject"]["revision"] == subject["revision"]
    assert receipt["client"]["version"] == subject["client"]["version"]
    assert receipt["readiness"] == dict.fromkeys(m.READINESS_FACTS, m.SATISFIED)
    assert report["control"]["listed"] is True
    assert len(report["inventory"]["skills"]) == len(
        [line for line in report["canary"]["treatment"]["listed"] if "/.codex/skills/." not in line]
    )


def test_the_committed_mattpocock_evidence_is_ready_and_well_formed() -> None:
    """#11's second subject, proving the same adapter and readiness facts
    against an independently authored collection with a different layout."""
    receipt = json.loads(MATTPOCOCK_RECEIPT.read_text(encoding="utf-8"))
    report = json.loads((MATTPOCOCK_EVIDENCE / "report.json").read_text(encoding="utf-8"))
    subject = json.loads((MATTPOCOCK_EVIDENCE.parent / "subject.json").read_text(encoding="utf-8"))
    assert checks.run_record(records.Record(path=Path("receipt.json"), data=receipt)) == []
    assert receipt["subject"]["revision"] == subject["revision"]
    assert receipt["client"]["version"] == subject["client"]["version"]
    assert receipt["readiness"] == dict.fromkeys(m.READINESS_FACTS, m.SATISFIED)
    assert report["control"]["listed"] is True
    installed_names = sorted(s["name"] for s in report["inventory"]["skills"])
    assert installed_names == ["diagnosing-bugs", "tdd"]
    # Cross-model review: `readiness` is a DERIVED claim; re-derive the same
    # fact from the RAW canary listing rather than trusting the summary - an
    # emptied or tampered treatment listing must not pass just because the
    # receipt still says SATISFIED and the inventory still names the skills.
    treatment_lines = [
        line for line in report["canary"]["treatment"]["listed"]
        if "/.codex/skills/." not in line
    ]
    assert sorted(line.split()[0] for line in treatment_lines) == installed_names
