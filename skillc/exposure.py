"""Rung 2 of ADR 0004 (issue #55): measure what actually reaches the model,
per client, with no model call. Every existing skillc check reads the
AUTHOR's files; this reads what the CLIENT actually renders into its
session-start input - the same disposable-home isolation `materialize.py`
already established (#7), reused wholesale here rather than duplicated.

WHY THIS EXISTS (ADR 0004): four exposure failures surfaced on 2026-09-26
that no file check could see - a memory index truncated at about 25 KB, a
policy-hidden skill, a frontmatter field one client ignores, and a manifest
that installs 25 of 38 skills. In each case the author's files and the
model's input silently disagreed. A file check cannot catch this by
definition: it never looks at what the client renders.

THREE LAYERS, each independently declarable in a surface declaration that
EXTENDS `subject.json` (materialize.py's own schema, unchanged - this module
adds `exposure_schema`, `always_loaded` and `index` as additional top-level
keys, validated here, then hands the remaining keys to
`materialize.Subject.from_dict` unmodified):

1. Always-loaded instruction files (`always_loaded`): a declared path is
   read from the acquired source and PLANTED, unmodified into a disposable
   arm's workspace unless a `claimed_limit_bytes` is declared, in which case
   a synthetic marker-bearing variant is built (see `_plant_always_loaded`)
   - the SOURCE's own copy is never touched, only the arm's own workspace,
   which is what the client actually reads (`materialize.run_client`'s
   `cwd`). A `claimed_limit_bytes` is the check's own claim under test, not
   a fact it asserts about the client - EF-style: `derive readiness fact ->
   commit the input that flips it`.
2. The skill listing: reuses `materialize.Subject`/`inventory`/`install`/
   `canary`/`parse_listing` wholesale. Each expected skill (from `select`,
   or every discovered entry) is `EXPOSED` when it appears in the parsed
   listing, `HIDDEN` otherwise - with a `policy` cause when
   `agents/openai.yaml`'s `policy.allow_implicit_invocation: false`
   explains it (verified against codex-cli 0.157.1, 2026-09-26: a skill
   carrying that policy is absent from `debug prompt-input`'s listing
   entirely).

   NOT MODELED: a "listing limit" in the ADR's own sense - a manifest that
   installs fewer skills than it DECLARES (25 of 38) - needs an independent
   count of what was declared, separate from what `select`/`inventory()`
   actually found; `materialize.Subject.from_dict` already refuses a
   `select` naming an unknown skill before this module ever runs, so a
   "declared but never attempted" entry cannot reach this classification
   loop as currently wired (found while reviewing this module's own first
   draft: the `entry is None` branch below is honest defensive code, but
   unreachable given `select`'s existing validation, not a demonstrated
   control). Comparing against a manifest's own independently-declared count
   is real, scoped-out follow-up work, not claimed here.
3. An index file with on-demand targets (`index`): the index file itself is
   checked the same way as an always-loaded file with no size limit
   (present or absent, no truncation claim); each declared `targets` entry
   is checked as a literal-string marker within the RENDERED text - proving
   the model at least KNOWS the target exists, never that it would actually
   be fetched on demand (that needs a real turn with tool use, a live-model
   fact, explicitly out of scope here - see `docs/specs/evaluation-facility/
   support-matrix.md`).

VERDICTS (never a bare bool): `EXPOSED` (found in full), `TRUNCATED` (a
marker's own longest proper prefix found at the tail of the rendered text -
named cut point included), `HIDDEN` (installed/declared but genuinely
absent, cause named when known), `UNMEASURED` (the client offered no render,
or the render failed - NEVER folded into a clean result; a blind run exits
nonzero, never zero findings).

MARKER COLLISION IS CHECKED BEFORE RENDERING, NOT AFTER: a planted marker
that happens to also match ambient text (the checkout path, the disposable
home's path, a skill's own description) would make an EXPOSED verdict
meaningless - it could not tell "the marker was rendered" from "some
unrelated ambient string happened to match". `check_collisions` refuses the
whole run rather than produce a verdict it cannot trust.

CLAUDE CODE: no supported way to render session-start input without an
actual model call was identified (`claude --help`, read 2026-09-26, Claude
Code 2.1.283 pinned per `docker/trial/pinned-versions.json`: only a generic
`--debug`/`--debug-file` verbose-logging flag exists, nothing shaped like
`codex debug prompt-input`). Every Claude Code render is therefore
`UNMEASURED`, by declaration, not by a failed attempt each time - this is
the honest answer the issue's own acceptance criteria permit ("If none
exists, the Claude Code arm reports UNMEASURED and the issue says so").

WHAT IS OWED TO THE LIVE RUN: the exact real-world cut point (if any) for
any given `claimed_limit_bytes` - this module reports the boundary it
observed against whatever client actually ran, never a prediction dressed
as a fact ("a wrong prediction reads as a finding, not as instrument
failure" - the issue's own words). Verified empirically against codex-cli
0.157.1 on 2026-09-26: a real AGENTS.md up to 30 KB was NOT truncated in
this environment - contradicting the ADR's ~25 KB observation, which may
reflect a different client version, a different file, or a different
mechanism (a memory index, not AGENTS.md). That discrepancy is itself
exactly the kind of finding this instrument exists to surface, not to
paper over with an assumed threshold.

Stdlib only (AGENTS.md), reusing materialize.py wholesale rather than a
second implementation of arm/home isolation.
"""

