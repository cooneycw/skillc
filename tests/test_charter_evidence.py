"""`skillc charter evidence` (#778 PR A): every existing piece of a skill's
charter, as cited suggestions, with a status for every source."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from skillc import charter, charter_evidence, cli
from skillc.charter_evidence import NOT_EXAMINED, SOURCES, extract, gather
from skillc.repo_reader import (
    Document,
    FakeReader,
    GhReader,
    Part,
    ReadOnlyViolation,
    Ref,
    RepoReadError,
    assert_read_only,
    parse_ref,
)

FIXTURES = Path(__file__).parent / "fixtures" / "charter-evidence"
V1_URL = "https://github.com/cooneycw/skillc/discussions/718#discussioncomment-19618555"
REPO = "cooneycw/skillc"


def _collection(tmp_path: Path, body: str = "Do the job.\n", description: str = "Run the thing.") -> Path:
    skill = tmp_path / "skills" / "demo"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(f"---\nname: demo\ndescription: {description}\n---\n\n{body}", encoding="utf-8")
    return tmp_path


def _doc(body: str, url: str = "https://github.com/o/n/discussions/9#c1", number: int = 9,
         kind: str = "discussion", repo: str = "o/n") -> Document:
    return Document(Ref(repo, number, kind), kind, url.split("#")[0], "planted", (Part(url, body),))


def _repo_suggestions(found: charter_evidence.EvidenceFile) -> list[charter_evidence.Suggestion]:
    return [s for s in found.suggestions if s.source == charter_evidence.REPOSITORY]


# ---------------------------------------------------------------- the frozen #718 Charter v1


def test_the_frozen_718_charter_v1_yields_its_job_four_always_and_five_never_with_its_url(tmp_path: Path) -> None:
    """The /skill-gauntlet acceptance: the evidence step finds #718's Charter v1."""
    body = (FIXTURES / "d718-charter-v1.md").read_text(encoding="utf-8")
    reader = FakeReader({(REPO, 718): _doc(body, V1_URL, 718, repo=REPO)})
    found = gather(_collection(tmp_path), "skills/demo", reader=reader, refs=["discussion:718"], repo=REPO)
    items = _repo_suggestions(found)
    by = {sec: [s for s in items if s.section == sec] for sec in ("intent", "always", "never")}
    assert [len(by["intent"]), len(by["always"]), len(by["never"])] == [1, 4, 5]
    assert len(items) == 10
    assert by["intent"][0].text.startswith("take any skill and return one evidenced verdict")
    assert by["never"][0].text == "Edit a skill, merge a change, or change a charter without the owner."
    assert by["never"][4].text.startswith("Grow into a second scaffold.")
    assert {s.cite for s in items} == {V1_URL}
    assert {s.kind for s in items} == {charter_evidence.OBSERVATIONAL}


def test_the_frozen_718_body_has_no_charter_headings_and_yields_nothing() -> None:
    """A real prose document full of MUST/never sentences and bold run-in labels
    inside bullets: nothing is charter-shaped, so nothing is taken."""
    body = (FIXTURES / "d718-body.md").read_text(encoding="utf-8")
    assert "never" in body and "Must always" in body
    assert extract(body) == []


# ---------------------------------------------------------------- the extractor's controls


def test_a_planted_discussion_must_never_is_offered_with_its_url(tmp_path: Path) -> None:
    url = "https://github.com/o/n/discussions/9#discussioncomment-1"
    reader = FakeReader({("o/n", 9): _doc("## Must never\n\n- Delete the owner's data.\n", url)})
    found = gather(_collection(tmp_path), "skills/demo", reader=reader, refs=["9"], repo="o/n")
    (item,) = _repo_suggestions(found)
    assert (item.section, item.text, item.cite, item.kind) == (
        "never", "Delete the owner's data.", url, charter_evidence.OBSERVATIONAL)


def test_prose_without_charter_shaped_headings_yields_no_suggestions() -> None:
    """The negative control: an instrument that invents a charter from prose
    would turn these into duties."""
    prose = ("We discussed this at length. The skill must never delete files, and it must always ask first.\n\n"
             "- It never answers for the owner.\n- It MUST cite evidence.\n\n"
             "## Background\n\n- Never skip the gate.\n\n**Notes**\n\n- Always run the tests.\n")
    assert extract(prose) == []


