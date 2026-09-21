"""skillc - skills are the new code. Code doesn't ship uncompiled.

Two commands carry the whole idea:

    skillc check <path>   refuse to build skills the spec rejects
    skillc selftest       prove every rule can still report the other verdict

The second one is the point. A green from a blind check and a green from a
working one look identical, and the difference is only ever found later, by
someone relying on it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import checks, records
from .checks import ERROR, Finding
from .spec import discover


def _controls_root(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).resolve()
    return Path(__file__).resolve().parent.parent / "controls"


def cmd_check(args: argparse.Namespace) -> int:
    root = Path(args.path).resolve()
    if not root.exists():
        print(f"skillc: no such path: {root}", file=sys.stderr)
        return 2

    skills = discover(root)
    if not skills:
        # Silence here would be indistinguishable from a clean run. Say so.
        print(f"skillc: no SKILL.md found under {root} - nothing was checked")
        return 2

    findings: list[Finding] = []
    for skill in skills:
        findings.extend(checks.run(skill, only=args.rule))

    base = root if root.is_dir() else root.parent
    for finding in findings:
        print(finding.render(base))

    errors = sum(1 for f in findings if f.severity == ERROR)
    warns = len(findings) - errors
    print(
        f"\nskillc: {len(skills)} skill(s) checked, "
        f"{errors} error(s), {warns} warning(s)"
    )
    if args.strict and warns:
        return 1
    return 1 if errors else 0


def cmd_check_records(args: argparse.Namespace) -> int:
    """Refuse evaluation records the contract rejects.

    What a green here means, and it is deliberately narrower than it looks:
    the records are WELL FORMED AND INTERNALLY CONSISTENT. It does not mean the
    result is true. Every run says so, including the passing ones, because a line
    that only appears on failure is a line nobody reads before quoting the green.
    """
    root = Path(args.path).resolve()
    if not root.exists():
        print(f"skillc: no such path: {root}", file=sys.stderr)
        return 2

    found = records.discover(root)
    if not found:
        # An empty population must not render as a clean one (AGENTS.md).
        print(f"skillc: no record found under {root} - nothing was checked")
        return 2

    findings: list[Finding] = []
    for record in found:
        findings.extend(checks.run_record(record, only=args.rule))

    base = root if root.is_dir() else root.parent
    for finding in findings:
        print(finding.render(base))

    errors = sum(1 for f in findings if f.severity == ERROR)
    print(f"\nskillc: {len(found)} record(s) checked, {errors} error(s)")
    print(f"skillc: examined {records.WHAT_WAS_EXAMINED}")
    return 1 if errors else 0


def cmd_selftest(args: argparse.Namespace) -> int:
    """Each rule must fire on its committed bad case and stay silent on its good one."""
    root = _controls_root(args.controls)
    if not root.is_dir():
        print(f"skillc: controls directory absent: {root}", file=sys.stderr)
        return 2

    width = max(len(rule.id) for rule in checks.ALL_RULES)
    failures = 0
    unproven = 0

    # ONE loop over ONE registry. The coverage check below is subject-agnostic - it
    # asks whether a control directory exists, keyed on rule.id - and so are the
    # counters and the exit code. Only the subject-LOADING step below knows which
    # family a rule belongs to. Giving record rules their own loop would give the
    # repository's central guarantee two places to be enforced, and one of them
    # would eventually stop being.
    for rule in checks.ALL_RULES:
        bad_dir, good_dir = root / rule.id / "bad", root / rule.id / "good"
        if not bad_dir.is_dir() or not good_dir.is_dir():
            print(f"UNPROVEN {rule.id:{width}}  no committed control - this rule is not evidence")
            unproven += 1
            continue

        if isinstance(rule, checks.RecordRule):
            bad = [f for r in records.discover(bad_dir) for f in checks.run_record(r, only=rule.id)]
            good = [f for r in records.discover(good_dir) for f in checks.run_record(r, only=rule.id)]
        else:
            bad = [f for s in discover(bad_dir) for f in checks.run(s, only=rule.id)]
            good = [f for s in discover(good_dir) for f in checks.run(s, only=rule.id)]

        if not bad:
            print(f"BLIND    {rule.id:{width}}  silent on its known-bad input")
            failures += 1
        elif good:
            print(f"NOISY    {rule.id:{width}}  fired on its known-good input: {good[0].detail}")
            failures += 1
        else:
            print(f"ok       {rule.id:{width}}  red on bad ({len(bad)}), green on good")

    total = len(checks.ALL_RULES)
    print(f"\nskillc selftest: {total - failures - unproven}/{total} rule(s) discriminate", end="")
    if unproven:
        print(f", {unproven} unproven", end="")
    print(f", {failures} failing" if failures else "")
    return 1 if (failures or unproven) else 0


def cmd_rules(args: argparse.Namespace) -> int:
    width = max(len(rule.id) for rule in checks.ALL_RULES)
    for rule in checks.ALL_RULES:
        print(f"{rule.severity:5}  {rule.id:{width}}  {rule.summary}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="skillc",
        description="Skills are the new code. Code doesn't ship uncompiled.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check", help="refuse to build skills the spec rejects")
    p_check.add_argument("path", nargs="?", default=".", help="skill dir, tree, or SKILL.md")
    p_check.add_argument("--rule", help="run only this rule")
    p_check.add_argument("--strict", action="store_true", help="exit non-zero on warnings too")
    p_check.set_defaults(func=cmd_check)

    p_self = sub.add_parser("selftest", help="prove every rule can report the other verdict")
    p_self.add_argument("--controls", help="controls directory (default: the shipped one)")
    p_self.set_defaults(func=cmd_selftest)

    p_records = sub.add_parser(
        "check-records", help="refuse evaluation records the contract rejects"
    )
    p_records.add_argument("path", help="file or directory of records")
    p_records.add_argument("--rule", help="run a single rule")
    p_records.set_defaults(func=cmd_check_records)

    p_rules = sub.add_parser("rules", help="list the rules")
    p_rules.set_defaults(func=cmd_rules)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
