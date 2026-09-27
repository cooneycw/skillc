"""#11's second-collection conformance manifest (`evals/second-collection-
conformance/run-manifest.json`) cites each subject's recorded evidence rather
than inventing numbers - the host evidence (`evals/subjects/*/evidence/`) and
the live runs (`evals/second-collection-conformance/evidence/README.md`). These
tests prove every citation is exact and attributed to the right subject, so a
manifest claim cannot drift from, or outrun, the evidence it names. No model
call, no Docker call: a plain JSON structure and cross-reference check.
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
        summary = run["host_evidence"]["installation_receipt_summary"]  # type: ignore[index]
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


EVIDENCE = CONFORMANCE_DIR / "evidence" / "README.md"


_BLOCK_HEADERS = ("collection agent run: ", "subject: ")


def _block(evidence: str, opener: str) -> str:
    """The text from the line starting with `opener` through ITS OWN `EXIT=`
    line - one subject's own printed block, so a line cited for one
    collection cannot be satisfied by the other collection's block. Empty
    when the opener is absent, AND when another run's header or a code fence
    comes before an `EXIT=` line: an unterminated block would otherwise run
    on into the next block and borrow its verdict (codex review of #11)."""
    lines = evidence.splitlines()
    for i, line in enumerate(lines):
        if line.startswith(opener):
            for j in range(i + 1, len(lines)):
                if lines[j].startswith("EXIT="):
                    return "\n".join(lines[i:j + 1])
                if lines[j].startswith(_BLOCK_HEADERS) or lines[j].startswith("```"):
                    return ""
            return ""
    return ""


def _uncited(evidence: str, opener: str, cited: list[str]) -> list[str]:
    """Every cited line that is NOT a whole line of `opener`'s block. An
    empty citation list is itself a problem: nothing cited proves nothing."""
    if not cited:
        return ["no lines cited"]
    block_lines = {line.strip() for line in _block(evidence, opener).splitlines()}
    return [line for line in cited if line.strip() not in block_lines]


def _openers(subject: str) -> dict[str, str]:
    return {"demo_subject": f"subject: {subject} revision=", "collection_run": f"collection agent run: {subject} "}


def test_every_observed_line_is_in_that_subject_s_own_evidence_block() -> None:
    evidence = EVIDENCE.read_text(encoding="utf-8")
    for subject, run in _runs_by_subject().items():
        observed = run["observed"]
        assert isinstance(observed, dict) and set(observed) == {"demo_subject", "collection_run"}
        for leg, opener in _openers(subject).items():
            missing = _uncited(evidence, opener, observed[leg])
            assert missing == [], f"{subject}/{leg}: cited but not in the evidence block: {missing}"


def test_both_agent_runs_are_captured_and_graded() -> None:
    """Bullet 2's MET rests on exactly these two facts per collection."""
    for subject, run in _runs_by_subject().items():
        agent_lines = run["observed"]["collection_run"]  # type: ignore[index]
        assert "disposition=captured" in agent_lines, subject
        assert "graded.status=PASS" in agent_lines, subject


def test_the_control_is_cited_from_its_own_block_and_blocked() -> None:
    control = _manifest()["control"]
    assert isinstance(control, dict)
    evidence = EVIDENCE.read_text(encoding="utf-8")
    # The control's block is the LAST mattpocock-skills agent block.
    tail = evidence[evidence.rindex("collection agent run: mattpocock-skills "):]
    assert _uncited(tail, "collection agent run: mattpocock-skills ", control["observed"]) == []
    assert "disposition=unavailable" in control["observed"]


def test_the_citation_check_can_fail() -> None:
    """Negative controls for the instrument above, against the REAL evidence:
    a planted wrong verdict, a line that belongs to the OTHER collection, a
    subject with no block at all, and an empty citation list are each refused."""
    evidence = EVIDENCE.read_text(encoding="utf-8")
    mp = "collection agent run: mattpocock-skills "
    assert _uncited(evidence, mp, ["graded.status=FAIL"]) == ["graded.status=FAIL"]
    assert _uncited(evidence, "collection agent run: cpp-codex ", ["skill_invocations=['diagnosing-bugs'] (detection=heuristic)"]) != []
    assert _uncited(evidence, "collection agent run: no-such-subject ", ["EXIT=0"]) == ["EXIT=0"]
    assert _uncited(evidence, mp, []) == ["no lines cited"]
    # A substring of a real line is not a whole line.
    assert _uncited(evidence, mp, ["graded.status=PA"]) == ["graded.status=PA"]
    # A block missing its own verdict and EXIT must not borrow the NEXT
    # block's (codex review of #11: this mutation used to pass).
    first = evidence.index(mp)
    own = evidence[first:evidence.index("EXIT=", first)]
    truncated = evidence.replace(own + "EXIT=0\n", own.replace("  graded.status=PASS\n", ""), 1)
    assert truncated != evidence
    assert _uncited(truncated, mp, ["graded.status=PASS", "EXIT=0"]) == ["graded.status=PASS", "EXIT=0"]


def test_the_manifest_states_it_was_executed_and_names_its_evidence() -> None:
    execution = _manifest()["execution"]
    assert isinstance(execution, str) and execution.startswith("executed")
    assert "evidence/README.md" in execution
    assert EVIDENCE.is_file()


def test_every_bullet_is_met() -> None:
    status = _manifest()["acceptance_status"]
    assert isinstance(status, dict)
    bullets = {k: v for k, v in status.items() if k.startswith("bullet_")}
    assert len(bullets) == 4
    for key, value in bullets.items():
        assert value.startswith("MET"), f"{key}: {value[:60]!r}"


def test_the_agent_run_s_funding_basis_quotes_the_owner_ruling_verbatim() -> None:
    """The owner's ruling on #98, quoted rather than paraphrased: agent runs
    use the operator's normal subscription login, not metered spend, and
    are NOT gated by the #12 cost stop (that covers judge calls only). A
    paraphrase risks widening or narrowing a ruling that was given in exact
    words for a reason."""
    bullet_2 = _manifest()["acceptance_status"]["bullet_2_same_client_fixture_contract_grader"]  # type: ignore[index]
    assert '"Normal Claude and codex"' in bullet_2
    assert "NOT metered" in bullet_2
    assert "NOT gated by the #12 $5 cost stop" in bullet_2
