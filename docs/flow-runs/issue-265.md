# Flow run record - issue #265

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=3a81c0b2da644a6582d9d8b32cd01deb -->
## Run 1

- Run-id:            3a81c0b2da644a6582d9d8b32cd01deb
- Run-start:         3ffceccf4b5ac87822c0b1f1f52e0784dd6d06dc
- Issue:             #265
- Base SHA:          4ef6feb (plan formed); merged forward to 3ffcecc before the first edit
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          repository owner (cooneycw), in the flow:auto session, after the ELI5 report; also directed coordination with the #264 session rather than holding for it
- Recorded at:       2026-10-04T17:45:00Z

### Section B evidence
Commits since filing touching the paths: none (only 4ef6feb, #289, uptake study).
Merged PRs since filing: #289, #257, #256, #244, #243, #241, #240, #239, #236 - none profile/manifest work.
Duplicate/superseding issues: none (#258 tracker, #247 parent, #20 nit store).
Prerequisite #264 OPEN at gate time; its branch (a9319a2, protocol.md section 10.4 and
evals/workflow-contracts/flow-check/case-contract.json) was pushed but had no PR. Owner approved
proceeding while coordinating; this run adopts 264's section 10.4 vocabulary verbatim.

Revision within the agreed outcome (no new approval): the plan named CPP pin b8825bd; #264's case
contract pins 85e9b03 (the historical cpp-codex pin) and cites reference.md line numbers there, so
the profile pins 85e9b03 to keep the obligation matrix and the inventory on the same bytes.

### Section C - the approved plan
1. `skillc/profile.py` - generic profile declaration loader, transitive closure walker, refusals, content-addressed inventory
2. `skillc/cli.py` - `skillc profile validate` subcommand
3. `evals/subjects/cpp-codex-flow-check/profile.json` - targeted product profile for flow-check at the pinned CPP revision
4. `evals/subjects/cpp-codex-flow-check/PROFILE.md` - human explanation of the profile and its limits
5. `evals/subjects/cpp-codex-flow-check/evidence/inventory.json` - generated inventory for the pinned source
6. `tests/test_profile.py` - committed controls: missing reference/helper, stale mirror, conflicting destination, empty selection, undeclared absolute path, valid transitive inventory, unrelated collection
7. `tests/test_materialize.py` - extend the genericity guard to profile.py
8. `docs/specs/evaluation-facility/profiles.md` - profile schema, refusals, and what the inventory does not establish
9. `docs/specs/evaluation-facility/materialization.md` - link to profiles.md

Scope: ~9 files, ~900-1200 lines. Risks: #264 vocabulary not yet merged; pattern-based scan
cannot see a dependency matching no declared pattern (absolute-path detector is a committed control);
subject.json is reused from cpp-codex rather than duplicated (plan item 3 said subject.json too).