def test_a_must_never_heading_inside_a_fenced_code_block_is_ignored() -> None:
    decoy = "Example:\n\n```markdown\n## Must never\n\n- Delete everything.\n```\n"
    assert extract(decoy) == []


def test_a_nested_fence_does_not_close_the_outer_one() -> None:
    """#749's rule: a shorter inner fence does not close a longer outer one."""
    decoy = "````\n```\n````x\n**Must never**\n- Delete everything.\n````\n"
    assert extract(decoy) == []
    after = decoy + "\n**Must never**\n\n- Keep the owner informed.\n"
    assert extract(after) == [("never", "Keep the owner informed.")]


def test_labels_take_list_items_and_a_paragraph_after_the_list_ends_the_section() -> None:
    body = ("**Job:** do one thing well.\n\n**Must always**\n1. Cite the source,\n   with its URL.\n2. Stop on UNKNOWN.\n\n"
            "That list was long. It must never be read as a duty.\n\n## Authority\n\n- Only the owner approves.\n")
    assert extract(body) == [
        ("intent", "do one thing well."),
        ("always", "Cite the source, with its URL."),
        ("always", "Stop on UNKNOWN."),
        ("authority", "Only the owner approves."),
    ]


def test_an_intent_heading_takes_its_first_paragraph() -> None:
    assert extract("## Intent\n\nThe owner sees the plan\nbefore any change.\n\nMore prose.\n") == [
        ("intent", "The owner sees the plan before any change.")]


# ---------------------------------------------------------------- not examined, never silently empty


def test_no_gh_reads_not_examined_and_the_run_continues(tmp_path: Path) -> None:
    found = gather(_collection(tmp_path, "You MUST cite evidence.\n"), "skills/demo",
                   reader=GhReader(gh=None), refs=["718"], repo=REPO)
    rows = [s for s in found.sources if s.source == charter_evidence.REPOSITORY]
    assert [r.status for r in rows] == [f"{NOT_EXAMINED}: gh not found on PATH"]
    assert rows[0].ref == "cooneycw/skillc#718"
    assert {s.source for s in found.sources} == set(SOURCES)  # every source reports a status
    assert any(s.source == charter_evidence.SKILL_TEXT for s in found.suggestions)  # the run went on


def test_no_ref_and_no_search_reads_not_examined_and_search_is_off_by_default(tmp_path: Path) -> None:
    reader = FakeReader()
    found = gather(_collection(tmp_path), "skills/demo", reader=reader, repo="o/n")
    (row,) = [s for s in found.sources if s.source == charter_evidence.REPOSITORY]
    assert row.status == f"{NOT_EXAMINED}: no --ref given, and --search is off"
    assert reader.calls == []


def test_search_runs_only_when_asked_and_reads_what_it_finds(tmp_path: Path) -> None:
    reader = FakeReader({("o/n", 4): _doc("**Must never**\n- Push to main.\n", number=4)},
                        searches={("o/n", "demo"): [Ref("o/n", 4)]})
    found = gather(_collection(tmp_path), "skills/demo", reader=reader, repo="o/n", search=True)
    assert reader.calls == ["search o/n demo", "read o/n#4"]
    assert [s.text for s in _repo_suggestions(found)] == ["Push to main."]


def test_an_unreadable_ref_is_not_examined_with_its_reason(tmp_path: Path) -> None:
    found = gather(_collection(tmp_path), "skills/demo", reader=FakeReader(fail="HTTP 401: bad credentials"),
                   refs=["718"], repo=REPO)
    (row,) = [s for s in found.sources if s.source == charter_evidence.REPOSITORY]
    assert row.status == f"{NOT_EXAMINED}: HTTP 401: bad credentials"


