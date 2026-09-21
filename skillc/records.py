"""Evaluation records as checkable objects.

`docs/specs/evaluation-facility/interfaces.md` already names four contracts, their
producers and their independent checks, and already fixes the vocabularies:
criteria report SATISFIED / VIOLATED / UNKNOWN, and the assembler reports
PASS / FAIL / UNAVAILABLE / INCONCLUSIVE / NOT_RUN. This module does not invent
those. It gives two of the four rows an executable form - the artifact and
observation manifest, and the per-criterion verified result - so something can
refuse a malformed one.

WHAT VALIDATION ESTABLISHES, AND WHAT IT DOES NOT. A record that passes here is
WELL FORMED AND INTERNALLY CONSISTENT. It is not true. interfaces.md says it
plainly - "Structure checks establish that fields are well formed and
consistent" - and PLAN.md says "A valid JSON record, hash or echoed config alone
does not authenticate success." Every verdict this module emits names what it
examined, including the green ones, so a passing line cannot be quoted as
verification by someone skimming.

Stdlib only: this has to run in a slim CI image with no network (AGENTS.md).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

#: The envelope version this build understands. interfaces.md permits "a versioned
#: local envelope [that] can wrap an upstream record while preserving its raw bytes",
#: and makes incompatible versions an explicit validation failure - never a
#: best-effort read of a record written by a future build.
SUPPORTED_VERSION = 1

ARTIFACT_MANIFEST = "artifact-manifest"
VERIFIED_RESULT = "verified-result"
KINDS = (ARTIFACT_MANIFEST, VERIFIED_RESULT)

#: Fixed by interfaces.md, not chosen here.
CRITERION_OUTCOMES = ("SATISFIED", "VIOLATED", "UNKNOWN")
PROTOCOL_STATUSES = ("PASS", "FAIL", "UNAVAILABLE", "INCONCLUSIVE", "NOT_RUN")
#: Run states a record may DECLARE; the rest of the statuses are DERIVED and may
#: never be declared, which is what the forged-verdict rule exists to enforce.
DECLARABLE_RUN_STATES = ("UNAVAILABLE", "NOT_RUN")

WHAT_WAS_EXAMINED = (
    "structure and internal consistency only; nothing here establishes that the "
    "result is true"
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
# The rules. Each is paired with a committed control under controls/<id>/.
# ---------------------------------------------------------------------------

def record_envelope(record: Record) -> Iterator[str]:
    if record.parse_error is not None:
        yield f"unreadable record: {record.parse_error}"
        return
    version = record.data.get("version")
    if version is None:
        yield "no envelope version; an unversioned record cannot be read safely"
    elif not isinstance(version, int):
        yield f"envelope version is not an integer: {version!r}"
    elif version > SUPPORTED_VERSION:
        yield (
            f"envelope version {version} is newer than the supported "
            f"{SUPPORTED_VERSION}; refused rather than read on a guess"
        )
    if record.kind not in KINDS:
        yield f"unknown record kind {record.kind!r}; expected one of {list(KINDS)}"


def attempt_binding(record: Record) -> Iterator[str]:
    """The attempt reference this record is bound to.

    The identifier is OPAQUE here. It is issued by the trial ledger, which this
    slice does not own, so this rule checks that a record CITES one and that a
    record set agrees about it - not that the attempt exists. Staleness against a
    ledger is not decidable from a record alone and is not claimed.
    """
    if record.parse_error is not None:
        return
    if not record.attempt_id:
        yield "no attempt_id; the record is not bound to any attempt"
    elif not record.attempt_id.strip():
        yield "attempt_id is blank"


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
