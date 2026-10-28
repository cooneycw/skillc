# Flow run record - issue #542

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=efb0e2b868404b9f9a438241b086f9c0 -->
## Run 1

- Run-id:            efb0e2b868404b9f9a438241b086f9c0
- Run-start:         1e7ae69f9af60d096d771218e1a6c0898b8e84c9

- Issue: #542
- Base SHA: 1e7ae69f9af60d096d771218e1a6c0898b8e84c9
- Necessity verdict: Still needed
- Approval: granted
- Approver: skillc-update orchestrator, Codex thread 01a17ce7-0301-7621-8b1f-bf330eed8b5d; durable outbox-worker-02 rev 5, GO-WITH-CONDITIONS
- Implementer identity: Codex thread 01a17cec-fab5-7860-b0e9-aeef446e1806
- Recorded at: 2026-10-27T10:42:17.334619+00:00

### Section B evidence

Issue created 2026-10-24T11:56:18Z. Audited remote main 1e7ae69,
not stale shared main 08a6887. Inspected post-filing commits 1e7ae69,
29d702d, 357095a, b246435, 6b78522, 1fcf690, 79fbaaf, 9a62b80,
a924c5f, 08a6887, 7373a5b, a3e9ba8, 3b7e256, 921aadc, 84ab2ab,
62eb329, afce0e4, c804555, 237ab8f. Merged PRs considered: #578,
#575, #573, #572, #570, #567, #566, #565, #564, #562, #561, #560,
#559, #558. Only 1fcf690 changed a scoped candidate path (an exact
pyproject.toml resume-v1 exclusion), repairing neither selected predicate.
Related issues considered: #19, #134, #341, #356, #543, #568, #554,
#462. None supersedes these two fixes. No sibling unpushed commit touched
the candidate paths; preserved worktrees remain untouched.

On unfixed main the actual tool test accepted uv 0.9.70 as pin 0.9.7.
The actual typecheck control accepted a population that omitted authored
tests but included an early fixture, and rejected a clean population when
an early excluded fixture stole the probe. Existing seven controls passed.
The #568 duplicate-module baseline and private-citation integration are
separate and reserved for its continuation.

### Section C - the approved plan

1. `ci/typecheck-control.sh` - Select deterministically from top-level authored tests/test_*.py regular files only with locale-stable ordering. Preserve empty-population, clean-baseline, exact file/line attribution and status guards.
2. `tests/test_typecheck_control.py` - Commit real earlier-included/excluded fixture controls, a fixture-only narrowed population false-green control and empty-authored-population control, with healthy twins and all seven existing controls retained.
3. `tests/test_trial_image_tools_live.py` - Parse uv executable/version tokens and require exact complete-version equality while retaining normal metadata, property-specific exceptions and infrastructure discrimination.
4. `tests/test_trial_image_tools_oracle.py` - Add offline tests invoking the actual live function with external I/O replaced; commit exact/metadata good cases, prefix/suffix-sharing and generic wrong-version/malformed/non-uv/failed-command bad cases.

Scope: Four product files, estimate 140-220 added-plus-deleted lines;
absolute product ceiling 260. Workflow record/snapshot are separate;
genuine independent-review receipt needs its later exact path grant.
Run new regression tests on unchanged predicates before applying fixes.
Retain pre-fix failures and post-fix results. Request serialized heavy
verification slot; focused checks may proceed. Independent review, genuine
receipt, full verification and exact-head required ci/woodpecker/pr/ci
precede guarded merge with exact-PR orchestrator clearance.

Risks: top-level probe certifies authored tests, not every fixture; mypy
controls need a clean baseline; preserve uv metadata without accepting a
longer version token. No material concern found with the bounded approach.
No broad exclusions or edits to reserved #568/#546 source. No live study,
deployment or physical image-conformance claim. Refs #542 only, no automatic
issue closure. Evals typing/latent errors, cold-cache diagnostic fragility
and committed-history changelog sequencing remain open in #542.

<!-- flow-run n=2 id=061d26d23f314847840a3c86d83b20c6 -->
## Run 2

