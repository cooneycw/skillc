<!-- flow-run n=1 id=bfaff44c62344e6b94602cebda83b6f2 -->
## Run 1 - issue #536 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #536
- Read at:      2026-10-24T22:30:36Z
- updatedAt:    2026-10-24T10:42:32Z   (context only - moves on comments and labels)
- Body digest:  260234ce1e12a98f01625bf20d8caaef825ad717441af47b3921d7aea6f8337e   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 7629 of 7629 (cap 16384)

### Body as read
**Severity: LOW to MEDIUM.** Four gaps in what the fixture/live path checks or records. Each one fails closed or costs evaluability; none is a false pass.

## Items
1. **The preflight never exercises `SKILLC_ALLOW_REAL_AGENT`.** A preflight read ALL PASS, and the live run was then refused at its first attempt. Assert the opt-in in the exact launch env, without launching, or route the rehearsal through the same guard.
2. **The live report omits `transcript_codex_invocations` and `transcript_files_found`.** These are computed in memory and used for credit, but persisted only on the `--judge-replay` path (`skillc/fixture_live.py` ~1696). Add both to the per-attempt report, next to `nested_codex`.
3. **`fixture_campaign.ACTOR_SOURCE` can't be credited under #518's steward**, because it never reads the credential. Its bytes are pinned by #434's candidate identities. Wrap it, as `TURN_ACTOR_SOURCE` is wrapped, or re-pin the identity. **Decide when #434 resumes.**
4. **Gate-runner state inheritance.** Today, any non-empty `.git/cpp-runs` at a witnessed run's start makes the run unattributable. Instead, record the state digest at the end of each witnessed run, and inherit it when the next run starts from exactly that state. **Needed before any flow-check task with a red fixture.**

## Acceptance
- [ ] Items 1 and 2 land as one PR. Each has a red case that fails on the pre-fix code.
- [ ] Item 3 is decided and recorded at #434's resume.
- [ ] Item 4 lands with the four reds from the source nit: seeded state is not attributed; plan→summary is SATISFIED; plan→plan is SATISFIED; tampered state is not attributed.

## Source nits (moved from the Nit Store, #20)
Full text of each source comment, so this issue stands on its own.

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6339769206 (2026-10-22)</summary>