from __future__ import annotations

import json
import posixpath
import secrets
from dataclasses import dataclass
from pathlib import Path

from . import materialize
from .materialize import Refused
from .spec import FrontmatterError, parse_frontmatter, parse_yaml_document

EXPOSURE_SCHEMA = 1

EXPOSED, TRUNCATED, HIDDEN, UNMEASURED = "EXPOSED", "TRUNCATED", "HIDDEN", "UNMEASURED"

#: Every marker carries this prefix, so a collision check can also catch a
#: marker that accidentally reproduces another marker's own text - not just
#: ambient text outside this module's control.
MARKER_PREFIX = "SKILLC-EXPOSURE-"

#: Bytes of separation kept between a claimed limit and the "just beyond"
#: marker's own start - enough that a client boundary a few bytes either
#: side of the exact claim still classifies unambiguously.
_BOUNDARY_GAP = 64

#: The smallest `claimed_limit_bytes` that can even hold the "inside" marker's
#: own minimal footprint (`MARKER_PREFIX` + "INSIDE-" + a 16-hex-char nonce +
#: a newline, ~40 bytes) with a little room to spare - anything smaller makes
#: "expect EXPOSED" structurally impossible, for any client (cross-model
#: review, PR #90).
_MIN_CLAIMED_LIMIT_BYTES = 64

_EXPOSURE_ONLY_KEYS = {"exposure_schema", "always_loaded", "index"}


def _escapes(rel: str) -> bool:
    """True when a declared relative path is absolute or climbs out of its
    base. Mirrors `materialize._escapes` exactly - kept independent rather
    than importing a private helper across modules."""
    norm = posixpath.normpath(rel)
    return rel.startswith("/") or norm == ".." or norm.startswith("../")


# ------------------------------------------------------------------ the surface


@dataclass(frozen=True)
class AlwaysLoadedFile:
    path: str
    claimed_limit_bytes: int | None


@dataclass(frozen=True)
class IndexFile:
    path: str
    targets: tuple[str, ...]


