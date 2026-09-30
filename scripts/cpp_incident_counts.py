#!/usr/bin/env python3
"""Re-derive the counts in docs/research/cpp-incident-catalogue.md (issue #211).

The catalogue's tables are not typed by hand. They are rendered from the
committed per-item records in docs/research/cpp-incident-catalogue/ by this
script, and `--check` fails when the markdown and the records disagree - so a
re-classified row, a hand-edited count or a dropped record turns the check red
instead of leaving a table that no longer follows from its data.

Usage:
  python3 scripts/cpp_incident_counts.py            print every block
  python3 scripts/cpp_incident_counts.py --check    exit 1 on any stale block

Each block lives in the markdown between `<!-- counts:<name> -->` and
`<!-- /counts:<name> -->`. A block the markdown lacks is a failure, not a skip:
a check over zero blocks would pass on any document.

Stdlib only.
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "docs" / "research" / "cpp-incident-catalogue"
DOC = ROOT / "docs" / "research" / "cpp-incident-catalogue.md"

CLASSES = (
    "BLIND",
    "EMPTY",
    "MISVERDICT",
    "WRONGTARGET",
    "SHARED",
    "STALEBASE",
    "CLOSEREF",
    "ASSERTED",
    "DRIFT",
    "DOCDRIFT",
    "ENV",
    "RACE",
    "LOGIC",
)
# Classes a skill collection's workflow discipline claims to address. The
# others (tool-specific logic, environment, flakiness, doc drift) are real
# defects but not hazards an agent walks into while doing ordinary work.
WORKFLOW = frozenset(
    {"BLIND", "EMPTY", "MISVERDICT", "WRONGTARGET", "SHARED", "STALEBASE", "CLOSEREF",
     "ASSERTED", "DRIFT"}
)


def load(name: str, data: Path = DATA) -> list[dict]:
    with open(data / name, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _table(header: list[str], rows: list[list[object]]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(out)


def population(data: Path = DATA) -> str:
    issues = load("issues.jsonl", data)
    nit = load("nit-store.jsonl", data)
    cm = load("counter-model.jsonl", data)
    defects = [r for r in issues if r["defect"]]
    rows: list[list[object]] = [
        ["CPP issues scanned", len(issues)],
        ["... recording a defect (catalogued)", len(defects)],
        ["... of which override a batch label (see overrides.json)",
         sum(1 for r in issues if r["override"])],
        ["Nit Store comments scanned", len(nit)],
        ["... recording a finding", sum(1 for r in nit if r["finding"])],
        ["PRs with a counter-model review section", len(cm)],
        ["... accepted findings they state", sum(r["accepted_stated"] or 0 for r in cm)],
        ["... accepted findings described individually (classified)",
         sum(len(r["itemized"]) for r in cm)],
    ]
    return _table(["Population", "Count"], rows)


def classes(data: Path = DATA) -> str:
    issues = load("issues.jsonl", data)
    nit = [r for r in load("nit-store.jsonl", data) if r["finding"]]
    cm = [f for r in load("counter-model.jsonl", data) for f in r["itemized"]]
    defects = [r for r in issues if r["defect"]]
    rows: list[list[object]] = []
    for cls in CLASSES:
        mine = [r for r in defects if r["cls"] == cls]
        stage = Counter(r["stage"] for r in mine)
        refs = [r["later_refs"] for r in mine]
        rows.append([
            cls,
            len(mine),
            sum(1 for r in defects if cls in r["cls2"]),
            stage["yes"],
            stage["partial"],
            stage["no"],
            f"{statistics.median(refs):g}" if refs else 0,
            sum(refs),
            sum(1 for r in mine if r["recur"] is not None),
            sum(1 for r in nit if r["cls"] == cls),
            sum(1 for f in cm if f["cls"] == cls),
        ])
    return _table(
        ["Class", "Issues", "Also (secondary)", "Stage yes", "Stage partial", "Stage no",
         "Later refs (median)", "Later refs (sum)", "Recurrences", "Nit Store", "Counter-model"],
        rows,
    )


def ranking(data: Path = DATA) -> str:
    """Rank workflow classes by stageable, costly frequency.

    score = (stage yes + 0.5 * stage partial) over the class's primary issues,
    weighted by (1 + median later refs) as the cost term and (1 + recurrences
    / issues) as the recurrence term. Issues staged "no" contribute nothing:
    a hazard no neutral fixture can stage cannot become a skillc task.
    """
    issues = [r for r in load("issues.jsonl", data) if r["defect"]]
    scored: list[tuple[float, str, float, float, float]] = []
    for cls in sorted(WORKFLOW):
        mine = [r for r in issues if r["cls"] == cls]
        if not mine:
            scored.append((0.0, cls, 0.0, 0.0, 0.0))
            continue
        stage = Counter(r["stage"] for r in mine)
        stageable = stage["yes"] + 0.5 * stage["partial"]
        cost = float(1 + statistics.median(r["later_refs"] for r in mine))
        recur = 1 + sum(1 for r in mine if r["recur"] is not None) / len(mine)
        scored.append((round(stageable * cost * recur, 1), cls, stageable, cost, round(recur, 2)))
    scored.sort(key=lambda t: (-t[0], t[1]))
    rows: list[list[object]] = [
        [i + 1, cls, f"{stageable:g}", f"{cost:g}", f"{recur:g}", f"{score:g}"]
        for i, (score, cls, stageable, cost, recur) in enumerate(scored)
    ]
    return _table(["Rank", "Class", "Stageable", "Cost term", "Recurrence term", "Score"], rows)


def agreement(data: Path = DATA) -> str:
    first = {r["n"]: r for r in load("issues.jsonl", data)}
    second = load("second-rater.jsonl", data)
    both = [s for s in second if s["defect"] and first[s["n"]]["defect"]]
    exact = sum(1 for s in both if first[s["n"]]["cls"] == s["cls"])
    loose = sum(
        1 for s in both
        if first[s["n"]]["cls"] == s["cls"]
        or s["cls"] in first[s["n"]]["cls2"]
        or first[s["n"]]["cls"] in s["cls2"]
    )
    rows: list[list[object]] = [
        ["Issues re-rated", len(second)],
        ["Defect / not-defect agree", sum(1 for s in second if first[s["n"]]["defect"] == s["defect"])],
        ["Both raters call it a defect", len(both)],
        ["... same primary class", exact],
        ["... primary class matches either rater's primary or secondary", loose],
    ]
    return _table(["Second-rater sample", "Count"], rows)


BLOCKS = {"population": population, "classes": classes, "ranking": ranking, "agreement": agreement}


def stale_blocks(doc_text: str, data: Path = DATA) -> list[str]:
    """Names of blocks whose markdown differs from the records, or are missing."""
    bad = []
    for name, render in BLOCKS.items():
        start, end = f"<!-- counts:{name} -->", f"<!-- /counts:{name} -->"
        if start not in doc_text or end not in doc_text:
            bad.append(f"{name} (block missing)")
            continue
        body = doc_text.split(start, 1)[1].split(end, 1)[0].strip()
        if body != render(data).strip():
            bad.append(name)
    return bad


def main(argv: list[str]) -> int:
    if argv[1:] == ["--check"]:
        bad = stale_blocks(DOC.read_text(encoding="utf-8"))
        if bad:
            print("stale count blocks: " + ", ".join(bad), file=sys.stderr)
            print("re-render with: python3 scripts/cpp_incident_counts.py", file=sys.stderr)
            return 1
        print(f"counts: {len(BLOCKS)} blocks match the records")
        return 0
    if argv[1:]:
        print(__doc__, file=sys.stderr)
        return 2
    for name, render in BLOCKS.items():
        print(f"<!-- counts:{name} -->\n{render()}\n<!-- /counts:{name} -->\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
