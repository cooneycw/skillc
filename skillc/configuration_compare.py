"""Matched-configuration comparison (issue #13's other acceptance bullet):
compare two ALREADY-CAPTURED evidence records, refusing when they are not
a matched pair per docs/specs/evaluation-facility/protocol.md's "Collection
comparison" row ("Common eligible tasks and matched configuration" fixed,
"Collection A versus B" the deliberate difference).

Pure post-hoc analysis - no live agent call, no docker call, no new run
capability of its own. Reads two JSON files a caller already produced and
reports what they show; it does not produce evidence.

INPUT SHAPE (deliberately generic, review ruling: "JSON in, parse only the
fields you need, typed" - not literally `collection-run`'s or
`pilot-run`'s own internal envelope, which #13 does not name as the one
required source, and either could evolve independently of this contract).
Each side is a JSON object with:

    task_id, grader_revision, image_digest, client, model, timeout_seconds,
        collection: identity fields (see IDENTITY_FIELDS)
    outcome_dimensions: the `outcome_report.OutcomeReport.as_dict()` shape
        (issue #13 PR1) - reused as-is, not reinvented, so `from_collection_run`
        below, or a future `pilot-report` adapter, can plug straight in.
    provenance (optional): `{field: "recorded"|"asserted"}` for zero or more
        `IDENTITY_FIELDS` entries - an unmentioned field defaults to
        `ASSERTED` (review ruling: defaulting the other way would make the
        STRONGER claim by default, so a generic, hand-written record with
        no `provenance` block would silently assert every identity field
        was recorded, which is exactly what this module cannot check from
        JSON alone). `RECORDED` must be earned - a caller marks it only for
        a field an adapter actually read from a real, captured artifact;
        `from_collection_run` does this for every field a `collection-run`
        record now carries (skillc#188 closed the `image_digest`/
        `timeout_seconds` gap this module originally had to work around -
        see `from_collection_run`'s own docstring for the OBSERVED-not-
        merely-planned distinction that fix required for `image_digest`
        specifically), and leaves a field on the `ASSERTED` default only
        when a caller supplies it as a side-channel value the record itself
        does not carry (a pre-#188 record, for these two fields).
        `compare` surfaces this per side and flags any MATCHED field that
        is asserted on either side, so a comparison never reads as if a
        real record had proved a match the caller only asserted.

`task_id`/`grader_revision` deliberately collapse what an earlier draft of
this schema kept as FOUR fields (`task_id`, `task_revision`,
`grader_revision`, and an implied separate task identity) into two: this
codebase's real data model has exactly one `grader.json` per task, with one
`id` and one `revision` covering both - `verify.GraderDef`'s own contract,
not two independently-versioned things. Inventing a second "task revision"
distinct from the grader's own would have been a fact this codebase does
not track, found while building `from_collection_run` against REAL output
rather than fixtures written to this module's own schema (review finding).

`from_collection_run` adapts a REAL `collection-run` attempt's actual saved
artifacts into this shape - see its own docstring for exactly which fields
it reads from each artifact, how `image_digest`/`timeout_seconds` are
resolved now that `collection-run` records both (skillc#188), and why its
VERIFIED_RESULT record's own `criteria` field is the WRONG source for
`outcome_dimensions` (a real finding: it mixes in the verifier's own
readiness criterion, never a grader's). Building the matching adapter for
`pilot-report`'s own output is separate, later work, noted as such, not
included here.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .trial import Refused

#: The closed set of identity fields a comparison checks. Exactly ONE, named
#: by `--vary`, may legitimately differ between the two sides; every other
#: one must match or the comparison is refused. Not an open set: an unknown
#: field name is refused the same way an unknown grader.json key is refused
#: elsewhere in this codebase, rather than silently ignored.
IDENTITY_FIELDS = (
    "task_id", "grader_revision", "image_digest",
    "client", "model", "timeout_seconds", "collection",
)

#: A field's PROVENANCE (review ruling): `RECORDED` means this value came
#: from a real, captured artifact - a caller must EARN this by actually
#: having read it from one; `load_record` never assumes it. `ASSERTED`
#: means a caller SUPPLIED the value (never read from anything captured),
#: and it is `load_record`'s own default for any field a caller does not
#: mark otherwise - the default is the WEAKER claim on purpose, so a
#: generic record with no `provenance` block never silently claims more
#: than JSON alone can support. `from_collection_run` marks every field it
#: actually reads `RECORDED` and leaves `image_digest`/`timeout_seconds` on
#: the `ASSERTED` default, since neither is recorded by `collection-run`
#: today (skillc#188). The comparison output carries this per field so a
#: reader can never mistake "the record proved these match" for "the
#: caller asserted these match" - the two are different strengths of
#: evidence, and collapsing them would let an asserted-only match read as
#: if collection-run itself had recorded and confirmed it.
RECORDED = "recorded"
ASSERTED = "asserted"
_PROVENANCE_VALUES = (RECORDED, ASSERTED)


@dataclass(frozen=True)
class ConfigRecord:
    """One side of a comparison, as loaded from its own JSON file. Every
    `IDENTITY_FIELDS` entry is REQUIRED - missing one refuses the load
    entirely (review ruling: "a missing identity field on either side is a
    refusal, not a match: absent is not equal"), so there is no way to reach
    the comparison step already missing one.

    `provenance` covers every `IDENTITY_FIELDS` entry - a field a caller's
    JSON does not mention defaults to `ASSERTED` (see that constant's own
    comment for why, and `from_collection_run` for how a real adapter earns
    `RECORDED` instead)."""

    source: Path
    task_id: str
    grader_revision: str
    image_digest: str
    client: str
    model: str
    timeout_seconds: float
    collection: str
    outcome_dimensions: Mapping[str, object]
    provenance: Mapping[str, str]

    def identity(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in IDENTITY_FIELDS}


def load_record(path: Path) -> ConfigRecord:
    """Refuses (never silently defaults) on: unreadable/non-JSON, not an
    object, a missing identity field, an identity field of the wrong type,
    or a missing/malformed `outcome_dimensions`."""
    where = str(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise Refused(f"{where}: cannot read: {exc}") from None
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise Refused(f"{where}: not JSON: {exc}") from None
    if not isinstance(data, dict):
        raise Refused(f"{where}: not an object")
    missing = [f for f in IDENTITY_FIELDS if f not in data]
    if missing:
        raise Refused(f"{where}: missing identity field(s) {missing} - absent is not the same as matching")
    for field in IDENTITY_FIELDS:
        value = data[field]
        if field == "timeout_seconds":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise Refused(f"{where}: {field} must be a number, got {value!r}")
        elif not isinstance(value, str) or not value:
            raise Refused(f"{where}: {field} must be a non-empty string, got {value!r}")
    dimensions = data.get("outcome_dimensions")
    if not isinstance(dimensions, dict):
        raise Refused(f"{where}: outcome_dimensions must be an object")
    provenance_in = data.get("provenance", {})
    if not isinstance(provenance_in, dict):
        raise Refused(f"{where}: provenance must be an object")
    unknown_provenance_fields = set(provenance_in) - set(IDENTITY_FIELDS)
    if unknown_provenance_fields:
        raise Refused(f"{where}: provenance names field(s) {sorted(unknown_provenance_fields)} not in {list(IDENTITY_FIELDS)}")
    bad_provenance_values = {v for v in provenance_in.values() if v not in _PROVENANCE_VALUES}
    if bad_provenance_values:
        raise Refused(
            f"{where}: provenance has unknown value(s) {sorted(bad_provenance_values)}; "
            f"must be one of {list(_PROVENANCE_VALUES)}"
        )
    provenance = {field: provenance_in.get(field, ASSERTED) for field in IDENTITY_FIELDS}
    return ConfigRecord(
        source=path,
        task_id=data["task_id"], grader_revision=data["grader_revision"],
        image_digest=data["image_digest"],
        client=data["client"], model=data["model"], timeout_seconds=data["timeout_seconds"],
        collection=data["collection"], outcome_dimensions=dimensions, provenance=provenance,
    )


def compare(a: ConfigRecord, b: ConfigRecord, vary: str) -> dict[str, object]:
    """Refuses unless every `IDENTITY_FIELDS` entry EXCEPT `vary` matches
    between `a` and `b`. `vary` itself must be one of `IDENTITY_FIELDS` -
    naming an unknown field is refused, not silently accepted as "nothing
    to check there."

    On a genuine mismatch, the refusal names every mismatched field and
    both values, and states the alternative protocol.md's own comparison-
    arms section names: report a compatibility/product comparison instead
    of a causal claim, rather than silently comparing configurations that
    are not actually matched.

    The RETURNED comparison is descriptive only - one attempt per side
    (n=1 each) - and states that explicitly; no rate, no significance, no
    causal claim is computed or implied anywhere in this module."""
    if vary not in IDENTITY_FIELDS:
        raise Refused(f"--vary {vary!r} is not one of {list(IDENTITY_FIELDS)}")
    mismatched = [
        f for f in IDENTITY_FIELDS
        if f != vary and getattr(a, f) != getattr(b, f)
    ]
    if mismatched:
        detail = "; ".join(f"{f}: a={getattr(a, f)!r} b={getattr(b, f)!r}" for f in mismatched)
        raise Refused(
            f"refusing a causal comparison between unmatched configurations ({detail}). "
            f"Per protocol.md: report a compatibility/product comparison instead of attributing "
            f"the difference to {vary!r}, or re-run with the mismatched field(s) actually matched."
        )
    dims_a = a.outcome_dimensions
    dims_b = b.outcome_dimensions
    all_dims = sorted(set(dims_a) | set(dims_b))
    per_dimension = {}
    for dim in all_dims:
        entry_a = dims_a.get(dim)
        entry_b = dims_b.get(dim)
        per_dimension[dim] = {
            "a": entry_a.get("verdict") if isinstance(entry_a, dict) else None,
            "b": entry_b.get("verdict") if isinstance(entry_b, dict) else None,
        }
    matched_fields = [f for f in IDENTITY_FIELDS if f != vary]
    # Review ruling: a matched field must not read as if the RECORD proved
    # the match when a caller only ASSERTED one (or both) sides' value -
    # from_collection_run's image_digest/timeout_seconds, skillc#188. Named
    # explicitly, never folded silently into "matched_fields" as if every
    # entry there carried the same strength of evidence.
    unverified_matched_fields = [
        f for f in matched_fields
        if a.provenance.get(f, ASSERTED) == ASSERTED or b.provenance.get(f, ASSERTED) == ASSERTED
    ]
    result: dict[str, object] = {
        "vary": vary,
        "matched_fields": matched_fields,
        "a": {
            "source": str(a.source), "n": 1, vary: getattr(a, vary), "outcome_dimensions": dict(dims_a),
            "provenance": dict(a.provenance),
        },
        "b": {
            "source": str(b.source), "n": 1, vary: getattr(b, vary), "outcome_dimensions": dict(dims_b),
            "provenance": dict(b.provenance),
        },
        "per_dimension": per_dimension,
        "scope": (
            "descriptive only - one attempt per side (n=1 each); no rate, "
            "significance, or causal claim is supported by this comparison"
        ),
    }
    if unverified_matched_fields:
        result["unverified_matched_fields"] = unverified_matched_fields
        result["unverified_matched_fields_note"] = (
            f"{unverified_matched_fields} matched because a CALLER ASSERTED equal values, not because either "
            f"side's own record captured and confirmed it - see each side's own 'provenance'. This comparison "
            f"does not claim collection-run itself recorded that these fields actually matched."
        )
    return result


def from_collection_run(
    envelope: Mapping[str, object], verified_result: Mapping[str, object],
    outcome_dimensions: Mapping[str, object],
    *, image_digest: str | None = None, timeout_seconds: float | None = None,
) -> dict[str, object]:
    """Builds this module's own input shape from a REAL `collection-run`
    attempt's two actual saved artifacts:

    - `envelope`: `collection_conformance.evidence_envelope()`'s own dict
      (equivalently, `collection-run-record.json` read back) - for
      `client`, `collection` (its own `subject` field), `model`
      (`record.observation.transcript_model`), and - since skillc#188 -
      `image_digest`/`timeout_seconds` when present.
    - `verified_result`: one entry from a real `--evidence` export's
      `result-*.json` (`verify.py`'s VERIFIED_RESULT shape) - for
      `task_id`/`grader_revision` ONLY (its own `grader.id`/
      `grader.revision`). This function does NOT read its `criteria` field
      - a SECOND real finding, found the same way as the two missing
      identity fields below: `verified_result["criteria"]` is NOT the
      task's own criteria population. It carries the verifier's own
      `installation-ready` criterion mixed in alongside the grader's
      (`records.READINESS_CRITERION` - explicitly "the verifier's
      criterion, not a grader's", per `GraderDef.load()`'s own refusal if a
      grader ever tried to declare one). Bucketing that list directly would
      silently fold an UNKNOWN readiness check into #13's functional/
      constraint/integration dimensions, which is not what any of them mean.
      The right source is `collection_conformance`'s own per-attempt
      `result.record["graded"]["criteria"]` (task-only - matches what
      `matched_pilot._criteria()`/`build_collection_paste_back` already use
      for the same reason) - build `outcome_dimensions` from THAT via
      `outcome_report.build(record["graded"]["criteria"], dimensions)`,
      `dimensions` being the task's own `GraderDef.dimensions`, and pass
      the result here. This function's own job is identity extraction, not
      re-deriving bucketing logic a caller already has in scope.

    `image_digest`/`timeout_seconds` (skillc#188, review-refined): a record
    produced by a `collection-run` that predates #188 carries neither field
    in its envelope, so this adapter still accepts both as OPTIONAL
    keyword arguments, a caller's own side-channel assertion, marked
    `ASSERTED` (`load_record`'s default - nothing here upgrades it).
    A record produced AFTER #188 carries `envelope["image_digest"]` -
    itself the OBSERVED digest `install()` measured on the running
    container, never a merely-planned one (`collection_conformance.
    CollectionAgentResult.image_digest`'s own comment) - and
    `envelope["timeout_seconds"]` - the controller's own input, which
    needs no separate observation to count as recorded. Either envelope
    field, when present, is used and marked `RECORDED`; the caller-supplied
    keyword argument is then only a REDUNDANT assertion, and this function
    REFUSES if it disagrees with what the record carries, naming both,
    rather than silently preferring either (review requirement - never let
    a caller's stale or mistaken side-channel value overrule, or be
    silently overruled by, what the record itself says). When the envelope
    carries neither field (a pre-#188 record) and the caller supplies
    neither either, this function refuses - there is no value to put in
    this adapter's own required output field.

    Refuses (never defaults) when `envelope`/`verified_result` are missing
    a field this function needs, naming which one - the same posture
    `load_record` already takes for the fields it can check completely."""
    grader = verified_result.get("grader")
    if not isinstance(grader, dict):
        raise Refused("verified_result: missing 'grader'")
    task_id = grader.get("id")
    grader_revision = grader.get("revision")
    if not isinstance(task_id, str) or not task_id:
        raise Refused("verified_result: grader.id missing")
    if not isinstance(grader_revision, str) or not grader_revision:
        raise Refused("verified_result: grader.revision missing")

    client = envelope.get("client")
    if not isinstance(client, str) or not client:
        raise Refused("envelope: missing 'client'")
    collection = envelope.get("subject")
    if not isinstance(collection, str) or not collection:
        raise Refused("envelope: missing 'subject' (this record's collection identity)")
    record = envelope.get("record")
    observation = record.get("observation") if isinstance(record, dict) else None
    model = observation.get("transcript_model") if isinstance(observation, dict) else None
    if not isinstance(model, str) or not model:
        raise Refused(
            "envelope: record.observation.transcript_model missing - no model was observed for this attempt"
        )

    provenance = {
        "task_id": RECORDED, "grader_revision": RECORDED,
        "client": RECORDED, "model": RECORDED, "collection": RECORDED,
    }

    envelope_image_digest = envelope.get("image_digest")
    resolved_image_digest: str
    if isinstance(envelope_image_digest, str) and envelope_image_digest:
        if image_digest is not None and image_digest != envelope_image_digest:
            raise Refused(
                f"image_digest disagreement: the record carries {envelope_image_digest!r}, "
                f"the caller asserted {image_digest!r} - refusing rather than silently "
                f"preferring either"
            )
        resolved_image_digest = envelope_image_digest
        provenance["image_digest"] = RECORDED
    elif image_digest is not None:
        resolved_image_digest = image_digest
    else:
        raise Refused(
            "image_digest: not present in the record (skillc#188: this attempt predates it, or the "
            "backend reported no identity) and not supplied by the caller"
        )

    envelope_timeout_seconds = envelope.get("timeout_seconds")
    resolved_timeout_seconds: float
    if isinstance(envelope_timeout_seconds, (int, float)) and not isinstance(envelope_timeout_seconds, bool):
        if timeout_seconds is not None and timeout_seconds != envelope_timeout_seconds:
            raise Refused(
                f"timeout_seconds disagreement: the record carries {envelope_timeout_seconds!r}, "
                f"the caller asserted {timeout_seconds!r} - refusing rather than silently "
                f"preferring either"
            )
        resolved_timeout_seconds = envelope_timeout_seconds
        provenance["timeout_seconds"] = RECORDED
    elif timeout_seconds is not None:
        resolved_timeout_seconds = timeout_seconds
    else:
        raise Refused(
            "timeout_seconds: not present in the record (skillc#188: this attempt predates it) "
            "and not supplied by the caller"
        )

    return {
        "task_id": task_id, "grader_revision": grader_revision, "image_digest": resolved_image_digest,
        "client": client, "model": model, "timeout_seconds": resolved_timeout_seconds, "collection": collection,
        "outcome_dimensions": dict(outcome_dimensions),
        "provenance": provenance,
    }
