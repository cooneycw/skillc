# Flow run record - issue #652

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=dc46121f5a944e8596306cd8edc65ec8 -->
## Run 1

- Run-id:            dc46121f5a944e8596306cd8edc65ec8
- Run-start:         18d89c86319a0a615f0d6f9ad488f8bf8e65ac53
- Issue:             #652
- Base SHA:          18d89c86319a
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          owner (cooneycw), "approved" in the flow:auto session
- Recorded at:       2026-10-31T00:00:00Z

### Section B evidence
No commits on origin/main after 18d89c8; no PRs merged since 2026-10-31 (only related: #646, which added the test); no duplicate/superseding issue (#640 parent, #645 unrelated oracle defect). Reproduced locally: executable case CLI fails with PermissionError EACCES on ./helper_cli because Docker's --tmpfs defaults to noexec (measured: rw,nosuid,nodev,noexec).

### Section C - the approved plan
1. `skillc/inventory_oracle.py` - add `exec` to the oracle /tmp tmpfs options, comment why (Docker noexec default; captured 100755 must run; nosuid/nodev kept).
2. `tests/test_inventory_runtime.py` - pin /tmp tmpfs options in the argv unit test: exec present, noexec absent, nosuid+nodev kept; red on pre-fix code.

Scope: small. Risks: local repro uses skillc-cicd-runtime image as a stand-in for the trial image; issue's done-when is post-merge evals26 runner SUCCESS, so Refs not Closes until observed. exec on /tmp slightly widens what a candidate can do in a disposable offline read-only container; nosuid kept.
