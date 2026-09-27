# Issue #106 as read by this run

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #106
- Read at:      2026-09-27T14:16:07Z
- updatedAt:    2026-09-27T14:00:03Z   (context only - moves on comments and labels)
- Body digest:  225f8040b0cd7234705b3dce47c98a6882ec855869cac3f455d612d45744f84b   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 3645 of 3645 (cap 16384)

## Body as read
Refs #10, #11, #26, #12. This is what every agent run is still waiting for.

## Problem

The pieces for one agent attempt are merged separately, but nothing runs them together:
- the Docker backend (#77/#85);
- the trial image and bootstrap, meaning the per-trial home and seed, the argv prompt, and the prompt-delivery check (#78/#84);
- the subscription-login credential (#98/#105);
- the lifecycle driver and grading through the backend (#70/#76);
- the per-tier verdicts (#88).

#11's remaining bullet (Level 1 per collection), #26's selection probe and #12's pilot all need that end-to-end driver. #105's manifests name it as the remaining prerequisite ("trial.py's execution loop").

## Scope

One attempt, end to end, through the ExecutionBackend seam:
1. `prepare()`.
2. Install the subject and task fixture.
3. Resolve and check the credential (#98: fresh copy; refuse on low remaining life), then deliver it to the home.
4. Compose the per-trial seed and MCP config (#78) and validate the seed before launch.
5. Launch the pinned client with the prompt by argv or stdin, never keystrokes.
6. Verify the transcript's first user message against the prompt that was sent (#78).
7. Check the liveness canary against the REAL transcript through a per-client transcript adapter. This is the gap recorded on #81: a real Write result doesn't echo file contents. The adapter must pair a tool call with its success result, or read the file back, so the canary can pass on a genuinely live run.
8. `confirm_stopped()`, then `export()`, then grade through the verifier, recording `refresh_observed`.
9. `destroy()` and `confirm_absent()`.

Every failure path lands in the lifecycle record as BLOCKED or UNKNOWN with its reason: an expired credential, a failed prompt-delivery check, a failed canary, a timeout, or a client crash. None is ever recorded as a skill result.

## Acceptance: each with a named red case

- [ ] Runs end to end against the fake docker, using a scripted fake client that writes a realistic transcript for each client format. This is the green it rests on.
- [ ] **Transcript adapter, per client, verified against a committed real-format fixture:** red when a tool call is requested but fails, and red on a no-op transcript.
- [ ] **Prompt-delivery mismatch:** the attempt is BLOCKED, not graded.
- [ ] **Credential below the threshold:** the attempt is BLOCKED before launch, and no container remains.
- [ ] **No real model call anywhere in the suite:** a structural test, as #96 did for the judge. A real run requires an explicit opt-in flag and is never the default.
- [ ] **Leak check on the exported record and transcript,** including the credential-token class from #105.
- [ ] Owed to the operator's live run, and stated so: a real client, a real login, the host login still working afterwards, and the real transcript format drift.


## Folded in from the Nit Store (#20), 2026-09-27

- [ ] **The agent run's observation is never persisted.** `agent_trial.run_one_attempt` returns `prompt_delivered`, `canary_satisfied`, `skill_invocations`, `skills_listed`, `credential_refresh_observed_in_container`, `grading_eligible` and `graded`/`grading_blocked_reason` only in memory. The kept store's `lifecycle-*.json` and journal hold none of them, so the printed paste-back is the only record. When it misprinted a field (#124), the real values were unrecoverable and two live runs had to be repeated. Persist the observation as an evidence file beside `lifecycle-*.json`, checked by `check-records`. This is step 8's "recording refresh_observed". (https://github.com/cooneycw/skillc/issues/20#issuecomment-5856161163)

