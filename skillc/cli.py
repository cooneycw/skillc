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
import json
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import checks, materialize, records
from .checks import ERROR, Finding
from .spec import DEFAULT_TARGET, TARGETS, discover


def _controls_root(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).resolve()
    return Path(__file__).resolve().parent.parent / "controls"


def _unknown_rule(
    only: str | None,
    family: tuple[checks.Rule, ...] | tuple[checks.RecordRule | checks.BundleRule, ...],
) -> bool:
    """Refuse an unknown --rule BEFORE scanning.

    A selector that matches no rule checks nothing, and nothing found reads
    exactly like a clean run.
    """
    try:
        checks.require_known(only, family)
    except ValueError as exc:
        print(f"skillc: {exc}", file=sys.stderr)
        return True
    return False


def _target_conflict(only: str | None, target: str | None) -> bool:
    """`--rule X --target Y` where X belongs to another target asks two things at once."""
    rule = checks.RULES_BY_ID.get(only or "")
    if target is None or rule is None or rule.target in (None, target):
        return False
    print(
        f"skillc: rule {rule.id!r} checks target {rule.target!r}, not {target!r}",
        file=sys.stderr,
    )
    return True


def cmd_check(args: argparse.Namespace) -> int:
    if _unknown_rule(args.rule, checks.RULES):
        return 2
    target = getattr(args, "target", None)
    if _target_conflict(args.rule, target):
        return 2
    selected = checks.RULES_BY_ID.get(args.rule or "")
    # A named scoped rule speaks for ITS target, whatever the default is.
    target = target or (selected.target if selected else None) or DEFAULT_TARGET
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
        findings.extend(checks.run(skill, only=args.rule, target=target))

    base = root if root.is_dir() else root.parent
    for finding in findings:
        print(finding.render(base))

    errors = sum(1 for f in findings if f.severity == ERROR)
    warns = len(findings) - errors
    print(
        f"\nskillc: {len(skills)} skill(s) checked, "
        f"{errors} error(s), {warns} warning(s)"
    )
    # Field findings are true of ONE client profile. Say which - and say so when no
    # field rule ran, so a green here cannot be read as a field check that passed.
    # An unparseable skill gets only the parser finding, so it was not field-checked.
    parsed = sum(1 for s in skills if s.parse_error is None)
    if selected is not None and selected.target is None:
        print(f"skillc: field rules NOT checked (--rule {selected.id} only)")
    elif not parsed:
        print("skillc: field rules NOT checked - no skill's frontmatter parsed")
    else:
        print(
            f"skillc: field rules checked against target '{target}' "
            f"on {parsed} of {len(skills)} skill(s)"
        )
    if args.strict and warns:
        return 1
    return 1 if errors else 0


def cmd_check_records(args: argparse.Namespace) -> int:
    """Refuse evaluation records the contract rejects.

    What a green here means, and it is deliberately narrower than it looks:
    the records are WELL FORMED AND INTERNALLY CONSISTENT, and each bundle is
    consistent with its own ledger. It does not mean the result is true. Every run
    says so, including the passing ones, because a line that only appears on
    failure is a line nobody reads before quoting the green. It also says how many
    records were bound to no ledger, so "checked alone" never reads as "bound".
    """
    if _unknown_rule(args.rule, checks.evidence_rules()):
        return 2
    root = Path(args.path).resolve()
    if not root.exists():
        print(f"skillc: no such path: {root}", file=sys.stderr)
        return 2

    found = records.discover(root)
    if not found:
        # An empty population must not render as a clean one (AGENTS.md).
        print(f"skillc: no record found under {root} - nothing was checked")
        return 2

    bundles = records.discover_bundles(root)
    if not bundles and any(r.id == args.rule for r in checks.BUNDLE_RULES):
        # A bundle rule with no bundle to read checks nothing; saying 0 errors
        # would read exactly like a bundle that bound correctly.
        print(f"skillc: no bundle (a directory holding a trial ledger) under {root} - "
              f"{args.rule} checked nothing")
        return 2
    findings: list[Finding] = []
    for record in found:
        findings.extend(checks.run_record(record, only=args.rule))
    for bundle in bundles:
        findings.extend(checks.run_bundle(bundle, only=args.rule))

    base = root if root.is_dir() else root.parent
    for finding in findings:
        print(finding.render(base))

    errors = sum(1 for f in findings if f.severity == ERROR)
    bound = {r.path for b in bundles for r in b.records}
    loose = sum(1 for r in found if r.path not in bound)
    print(
        f"\nskillc: {len(found)} record(s) in {len(bundles)} bundle(s) checked, "
        f"{errors} error(s)"
    )
    if loose:
        print(
            f"skillc: {loose} record(s) belong to no bundle and were checked alone - "
            f"NOT against any ledger"
        )
    print(f"skillc: examined {records.WHAT_WAS_EXAMINED}")
    return 1 if errors else 0


