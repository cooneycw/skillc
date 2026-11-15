"""The plain-English gauntlet report (#783) and the machine lines it must not change.

Owner, 2026-11-15: "Output is engine-speak." `gauntlet run` now leads with a
report a person reads - for each round reached, what was Checked, what was
Found, what it Means, and the one thing to Do next - then prints the machine
lines (ROUND / RECORD / NEXT / GAUNTLET) BYTE-IDENTICAL to before, because
tests and `gauntlet verdict` read them.

Every fixture stop has two goldens in tests/fixtures/gauntlet-report/:
`<case>.machine.txt`, captured from the engine BEFORE #783 (f29e3a3), and
`<case>.plain.txt`, the report the owner reads. Set GAUNTLET_REPORT_CAPTURE=1
to rewrite them; the machine goldens must never need it.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from skillc import gauntlet

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "evals" / "subjects" / "gauntlet"
GOLDEN = ROOT / "tests" / "fixtures" / "gauntlet-report"
CAPTURE = os.environ.get("GAUNTLET_REPORT_CAPTURE") == "1"
MACHINE_PREFIXES = ("GAUNTLET ", "ROUND ", "RECORD: ", "NEXT: ", "GAUNTLET: ", "  ")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _collection(tmp_path: Path) -> Path:
    root = tmp_path / "coll"
    shutil.copytree(FIXTURES / "collection", root)
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "fixture")
    return root


def _edit(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    assert old in text, (path, old)
    path.write_text(text.replace(old, new, 1))


UNBACKED = """owner: owner
invariants:
  always: []
  never:
    - id: alpha.never-guess
      test: checks/alpha-never-guess/{bad,good}
    - id: alpha.never-push
      test: checks/alpha-never-push/{bad,good}
