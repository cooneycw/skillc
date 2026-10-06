#!/usr/bin/env python3
"""Run one batch of #238's description optimizer, skill by skill.

Usage (from a clone at the batch's declared commit, with a claude-power-pack
checkout at the subject's pinned revision):

    SKILLC_ALLOW_REAL_AGENT=1 python3 scripts/description_optimizer.py \\
        evals/description-optimizer/batch-1.json --cpp <cpp checkout> --work <dir>

For each skill in the batch file, in order:

  1. write one override SKILL.md per variant: the pinned file with ONLY its
     description line replaced (JSON-quoted), and build each with
     `skillc degrade-subject --override-file`;
  2. SCREEN: a probe `uptake-study` with arms published + the variants on the
     skill's development cases; each arm is scored select-rate minus
     abstain-rate (`uptake_study._scores`);
  3. pick the best-scoring variant. If no variant scores above published, the
     published description is KEPT and step 4 is skipped;
  4. CONFIRM: a two-arm probe study, published vs the winner, on the held-out
     cases, with the predeclared one-sided Fisher's exact test on the select
     case;
  5. write `<work>/results/<skill>.json`.

Every declaration is derived mechanically from the committed batch file and
this script (seeds from the skill name), and records the owner's 2026-10-06
ruling on #238 as its approval. A skill whose result file exists is skipped,
so an interrupted batch resumes where it stopped.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from skillc import uptake_study as us

PROBE_SECONDS = 45
OVERHEAD_SECONDS = 40  # setup, grading and teardown per attempt (Nit Store #20, PR #311's lesson)
SCREEN_N, CONFIRM_SELECT_N, CONFIRM_ABSTAIN_N = 3, 8, 5
APPROVAL = {
    "by": "owner (cooneycw)", "at": "2026-10-06",
    "source": "owner rulings on #238, 2026-10-06: \"q2. (c) but in priority sequence, updating results in the cpp "
              "issues 12 at a time.  q3. yes.\" and \"q2. yes\" (variants may be generated and tested without "
              "per-wording approval)",
    "scope": "the screen and confirmation probes this script derives for each skill in the batch, run under the "
             "operator's codex subscription login (ADR 0005 rule 6); no judge tier, no dollar-metered spend",
}


def seed(*parts: str) -> int:
    return int(hashlib.sha256("/".join(parts).encode()).hexdigest()[:8], 16)


def base_declaration() -> dict[str, object]:
    """The shared identities, task and subject, from the committed #237 study."""
    src = json.loads((ROOT / "evals" / "uptake-study" / "run-manifest.json").read_text(encoding="utf-8"))
    return {k: src[k] for k in ("task", "shared")} | {"subject": src["arms"][0]["subject"]}


def override_file(cpp: Path, skill: str, description: str, out: Path) -> Path:
    original = (cpp / "codex" / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
    lines = original.split("\n")
    hits = [i for i, line in enumerate(lines) if line.startswith("description:")]
    if len(hits) != 1:
        raise SystemExit(f"{skill}: expected one description line, found {len(hits)}")
    lines[hits[0]] = "description: " + json.dumps(description)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def declaration(base: dict[str, object], skill: str, kind: str, arms: list[dict[str, object]],
                cases: list[dict[str, object]], *, test: bool) -> dict[str, object]:
    names = [a["name"] for a in arms]
    parsed = [us.Case(c["id"], c["prompt_addendum"], c["attempts_per_arm"], c["primary"], c.get("expect"))
              for c in cases]
    attempts = sum(c["attempts_per_arm"] for c in cases) * len(names)
    s = seed(skill, kind)
    shared = dict(base["shared"])  # type: ignore[arg-type]
    shared.update(per_attempt_seconds=PROBE_SECONDS, total_seconds=attempts * (PROBE_SECONDS + OVERHEAD_SECONDS))
    data: dict[str, object] = {
        "kind": "uptake-study", "issue": 238, "declared_at": "derived at run time by scripts/description_optimizer.py",
        "_comment": f"#238 {kind} for {skill}.", "approval": APPROVAL, "task": base["task"], "arms": arms,
        "shared": shared, "cases": cases, "probe": {"cutoff_seconds": PROBE_SECONDS},
        "arm_order": {"seed": s, "sequence": [list(x) for x in us.derive_order(s, parsed, names)]},
    }
    if test:
        data["test"] = {"kind": "fisher-exact-one-sided", "direction": "rewritten > published", "alpha": 0.05}
    us.parse_declaration(data)
    return data


def run_study(decl_path: Path, rewritten: dict[str, Path], private: Path) -> dict[str, object]:
    args = ["uv", "run", "--no-sync", "skillc", "uptake-study", str(decl_path), "--private-dir", str(private)]
    for arm, path in rewritten.items():
        args += ["--rewritten", str(path) if arm == "rewritten" else f"{arm}={path}"]
    private.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=False)
    (private / "stdout.txt").write_text(proc.stdout + "\n--- stderr\n" + proc.stderr, encoding="utf-8")
    reports = sorted(private.glob("*/uptake-report.json"))
    if not reports:
        raise SystemExit(f"{decl_path.name}: no report (exit {proc.returncode}); see {private / 'stdout.txt'}")
    return {"exit": proc.returncode, "report": json.loads(reports[-1].read_text(encoding="utf-8"))}


