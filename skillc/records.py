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
from collections.abc import Callable, Iterator
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
#: Additive in version 2 (#12): the evidence report a completed pilot's
#: acceptance requires - per-attempt disposition, per-criterion success,
#: uncertainty and intervention counts, and a cost/time split into setup,
#: agent and grading, with missing values explicit. Not attempt-bound: like
#: `TRIAL_LEDGER`, it is ONE record summarizing every attempt an experiment
#: planned, produced after a run rather than before one.
PILOT_REPORT = "pilot-report"
#: Additive in version 2 (#106): what the controller concluded from a REAL
#: agent's transcript for one attempt - prompt delivery, the liveness canary,
#: skill invocations, the credential's in-container fate, and whether the
#: attempt was graded. Before it existed these facts lived only in memory and a
#: printed paste-back, so a misprint was unrecoverable (#124 repeated two live
#: runs). Not a verdict: a grade it carries is an audit copy, checked against
#: its own criteria, never a substitute for a `verified-result`.
AGENT_OBSERVATION = "agent-observation"
#: Additive in version 2 (#268): per-attempt, per-skill attribution - skill
#: identity (reused from the installation receipt, never re-declared), parent/
#: child invocation lineage, criterion ownership (an audit copy of the
#: attempt's own verified-result, never an independent claim), and reconciliation
#: of externally produced evidence (a usage record a subject's own tooling
#: wrote) that never becomes a trusted observation. See
#: docs/specs/evaluation-facility/records.md's `skill-evidence` section.
SKILL_EVIDENCE = "skill-evidence"
KINDS = (
    INSTALLATION_RECEIPT, TRIAL_LEDGER, ARTIFACT_MANIFEST, VERIFIED_RESULT, ATTEMPT_LIFECYCLE, PILOT_REPORT,
    AGENT_OBSERVATION, SKILL_EVIDENCE,
)

#: Records that belong to ONE attempt. The ledger is not one of them: it issues
#: the attempt identifiers the others cite.
ATTEMPT_BOUND = (
    INSTALLATION_RECEIPT, ARTIFACT_MANIFEST, VERIFIED_RESULT, ATTEMPT_LIFECYCLE, AGENT_OBSERVATION, SKILL_EVIDENCE,
)

#: The one role allowed to produce each kind, from interfaces.md's producer column.
#: The subject adapter writes the receipt, and the controller must have checked it.
AUTHORIZED_PRODUCER = {
    INSTALLATION_RECEIPT: "subject-adapter",
    TRIAL_LEDGER: "controller",
    ARTIFACT_MANIFEST: "controller",
    VERIFIED_RESULT: "assembler",
    ATTEMPT_LIFECYCLE: "controller",
    PILOT_REPORT: "assembler",
    AGENT_OBSERVATION: "controller",
    SKILL_EVIDENCE: "assembler",
}
RECEIPT_CHECKER = "controller"

#: `skill-evidence.lifecycle.{listed,read_observed,execution_observed}` (#268):
#: a usage FACT, never a compliance outcome - deliberately a separate, closed
#: vocabulary from `CRITERION_OUTCOMES` so neither can be mistaken for the
#: other. Mirrors `skillc/backend.py`'s own three-way `Confirmation`
#: (`confirm_stopped`/`confirm_absent`): a backend that cannot observe returns
#: `UNKNOWN`, never a guess, and `UNKNOWN` is never treated as confirmed.
SKILL_EVIDENCE_CONFIRMATION = ("CONFIRMED", "NOT_CONFIRMED", "UNKNOWN")

#: `invocation.lineage` (#268): whether a `skills` entry is the attempt's
#: directly-selected skill or one invoked BY another skill in the same record.
SKILL_EVIDENCE_LINEAGE = ("root", "child")

#: `external_evidence.reconciliation` (#268): CPP #1368's R9, exactly these four
#: states and no fifth. `absent` is never conflated with `contradicting` - no
#: evidence is not evidence of a disagreement - and `unmatched` is never
#: silently promoted to `matched` for lack of a reason to doubt it.
SKILL_EVIDENCE_RECONCILIATION = ("absent", "unmatched", "matched", "contradicting")

#: `external_evidence.source` (#268): closed, so an unrecognized label is refused
#: as unknown schema rather than silently accepted as a reference skillc cannot
#: name. `check-records` never decodes the referenced bytes against this label
#: (that parse belongs to the consumer, per ADR 0003) - it only checks the label
#: itself is one skillc recognizes.
EXTERNAL_EVIDENCE_SOURCES = ("cpp.execution-evidence/v1",)

#: The four cost/time split components a pilot report's own control requires
#: (#12's acceptance: "Separate setup/agent/grading cost and time"). Closed:
#: an entry missing one of these keys is refused, not silently treated as
#: zero - matching this codebase's "silence is not absence" convention
#: (`skill-invocations`, `observation-coverage`). A missing VALUE is the
#: literal string `"UNKNOWN"`, the same spelling `skill-invocations` already
#: uses for the same reason.
PILOT_REPORT_SPLIT_KEYS = ("setup", "agent", "grading", "total")

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

#: The optional per-skill invocation stream (#39, concept from config-drift-checker,
#: docs/research/config-drift-checker-lessons.md, per ADR 0003). Deliberately NOT
#: in REQUIRED_OBSERVATIONS: unlike client-events/process-lifecycle, making it
#: mandatory would invalidate every v2 manifest written before this stream existed.
#: records.md "skill-invocations" records the version decision and the scope this
#: leaves to #26 (making it required for a case that declares selection as an
#: observation - #26's case format does not exist yet, so that wiring is deferred).
SKILL_INVOCATIONS = "skill-invocations"

