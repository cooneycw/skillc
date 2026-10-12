# Flow run record - issue #341

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=1c358b19280b4a519b2a2c6e1076492a -->
## Run 1

- Run-id:            1c358b19280b4a519b2a2c6e1076492a
- Run-start:         450445da5eb83719aa68f0f448f29bda56358ec9

- Issue: #341
- Base SHA: 450445d
- Necessity verdict: Needs reframing
- Approval: granted with conditions
- Approver: orchestrator
- Recorded at: 2026-10-12T14:19:47.549193+00:00

### Section B evidence
Evidence since 2026-10-07T00:57:09Z:
- Main: 450445d. Relevant merged commits: da2d572 / PR #352 (#336), 10ff168 / #342 (#332), 5cf1586 / #340 (#266). They leave one shared exception per live file. New floor files arrived in e43445a / #347 (#343) and 0518cc0 / #349 (#334).
- Other post-filing history inspected: 23bb1ba / #353, eeec8d2 / #351, 8cde2ac / #350, 0051fab / #345, 037fa19 / #344, 450445d / #335. None implements #341. Date-only PR search also returned #337 and #339, whose merge times predate the exact issue timestamp.
- Related/duplicate search inspected #341, #355, #336, #332, #269, #266, #334, #309. #336 is the predecessor, not a superseding fix. #355 repairs test infrastructure and overlaps three files. No superseding #341 implementation is merged.
- Parked 5b06193 is one implementation commit; current main is two commits beyond its base. It edits six files (+443/-167). All 15 _require calls explicitly name a subtype, and the generic pytester sibling/mutation controls are present.
- Read-only execution of the parked classes, _require, and actual mapping yielded: wrong-env failure matches drops-cwd marker=True (_ForwardingPropertyHeld); secret-mount failure matches skill-mount marker=True (_MountEmptinessPropertyHeld). The proposed generic pytester tests would not catch either live mapping error.
- Sibling worktree audit: unpushed 99e8474 for #355 modifies tests/test_gate_overlay_live.py, tests/test_decide_reply_channel_live.py and tests/test_gate_witness_live.py. Other current sibling worktrees have no unpushed commits touching the reviewed paths. No sibling contents were edited.

Floor reconciliation: there are seven tests/*_live.py files now. test_trial_image_build_live.py has no break selector or xfail, so there is no marker to convert. test_trial_image_tools_live.py already uses _UvPropertyHeld for its sole no-uv property; unrelated tools remain plain assertions. test_profile_closure_preflight_live.py separates the preflight verdict from runner reachability, but missing-closure and tampered-closure still share a verdict exception and their outcome logic deserves separate acceptance scrutiny. Proposed scope here audits/tests their actual marker isolation without silently changing #334's behavioral contract; report any consequential closure-test finding to orchestrator before editing that file.


### Section C - the approved plan
1. `tests/test_decide_reply_channel_live.py` - retain parked connectivity/uid/decision subtype split and unconditional checks; reconcile #355's cleanup changes.
2. `tests/test_gate_witness_live.py` - retain concurrent-access, kill-confirmation and primary-unaffected checks with specific subtypes; narrow kill-wrong-pid to kill-confirmation rather than the parked tuple that also credits unrelated primary failure. Both kill modes deliberately leave the gate alive, so sharing that observed invariant is justified; primary-only failures must remain hard failures.
3. `tests/test_gate_overlay_live.py` - refine the parked forwarding group into independently checked output integrity, working-directory and declared-environment properties, alongside channel-failure behavior. Factor observation checks only as needed for no-daemon controls. Checks inspect the same returned output in every mode; never choose the raised exception from BREAK_MODE. Preserve byte-exact whole-output and exit-code conformance, with unrelated mismatches remaining hard failures.
4. `tests/test_profile_install_cold_container_live.py` - refine the parked mount group into independently observed forbidden destinations with property-specific failures, keep unknown mounts a hard failure, and preserve the zero-mount invariant and offline-cache subtype. A secret-only mount must not certify skill-mount, and vice versa. No exception chosen from the active break mode.
5. `tests/test_property_held_xfail_pattern.py` - keep parked pytester controls and add controls using real live-file marker mappings and observation predicates. Demonstrate targeted failure => XFAIL; sibling-property/infra failure => FAILED; intact under a strict break marker => XPASS failure. Mutation-widen actual markers to the shared base and prove those same controls detect the false certification. Cover channel, witness, overlay, cold install, and the two newer files' existing exception boundaries without requiring Docker.
6. `CHANGELOG.md` - integrate the parked hunk, correct its grouped-property claims and distinguish code/mechanics evidence from real-runner evidence still owed.

Scope: six implementation/documentation files, roughly 600-800 changed lines including reuse and tests; exact diff depends on #355. Flow bookkeeping additionally requires docs/flow-runs/issue-341.md, docs/flow-runs/issue-341.as-read.md and a counter-model receipt if the installed helper supports this Codex session. Those are workflow records rather than product scope; include them in the final granted lane as applicable.

Risks and alternative: blindly accepting 5b06193 preserves verified false certification. Merely assigning a different exception by BREAK_MODE would hide it rather than fix it. Use mode-independent predicates and real-mapping negative controls instead. The older five-file criterion needs explicit acknowledgement of the image-build no-op and the now-seven-file audit. Any refusal-vs-xfail issue found in closure preflight is not silently declared delivered by this subtype change. Review/runner coordination is required for #355 and #315. The ordinary host suite may run real Docker tests when a daemon is present; keep targeted analysis no-daemon, and run live modes only on the declared isolated runner.


Approval conditions: reuse parked work; predicates remain mode-independent; no edits to the three #355-owned live files until merge or explicit handoff. Initial implementation covers cold-install and control tests. Full suite and live runner remain serialized. Refs #341 until runner acceptance is demonstrated. Seven-file audit includes image-build with no marker and image-tools with an existing uv-specific marker.

### Approved revision - closure control

Orchestrator expanded the gate after independent confirmation that closure-preflight credited a missed or wrong-reason refusal as XFAIL. No production behavior changes. The healthy predicate remains acceptance in every mode; precise path/symptom verification is a hard failure before a targeted refusal can receive credit. Actual-oracle and mutation controls are required. This resolves a seven-file-floor acceptance blocker.

7. `tests/test_profile_closure_preflight_live.py` - repair the inverted preflight oracle and validate refusal identity before crediting XFAIL; retain independent runner failure.
