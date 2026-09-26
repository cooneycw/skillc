"""The Agent Skills specification, as a machine-checkable object.

Sources: agentskills.io/specification and the Anthropic skill-authoring docs.
Stdlib only and on purpose - skillc must run anywhere a skill might be edited,
including a slim CI image with no wheel cache and no network.

The frontmatter parser reads a documented SUBSET of YAML, not YAML. What it
accepts, what it diagnoses and why is in docs/frontmatter.md; keep the two in
step.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

# --- frontmatter fields the portable specification defines ----------------------
# agentskills.io/specification. These are the only fields a skill can rely on
# every conforming client to know about.
REQUIRED_FIELDS = frozenset({"name", "description"})
OPTIONAL_FIELDS = frozenset({"license", "compatibility", "metadata", "allowed-tools"})
SPEC_FIELDS = REQUIRED_FIELDS | OPTIONAL_FIELDS

PORTABLE = "portable"


@dataclass(frozen=True)
class TargetProfile:
    """The fields ONE client documents beyond the portable specification.

    A profile is a dated reading of that client's own documentation, not a
    measurement of what it loads. `verified` says when the reading was taken;
    re-read `source` before relying on it after the client changes.
    """

    id: str
    label: str
    extensions: frozenset[str]
    source: str
    verified: str

    @property
    def fields(self) -> frozenset[str]:
        return SPEC_FIELDS | self.extensions


CLAUDE_CODE = TargetProfile(
    id="claude-code",
    label="Claude Code",
    extensions=frozenset({
        "when_to_use", "argument-hint", "arguments", "disable-model-invocation",
        "user-invocable", "disallowed-tools", "model", "effort", "context", "agent",
        "background", "hooks", "paths", "shell",
    }),
    source="https://code.claude.com/docs/en/skills#frontmatter-reference",
    verified="2026-09-25",
)

TARGET_PROFILES: dict[str, TargetProfile] = {CLAUDE_CODE.id: CLAUDE_CODE}
TARGETS = (PORTABLE, *TARGET_PROFILES)
DEFAULT_TARGET = PORTABLE

NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
NAME_MAX = 64
DESCRIPTION_MAX = 1024
COMPATIBILITY_MAX = 500

# Body-length guidance: keep SKILL.md under 500 lines, disclose the rest.
BODY_LINE_BUDGET = 500

FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)

SUBSET_DOC = "docs/frontmatter.md"


class FrontmatterError(ValueError):
    """The frontmatter block is absent or structurally invalid."""


def _invalid(lineno: int, what: str) -> FrontmatterError:
    return FrontmatterError(f"line {lineno}: invalid YAML: {what}")


def _unsupported(lineno: int, what: str) -> FrontmatterError:
    # Distinct from `_invalid` on purpose: this input may be perfectly good YAML.
    # The finding is that skillc cannot read it, so nothing else was checked -
    # which is still an error, because an unchecked skill must not read as clean.
    return FrontmatterError(
        f"line {lineno}: {what} is outside the YAML subset skillc reads "
        f"({SUBSET_DOC}); it may be valid YAML, but nothing else in this skill was checked"
    )


# --- scalars ---------------------------------------------------------------------
# Plain scalars resolve by the YAML 1.2 core schema, so `name: 123` is a number and
# `description: true` a boolean, exactly as a real YAML loader would hand them over.
_NULL = frozenset({"~", "null", "Null", "NULL"})
_TRUE = frozenset({"true", "True", "TRUE"})
_FALSE = frozenset({"false", "False", "FALSE"})
_INT_RE = re.compile(r"[-+]?[0-9]+\Z")
_OCT_RE = re.compile(r"0o[0-7]+\Z")
_HEX_RE = re.compile(r"0x[0-9a-fA-F]+\Z")
_FLOAT_RE = re.compile(r"[-+]?(\.[0-9]+|[0-9]+(\.[0-9]*)?)([eE][-+]?[0-9]+)?\Z")
_INF_RE = re.compile(r"[-+]?\.(inf|Inf|INF)\Z")
_NAN_RE = re.compile(r"\.(nan|NaN|NAN)\Z")

# First characters a plain scalar may not start with, and what they would mean.
_INDICATORS = {
    "[": ("a flow sequence", True), "{": ("a flow mapping", True),
    "&": ("an anchor", True), "*": ("an alias", True), "!": ("a tag", True),
    "@": ("a reserved indicator '@'", False), "`": ("a reserved indicator '`'", False),
    "%": ("a directive indicator '%'", False), "]": ("an unmatched ']'", False),
    "}": ("an unmatched '}'", False), ",": ("a leading ','", False),
    "|": ("a malformed block header", False), ">": ("a malformed block header", False),
}

# Double-quoted escapes, per YAML 1.2 section 5.7.
_ESCAPES = {
    "0": "\0", "a": "\a", "b": "\b", "t": "\t", "\t": "\t", "n": "\n",
    "v": "\v", "f": "\f", "r": "\r", "e": "\x1b", " ": " ", '"': '"', "/": "/",
    "\\": "\\", "N": "\x85", "_": "\xa0", "L": "\u2028", "P": "\u2029",
}
_HEX_ESCAPES = {"x": 2, "u": 4, "U": 8}


def _resolve_plain(value: str, lineno: int) -> object:
    if value in _NULL:
        return None
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    if _INT_RE.match(value) or _OCT_RE.match(value) or _HEX_RE.match(value):
        try:
            return int(value, 10 if _INT_RE.match(value) else 0)
        except ValueError as exc:  # beyond Python's integer-string limit
            raise _unsupported(lineno, f"a {len(value)}-digit number") from exc
    if _FLOAT_RE.match(value):
        return float(value)
    if _INF_RE.match(value):
        return float("-inf") if value.startswith("-") else float("inf")
    if _NAN_RE.match(value):
        return float("nan")
    return value


def _strip_comment(value: str) -> str:
    """Drop a trailing ` # comment` from a plain value."""
    if value.startswith("#"):
        return ""
    cut = value.find(" #")
    return (value[:cut] if cut >= 0 else value).rstrip()


def _quoted(value: str, lineno: int) -> str:
    quote = value[0]
    i = 1
    while i < len(value):
        ch = value[i]
        if quote == "'" and ch == "'":
            if value[i + 1: i + 2] == "'":
                i += 2
                continue
            break
        if quote == '"' and ch == "\\":
            i += 2
            continue
        if quote == '"' and ch == '"':
            break
        i += 1
    else:
        raise _unsupported(lineno, "a quoted value continued onto the next line")
    inner, tail = value[1:i], value[i + 1:].strip()
    if tail and not tail.startswith("#"):
        raise _invalid(lineno, f"unexpected text after the closing quote: {tail!r}")
    if quote == "'":
        return inner.replace("''", "'")
    return _unescape(inner, lineno)


def _unescape(inner: str, lineno: int) -> str:
    out: list[str] = []
    i = 0
    while i < len(inner):
        ch = inner[i]
        if ch != "\\":
            out.append(ch)
            i += 1
            continue
        code = inner[i + 1: i + 2]
        if code in _ESCAPES:
            out.append(_ESCAPES[code])
            i += 2
        elif code in _HEX_ESCAPES:
            width = _HEX_ESCAPES[code]
            digits = inner[i + 2: i + 2 + width]
            if len(digits) != width or not all(c in "0123456789abcdefABCDEF" for c in digits):
                raise _invalid(lineno, f"malformed escape '\\{code}{digits}'")
            point = int(digits, 16)
            if point > 0x10FFFF:
                raise _invalid(lineno, f"escape '\\{code}{digits}' is not a Unicode code point")
            out.append(chr(point))
            i += 2 + width
        else:
            raise _invalid(lineno, f"unknown escape '\\{code}'")
    return "".join(out)


def _scalar(raw: str, lineno: int) -> object:
    """One single-line scalar: quoted, or plain and resolved by the core schema."""
    value = raw.strip()
    if value[:1] in {'"', "'"}:
        return _quoted(value, lineno)
    value = _strip_comment(value)
    if not value:
        return None
    first = value[0]
    if first in _INDICATORS:
        what, unsupported = _INDICATORS[first]
        raise (_unsupported if unsupported else _invalid)(lineno, what)
    if value == "?" or value.startswith("? "):
        raise _unsupported(lineno, "an explicit key")
    if value == "-" or value.startswith("- "):
        raise _invalid(lineno, "a list item where a single value was expected")
    if _MAPPING_INDICATOR_RE.search(value):
        # Real loaders reject this ("mapping values are not allowed here"), and a
        # client that cannot parse the block loads the skill with NO fields set.
        raise _invalid(
            lineno,
            f"': ' inside an unquoted value ({value!r}) - quote the value or use a '>' block",
        )
    return _resolve_plain(value, lineno)


# --- block structure -------------------------------------------------------------
# A comment after a block header needs whitespace before its '#': `|# x` is invalid.
_BLOCK_HEADER_RE = re.compile(r"([|>])(?:([1-9])([-+]?)|([-+])([1-9]?))?(?:[ \t]+(?:#.*)?)?\Z")
# ':' followed by whitespace (a space OR a tab) or ending a plain value starts a
# mapping value, which a plain scalar may not contain.
_MAPPING_INDICATOR_RE = re.compile(r":(?:[ \t]|\Z)")


def _indent(raw: str, lineno: int) -> int:
    body = raw.lstrip(" ")
    if body.startswith("\t") and body.strip():
        raise _invalid(lineno, "tabs are not valid indentation")
    return len(raw) - len(body)


def _significant(raw: str) -> bool:
    text = raw.strip()
    return bool(text) and not text.startswith("#")


def _is_item(text: str) -> bool:
    return text == "-" or text.startswith("- ")


def _key_split(text: str) -> tuple[str, str] | None:
    """`key: value` -> (key, value); None when the line is not a mapping entry."""
    for i, ch in enumerate(text):
        if ch == ":" and (i + 1 == len(text) or text[i + 1] == " "):
            return text[:i].rstrip(), text[i + 1:]
    return None


def _fold(lines: list[str]) -> str:
    """YAML line folding for a `>` block's content lines (indentation removed)."""
    out: list[str] = []
    breaks = 0
    prev: str | None = None
    for line in lines:
        if not line:
            breaks += 1
            continue
        if prev is None:
            out.append("\n" * breaks)
        else:
            more = line[:1] in {" ", "\t"} or prev[:1] in {" ", "\t"}
            if breaks == 0:
                out.append("\n" if more else " ")
            else:
                out.append("\n" * (breaks + (1 if more else 0)))
        out.append(line)
        prev, breaks = line, 0
    return "".join(out)


