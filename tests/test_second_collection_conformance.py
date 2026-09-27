"""#11's second-collection conformance manifest (`evals/second-collection-
conformance/run-manifest.json`) cites each subject's ALREADY-recorded host
evidence rather than inventing numbers - this proves the citation is exact,
so a future regeneration of either subject's evidence cannot silently drift
out of sync with what this manifest claims. No model call, no Docker call:
this is a plain JSON structure and cross-reference check.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFORMANCE_DIR = ROOT / "evals" / "second-collection-conformance"
SUBJECTS_DIR = ROOT / "evals" / "subjects"


def _manifest() -> dict[str, object]:
    return json.loads((CONFORMANCE_DIR / "run-manifest.json").read_text(encoding="utf-8"))


def _runs_by_subject() -> dict[str, dict[str, object]]:
    manifest = _manifest()
    runs = manifest["runs"]
    assert isinstance(runs, list)
    return {run["subject"]: run for run in runs}  # type: ignore[index]


def test_the_manifest_declares_exactly_the_two_subjects_issue_11_names() -> None:
    assert set(_runs_by_subject()) == {"cpp-codex", "mattpocock-skills"}


def test_each_run_names_a_subject_declaration_that_actually_exists() -> None:
    for subject, run in _runs_by_subject().items():
        declaration = run["subject_declaration"]
        assert isinstance(declaration, str)
        declared = ROOT / declaration
        assert declared.is_file(), f"{subject}: {declared} does not exist"


def test_each_run_names_a_command_carrying_its_own_subject_name() -> None:
    """A copy-paste error (the wrong subject name in the command string)
    would otherwise be invisible - this is the one thing simple enough to
    check without executing anything."""
    for subject, run in _runs_by_subject().items():
        assert f"--subject {subject}" in run["command"]  # type: ignore[operator]


def test_the_installation_receipt_summary_matches_the_real_evidence() -> None:
    """The manifest CITES each subject's already-recorded observations - this
    proves the citation is exact, not a stale or hand-typed approximation.
    If a subject's evidence is ever regenerated with different counts, this
    test goes red rather than leaving the manifest quietly wrong."""
    for subject, run in _runs_by_subject().items():
        report_path = SUBJECTS_DIR / subject / "evidence" / "report.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        installed = report["observations"]["installed"]
        available = report["observations"]["available"]
        summary = run["expected_paste_back"]["installation_receipt_summary"]  # type: ignore[index]
        assert installed in summary, f"{subject}: manifest cites {summary!r}, evidence says {installed!r}"
        assert available in summary, f"{subject}: manifest cites {summary!r}, evidence says {available!r}"


def test_neither_run_invents_a_discovery_result() -> None:
    """#11's acceptance is prepared-not-run; a real per-skill discovery
    verdict does not exist until #81's client-listing step lands. Every
    `discovered` field must say so, in words, rather than assert a result."""
    for subject, run in _runs_by_subject().items():
        discovered = run["expected_paste_back"]["discovered"]  # type: ignore[index]
        assert "owed to" in discovered, f"{subject}: 'discovered' does not defer to the follow-up: {discovered!r}"


def test_the_manifest_states_it_is_not_yet_executed() -> None:
    assert "not executed" in _manifest()["execution"]  # type: ignore[operator]