- Run-id:            061d26d23f314847840a3c86d83b20c6
- Run-start:         8187bc07bdf4f4e4f820bb7f11c9894cf6261c19
- Salvage:           8187bc07bdf4f4e4f820bb7f11c9894cf6261c19
- Salvage-Reason:    Orchestrator-authorized deliberate preservation of approved source and legacy workflow record before supported native Codex ownership reconciliation; original scope and 106 product changed lines remain charged.

- Issue: #542
- Base SHA: 1e7ae69f9af60d096d771218e1a6c0898b8e84c9
- Necessity verdict: Still needed
- Approval: granted
- Approver: skillc-update orchestrator, thread 01a17ce7-0301-7621-8b1f-bf330eed8b5d; outbox-worker-02 rev 5 (original gate) and rev 9 (supported salvage)
- Implementer identity: Codex thread 01a17cec-fab5-7860-b0e9-aeef446e1806
- Recorded at: 2026-10-27T10:50:32.490030+00:00

This native Codex-owned continuation retains the original approved scope,
source contribution, and 106 added-plus-deleted product lines in salvage
8187bc07bdf4f4e4f820bb7f11c9894cf6261c19. It does not reset the 260-line cap.
The old helper minted the first run without native ownership. While examining
that metadata the orchestrator mistakenly reconciled this worktree, minting
3ed1ee4d43e749348b3a6106cfe62a18 under its own thread. That event was preserved
as a diagnostic and corrected by supported reconcile under the actual worker
identity, not by rewriting run metadata. Original committed history stays
unchanged. Pinned toolchain 7f17055c was restored after its path disappeared;
the cause is unknown. Neither event changed product source.

The unchanged approved Section B/Section C follows verbatim. Review and final
checks cover the full origin/main-to-final contribution including salvage,
not an empty diff since this continuation's Run-start. The existing actual
pre-fix 11 failures/12 passes and post-fix 116 passes remain evidence; the
completed independent Astra review is retained without another pass solely
for metadata correction. Physical image conformance remains unexecuted.

### Section B evidence

Issue created 2026-10-24T11:56:18Z. Audited remote main 1e7ae69,
not stale shared main 08a6887. Inspected post-filing commits 1e7ae69,
29d702d, 357095a, b246435, 6b78522, 1fcf690, 79fbaaf, 9a62b80,
a924c5f, 08a6887, 7373a5b, a3e9ba8, 3b7e256, 921aadc, 84ab2ab,
62eb329, afce0e4, c804555, 237ab8f. Merged PRs considered: #578,
#575, #573, #572, #570, #567, #566, #565, #564, #562, #561, #560,
#559, #558. Only 1fcf690 changed a scoped candidate path (an exact
pyproject.toml resume-v1 exclusion), repairing neither selected predicate.
Related issues considered: #19, #134, #341, #356, #543, #568, #554,
#462. None supersedes these two fixes. No sibling unpushed commit touched
the candidate paths; preserved worktrees remain untouched.

On unfixed main the actual tool test accepted uv 0.9.70 as pin 0.9.7.
The actual typecheck control accepted a population that omitted authored
tests but included an early fixture, and rejected a clean population when
an early excluded fixture stole the probe. Existing seven controls passed.
The #568 duplicate-module baseline and private-citation integration are
separate and reserved for its continuation.

### Section C - the approved plan

1. `ci/typecheck-control.sh` - Select deterministically from top-level authored tests/test_*.py regular files only with locale-stable ordering. Preserve empty-population, clean-baseline, exact file/line attribution and status guards.
2. `tests/test_typecheck_control.py` - Commit real earlier-included/excluded fixture controls, a fixture-only narrowed population false-green control and empty-authored-population control, with healthy twins and all seven existing controls retained.
3. `tests/test_trial_image_tools_live.py` - Parse uv executable/version tokens and require exact complete-version equality while retaining normal metadata, property-specific exceptions and infrastructure discrimination.
4. `tests/test_trial_image_tools_oracle.py` - Add offline tests invoking the actual live function with external I/O replaced; commit exact/metadata good cases, prefix/suffix-sharing and generic wrong-version/malformed/non-uv/failed-command bad cases.

Scope: Four product files, estimate 140-220 added-plus-deleted lines;
absolute product ceiling 260. Workflow record/snapshot are separate;
genuine independent-review receipt needs its later exact path grant.
Run new regression tests on unchanged predicates before applying fixes.
Retain pre-fix failures and post-fix results. Request serialized heavy
verification slot; focused checks may proceed. Independent review, genuine
receipt, full verification and exact-head required ci/woodpecker/pr/ci
precede guarded merge with exact-PR orchestrator clearance.

