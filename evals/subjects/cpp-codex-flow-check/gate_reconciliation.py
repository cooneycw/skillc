"""Subject-scoped reconciliation of a CPP usage-record gate claim against the
controller's own gate-witness facts (issue #269, skillc #272 acceptance item 5).

`skillc/records.py`'s core never decodes `cpp.execution-evidence/v1`
(records.md Q4) - it checks only a digest and a declared source. Deciding
`matched`/`contradicting` requires reading what a usage record actually
CLAIMS about a gate, which is exactly the boundary that rule protects. So
this comparison lives here, outside `skillc/`, where the genericity guard
(`tests/test_materialize.py`) does not reach - the same placement
`gate_path.py` already uses for the same reason.

`unmatched`'s own two reasons (`duplicate-invocation`, `no-correlating-
attempt`) are NOT this module's concern: those are skillc-side facts
(digest/attempt-id equality) already decided generically in
`skillc/records.py`. This module decides only `matched` and `contradicting`.

FIELD NAMES PINNED FROM `cooneycw/claude-power-pack` at
`5e1de6d848eb29c2b926f2fdf79e8aa375c12c43` (orchestrator review, #272; the
cross-group reviewer's mailbox was unreachable, so the FROZEN spec and its
producer are read directly rather than waited on):
- `.specify/specs/per-skill-audit/spec.md` - R1-R15, the `cpp.execution-
  evidence/v1` field inventory.
- `lib/cicd/evidence.py::check_entry` - each `observed.checks[]` entry is
  `{id, gate, status, exit_code, attempt, max_attempts, attempted_at,
  completed_at, executed_in_this_invocation, carried_from_previous_run,
  population, reason, evidence}`. EXACTLY ONE entry per gate, holding the
  FINAL state (relayed fact, confirmed against the real sample below) -
  never a list of runs. `build_record()` nests `checks` under `observed`.
- `scripts/execution-evidence-verify.py` - confirms the reader's own field
  access, no additional fields relevant here.
- The committed sample, `docs/measurements/execution-evidence/
  cbf9931314ed45d2927fa5e150daa9d2.json` (sha256 `8dd12170e425d4d3c4211a0
  f4d15934bfaaff56a37047605bee89ec90d912c40`): confirms `checks[]` shape
  directly, but shows NO per-check `carried_from_previous_run` key at all -
  only a RECORD-level `observed.runner.carried_from_previous_run` (a list,
  empty in this sample). This DISAGREES with `check_entry()`'s own dict
  construction, which writes a per-check boolean of that name. Relayed to
  the orchestrator as a found disagreement, not resolved by this module -
  this module reads whatever boolean a caller supplies for
  `GateClaim.carried_from_previous_run`, agnostic to which JSON shape it
  came from.
If CPP amends the frozen spec, this pin needs re-reading before trusting it
further; until then the frozen spec and its producer win over anything said
elsewhere (orchestrator ruling, #272).

A CARRIED-FORWARD CHECK IS ALWAYS UNKNOWN, NEVER CONTRADICTING (relayed
fact, #272): a resumed run carries `carried_from_previous_run=true` and
`executed_in_this_invocation=false`. THIS attempt's gate-witness cannot
have observed a run from a PREVIOUS invocation, so no witness comparison
can possibly apply - the claim is `unknown` before exit codes are even
read.

WHICH WITNESS RUN TO COMPARE - PROPOSED, NOT YET CONFIRMED (relayed
question, #272): CPP's `checks[]` entry is the FINAL state of a gate
WITHIN ONE INVOCATION (its own `attempt` counts CPP-internal retries, not
necessarily the same thing as how many times the subject asked the
controller to `run_gate`). This module compares against the gate-witness's
OWN LAST recorded run (`GateWitnessFact.exit_code`, already documented as
the last run's value) rather than trying to match CPP's `attempt` number
to a specific witness run index - the two attempt-counters are not proven
to count the same thing, and matching them positionally risks comparing
the wrong pair of runs with high confidence. If the run COUNTS disagree
(`GateClaim.attempt` vs `GateWitnessFact.run_count`), this module reports
`unknown` (reason `run-count-disagreement`), never `contradicting`: a count
mismatch signals the two systems' accounting is not comparable for this
attempt, not that any one claim is false, and `run-count-mismatch` is not
in `CONTRADICTING_REASONS` - inventing a fifth reason without approval
would repeat the exact mistake `gate-not-executed` was removed for.

ONLY `exit-code-mismatch` IS IMPLEMENTED. `outcome-disagreement` and
`stale-identity` are real, named reasons in `skillc/records.py`'s closed
vocabulary, but mapping them precisely onto CPP's fields (which `outcome`/
`qualifications` state, or which `observed.repository`/`tree_at_start`
field constitutes "bound subject/client identity") is an interpretation
this module does not make without the orchestrator confirming it - an
invented mapping is exactly what records.md's Q4 boundary and the
orchestrator's caution 2 (#272) warn against for `tree-mismatch`, and the
same discipline applies here: a CONFIDENT field-for-field match
(`checks[].exit_code`, verified against the actual producer code, not
prose) is implemented; an UNCERTAIN one is left `unknown`, not guessed.

`tree-mismatch` IS UNREACHABLE FOR THIS SUBJECT, confirmed, not merely
unconfigured. CPP's `tree_signature` (`lib/cicd/state.py::
compute_tree_signature`) is a scratch-git-index `git write-tree` content
hash, RECORD-level (one pair, `tree_at_start`/`tree_at_end`, not per-gate).
skillc's own `gate_witness.py` tree digest (`skillc/materialize.py::
tree_digest`) is `sha256` over `(relative_path, executable_bit,
file_sha256)` tuples, PER-GATE-RUN. Two independently authored algorithms,
at two different granularities, with no documented equivalence anywhere in
either repository - never bit-comparable by construction. This module never
produces `tree-mismatch`; `GateClaim` below carries no tree-identity field
at all, because a field this module cannot compare should not exist on its
input type pretending it might be used.
"""

