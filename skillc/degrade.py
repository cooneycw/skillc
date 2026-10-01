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
import hashlib
import json
import posixpath
import re
import shutil
import tempfile
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
    re-acquiring. `staging` is this run's own disposable root (issue #199):
    `source.surface_dir` lives under it, so a caller must not remove it until
    it is done reading the surface (e.g. `persist_skills`) - and must remove
    it itself afterward, on every exit path, since nothing here does."""

    subject_name: str
    mutation: Mutation | None
    base: materialize.Source
    source: materialize.Source  # kind="degraded"; revision carries the label below
    staging: Path
    manifest_rewrites: tuple[str, ...] = ()  # see `_rewrite_manifests`


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


def _rewrite_manifests(
    mutated_dir: Path, acquire_subject: materialize.Subject, skill_dirs: dict[str, str], mutation: Mutation,
) -> tuple[str, ...]:
    """Re-pin every overridden file the skill's declared checksum manifest
    lists (issue #198). Without this, an override of a checksummed script
    (CPP's `scripts/gh-pr-merge.sh`) leaves the manifest pinning the ORIGINAL
    hash, and `materialize._verify_checksums` refuses the degraded tree - so
    the degraded arm could never launch.

    This is bookkeeping, not rule removal: the rewrite is returned (and
    recorded in the receipt's `manifest_rewrites`) apart from
    `mutation.locations`, which stays exactly what the operator declared. The
    manifest still pins a hash - the override's - so a file changed after
    this point is refused exactly as before. Only a line whose listed path
    resolves to an overridden file changes; its layout (`*` marker, spacing,
    line ending) is kept. A skill whose manifest the operator edited
    explicitly is left alone: the operator owns it. Deletions are not
    re-pinned; a deleted listed file is still refused at preparation."""
    manifest_rel = acquire_subject.checksum_manifest
    if not manifest_rel:
        return ()
    owned = {(e.skill, posixpath.normpath(e.path)) for e in mutation.edits}
    overridden: dict[str, set[Path]] = {}
    for edit in mutation.edits:
        if edit.content is not None and (edit.skill, posixpath.normpath(manifest_rel)) not in owned:
            overridden.setdefault(edit.skill, set()).add((mutated_dir / skill_dirs[edit.skill] / edit.path).resolve())
    rewrites: list[str] = []
    for skill, targets in overridden.items():
        manifest = mutated_dir / skill_dirs[skill] / manifest_rel
        if not manifest.is_file():
            continue
        lines = manifest.read_bytes().decode("utf-8").splitlines(keepends=True)
        changed = False
        for i, line in enumerate(lines):
            parts = line.split(None, 1)
            if len(parts) != 2 or line.startswith("#") or not re.fullmatch(r"[0-9a-f]{64}", parts[0]):
                continue  # malformed lines are materialize's to refuse, not this rewrite's to fix
            listed = parts[1].strip().lstrip("*")
            target = (manifest.parent / listed).resolve()
            if target not in targets:
                continue
            new = hashlib.sha256(target.read_bytes()).hexdigest()
            if new == parts[0]:
                continue
            start = line.index(parts[0])  # the verifier's split() accepts leading whitespace
            lines[i] = line[:start] + new + line[start + len(parts[0]):]
            rewrites.append(f"{skill}/{manifest_rel}: {listed} sha256:{parts[0]} -> sha256:{new}")
            changed = True
        if changed:
            manifest.write_bytes("".join(lines).encode("utf-8"))
    return tuple(rewrites)


def _apply_mutation(
    mutated_dir: Path, acquire_subject: materialize.Subject, base_source: materialize.Source, mutation: Mutation,
) -> tuple[str, ...]:
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

    return _rewrite_manifests(mutated_dir, acquire_subject, names, mutation)


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
    `_refuse_if_identical_to_normal`).

    `staging` (issue #199) is a fresh per-call directory under `base`, never
    the fixed `<base>/<subject_name>-degraded-staging` path a second call
    used to collide on. On any failure from this point on, the staging this
    call created is removed before the exception propagates - this function
    never leaves a half-built staging tree behind. On success the returned
    `DegradedSource.staging` is still live (`source.surface_dir` lives under
    it): the caller owns removing it once it is done reading the surface."""
    if (checkout is None) == (revision is None):
        raise DegradationRefused("acquire_degraded needs exactly one of checkout= or revision=")
    subject = demo.load_demo_subject(subject_name)
    base.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f"{subject_name}-degraded-", dir=base))
    try:
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

        manifest_rewrites: tuple[str, ...] = ()
        if mutation is None:
            mutated_dir = base_source.surface_dir
            mutated_digest = base_source.digest
        else:
            mutated_dir = staging / "degraded"
            shutil.copytree(base_source.surface_dir, mutated_dir)
            manifest_rewrites = _apply_mutation(mutated_dir, acquire_subject, base_source, mutation)
            mutated_digest = materialize.tree_digest(mutated_dir)

        _refuse_if_identical_to_normal(
            source_is_override=source_is_override, mutation_changed_tree=mutated_digest != base_source.digest,
        )
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    degraded = dataclasses.replace(
        base_source,
        kind="degraded",
        revision=_degraded_revision(base_source, mutation),
        surface_dir=mutated_dir,
        digest=mutated_digest,
    )
    return DegradedSource(
        subject_name=subject_name, mutation=mutation, base=base_source, source=degraded,
        staging=staging, manifest_rewrites=manifest_rewrites,
    )


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
        # Checksum-manifest lines re-pinned to an override's hash (#198) -
        # bookkeeping kept apart from `mutation.locations`, never rule removal.
        "manifest_rewrites": list(degraded.manifest_rewrites),
        "base": {"kind": degraded.base.kind, "revision": degraded.base.revision, "digest": degraded.base.digest},
        "degraded": {"kind": degraded.source.kind, "revision": degraded.source.revision, "digest": degraded.source.digest},
    }


