#!/usr/bin/env python3
"""One local author consumer of `skillc check --json` (issue #27).

Reads skillc's machine-readable findings - stable `rule`, `severity`, `path`
and `detail` per entry (docs/findings.md) - and prints one line of concise
repair guidance per finding, keyed on the rule's stable id. This is
deliberately the smallest useful consumer: one script, one guidance table, no
parallel findings database and no general integration API. A finding this
table does not name still prints, with a pointer to `skillc rules` instead of
silence - an unmapped rule is a gap in this table, not a reason to say nothing.

Usage: python3 scripts/repair_hint.py <skill dir, tree, or SKILL.md>
Exit: 0 nothing to diagnose, 1 findings printed, 2 could not run skillc.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

# Keyed on the rule's STABLE id (skillc/checks.py's `RULES` / `RECORD_RULES`),
# never on its `detail` text, which is prose and may be reworded without notice.
GUIDANCE: dict[str, str] = {
    "name-spec": "rename the frontmatter `name` (and its directory, if mismatched) to a spec-legal, matching slug",
    "required-fields": "add the missing required frontmatter field, or bring an out-of-range one back in bounds",
    "trigger-shape": "add a 'Use when ...' triggering condition to the description, or set disable-model-invocation if this skill is meant to be user-invoked only",
    "unknown-field": "remove the field, or fold its content into 'description' or 'metadata'",
    "claude-code-field": "remove the field; Claude Code does not document it (see docs/frontmatter.md)",
    "body-budget": "disclose branch-specific material behind a reference file instead of inlining it in the body",
    "ref-depth": "flatten the reference chain so nothing links more than one hop from SKILL.md",
    "frontmatter": "fix the YAML frontmatter block so it parses",
}


def _run_json(skillc: list[str], path: str) -> dict[str, object] | None:
    """The parsed `--json` document, or None with a stderr diagnostic already
    printed - never a traceback. A missing `skillc` executable is exactly the
    "could not run skillc" case this script documents as exit 2, not a crash."""
    try:
        proc = subprocess.run(
            [*skillc, "check", path, "--json"],
            capture_output=True, text=True, check=False,
        )
    except OSError as exc:
        print(f"repair-hint: could not run {skillc[0]!r}: {exc}", file=sys.stderr)
        return None
    try:
        payload = json.loads(proc.stdout)
    except ValueError:
        sys.stderr.write(proc.stdout)
        sys.stderr.write(proc.stderr)
        print(
            f"repair-hint: skillc produced no parseable JSON (exit {proc.returncode})",
            file=sys.stderr,
        )
        return None
    if not isinstance(payload, dict):
        print("repair-hint: skillc's JSON was not an object", file=sys.stderr)
        return None
    return payload


def _report(findings: list[object]) -> int:
    """Print one diagnosis + repair line per finding. Returns 1: there was at
    least one finding to report (the empty case is handled by the caller,
    which prints a different, non-diagnostic message)."""
    for finding in findings:
        assert isinstance(finding, dict)
        rule = finding["rule"]
        hint = GUIDANCE.get(rule, "see `skillc rules` for what this rule checks")
        print(f"diagnosed [{finding['severity']}] {rule} at {finding['path']}: {finding['detail']}")
        print(f"  repair: {hint}")
    return 1


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: repair_hint.py <skill dir, tree, or SKILL.md>", file=sys.stderr)
        return 2
    skillc = os.environ.get("SKILLC", "skillc").split()
    payload = _run_json(skillc, argv[0])
    if payload is None:
        return 2
    if "error" in payload:
        print(f"repair-hint: {payload['error']}", file=sys.stderr)
        return 2
    findings = payload.get("findings")
    if not isinstance(findings, list):
        print("repair-hint: skillc's JSON carried no findings list", file=sys.stderr)
        return 2
    if not findings:
        print("repair-hint: no findings - nothing to diagnose")
        return 0
    return _report(findings)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
