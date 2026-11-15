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


# ------------------------------------------------- counter-model review, pass 2

def test_a_flag_after_a_subshell_still_belongs_to_the_outer_script(tmp_path: Path) -> None:
    """Pass 2 finding 2: `$(...)` ends; the outer command's flags resume."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "helper.sh").write_text("--path\n", encoding="utf-8")
    _skill(tmp_path, "a", '```bash\nscripts/helper.sh --path "$(git rev-parse --show-toplevel)" --absent\n```\n')
    hits = decay.dangling_reference(_load(tmp_path)).hits
    assert [h.data["reference"] for h in hits] == ["scripts/helper.sh --absent"]


def test_a_single_star_does_not_cross_a_directory(tmp_path: Path) -> None:
    """Pass 2 finding 3."""
    for rel in (".claude/skills/x/SKILL.md", ".claude/skills/x/references/nested/SKILL.md"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("text\n", encoding="utf-8")
    coll = _load(tmp_path, include=[".claude/skills/*/SKILL.md"])
    assert [s.rel for s in coll.subjects] == [".claude/skills/x/SKILL.md"]
    coll = _load(tmp_path, include=["**/SKILL.md"])
    assert len(coll.subjects) == 2


def test_repetitive_text_stays_bounded(tmp_path: Path) -> None:
    """Pass 2 finding 5: no occurrence cross-product on repeated words."""
    import tracemalloc

    same = " ".join(["same"] * 5000)
    _skill(tmp_path, "a", same + "\n")
    _skill(tmp_path, "b", same + "\n")
    tracemalloc.start()
    [hit] = decay.copied_passage(_load(tmp_path)).hits
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert peak < 64 * 1024 * 1024, f"peak {peak} bytes"
    assert hit.data["longest_words"] == 5000


def test_a_url_encoded_link_resolves_to_its_decoded_file(tmp_path: Path) -> None:
    """Pass 2 finding 6."""
    _skill(tmp_path, "a", "[guide](references/my%20guide.md) and [gone](references/no%20such.md)\n")
    (tmp_path / "skills" / "a" / "references").mkdir()
    (tmp_path / "skills" / "a" / "references" / "my guide.md").write_text("x", encoding="utf-8")
    hits = decay.dangling_reference(_load(tmp_path)).hits
    assert [h.data["reference"] for h in hits] == ["references/no%20such.md"]


# ------------------------------------------------- #731 (counter-model pass 3, deferred)

def test_731_a_single_token_substitution_restores_the_outer_command(tmp_path: Path) -> None:
    """#731 item 2, the issue's exact input."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "helper.sh").write_text("#!/bin/sh\n# helper.sh [--verbose]\n", encoding="utf-8")
    _skill(tmp_path, "a", '```bash\nscripts/helper.sh --verbose "$(pwd)" --absent\n```\n')
    hits = decay.dangling_reference(_load(tmp_path)).hits
    assert [h.data["reference"] for h in hits] == ["scripts/helper.sh --absent"]


def test_731_a_file_argument_does_not_own_later_flags(tmp_path: Path) -> None:
    """#731 item 3, the issue's exact input against controls/dangling-reference/good/present."""
    import shutil

    case = tmp_path / "present"
    shutil.copytree(CONTROLS / "dangling-reference" / "good" / "present", case)
    skill_md = case / "skills" / "demo" / "SKILL.md"
    skill_md.write_text(skill_md.read_text(encoding="utf-8")
                        + "\nRun `scripts/helper.sh references/guide.md --verbose`.\n", encoding="utf-8")
    assert decay.dangling_reference(_load(case)).hits == []


def _prefix_case(root: Path, swap: bool) -> list[decay.Hit]:
    tail = " ".join(f"t{i}" for i in range(50))
    first, second = " ".join(["same"] * 60) + " " + tail, " ".join(["same"] * 100) + " " + tail
    if swap:
        first, second = second, first
    _skill(root, "a", first + "\n")
    _skill(root, "b", second + "\n")
    return decay.copied_passage(_load(root)).hits


@pytest.mark.parametrize("swap", [False, True], ids=["60-first", "100-first"])
def test_731_a_repetitive_prefix_is_measured_whole_in_both_orders(tmp_path: Path, swap: bool) -> None:
    """#731 item 4, the issue's exact case: 110 words, in either document order,
    and not labelled an estimate - an anchor measured it exactly."""
    [hit] = _prefix_case(tmp_path, swap)
    assert (hit.data["longest_words"], hit.data["runs"], hit.data["shared_words"]) == (110, 1, 110)
    assert hit.data["estimate"] is False and "bounded estimate" not in hit.detail