@dataclass(frozen=True)
class ExposureSurface:
    """A surface declaration: `materialize.Subject`'s own schema (the skills
    layer, unchanged) plus `always_loaded` and `index`. One JSON file, one
    `Subject.from_dict` call for the shared fields - never a second,
    divergent parser for the same subject conventions."""

    subject: materialize.Subject
    always_loaded: tuple[AlwaysLoadedFile, ...]
    index: IndexFile | None

    @classmethod
    def load(cls, path: Path) -> ExposureSurface:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise Refused(f"exposure surface declaration unreadable: {path}: {exc}") from exc
        if not isinstance(data, dict):
            raise Refused("exposure surface declaration is not a JSON object")
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> ExposureSurface:
        if data.get("exposure_schema") != EXPOSURE_SCHEMA:
            raise Refused(f"exposure_schema is {data.get('exposure_schema')!r}, not {EXPOSURE_SCHEMA}")
        subject_data = {k: v for k, v in data.items() if k not in _EXPOSURE_ONLY_KEYS}
        subject = materialize.Subject.from_dict(subject_data)
        return cls(
            subject=subject,
            always_loaded=_parse_always_loaded(data.get("always_loaded")),
            index=_parse_index(data.get("index")),
        )


def _parse_always_loaded(raw: object) -> tuple[AlwaysLoadedFile, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise Refused("always_loaded must be a list")
    out: list[AlwaysLoadedFile] = []
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not item["path"]:
            raise Refused("every always_loaded entry needs a non-empty string path")
        path = posixpath.normpath(str(item["path"]))
        if _escapes(path):
            raise Refused(f"always_loaded path {path!r} escapes the subject")
        limit = item.get("claimed_limit_bytes")
        if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0):
            raise Refused("always_loaded claimed_limit_bytes must be a positive integer or absent")
        if limit is not None and limit < _MIN_CLAIMED_LIMIT_BYTES:
            # Below this, the "inside" marker's own minimal footprint (the
            # fixed prefix plus its 16-hex-char nonce) cannot fit inside the
            # claimed limit at all, making "expect EXPOSED" impossible for
            # any client, real or fake (cross-model review, PR #90).
            raise Refused(
                f"always_loaded claimed_limit_bytes must be at least {_MIN_CLAIMED_LIMIT_BYTES} "
                f"(the inside marker's own footprint), got {limit}"
            )
        out.append(AlwaysLoadedFile(path=path, claimed_limit_bytes=limit))
    return tuple(out)


def _parse_index(raw: object) -> IndexFile | None:
    if raw is None:
        return None
    if not isinstance(raw, dict) or not isinstance(raw.get("path"), str) or not raw["path"]:
        raise Refused("index needs a non-empty string path")
    path = posixpath.normpath(str(raw["path"]))
    if _escapes(path):
        raise Refused(f"index path {path!r} escapes the subject")
    targets = raw.get("targets", [])
    if not isinstance(targets, list) or not all(isinstance(t, str) and t for t in targets):
        raise Refused("index targets must be a list of non-empty strings")
    return IndexFile(path=path, targets=tuple(targets))


# ------------------------------------------------------------------------ markers


@dataclass(frozen=True)
class Marker:
    marker_id: str
    text: str
    layer: str
    note: str


def _nonce() -> str:
    return secrets.token_hex(8)


