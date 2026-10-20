# Flow run record - issue #486

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=390594b2645a47a1bacfcad1cfca611a -->
## Run 1

- Run-id:            390594b2645a47a1bacfcad1cfca611a
- Run-start:         00a5e5ad23e1b4abe29122a03fa8d3b2a64fe4f6
- Issue:             #486
- Base SHA:          00a5e5a
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          wave skillc-400 orchestrator (authority-model orchestrator-only), GATE: GO-WITH-CONDITIONS #486, R1-R4; this run is PR-1
- Recorded at:       2026-10-20T15:30:00Z

### Section B evidence
#486 filed 2026-10-20, OPEN. No merged change touches transcript_adapter.py, the census or containment_trigger since (00a5e5a, 16ccfdf, 043279f). Duplicates: none; #106 is the census's origin. Verified on the 10 retained transcripts of run 20261020T141529Z-3585c9: 110 function_call exec_command (args {cmd,max_output_tokens[,workdir]}, string outputs "Process exited with code N"); batched exec outputs with nested exit_code; census unrecognized_types [function_call, function_call_output] on all 10, consumed by nothing.

### Section C - the approved plan (PR-1)
1. `skillc/transcript_adapter.py` - function_call exec_command + output to tool_use (confirmed only when every exit line is 0), skill_invocation from cmd, batched exec nested exit codes (worst wins, rejected = failure)
2. `skillc/agent_trial.py` - census known types gain function_call/_output; credit gate refuses unrecognized or unassessable codex census
3. `skillc/fixture_live.py` - containment_trigger stops on unrecognized or unassessable codex census types
4. `tests/fixtures/transcripts/codex` - synthetic, shape-faithful fixtures mirroring the 2026-10-20 capture, with README
5. `tests/test_transcript_adapter.py` - new shapes, reds, old shape unchanged, real-store test that skips loudly
6. `tests/test_agent_trial.py` - credit gate reds
7. `tests/test_fixture_live.py` - containment stop on unknown types, no stop on known
8. `changelog.d/486.md` - one bullet
Scope: medium. Risks: fail-closed stops on any new benign type (intended); old-shape regression; Claude client must stay unaffected.
