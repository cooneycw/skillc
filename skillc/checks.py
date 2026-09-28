"""The rules, and the committed input that proves each one can fail.

Every rule declares `control`: the fixture directory under `controls/<id>/` that
holds a `bad/` case the rule MUST fire on and a `good/` case it MUST stay silent
on. `skillc selftest` runs that pairing. A rule without a passing control is not
evidence, and skillc refuses to report it as one.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from . import records
from .spec import (
    BODY_LINE_BUDGET,
    CLAUDE_CODE,
    COMPATIBILITY_MAX,
    DEFAULT_TARGET,
    DESCRIPTION_MAX,
    NAME_MAX,
    NAME_RE,
    PORTABLE,
    REQUIRED_FIELDS,
    SPEC_FIELDS,
    TARGETS,
    FrontmatterError,
    Manifest,
    ManifestError,
    Skill,
    manifest_entry,
    parse_yaml_document,
)

ERROR = "error"
WARN = "warn"

# A description earns its place by saying WHEN to reach for the skill. These are
# the shapes that state a triggering condition rather than a capability.
TRIGGER_RE = re.compile(
    r"\b(use (this )?(skill )?(when|whenever|for)|use when|when the user|when you|"
    r"whenever the user|whenever you|invoke when|trigger(s|ed)? (when|on)|"
    r"reach for (this|it) when|applies when)\b",
    re.IGNORECASE,
)
MD_LINK_RE = re.compile(r"\[[^\]]*\]\(\s*<?([^\s)>#]+\.md)")


@dataclass(frozen=True)
class Finding:
    rule: str
    severity: str
    path: Path
    detail: str

    def render(self, root: Path) -> str:
        try:
            shown: Path | str = self.path.relative_to(root)
        except ValueError:
            shown = self.path
        return f"{self.severity:5} {self.rule:20} {shown}: {self.detail}"


@dataclass(frozen=True)
class Rule:
    """A rule whose subject is one SKILL.md.

    `parser` is the explicit expectation for the one kind of rule allowed to be
    proven by input that does not parse. A semantic rule (`parser=False`) must be
    proven on subjects that DO parse, or a parse failure could stand in for it;
    a parser rule must be proven on at least one subject that does NOT.

    `target` scopes a rule to one client profile (spec.TARGETS). A rule with no
    target applies everywhere; a scoped rule runs only when its target is the one
    selected, because a claim about which fields load is only true of a named
    client. `check` is always handed the ACTIVE target, even for a rule with no
    `target` of its own, so a rule that applies everywhere can still vary what it
    says between profiles (`trigger-shape` is the one that does).
    """

    id: str
    severity: str
    summary: str
    check: Callable[[Skill, str], Iterator[str]]
    parser: bool = False
    target: str | None = None


def _frontmatter(skill: Skill, target: str) -> Iterator[str]:
    if skill.parse_error is not None:
        yield skill.parse_error


def _name_spec(skill: Skill, target: str) -> Iterator[str]:
    name = skill.get("name")
    if name is None:
        return
    if not NAME_RE.match(name):
        yield (
            f"name {name!r} is not [a-z0-9] with single hyphens "
            f"(no uppercase, spaces, punctuation, leading/trailing/double hyphen)"
        )
    elif len(name) > NAME_MAX:
        yield f"name is {len(name)} characters, over the {NAME_MAX} limit"
    if name != skill.dir_name:
        yield f"name {name!r} does not match its directory {skill.dir_name!r}"


def _kind(value: object) -> str:
    if value is None:
        return "null (no value)"
    if isinstance(value, bool):
        return f"a boolean ({value!r})"
    if isinstance(value, int | float):
        return f"a number ({value!r})"
    if isinstance(value, dict):
        return "a mapping"
    if isinstance(value, list):
        return "a list"
    return type(value).__name__  # pragma: no cover - the parser yields no other type


def _required_fields(skill: Skill, target: str) -> Iterator[str]:
    # This rule OWNS the type of a required field. The rules that read one
    # (`name-spec`, `trigger-shape`) see only strings via `Skill.get`, so a
    # mapping-valued name used to pass every rule unexamined.
    for key in sorted(REQUIRED_FIELDS):
        if key not in skill.frontmatter:
            yield f"missing required field {key!r}"
            continue
        value = skill.frontmatter[key]
        if not isinstance(value, str):
            yield f"{key} must be a string, got {_kind(value)}"
        elif not value.strip():
            yield f"{key} is empty"
    description = skill.get("description")
    if description and len(description) > DESCRIPTION_MAX:
        yield f"description is {len(description)} characters, over the {DESCRIPTION_MAX} limit"
    compatibility = skill.get("compatibility")
    if compatibility and len(compatibility) > COMPATIBILITY_MAX:
        yield f"compatibility is {len(compatibility)} characters, over {COMPATIBILITY_MAX}"


def _trigger_shape(skill: Skill, target: str) -> Iterator[str]:
    description = skill.get("description")
    if not description or not description.strip():
        return  # required-fields owns that failure; do not double-report
    if TRIGGER_RE.search(description):
        return
    if target == CLAUDE_CODE.id and skill.frontmatter.get("disable-model-invocation") is True:
        # The model cannot fire a user-invoked skill, so it never reads this
        # description to decide whether to - the premise this rule warns
        # under does not hold for this client. Under `portable` the field is
        # a Claude Code extension a conforming client need not honour, so the
        # description may still steer auto-selection there; keep warning.
        # See docs/frontmatter.md#trigger-shape-and-user-invoked-skills.
        return
    yield (
        "description states a capability but no triggering condition - "
        "the model reads this to decide whether to fire the skill"
    )


def _unknown_field(skill: Skill, target: str) -> Iterator[str]:
    """Target `portable`: a field the Agent Skills specification does not define."""
    for key in sorted(set(skill.frontmatter) - SPEC_FIELDS):
        if key in CLAUDE_CODE.extensions:
            yield (
                f"{key!r} is a {CLAUDE_CODE.label} extension, not an Agent Skills "
                f"specification field; other clients may ignore it "
                f"(check with --target {CLAUDE_CODE.id} if that is the only client)"
            )
        else:
            yield (
                f"{key!r} is not an Agent Skills specification field, nor one any "
                f"target profile skillc knows documents; content here may be inert. "
                f"Fold it into 'description' or 'metadata'"
            )


def _claude_code_field(skill: Skill, target: str) -> Iterator[str]:
    """Target `claude-code`: a field outside the spec AND Claude Code's documentation."""
    for key in sorted(set(skill.frontmatter) - CLAUDE_CODE.fields):
        yield (
            f"{key!r} is not a field {CLAUDE_CODE.label} documents (profile read from "
            f"{CLAUDE_CODE.source} on {CLAUDE_CODE.verified}); content here is inert "
            f"for that client. Fold it into 'description' or 'metadata'"
        )