def _plant_always_loaded(source_dir: Path, entry: AlwaysLoadedFile) -> tuple[bytes, list[Marker]]:
    """The content to write into the arm's workspace at `entry.path`, and
    the marker(s) planted inside it. Reads the real file if the acquired
    source has one at that path; otherwise starts from empty content -
    either way, `source_dir` itself is only ever READ, never written (the
    arm's own workspace copy is what carries the plant).

    The REAL content is always PRESERVED as a prefix, in both branches -
    never replaced wholesale by synthetic filler (cross-model review, PR
    #90: an earlier draft discarded it entirely in the claimed-limit branch,
    which measured a fabricated stand-in's exposure, never the author's own
    declared file - directly contradicting this module's own opening claim,
    "measure what actually reaches the model...never what the author's files
    merely declare")."""
    real = source_dir / entry.path
    base = real.read_bytes() if real.is_file() else b""
    if entry.claimed_limit_bytes is None:
        marker = f"{MARKER_PREFIX}ALWAYS-{_nonce()}"
        content = base + b"\n" + marker.encode() + b"\n"
        return content, [Marker(f"always_loaded:{entry.path}", marker, f"always_loaded:{entry.path}",
                                 "no claimed limit - expect EXPOSED")]

    limit = entry.claimed_limit_bytes
    inside = f"{MARKER_PREFIX}INSIDE-{_nonce()}"
    outside = f"{MARKER_PREFIX}OUTSIDE-{_nonce()}"
    if len(base) >= limit:
        # The real declared file already exceeds the claimed limit on its
        # own - markers appended after it cannot test THIS boundary
        # meaningfully. Surfaced explicitly in the note rather than silently
        # producing a test of a different boundary than the one declared.
        content = base + b"\n" + inside.encode() + b"\n" + outside.encode() + b"\n"
        caveat = f" - the real file is already {len(base)} bytes, past the {limit}-byte claim on its own"
        inside_note = f"planted after the real content{caveat}"
        outside_note = f"planted after the real content{caveat}"
    else:
        room = limit - len(base) - len(inside) - 1
        content = base + (b"." * room) + inside.encode() + b"\n"
        content += (b"." * _BOUNDARY_GAP) + b"\n" + outside.encode() + b"\n"
        inside_note = (
            f"planted after the real {len(base)}-byte file to end at byte {limit} "
            f"of a {limit}-byte claimed limit - expect EXPOSED"
        )
        outside_note = f"planted to start beyond the {limit}-byte claimed limit - expect TRUNCATED or HIDDEN"
    markers = [
        Marker(f"always_loaded:{entry.path}:inside", inside, f"always_loaded:{entry.path}", inside_note),
        Marker(f"always_loaded:{entry.path}:outside", outside, f"always_loaded:{entry.path}", outside_note),
    ]
    return content, markers


def _plant_index(source_dir: Path, index: IndexFile) -> tuple[bytes, list[Marker]]:
    """Like `_plant_always_loaded`: the real declared index content (if any)
    is preserved as a prefix, never replaced (cross-model review, PR #90)."""
    real = source_dir / index.path
    base = real.read_bytes() if real.is_file() else b""
    marker = f"{MARKER_PREFIX}INDEX-{_nonce()}"
    lines = [marker, "", "On-demand targets:"]
    target_markers = []
    for target in index.targets:
        lines.append(f"- {target}")
        target_markers.append(
            Marker(f"index-target:{target}", target, "index-target",
                   "declared on-demand target name - expect EXPOSED (listed), "
                   "never that the target's own content was fetched")
        )
    appended = "\n".join(lines).encode() + b"\n"
    content = base + b"\n" + appended if base else appended
    return content, [
        Marker("index", marker, "index", "the index file itself - expect EXPOSED"),
        *target_markers,
    ]


def check_collisions(markers: list[Marker], ambient: list[str]) -> list[Marker]:
    """Markers whose text already appears somewhere it should not - the
    checkout path, the disposable home's own path, a skill's description,
    or another marker's own text. A collision here means an EXPOSED verdict
    for that marker could not be trusted (it might be the ambient text a
    real render was always going to contain, not this run's own plant).

    Ambient strings are compared WITHOUT excluding an exact match (found by
    this module's own test suite): comparing only strings that differ from
    the marker's own text is backwards - an ambient string EQUAL to a
    marker's text is the single worst collision there is, and excluding
    exact-equal candidates hid exactly that case.

    Ambient comparison is ONE-DIRECTIONAL - is the FULL marker contained in
    the ambient text - never the reverse (cross-model review, PR #90: a
    skill merely named `topic` is not a collision risk for a target marker
    `docs/topic-a.md` just because `topic` happens to be a substring of it;
    rendering the short ambient string cannot somehow produce the longer
    marker's own text). Marker-to-marker comparison stays SYMMETRIC and
    excluded by INDEX rather than value, since two independently generated
    markers - potentially of different lengths - genuinely could collide
    with each other in either direction (structurally near-impossible with
    nonces, but a real check should not simply assume its own inputs never
    collide)."""
    colliding: list[Marker] = []
    for i, marker in enumerate(markers):
        if any(candidate and marker.text in candidate for candidate in ambient):
            colliding.append(marker)
            continue
        others = (m.text for j, m in enumerate(markers) if j != i)
        if any(other and (marker.text in other or other in marker.text) for other in others):
            colliding.append(marker)
    return colliding