def test_731_purely_repetitive_text_is_labelled_a_bounded_estimate(tmp_path: Path) -> None:
    """The orchestrator's condition: where the bounded search could not rule out
    a missed run, the finding says it is an estimate.

    #741 changed the input. With the fallback's alignments pooled before any word
    is consumed, 200 x `same` is now measured EXACTLY (asserted below), so the
    estimate case is an input that genuinely hits the extension cap."""
    same = " ".join(["same"] * 200)
    _skill(tmp_path, "a", same + "\n")
    _skill(tmp_path, "b", same + "\n")
    [hit] = decay.copied_passage(_load(tmp_path)).hits
    assert hit.data["longest_words"] == 200 and hit.data["estimate"] is False
    long_same = " ".join(["same"] * 1000)
    _skill(tmp_path, "a", long_same + "\n")
    _skill(tmp_path, "b", long_same + "\n")
    [hit] = decay.copied_passage(_load(tmp_path)).hits
    assert hit.data["estimate"] is True and "bounded estimate" in hit.detail


def test_731_a_shell_keyword_keeps_the_command_position(tmp_path: Path) -> None:
    """`if ! scripts/x.sh --bad` and `elif scripts/x.sh --bad`: the script IS the
    command, so its flags are still checked (found on CPP's update.md/wave.md)."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "x.sh").write_text("--check\n", encoding="utf-8")
    _skill(tmp_path, "a", "```bash\nif ! scripts/x.sh --check --bad; then :; fi\nelif scripts/x.sh --worse\n```\n")
    hits = decay.dangling_reference(_load(tmp_path)).hits
    assert [h.data["reference"] for h in hits] == ["scripts/x.sh --bad", "scripts/x.sh --worse"]


# ------------------------------------------------- #731 counter-model pass 1

def test_731_r1_a_separator_after_a_substitution_ends_the_command(tmp_path: Path) -> None:
    """Reviewer's exact input: `echo --absent` is echo's flag, not the helper's."""
    import shutil

    case = tmp_path / "present"
    shutil.copytree(CONTROLS / "dangling-reference" / "good" / "present", case)
    skill_md = case / "skills" / "demo" / "SKILL.md"
    skill_md.write_text(skill_md.read_text(encoding="utf-8")
                        + '\n```bash\nscripts/helper.sh --verbose "$(pwd)"; echo --absent\n```\n', encoding="utf-8")
    assert decay.dangling_reference(_load(case)).hits == []


@pytest.mark.parametrize("swap", [False, True], ids=["A-first", "B-first"])
def test_731_r1_a_longer_match_is_not_starved_by_an_earlier_shorter_one(tmp_path: Path, swap: bool) -> None:
    """Reviewer's exact P/T case: the longest run is 60 words in BOTH orders."""
    p = " ".join(f"p{i}" for i in range(40))
    t = " ".join(f"t{i}" for i in range(20))
    first = " ".join(f"{p} sep{i}" for i in range(9)) + f" {p} {t}"
    second = f"{p} {t}"
    if swap:
        first, second = second, first
    _skill(tmp_path, "a", first + "\n")
    _skill(tmp_path, "b", second + "\n")
    [hit] = decay.copied_passage(_load(tmp_path)).hits
    assert hit.data["longest_words"] == 60


@pytest.mark.parametrize("wrapper", ["sudo -u root", "env -u VAR"])
def test_731_r1_a_wrapper_option_operand_is_not_the_command(tmp_path: Path, wrapper: str) -> None:
    """Reviewer's exact inputs: the helper is still the command, so --absent fires."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "helper.sh").write_text("--verbose\n", encoding="utf-8")
    _skill(tmp_path, "a", f"```bash\n{wrapper} scripts/helper.sh --absent\n```\n")
    hits = decay.dangling_reference(_load(tmp_path)).hits
    assert [h.data["reference"] for h in hits] == ["scripts/helper.sh --absent"]


def test_731_r1_flags_after_a_non_command_path_are_counted_not_silent(tmp_path: Path) -> None:
    """A path outside command position keeps its flags unexamined - but SAYS so."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "helper.sh").write_text("--verbose\n", encoding="utf-8")
    _skill(tmp_path, "a", "```bash\nmystery-wrapper --odd scripts/helper.sh --absent\n```\n")
    result = decay.dangling_reference(_load(tmp_path))
    assert result.hits == []
    assert result.population["flags_after_a_non_command_path"] == 1


