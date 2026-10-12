# Flow run record - issue #348

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=f7f10e687f504aa2b32b8e0fa1d7b0b9 -->
## Run 1

- Run-id:            f7f10e687f504aa2b32b8e0fa1d7b0b9
- Run-start:         faf8810d1ec47eb9a9f6b3bb4c41a4d3730be026
- Issue: #348
- Base SHA: faf8810d1ec47eb9a9f6b3bb4c41a4d3730be026
- Necessity verdict: Needs reframing
- Approval: granted
- Approver: skillc wave orchestrator, phase-one GO-WITH-CONDITIONS
- Recorded at: 2026-10-12

### Section B evidence

#357 merged as 8330729, #346/#359 as 9d623f5 and #355/#358 as faf8810.
No production GateWitness construction exists; calibration CLI still omits
subject.profile when building treatment. Existing consumers require the witness
and exact graded_tree_digest envelope. The capture projection writes object
blobs and can return partial or empty populations, so reuse needs isolated
scratch storage and explicit refusal. #354 owns trial/profile/records files.

### Section C - the approved plan

1. `skillc/cli.py` - forward calibration subject.profile/root, preserve absent profile.
2. `skillc/witness_capture.py` - reuse actual capture projection in a disposable controller store, reject partial/empty/error outcomes, hash canonical grading population.
3. `skillc/verify.py` - optional finalized controller witness at locked frozen-file seam, both grading paths, reject raw-byte conflicts and preserve existing callers.
4. `tests/test_calibration_run_profile_closure.py` - real CLI/profile construction regression and absent-profile control.
5. `tests/test_witness_capture.py` - actual capture parity, modes/exclusions/mutations, failure/empty/cleanup controls.
6. `tests/test_verify.py` - exact frozen-file trusted delivery in both grading branches, forgery/conflict/staleness controls.

Phase one only: no backend, live-test, grader, records, trial or profile edits.
Existing digest persistence plus private acceptance bytes meets this phase's
contract; raw witness archival is not added. Production construction and runtime
receipt plumbing await separate approval and dependency handoffs. #354 caller
pin adoption and integrated isolated-VM evidence remain required for study
readiness. Tests and negative controls precede independent review; full verify
requires the shared serialized slot. No Docker or model calls are authorized.
