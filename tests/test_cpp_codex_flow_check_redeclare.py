"""Regression tests for skillc#265/#287: `cpp-codex-flow-check` re-declared
as its OWN, SEPARATE profile at claude-power-pack's current pin
(`evals/subjects/cpp-codex-flow-check-ea6dbfa/`), per the original profile's
own stated rule ("a later pin is a new profile with its own inventory, not
an edit to this one") - the original `evals/subjects/cpp-codex-flow-check/`
profile (pinned at 85e9b03) is untouched.

The committed snapshot `tests/fixtures/profile-cpp-codex-flow-check-ea6dbfa/`
is the REAL `codex/skills/flow-check/` tree (plus the checkout-root files its
dependencies name) at the NEW pin, trimmed to exactly what diagnosing this
profile needs - nothing synthesized, nothing padded to hit a target count.

Red case (`test_the_old_profile_is_stale_against_the_new_pin`): the OLD,
untouched `evals/subjects/cpp-codex-flow-check/profile.json` against this
NEW-pin snapshot must report the EXACT SET of unresolved-reference strings
claude-power-pack#1370 found - not merely a matching count (orchestrator
review: "a count can stay the same while the set changes").

Green case (`test_the_new_profile_is_clean_against_its_own_pin`): the NEW
`evals/subjects/cpp-codex-flow-check-ea6dbfa/profile.json` against the SAME
snapshot must report zero problems.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from skillc import profile as p

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = Path(__file__).resolve().parent / "fixtures" / "profile-cpp-codex-flow-check-ea6dbfa"
OLD_DECLARATION = ROOT / "evals" / "subjects" / "cpp-codex-flow-check" / "profile.json"
NEW_DECLARATION = ROOT / "evals" / "subjects" / "cpp-codex-flow-check-ea6dbfa" / "profile.json"

#: claude-power-pack#1370's exact finding, reproduced here as a committed
#: constant so the red case's assertion is not just "whatever diagnose says
#: today" - these 20 distinct strings (one, `${HOME}/Projects`, appears twice
#: across two different files, for 21 total problem occurrences) are the
#: fixed target the old declaration must keep failing against.
EXPECTED_UNRESOLVED_REFERENCE_SET = frozenset({
    "$CPP_DIR/scripts/execution-evidence-verify.py",
    "${CLAUDE_PLUGIN_ROOT}/scripts/flow-finish-gate.sh",
    "${HOME}/Projects",
    "/opt/venv/bin/pytest",
    "/usr/local/bin",
    "/usr/local/bin/app",
    "/usr/local/bin/uv",
    "/usr/local/lib/python3.12",
    "~/.cache",
    "~/.cache/pip",
    "~/.cache/pypoetry",
    "~/.cache/uv",
    "~/.cache/yarn",
    "~/.cargo",
    "~/.local/share/pnpm",
    "~/.local/share/powershell/Modules",
    "~/.npm",
    "~/Projects/claude-power-pack/templates/Makefile.example",
    "~/Projects/claude-power-pack/templates/cicd.yml.example",
    "~/go/pkg/mod",
})
EXPECTED_TOTAL_PROBLEM_OCCURRENCES = 21  # 20 distinct strings; ${HOME}/Projects counted twice


def _unresolved_reference_strings(report: dict[str, Any]) -> list[str]:
    strings = []
    for problem in report["problems"]:
        assert isinstance(problem, dict)
        if problem["category"] != "unresolved-reference":
            continue
        match = re.search(r"unresolved reference: (\S+)", str(problem["detail"]))
        assert match is not None, f"could not extract a reference string from: {problem['detail']}"
        strings.append(match.group(1))
    return strings


def test_the_old_profile_is_stale_against_the_new_pin() -> None:
    prof = p.Profile.load(OLD_DECLARATION)
    tree = p.load_tree(prof, None, SNAPSHOT)
    report = p.diagnose(prof, tree)

    assert report["complete"] is True
    assert report["problem_count"] == EXPECTED_TOTAL_PROBLEM_OCCURRENCES

    strings = _unresolved_reference_strings(report)
    assert len(strings) == EXPECTED_TOTAL_PROBLEM_OCCURRENCES, (
        "every problem the old profile reports against this snapshot must be "
        "unresolved-reference - a different category appearing here means this test's "
        "assertions below are checking the wrong population"
    )
    assert set(strings) == EXPECTED_UNRESOLVED_REFERENCE_SET
    assert strings.count("${HOME}/Projects") == 2, (
        "this one string must be reported from BOTH lib/cicd/manifest.py and "
        "lib/cicd/steps.py - losing either occurrence would silently narrow the red case"
    )


def test_the_new_profile_is_clean_against_its_own_pin() -> None:
    prof = p.Profile.load(NEW_DECLARATION)
    tree = p.load_tree(prof, None, SNAPSHOT)
    report = p.diagnose(prof, tree)

    assert report["complete"] is True
    assert report["problem_count"] == 0
    assert report["problems"] == []


def test_red_case_a_diagnose_that_ignored_the_snapshot_would_pass_both() -> None:
    """Mutation check: a diagnose() that silently fell back to SOME OTHER
    source (e.g. one that accidentally re-resolved to the real repo tree at
    HEAD rather than this fixture) could make the red case above pass for
    the wrong reason - reporting problems that have nothing to do with THIS
    snapshot's content. Proves the two cases are actually tied to the same
    fixture by showing a deliberately EMPTY snapshot disagrees with both:
    the old profile against nothing is `missing-dependency-source`
    (not `unresolved-reference`), and the new profile against nothing
    is the same - so a diagnose that silently stopped reading the snapshot
    at all could not reproduce either test's real population by accident."""
    prof_old = p.Profile.load(OLD_DECLARATION)
    prof_new = p.Profile.load(NEW_DECLARATION)
    for prof in (prof_old, prof_new):
        tree = p.load_tree(prof, None, SNAPSHOT.parent / "profile-install-synthetic")
        report = p.diagnose(prof, tree)
        categories = {problem["category"] for problem in report["problems"]}  # type: ignore[index]
        assert "unresolved-reference" not in categories, (
            "diagnosing against an unrelated fixture must not reproduce the real "
            "unresolved-reference population - if it did, the two real tests above "
            "would not actually be exercising this profile's own snapshot"
        )
