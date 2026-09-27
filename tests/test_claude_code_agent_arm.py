"""#124's Claude Code agent arm manifest (`evals/claude-code-agent-arm/
run-manifest.json`) cites the live runs recorded in its `evidence/README.md`
rather than restating them. These tests prove every citation is exact and
attributed to the right collection's own printed block, so a manifest claim
cannot drift from, or outrun, the evidence it names. No model call, no Docker
call: a plain JSON structure and cross-reference check.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARM_DIR = ROOT / "evals" / "claude-code-agent-arm"
EVIDENCE = ARM_DIR / "evidence" / "README.md"
SUBJECTS = ("cpp-claude-code", "mattpocock-skills-claude-code")


def _manifest() -> dict[str, object]:
    return json.loads((ARM_DIR / "run-manifest.json").read_text(encoding="utf-8"))


def _runs() -> dict[str, dict[str, object]]:
    runs = _manifest()["runs"]
    assert isinstance(runs, list)
    return {run["subject"]: run for run in runs}


def _block(evidence: str, opener: str) -> list[str]:
    """The stripped lines from the one starting with `opener` through ITS OWN
    `EXIT=` line. Empty when the opener is absent, or when another run's
    header or a code fence comes first: an unterminated block would otherwise
    borrow the next block's verdict."""
    lines = evidence.splitlines()
    for i, line in enumerate(lines):
        if line.startswith(opener):
            out = [line.strip()]
            for later in lines[i + 1:]:
                if later.startswith(("collection agent run: ", "```")):
                    return []
                out.append(later.strip())
                if later.startswith("EXIT="):
                    return out
            return []
    return []


def _uncited(evidence: str, opener: str, cited: list[str]) -> list[str]:
    """Every cited line NOT in the block `opener` names - the check itself,
    split out so its negative control can feed it known-bad citations."""
    block = _block(evidence, opener)
    if not block:
        return [f"no terminated block starts with {opener!r}"]
    return [line for line in cited if line not in block]


def test_the_manifest_declares_exactly_the_two_claude_subjects() -> None:
    assert set(_runs()) == set(SUBJECTS)


def test_each_run_names_a_claude_code_subject_declaration() -> None:
    for subject, run in _runs().items():
        declared = ROOT / str(run["subject_declaration"])
        data = json.loads(declared.read_text(encoding="utf-8"))
        assert (data["surface"], data["client"]["name"]) == ("claude-code-skills", "claude"), subject
        assert str(run["agent_command"]).endswith(f"collection-run {subject}")


def test_every_cited_line_is_in_its_own_subject_s_block() -> None:
    evidence = EVIDENCE.read_text(encoding="utf-8")
    for subject, run in _runs().items():
        cited = run["observed"]["collection_run"]  # type: ignore[index]
        assert isinstance(cited, list) and cited, subject
        assert _uncited(evidence, f"collection agent run: {subject} ", cited) == [], subject


_SOURCE_SUFFIX = " (source=transcript skill_listing)"


def _discovery_problems(selected: list[str], discovery_line: str) -> list[str]:
    """Every way `discovery_line` fails to show each of `selected` listed from
    the transcript. The map is PARSED and compared as a set - an empty map, or
    one missing a skill, is a problem, never a vacuous pass (counter-model
    review, #124: a substring check let `discovery={}` through for a subject
    selecting "all")."""
    if not selected:
        return ["no selected skills to check - an empty population proves nothing"]
    if not discovery_line.startswith("discovery=") or not discovery_line.endswith(_SOURCE_SUFFIX):
        return [f"not a transcript-sourced discovery line: {discovery_line!r}"]
    try:
        observed = ast.literal_eval(discovery_line[len("discovery="):-len(_SOURCE_SUFFIX)])
    except (ValueError, SyntaxError):
        return [f"discovery map does not parse: {discovery_line!r}"]
    if not isinstance(observed, dict):
        return [f"discovery is not a map: {observed!r}"]
    problems = []
    if set(observed) != set(selected):
        problems.append(f"keys {sorted(observed)} != selected {sorted(selected)}")
    problems += [f"{name}={value}" for name, value in sorted(observed.items()) if value != "listed"]
    return problems


