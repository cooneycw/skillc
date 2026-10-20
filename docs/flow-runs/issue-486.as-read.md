<!-- flow-run n=1 id=390594b2645a47a1bacfcad1cfca611a -->
## Run 1 - issue #486 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #486
- Read at:      2026-10-20T14:43:59Z
- updatedAt:    2026-10-20T14:43:11Z   (context only - moves on comments and labels)
- Body digest:  7d70c21971c9a57ae256ff1381ade3b01320b2d98ff5dcf21b50fdd2e9550bb7   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 3081 of 3081 (cap 16384)

### Body as read
## Codex transcript adapter is blind to `exec_command` function calls and batched `exec` output, so every #434 campaign attempt was never graded

**Severity:** blocks the #434 live campaign. Its one owner-approved run produced **0 graded attempts out of 10**.

### What happened

#434's owner-approved campaign ran on 2026-10-20 (run `20261020T141529Z-8f538e`'s sibling `20261020T141529Z-3585c9`, declaration `sha256:694e2b82…bacf2`, skillc `00a5e5a`):
- all 10 attempts were captured;
- every one was refused for grading with "prompt_delivered=True, canary_satisfied=False - never graded without both confirmed against the real transcript";
- the canary reason in every case: "no confirmed, error-free tool_use event in the transcript".

The 2026-10-18 measurement used the same client (codex 0.157.1), the same image (`773ea763`) and the same model (gpt-6-astra, effort high), and had `canary_satisfied=True` on both attempts.

### Cause, read from the retained transcripts

`skillc/transcript_adapter.py`'s codex path turns a tool call into a `tool_use` event ONLY for `custom_tool_call` + `custom_tool_call_output`. It confirms one (error=False) only when the call is named `exec` and `_codex_exec_exit_code` finds a parseable `exit_code` of 0. The live model now uses two shapes the adapter cannot read:

1. **`response_item/function_call` named `exec_command`**, with its `function_call_output`. There were 10-11 per campaign attempt and 0 in the measurement. The adapter never maps `function_call`, so these are invisible.
2. **`custom_tool_call` `exec` scripts that batch results**, with output like `{"i":0,"result":{"status":"fulfilled","value":{...}}}` instead of the `{"chunk_id":…,"exit_code":0,…}` chunk. No `exit_code` is found, so each reads as error=True.

Same client and same model name means this is a change in the model's tool use. The canary (`trial_bootstrap.check_agent_canary`) is therefore an instrument that cannot see the tool work actually done.

### Evidence it is the instrument, not the agent

The retained trusted observations (case, service record, git capture, final report) were replayed through `flow-auto-necessity` revision 3, as an UNOFFICIAL, no-spend diagnostic:
- TWIN: endpoint PASS 5/5;
- CLEAN: PASS 4/5. The fifth is a verdict-phrasing gap in the grader, filed separately.

The containment held on every attempt: no stop, nested-codex guard `zero`, egress eligible, and the declared model and effort observed.

### What a fix needs (a question for the owner/orchestrator, not a decision)

- Map `function_call` `exec_command` (+ output) to `tool_use`, with its exit status read from its own output shape.
- Read the batched `exec` result shape.
- Each with a red from these exact transcripts: the retained objects are on kyle19 under the run dir above (private).
- Whether retained attempts may then be re-graded without spend, or the campaign re-run, is an owner approval question: the approval was for one run, no re-run.

Found by skillc-worker-A (wave skillc-400) while running and verifying the #434 campaign.

Refs #434

