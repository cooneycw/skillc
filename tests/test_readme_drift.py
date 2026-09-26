"""README drift checks (#73): commands, version, status vs. milestones.

Each committed pair below is the red case the issue's acceptance names:
a command README lists that does not exist, a real one it omits, a stated
version that disagrees with the package, and a stale status claim against
`docs/milestones.json`.
"""

from __future__ import annotations

from ci import readme_drift as rd
from skillc.cli import build_parser

COMMANDS_BLOCK = (
    "<!-- commands:start -->\n"
    "```bash\n"
    "skillc check <path>\n"
    "skillc selftest\n"
    "```\n"
    "<!-- commands:end -->\n"
)

FULL_COMMANDS_BLOCK = (
    "<!-- commands:start -->\n"
    "```bash\n"
    "skillc check <path>\n"
    "skillc selftest\n"
    "skillc check-records <path>\n"
    "skillc materialize <subject>\n"
    "skillc rules\n"
    "skillc leak-check <path>\n"
    "```\n"
    "<!-- commands:end -->\n"
)


def test_real_commands_matches_the_actual_parser() -> None:
    real = rd.real_commands(build_parser())
    assert real == {"check", "selftest", "check-records", "materialize", "rules", "leak-check"}


def test_bad_readme_omits_a_real_command() -> None:
    problems = rd.command_drift(COMMANDS_BLOCK, {"check", "selftest", "leak-check"})
    assert problems and "omits" in problems[0]


def test_bad_readme_lists_a_command_that_does_not_exist() -> None:
    block = COMMANDS_BLOCK.replace("skillc selftest", "skillc selftest\nskillc frobnicate")
    problems = rd.command_drift(block, {"check", "selftest"})
    assert any("do not exist" in p for p in problems)
    assert any("frobnicate" in p for p in problems)


def test_good_readme_lists_exactly_the_real_commands() -> None:
    real = {"check", "selftest", "check-records", "materialize", "rules", "leak-check"}
    assert rd.command_drift(FULL_COMMANDS_BLOCK, real) == []


def test_bad_no_commands_block_at_all() -> None:
    assert rd.command_drift("nothing here", {"check"}) != []


def test_bad_empty_real_command_set_is_not_a_match() -> None:
    """One side non-empty already mismatches via ordinary set difference; kept
    as a sanity check, not the precise vacuous-pass case (below)."""
    assert rd.command_drift(FULL_COMMANDS_BLOCK, set()) != []


def test_bad_readme_commands_block_is_empty() -> None:
    empty_block = "<!-- commands:start -->\n```bash\n```\n<!-- commands:end -->\n"
    assert rd.command_drift(empty_block, {"check"}) != []


def test_bad_both_sides_empty_is_not_a_vacuous_match() -> None:
    """Cross-model review [MEDIUM], the precise case: an empty commands block
    against an empty real set matched by ordinary set equality (both empty),
    so it read as agreement with nothing actually compared. Confirmed real on
    the pre-fix code: `command_drift(empty_block, set()) == []` there."""
    empty_block = "<!-- commands:start -->\n```bash\n```\n<!-- commands:end -->\n"
    assert rd.command_drift(empty_block, set()) != []


# ----------------------------------------------------------------- version


def test_good_readme_states_no_version() -> None:
    assert rd.version_drift("no version mentioned", "1.2.3") == []


def test_good_readme_version_matches() -> None:
    assert rd.version_drift("**Version:** `1.2.3`", "1.2.3") == []


def test_bad_readme_version_differs() -> None:
    problems = rd.version_drift("**Version:** `1.2.3`", "1.2.4")
    assert problems and "1.2.3" in problems[0] and "1.2.4" in problems[0]


# ------------------------------------------------------------------ status


MILESTONES_BLOCK = (
    "<!-- milestones:start -->\n"
    "| Milestone | State |\n"
    "|---|---|\n"
    "| 0.1.0 - static checker | closed |\n"
    "| 0.2.0 - real Docker trial end to end (#10) | open |\n"
    "<!-- milestones:end -->\n"
)

MILESTONES_DATA: dict[str, object] = {
    "milestones": [
        {"version": "0.1.0", "label": "static checker", "issue": None, "state": "closed"},
        {"version": "0.2.0", "label": "real Docker trial end to end (#10)", "issue": 10, "state": "open"},
    ]
}


