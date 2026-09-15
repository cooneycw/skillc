"""The Agent Skills specification, as a machine-checkable object.

Sources: agentskills.io/specification and the Anthropic skill-authoring docs.
Stdlib only and on purpose - skillc must run anywhere a skill might be edited,
including a slim CI image with no wheel cache and no network.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

# --- frontmatter fields the specification defines -------------------------------
REQUIRED_FIELDS = frozenset({"name", "description"})
OPTIONAL_FIELDS = frozenset({"license", "compatibility", "metadata", "allowed-tools"})
SPEC_FIELDS = REQUIRED_FIELDS | OPTIONAL_FIELDS

# Claude Code reads these even though the cross-vendor spec does not define them.
# They are tolerated, never required, and never counted as spec fields.
HARNESS_FIELDS = frozenset({"disable-model-invocation", "model", "argument-hint"})

NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
NAME_MAX = 64
DESCRIPTION_MAX = 1024
COMPATIBILITY_MAX = 500

# Body-length guidance: keep SKILL.md under 500 lines, disclose the rest.
BODY_LINE_BUDGET = 500

FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)


class FrontmatterError(ValueError):
    """The frontmatter block is absent or structurally invalid."""


def _scalar(raw: str) -> str:
    value = raw.strip()
    if value[:1] in {'"', "'"}:
        try:
            parsed = ast.literal_eval(value)
        except (SyntaxError, ValueError) as exc:
            raise FrontmatterError(f"invalid quoted scalar: {value}") from exc
        if not isinstance(parsed, str):
            raise FrontmatterError(f"frontmatter scalars must be strings: {value}")
        return parsed
    return value


def parse_frontmatter(text: str) -> tuple[dict[str, object], str]:
    """Parse the strict YAML subset skill frontmatter is allowed to use.

    Nested mappings and string scalars only. Rejecting richer YAML keeps the
    parser small enough to audit, which matters more here than convenience:
    this is the code that decides whether a skill is well-formed.
    """
    match = FRONTMATTER_RE.match(text)
    if not match:
        raise FrontmatterError("no YAML frontmatter block")

    root: dict[str, object] = {}
    stack: list[tuple[int, dict[str, object]]] = [(-1, root)]

    for lineno, raw_line in enumerate(match.group(1).split("\n"), start=2):
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent_src = raw_line[: len(raw_line) - len(raw_line.lstrip())]
        if "\t" in indent_src:
            raise FrontmatterError(f"line {lineno}: tabs are not valid indentation")
        indent = len(indent_src)
        key, sep, raw_value = raw_line.strip().partition(":")
        if not sep or not key.strip():
            raise FrontmatterError(f"line {lineno}: expected 'key: value'")
        while stack and indent <= stack[-1][0]:
            stack.pop()
        if not stack:
            raise FrontmatterError(f"line {lineno}: invalid indentation")
        parent = stack[-1][1]
        key = key.strip()
        if raw_value.strip():
            parent[key] = _scalar(raw_value)
        else:
            child: dict[str, object] = {}
            parent[key] = child
            stack.append((indent, child))

    return root, text[match.end():]


@dataclass
class Skill:
    """One SKILL.md and the directory it governs."""

    path: Path
    frontmatter: dict[str, object] = field(default_factory=dict)
    body: str = ""
    parse_error: str | None = None

    @property
    def dir_name(self) -> str:
        return self.path.parent.name

    @property
    def body_lines(self) -> int:
        return len(self.body.splitlines())

    def get(self, key: str) -> str | None:
        value = self.frontmatter.get(key)
        return value if isinstance(value, str) else None

    @classmethod
    def load(cls, path: Path) -> Skill:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            return cls(path=path, parse_error=f"unreadable: {exc}")
        try:
            frontmatter, body = parse_frontmatter(text)
        except FrontmatterError as exc:
            return cls(path=path, parse_error=str(exc))
        return cls(path=path, frontmatter=frontmatter, body=body)


def discover(root: Path) -> list[Skill]:
    """Every SKILL.md at or below root, in a stable order."""
    if root.is_file() and root.name == "SKILL.md":
        return [Skill.load(root)]
    return [Skill.load(p) for p in sorted(root.rglob("SKILL.md"))]