# ------------------------------------------------- #731 counter-model pass 2 (ratified: shlex)

def _helper(root: Path) -> None:
    (root / "scripts").mkdir(exist_ok=True)
    (root / "scripts" / "helper.sh").write_text("#!/bin/sh\n# helper.sh [--verbose]\n", encoding="utf-8")


def _flag_refs(root: Path) -> list[str]:
    return [str(h.data["reference"]) for h in decay.dangling_reference(_load(root)).hits]


def test_731_r2_a_substitution_as_an_option_value_is_that_value(tmp_path: Path) -> None:
    """Reviewer's exact input: `"$(id -un)"` IS sudo's -u value; the helper is the command."""
    _helper(tmp_path)
    _skill(tmp_path, "a", '```bash\nsudo -u "$(id -un)" scripts/helper.sh --absent\n```\n')
    assert _flag_refs(tmp_path) == ["scripts/helper.sh --absent"]


@pytest.mark.parametrize("wrapper", ["sudo --user root", "sudo --user=root", "env --unset VAR", "env --unset=VAR"])
def test_731_r2_long_wrapper_options_take_their_value(tmp_path: Path, wrapper: str) -> None:
    """Reviewer's exact inputs, separate and `=` forms."""
    _helper(tmp_path)
    _skill(tmp_path, "a", f"```bash\n{wrapper} scripts/helper.sh --absent\n```\n")
    assert _flag_refs(tmp_path) == ["scripts/helper.sh --absent"]


def test_731_r2_a_quoted_separator_is_not_a_separator(tmp_path: Path) -> None:
    """Reviewer's exact input: the `;` is inside a quoted argument."""
    _helper(tmp_path)
    _skill(tmp_path, "a", '```bash\nscripts/helper.sh "$(printf x);" --absent\n```\n')
    assert _flag_refs(tmp_path) == ["scripts/helper.sh --absent"]


def test_731_r2_prose_apostrophes_never_hide_a_command(tmp_path: Path) -> None:
    """The orchestrator's guard: shlex reads command-shaped text only, so two
    apostrophes in the surrounding prose cannot swallow the code span."""
    _helper(tmp_path)
    _skill(tmp_path, "a", "Don't run `scripts/helper.sh --absent` if it isn't needed.\n")
    assert _flag_refs(tmp_path) == ["scripts/helper.sh --absent"]


def test_731_r2_an_unbalanced_quote_falls_back_to_whitespace_words(tmp_path: Path) -> None:
    """shlex refuses an unterminated quote; the span is then read as plain
    whitespace-separated words, so the command and its flag are still checked."""
    _helper(tmp_path)
    _skill(tmp_path, "a", '```bash\nscripts/helper.sh "unterminated --absent\n```\n')
    assert _flag_refs(tmp_path) == ["scripts/helper.sh --absent"]


def test_731_r2_a_truncated_fallback_search_is_an_estimate_even_when_it_finds_nothing(tmp_path: Path) -> None:
    """Reviewer's exact case: 100 `same` + 50 distinct + a different separator +
    100 `same`, in both documents. The anchor takes the first 150; the fallback's
    first candidates are already consumed, so the last 100 are not measured - and
    the finding must SAY so."""
    from skillc import inspect

    distinct = " ".join(f"d{i}" for i in range(50))
    same = " ".join(["same"] * 100)
    _skill(tmp_path, "a", f"{same} {distinct} sepA {same}\n")
    _skill(tmp_path, "b", f"{same} {distinct} sepB {same}\n")
    [hit] = decay.copied_passage(_load(tmp_path)).hits
    assert hit.data["estimate"] is True and "bounded estimate" in hit.detail
    assert "bounded estimate" in inspect.run(decay.load(tmp_path, offline=True)).data["summary"]


def test_731_r2_the_fallback_still_ends_a_command_after_a_substitution(tmp_path: Path) -> None:
    """The whitespace fallback (an unterminated quote later on the line) keeps
    the separator rule: `"$(pwd)";` ends the helper, so `echo --absent` is echo's."""
    _helper(tmp_path)
    _skill(tmp_path, "a", '```bash\nscripts/helper.sh --verbose "$(pwd)"; echo --absent \'dangling\n```\n')
    assert _flag_refs(tmp_path) == []