Risks: top-level probe certifies authored tests, not every fixture; mypy
controls need a clean baseline; preserve uv metadata without accepting a
longer version token. No material concern found with the bounded approach.
No broad exclusions or edits to reserved #568/#546 source. No live study,
deployment or physical image-conformance claim. Refs #542 only, no automatic
issue closure. Evals typing/latent errors, cold-cache diagnostic fragility
and committed-history changelog sequencing remain open in #542.

<!-- flow-run n=3 id=c6a6873f35334f95af263e66703303ad -->
## Run 3

- Run-id:            c6a6873f35334f95af263e66703303ad
- Run-start:         a26d8a49b5292e16e22ac54a2287b99cad87a3ce

- Issue: #542
- Base SHA: a26d8a49b5292e16e22ac54a2287b99cad87a3ce
- Necessity verdict: Partially addressed
- Approval: granted
- Approver: skillc-update orchestrator, native thread 01a17ce7-0301-7621-8b1f-bf330eed8b5d; clearance-542-changelog-clean-inputs-implementation.md
- Implementer identity: Codex thread 01a17cec-fab5-7860-b0e9-aeef446e1806

### Section A - intent

The local changelog gate can approve committed history while pending code
was never inspected. Refuse relevant pending inputs locally until checkpointed,
then apply existing committed fragment rules; do not evaluate pending content.

### Section B evidence

Issue created2026-10-24T11:56:18Z. Prior579/028dde5 delivered authored-test
selection and exact uv matching, not this residual. Currenta26 checker uses
merge-base..HEAD/git-show/HEAD trailer; local Makefile and CI call that default.
Existing real-Git CLI controls commit their inputs. No postfiling checker/test
change;42e367b/586 changes Makefile Ruff cache only; b2fa7f8/452 changed fragment
format, not source selection. Related542/20/439/134/19/341/356/543/568/554/462
were considered in accepted external triage. No superseding fix. Refreshed21
host sibling scoped unpublished queries all succeeded with none matching.
Current source/hash/as-read verified on freshc6a6873f, not old579 approval.

### Section C - approved bounded repair

1. `ci/changelog_check.py` - Add optional --require-clean-inputs; strict NUL-safe staged/unstaged/untracked nonignored relevant input guard; deletion/type/conflict and rename both ends; incomplete/error enumeration REFUSED2, before evaluation and before green with HEAD stability. Preserve pure policy/assembler API and default committed semantics.
2. `Makefile` - Select local flag for changelog-check, preserve fetch failure and verify membership.
3. `tests/test_changelog_check.py` - Actual unchanged Makefile behavioral red with clean/default twins before production edit; committed real-Git status/path/error and blinded-discrimination controls; assembler compatibility retained.
4. `AGENTS.md` - Explain local refusal versus committed CI/default, explicit refs/scope and intentional checkpoint-before-full requirement.
5. `changelog.d/542-changelog-state.md` - New single-bullet fragment; shipped542 fragments unchanged.

Scope: exact5 product paths above plus this record and issue-542.as-read.md.
Hard450 product A+D INCLUDING later genuine receipt reserve<=60; receipt path
requires separate grant, not selected now. Workflow cap300 separate. Desired
pre-receipt300-375; stop on cap/path/boundary expansion. Dirty good fragment also
refuses; unrelated notes/reports/ineligible names do not. No dirty symlink read.
HEAD trailer remains committed-only, cannot rescue pending source. Git failures
and malformed/incomplete observations refuse; no adversarial atomicity claim.

Structural challenge: generic flow quality-before-commit now refuses relevant
dirty input intentionally. This wave uses checkpoint before canonical full;
no automatic commit/stash or CPP lifecycle edit. Frozen pre439/CPP389/task/
grader/declarations/receipts/history and old record/snapshot prefixes preserved.
No CI/pyproject/assembler/evals/helper path. No review/receipt/checkpoint/full/
push/PR/merge/issueedit/cleanup yet.538 retains next exclusive full.

<!-- flow-run n=4 id=a7a19d2097f1484cb522cf39a213bb3a -->
## Run 4

