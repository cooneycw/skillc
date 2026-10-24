<!-- flow-run n=1 id=51f027dfd0214311898082a384133e58 -->
## Run 1 - issue #556 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #556
- Read at:      2026-10-24T21:19:04Z
- updatedAt:    2026-10-24T21:17:50Z   (context only - moves on comments and labels)
- Body digest:  9f847728b21edfa58b6ea4f965dac2542bd9a69105274f436f7e325e5bf7de3b   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 4167 of 4167 (cap 16384)

### Body as read
## Outcome

Complete one real retained flow-check producer-to-CPP evidence handoff without another model run. This is EXPORT-1 from the 2026-10-24 WSJF assessment, authorized by the owner through wave skillc-complete. Parent outcome contracts: #249 and #262; CPP consumer outcome: cooneycw/claude-power-pack#1367.

## Existing evidence and measured gaps

Use #529 D3 at CPP 652c0118, declaration sha256:9f721d18c0da364be5dce393e51322a8c40a9c9e96daf3ba65015fe6bd24ba9c, with correction #534. The original live-report must remain unchanged. Retained source store is host-private; obtain its location from the wave brief, never publish private raw transcripts by default.

The 2026-10-24 assessment checked a temporary copy of the 11 retained record files: skillc bundle validation passed, CPP consumer read INCONCLUSIVE, and fabricated PASS statuses were refused by both. Both attempts have report-honest/no-commit/gate-definition-unmodified SATISFIED, installation-ready UNKNOWN, and overall verified-result INCONCLUSIVE. The live report's primary endpoint PASS must not replace that overall verdict.

The bundle contains no skill-evidence records. The coverage assembler without a separately supplied declared inventory renders zero rows. CPP intentionally implements a subset of producer validation: removing a manifest was rejected by skillc but not independently diagnosed by CPP. The handoff therefore must establish and preserve the actual producer-validation trust boundary.

## Bounded delivery

1. Audit the retained records and referenced bytes needed for the claims; name what is retained, reconstructible, or unavailable. Do not assume fixture finalization succeeded merely because no persistent field records failure (#547).
2. Add the smallest reusable no-spend export path needed for this existing live store. Prefer existing record, coverage, profile and export contracts. Bind exact subject/skill/profile/task/grader/client identities and declared inventory. Derive skill-evidence only from retained authoritative evidence and name any limits; do not invent positive observations.
3. Preserve original records and attach correction lineage for #534. Publish only privacy-safe reviewed artifacts; retain unknown installation readiness and distinguish primary endpoint from overall status.
4. Supply a real consumer-ready bundle plus concise human interpretation. Coordinate a bounded CPP child under #1367 to consume it using the existing reader/freshness mechanisms; do not declare the cross-repo handoff complete before CPP actually reads the produced artifact.
5. If the store lacks indispensable evidence, deliver an exact refusal/gap disposition and a bounded repair plan rather than manufacture facts or silently run a replacement study.

## Acceptance

- A reader reproduces the producer report from retained source records and maps the result to one declared flow-check skill/profile, with fixed attempt counts and explicit unknowns.
- Actual CPP consumption preserves the bounded inconclusive/advisory interpretation; no universal PASS or CI blocking enrollment.
- Committed negative controls show fabricated positive, missing required record, changed skill/helper content and tampered cited evidence cannot produce current positive assurance. Keep producer vs consumer checking scope explicit.
- Original D3 evidence and correction are both traceable. Original host store is unchanged. Export passes leak checking with its own discriminating controls.
- Appropriate repository gates and exact-head CI pass. Any regression test is demonstrated red before its fix.

## Boundaries

No paid trial, new backend, generic schema redesign or deployment. #547 is an audit input, not a whole-ticket dependency; coordinate overlapping record changes through the orchestrator. Work is authorized to implement, commit, push and merge after wave gate review and required checks. New study approval remains separate.

Likely paths: skillc/cli.py, skillc/coverage.py, a dedicated retained-export module, export tests, privacy-safe eval evidence, docs/specs/evaluation-facility/behavioral-eval-export.md, changelog.d/. Exact lane is set after Step-3 review.

