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
        --inventory ../../subjects/cpp-codex-flow-check-ea6dbfa/evidence/inventory.json \\
        --intact-root /path/to/claude-power-pack-checkout-at-ea6dbfa \\
        --degraded-root /path/to/degraded-snapshot \\
        --out discrimination-mutation-diagnose.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

PHRASES = ("never a PASS", "skipped gates", "SKIP row")

#: Classification, from #270's own PROVENANCE.md finding ("The #287
#: case-pairing (discrimination) obligation" section) - confirmed directly
#: against the measured hits, not reasoned about in the abstract. These
#: files are the plumbing that PRODUCES the raw marker text the agent
#: reads (shell/Python comments, and the literal verdict string flow-
#: finish-gate.sh EMITS) - never a second, interpretive copy of the
#: instruction telling the agent what to do with it.
NON_AGENT_FACING_FILES = frozenset({
    "codex/skills/flow-check/lib/cicd/runner.py",
    "codex/skills/flow-check/lib/cicd/steps.py",
    "codex/skills/flow-check/scripts/flow-finish-gate.sh",
})

REFERENCE_MD = "codex/skills/flow-check/reference.md"


def closure_sources(inventory_path: Path) -> list[str]:
    with open(inventory_path, encoding="utf-8") as f:
        inventory = json.load(f)
    return [entry["source"] for skill in inventory["skills"] for entry in skill["files"]]


def scan(root: Path, sources: list[str]) -> list[dict[str, object]]:
    hits: list[dict[str, object]] = []
    for rel in sources:
        path = root / rel
        if not path.is_file():
            hits.append({"file": rel, "error": "missing"})
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for phrase in PHRASES:
                if phrase not in line:
                    continue
                agent_facing = rel not in NON_AGENT_FACING_FILES
                is_removed_sentence = rel == REFERENCE_MD and (
                    ("skipped gates" in line and "SKIP row" in line) or line.strip() == "a WARN row - never a PASS."
                )
                hits.append({
                    "file": rel, "line": lineno, "phrase": phrase, "text": line.strip(),
                    "agent_facing": agent_facing,
                    "classification": (
                        "removed sentence itself" if is_removed_sentence
                        else "agent-facing, unrelated sentence (same file, different bullet)" if agent_facing
                        else "non-agent-facing: implementation comment or the literal verdict string the "
                             "script EMITS, never an interpretive instruction the agent reads"
                    ),
                })
    return hits


def main(argv: list[str] | None = None) -> int:
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
        "sha256:9149e393bb1d9e40adb97dca85774e23f77317a21e6bff832c160055c726234d"
    ))
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)

    sources = closure_sources(args.inventory)
    intact_hits = scan(args.intact_root, sources)
    degraded_hits = scan(args.degraded_root, sources)

    def unrelated_agent_facing(hits: list[dict[str, object]]) -> set[tuple[object, object, object]]:
        """(file, phrase, text) for every agent-facing hit that is NOT the
        removed sentence itself - keyed on TEXT, never line number, since
        removing two lines shifts every later line number without adding
        any new sentence. A pre-existing unrelated bullet (this task's own
        "...three SKIP rows." sentence, a different bullet than the one
        removed) sharing one of the three generic phrases is expected and
        harmless; what the claim actually cares about is whether DEGRADED
        introduces an agent-facing hit intact never had."""
        return {
            (h["file"], h["phrase"], h["text"]) for h in hits
            if h.get("agent_facing") and h.get("classification") != "removed sentence itself" and "error" not in h
        }

    intact_unrelated = unrelated_agent_facing(intact_hits)
    degraded_unrelated = unrelated_agent_facing(degraded_hits)
    leftover = sorted(degraded_unrelated - intact_unrelated)
    removed_sentence_gone = not any(h.get("classification") == "removed sentence itself" for h in degraded_hits)
    positive_control_held = any(h.get("classification") == "removed sentence itself" for h in intact_hits)

    evidence = {
        "evidence_schema": 1,
        "purpose": (
            "skillc#287 pilot discrimination declaration, mutation.diagnose_evidence for gate-stops-early's "
            "degraded arm (cpp-codex-flow-check-ea6dbfa, flow-check skill, reference.md)."
        ),
        "removed_text": args.removed_text,
        "mutated_digest": args.mutated_digest,
        "closure_file_count": len(sources),
        "closure_source": str(args.inventory),
        "diagnose": {
            "intact": json.loads(args.intact_diagnose.read_text(encoding="utf-8")),
            "degraded": json.loads(args.degraded_diagnose.read_text(encoding="utf-8")),
            "conclusion": (
                "Both reports are expected to show 0 problems and complete=true - removing one prose "
                "sentence never breaks a declared reference, so a clean diagnose on EITHER side cannot by "
                "itself show whether the removed instruction still appears elsewhere. That is what the "
                "occurrence scan below is for; diagnose is included here as the first, necessary-but-"
                "insufficient check, not skipped."
            ),
        },
        "occurrence_scan": {
            "phrases": list(PHRASES),
            "positive_control_held": positive_control_held,
            "intact_hit_count": len(intact_hits),
            "intact_hits": intact_hits,
            "degraded_hit_count": len(degraded_hits),
            "degraded_hits": degraded_hits,
            "removed_sentence_confirmed_absent_in_degraded": removed_sentence_gone,
            "new_agent_facing_hits_in_degraded_not_present_in_intact": [
                {"file": f, "phrase": p, "text": t} for f, p, t in leftover
            ],
            "claim_holds": positive_control_held and removed_sentence_gone and not leftover,
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(evidence, f, indent=1)
        f.write("\n")
    print(f"wrote {args.out}: claim_holds={evidence['occurrence_scan']['claim_holds']}, "
          f"intact={len(intact_hits)}, degraded={len(degraded_hits)}, leftover={len(leftover)}")
    return 0 if evidence["occurrence_scan"]["claim_holds"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
