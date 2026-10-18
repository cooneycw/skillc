#!/usr/bin/env python3
"""Re-runnable evidence builder for skillc#287's degraded-arm mutation
(gate-stops-early's discrimination case): combines `skillc profile
diagnose`'s own closure-problem report with an occurrence scan of the whole
installed closure for the removed sentence's distinctive phrases.

`skillc profile diagnose` answers "does every declared reference still
resolve" - removing one prose sentence from `reference.md` never breaks
that, so a clean diagnose on its own cannot show whether the removed
INSTRUCTION still appears elsewhere in what gets installed. This script
answers that second question directly, over the real closure (every file
`evidence/inventory.json` says this profile actually installs - never a
blind grep over the whole claude-power-pack checkout, which would scan far
more than what a subject ever receives).

Run against the INTACT checkout first (the positive control: the scan must
find the sentence in `reference.md` there) before trusting a result against
the DEGRADED one - an occurrence scan that cannot find a real occurrence
proves nothing by finding none.

Usage:
    python3 scan_mutation_closure.py \\
        --inventory ../../subjects/cpp-codex-flow-check-86641e8/evidence/inventory.json \\
        --intact-root /path/to/claude-power-pack-checkout-at-86641e8 \\
        --degraded-root /path/to/degraded-snapshot \\
        --out discrimination-mutation-diagnose.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

PHRASES = ("never a PASS", "skipped gates", "SKIP row")

#: Files whose phrase hits are plumbing that PRODUCES the raw marker text the
#: agent reads (shell/Python comments, and the literal verdict string
#: flow-finish-gate.sh EMITS) - never a second, interpretive copy of the
#: instruction. Classification from #270's PROVENANCE.md finding ("The #287
#: case-pairing (discrimination) obligation" section), extended in #287 P1 to
#: the same files installed as dependencies (`scripts/`, `lib/cicd/`). The
#: exemption is bound to VERIFIED CONTENT: it applies only while the file's
#: bytes hash to the digest the inventory recorded at the pin (the content that
#: was reviewed). An exempt file that changed, for example to print the removed
#: interpretation to the agent, loses its exemption and its hits need review.
NON_AGENT_FACING_FILES = frozenset({
    "codex/skills/flow-check/lib/cicd/runner.py",
    "codex/skills/flow-check/lib/cicd/steps.py",
    "codex/skills/flow-check/scripts/flow-finish-gate.sh",
    "lib/cicd/runner.py",
    "lib/cicd/steps.py",
    "scripts/flow-finish-gate.sh",
})

REFERENCE_MD = "codex/skills/flow-check/reference.md"

#: Agent-facing lines that share a generic phrase with the removed sentence
#: but were each REVIEWED as a different instruction (#287 P1, at 86641e8):
#: (file, exact stripped PRECEDING line, exact stripped line). Bound to the
#: preceding line too, so a reviewed continuation line moved under a different
#: instruction is no longer reviewed. An edited line, or one in a new context,
#: comes back as NEEDS_REVIEW, never as a pass. These are the sibling routes
#: #287's comment 6034325559 pre-registered as a risk.
REVIEWED_UNRELATED = frozenset({
    (REFERENCE_MD, "not-run` rather than running at all. That step is its own **NOT_RUN** row -",
     "never a PASS, and never left out of the table. Its detail is the entry's"),
    (REFERENCE_MD, "- `FLOW_FINISH_GATE: skipped` (exit 4) - no runner and no Makefile gates: three",
     "SKIP rows."),
})

#: The removed sentence's two specific instructions, matched across
#: whitespace-normalized FILE text (so a clause wrapped over lines, or split
#: from a reviewed continuation line, is still found). Either one surviving
#: anywhere in an installed, non-exempt file is SURVIVES. The generic
#: "never a PASS" is NOT a clause: it also ends reviewed sibling bullets.
REMOVED_CLAUSES = (
    "`skipped gates:` name is a SKIP row",
    "`zero coverage:` or no-tests name is a WARN row",
)


def _norm(text: str) -> str:
    return " ".join(text.split())


def closure_entries(inventory_path: Path) -> list[dict[str, object]]:
    """Every installed file the inventory declares: each skill's files AND
    each dependency's files (#287 P1: the scan covers the whole installed
    closure). A file with inline `content` (a synthetic entry) is scanned from
    that content; one with neither a source nor content is reported."""
    with open(inventory_path, encoding="utf-8") as f:
        inventory = json.load(f)
    entries = [entry for skill in inventory["skills"] for entry in skill["files"]]
    entries += [entry for dep in inventory.get("dependencies", []) for entry in dep.get("files", [])]
    return entries


def closure_sources(inventory_path: Path) -> list[str]:
    return [str(e["source"]) for e in closure_entries(inventory_path) if e.get("source")]


def _read(root: Path, entry: dict[str, object]) -> tuple[str, str | None, str | None, bool]:
    """(label, text or None, coverage error or None, content matches the
    inventory's recorded digest)."""
    source = entry.get("source")
    if source:
        path = root / str(source)
        if not path.is_file():
            return str(source), None, "missing", False
        data = path.read_bytes()
        verified = entry.get("digest") == "sha256:" + hashlib.sha256(data).hexdigest()
        try:
            return str(source), data.decode("utf-8"), None, verified
        except UnicodeDecodeError:
            return str(source), None, "undecodable", False
    if isinstance(entry.get("content"), str):
        return f"synthetic:{entry.get('destination')}", str(entry["content"]), None, False
    return f"unnamed:{entry.get('destination')}", None, "no source and no inline content", False


def _is_removed_piece(line: str) -> bool:
    """A line that is itself a piece of the removed sentence (at least three
    words, contained in it once whitespace is normalized)."""
    n = _norm(line)
    return bool(_REMOVED_NORM) and len(n.split()) >= 3 and n in _REMOVED_NORM


def scan(root: Path, entries: list[dict[str, object]]) -> tuple[list[dict[str, object]], list[dict[str, str]],
                                                                list[str], list[dict[str, str]]]:
    """(phrase hits, coverage errors, labels of files carrying the FULL removed
    sentence, and every removed clause found in an installed non-exempt file),
    all matched on whitespace-normalized text."""
    hits: list[dict[str, object]] = []
    errors: list[dict[str, str]] = []
    full_copies: list[str] = []
    clauses: list[dict[str, str]] = []
    for entry in entries:
        label, text, error, verified = _read(root, entry)
        if error:
            errors.append({"file": label, "error": error})
            continue
        assert text is not None
        normalized = _norm(text)
        if _REMOVED_NORM and _REMOVED_NORM in normalized:
            full_copies.append(label)
        if not (label in NON_AGENT_FACING_FILES and verified):
            clauses += [{"file": label, "clause": c} for c in REMOVED_CLAUSES if _norm(c) in normalized]
        prev = ""
        for lineno, line in enumerate(text.splitlines(), start=1):
            for phrase in PHRASES:
                if phrase not in line:
                    continue
                exempt = label in NON_AGENT_FACING_FILES
                agent_facing = not (exempt and verified)
                stripped = line.strip()
                is_removed_sentence = _is_removed_piece(line)
                reviewed = (label, prev, stripped) in REVIEWED_UNRELATED
                hits.append({
                    "file": label, "line": lineno, "phrase": phrase, "text": stripped,
                    "agent_facing": agent_facing,
                    "classification": (
                        "removed sentence itself" if is_removed_sentence
                        else "agent-facing, reviewed as a different instruction" if agent_facing and reviewed
                        else "exempt file changed from its inventoried content: UNREVIEWED" if exempt and not verified
                        else "agent-facing, UNREVIEWED" if agent_facing
                        else "non-agent-facing: implementation comment or the literal verdict string the "
                             "script EMITS, never an interpretive instruction the agent reads"
                    ),
                })
            if line.strip():
                prev = line.strip()
    return hits, errors, full_copies, clauses


_REMOVED_NORM = ""

#: What the success verdict does and does not mean (orchestrator ruling on
#: #287 P1, 2026-10-17). Written into the evidence beside the verdict.
VERDICT_MEANING = (
    "NO_TEXTUAL_SURVIVOR means only: at the verified mutated_digest, no full copy, no removed clause and no "
    "3+-word fragment of the removed sentence was found in any installed non-exempt file, under these matching "
    "rules. It is a NECESSARY but NOT SUFFICIENT textual check, NOT evidence that the obligation is absent: a "
    "text scan cannot rule out a paraphrase or another surface form. The evidence that the degraded arm is "
    "degraded is the pre-registered discrimination pilot (P1-P6: no main study if no difference is "
    "detectable), per #287 comment 6034325559's risk note."
)


def _diagnose_ok(report: object) -> bool:
    return isinstance(report, dict) and report.get("complete") is True and report.get("problem_count") == 0


def main(argv: list[str] | None = None) -> int:
    global _REMOVED_NORM
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--intact-root", required=True, type=Path)
    parser.add_argument("--degraded-root", required=True, type=Path)
    parser.add_argument("--intact-diagnose", required=True, type=Path,
                        help="output of: skillc profile diagnose profile.json --repo <intact checkout>")
    parser.add_argument("--degraded-diagnose", required=True, type=Path,
                        help="output of: skillc profile diagnose profile.json --snapshot <degraded root>")
    parser.add_argument("--removed-text", default=(
        "A\n  `skipped gates:` name is a SKIP row and a `zero coverage:` or no-tests name is\n"
        "  a WARN row - never a PASS."
    ))
    parser.add_argument("--mutated-digest", default=(
        "sha256:edb26e56feac59ec548bc44afbbfeec54d970e95110c4506fa4be0cd9e8436ea"
    ))
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    _REMOVED_NORM = _norm(args.removed_text)

    entries = closure_entries(args.inventory)
    intact_hits, intact_errors, intact_copies, _intact_clauses = scan(args.intact_root, entries)
    degraded_hits, degraded_errors, degraded_copies, degraded_clauses = scan(args.degraded_root, entries)
    # The evidence is about the DECLARED mutation: the degraded reference file
    # must hash to the declared digest, or the scan describes other bytes.
    degraded_ref = args.degraded_root / REFERENCE_MD
    measured_digest = ("sha256:" + hashlib.sha256(degraded_ref.read_bytes()).hexdigest()
                       if degraded_ref.is_file() else None)
    digest_matches = measured_digest == args.mutated_digest
    intact_diag = json.loads(args.intact_diagnose.read_text(encoding="utf-8"))
    degraded_diag = json.loads(args.degraded_diagnose.read_text(encoding="utf-8"))

    positive_control_held = REFERENCE_MD in intact_copies
    unreviewed = [h for h in degraded_hits if str(h["classification"]).endswith("UNREVIEWED")]
    #: A degraded line that is still a PIECE of the removed sentence (a partial
    #: removal) is the obligation surviving, not a clean removal. A line that
    #: merely shares phrases (even one negating the instruction) is not a
    #: piece: it is unreviewed, so NEEDS_REVIEW.
    fragments = [h for h in degraded_hits if h["classification"] == "removed sentence itself"]
    # One verdict, four values, checked in order. Only NO_TEXTUAL_SURVIVOR
    # exits 0, and it is a NECESSARY-but-NOT-SUFFICIENT textual check (see
    # VERDICT_MEANING): it is never evidence that the obligation is absent.
    if intact_errors or degraded_errors or not positive_control_held or not digest_matches \
            or not (_diagnose_ok(intact_diag) and _diagnose_ok(degraded_diag)):
        verdict = "UNKNOWN"      # coverage or the control failed: absence of evidence, not of the instruction
    elif degraded_copies or degraded_clauses or fragments:
        verdict = "SURVIVES"     # the removed sentence, whole or in part, is still installed
    elif unreviewed:
        verdict = "NEEDS_REVIEW"  # an unreviewed agent-facing line shares a phrase; not shown to survive
    else:
        verdict = "NO_TEXTUAL_SURVIVOR"  # see VERDICT_MEANING: textual, not semantic

    evidence = {
        "evidence_schema": 2,
        "purpose": (
            "skillc#287 pilot discrimination declaration, mutation.diagnose_evidence for gate-stops-early's "
            f"degraded arm ({args.inventory.parent.parent.name}, flow-check skill, reference.md)."
        ),
        "removed_text": args.removed_text,
        "mutated_digest": args.mutated_digest,
        "measured_degraded_reference_digest": measured_digest,
        "mutated_digest_matches": digest_matches,
        "closure_file_count": len(entries),
        "closure_source": str(args.inventory),
        "diagnose": {
            "intact": intact_diag,
            "degraded": degraded_diag,
            "both_complete_with_zero_problems": _diagnose_ok(intact_diag) and _diagnose_ok(degraded_diag),
            "conclusion": (
                "Both reports must show 0 problems and complete=true. Removing one prose sentence never "
                "breaks a declared reference, so a clean diagnose is necessary but cannot by itself show "
                "whether the removed instruction still appears elsewhere: the occurrence scan answers that."
            ),
        },
        "occurrence_scan": {
            "phrases": list(PHRASES),
            "coverage_errors": {"intact": intact_errors, "degraded": degraded_errors},
            "positive_control_held": positive_control_held,
            "full_copies_of_removed_sentence": {"intact": intact_copies, "degraded": degraded_copies},
            "intact_hit_count": len(intact_hits),
            "intact_hits": intact_hits,
            "degraded_hit_count": len(degraded_hits),
            "degraded_hits": degraded_hits,
            "removed_clauses_in_degraded": degraded_clauses,
            "removed_sentence_fragments_in_degraded": fragments,
            "unreviewed_agent_facing_in_degraded": unreviewed,
            "verdict": verdict,
            "verdict_meaning": VERDICT_MEANING,
            "textual_check_passed": verdict == "NO_TEXTUAL_SURVIVOR",
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(evidence, f, indent=1)
        f.write("\n")
    print(f"wrote {args.out}: verdict={verdict}, closure={len(entries)}, intact_hits={len(intact_hits)}, "
          f"degraded_hits={len(degraded_hits)}, coverage_errors={len(intact_errors) + len(degraded_errors)}, "
          f"degraded_full_copies={len(degraded_copies)}, unreviewed={len(unreviewed)}")
    return 0 if verdict == "NO_TEXTUAL_SURVIVOR" else 1


if __name__ == "__main__":
    raise SystemExit(main())
