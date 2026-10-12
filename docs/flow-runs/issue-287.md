# Flow run record - issue #287

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=e730aecff9f1451aa5bf0958e3596666 -->
## Run 1

- Run-id:            e730aecff9f1451aa5bf0958e3596666
- Run-start:         5e80d3e5f714e6277e7a5b75fae54c35089ca338
- Issue: #287
- Base SHA: 5e80d3e5f714e6277e7a5b75fae54c35089ca338
- Necessity verdict: Partially addressed
- Approval: granted
- Approver: wave skillc orchestrator, initial endpoint preparation gate, mailbox revision 15
- Recorded at: 2026-10-12

### Section B evidence

Main 5e80d3e has the declaration parser and task grader but no symmetric
improvement endpoint: absent baseline witness forces raw honesty UNKNOWN.
Pending #348 supplies profile forwarding and treatment witness construction;
it does not create a baseline observer. Parked preparation 571d763 remains
unchanged. This slice references #287; it does not close it or authorize #288.

### Section C - the approved plan

1. `skillc/calibration.py` - closed optional outcome/task-content schema, exact declaration approval binding, strict selected endpoint and discrimination refusal.
2. `skillc/calibration_run.py` - bind dispatched inputs and immutable declaration to trial config; reconstruct reports from verified ledger; retain all raw outcomes and counts.
3. `tests/test_calibration_outcome_endpoint.py` - committed good/bad controls and actual pre-fix report regression, using only local deterministic adapters.
4. `evals/calibration-287/pilot-improvement-declaration.json` - scoped transplant from 571d763, endpoint and actual current task identities, profile opt-in, approval null.
5. `evals/calibration-287/pilot-discrimination-declaration.json` - scoped transplant preserving separate discrimination endpoint and pending runtime/closure prerequisites.
6. `evals/calibration-287/README.md` - exact preparation semantics, unmeasured public-vocabulary prompt risk and remaining execution holds.

Scope: bounded endpoint preparation, not a new experiment framework. Preserve
nonempty legacy reports and all raw honesty/verified results and eligibility.
Risks: post-run endpoint drift, malformed selected rows manufacturing PASS,
unobserved honesty being mistaken for abstention, and public prompt vocabulary
changing discrimination. Commit controls for the implemented boundaries.
CLI and CHANGELOG are not granted; consuming CLI refusal handling remains a
later integration requirement. Merge #348 before finish. Full verification
requires root scheduling after CC and EE. No paid trials, Docker campaign,
task-tree edits, profile/records changes, or changes to parked draft history.
