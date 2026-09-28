"""An operator-expressible degraded CPP subject (issue #150 acceptance item 2).

`collection_conformance.acquire_collection` (issue #11) and `materialize.py`
(issue #101) both read a subject's DECLARED, PINNED revision - `demo.py`'s
`acquire_subject_checkout` clones `https://{locator}` and forces it to
`subject.revision` via `git checkout`. Nothing before this module let an
operator ask for anything else from the command line: a local `checkout=`
exists only as a Python/test parameter (`acquire_collection`,
`run_subject_demo`), and a degraded skill set was expressible only by hand-
editing a non-default-branch revision into a `subject.json` and never
exercising that path in a test.

This module builds ONE degraded subject from TWO knobs, both operator-facing:

  - the SOURCE: either a local snapshot directory the operator already
    prepared (`checkout=`, reusing `materialize.acquire_snapshot` exactly as
    `materialize`/`exposure`'s own `--snapshot` flag already does), or an
    explicitly supported alternative git revision on the subject's OWN
    locator (`revision=`, acquired the same way `materialize.acquire_git`
    acquires the subject's declared pin - never an unpinned ref, never a
    different repository);
  - the MUTATION (optional): zero or more skills removed WHOLESALE
    (`Mutation.remove_skills`), plus zero or more single-file edits within a
    skill (`Mutation.edits`), applied together as one declared mutation.

A single rule can live in more than one place - CPP #1084's own #150-A found
one restated across three skills and two identical scripts (five files) - so
"one skill mutated or removed" (the acceptance line's own wording) is a
special case of a mutation that can touch SEVERAL files or passages across
SEVERAL skills at once, not the ceiling. A `FileEdit` never does a byte-level
in-place patch: it names a whole file, either deleted (`content=None`) or
REPLACED with content the caller already prepared (`content=<bytes>`) - "what
changed" is always the (skill, path) pair, never a diff someone has to
recompute, and `receipt()`'s `mutation.locations` lists every one of them by
name, so an incomplete mutation is visible in its own statement rather than
silently read as "the degraded subject" once one location was missed.

Generic over `subject_name` and over which skill or file is mutated (#150-A
is choosing them for the task this collection is graded against; this module
does not know or care which names it will be called with).

THE RESULTING IDENTITY IS NEVER THE PINNED ONE (the acceptance line's "must be
clearly distinguishable from the real subject, never passed off as the pinned
one"): the degraded `Source.revision` is always a `degraded:` label naming
the base acquisition, never a bare commit SHA or a bare `snapshot:<digest>`
that could be mistaken for an ordinary acquisition.

No Docker, no client, no network beyond the single git operation `revision=`
needs (identical to what `acquire_subject_checkout` already does for the
pinned leg) - `checkout=` needs none at all. Stdlib plus this repository's own
modules (AGENTS.md).
"""

from __future__ import annotations

import dataclasses
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from . import demo, materialize


class DegradationRefused(Exception):
    """A degraded subject could not be built as declared - refused before any
    attempt, receipt, or export reads it."""


@dataclass(frozen=True)
class FileEdit:
    """One location a degradation touches, inside ONE skill's own directory.
    `path` is POSIX-relative to that skill's directory (e.g. `"reference.md"`
    or `"scripts/gh-pr-merge.sh"`), never absolute and never climbing out of
    it. `content=None` deletes the file; a `bytes` value replaces its content
    wholesale - never a byte-level patch, so the receipt can always say
    exactly what this location now is without anyone re-deriving a diff."""

    skill: str
    path: str
    content: bytes | None = None


@dataclass(frozen=True)
class Mutation:
    """One committed statement of what a degradation removes or overrides:
    zero or more whole skills (`remove_skills`) and zero or more single-file
    edits (`edits`), all applied together. At least one of the two must be
    non-empty - an otherwise-empty `Mutation` is a caller error, refused
    before anything is acquired."""

    remove_skills: tuple[str, ...] = ()
    edits: tuple[FileEdit, ...] = field(default_factory=tuple)

    def locations(self) -> tuple[str, ...]:
        """One line per touched location, in declaration order - the
        "committed statement of what the mutation removes" the acceptance
        line asks for, and what a reviewer checks against a list like #150-A's
        five-location finding to see whether every one was actually covered."""
        return (
            *(f"{skill} (whole skill removed)" for skill in self.remove_skills),
            *(
                f"{edit.skill}/{edit.path} "
                f"({'removed' if edit.content is None else f'overridden ({len(edit.content)} bytes)'})"
                for edit in self.edits
            ),
        )