# ------------------------------------------------------------------- rendering


@dataclass(frozen=True)
class Rendering:
    status: str  # "ok", "absent", "failed", "timeout"
    detail: str
    raw_text: str  # every content[].text, concatenated - "" unless status == "ok"
    listing: materialize.Listing


def render_codex(
    argv: list[str] | None, arm: materialize.Arm, timeout: float,
) -> Rendering:
    if argv is None:
        return Rendering("absent", f"client {materialize.CLIENT!r} not found", "", materialize.Listing("absent"))
    try:
        code, out, err = materialize.run_client(
            argv, arm.home, arm.codex_home, arm.workspace, materialize.CANARY_ARGV, timeout,
        )
    except OSError as exc:
        return Rendering("failed", f"client could not be started: {exc}", "", materialize.Listing("failed"))
    if code is None:
        return Rendering("timeout", f"client did not finish within {timeout}s", "", materialize.Listing("timeout"))
    if code != 0:
        return Rendering("failed", f"client exited {code}: {err.strip()[:400]}", "", materialize.Listing("failed"))
    if not out.strip():
        # Exit 0 with empty output is its own blind case, named explicitly by
        # the issue's own acceptance criteria - never let it fall through to
        # "ok" with an empty raw_text, which would classify every marker
        # HIDDEN (a real verdict) rather than UNMEASURED (no render to judge).
        return Rendering("failed", "client returned empty output", "", materialize.Listing("failed"))
    listing = materialize.parse_listing(out, arm.directory)
    try:
        items = json.loads(out)
        texts = [
            str(content.get("text", ""))
            for item in items if isinstance(item, dict)
            for content in item.get("content", []) or []
            if isinstance(content, dict)
        ]
    except (ValueError, AttributeError):
        texts = [out]
    raw_text = "\n".join(texts)
    if not raw_text.strip():
        # A well-formed but textless response (`[]`, `{}`,
        # `[{"content":[]}]`) is exit 0 with nothing observable, same as
        # empty stdout above - never "ok" with an empty raw_text, which
        # would classify every marker HIDDEN across the board rather than
        # UNMEASURED (cross-model review, PR #90). If `listing.status ==
        # "ok"` the skills block itself contributed text, so raw_text is
        # guaranteed non-blank in that case - this path is reached only
        # when nothing at all was extractable.
        return Rendering("failed", "client output parsed but contained no observable text", "",
                          materialize.Listing("failed"))
    return Rendering("ok", "", raw_text, listing)


#: The Claude Code arm is a declared limit, not a per-run measurement - see
#: the module docstring's "CLAUDE CODE" section for the evidence behind it.
CLAUDE_CODE_UNMEASURED_REASON = (
    "no supported way to render Claude Code's session-start input without an "
    "actual model call was identified (`claude --help`, read 2026-09-26, Claude "
    "Code 2.1.283 pinned per docker/trial/pinned-versions.json): only a generic "
    "--debug/--debug-file verbose-logging flag exists, nothing shaped like "
    "`codex debug prompt-input`"
)


def render_claude_code() -> Rendering:
    return Rendering(UNMEASURED, CLAUDE_CODE_UNMEASURED_REASON, "", materialize.Listing("absent"))


# --------------------------------------------------------------- classification


#: A truncation match must cover at least this fraction of the marker's own
#: text - deep enough into its random nonce (16 hex chars, `secrets.token_hex(8)`)
#: that a coincidental match is not practically possible, and past the
#: fixed, SHARED `MARKER_PREFIX` every marker begins with (cross-model
#: review, PR #90: a naive shortest-acceptable-prefix search could match the
#: literal `MARKER_PREFIX` text inside a DIFFERENT, fully-EXPOSED marker's
#: own rendered text, reporting a HIDDEN marker as falsely TRUNCATED).
_MIN_TRUNCATION_FRACTION = 0.75


