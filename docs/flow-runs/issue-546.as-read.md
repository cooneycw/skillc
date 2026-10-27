<!-- flow-run n=1 id=86373c74a2904f7685a8dbced1ed0dc1 -->
## Run 1 - issue #546 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #546
- Read at:      2026-10-25T10:45:18Z
- updatedAt:    2026-10-25T09:52:58Z   (context only - moves on comments and labels)
- Body digest:  75278aab64fb4594af499f04bf6074f86f5bdc5de045f1035b04b7788f26646b   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 15769 of 15769 (cap 16384)

### Body as read
**Severity: LOW, MEDIUM.** Nothing here is HIGH, and nothing blocks work now. Filed at the owner's request from the Nit Store aggregation pass https://github.com/cooneycw/skillc/issues/20#issuecomment-6383442993 (group G5).

## Problem
Live-run budgets and stops. Matched-pilot setup time isn't charged against the total cap. The total-cap checks accept equality with no margin. Uptake conflates not-run with undecided. An operator SIGINT didn't stop calibration-run (unverified). An attempt killed after dispatch was reconciled as never dispatched (unverified). There's no `calibration-report` recovery command. calibration-run has no native stop on server-side tool use or off-allowlist egress.

## Items (each re-checked against main `5ece908` on 2026-10-24)
- [ ] **MEDIUM**: matched_pilot.run_schedule computes each attempt's agent budget as min(per_attempt_seconds, remaining) before setup (prepare/install/credential delivery) runs, so the backend's Limits(timeout=budget) only bounds execute(); setup time is never charged against the total cap.
  - Still present: skillc/matched_pilot.py:358-408 (budget calc), :937-947 (passes timeout=budget into collection_conformance.run_level1_agent_attempt), collection_conformance.py:763 builds Limits(timeout=timeout); no setup-time accounting exists in the chain.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-5856506863
- [ ] **MEDIUM**: uptake_study.parse_declaration's and calibration.parse_declaration's total-cap checks still accept total == attempts*per_attempt exactly, ignoring per-attempt container/grading overhead, so a schedule can be declared that can never complete.
  - Still present: skillc/uptake_study.py:232 `if total < per_attempt * attempts:`; skillc/calibration.py:481 same shape with `* len(names)`.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6014582924
- [ ] **LOW**: uptake_study.build_report/_decided still counts not-run attempts (e.g. ones cut by the total cap) as 'undecided', conflating 'probe cut the agent off' with 'attempt never executed'.
  - Still present: skillc/uptake_study.py:551-569,652,664 unchanged; no disposition check separates not-run from undecided.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6014583153
- [ ] **MEDIUM** (unverified): An operator SIGINT sent to calibration-run's pid did not stop the schedule; three-plus attempts ran after the interrupt before a later SIGTERM actually ended the process. Root cause was never diagnosed.
  - Still present: skillc/calibration_run.py:686 and :1258 still have only the same outer `except KeyboardInterrupt` at the schedule level; no signal-forwarding or subprocess-level SIGINT fix was found, and no commit or issue references this specific defect. Confirming or refuting the live behavior needs a scripted multi-attempt SIGINT run, which is out of scope for this read-only triage.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6250478805
- [ ] **MEDIUM** (unverified): An attempt that was dispatched (containers up, tokens spent) but killed before its lifecycle record was written was reconciled as 'not-run' ('never dispatched'), making its spend vanish from the accounting, identical to a slot that never started.
  - Still present: skillc/matched_pilot.py reconcile() (576-605) and skillc/trial.py finalize() (1227+) already derive the disposition from the attempt's own durable 'dispatched' journal event (trial.py:761-821, written at trial.py:821 before launch) rather than blindly defaulting to not-run - the shape of the fix the comment asked for appears to already exist structurally. But no commit since 2026-10-18 references this report, the comment's own root cause (why attempt 12 specifically read not-run) was never diagnosed, and confirming the fix needs reproducing the pilot's kill timing, which is out of scope here.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6250478948