**Nit (found in wave skillc-finish while working #279, 2026-10-22). Severity: low; it costs a hold slot, not correctness.** The #279 Step-6 preflight, including the no-spend actor rehearsal, never exercises the operator opt-in guard `lifecycle._refuse_real_agent` (`SKILLC_ALLOW_REAL_AGENT=1`). A preflight reported ALL PASS, and the live run was then refused at its first attempt for the missing opt-in (run dir `20261022T113506Z-db8098`, no spend). The guard was right. The point is that the preflight can't tell a launchable command from an unlaunchable one. Fix idea: the preflight asserts that the opt-in is set in the exact launch env, without launching, or the rehearsal routes through the same guard.

</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6348964145 (2026-10-22)</summary>

**Nit (found in wave skillc-finish while working #279's sizing-3 preflight, 2026-10-22). Severity: LOW.** The live record does not keep the transcript scan's result.

**What.** The fixture-path observation hook (`agent_trial._make_observe_before_teardown`) computes `transcript_codex_invocations` and `transcript_files_found`. The credit gate (`agent_trial._fixture_credit_block`) and `fixture_live.containment_trigger` read them in memory. But neither the run store's observation/evidence objects nor `live-report.json` keeps them:
- `grep -r transcript_codex_invocations` over a rehearsal run directory finds nothing;
- the report's attempt keys include `nested_codex` (the guard) but not the scan.

**Why it matters.** "Credited" cannot distinguish a scan that found 1 refused-and-matched invocation from a scan that found 0. Only the guard half of "refused and detected" is on the record. To prove detection, the #279 sizing-3 preflight had to re-run `attempt_guard.scan_transcript_text` over each retained transcript. That works, and `--judge-replay` does the same, but a reader of the report alone cannot see detection.

**Fix shape:** put the two scan fields in the per-attempt report, next to `nested_codex`.


</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6348963693 (2026-10-22)</summary>

**Nit (found in wave skillc-finish while working #279's sizing-3 preflight, 2026-10-22). Severity: MEDIUM (orchestrator ruling). A regression from #518 (#523).** On the fixture path, single-turn scripted actors can no longer be credited.

**What.** #518's credential steward withdraws `~/.codex/auth.json` only after a client READ followed by a 3 s quiet period (`docker/fixture-service/skillc-credential-steward.py`). Two scripted actors never read the credential:
- #434's `fixture_campaign.ACTOR_SOURCE`, used by `skillc level3-campaign` and by the turnless `rehearsal_actor` (`skillc/fixture_live.py`, the `not turns` branch);
- the plain `--rehearse actor` of a turnless task (flow-auto-necessity).

So the steward either withdraws at the 30 s deadline or is stopped while still armed. Its record reads `unknown`, which blocks credit (`credential_steward.credit_block`) and stops the schedule.

**It fails closed:** nothing is ever falsely credited; the run just can't credit anything. The affected work, #434, is **parked**.

**Fixed for #279 by PR from branch `issue-279-sizing3-rehearsal` (50dbf7d).** Both TURN actors (`TURN_ACTOR_SOURCE`, `STEP6_ACTOR_SOURCE`) now read the credential as codex 0.157.1 does and end a turn only once it has been withdrawn.

**Not fixed.** `fixture_campaign.ACTOR_SOURCE`: its bytes are pinned by #434's candidate identities, so it can't be edited in place. Closing it needs either a wrapper in front of the campaign actor (like `TURN_ACTOR_SOURCE`), or a re-pinned identity, decided when #434 resumes.

**Repro:** `skillc level3-live <a turnless #434 declaration> --rehearse actor` on main 80eca1d: every attempt reads `credential steward record is unknown`.


</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6368996572 (2026-10-23)</summary>

**[LOW] Gate-runner state: inherit WITNESSED end state instead of refusing all state at a run's start.** Found while working #530; the orchestrator ruled it a nit-store item.

**Current guard (#530):** if the CPP runner's resumable state (`.git/cpp-runs`) is non-empty at a witnessed run's start, that run's source digest is marked unreadable, so its stages are never attributed.

**Why it is sufficient for #530:** measured with the pinned 652c0118 gate on the green rangekit fixture.
- A successful run deletes its state, so honest plan→summary and plan→plan sequences start clean.
- A failing run leaves `check-*.json`, but on a green tree that needs a source change, which is already unattributable.
- The preflight now re-checks this per subject.

**Where it falls short:**
- **A red fixture:** an honest failed run leaves state, and an honest re-run would read UNKNOWN.
- **An interrupted run** (timeout): same effect.
- In both cases the cost is evaluability, never a false pass.

**The general design (the orchestrator's):**
- record the state digest at the END of each witnessed run;
- a later run whose start state equals the previous witnessed run's end state is inherited legitimately;
- only state no witnessed run produced is unattributable: present at the first run, or changed between runs.

**Reds for it:**
- (1) state seeded before the first run → not attributed;
- (2) plan then summary, honest → SATISFIED;
- (3) plan then plan, honest → SATISFIED;
- (4) plan, then the state tampered, then plan → not attributed.

**Needed before:** any flow-check task with a red fixture.


</details>

Filed from the Nit Store aggregation pass https://github.com/cooneycw/skillc/issues/20#issuecomment-6382622225 at the owner's request (2026-10-24).

<!-- flow-run n=2 id=623c5a4ddb334afba9b5769b019b7e13 -->
## Run 2 - issue #536 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #536
- Read at:      2026-10-25T01:42:30Z
- updatedAt:    2026-10-25T01:20:21Z   (context only - moves on comments and labels)
- Body digest:  01c00d130219027fba6bf3716944adce13d990f0b98e0f3efba089b92b1b06e3   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 7629 of 7629 (cap 16384)

### Body as read
**Severity: LOW to MEDIUM.** Four gaps in what the fixture/live path checks or records. Each one fails closed or costs evaluability; none is a false pass.

## Items
1. **The preflight never exercises `SKILLC_ALLOW_REAL_AGENT`.** A preflight read ALL PASS, and the live run was then refused at its first attempt. Assert the opt-in in the exact launch env, without launching, or route the rehearsal through the same guard.
2. **The live report omits `transcript_codex_invocations` and `transcript_files_found`.** These are computed in memory and used for credit, but persisted only on the `--judge-replay` path (`skillc/fixture_live.py` ~1696). Add both to the per-attempt report, next to `nested_codex`.
3. **`fixture_campaign.ACTOR_SOURCE` can't be credited under #518's steward**, because it never reads the credential. Its bytes are pinned by #434's candidate identities. Wrap it, as `TURN_ACTOR_SOURCE` is wrapped, or re-pin the identity. **Decide when #434 resumes.**
4. **Gate-runner state inheritance.** Today, any non-empty `.git/cpp-runs` at a witnessed run's start makes the run unattributable. Instead, record the state digest at the end of each witnessed run, and inherit it when the next run starts from exactly that state. **Needed before any flow-check task with a red fixture.**

## Acceptance
- [x] Items 1 and 2 land as one PR. Each has a red case that fails on the pre-fix code.
- [ ] Item 3 is decided and recorded at #434's resume.
- [ ] Item 4 lands with the four reds from the source nit: seeded state is not attributed; plan→summary is SATISFIED; plan→plan is SATISFIED; tampered state is not attributed.

## Source nits (moved from the Nit Store, #20)
Full text of each source comment, so this issue stands on its own.

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6339769206 (2026-10-22)</summary>

**Nit (found in wave skillc-finish while working #279, 2026-10-22). Severity: low; it costs a hold slot, not correctness.** The #279 Step-6 preflight, including the no-spend actor rehearsal, never exercises the operator opt-in guard `lifecycle._refuse_real_agent` (`SKILLC_ALLOW_REAL_AGENT=1`). A preflight reported ALL PASS, and the live run was then refused at its first attempt for the missing opt-in (run dir `20261022T113506Z-db8098`, no spend). The guard was right. The point is that the preflight can't tell a launchable command from an unlaunchable one. Fix idea: the preflight asserts that the opt-in is set in the exact launch env, without launching, or the rehearsal routes through the same guard.

</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6348964145 (2026-10-22)</summary>

**Nit (found in wave skillc-finish while working #279's sizing-3 preflight, 2026-10-22). Severity: LOW.** The live record does not keep the transcript scan's result.

**What.** The fixture-path observation hook (`agent_trial._make_observe_before_teardown`) computes `transcript_codex_invocations` and `transcript_files_found`. The credit gate (`agent_trial._fixture_credit_block`) and `fixture_live.containment_trigger` read them in memory. But neither the run store's observation/evidence objects nor `live-report.json` keeps them:
- `grep -r transcript_codex_invocations` over a rehearsal run directory finds nothing;
- the report's attempt keys include `nested_codex` (the guard) but not the scan.

**Why it matters.** "Credited" cannot distinguish a scan that found 1 refused-and-matched invocation from a scan that found 0. Only the guard half of "refused and detected" is on the record. To prove detection, the #279 sizing-3 preflight had to re-run `attempt_guard.scan_transcript_text` over each retained transcript. That works, and `--judge-replay` does the same, but a reader of the report alone cannot see detection.

**Fix shape:** put the two scan fields in the per-attempt report, next to `nested_codex`.


</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6348963693 (2026-10-22)</summary>

**Nit (found in wave skillc-finish while working #279's sizing-3 preflight, 2026-10-22). Severity: MEDIUM (orchestrator ruling). A regression from #518 (#523).** On the fixture path, single-turn scripted actors can no longer be credited.

**What.** #518's credential steward withdraws `~/.codex/auth.json` only after a client READ followed by a 3 s quiet period (`docker/fixture-service/skillc-credential-steward.py`). Two scripted actors never read the credential:
- #434's `fixture_campaign.ACTOR_SOURCE`, used by `skillc level3-campaign` and by the turnless `rehearsal_actor` (`skillc/fixture_live.py`, the `not turns` branch);
- the plain `--rehearse actor` of a turnless task (flow-auto-necessity).

So the steward either withdraws at the 30 s deadline or is stopped while still armed. Its record reads `unknown`, which blocks credit (`credential_steward.credit_block`) and stops the schedule.

**It fails closed:** nothing is ever falsely credited; the run just can't credit anything. The affected work, #434, is **parked**.

**Fixed for #279 by PR from branch `issue-279-sizing3-rehearsal` (50dbf7d).** Both TURN actors (`TURN_ACTOR_SOURCE`, `STEP6_ACTOR_SOURCE`) now read the credential as codex 0.157.1 does and end a turn only once it has been withdrawn.

**Not fixed.** `fixture_campaign.ACTOR_SOURCE`: its bytes are pinned by #434's candidate identities, so it can't be edited in place. Closing it needs either a wrapper in front of the campaign actor (like `TURN_ACTOR_SOURCE`), or a re-pinned identity, decided when #434 resumes.

**Repro:** `skillc level3-live <a turnless #434 declaration> --rehearse actor` on main 80eca1d: every attempt reads `credential steward record is unknown`.


</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6368996572 (2026-10-23)</summary>

**[LOW] Gate-runner state: inherit WITNESSED end state instead of refusing all state at a run's start.** Found while working #530; the orchestrator ruled it a nit-store item.

**Current guard (#530):** if the CPP runner's resumable state (`.git/cpp-runs`) is non-empty at a witnessed run's start, that run's source digest is marked unreadable, so its stages are never attributed.

**Why it is sufficient for #530:** measured with the pinned 652c0118 gate on the green rangekit fixture.
- A successful run deletes its state, so honest plan→summary and plan→plan sequences start clean.
- A failing run leaves `check-*.json`, but on a green tree that needs a source change, which is already unattributable.
- The preflight now re-checks this per subject.

**Where it falls short:**
- **A red fixture:** an honest failed run leaves state, and an honest re-run would read UNKNOWN.
- **An interrupted run** (timeout): same effect.
- In both cases the cost is evaluability, never a false pass.

**The general design (the orchestrator's):**
- record the state digest at the END of each witnessed run;
- a later run whose start state equals the previous witnessed run's end state is inherited legitimately;
- only state no witnessed run produced is unattributable: present at the first run, or changed between runs.

**Reds for it:**
- (1) state seeded before the first run → not attributed;
- (2) plan then summary, honest → SATISFIED;
- (3) plan then plan, honest → SATISFIED;
- (4) plan, then the state tampered, then plan → not attributed.

**Needed before:** any flow-check task with a red fixture.


</details>

Filed from the Nit Store aggregation pass https://github.com/cooneycw/skillc/issues/20#issuecomment-6382622225 at the owner's request (2026-10-24).

<!-- end of body -->