@dataclass(frozen=True)
class DegradedSource:
    """A subject's surface, acquired from an operator-chosen source and then
    optionally mutated. `base` is the UNDEGRADED acquisition's own identity -
    what this subject's source would have reported before any mutation - kept
    beside the degraded identity so a receipt can show both without
    re-acquiring."""

    subject_name: str
    mutation: Mutation | None
    base: materialize.Source
    source: materialize.Source  # kind="degraded"; revision carries the label below


def _degraded_revision(base: materialize.Source, mutation: Mutation | None) -> str:
    """Never a bare commit SHA and never `snapshot:<digest>` - both of those
    shapes already mean something else (a real pin, an undegraded local
    snapshot) and could be passed off as one. This label can only ever mean
    "degraded"; the full per-location statement lives in `receipt()`, not
    squeezed in here."""
    tag = "none" if mutation is None else f"{len(mutation.remove_skills) + len(mutation.edits)}-location"
    return f"degraded:mutated={tag}:{base.kind}:{base.revision}"


def _refuse_if_identical_to_normal(
    *, source_is_override: bool, mutation_changed_tree: bool,
) -> None:
    """The acceptance line's first red case: a degraded subject whose
    recorded identity equals the normal one must be refused. Structural, not
    a second network fetch of the real pin: if the acquisition used neither a
    distinct source (a local snapshot, or a revision other than the
    subject's own pin) NOR did a mutation actually change any bytes, then the
    acquired SURFACE is byte-for-byte what an ordinary, undegraded
    acquisition of the subject's own pinned revision would be - reachable in
    practice exactly by calling with `mutation=None` and `revision=` equal to
    the subject's own pin, and it is exactly that call this rule's own test
    fires it with. The `degraded:` label alone (see `_degraded_revision`)
    would still read as "not the pin" in a receipt, which is why this check
    exists at all: a caller must not be able to claim degradation while
    changing nothing a discrimination run could tell apart."""
    if not source_is_override and not mutation_changed_tree:
        raise DegradationRefused(
            "the degraded subject's recorded identity would equal the normal "
            "one: no source override was given (revision equals the subject's "
            "own pin) and no mutation changed the acquired tree"
        )


def _apply_mutation(
    mutated_dir: Path, acquire_subject: materialize.Subject, base_source: materialize.Source, mutation: Mutation,
) -> None:
    """Apply every removal and edit `mutation` declares, in place, under
    `mutated_dir` (already a fresh copy of `base_source.surface_dir` - see
    `acquire_degraded`). Refuses (never applies partially) when: the mutation
    is empty; a removal or edit names a skill absent from the collection (or
    excluded by `subject.select` - `inventory()` already scopes to it); a
    skill is both wholly removed and separately edited; an edit's `path`
    escapes its skill's own directory, is absent, or is a directory; or an
    override's content is byte-identical to what is already there (a no-op
    edit an operator almost certainly did not intend)."""
    if not mutation.remove_skills and not mutation.edits:
        raise DegradationRefused("mutation declares neither a skill removal nor a file edit")
    overlap = set(mutation.remove_skills) & {edit.skill for edit in mutation.edits}
    if overlap:
        raise DegradationRefused(
            f"skill(s) {sorted(overlap)} are both wholly removed and separately file-edited; redundant"
        )
    entries = materialize.inventory(acquire_subject, base_source)
    names = {e.name: e.directory for e in entries}

    for skill in mutation.remove_skills:
        if skill not in names:
            raise DegradationRefused(
                f"mutation names skill {skill!r}, absent from the collection (has: {sorted(names)})"
            )
        target = mutated_dir / names[skill]
        if not target.is_dir():
            raise DegradationRefused(f"mutation names skill {skill!r}, whose directory is absent from the staged surface")
        shutil.rmtree(target)

    for edit in mutation.edits:
        if edit.skill not in names:
            raise DegradationRefused(
                f"mutation edits skill {edit.skill!r}, absent from the collection (has: {sorted(names)})"
            )
        skill_dir = mutated_dir / names[edit.skill]
        target = skill_dir / edit.path
        if not target.resolve().is_relative_to(skill_dir.resolve()):
            raise DegradationRefused(f"mutation edits {edit.skill}/{edit.path}, which escapes its skill's directory")
        if not target.is_file():
            raise DegradationRefused(f"mutation edits {edit.skill}/{edit.path}, absent from the staged surface")
        if edit.content is None:
            target.unlink()
        else:
            if target.read_bytes() == edit.content:
                raise DegradationRefused(
                    f"mutation overrides {edit.skill}/{edit.path} with byte-identical content; nothing would change"
                )
            target.write_bytes(edit.content)