def test_731_r2_a_path_inside_a_quoted_string_is_still_checked_for_existence(tmp_path: Path) -> None:
    """shlex keeps `"..."` as one word; its inner paths must still exist (a
    deleted helper named in an echo string is still a dangling reference), but
    none of them is a command, so no flag is checked against them."""
    _helper(tmp_path)
    _skill(tmp_path, "a", '```bash\necho "run scripts/gone.sh, then scripts/helper.sh --absent"\n```\n')
    assert _flag_refs(tmp_path) == ["scripts/gone.sh,"[:-1]]


# ------------------------------------------------- #741 (five pass-3 false negatives)

def test_741_a_quoted_separator_is_an_argument(tmp_path: Path) -> None:
    """#741 item 1, the issue's exact input."""
    _helper(tmp_path)
    _skill(tmp_path, "a", '```bash\nscripts/helper.sh ";" --absent\n```\n')
    assert _flag_refs(tmp_path) == ["scripts/helper.sh --absent"]


def test_741_a_quoted_assignment_before_a_real_separator(tmp_path: Path) -> None:
    """Orchestrator's guard: `p="a b"` stays ONE word (posix boundaries), and the
    unquoted `;` after it still starts the helper's command."""
    _helper(tmp_path)
    _skill(tmp_path, "a", '```bash\np="a b" ; scripts/helper.sh --absent\n```\n')
    assert _flag_refs(tmp_path) == ["scripts/helper.sh --absent"]


def test_741_a_quoted_option_value_stays_one_word(tmp_path: Path) -> None:
    """Orchestrator's guard: `--opt="x y"` is one token; `--absent` is still checked."""
    _helper(tmp_path)
    _skill(tmp_path, "a", '```bash\nscripts/helper.sh --opt="x y" --absent\n```\n')
    assert _flag_refs(tmp_path) == ["scripts/helper.sh --opt", "scripts/helper.sh --absent"]


def test_741_a_path_beside_a_substitution_in_one_quoted_argument(tmp_path: Path) -> None:
    """#741 item 2, the issue's exact input."""
    _helper(tmp_path)
    _skill(tmp_path, "a", '```bash\necho "$(pwd) scripts/gone.sh"\n```\n')
    assert _flag_refs(tmp_path) == ["scripts/gone.sh"]


def test_741_wrapper_state_survives_a_substitution_with_a_separator_inside(tmp_path: Path) -> None:
    """#741 item 3, the issue's exact input."""
    _helper(tmp_path)
    _skill(tmp_path, "a", '```bash\nsudo -u $(id -un; echo root) -g root scripts/helper.sh --absent\n```\n')
    assert _flag_refs(tmp_path) == ["scripts/helper.sh --absent"]


@pytest.mark.parametrize("swap", [False, True], ids=["A-first", "B-first"])
def test_741_a_rare_anchor_does_not_starve_a_longer_repetitive_match(tmp_path: Path, swap: bool) -> None:
    """#741 item 4, the issue's exact case: 70 words in both orders, and exact."""
    tail = " ".join(f"t{i}" for i in range(20))
    first = " ".join(["same"] * 70) + " " + tail
    second = " ".join(["same"] * 100) + " separator " + " ".join(["same"] * 31) + " " + tail
    if swap:
        first, second = second, first
    _skill(tmp_path, "a", first + "\n")
    _skill(tmp_path, "b", second + "\n")
    [hit] = decay.copied_passage(_load(tmp_path)).hits
    assert hit.data["longest_words"] == 70 and hit.data["estimate"] is False


def test_741_the_fallback_extension_cap_labels_an_estimate(tmp_path: Path) -> None:
    """Orchestrator's negative control: an input that hits the extension cap is
    an estimate. (The 70-word case above is the exact, unlabelled side.)"""
    same = " ".join(["same"] * 1000)
    _skill(tmp_path, "a", same + "\n")
    _skill(tmp_path, "b", same + "\n")
    [hit] = decay.copied_passage(_load(tmp_path)).hits
    assert hit.data["estimate"] is True and "bounded estimate" in hit.detail


