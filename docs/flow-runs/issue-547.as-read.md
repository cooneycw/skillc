<!-- flow-run n=1 id=7f1fd2bf1aa54a94a0382d8d257608a9 -->
## Run 1 - issue #547 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #547
- Read at:      2026-10-24T21:19:04Z
- updatedAt:    2026-10-24T11:56:23Z   (context only - moves on comments and labels)
- Body digest:  5fe9be4d6427f90dea20fef153e2469c8d3fae08d2b69754ffe503f5ce2d9884   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 15844 of 15844 (cap 16384)

### Body as read
**Severity: LOW, MEDIUM.** Nothing here is HIGH, and nothing blocks work now. Filed at the owner's request from the Nit Store aggregation pass https://github.com/cooneycw/skillc/issues/20#issuecomment-6383442993 (group G6).

## Problem
Retained records keep less than later claims need. The transcript is captured only on the success path. A witnessed gate run keeps no stdout/stderr or their digests. The fixture-finalization latch is in memory only. The prompt is recorded as a boolean. The evaluated-skill selection isn't in the v2 bundle. `witness_ref.digest` is membership-only. `SKILL_EVIDENCE_UNMATCHED_REASONS` has no declared-skill-not-installed reason.

## Items (each re-checked against main `5ece908` on 2026-10-24)
- [ ] **MEDIUM**: lifecycle.run_through_backend only calls trial.capture(...,transcript=...) inside the success (confirmed-and-live) branch; if export() raises or liveness fails first, the transcript the observe hook already read is discarded at teardown and never retained - exactly the case #202 reports (transcript_retention.coverage='missing') but leaves unretained.
  - Still present: skillc/lifecycle.py:538-574: the export-OSError branch and the not-live branch both report 'capture-failed' without calling trial.capture; only the success `else` branch at :568 calls it. No follow-up issue found.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-5914939732
