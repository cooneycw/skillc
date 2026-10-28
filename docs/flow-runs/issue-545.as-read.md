<!-- flow-run n=1 id=cb48308680c346f39ed88624e941e6a5 -->
## Run 1 - issue #545 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #545
- Read at:      2026-10-28T03:34:41Z
- updatedAt:    2026-10-24T11:56:21Z   (context only - moves on comments and labels)
- Body digest:  f43e093d649e0c99a273f9275b3cd7b0a9ced5a81acba21191e27bb4ecd6983e   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 8846 of 8846 (cap 16384)

### Body as read
**Severity: LOW, MEDIUM.** Nothing here is HIGH, and nothing blocks work now. Filed at the owner's request from the Nit Store aggregation pass https://github.com/cooneycw/skillc/issues/20#issuecomment-6383442993 (group G4).

## Problem
selection-probe still grades through `verify.grade_files` (no stored verified-result, grader pinned without a digest) and has its own baseline digest identity. `verify.regrade()` drops the trusted-observation channel. Both demo and selection-probe hard-code GRADER_ROOT. Related: #538.

## Items (each re-checked against main `5ece908` on 2026-10-24)
- [ ] **MEDIUM**: verify.regrade() still has no trusted_observation parameter, so regrading an agent-path result (readiness_source==AGENT_OBSERVATION_READINESS) loses the 'trusted' envelope key and falls back to UNKNOWN on provenance-checked criteria.
  - Still present: skillc/verify.py:1482-1505 regrade() never forwards a trusted_observation to _grade_and_store (line 1242, which does accept the parameter); no issue found closing this gap. Comment itself notes this is safe (UNKNOWN, never a false PASS) but a real capability gap.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-5879098734
- [ ] **MEDIUM**: selection_probe still grades agent attempts through verify.grade_files (stores no verified-result) and pins its grader by id+revision only (no digest) - the same gap #146 fixed only in agent_trial.run_one_attempt.
  - Still present: skillc/selection_probe.py:237 `verify.grade_files(grader, list(transcript.candidate_files), base, backend=backend)` unchanged; no PR/issue found touching selection_probe.py for this gap; #139's fix (f5b9099) only touched agent_trial.py.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-5858346022
- [ ] **LOW**: skillc/selection_probe.py defines its own placeholder BASELINE_SUBJECT_DIGEST ("sha256:0000...0000baseline"), a second baseline identity not recognized by #427's ledger-binding rule, which keys only on records.BASELINE_SUBJECT_DIGEST (sha256 of empty bytes); low risk today because selection_probe writes no skill-evidence records and no automatic checks.run_bundle caller reaches it.
  - Still present: skillc/selection_probe.py:87 still defines its own distinct `BASELINE_SUBJECT_DIGEST = "sha256:0000...baseline"`, separate from skillc/records.py:250 (`"sha256:" + hashlib.sha256(b'').hexdigest()`), on main 5ece908. Orchestrator ruling on #427 (skillc-400): key only on matched_pilot's digest for now, record in Nit Store -- matches current state exactly.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6237433718
- [ ] **LOW**: demo.py and selection_probe.py each still hardcode module-level GRADER_ROOT = evals/level1/slug-small-fix; neither command can be pointed at a different Level-1 task without a code change (only collection-run got a --task flag).
  - Still present: skillc/demo.py:93 `GRADER_ROOT = REPO_ROOT / "evals" / "level1" / "slug-small-fix"`; skillc/selection_probe.py:80 same constant; no issue found generalizing --task to demo/selection-probe.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-5870255734

## Acceptance
- [ ] Each item above is either fixed or explicitly ruled out, with the reason recorded here.
- [ ] Each fix comes with a test that FAILS on the pre-fix code (run it there and say so).
- [ ] Any instrument changed here gets a committed negative control: the input that makes it report the other verdict.
- [ ] Unverified items are first reproduced, or closed as not reproducible with what was tried.

## Source nits (full text)

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-5879098734 (2026-09-28)</summary>