@dataclass(frozen=True)
class _Subject:
    """One control input, and what the rule under test said about it."""

    path: Path
    parse_error: str | None
    own: int  # findings ATTRIBUTED to the rule under test; a neighbour's never count

    @property
    def shown(self) -> str:
        return f"{self.path.parent.name}/{self.path.name}"


def _population(
    rule: checks.Rule | checks.RecordRule | checks.BundleRule, where: Path
) -> list[_Subject]:
    # The ONLY family-aware step. Everything after it is subject-agnostic.
    if isinstance(rule, checks.BundleRule):
        # Every CASE DIRECTORY is a subject, whether or not it loads as a bundle.
        # Enumerating only what discovery found would let a case whose ledger
        # became unreadable drop out of the population and leave a green behind.
        subjects = []
        for case in sorted(p for p in where.iterdir() if p.is_dir()):
            bundle = records.bundle_at(case)
            if bundle is None:
                subjects.append(_Subject(case, "not a bundle: no readable trial ledger", 0))
                continue
            own = sum(f.rule == rule.id for f in checks.run_bundle(bundle, only=rule.id))
            subjects.append(_Subject(case, bundle.parse_error, own))
        return subjects
    if isinstance(rule, checks.RecordRule):
        return [
            _Subject(r.path, r.parse_error,
                     sum(f.rule == rule.id for f in checks.run_record(r, only=rule.id)))
            for r in records.discover(where)
        ]
    return [
        _Subject(s.path, s.parse_error,
                 sum(f.rule == rule.id for f in checks.run(s, only=rule.id)))
        for s in discover(where)
    ]


def _refusal(
    rule: checks.Rule | checks.RecordRule | checks.BundleRule, bad: list[_Subject], good: list[_Subject]
) -> tuple[str, str] | None:
    """Why this rule's control does not prove it, or None when it does.

    Each refusal closes a way a control could certify a rule it never exercised:
    an empty population proves nothing on that side; a semantic rule shown red on
    input that does not parse was shown red by the PARSER; and a finding counts
    only when the rule under test is the one that raised it.
    """
    for side, population in (("bad", bad), ("good", good)):
        if not population:
            return "EMPTY", f"no subject in its known-{side} control - that side proves nothing"

    unparsed_good = [s for s in good if s.parse_error is not None]
    if unparsed_good:
        s = unparsed_good[0]
        return "UNPARSED", f"known-good input does not parse ({s.shown}: {s.parse_error})"
    unparsed_bad = [s for s in bad if s.parse_error is not None]
    if not rule.parser and unparsed_bad:
        s = unparsed_bad[0]
        return "UNPARSED", (
            f"known-bad input does not parse ({s.shown}); a parse failure cannot "
            f"prove a semantic rule"
        )
    if rule.parser and not unparsed_bad:
        return "UNPARSED", "parser rule has no unparseable known-bad input"

    silent = [s for s in bad if not s.own]
    if silent:
        return "BLIND", f"silent on {len(silent)} of {len(bad)} known-bad input(s)"
    noisy = [s for s in good if s.own]
    if noisy:
        return "NOISY", f"fired on its known-good input: {noisy[0].shown}"
    return None


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
    # counters, the refusals and the exit code. Only `_population` knows which
    # family a rule belongs to. Giving record rules their own loop would give the
    # repository's central guarantee two places to be enforced, and one of them
    # would eventually stop being.
    for rule in checks.ALL_RULES:
        bad_dir, good_dir = root / rule.id / "bad", root / rule.id / "good"
        if not bad_dir.is_dir() or not good_dir.is_dir():
            print(f"UNPROVEN {rule.id:{width}}  no committed control - this rule is not evidence")
            unproven += 1
            continue

        bad, good = _population(rule, bad_dir), _population(rule, good_dir)
        refusal = _refusal(rule, bad, good)
        if refusal:
            verdict, detail = refusal
            print(f"{verdict:8} {rule.id:{width}}  {detail}")
            failures += 1
        else:
            print(
                f"ok       {rule.id:{width}}  red on bad ({sum(s.own for s in bad)}), "
                f"green on good ({len(good)})"
            )

    total = len(checks.ALL_RULES)
    print(f"\nskillc selftest: {total - failures - unproven}/{total} rule(s) discriminate", end="")
    if unproven:
        print(f", {unproven} unproven", end="")
    print(f", {failures} failing" if failures else "")
    return 1 if (failures or unproven) else 0


