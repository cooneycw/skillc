# Issue #106 as read by this run

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #106
- Read at:      2026-09-27T12:22:46Z
- updatedAt:    2026-09-27T10:34:26Z   (context only - moves on comments and labels)
- Body digest:  e98beefcc4511dbc612f95903110d1d265c7af9341bcede457ccf76d63181cb5   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 2863 of 2863 (cap 16384)

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

