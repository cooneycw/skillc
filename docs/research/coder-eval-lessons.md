# Coder Eval lessons and contract map

- Date: 2026-09-26
- Issue: [#6](https://github.com/cooneycw/skillc/issues/6)
- Decision: [ADR 0003](../decisions/0003-no-external-evaluation-runtime.md) - no
  runtime dependency; Coder Eval is a design reference only
- Source: [UiPath/coder_eval at d960de1](https://github.com/UiPath/coder_eval/tree/d960de1c433a1b050d2509f04d94a60e3cabaaf0),
  version 0.12.4, Apache-2.0
- Basis: the [September 20 handoff](coder-eval-skillc-contract-handoff-2026-09-20.md),
  with its line references re-checked against the pinned source on 2026-09-26

## What this document is

skillc will not run, import or wrap Coder Eval. It still read that project
closely, and much of what it read answers questions skillc now has to answer
itself. This document keeps those answers, and the traps, so the reading is not
lost when the dependency question closed.

**Everything below is static inspection.** No Coder Eval code was executed and no
attack was attempted. "Does X" means "the pinned source is written to do X", not
"X was observed". Paths are relative to `src/coder_eval/` at `d960de1`.

Borrowing an idea listed here is allowed and expected. Name this document (or the
upstream file) in the design note that introduces it; do not copy source.

## Contract map

One row per contract in [interfaces.md](../specs/evaluation-facility/interfaces.md)
and [records.md](../specs/evaluation-facility/records.md). "skillc builds" is the
work that exists whatever the backend decision; ADR 0003 means none of it is
delegated.

| skillc contract | What Coder Eval does (pinned source) | What skillc builds | Owner |
|---|---|---|---|
| Installation receipt | Claude adapter passes `plugins` and `setting_sources` to the SDK (`agents/claude_code_agent.py:1185-1208`); Codex adapter symlinks discovered `SKILL.md` dirs into `.agents/skills`, warning rather than failing on zero skills (`agents/codex_agent.py:1090-1180`). No receipt: no content digests, dependency closure or discovery canary | Native materialization, receipt with resolved paths and digests, discovery canary, baseline absence proof; refuse an empty surface | [#7](https://github.com/cooneycw/skillc/issues/7) |
| Trial ledger | Run/variant/replicate layout on disk and a strict dispatch context (`models/container_context.py`, `extra="forbid"`, strict bool/int). No controller-held expected inventory or per-attempt nonce | Controller-issued attempt IDs, expected population, reruns as new IDs, lifecycle and cleanup observations | [#8](https://github.com/cooneycw/skillc/issues/8) |
| Artifact and observation bundle | Results written by the in-container orchestrator to a writable bind mount (`isolation/docker_runner.py:1303-1306`); events framed on container stdout with a sentinel (`streaming/wire.py:39`); collector ignores nested-thread events (`streaming/collector.py`) | Controller-owned capture after the subject stops: path/type/size/digest manifest, raw events with declared coverage, capture failures explicit | [#8](https://github.com/cooneycw/skillc/issues/8) |
| Verified result | Grading runs inside the same container as the agent; host reads `task.json` and checks the echoed contract for equality (`isolation/docker_runner.py:843-913`). Detached regrade exists (`orchestration/regrade.py`) | Separate verifier on a disposable copy with trusted grader inputs; status derived by `skillc.records.derive_status`, never copied | [#9](https://github.com/cooneycw/skillc/issues/9) |
| Lifecycle: stop and clean up | Best-effort container kill on cancellation (`isolation/docker_runner.py:798`); synthetic ERROR record when `task.json` is missing (`isolation/docker_runner.py:967`) | Confirmed termination, cleanup of owned resources only, repeated-cleanup safety | [#10](https://github.com/cooneycw/skillc/issues/10) |
| Reporting semantics | `FinalStatus` separates ERROR, BUILD_FAILED, TIMEOUT and NOT_GRADED (`models/enums.py:7-21`); unavailable cost is representable | PASS/FAIL/UNAVAILABLE/INCONCLUSIVE/NOT_RUN derived from criteria, per [protocol.md](../specs/evaluation-facility/protocol.md) | [#9](https://github.com/cooneycw/skillc/issues/9), [#12](https://github.com/cooneycw/skillc/issues/12) |

## Lessons worth taking as ideas

1. **Reject unknown fields at the dispatch boundary.** The container context uses
   `extra="forbid"` and strict booleans/integers, with the comment that a bool is
   an int and `True` would land in replicate `01/` (`models/container_context.py:21-25`).
   skillc's ledger and receipt readers should refuse unknown and loosely typed
   identity fields the same way.
2. **Separate execute from grade.** Running and grading are distinct operations,
   and a stored run can be regraded later (`orchestration/regrade.py`). skillc's
   verifier (#9) needs the same split, with the grade in a different environment.
3. **Keep "not graded" distinct from pass and fail.** `NOT_GRADED`, `ERROR`,
   `BUILD_FAILED` and `TIMEOUT` are separate statuses (`models/enums.py:7-21`), and
   missing cost is not zero. This matches skillc's INCONCLUSIVE/UNAVAILABLE rule.
4. **Digest the answer key before grading, and check it again.** The reference is
   hashed when staged and re-hashed before grading, failing on a mismatch
   (`orchestrator.py:1396`, `orchestrator.py:1429`). #9 should do the same for
   grader and held-out inputs.
5. **Atomic writes that refuse symlinks.** `write_text_atomic` opens a unique temp
   file with `O_CREAT | O_EXCL | O_NOFOLLOW` then renames (`path_utils.py:54-76`).
   Controller-written records in #8 should be written this way.
6. **Refuse embedded commands from a stored record.** Regrade will not execute
   commands carried in a recorded config without explicit opt-in
   (`orchestration/regrade.py:309-347`), and checks that the recorded workspace
   stays contained, including symlink escapes (`orchestration/regrade.py:425-455`).
   A stored bundle is untrusted input to the verifier.
7. **A missing result is a record, not a gap.** When the container returns no
   `task.json`, the host writes a synthetic ERROR record
   (`isolation/docker_runner.py:967`). #8's accounting should give every planned
   attempt a record, whatever happened to it.
8. **Pin the agent binary.** The Dockerfile pins the Claude Code CLI version
   because the binary drives results as much as the model does
   (`docker/Dockerfile`, `CLAUDE_CODE_VERSION`). #12's manifest should record it.

## Pitfalls to avoid

1. **Trusting the record the subject's container wrote.** The result that decides
   the status is written by code running in the same container as the agent, to a
   writable mount (`isolation/docker_runner.py:1303-1306`). A correctly shaped
   `task.json` can be untrue. skillc derives status outside the subject's reach.
2. **Reading an echo as proof.** The host checks that the container echoed back
   the contract it was sent (`isolation/docker_runner.py:878-913`). That detects a
   mismatched image; it does not show the workload obeyed the contract. A forger
   can echo too.
3. **Reading framing as authentication.** The stdout sentinel
   `\x1ecoder-eval-stream\x1e:` (`streaming/wire.py:39`) avoids collisions with
   ordinary output. Anything that can write to stdout can write it.
4. **Warn-and-proceed on missing evidence.** A regrade with no recorded
   reference digest logs a warning and grades anyway
   (`orchestration/regrade.py:485-493`). skillc refuses: missing required
   evidence is never a pass.
5. **Full access by default.** The Codex adapter always sets
   `Sandbox.full_access`; the comment says the Docker driver is the only real
   boundary (`agents/codex_agent.py:1381-1387`). Any agent skillc launches runs
   inside a container, never on the host.
6. **A grader with the subject's powers.** The default agent judge runs with
   Bash and `bypassPermissions` (`models/criteria.py:56-70`). A grader that can
   run subject-controlled code with grader credentials is not independent.
7. **Counting a mention as an invocation.** `skill_triggered` credits an explicit
   Skill call or a `skills/<name>/` substring in tool parameters
   (`criteria/skill_triggered.py:42-62`). That is a weak signal; it does not show
   the skill was read or followed. #26 must not use it as evidence of selection.
8. **Warning on an empty install.** Zero linked skills warns rather than fails
   (`agents/codex_agent.py:1090-1180`). skillc's rule is that an empty population
   never renders as clean.

## What moved where

#6 originally required running probes against Coder Eval. With no dependency,
those requirements apply to skillc's own machinery instead:

| #6 acceptance item | Now owned by |
|---|---|
| Map each required contract to code, adapter work or a blocker | This document (contract map above) |
| Deterministic/fake-client Docker probes: failure accounting, cancellation, candidate export, install hooks | [#10](https://github.com/cooneycw/skillc/issues/10) against skillc's runner; install hooks with [#7](https://github.com/cooneycw/skillc/issues/7) |
| Grading outside the subject's authority | [#9](https://github.com/cooneycw/skillc/issues/9) |
| Forged/stale success records and missing digests refused; echo and framing are not authentication | [#9](https://github.com/cooneycw/skillc/issues/9) (verifier), [#8](https://github.com/cooneycw/skillc/issues/8) (capture) |
| Adopt/wrap/reject with evidence, dependency boundary, maintenance cost | [ADR 0003](../decisions/0003-no-external-evaluation-runtime.md) |
| Bounded investigation; Codex full access never on the host | Satisfied: nothing was run |