def _body_budget(skill: Skill, target: str) -> Iterator[str]:
    if skill.body_lines > BODY_LINE_BUDGET:
        yield (
            f"body is {skill.body_lines} lines, over the {BODY_LINE_BUDGET}-line budget - "
            f"disclose branch-specific material behind a reference"
        )


def _ref_depth(skill: Skill, target: str) -> Iterator[str]:
    """A second-hop link only counts if it is a NEW file: not SKILL.md itself,
    and not something SKILL.md already links directly. A back-link to the entry
    point, or a sibling already linked from SKILL.md, is not a deeper chain -
    the agent reaches it either way. Every distinct chain is reported, sorted
    by (first-hop, second-hop) for deterministic output, not just the first.
    """
    base = skill.path.parent
    skill_path = skill.path.resolve()
    first_hop_links = MD_LINK_RE.findall(skill.body)
    first_hop_paths = {
        resolved for link in first_hop_links if (resolved := (base / link).resolve()).is_file()
    }
    chains: set[tuple[str, str]] = set()
    for link in first_hop_links:
        first = (base / link).resolve()
        if first not in first_hop_paths:
            continue
        try:
            nested = MD_LINK_RE.findall(first.read_text(encoding="utf-8"))
        except (OSError, UnicodeError):
            continue
        for second in nested:
            resolved_second = (first.parent / second).resolve()
            if not resolved_second.is_file():
                continue
            if resolved_second == skill_path or resolved_second in first_hop_paths:
                continue
            chains.add((link, second))
    for link, second in sorted(chains):
        yield (
            f"{link} links on to {second}: references must stay one level "
            f"deep or the agent reads only part of the chain"
        )