def acquire_degraded(
    subject_name: str, base: Path, mutation: Mutation | None, *,
    checkout: Path | None = None, revision: str | None = None,
) -> DegradedSource:
    """Acquire `subject_name`'s declared surface from `checkout` XOR
    `revision`, then apply `mutation` over the result, when one is given.

    Refuses (`DegradationRefused`) when: neither or both of `checkout`/
    `revision` are given; the subject declaration itself is unusable
    (`demo.SubjectRefused`, allowed to propagate); `mutation` is malformed or
    unsatisfiable (see `_apply_mutation`); or the resulting identity would be
    indistinguishable from a normal, undegraded acquisition (see
    `_refuse_if_identical_to_normal`)."""
    if (checkout is None) == (revision is None):
        raise DegradationRefused("acquire_degraded needs exactly one of checkout= or revision=")
    subject = demo.load_demo_subject(subject_name)
    staging = base / f"{subject_name}-degraded-staging"
    staging.mkdir(parents=True, exist_ok=True)

    if checkout is not None:
        base_source = materialize.acquire_snapshot(subject, checkout, staging / "base")
        acquire_subject = subject
        source_is_override = True  # a snapshot is never the subject's own git pin
    else:
        assert revision is not None
        acquire_subject = dataclasses.replace(subject, revision=revision)
        repo = demo.acquire_subject_checkout(acquire_subject, staging / "base-checkout")
        base_source = materialize.acquire_git(acquire_subject, repo, staging / "base")
        source_is_override = revision != subject.revision

    if mutation is None:
        mutated_dir = base_source.surface_dir
        mutated_digest = base_source.digest
    else:
        mutated_dir = staging / "degraded"
        shutil.copytree(base_source.surface_dir, mutated_dir)
        _apply_mutation(mutated_dir, acquire_subject, base_source, mutation)
        mutated_digest = materialize.tree_digest(mutated_dir)

    _refuse_if_identical_to_normal(
        source_is_override=source_is_override, mutation_changed_tree=mutated_digest != base_source.digest,
    )

    degraded = dataclasses.replace(
        base_source,
        kind="degraded",
        revision=_degraded_revision(base_source, mutation),
        surface_dir=mutated_dir,
        digest=mutated_digest,
    )
    return DegradedSource(subject_name=subject_name, mutation=mutation, base=base_source, source=degraded)


def receipt(degraded: DegradedSource, *, pinned_revision: str) -> dict[str, object]:
    """A JSON-serializable statement of what this degradation is - no
    absolute path anywhere (`materialize.materialize`'s own `report["source"]`
    convention: `kind`/`revision`/`digest` only), so nothing here needs the
    host-path redaction pass the CLI commands that DO print paths (`demo.py`)
    apply. `mutation.locations` is the full, ordered list of every skill or
    file this degradation touched - deliberately explicit rather than a count,
    so a reviewer checking this receipt against an independently compiled
    list (like #150-A's own five-location finding) can see directly whether
    every location was covered."""
    mutation = degraded.mutation
    if mutation is None:
        mutation_field: dict[str, object] = {
            "locations": [], "statement": "no skill removed; this degradation is a source override only",
        }
    else:
        locations = list(mutation.locations())
        mutation_field = {"locations": locations, "statement": "removed/overrode: " + "; ".join(locations)}
    return {
        "version": 1,
        "kind": "degraded-subject-receipt",
        "subject": degraded.subject_name,
        "pinned_revision": pinned_revision,
        "mutation": mutation_field,
        "base": {"kind": degraded.base.kind, "revision": degraded.base.revision, "digest": degraded.base.digest},
        "degraded": {"kind": degraded.source.kind, "revision": degraded.source.revision, "digest": degraded.source.digest},
    }
