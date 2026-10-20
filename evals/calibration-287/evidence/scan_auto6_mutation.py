#!/usr/bin/env python3
"""Re-runnable evidence builder for skillc#287 option 1's degraded arm
(gate-stops-early-auto6, profile cpp-codex-flow-auto-86641e8-step6): the WHOLE
verdict-rules block of flow-auto's `reference.md` (lines 1221-1262 at
claude-power-pack 86641e8) is removed, and this script checks the textual
consequence over the closure the profile actually installs.

It is the auto6 counterpart of `scan_mutation_closure.py`, which is specific to
flow-check's one removed sentence and stays byte-unchanged (the approved
option-0 declaration's evidence was built by it). The matching rule here is
the RUNNER's own (`calibration_run.require_no_delivered_survivor`): a delivered
file still carries the removed text whole, or any line of three or more words
that is itself contained in it, on whitespace-normalized text.

Positive control first: against the INTACT closure the same rule must find the
block in `reference.md` (whole, and line by line). A scan that cannot find a
real occurrence proves nothing by finding none.

Usage (a snapshot or a checkout at the pin can be the intact root):
    python3 scan_auto6_mutation.py \\
        --inventory evals/subjects/cpp-codex-flow-auto-86641e8-step6/evidence/inventory.json \\
        --intact-root /path/to/claude-power-pack-at-86641e8 \\
        --out evals/calibration-287/evidence/auto6-mutation-diagnose.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REFERENCE_MD = "codex/skills/flow-auto/reference.md"
#: The removed block, by line number at the pin (1-based, inclusive).
BLOCK_LINES = (1221, 1262)

#: What the success verdict does and does not mean: the same reading as
#: scan_mutation_closure.py's (orchestrator ruling on #287 P1, 2026-10-17).
VERDICT_MEANING = (
    "NO_TEXTUAL_SURVIVOR means only: at the verified mutated_digest, no full copy and no 3+-word line of the "
    "removed block was found in any installed file, under the runner's own matching rule. It is a NECESSARY "
    "but NOT SUFFICIENT textual check, NOT evidence that the obligation is absent: a text scan cannot rule out "
    "a paraphrase, another surface form, or the gate's own runtime warnings (pre-registration i). The evidence "
    "that the degraded arm is degraded is the pre-registered pre-check and pilot."
)


def _norm(text: str) -> str:
    return " ".join(text.split())


def removed_block(reference: bytes) -> str:
    """Lines BLOCK_LINES of the intact reference.md, each with its newline."""
    lines = reference.decode("utf-8").splitlines(keepends=True)
    first, last = BLOCK_LINES
    return "".join(lines[first - 1:last])


def closure_entries(inventory: dict[str, object]) -> list[dict[str, object]]:
    skills = inventory["skills"]
    deps = inventory.get("dependencies", [])
    assert isinstance(skills, list) and isinstance(deps, list)
    return ([entry for skill in skills for entry in skill["files"]]
            + [entry for dep in deps for entry in dep.get("files", [])])


def _text(root: Path, entry: dict[str, object], override: dict[str, bytes]) -> tuple[str, str | None, str | None]:
    """A file's text as the closure delivers it. `override` substitutes the
    degraded bytes of the mutated file; every other file must still hash to
    the digest the inventory recorded, or the scan would describe other bytes."""
    source = entry.get("source")
    if source:
        if str(source) in override:
            data = override[str(source)]
        else:
            path = root / str(source)
            if not path.is_file():
                return str(source), None, "missing"
            data = path.read_bytes()
            if entry.get("digest") != "sha256:" + hashlib.sha256(data).hexdigest():
                return str(source), None, "content differs from the inventoried digest"
        try:
            return str(source), data.decode("utf-8"), None
        except UnicodeDecodeError:
            return str(source), None, "undecodable"
    if isinstance(entry.get("content"), str):
        return f"synthetic:{entry.get('destination')}", str(entry["content"]), None
    return f"unnamed:{entry.get('destination')}", None, "no source and no inline content"


def scan(root: Path, entries: list[dict[str, object]], removed: str,
         override: dict[str, bytes] | None = None) -> dict[str, object]:
    """Full copies and contained lines (3+ words) of `removed` per file, plus
    coverage errors - the runner's rule, applied to the inventory's closure."""
    norm = _norm(removed)
    full: list[str] = []
    lines: list[dict[str, object]] = []
    errors: list[dict[str, str]] = []
    for entry in entries:
        label, text, error = _text(root, entry, override or {})
        if error:
            errors.append({"file": label, "error": error})
            continue
        assert text is not None
        if norm in _norm(text):
            full.append(label)
        for lineno, line in enumerate(text.splitlines(), start=1):
            n = _norm(line)
            if len(n.split()) >= 3 and n in norm:
                lines.append({"file": label, "line": lineno, "text": line.strip()})
    return {"full_copies": full, "contained_lines": lines, "coverage_errors": errors}


def build(inventory_path: Path, intact_root: Path, inventory_label: str) -> dict[str, object]:
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    entries = closure_entries(inventory)
    intact_ref = (intact_root / REFERENCE_MD).read_bytes()
    removed = removed_block(intact_ref)
    occurrences = intact_ref.count(removed.encode("utf-8"))
    degraded_ref = intact_ref.replace(removed.encode("utf-8"), b"", 1)
    mutated = "sha256:" + hashlib.sha256(degraded_ref).hexdigest()
    intact = scan(intact_root, entries, removed)
    degraded = scan(intact_root, entries, removed, override={REFERENCE_MD: degraded_ref})
    # Every delivered copy of reference.md in the closure is the degraded one
    # (the runner mutates each); the measured digest is of those bytes.
    measured = "sha256:" + hashlib.sha256(degraded_ref).hexdigest()
    positive_control = REFERENCE_MD in intact["full_copies"] and bool(intact["contained_lines"])  # type: ignore[operator]
    if occurrences != 1 or not positive_control or intact["coverage_errors"] or degraded["coverage_errors"] \
            or measured != mutated:
        verdict = "UNKNOWN"  # coverage or the control failed: absence of evidence, not of the instruction
    elif degraded["full_copies"] or degraded["contained_lines"]:
        verdict = "SURVIVES"
    else:
        verdict = "NO_TEXTUAL_SURVIVOR"
    return {
        "evidence_schema": 2,
        "purpose": ("skillc#287 option 1, mutation.diagnose_evidence for the auto6 degraded arm "
                    "(cpp-codex-flow-auto-86641e8-step6, flow-auto skill, reference.md lines "
                    f"{BLOCK_LINES[0]}-{BLOCK_LINES[1]} at the pin: the whole verdict-rules block)."),
        "removed_text": removed,
        "removed_text_occurrences_in_intact": occurrences,
        "mutated_digest": mutated,
        "measured_degraded_reference_digest": measured,
        "mutated_digest_matches": measured == mutated,
        "closure_file_count": len(entries),
        "closure_source": inventory_label,
        "matching_rule": "calibration_run.require_no_delivered_survivor: a whole copy, or any line of 3+ words "
                         "contained in the removed text, whitespace-normalized",
        "occurrence_scan": {
            "positive_control_held": positive_control,
            "intact": {"full_copies": intact["full_copies"],
                       "contained_line_count": len(intact["contained_lines"]),  # type: ignore[arg-type]
                       "coverage_errors": intact["coverage_errors"]},
            "degraded": degraded,
            "verdict": verdict,
            "verdict_meaning": VERDICT_MEANING,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--intact-root", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    evidence = build(args.inventory, args.intact_root, args.inventory.as_posix())
    args.out.write_text(json.dumps(evidence, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    verdict = evidence["occurrence_scan"]["verdict"]  # type: ignore[index]
    print(f"auto6 mutation scan: {verdict} (mutated_digest {evidence['mutated_digest']})")
    return 0 if verdict == "NO_TEXTUAL_SURVIVOR" else 1


if __name__ == "__main__":
    sys.exit(main())