#: Nesting deeper than this is refused rather than recursed into: no skill needs it,
#: and an unbounded depth lets one file exhaust the stack and abort the whole scan.
MAX_DEPTH = 32


class _Parser:
    def __init__(self, lines: list[str], first_lineno: int) -> None:
        self.lines = [line.rstrip("\r") for line in lines]
        self.first = first_lineno

    def no(self, i: int) -> int:
        return self.first + i

    def next_significant(self, i: int) -> int:
        while i < len(self.lines) and not _significant(self.lines[i]):
            i += 1
        return i

    def mapping(self, i: int, indent: int, depth: int = 0) -> tuple[dict[str, object], int]:
        if depth > MAX_DEPTH:
            raise _unsupported(self.no(i), f"nesting deeper than {MAX_DEPTH} levels")
        result: dict[str, object] = {}
        while True:
            i = self.next_significant(i)
            if i >= len(self.lines):
                return result, i
            raw, lineno = self.lines[i], self.no(i)
            ind = _indent(raw, lineno)
            if ind < indent:
                return result, i
            if ind > indent:
                raise _unsupported(
                    lineno, "an indented line continuing the value above (use a '>' block)"
                )
            text = raw.strip()
            if text == "?" or text.startswith("? "):
                raise _unsupported(lineno, "an explicit key")
            if _is_item(text):
                # Valid YAML, but frontmatter is a mapping of fields, not a list.
                raise FrontmatterError(f"line {lineno}: expected a 'key: value' field, found a list item")
            split = _key_split(text)
            if split is None or not split[0]:
                raise _invalid(lineno, "expected 'key: value'")
            key, value = split
            if key[0] in _INDICATORS or key[0] in {'"', "'"}:
                raise _unsupported(lineno, f"the key {key!r}")
            if key in result:
                # YAML requires unique keys; loaders that tolerate them disagree
                # on which value wins, so the field's value is undefined.
                raise _invalid(lineno, f"duplicate key {key!r}")
            result[key], i = self.value(i + 1, indent, value, lineno, depth)

    def value(
        self, i: int, indent: int, raw_value: str, lineno: int, depth: int
    ) -> tuple[object, int]:
        text = raw_value.strip()
        header = _BLOCK_HEADER_RE.match(text) if text[:1] in {"|", ">"} else None
        if header:
            return self.block_scalar(i, indent, header, lineno)
        if _strip_comment(text):
            return _scalar(text, lineno), i
        # An empty value: a nested mapping, a list, or null.
        j = self.next_significant(i)
        if j < len(self.lines):
            child = self.lines[j]
            child_indent = _indent(child, self.no(j))
            if _is_item(child.strip()) and child_indent >= indent:
                return self.sequence(j, child_indent)
            if child_indent > indent:
                return self.mapping(j, child_indent, depth + 1)
        return None, i

    def block_scalar(
        self, i: int, indent: int, header: re.Match[str], lineno: int
    ) -> tuple[str, int]:
        style = header.group(1)
        digit = header.group(2) or header.group(5)
        chomp = header.group(3) or header.group(4) or ""
        start = i
        while i < len(self.lines):
            raw = self.lines[i]
            if raw.strip() and len(raw) - len(raw.lstrip(" ")) <= indent:
                break
            i += 1
        body = self.lines[start:i]
        if digit:
            content = indent + int(digit)
        else:
            firsts = [len(r) - len(r.lstrip(" ")) for r in body if r.strip()]
            content = firsts[0] if firsts else indent + 1
            # A blank line BEFORE the first text may not be more indented than it:
            # the text's own indentation is what fixes the block's.
            for offset, raw in enumerate(body):
                if raw.strip():
                    break
                if len(raw) > content:
                    raise _invalid(
                        self.no(start + offset),
                        "a leading blank line is more indented than the block text",
                    )
        lines: list[str] = []
        for offset, raw in enumerate(body):
            if not raw.strip():
                # Spaces beyond the content indentation ARE content, not an empty line.
                lines.append(raw[content:] if len(raw) > content else "")
                continue
            if len(raw) - len(raw.lstrip(" ")) < content:
                raise _invalid(self.no(start + offset), "block text is less indented than its first line")
            lines.append(raw[content:])
        last = max((k for k, line in enumerate(lines) if line), default=-1)
        kept, trailing = lines[: last + 1], len(lines) - last - 1
        text = _fold(kept) if style == ">" else "\n".join(kept)
        # The frontmatter block excludes the newline before its closing `---`, so
        # block text that runs to the end has no final line break to keep.
        breaks = trailing + (0 if i == len(self.lines) else 1)
        if not kept:
            return ("\n" * trailing if chomp == "+" else ""), i
        if chomp == "-":
            return text, i
        if chomp == "+":
            return text + "\n" * breaks, i
        return text + ("\n" if breaks else ""), i

    def sequence(self, i: int, indent: int) -> tuple[list[object], int]:
        items: list[object] = []
        while True:
            i = self.next_significant(i)
            if i >= len(self.lines):
                return items, i
            raw, lineno = self.lines[i], self.no(i)
            ind = _indent(raw, lineno)
            text = raw.strip()
            if ind < indent or (ind == indent and not _is_item(text)):
                return items, i
            if ind > indent:
                raise _unsupported(lineno, "a list item continued onto the next line")
            value = text[1:].strip()
            if _is_item(value):
                raise _unsupported(lineno, "a nested list")
            if value[:1] in {"|", ">"}:
                raise _unsupported(lineno, "block text inside a list")
            if value[:1] not in {'"', "'"} and _key_split(_strip_comment(value)):
                raise _unsupported(lineno, "a list of mappings")
            items.append(_scalar(value, lineno) if value else None)
            i += 1