def test_741_env_split_string_flags_are_counted(tmp_path: Path) -> None:
    """#741 item 5, the issue's exact input: the -S value is command text - its
    path is checked, and the flag after it is COUNTED, never silently dropped."""
    _helper(tmp_path)
    _skill(tmp_path, "a", '```bash\nenv -S "bash scripts/helper.sh" --absent\nenv --split-string="bash scripts/gone.sh" --x\n```\n')
    result = decay.dangling_reference(_load(tmp_path))
    assert [h.data["reference"] for h in result.hits] == ["scripts/gone.sh"]
    assert result.population["flags_after_a_non_command_path"] == 2


def test_741_the_tokeniser_keeps_shlex_posix_boundaries() -> None:
    """Word boundaries are exactly shlex posix=True's (the orchestrator's
    condition); only the quoting of operators is added."""
    import shlex

    cases = [
        'p="a b" ; c', 'a"b c" d', 'x --opt="x y" --z', '"$(pwd)"; echo --a', "it's \"a\" b",
        'sudo -u "$(id -un)" s.sh', 'a && b || c | d', "e 'single ; quoted' f", 'esc\\ aped word',
    ]
    for text in cases:
        lexer = shlex.shlex(text, posix=True, punctuation_chars=";&|")
        lexer.whitespace_split = True
        lexer.commenters = ""
        try:
            expected = list(lexer)
        except ValueError:
            # Unbalanced for shlex (the apostrophe in "it's"): ours refuses too,
            # and the caller falls back to whitespace words.
            with pytest.raises(ValueError):
                decay.shell_tokens(text)
            continue
        assert [t.text for t in decay.shell_tokens(text)] == expected, text


def test_741_single_quotes_are_quotes_too(tmp_path: Path) -> None:
    """The single-quote twins: `';'` is an argument, and a path inside a
    single-quoted string is still checked for existence."""
    _helper(tmp_path)
    _skill(tmp_path, "a", "```bash\nscripts/helper.sh ';' --absent\necho 'run scripts/gone.sh now'\n```\n")
    assert _flag_refs(tmp_path) == ["scripts/helper.sh --absent", "scripts/gone.sh"]


def test_741_an_unquoted_substitution_as_an_option_value(tmp_path: Path) -> None:
    """`sudo -u $(id -un)` unquoted: the substitution branch (not the string
    branch) must consume the pending value, so the helper is still the command."""
    _helper(tmp_path)
    _skill(tmp_path, "a", "```bash\nsudo -u $(id -un) scripts/helper.sh --absent\n```\n")
    assert _flag_refs(tmp_path) == ["scripts/helper.sh --absent"]


def test_741_a_quoted_string_that_closes_a_substitution_still_closes_it(tmp_path: Path) -> None:
    """`X=$(sed 's/a b/c/') scripts/helper.sh --absent`: the last token of the
    substitution is a quoted string WITH the unquoted `)` attached. Its words are
    a string, but the `)` still ends the substitution, so the helper after it is
    the command and `--absent` is checked."""
    _helper(tmp_path)
    _skill(tmp_path, "a", "```bash\nX=$(sed 's/a b/c/') scripts/helper.sh --absent\n"
                          "sudo -u $(id 'a b') -g root scripts/helper.sh --absent\n```\n")
    # The second line only passes if the `)` restores the OUTER state (the
    # `sudo` prefix, so `-g root` is an option value and the helper the command).
    assert _flag_refs(tmp_path) == ["scripts/helper.sh --absent", "scripts/helper.sh --absent"]


def test_741_quoted_delimiters_are_not_substitution_delimiters() -> None:
    """Only UNQUOTED `$(` and `)` move the substitution stack."""
    tokens = decay.shell_tokens('a "$(pwd)" $(id x) "x)"')
    assert [(t.text, t.opens, t.closes) for t in tokens] == [
        ("a", 0, 0), ("$(pwd)", 0, 0), ("$(id", 1, 0), ("x)", 0, 1), ("x)", 0, 0),
    ]


def test_741_an_unquoted_single_token_substitution_restores_the_outer_command(tmp_path: Path) -> None:
    """Unquoted `$(pwd)` opens and closes in one word: the outer command is
    restored at once, so `--absent` is the helper's. (The quoted `"$(pwd)"` form is
    self-contained and never touches the stack.)"""
    _helper(tmp_path)
    _skill(tmp_path, "a", "```bash\nscripts/helper.sh --verbose $(pwd) --absent\n```\n")
    assert _flag_refs(tmp_path) == ["scripts/helper.sh --absent"]