skillc/verify.py `regrade()` (around line 1292) does not accept a `trusted_observation` parameter, unlike `grade_files`/`grade_agent_attempt`/`_grade_and_store` added for #14's runtime channel. Regrading a stored agent-path result (`readiness_source == AGENT_OBSERVATION_READINESS`) therefore always omits the `"trusted"` envelope key, so a regrade of an attempt originally graded with a fixture-service log silently loses that channel - the judge falls back to UNKNOWN on the provenance-checked criteria rather than reusing (or requiring a fresh) trusted observation. Not a correctness bug today (UNKNOWN is safe, never a false PASS) but a real gap worth a deliberate decision: should `regrade()` take its own `trusted_observation` argument, or refuse regrading an agent-path result that had one without it? Found while building #14's verify.py trusted-observation channel (PR for issue #14, runtime half).

</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-5858346022 (2026-09-27)</summary>

**[MEDIUM] `selection_probe` grades agent attempts through `verify.grade_files` and stores no `verified-result`, so its bundles will fail `attempt-accounting` exactly as #139 described.**

- Where: `skillc/selection_probe.py:204` (`verify.grade_files(grader, list(transcript.candidate_files), base, backend=backend)`), fed by `agent_trial._frozen_candidate_files` (~line 489). The plan in `selection_probe.plan_selection_trials` (~line 119) also pins the grader by id and revision only, with no digest. `verify.grade`/`grade_agent_attempt` refuse to store a result without a digest.
- Why it matters: #139's own body said "#26's selection probe will hit the same gap on the same driver". PR #146 fixes `agent_trial.run_one_attempt` (a graded attempt now stores a result via `verify.grade_agent_attempt`, the agent-observation standing in for the receipt, `installation-ready` UNKNOWN). The selection probe grades on its own path and does not use it. So every captured selection-probe attempt still reads "captured but has no result; grading is still owed".
- Suggested direction: pin `verify.GraderDef.load(...).identity()` in the plan, and grade through `verify.grade_agent_attempt` with the attempt's observation, as `run_one_attempt` now does.
- Found while working #139 / PR #146. Deliberately not widened into that PR.


</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6237433718 (2026-10-17)</summary>

**Severity: low.** Possible second baseline identity, not covered by #427's contaminated-baseline rule.

`skillc/selection_probe.py:87` defines its own `BASELINE_SUBJECT_DIGEST = "sha256:0000…0000baseline"`. This is a named placeholder and not a valid sha256 hex digest. #427's new `ledger-binding` rule (refuse any `skill-evidence` on a baseline trial) keys only on `records.BASELINE_SUBJECT_DIGEST`, the sha256 of empty bytes, which `matched_pilot` (and through it `calibration_run`) writes. So a selection-probe baseline trial is not recognised as a baseline by that rule.