"""


def _charter(coll: Path) -> Path:
    return coll / "skills" / "alpha" / "CHARTER.md"


#: Each fixture stop the owner can reach: the skill, the change that reaches
#: it, and the run's settings.
CASES: dict[str, tuple[str, Callable[[Path], None], dict[str, object]]] = {
    "no-charter": ("skills/beta", lambda c: None, {}),
    "draft-unbacked": ("skills/alpha", lambda c: _edit(_charter(c), "owner: owner\n", UNBACKED), {}),
    "contract-bad": ("skills/alpha", lambda c: _edit(_charter(c), "owner: owner\n", "owner: owner\nnot_a_field: 1\n"),
                     {}),
    "unapproved": ("skills/alpha", lambda c: _edit(_charter(c), "  approved: 2026-11-15\n", ""), {}),
    "inspect-errors": ("skills/alpha", lambda c: _edit(c / "skills" / "alpha" / "SKILL.md", "\n",
                                                       "\nRun `scripts/deleted-helper.sh` first.\n"), {}),
    "inspect-unknown": ("skills/alpha", lambda c: None, {"issue_states": None, "offline": True}),
    "findings-round3": ("skills/alpha", lambda c: None, {}),
}


def _run(tmp_path: Path, case: str, mode: str | None = None) -> tuple[int, list[str], Path]:
    skill, change, extra = CASES[case]
    coll = _collection(tmp_path)
    change(coll)
    settings: dict[str, object] = {"issue_states": coll / "issue-states.json", "repo": "example/gauntlet",
                                   "usage": [FIXTURES / "usage"]}
    settings.update(extra)
    if mode is not None:
        settings["output"] = mode
    lines: list[str] = []
    code = gauntlet.run(coll, skill, gauntlet.Options(**settings), out=lines.append)  # type: ignore[arg-type]
    return code, lines, coll


def _normal(lines: list[str], coll: Path) -> str:
    text = "\n".join(lines) + "\n"
    return text.replace(str(coll), "<COLL>")


def _golden(name: str, text: str) -> str:
    path = GOLDEN / name
    if CAPTURE:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return path.read_text()


def _machine(lines: list[str]) -> list[str]:
    """The machine part: from the GAUNTLET header line to the end."""
    start = next(i for i, line in enumerate(lines) if line.startswith("GAUNTLET ") and not line.startswith("GAUNTLET:"))
    return lines[start:]


@pytest.mark.parametrize("case", sorted(CASES))
def test_the_machine_lines_are_byte_identical_to_before(tmp_path: Path, case: str) -> None:
    """Captured from f29e3a3's engine, before #783: tests and `gauntlet
    verdict` read these lines, so the plain report must never change them."""
    _code, lines, coll = _run(tmp_path, case)
    assert _normal(_machine(lines), coll) == _golden(f"{case}.machine.txt", _normal(_machine(lines), coll))


# ------------------------------------------------------------ the plain report

def _plain(lines: list[str]) -> list[str]:
    return lines[: next(i for i, line in enumerate(lines) if line.startswith("GAUNTLET ")
                        and not line.startswith("GAUNTLET:"))]


def _rule_ids() -> set[str]:
    """Every internal rule id the report must not show: inspect's own rule
    names (asked of the real command) and the contract checks."""
    import json

    from skillc import gauntlet_report

    done = subprocess.run(["python", "-m", "skillc.cli", "inspect", str(FIXTURES / "collection"), "--offline",
                           "--json"], capture_output=True, text=True, check=False, cwd=ROOT)
    return set(json.loads(done.stdout)["rules"]) | set(gauntlet_report.RULE_WORDS) | {"rule-line"}


@pytest.mark.parametrize("case", sorted(CASES))
def test_each_stop_has_a_golden_plain_report(tmp_path: Path, case: str) -> None:
    _code, lines, coll = _run(tmp_path, case)
    text = _normal(_plain(lines), coll)
    assert text == _golden(f"{case}.plain.txt", text)


@pytest.mark.parametrize("case", sorted(CASES))
def test_every_round_has_four_parts_and_no_rule_id(tmp_path: Path, case: str) -> None:
    _code, lines, _coll = _run(tmp_path, case)
    plain = _plain(lines)
    rounds = [i for i, line in enumerate(plain) if re.match(r"Round \S", line)]
    assert rounds, plain
    for i in rounds:
        assert [plain[i + k].split(":")[0].strip() for k in range(1, 5)] == ["Checked", "Found", "Means", "Do next"]
    text = "\n".join(plain)
    leaked = sorted(r for r in _rule_ids() if re.search(rf"(?<![\w-]){re.escape(r)}(?![\w-])", text))
    assert leaked == [], f"rule ids in the plain report: {leaked}"


@pytest.mark.parametrize("case", sorted(CASES))
def test_the_stopping_rounds_do_next_names_a_command_or_file(tmp_path: Path, case: str) -> None:
    _code, lines, _coll = _run(tmp_path, case)
    plain = _plain(lines)
    do_next = [line for line in plain if line.startswith("  Do next:")][-1]
    assert _actionable(do_next), do_next


#: What counts as naming something to DO: a command in backticks (skillc, a
#: slash command, make, a flag) or a file path. Prose in backticks does not.
ACTIONABLE = re.compile(r"`(?:skillc |/[\w-]+|make |--[\w-]+)[^`]*`|(?<![\w`])[\w.-]+/[\w./-]+\.\w+|\b[\w-]+\.md\b")


def _actionable(line: str) -> bool:
    return bool(ACTIONABLE.search(line))


def test_the_actionability_check_refuses_prose_in_backticks() -> None:
    assert not _actionable("  Do next: `this is prose`")
    assert not _actionable("  Do next: nothing for this round")
    assert _actionable("  Do next: run `skillc contracts <COLL>`")
    assert _actionable("  Do next: fix line 2 of skills/alpha/SKILL.md")


def test_the_no_rule_id_scan_finds_one() -> None:
    """The scan above, on a planted id: it is not blind."""
    text = "Found: the charter fails clause-backed"
    assert sorted(r for r in _rule_ids() if re.search(rf"(?<![\w-]){re.escape(r)}(?![\w-])", text)) == \
        ["clause-backed"]


def test_charter_create_is_named_only_when_this_skillc_has_it(tmp_path: Path,
                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    real = gauntlet.available
    monkeypatch.setattr(gauntlet, "available",
                        lambda words, cwd: True if words == ["charter", "create"] else real(words, cwd))
    _code, lines, coll = _run(tmp_path, "no-charter")
    assert any(f"`/charter-create {coll} skills/beta`" in line for line in _plain(lines)), _plain(lines)
    monkeypatch.setattr(gauntlet, "available",
                        lambda words, cwd: False if words == ["charter", "create"] else real(words, cwd))
    _code, lines, _coll = _run(tmp_path / "again", "no-charter")
    plain = "\n".join(_plain(lines))
    assert "is not in this skillc yet" in plain and "`/charter-create /" not in plain


def test_an_unmapped_reason_shows_its_own_detail_never_other_advice(tmp_path: Path) -> None:
    from skillc import gauntlet_report

    coll = _collection(tmp_path)
    skill = gauntlet.resolve_skill(coll, "skills/alpha")
    odd = gauntlet.Result("2", "inspect", "UNKNOWN", "a reason nobody wrote advice for", proceed=False,
                          reason="brand-new-reason")
    text = gauntlet_report.render(skill, [odd], odd, draft=coll / "x", charter_create=False)
    assert "Found:   a reason nobody wrote advice for" in text
    assert "Do next: act on the ROUND 2 line below" in text
    for _f, _m, advice in gauntlet_report.TABLE.values():
        ctx = gauntlet_report.Ctx(skill, odd, coll / "x", False)
        try:
            other = advice(ctx)
        except (AttributeError, TypeError, KeyError):
            continue
        assert other not in text or other.startswith("act on"), other


def test_a_cached_rerun_reports_the_same(tmp_path: Path) -> None:
    """reason and facts come back from the host-local display cache."""
    skill, change, extra = CASES["draft-unbacked"]
    coll = _collection(tmp_path)
    change(coll)
    settings: dict[str, object] = {"issue_states": coll / "issue-states.json", "repo": "example/gauntlet",
                                   "usage": [FIXTURES / "usage"], **extra}
    first: list[str] = []
    gauntlet.run(coll, skill, gauntlet.Options(**settings), out=first.append)  # type: ignore[arg-type]
    second: list[str] = []
    gauntlet.run(coll, skill, gauntlet.Options(**settings), out=second.append)  # type: ignore[arg-type]
    assert any("(cached)" in line for line in second)
    assert _plain(second) == _plain(first)


@pytest.mark.parametrize("flag,plain,machine", [("--plain-only", True, False), ("--machine-only", False, True)])
def test_the_output_switches_print_only_their_part(tmp_path: Path, flag: str, plain: bool, machine: bool) -> None:
    coll = _collection(tmp_path)
    done = subprocess.run(["python", "-m", "skillc.cli", "gauntlet", "run", str(coll), "skills/alpha",
                           "--issue-states", str(coll / "issue-states.json"), "--repo", "example/gauntlet",
                           "--usage", str(FIXTURES / "usage"), flag], capture_output=True, text=True,
                          check=False, cwd=ROOT)
    assert ("Where it stands:" in done.stdout) is plain
    assert ("ROUND 0 usage:" in done.stdout) is machine
    assert done.returncode == gauntlet.EXIT_STOPPED


def test_a_cached_failure_without_display_data_never_reads_as_a_pass(tmp_path: Path) -> None:
    """The host-local display cache is gone (deleted, or the record moved
    hosts): the recorded FAIL shows its recorded detail, never the success
    wording."""
    skill, change, extra = CASES["draft-unbacked"]
    coll = _collection(tmp_path)
    change(coll)
    settings: dict[str, object] = {"issue_states": coll / "issue-states.json", "repo": "example/gauntlet",
                                   "usage": [FIXTURES / "usage"], **extra}
    gauntlet.run(coll, skill, gauntlet.Options(**settings), out=lambda _: None)  # type: ignore[arg-type]
    for display in (coll / ".skillc").rglob("*.json"):
        if display.name != gauntlet.RECORD_NAME:
            display.unlink()
    lines: list[str] = []
    gauntlet.run(coll, skill, gauntlet.Options(**settings), out=lines.append)  # type: ignore[arg-type]
    plain = "\n".join(_plain(lines))
    assert any("(cached)" in line for line in lines), "the round came from the record"
    assert "Round 1: fail" in plain and "Found:   contract BAD: clause-backed" in plain
    assert "the charter is valid" not in plain and "nothing for this round" not in plain.split("Round 1: fail")[1]


def test_a_list_of_test_paths_counts_as_tested(tmp_path: Path) -> None:
    """`test:` may be a list (#720): both paths exist, so the promise is tested."""
    coll = _collection(tmp_path)
    (coll / "README.md").write_text("x\n")
    (coll / "PLAN.md").write_text("x\n")
    charter = _charter(coll)
    _edit(charter, "owner: owner\n", "owner: owner\ninvariants:\n  always: []\n  never:\n"
                                      "    - id: alpha.never-x\n      test: [README.md, PLAN.md]\n")
    facts = gauntlet._charter_facts(charter, coll)
    assert facts["never"] == {"count": 1, "tested": 1}, facts


def test_plain_only_points_at_nothing_it_hides(tmp_path: Path) -> None:
    from skillc import gauntlet_report

    coll = _collection(tmp_path)
    skill = gauntlet.resolve_skill(coll, "skills/alpha")
    odd = gauntlet.Result("2", "inspect", "UNKNOWN", "a reason nobody wrote advice for", proceed=False,
                          reason="brand-new-reason")
    text = gauntlet_report.render(skill, [odd], odd, draft=coll / "x", charter_create=False, machine_follows=False)
    assert "line below" not in text and "machine lines follow" not in text
    assert "`skillc gauntlet run` without `--plain-only`" in text
