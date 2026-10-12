# Flow run record - issue #315

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=15df254ef4304a81b71efba70ac896f0 -->
## Run 1

- Run-id:            15df254ef4304a81b71efba70ac896f0
- Run-start:         450445da5eb83719aa68f0f448f29bda56358ec9
- Issue: #315
- Base SHA: 450445da5eb83719aa68f0f448f29bda56358ec9
- Necessity verdict: Partially addressed
- Approval: granted
- Approver: wave skillc orchestrator, GO-WITH-CONDITIONS on 2026-10-12
- Recorded at: 2026-10-12

### Section B evidence

The installed runner shipped in ef04faf (#328), the family controls in
87190e1 (#331), witness in 50b5098 (#329), overlay in 9c79510 (#339)
and 10ff168 (#342), cold install in 5cf1586 (#340), trial tools in
e43445a (#347), and closure in 0518cc0 (#349). The later #352
(da2d572) narrowed expected failures to property-specific exceptions.
The superseded #309 design does not authorize Woodpecker changes.
Issues #183, #266, #269, #332, #334 and #343 still require real-Docker
evidence. The active #355 repair must land before the campaign; its
local sibling worktree carried 99e8474 during this audit and was preserved.

Executing the installed runner's probe snippet with a simulated DNS or
permission error returned unreachable and allowed the isolation classifier
to proceed. A report with a targeted trialimage:no-uv expected failure and
passing sibling tool tests returned SUCCESS. Both defects were reproduced
without Docker or network access; the existing 106 runner tests passed.

### Section C - the approved plan

1. `ci/real-docker/run-real-docker` - only explicit timeouts and routing errors may report unreachable; DNS, permission and unexpected errors report probe_error, while successful and refused TCP connections remain reachable.
2. `tests/test_real_docker_isolation.py` - execute the actual embedded probe with controlled socket outcomes and bind them through the classifier; prove that restoring broad OSError handling fails the controls.
3. `ci/check_real_docker_ran.py` - after worker-BB releases its eighth-floor work, make pytest.xfail prevent SUCCESS beside passing siblings, preserving ordinary-skip semantics.
4. `tests/test_real_docker_verdict.py` - after worker-BB release, prove mixed pass/xfail refusal and ordinary-skip compatibility against the current complete floor.
5. `ci/real-docker/README.md` - document detector and verdict boundaries and concrete operator setup/evidence requirements; refresh the campaign floor after merged fixes, including #338 and #348.
6. `CHANGELOG.md` - record the detector and verdict corrections.

Scope: approximately 120-220 lines in six implementation/documentation files,
plus this record and its issue snapshot. The initial lane excludes the verdict
pair until worker-BB releases it; no edits there may precede that handoff.

Risks: a probe error must not be mistaken for isolation; expected-red evidence
must identify the intended property, not unrelated setup failure; concurrent
floor changes require a fresh merged-base inventory. Preserve ordinary skip
behavior rather than silently broadening the floor's claim. No other material
approach concern found.

Keep #315 open until the operator records isolation off/on and guest-firewall
flushed evidence and the final shared campaign. VM identity/access and
hypervisor-owned boundary remain unestablished. No shared network changes,
Woodpecker changes, paid model calls or campaign before those prerequisites.
The timer remains disabled until setup and campaign are accepted. Commit,
push and PR are authorized; merge requires the orchestrator's review and a
green ci/woodpecker/pr/ci check on an up-to-date base.

### Approved revision: verdict publication and multi-address probe

On 2026-10-12 the orchestrator approved the additional publication repair and
expanded the lane to `tests/test_real_docker_post.py`. Offline whole-process
controls confirmed that the runner's `set -e` aborted on the posting helper's
valid FAILURE/ERROR exits before status publication and cleanup. The approved
repair captures those exits, validates the status/output contract, maps helper
crashes and malformed output to ERROR, and tests the actual shell process with
fake external executables. Healthy results, expected-red control routing,
cleanup and final exit codes remain explicit requirements.

The independent review also identified stdlib connection error collapsing
across multiple resolved addresses. Preserving all address errors and adding
controls using the real connection routine is within the approved probe
behavior. Any successful/refused address means reachable; otherwise unknown
errors refuse; only exclusively timeout/routing failures mean unreachable.

The orchestrator revised sequencing after worker-BB released the verdict pair:
this PR keeps the existing seven-file floor. Worker-BB adds the eighth floor
only after this repair merges and releases the pair; registering the matching
cwd break family follows the test/floor merge, before the final campaign.
The original approved plan above is retained as history.

### Independent review evidence

A GPT-6.1-Sol reviewer read the full change independently of the GPT-6-Astra
implementer. The first pass found the multiple-address error-collapse defect;
that finding was accepted and repaired. The second pass found no defects and
ran 69 offline isolation, verdict and posting tests successfully. No Docker
or network operation was used for that review. This records the actual review;
the flow receipt helper's Claude/Codex identity pairing cannot represent this
Codex/Codex review without fabricating a Claude session identity.