Why it is low today (checked, not guessed, while driving #427 / PR for #427):
- `selection_probe.py` writes no `skill-evidence` records at all.
- No code path runs `ledger-binding` on selection-probe output automatically. The only automatic `checks.run_bundle` callers are `coverage.py:529` and `matched_pilot.py:999`. The committed selection-probe evidence (`evals/selection-probe/evidence/2026-10-03-retention-run/`) holds a report and transcripts, but no trial ledger.
- However, its trial store does carry a `trial-ledger` record (`trial.plan` → `ledger.json`), so a manual `skillc check-records <store>` would bind it, and there the placeholder baseline would be treated as an ordinary subject.

Fix if it ever matters: either move selection-probe to `records.BASELINE_SUBJECT_DIGEST`, or have the rule recognise both identities. Orchestrator ruling on #427 (skillc-400): key only on matched_pilot's digest for now, and record this here.


</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-5870255734 (2026-09-28)</summary>

**Finding while scoping #150-B2 (2026-09-28):** `skillc/demo.py:93` and `skillc/selection_probe.py:71` each declare their own module-level `GRADER_ROOT = evals/level1/slug-small-fix` constant and read it unconditionally (`demo.py`'s grading leg, `selection-probe`'s own attempt planning) - the same hard-wiring #150-B2 is fixing in `collection_conformance.py`'s `run_collection_agent_attempt`/`plan_collection_attempt` via a new `collection-run --task DIR`. Neither `skillc demo` nor `skillc selection-probe` can be pointed at a different Level-1 task (e.g. `evals/level1/finish-close-ref`) without a code change. Out of scope for #150-B2 (which only touches `collection-run`'s own path) - noting for whoever wants a similar `--task` flag on either command later. grader.json already carries `id`/`revision` generically (`verify.GraderDef.load`), so the same low-risk approach (derive the ledger/plan identity from the loaded grader instead of a hardcoded literal) should apply to both.

</details>


<!-- end of body -->

<!-- flow-run n=2 id=ed6706f418af4344aea27284f7fed7a2 -->
## Run 2 - issue #545 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #545
- Read at:      2026-10-28T05:14:56Z
- updatedAt:    2026-10-28T05:13:22Z   (context only - moves on comments and labels)
- Body digest:  979bf5990beaf025cfbf5391158c0a9f6e4aafbd4a71ed67c78f8973ad37b3c9   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 8846 of 8846 (cap 16384)

### Body as read
**Severity: LOW, MEDIUM.** Nothing here is HIGH, and nothing blocks work now. Filed at the owner's request from the Nit Store aggregation pass https://github.com/cooneycw/skillc/issues/20#issuecomment-6383442993 (group G4).

## Problem
selection-probe still grades through `verify.grade_files` (no stored verified-result, grader pinned without a digest) and has its own baseline digest identity. `verify.regrade()` drops the trusted-observation channel. Both demo and selection-probe hard-code GRADER_ROOT. Related: #538.

## Items (each re-checked against main `5ece908` on 2026-10-24)
- [ ] **MEDIUM**: verify.regrade() still has no trusted_observation parameter, so regrading an agent-path result (readiness_source==AGENT_OBSERVATION_READINESS) loses the 'trusted' envelope key and falls back to UNKNOWN on provenance-checked criteria.
  - Still present: skillc/verify.py:1482-1505 regrade() never forwards a trusted_observation to _grade_and_store (line 1242, which does accept the parameter); no issue found closing this gap. Comment itself notes this is safe (UNKNOWN, never a false PASS) but a real capability gap.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-5879098734
- [ ] **MEDIUM**: selection_probe still grades agent attempts through verify.grade_files (stores no verified-result) and pins its grader by id+revision only (no digest) - the same gap #146 fixed only in agent_trial.run_one_attempt.
  - Still present: skillc/selection_probe.py:237 `verify.grade_files(grader, list(transcript.candidate_files), base, backend=backend)` unchanged; no PR/issue found touching selection_probe.py for this gap; #139's fix (f5b9099) only touched agent_trial.py.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-5858346022
- [ ] **LOW**: skillc/selection_probe.py defines its own placeholder BASELINE_SUBJECT_DIGEST ("sha256:0000...0000baseline"), a second baseline identity not recognized by #427's ledger-binding rule, which keys only on records.BASELINE_SUBJECT_DIGEST (sha256 of empty bytes); low risk today because selection_probe writes no skill-evidence records and no automatic checks.run_bundle caller reaches it.
  - Still present: skillc/selection_probe.py:87 still defines its own distinct `BASELINE_SUBJECT_DIGEST = "sha256:0000...baseline"`, separate from skillc/records.py:250 (`"sha256:" + hashlib.sha256(b'').hexdigest()`), on main 5ece908. Orchestrator ruling on #427 (skillc-400): key only on matched_pilot's digest for now, record in Nit Store -- matches current state exactly.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6237433718
- [x] **LOW**: demo.py and selection_probe.py each still hardcode module-level GRADER_ROOT = evals/level1/slug-small-fix; neither command can be pointed at a different Level-1 task without a code change (only collection-run got a --task flag).
  - Still present: skillc/demo.py:93 `GRADER_ROOT = REPO_ROOT / "evals" / "level1" / "slug-small-fix"`; skillc/selection_probe.py:80 same constant; no issue found generalizing --task to demo/selection-probe.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-5870255734

## Acceptance
- [ ] Each item above is either fixed or explicitly ruled out, with the reason recorded here.
- [ ] Each fix comes with a test that FAILS on the pre-fix code (run it there and say so).
- [ ] Any instrument changed here gets a committed negative control: the input that makes it report the other verdict.
- [ ] Unverified items are first reproduced, or closed as not reproducible with what was tried.

## Source nits (full text)

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-5879098734 (2026-09-28)</summary>

skillc/verify.py `regrade()` (around line 1292) does not accept a `trusted_observation` parameter, unlike `grade_files`/`grade_agent_attempt`/`_grade_and_store` added for #14's runtime channel. Regrading a stored agent-path result (`readiness_source == AGENT_OBSERVATION_READINESS`) therefore always omits the `"trusted"` envelope key, so a regrade of an attempt originally graded with a fixture-service log silently loses that channel - the judge falls back to UNKNOWN on the provenance-checked criteria rather than reusing (or requiring a fresh) trusted observation. Not a correctness bug today (UNKNOWN is safe, never a false PASS) but a real gap worth a deliberate decision: should `regrade()` take its own `trusted_observation` argument, or refuse regrading an agent-path result that had one without it? Found while building #14's verify.py trusted-observation channel (PR for issue #14, runtime half).

</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-5858346022 (2026-09-27)</summary>

**[MEDIUM] `selection_probe` grades agent attempts through `verify.grade_files` and stores no `verified-result`, so its bundles will fail `attempt-accounting` exactly as #139 described.**

- Where: `skillc/selection_probe.py:204` (`verify.grade_files(grader, list(transcript.candidate_files), base, backend=backend)`), fed by `agent_trial._frozen_candidate_files` (~line 489). The plan in `selection_probe.plan_selection_trials` (~line 119) also pins the grader by id and revision only, with no digest. `verify.grade`/`grade_agent_attempt` refuse to store a result without a digest.
- Why it matters: #139's own body said "#26's selection probe will hit the same gap on the same driver". PR #146 fixes `agent_trial.run_one_attempt` (a graded attempt now stores a result via `verify.grade_agent_attempt`, the agent-observation standing in for the receipt, `installation-ready` UNKNOWN). The selection probe grades on its own path and does not use it. So every captured selection-probe attempt still reads "captured but has no result; grading is still owed".
- Suggested direction: pin `verify.GraderDef.load(...).identity()` in the plan, and grade through `verify.grade_agent_attempt` with the attempt's observation, as `run_one_attempt` now does.
- Found while working #139 / PR #146. Deliberately not widened into that PR.


</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6237433718 (2026-10-17)</summary>

**Severity: low.** Possible second baseline identity, not covered by #427's contaminated-baseline rule.

`skillc/selection_probe.py:87` defines its own `BASELINE_SUBJECT_DIGEST = "sha256:0000…0000baseline"`. This is a named placeholder and not a valid sha256 hex digest. #427's new `ledger-binding` rule (refuse any `skill-evidence` on a baseline trial) keys only on `records.BASELINE_SUBJECT_DIGEST`, the sha256 of empty bytes, which `matched_pilot` (and through it `calibration_run`) writes. So a selection-probe baseline trial is not recognised as a baseline by that rule.

Why it is low today (checked, not guessed, while driving #427 / PR for #427):
- `selection_probe.py` writes no `skill-evidence` records at all.
- No code path runs `ledger-binding` on selection-probe output automatically. The only automatic `checks.run_bundle` callers are `coverage.py:529` and `matched_pilot.py:999`. The committed selection-probe evidence (`evals/selection-probe/evidence/2026-10-03-retention-run/`) holds a report and transcripts, but no trial ledger.
- However, its trial store does carry a `trial-ledger` record (`trial.plan` → `ledger.json`), so a manual `skillc check-records <store>` would bind it, and there the placeholder baseline would be treated as an ordinary subject.

Fix if it ever matters: either move selection-probe to `records.BASELINE_SUBJECT_DIGEST`, or have the rule recognise both identities. Orchestrator ruling on #427 (skillc-400): key only on matched_pilot's digest for now, and record this here.


</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-5870255734 (2026-09-28)</summary>

**Finding while scoping #150-B2 (2026-09-28):** `skillc/demo.py:93` and `skillc/selection_probe.py:71` each declare their own module-level `GRADER_ROOT = evals/level1/slug-small-fix` constant and read it unconditionally (`demo.py`'s grading leg, `selection-probe`'s own attempt planning) - the same hard-wiring #150-B2 is fixing in `collection_conformance.py`'s `run_collection_agent_attempt`/`plan_collection_attempt` via a new `collection-run --task DIR`. Neither `skillc demo` nor `skillc selection-probe` can be pointed at a different Level-1 task (e.g. `evals/level1/finish-close-ref`) without a code change. Out of scope for #150-B2 (which only touches `collection-run`'s own path) - noting for whoever wants a similar `--task` flag on either command later. grader.json already carries `id`/`revision` generically (`verify.GraderDef.load`), so the same low-risk approach (derive the ledger/plan identity from the loaded grader instead of a hardcoded literal) should apply to both.

</details>


<!-- end of body -->