def parse_frontmatter(text: str) -> tuple[dict[str, object], str]:
    """Parse the YAML subset skill frontmatter is checked in.

    Block mappings, block lists of scalars, single-line scalars (plain, single- or
    double-quoted) and `|`/`>` block text. Plain scalars resolve by the YAML 1.2
    core schema. Anything else is diagnosed as outside the subset or as invalid,
    never silently misread: the parser stays small enough to audit, and honest
    about the fact that it is not a YAML implementation (docs/frontmatter.md).
    """
    match = FRONTMATTER_RE.match(text)
    if not match:
        raise FrontmatterError("no YAML frontmatter block")
    parser = _Parser(match.group(1).split("\n"), first_lineno=2)
    root, end = parser.mapping(0, 0)
    if end < len(parser.lines):  # pragma: no cover - mapping(…, 0) consumes all
        raise _invalid(parser.no(end), "unexpected content")
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
        except (ValueError, RecursionError) as exc:
            # A parser defect must become THIS skill's finding, never abort the scan
            # of every other skill. Still an error: nothing here was checked.
            return cls(path=path, parse_error=f"skillc could not parse this frontmatter: {exc!r}")
        return cls(path=path, frontmatter=frontmatter, body=body)


def discover(root: Path) -> list[Skill]:
    """Every SKILL.md at or below root, in a stable order."""
    if root.is_file() and root.name == "SKILL.md":
        return [Skill.load(root)]
    return [Skill.load(p) for p in sorted(root.rglob("SKILL.md"))]