- [ ] **LOW**: calibration-run has no calibration-report <run_dir> recovery command (unlike pilot-run's pilot-report) for rebuilding a report after an uncatchable kill (SIGKILL/reboot) leaves only the outcomes.json checkpoint.
  - Still present: skillc/cli.py has p_pilot_report (:3096-3107)/cmd_pilot_report (:1627) but no equivalent calibration-report subparser; skillc/calibration_run.py only exposes reconcile() (:550) and build_report() (:1520) as library functions. PR #212 (Closes #204, docs-only) produced evals/calibration-204/report.md via this exact manual recovery path, confirming the gap persisted even after being hit.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-5917953932
- [ ] **MEDIUM**: skillc calibration-run has no native schedule-level stop when an attempt's census reports a server-side tool use or its egress summary shows an ALLOWED target outside the declared allowlist; only grading of that one attempt is blocked, and the schedule continues.
  - Still present: Partially addressed by #500 (CLOSED): skillc/calibration_run.py now wires a GuardStop (lines 771-790) into run_calibration/run_discrimination (lines 640-678, 1226-1252) via containment_trigger(), but that native stop is scoped specifically to the nested-codex guard report - not to `observation.server_side_tool_uses` being non-empty or to an egress-outside-allowlist condition, which `_apply_egress` (line 864) still only computes post-hoc after the whole schedule has already run. The two literal conditions this comment asked for remain unimplemented as a schedule stop.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6249880695

## Acceptance
- [ ] Each item above is either fixed or explicitly ruled out, with the reason recorded here.
- [ ] Each fix comes with a test that FAILS on the pre-fix code (run it there and say so).
- [ ] Any instrument changed here gets a committed negative control: the input that makes it report the other verdict.
- [ ] Unverified items are first reproduced, or closed as not reproducible with what was tried.

## Source nits (full text)

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-5856506863 (2026-09-27)</summary>

**Severity: medium.** Found by the Codex counter-model review (second pass) while working #12.

`skillc/matched_pilot.py` `run_schedule`: each attempt's agent limit is `min(per_attempt_seconds, remaining)`, computed before the attempt's setup (prepare, install, credential delivery). The backend starts its timeout only at `execute()`. So when setup is slow, the last attempt's agent can run past the declared total cap by as long as that setup took (seconds on the live run, but unbounded in principle).

Why it matters: the pilot's total time cap is a predeclared bound, and at the moment it bounds attempt starts and agent allowance, not the wall-clock.

Fix: pass an absolute deadline through `collection_conformance.run_level1_agent_attempt` / `agent_trial.run_one_attempt` into `lifecycle.run_through_backend`, recompute the allowance immediately before `execute()`, and refuse to launch once setup has used it up. Add a control with delayed setup. This was left out of #12 because it changes #106's lifecycle module. The docstring now states the gap.


</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6014582924 (2026-10-06)</summary>

**Severity: medium. `uptake_study.parse_declaration`'s total-cap check ignores per-attempt overhead.**

- **Where:** `skillc/uptake_study.py`, `parse_declaration`, the check `total < per_attempt * attempts`.
- **What is wrong:** the check accepts a `shared.total_seconds` equal to exactly `attempts × per_attempt_seconds`. Every attempt also spends roughly 10 s in container setup, grading and teardown outside the agent's limit.
- **Why it matters:** in #238's probe agreement check (PR #311, experiments `uptake-1e827527` and `uptake-af5eda18`) I declared 900 s for 20 × 45 s attempts. Each run stopped after 17 attempts, and 6 of 40 were `not-run`. The schedule as declared could never complete, and the validator said nothing. The relative overhead is largest for probes. `calibration.parse_declaration` has the same shape.
- **Suggested fix:** require `total ≥ attempts × (per_attempt + margin)` with a declared margin of at least 30 s, or refuse a schedule whose cap leaves no overhead room.
- **Found while:** running the #238 probe agreement check.

</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6014583153 (2026-10-06)</summary>

**Severity: low. `uptake_study.build_report` counts `not-run` attempts as `undecided`.**

- **Where:** `skillc/uptake_study.py`, `build_report` / `_decided`, and the top-level `undecided` counter.
- **What is wrong:** a `not-run` attempt (for example, one cut by the total cap) has no observation, so `tool_calls` is None and `_decided` returns False. The report's `undecided` count and the paste-back line ("PROBE cut-off 45s, undecided=3") then include attempts that never executed.
- **Why it matters:** "undecided" is meant to say the probe cut the agent off before it acted, which is a property of the probe. In PR #311's run, all 6 "undecided" attempts were `not-run`, and the counter read as if the 45 s cut-off had been too short. Cell denominators are unaffected; this is reporting only.
- **Suggested fix:** report `not_run` separately, and compute `decided` only for executed attempts.
- **Found while:** writing up the #238 probe agreement check.

</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6250478805 (2026-10-18)</summary>

**Severity: medium (orchestrator skillc-400).** An operator SIGINT does not stop `skillc calibration-run`'s schedule. Found in the #287/#288 live discrimination pilot (run `20261018T130109Z-56c86b`, checkout `2a2e287`), 2026-10-18.

**What happened:** after the owner's "stop now", SIGINT was sent to the `calibration-run` python process (pid only, not its process group) at 09:16:42. Attempt 9 was in flight. Attempts 9, 10 and 11 then finalized, and attempt 12's agent and proxy containers started at 09:20:40-44. Only a later SIGTERM (09:21:03) ended the process. About 3 full attempts plus a partial 12th were spent after the stop.

**Why it matters:**
- `run_calibration`/`run_discrimination` document an operator interrupt as the way to stop and still account for every slot (the `except KeyboardInterrupt` that reconciles and re-raises). In practice the interrupt appears to be consumed per attempt, somewhere in the attempt or backend path, and the schedule continues.
- The #287 containment watcher (an external SIGINT on a containment failure) therefore **could not have stopped the schedule either**.
- The cause was not diagnosed. Candidates: a `BaseException` handler in the attempt or backend path that converts the interrupt; the signal landing during a `subprocess.run` that swallows it.

**Shape of a fix:** a red that sends SIGINT mid-schedule to a scripted multi-attempt run and asserts the remaining slots finalize `not-run` and no new attempt starts. Plus a native stop path, see the containment-stop entry above (issuecomment-6249880695).


</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6250478948 (2026-10-18)</summary>

**Severity: medium.** An attempt that was DISPATCHED, but interrupted by a kill before its lifecycle record was written, is reconciled as `not-run` ("never dispatched"). Its spend then vanishes from the accounting. Found in the #287/#288 live discrimination pilot (run `20261018T130109Z-56c86b`), 2026-10-18.

**Where:** `skillc/matched_pilot.py` `reconcile` (via `calibration_run.reconcile`). An attempt with no recorded outcome "takes its lifecycle record if one was written, else is finalized now", with the disposition DERIVED (never dispatched = `not-run`).

**What happened:** attempt 12 (`a-e305d353e904`, degraded) had its agent and proxy containers up for about 5 minutes. It was making model calls (egress via the proxy) when SIGTERM ended the run. After reconciling, the ledger and report show it as `not-run`, "no outcome was recorded for this attempt (the run was interrupted)", identical to the 8 slots that never started.

**Why it matters:** a pilot's accounting is meant to keep every slot honest. `not-run` says no spend and no attempt, but here tokens were spent and the provider was contacted. A report's not-run count can therefore understate dispatched attempts. Here the slot was corrected by hand in the result note.

**Shape of a fix:** record a dispatch lifecycle event before the agent starts. Reconcile an attempt that has a dispatch record but no outcome as `interrupted` (non-evaluable, with spend unknown), never as `not-run`. Add a red: kill a scripted run mid-attempt, then reconcile.


</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-5917953932 (2026-09-30)</summary>

**Severity: LOW** - found while working #207 (counter-model review follow-up).

`skillc calibration-run` reconciles and persists every planned attempt on `KeyboardInterrupt` (#207), but a kill that cannot be caught (SIGKILL, host reboot) leaves only the private `outcomes.json` checkpoint. `pilot-run` has `pilot-report <run_dir>` to rebuild a report from that record; calibration has no equivalent command, so recovery means calling `calibration_run.reconcile` + `build_report` by hand.

Why it matters: the #204 run is 8 attempts of up to 20 minutes each on the operator's host. An interrupted run's evidence is intact in the store, but there's no supported path to its report. Likely home: the calibration-report work under #204 (which also owns publishing), as a `calibration-report <run_dir>` subcommand.


</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6249880695 (2026-10-18)</summary>

**Severity: medium.** `skillc calibration-run` has no native study-level containment stop. Found while preparing the #287/#288 live study (PR for the #287 owner-approval stamp, branch `issue-287-p5-owner-approval`).

**Where:** `skillc/calibration_run.py`, `run_calibration` (`mp.run_schedule(..., on_outcome=on_outcome)`) and `run_discrimination`. Nothing in the schedule loop inspects a finalized attempt for containment failure.

**What is wrong:** the #288 run plan pre-registers, and the orchestrator approved, a study-level stop. If any attempt's census reports a server-side tool use (`observation.server_side_tool_uses` non-empty), or its egress summary shows an ALLOWED target outside the allowlist, the remaining schedule must stop. The runner implements neither condition. It only blocks *grading* of that one attempt (`grading_blocked_reason`, "not credited") and carries on to the next slot.

**Why it matters:** a containment failure is a failure of the premise of every count. Continuing spends subscription usage on attempts whose results cannot be read as contained. Today the rule is enforced only by an external watcher written for #288. It polls `outcomes.json` after each attempt and sends SIGINT, an operator interrupt whose handler finalizes the remaining slots as `not-run`. That works, but it lives outside the codebase, so a future study that forgets the watcher silently loses the rule.

**Suggested shape (for whoever aggregates this):** an `on_outcome` hook in `run_calibration`/`run_discrimination` that raises a dedicated stop on either condition. The remaining slots would be finalized `not-run` with a containment reason, the report would name the triggering attempt and its evidence, and there would be a red (a scripted attempt whose record shows `server_side_tool_uses: ["web_search"]` must stop the schedule).


</details>


<!-- end of body -->

<!-- flow-run n=2 id=9e3e19ff488848bd9d25d5b0f297a623 -->
## Run 2 - issue #546 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #546
- Read at:      2026-10-27T10:37:18Z
- updatedAt:    2026-10-27T10:36:44Z   (context only - moves on comments and labels)
- Body digest:  75278aab64fb4594af499f04bf6074f86f5bdc5de045f1035b04b7788f26646b   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 15769 of 15769 (cap 16384)

### Body as read
**Severity: LOW, MEDIUM.** Nothing here is HIGH, and nothing blocks work now. Filed at the owner's request from the Nit Store aggregation pass https://github.com/cooneycw/skillc/issues/20#issuecomment-6383442993 (group G5).

## Problem
Live-run budgets and stops. Matched-pilot setup time isn't charged against the total cap. The total-cap checks accept equality with no margin. Uptake conflates not-run with undecided. An operator SIGINT didn't stop calibration-run (unverified). An attempt killed after dispatch was reconciled as never dispatched (unverified). There's no `calibration-report` recovery command. calibration-run has no native stop on server-side tool use or off-allowlist egress.

## Items (each re-checked against main `5ece908` on 2026-10-24)
- [ ] **MEDIUM**: matched_pilot.run_schedule computes each attempt's agent budget as min(per_attempt_seconds, remaining) before setup (prepare/install/credential delivery) runs, so the backend's Limits(timeout=budget) only bounds execute(); setup time is never charged against the total cap.
  - Still present: skillc/matched_pilot.py:358-408 (budget calc), :937-947 (passes timeout=budget into collection_conformance.run_level1_agent_attempt), collection_conformance.py:763 builds Limits(timeout=timeout); no setup-time accounting exists in the chain.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-5856506863
- [ ] **MEDIUM**: uptake_study.parse_declaration's and calibration.parse_declaration's total-cap checks still accept total == attempts*per_attempt exactly, ignoring per-attempt container/grading overhead, so a schedule can be declared that can never complete.
  - Still present: skillc/uptake_study.py:232 `if total < per_attempt * attempts:`; skillc/calibration.py:481 same shape with `* len(names)`.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6014582924
- [ ] **LOW**: uptake_study.build_report/_decided still counts not-run attempts (e.g. ones cut by the total cap) as 'undecided', conflating 'probe cut the agent off' with 'attempt never executed'.
  - Still present: skillc/uptake_study.py:551-569,652,664 unchanged; no disposition check separates not-run from undecided.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6014583153
- [ ] **MEDIUM** (unverified): An operator SIGINT sent to calibration-run's pid did not stop the schedule; three-plus attempts ran after the interrupt before a later SIGTERM actually ended the process. Root cause was never diagnosed.
  - Still present: skillc/calibration_run.py:686 and :1258 still have only the same outer `except KeyboardInterrupt` at the schedule level; no signal-forwarding or subprocess-level SIGINT fix was found, and no commit or issue references this specific defect. Confirming or refuting the live behavior needs a scripted multi-attempt SIGINT run, which is out of scope for this read-only triage.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6250478805
- [ ] **MEDIUM** (unverified): An attempt that was dispatched (containers up, tokens spent) but killed before its lifecycle record was written was reconciled as 'not-run' ('never dispatched'), making its spend vanish from the accounting, identical to a slot that never started.
  - Still present: skillc/matched_pilot.py reconcile() (576-605) and skillc/trial.py finalize() (1227+) already derive the disposition from the attempt's own durable 'dispatched' journal event (trial.py:761-821, written at trial.py:821 before launch) rather than blindly defaulting to not-run - the shape of the fix the comment asked for appears to already exist structurally. But no commit since 2026-10-18 references this report, the comment's own root cause (why attempt 12 specifically read not-run) was never diagnosed, and confirming the fix needs reproducing the pilot's kill timing, which is out of scope here.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6250478948
- [ ] **LOW**: calibration-run has no calibration-report <run_dir> recovery command (unlike pilot-run's pilot-report) for rebuilding a report after an uncatchable kill (SIGKILL/reboot) leaves only the outcomes.json checkpoint.
  - Still present: skillc/cli.py has p_pilot_report (:3096-3107)/cmd_pilot_report (:1627) but no equivalent calibration-report subparser; skillc/calibration_run.py only exposes reconcile() (:550) and build_report() (:1520) as library functions. PR #212 (Closes #204, docs-only) produced evals/calibration-204/report.md via this exact manual recovery path, confirming the gap persisted even after being hit.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-5917953932
- [ ] **MEDIUM**: skillc calibration-run has no native schedule-level stop when an attempt's census reports a server-side tool use or its egress summary shows an ALLOWED target outside the declared allowlist; only grading of that one attempt is blocked, and the schedule continues.
  - Still present: Partially addressed by #500 (CLOSED): skillc/calibration_run.py now wires a GuardStop (lines 771-790) into run_calibration/run_discrimination (lines 640-678, 1226-1252) via containment_trigger(), but that native stop is scoped specifically to the nested-codex guard report - not to `observation.server_side_tool_uses` being non-empty or to an egress-outside-allowlist condition, which `_apply_egress` (line 864) still only computes post-hoc after the whole schedule has already run. The two literal conditions this comment asked for remain unimplemented as a schedule stop.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6249880695

## Acceptance
- [ ] Each item above is either fixed or explicitly ruled out, with the reason recorded here.
- [ ] Each fix comes with a test that FAILS on the pre-fix code (run it there and say so).
- [ ] Any instrument changed here gets a committed negative control: the input that makes it report the other verdict.
- [ ] Unverified items are first reproduced, or closed as not reproducible with what was tried.

## Source nits (full text)

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-5856506863 (2026-09-27)</summary>

**Severity: medium.** Found by the Codex counter-model review (second pass) while working #12.

`skillc/matched_pilot.py` `run_schedule`: each attempt's agent limit is `min(per_attempt_seconds, remaining)`, computed before the attempt's setup (prepare, install, credential delivery). The backend starts its timeout only at `execute()`. So when setup is slow, the last attempt's agent can run past the declared total cap by as long as that setup took (seconds on the live run, but unbounded in principle).

Why it matters: the pilot's total time cap is a predeclared bound, and at the moment it bounds attempt starts and agent allowance, not the wall-clock.

Fix: pass an absolute deadline through `collection_conformance.run_level1_agent_attempt` / `agent_trial.run_one_attempt` into `lifecycle.run_through_backend`, recompute the allowance immediately before `execute()`, and refuse to launch once setup has used it up. Add a control with delayed setup. This was left out of #12 because it changes #106's lifecycle module. The docstring now states the gap.


</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6014582924 (2026-10-06)</summary>

**Severity: medium. `uptake_study.parse_declaration`'s total-cap check ignores per-attempt overhead.**

- **Where:** `skillc/uptake_study.py`, `parse_declaration`, the check `total < per_attempt * attempts`.
- **What is wrong:** the check accepts a `shared.total_seconds` equal to exactly `attempts × per_attempt_seconds`. Every attempt also spends roughly 10 s in container setup, grading and teardown outside the agent's limit.
- **Why it matters:** in #238's probe agreement check (PR #311, experiments `uptake-1e827527` and `uptake-af5eda18`) I declared 900 s for 20 × 45 s attempts. Each run stopped after 17 attempts, and 6 of 40 were `not-run`. The schedule as declared could never complete, and the validator said nothing. The relative overhead is largest for probes. `calibration.parse_declaration` has the same shape.
- **Suggested fix:** require `total ≥ attempts × (per_attempt + margin)` with a declared margin of at least 30 s, or refuse a schedule whose cap leaves no overhead room.
- **Found while:** running the #238 probe agreement check.

</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6014583153 (2026-10-06)</summary>

**Severity: low. `uptake_study.build_report` counts `not-run` attempts as `undecided`.**

- **Where:** `skillc/uptake_study.py`, `build_report` / `_decided`, and the top-level `undecided` counter.
- **What is wrong:** a `not-run` attempt (for example, one cut by the total cap) has no observation, so `tool_calls` is None and `_decided` returns False. The report's `undecided` count and the paste-back line ("PROBE cut-off 45s, undecided=3") then include attempts that never executed.
- **Why it matters:** "undecided" is meant to say the probe cut the agent off before it acted, which is a property of the probe. In PR #311's run, all 6 "undecided" attempts were `not-run`, and the counter read as if the 45 s cut-off had been too short. Cell denominators are unaffected; this is reporting only.
- **Suggested fix:** report `not_run` separately, and compute `decided` only for executed attempts.
- **Found while:** writing up the #238 probe agreement check.

</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6250478805 (2026-10-18)</summary>

**Severity: medium (orchestrator skillc-400).** An operator SIGINT does not stop `skillc calibration-run`'s schedule. Found in the #287/#288 live discrimination pilot (run `20261018T130109Z-56c86b`, checkout `2a2e287`), 2026-10-18.

**What happened:** after the owner's "stop now", SIGINT was sent to the `calibration-run` python process (pid only, not its process group) at 09:16:42. Attempt 9 was in flight. Attempts 9, 10 and 11 then finalized, and attempt 12's agent and proxy containers started at 09:20:40-44. Only a later SIGTERM (09:21:03) ended the process. About 3 full attempts plus a partial 12th were spent after the stop.

**Why it matters:**
- `run_calibration`/`run_discrimination` document an operator interrupt as the way to stop and still account for every slot (the `except KeyboardInterrupt` that reconciles and re-raises). In practice the interrupt appears to be consumed per attempt, somewhere in the attempt or backend path, and the schedule continues.
- The #287 containment watcher (an external SIGINT on a containment failure) therefore **could not have stopped the schedule either**.
- The cause was not diagnosed. Candidates: a `BaseException` handler in the attempt or backend path that converts the interrupt; the signal landing during a `subprocess.run` that swallows it.

**Shape of a fix:** a red that sends SIGINT mid-schedule to a scripted multi-attempt run and asserts the remaining slots finalize `not-run` and no new attempt starts. Plus a native stop path, see the containment-stop entry above (issuecomment-6249880695).


</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6250478948 (2026-10-18)</summary>

**Severity: medium.** An attempt that was DISPATCHED, but interrupted by a kill before its lifecycle record was written, is reconciled as `not-run` ("never dispatched"). Its spend then vanishes from the accounting. Found in the #287/#288 live discrimination pilot (run `20261018T130109Z-56c86b`), 2026-10-18.

**Where:** `skillc/matched_pilot.py` `reconcile` (via `calibration_run.reconcile`). An attempt with no recorded outcome "takes its lifecycle record if one was written, else is finalized now", with the disposition DERIVED (never dispatched = `not-run`).

**What happened:** attempt 12 (`a-e305d353e904`, degraded) had its agent and proxy containers up for about 5 minutes. It was making model calls (egress via the proxy) when SIGTERM ended the run. After reconciling, the ledger and report show it as `not-run`, "no outcome was recorded for this attempt (the run was interrupted)", identical to the 8 slots that never started.

**Why it matters:** a pilot's accounting is meant to keep every slot honest. `not-run` says no spend and no attempt, but here tokens were spent and the provider was contacted. A report's not-run count can therefore understate dispatched attempts. Here the slot was corrected by hand in the result note.

**Shape of a fix:** record a dispatch lifecycle event before the agent starts. Reconcile an attempt that has a dispatch record but no outcome as `interrupted` (non-evaluable, with spend unknown), never as `not-run`. Add a red: kill a scripted run mid-attempt, then reconcile.


</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-5917953932 (2026-09-30)</summary>

**Severity: LOW** - found while working #207 (counter-model review follow-up).

`skillc calibration-run` reconciles and persists every planned attempt on `KeyboardInterrupt` (#207), but a kill that cannot be caught (SIGKILL, host reboot) leaves only the private `outcomes.json` checkpoint. `pilot-run` has `pilot-report <run_dir>` to rebuild a report from that record; calibration has no equivalent command, so recovery means calling `calibration_run.reconcile` + `build_report` by hand.

Why it matters: the #204 run is 8 attempts of up to 20 minutes each on the operator's host. An interrupted run's evidence is intact in the store, but there's no supported path to its report. Likely home: the calibration-report work under #204 (which also owns publishing), as a `calibration-report <run_dir>` subcommand.


</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6249880695 (2026-10-18)</summary>

**Severity: medium.** `skillc calibration-run` has no native study-level containment stop. Found while preparing the #287/#288 live study (PR for the #287 owner-approval stamp, branch `issue-287-p5-owner-approval`).

**Where:** `skillc/calibration_run.py`, `run_calibration` (`mp.run_schedule(..., on_outcome=on_outcome)`) and `run_discrimination`. Nothing in the schedule loop inspects a finalized attempt for containment failure.

**What is wrong:** the #288 run plan pre-registers, and the orchestrator approved, a study-level stop. If any attempt's census reports a server-side tool use (`observation.server_side_tool_uses` non-empty), or its egress summary shows an ALLOWED target outside the allowlist, the remaining schedule must stop. The runner implements neither condition. It only blocks *grading* of that one attempt (`grading_blocked_reason`, "not credited") and carries on to the next slot.

**Why it matters:** a containment failure is a failure of the premise of every count. Continuing spends subscription usage on attempts whose results cannot be read as contained. Today the rule is enforced only by an external watcher written for #288. It polls `outcomes.json` after each attempt and sends SIGINT, an operator interrupt whose handler finalizes the remaining slots as `not-run`. That works, but it lives outside the codebase, so a future study that forgets the watcher silently loses the rule.

**Suggested shape (for whoever aggregates this):** an `on_outcome` hook in `run_calibration`/`run_discrimination` that raises a dedicated stop on either condition. The remaining slots would be finalized `not-run` with a containment reason, the report would name the triggering attempt and its evidence, and there would be a red (a scripted attempt whose record shows `server_side_tool_uses: ["web_search"]` must stop the schedule).


</details>


<!-- end of body -->