# mattpocock/skills' own convention for shipping to more than one client
# (`.agents/invocation.md`), read 2026-09-26 at c55ee46073ed923f86ce59a5eb3b6d895095d1b7
# (#50). Not a Codex specification - `agents/openai.yaml` is an upstream
# convention, so there is nothing else to cite; this date is what a later change
# to that convention would need to invalidate.
CODEX_POLICY_READ = "2026-09-26"


def _invocation_consistency(skill: Skill, target: str) -> Iterator[str]:
    """Target `claude-code`: Claude Code's `disable-model-invocation` and Codex's
    `agents/openai.yaml` `policy.allow_implicit_invocation` both say whether the
    MODEL may invoke a skill without being asked. A skill that ships to both
    clients can end up user-invoked in one and auto-selectable in the other if
    the two disagree - exactly the split skillc exists to surface, and one no
    other rule reads `agents/openai.yaml` to catch.

    Scoped to `claude-code` for the same reason `claude-code-field` is: the
    portable specification has no invocation control at all, so under
    `--target portable` `disable-model-invocation` is already reported as a
    non-portable extension by `unknown-field`, and "does Claude Code's
    invocation flag agree with Codex's" is not a claim the portable profile has
    any stake in.

    Silent when `agents/openai.yaml` is absent: that file is an upstream
    convention, not a specification requirement, so a skill that never carries
    it says nothing about a second client to compare against.
    """
    openai_yaml = skill.path.parent / "agents" / "openai.yaml"
    if not openai_yaml.is_file():
        return
    try:
        text = openai_yaml.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        yield f"agents/openai.yaml is unreadable: {exc}"
        return
    try:
        doc = parse_yaml_document(text)
    except FrontmatterError as exc:
        # A file skillc cannot read says nothing about agreement - reported,
        # never silently folded into "consistent" the way absence is.
        yield f"agents/openai.yaml {exc}"
        return

    # `in` on purpose, not `.get(...) is not None`: an ABSENT key defaults (below),
    # but a key present with an explicit `null` is a value of the wrong type, same
    # as any other wrong type, and `.get` cannot tell the two apart.
    policy: dict[str, object] = {}
    if "policy" in doc:
        found = doc["policy"]
        if not isinstance(found, dict):
            yield f"agents/openai.yaml policy is {_kind(found)}, not a mapping - cannot compare"
            return
        policy = found
    allow_implicit: object = None
    if "allow_implicit_invocation" in policy:
        allow_implicit = policy["allow_implicit_invocation"]
        if not isinstance(allow_implicit, bool):
            yield (
                f"agents/openai.yaml policy.allow_implicit_invocation is {_kind(allow_implicit)}, "
                f"not a boolean - cannot compare"
            )
            return

    # Absence defaults to "the model may invoke it" on BOTH sides - the same
    # default `disable-model-invocation` already has in Claude Code.
    codex_user_invoked = allow_implicit is False
    claude_user_invoked = skill.frontmatter.get("disable-model-invocation") is True
    if claude_user_invoked == codex_user_invoked:
        return
    claude_label = "user-invoked" if claude_user_invoked else "model-invoked"
    codex_label = "user-invoked" if codex_user_invoked else "model-invoked"
    yield (
        f"disable-model-invocation makes this skill {claude_label} in Claude Code, but "
        f"agents/openai.yaml's policy.allow_implicit_invocation makes it {codex_label} in "
        f"Codex - keep the two in sync (a skill is user-invoked in both harnesses or neither)"
    )


