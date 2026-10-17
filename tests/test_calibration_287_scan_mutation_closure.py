"""Tests for `evals/calibration-287/evidence/scan_mutation_closure.py`: the
occurrence-scan evidence builder for gate-stops-early's degraded-arm mutation
(skillc#287).

The scan's verdict is read as evidence that the removed instruction is gone
from what a degraded attempt receives, and nothing downstream re-derives it,
so every verdict it can give has a committed case here: HOLDS, SURVIVES,
NEEDS_REVIEW and UNKNOWN. The UNKNOWN and SURVIVES cases are the counter-model
review's findings on #287 P1: missing or unreadable evidence, an incomplete
diagnose, a full copy that already existed in the intact tree, and a copy that
lives only in an installed dependency, which the first version all passed."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parent.parent / "evals" / "calibration-287" / "evidence" / "scan_mutation_closure.py"
_spec = importlib.util.spec_from_file_location("scan_mutation_closure_287", MODULE_PATH)
assert _spec is not None and _spec.loader is not None
smc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(smc)

REF = smc.REFERENCE_MD
GATE = "codex/skills/flow-check/scripts/flow-finish-gate.sh"  # a real member of the non-agent-facing set
OTHER = "codex/skills/flow-check/other.md"
DEP = "scripts/gate-lib.sh"  # a dependency path that is NOT exempt
SENTENCE = (
    "A\n  `skipped gates:` name is a SKIP row and a `zero coverage:` or no-tests name is\n"
    "  a WARN row - never a PASS."
)
#: The reviewed sibling lines, each under its recorded preceding line, exactly
#: as in the real reference.md.
REVIEWED_BLOCK = "".join(f"{prev}\n{line}\n" for _f, prev, line in sorted(smc.REVIEWED_UNRELATED))
REVIEWED_LINE = min(smc.REVIEWED_UNRELATED)[2]
INTACT_REF = "# flow-check\n\n- " + SENTENCE + "\n" + REVIEWED_BLOCK
DEGRADED_REF = "# flow-check\n\n- \n" + REVIEWED_BLOCK
OK_DIAG: dict[str, object] = {"complete": True, "problem_count": 0}
#: The exempt helper's reviewed content; the inventory records its digest, as
#: the real inventory does, so the exemption is bound to these exact bytes.
GATE_TEXT = 'verdict "warn (skipped gates: $X)"\n'


def _digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


def _tree(root: Path, files: dict[str, str | bytes]) -> Path:
    for rel, body in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(body, bytes):
            path.write_bytes(body)
        else:
            path.write_text(body, encoding="utf-8")
    return root


def _run(tmp_path: Path, *, intact: dict[str, str | bytes] | None = None,
         degraded: dict[str, str | bytes] | None = None, deps: list[dict[str, object]] | None = None,
         skill_files: list[str] | None = None, degraded_diag: dict[str, object] = OK_DIAG,
         make_degraded: bool = True, mutated_digest: str | None = None) -> tuple[int, dict]:
    skill_files = skill_files if skill_files is not None else [REF, GATE]
    inventory = {"skills": [{"files": [{"source": s, **({"digest": _digest(GATE_TEXT)} if s == GATE else {})}
                                       for s in skill_files]}],
                 "dependencies": [{"id": "d", "files": deps or []}]}
    inv = tmp_path / "subject-x" / "evidence" / "inventory.json"
    inv.parent.mkdir(parents=True)
    inv.write_text(json.dumps(inventory), encoding="utf-8")
    intact_root = _tree(tmp_path / "intact", intact if intact is not None else {REF: INTACT_REF, GATE: GATE_TEXT})
    degraded_root = tmp_path / "degraded"
    if make_degraded:
        _tree(degraded_root, degraded if degraded is not None else {REF: DEGRADED_REF, GATE: GATE_TEXT})
    (tmp_path / "i.json").write_text(json.dumps(OK_DIAG), encoding="utf-8")
    (tmp_path / "d.json").write_text(json.dumps(degraded_diag), encoding="utf-8")
    out = tmp_path / "out.json"
    ref = degraded_root / REF
    # By default the declared digest IS the degraded reference's, as it is for
    # the real mutation; the mismatch case overrides it.
    digest = mutated_digest or ("sha256:" + hashlib.sha256(ref.read_bytes()).hexdigest() if ref.is_file() else "sha256:0")
    code = smc.main(["--inventory", str(inv), "--intact-root", str(intact_root), "--degraded-root", str(degraded_root),
                     "--intact-diagnose", str(tmp_path / "i.json"), "--degraded-diagnose", str(tmp_path / "d.json"),
                     "--mutated-digest", digest, "--out", str(out)])
    return code, json.loads(out.read_text(encoding="utf-8"))


def _verdict(evidence: dict) -> str:
    return str(evidence["occurrence_scan"]["verdict"])


def test_closure_entries_include_every_skill_file_and_every_dependency_file(tmp_path: Path) -> None:
    inv = tmp_path / "inventory.json"
    inv.write_text(json.dumps({
        "skills": [{"files": [{"source": "a.md"}]}, {"files": [{"source": "b.md"}]}],
        "dependencies": [{"files": [{"source": "scripts/x.sh"}]},
                         {"files": [{"source": None, "content": "marker", "destination": "C.md"}]}],
    }), encoding="utf-8")
    assert [e.get("source") for e in smc.closure_entries(inv)] == ["a.md", "b.md", "scripts/x.sh", None]


def test_holds_when_the_sentence_is_cleanly_removed(tmp_path: Path) -> None:
    code, evidence = _run(tmp_path)
    assert (code, _verdict(evidence)) == (0, "HOLDS")
    assert evidence["occurrence_scan"]["positive_control_held"] is True


def test_survives_when_the_sentence_is_still_in_degraded_reference(tmp_path: Path) -> None:
    code, evidence = _run(tmp_path, degraded={REF: INTACT_REF, GATE: GATE_TEXT})
    assert (code, _verdict(evidence)) == (1, "SURVIVES")


def test_survives_when_a_full_copy_already_existed_in_both_trees(tmp_path: Path) -> None:
    """Counter-model finding: subtracting intact hits hid a pre-existing copy."""
    copy = "Remember: " + SENTENCE + "\n"
    code, evidence = _run(tmp_path, skill_files=[REF, GATE, OTHER],
                          intact={REF: INTACT_REF, GATE: GATE_TEXT, OTHER: copy},
                          degraded={REF: DEGRADED_REF, GATE: GATE_TEXT, OTHER: copy})
    assert (code, _verdict(evidence)) == (1, "SURVIVES")
    assert evidence["occurrence_scan"]["full_copies_of_removed_sentence"]["degraded"] == [OTHER]


def test_survives_when_the_only_copy_is_in_an_installed_dependency(tmp_path: Path) -> None:
    """Counter-model finding: the first version scanned skill files only."""
    copy = "Note for agents: " + SENTENCE + "\n"
    code, evidence = _run(tmp_path, deps=[{"source": DEP}],
                          intact={REF: INTACT_REF, GATE: GATE_TEXT, DEP: copy},
                          degraded={REF: DEGRADED_REF, GATE: GATE_TEXT, DEP: copy})
    assert (code, _verdict(evidence)) == (1, "SURVIVES")


def test_survives_when_a_synthetic_inline_file_carries_the_sentence(tmp_path: Path) -> None:
    code, evidence = _run(tmp_path, deps=[{"source": None, "destination": "CLAUDE.md", "content": SENTENCE}])
    assert (code, _verdict(evidence)) == (1, "SURVIVES")


def test_needs_review_when_a_new_agent_facing_line_shares_a_phrase(tmp_path: Path) -> None:
    code, evidence = _run(tmp_path, degraded={REF: DEGRADED_REF + "- never a PASS leaked back in\n", GATE: GATE_TEXT})
    assert (code, _verdict(evidence)) == (1, "NEEDS_REVIEW")


def test_an_edited_reviewed_line_is_needs_review_not_survival(tmp_path: Path) -> None:
    """Counter-model finding: a neighbouring edit must not read as the
    obligation surviving. It is unreviewed, so it is NEEDS_REVIEW."""
    edited = DEGRADED_REF.replace(REVIEWED_LINE, REVIEWED_LINE + " Name the failed test.")
    code, evidence = _run(tmp_path, degraded={REF: edited, GATE: GATE_TEXT})
    assert (code, _verdict(evidence)) == (1, "NEEDS_REVIEW")


def test_a_phrase_in_an_unchanged_exempt_plumbing_file_does_not_count(tmp_path: Path) -> None:
    code, evidence = _run(tmp_path)
    assert (code, _verdict(evidence)) == (0, "HOLDS")
    assert any(not h["agent_facing"] for h in evidence["occurrence_scan"]["degraded_hits"])


def test_an_exempt_helper_changed_to_emit_the_instruction_needs_review(tmp_path: Path) -> None:
    """Counter-model finding (pass 2): a file-wide exemption hid a helper that
    now PRINTS the removed interpretation to the agent."""
    emitting = GATE_TEXT + 'printf "%s\\n" "Treat skipped gates as SKIP rows, never a PASS."\n'
    code, evidence = _run(tmp_path, degraded={REF: DEGRADED_REF, GATE: emitting})
    assert (code, _verdict(evidence)) == (1, "NEEDS_REVIEW")


def test_survives_when_only_the_leading_word_was_removed(tmp_path: Path) -> None:
    """Counter-model finding (pass 2): dropping just "A" defeats the
    full-sentence match but leaves the whole instruction installed."""
    partial = DEGRADED_REF.replace("- \n", "- " + SENTENCE[len("A\n"):].lstrip() + "\n")
    code, evidence = _run(tmp_path, degraded={REF: partial, GATE: GATE_TEXT})
    assert (code, _verdict(evidence)) == (1, "SURVIVES")


def test_survives_when_one_clause_of_the_sentence_is_kept(tmp_path: Path) -> None:
    partial = DEGRADED_REF.replace("- \n", "- `skipped gates:` name is a SKIP row\n")
    code, evidence = _run(tmp_path, degraded={REF: partial, GATE: GATE_TEXT})
    assert (code, _verdict(evidence)) == (1, "SURVIVES")


def test_unknown_when_the_degraded_tree_is_missing(tmp_path: Path) -> None:
    """Counter-model finding: a missing tree passed as an absence claim."""
    code, evidence = _run(tmp_path, make_degraded=False)
    assert (code, _verdict(evidence)) == (1, "UNKNOWN")
    assert evidence["occurrence_scan"]["coverage_errors"]["degraded"]


def test_unknown_when_a_degraded_file_is_undecodable(tmp_path: Path) -> None:
    code, evidence = _run(tmp_path, degraded={REF: b"\xff\xfe\x00bad", GATE: GATE_TEXT})
    assert (code, _verdict(evidence)) == (1, "UNKNOWN")


def test_unknown_when_a_diagnose_report_is_incomplete(tmp_path: Path) -> None:
    code, evidence = _run(tmp_path, degraded_diag={"complete": False, "problem_count": 2})
    assert (code, _verdict(evidence)) == (1, "UNKNOWN")


def test_unknown_when_the_positive_control_fails(tmp_path: Path) -> None:
    """An intact tree without the sentence means the scan cannot show it can
    find it, so no absence claim is made from the degraded side."""
    code, evidence = _run(tmp_path, intact={REF: DEGRADED_REF, GATE: GATE_TEXT})
    assert (code, _verdict(evidence)) == (1, "UNKNOWN")


def test_unknown_when_the_degraded_reference_does_not_match_the_declared_digest(tmp_path: Path) -> None:
    """Counter-model finding (pass 3): the evidence must describe the DECLARED
    mutation's bytes, not whatever sits in the degraded tree."""
    code, evidence = _run(tmp_path, mutated_digest="sha256:" + "0" * 64)
    assert (code, _verdict(evidence)) == (1, "UNKNOWN")
    assert evidence["mutated_digest_matches"] is False