def test_good_status_matches_milestones_file() -> None:
    assert rd.status_drift(MILESTONES_BLOCK, MILESTONES_DATA) == []


def test_bad_a_closed_milestone_still_reads_open_in_the_readme() -> None:
    """The exact shape the issue names: a capability's milestone closed, but
    the README still calls it not implemented."""
    stale_data: dict[str, object] = {
        "milestones": [
            {"version": "0.1.0", "label": "static checker", "issue": None, "state": "closed"},
            {"version": "0.2.0", "label": "real Docker trial end to end (#10)", "issue": 10, "state": "closed"},
        ]
    }
    problems = rd.status_drift(MILESTONES_BLOCK, stale_data)
    assert problems and "0.2.0" in problems[0]
    assert "'open'" in problems[0] and "'closed'" in problems[0]


def test_bad_readme_has_no_milestones_block() -> None:
    assert rd.status_drift("nothing here", MILESTONES_DATA) != []


def test_bad_empty_milestones_table_is_not_a_match() -> None:
    """Cross-model review [MEDIUM]: an empty table and an empty file's
    'milestones' list must not read as agreement. Confirmed real on the
    pre-fix code."""
    empty_block = "<!-- milestones:start -->\n| Milestone | State |\n|---|---|\n<!-- milestones:end -->\n"
    assert rd.status_drift(empty_block, MILESTONES_DATA) != []


def test_bad_empty_milestones_file_is_not_a_match() -> None:
    empty_data: dict[str, object] = {"milestones": []}
    assert rd.status_drift(MILESTONES_BLOCK, empty_data) != []


def test_bad_both_milestones_sides_empty_is_not_a_vacuous_match() -> None:
    """Cross-model review [MEDIUM], the precise case: an empty table against
    an empty file's 'milestones' list matched by having nothing to disagree
    on. Confirmed real on the pre-fix code: `status_drift` returned `[]` for
    this exact pair there."""
    empty_block = "<!-- milestones:start -->\n| Milestone | State |\n|---|---|\n<!-- milestones:end -->\n"
    empty_data: dict[str, object] = {"milestones": []}
    assert rd.status_drift(empty_block, empty_data) != []


def test_bad_malformed_milestone_entries_are_reported_not_skipped() -> None:
    """Cross-model review [MEDIUM]: a list of only non-dict entries used to be
    silently skipped down to an empty (falsely matching) population."""
    malformed_data: dict[str, object] = {"milestones": ["not a dict", 42]}
    problems = rd.status_drift(MILESTONES_BLOCK, malformed_data)
    assert any("non-object milestone entry" in p for p in problems)


_MILESTONE_ENTRIES: list[dict[str, object]] = [
    {"version": "0.1.0", "label": "static checker", "issue": None, "state": "closed"},
    {"version": "0.2.0", "label": "real Docker trial end to end (#10)", "issue": 10, "state": "open"},
]


def test_bad_milestones_file_names_an_entry_the_readme_omits() -> None:
    extra_data: dict[str, object] = {
        "milestones": [
            *_MILESTONE_ENTRIES,
            {"version": "0.3.0", "label": "third thing", "issue": 99, "state": "open"},
        ]
    }
    problems = rd.status_drift(MILESTONES_BLOCK, extra_data)
    assert any("0.3.0" in p for p in problems)


def test_bad_readme_names_an_entry_the_file_omits() -> None:
    trimmed_data: dict[str, object] = {"milestones": _MILESTONE_ENTRIES[:1]}
    problems = rd.status_drift(MILESTONES_BLOCK, trimmed_data)
    assert any("0.2.0" in p for p in problems)


# ------------------------------------------------------------- the real README


def test_the_real_readme_passes_every_check() -> None:
    import json
    import tomllib

    from skillc import __version__

    readme_text = (rd.ROOT / "README.md").read_text(encoding="utf-8")
    milestones_data = json.loads((rd.ROOT / "docs" / "milestones.json").read_text(encoding="utf-8"))
    pyproject_version = tomllib.loads(
        (rd.ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]["version"]
    assert pyproject_version == __version__
    assert rd.command_drift(readme_text, rd.real_commands(build_parser())) == []
    assert rd.version_drift(readme_text, __version__) == []
    assert rd.status_drift(readme_text, milestones_data) == []