def cmd_materialize(args: argparse.Namespace) -> int:
    """Install a declared skill surface into disposable homes and prove what the client sees.

    Exit 0 only when every readiness fact is SATISFIED. A receipt is still written
    when readiness is VIOLATED or UNKNOWN - it is useful evidence - but the exit
    code never lets an unready install read as a ready one.
    """
    out = Path(args.out).resolve()
    # The receipt sits alone under records/, so `skillc check-records <out>/records`
    # reads exactly the evaluation records and never mistakes the report for one.
    if (out / "records").exists() or (out / "report.json").exists():
        print(f"skillc: {out} already holds evidence; refusing to overwrite it", file=sys.stderr)
        return 2
    try:
        subject = materialize.Subject.load(Path(args.subject))
    except materialize.Refused as exc:
        print(f"skillc: {exc}", file=sys.stderr)
        return 2
    client = materialize.find_client(args.client)
    try:
        # Evidence written into the source or a host client home would change it
        # AFTER the immutability facts were taken, and nothing would say so.
        origin = Path(args.repo or args.snapshot).resolve()
        materialize.refuse_protected(out, materialize.forbidden_roots(origin), "write evidence")
        result = materialize.materialize(
            subject,
            attempt_id=args.attempt_id,
            trial_id=args.trial_id,
            base=Path(args.base) if args.base else Path(tempfile.gettempdir()),
            repo=Path(args.repo) if args.repo else None,
            snapshot=Path(args.snapshot) if args.snapshot else None,
            client=client,
            workspace_fixture=Path(args.workspace) if args.workspace else None,
            keep=args.keep,
            timeout=args.timeout,
        )
    except materialize.Refused as exc:
        # Refused before any disposable root existed: there is nothing to report on.
        print(f"skillc: {exc}", file=sys.stderr)
        return 2
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(result.report, indent=1) + "\n", encoding="utf-8")
    if result.receipt is not None:
        (out / "records").mkdir()
        (out / "records" / "receipt.json").write_text(
            json.dumps(result.receipt, indent=1) + "\n", encoding="utf-8"
        )

    report = result.report
    if "refused" in report:
        print(f"skillc: REFUSED - {report['refused']}")
        print("skillc: no receipt written; nothing was installed that could be called ready")
    observations = report["observations"]
    assert isinstance(observations, dict)
    for fact in ("installed", "available", "invoked", "task_outcome"):
        print(f"{fact:13} {observations[fact]}")
    readiness = report.get("readiness", {})
    assert isinstance(readiness, dict)
    reasons = readiness.get("reasons", {})
    for fact in materialize.READINESS_FACTS:
        if fact in readiness:
            print(f"{readiness[fact]:9} {fact:17} {reasons.get(fact, '')}")
    cleanup = report.get("cleanup", {})
    assert isinstance(cleanup, dict)
    print(f"cleanup       {cleanup.get('status')}")
    print(f"\nskillc: {'READY' if result.ready else 'NOT READY'} - evidence in {out}")
    return 0 if result.ready else 1


def cmd_rules(args: argparse.Namespace) -> int:
    width = max(len(rule.id) for rule in checks.ALL_RULES)
    for rule in checks.ALL_RULES:
        scope = getattr(rule, "target", None)
        suffix = f"  [target: {scope}]" if scope else ""
        print(f"{rule.severity:5}  {rule.id:{width}}  {rule.summary}{suffix}")
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
    p_check.add_argument(
        "--target",
        choices=TARGETS,
        help=f"client profile the field rules check against (default: {DEFAULT_TARGET})",
    )
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

    p_mat = sub.add_parser(
        "materialize",
        help="install a declared skill surface into disposable homes and prove it",
    )
    p_mat.add_argument("subject", help="subject declaration (subject.json)")
    source = p_mat.add_mutually_exclusive_group(required=True)
    source.add_argument("--repo", help="git checkout to read the pinned revision from")
    source.add_argument("--snapshot", help="local directory holding the skills root")
    p_mat.add_argument("--out", required=True, help="directory for receipt.json and report.json")
    p_mat.add_argument("--attempt-id", required=True, help="attempt this receipt belongs to")
    p_mat.add_argument("--trial-id", required=True, help="trial this receipt belongs to")
    p_mat.add_argument("--client", help="client executable (default: codex on PATH)")
    p_mat.add_argument("--workspace", help="fixture copied identically into every arm")
    p_mat.add_argument("--base", help="where the disposable root is created (default: TMPDIR)")
    p_mat.add_argument("--keep", action="store_true", help="keep the disposable root")
    p_mat.add_argument("--timeout", type=float, default=120, help="per client call, seconds")
    p_mat.set_defaults(func=cmd_materialize)

    p_rules = sub.add_parser("rules", help="list the rules")
    p_rules.set_defaults(func=cmd_rules)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