def test_each_run_passed_and_listed_every_selected_skill_from_the_transcript() -> None:
    """The acceptance the manifest stands for, re-read from the cited lines:
    captured, PASS, EXIT=0, and a transcript-sourced discovery map whose keys
    are exactly the run's selected inventory, every one `listed`."""
    for subject, run in _runs().items():
        cited = run["observed"]["collection_run"]  # type: ignore[index]
        assert {"disposition=captured", "graded.status=PASS", "EXIT=0"} <= set(cited), subject
        [discovery] = [line for line in cited if line.startswith("discovery=")]
        selected = run["selected_skills"]
        assert isinstance(selected, list)
        declared = json.loads((ROOT / str(run["subject_declaration"])).read_text(encoding="utf-8"))
        if isinstance(declared["select"], list):
            assert sorted(declared["select"]) == sorted(selected), subject
        assert _discovery_problems(selected, discovery) == [], subject


def test_the_discovery_check_refuses_an_empty_or_partial_map() -> None:
    """Negative control for the check above: the codex-review red cases."""
    selected = ["diagnosing-bugs", "tdd"]
    assert _discovery_problems(selected, "discovery={}" + _SOURCE_SUFFIX) != []
    assert _discovery_problems(selected, "discovery={'tdd': 'listed'}" + _SOURCE_SUFFIX) != []
    assert _discovery_problems(
        selected, "discovery={'diagnosing-bugs': 'listed', 'tdd': 'not-listed'}" + _SOURCE_SUFFIX,
    ) == ["tdd=not-listed"]
    assert _discovery_problems([], "discovery={}" + _SOURCE_SUFFIX) != []
    assert _discovery_problems(selected, "discovery=UNMEASURED (no listing)") != []


def _control_problems(evidence: str, subject: str, cited: list[str]) -> list[str]:
    """The control's OWN subject block must be the unavailable one, and must
    say so and exit non-zero independently of what the manifest cites
    (counter-model review, #124: the check used to accept empty citations and
    an unavailable block ending `EXIT=0`, from any subject)."""
    if not cited:
        return ["the control cites nothing"]
    opener = f"collection agent run: {subject} "
    blocks = [
        _block(evidence[i:], opener) for i in range(len(evidence)) if evidence.startswith(opener, i)
    ]
    unavailable = [b for b in blocks if "disposition=unavailable" in b]
    if len(unavailable) != 1:
        return [f"expected exactly one unavailable block for {subject}, found {len(unavailable)}"]
    [block] = unavailable
    problems = [line for line in cited if line not in block]
    exits = [line for line in block if line.startswith("EXIT=")]
    if exits != ["EXIT=1"]:
        problems.append(f"control exit is {exits}, not EXIT=1")
    return problems


def test_the_control_is_unavailable_and_exits_nonzero() -> None:
    control = _manifest()["control"]
    assert isinstance(control, dict)
    evidence = EVIDENCE.read_text(encoding="utf-8")
    assert _control_problems(evidence, str(control["subject"]), list(control["observed"])) == []


def test_the_control_check_refuses_a_zero_exit_an_empty_citation_and_another_subject() -> None:
    evidence = EVIDENCE.read_text(encoding="utf-8")
    subject = "mattpocock-skills-claude-code"
    good = ["disposition=unavailable", "EXIT=1"]
    assert _control_problems(evidence, subject, []) != []
    assert _control_problems(evidence, "cpp-claude-code", good) != []  # no unavailable block of its own
    zero_exit = evidence.replace(
        "grading_blocked_reason=attempt disposition is 'unavailable', not captured\nEXIT=1",
        "grading_blocked_reason=attempt disposition is 'unavailable', not captured\nEXIT=0",
    )
    assert zero_exit != evidence
    assert _control_problems(zero_exit, subject, ["disposition=unavailable"]) != []


def test_the_citation_check_refuses_a_line_borrowed_from_the_other_collection() -> None:
    """Negative control: the check must be able to report the OTHER verdict.
    A line that IS in the evidence, but in the other collection's block, and a
    line that is nowhere, are both refused."""
    evidence = EVIDENCE.read_text(encoding="utf-8")
    other = _block(evidence, "collection agent run: cpp-claude-code ")
    borrowed = next(line for line in other if line.startswith("discovery="))
    opener = "collection agent run: mattpocock-skills-claude-code "
    assert _uncited(evidence, opener, [borrowed]) == [borrowed]
    assert _uncited(evidence, opener, ["graded.status=FAIL"]) == ["graded.status=FAIL"]
    assert _uncited(evidence, "collection agent run: no-such-subject ", ["EXIT=0"]) != []
