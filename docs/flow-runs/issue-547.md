# Flow run record - issue #547

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=7f1fd2bf1aa54a94a0382d8d257608a9 -->
## Run 1

- Run-id:            7f1fd2bf1aa54a94a0382d8d257608a9
- Run-start:         5ece908196fc5811293522c30fd3ab20b581a1aa

- Issue: #547
- Base SHA: 5ece908196fc5811293522c30fd3ab20b581a1aa
- Necessity verdict: Still needed
- Approval: granted
- Approver: skillc-complete orchestrator (Codex thread 01a16fc0-b6a3-7011-9980-717e7c02f426), GO-WITH-CONDITIONS
- Recorded at: 2026-10-24T21:24:59.133136+00:00

### Section B evidence
Verdict: Still needed for assigned items 1-3; this is a bounded delivery, not closure of #547.

Evidence since filing 2026-10-24T11:56:23Z:
- Commits: none since filing globally or touching lifecycle.py, gate_witness.py, agent_trial.py, records.py or fixture_live.py. Current base is 5ece908. Relevant inspected history: 5ece908 (#534), f280331 (#532), d846a69 (#531), 653353e (#527), 000dbf8 (#526), bbfb55d (#524), 80eca1d (#523), 0636d81 (#517).
- Merged PRs since filing: none (same-day merged query returned []). Above earlier PRs changed witness/fixture plumbing but retained the three omissions.
- Related/duplicate issues inspected: #202 (closed transcript retention on success), #404 (closed forwarding truncation, not persistence), #367 (closed channel-finalization latch), #434 (closed campaign), #545 (open grading-path lag), #556 (AA's EXPORT-1), #20 (source Nit Store). None supersedes these retention items. Searches also returned #542/#544/#550/#551/#552/#554/#555; no claim that those unrelated aggregates close this slice.
- Host sibling inspection: all listed worktrees were queried for unpushed commits touching the five issue paths. Only skillc-348-qualify-stdout-compat has such a commit: 9caf33c, the old #348 runtime/witness integration. Its diff integrates witness readiness/controller output transport, not transcript-on-failure, retained run output or finalization outcomes. No sibling implementation of the assigned slice found; no unreadable worktree.
- Pre-fix reproduction run now, without source edits: FakeBackend export failure and untouched-canary paths both return inconclusive, call transcript_for_capture zero times, and report retention missing/no manifest. A real GateWitness decision returns stdout='FLOW_FINISH_GATE: warn\n' and stderr='check skipped\n', but its serialized run has only timestamps/exit_code/reason/tree_digest/stop_confirmed. A live failure supplied to build_observation_record is absent from the resulting closed record. Code inspection confirms FixtureSession.extras also omits its failure/finalization state and judge_replay blocks by default for that reason.


### Section C - the approved plan
One PR, three reviewable implementation stages (transcript, gate output, finalization), with no issue-closing trailer. Requested complete actual lane is the numbered file list below; extensions beyond the initial grant are marked EXTEND.

1. `skillc/trial.py` - add write-once retention of the caller's already leak-checked TranscriptEvidence as content-addressed bytes plus a transcript-retained journal detail event. Add a reader validating attempt identity, stream/origin/coverage, digest, size and referenced bytes. This is independent of the artifact manifest and never records captured or changes disposition. Existing manifest transcript entries remain available.
2. `skillc/lifecycle.py` - obtain and retain the observed transcript before export/liveness can fail and before teardown. Reuse the same evidence for normal manifest capture. If stop is unconfirmed, retain only explicitly partial evidence; missing/refused evidence carries its reason. Callback/storage failures must not skip teardown/accounting or manufacture captured success.
3. `skillc/agent_trial.py` - make stored-transcript lookup use manifest entries or the independent retained event, recheck content-addressed bytes, and preserve refusal of incomplete evidence for recomputation. Supply the production GateWitness with a controller-owned output sink. Keep existing transcript leak checks; gate output also must pass identity/credential checks before storage.
4. `skillc/gate_witness.py` - snapshot each resolved run's stdout/stderr through the output sink before forwarding/refusal, storing only bounded content-addressed references and explicit coverage metadata in the run. Bound each stream by its corresponding execution capture cap; retain available prefixes as partial when truncated/incomplete, and keep missing/refused distinct from empty complete. Add a reader that validates reference shape, size and digest against retained bytes. No synthetic stderr from the human error summary is called raw stderr. Gate execution/credit derivation is unchanged by retention.
5. `skillc/fixture_attempt.py` - latch an explicit first finalization outcome (not-observed/succeeded/failed) around the whole finish operation, including exceptions after service/git capture. Include that outcome in controller-held extras persisted before grading; an early bind failure or finish never reached is not succeeded.
6. `skillc/fixture_live.py` - recognize historical extras and extras with finalization. Strict replay accepts only validated recorded succeeded; recorded failed/malformed/unknown blocks, including when --assume-fixture-finalized is supplied. The historical assumption remains available only when no outcome was retained. Labels state whether evidence was established or historically assumed.
7. `tests/test_trial.py` - retention write-once, missing bytes, altered bytes, wrong attempt, bounds and no-promotion cases.
8. `tests/test_lifecycle.py` - regressions for export failure, untouched canary, capture refusal, unconfirmed stop and normal capture, proving bytes survive teardown while failed attempts remain inconclusive.
9. `tests/test_agent_trial.py` - manifest/independent-event lookup, honest missing/refused coverage, tamper refusal and recomputation limits.
10. `tests/test_gate_witness.py` - exact stdout and successful-run stderr retention, red gate diagnostics, reruns, missing/partial/refused output, invalid reference/digest/size and unchanged execution conclusions. Retain the existing assertion that ExecuteResult objects are not accumulated.
11. `tests/test_agent_trial_fixture.py` - actual fixture finish success and late failure both survive in the raw retained extras, including evidence already produced before the exception.
12. `tests/test_fixture_live.py` - strict replay from succeeded evidence; failed, missing, malformed and tampered evidence cannot authorize grading; legacy default remains blocked and legacy explicit assumption remains labeled.
13. `tests/fixtures/retention/cases.json` - committed good/bad reader inputs for transcript metadata, gate output metadata and fixture outcomes; include wrong-attempt, altered/missing-object, bad digest/size, succeeded, failed, unknown and malformed outcomes. These controls are exercised through the real readers/strict replay and are not declarations of expected success alone.
14. `docs/specs/evaluation-facility/records.md` - independent retention journal detail semantics, content identity, failure coverage, historical absence and limits. No new version-2 record family or relaxed artifact-manifest requirements.
15. `docs/specs/evaluation-facility/gate-witness.md` - output retention shape, bounds, leak refusal, missing versus empty, and reader verification.
16. `changelog.d/547.md` - scope and explicit residual boundary.

Schema compatibility:
- Keep v2 ledger/manifest/lifecycle/agent-observation schemas unchanged, including nonempty artifact capture and existing controls. No records.py or controls-family change is needed for a new rule because no v2 rule is being widened.
- transcript-retained is an additive raw-journal DETAIL event, not a new lifecycle verdict. It carries the existing observation metadata shape. Old stores lacking it still read via their manifests, otherwise missing. New reader validates identity/content before reporting retained bytes.
- Gate witness remains version 3 with an additive per-run output field (the same compatibility approach used for stages/source_digest/via). Historical absence is unavailable, never empty complete. Manually constructed historical GateRunRecord instances remain serializable. Production always supplies the retention sink; no sink records unavailable rather than claiming retention.
- Raw fixture extras gain a finalization object; replay explicitly recognizes old and new shapes. Existing v2 record schemas are untouched. No outcome means historical unknown, not clean.

Validation / committed negative controls:
- Write regression tests first and execute them on unchanged production code, recording their expected failures, before implementing each stage.
- Transcript: backend writes observed transcript then export raises, canary remains untouched, or capture refuses; read back identical bytes after teardown and verify inconclusive remains. Wrong-attempt/missing/tampered object controls must refuse through the actual reader; complete valid references must pass. Leak-refused bytes must not be stored.
- Gate: real failed gate stdout plus raw stderr survive serialization and object readback; committed missing/altered/wrong-size output references refuse. Capped/incomplete output is partial, missing raw stderr is missing, empty actual bytes are complete, and credential-bearing output is refused without storing it. Existing process/coverage controls remain unchanged.
- Fixture: inject failure after service evidence exists. Retained outcome must be failed and strict replay must not invoke the judge, even with the historical assumption switch. Recorded succeeded plus valid surrounding evidence must invoke the real judge; missing/malformed/unknown/failed controls must not. Historical records retain the current default refusal and explicit assumption label.
- Run targeted suites plus selftest before trusting any check output, lint and typecheck. Request a heavy-gate slot before make verify; strict required check is ci/woodpecker/pr/ci at the final reviewed head. No paid run.

Scope: 17 files, approximately 600-900 added/changed lines including tests/docs/controls; medium-sized, staged retention change.
Risks: output can contain identities/credentials; retention must reject unsafe bytes without changing the observed execution result. Retention must never promote failed capture to captured or incomplete evidence to complete. Historical compatibility must not convert missing outcomes into success. Finalization must cover the late-exception window. The sibling #348 branch overlaps old plumbing but does not implement this work.
Plan challenge: coupling transcript storage to successful artifact capture undermines the intended diagnostic outcome; the separate journal-bound reference removes that dependency while leaving capture's success conditions intact. No other material concern found.

### Execution note - approved review-attribution disposition

The skillc-complete orchestrator approved this annotation after independently
checking both reviewer rollouts and this worker's model-change timeline. Section C
above remains the approved plan; this note adds execution evidence, not scope.

Counter-model review ran twice on measured `codex/gpt-6-astra`. The implementer
changed from `gpt-6-astra` during registration to `gpt-6.1-sol` before the assigned
analysis/implementation; the orchestrator verified that detected write events
were in the latter interval. The receipt helper refuses whole-thread attribution
because its turn contexts name both models. No receipt was invented, and the
completed review is not represented as skipped. Preflight scope: `unverified`;
network: measured `blocked`; repository-local credentials: measured `absent`.

- Pass 1: reviewer thread `01a16fd5-da5f-7690-9310-64a3d17c5b41`, report digest `sha256:aaee880d3ee12af82a821163368056a5d057fd62e46b19edee7e2d891d60f3f3`; one LOW finding accepted/fixed.
- Pass 2: reviewer thread `01a16fd9-369b-74d2-80b0-975380693448`, report digest `sha256:e40bdd6e4efc76340f6cdd41358cdfe53af1a078924f5bc12d1b0d3c2403ffa1`; clean after the test fix.

The accepted LOW finding was a test gap: finalization's late failure was only
checked in memory. The added production-path test reads its persisted failed
outcome, then proves strict replay never invokes the judge with either historical
assumption setting. Five new live-path cases pass, also covering raw gate stderr,
failed channel drain and unsafe-output refusal. No new paid evaluation ran.

Receipt limitation: https://github.com/cooneycw/claude-power-pack/issues/864#issuecomment-6389865902.

### Validation note - baseline prerequisite and synchronized tree

The first full local finish gate reconciled 6,910 identities: 6,904 passed,
5 skipped and one unchanged make-shim test failed because `make verify` exports
`MFLAGS`/`MAKELEVEL` while the test cleared only `MAKEFLAGS`. The exact failure
was reproduced on clean main and recorded separately in skillc's Nit Store
comment 6389989656. That failed run is not relabeled green.

The separately reviewed test-only prerequisite landed in PR #558 at
`237ab8fb6198c61f4dd687ef3179906aca5b6e3f`, after required
`ci/woodpecker/pr/ci` succeeded on its exact reviewed head
`1b1ce3fc183b159f74bc6cd348053a32416bd4dc`. Its worktree and branch were
removed by the guarded helper. This branch then merged that main base normally,
without stash or conflict.

On the combined tree, both exact polluted-environment controls passed and all
692 tests in the eight affected suites passed (73.05 seconds, four workers).
The remaining checks caught and corrected this PR's fragment format: the
repository requires one bullet per issue, not three. That gate reads committed
HEAD, so the correction is committed before rerunning the remaining checks.
Per the orchestrator's validation ruling, the combined tree uses affected local
suites plus required exact-head full CI instead of repeating the complete local
suite while the other worker owns that slot. Final check evidence is recorded
in the PR and the wave ledger; no new paid evaluation was run.

<!-- flow-run n=2 id=4de641e636f84d66aeca12423bd7b3a0 -->
## Run 2

- Run-id:            4de641e636f84d66aeca12423bd7b3a0
- Run-start:         1c7c4c73b22c666131d0bb38a3a7ccc79999b756

- Issue: #547
- Base SHA: 1c7c4c73b22c666131d0bb38a3a7ccc79999b756
- Necessity verdict: Partially addressed
- Approval: granted
- Approver: skillc-update root orchestrator, native thread 01a17ce7-0301-7621-8b1f-bf330eed8b5d; actual Section C ruling 2026-10-27
- Recorded at: 2026-10-27T14:53:39.757758+00:00

### Section B evidence
Verdict: **Partially addressed**. Implement only independent controller-issued input retention and record explicit bounded dispositions for the remaining checklist items.

Issue filed 2026-10-24T11:56:23Z, OPEN at the fresh read. Global and scoped post-filing logs, all returned merged PR metadata and both duplicate searches are saved beside this report. Scoped post-filing commits inspected: c80455538d4412391a375b76202f8c4ec6338be7 (#559, first three retention slices); 1fcf690621d6d8fb091abafa17b56a134614e786 (#567, resumed fixture-state attribution); 6b78522a9e16baca33254dfc448a8cbc59e166d1 (#570, frozen declaration/pre-nonce prompt fingerprints); 1c7c4c73b22c666131d0bb38a3a7ccc79999b756 (#583, shared completion/ownership endpoint). None supplies an independent actual post-nonce initial/final-resume input trace.

All returned post-filing merged PR metadata, explicitly enumerated (not a claim every diff was read):
- #583: 1c7c4c73b22c666131d0bb38a3a7ccc79999b756 - Preserve shared completion deadlines through Docker dispatch and grading
- #582: 5d04193feaa17194172ae37740ed5d4480b0b711 - Prepare offline flow-auto profile and strict synthetic-path leak checks
- #579: 028dde512f2f43f1c47cb77abff6740b4cf86ca6 - fix(controls): target authored tests and require exact uv version (Refs #542)
- #578: 1e7ae69f9af60d096d771218e1a6c0898b8e84c9 - Support bounded owner-triggered real-Docker opt-ins
- #575: 29d702d8cc7cc24620c64d9275d286b4f34cfefd - fix(tests): make offline publication proofs discriminate (Refs #574)
- #573: 357095af692b72565e4273a14d0aab6a3c8fae04 - feat(coordination): certify bounded scripted register waves (Refs #569)
- #572: b2464354b16d0cc28b1c2ffcd6f133715e38c2d6 - feat(eval): certify atomic inventory artifact task (Refs #568)
- #570: 6b78522a9e16baca33254dfc448a8cbc59e166d1 - Add bound explicit-product calibration comparisons
- #567: 1fcf690621d6d8fb091abafa17b56a134614e786 - Attribute resumed fixture gates to witnessed state
- #566: 08a6887053eb7bcf3c7d3fc6545a7aa7aad2ec74 - test(evals): replay source-linked historical helper failure (#28)
- #565: a924c5f00a9da21b87357764a979c9c6868340a5 - fix(backend): validate concurrent trigger directory winner (#563)
- #564: 79fbaaffe5c22606d5356d268d0b42b74201f885 - test(controls): label nested pytest child outcomes (#489)
- #562: 9a62b80979bf3e374049d0933f7e6822bb9d9cda - fix(fixture): preflight live opt-in and retain scan facts (#536)
- #561: 7373a5b4c6245a20a2cbff74e3dfba51e240f9f4 - Run and audit the historical 18-attempt calibration repeat (#557)
- #560: a3e9ba8049c6dd3a97c64fd8d9d35e7296cd3835 - Export retained fixture-live evidence without another trial (Refs #556)
- #559: c80455538d4412391a375b76202f8c4ec6338be7 - feat(retention): keep failed-attempt diagnostics and fixture finalization (Refs #547)
- #558: 237ab8fb6198c61f4dd687ef3179906aca5b6e3f - test: isolate make-shim roundtrip from inherited make variables

#559/c804555 and issue comment 6390273375 already delivered failed-attempt transcript retention, bounded gate stdout, and the fixture-finalization latch. Complete safe transcripts can already retain initial/resume text; no claim that prompt bytes are absent everywhere. #560 preserves withholding of private retained objects, and #582 tightened synthetic-path leak handling. #583 is now shipped, #580 closed, and separate actual main push 1125 succeeded; no longer a prospective dependency.

Related-issue search hits considered by number/title/state: prompt/retention #547,#26,#287,#568,#203,#434,#20,#376,#375,#288; vocabulary/selection #547,#548,#247,#26,#249,#286,#553,#255,#279,#203,#287,#20,#568,#525,#530,#529,#334,#505,#39,#266,#101,#237,#78,#55,#332,#11,#270,#288,#10,#271,#315. #547 and #548 bodies were inspected; most other hits were title/state triage, not full-body inspection. #568/#571 are downstream study/attachment consumers, not delivered controller-input retention. Shipped #354/#424 per-skill pinning and #272 stale-identity binding narrow the original ask. No search result was treated as a duplicate merely because its title overlaps.

Host check: all 19 listed worktrees were readable; scoped dirty paths were empty. One sibling has a relevant commit on no remote: skillc-348-qualify-stdout-compat, HEAD d3ea7029b89b6358ff0ed2e8b2e3952d018b92d5, commit 9caf33c452efb9c1da5b3b0714677d2e9f1db5d6. Its relevant agent_trial/test_agent_trial diff was inspected: runtime/witness readiness, trusted stdout, finalization/grading wiring, not independent controller input retention. #348 closed 2026-10-24T09:35:06Z, before #547 filing. The other 18 had no unreachable scoped commits or dirty scoped paths at the recorded check. This is this host's evidence only; not a statement about other hosts or all future sibling changes.

Fresh source proof: source-facts.json records file SHA256 and 49 named function extents/hashes; all 28 functions compared with the previous prospective preparation are byte-identical at actual delivered base 1c7. Extraction controls found a known function and rejected an absent name; actual plan_calibration is also present. The hash method matches the earlier AST source-segment method, excluding decorators. Lock decorators were separately inspected in source. Important source facts:

- agent_trial.py:2758 builds full_prompt after the actual runtime nonce; :2762 appends it to initial argv. Its next_turn closure constructs final resume_argv after header/session/steward checks. controller_turns.resume_argv appends the literal resume text. Only that prompt argument is selected for retention, never the full argv/session/environment.
- Fresh lifecycle.py:321/:531 dispatch details contain no argv; resume ended/delivered fields describe backend launch. trial.run also journals dispatch without argv. agent_trial's turn-record projection keeps status/index/order, not prompt text. Thus existing journals do not secretly fill the proposed independent-text gap. Agent-observation remains closed and text-free.
- trial._locked/experiment_lock and retain_transcript provide the existing locking pattern. The new terminal writer needs deliberate post-finalization detail permission under the SAME lock; calling retain_transcript after finalization would refuse. No lifecycle.py edit is proposed.
- Existing trial._read_object uses unbounded read_bytes. The new strict prompt reader must use the existing _read_bounded O_NOFOLLOW/fstat/bounded-descriptor pattern with canonical digest/ref, size and strict UTF-8 verification. Do not stat then read unbounded, or silently trust object membership.
- matched_pilot.export_bundle copies records/report only; objects and journals remain private in the source store. retained_export lists raw objects as withheld. Neither gets a raw-prompt export feature.

Proposed remaining-item dispositions:

- Item 4: implement the bounded independent controller-issued text trace; healthy transcripts remain complementary evidence. No claim to capture all startup context, manual intervention, system/tool messages or all protocol 10.1 requirements.
- Item 5: already addressed for the planned per-path/version selection in pinned trials. records.md:164-178 explicitly explains trial.skill_digests and why outside-bundle inventory no longer leaves that pinning gap. profile.skill_digest_pins, calibration_run._installed_skill_pins (same captured installed bytes), calibration/discrimination, fixture_live and uptake_study planners were inspected. Historical/unpinned absence stays unknown. level3_campaign and fixture_campaign, matched_pilot and collection_conformance remain unpinned routes; #548 owns its selected level3 remedy, not proof all other routes are fixed. coverage reports still require separate DeclaredInventory; no duplicate inventory or automatic inference added here.
- Item 6: accepted bounded validation for general witness citations: captured-digest membership plus structure/internal consistency, not universal path/type/semantic authenticity. Stale-identity already separately binds receipt identity under #272 and rejects wrong witness kind. Stronger source-specific semantics need a separately authorized contract and accepted/refused populations.
- Item 7: explicitly rule out adding declared-skill-not-installed under the current schema. records.py:204-207 keeps two reasons; _skill_evidence_binding rejects an uninstalled skill.path unconditionally. There is no legitimate accepted bundle for that extra reason without an independent externally claimed identity/new field. Do not add dead vocabulary just to check a box.

These last three are proposed bounded dispositions requiring the actual source/control reason to be recorded on #547 before whole-issue closure, not a claim it is already closed. Existing pin controls test_a_skill_digests_pin_is_kept_in_the_ledger and test_every_treated_trial_is_planned_with_the_installed_skills_digests were located; no new execution is claimed.


### Section C - the approved plan
1. `skillc/trial.py` - bounded store-local prompt-input marker and ordered turn entries, private CAS/journal publication, strict actual-byte/state reader, and terminal prepared-population detail under the existing experiment lock. Separate per-turn availability from whole-trace coverage and launch/transcript facts.
2. `skillc/agent_trial.py` - capture exact initial argv prompt after nonce assembly and exact final resume argv prompt when actually prepared; integrate existing leak/secret checks, bounded class-only refusal, terminal evidence before grading, and inherited completion/cleanup behavior.
3. `tests/test_prompt_retention.py (new)` - committed accepted/refused inputs for byte, identity, ordering, terminal, privacy, allocation/cap, CAS/journal failures, locking and public withholding claims. Include prospective export controls without calling them old-code regressions.
4. `tests/test_trial.py` - CAS/journal integration and frozen attempt binding using the actual existing store machinery.
5. `tests/test_agent_trial.py` - existing production entrypoint with synthetic nonce/scripted backend: no usable transcript, mismatch and failure retain independently bound exact initial text; raw task facts remain intact when diagnostic retention refuses.
6. `tests/test_controller_turns.py` - actual final resume text and prepared-but-suppressed, never-started, cancelled, healthy and legacy distinctions; no launched-equals-read assertion.
7. `docs/specs/evaluation-facility/records.md` - store-local detail/read contract and explicit pin/witness/vocabulary/historical bounds; no public record-kind/schema expansion.
8. `docs/specs/evaluation-facility/protocol.md` - exact controller input versus full startup context and observed reception; privacy/length/unknown limits without weakening existing requirements.
9. `changelog.d/547.md` - describe only the selected retention change and recorded bounded dispositions.

Scope: nine product paths, estimated 700-1000 authored added/deleted lines; ceiling 1100 inclusive later genuine receipt at separately root-granted path. Workflow records are excluded from product compliance.
Risks: full startup-context capture, public raw-byte export and downstream study readiness are not supplied. Exact bounded descriptor reads, shared experiment lock including post-final terminal writes, independent prepared population and UNKNOWN incomplete coverage are required. Missing diagnostics preserve raw task facts.

Root approval conditions: existing-API behavioral red on actual pre-fix first; committed accepted/refused reader/privacy/terminal/cap inputs; bounded item5-7 dispositions before any proposed closure; no whole-issue closure or heavy/full/review/receipt/PR/merge without later gates. No lifecycle/backend/public-schema/CLI/inventory changes.
