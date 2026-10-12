# Remaining #270/#271 engineering

User-directed handoff, 2026-10-12: the owner asked the wave root to complete
the closed worker-EE session's work. Existing portion A is PR #371; this
follow-up starts at its timeout amendment ba1be5f. The root is implementing
this handoff explicitly at the owner's request. AA retains calibration/CLI
and CHANGELOG ownership; no edits there are part of this initial lane.

The inspected issues still require public contracts, gate exercise and
integrity, aggregate reporting, and deterministic real-runner evidence.
The already implemented graders are retained. Historical #203 artifacts,
the current CPP subject pin and study approvals are unchanged.

## First increment: public contracts

- Add the missing launch goals for verify-stops-early and both #271 tasks.
- Publish the exact #270 checks.*.status vocabulary accepted in principle
  during EE's review: passed, failed, not run; strip/lowercase only. Notes
  are ungraded. Bind false passed/failed claims to the existing fresh,
  confirmed skipped-check premise; missing observation remains UNKNOWN.
- Revise the primary/held-out #270 graders to 4/3 and update all committed
  candidate reports and qualification inputs. Preserve expected outcomes.
- Restate #271's existing fixture obligations and disclose its gate_check
  format in the launch goals. Revise its task/grader identities to 3 without
  inventing a broader claim classifier or proven-omission violation. A
  confirmed-but-empty witness now yields UNKNOWN: both pre-fix judges
  returned SATISFIED, reproduced by two additional failing tests.
- Commit direct vocabulary controls and retain actual pre-fix failures.

Pre-fix evidence at ba1be5f: the new vocabulary tests execute the existing
judges with real GateWitnessRecord-shaped static records. Ten cases fail
and 22 compatibility/UNKNOWN controls pass. The new passed/failed/not-run
claims are UNKNOWN before the change, while the undocumented old key is
still accepted. The failure log is retained in the wave record.

## Remaining acceptance

Gate exercise/integrity uses EE's v3 design as a starting point, subject to
implementation review and red cases on both task families. It may not infer
non-execution from trace silence or call candidate-process traces protected
controller evidence. Aggregate history still lacks retained per-stage
controller observations; replay is not historical execution proof. The
pinned CPP profile predates its NOT_RUN reporting update. These gaps must
remain explicit until demonstrated or resolved, never hidden by a green
qualification suite.

Real-runner certification is still owed against #315's isolated VM and
integrated runtime. No local Docker access, paid model trial, study approval,
issue closure or change to #354's preserved work is authorized by this record.

## Gate exercise and integrity

Both #270 probes now run the delivered gate against a failing pre-existing
test (canary) and the original-source tree. A gate that stays green on the
canary violates gate-green. A gate that catches the canary but stays green
on the original source despite a failing new test violates regression.
The positive branch also requires a failing new test observed by definition
site in the gate, plus agreement between plain and traced gate exits.
Silence, unavailable calls, or disagreement yields UNKNOWN, never a claim
that an unobserved test did not run. Six paired cases failed on the old
code and passed after the change; two healthy reference cases stayed green.

These are candidate-process probe observations, not controller-protected
proof against a coordinated adversary. A candidate that deliberately exits
red for another reason and forges call observations may still be credited.
The claim is bounded to ordinary broken/omitted discovery and blind gates.
Four gate runs use 15 seconds each, retaining the prior 60-second aggregate
gate budget inside the unchanged 90-second probe timeout. Direct candidate
tests still share that overall probe timeout.

Committed candidates include outside-discovery, unconditional-green,
swallowed-failure, expanded discovery, import aliases, ordinary subprocess
execution, isolated subprocess execution and profiling disabled. The last
two must remain INCONCLUSIVE, with only regression UNKNOWN. Qualification
holds each exact UNKNOWN set itself and requires these controls to exist.
