# Flow run record - issue #346

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=6824eef8bd2748619594fc78918252d9 -->
## Run 1

- Run-id:            6824eef8bd2748619594fc78918252d9
- Run-start:         450445da5eb83719aa68f0f448f29bda56358ec9

- Issue: #346
- Base SHA: 450445da5eb83719aa68f0f448f29bda56358ec9
- Necessity verdict: Partially addressed
- Approval: granted
- Approver: skillc wave orchestrator
- Recorded at: 2026-10-12T14:16:44.625869+00:00

### Section B evidence

Issue created 2026-10-07T03:05:30Z. Inspected post-filing commits:
0051fab (#345), e43445a (#347), 0518cc0 (#349), 8cde2ac (#350),
eeec8d2 (#351), da2d572 (#352), 23bb1ba (#353), 450445d (#335).
Relevant-path commits are 0518cc0 and 23bb1ba. PR #349 supplies the wrapper
and calibration forwarding; uptake still omits all three closure fields.
Related #334 and #348 retain separate installation and witness acceptance.
No duplicate issue or sibling unpushed commit covers the uptake change.

### Section C - the approved plan

1. `skillc/uptake_study.py` - forward the selected arm's verify_home_files, preflight_tools and gate_entrypoint to the existing attempt wrapper.
2. `tests/test_uptake_study.py` - exercise real run_study through real run_level1_agent_attempt, observing run_one_attempt; cover both named arm choices and the empty default comparison, and mutation-check each forwarded field.
3. `skillc/collection_conformance.py` - correct the docstring's stale claim that uptake does not forward closure fields; no behavior change.
4. `CHANGELOG.md` - add one #346 entry under Unreleased.

Scope: four implementation/documentation files, about 100 lines, plus this
required plan record and generated issue snapshot. No material concern with
the minimal forwarding approach.

Risks: uptake has published/rewritten arms, not calibration's baseline/treated.
Tests must call the no-profile comparison by its real meaning. Forwarding
coverage does not establish live Docker or paid-model behavior; #348's witness
construction remains separate. records.py and controls are excluded.

Validation: original-code regression and each independent dropped-argument
mutation fail; focused uptake/calibration/collection-conformance tests and
make verify pass. No paid calls or Woodpecker changes. Commit, push and PR are
authorized; merge requires orchestrator review and current-base CI success.
