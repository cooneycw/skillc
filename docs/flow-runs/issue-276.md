# Flow run record - issue #276

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=8e022ebb4fa34398a5f4faa53ecc9834 -->
## Run 1

- Run-id:            8e022ebb4fa34398a5f4faa53ecc9834
- Run-start:         1fc1e6ecf0c7e7c6b7fad6be99a7953b8a6bbe23
- Issue:             #276
- Base SHA:          1fc1e6e
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          skillc-400 (orchestrator, owner-delegated)
- Recorded at:       2026-10-17T20:40:00Z

### Section B evidence
Commits since 2026-10-04T16:31:48Z are building blocks only:
- b86bdf1: the #183 channel and the one-socket mount
- 992934e and f22d6c8: the #269 gate witness
- 9c79510: the #332 gate shim
- b786ec1: the #275 git fixtures
- 29b60f9: the L5 trigger
- d41001c, a2ef507, 7d3db24, f511779, c64bdd6: hardening

PRs: #298, #301, #306, #322, #339, #369, #397, #406, #407, #411, #417. None implements an issue or PR service.

Duplicate or superseding issues: none. #434, #277 and #279 depend on #276.

gh call inventory: read from the pinned CPP 86641e8 sources (flow-start-resolve.sh, flow-plan-record.py, auto.md, eli5.md, nit-store-resolve.sh, gh-pr-merge.sh, flow-ci-status.sh).

### Section C - the approved plan
1. `skillc/fixture_service.py` - The controller-owned fixture service: declared issue/PR state for one repository, and an append-only event log written before each reply. A closed gh argv grammar and a jq subset. The controller performs the squash merge through an injected GitRemote. Faults (lost-response, stale-read) are armed by the declaration on the first admitted matching request. finalize() runs the remote-divergence check. A composable op dispatch is isolated per side.
2. `docker/trial/skillc-gh-shim.py` - Stdlib gh stand-in. It forwards argv, cwd and stdin over /run/skillc/trigger.sock, writes back stdout, stderr and exit byte for byte, and exits 125 on any channel failure. No image or profile change.
3. `docs/specs/evaluation-facility/fixture-service.md` - Spec covering the supported semantics, the record schema, the trust boundary, the three-way read, the faults, and the simulator limits, including the detection-only bound on remote integrity.
4. `docs/specs/evaluation-facility/fixture-service-gh-inventory.txt` - The gh calls in pinned CPP 86641e8, with source:line and jq filters.
5. `tests/test_fixture_service.py` - API transition tests: valid transitions, wrong repo, duplicate create, unauthorized transition, forged history, missing coverage, bypass, direct push and force-push divergence, search, faults, and the junk-flood control.
6. `tests/test_fixture_service_channel.py` - Exercises the real DecideReplyChannel and the real shim subprocess with adversarial clients: cross-side op refusal including mixed fields, and observed effects equal to the record.
7. `tests/test_fixture_service_inventory.py` - Every inventory call and every jq filter must parse, or be declared unsupported. Committed negative controls: `gh release create`, and a filter outside the subset.
8. `CHANGELOG.md` - An Unreleased entry.
9. `docs/README.md` - Links the new spec page. This is the approved "spec.md or that directory's index"; docs/README.md is the evaluation-facility index.

Scope: 9 files, about 1,500 to 1,900 lines. Medium-large.

Risks and rulings:
(a) Multiplexing on the one socket is APPROVED, on condition that dispatch is unambiguous and isolated, with a cross-side refusal test.
(b) Detection-only remote integrity is ACCEPTED:
  - divergence must surface as VIOLATED or UNKNOWN, and is never reconciled;
  - direct-push and force-push tests are required;
  - the bound is stated in the spec;
  - a follow-up issue is filed for a controller-routed push, linked from #434.
(c) The grammar is pinned to 86641e8, and the inventory test reports any new call.
(d) The jq subset is refused outside its grammar, never approximated.
(e) No Docker or live run; wiring is #434's.
