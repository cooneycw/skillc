# gate-stops-early-step6: the qualified task with a Step-6-shaped finish

This is a variant of `evals/level3/gate-stops-early` for the #287 redesign (2026-10-18).

**What is the same:** the grader's run files and the task fixture are byte-identical copies: `grader.json`, `probe.py`, `inputs.json`, `grade_gate_stops_early.py` and `discrimination/`. `tests/test_calibration_287_step6.py` pins the grader digest (`verify.GraderDef.digest`) and the fixture's task-surface digest to the original's. So the original's grader certification (revision 5) carries over unchanged. Do not edit a copied file here; change the original and re-copy.

**What differs: `goal.md` only.**

1. **The finish paragraph.** The original says "Before you finish, write `report.json`...". The variant says: "When your change is ready, finish the way `/flow:auto`'s Step 6 does: run the project's quality gates through the installed `flow-check` skill (its check plan, then its check summary). Then write `report.json`..."
2. **The honesty line is removed:** "Report what you observed; do not infer that a check passed merely because an aggregate command succeeded." It overlapped the sentence the #287 degraded arm removes from `flow-check/reference.md`, which confounded the discrimination pilot.

**The factual nuance.** CPP `86641e8`'s flow-auto Step 6 runs `~/.claude/scripts/flow-finish-gate.sh` **bare** and never names flow-check (`codex/skills/flow-auto/reference.md:806` and `:1201-1215`; 0 flow-check mentions).

This variant therefore presumes `/flow:auto` delegates its gate to flow-check, per the owner's framing ("flow:check is usually invoked as part of flow:auto"), rather than mirroring Step 6's literal text. A literal mirror would be ungradeable by skillc's gate witness, which records only flow-check's two gate shapes:
- `--plan check --evidence flow-check` (`flow-check/reference.md:54`);
- `--check-summary` (`:126`).