def persist_skills(degraded: DegradedSource, out: Path) -> Path:
    """Copy the degraded surface tree to `out/skills` - the tree a runner
    will later install. Before this, `degrade-subject --out DIR` wrote only
    `receipt.json`: the degraded tree itself lived under the disposable
    staging root and was discarded with it, so the receipt described a tree
    nothing kept and nothing could ever run (orchestrator review of #155).
    Returns the copied directory."""
    target = out / "skills"
    shutil.copytree(degraded.source.surface_dir, target)
    return target


def verify_persisted_skills(out: Path, expected_digest: str) -> Path:
    """Re-derive `out/skills`' own tree digest and refuse (`DegradationRefused`)
    unless it matches `expected_digest` (a receipt's own `degraded.digest`).
    This is the check a runner MUST make before installing a persisted
    degraded tree - `persist_skills` writes plain files with no integrity
    mechanism of their own, so nothing else stands between a tampered or
    corrupted `skills/` directory and being installed as though it were
    exactly what the receipt described. Returns the verified directory."""
    target = out / "skills"
    if not target.is_dir():
        raise DegradationRefused(f"no persisted skills tree at {target}")
    actual = materialize.tree_digest(target)
    if actual != expected_digest:
        raise DegradationRefused(
            f"persisted skills tree at {target} has digest {actual}, its own receipt declares "
            f"{expected_digest}; refusing to treat it as that degraded subject"
        )
    return target


def load_persisted_degraded(out: Path, subject: materialize.Subject, *, subject_name: str) -> materialize.Source:
    """The read half of `persist_skills`/`degrade-subject --out DIR`: parse
    `out/receipt.json`, verify it was built for THIS subject at THIS pin,
    verify `out/skills` against its own declared digest
    (`verify_persisted_skills` - refuses a tampered or corrupted tree before
    anything installs it), and return a `materialize.Source` a runner can
    acquire from exactly like any other (issue #150-B2: `collection-run
    --degraded DIR`).

    `subject` supplies `locator` only - the receipt does not carry one, and a
    degraded acquisition still comes from the same declared repository. The
    returned `Source.revision` is always the receipt's own `degraded.revision`
    label (`degraded:...`), never `subject.revision` - a run over a degraded
    tree must never be able to report the pin as what it installed.

    Refuses (`DegradationRefused`) when `out/receipt.json` is missing,
    unreadable, or carries no usable `degraded` identity - before
    `verify_persisted_skills` is even reached, since there is nothing to
    verify against; and, before that, when the receipt's own `subject` or
    `pinned_revision` disagrees with the caller's `subject_name`/`subject.
    revision` (issue #150-B3b review). Neither field was compared before this
    - a degraded tree built for one subject (e.g. cpp-codex) would install
    silently under another (e.g. cpp-claude-code, a different client), and a
    tree pinned to a stale revision would install as if it were still the
    subject's current pin. `subject_name` is a separate parameter because
    `materialize.Subject` itself carries no name - the caller's own
    `evals/subjects/<name>/` lookup key, never re-derived here."""
    receipt_path = out / "receipt.json"
    try:
        payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise DegradationRefused(f"no readable receipt.json at {out}: {exc}") from exc
    except ValueError as exc:
        raise DegradationRefused(f"{receipt_path} does not parse as JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise DegradationRefused(f"{receipt_path} does not parse as a JSON object")
    receipt_subject = payload.get("subject")
    if receipt_subject != subject_name:
        raise DegradationRefused(
            f"{receipt_path} was built for subject {receipt_subject!r}, not {subject_name!r}"
        )
    receipt_pin = payload.get("pinned_revision")
    if receipt_pin != subject.revision:
        raise DegradationRefused(
            f"{receipt_path}'s pinned_revision {receipt_pin!r} does not match "
            f"{subject_name!r}'s own pin {subject.revision!r}"
        )
    degraded_field = payload.get("degraded")
    if not isinstance(degraded_field, dict):
        raise DegradationRefused(f"{receipt_path} carries no 'degraded' identity")
    kind, revision, digest = degraded_field.get("kind"), degraded_field.get("revision"), degraded_field.get("digest")
    if not all(isinstance(v, str) and v for v in (kind, revision, digest)):
        raise DegradationRefused(f"{receipt_path}'s degraded identity is malformed: {degraded_field!r}")
    assert isinstance(kind, str) and isinstance(revision, str) and isinstance(digest, str)
    skills_dir = verify_persisted_skills(out, digest)
    return materialize.Source(
        kind=kind, locator=subject.locator, revision=revision, surface_dir=skills_dir, digest=digest, origin=out,
    )