def degrade(cpp: Path, skill: str, override: Path, out: Path) -> Path:
    if not (out / "receipt.json").is_file():
        subprocess.run(["uv", "run", "--no-sync", "skillc", "degrade-subject", "cpp-codex", "--checkout", str(cpp),
                        "--override-file", f"{skill}:SKILL.md={override}", "--out", str(out)],
                       cwd=ROOT, check=True, capture_output=True, text=True)
    return out


def optimize(entry: dict[str, object], cpp: Path, work: Path, base: dict[str, object]) -> dict[str, object]:
    skill = str(entry["skill"])
    variants: dict[str, str] = dict(entry["variants"])  # type: ignore[arg-type]
    published = (cpp / "codex" / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
    published_desc = json.loads(next(line for line in published.split("\n")
                                     if line.startswith("description:")).split(":", 1)[1])
    sdir = work / skill
    snapshots = {arm: degrade(cpp, skill, override_file(cpp, skill, d, sdir / f"{arm}-SKILL.md"), sdir / f"rw-{arm}")
                 for arm, d in variants.items()}
    subject = base["subject"]
    arms = [{"name": "published", "subject": subject}] + [
        {"name": arm, "subject": subject, "target_skill": skill, "description": d} for arm, d in variants.items()]
    dev = [{**c, "attempts_per_arm": SCREEN_N, "primary": False} for c in entry["development"]]  # type: ignore[union-attr]
    screen_decl = declaration(base, skill, "screen", arms, dev, test=False)
    (sdir / "screen.json").write_text(json.dumps(screen_decl, indent=1) + "\n", encoding="utf-8")
    screen = run_study(sdir / "screen.json", snapshots, sdir / "screen-private")
    scores = screen["report"]["scores"]
    ranked = sorted(variants, key=lambda a: (scores[a]["score"] is not None, scores[a]["score"] or -9), reverse=True)
    best = ranked[0]
    pub = scores["published"]["score"]
    result: dict[str, object] = {"skill": skill, "published": published_desc, "variants": variants,
                                 "screen": {"experiment": screen["report"]["experiment_id"], "scores": scores},
                                 "winner": None, "confirm": None}
    if scores[best]["score"] is None or (pub is not None and scores[best]["score"] <= pub):
        result["verdict"] = "kept: no variant scored above the published description on the development screen"
        return result
    result["winner"] = best
    held = [{**c, "attempts_per_arm": CONFIRM_SELECT_N if c["expect"] == "select" else CONFIRM_ABSTAIN_N,
             "primary": c["expect"] == "select"} for c in entry["held_out"]]  # type: ignore[union-attr]
    confirm_arms = [{"name": "published", "subject": subject},
                    {"name": "rewritten", "subject": subject, "target_skill": skill, "description": variants[best]}]
    confirm_decl = declaration(base, skill, "confirm", confirm_arms, held, test=True)
    (sdir / "confirm.json").write_text(json.dumps(confirm_decl, indent=1) + "\n", encoding="utf-8")
    confirm = run_study(sdir / "confirm.json", {"rewritten": snapshots[best]}, sdir / "confirm-private")
    report = confirm["report"]
    test = report["primary_test"]
    result["confirm"] = {"experiment": report["experiment_id"], "cells": report["cells"], "primary_test": test}
    abstain = next(cell for case, arms_ in report["cells"].items()
                   for arm, cell in arms_.items() if arm == "rewritten" and case != test["case"])
    selective = abstain["observed"] > 0 and abstain["selected"] / abstain["observed"] <= 0.2
    if test.get("available") and test.get("significant") and selective:
        result["verdict"] = f"improved: {best} is selected more often when it applies, and stays selective"
    elif test.get("available") and test.get("significant"):
        result["verdict"] = f"recall improved but NOT selective: {best} also fires on the held-out abstain case"
    else:
        result["verdict"] = f"not confirmed: {best} did not beat published on the held-out select case"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("batch")
    parser.add_argument("--cpp", required=True, type=Path)
    parser.add_argument("--work", required=True, type=Path)
    parser.add_argument("--only", help="run just this skill")
    args = parser.parse_args()
    batch = json.loads(Path(args.batch).read_text(encoding="utf-8"))
    base = base_declaration()
    (args.work / "results").mkdir(parents=True, exist_ok=True)
    for entry in batch["skills"]:
        skill = entry["skill"]
        if args.only and skill != args.only:
            continue
        out = args.work / "results" / f"{skill}.json"
        if out.is_file():
            print(f"{skill}: already done", flush=True)
            continue
        print(f"{skill}: starting", flush=True)
        result = optimize(entry, args.cpp, args.work, base)
        out.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
        print(f"{skill}: {result['verdict']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
