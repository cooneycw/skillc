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

THREE OF FOUR REASONS ARE IMPLEMENTED, each only once the field mapping was
confirmed against actual producer code, never guessed:
- `exit-code-mismatch` (`reconcile_gate_claim`): `checks[].exit_code`
  against the gate-witness's last run.
- `outcome-disagreement` (`reconcile_gate_claim`): CPP's `checks[].status
  == "not-run"` while the witness shows a COMPLETE run of that gate in
  this attempt - reachable without any attempt/run-count mapping
  (orchestrator review, #272). The reverse (CPP claims it ran, witness
  shows no confirmed execution) is `unknown`, never a claim this module can
  contradict - only a controller-CONFIRMED observation can contradict a
  claim, never silence standing in for one.
- `stale-identity` (`reconcile_helper_identity`, record-level, not
  per-gate): `observed.helper.module_sha256` against the SAME attempt's
  `installation-receipt.installed` digests - both SHA-256 over raw file
  bytes (confirmed by reading `lib/cicd/evidence.py::_sha256` and
  `skillc/materialize.py::sha256_file`/`sha256_bytes`), differing only in
  a `sha256:` prefix. Its `witness_ref` cites THIS attempt's own
  installation-receipt (by `subject.digest`) rather than a gate-witness
  artifact - `skillc/records.py` now accepts that citation for
  `stale-identity` specifically, and refuses a receipt citation for a gate
  reason or a gate-witness citation for `stale-identity` (orchestrator
  review, #272 - closing a structural gap found while first building this).

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
    if claim.status == "not-run" and witness.coverage == "complete":
        # Reachable without any attempt/run-count mapping (orchestrator
        # review, #272): CPP's own record says this gate never ran, while
        # the controller confirms a COMPLETE run of it in this attempt.
        # The reverse - CPP claims it ran, witness shows not-observed -
        # stays `witness-did-not-confirm-execution` (above), never this:
        # only the controller's own confirmed observation can contradict a
        # claim, never silence standing in for one.
        return GateReconciliation("contradicting", "outcome-disagreement", witness_artifact)
    if claim.attempt != witness.run_count:
        return GateReconciliation("unknown", "run-count-disagreement", None)
    if claim.status not in CPP_SETTLED_STATUSES or claim.claimed_exit_code is None:
        return GateReconciliation("unknown", "usage-record-claim-not-settled", None)
    if witness.exit_code is None:
        return GateReconciliation("unknown", "witness-exit-code-not-settled", None)
    if claim.claimed_exit_code != witness.exit_code:
        return GateReconciliation("contradicting", "exit-code-mismatch", witness_artifact)
    return GateReconciliation("matched", None, witness_artifact)


def _normalize_hex_digest(value: str) -> str:
    """CPP's `helper.module_sha256` values are bare hex
    (`lib/cicd/evidence.py::_sha256`, `hashlib.sha256(data).hexdigest()`).
    skillc's `installation-receipt.installed[].digest` values carry a
    `sha256:` prefix (`skillc/materialize.py::sha256_bytes`). Both hash the
    SAME algorithm over the SAME byte population (raw file content, no path
    or mode mixed in) - confirmed by reading both implementations, not
    assumed - so this is a format normalization, never an invented mapping
    the way a tree-identity comparison would be."""
    prefix = "sha256:"
    return value.removeprefix(prefix)


def reconcile_helper_identity(
    claimed_module_sha256: dict[str, str],
    installed_digests: dict[str, str],
    receipt_identity: WitnessRef | None = None,
) -> GateReconciliation:
    """RECORD-level, not per-gate: CPP's `observed.helper.module_sha256` is
    one map for the whole usage record, compared against the SAME attempt's
    `installation-receipt.installed` digests - "stale-identity", "the usage
    record's own bound ... identity differs from this trial's planned one"
    (R9, records.md).

    `receipt_identity` is this attempt's own installation-receipt citation -
    `WitnessRef(ref=..., digest=<receipt's subject.digest>)` - CLOSING the
    structural gap found while first building this (orchestrator review,
    #272): `skill_evidence()`/`_skill_evidence_binding` now accept a
    `stale-identity` `witness_ref` that resolves to THIS attempt's own
    installation-receipt (by `subject.digest`), never a gate-witness
    artifact - the two are different authorities for different reasons, and
    a citation of the wrong kind for its own reason is refused explicitly.
    When `contradicting` is returned here, `receipt_identity` is passed
    straight through as the verdict's own `witness_ref` - this function
    never invents one, only cites what the caller already resolved.

    A path present on only one side (CPP reports a module skillc never
    installed, or vice versa) is `unknown`, not a guessed verdict either
    way - only a path BOTH sides name, with digests that disagree, is a
    real contradiction, and only then is a witness_ref even relevant.

    A MIX of comparable and one-sided CLAIMED paths is also `unknown`, not
    `matched` (Codex review, #272): claiming `{a: X, b: Y}` against an
    installed set that only names `a` used to report `matched` once `a`
    agreed, silently treating `b` - a helper CPP's execution touched that
    skillc has no installed record of at all - as outside the comparison.
    `matched` is reserved for every CLAIMED path being comparable and
    agreeing; anything less is an incomplete comparison, not a confirmed
    one. (Extra `installed_digests` paths CPP never claims are a different
    question - this function iterates `claimed_module_sha256` by design,
    since CPP's claim set is the population this comparison verifies, and
    an installed helper CPP never touched has nothing here to agree or
    disagree with.)
    """
    disagreeing: list[str] = []
    comparable = 0
    for path, claimed_digest in claimed_module_sha256.items():
        installed_digest = installed_digests.get(path)
        if installed_digest is None or claimed_digest is None:
            continue
        comparable += 1
        if _normalize_hex_digest(claimed_digest) != _normalize_hex_digest(installed_digest):
            disagreeing.append(path)
    if comparable == 0:
        return GateReconciliation("unknown", "no-comparable-helper-path", None)
    if disagreeing:
        if receipt_identity is None:
            return GateReconciliation("unknown", "no-installation-receipt-to-cite", None)
        return GateReconciliation("contradicting", "stale-identity", receipt_identity)
    if comparable != len(claimed_module_sha256):
        return GateReconciliation("unknown", "partial-helper-coverage", None)
    return GateReconciliation("matched", None, None)
