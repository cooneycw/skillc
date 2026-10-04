# Flow run record - issue #264

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=80aa74219277433d9e70e58e1633797f -->
## Run 1

- Run-id:            80aa74219277433d9e70e58e1633797f
- Run-start:         8c74a88e814ae1aebe967fa968364f868d68ff84
- Issue:             #264
- Base SHA:          8c74a88e814ae1aebe967fa968364f868d68ff84
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          owner (cooneycw), session reply "approve"
- Recorded at:       2026-10-04T17:10:00Z

### Section B evidence
Commits on origin/main since filing: none. PRs merged since filing: none
(same-day earlier, not addressing it: #257, #256, #244, #243, #241, #240, #239, #236).
Open PR #289 (uptake-study runner) has no file overlap. Related, not superseding:
#246, #258, #273, #274, #270, #271.

### Section C - the approved plan
1. `docs/specs/evaluation-facility/protocol.md` - add section 10 "Workflow-contract lanes": three lanes, obligation sources and measure classes, S/V/U + NOT_APPLICABLE, four observation states, treatment inventory/helper parity/identities/nudges/prompt accounting, all-k, intervals and clustering, all-attempt/retry rules, convenience proxies, held-out policy; cross-references from sections 2 and 7.
2. `evals/workflow-contracts/flow-check/case-contract.json` - new, version 1: pinned flow-check inventory at cpp-codex @85e9b03, obligations with source/evidence/rule/class/denominator, lane x task applicability matrix.
3. `evals/workflow-contracts/flow-check/README.md` - new: the matrix in prose with worked good, bad and unobservable examples on both calibration tasks plus a valid alternative workflow; #203/#237 untouched.
4. `evals/README.md` - add a workflow-contracts row and a short lanes note mapping existing B/N/P (informational).
5. `tests/test_workflow_case_contract.py` - new: format check for the contract and link resolution in the new docs, with a mutated-contract red case.

Scope: 5 files, ~450-600 lines, no skillc/ code. Risks: existing fixtures have no lint/test/typecheck targets so flow-check's run obligations are NOT_APPLICABLE on all of them (stated, deferred to #270); interval methods are declared defaults, overridable with justification; must not become #274's validator.