RULES: tuple[Rule, ...] = (
    Rule("name-spec", ERROR, "name is spec-legal and matches its directory", _name_spec),
    Rule("required-fields", ERROR, "required frontmatter is present and in range", _required_fields),
    Rule("trigger-shape", WARN, "description says when to fire, not just what it does", _trigger_shape),
    Rule("unknown-field", WARN, "every field is defined by the portable specification",
         _unknown_field, target=PORTABLE),
    Rule("claude-code-field", WARN, "every field is one Claude Code documents",
         _claude_code_field, target=CLAUDE_CODE.id),
    Rule("body-budget", WARN, "SKILL.md body stays inside the line budget", _body_budget),
    Rule("ref-depth", WARN, "references stay one level deep", _ref_depth),
    Rule("invocation-consistency", ERROR,
         "Claude Code's disable-model-invocation and Codex's agents/openai.yaml agree",
         _invocation_consistency, target=CLAUDE_CODE.id),
    Rule("frontmatter", ERROR, "frontmatter is present and parses", _frontmatter, parser=True),
)

#: The parser rule. `run` applies ONLY this rule to a SKILL.md that did not parse,
#: whichever rule was asked for - no other rule has anything to read.
PARSER_RULE = "frontmatter"

RULES_BY_ID = {rule.id: rule for rule in RULES}


@dataclass(frozen=True)
class RecordRule:
    """A rule whose subject is an evaluation record rather than a SKILL.md.

    It is a SEPARATE type so `Rule.check` is not loosened to a union for the sake
    of one new family - but it is NOT a separate machinery. `selftest` keeps one
    coverage check, one counter and one exit code over `ALL_RULES`, and dispatches
    only where the subject is loaded. Splitting the guarantee that "a check with no
    control is UNPROVEN" across two arms is how one arm later goes unenforced.

    `kinds` is the record kinds this rule actually reads (issue #131 item 2):
    `check.__code__`'s own early-exit guard already decides this internally
    (`if record.kind != SOME_KIND: return`), but nothing outside the function
    could see it, so `--rule installation-receipt` over a population with no
    installation-receipt record ran the check on every record, got silence
    from every one of its own no-op guards, and reported "0 error(s)" -
    indistinguishable from a population that WAS examined and found clean.
    `cmd_check_records` reports how many discovered records are actually
    `kinds`-applicable under a `--rule` selection, and refuses (rather than
    reporting a green over zero) when that count is zero."""

    id: str
    severity: str
    summary: str
    check: Callable[[records.Record], Iterator[str]]
    kinds: tuple[str, ...]
    parser: bool = False


RECORD_RULES: tuple[RecordRule, ...] = (
    RecordRule("record-envelope", ERROR, "record declares a version this build can read",
               records.record_envelope, records.KINDS, parser=True),
    RecordRule("producer-authority", ERROR, "record declares the one producer allowed for its kind",
               records.producer_authority, records.KINDS),
    RecordRule("attempt-binding", ERROR, "record cites a well-formed attempt and trial",
               records.attempt_binding, records.ATTEMPT_BOUND),
    RecordRule("installation-receipt", ERROR, "receipt records what was installed and whether it was ready",
               records.installation_receipt, (records.INSTALLATION_RECEIPT,)),
    RecordRule("trial-ledger", ERROR, "ledger plans a non-empty population under full identities",
               records.trial_ledger, (records.TRIAL_LEDGER,)),
    RecordRule("artifact-digest", ERROR, "every captured artifact carries its identity",
               records.artifact_digest, (records.ARTIFACT_MANIFEST,)),
    RecordRule("observation-coverage", ERROR, "every required stream declares its origin and coverage",
               records.observation_coverage, (records.ARTIFACT_MANIFEST,)),
    RecordRule("criterion-vocabulary", ERROR, "criteria use the specified outcomes",
               records.criterion_vocabulary, (records.VERIFIED_RESULT,)),
    RecordRule("result-evidence", ERROR, "result names its grader, what it graded and each criterion's evidence",
               records.result_evidence, (records.VERIFIED_RESULT,)),
    RecordRule("derived-status", ERROR, "status follows from the criteria, not from a claim",
               records.derived_status, (records.VERIFIED_RESULT,)),
    RecordRule("verdict-tiers", ERROR, "a per-tier verdict names a tier this result actually enabled",
               records.verdict_tiers, (records.VERIFIED_RESULT,)),
    RecordRule("attempt-lifecycle", ERROR, "controller accounts for how an attempt ended and why",
               records.attempt_lifecycle, (records.ATTEMPT_LIFECYCLE,)),
    RecordRule("agent-observation", ERROR, "a real agent's observation agrees with itself: eligibility, grading account, grade vs criteria",
               records.agent_observation, (records.AGENT_OBSERVATION,)),
    RecordRule("pilot-report", ERROR, "report gives every attempt a disposition, criteria, uncertainty and a cost/time split",
               records.pilot_report, (records.PILOT_REPORT,)),
)