def test_a_truncated_thread_says_so(tmp_path: Path) -> None:
    doc = Document(Ref("o/n", 9, "discussion"), "discussion", "u", "t", (Part("u", "**Must never**\n- X.\n"),),
                   truncated=True)
    found = gather(_collection(tmp_path), "skills/demo", reader=FakeReader({("o/n", 9): doc}), refs=["9"], repo="o/n")
    (row,) = [s for s in found.sources if s.source == charter_evidence.REPOSITORY]
    assert "TRUNCATED" in row.detail


def test_a_charter_that_does_not_parse_is_not_examined(tmp_path: Path) -> None:
    root = _collection(tmp_path)
    (root / "skills/demo/CHARTER.md").write_text("no block here\n", encoding="utf-8")
    found = gather(root, "skills/demo", reader=None)
    (row,) = [s for s in found.sources if s.source == charter_evidence.EXISTING_CHARTER]
    assert row.status.startswith(f"{NOT_EXAMINED}: skills/demo/CHARTER.md not parsed")


def test_no_usage_is_not_examined_never_none_found(tmp_path: Path) -> None:
    found = gather(_collection(tmp_path), "skills/demo", reader=None)
    (row,) = [s for s in found.sources if s.source == charter_evidence.USAGE]
    assert row.status.startswith(NOT_EXAMINED)


# ---------------------------------------------------------------- other sources


def test_an_existing_charter_offers_every_clause_marked_draft(tmp_path: Path) -> None:
    root = _collection(tmp_path)
    (root / "skills/demo/CHARTER.md").write_text(
        '---\ncontract: "demo"\nversion: 1\nintent:\n  id: "demo.intent"\n  draft: true\n  what: "Do the job."\n'
        'purpose: "p"\nowner: "owner"\ninvariants:\n  always: []\n  never:\n    - id: "demo.never-1"\n'
        '      draft: true\n      what: "Never guess."\n---\n', encoding="utf-8")
    found = gather(root, "skills/demo", reader=None)
    items = [s for s in found.suggestions if s.source == charter_evidence.EXISTING_CHARTER]
    assert [(s.section, s.text, s.cite) for s in items] == [
        ("intent", "Do the job.", "skills/demo/CHARTER.md: demo.intent"),
        ("purpose", "p", "skills/demo/CHARTER.md: purpose"),
        ("never", "Never guess.", "skills/demo/CHARTER.md: demo.never-1 (draft)"),
    ]


def test_existing_tests_that_name_the_skill_are_offered(tmp_path: Path) -> None:
    root = _collection(tmp_path)
    (root / "tests").mkdir()
    (root / "tests/test_demo.py").write_text("def test_x():\n    run('demo')\n", encoding="utf-8")
    (root / "tests/test_other.py").write_text("def test_y():\n    run('demonstration')\n", encoding="utf-8")
    found = gather(root, "skills/demo", reader=None)
    items = [s for s in found.suggestions if s.source == charter_evidence.TESTS]
    assert [(s.text, s.cite) for s in items] == [("tests/test_demo.py names the skill", "tests/test_demo.py:2")]


def test_skill_text_and_a_spec_doc_are_offered_with_file_line_citations(tmp_path: Path) -> None:
    root = _collection(tmp_path, "You MUST cite evidence.\n")
    (root / "docs").mkdir()
    (root / "docs/spec.md").write_text("# Spec\n\nIt NEVER edits the skill.\n", encoding="utf-8")
    found = gather(root, "skills/demo", reader=None, docs=[Path("docs/spec.md")])
    items = [(s.section, s.cite) for s in found.suggestions if s.source == charter_evidence.SKILL_TEXT]
    assert items == [("intent", "skills/demo/SKILL.md: frontmatter description"),
                     ("always", "skills/demo/SKILL.md:6"), ("never", "docs/spec.md:3")]


# ---------------------------------------------------------------- quotes stay short


