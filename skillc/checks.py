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

from .spec import (
    BODY_LINE_BUDGET,
    COMPATIBILITY_MAX,
    DESCRIPTION_MAX,
    HARNESS_FIELDS,
    NAME_MAX,
    NAME_RE,
    REQUIRED_FIELDS,
    SPEC_FIELDS,
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
    id: str
    severity: str
    summary: str
    check: Callable[[Skill], Iterator[str]]


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


def _required_fields(skill: Skill) -> Iterator[str]:
    for missing in sorted(REQUIRED_FIELDS - set(skill.frontmatter)):
        yield f"missing required field {missing!r}"
    description = skill.get("description")
    if description is not None and not description.strip():
        yield "description is empty"
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
    for key in sorted(set(skill.frontmatter) - SPEC_FIELDS - HARNESS_FIELDS):
        yield (
            f"{key!r} is not a field any harness loads; content here is inert. "
            f"Fold it into 'description' or 'metadata'"
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
    Rule("unknown-field", WARN, "no content parked in a field nothing loads", _unknown_field),
    Rule("body-budget", WARN, "SKILL.md body stays inside the line budget", _body_budget),
    Rule("ref-depth", WARN, "references stay one level deep", _ref_depth),
)

RULES_BY_ID = {rule.id: rule for rule in RULES}


def run(skill: Skill, only: str | None = None) -> list[Finding]:
    """Apply every rule (or one) to a single skill."""
    if skill.parse_error is not None:
        return [Finding("frontmatter", ERROR, skill.path, skill.parse_error)]
    findings: list[Finding] = []
    for rule in RULES:
        if only and rule.id != only:
            continue
        findings.extend(
            Finding(rule.id, rule.severity, skill.path, detail) for detail in rule.check(skill)
        )
    return findings
