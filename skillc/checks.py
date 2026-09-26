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
    Skill,
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
    client.
    """

    id: str
    severity: str
    summary: str
    check: Callable[[Skill], Iterator[str]]
    parser: bool = False
    target: str | None = None


def _frontmatter(skill: Skill) -> Iterator[str]:
    if skill.parse_error is not None:
        yield skill.parse_error


def _name_spec(skill: Skill) -> Iterator[str]:
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


def _required_fields(skill: Skill) -> Iterator[str]:
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


def _trigger_shape(skill: Skill) -> Iterator[str]:
    description = skill.get("description")
    if not description or not description.strip():
        return  # required-fields owns that failure; do not double-report
    if not TRIGGER_RE.search(description):
        yield (
            "description states a capability but no triggering condition - "
            "the model reads this to decide whether to fire the skill"
        )


def _unknown_field(skill: Skill) -> Iterator[str]:
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


def _claude_code_field(skill: Skill) -> Iterator[str]:
    """Target `claude-code`: a field outside the spec AND Claude Code's documentation."""
    for key in sorted(set(skill.frontmatter) - CLAUDE_CODE.fields):
        yield (
            f"{key!r} is not a field {CLAUDE_CODE.label} documents (profile read from "
            f"{CLAUDE_CODE.source} on {CLAUDE_CODE.verified}); content here is inert "
            f"for that client. Fold it into 'description' or 'metadata'"
        )


def _body_budget(skill: Skill) -> Iterator[str]:
    if skill.body_lines > BODY_LINE_BUDGET:
        yield (
            f"body is {skill.body_lines} lines, over the {BODY_LINE_BUDGET}-line budget - "
            f"disclose branch-specific material behind a reference"
        )


def _ref_depth(skill: Skill) -> Iterator[str]:
    base = skill.path.parent
    for target in MD_LINK_RE.findall(skill.body):
        first = (base / target).resolve()
        if not first.is_file():
            continue
        try:
            nested = MD_LINK_RE.findall(first.read_text(encoding="utf-8"))
        except (OSError, UnicodeError):
            continue
        for second in nested:
            if (first.parent / second).resolve().is_file():
                yield (
                    f"{target} links on to {second}: references must stay one level "
                    f"deep or the agent reads only part of the chain"
                )
                return


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
    """

    id: str
    severity: str
    summary: str
    check: Callable[[records.Record], Iterator[str]]
    parser: bool = False


RECORD_RULES: tuple[RecordRule, ...] = (
    RecordRule("record-envelope", ERROR, "record declares a version this build can read",
               records.record_envelope, parser=True),
    RecordRule("attempt-binding", ERROR, "record cites the attempt it belongs to",
               records.attempt_binding),
    RecordRule("artifact-digest", ERROR, "every captured artifact carries its identity",
               records.artifact_digest),
    RecordRule("criterion-vocabulary", ERROR, "criteria use the specified outcomes",
               records.criterion_vocabulary),
    RecordRule("derived-status", ERROR, "status follows from the criteria, not from a claim",
               records.derived_status),
)

#: ONE registry. `selftest` iterates this; the coverage check, the totals and the
#: exit code never learn which family a rule came from.
ALL_RULES: tuple[Rule | RecordRule, ...] = RULES + RECORD_RULES


def require_known(only: str | None, family: tuple[Rule, ...] | tuple[RecordRule, ...]) -> None:
    """An unknown selector is a caller error, never a request to check nothing.

    Filtering by an id that matches no rule used to return zero findings, which
    reads exactly like a clean run.
    """
    if only is not None and all(rule.id != only for rule in family):
        known = ", ".join(rule.id for rule in family)
        raise ValueError(f"unknown rule {only!r}; known rules: {known}")


def run_record(record: records.Record, only: str | None = None) -> list[Finding]:
    """Apply every record rule (or one) to a single record."""
    require_known(only, RECORD_RULES)
    findings: list[Finding] = []
    for rule in RECORD_RULES:
        if only and rule.id != only:
            continue
        findings.extend(
            Finding(rule.id, rule.severity, record.path, detail)
            for detail in rule.check(record)
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
            Finding(rule.id, rule.severity, skill.path, detail) for detail in rule.check(skill)
        )
    return findings
