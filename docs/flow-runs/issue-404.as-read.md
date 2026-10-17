<!-- flow-run n=1 id=8ab1668c331a49b7a8abd279f7eb7246 -->
## Run 1 - issue #404 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #404
- Read at:      2026-10-17T11:27:00Z
- updatedAt:    2026-10-17T11:26:46Z   (context only - moves on comments and labels)
- Body digest:  a4fcce9c7729cce79f6a51b70ac1e7b9b866e8e1e72743548f090e83e53972b9   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 3278 of 3278 (cap 16384)

### Body as read
## Problem

`GateWitness` cuts the gate output it forwards to the subject at `reply_byte_cap` without telling anyone (`skillc/gate_witness.py`, the `run_gate` reply: `(result.stdout or b"")[:self._reply_byte_cap]`, and stderr the same way). Production constructs the witness with the default, `DEFAULT_REPLY_BYTE_CAP = 4096` (`skillc/agent_trial.py:360`, no `reply_byte_cap` argument).

The real `flow-finish-gate.sh` prints its verdict, `FLOW_FINISH_GATE: <ok|warn|fail> ...`, as the **last** line of stdout, after the runner's JSON report. Once stdout passes 4,096 bytes, the subject receives a prefix with no verdict line and no sign that anything was cut. Only the exit code still arrives intact. A byte cut mid-character also turns into U+FFFD, because of `decode(errors="replace")`.

## Evidence (host, pinned closure `cpp-codex-flow-check-86641e8`, 2026-10-16)

| Tree | exit | stdout bytes | stderr bytes | last stdout line |
|---|---|---|---|---|
| `gate-stops-early/discrimination/fixture` | 3 | 2,233 | 961 | `FLOW_FINISH_GATE: warn (skipped gates: typecheck)` |
| `gate-stops-early/fixture` | 0 | 2,848 | 648 | `FLOW_FINISH_GATE: ok` |
| `gate-stops-early/fixture` + 2 small failing asserts | 1 | **4,324** | 2,500 | `FLOW_FINISH_GATE: fail` (**past the cap**) |

So the cap is already exceeded by an ordinary failing run: two one-line assertion failures. A real failing gate with tracebacks will exceed it by more.

## Why it matters

- **Live correctness for treated model attempts (#287/#288).** A subject that runs the gate and gets a failure sees a truncated JSON report and no verdict line. That changes the workflow under test: flow-check's own reading instruction keys on the `FLOW_FINISH_GATE:` line. Honest-reporting outcomes would be measured on an output the real tool never produces.
- **Silent.** The witness record and the controller's own capture keep the full bytes, so grading is unaffected. Only what the subject sees is cut. Nothing records that a reply was truncated, so this would not show up in any result.
- The Level-3 campaign (#375/#376) uses scripted actors that do not read the reply, so it cannot have surfaced this.

## Design choices (owner/orchestrator call, not decided here)

1. Raise the production cap to the backend's capture bound (`Limits.max_captured_stdout_bytes`). The reply stays bounded, but by the same bound as the capture, so whatever the controller captured whole reaches the subject whole.
2. Keep a cap, but refuse a reply that would truncate, as a channel failure with exit 125 (the shim's existing infrastructure-failure code). Never forward a silent prefix.
3. Keep a cap and forward the tail instead of the head, plus an explicit truncation marker. This changes the bytes, so it is not a byte-identity claim.

Whatever is chosen needs a red case: a gate whose stdout exceeds the old cap must reach the subject with its verdict line, or be refused, on today's code red and after the fix green.

## Found while

Working #334's byte-identity item (moved from #332). That PR fixes the separate stderr-forwarding defect (`error` was forwarded instead of the raw stream) and asserts byte identity at the production default cap on the discrimination fixture, which fits under 4,096 bytes. It does not change the cap.

