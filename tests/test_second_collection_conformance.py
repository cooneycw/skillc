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


def _receipt_summary_problems(installed: str, available: str, summary: str) -> list[str]:
    """Every way `summary` could fail to be an honest citation of
    `installed`/`available`. Both are required NONEMPTY (codex review of
    this PR): `"" in summary` is True unconditionally in Python, so an
    empty observation would otherwise pass the membership check silently -
    exactly the "found nothing because there was nothing to look at"
    failure this repository's own negative-control discipline exists to
    catch."""
    problems = []
    if not installed:
        problems.append("evidence's 'installed' observation is empty")
    if not available:
        problems.append("evidence's 'available' observation is empty")
    if installed and installed not in summary:
        problems.append(f"manifest cites {summary!r}, evidence says installed={installed!r}")
    if available and available not in summary:
        problems.append(f"manifest cites {summary!r}, evidence says available={available!r}")
    return problems


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
        problems = _receipt_summary_problems(installed, available, summary)
        assert problems == [], f"{subject}: {problems}"


def test_the_receipt_check_refuses_empty_observations() -> None:
    """The negative control for the emptiness guard above (codex review,
    MEDIUM): before this fix, an empty `installed`/`available` observation
    passed the membership check silently, since an empty string is a
    substring of anything. Confirmed this reproduces the described failure
    class, not merely asserted to."""
    assert _receipt_summary_problems("", "", "installed: 273 file(s) in 74 skill(s)") == [
        "evidence's 'installed' observation is empty",
        "evidence's 'available' observation is empty",
    ]
    # Nonempty and genuinely mismatched is still caught, unaffected by the fix.
    assert _receipt_summary_problems("999 file(s)", "SATISFIED", "installed: 273 file(s)") == [
        "manifest cites 'installed: 273 file(s)', evidence says installed='999 file(s)'",
        "manifest cites 'installed: 273 file(s)', evidence says available='SATISFIED'",
    ]


def test_neither_run_invents_a_discovery_result() -> None:
    """#11's acceptance is prepared-not-run; a real per-skill discovery
    verdict does not exist until #81's client-listing step lands. Every
    `discovered` field must say so, in words, rather than assert a result."""
    for subject, run in _runs_by_subject().items():
        discovered = run["expected_paste_back"]["discovered"]  # type: ignore[index]
        assert "owed to" in discovered, f"{subject}: 'discovered' does not defer to the follow-up: {discovered!r}"


def test_the_manifest_states_it_is_not_yet_executed() -> None:
    assert "not executed" in _manifest()["execution"]  # type: ignore[operator]
