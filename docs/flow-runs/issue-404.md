# Flow run record - issue #404

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=8ab1668c331a49b7a8abd279f7eb7246 -->
## Run 1

- Run-id:            8ab1668c331a49b7a8abd279f7eb7246
- Run-start:         f511779b9a1206dad0141b593c4310636f04914a
- Issue:             #404
- Base SHA:          f511779b9a1206dad0141b593c4310636f04914a
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          owner (cooneycw), "approved, go ahead" in this /flow:auto session; option 1 itself recorded on #404 (2026-10-17)
- Recorded at:       2026-10-17T11:35:00Z

### Section B evidence
- commits since filing touching skillc/gate_witness.py, skillc/agent_trial.py, skillc/decide_reply_channel.py, docker/trial/flow-check-gate-shim.py: f511779 (#406, stderr forwarding, cap unchanged), c64bdd6 (#407, gate env, cap unchanged)
- merged PRs since filing: #405, #406, #407 - none touches DEFAULT_REPLY_BYTE_CAP
- dup/super: none

### Section C - the approved plan
1. `skillc/gate_witness.py` - default reply cap is the capture bound per stream (limits.max_captured_stdout_bytes / max_captured_stderr_bytes); drop the 4096 constant; explicit reply_byte_cap kept for tests and documented as truncating
2. `tests/test_gate_witness.py` - >4096-byte stdout/stderr reach the subject whole under the default; a capture-bound overflow is refused, never silently cut
3. `tests/test_agent_trial_gate_witness.py` - production path: a gate printing >4 KB ending in its verdict; the fake subject asserts it received the last line
4. `CHANGELOG.md` - entry

Scope: 4 files, ~80 lines. Risk: the channel's in-memory decision log deep-copies full replies per gate run (bounded by the capture bound; not persisted) - nit store.