class ManifestError(Exception):
    """A plugin manifest that cannot be trusted to say what it declares."""


@dataclass(frozen=True)
class Manifest:
    """A Claude Code plugin manifest's declared skill directories.

    Only the `skills` field is read - a plugin manifest is a third-party
    format skillc does not own, so an unrelated field is neither validated
    nor an error. Entries resolve against the PLUGIN root, not the manifest's
    own directory: the conventional location is `<plugin root>/.claude-plugin/
    plugin.json`, and its `skills` entries (e.g. `./skills/foo`) are relative
    to `<plugin root>`.
    """

    path: Path
    plugin_root: Path
    declared: tuple[Path, ...]  # resolved directories, manifest order, de-duplicated

    @classmethod
    def load(cls, path: Path) -> Manifest:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise ManifestError(f"manifest unreadable: {path}: {exc}") from exc
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise ManifestError(f"manifest is not valid JSON: {path}: {exc}") from exc
        if not isinstance(data, dict):
            raise ManifestError(f"manifest is not a JSON object: {path}")
        skills = data.get("skills")
        if not isinstance(skills, list) or not all(
            isinstance(entry, str) and entry for entry in skills
        ):
            raise ManifestError(
                f"manifest has no 'skills' list of non-empty strings: {path}"
            )
        plugin_root = path.parent.parent if path.parent.name == ".claude-plugin" else path.parent
        plugin_root = plugin_root.resolve()
        declared: list[Path] = []
        seen: set[Path] = set()
        for entry in skills:
            resolved = (plugin_root / entry).resolve()
            if not resolved.is_relative_to(plugin_root):
                # Claude Code itself refuses a component outside the plugin
                # root ("Path escapes plugin directory"). Mirror that: an
                # escaping entry is a malformed manifest, not a dangling one -
                # the whole declaration cannot be trusted, not just this entry.
                raise ManifestError(
                    f"manifest entry escapes the plugin root: {entry!r} in {path}"
                )
            if resolved not in seen:
                seen.add(resolved)
                declared.append(resolved)
        return cls(path=path, plugin_root=plugin_root, declared=tuple(declared))