@dataclass(frozen=True)
class BundleRule:
    """A rule whose subject is a BUNDLE: a ledger and the records bound to it.

    Some facts exist only between records - that a receipt belongs to the attempt
    the ledger planned, that no planned attempt went missing. Like `RecordRule` it
    is a separate TYPE and not a separate machinery: it sits in `ALL_RULES`, and
    `selftest` differs for it only where the subject is loaded.
    """

    id: str
    severity: str
    summary: str
    check: Callable[[records.Bundle], Iterator[str]]
    parser: bool = False


BUNDLE_RULES: tuple[BundleRule, ...] = (
    BundleRule("ledger-binding", ERROR, "records bind to an attempt the ledger planned, under its identities",
               records.ledger_binding),
    BundleRule("unique-ids", ERROR, "no identifier is duplicated or claimed by conflicting records",
               records.unique_ids),
    BundleRule("attempt-accounting", ERROR, "every planned attempt is accounted for with its evidence",
               records.attempt_accounting),
    BundleRule("lineage", ERROR, "retries and regrades link to originals that are retained",
               records.lineage),
)


@dataclass(frozen=True)
class ManifestRule:
    """A rule whose subject is a plugin manifest (issue #131 item 3).

    `check --manifest` used to build its `manifest-entry` `Finding` straight
    in `cli.py`, entirely outside `Rule`/`RecordRule`/`BundleRule` and the
    registries `selftest` iterates - so `selftest` could report "N/N rules
    discriminate" while this specific check was never proven able to fail at
    all. Its committed controls (`controls/manifest-entry/{bad,good}`)
    already existed, exercised only by pytest directly. This is a separate
    TYPE for the same reason `BundleRule` is: the subject a manifest rule
    loads (a `Manifest`) is neither a `Skill` nor a `records.Record`, but it
    sits in the SAME `ALL_RULES` `selftest` already iterates.
    """

    id: str
    severity: str
    summary: str
    check: Callable[[Manifest], Iterator[str]]
    parser: bool = False


MANIFEST_RULES: tuple[ManifestRule, ...] = (
    ManifestRule("manifest-entry", ERROR, "every manifest-declared skill directory has a SKILL.md",
                 manifest_entry),
)


def run_manifest(case: Path, only: str | None = None) -> tuple[list[Finding], str | None]:
    """Apply every manifest rule (or one) to the manifest at
    `case/.claude-plugin/plugin.json` - the convention both `cmd_check
    --manifest` and the committed `controls/manifest-entry/*` fixtures use.

    Returns `(findings, load_error)`: a manifest that fails to load at all is
    not a `manifest-entry` finding, it is a reason nothing here could be
    checked - the same distinction `bundle_at` draws for an unreadable trial
    ledger, kept separate so a load failure is never silently read as "zero
    dangling entries found"."""
    require_known(only, MANIFEST_RULES)
    manifest_path = case / ".claude-plugin" / "plugin.json"
    try:
        manifest = Manifest.load(manifest_path)
    except ManifestError as exc:
        return [], str(exc)
    findings: list[Finding] = []
    for rule in MANIFEST_RULES:
        if only and rule.id != only:
            continue
        findings.extend(
            Finding(rule.id, rule.severity, manifest_path, detail)
            for detail in rule.check(manifest)
        )
    return findings, None


def evidence_rules() -> tuple[RecordRule | BundleRule, ...]:
    """Every rule `check-records` can run, either family - resolved at CALL time,
    so a registry patched in a test is the registry the selector is checked against."""
    return RECORD_RULES + BUNDLE_RULES


