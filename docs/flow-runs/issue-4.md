# Flow run record - issue #4

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
below. It is not a description of the shipped system, it is not a second
statement of the issue contract or of a Tier 3 spec, and it does not graduate.

- Issue:             #4
- Base SHA:          95fead8709e97c843907d531a4da9594799019d9
- Necessity verdict: Partially addressed
- Approval:          granted
- Approver:          repository owner (cooneycw), interactive "approved" in the /flow:auto session; D1 took envelope version 2 with an exact supported set, D2 took one PR closing #4
- Recorded at:       2026-09-26T13:00:00Z

## Section B evidence
- commits since filing touching skillc/ controls/ docs/specs: 857781f (#17, the
  artifact-manifest + verified-result slice, "#4 stays open"), b8809e0 (#2), 95fead8 (#3),
  e02a217 (#22 docs), 2f74b83 (planning baseline)
- merged PRs since filing: #17, #21, #24, #25, #29, #30, #31 - only #17 addresses #4, partially
- duplicate/superseding issues: none (#8, #9, #28 depend on #4; #1 is the roadmap)
- remaining per #17's own boundary: installation receipts, trial ledger and planned
  attempts, producer/authority, retry/regrade lineage, observation requirements and
  retention, the ledger half of stale/cross-trial receipts
- stdlib-only already enforced by tests/test_frontmatter.py import walk with a control (#3)
- defect found in scope: record_envelope accepts version 0, negative and `true`

## Section C - the approved plan
1. `skillc/records.py` - installation-receipt and trial-ledger kinds; producer authority per kind; envelope version 2 exact set, bool/zero/negative refused; optional raw ref+digest; per-record and bundle rules
2. `skillc/checks.py` - register new rules; BundleRule in the one ALL_RULES registry
3. `skillc/cli.py` - check-records runs bundle rules; selftest subject loader third branch
4. `docs/specs/evaluation-facility/records.md` - full v2 contract: producers, derivation, missing evidence, origin/coverage, lineage, versions, observation requirements, retention boundary, what a green does not establish
5. `docs/specs/evaluation-facility/interfaces.md` - status line points at records.md
6. `docs/specs/evaluation-facility/review.md` - correct the stale "Two record forms" sentence
7. `PLAN.md` - note that the contracts are versioned; gates and order unchanged
8. `controls/record-envelope/` - bump to v2; bad cases v1, bool, zero
9. `controls/attempt-binding/` - bump to v2, add producer
10. `controls/artifact-digest/` - bump to v2, add producer
11. `controls/criterion-vocabulary/` - bump to v2, add producer
12. `controls/derived-status/` - bump to v2, add producer
13. `controls/installation-receipt/` - new pair
14. `controls/trial-ledger/` - new pair
15. `controls/producer-authority/` - new pair; bad is a forged subject verdict
16. `controls/criterion-evidence/` - new pair; bad is missing mandatory evidence
17. `controls/observation-coverage/` - new pair; bad is a silent required stream
18. `controls/ledger-binding/` - new bundle pair; cross-trial, stale, unknown attempt, artifact digest mismatch
19. `controls/unique-ids/` - new bundle pair; duplicate and conflicting IDs
20. `controls/attempt-accounting/` - new bundle pair; planned attempt with no result
21. `controls/lineage/` - new bundle pair; retry reusing an ID, erased original, cross-attempt regrade
22. `tests/test_records.py` - discrimination/attribution over new rules incl. bundles, uncontrolled bundle rule UNPROVEN, version edge cases, preserved FAIL, malformed attempt ID
23. `README.md` - rule count and records description
24. `AGENTS.md` - layout line
25. `docs/flow-runs/issue-4.md` - this record

Scope: ~21 source/doc files plus ~30 small JSON fixtures, ~1,200 lines, about half fixtures/tests.
Risks: v1 records stop validating (intended, D1); a bundle subject must not split the
UNPROVEN guarantee (pinned by test); producer is declared, not authenticated (stated in
docs and output); large PR.