- Run-id:            a7a19d2097f1484cb522cf39a213bb3a
- Run-start:         000753d82c4c5e102fefb90d25eef9e9f0b226a1
- Issue: #542
- Base SHA: 000753d82c4c5e102fefb90d25eef9e9f0b226a1
- Necessity verdict: Partially addressed
- Approval: granted
- Approver: root orchestrator, clearance-542-cold-cache-oracle-implementation.md
- Recorded at: 2026-10-28T04:27:38Z

### Section B evidence

Issue created 2026-10-24T11:56:18Z. PR579/028dde512f2f43f1c47cb77abff6740b4cf86ca6 delivered authored-test targeting/exact uv; PR595/000753d82c4c5e102fefb90d25eef9e9f0b226a1 delivered changelog sequencing. Parent remains OPEN with typing/cold/acceptance residuals. Post-filing scoped commit79fbaaffe5c22606d5356d268d0b42b74201f885/PR564 labels child controls, not cold predicate. Historical b6e238b/PR378 normalized closure diagnostic;558fe767/PR386 repinned profile;9bda3c59/PR363 targeted evidence;5cf15861/PR340 introduced cold install. Related issues542/568/266/360/20 do not supersede this slice. All21 host worktrees readable; unpublished380c0b885ee3391b4a5495f3f063dd7103aa9e30 in sibling348 touches closure controls in shared test file, not cold predicate, preserved/not adopted.

Current cold consumer raw substring can produce FALSE HARD FAILURE under a phrase-internal wrap, not false green; no live Docker failure established. Closure already folds whitespace and requires both authentic uv clauses. Current complete cold consumer control uses incomplete synthetic cache-only wording; replace within scoped test. Captured fixture, profiles/frozen CPP, Dockerfile/uv pin/public protocol remain unchanged. Actual old complete-consumer wrapped acceptance red must precede production repair; tests use controlled observations, no physical Docker proof.

### Section C - the approved plan

1. `tests/test_profile_install_cold_container_live.py` - small local _offline_cache_miss folds whitespace and requires BOTH literal clauses; use only existing cold-cache/nonzero diagnostic assertion. Preserve unconditional success check, strict _OfflineSyncPropertyHeld marker, cleanup/isolation/env/defaults.
2. `tests/test_offline_cache_miss_oracle.py` - run authentic captured/wrapped/spaces-tabs and missing-clause/unrelated matrices against actual closure AND cold predicates with daemon discovery disabled; closure and fixture unchanged.
3. `tests/test_property_held_xfail_pattern.py` - complete actual cold consumer wrapped regression and contiguous contrast; preserve successful-sync XPASS hardFAIL/unrelated127/permission/setup hardFAIL/cross-property controls. Commit actual consumer acceptance opposite with ONLY cold normalization disabled; named wrapped assertion must fail, contiguous stays narrow XFAIL.
4. `changelog.d/542-cold-cache-oracle.md` - new direct bullet fragment describing bounded robustness, no fresh physical proof or whole542 closure.

Scope: exact4 product paths; approximately110-175 product A+D before separately granted genuine receipt<=60, HARD250 total including future receipt. Exact2 workflow paths issue-542.md and issue-542.as-read.md; HARD250 workflow A+D, preserve old history prefixes. No receipt filename enrolled. Same native a7a19d2097f1484cb522cf39a213bb3a/base000753, no reset.
Risks: exact two-clause grammar intentionally rejects old synthetic cache-only input; no fuzz/casefold/generic xfail or weakening marker. Future uv wording may need fresh evidence; controlled subprocess tests prove discrimination, not container behavior. Small duplicate predicate avoids widening helper/closure ownership; defer remains possible for lower impact. No material frozen protocol concern.545 retains sole heavy priority.
Validation: BEFORE repair genuine outer per-node wrapped acceptance FAIL on unchanged complete consumer, healthy contiguous XFAIL and success/unrelated contrasts. AFTER repair same acceptance PASS; actual-consumer normalization-disabled opposite FAILS acceptance while intact/contiguous controls discriminate. Focused two-file population/IDs/child labels, Ruff/scoped mypy/diff/strict389/frozen/all off-lane hashes/history/native/normal guards and leak bad+healthy controls. Return TESTED UNCOMMITTED; no checkpoint/review/receipt/full/push/issue edit.
