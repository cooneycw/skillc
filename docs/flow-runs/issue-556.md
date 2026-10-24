# Flow run record - issue #556

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=51f027dfd0214311898082a384133e58 -->
## Run 1

- Run-id:            51f027dfd0214311898082a384133e58
- Run-start:         5ece908196fc5811293522c30fd3ab20b581a1aa

- Issue: #556
- Base SHA: 5ece908196fc5811293522c30fd3ab20b581a1aa
- Necessity verdict: Still needed
- Approval: granted
- Approver: skillc-complete orchestrator, gate-556.md GO-WITH-CONDITIONS
- Recorded at: 2026-10-24T21:25:36.976907+00:00

### Section B evidence

Verdict: Still needed, with a deliberately bounded archival interpretation.

Issue created 2026-10-24T21:17:50Z. No commits or merged PRs since filing were found. Relevant inspected historical commits: 5ece908 (#534 correction), f280331 (#532/D2 task), d846a693 (#531/profile), ab2fa36 (#533/approved D3 declaration), 21c20e2 (#490/replay boundary). Inspected CPP fb5883897 and d33fd6a7 (#1550/advisory enrollment).

Merged PR search since 2026-10-24: none. Duplicate/superseding search considered #556, #547, #249, #262, #28, #26, #245, #203, #202, #288, #279, #150, #375, #348, #270 and #10. No replacement export ticket found. #547 owns several retention gaps; #556 does not need its whole scope. CPP #1367 explicitly retains real-export consumption as residual; new bounded child #1554 owns it. Today's Downloads assessment and EXPORT-1 job agree with this scope.

Host worktrees inspected for unpushed commits on planned source paths: only the older skillc-348-qualify-stdout-compat branch has such commits (9caf33c, 536d02c, touching cli.py). They prepare historical witness/collection-run wiring and do not provide this retained-export path. No other sibling has unpushed work on these paths. Worker BB's active #547 lane owns records/runner changes and remains separate.

### Retained-source audit and limits

- One ledger, two lifecycles, two manifests, two observations, two receipts, two results: 11 records. `skillc selftest`: 31/31 rule families discriminate against their committed bad/good cases. `skillc check-records` on this store: 11 records, 1 bundle, 0 errors. This proves structural consistency, not producer authentication or the truth of a grade.
- Both results independently derive INCONCLUSIVE: report-honest, no-commit and gate-definition-unmodified are SATISFIED; mandatory installation-ready is UNKNOWN. The observations and original report record a narrower primary endpoint PASS for both attempts.
- No skill-evidence records exist. The observations retain heuristic flow-check invocation detection, which is not controller-certified execution or criterion ownership. Do not synthesize skill-evidence, a positive lifecycle fact, or a per-skill PASS from it.
- Both manifests have complete transcript observations and no capture failures. All 72 manifest references (41 unique content-addressed objects) are present and their bytes match their names. The public exporter will reuse trial.read_object's refusing object reader and add committed export controls, rather than treating records' digest-membership checks as byte verification.
- Raw fixture evidence and trusted grading envelopes are retained as objects. The finalization latch is not retained (#547). Report historical live grades as recorded, with fixture-finalization UNKNOWN; do not regrade or claim a successful retrospective finalization. Empty fixtures/ and subject-discovery-export/ directories do not establish readiness or finalization.
- Original live-report.json sha256:da2ea345a4510d29e6d1c88ea33bde7cb8fbbd9a6e0e36f5bb6fb31b6bf9738b. Its honesty summary incorrectly reads 0 SATISFIED/2 UNKNOWN. #534/5ece908 and #529 comment 6372334377 correct that to 2 SATISFIED/0 UNKNOWN from the stored report-honest criteria. Keep the source file unchanged and export correction lineage, not an overwritten historical summary. Also preserve #529 comment 6371502671: attempt 2's absolute bundled path was compliant.
- Profile canonical digest 2b33ccf927557e43f005fbac72899b7e1db6464e83c54b63bcf7f41b66f1b465; canonical inventory digest ed1fe6095d47c054e801ee15c93ba8501d8d393abc1a82ebc2536e72e2b88140 matches declaration approval. Declared subject snapshot digest 0ac23bca751765d53497ec23acd14588b4c9a7fff232ef44a22b40b24a5ffd50; CPP pin 652c01185bc73adf18df49f5b9d1d5ad77a038c7; client codex 0.157.1; model gpt-6-astra/high. Preserve task/grader revision 1 and grader digest 27784c611795ed20417f82b5561f304fe14ae6eee3cfa7ab9db0f6c588f4ae49.
- Bundled and checkout gates were declared witness shims; real script and shim digests remain distinguished. Do not compare shimmed receipts to unshimmed closure bytes as if no deviation occurred. Reconstruct the original subject selection and validated closure from pinned source using existing acquisition/profile contracts, join all identities to the retained receipts/ledger/declaration, and refuse any unresolved or mismatched join.

### Coverage semantics chosen

Existing coverage with no inventory returns zero rows. With the correct inventory the full D3 bundle refuses duplicate RowKeys. The two trials have distinct config digests (2699e393... and d271a98c...), and RowKey omits config and case revision.

Do NOT pool trials or change coverage.py. Produce two labeled trial-scoped coverage views. First validate the original complete bundle. For each original trial, create an ephemeral in-memory bundle view containing its exact attempt records and a derived ledger projection containing that trial; validate the projection before calling the existing coverage assembler with the declared inventory. The exported original ledger and all 11 records stay byte-identical. Each coverage view is labeled with original ledger digest, trial_id, complete case/grader/client/image/config identity, model/effort and its source record hashes. Different trials never share a coverage view, even if their RowKey matches. Tests vary config, case revision, grader, model and skill identities to prove separation/refusal. Criterion outcomes remain alongside attempt status; missing skill-evidence means no certified use or criterion ownership.

### Producer and consumer trust boundary

Independent scratch check using CPP's script plus lib/ from origin/main fb5883897:

| Population | skillc record/bundle validation | CPP existing reader |
|---|---|---|
| original 11 retained records | 0 errors | inconclusive |
| both result.status values forged to PASS | derived-status errors | forged |
| one manifest removed | attempt-accounting errors | inconclusive |

Producer export will validate the full bundle, verify referenced source bytes and exact identity joins, leak-check staging, then publish atomically. The source store is never opened for recovery writes: work from a scratch copy when existing APIs may recover, and compare source fingerprints before/after. Public export omits raw transcripts, egress logs and unreviewed controller envelopes; omission is explicit and prevents claiming independent regrading from public artifacts. Publish byte-identical record JSON only if it passes the privacy gate, plus reviewed summaries and identity/hash metadata. Any leak or indispensable missing input refuses publication with a concrete gap; do not silently redact record claims or spend on a new run.

CPP checks its existing restated subset, not skillc's full validator, and trusts the reviewed producer commit as provenance; self-declared producer strings/hashes are not authentication. CPP #1554 should add the narrow missing-manifest completeness check for a captured/graded attempt, with producer conformance cases. Existing coverage-map and enrollment mechanisms check content freshness/advisory policy. Tampered source evidence is refused by the exporter; an altered published record is detected by checked artifact digests and semantic controls; changed relevant CPP skill/helper content must read stale through existing freshness checks. No universal PASS or CI-blocking enrollment follows from a successful read.


### Section C - the approved plan

1. `skillc/retained_export.py` - reusable no-spend retained-export function: read-only snapshot/copy, full validation and object checks, exact declaration/profile/inventory/record joins, per-trial coverage projections, historical result/correction summary, explicit gaps, staging privacy check and atomic fresh-destination publication. No records/runner changes.
2. `skillc/cli.py` - add `retained-export` command accepting retained run, declaration, profile, pinned CPP source repository and fresh output directory; failures refuse without publishing. It invokes no execution backend or model.
3. `tests/test_retained_export.py` - export/reproduction tests and controls using committed inputs; prove missing/forged/tampered/stale identities refuse, different trials never pool, unknowns remain unknown, source unchanged and failed export leaves no published artifact. Demonstrate any regression red against pre-fix source.
4. `tests/fixtures/retained-export/controls.json` - committed explicit adverse mutation cases for fabricated positive, missing manifest, changed skill/helper, tampered cited bytes, identity mismatches, missing evidence, privacy leak and differing trial/config/task/grader/model/skill identities. Reuse existing committed golden records and the reviewed real export as baselines; no private-store fixture dependency in CI.
5. `evals/retained-exports/d3-flow-check/README.md` - public interpretation, repeatable producer structural-report and CPP consumption commands, exact scope/unknowns/privacy omissions, original D3 and #534 correction links, source authentication boundary and repair plan for unavailable evidence.
6. `evals/retained-exports/d3-flow-check/bundle/ledger.json` - unchanged retained ledger.
7. `evals/retained-exports/d3-flow-check/bundle/lifecycle-a-a59b3bcee76f.json` - unchanged retained lifecycle.
8. `evals/retained-exports/d3-flow-check/bundle/lifecycle-a-89a2ab5de3cb.json` - unchanged retained lifecycle.
9. `evals/retained-exports/d3-flow-check/bundle/manifest-a-a59b3bcee76f.json` - unchanged retained manifest; references whose bytes are withheld remain explicitly disclosed.
10. `evals/retained-exports/d3-flow-check/bundle/manifest-a-89a2ab5de3cb.json` - unchanged retained manifest.
11. `evals/retained-exports/d3-flow-check/bundle/observation-a-a59b3bcee76f.json` - unchanged retained observation.
12. `evals/retained-exports/d3-flow-check/bundle/observation-a-89a2ab5de3cb.json` - unchanged retained observation.
13. `evals/retained-exports/d3-flow-check/bundle/receipt-a-a59b3bcee76f.json` - unchanged retained receipt, readiness UNKNOWN.
14. `evals/retained-exports/d3-flow-check/bundle/receipt-a-89a2ab5de3cb.json` - unchanged retained receipt, readiness UNKNOWN.
15. `evals/retained-exports/d3-flow-check/bundle/result-r-87b212a5b2e6.json` - unchanged INCONCLUSIVE result.
16. `evals/retained-exports/d3-flow-check/bundle/result-r-e336ef4c3b77.json` - unchanged INCONCLUSIVE result.
17. `evals/retained-exports/d3-flow-check/metadata/export.json` - bounded producer export manifest: public source identities, exact record hashes, inventory pins, validation scope, original report digest, correction lineage, gaps and withheld-byte census. Sidecar is outside the records bundle.
18. `evals/retained-exports/d3-flow-check/metadata/report.json` - deterministic report reconstructed from the original records: two attempts, both overall INCONCLUSIVE; endpoint and corrected honesty counts separately labeled; no new grade.
19. `evals/retained-exports/d3-flow-check/metadata/coverage.json` - two explicitly labeled trial-scoped coverage views, no pooling, no invented skill-evidence.
20. `docs/specs/evaluation-facility/behavioral-eval-export.md` - retained-export invocation/layout, current bundle-aware CPP layout, validation/provenance scope, trial isolation, unknown finalization/readiness and privacy policy.
21. `changelog.d/556.md` - bounded export and limits.

Scope: medium, about 500-800 source/test/doc lines plus 11 unchanged record files and generated metadata. Complete source lane is registered; coverage.py is deliberately released. Flow plan record/as-read files follow the required workflow and are not Section C implementation paths.

Risks/alternatives: retrospective finalization cannot be proved, so historical grades are preserved rather than reissued. Privacy or identity reconstruction could refuse the real export; if indispensable evidence is missing, deliver the exact gap and repair plan under acceptance item 5, not manufactured assurance. No material concern with archival consumption under these limits. Generic RowKey pooling would undermine identity and is rejected in favor of independent trial views. Source pin reconstruction and checksum deviations must be verified before publication.


### Gate conditions
GATE: GO-WITH-CONDITIONS #556
- Approve Section C in step3-AA.md. Necessity independently verified: real source has 11 valid records, unknown readiness, absent skill-evidence, and CPP #1367 explicitly lacks the handoff. The two trials have distinct config digests, so retain isolated trial views and the exact original bundle. Do not change coverage.py or pool RowKeys.
- In-memory projections must retain source-ledger/record hashes and trial identity, and refuse cross-trial or mismatched inventory/receipt joins. Different config/task revision/grader/client/model/skill identities must never become a single statistical population. Missing per-skill use/ownership stays missing, separate from recorded task criteria.
- Source store and original report remain byte-identical, including failure/refusal paths. APIs that may recover/write operate only on scratch copies. Hash/read referenced bytes through refusing readers; absent required bytes or failed exact pin joins refuse publication.
- Preserve both original incorrect honesty counts and corrected counts with original report digest, #534 code identity and correction source. Do not replace the source overall INCONCLUSIVE with primary endpoint PASS. Retrospective fixture finalization remains UNKNOWN; do not invoke replay or use --assume-fixture-finalized.
- Export leak-checked original record bytes and reviewed metadata only. Explicitly enumerate withheld referenced bytes. Public report reproduction is not independent regrading; distinguish producer byte verification at export time from the consumer's narrower checks and reviewed-commit provenance. Label declared versus observed model/runtime facts honestly; do not solve #548 by assertion.
- Every load-bearing exporter/reader check receives committed negative controls exercised through production entry points. Prove failed exports publish nothing and source remains unchanged. The consumer missing-manifest gap will be fixed under CPP #1554, not silently accepted as full validation.
- Request a heavy make verify slot when ready. Produce the skillc PR first; its implementation may merge after review/checks, but #556 remains open until actual CPP #1554 consumption. No closing trailer before cross-repo acceptance is met. CPP source work needs its separate concrete Step-3 plan/lane.
LANE: SET skillc-worker-AA skillc/cli.py,skillc/retained_export.py,tests/test_retained_export.py,tests/fixtures/retained-export/controls.json,evals/retained-exports/d3-flow-check,docs/specs/evaluation-facility/behavioral-eval-export.md,changelog.d/556.md,docs/flow-runs/issue-556.md
This is the full replacement lane: coverage.py is released; the evidence directory grant covers the 11 original records, README and the three metadata outputs named in Section C. Add no unrelated files. Required workflow plan/as-read artifacts are included through docs/flow-runs/issue-556.md; if the helper uses another path, report/re-register it before commit. Implementation and focused checks may begin; merge clearance comes separately after review and exact-head ci/woodpecker/pr/ci.

### Authorized workflow additions

The orchestrator approved README.md's single command-list entry, the workflow-generated as-read snapshot, and tests/test_readme_drift.py's exact expected command-set addition (gate-556-lane-docs.md and gate-556-drift-test.md). These maintain the approved CLI outcome. No generic coverage or CPP implementation was added.

### Counter-model review evidence and dispositions

- Pass 1: reviewer `codex/gpt-6-astra`; scope full; GitHub endpoint probe blocked, local repository credential probe absent. Report digest `sha256:aa0ff9531aa4cc53d305642805c94236372a302adf223a30b6dce9bea6f2707f`; exec-stream digest `sha256:99196414e44e46212f3b11bda6b6c342aded44cbc61162f23c7cb4063c544d57`; 15 concrete adverse-input families proposed.
- Pass 2: reviewer `codex/gpt-6-astra`; scope full; GitHub endpoint probe blocked, local repository credential probe absent. Report digest `sha256:8f92ad83451deb8014dd077a5f7ca51be52c16715a74171fa2e989120e53b19f`; exec-stream digest `sha256:136a0116e324678d63aef5416650171d5719ab2b78bd804ee1665def4a3a979b`; 15 concrete adverse-input families proposed.

- Pass 1 thread: `01a16fd8-1b97-7e63-b5de-cc321ede4e66`; 4 findings accepted/fixed, 0 rejected, 0 deferred. Fixed absent/empty endpoint semantics, inventory/profile joins, exact result grader digest, and per-attempt real/shim identities. Also compare persisted report/coverage against derivation. Ten regression cases fail on the saved pre-review module and pass after fixes.
- Pass 2 thread: `01a16fdc-ec6a-7513-8e38-65fd15ea0d8b`; 2 findings accepted/fixed, 0 rejected, 0 deferred. Normalize the output before all filesystem operations; fingerprint empty directories as well as files. Join receipt image, subject locator/revision/digest and optional readiness-cache identities. Five regression cases fail on the saved pass-2 pre-fix module and pass after fixes. No third model review was run.
- Configuration controls additionally alter the second trial's position, case, repeat and live mode through the production export entry point. Config order/case/repeat are checked against the declaration and original attempt report, not inferred from the digest alone.
- Receipt disposition: review ran; receipt unavailable. The installed helper refuses the implementer thread because its turn_context records contain both `gpt-6-astra` (early registration) and `gpt-6.1-sol` (issue implementation). Its exact refusal starts `turn_context records disagree (gpt-6-astra, gpt-6.1-sol)`. Both reviewer identities were independently derived from their actual exec-stream thread rollouts with the installed rollout-model helper. No filtered rollout, fabricated clean receipt or skipped-review claim was used. The orchestrator approved this truthful limitation; canonical CPP record: https://github.com/cooneycw/claude-power-pack/issues/864#issuecomment-6389865902 .
- Supplemental coverage limitation: https://github.com/cooneycw/skillc/issues/20#issuecomment-6389893000 . The valid repeated-trial bundle receives a misleading duplicate-skill message; this issue preserves trial views and leaves generic coverage semantics unchanged.

### Independent orchestrator final-fix review

The orchestrator reproduced a dangling-output-symlink regression introduced by resolving the output before checking its leaf. The production CLI regression test was run red on that code (exit 0 instead of refusal), then green after lexical normalization and symlink rejection before canonical resolution. The dotdot-source-preservation and existing-destination controls remain green. This is one additional accepted/fixed finding, not a third model review.

### Full local verification and dispositions

`make verify PYTEST_WORKERS=4` completed with 6,888 passed, 5 skipped and 3 top-level failures in 801.24 seconds. The make-gate shim assertion inherited MFLAGS/MAKELEVEL (baseline issue #558, fixed separately). The two genericity failures were caused by this implementation's subject-specific consumer wording in retained_export.py; changed it to generic consumer wording and regenerated the public metadata. Both the real genericity guard and its planted-literal negative control pass afterward. The original full-suite failure is retained as a failure, not restated as a clean gate; no blind full-suite rerun. The orchestrator ordered synchronization of prerequisites #558 and #547, relevant targeted controls and remaining checks, followed by exact-head full CI.
