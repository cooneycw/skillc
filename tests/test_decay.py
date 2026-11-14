"""The decay rules (issue #725): each one's population, its UNKNOWN handling,
and the cases that show what it can and cannot say."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from skillc import checks, cli, decay

CONTROLS = Path(__file__).resolve().parent.parent / "controls"


def _skill(root: Path, name: str, body: str) -> Path:
    path = root / "skills" / name / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nname: {name}\ndescription: Use when testing.\n---\n{body}", encoding="utf-8")
    return path


def _load(root: Path, **kw: object) -> decay.Collection:
    kw.setdefault("offline", True)
    return decay.load(root, **kw)  # type: ignore[arg-type]


# ------------------------------------------------------------ the collection

def test_default_surface_is_every_skill_md_including_the_root(tmp_path: Path) -> None:
    (tmp_path / "SKILL.md").write_text("---\nname: x\ndescription: d\n---\nbody\n", encoding="utf-8")
    _skill(tmp_path, "a", "body\n")
    assert [s.rel for s in _load(tmp_path).subjects] == ["SKILL.md", "skills/a/SKILL.md"]


def test_cpp_style_surface_reads_commands_and_drops_generated_mirrors(tmp_path: Path) -> None:
    for rel in (".claude/commands/flow/auto.md", ".claude/skills/x/SKILL.md", "codex/skills/flow-auto/SKILL.md"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("text\n", encoding="utf-8")
    coll = _load(tmp_path, include=[".claude/commands/**/*.md", ".claude/skills/*/SKILL.md", "**/SKILL.md"],
                 exclude=["codex/skills/**"])
    assert [s.rel for s in coll.subjects] == [".claude/commands/flow/auto.md", ".claude/skills/x/SKILL.md"]
    assert coll.excluded_count == 1


def test_unparseable_frontmatter_is_kept_as_body_never_dropped(tmp_path: Path) -> None:
    (tmp_path / "cmd.md").write_text("---\n: : bad\n---\nuntil #4 lands\n", encoding="utf-8")
    coll = _load(tmp_path, include=["*.md"], repo="o/r", issue_states={"o/r#4": "CLOSED"})
    assert "until #4" in coll.subjects[0].body
    assert decay.expired_marker(coll).hits


def test_parsed_frontmatter_keeps_true_line_numbers(tmp_path: Path) -> None:
    _skill(tmp_path, "a", "one\ntwo\nuntil #4 lands\n")
    coll = _load(tmp_path, repo="o/r", issue_states={"o/r#4": "CLOSED"})
    assert decay.expired_marker(coll).hits[0].line == 7


# ------------------------------------------------------------ dangling-reference

def test_exact_paths_only_never_a_substring(tmp_path: Path) -> None:
    _skill(tmp_path, "a", "Run `scripts/helper.sh` now.\n")
    (tmp_path / "skills" / "a" / "scripts").mkdir()
    (tmp_path / "skills" / "a" / "scripts" / "helper.sh.bak").write_text("x", encoding="utf-8")
    assert decay.dangling_reference(_load(tmp_path)).hits, "a neighbour's name must not satisfy the reference"


def test_collection_root_resolves_a_reference_the_skill_dir_does_not(tmp_path: Path) -> None:
    _skill(tmp_path, "a", "Run `scripts/shared.sh` now.\n")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "shared.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    assert not decay.dangling_reference(_load(tmp_path)).hits


def test_a_mapped_install_prefix_resolves_and_an_unmapped_one_is_out_of_population(tmp_path: Path) -> None:
    _skill(tmp_path, "a", "```bash\n~/.claude/scripts/gone.sh\n~/.codex/skills/x/run.py\n```\n")
    result = decay.dangling_reference(_load(tmp_path, maps=[("~/.claude/scripts/", "scripts/")]))
    assert [h.data["reference"] for h in result.hits] == ["~/.claude/scripts/gone.sh"]
    assert result.population["path_like_not_examined"] == 1


def test_a_reference_cannot_escape_the_collection(tmp_path: Path) -> None:
    inner = tmp_path / "coll"
    _skill(inner, "a", "Run `scripts/../../../outside.sh`.\n")
    (tmp_path / "outside.sh").write_text("x", encoding="utf-8")
    assert decay.dangling_reference(_load(inner)).hits


def test_placeholders_globs_and_extensionless_names_are_counted_not_fired(tmp_path: Path) -> None:
    _skill(tmp_path, "a", "`scripts/<name>.sh`, `scripts/*.sh`, `${ROOT}/scripts/x.sh`, `scripts/foo`\n")
    result = decay.dangling_reference(_load(tmp_path))
    assert not result.hits
    assert result.population["placeholder_paths_not_examined"] == 3


def test_flag_checked_against_the_script_and_a_wrapped_sibling(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "tool.sh").write_text('#!/bin/sh\npython3 "$(dirname "$0")/tool.py" "$@"\n', encoding="utf-8")
    (scripts / "tool.py").write_text('p.add_argument("--json")\n', encoding="utf-8")
    _skill(tmp_path, "a", "Run `scripts/tool.sh --json` then `scripts/tool.sh --yaml`.\n")
    hits = decay.dangling_reference(_load(tmp_path)).hits
    assert [h.data["reference"] for h in hits] == ["scripts/tool.sh --yaml"]


def test_a_flag_inside_a_subshell_belongs_to_that_command(tmp_path: Path) -> None:
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "ci.sh").write_text("--path\n", encoding="utf-8")
    _skill(tmp_path, "a", '```bash\nscripts/ci.sh --path "$(git rev-parse --show-toplevel)"\n```\n')
    assert not decay.dangling_reference(_load(tmp_path)).hits


def test_a_dead_relative_link_fires_and_a_live_one_does_not(tmp_path: Path) -> None:
    _skill(tmp_path, "a", "[ok](../../README.md) and [gone](../../docs/missing.md) and [web](https://x.y/z.md)\n")
    (tmp_path / "README.md").write_text("x", encoding="utf-8")
    hits = decay.dangling_reference(_load(tmp_path)).hits
    assert [h.data["reference"] for h in hits] == ["../../docs/missing.md"]


# ------------------------------------------------------------ expired-marker

def test_marker_forms(tmp_path: Path) -> None:
    _skill(tmp_path, "a", "until #1 lands\nUntil other/repo#2\n<!-- expires-with: #3 -->\nonce #4 lands\n")
    found = decay.markers(_load(tmp_path, repo="o/r"))
    assert [(m.kind, m.key) for m in found] == [
        ("until", "o/r#1"), ("until", "other/repo#2"), ("expires-with", "o/r#3"),
    ], "'once #4 lands' is a documented blind spot, not a marker"


def test_with_no_network_every_marker_is_UNKNOWN_and_the_run_is_not_clean(tmp_path: Path) -> None:
    """Acceptance: expired-marker with the network unavailable reports UNKNOWN
    for every marker, and the run summary does not say clean."""
    from skillc import inspect

    _skill(tmp_path, "a", "until #1 lands\n<!-- expires-with: #2 -->\n")
    _skill(tmp_path, "b", "plain text\n")

    def no_network(keys):  # type: ignore[no-untyped-def]
        return {}  # what gh_lookup yields when every call fails

    coll = decay.load(tmp_path, repo="o/r", offline=False)
    result = decay.resolve_states(coll, ["o/r#1", "o/r#2"], no_network)
    assert set(result.values()) == {decay.UNKNOWN}
    report = inspect.run(coll, lookup=no_network)
    assert report.data["counts"]["unknown"] == 2
    assert report.verdict == inspect.INCOMPLETE
    assert "NOT clean" in report.data["summary"] and "clean -" not in report.data["summary"]
    assert report.exit_code == 1


def test_gh_missing_is_UNKNOWN_never_OPEN(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(decay.shutil, "which", lambda _name: None)
    assert decay.gh_lookup(["o/r#1"]) == {"o/r#1": decay.UNKNOWN}


def test_a_failing_gh_is_UNKNOWN(monkeypatch: pytest.MonkeyPatch) -> None:
    class Proc:
        returncode = 1
        stdout = ""

    monkeypatch.setattr(decay.shutil, "which", lambda _name: "/usr/bin/gh")
    monkeypatch.setattr(decay.subprocess, "run", lambda *a, **k: Proc())
    assert decay.gh_lookup(["o/r#1"]) == {"o/r#1": decay.UNKNOWN}


def test_an_unknown_repository_is_UNKNOWN(tmp_path: Path) -> None:
    _skill(tmp_path, "a", "until #1 lands\n")
    result = decay.expired_marker(_load(tmp_path, issue_states={}))
    assert not result.hits and len(result.unknown) == 1


def test_a_bare_until_is_noted_as_prose_only_and_a_marked_one_is_not(tmp_path: Path) -> None:
    _skill(tmp_path, "a", "until #1 lands\n<!-- expires-with: #2 --> stagger runs\n")
    result = decay.expired_marker(_load(tmp_path, repo="o/r", issue_states={"o/r#1": "OPEN", "o/r#2": "OPEN"}))
    assert [n.data["issue"] for n in result.notes] == ["o/r#1"]
    assert not result.hits


def test_issue_state_fixture_is_validated(tmp_path: Path) -> None:
    bad = tmp_path / "s.json"
    bad.write_text(json.dumps({"o/r#1": "open"}), encoding="utf-8")
    with pytest.raises(decay.CollectionError):
        decay.read_issue_states(bad)


# ------------------------------------------------------------ copied-passage

WORDS = " ".join(f"w{i}" for i in range(60))


def test_a_rewrapped_copy_is_still_a_copy(tmp_path: Path) -> None:
    _skill(tmp_path, "a", WORDS + "\n")
    _skill(tmp_path, "b", "\n".join(WORDS.split()) + "\n")
    hits = decay.copied_passage(_load(tmp_path)).hits
    assert len(hits) == 1 and hits[0].data["longest_words"] == 60


def test_a_run_one_word_short_of_the_floor_does_not_fire(tmp_path: Path) -> None:
    run = " ".join(WORDS.split()[: decay.COPIED_MIN_WORDS - 1])
    _skill(tmp_path, "a", run + " alpha\n")
    _skill(tmp_path, "b", run + " beta\n")
    assert not decay.copied_passage(_load(tmp_path)).hits
    _skill(tmp_path, "b", run + " alpha\n")
    assert decay.copied_passage(_load(tmp_path)).hits


def test_one_subject_is_not_examined_rather_than_clean(tmp_path: Path) -> None:
    _skill(tmp_path, "a", WORDS + "\n")
    result = decay.copied_passage(_load(tmp_path))
    assert result.examined is False
    assert decay.not_exercised("copied-passage", result)


def test_two_separate_runs_with_one_pair_are_one_finding(tmp_path: Path) -> None:
    words = WORDS.split()
    _skill(tmp_path, "a", " ".join(words[:45]) + " X " + " ".join(f"v{i}" for i in range(45)) + "\n")
    _skill(tmp_path, "b", " ".join(words[:45]) + " Y " + " ".join(f"v{i}" for i in range(45)) + "\n")
    hits = decay.copied_passage(_load(tmp_path)).hits
    assert len(hits) == 1 and hits[0].data["runs"] == 2 and hits[0].data["shared_words"] == 90


# ------------------------------------------------------------ emphasis-density

def test_lowercase_and_partial_words_are_not_emphasis(tmp_path: Path) -> None:
    _skill(tmp_path, "a", "you must, Never, MUSTARD, ALWAYSON\n")
    assert decay.emphasis_lines(_load(tmp_path).subjects[0]) == []


def test_density_uses_the_floor_denominator(tmp_path: Path) -> None:
    _skill(tmp_path, "a", "MUST\nMUST\n")  # 2 per max(2, 50) lines = 4 per 100
    assert not decay.emphasis_density(_load(tmp_path)).hits
    _skill(tmp_path, "a", "MUST\nMUST\nMUST\n")  # 6 per 100, over 5
    assert decay.emphasis_density(_load(tmp_path)).hits


# ------------------------------------------------------------ selftest

@pytest.mark.parametrize("rule", checks.COLLECTION_RULES, ids=lambda r: r.id)
def test_a_blinded_collection_rule_reads_BLIND(
    rule: checks.CollectionRule, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """Selftest is under its own negative control for this family too."""
    def blind(coll: decay.Collection) -> decay.Result:
        result = rule.check(coll)
        result.hits = []
        return result

    blinded = checks.CollectionRule(rule.id, rule.severity, rule.summary, blind)
    rules = tuple(blinded if r.id == rule.id else r for r in checks.COLLECTION_RULES)
    monkeypatch.setattr(checks, "COLLECTION_RULES", rules)
    monkeypatch.setattr(checks, "ALL_RULES", (blinded,))
    assert cli.main(["selftest"]) == 1
    assert f"BLIND    {rule.id}" in capsys.readouterr().out


def test_a_good_case_with_nothing_to_examine_is_not_green(tmp_path: Path) -> None:
    """The #723 empty-population hole, closed for this family: a good case the
    rule examined nothing in is refused, not counted as a clean subject."""
    case = tmp_path / "empty"
    _skill(case, "a", "no markers here\n")
    findings, error = checks.collection_findings(case, only="expired-marker")
    assert findings == [] and error and "no marker" in error


def test_an_uncontrolled_collection_rule_is_UNPROVEN(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path,
) -> None:
    rule = checks.CollectionRule("no-such-control", checks.WARN, "x", decay.emphasis_density)
    monkeypatch.setattr(checks, "ALL_RULES", (rule,))
    assert cli.main(["selftest", "--controls", str(tmp_path)]) == 1
    assert "UNPROVEN no-such-control" in capsys.readouterr().out


def test_every_committed_bad_case_names_its_verdict() -> None:
    """The PR names each bad case with its verdict; this is that list, live."""
    for rule in checks.COLLECTION_RULES:
        for case in sorted((CONTROLS / rule.id / "bad").iterdir()):
            findings, error = checks.collection_findings(case, only=rule.id)
            assert error is None and findings, f"{rule.id}/{case.name} is not red"


# ------------------------------------------------------------ lanes (.claude/lanes.md)

def test_repo_from_git_reads_origin_in_a_main_checkout_and_a_linked_worktree(tmp_path: Path) -> None:
    """Lane 'Checkout: main checkout / linked worktree': a bare `#N` belongs to
    the origin remote either way."""
    import shutil
    import subprocess

    if shutil.which("git") is None:
        pytest.skip("git not installed")
    main = tmp_path / "main"
    env = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "HOME": str(tmp_path),
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid", "PATH": "/usr/bin:/bin"}

    def git(*args: str) -> None:
        subprocess.run(["git", *args], check=True, capture_output=True, env=env)

    git("init", "-q", str(main))
    git("-C", str(main), "remote", "add", "origin", "git@github.com:example/collection.git")
    git("-C", str(main), "commit", "-q", "--allow-empty", "-m", "x")
    git("-C", str(main), "worktree", "add", "-q", str(tmp_path / "linked"))
    assert decay.repo_from_git(main) == "example/collection"
    assert decay.repo_from_git(tmp_path / "linked") == "example/collection"
    assert decay.repo_from_git(tmp_path) is None


# ------------------------------------------------- counter-model review, pass 1

def test_a_good_control_whose_states_are_UNKNOWN_does_not_certify(tmp_path: Path) -> None:
    """Review finding 1: a good case whose issue states were never established
    is silent because nothing was known, not because it is good."""
    import shutil

    case = tmp_path / "open"
    shutil.copytree(CONTROLS / "expired-marker" / "good" / "open", case)
    (case / "issue-states.json").write_text("{}", encoding="utf-8")
    findings, error = checks.collection_findings(case, only="expired-marker")
    assert findings == [] and error and "UNKNOWN" in error


def test_a_neighbouring_filename_cannot_lend_a_flag(tmp_path: Path) -> None:
    """Review finding 2: `elper.sh` occurs inside `helper.sh`, but is not it."""
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "helper.sh").write_text("#!/bin/sh\n# helper.sh [--verbose]\n", encoding="utf-8")
    (scripts / "elper.sh").write_text("--dry-run\n", encoding="utf-8")
    _skill(tmp_path, "a", "Run `scripts/helper.sh --dry-run`.\n")
    assert decay.dangling_reference(_load(tmp_path)).hits


def test_repeated_text_reports_one_maximal_run(tmp_path: Path) -> None:
    """Review finding 4: alignments must not interleave."""
    same = " ".join(["same"] * 60)
    _skill(tmp_path, "a", same + "\n")
    _skill(tmp_path, "b", same + "\n")
    [hit] = decay.copied_passage(_load(tmp_path)).hits
    assert hit.data["runs"] == 1 and hit.data["longest_words"] == 60