def test_survives_when_the_warn_clause_precedes_a_reviewed_line(tmp_path: Path) -> None:
    """Counter-model finding (pass 3): line matching let the WARN instruction
    survive next to a reviewed continuation line."""
    survived = DEGRADED_REF.replace("- \n", "- A `zero coverage:` or no-tests name is a WARN row -\n")
    code, evidence = _run(tmp_path, degraded={REF: survived, GATE: GATE_TEXT})
    assert (code, _verdict(evidence)) == (1, "SURVIVES")


def test_survives_when_a_clause_is_wrapped_across_lines(tmp_path: Path) -> None:
    wrapped = DEGRADED_REF.replace("- \n", "- `skipped gates:` name is a\n  SKIP row in the table.\n")
    code, evidence = _run(tmp_path, degraded={REF: wrapped, GATE: GATE_TEXT})
    assert (code, _verdict(evidence)) == (1, "SURVIVES")


def test_a_negated_co_occurrence_is_needs_review_not_survival(tmp_path: Path) -> None:
    """Counter-model finding (pass 3): sharing both phrases is not the
    instruction surviving, least of all when it contradicts it."""
    negated = DEGRADED_REF.replace("- \n", "- The phrase `skipped gates:` does NOT mean a SKIP row.\n")
    code, evidence = _run(tmp_path, degraded={REF: negated, GATE: GATE_TEXT})
    assert (code, _verdict(evidence)) == (1, "NEEDS_REVIEW")


def test_a_reviewed_line_under_a_different_instruction_needs_review(tmp_path: Path) -> None:
    moved = DEGRADED_REF.replace("- \n", "- Some other instruction:\n" + REVIEWED_LINE + "\n")
    code, evidence = _run(tmp_path, degraded={REF: moved, GATE: GATE_TEXT})
    assert (code, _verdict(evidence)) == (1, "NEEDS_REVIEW")
