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
import json
from pathlib import Path

PHRASES = ("never a PASS", "skipped gates", "SKIP row")

#: Files whose phrase hits are plumbing that PRODUCES the raw marker text the
#: agent reads (shell/Python comments, and the literal verdict string
#: flow-finish-gate.sh EMITS) - never a second, interpretive copy of the
#: instruction. Classification from #270's PROVENANCE.md finding ("The #287
#: case-pairing (discrimination) obligation" section), extended in #287 P1 to
#: the same files installed as dependencies (`scripts/`, `lib/cicd/`). LIMIT:
#: this exemption is per FILE, so it does not prove every occurrence inside an
#: exempt file is non-interpretive.
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
#: (file, exact stripped line). Keyed on the exact text, so an edited line is
#: no longer reviewed and comes back as NEEDS_REVIEW, never as a pass. These
#: are the sibling routes #287's comment 6034325559 pre-registered as a risk.
REVIEWED_UNRELATED = frozenset({
    (REFERENCE_MD, "never a PASS, and never left out of the table. Its detail is the entry's"),
    (REFERENCE_MD, "SKIP rows."),
})


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


def _read(root: Path, entry: dict[str, object]) -> tuple[str, str | None, str | None]:
    """(label, text or None, coverage error or None)."""
    source = entry.get("source")
    if source:
        path = root / str(source)
        if not path.is_file():
            return str(source), None, "missing"
        try:
            return str(source), path.read_text(encoding="utf-8"), None
        except UnicodeDecodeError:
            return str(source), None, "undecodable"
    if isinstance(entry.get("content"), str):
        return f"synthetic:{entry.get('destination')}", str(entry["content"]), None
    return f"unnamed:{entry.get('destination')}", None, "no source and no inline content"


def scan(root: Path, entries: list[dict[str, object]]) -> tuple[list[dict[str, object]], list[dict[str, str]],
                                                                list[str]]:
    """(phrase hits, coverage errors, labels of files carrying the FULL
    removed sentence once whitespace is normalized)."""
    hits: list[dict[str, object]] = []
    errors: list[dict[str, str]] = []
    full_copies: list[str] = []
    for entry in entries:
        label, text, error = _read(root, entry)
        if error:
            errors.append({"file": label, "error": error})
            continue
        assert text is not None
        if _REMOVED_NORM and _REMOVED_NORM in _norm(text):
            full_copies.append(label)
        for lineno, line in enumerate(text.splitlines(), start=1):
            for phrase in PHRASES:
                if phrase not in line:
                    continue
                agent_facing = label not in NON_AGENT_FACING_FILES
                stripped = line.strip()
                is_removed_sentence = label == REFERENCE_MD and (
                    ("skipped gates" in line and "SKIP row" in line) or stripped == "a WARN row - never a PASS."
                )
                reviewed = (label, stripped) in REVIEWED_UNRELATED
                hits.append({
                    "file": label, "line": lineno, "phrase": phrase, "text": stripped,
                    "agent_facing": agent_facing,
                    "classification": (
                        "removed sentence itself" if is_removed_sentence
                        else "agent-facing, reviewed as a different instruction" if agent_facing and reviewed
                        else "agent-facing, UNREVIEWED" if agent_facing
                        else "non-agent-facing: implementation comment or the literal verdict string the "
                             "script EMITS, never an interpretive instruction the agent reads"
                    ),
                })
    return hits, errors, full_copies


_REMOVED_NORM = ""


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
    intact_hits, intact_errors, intact_copies = scan(args.intact_root, entries)
    degraded_hits, degraded_errors, degraded_copies = scan(args.degraded_root, entries)
    intact_diag = json.loads(args.intact_diagnose.read_text(encoding="utf-8"))
    degraded_diag = json.loads(args.degraded_diagnose.read_text(encoding="utf-8"))

    positive_control_held = REFERENCE_MD in intact_copies
    unreviewed = [h for h in degraded_hits if h["classification"] == "agent-facing, UNREVIEWED"]
    # One verdict, four values, checked in order. Only HOLDS exits 0.
    if intact_errors or degraded_errors or not positive_control_held \
            or not (_diagnose_ok(intact_diag) and _diagnose_ok(degraded_diag)):
        verdict = "UNKNOWN"      # coverage or the control failed: absence of evidence, not of the instruction
    elif degraded_copies:
        verdict = "SURVIVES"     # the full removed sentence is still installed somewhere
    elif unreviewed:
        verdict = "NEEDS_REVIEW"  # an unreviewed agent-facing line shares a phrase; not shown to survive
    else:
        verdict = "HOLDS"

    evidence = {
        "evidence_schema": 2,
        "purpose": (
            "skillc#287 pilot discrimination declaration, mutation.diagnose_evidence for gate-stops-early's "
            f"degraded arm ({args.inventory.parent.parent.name}, flow-check skill, reference.md)."
        ),
        "removed_text": args.removed_text,
        "mutated_digest": args.mutated_digest,
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
            "unreviewed_agent_facing_in_degraded": unreviewed,
            "verdict": verdict,
            "claim_holds": verdict == "HOLDS",
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(evidence, f, indent=1)
        f.write("\n")
    print(f"wrote {args.out}: verdict={verdict}, closure={len(entries)}, intact_hits={len(intact_hits)}, "
          f"degraded_hits={len(degraded_hits)}, coverage_errors={len(intact_errors) + len(degraded_errors)}, "
          f"degraded_full_copies={len(degraded_copies)}, unreviewed={len(unreviewed)}")
    return 0 if verdict == "HOLDS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
