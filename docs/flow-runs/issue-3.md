# Flow run record - issue #3

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
below. It is not a description of the shipped system, it is not a second
statement of the issue contract or of a Tier 3 spec, and it does not graduate.

- Issue:             #3
- Base SHA:          b8809e0a3bace06fd9c9db524897a21dc02f510f
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          repository owner (cooneycw), interactive "approved" in the /flow:auto session; the two open decisions took the recommended options (default target portable; PyYAML as a dev-only test oracle)
- Recorded at:       2026-09-26T11:09:03Z

## Section B evidence
- commits since filing touching skillc/ controls/ tests/: b8809e0 (#2), 36bc172 (#19),
  c352bbe (#18), 857781f (record rules) - none touch parse_frontmatter, Skill.get,
  _required_fields or HARNESS_FIELDS
- merged PRs since filing: #30, #29, #25, #24, #21, #17 - none address this
- duplicate/superseding issues: none (#27 and #7 depend on #3; #1 is the roadmap)
- reproduced on b8809e0: folded description -> frontmatter error; mapping-valued
  name/description -> 0 findings exit 0; `user-invocable: false` -> "not a field any
  harness loads"; `description: Use when: x` -> 0 findings exit 0
- primary sources checked 2026-09-25: agentskills.io/specification (6 fields),
  code.claude.com/docs/en/skills (14 Claude Code extension fields)

## Section C - the approved plan
1. `skillc/spec.py` - documented YAML subset: block scalars, scalar block sequences, empty childless value is null, YAML 1.2 core typing of plain scalars, inline comments, named diagnoses for unsupported/invalid syntax; PORTABLE_FIELDS + TARGET_PROFILES["claude-code"] with source URL and verification date replace HARNESS_FIELDS
2. `skillc/checks.py` - required-fields rejects non-string/empty name and description naming the type; unknown-field rescoped to portable with an extension-aware message; new claude-code-field rule; Rule.target and run(..., target=)
3. `skillc/cli.py` - check --target {portable,claude-code} (default portable); rules shows target
4. `controls/required-fields/` - bad: mapping name, mapping description, numeric name, null description; good: folded description
5. `controls/frontmatter/` - bad: flow sequence, colon in plain scalar; good: literal block description
6. `controls/unknown-field/` - bad: Claude Code extension field
7. `controls/claude-code-field/` - new control pair
8. `tests/test_frontmatter.py` - subset syntax, typing, PyYAML differential, required types, extension field per target, stdlib-only import walk
9. `pyproject.toml` - pyyaml and types-PyYAML dev-only
10. `uv.lock` - lock the dev dependencies
11. `docs/frontmatter.md` - supported subset, diagnoses, target profiles with source and date
12. `README.md` - rules, selftest sample, --target, rule count, link
13. `AGENTS.md` - layout line
14. `docs/flow-runs/issue-3.md` - this record

Scope: ~20 files (control fixtures are small), ~600 lines, about half tests/fixtures.
Risks: default portable target adds unknown-field warnings for Claude Code extensions
on CPP skills; diagnosing ": " in plain scalars can turn existing descriptions into
frontmatter errors (correct - Claude Code drops their fields); the claude-code profile
is a dated snapshot of documentation.
