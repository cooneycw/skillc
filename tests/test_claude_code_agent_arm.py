"""#124's Claude Code agent arm manifest (`evals/claude-code-agent-arm/
run-manifest.json`) cites the live runs recorded in its `evidence/README.md`
rather than restating them. These tests prove every citation is exact and
attributed to the right collection's own printed block, so a manifest claim
cannot drift from, or outrun, the evidence it names. No model call, no Docker
call: a plain JSON structure and cross-reference check.
"""

from __future__ import annotations

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


def test_each_run_passed_and_listed_every_selected_skill_from_the_transcript() -> None:
    """The acceptance the manifest stands for, re-read from the cited lines:
    captured, PASS, EXIT=0, and a transcript-sourced discovery line naming
    every selected skill as `listed` - never UNMEASURED or not-listed."""
    for subject, run in _runs().items():
        cited = run["observed"]["collection_run"]  # type: ignore[index]
        assert {"disposition=captured", "graded.status=PASS", "EXIT=0"} <= set(cited), subject
        [discovery] = [line for line in cited if line.startswith("discovery=")]
        assert discovery.endswith("(source=transcript skill_listing)"), subject
        assert "not-listed" not in discovery and "UNMEASURED" not in discovery, subject
        declared = json.loads((ROOT / str(run["subject_declaration"])).read_text(encoding="utf-8"))
        if isinstance(declared["select"], list):
            for name in declared["select"]:
                assert f"'{name}': 'listed'" in discovery, (subject, name)


def test_the_control_is_unavailable_and_exits_nonzero() -> None:
    evidence = EVIDENCE.read_text(encoding="utf-8")
    control = _manifest()["control"]
    assert isinstance(control, dict)
    blocks = [
        _block(evidence[i:], "collection agent run: ")
        for i in range(len(evidence)) if evidence.startswith("collection agent run: ", i)
    ]
    unavailable = [b for b in blocks if "disposition=unavailable" in b]
    assert len(unavailable) == 1
    assert set(control["observed"]) <= set(unavailable[0])


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