def classify_marker(marker: Marker, rendered: str) -> dict[str, object]:
    """A marker's cut point is searched for ANYWHERE in the rendered text,
    never only at its very end (cross-model review, PR #90: a real render
    wraps planted content in closing tags and further messages - `# path
    instructions for <cwd>\\n\\n<INSTRUCTIONS>\\n<content>\\n\\n</INSTRUCTIONS>`,
    then more items after it - so a marker cut mid-string almost never ends
    up at the literal tail of the whole rendered blob, and an `endswith`
    check missed exactly the realistic case it needed to catch)."""
    if marker.text in rendered:
        return {"marker_id": marker.marker_id, "layer": marker.layer, "verdict": EXPOSED, "note": marker.note}
    floor = max(len(MARKER_PREFIX) + 8, int(len(marker.text) * _MIN_TRUNCATION_FRACTION))
    for cut in range(len(marker.text) - 1, floor - 1, -1):
        prefix = marker.text[:cut]
        if prefix in rendered:
            return {
                "marker_id": marker.marker_id, "layer": marker.layer, "verdict": TRUNCATED,
                "note": marker.note, "cut_point_bytes": cut,
            }
    return {"marker_id": marker.marker_id, "layer": marker.layer, "verdict": HIDDEN, "note": marker.note}


def _policy_hidden_cause(skill_dir: Path) -> str | None:
    """Why a skill might be legitimately absent from the listing, if known -
    verified against codex-cli 0.157.1, 2026-09-26: a skill whose
    `agents/openai.yaml` sets `policy.allow_implicit_invocation: false` is
    absent from `debug prompt-input`'s listing entirely."""
    openai_yaml = skill_dir / "agents" / "openai.yaml"
    if not openai_yaml.is_file():
        return None
    try:
        doc = parse_yaml_document(openai_yaml.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, FrontmatterError):
        return None
    policy = doc.get("policy")
    if isinstance(policy, dict) and policy.get("allow_implicit_invocation") is False:
        return "policy (agents/openai.yaml policy.allow_implicit_invocation: false)"
    return None


def _skill_description(skill_dir: Path) -> str | None:
    """A skill's own declared description - natural-language text that could
    legitimately contain almost anything, including an accidental marker
    match, so it belongs in `check_collisions`'s ambient population (the
    module's own docstring already claimed this was checked; cross-model
    review, PR #90, found it was not actually collected anywhere)."""
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        return None
    try:
        frontmatter, _body = parse_frontmatter(skill_md.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, FrontmatterError):
        return None
    description = frontmatter.get("description")
    return description if isinstance(description, str) else None


# ------------------------------------------------------------------------ report


@dataclass(frozen=True)
class ExposureReport:
    client: str
    status: str  # "ok" (a verdict was reached for every declared item) or "refused"
    reason: str | None
    markers: list[dict[str, object]]
    skills: list[dict[str, object]]
    #: The client version actually observed (`--version`), never merely the
    #: subject's declared one - "unknown" when it could not be read (client
    #: absent, or never invoked at all, as for `claude-code`). The
    #: acceptance's own wording: "It records the client version and flags
    #: in effect."
    client_version: str = "unknown"
    #: Config overrides in effect for this run (`-c key=value` pairs) -
    #: empty by default; `check_exposure` has none to declare today, but the
    #: field exists so a future caller passing them has somewhere honest to
    #: record them, rather than silently dropping them from the evidence.
    client_flags: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": "exposure-report", "client": self.client, "client_version": self.client_version,
            "client_flags": list(self.client_flags), "status": self.status,
            "reason": self.reason, "markers": self.markers, "skills": self.skills,
        }