#: The client's own transcript (#202): the codex session rollout or the Claude
#: Code session file, as a content-addressed object. Optional like
#: skill-invocations, so no earlier manifest is invalidated. It has its own
#: coverage vocabulary: `missing` (with a reason) says no transcript was
#: retained - none was found, or the leak check refused it - which is a
#: different fact from `unsupported`. `missing` is legal on THIS stream only;
#: the required streams keep `OBSERVATION_COVERAGE`.
CLIENT_TRANSCRIPT = "client-transcript"
CLIENT_TRANSCRIPT_COVERAGE = ("complete", "partial", "missing")

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
    """Every `*.json` under `root`, in a stable order.

    `root` naming a single `.json` file directly (`spec.discover`'s own
    shape, for `SKILL.md`) loads just that file - issue #131 item 1:
    `Path.rglob` treats its receiver as a directory to search WITHIN, so on
    a file path it silently matches nothing, and `check-records one.json`
    read that as an empty population (`skillc: no record found ...`,
    exit 2) rather than checking the one record it was given."""
    if root.is_file() and root.suffix == ".json":
        return [load(root)]
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

    A declared run state is honoured only AFTER the violation test (#130).
    protocol.md section 4 allows UNAVAILABLE only "without an already-established
    task failure", so a record that declares UNAVAILABLE or NOT_RUN over a
    VIOLATED mandatory criterion still derives FAIL - otherwise relabelling a
    failure as a provider outage would take it out of the count.
    """
    criteria = record.data.get("criteria")
    mandatory = [
        c for c in criteria
        if isinstance(c, dict) and c.get("mandatory") is True
    ] if isinstance(criteria, list) else []
    outcomes = [c.get("outcome") for c in mandatory]
    if "VIOLATED" in outcomes:
        return "FAIL"

    declared = record.data.get("run_state")
    if isinstance(declared, str) and declared in DECLARABLE_RUN_STATES:
        return declared

    if not outcomes:
        return "INCONCLUSIVE"
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
        case = trial.get("case")
        if isinstance(case, dict) and "observes_selection" in case and not isinstance(case["observes_selection"], bool):
            yield (
                f"trial {name!r}: case.observes_selection must be a boolean, "
                f"not {case['observes_selection']!r}"
            )
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
        # Present is not enough: `null` for all three with a valid digest names
        # bytes nobody can locate or re-hash (#130).
        for key in ("path", "type"):
            if key in entry and not _nonempty_str(entry[key]):
                yield f"artifact {index} has {key} {entry[key]!r}"
        size = entry.get("size")
        if "size" in entry and (isinstance(size, bool) or not isinstance(size, int) or size < 0):
            yield f"artifact {index} has size {size!r}, not a non-negative integer"
        if "digest" in entry and not _nonempty_str(entry["digest"]):
            # `null` is not a content identity, and must not become the string
            # "None" that a result could then cite in agreement.
            yield f"artifact {entry.get('path', index)!r} has digest {entry['digest']!r}"


def _skill_invocations(entry: dict[str, object]) -> Iterator[str]:
    """The optional `skill-invocations` stream (#39): one row per installed skill,
    keyed by path to `installation-receipt.installed` (the cross-check against the
    receipt itself is `ledger_binding`'s, which is the rule with a receipt to
    read). Each row carries a `count` - either a non-negative integer or the
    literal string `"UNKNOWN"`.

    Coverage governs which is legal, the same rule `observation_coverage` already
    enforces for a whole stream, applied per skill: incomplete coverage may only
    ever report UNKNOWN, never a real count including 0 - a silent skill is not an
    uninvoked one. Complete coverage must report a real count, since "unknown" is
    not an honest answer once everything was seen.
    """
    coverage = entry.get("coverage")
    skills = entry.get("skills")
    if not isinstance(skills, list):
        yield "observation 'skill-invocations' carries no skills list"
        return
    if coverage == "complete" and not skills:
        # `installation-receipt` refuses an empty `installed` list, so every
        # attempt with a receipt has at least one installed skill. "Complete"
        # coverage naming none is the same silent-empty-population defect
        # `artifact_digest` already refuses for an empty capture, one level up.
        yield (
            "observation 'skill-invocations' declares complete coverage but names "
            "no skills; a capture that recorded nothing is not a capture that "
            "found nothing"
        )
    seen: set[str] = set()
    for index, row in enumerate(skills):
        if not isinstance(row, dict) or not _nonempty_str(row.get("path")):
            yield f"skill-invocations entry {index} names no path"
            continue
        path, count = row["path"], row.get("count")
        if path in seen:
            yield (
                f"skill-invocations: {path!r} appears more than once; a second row "
                f"is a conflicting count, and nothing here can say which is true"
            )
        seen.add(path)
        if coverage != "complete":
            if count != "UNKNOWN":
                yield (
                    f"skill-invocations: {path!r} has coverage {coverage!r} but "
                    f"count {count!r}, not 'UNKNOWN' - silence is not 'not invoked'"
                )
        elif isinstance(count, bool) or not isinstance(count, int) or count < 0:
            yield (
                f"skill-invocations: {path!r} has count {count!r}, not a "
                f"non-negative integer, under complete coverage"
            )


def _client_transcript(entry: dict[str, object]) -> Iterator[str]:
    """The `client-transcript` stream (#202). A retained transcript names the
    object it is (`ref`, `digest`, `size`); a missing one says why and names
    no object - a `missing` entry pointing at bytes, or a `complete` one
    pointing at none, would each claim the opposite of what the store holds."""
    coverage = entry.get("coverage")
    if coverage not in CLIENT_TRANSCRIPT_COVERAGE:
        yield (
            f"observation {CLIENT_TRANSCRIPT!r} has coverage {coverage!r}, not one of "
            f"{list(CLIENT_TRANSCRIPT_COVERAGE)}"
        )
        return
    if coverage == "missing":
        if not _nonempty_str(entry.get("reason")):
            yield (
                f"observation {CLIENT_TRANSCRIPT!r} is missing but gives no reason; "
                f"an absent transcript must say why it is absent"
            )
        if any(key in entry for key in ("ref", "digest", "size")):
            yield f"observation {CLIENT_TRANSCRIPT!r} is missing but names an object"
        return
    size = entry.get("size")
    if (
        not _nonempty_str(entry.get("ref")) or not _nonempty_str(entry.get("digest"))
        or isinstance(size, bool) or not isinstance(size, int) or size <= 0
    ):
        yield (
            f"observation {CLIENT_TRANSCRIPT!r} has coverage {coverage!r} but no ref, digest "
            f"and non-empty size; a retained transcript names the object it is"
        )


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
        if stream == CLIENT_TRANSCRIPT:
            yield from _client_transcript(entry)
        elif entry.get("coverage") not in OBSERVATION_COVERAGE:
            yield (
                f"observation {stream!r} has coverage {entry.get('coverage')!r}, not "
                f"one of {list(OBSERVATION_COVERAGE)}"
            )
        if stream == SKILL_INVOCATIONS:
            yield from _skill_invocations(entry)
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
        # Evidence and `missing` are cited per criterion id; one without an id
        # cannot be referred to at all (#130).
        problem = _bad_id(entry.get("id"), f"criterion {index} id")
        if problem:
            yield problem
        outcome = entry.get("outcome")
        if outcome not in CRITERION_OUTCOMES:
            yield (
                f"criterion {entry.get('id', index)!r} reports {outcome!r}, which is "
                f"not one of {list(CRITERION_OUTCOMES)}"
            )
        # `derive_status` selects with `is True`, so a string "true", a 1 or a
        # missing flag would make the criterion optional, and a VIOLATED one would
        # drop out of the verdict rather than contradict it - which derived-status
        # cannot see (#37). bool, not int: `1` is an int that equals True.
        mandatory = entry.get("mandatory")
        if not isinstance(mandatory, bool):
            yield (
                f"criterion {entry.get('id', index)!r} has mandatory {mandatory!r}, "
                f"which is not a JSON boolean; it would silently read as optional"
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
    if "run_state" in data and declared not in DECLARABLE_RUN_STATES:
        # Otherwise any other value reads as "no run state" and is silently
        # dropped, while the record still claims to have declared one (#130).
        yield f"run state {declared!r} is not one of {list(DECLARABLE_RUN_STATES)}"
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
    declared = record.data.get("run_state")
    if declared in DECLARABLE_RUN_STATES and declared != derived:
        # A FAIL status beside a declared UNAVAILABLE still reads as a non-run to
        # anything that trusts run_state (attempt-accounting does) (#130).
        yield (
            f"run state {declared!r} is declared over an established mandatory "
            f"violation, which derives {derived!r}; a run state cannot relabel a failure"
        )


def verdict_tiers(record: Record) -> Iterator[str]:
    """Every enabled tier has a verdict, and every verdict names an enabled tier (#69).

    The owner ruling behind this (#69, relayed to a keyed collection rather than
    a single `grading_tier` field): a trial graded by more than one tier carries
    ALL of their verdicts side by side, never averaged or overridden, and "one
    judge unavailable gives that tier `unavailable` while the others still
    report" - never a silent drop. Both directions of that consistency are
    checked, not just one (orchestrator review of PR #88, ffae7eb): a stray
    verdict for a tier never requested is indistinguishable from one that
    silently ran unrequested, and an enabled tier with NO verdict entry is
    indistinguishable from one that ran and was simply never written down -
    the exact silent-drop #69 forbids, just facing the other way. An
    UNAVAILABLE verdict must say why, for the same reason a declared run state
    must (`result_evidence`, above). `verification` itself is optional here: a
    record with none of this structure is not this rule's concern (other rules
    own whether `verification` must exist at all).
    """
    if record.parse_error is not None or record.kind != VERIFIED_RESULT:
        return
    verification = record.data.get("verification")
    if not isinstance(verification, dict):
        return
    enabled = verification.get("tiers_enabled")
    if "tiers_enabled" in verification and (
        not isinstance(enabled, list) or not all(_nonempty_str(t) for t in enabled)
    ):
        yield "verification.tiers_enabled is present but is not a list of non-empty tier names"
    # Built from validated entries only (codex review): a stray non-string or
    # unhashable element (a nested list, a dict) must not raise here just
    # because it was already flagged above - `set()` on an unhashable value,
    # and `sorted()` on a mixed-type set below, would abort validation with a
    # traceback instead of a diagnostic, which is worse than reporting nothing.
    enabled_set = {t for t in enabled if _nonempty_str(t)} if isinstance(enabled, list) else set()

    verdicts = verification.get("verdicts")
    if verdicts is not None and not isinstance(verdicts, dict):
        yield "verification.verdicts is present but is not an object keyed by tier name"
        verdicts = None
    verdict_map = verdicts if isinstance(verdicts, dict) else {}

    # The converse direction: an enabled tier missing from `verdicts` entirely
    # (including `verdicts` absent altogether while a tier is enabled) is the
    # silent drop this rule exists to catch, not merely the mirror image of
    # the forward check below.
    for tier in sorted(enabled_set):
        if tier not in verdict_map:
            yield (
                f"tier {tier!r} is in tiers_enabled but verification.verdicts has no entry "
                f"for it; an unavailable tier still needs its own UNAVAILABLE entry, never "
                f"a silent absence"
            )

    for tier, entry in verdict_map.items():
        if tier not in enabled_set:
            yield (
                f"verification.verdicts has an entry for tier {tier!r}, which is not in "
                f"tiers_enabled {sorted(enabled_set)}; a verdict for a tier never requested "
                f"is refused, not silently accepted"
            )
            continue
        if not isinstance(entry, dict):
            yield f"verdict for tier {tier!r} is not an object"
            continue
        status = entry.get("status")
        if status not in PROTOCOL_STATUSES:
            yield (
                f"verdict for tier {tier!r} reports status {status!r}, "
                f"not one of {list(PROTOCOL_STATUSES)}"
            )
        elif status == "UNAVAILABLE" and not _nonempty_str(entry.get("reason")):
            yield f"verdict for tier {tier!r} is UNAVAILABLE without stating why"
        if not isinstance(entry.get("criteria"), list):
            yield f"verdict for tier {tier!r} carries no criteria list"
    disagreement = verification.get("disagreement")
    if disagreement is None:
        return
    if not isinstance(disagreement, dict) or not isinstance(disagreement.get("available"), bool):
        yield "verification.disagreement, when present, must state a boolean 'available'"
    elif disagreement["available"] is False and not _nonempty_str(disagreement.get("reason")):
        yield "verification.disagreement is unavailable without stating why"


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


#: `agent-observation`'s schema is CLOSED and TYPED at every level (#106): an
#: unknown key is refused, a missing key is refused (silence is not absence),
#: and every value must have its declared type - a key-only closure let an
#: object ride in a scalar field (codex review). Every field below is a fact the
#: controller derived; none is a place a credential or transcript text could be
#: copied into. A new observation field has to be named here before it can be
#: recorded, which fails loudly (the finding names the key).
AGENT_OBSERVATION_STATUSES = ("observed", "unknown", "not-observed")
_AO_DETECTION = ("structural", "heuristic")
#: The graded statuses that ARE verdicts. Only these must follow from the
#: record's own criteria; the grader reports the others (a backend it could not
#: reach, say) without criteria that derive to them.
_AO_VERDICTS = ("PASS", "FAIL")


def _is_bool(v: object) -> bool:
    return isinstance(v, bool)


def _is_count(v: object) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def _is_opt(check: Callable[[object], bool]) -> Callable[[object], bool]:
    return lambda v: v is None or check(v)


def _is_text(v: object) -> bool:
    return isinstance(v, str)


def _is_names(v: object) -> bool:
    return _str_list(v) is not None


def _is_count_map(v: object) -> bool:
    return isinstance(v, dict) and all(isinstance(k, str) and _is_count(n) for k, n in v.items())


_Spec = dict[str, tuple[Callable[[object], bool], str]]
_AO_TOP: _Spec = {
    "version": (lambda v: True, "checked by record-envelope"),
    "kind": (lambda v: True, "checked by record-envelope"),
    "producer": (lambda v: True, "checked by producer-authority"),
    "attempt_id": (lambda v: True, "checked by attempt-binding"),
    "trial_id": (lambda v: True, "checked by attempt-binding"),
    "client": (_nonempty_str, "a non-empty client name"),
    "status": (lambda v: v in AGENT_OBSERVATION_STATUSES, f"one of {list(AGENT_OBSERVATION_STATUSES)}"),
    "reason": (_is_opt(_is_text), "text or null"),
    "transcript": (lambda v: v is None or isinstance(v, dict), "an object or null"),
    "credential": (lambda v: isinstance(v, dict), "an object"),
    "grading": (lambda v: isinstance(v, dict), "an object"),
}
_AO_TRANSCRIPT: _Spec = {
    "files_found": (_is_count, "a non-negative integer"),
    "prompt_delivered": (_is_bool, "a boolean"),
    "prompt_delivery_reason": (_is_opt(_is_text), "text or null"),
    "canary_satisfied": (_is_bool, "a boolean"),
    "canary_reason": (_is_opt(_is_text), "text or null"),
    "skill_invocations": (_is_names, "a list of skill names"),
    "skill_invocation_detection": (lambda v: v in _AO_DETECTION, f"one of {list(_AO_DETECTION)}"),
    "skills_listed": (_is_opt(_is_names), "a list of skill names or null"),
    "skills_listed_source": (_is_text, "text"),
    "grading_eligible": (_is_bool, "a boolean"),
    "census": (lambda v: v is None or isinstance(v, dict), "an object or null"),
}
_AO_CENSUS: _Spec = {
    "client_version": (_is_opt(_is_text), "text or null"),
    "model": (_is_opt(_is_text), "text or null"),
    "line_types": (_is_opt(_is_count_map), "a map of line type to count, or null"),
    "unrecognized_types": (_is_opt(_is_names), "a list of type names or null"),
    "response_items_inspected": (_is_opt(_is_count), "a non-negative integer or null"),
    "error": (_is_opt(_is_text), "text or null"),
}
_AO_CREDENTIAL: _Spec = {
    "delivered": (_is_opt(_is_bool), "a boolean or null"),
    "source": (_is_opt(_is_text), "text or null"),
    "remaining_seconds_at_launch": (_is_opt(_is_count), "a non-negative integer or null"),
    "refresh_observed_in_container": (_is_opt(_is_bool), "a boolean or null"),
}
_AO_GRADING: _Spec = {
    "grader_supplied": (_is_bool, "a boolean"),
    "eligible": (_is_bool, "a boolean"),
    "blocked_reason": (_is_opt(_nonempty_str), "non-empty text or null"),
    "graded_status": (_is_opt(lambda v: v in PROTOCOL_STATUSES), f"one of {list(PROTOCOL_STATUSES)} or null"),
    "category": (_is_opt(_is_text), "text or null"),
    "criteria": (lambda v: v is None or isinstance(v, list), "a list or null"),
}
_AO_CRITERION: _Spec = {
    "id": (_nonempty_str, "a non-empty id"),
    # Literal booleans only: `derive_status` selects `mandatory is True`, so a
    # "true" string or a 1 would silently drop a VIOLATED criterion out of the
    # derivation - the same hole `criterion_vocabulary` closes for results.
    "mandatory": (_is_bool, "a boolean"),
    "outcome": (lambda v: v in CRITERION_OUTCOMES, f"one of {list(CRITERION_OUTCOMES)}"),
}


def _typed(value: object, spec: _Spec, where: str) -> Iterator[str]:
    if not isinstance(value, dict):
        yield f"{where} is not an object"
        return
    for key in sorted(set(value) - set(spec)):
        yield f"{where} carries unknown field {key!r}; the schema is closed - name it in records.py first"
    for key, (check, expected) in spec.items():
        if key not in value:
            yield f"{where} has no {key!r}; silence is not absence - write null where nothing was observed"
        elif not check(value[key]):
            yield f"{where}.{key} is {value[key]!r}, not {expected}"


def agent_observation(record: Record) -> Iterator[str]:
    """What the controller concluded from a real agent's transcript, for one
    attempt (#106). Checked for SHAPE - closed, complete and typed at every
    level - and for the facts that must agree inside the record:

      - positive transcript conclusions (prompt delivered, canary satisfied)
        rest on exactly ONE transcript file - the driver reads nothing
        otherwise, so a record claiming them from zero or two files concludes
        more than its own population supports;
      - `grading_eligible` is exactly `prompt_delivered AND canary_satisfied`;
      - a grader that was supplied either graded (a status) or was blocked (a
        reason), never both and never neither;
      - a PASS or FAIL copied here follows from the criteria copied with it
        (`derive_status`), so the audit copy cannot say more than its evidence.

    A `status` other than `observed` names its reason and carries no transcript
    conclusions: an attempt whose transcript was never read has none.
    """
    if record.parse_error is not None or record.kind != AGENT_OBSERVATION:
        return
    data = record.data
    yield from _typed(data, _AO_TOP, "the record")
    status = data.get("status")
    if status in AGENT_OBSERVATION_STATUSES and status != "observed" and not _nonempty_str(data.get("reason")):
        yield f"status {status!r} gives no reason; an unobserved attempt must say why"

    transcript = data.get("transcript")
    eligible_observed = False
    if status == "observed":
        if not isinstance(transcript, dict):
            yield "status observed, but no transcript conclusions are recorded"
        else:
            yield from _typed(transcript, _AO_TRANSCRIPT, "transcript")
            prompt, canary = transcript.get("prompt_delivered"), transcript.get("canary_satisfied")
            eligible, files = transcript.get("grading_eligible"), transcript.get("files_found")
            if (prompt is True or canary is True) and files != 1:
                yield (
                    f"transcript claims prompt_delivered={prompt} / canary_satisfied={canary} from "
                    f"{files!r} transcript files; a conclusion needs exactly one transcript to rest on"
                )
            if _is_bool(prompt) and _is_bool(canary) and _is_bool(eligible):
                if eligible != (prompt and canary):
                    yield (
                        f"transcript.grading_eligible is {eligible}, but prompt_delivered={prompt} "
                        f"and canary_satisfied={canary}; eligibility is exactly both"
                    )
                eligible_observed = eligible is True
            census = transcript.get("census")
            if isinstance(census, dict):
                yield from _typed(census, _AO_CENSUS, "transcript.census")
    elif transcript is not None:
        yield f"status {status!r}, but transcript conclusions are recorded; nothing was observed to conclude from"

    credential = data.get("credential")
    if isinstance(credential, dict):
        yield from _typed(credential, _AO_CREDENTIAL, "credential")

    grading = data.get("grading")
    if not isinstance(grading, dict):
        return
    yield from _typed(grading, _AO_GRADING, "grading")
    supplied, eligible = grading.get("grader_supplied"), grading.get("eligible")
    blocked, graded = grading.get("blocked_reason"), grading.get("graded_status")
    if _is_bool(eligible) and eligible != eligible_observed:
        yield (
            f"grading.eligible is {eligible}, but the transcript conclusions make it {eligible_observed}; "
            f"an attempt is eligible only when observed prompt and canary both hold"
        )
    if supplied is True and (graded is None) == (blocked is None):
        yield (
            "a grader was supplied, so the attempt was either graded or blocked from grading - "
            f"this record says graded_status={graded!r} and blocked_reason={blocked!r}"
        )
    if supplied is False and (graded is not None or blocked is not None):
        yield "no grader was supplied, yet the record carries a grade or a blocked reason"
    criteria = grading.get("criteria")
    if isinstance(criteria, list):
        for index, criterion in enumerate(criteria):
            yield from _typed(criterion, _AO_CRITERION, f"grading.criteria[{index}]")
    if graded is not None:
        if eligible is not True:
            yield "a graded status on an attempt that was not eligible for grading"
        if not isinstance(criteria, list):
            yield "a graded status with no criteria; the copy cannot be checked against its evidence"
        elif graded in _AO_VERDICTS:
            derived = derive_status(Record(path=record.path, data={"criteria": criteria}))
            if derived != graded:
                yield f"grading.graded_status is {graded}, but its own criteria derive {derived}"


def _pilot_report_split(entry: dict[str, object], where: str, field_name: str) -> Iterator[str]:
    """One cost/time split (`cost_usd` or `time_seconds`): EXACTLY the four
    keys `PILOT_REPORT_SPLIT_KEYS`, each a non-negative number or the literal
    `"UNKNOWN"` - a missing key is refused rather than read as zero."""
    split = entry.get(field_name)
    if not isinstance(split, dict):
        yield f"{where}: {field_name} is not an object"
        return
    unknown_keys = set(split) - set(PILOT_REPORT_SPLIT_KEYS)
    if unknown_keys:
        yield f"{where}: {field_name} carries unknown key(s) {sorted(unknown_keys)}"
    numeric: dict[str, float] = {}
    for key in PILOT_REPORT_SPLIT_KEYS:
        if key not in split:
            yield f"{where}: {field_name} has no {key!r}"
            continue
        value = split[key]
        if value == "UNKNOWN":
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            yield f"{where}: {field_name}.{key} is {value!r}, not a non-negative number or 'UNKNOWN'"
            continue
        numeric[key] = value
    # Consistency only when every component is a real number - an "UNKNOWN"
    # anywhere makes the sum unverifiable, not wrong.
    if set(numeric) == set(PILOT_REPORT_SPLIT_KEYS):
        parts_total = numeric["setup"] + numeric["agent"] + numeric["grading"]
        if abs(parts_total - numeric["total"]) > 1e-9:
            yield (
                f"{where}: {field_name} total {numeric['total']} does not equal "
                f"setup+agent+grading ({parts_total})"
            )


def pilot_report(record: Record) -> Iterator[str]:
    """The evidence report a completed pilot's acceptance requires (#12): every
    scheduled attempt's disposition, per-criterion success, uncertainty,
    intervention count, and a cost/time split into setup, agent and grading -
    with missing values explicit, never a silent absence.

    Whether every SCHEDULED attempt (from the ledger) appears here at all is a
    bundle fact (`ledger_binding`'s pilot-report check, #12) - this rule only
    checks each entry's own shape, exactly as `observation_coverage` checks a
    stream's shape while `ledger_binding` checks it against the receipt.
    """
    if record.parse_error is not None or record.kind != PILOT_REPORT:
        return
    attempts = record.data.get("attempts")
    if not isinstance(attempts, list) or not attempts:
        yield "pilot report names no attempts; an empty report is refused, not passed"
        return
    seen_ids: set[str] = set()
    for index, entry in enumerate(attempts):
        where = f"attempts[{index}]"
        if not isinstance(entry, dict):
            yield f"{where} is not an object"
            continue
        attempt_id = entry.get("attempt_id")
        if not _nonempty_str(attempt_id):
            yield f"{where}: no attempt_id"
        elif attempt_id in seen_ids:
            yield f"{where}: attempt_id {attempt_id!r} appears more than once"
        else:
            seen_ids.add(attempt_id)  # type: ignore[arg-type]
        if not _nonempty_str(entry.get("trial_id")):
            yield f"{where}: no trial_id"
        disposition = entry.get("disposition")
        if disposition not in DISPOSITIONS:
            yield f"{where}: disposition {disposition!r} is not one of {list(DISPOSITIONS)}"
        criteria = entry.get("criteria")
        if not isinstance(criteria, list):
            yield f"{where}: no criteria list"
        else:
            for c_index, criterion in enumerate(criteria):
                if not isinstance(criterion, dict) or not _nonempty_str(criterion.get("id")):
                    yield f"{where}: criteria[{c_index}] has no id"
                elif criterion.get("outcome") not in CRITERION_OUTCOMES:
                    yield f"{where}: criteria[{c_index}] outcome {criterion.get('outcome')!r} is not one of {list(CRITERION_OUTCOMES)}"
        if not _nonempty_str(entry.get("uncertainty")):
            yield f"{where}: no uncertainty - explicit, even when there is none to report (e.g. 'none')"
        interventions = entry.get("interventions")
        if isinstance(interventions, bool) or not isinstance(interventions, int) or interventions < 0:
            yield f"{where}: interventions is {interventions!r}, not a non-negative integer"
        yield from _pilot_report_split(entry, where, "cost_usd")
        yield from _pilot_report_split(entry, where, "time_seconds")


def _skill_evidence_lifecycle_fact(entry: dict[str, object], where: str, name: str) -> Iterator[str]:
    """One of `lifecycle.{listed,read_observed,execution_observed}` (#268): a
    USAGE fact, never a compliance outcome, so it uses `SKILL_EVIDENCE_CONFIRMATION`
    and never `CRITERION_OUTCOMES`. `CONFIRMED`/`NOT_CONFIRMED` must cite `evidence`
    (a reference already present in this attempt's own bundle - `ledger_binding`
    checks that it actually is, the same way it already checks `graded_digests`);
    `UNKNOWN` must say why, and carries no evidence - an `UNKNOWN` with an
    evidence reference would be a confirmed fact wearing an unknown's label.
    """
    fact = entry.get(name)
    if not isinstance(fact, dict):
        yield f"{where}: lifecycle.{name} is not an object"
        return
    status = fact.get("status")
    if status not in SKILL_EVIDENCE_CONFIRMATION:
        yield (
            f"{where}: lifecycle.{name} has status {status!r}, not one of "
            f"{list(SKILL_EVIDENCE_CONFIRMATION)}"
        )
        return
    if status == "UNKNOWN":
        if not _nonempty_str(fact.get("reason")):
            yield f"{where}: lifecycle.{name} is UNKNOWN without a reason"
        if "evidence" in fact:
            yield f"{where}: lifecycle.{name} is UNKNOWN but carries an evidence reference"
    else:
        evidence = fact.get("evidence")
        if not isinstance(evidence, dict) or not _nonempty_str(evidence.get("digest")):
            yield (
                f"{where}: lifecycle.{name} is {status} but cites no evidence digest; "
                f"a confirmed usage fact names what confirms it"
            )


def skill_evidence(record: Record) -> Iterator[str]:
    """Per-attempt, per-skill attribution (#268): skill identity, invocation
    lineage, criterion ownership and external-evidence reconciliation.

    Three things this rule does NOT check, because another rule or record owns
    them: that `skill.path` was actually installed by this attempt's receipt, and
    that `criteria_owned`/`external_evidence.artifact_ref` agree with this
    attempt's own `verified-result`/`artifact-manifest` - all three need records
    this one does not carry, so they are `ledger_binding`'s findings, exactly as
    `_skill_invocation_binding` already draws that line for `skill-invocations`.
    """
    if record.parse_error is not None or record.kind != SKILL_EVIDENCE:
        return
    skills = record.data.get("skills")
    if not isinstance(skills, list) or not skills:
        yield "skill-evidence names no skills; an empty record is refused, not passed"
        return

    paths: list[str] = [
        s["skill"]["path"] for s in skills
        if isinstance(s, dict) and isinstance(s.get("skill"), dict) and _nonempty_str(s["skill"].get("path"))
    ]
    seen_paths: set[str] = set()
    #: child path -> parent path, for well-formed child links only (self and
    #: dangling parents are already reported above and excluded here, so a
    #: cycle this dict can walk is a cycle among otherwise-valid entries).
    child_links: dict[str, str] = {}
    for index, entry in enumerate(skills):
        where = f"skills[{index}]"
        if not isinstance(entry, dict):
            yield f"{where} is not an object"
            continue

        skill = entry.get("skill")
        path = skill.get("path") if isinstance(skill, dict) else None
        if not isinstance(skill, dict) or not _nonempty_str(path):
            yield f"{where}: no skill.path"
        elif path in seen_paths:
            yield f"{where}: skill.path {path!r} appears more than once in this record"
        else:
            seen_paths.add(path)  # type: ignore[arg-type]
        if isinstance(skill, dict):
            for digest_key in ("body_digest", "description_digest"):
                if digest_key in skill and not _nonempty_str(skill.get(digest_key)):
                    yield f"{where}: skill.{digest_key} is present but empty"

        invocation = entry.get("invocation")
        lineage = invocation.get("lineage") if isinstance(invocation, dict) else None
        if lineage not in SKILL_EVIDENCE_LINEAGE:
            yield (
                f"{where}: invocation.lineage is {lineage!r}, not one of "
                f"{list(SKILL_EVIDENCE_LINEAGE)}"
            )
        elif lineage == "child":
            parent = invocation.get("parent_path") if isinstance(invocation, dict) else None
            if not _nonempty_str(parent):
                yield f"{where}: invocation.lineage is 'child' but names no parent_path"
            elif parent == path:
                yield f"{where}: invocation.parent_path names itself"
            elif parent not in paths:
                yield (
                    f"{where}: invocation.parent_path {parent!r} is not a skill.path "
                    f"anywhere in this record"
                )
            elif isinstance(path, str):
                child_links[path] = parent  # type: ignore[assignment]
        elif isinstance(invocation, dict) and "parent_path" in invocation:
            yield f"{where}: invocation.lineage is 'root' but carries a parent_path"

        lifecycle = entry.get("lifecycle")
        if not isinstance(lifecycle, dict):
            yield f"{where}: no lifecycle object"
        else:
            for name in ("listed", "read_observed", "execution_observed"):
                yield from _skill_evidence_lifecycle_fact(lifecycle, where, name)

        criteria_owned = entry.get("criteria_owned")
        if not isinstance(criteria_owned, list):
            yield f"{where}: criteria_owned is not a list"
        else:
            for c_index, criterion in enumerate(criteria_owned):
                c_where = f"{where}.criteria_owned[{c_index}]"
                if not isinstance(criterion, dict) or not _nonempty_str(criterion.get("id")):
                    yield f"{c_where}: no id"
                    continue
                if criterion.get("outcome") not in CRITERION_OUTCOMES:
                    yield (
                        f"{c_where}: outcome {criterion.get('outcome')!r} is not one of "
                        f"{list(CRITERION_OUTCOMES)}"
                    )
                if not isinstance(criterion.get("shared"), bool):
                    yield f"{c_where}: shared is {criterion.get('shared')!r}, not a JSON boolean"

        external = entry.get("external_evidence")
        if not isinstance(external, dict):
            yield f"{where}: no external_evidence object"
            continue
        present = external.get("present")
        if not isinstance(present, bool):
            yield f"{where}: external_evidence.present is {present!r}, not a JSON boolean"
            continue
        reconciliation = external.get("reconciliation")
        if reconciliation not in SKILL_EVIDENCE_RECONCILIATION:
            yield (
                f"{where}: external_evidence.reconciliation is {reconciliation!r}, not "
                f"one of {list(SKILL_EVIDENCE_RECONCILIATION)}"
            )
        elif present and reconciliation == "absent":
            yield f"{where}: external_evidence.present is true but reconciliation is 'absent'"
        elif not present and reconciliation != "absent":
            yield (
                f"{where}: external_evidence.present is false but reconciliation is "
                f"{reconciliation!r}, not 'absent' - no evidence is not evidence of a "
                f"disagreement"
            )
        if reconciliation not in ("matched", "absent") and not _nonempty_str(external.get("reason")):
            yield f"{where}: external_evidence.reconciliation is {reconciliation!r} without a reason"
        if present:
            source = external.get("source")
            if source not in EXTERNAL_EVIDENCE_SOURCES:
                yield (
                    f"{where}: external_evidence.source {source!r} is not one of "
                    f"{list(EXTERNAL_EVIDENCE_SOURCES)} - unknown schema"
                )
            ref = external.get("artifact_ref")
            if not isinstance(ref, dict) or not _nonempty_str(ref.get("digest")):
                yield f"{where}: external_evidence.present is true but names no artifact_ref digest"
        elif "source" in external or "artifact_ref" in external:
            yield f"{where}: external_evidence.present is false but names a source or artifact_ref"

    # A chain of otherwise-valid child links can still loop back on itself with
    # no root at the end (A's parent is B, B's parent is A) - neither entry is
    # self-referential and both parents resolve, so the per-entry checks above
    # cannot see it. Reuses `_chain_root`, the same walk `lineage` (bundle rule)
    # already uses for retry/regrade chains.
    reported_cycle: set[str] = set()
    for path in sorted(child_links):
        root, chain = _chain_root(path, child_links)
        if root is None and not reported_cycle & set(chain):
            reported_cycle.update(chain)
            yield (
                f"invocation lineage forms a cycle ({' -> '.join(chain)}); no root "
                f"skill exists for it"
            )


# ---------------------------------------------------------------------------
# Bundle rules: facts that exist only BETWEEN records. Each is paired with a
# committed control whose bad and good cases are bundle directories.
# ---------------------------------------------------------------------------

def _ident(value: object, *keys: str) -> tuple[object, ...]:
    return tuple(value.get(k) for k in keys) if isinstance(value, dict) else ()


def _skill_invocation_binding(
    record: Record, where: str, installed: set[str] | None
) -> Iterator[str]:
    """A `skill-invocations` row must name a skill the attempt's own receipt
    installed. No receipt for this attempt in the bundle is a silent skip here:
    that gap is `attempt-accounting`'s finding, not a mismatch this rule can call.
    A malformed `skills` list is `observation_coverage`'s finding; this rule only
    checks well-formed rows against the receipt.

    The REVERSE direction too (issue #26, folded in from the Nit Store):
    under `coverage: "complete"`, every path the receipt installed must have
    a row - `_skill_invocations` (the per-record check) only refuses a
    `"complete"` stream that names NO skills at all, never one that is
    missing some of them, so a second installed skill with no invocation row
    passed clean (reproduced at `70ead2c`, exit 0, 0 errors). "Complete"
    means every installed path was seen, not merely that the stream is
    non-empty - a silent skill is not an accounted-for one.
    """
    if installed is None:
        return
    observations = record.data.get("observations")
    if not isinstance(observations, list):
        return
    for entry in observations:
        if not isinstance(entry, dict) or entry.get("stream") != SKILL_INVOCATIONS:
            continue
        skills = entry.get("skills")
        if not isinstance(skills, list):
            continue
        named: set[str] = set()
        for row in skills:
            path = row.get("path") if isinstance(row, dict) else None
            if not isinstance(path, str) or not path:
                continue
            named.add(path)
            if path not in installed:
                yield (
                    f"{where}: skill-invocations names {path!r}, which this "
                    f"attempt's installation receipt never installed"
                )
        if entry.get("coverage") == "complete":
            missing = sorted(installed - named)
            if missing:
                yield (
                    f"{where}: skill-invocations declares complete coverage but names no row "
                    f"for installed path(s) {missing} - a silent skill is not an uninvoked one"
                )


def _skill_invocations_required_but_absent(record: Record, where: str, trial: dict[str, object]) -> Iterator[str]:
    """#39's "left to #26" control: when the attempt's TRIAL declares
    `case.observes_selection: true` (#26), its manifest's `observations`
    must include a `skill-invocations` stream - silence no longer means "not
    declared", it means the case's own contract was not met. A trial that
    does not declare it (the default) requires nothing here; `#39`'s stream
    stays optional exactly as `records.md` states.
    """
    case = trial.get("case")
    if not isinstance(case, dict) or case.get("observes_selection") is not True:
        return
    observations = record.data.get("observations")
    entries = observations if isinstance(observations, list) else []
    if not any(isinstance(e, dict) and e.get("stream") == SKILL_INVOCATIONS for e in entries):
        yield (
            f"{where}: this attempt's trial declares case.observes_selection: true, "
            f"so a 'skill-invocations' observation is required, but none is present"
        )


def _skill_evidence_binding(
    record: Record,
    where: str,
    installed: set[str] | None,
    criteria: dict[str, set[object]] | None,
    captured: set[str] | None,
) -> Iterator[str]:
    """`skill-evidence` (#268) cross-checked against the three OTHER records of
    its own attempt - the one thing a lone `skill-evidence` record cannot do
    for itself, exactly as `_skill_invocation_binding` does for `skill-invocations`.

    - `skill.path` against the receipt's own `installed` paths: a path this
      attempt never installed is a skill it never had.
    - `criteria_owned[].outcome` against every outcome this attempt's own
      `verified-result`(s) actually recorded for that id: a copy that matches
      NONE of them is a **forged status** - the "Forged status" golden case.
    - `external_evidence.artifact_ref.digest` against the manifest's captured
      digests: one that was never captured is an **altered** artifact.

    No receipt, no result or no manifest at all for this attempt is NOT this
    rule's finding - that gap belongs to `attempt_accounting`, the same
    division `_skill_invocation_binding` already draws.
    """
    skills = record.data.get("skills")
    if not isinstance(skills, list):
        return
    for index, entry in enumerate(skills):
        if not isinstance(entry, dict):
            continue
        e_where = f"{where} skills[{index}]"
        skill = entry.get("skill")
        path = skill.get("path") if isinstance(skill, dict) else None
        if installed is not None and isinstance(path, str) and path and path not in installed:
            yield f"{e_where}: names {path!r}, which this attempt's installation receipt never installed"

        if criteria is not None:
            owned = entry.get("criteria_owned")
            for c in owned if isinstance(owned, list) else []:
                if not isinstance(c, dict):
                    continue
                c_id, outcome = c.get("id"), c.get("outcome")
                if not isinstance(c_id, str) or not c_id:
                    continue
                known = criteria.get(c_id)
                if known is None:
                    yield f"{e_where}: criteria_owned names {c_id!r}, which this attempt's verified-result never defines"
                elif outcome not in known:
                    yield (
                        f"{e_where}: criteria_owned claims {c_id!r} is {outcome!r}, but this "
                        f"attempt's verified-result never recorded that outcome for it - a forged status"
                    )

        if captured is not None:
            external = entry.get("external_evidence")
            if isinstance(external, dict) and external.get("present") is True:
                ref = external.get("artifact_ref")
                digest = ref.get("digest") if isinstance(ref, dict) else None
                if isinstance(digest, str) and digest and digest not in captured:
                    yield (
                        f"{e_where}: external_evidence.artifact_ref cites {digest!r}, "
                        f"which no manifest for this attempt captured - an altered artifact"
                    )


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
        nobody captured - an altered or substituted artifact;
      - a manifest's `skill-invocations` stream (#39) names a skill the attempt's
        own installation receipt never installed. `observation_coverage` checks the
        stream's own shape; only this rule has the receipt to check it against;
      - a manifest for a trial whose `case.observes_selection` is `true` (#26)
        carries no `skill-invocations` stream at all - #39's "left to #26"
        control, closing it: the stream is required when the case says so,
        and only this rule has the trial's case identity to check it against;
      - a `pilot-report` (#12) that omits a scheduled attempt, or names one
        the ledger never planned - only this rule has the ledger's own
        planned population to check a report against; `pilot_report` checks
        each entry's own shape, not which attempts are present at all.
      - a `skill-evidence` (#268) entry names a `skill.path` the attempt's own
        installation receipt never installed; names a `criteria_owned` id its
        attempt's own `verified-result` does not define, or copies an outcome
        that disagrees with that criterion's real one there (a **forged
        status**); or cites an `external_evidence.artifact_ref` digest its
        attempt's manifest did not capture (an **altered** artifact, the same
        finding a `verified-result`'s `graded_digests` already gets).
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
    installed_paths: dict[str, set[str]] = {}
    for receipt in bundle.of_kind(INSTALLATION_RECEIPT):
        entries = receipt.data.get("installed")
        paths = {
            e["path"] for e in entries or []
            if isinstance(e, dict) and _nonempty_str(e.get("path"))
        } if isinstance(entries, list) else set()
        installed_paths.setdefault(receipt.attempt_id, set()).update(paths)
    criteria_by_attempt: dict[str, dict[str, set[object]]] = {}
    for result in bundle.of_kind(VERIFIED_RESULT):
        criteria = result.data.get("criteria")
        if not isinstance(criteria, list):
            continue
        bucket = criteria_by_attempt.setdefault(result.attempt_id, {})
        for c in criteria:
            if isinstance(c, dict) and _nonempty_str(c.get("id")):
                bucket.setdefault(c["id"], set()).add(c.get("outcome"))

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
        if record.kind == ARTIFACT_MANIFEST:
            yield from _skill_invocation_binding(record, where, installed_paths.get(record.attempt_id))
            yield from _skill_invocations_required_but_absent(record, where, trial)
        if record.kind == SKILL_EVIDENCE:
            yield from _skill_evidence_binding(
                record, where,
                installed_paths.get(record.attempt_id),
                criteria_by_attempt.get(record.attempt_id),
                captured.get(record.attempt_id),
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

    for report in bundle.of_kind(PILOT_REPORT):
        attempts = report.data.get("attempts")
        entries = attempts if isinstance(attempts, list) else []
        # Only a non-empty STRING id can ever match a planned attempt_id (also
        # a string, from _ledger_attempts). An unhashable id (a list or dict -
        # `pilot_report`'s own rule already flags it as malformed) must not
        # reach a set literal here: building `{..., [], ...}` raises
        # TypeError immediately, crashing this rule instead of reporting a
        # finding (found by cross-model review).
        reported_ids = {e["attempt_id"] for e in entries if isinstance(e, dict) and _nonempty_str(e.get("attempt_id"))}
        where = f"{report.path.name} ({report.kind})"
        for attempt_id in plan:
            if attempt_id not in reported_ids:
                yield f"{where}: omits scheduled attempt {attempt_id!r}"
        for reported_id in reported_ids - set(plan):
            yield f"{where}: reports attempt {reported_id!r}, which the ledger never planned"


def unique_ids(bundle: Bundle) -> Iterator[str]:
    """Identifiers identify. interfaces.md makes duplicate/conflicting IDs an
    explicit validation failure, never verified success.

    An attempt has at most one receipt, one manifest, one lifecycle and one
    `skill-evidence` record: a second one is a conflicting account of the same
    attempt, and nothing here can say which is true. Results may be several (a
    regrade is a new result), but each has its own `result_id`.
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
    for kind in (INSTALLATION_RECEIPT, ARTIFACT_MANIFEST, ATTEMPT_LIFECYCLE, AGENT_OBSERVATION, SKILL_EVIDENCE):
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

    The one stand-in for the receipt (#139): an agent-trial result that declares
    `verification.readiness_source: agent-observation`. It is accepted in place
    of a receipt only when the bundle holds that attempt's `agent-observation`,
    observed and eligible for grading, and when the result's own
    `installation-ready` criterion is UNKNOWN - the observation shows the
    attempt ran as planned, never that the subject was installed and
    discovered, so it may account for the grade but never ready a PASS.
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
    observations = {r.attempt_id: r for r in bundle.of_kind(AGENT_OBSERVATION)}
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
            if attempt_id not in manifests:
                yield f"attempt {attempt_id!r} was graded without its artifact manifest"
            yield from _receipt_stand_in(attempt_id, graded, observations.get(attempt_id), attempt_id in receipts)


#: `verification.readiness_source` on a result graded without a receipt (#139);
#: `skillc.verify.AGENT_OBSERVATION_READINESS` is this constant.
OBSERVATION_STAND_IN = "agent-observation"
_READINESS_CRITERION = "installation-ready"


def _receipt_stand_in(
    attempt_id: str, graded: list[Record], observation: Record | None, has_receipt: bool,
) -> Iterator[str]:
    """Why a graded result is not accounted for by its readiness evidence, if
    it is not. A result declaring the observation stand-in is held to it
    WHETHER OR NOT a receipt also exists (codex review): a receipt beside it
    must not let the stand-in claim the readiness it never establishes."""
    for result in graded:
        verification = result.data.get("verification")
        source = verification.get("readiness_source") if isinstance(verification, dict) else None
        if source != OBSERVATION_STAND_IN:
            if not has_receipt:
                yield f"attempt {attempt_id!r} was graded without its installation receipt"
            continue
        criteria = result.data.get("criteria")
        readiness = [
            c for c in criteria if isinstance(c, dict) and c.get("id") == _READINESS_CRITERION
        ] if isinstance(criteria, list) else []
        # MANDATORY and UNKNOWN (codex review): an optional UNKNOWN criterion
        # drops out of `derive_status`, so a PASS would stand on no readiness.
        if [(c.get("mandatory"), c.get("outcome")) for c in readiness] != [(True, "UNKNOWN")]:
            yield (
                f"attempt {attempt_id!r}: {result.path.name} stands an agent-observation in for its receipt, "
                f"but its {_READINESS_CRITERION!r} criterion is not exactly one mandatory UNKNOWN; an "
                f"observation never establishes installation readiness, so it must still gate PASS"
            )
        if observation is None:
            yield (
                f"attempt {attempt_id!r}: {result.path.name} stands an agent-observation in for its "
                f"installation receipt, but the bundle holds no agent-observation for this attempt"
            )
            continue
        transcript = observation.data.get("transcript")
        eligible = isinstance(transcript, dict) and transcript.get("grading_eligible") is True
        if observation.data.get("status") != "observed" or not eligible:
            yield (
                f"attempt {attempt_id!r}: {result.path.name} stands {observation.path.name} in for its "
                f"receipt, but that observation is not an observed, grading-eligible attempt"
            )


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
