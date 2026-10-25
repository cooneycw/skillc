# Flow run record - issue #574

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=632db4be8d5a47d78f2619c273066fe0 -->
## Run 1

- Run-id:            632db4be8d5a47d78f2619c273066fe0
- Run-start:         357095af692b72565e4273a14d0aab6a3c8fae04

- Issue: #574
- Base SHA: 357095af692b72565e4273a14d0aab6a3c8fae04
- Necessity verdict: Still needed
- Approval: granted
- Approver: skillc-proof orchestrator, gate-574.md, durable revision11

### Section A - intent

Offline proof checks currently depend on machine startup speed or expire before
the step they intend to measure. Make each boundary observable and discriminating,
while preserving real process execution, full qualification and finite guards.

### Section B evidence

Issue created2026-10-25T10:58:32Z. No commits globally or on proposed paths since
filing. Merged PRs573,572,570,567,565,564,562 precede filing. Search considered
574,571,554,20; none supersedes this repair. Host worktrees were readable; only
the protected historical569 archive has relevant unpublished acf28fc, not a repair.
Actual main pipeline1111 outer summary:2failed,7212passed,106skipped,3errors
in482.89s. Coordination's0.6s healthy wave expired before final publication;
B1 full qualification hit120s before its final-step injection. Its declared
qualification allowance is450s with359managed launches. Nested deliberate failure
output is not part of this incident population. No shared production defect shown.
Fresh resolver created this branch from origin/main357095af; the separate literal
unprefixed initial git status probe was empty before reconcile. Genuine run and
approval anchors must pass complete-original-rollout attribution before product.

### Section C - approved bounded repair

1. `tests/test_coordination_wave.py` - replace machine-speed publication test
   with committed policy-clock twins retaining real three-role/socket/capture/
   cleanup: expire after initial authoritative non-PASS write=>FAIL; expire after
   final staging=>PASS. Assert actual outputs, cleanup, report bytes and clock label.
2. `evals/level3/change-with-regression-568/qualify.py` - tiny task-local extraction
   of actual final serialization/check/emit/return, called by unchanged qualifier.
3. `tests/test_change_with_regression_568.py` - direct healthy/expired/during-
   serialization publisher controls without child launches, plus actual full
   fixture observing that same helper/report/budget once. Only the three existing
   full-fixture consumers share an explicit xdist group and510s test allowance:
   qualification450s plus60s finite external cleanup/scheduling margin.
4. `changelog.d/574.md` - describe repaired proof controls without readiness claims.
5. `docs/flow-runs/issue-574.md` - actual approved plan and append-only run evidence.
6. `docs/flow-runs/issue-574.as-read.md` - helper-generated issue snapshot.

Maximum220added+deleted nonworkflow lines across four product paths, plus two
workflow paths. No generic coordination/verifier source, global timeout, Makefile,
CI policy, normalizer, READINESS or controls population edits. Grouping explicitly
shares one real qualifier for the three unchanged consumers under loadgroup;
collection/JUnit identity equality must still pass. Full real report retains24cases,
48validvectors,6protection suites,30tests and359managed wrapper launches, distinct
from other targeted probes. Keep qualification450s cap unchanged;510s is an outer
instrument allowance, never extra success time or a host-I/O guarantee.

Retain actual1111 reds; reproduce old coordination speed assumption with slow
allocation on pre-fix source and real cleanup. Opposite-boundary private mutants
must fail corresponding committed clock controls. B1 removed-final-check and
check-before-serialization mutants must fail actual publisher tests; API absence
is not a behavioral regression. Full fixture must catch missed publisher wiring.
Use exact mutation preconditions, retain execution counts and distinguish logical
policy evidence from latency. No canned substitute for full qualification.

Focused checks with two workers, lint/types, ordinary independent review at most
two different-model passes, then serialized full verification only with root slot.
Actual receipt path and exact-head merge clearance require later root grants.
No blind CI retry, baseline exemption, live study or efficacy claim. Parents568/569
remain open. Preserve clean owned571P42ad unchanged and inactive.

Risk: a narrow helper could lose real wiring evidence; unchanged full qualification
must observe the actual publisher. Timeout scope and group metadata are explicit;
stop if identity normalization fails rather than changing global machinery.