def check_exposure(
    surface: ExposureSurface,
    *,
    base: Path,
    repo: Path | None = None,
    snapshot: Path | None = None,
    client: list[str] | None = None,
    client_name: str = "codex",
    timeout: float = 120,
    keep: bool = False,
) -> ExposureReport:
    """Acquire the source, install the declared skills, plant every marker,
    render once, classify every declared item, then tear down. Never raises
    for a subject or render problem - a refusal comes back as a report with
    an empty verdict list.

    A render that never happened at all (client absent, crashed, hung, or -
    `claude-code`, always - no supported render exists) reports EVERY
    declared marker AND every declared skill as `UNMEASURED`, never an empty
    list: an empty list reads as "nothing was checked", which a blind run
    is not - it is "everything was checked and none of it could be
    observed" (cross-model review would rightly flag the difference, since
    an empty list and a fully-UNMEASURED list both look "clean" to a caller
    that only counts findings)."""
    if client_name not in ("codex", "claude-code"):
        raise Refused(f"unsupported client {client_name!r}: this check supports codex and claude-code")
    if (repo is None) == (snapshot is None):
        raise ValueError("exactly one of repo or snapshot")
    origin = (repo or snapshot)
    assert origin is not None
    origin = origin.resolve()

    root, nonce = materialize.create_root(base, materialize.forbidden_roots(origin))
    try:
        staging = root / "staging"
        staging.mkdir()
        subject = surface.subject
        source = (materialize.acquire_git(subject, origin, staging) if repo is not None
                  else materialize.acquire_snapshot(subject, origin, staging))
        entries = materialize.inventory(subject, source)

        arm = materialize.prepare_arm(root, "exposure", None)
        materialize.install(arm, source, entries)
        version = (
            materialize.client_version(client, arm.home, arm.codex_home, arm.workspace)
            if client_name == "codex" and client is not None else "unknown"
        )

        markers: list[Marker] = []
        for always in surface.always_loaded:
            content, planted = _plant_always_loaded(source.surface_dir, always)
            dest = arm.workspace / always.path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content)
            markers.extend(planted)
        if surface.index is not None:
            content, planted = _plant_index(source.surface_dir, surface.index)
            dest = arm.workspace / surface.index.path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content)
            markers.extend(planted)

        descriptions = [
            d for e in entries
            if (d := _skill_description(source.surface_dir / e.directory)) is not None
        ]
        ambient = [str(root), str(arm.home), str(arm.workspace), *(e.name for e in entries), *descriptions]
        colliding = check_collisions(markers, ambient)
        if colliding:
            names = ", ".join(m.marker_id for m in colliding)
            return ExposureReport(client_name, "refused", f"marker collision: {names}", [], [], client_version=version)

        selected = {e.name: e for e in entries}
        wanted = subject.select if subject.select is not None else tuple(selected)

        rendering = render_codex(client, arm, timeout) if client_name == "codex" else render_claude_code()
        if rendering.status != "ok":
            unmeasured_markers: list[dict[str, object]] = [
                {"marker_id": m.marker_id, "layer": m.layer, "verdict": UNMEASURED, "note": rendering.detail}
                for m in markers
            ]
            unmeasured_skills: list[dict[str, object]] = [
                {"skill": name, "verdict": UNMEASURED, "cause": rendering.detail} for name in wanted
            ]
            return ExposureReport(client_name, "ok", None, unmeasured_markers, unmeasured_skills, client_version=version)

        marker_verdicts = [classify_marker(m, rendering.raw_text) for m in markers]

        listed = (
            {(n, str(Path(p).resolve())) for n, p in rendering.listing.entries}
            if rendering.listing.status == "ok" else set()
        )
        skill_verdicts: list[dict[str, object]] = []
        for name in wanted:
            entry = selected.get(name)
            if entry is None:
                skill_verdicts.append({"skill": name, "verdict": HIDDEN, "cause": "not installed"})
                continue
            path = str((arm.skills / entry.directory / "SKILL.md").resolve())
            if (name, path) in listed:
                skill_verdicts.append({"skill": name, "verdict": EXPOSED, "cause": None})
            else:
                cause = _policy_hidden_cause(source.surface_dir / entry.directory)
                skill_verdicts.append({"skill": name, "verdict": HIDDEN, "cause": cause})

        return ExposureReport(client_name, "ok", None, marker_verdicts, skill_verdicts, client_version=version)
    except Refused as exc:
        return ExposureReport(client_name, "refused", str(exc), [], [])
    finally:
        if not keep:
            materialize.cleanup(root, nonce)
