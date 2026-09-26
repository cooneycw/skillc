# Frontmatter: what skillc reads, and against which client

`skillc` reads `SKILL.md` frontmatter with its own small parser, because the
runtime is stdlib-only. That parser reads a **documented subset of YAML. It is
not a YAML implementation**, and `skillc` does not claim full compatibility with
any client's loader. This page is the contract; `skillc/spec.py` implements it
and `tests/test_frontmatter.py` checks it against a real YAML loader.

## The supported subset

| Construct | Example | Read as |
|---|---|---|
| Block mapping, nested by spaces | `metadata:` then `  version: "1.0"` | a mapping |
| Plain single-line value | `name: pdf-tools` | a string, or a typed value (below) |
| Single-quoted value (`''` escapes a quote) | `a: 'it''s'` | a string |
| Double-quoted value, YAML escapes | `a: "tab\there é"` | a string |
| Literal block, `|` `|-` `|+`, optional indent digit | `description: |` | a string with its line breaks |
| Folded block, `>` `>-` `>+`, optional indent digit | `description: >` | a string, lines folded to spaces |
| Block list of single-line values | `paths:` then `  - "*.py"` | a list |
| Empty value with nothing nested under it | `description:` | null |
| Comments, whole-line or after a plain value | `a: 1 # note` | ignored |

Plain values resolve by the **YAML 1.2 core schema**: `true`/`false`, `null`/`~`,
integers (`404`, `0x1F`, `0o17`) and floats become those types, not strings,
exactly as a YAML loader would hand them over. So `name: 404` is a number and is
refused by `required-fields`. Quote a value to keep it a string.

Every input in the subset is checked against PyYAML (a test-only dependency) on
the block a `SKILL.md` actually yields. PyYAML resolves by YAML 1.1, so words such
as `yes`/`on` are booleans there and strings here; the test corpus avoids them.

## What is diagnosed

Anything outside the subset is a `frontmatter` **error**, with one of two messages:

- **`invalid YAML`** - a real YAML loader also rejects it. The common one is
  `': '` inside an unquoted value (`description: Use when: x`). Claude Code loads a
  skill whose frontmatter does not parse "with no fields set", so this used to be a
  silent false green. Also: unknown escapes, text after a closing quote, reserved
  indicators (`@`, `` ` ``), tab indentation, duplicate keys.
- **`outside the YAML subset skillc reads`** - the input may be valid YAML, but
  `skillc` does not read it: flow collections (`[a, b]`, `{a: 1}`), anchors,
  aliases, tags, explicit keys, a plain or quoted value continued onto the next
  line, nested lists, lists of mappings, block text inside a list, nesting
  deeper than 32 levels, and a number too long for Python to convert.

A parser defect nobody has found yet is caught too: it becomes that skill's
`frontmatter` error ("skillc could not parse this frontmatter") and the scan goes
on to the other skills.

Both are errors on purpose. A skill `skillc` cannot read has had none of its other
rules applied, and an unchecked skill must not read as a clean one. Rewrite the
construct into the subset (a `>` block for a long description, a block list for
`[a, b]`) and every rule runs.

A top-level list, or a line that is not `key: value`, is refused as not being a
mapping of fields.

## Required field types

`name` and `description` must be non-empty **strings**. `required-fields` owns
that type: a mapping, list, boolean, number or null value is refused there with
the type it found. `name-spec` and `trigger-shape` read only string values, so
before this rule owned the type, a mapping-valued `name` passed every rule.

## Field rules are scoped to a target

Which fields a client loads is a property of **that client**. `skillc check
--target` names the client the field rules speak for. Every run prints the target
and how many skills the field rules actually examined (an unparseable skill is not
field-checked), or says plainly that no field rule ran.

| Target | Rule | Fields known | Source |
|---|---|---|---|
| `portable` (default) | `unknown-field` | the Agent Skills specification | [agentskills.io/specification](https://agentskills.io/specification) |
| `claude-code` | `claude-code-field` | the specification plus Claude Code's extensions | [Claude Code frontmatter reference](https://code.claude.com/docs/en/skills#frontmatter-reference), read 2026-09-25 |

**Specification fields:** `name`, `description`, `license`, `compatibility`,
`metadata`, `allowed-tools`.

**Claude Code extensions, as documented on 2026-09-25:** `when_to_use`,
`argument-hint`, `arguments`, `disable-model-invocation`, `user-invocable`,
`disallowed-tools`, `model`, `effort`, `context`, `agent`, `background`, `hooks`,
`paths`, `shell`.

Under `portable`, a Claude Code extension is reported as non-portable (other
clients may ignore it), and any other extra field as defined nowhere skillc
knows. Under `claude-code`, only fields outside both lists are reported.

The Claude Code profile is a dated reading of documentation, not a measurement of
what the client loads. When Claude Code changes, re-read the source, update
`CLAUDE_CODE` in `skillc/spec.py` with the new date, and update this list;
`tests/test_frontmatter.py` pins the two together.

`--rule` names one rule and runs it whatever the target; `--rule` and `--target`
that disagree are refused.

## trigger-shape and user-invoked skills

`trigger-shape` warns when a description states a capability but no triggering
condition, on the premise that "the model reads this to decide whether to fire
the skill". A skill with `disable-model-invocation: true` breaks that premise
under `claude-code`: the model cannot fire it at all, so it never reads the
description to decide anything. `--target claude-code` stays silent on such a
skill's description shape (issue #51); a model-invoked skill under the same
target is unaffected.

`--target portable` still fires on the identical skill. The Agent Skills
specification has no invocation control, so `disable-model-invocation` is a
Claude Code extension a conforming client is free to ignore - such a client may
still read the description to auto-select the skill, and silencing the warning
there would hide that real concern for it. This is a decision, not a default:
skillc does not know every client's invocation rules, so it warns for the ones
it cannot rule out rather than assuming they all behave like Claude Code.

## Not covered

Types of optional fields (`metadata` as a string-to-string map, `compatibility`
as a string), and client-specific limits such as Claude Code's combined
`description` + `when_to_use` listing cap, are not checked yet.