from __future__ import annotations

from dataclasses import dataclass

#: The closed reason vocabulary for `reconciliation: "contradicting"`
#: (`skillc/records.py`'s `SKILL_EVIDENCE_CONTRADICTING_REASONS`, as merged -
#: `gate-not-executed` was proposed and REMOVED; see module docstring).
CONTRADICTING_REASONS = ("outcome-disagreement", "stale-identity", "exit-code-mismatch", "tree-mismatch")

#: `gate-witness` (#269) coverage values under which the witness did NOT
#: confirm a real process started - a claim cannot be "contradicted" by one
#: of these, only reported as unknown (orchestrator review, #272: #301
#: removed `gate-not-executed` because silence cannot prove non-execution).
NOT_CONFIRMED_EXECUTION_COVERAGE = ("not-observed", "launch-failed", "channel-unavailable")

#: CPP `observed.checks[].status` values under which `exit_code` is a real,
#: settled value rather than `None` (`lib/cicd/evidence.py::check_entry`,
#: pinned `b8825bd`: "None, not 0, when the command never ran").
CPP_SETTLED_STATUSES = ("success", "failed", "subsumed")


@dataclass(frozen=True)
class GateClaim:
    """One `observed.checks[]` entry from a CPP usage record, for the gate
    this reconciliation is about (`id` matched against the gate-witness's
    own gate name). Field names pinned to `lib/cicd/evidence.py::
    check_entry` at `b8825bd` (module docstring) - not a paraphrase.

    No tree-identity field: CPP's tree signature is record-level, not
    per-gate, and not comparable to skillc's own tree digest regardless
    (module docstring) - carrying a field this module can never compare
    would invite a future caller to populate it as if it mattered.
    """

    gate: str
    status: str
    claimed_exit_code: int | None
    attempt: int
    carried_from_previous_run: bool


@dataclass(frozen=True)
class GateWitnessFact:
    """The controller-observed facts for one gate, read from a `gate-witness`
    record's own `gates[gate]` entry (#269, `skillc/gate_witness.py`) -
    never anything the subject reported. `exit_code` is the LAST run's
    value when `coverage` is `complete` or `interrupted`; `None` otherwise.
    `run_count` is `len(gates[gate].runs)` - compared against the claim's
    own `attempt` only to detect accounting disagreement (module docstring),
    never to pick which run `exit_code` came from."""

    coverage: str
    exit_code: int | None
    run_count: int


@dataclass(frozen=True)
class WitnessRef:
    """The `{ref, digest}` citation `skill-evidence.external_evidence.
    witness_ref` requires for `contradicting` (#269's own closed check) -
    identifies the captured `gate-witness` artifact this verdict rests on."""

    ref: str
    digest: str


@dataclass(frozen=True)
class GateReconciliation:
    """`state` is `"matched"`, `"contradicting"`, or `"unknown"` - NOT the
    same closed vocabulary `skill-evidence.external_evidence.reconciliation`
    uses (`absent`/`unmatched`/`matched`/`contradicting`, no `unknown`
    member). `"unknown"` here means this function could not decide either
    way; a caller writing a skill-evidence record from it must not spell
    that as `matched` or `contradicting`, and `absent`/`unmatched` are
    decided elsewhere (skillc core), never by this module."""

    state: str
    reason: str | None
    witness_ref: WitnessRef | None


def reconcile_gate_claim(
    claim: GateClaim | None,
    witness: GateWitnessFact | None,
    witness_artifact: WitnessRef | None,
) -> GateReconciliation:
    """The one entry point. Refuses to decide `matched`/`contradicting`
    without BOTH a claim and a confirmed-execution witness - every other
    input shape is `"unknown"` with a named reason, never a guess.

    Implements `exit-code-mismatch` only (module docstring). A claim whose
    own CPP status never settled (not in `CPP_SETTLED_STATUSES`) carries no
    comparable exit code either, so it is `"unknown"`, not `"matched"` by
    a vacuous absence of disagreement. A carried-forward claim, or a claim
    whose run count disagrees with the witness's own, is `"unknown"` before
    any exit code is compared (module docstring - both relayed facts).
    """
    if witness is None or witness_artifact is None:
        return GateReconciliation("unknown", "no-controller-witness", None)
    if claim is None:
        return GateReconciliation("unknown", "no-usage-record-claim", None)
    if claim.carried_from_previous_run:
        return GateReconciliation("unknown", "claim-carried-from-previous-invocation", None)
    if witness.coverage in NOT_CONFIRMED_EXECUTION_COVERAGE:
        return GateReconciliation("unknown", "witness-did-not-confirm-execution", None)
    if claim.attempt != witness.run_count:
        return GateReconciliation("unknown", "run-count-disagreement", None)
    if claim.status not in CPP_SETTLED_STATUSES or claim.claimed_exit_code is None:
        return GateReconciliation("unknown", "usage-record-claim-not-settled", None)
    if witness.exit_code is None:
        return GateReconciliation("unknown", "witness-exit-code-not-settled", None)
    if claim.claimed_exit_code != witness.exit_code:
        return GateReconciliation("contradicting", "exit-code-mismatch", witness_artifact)
    return GateReconciliation("matched", None, witness_artifact)
