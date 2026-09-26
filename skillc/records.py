"""Evaluation records as checkable objects.

`docs/specs/evaluation-facility/interfaces.md` already names four contracts, their
producers and their independent checks, and already fixes the vocabularies:
criteria report SATISFIED / VIOLATED / UNKNOWN, and the assembler reports
PASS / FAIL / UNAVAILABLE / INCONCLUSIVE / NOT_RUN. This module does not invent
those. It gives all four rows an executable form - the installation receipt, the
controller's trial ledger, the artifact and observation manifest, and the
per-criterion verified result - so something can refuse a malformed one.

TWO SUBJECTS. Most rules read ONE record. A few facts only exist BETWEEN records -
that a receipt belongs to the attempt the ledger planned, that no planned attempt
went missing, that a regrade's original was not erased - so those rules read a
BUNDLE: one directory holding a trial ledger and the records bound to it. A record
outside any bundle is checked alone, and `skillc check-records` says so rather than
letting "not bound to anything" read as "bound correctly".

WHAT VALIDATION ESTABLISHES, AND WHAT IT DOES NOT. A record that passes here is
WELL FORMED AND INTERNALLY CONSISTENT, and a bundle that passes is CONSISTENT WITH
ITS OWN LEDGER. Neither is true because of that. interfaces.md says it plainly -
"Structure checks establish that fields are well formed and consistent" - and
PLAN.md says "A valid JSON record, hash or echoed config alone does not
authenticate success." In particular `producer` is a DECLARED field: it catches a
subject-authored verdict that says where it came from, and a record routed to the
wrong producer, but a forger can write any role. Authenticating the producer
belongs to the trusted controller host (#8, #9), not to this module. Every verdict
this module emits names what it examined, including the green ones.

Stdlib only: this has to run in a slim CI image with no network (AGENTS.md).
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

#: The envelope versions this build reads - an EXACT set, not a ceiling. interfaces.md
#: makes incompatible versions an explicit validation failure, and "older" is as
#: incompatible as "newer": version 1 predates producer authority and ledger
#: binding, so a v1 record lacks exactly the fields the v2 rules exist to check.
SUPPORTED_VERSIONS = (2,)

INSTALLATION_RECEIPT = "installation-receipt"
TRIAL_LEDGER = "trial-ledger"
ARTIFACT_MANIFEST = "artifact-manifest"
VERIFIED_RESULT = "verified-result"
#: Additive in version 2 (#8): what happened to ONE attempt, written by the
#: controller. The ledger is immutable once dispatched, so lifecycle, stop reason
#: and cleanup cannot live in it; and a result cannot say "INCONCLUSIVE, nothing
#: was captured", because a graded result must cite what it graded.
ATTEMPT_LIFECYCLE = "attempt-lifecycle"
KINDS = (INSTALLATION_RECEIPT, TRIAL_LEDGER, ARTIFACT_MANIFEST, VERIFIED_RESULT, ATTEMPT_LIFECYCLE)

#: Records that belong to ONE attempt. The ledger is not one of them: it issues
#: the attempt identifiers the others cite.
ATTEMPT_BOUND = (INSTALLATION_RECEIPT, ARTIFACT_MANIFEST, VERIFIED_RESULT, ATTEMPT_LIFECYCLE)

#: The one role allowed to produce each kind, from interfaces.md's producer column.
#: The subject adapter writes the receipt, and the controller must have checked it.
AUTHORIZED_PRODUCER = {
    INSTALLATION_RECEIPT: "subject-adapter",
    TRIAL_LEDGER: "controller",
    ARTIFACT_MANIFEST: "controller",
    VERIFIED_RESULT: "assembler",
    ATTEMPT_LIFECYCLE: "controller",
}
RECEIPT_CHECKER = "controller"

#: Fixed by interfaces.md, not chosen here.
CRITERION_OUTCOMES = ("SATISFIED", "VIOLATED", "UNKNOWN")
PROTOCOL_STATUSES = ("PASS", "FAIL", "UNAVAILABLE", "INCONCLUSIVE", "NOT_RUN")
#: Run states a record may DECLARE; the rest of the statuses are DERIVED and may
#: never be declared, which is what the forged-verdict rule exists to enforce.
DECLARABLE_RUN_STATES = ("UNAVAILABLE", "NOT_RUN")

#: interfaces.md: "externally observed process events, client reports and
#: model-authored assertions differ."
OBSERVATION_ORIGINS = ("observed", "client-reported", "model-asserted")
#: "Record unsupported or incomplete event coverage explicitly."
OBSERVATION_COVERAGE = ("complete", "partial", "unsupported")
#: The initial observation requirement. Every manifest declares its coverage of
#: these streams, even when that coverage is `unsupported`: silence about a stream
#: must never read as a stream that saw nothing.
REQUIRED_OBSERVATIONS = ("client-events", "process-lifecycle")

#: What the controller concluded about one attempt. Only `captured` hands the
#: attempt to grading; the other three are explicit non-results, each with a reason,
#: and none of them may be dropped (EF-07).
DISPOSITIONS = ("captured", "not-run", "unavailable", "inconclusive")
#: Why the subject stopped. A `not-run` attempt is `never-started`; so may be an
#: `unavailable` one, whose dependency failed before dispatch.
STOP_REASONS = (
    "exited", "timeout", "budget-exhausted", "operator-cancelled", "launch-failed",
    "never-started", "unobserved",
)
#: Stop reasons after which nothing ran long enough to leave output to capture.
NOTHING_RAN = ("launch-failed", "never-started")
#: Lifecycle events, in the vocabulary the controller writes.
LIFECYCLE_EVENTS = (
    "planned", "dispatched", "started", "stop-requested", "stopped", "stop-confirmed",
    "stop-unconfirmed", "captured", "capture-failed", "cleaned", "not-run", "unavailable",
)
CLEANUP_STATUSES = ("removed", "already-absent", "not-needed", "partial", "refused-not-owned")
#: A disposition that is not `captured`, and the run state a result for it must
#: declare when one exists. `inconclusive` has none: v2 cannot declare it, and a
#: graded result for an attempt nobody captured is a disagreement.
RUN_STATE_FOR = {"not-run": "NOT_RUN", "unavailable": "UNAVAILABLE"}

#: A well-formed identifier: no whitespace, no path separators, bounded length.
#: IDs end up in file names and log lines; `att 1/../x` must not be one. Always
#: `fullmatch`: `$` alone also matches before a trailing newline.
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")

WHAT_WAS_EXAMINED = (
    "structure and internal consistency only; nothing here establishes that the "
    "result is true or that a declared producer is authentic"
)


@dataclass
class Record:
    """One evaluation record file and the fields it carries."""

    path: Path
    data: dict[str, object] = field(default_factory=dict)
    parse_error: str | None = None

    @property
    def kind(self) -> str:
        value = self.data.get("kind")
        return value if isinstance(value, str) else ""

    @property
    def attempt_id(self) -> str:
        value = self.data.get("attempt_id")
        return value if isinstance(value, str) else ""

    @property
    def trial_id(self) -> str:
        value = self.data.get("trial_id")
        return value if isinstance(value, str) else ""


@dataclass
class Bundle:
    """One directory: a trial ledger and the records bound to it."""

    path: Path
    records: list[Record]

    @property
    def parse_error(self) -> str | None:
        broken = [r for r in self.records if r.parse_error is not None]
        return f"{broken[0].path.name}: {broken[0].parse_error}" if broken else None

    def of_kind(self, kind: str) -> list[Record]:
        return [r for r in self.records if r.kind == kind]


def load(path: Path) -> Record:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return Record(path=path, parse_error=str(exc))
    if not isinstance(raw, dict):
        return Record(path=path, parse_error="top-level value is not an object")
    return Record(path=path, data=raw)


def discover(root: Path) -> list[Record]:
    """Every `*.json` under `root`, in a stable order."""
    return [load(p) for p in sorted(root.rglob("*.json"))]


def discover_bundles(root: Path) -> list[Bundle]:
    """Every directory under `root` (itself included) that directly holds a ledger.

    A bundle is the directory, not the ledger file: its records are the `*.json`
    files directly inside it. One definition serves both `check-records` and
    `selftest`, so a control cannot be proven under a looser notion of "bundle"
    than the one real evidence is checked under.
    """
    if not root.is_dir():
        return []
    directories = [root, *sorted(p for p in root.rglob("*") if p.is_dir())]
    return [b for b in map(bundle_at, directories) if b is not None]


def bundle_at(directory: Path) -> Bundle | None:
    """The bundle `directory` holds, or None when no readable ledger is directly in it."""
    found = [load(p) for p in sorted(directory.glob("*.json"))]
    if any(r.kind == TRIAL_LEDGER for r in found):
        return Bundle(path=directory, records=found)
    return None


def derive_status(record: Record) -> str:
    """The protocol status the criteria SUPPORT, per interfaces.md.

    Its three sentences, in the order they bind:

      - "An established mandatory violation remains FAIL when another criterion is
        unknown" - so VIOLATED is tested BEFORE UNKNOWN.
      - "missing mandatory evidence prevents PASS" - so an UNKNOWN mandatory
        criterion yields INCONCLUSIVE.
      - "Optional quality scores cannot average away mandatory failures" - so
        optional criteria never enter this computation at all.

    A record with no mandatory criteria is INCONCLUSIVE, never PASS: an empty
    population must not render as a clean one (AGENTS.md).
    """
    declared = record.data.get("run_state")
    if isinstance(declared, str) and declared in DECLARABLE_RUN_STATES:
        return declared

    criteria = record.data.get("criteria")
    if not isinstance(criteria, list):
        return "INCONCLUSIVE"
    mandatory = [
        c for c in criteria
        if isinstance(c, dict) and c.get("mandatory") is True
    ]
    if not mandatory:
        return "INCONCLUSIVE"
    outcomes = [c.get("outcome") for c in mandatory]
    if "VIOLATED" in outcomes:
        return "FAIL"
    if any(o != "SATISFIED" for o in outcomes):
        return "INCONCLUSIVE"
    return "PASS"


# ---------------------------------------------------------------------------
# Field helpers. Each returns a problem description, or None when the field holds.
# ---------------------------------------------------------------------------

def _nonempty_str(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _identity(data: dict[str, object], name: str, *keys: str) -> Iterator[str]:
    """`data[name]` is an object carrying a non-empty string at each key."""
    value = data.get(name)
    if not isinstance(value, dict):
        yield f"no {name} identity"
        return
    for key in keys:
        if not _nonempty_str(value.get(key)):
            yield f"{name} identity has no {key}"


def _bad_id(value: object, what: str) -> str | None:
    if not isinstance(value, str) or not value:
        return f"no {what}"
    if not ID_RE.fullmatch(value):
        return f"{what} {value!r} is malformed; expected {ID_RE.pattern}"
    return None


def _str_list(value: object) -> list[str] | None:
    """A list of NON-BLANK strings, or None. `[""]` is a list with no reference in it."""
    if not isinstance(value, list) or not all(_nonempty_str(v) for v in value):
        return None
    return list(value)


def _ledger_attempts(ledger: Record) -> Iterator[tuple[dict[str, object], dict[str, object]]]:
    """Every (trial, attempt) pair a ledger plans, skipping malformed entries."""
    trials = ledger.data.get("trials")
    if not isinstance(trials, list):
        return
    for trial in trials:
        if not isinstance(trial, dict):
            continue
        attempts = trial.get("attempts")
        if not isinstance(attempts, list):
            continue
        for attempt in attempts:
            if isinstance(attempt, dict):
                yield trial, attempt


# ---------------------------------------------------------------------------
# Record rules. Each is paired with a committed control under controls/<id>/.
# ---------------------------------------------------------------------------

def record_envelope(record: Record) -> Iterator[str]:
    if record.parse_error is not None:
        yield f"unreadable record: {record.parse_error}"
        return
    version = record.data.get("version")
    supported = list(SUPPORTED_VERSIONS)
    if version is None:
        yield "no envelope version; an unversioned record cannot be read safely"
    # bool is a subclass of int: `"version": true` would otherwise read as 1.
    elif isinstance(version, bool) or not isinstance(version, int):
        yield f"envelope version is not an integer: {version!r}"
    elif version == 1:
        yield (
            "envelope version 1 predates producer authority and ledger binding; "
            f"this build reads only {supported} and defines no migration"
        )
    elif version not in SUPPORTED_VERSIONS:
        yield (
            f"envelope version {version} is not one this build reads ({supported}); "
            f"refused rather than read on a guess"
        )
    if record.kind not in KINDS:
        yield f"unknown record kind {record.kind!r}; expected one of {list(KINDS)}"
    if "raw" in record.data:
        # interfaces.md: a local envelope may wrap an upstream record "while
        # preserving its raw bytes". A reference with no digest is a path to
        # something that can be overwritten, which protocol.md calls insufficient.
        raw = record.data["raw"]
        if not isinstance(raw, dict) or not _nonempty_str(raw.get("ref")):
            yield "raw backend data is carried without a ref"
        elif not _nonempty_str(raw.get("digest")):
            yield f"raw backend data {raw.get('ref')!r} has no digest"


def producer_authority(record: Record) -> Iterator[str]:
    """Each kind has exactly one role allowed to produce it (interfaces.md).

    A verified result produced by `subject` is the forged subject verdict: the
    subject declared its own success. This refuses it when it says so. It cannot
    refuse a forger who writes `assembler` - that is authentication, which belongs
    to the trusted controller host, and WHAT_WAS_EXAMINED says so on every run.
    """
    if record.parse_error is not None or record.kind not in AUTHORIZED_PRODUCER:
        return
    expected = AUTHORIZED_PRODUCER[record.kind]
    producer = record.data.get("producer")
    if producer != expected:
        yield (
            f"{record.kind} declares producer {producer!r}; only {expected!r} may "
            f"produce it"
        )
    if record.kind == INSTALLATION_RECEIPT and record.data.get("checked_by") != RECEIPT_CHECKER:
        yield (
            f"installation receipt is not checked_by {RECEIPT_CHECKER!r}; an adapter's "
            f"unchecked account of its own install is a claim, not a receipt"
        )


def attempt_binding(record: Record) -> Iterator[str]:
    """The attempt and trial this record is bound to, well formed.

    Whether that attempt EXISTS, and belongs to that trial, is a fact about the
    ledger rather than the record; `ledger_binding` checks it on a bundle.
    """
    if record.parse_error is not None or record.kind not in ATTEMPT_BOUND:
        return
    for key, what in (("attempt_id", "attempt_id"), ("trial_id", "trial_id")):
        problem = _bad_id(record.data.get(key), what)
        if problem:
            yield f"{problem}; the record is not bound to a well-formed attempt"


def installation_receipt(record: Record) -> Iterator[str]:
    """interfaces.md's receipt row: what was installed, into what, and was it ready.

    "A file count, checkout path or adapter boolean alone cannot prove a usable
    install", so an empty `installed` list is refused and readiness must be
    reported against both of its independent checks.
    """
    if record.parse_error is not None or record.kind != INSTALLATION_RECEIPT:
        return
    data = record.data
    yield from _identity(data, "subject", "locator", "revision", "digest")
    yield from _identity(data, "adapter", "name", "version")
    yield from _identity(data, "client", "name", "version")
    if not _nonempty_str(data.get("surface")):
        yield "no selected native surface"
    for listed in ("layers", "dependencies", "allowed_writes"):
        if not isinstance(data.get(listed), list):
            yield f"no {listed} list; an empty list says none, a missing one says unknown"
    installed = data.get("installed")
    if not isinstance(installed, list) or not installed:
        yield "no installed paths; an install that recorded nothing is not a ready one"
    else:
        for index, entry in enumerate(installed):
            if not isinstance(entry, dict) or not all(
                _nonempty_str(entry.get(k)) for k in ("path", "digest")
            ):
                yield f"installed entry {index} lacks a path or digest"
    readiness = data.get("readiness")
    if not isinstance(readiness, dict):
        yield "no readiness evidence"
        return
    for check in ("discovery_canary", "baseline_absence"):
        if readiness.get(check) not in CRITERION_OUTCOMES:
            yield (
                f"readiness {check} is {readiness.get(check)!r}, not one of "
                f"{list(CRITERION_OUTCOMES)}"
            )


def trial_ledger(record: Record) -> Iterator[str]:
    """The controller's plan: every trial's identities and its expected attempts.

    protocol.md: "Empty selections refuse." A ledger with no trial, or a trial with
    no planned attempt, has an expected population of zero, and nothing measured
    against it could ever go missing.
    """
    if record.parse_error is not None or record.kind != TRIAL_LEDGER:
        return
    problem = _bad_id(record.data.get("experiment_id"), "experiment_id")
    if problem:
        yield problem
    trials = record.data.get("trials")
    if not isinstance(trials, list) or not trials:
        yield "ledger plans no trials; an empty selection is refused, not passed"
        return
    for index, trial in enumerate(trials):
        if not isinstance(trial, dict):
            yield f"trial {index} is not an object"
            continue
        name = trial.get("trial_id", index)
        problem = _bad_id(trial.get("trial_id"), "trial_id")
        if problem:
            yield f"trial {index}: {problem}"
        for ident, keys in (
            ("case", ("id", "revision")),
            ("grader", ("id", "revision")),
            ("subject", ("digest",)),
            ("client", ("name", "version")),
            ("image", ("digest",)),
            ("config", ("digest",)),
        ):
            for missing in _identity(trial, ident, *keys):
                yield f"trial {name!r}: {missing}"
        attempts = trial.get("attempts")
        if not isinstance(attempts, list) or not attempts:
            yield f"trial {name!r} plans no attempts; its expected population is empty"
            continue
        for attempt in attempts:
            attempt_id = attempt.get("attempt_id") if isinstance(attempt, dict) else None
            problem = _bad_id(attempt_id, "attempt_id")
            if problem:
                yield f"trial {name!r}: {problem}"


def artifact_digest(record: Record) -> Iterator[str]:
    if record.parse_error is not None or record.kind != ARTIFACT_MANIFEST:
        return
    artifacts = record.data.get("artifacts")
    if not isinstance(artifacts, list):
        yield "artifact manifest carries no artifacts list"
        return
    if not artifacts:
        yield "artifact manifest lists no artifacts; an empty capture is not a clean one"
        return
    for index, entry in enumerate(artifacts):
        if not isinstance(entry, dict):
            yield f"artifact {index} is not an object"
            continue
        for required in ("path", "type", "size", "digest"):
            if required not in entry:
                yield f"artifact {entry.get('path', index)!r} has no {required}"
        if "digest" in entry and not _nonempty_str(entry["digest"]):
            # `null` is not a content identity, and must not become the string
            # "None" that a result could then cite in agreement.
            yield f"artifact {entry.get('path', index)!r} has digest {entry['digest']!r}"


def observation_coverage(record: Record) -> Iterator[str]:
    """Each required stream declares its origin and coverage; failures are listed.

    "Missing events cannot prove a forbidden action never happened", so a manifest
    silent about a stream is refused - `unsupported` is an answer, absence is not.
    """
    if record.parse_error is not None or record.kind != ARTIFACT_MANIFEST:
        return
    observations = record.data.get("observations")
    if not isinstance(observations, list):
        yield "manifest carries no observations list"
        return
    declared: set[str] = set()
    for index, entry in enumerate(observations):
        if not isinstance(entry, dict) or not _nonempty_str(entry.get("stream")):
            yield f"observation {index} names no stream"
            continue
        stream = str(entry["stream"])
        declared.add(stream)
        if entry.get("origin") not in OBSERVATION_ORIGINS:
            yield (
                f"observation {stream!r} has origin {entry.get('origin')!r}, not one "
                f"of {list(OBSERVATION_ORIGINS)}"
            )
        if entry.get("coverage") not in OBSERVATION_COVERAGE:
            yield (
                f"observation {stream!r} has coverage {entry.get('coverage')!r}, not "
                f"one of {list(OBSERVATION_COVERAGE)}"
            )
    for stream in REQUIRED_OBSERVATIONS:
        if stream not in declared:
            yield (
                f"required observation {stream!r} is not declared; silence about a "
                f"stream is not a stream that saw nothing"
            )
    if not isinstance(record.data.get("capture_failures"), list):
        yield "no capture_failures list; an empty list says none, a missing one says unknown"


def criterion_vocabulary(record: Record) -> Iterator[str]:
    if record.parse_error is not None or record.kind != VERIFIED_RESULT:
        return
    criteria = record.data.get("criteria")
    if not isinstance(criteria, list):
        yield "verified result carries no criteria list"
        return
    for index, entry in enumerate(criteria):
        if not isinstance(entry, dict):
            yield f"criterion {index} is not an object"
            continue
        outcome = entry.get("outcome")
        if outcome not in CRITERION_OUTCOMES:
            yield (
                f"criterion {entry.get('id', index)!r} reports {outcome!r}, which is "
                f"not one of {list(CRITERION_OUTCOMES)}"
            )


def result_evidence(record: Record) -> Iterator[str]:
    """A verified result names its grader, what it graded, and why each criterion.

    interfaces.md requires "criterion outcomes/evidence references, grader/control
    identities, artifact digest ... and explicit missing evidence". So an
    established outcome cites its evidence, an UNKNOWN one says what is missing,
    and a declared run state gives its reason. A SATISFIED mandatory criterion with
    no evidence is the missing-mandatory-evidence case: without this rule it would
    derive PASS.
    """
    if record.parse_error is not None or record.kind != VERIFIED_RESULT:
        return
    data = record.data
    problem = _bad_id(data.get("result_id"), "result_id")
    if problem:
        yield problem
    yield from _identity(data, "grader", "id", "revision")
    declared = data.get("run_state")
    if declared in DECLARABLE_RUN_STATES:
        if not _nonempty_str(data.get("reason")):
            yield f"run state {declared!r} is declared without a reason"
    else:
        digests = _str_list(data.get("graded_digests"))
        if not digests:
            yield "no graded_digests; the result does not say which artifact it graded"
    criteria = data.get("criteria")
    if not isinstance(criteria, list):
        return  # criterion-vocabulary reports this
    for index, entry in enumerate(criteria):
        if not isinstance(entry, dict):
            continue
        name = entry.get("id", index)
        outcome = entry.get("outcome")
        if outcome in ("SATISFIED", "VIOLATED") and not _str_list(entry.get("evidence")):
            yield f"criterion {name!r} reports {outcome} with no evidence reference"
        if outcome == "UNKNOWN" and not _nonempty_str(entry.get("missing")):
            yield f"criterion {name!r} is UNKNOWN without naming the missing evidence"


def derived_status(record: Record) -> Iterator[str]:
    """The status must be DERIVED from the criteria, never copied from the subject.

    interfaces.md requires that "the assembler derives status rather than copying a
    subject-authored success flag", and PLAN.md that "A valid JSON record, hash or
    echoed config alone does not authenticate success". A forged verdict is a
    structurally perfect record whose status does not follow from its own criteria,
    so this is the rule that refuses it - and the reason a schema alone would not.
    """
    if record.parse_error is not None or record.kind != VERIFIED_RESULT:
        return
    claimed = record.data.get("status")
    if claimed not in PROTOCOL_STATUSES:
        yield f"status {claimed!r} is not one of {list(PROTOCOL_STATUSES)}"
        return
    derived = derive_status(record)
    if claimed != derived:
        yield (
            f"status {claimed!r} does not follow from this record's own criteria, "
            f"which derive {derived!r}; a status that does not follow was asserted, "
            f"not established"
        )


def attempt_lifecycle(record: Record) -> Iterator[str]:
    """The controller's account of one attempt: what it concluded, why it stopped,
    whether that stop was confirmed, and what cleanup did.

    `captured` is the only disposition that hands bytes to grading, so it requires
    a CONFIRMED stop - capture before the subject stopped is capture of something
    that could still be changing (interfaces.md lifecycle steps 6-7). Every other
    disposition names its reason: an unexplained non-result is a dropped attempt
    with a label on it.
    """
    if record.parse_error is not None or record.kind != ATTEMPT_LIFECYCLE:
        return
    data = record.data
    disposition = data.get("disposition")
    if disposition not in DISPOSITIONS:
        yield f"disposition {disposition!r} is not one of {list(DISPOSITIONS)}"
    elif disposition != "captured" and not _nonempty_str(data.get("reason")):
        yield f"disposition {disposition!r} gives no reason; a non-result must say why"
    stop = data.get("stop")
    if not isinstance(stop, dict):
        yield "no stop observation; how the subject stopped is unknown"
    else:
        reason = stop.get("reason")
        if reason not in STOP_REASONS:
            yield f"stop reason {reason!r} is not one of {list(STOP_REASONS)}"
        if not isinstance(stop.get("confirmed"), bool):
            yield "stop does not say whether it was confirmed"
        if disposition == "captured":
            if stop.get("confirmed") is not True:
                yield "captured without a confirmed stop; the output could still have been changing"
            if reason in NOTHING_RAN:
                yield f"captured, but the stop reason {reason!r} says nothing ran"
        if disposition == "not-run" and reason != "never-started":
            yield f"disposition not-run with stop reason {reason!r}; a not-run attempt never started"
        if reason == "never-started" and disposition not in ("not-run", "unavailable"):
            yield (
                f"disposition {disposition!r} with stop reason never-started; an attempt that "
                f"never started is not-run, or unavailable when a dependency prevented it"
            )
    events = data.get("events")
    if not isinstance(events, list) or not events:
        yield "no lifecycle events"
    else:
        names = [e.get("event") if isinstance(e, dict) else None for e in events]
        for index, (entry, name) in enumerate(zip(events, names)):
            if name not in LIFECYCLE_EVENTS:
                yield f"event {index} is {name!r}, not one of {list(LIFECYCLE_EVENTS)}"
            elif not isinstance(entry, dict) or not _nonempty_str(entry.get("at")):
                yield f"event {index} ({name}) has no time"
        if names[0] != "planned":
            yield "events do not start at planned; the attempt's origin is unrecorded"
        if disposition == "captured" and "captured" not in names:
            yield "disposition captured, but no captured event was recorded"
    cleanup = data.get("cleanup")
    if not isinstance(cleanup, dict) or cleanup.get("status") not in CLEANUP_STATUSES:
        yield f"cleanup status is not one of {list(CLEANUP_STATUSES)}"
    elif not isinstance(cleanup.get("failures"), list):
        yield "no cleanup failures list; an empty list says none, a missing one says unknown"


# ---------------------------------------------------------------------------
# Bundle rules: facts that exist only BETWEEN records. Each is paired with a
# committed control whose bad and good cases are bundle directories.
# ---------------------------------------------------------------------------

def _ident(value: object, *keys: str) -> tuple[object, ...]:
    return tuple(value.get(k) for k in keys) if isinstance(value, dict) else ()


def ledger_binding(bundle: Bundle) -> Iterator[str]:
    """Every record is bound to an attempt the ledger planned, under that trial's
    identities, and a result graded bytes that were actually captured.

    This is the half of "stale/cross-trial receipt" a single record cannot decide:
      - an attempt the ledger never issued is refused;
      - a record naming the wrong trial for its attempt is cross-trial;
      - a receipt whose subject or client differs from the trial's plan is stale;
      - a result whose grader differs from the trial's, other than a regrade's new
        revision, graded under a configuration nobody planned;
      - a result citing a digest its attempt's manifest does not list graded bytes
        nobody captured - an altered or substituted artifact.
    """
    ledgers = bundle.of_kind(TRIAL_LEDGER)
    if len(ledgers) != 1:
        yield f"bundle holds {len(ledgers)} trial ledgers; exactly one issues its attempt IDs"
        return
    plan = {
        str(attempt.get("attempt_id")): trial
        for trial, attempt in _ledger_attempts(ledgers[0])
    }
    captured: dict[str, set[str]] = {}
    for manifest in bundle.of_kind(ARTIFACT_MANIFEST):
        artifacts = manifest.data.get("artifacts")
        digests = {
            a["digest"] for a in artifacts or []
            if isinstance(a, dict) and _nonempty_str(a.get("digest"))
        } if isinstance(artifacts, list) else set()
        captured.setdefault(manifest.attempt_id, set()).update(digests)

    for record in bundle.records:
        if record.kind not in ATTEMPT_BOUND or not record.attempt_id:
            continue
        where = f"{record.path.name} ({record.kind}, {record.attempt_id})"
        trial = plan.get(record.attempt_id)
        if trial is None:
            yield f"{where}: the ledger issued no attempt {record.attempt_id!r}"
            continue
        if record.trial_id != trial.get("trial_id"):
            yield (
                f"{where}: names trial {record.trial_id!r}, but the ledger planned this "
                f"attempt under {trial.get('trial_id')!r}; a cross-trial record"
            )
        if record.kind == INSTALLATION_RECEIPT:
            for ident, keys in (("subject", ("digest",)), ("client", ("name", "version"))):
                got = _ident(record.data.get(ident), *keys)
                want = _ident(trial.get(ident), *keys)
                if got != want:
                    yield (
                        f"{where}: {ident} {got} differs from the trial's planned "
                        f"{want}; a stale receipt"
                    )
        if record.kind == VERIFIED_RESULT:
            grader, planned = record.data.get("grader"), trial.get("grader")
            regrade = "regrade_of" in record.data
            keys = ("id",) if regrade else ("id", "revision")
            if _ident(grader, *keys) != _ident(planned, *keys):
                yield (
                    f"{where}: grader {_ident(grader, *keys)} is not the trial's "
                    f"planned {_ident(planned, *keys)}"
                )
            graded = _str_list(record.data.get("graded_digests")) or []
            # No manifest at all is attempt-accounting's finding, not a mismatch.
            have = captured.get(record.attempt_id)
            if have is None:
                continue
            for digest in graded:
                if digest not in have:
                    yield (
                        f"{where}: graded {digest!r}, which no manifest for this "
                        f"attempt captured"
                    )


def unique_ids(bundle: Bundle) -> Iterator[str]:
    """Identifiers identify. interfaces.md makes duplicate/conflicting IDs an
    explicit validation failure, never verified success.

    An attempt has at most one receipt, one manifest and one lifecycle: a second one is a
    conflicting account of the same attempt, and nothing here can say which is
    true. Results may be several (a regrade is a new result), but each has its own
    `result_id`.
    """
    for ledger in bundle.of_kind(TRIAL_LEDGER):
        trials = ledger.data.get("trials")
        # Only string IDs are counted: a malformed one is trial-ledger's finding,
        # and must not crash the scan before any finding is printed.
        trial_ids = Counter(
            t.get("trial_id") for t in trials or []
            if isinstance(t, dict) and isinstance(t.get("trial_id"), str)
        ) if isinstance(trials, list) else Counter()
        attempt_ids = Counter(
            a.get("attempt_id") for _t, a in _ledger_attempts(ledger)
            if isinstance(a.get("attempt_id"), str)
        )
        for name, what in ((trial_ids, "trial_id"), (attempt_ids, "attempt_id")):
            for value, count in sorted(name.items(), key=str):
                if count > 1:
                    yield f"ledger plans {what} {value!r} {count} times"
    for kind in (INSTALLATION_RECEIPT, ARTIFACT_MANIFEST, ATTEMPT_LIFECYCLE):
        per_attempt = Counter(r.attempt_id for r in bundle.of_kind(kind) if r.attempt_id)
        for attempt, count in sorted(per_attempt.items()):
            if count > 1:
                yield f"{count} conflicting {kind} records for attempt {attempt!r}"
    originals = Counter(
        r.attempt_id for r in bundle.of_kind(VERIFIED_RESULT)
        if r.attempt_id and "regrade_of" not in r.data
    )
    for attempt, count in sorted(originals.items()):
        if count > 1:
            yield (
                f"{count} original results for attempt {attempt!r}; a further result "
                f"is a regrade and says so, or it is a conflicting verdict"
            )
    result_ids = Counter(
        r.data.get("result_id") for r in bundle.of_kind(VERIFIED_RESULT)
        if isinstance(r.data.get("result_id"), str)
    )
    for result_id, count in sorted(result_ids.items(), key=str):
        if count > 1:
            yield f"result_id {result_id!r} is used by {count} results"


def attempt_accounting(bundle: Bundle) -> Iterator[str]:
    """Every planned attempt remains accounted for (interfaces.md, EF-07).

    The controller's account of an attempt is its `attempt-lifecycle` record, so
    every planned attempt has one: without it the attempt has silently dropped out
    of the population. From its disposition:

      - `captured` hands bytes to grading: it has its artifact manifest, and it has
        a result - a captured attempt with no result is grading still owed;
      - `not-run` and `unavailable` need no result, and any result they have
        declares the matching run state;
      - no attempt the controller did not capture carries a manifest or a GRADED
        result, and no captured attempt carries a declared non-run: the accounts
        disagree.

    An attempt that was graded (a result declaring no run state) also has its
    installation receipt and artifact manifest: a verdict over an install nobody
    recorded, or bytes nobody captured, is missing mandatory evidence.
    """
    ledgers = bundle.of_kind(TRIAL_LEDGER)
    if len(ledgers) != 1:
        # Not silent: under `--rule attempt-accounting` ledger-binding does not
        # run, and an empty return would read as a fully accounted population.
        yield f"cannot account: the bundle holds {len(ledgers)} trial ledgers, not one"
        return
    results: dict[str, list[Record]] = {}
    for result in bundle.of_kind(VERIFIED_RESULT):
        results.setdefault(result.attempt_id, []).append(result)
    lifecycles = {r.attempt_id: r for r in bundle.of_kind(ATTEMPT_LIFECYCLE)}
    receipts = {r.attempt_id for r in bundle.of_kind(INSTALLATION_RECEIPT)}
    manifests = {r.attempt_id for r in bundle.of_kind(ARTIFACT_MANIFEST)}
    planned = list(_ledger_attempts(ledgers[0]))
    if not planned:
        # Zero planned attempts leaves nothing to account for; reporting 0 errors
        # would read like a population that was fully accounted.
        yield "the ledger plans no attempts, so there is nothing to account for"
        return
    for _trial, attempt in planned:
        attempt_id = str(attempt.get("attempt_id"))
        own = results.get(attempt_id, [])
        graded = [r for r in own if r.data.get("run_state") not in DECLARABLE_RUN_STATES]
        lifecycle = lifecycles.get(attempt_id)
        if lifecycle is None:
            yield (
                f"planned attempt {attempt_id!r} has no attempt-lifecycle record; the "
                f"controller never accounted for it, so it has silently dropped out"
            )
        else:
            disposition = lifecycle.data.get("disposition")
            if disposition == "captured":
                if attempt_id not in manifests:
                    yield f"attempt {attempt_id!r} is captured but has no artifact manifest"
                if not own:
                    yield (
                        f"attempt {attempt_id!r} is captured but has no result; grading "
                        f"is still owed, so it is not accounted for yet"
                    )
                for r in own:
                    if r.data.get("run_state") in DECLARABLE_RUN_STATES:
                        yield (
                            f"attempt {attempt_id!r} is captured, but {r.path.name} "
                            f"declares {r.data.get('run_state')}; the accounts disagree"
                        )
            elif isinstance(disposition, str):
                if attempt_id in manifests:
                    yield (
                        f"attempt {attempt_id!r} is {disposition}, but a manifest captured its "
                        f"output; the accounts disagree"
                    )
                if graded:
                    yield (
                        f"attempt {attempt_id!r} is {disposition}, but {graded[0].path.name} "
                        f"graded it; nothing the controller did not capture can be graded"
                    )
                want = RUN_STATE_FOR.get(disposition)
                for r in own:
                    declared = r.data.get("run_state")
                    if declared in DECLARABLE_RUN_STATES and declared != want:
                        yield (
                            f"attempt {attempt_id!r} is {disposition}, but {r.path.name} "
                            f"declares {declared}; the accounts disagree"
                        )
        if graded:
            for have, what in ((receipts, "installation receipt"), (manifests, "artifact manifest")):
                if attempt_id not in have:
                    yield f"attempt {attempt_id!r} was graded without its {what}"


def _chain_root(start: str, links: dict[str, str]) -> tuple[str | None, list[str]]:
    """Follow `links` from `start`. Returns (root, path), or (None, path) on a cycle."""
    path, current = [start], start
    while current in links:
        current = links[current]
        if current in path:
            return None, path + [current]
        path.append(current)
    return current, path


def lineage(bundle: Bundle) -> Iterator[str]:
    """Reruns and regrades link to their originals and erase nothing.

    protocol.md: "A rerun gets a new ID and links to the original. Regrading
    creates a new result linked to the unchanged original artifact ... Neither
    operation erases the earlier attempt."

    Each link is checked, AND each chain: it must end at an original that is not
    itself a retry or regrade. Two results naming each other satisfy every single
    link while no original exists at all - and since ledger-binding lets a regrade
    carry a new grader revision, a cycle would exempt every result in it from the
    planned grader.
    """
    for ledger in bundle.of_kind(TRIAL_LEDGER):
        in_trial: dict[str, set[str]] = {}
        retries: dict[str, str] = {}
        for trial, attempt in _ledger_attempts(ledger):
            attempt_id, trial_id = attempt.get("attempt_id"), trial.get("trial_id")
            if isinstance(attempt_id, str) and isinstance(trial_id, str):
                in_trial.setdefault(trial_id, set()).add(attempt_id)
        for trial, attempt in _ledger_attempts(ledger):
            if "retry_of" not in attempt:
                continue
            attempt_id, original = attempt.get("attempt_id"), attempt.get("retry_of")
            trial_id = trial.get("trial_id")
            planned = in_trial.get(trial_id, set()) if isinstance(trial_id, str) else set()
            if not isinstance(attempt_id, str) or not isinstance(original, str):
                yield f"retry {attempt_id!r} links to {original!r}, which is not an attempt ID"
            elif original == attempt_id:
                yield f"retry {attempt_id!r} reuses its original's ID; a rerun gets a new one"
            elif original not in planned:
                yield (
                    f"retry {attempt_id!r} links to {original!r}, which this trial does "
                    f"not plan; the original is gone or belongs elsewhere"
                )
            else:
                retries[attempt_id] = original
        seen: set[str] = set()
        for attempt_id in sorted(retries):
            root, path = _chain_root(attempt_id, retries)
            if root is None and not seen & set(path):
                seen.update(path)
                yield f"retries form a cycle ({' -> '.join(path)}); no original attempt exists"

    results = {
        str(r.data["result_id"]): r for r in bundle.of_kind(VERIFIED_RESULT)
        if isinstance(r.data.get("result_id"), str)
    }
    regrades: dict[str, str] = {}
    for result in bundle.of_kind(VERIFIED_RESULT):
        if "regrade_of" not in result.data:
            continue
        name, original_id = result.data.get("result_id"), result.data.get("regrade_of")
        original = results.get(original_id) if isinstance(original_id, str) else None
        if original is None or original is result:
            yield (
                f"regrade {name!r} links to {original_id!r}, which is not retained here; "
                f"a regrade never erases its original"
            )
            continue
        if isinstance(name, str) and isinstance(original_id, str):
            regrades[name] = original_id
        if original.attempt_id != result.attempt_id:
            yield (
                f"regrade {name!r} is for attempt {result.attempt_id!r}, but its original "
                f"graded {original.attempt_id!r}"
            )
        if sorted(_str_list(result.data.get("graded_digests")) or []) != sorted(
            _str_list(original.data.get("graded_digests")) or []
        ):
            yield (
                f"regrade {name!r} graded different bytes from its original; a regrade "
                f"reads the unchanged original artifact"
            )
    reported: set[str] = set()
    for name in sorted(regrades):
        root, path = _chain_root(name, regrades)
        if root is None and not reported & set(path):
            reported.update(path)
            yield (
                f"regrades form a cycle ({' -> '.join(path)}); no original result under "
                f"the planned grader is retained"
            )
