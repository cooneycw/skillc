"""The skill-gauntlet engine, part 1 (#754): `skillc gauntlet run`.

Every control here runs the REAL round commands (`usage report`, `contracts`,
`inspect`, `charter ...`) as subprocesses, the way the engine does. Only
`gauntlet.available` is replaced, and only where a test needs a command to be
absent or present regardless of this skillc. Each control is paired with the
input that makes it report the other verdict.
"""

from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from skillc import gauntlet

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "evals" / "subjects" / "gauntlet"
SKILL_MD = ROOT / ".claude" / "skills" / "skill-gauntlet" / "SKILL.md"
ENGINE = ROOT / "skillc" / "gauntlet.py"
SPECS = [ROOT / "docs" / "specs" / name for name in ("gauntlet.md", "inspect.md", "contracts.md")]
#: The skill's own size limit (#718 must-never 5: a gauntlet that outgrows a
#: fixed size is a finding against itself). It may be LOWERED; raising it is the
#: change this test exists to make visible.
WORD_BUDGET = 600
PLANTED = ("planted-session-7f3a91", "planted-stop-reason")
#: The round modules the engine must never import: it runs their commands.
ROUND_MODULES = {"usage", "charter", "charter_confirm", "contracts", "inspect", "decay", "checks", "exposure"}
CPP = Path.home() / "Projects" / "claude-power-pack"
CPP_PIN = "d5ef0a66912436925078184d1ec8e89cb40323e6"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def coll(tmp_path: Path) -> Path:
    """The fixture collection, in a fresh git repository: the engine writes into it."""
    root = tmp_path / "coll"
    shutil.copytree(FIXTURES / "collection", root)
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "fixture")
    return root


def _run(collection: Path, skill: str, **changes: Any) -> tuple[int, list[str]]:
    settings: dict[str, Any] = {"issue_states": collection / "issue-states.json", "repo": "example/gauntlet",
                                "usage": [FIXTURES / "usage"]}
    settings.update(changes)
    lines: list[str] = []
    code = gauntlet.run(collection, skill, gauntlet.Options(**settings), out=lines.append)
    return code, lines


def _rounds(lines: list[str]) -> dict[str, str]:
    """ROUND <key> <name>: <rest> -> {key: rest}."""
    return {m.group(1): m.group(2) for m in (re.match(r"ROUND (\S+) \S+: (.*)$", line) for line in lines) if m}


def _absent(*commands: tuple[str, ...]):
    """`available`, with the named commands absent and every other one asked for real."""
    real = gauntlet.available

    def fake(words: list[str], cwd: Path) -> bool:
        return False if tuple(words) in commands else real(words, cwd)
    return fake


def _present(*commands: tuple[str, ...]):
    real = gauntlet.available

    def fake(words: list[str], cwd: Path) -> bool:
        return True if tuple(words) in commands else real(words, cwd)
    return fake


# ------------------------------------------------------------ the run's shape

def test_a_charted_skill_runs_rounds_0_to_2_and_stops_at_round_3_not_built(
        coll: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gauntlet, "available", _absent(("gauntlet", "round3")))
    code, lines = _run(coll, "skills/alpha")
    rounds = _rounds(lines)
    assert list(rounds) == ["0", "1", "1-overlap", "2", "3"]
    assert rounds["0"].startswith("OBSERVED") and rounds["1"].startswith("PASS")
    assert rounds["2"].startswith("PASS") and "D=1" in rounds["2"]
    assert any("D skills/alpha/SKILL.md:7 expired-marker" in line for line in lines)
    assert rounds["3"].startswith("NOT BUILT")
    assert lines[-1] == f"GAUNTLET: stopped at round 3 (NOT BUILT) - {gauntlet.NOT_A_VERDICT}"
    assert code == gauntlet.EXIT_STOPPED


@pytest.mark.parametrize("skill", ["skills/alpha", "skills/beta"])
def test_every_run_prints_exactly_one_next_line(coll: Path, skill: str) -> None:
    _, lines = _run(coll, skill)
    assert sum(line.startswith("NEXT:") for line in lines) == 1