def test_quotes_stay_under_40_words_and_the_copied_passage_detector_is_clean_on_the_evidence(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Run the REAL detector. The skill holds one long passage; a `source`
    skill stands for the discussion holding another; the evidence file's
    quotes of both are a third skill."""
    words = " ".join(f"w{i}" for i in range(80))
    other = " ".join(f"v{i}" for i in range(80))
    root = _collection(tmp_path, f"You MUST {other}.\n")
    reader = FakeReader({("o/n", 9): _doc(f"**Must never**\n- Never {words}.\n")})
    found = gather(root, "skills/demo", reader=reader, refs=["9"], repo="o/n")
    assert max(len(s.text.replace(" ...", "").split()) for s in found.suggestions) <= charter.MAX_QUOTE_WORDS < 40
    (root / "skills/source").mkdir()
    (root / "skills/source/SKILL.md").write_text(f"---\nname: source\ndescription: d\n---\n\nNever {words}.\n",
                                                 encoding="utf-8")
    (root / "skills/evidence").mkdir()
    (root / "skills/evidence/SKILL.md").write_text("---\nname: evidence\ndescription: d\n---\n\n" + found.to_json(),
                                                   encoding="utf-8")
    capsys.readouterr()
    cli.main(["inspect", str(root / "skills"), "--offline", "--json"])
    report = json.loads(capsys.readouterr().out)
    assert '"rule": "copied-passage"' not in json.dumps(report.get("findings", report))


# ---------------------------------------------------------------- gh is read-only


class _Recorder:
    def __init__(self, replies: list[str]) -> None:
        self.argv: list[list[str]] = []
        self.replies = replies

    def __call__(self, argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        self.argv.append(argv)
        out = self.replies.pop(0)
        return subprocess.CompletedProcess(argv, 0 if '"errors"' not in out else 1, out, "")


_NOT_A_DISCUSSION = json.dumps({"data": {"repository": {"discussion": None}},
                                "errors": [{"type": "NOT_FOUND", "message": "no discussion"}]})
_AN_ISSUE = json.dumps({"data": {"repository": {"issueOrPullRequest": {
    "__typename": "Issue", "url": "https://github.com/o/n/issues/5", "title": "t", "body": "**Must never**\n- X.\n",
    "comments": {"pageInfo": {"hasNextPage": False}, "nodes": [{"url": "https://github.com/o/n/issues/5#c", "body": ""}]}}}}})


def test_every_gh_call_is_a_read_only_graphql_query_and_a_discussion_miss_falls_back_to_the_issue() -> None:
    rec = _Recorder([_NOT_A_DISCUSSION, _AN_ISSUE])
    doc = GhReader(runner=rec, gh="gh").read(Ref("o/n", 5))
    assert (doc.kind, len(doc.parts)) == ("issue", 2)
    assert len(rec.argv) == 2
    for argv in rec.argv:
        assert argv[:3] == ["gh", "api", "graphql"]
        assert_read_only(argv[1:])


def test_a_github_error_that_is_not_not_found_is_a_failed_read() -> None:
    reply = json.dumps({"data": None, "errors": [{"type": "FORBIDDEN", "message": "rate limited"}]})
    with pytest.raises(RepoReadError, match="rate limited"):
        GhReader(runner=_Recorder([reply]), gh="gh").read(Ref("o/n", 5, "discussion"))


def test_output_that_is_not_json_is_a_failed_read() -> None:
    def runner(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 4, "", "gh: To get started, please run: gh auth login\n")
    with pytest.raises(RepoReadError, match="gh exited 4: gh: To get started"):
        GhReader(runner=runner, gh="gh").read(Ref("o/n", 5, "issue"))


@pytest.mark.parametrize("argv", [
    ["issue", "comment", "5", "--body", "x"],
    ["api", "repos/o/n/issues/5/comments", "-f", "body=x"],
    ["api", "graphql", "-f", "query=mutation{addComment(input:{}){clientMutationId}}"],
    ["api", "graphql", "-f", "query=query{viewer{login}} mutation{x}"],
    ["api", "graphql", "-f", "query=query{viewer{login}}", "-f", "query=mutation{x}"],
    ["api", "graphql", "-f", "query=query{viewer{login}}", "--method", "POST"],
])
def test_anything_but_a_read_only_query_is_refused_before_it_runs(argv: list[str]) -> None:
    ran: list[list[str]] = []
    reader = GhReader(runner=lambda a, **_: ran.append(a), gh="gh")  # type: ignore[arg-type,return-value]
    with pytest.raises(ReadOnlyViolation):
        assert_read_only(argv)
    with pytest.raises(ReadOnlyViolation):
        reader._gh(argv)
    assert ran == []


def test_a_kind_mismatch_is_refused() -> None:
    with pytest.raises(RepoReadError, match="is a issue, not a pr"):
        GhReader(runner=_Recorder([_AN_ISSUE]), gh="gh").read(Ref("o/n", 5, "pr"))


@pytest.mark.parametrize(("text", "ref"), [
    ("718", Ref(REPO, 718)), ("#718", Ref(REPO, 718)), ("discussion:718", Ref(REPO, 718, "discussion")),
    ("cooneycw/claude-power-pack#1830", Ref("cooneycw/claude-power-pack", 1830)),
    ("issue:o/n#5", Ref("o/n", 5, "issue")),
])
def test_refs_parse(text: str, ref: Ref) -> None:
    assert parse_ref(text, REPO) == ref


def test_a_bare_ref_with_no_repository_is_refused() -> None:
    with pytest.raises(ValueError, match="names no repository"):
        parse_ref("718", None)


# ---------------------------------------------------------------- the CLI


def test_the_cli_writes_schema_1_and_never_overwrites(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _collection(tmp_path / "c")
    out = tmp_path / "evidence.json"
    assert cli.main(["charter", "evidence", str(root), "skills/demo", "--repo", "o/n", "--out", str(out)]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["schema"] == 1 and data["skill"] == "skills/demo"
    assert {s["source"] for s in data["sources"]} == set(SOURCES)
    assert "SOURCE repository evidence: not examined" in capsys.readouterr().out
    assert cli.main(["charter", "evidence", str(root), "skills/demo", "--out", str(out)]) == 2


# ---------------------------------------------------------------- counter-model review, pass 1


def test_a_search_that_finds_nothing_is_none_found_not_a_crash(tmp_path: Path) -> None:
    reader = FakeReader(searches={("o/n", "demo"): []})
    found = gather(_collection(tmp_path), "skills/demo", reader=reader, repo="o/n", search=True)
    (row,) = [s for s in found.sources if s.source == charter_evidence.REPOSITORY]
    assert row.status == charter_evidence.NONE_FOUND and "demo" in row.ref


def test_a_partial_graphql_answer_with_an_error_is_a_failed_read() -> None:
    reply = json.dumps({"data": {"repository": {"discussion": {
        "url": "u", "title": "t", "body": "**Must never**\n- X.\n", "comments": None}}},
        "errors": [{"type": "FORBIDDEN", "path": ["repository", "discussion", "comments"], "message": "no access"}]})
    with pytest.raises(RepoReadError, match="no access"):
        GhReader(runner=_Recorder([reply]), gh="gh").read(Ref("o/n", 9, "discussion"))


def test_a_search_with_more_results_than_one_page_says_truncated(tmp_path: Path) -> None:
    page = {"pageInfo": {"hasNextPage": True}, "nodes": [{"number": n} for n in range(1, 21)]}
    reply = json.dumps({"data": {"issues": page, "discussions": {"pageInfo": {"hasNextPage": False}, "nodes": []}}})
    result = GhReader(runner=_Recorder([reply]), gh="gh").search("o/n", "demo")
    assert result.truncated and len(result.refs) == 20
    reader = FakeReader(searches={("o/n", "demo"): [Ref("o/n", 4)]}, search_truncated=True,
                        documents={("o/n", 4): _doc("**Must never**\n- X.\n", number=4)})
    found = gather(_collection(tmp_path), "skills/demo", reader=reader, repo="o/n", search=True)
    assert any("TRUNCATED" in s.detail for s in found.sources if s.source == charter_evidence.REPOSITORY)


def test_an_unreadable_test_directory_is_not_none_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _collection(tmp_path)
    (root / "tests").mkdir()
    real = Path.iterdir

    def iterdir(self: Path):  # type: ignore[no-untyped-def]
        if self.name == "tests":
            raise PermissionError("denied")
        return real(self)

    monkeypatch.setattr(Path, "iterdir", iterdir)
    found = gather(root, "skills/demo", reader=None)
    (row,) = [s for s in found.sources if s.source == charter_evidence.TESTS]
    assert row.status.startswith(NOT_EXAMINED) and "1 director" in row.status


def test_an_oversized_test_file_is_not_none_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _collection(tmp_path)
    (root / "tests").mkdir()
    (root / "tests/test_big.py").write_text("x = 'demo'\n" * 10, encoding="utf-8")
    monkeypatch.setattr(charter_evidence, "TEST_MAX_BYTES", 5)
    found = gather(root, "skills/demo", reader=None)
    (row,) = [s for s in found.sources if s.source == charter_evidence.TESTS]
    assert row.status.startswith(NOT_EXAMINED) and "too large" in row.status


def test_the_gauntlets_own_draft_under_skillc_gauntlet_is_found(tmp_path: Path) -> None:
    root = _collection(tmp_path)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    from skillc.gauntlet import resolve_skill
    draft_dir = root / ".skillc" / "gauntlet" / resolve_skill(root, "skills/demo").slug
    draft_dir.mkdir(parents=True)
    (draft_dir / "CHARTER.draft.md").write_text(
        '---\ncontract: "demo"\nversion: 1\nintent: "Draft intent."\npurpose: "p"\nowner: "owner"\n---\n',
        encoding="utf-8")
    found = gather(root, "skills/demo", reader=None)
    items = [s for s in found.suggestions if s.source == charter_evidence.EXISTING_CHARTER]
    assert ("intent", "Draft intent.") in [(s.section, s.text) for s in items]
    explicit = gather(root, "skills/demo", reader=None, drafts=[draft_dir / "CHARTER.draft.md"])
    assert len([s for s in explicit.suggestions if s.source == charter_evidence.EXISTING_CHARTER]) == len(items)


def test_a_clause_with_only_an_id_and_a_test_is_still_offered_with_its_test(tmp_path: Path) -> None:
    root = _collection(tmp_path)
    alpha = Path(__file__).parent.parent / "controls/contract-shape/good/valid/alpha/CHARTER.md"
    (root / "skills/demo/CHARTER.md").write_text(alpha.read_text(encoding="utf-8"), encoding="utf-8")
    found = gather(root, "skills/demo", reader=None)
    items = {s.cite.split(": ", 1)[1]: s for s in found.suggestions if s.source == charter_evidence.EXISTING_CHARTER}
    assert {"alpha.out", "alpha.never", "alpha.no-self-approval"} <= set(items)
    assert items["alpha.never"].section == "never"
    assert items["alpha.never"].test == "checks/alpha-never/{bad,good}"


def test_a_usage_suggestion_cites_its_log_and_line(tmp_path: Path) -> None:
    """#726's committed complete-coverage log: each observed token cites the
    record lines that carry it."""
    logs = Path(__file__).parent.parent / "evals/subjects/charter-draft/logs/complete"
    found = gather(_collection(tmp_path), "skills/demo", reader=None, usage_paths=[logs])
    items = [s for s in found.suggestions if s.source == charter_evidence.USAGE]
    assert items
    for item in items:
        assert re.search(r"usage\.jsonl:\d+", item.cite), item.cite


# ---------------------------------------------------------------- counter-model review, pass 2; the Checkout lane


def test_an_unreadable_skill_md_is_not_examined_and_the_other_sources_still_run(tmp_path: Path) -> None:
    root = _collection(tmp_path)
    (root / "skills/demo/SKILL.md").write_bytes(b"---\nname: demo\n---\n\xff\xfe bad bytes\n")
    reader = FakeReader({("o/n", 9): _doc("**Must never**\n- X.\n")})
    found = gather(root, "skills/demo", reader=reader, refs=["9"], repo="o/n")
    (row,) = [s for s in found.sources if s.source == charter_evidence.SKILL_TEXT]
    assert row.status.startswith(f"{NOT_EXAMINED}: skills/demo/SKILL.md not read")
    assert [s.text for s in _repo_suggestions(found)] == ["X."]


def test_no_git_reads_the_gauntlet_draft_location_as_not_examined(tmp_path: Path,
                                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    root = _collection(tmp_path)

    def no_git(*a: object, **k: object) -> object:
        raise FileNotFoundError("git")

    monkeypatch.setattr(subprocess, "run", no_git)
    found = gather(root, "skills/demo", reader=None)
    rows = [s for s in found.sources if s.source == charter_evidence.EXISTING_CHARTER]
    assert any(r.status.startswith(NOT_EXAMINED) and "gauntlet" in r.status for r in rows)


def test_a_pr_read_includes_review_bodies_and_review_thread_comments() -> None:
    reply = json.dumps({"data": {"repository": {"issueOrPullRequest": {
        "__typename": "PullRequest", "url": "https://github.com/o/n/pull/7", "title": "t", "body": "",
        "comments": {"pageInfo": {"hasNextPage": False}, "nodes": []},
        "reviews": {"pageInfo": {"hasNextPage": False},
                    "nodes": [{"url": "https://github.com/o/n/pull/7#pullrequestreview-1", "body": "**Must never**\n- A.\n"}]},
        "reviewThreads": {"pageInfo": {"hasNextPage": False}, "nodes": [{"comments": {
            "pageInfo": {"hasNextPage": False},
            "nodes": [{"url": "https://github.com/o/n/pull/7#discussion_r2", "body": "**Must never**\n- B.\n"}]}}]}}}}})
    doc = GhReader(runner=_Recorder([reply]), gh="gh").read(Ref("o/n", 7, "pr"))
    assert [p.url.rsplit("#", 1)[1] for p in doc.parts[1:]] == ["pullrequestreview-1", "discussion_r2"]


def test_bold_emphasis_in_prose_is_not_a_label() -> None:
    assert extract("**Never** assume the examples below are charter clauses.\n\n- Delete things.\n") == []
    assert extract("**Must always** be careful here, it said.\n") == []
    assert extract("**Must never:** delete data.\n") == [("never", "delete data.")]
    assert extract("**Must never**: delete data.\n") == [("never", "delete data.")]


def test_a_heading_inside_an_html_comment_is_ignored() -> None:
    assert extract("<!--\n## Must never\n- Delete everything.\n-->\n") == []
    assert extract("<!-- old --> **Must never**\n- Keep it.\n") == [("never", "Keep it.")]


def test_a_doc_outside_the_collection_keeps_a_citation_that_resolves(tmp_path: Path) -> None:
    root = _collection(tmp_path / "c")
    outside = tmp_path / "elsewhere" / "spec.md"
    outside.parent.mkdir()
    outside.write_text("It NEVER edits the skill.\n", encoding="utf-8")
    found = gather(root, "skills/demo", reader=None, docs=[outside])
    (item,) = [s for s in found.suggestions if s.cite.endswith(":1") and s.source == charter_evidence.SKILL_TEXT]
    assert Path(item.cite.rsplit(":", 1)[0]) == outside


def test_from_a_linked_worktree_the_draft_in_the_main_checkout_is_found(tmp_path: Path) -> None:
    """The Checkout lane: `skillc gauntlet run` keeps the draft in the MAIN
    checkout's .skillc/, so a collection opened from a linked worktree must
    still find it."""
    main = _collection(tmp_path / "main")
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
    subprocess.run([*git, "init", "-q", str(main)], check=True)
    subprocess.run([*git, "-C", str(main), "add", "-A"], check=True)
    subprocess.run([*git, "-C", str(main), "commit", "-qm", "x"], check=True)
    linked = tmp_path / "linked"
    subprocess.run([*git, "-C", str(main), "worktree", "add", "-q", str(linked)], check=True)
    from skillc.gauntlet import resolve_skill
    slug = resolve_skill(linked, "skills/demo").slug
    draft_dir = main / ".skillc" / "gauntlet" / slug
    draft_dir.mkdir(parents=True)
    (draft_dir / "CHARTER.draft.md").write_text(
        '---\ncontract: "demo"\nversion: 1\nintent: "Main-checkout draft."\npurpose: "p"\nowner: "owner"\n---\n',
        encoding="utf-8")
    found = gather(linked, "skills/demo", reader=None)
    assert ("intent", "Main-checkout draft.") in [
        (s.section, s.text) for s in found.suggestions if s.source == charter_evidence.EXISTING_CHARTER]
