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