def record_rule_by_id(rule_id: str) -> RecordRule | None:
    """The `RecordRule` named `rule_id`, or `None` when it names a `BundleRule`
    (or nothing) instead - `cmd_check_records`'s own way to ask "does `only`
    name a record rule, and if so, which kinds does it read?" without
    re-deriving `evidence_rules()`'s search."""
    return next((r for r in RECORD_RULES if r.id == rule_id), None)


def applicable_population(rule: RecordRule, found: list[records.Record]) -> int:
    """How many of `found` are `rule.kinds`-applicable (issue #131 item 2) -
    the population a `--rule <rule.id>` selection actually examines, as
    opposed to how many records were merely discovered. `0` here means the
    rule's own `record.kind != ...` guard silently declined every one of
    them, which a bare "0 error(s)" cannot be told apart from."""
    return sum(1 for record in found if record.kind in rule.kinds)

#: ONE registry. `selftest` iterates this; the coverage check, the totals and the
#: exit code never learn which family a rule came from.
ALL_RULES: tuple[Rule | RecordRule | BundleRule | ManifestRule, ...] = (
    RULES + RECORD_RULES + BUNDLE_RULES + MANIFEST_RULES
)


def require_known(
    only: str | None,
    family: (
        tuple[Rule, ...] | tuple[RecordRule, ...] | tuple[ManifestRule, ...]
        | tuple[RecordRule | BundleRule, ...]
    ),
) -> None:
    """An unknown selector is a caller error, never a request to check nothing.

    Filtering by an id that matches no rule used to return zero findings, which
    reads exactly like a clean run.
    """
    if only is not None and all(rule.id != only for rule in family):
        known = ", ".join(rule.id for rule in family)
        raise ValueError(f"unknown rule {only!r}; known rules: {known}")


def run_record(record: records.Record, only: str | None = None) -> list[Finding]:
    """Apply every record rule (or one) to a single record.

    `only` may name a bundle rule; that selects no record rule, which is correct
    and not a silent no-op - `check-records` runs the bundle rule on bundles.
    """
    require_known(only, evidence_rules())
    findings: list[Finding] = []
    for rule in RECORD_RULES:
        if only and rule.id != only:
            continue
        findings.extend(
            Finding(rule.id, rule.severity, record.path, detail)
            for detail in rule.check(record)
        )
    return findings


def run_bundle(bundle: records.Bundle, only: str | None = None) -> list[Finding]:
    """Apply every bundle rule (or one) to a single bundle."""
    require_known(only, evidence_rules())
    findings: list[Finding] = []
    for rule in BUNDLE_RULES:
        if only and rule.id != only:
            continue
        findings.extend(
            Finding(rule.id, rule.severity, bundle.path, detail)
            for detail in rule.check(bundle)
        )
    return findings


def require_target(target: str) -> None:
    """An unknown target is a caller error, never a request for no field rules."""
    if target not in TARGETS:
        raise ValueError(f"unknown target {target!r}; known targets: {', '.join(TARGETS)}")


def run(skill: Skill, only: str | None = None, target: str = DEFAULT_TARGET) -> list[Finding]:
    """Apply every rule for `target` (or exactly one rule) to a single skill.

    Naming a rule with `only` runs it whatever its target: the caller has said
    which claim they want checked.

    A SKILL.md that does not parse gets the parser rule's finding and nothing
    else, WHICHEVER rule was selected: `skillc check --rule name-spec` must still
    hear that the file is unreadable. That is also why a finding's `rule` - not
    its presence - is what `selftest` credits (tests/test_records.py).
    """
    require_known(only, RULES)
    require_target(target)
    if skill.parse_error is not None:
        selected = [rule for rule in RULES if rule.id == PARSER_RULE]
    elif only:
        selected = [rule for rule in RULES if rule.id == only]
    else:
        selected = [rule for rule in RULES if rule.target in (None, target)]
    findings: list[Finding] = []
    for rule in selected:
        findings.extend(
            Finding(rule.id, rule.severity, skill.path, detail)
            for detail in rule.check(skill, target)
        )
    return findings