- [ ] **MEDIUM**: A witnessed gate run's retained record keeps only exit_code/reason/stages, never the run's stdout/stderr, so a red gate result (e.g. a real flow-auto-finish gate) can't be attributed from the campaign's own retained evidence and has to be reproduced out of band.
  - Still present: skillc/gate_witness.py GateRunRecord.to_json() (lines 208-236) still has no stdout/stderr field or digest of either; only `stages` is captured, and only for gates with a stage reader (flow-auto-finish has none).
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6247414595
- [ ] **MEDIUM**: A FixtureSession's 'fixture finalization failed' latch (set after the run's evidence is already complete) is stored in no retained record (the agent-observation schema and the journal's event set are both closed), so no later replay or audit can establish a live attempt's fixture finalized cleanly.
  - Still present: skillc/agent_trial.py:2822-2828 still stores the latch only in-memory on fixture_session.failure, with no new observation/journal field. The #486 judge replay still needs the opt-in --assume-fixture-finalized workaround (skillc/fixture_live.py:1606-1778, skillc/cli.py:3047) rather than reading a persisted finalization outcome. Orchestrator ruled to nit-store this at MEDIUM rather than file it.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6295464395
- [ ] **MEDIUM**: protocol.md's requirement that the full prompt be recorded is still unmet: agent-observation only stores a prompt_delivered boolean, never the prompt text/bytes/length, so instruction-length audits cannot be re-derived from the record store.
  - Still present: skillc/records.py:1224,1313-1346 only ever handles prompt_delivered as a boolean; skillc/calibration_run.py builds the prompt string in-memory (lines ~650-657) and never persists it to a record.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6009623264
- [ ] **LOW**: The evaluated-skill selection is still not captured inside the v2 record bundle; trial-ledger.subject still carries only {digest}, with the actual selection living in a separate Profile artifact.
  - Still present: docs/specs/evaluation-facility/records.md:107,141 unchanged trial-ledger subject shape.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6011799941
- [ ] **LOW**: records.py's witness_ref.digest check (added for #269) remains digest-membership-only like the pre-existing artifact_ref.digest check, with no path/type binding or content inspection - a deliberate mirror of the established, accepted limitation, not a new gap.
  - Still present: skillc/records.py:1774-1799 docstring states explicitly: 'NONE of these checks read the bytes behind artifact_ref.digest - they compare digests and attempt ids skillc already recorded.'
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6009887131
- [ ] **LOW**: SKILL_EVIDENCE_UNMATCHED_REASONS is still closed to duplicate-invocation/no-correlating-attempt only; declared-skill-not-installed is still not added, a deliberately deferred schema decision.
  - Still present: skillc/records.py:204-207 unchanged 2-entry tuple.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6011720885

## Acceptance
- [ ] Each item above is either fixed or explicitly ruled out, with the reason recorded here.
- [ ] Each fix comes with a test that FAILS on the pre-fix code (run it there and say so).
- [ ] Any instrument changed here gets a committed negative control: the input that makes it report the other verdict.
- [ ] Unverified items are first reproduced, or closed as not reproducible with what was tried.

## Source nits (full text)

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-5914939732 (2026-09-30)</summary>

**Severity: MEDIUM** - found by Codex (gpt-6-astra) counter-model review while working #202; deferred as out of scope.

`skillc/lifecycle.py` `run_through_backend` (the `trial.capture(..., transcript=...)` call inside the export + liveness branch): the transcript is retained only when artifact capture actually runs. When an agent writes a valid transcript but its capture fails first (the backend canary was never touched, or `backend.export()` raised), the observe hook has already read the transcript, but `trial.capture()` is never called and teardown destroys the only copy.

Why it matters: exactly those failed attempts are the ones that most need diagnosing. #202 reports this case explicitly (`transcript_retention.coverage = missing`, reason `no manifest: the attempt was not captured`), so it is never silent, but the bytes are lost. Possible fix: retain the leak-checked transcript independently of capture (e.g. a journal-bound object reference), with a regression where the client writes a transcript but leaves the canary untouched. That touches the attempt-lifecycle/accounting records, which is why it was not done in #202.


</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6247414595 (2026-10-18)</summary>

**Severity: MEDIUM (an evidence gap; it cost a direct reading in #434). A witnessed gate run's OUTPUT is not retained anywhere in a live attempt's store: only its exit code and reason are.**

**Where:**
- `skillc/gate_witness.py`'s `_Run.to_json()` (around line 182) records `requested_at`, `completed_at`, `exit_code`, `reason`, `tree_digest_at_start`, `stop_confirmed` and `stages`. No stdout and no stderr, nor a digest of either.
- The gate's stdout is forwarded to the subject through the shim and then lost: under `witness_io=True`, the attempt's `client-events`/`client-stderr` streams were empty (size 0) in #434's run.

**What it cost:** #434's revision-1 certifying run (comment 6247128286) saw the REAL CPP finish gate exit 3 on four observed rows. The question "which check, the exact output?" could not be answered from the retained run. It had to be REPRODUCED out of band: the pinned gate on a controller-built fixture. That reproduction gave `FLOW_FINISH_GATE: warn (skipped gates: lint test typecheck verify)`: the fixture has no gate surface. A reproduction is weaker evidence than the record of the run itself. For a flow-check `plan` run, `stage_capture` reads the stdout at resolve time and keeps per-stage outcomes, but a gate with no stage reader (`flow-auto-finish`) keeps nothing.

**Why it matters:** a red gate result in a certifying campaign can't be attributed from the campaign's own evidence, and a later grader revision that wants to freeze those rows has no retained output to freeze from.

**Possible fix (not applied):** retain each run's controller-held stdout and stderr (bounded, leak-checked) as content-addressed objects referenced from the run record, or at minimum the `FLOW_FINISH_GATE:` verdict line. Add a red: a run whose stored output is missing or tampered is refused by the reader.

**How it was found:** diagnosing #434 PR 3's observed gate rows. The orchestrator ruled it to the nit store rather than widening #434's revision 2.


</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6295464395 (2026-10-20)</summary>

**Severity: MEDIUM.** Found while working #486 PR-2 (judge replay), worker-A, wave skillc-400.

**Where:** `skillc/agent_trial.py` around line 2268, where a live `FixtureSession` latches "fixture finalization failed" after its evidence is complete. The latched state is stored in **no** retained record:
- the agent-observation schema is closed (`skillc/records.py`);
- journal events are a closed set (`skillc/trial.py`).

**What is wrong:** live grading sees the latch, but nothing after the run can. So no retained live attempt, past or future, can establish that its fixture finalized cleanly.

**Why it matters:** any future replay or audit of a live run depends on this. The #486 judge replay therefore fails closed by default: a strict replay of a fully captured run judges nothing. To judge anything, it needs the opt-in `--assume-fixture-finalized`, which records the assumption in the first line of its label. Persisting the finalization outcome (for example a field on the observation record, or a journal event) would let a strict replay judge such an attempt without that assumption.

**Not a live-grading defect:** the live credit gate already refuses a latched failure. This affects only after-the-fact replay and audit. The orchestrator ruled to nit-store it at MEDIUM rather than file it.


</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6009623264 (2026-10-06)</summary>

`docs/specs/evaluation-facility/protocol.md:237-238` requires the prompt to be "recorded in full, so instruction length is measured, not assumed." No producer in the v2 record schema does this: `agent-observation` (`docs/specs/evaluation-facility/records.md:366`) persists only `prompt_delivered`, a boolean comparing the transcript's first user message against the expected prompt - never the prompt text, its bytes, or its length. `skillc/calibration_run.py` builds the prompt in-memory (`goal.md` + the arm's declared `instruction`) and never writes it to a record.

Why it matters: this is a protocol requirement the implementation does not meet, not just a missing nice-to-have. It is also why the instruction-length convenience proxy (protocol.md 10.6) is currently unobservable rather than reportable - and any later audit of exactly what a subject was told cannot be re-derived from the record store, only reconstructed from source files that may have moved on. Reconstructing the length from `goal.md` + arm instruction at report time would not satisfy 10.1 either - that is reconstruction, not capture, and it would not survive the fixture or goal file changing after the fact.

Found while working #273 (repeat-reliability and convenience summaries).


</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6011799941 (2026-10-06)</summary>

The evaluated-skill selection is not captured anywhere in the v2 record bundle. `trial-ledger.subject` carries only `{digest}` (docs/specs/evaluation-facility/records.md, trial-ledger section); the actual skill selection lives in a `Profile` artifact (`skillc/profile.py`'s `select` field, loaded from a declaration file outside the bundle) and in #265's own `evidence/inventory.json` - both already documented as "a different artifact family... not a bundle member" (records.md Q3).

Consequence: a retained bundle, read alone, cannot reconstruct its own declared-skill inventory - it can only report rows for skills it happens to have evidence for (skill-evidence entries), never the full set including untested skills, and never a fixed row-count assertion. #272's report module takes the profile as a separate, optional input and records its own content digest + subject digest join when supplied, rather than guessing from `installation-receipt.installed` (which lists every installed file - helpers and libraries too, not just skills under evaluation).

Capturing the evaluated selection IN the bundle (e.g. a digest-addressed reference from trial-ledger to the profile, or the selection itself as a record field) is a records.py schema decision, not something #272 should do as a side effect.

Found while designing #272 (assemble reproducible per-skill coverage reports from retained bundles).


</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6009887131 (2026-10-06)</summary>

Codex finding (codex code_review of #269, model identity unestablished - sandbox was diff-only), triaged as deferred rather than fixed in #269's own PR:

skillc/records.py `_skill_evidence_binding`'s new `witness_ref.digest` cross-check (added for #269's closed-reconciliation-reason work) only verifies the cited digest is present SOMEWHERE in the attempt's captured-digest set, not that the manifest entry it names actually is a controller-witness artifact (by path/type) or contains content supporting the claimed reason. This is not a new weakness: the EXISTING `artifact_ref.digest` check in the same function (merged with #268) has the identical shape - digest-membership only, no path/type binding, no content inspection. #269's addition deliberately mirrors that established pattern rather than exceeding it (explicit instruction: "the identical 'altered artifact' check artifact_ref.digest already gets").

Closing this fully would mean passing the full manifest artifact list (path+type+digest), not just a `captured: set[str]` of digests, into `_skill_evidence_binding`, and likely parsing the cited gate-witness/usage-record content to confirm it actually supports the claimed reason - a signature change affecting the already-shipped `artifact_ref` check too, not scoped to #269's own addition.

File: skillc/records.py, `_skill_evidence_binding` (~line 1693 on the issue-269-gate-witness branch). Found while implementing #269's contradicting-reconciliation witness-citation requirement.

</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6011720885 (2026-10-06)</summary>

`skillc/records.py`'s `SKILL_EVIDENCE_UNMATCHED_REASONS` closes `unmatched`'s reason vocabulary to `duplicate-invocation` and `no-correlating-attempt` only (docs/specs/evaluation-facility/records.md, "Closing unmatched's own reason vocabulary"). R9's original answer also named a third reason, `declared-skill-not-installed` (records.md Q3: "a declared skill name with no correlating installed path is reconciliation: unmatched, reason declared-skill-not-installed"), but it is not closed and has no working check.

Why: that reason needs a field `external_evidence` does not carry today - a CPP usage record's own self-declared skill name, read skillc-side as metadata alongside the digest (never the opaque payload itself), separate from the entry's own top-level `skill.path`. Reusing `skill.path` doesn't work: `_skill_evidence_binding`'s existing unconditional check already refuses any entry whose `skill.path` isn't installed, regardless of reconciliation or reason, so there is no "good" bundle this reason could legitimately describe without adding that field. Adding a schema field is a decision bigger than one issue's scope.

Found while working #272 (assemble reproducible per-skill coverage reports from retained bundles).


</details>

