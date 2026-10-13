# Flow run record - issue #376

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=8bc8816671664b75898c8f8f140950af -->
## Run 1

- Run-id:            8bc8816671664b75898c8f8f140950af
- Run-start:         b6e238b60a2357f036a4217e17263854e646751f
- Issue:             #376
- Base SHA:          b6e238b
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          owner (cooneycw), interactive session reply "approved"
- Recorded at:       2026-10-13T00:00:00Z

### Section B evidence
Merged since filing: 7b800c6 (#377, #315 provisioning record), b6e238b (#378, #360 live test) - neither touches graders/witness. No duplicate or superseding issue (#375 portion B is separate scope; #270 parent). Pinned runner ea6dbfa already emits step_details with not-run/skipped; CPP 8e0a34fb changed only agent-facing instructions.

Deferred (issue stays open, Refs #376): CPP/profile repin and identity refresh (separate PR coordinated with #287 approval and #360 image supply); real-runner demonstration on #315 (blocked on #315/#360).

### Section C - the approved plan
1. `skillc/gate_witness.py` - caller-declared stage-bearing gates; controller parses runner final JSON step_details from real stdout into per-run stages; strict, unavailable on ambiguity; record version 3
2. `skillc/agent_trial.py` - declare flow-check-plan as stage-bearing
3. `docs/specs/evaluation-facility/gate-witness.md` - document per-run stage capture and v3
4. `evals/level3/gate-stops-early/grade_gate_stops_early.py` - revision 5: reconcile lint/test/typecheck claims against last fresh completed plan run's stages; UNKNOWN on missing/stale/malformed/exit-only
5. `evals/level3/gate-stops-early/qualify.py` - stage-bearing witnesses, validity cases, grader mutations
6. `evals/level3/gate-stops-early/alternatives/` - new healthy candidates (and wrong/, incomplete/ false-claim and unknown candidates)
7. `evals/level3/verify-stops-early/grade_verify_stops_early.py` - revision 4 port
8. `evals/level3/verify-stops-early/qualify.py` - port
9. `evals/level3/verify-stops-early/alternatives/` - new candidates (and wrong/, incomplete/)
10. `tests/test_gate_witness.py` - stage parser unit tests incl. real pinned-runner stdout samples
11. `tests/test_level3_gate_stops_early.py` - regression tests (and verify-stops-early counterpart)
12. `evals/level3/gate-stops-early/PROVENANCE.md` - revision notes (plus grader.json, eligibility-manifest.json for both tasks)
13. `CHANGELOG.md` - entry

Scope: ~20 files, ~1500 lines. Risk: runner stdout shares a stream with candidate Makefile output (forged step_details); accept only the single final runner JSON before the verdict line, ambiguous -> unavailable; bounded, not anti-forgery proof. Risk: rebuilt witnesses could silently shift existing candidate outcomes; qualification must show them unchanged.