@pytest.mark.parametrize("skill", ["skills/alpha", "skills/beta"])
def test_exit_0_is_unreachable_in_part_1_even_with_every_command_present(coll: Path, skill: str,
                                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    for available in (gauntlet.available, _present(("gauntlet", "round3"))):
        monkeypatch.setattr(gauntlet, "available", available)
        code, lines = _run(coll, skill)
        assert code != 0, lines
        assert gauntlet.NOT_A_VERDICT in lines[-1]


def test_round_3_never_passes_even_when_its_command_exists(coll: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The unbuilt-round control: with round 3 absent it reads NOT BUILT; with it
    present it reads NOT RUN. Neither proceeds, so neither is ever a pass."""
    monkeypatch.setattr(gauntlet, "available", _absent(("gauntlet", "round3")))
    _, absent = _run(coll, "skills/alpha")
    assert _rounds(absent)["3"].startswith("NOT BUILT")
    monkeypatch.setattr(gauntlet, "available", _present(("gauntlet", "round3")))
    code, present = _run(coll, "skills/alpha")
    assert _rounds(present)["3"].startswith("NOT RUN") and code == gauntlet.EXIT_STOPPED


def test_an_absent_command_reads_not_built_and_stops_there(coll: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gauntlet, "available", _absent(("charter", "draft")))
    code, lines = _run(coll, "skills/beta")
    rounds = _rounds(lines)
    assert list(rounds) == ["0", "1"] and rounds["1"].startswith("NOT BUILT")
    assert code == gauntlet.EXIT_STOPPED


def test_no_usage_log_reads_unknown_and_the_run_continues(coll: Path) -> None:
    _, lines = _run(coll, "skills/alpha", usage=[])
    rounds = _rounds(lines)
    assert rounds["0"].startswith("UNKNOWN - no usage log found")
    assert "1" in rounds  # continued: round 1 reads missing usage itself


def test_the_collections_own_usage_log_is_found_without_being_named(coll: Path) -> None:
    (coll / ".skillc").mkdir()
    shutil.copy(FIXTURES / "usage" / "usage.jsonl", coll / ".skillc" / "usage.jsonl")
    skill = gauntlet.resolve_skill(coll, "skills/alpha")
    assert gauntlet.discover_usage(skill, gauntlet.Options()) == [coll / ".skillc" / "usage.jsonl"]
    _, lines = _run(coll, "skills/alpha", usage=[])
    assert _rounds(lines)["0"].startswith("OBSERVED")


def test_no_charter_stops_at_round_1_with_a_draft_ready_and_writes_nothing_beside_the_skill(coll: Path) -> None:
    """The no-charter control. It needs `skillc charter draft` (#726, PR #755):
    #754 merges after it, so this fails, loudly, on a skillc without it."""
    assert gauntlet.available(["charter", "draft"], ROOT), "needs #726's `skillc charter draft` (PR #755) on main"
    code, lines = _run(coll, "skills/beta")
    rounds = _rounds(lines)
    assert list(rounds) == ["0", "1"], "no later round's verdict after a stop at round 1"
    assert rounds["1"] == "STOP - no CHARTER.md - draft ready for owner confirmation"
    draft = coll / ".skillc" / "gauntlet" / "skills__beta" / gauntlet.DRAFT_NAME
    assert draft.is_file()
    assert sorted(p.name for p in (coll / "skills" / "beta").iterdir()) == ["SKILL.md"]
    assert any(line.startswith("NEXT:") and "charter confirm" in line for line in lines)
    assert code == gauntlet.EXIT_STOPPED


def test_an_unapproved_charter_stops_round_1_and_an_approved_one_passes(coll: Path) -> None:
    charter = coll / "skills" / "alpha" / "CHARTER.md"
    charter.write_text(charter.read_text().replace("  approved: 2026-11-15\n", ""))
    code, lines = _run(coll, "skills/alpha")
    assert _rounds(lines)["1"].startswith("STOP - the charter has an intent or authority clause")
    assert list(_rounds(lines)) == ["0", "1"] and code == gauntlet.EXIT_STOPPED


def test_a_bad_contract_fails_round_1_with_exit_1(coll: Path) -> None:
    charter = coll / "skills" / "alpha" / "CHARTER.md"
    charter.write_text(charter.read_text().replace("owner: owner\n", "owner: owner\nnot_a_field: 1\n"))
    code, lines = _run(coll, "skills/alpha")
    assert _rounds(lines)["1"].startswith("FAIL - contract BAD") and code == gauntlet.EXIT_FAILED


def test_an_error_finding_on_the_skill_fails_round_2(coll: Path) -> None:
    skill = coll / "skills" / "alpha" / "SKILL.md"
    skill.write_text(skill.read_text() + "\nRun `scripts/deleted-helper.sh` first.\n")
    code, lines = _run(coll, "skills/alpha")
    assert _rounds(lines)["2"].startswith("FAIL") and code == gauntlet.EXIT_FAILED


def test_an_unreadable_issue_state_on_the_skill_is_unknown_never_a_pass(coll: Path) -> None:
    code, lines = _run(coll, "skills/alpha", issue_states=None, offline=True)
    assert _rounds(lines)["2"].startswith("UNKNOWN") and code == gauntlet.EXIT_STOPPED


# ------------------------------------------------------------------- resume

def _spy(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    calls: list[list[str]] = []
    real = gauntlet._skillc

    def spy(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        if "--help" not in args:
            calls.append(list(args))
        return real(args, cwd)
    monkeypatch.setattr(gauntlet, "_skillc", spy)
    return calls


def test_an_unchanged_rerun_runs_nothing_and_leaves_the_record_byte_identical(
        coll: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _spy(monkeypatch)
    _run(coll, "skills/alpha")
    record = coll / "skills" / "alpha" / gauntlet.RECORD_NAME
    first, ran = record.read_bytes(), len(calls)
    assert ran > 0
    _, lines = _run(coll, "skills/alpha")
    assert len(calls) == ran, "a re-run with unchanged inputs ran a round command"
    assert all(line.endswith("(cached)") for line in lines if line.startswith("ROUND"))
    assert record.read_bytes() == first
    assert any(line.startswith("RECORD:") and "unchanged" in line for line in lines)


def test_editing_skill_md_reruns_rounds_1_and_2_but_not_round_0(coll: Path) -> None:
    _run(coll, "skills/alpha")
    skill = coll / "skills" / "alpha" / "SKILL.md"
    skill.write_text(skill.read_text() + "\nReport the result.\n")
    _, lines = _run(coll, "skills/alpha")
    cached = {k: v.endswith("(cached)") for k, v in _rounds(lines).items()}
    assert cached["0"] and not cached["1"] and not cached["2"]


def test_a_tampered_input_digest_reruns_that_round(coll: Path) -> None:
    """The resume control's own red: the cache keys on the recorded inputs, so a
    record whose digest no longer matches re-runs the round."""
    _run(coll, "skills/alpha")
    record = coll / "skills" / "alpha" / gauntlet.RECORD_NAME
    data = json.loads(record.read_text())
    data["rounds"]["2"]["inputs"]["skill"] = "sha256:" + "0" * 64
    record.write_text(json.dumps(data))
    _, lines = _run(coll, "skills/alpha")
    rounds = _rounds(lines)
    assert not rounds["2"].endswith("(cached)") and rounds["1"].endswith("(cached)")


# ------------------------------------------------------------------- record

def _leaks(text: str, host_paths: list[Path]) -> list[str]:
    found = [p for p in PLANTED if p in text]
    found += [str(p) for p in host_paths if str(p) in text]
    found += re.findall(r"/home/[^\"\s]+|/Users/[^\"\s]+", text)
    found += re.findall(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", text)
    return found


def test_the_leak_scan_can_find_each_kind_of_leak() -> None:
    """Negative control for the publish-safety scan below: it is not blind."""
    home = Path.home()
    assert _leaks("x planted-session-7f3a91 x", [])
    assert _leaks(f'"{home}/data"', [home])
    assert _leaks('"/' + 'home/someone/x"', [])  # split, so the repository's own leak-check does not read it
    assert _leaks('"2026-11-15T10:01:00Z"', [])
    assert _leaks('{"verdict": "PASS"}', [home]) == []


def test_the_record_holds_digests_and_verdicts_only(coll: Path, tmp_path: Path) -> None:
    _run(coll, "skills/alpha")
    text = (coll / "skills" / "alpha" / gauntlet.RECORD_NAME).read_text()
    assert _leaks(text, [Path.home(), tmp_path, ROOT]) == []
    data = json.loads(text)
    assert set(data) == {"kind", "schema", "skill", "rounds"}
    for entry in data["rounds"].values():
        assert set(entry) == {"name", "verdict", "detail", "proceed", "inputs"}
        assert all(v == "none" or v.startswith("sha256:") or v in ("available", "absent") or k == "options"
                   for k, v in entry["inputs"].items())


def test_the_record_is_deterministic(coll: Path) -> None:
    _run(coll, "skills/alpha")
    text = (coll / "skills" / "alpha" / gauntlet.RECORD_NAME).read_text()
    assert text == json.dumps(json.loads(text), indent=2, sort_keys=True) + "\n"


def test_the_draft_location_is_the_main_checkout_from_a_linked_worktree(
        coll: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gauntlet, "available", _absent(("charter", "draft")))
    worktree = tmp_path / "wt"
    _git(coll, "worktree", "add", "-q", str(worktree))
    for collection in (coll, worktree):
        _run(collection, "skills/beta", issue_states=None)
        assert (coll / ".skillc" / "gauntlet" / "skills__beta" / gauntlet.RECORD_NAME).is_file()
        assert not (worktree / ".skillc").exists()
    assert (coll / ".skillc" / ".gitignore").read_text() == "*\n"


def test_the_engine_never_stages_or_commits_the_record(coll: Path) -> None:
    _run(coll, "skills/alpha")
    status = subprocess.run(["git", "-C", str(coll), "status", "--porcelain"], capture_output=True, text=True,
                            check=True).stdout
    assert status == f"?? skills/alpha/{gauntlet.RECORD_NAME}\n"


# --------------------------------------------------------- orchestration only

def _round_imports(source: str) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            names = [f"{base}.{a.name}" if base else a.name for a in node.names] + [base]
        else:
            continue
        found |= {part for name in names for part in name.split(".") if part in ROUND_MODULES}
    return found


def test_the_engine_imports_no_round_module() -> None:
    assert _round_imports(ENGINE.read_text()) == set()


def test_the_import_check_finds_a_round_import() -> None:
    bad = "from skillc import inspect\nfrom . import contracts\nimport skillc.usage\nfrom .charter import x\n"
    assert _round_imports(bad) == {"inspect", "contracts", "usage", "charter"}


def _copied_passages(tmp_path: Path, skill_text: str) -> list[dict[str, Any]]:
    root = tmp_path / "copies"
    (root / "skill").mkdir(parents=True)
    (root / "skill" / "SKILL.md").write_text(skill_text)
    for spec in SPECS:
        (root / "specs").mkdir(exist_ok=True)
        shutil.copy(spec, root / "specs" / spec.name)
    done = subprocess.run(["python", "-m", "skillc.cli", "inspect", str(root), "--include", "**/*.md",
                           "--offline", "--json"], capture_output=True, text=True, check=False, cwd=ROOT)
    report = json.loads(done.stdout)
    assert report["rules"]["copied-passage"]["examined"]
    return [f for f in report["findings"] if f["rule"] == "copied-passage"
            and "skill/SKILL.md" in (f["path"], f.get("detail", ""))]


def test_the_skill_text_copies_no_passage_from_the_round_specs(tmp_path: Path) -> None:
    assert _copied_passages(tmp_path, SKILL_MD.read_text()) == []


def test_the_copied_passage_check_finds_a_pasted_paragraph(tmp_path: Path) -> None:
    inspect_spec = (ROOT / "docs" / "specs" / "inspect.md").read_text()
    paragraph = inspect_spec[inspect_spec.index("**Examines.**"):inspect_spec.index("**N = 40**")]
    assert _copied_passages(tmp_path, SKILL_MD.read_text() + "\n" + paragraph) != []


# ---------------------------------------------------------------- the skill

def _body_words(text: str) -> int:
    return len(text.split("---", 2)[2].split())


def test_the_skill_stays_inside_its_word_budget() -> None:
    assert _body_words(SKILL_MD.read_text()) <= WORD_BUDGET


def test_the_word_budget_fails_one_word_over() -> None:
    over = "---\nname: x\n---\n" + "word " * (WORD_BUDGET + 1)
    assert _body_words(over) > WORD_BUDGET


def test_the_skill_says_part_1_never_gives_a_verdict() -> None:
    text = SKILL_MD.read_text()
    assert "never exits 0" in text and "keep, trim or retire" in text


# ---------------------------------------------------------- purpose control

def test_on_cpp_flow_wave_at_d5ef0a66_round_2_surfaces_the_closed_rules_as_d(tmp_path: Path) -> None:
    """#754's purpose control, as revised at the gate (option a): #635, #699 and
    #788 surface as D, and #640 does not - inspect's documented miss
    (docs/measurements/inspect/2026-11-14-cpp-and-mattpocock.md). Host-only."""
    if not (CPP / ".git").exists() or subprocess.run(["git", "-C", str(CPP), "cat-file", "-e", CPP_PIN],
                                                     capture_output=True, check=False).returncode != 0:
        pytest.skip(f"CPP CHECKOUT ABSENT: {CPP} at {CPP_PIN[:8]} is not on this host; the purpose control did not run")
    export = tmp_path / "cpp"
    export.mkdir()
    archive = subprocess.run(["git", "-C", str(CPP), "archive", CPP_PIN], capture_output=True, check=True)
    subprocess.run(["tar", "-x", "-C", str(export)], input=archive.stdout, check=True)
    shutil.copytree(FIXTURES / "cpp-d5ef0a66" / "charters", export / "charters")
    options = gauntlet.Options(
        offline=True, issue_states=FIXTURES / "cpp-d5ef0a66" / "issue-states.json", repo="cooneycw/claude-power-pack",
        include=[".claude/commands/**/*.md", ".claude/skills/*/SKILL.md"],
        maps=["~/.claude/scripts/=scripts/", "~/.claude/commands/=.claude/commands/"])
    lines: list[str] = []
    code = gauntlet.run(export, ".claude/commands/flow/wave.md", options, out=lines.append)
    rounds = _rounds(lines)
    assert rounds["1"].startswith("PASS"), lines
    d_items = [line for line in lines if line.startswith("  D .claude/commands/flow/wave.md:")]
    for issue in ("#635", "#699", "#788"):
        assert any(issue in line for line in d_items), (issue, d_items)
    assert not any("#640" in line for line in d_items)
    # Round 3 reads NOT BUILT, or NOT RUN once #736 PR 1's `gauntlet round3` is in this skillc; never a pass.
    assert rounds["3"].startswith(("NOT BUILT", "NOT RUN")) and code == gauntlet.EXIT_STOPPED


# ------------------------------------- counter-model review pass 1 (Codex), each a red

def test_a_symlinked_record_is_refused_and_the_skill_is_untouched(coll: Path) -> None:
    skill = coll / "skills" / "alpha" / "SKILL.md"
    before = skill.read_bytes()
    (coll / "skills" / "alpha" / gauntlet.RECORD_NAME).symlink_to("SKILL.md")
    code, _ = _run(coll, "skills/alpha")
    assert code == gauntlet.EXIT_USAGE and skill.read_bytes() == before


def test_an_absolute_option_path_never_reaches_the_record(coll: Path, tmp_path: Path) -> None:
    private = tmp_path / "private-map-target"
    _run(coll, "skills/alpha", maps=[f"{private}/=scripts/"], include=["**/SKILL.md"])
    text = (coll / "skills" / "alpha" / gauntlet.RECORD_NAME).read_text()
    assert str(private) not in text and _leaks(text, [tmp_path]) == []


def test_an_unapproved_charter_under_a_spaced_directory_still_stops(coll: Path) -> None:
    spaced = coll / "skills" / "my alpha"
    shutil.copytree(coll / "skills" / "alpha", spaced)
    (spaced / "SKILL.md").write_text((spaced / "SKILL.md").read_text().replace("name: alpha", "name: my-alpha"))
    charter = spaced / "CHARTER.md"
    charter.write_text(charter.read_text().replace("contract: alpha", "contract: my-alpha")
                       .replace("  approved: 2026-11-15\n", ""))
    _, lines = _run(coll, "skills/my alpha")
    assert _rounds(lines)["1"].startswith("STOP - the charter has an intent or authority clause"), lines


def test_round_2_inspects_the_selected_skill_even_outside_the_given_surface(coll: Path) -> None:
    _, lines = _run(coll, "skills/alpha", include=["skills/beta/SKILL.md"])
    assert any(line.startswith("  D skills/alpha/SKILL.md:7") for line in lines)


def test_an_exclude_that_drops_the_skill_is_unknown_not_a_clean_round_2(coll: Path) -> None:
    code, lines = _run(coll, "skills/alpha", exclude=["skills/alpha/*"])
    assert _rounds(lines)["2"].startswith("UNKNOWN - an --exclude drops this skill") and code == gauntlet.EXIT_STOPPED


def test_an_exclude_inspect_does_not_apply_to_the_skill_keeps_it_inspected(coll: Path) -> None:
    """Codex pass 2: membership is inspect's own answer, not a re-implemented
    matcher. In inspect a `*` does not cross `/`, so `skills/*` drops nothing."""
    _, lines = _run(coll, "skills/alpha", exclude=["skills/*"])
    assert _rounds(lines)["2"].startswith("PASS"), lines


def test_a_neighbours_broken_contract_makes_round_1_unknown_not_pass(coll: Path) -> None:
    gamma = coll / "skills" / "gamma"
    gamma.mkdir()
    (gamma / "SKILL.md").write_text("---\nname: gamma\ndescription: Use for the gamma fixture.\n---\nReport.\n")
    (gamma / "CHARTER.md").write_text("---\ncontract: gamma\nversion: 1\nnot_a_field: 1\n---\n")
    code, lines = _run(coll, "skills/alpha")
    assert _rounds(lines)["1"].startswith("UNKNOWN - `skillc contracts` says its hand-off rules did NOT run")
    assert code == gauntlet.EXIT_STOPPED


@pytest.mark.parametrize("change", ["alias", "file"])
def test_round_1_reruns_when_an_alias_or_any_collection_file_changes(coll: Path, change: str) -> None:
    _run(coll, "skills/alpha")
    if change == "alias":
        _, lines = _run(coll, "skills/alpha", aliases=["alpha-old"])
    else:
        (coll / "checks").mkdir()
        (coll / "checks" / "added.txt").write_text("a declared test path appeared\n")
        _, lines = _run(coll, "skills/alpha")
    assert not _rounds(lines)["1"].endswith("(cached)")


def test_round_2_reading_live_issue_states_is_never_served_from_cache(coll: Path) -> None:
    _run(coll, "skills/alpha", issue_states=None)
    _, lines = _run(coll, "skills/alpha", issue_states=None)
    assert not _rounds(lines)["2"].endswith("(cached)")
    _run(coll, "skills/alpha")
    _, again = _run(coll, "skills/alpha")
    assert _rounds(again)["2"].endswith("(cached)"), "a frozen issue-state snapshot is cached"


def test_a_cached_round_2_shows_the_same_findings_as_a_fresh_one(coll: Path) -> None:
    _, fresh = _run(coll, "skills/alpha")
    _, cached = _run(coll, "skills/alpha")
    assert _rounds(cached)["2"].endswith("(cached)")
    assert [line for line in cached if line.startswith("  ")] == [line for line in fresh if line.startswith("  ")]


def test_an_unreadable_usage_log_is_unknown_and_the_run_continues(coll: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log = FIXTURES / "usage" / "usage.jsonl"
    real = Path.read_bytes

    def denied(self: Path) -> bytes:
        if self == log:
            raise PermissionError(13, "Permission denied", str(self))
        return real(self)
    monkeypatch.setattr(Path, "read_bytes", denied)
    code, lines = _run(coll, "skills/alpha")
    rounds = _rounds(lines)
    assert rounds["0"].startswith("UNKNOWN") and "1" in rounds and code != 0
    data = json.loads((coll / "skills" / "alpha" / gauntlet.RECORD_NAME).read_text())
    assert data["rounds"]["0"]["inputs"]["usage-1"] == "unreadable"


def test_the_skill_passes_skillc_check_for_the_claude_code_target() -> None:
    done = subprocess.run(["python", "-m", "skillc.cli", "check", "--target", "claude-code", str(SKILL_MD.parent)],
                          capture_output=True, text=True, check=False, cwd=ROOT)
    assert done.returncode == 0 and "0 error(s), 0 warning(s)" in done.stdout, done.stdout


# ------------------------------------- counter-model review pass 2 (Codex), each a red

def test_a_collection_holding_its_own_skillc_package_is_never_executed(coll: Path, tmp_path: Path) -> None:
    marker = tmp_path / "executed"
    (coll / "skillc").mkdir()
    (coll / "skillc" / "__init__.py").write_text("")
    (coll / "skillc" / "cli.py").write_text(f"open({str(marker)!r}, 'w').write('ran')\n")
    _run(coll, "skills/alpha")
    assert not marker.exists(), "the round subprocess imported the collection's own skillc"


def test_a_symlinked_state_directory_is_refused_and_nothing_is_written_through_it(
        coll: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gauntlet, "available", _absent(("charter", "draft")))
    outside = tmp_path / "outside"
    outside.mkdir()
    (coll / ".skillc").symlink_to(outside, target_is_directory=True)
    code, _ = _run(coll, "skills/beta")
    assert code == gauntlet.EXIT_USAGE and list(outside.iterdir()) == []


def test_a_symlinked_skill_file_is_refused(coll: Path) -> None:
    target = coll / "skills" / "beta" / "real.md"
    (coll / "skills" / "beta" / "SKILL.md").rename(target)
    (coll / "skills" / "beta" / "SKILL.md").symlink_to("real.md")
    code, _ = _run(coll, "skills/beta")
    assert code == gauntlet.EXIT_USAGE


def test_round_2_keeps_the_skills_classified_rule_statements(coll: Path) -> None:
    _, lines = _run(coll, "skills/alpha")
    assert any(line.startswith("  rule UNSORTED skills/alpha/SKILL.md:5") for line in lines), lines
    assert "rule statements UNSORTED=1" in _rounds(lines)["2"]


def test_another_skillc_implementation_reruns_every_round(coll: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _run(coll, "skills/alpha")
    monkeypatch.setattr(gauntlet, "_IMPLEMENTATION", "sha256:" + "1" * 64)
    _, lines = _run(coll, "skills/alpha")
    assert not any(v.endswith("(cached)") for v in _rounds(lines).values())


def test_the_tree_digest_sees_a_retargeted_link_and_a_removed_empty_directory(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    (root / "checks" / "empty").mkdir(parents=True)
    (root / "a.txt").write_text("a")
    (root / "link").symlink_to("a.txt")
    before = gauntlet._tree_digest(root)
    (root / "link").unlink()
    (root / "link").symlink_to("missing.txt")
    retargeted = gauntlet._tree_digest(root)
    (root / "checks" / "empty").rmdir()
    assert len({before, retargeted, gauntlet._tree_digest(root)}) == 3


# ------------------------- #759 (pass-3 HIGH, folded in by orchestrator ruling), red first

def _command_collection(root: Path, charter_dir: Path) -> None:
    (root / ".claude" / "commands" / "flow").mkdir(parents=True)
    (root / ".claude" / "commands" / "flow" / "wave.md").write_text("Drive the wave. Report, then stop.\n")
    charter_dir.mkdir(parents=True, exist_ok=True)
    (charter_dir / "CHARTER.md").write_text(
        "---\ncontract: flow-wave\nversion: 1\nsubject: .claude/commands/flow/wave.md\nintent:\n  id: wave.intent\n"
        "  what: Drive the wave.\n  approved: 2026-11-15\npurpose: fixture\nowner: owner\n---\n")


def test_a_symlinked_command_charter_dir_never_gets_a_record_outside(tmp_path: Path) -> None:
    """#759's exact input: charters/flow/wave -> a directory outside the collection."""
    root, outside = tmp_path / "coll", tmp_path / "outside"
    _command_collection(root, outside)
    (root / "charters" / "flow").mkdir(parents=True)
    (root / "charters" / "flow" / "wave").symlink_to(outside, target_is_directory=True)
    code = gauntlet.run(root, ".claude/commands/flow/wave.md", gauntlet.Options(offline=True), out=lambda _: None)
    assert not (outside / gauntlet.RECORD_NAME).exists()
    assert code == gauntlet.EXIT_USAGE


def test_a_symlinked_native_skill_dir_is_refused(coll: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside-skill"
    shutil.copytree(coll / "skills" / "alpha", outside)
    (coll / "skills" / "linked").symlink_to(outside, target_is_directory=True)
    code, _ = _run(coll, "skills/linked")
    assert code == gauntlet.EXIT_USAGE and not (outside / gauntlet.RECORD_NAME).exists()


def test_a_symlinked_charters_root_is_refused(tmp_path: Path) -> None:
    root, outside = tmp_path / "coll", tmp_path / "outside"
    _command_collection(root, outside / "flow" / "wave")
    (root / "charters").symlink_to(outside, target_is_directory=True)
    code = gauntlet.run(root, ".claude/commands/flow/wave.md", gauntlet.Options(offline=True), out=lambda _: None)
    assert code == gauntlet.EXIT_USAGE and not (outside / "flow" / "wave" / gauntlet.RECORD_NAME).exists()


def test_a_plain_command_charter_dir_still_gets_its_record(tmp_path: Path) -> None:
    """The negative control: without a link, the record lands beside the charter."""
    root = tmp_path / "coll"
    _command_collection(root, root / "charters" / "flow" / "wave")
    gauntlet.run(root, ".claude/commands/flow/wave.md", gauntlet.Options(offline=True), out=lambda _: None)
    assert (root / "charters" / "flow" / "wave" / gauntlet.RECORD_NAME).is_file()


def test_a_symlinked_draft_dir_is_refused_and_nothing_lands_where_it_points(
        coll: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """#759, the scoped check's remaining path (orchestrator ruling b): an
    explicit --draft-dir that is itself a symlink, or holds one below it."""
    monkeypatch.setattr(gauntlet, "available", _absent(("charter", "draft")))
    outside = tmp_path / "outside-drafts"
    outside.mkdir()
    (tmp_path / "drafts-link").symlink_to(outside, target_is_directory=True)
    code, _ = _run(coll, "skills/beta", draft_dir=tmp_path / "drafts-link")
    assert code == gauntlet.EXIT_USAGE and list(outside.iterdir()) == []
    real = tmp_path / "drafts-real"
    real.mkdir()
    (real / "skills__beta").symlink_to(outside, target_is_directory=True)
    code, _ = _run(coll, "skills/beta", draft_dir=real)
    assert code == gauntlet.EXIT_USAGE and list(outside.iterdir()) == []


def test_a_plain_draft_dir_gets_the_record(coll: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The negative control for the refusal above."""
    monkeypatch.setattr(gauntlet, "available", _absent(("charter", "draft")))
    drafts = tmp_path / "drafts"
    code, _ = _run(coll, "skills/beta", draft_dir=drafts)
    assert code == gauntlet.EXIT_STOPPED and (drafts / "skills__beta" / gauntlet.RECORD_NAME).is_file()


def test_state_files_are_never_written_through_a_link(coll: Path, tmp_path: Path,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gauntlet, "available", _absent(("charter", "draft")))
    victim = tmp_path / "victim.txt"
    victim.write_text("keep me\n")
    drafts = tmp_path / "drafts"
    (drafts / "skills__beta").mkdir(parents=True)
    (drafts / "skills__beta" / "display.json").symlink_to(victim)
    code, _ = _run(coll, "skills/beta", draft_dir=drafts)
    assert victim.read_text() == "keep me\n" and code == gauntlet.EXIT_USAGE
