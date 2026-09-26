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
from .spec import DEFAULT_TARGET, TARGETS, Manifest, ManifestError, Skill, discover


def _relative_to(path: Path, root: Path) -> Path:
    """Same fallback `Finding.render` already uses: shown relative to the scanned
    root when possible, absolute when the finding's path is not under it."""
    try:
        return path.relative_to(root)
    except ValueError:
        return path


def _controls_root(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).resolve()
    return Path(__file__).resolve().parent.parent / "controls"


def _unknown_rule_message(
    only: str | None,
    family: tuple[checks.Rule, ...] | tuple[checks.RecordRule | checks.BundleRule, ...],
) -> str | None:
    """The refusal message for an unknown `--rule`, or None when it is known.

    A selector that matches no rule checks nothing, and nothing found reads
    exactly like a clean run. Returning the message (not printing it here) lets
    every caller decide how to render its OWN refusal - stderr prose, a `--json`
    document, or both - rather than fixing that decision in one shared helper.
    """
    try:
        checks.require_known(only, family)
    except ValueError as exc:
        return str(exc)
    return None


def _unknown_rule(
    only: str | None,
    family: tuple[checks.Rule, ...] | tuple[checks.RecordRule | checks.BundleRule, ...],
) -> bool:
    """`check-records` has no `--json` mode; keep its plain stderr-and-refuse shape."""
    message = _unknown_rule_message(only, family)
    if message is not None:
        print(f"skillc: {message}", file=sys.stderr)
    return message is not None


def _target_conflict_message(only: str | None, target: str | None) -> str | None:
    """`--rule X --target Y` where X belongs to another target asks two things at
    once. Returns the refusal message (see `_unknown_rule_message`), or None."""
    rule = checks.RULES_BY_ID.get(only or "")
    if target is None or rule is None or rule.target in (None, target):
        return None
    return f"rule {rule.id!r} checks target {rule.target!r}, not {target!r}"


def _json_refusal(as_json: bool, message: str) -> None:
    """The refusal a consumer sees in `--json` mode: still one JSON document on
    stdout, never prose on stderr it would have to special-case. Human mode is
    unchanged - this is additive, not a replacement for the existing message."""
    if as_json:
        print(json.dumps({"schema": 1, "error": message}))


def cmd_check(args: argparse.Namespace) -> int:
    as_json = bool(getattr(args, "json", False))
    message = _unknown_rule_message(args.rule, checks.RULES)
    if message is not None:
        print(f"skillc: {message}", file=sys.stderr)
        _json_refusal(as_json, message)
        return 2
    target = getattr(args, "target", None)
    message = _target_conflict_message(args.rule, target)
    if message is not None:
        print(f"skillc: {message}", file=sys.stderr)
        _json_refusal(as_json, message)
        return 2
    selected = checks.RULES_BY_ID.get(args.rule or "")
    # A named scoped rule speaks for ITS target, whatever the default is.
    target = target or (selected.target if selected else None) or DEFAULT_TARGET
    root = Path(args.path).resolve()
    if not root.exists():
        message = f"no such path: {root}"
        print(f"skillc: {message}", file=sys.stderr)
        _json_refusal(as_json, message)
        return 2

    manifest_arg = getattr(args, "manifest", None)
    scope: tuple[int, int, int] | None = None  # (declared, checked, undeclared)
    findings: list[Finding] = []
    if manifest_arg:
        manifest_path = Path(manifest_arg).resolve()
        try:
            manifest = Manifest.load(manifest_path)
        except ManifestError as exc:
            print(f"skillc: {exc}", file=sys.stderr)
            return 2
        if not manifest.declared:
            # A manifest that names nothing is as empty a population as a tree
            # with no SKILL.md - see the same contract just below.
            message = f"manifest {manifest_path} declares no skills - nothing was checked"
            if as_json:
                _json_refusal(as_json, message)
            else:
                print(f"skillc: {message}")
            return 2

        skills: list[Skill] = []
        for declared_dir in manifest.declared:
            skill_md = declared_dir / "SKILL.md"
            if skill_md.is_file():
                skills.append(Skill.load(skill_md))
            else:
                # A dangling entry must never read as a clean skill - it is an
                # error even though nothing here was checked, not silence.
                findings.append(
                    Finding(
                        rule="manifest-entry",
                        severity=ERROR,
                        path=skill_md,
                        detail="declared in the manifest but no SKILL.md exists here",
                    )
                )
        skills.sort(key=lambda s: s.path)
        declared_set = set(manifest.declared)
        undeclared = sum(
            1 for s in discover(root) if s.path.parent.resolve() not in declared_set
        )
        scope = (len(manifest.declared), len(skills), undeclared)
    else:
        skills = discover(root)
        if not skills:
            # Silence here would be indistinguishable from a clean run. Say so.
            message = f"no SKILL.md found under {root} - nothing was checked"
            if as_json:
                _json_refusal(as_json, message)
            else:
                print(f"skillc: {message}")
            return 2

    for skill in skills:
        findings.extend(checks.run(skill, only=args.rule, target=target))

    base = root if root.is_dir() else root.parent
    errors = sum(1 for f in findings if f.severity == ERROR)
    warns = len(findings) - errors
    if scope is not None:
        declared, checked, undeclared = scope
        human_summary = (
            f"\nskillc: {declared} declared, {checked} checked, {undeclared} undeclared, "
            f"{errors} error(s), {warns} warning(s)"
        )
    else:
        human_summary = (
            f"\nskillc: {len(skills)} skill(s) checked, "
            f"{errors} error(s), {warns} warning(s)"
        )
    # Field findings are true of ONE client profile. Say which - and say so when no
    # field rule ran, so a green here cannot be read as a field check that passed.
    # An unparseable skill gets only the parser finding, so it was not field-checked.
    parsed = sum(1 for s in skills if s.parse_error is None)
    if selected is not None and selected.target is None:
        field_rules: dict[str, object] | None = None
        human_field_line = f"skillc: field rules NOT checked (--rule {selected.id} only)"
        json_field_reason: str | None = f"rule {selected.id!r} only"
    elif not parsed:
        field_rules = None
        human_field_line = "skillc: field rules NOT checked - no skill's frontmatter parsed"
        json_field_reason = "no skill's frontmatter parsed"
    else:
        field_rules = {"target": target, "checked": parsed, "total": len(skills)}
        human_field_line = (
            f"skillc: field rules checked against target '{target}' "
            f"on {parsed} of {len(skills)} skill(s)"
        )
        json_field_reason = None

    if as_json:
        # ONE document on stdout - the whole reason this branch exists. Mixing it
        # with the human prose below would make a consumer's `json.loads` a
        # coin-flip depending on which findings happened to fire.
        payload: dict[str, object] = {
            "schema": 1,
            "skills_checked": len(skills),
            "errors": errors,
            "warnings": warns,
            "findings": [
                {
                    "rule": f.rule,
                    "severity": f.severity,
                    "path": str(_relative_to(f.path, base)),
                    "detail": f.detail,
                }
                for f in findings
            ],
            "field_rules": field_rules,
        }
        if scope is not None:
            declared, checked, undeclared = scope
            payload["manifest_scope"] = {
                "declared": declared, "checked": checked, "undeclared": undeclared,
            }
        if json_field_reason is not None:
            payload["field_rules_reason"] = json_field_reason
        print(json.dumps(payload, indent=1))
    else:
        for finding in findings:
            print(finding.render(base))
        print(human_summary)
        print(human_field_line)
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
    rule: checks.Rule | checks.RecordRule | checks.BundleRule,
    where: Path,
    target: str = DEFAULT_TARGET,
) -> list[_Subject]:
    # The ONLY family-aware step. Everything after it is subject-agnostic.
    # `target` matters only to the `checks.Rule` branch below - a record or
    # bundle rule has no target to vary against.
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
                 sum(f.rule == rule.id for f in checks.run(s, only=rule.id, target=target)))
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


def _target_dirs(rule_dir: Path) -> tuple[list[Path], str | None]:
    """Optional `targets/<target>/{bad,good}` cases layered on the base pair.

    A rule with no `targets/` directory commits none - this layer is additive,
    for the rule that needs to prove it behaves differently per target
    (`trigger-shape` is the first, #51). Most rules need nothing here.

    A `targets/` directory that exists is not optional in ITS OWN CONTENTS: a
    subdirectory naming an unknown target, or one with neither `bad/` nor
    `good/` under it, is MALFORMED and refused, never silently skipped - a
    typo'd target name, or a case emptied down to nothing, must not quietly
    stop being checked.
    """
    targets_root = rule_dir / "targets"
    if not targets_root.is_dir():
        return [], None
    dirs = sorted(p for p in targets_root.iterdir() if p.is_dir())
    if not dirs:
        # Distinct from "no targets/ at all": someone deleted every case but
        # left the empty directory behind, which must not read as "nothing to
        # check here" the same way absence legitimately does.
        return [], "targets/ exists but declares no target case - remove it or add one"
    for d in dirs:
        if d.name not in TARGETS:
            return [], f"targets/{d.name} names an unknown target (known: {', '.join(TARGETS)})"
        if not (d / "bad").is_dir() and not (d / "good").is_dir():
            return [], f"targets/{d.name} has neither bad/ nor good/ - nothing to check"
    return dirs, None


def _bad_verdict(rule: checks.Rule, bad: list[_Subject], target: str) -> tuple[str, str] | None:
    """The base pair's `_refusal` discipline for `bad`, scoped to one target."""
    unparsed = [s for s in bad if s.parse_error is not None]
    if not rule.parser and unparsed:
        s = unparsed[0]
        return "UNPARSED", (
            f"known-bad input under {target!r} does not parse ({s.shown}); a parse "
            f"failure cannot prove a semantic rule"
        )
    if rule.parser and not unparsed:
        return "UNPARSED", f"parser rule has no unparseable known-bad input under {target!r}"
    silent = [s for s in bad if not s.own]
    if silent:
        return "BLIND", f"silent on {len(silent)} of {len(bad)} known-bad input(s) under {target!r}"
    return None


def _good_verdict(good: list[_Subject], target: str) -> tuple[str, str] | None:
    """The base pair's `_refusal` discipline for `good`, scoped to one target."""
    unparsed = [s for s in good if s.parse_error is not None]
    if unparsed:
        s = unparsed[0]
        return "UNPARSED", f"known-good input under {target!r} does not parse ({s.shown}: {s.parse_error})"
    noisy = [s for s in good if s.own]
    if noisy:
        return "NOISY", f"fired on its known-good input under {target!r}: {noisy[0].shown}"
    return None


def _target_case(rule: checks.Rule, target_dir: Path) -> list[tuple[str, str]]:
    """Verdicts for one `targets/<target>/` case.

    Unlike the base pair, a target case may commit only ONE side - the other
    side's behaviour at this target is already proven elsewhere (the base pair,
    or a sibling case), so an absent side is not scored. A side that IS
    committed is held to the SAME discipline as the base pair: present-but-empty
    is EMPTY, and an unparseable input is UNPARSED rather than being silently
    credited as a passing good (nothing ran) or a correctly-firing bad (a parse
    failure, not the rule, produced the only finding) - `_bad_verdict` and
    `_good_verdict` are that discipline, not a looser one for this optional layer.
    """
    target = target_dir.name
    results: list[tuple[str, str]] = []
    ok_parts: list[str] = []
    good_dir, bad_dir = target_dir / "good", target_dir / "bad"
    if good_dir.is_dir():
        good = _population(rule, good_dir, target=target)
        if not good:
            results.append(("EMPTY", f"no subject in its known-good control under {target!r}"))
        else:
            verdict = _good_verdict(good, target)
            if verdict:
                results.append(verdict)
            else:
                ok_parts.append(f"green on good ({len(good)})")
    if bad_dir.is_dir():
        bad = _population(rule, bad_dir, target=target)
        if not bad:
            results.append(("EMPTY", f"no subject in its known-bad control under {target!r}"))
        else:
            verdict = _bad_verdict(rule, bad, target)
            if verdict:
                results.append(verdict)
            else:
                ok_parts.append(f"red on bad ({sum(s.own for s in bad)})")
    if not results:
        results.append(("ok", ", ".join(ok_parts)))
    return results


def cmd_selftest(args: argparse.Namespace) -> int:
    """Each rule must fire on its committed bad case and stay silent on its good one."""
    root = _controls_root(args.controls)
    if not root.is_dir():
        print(f"skillc: controls directory absent: {root}", file=sys.stderr)
        return 2

    width = max(len(rule.id) for rule in checks.ALL_RULES)
    failures = 0
    unproven = 0
    target_failures = 0

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

        # Target-scoped cases (optional; `_target_dirs` returns none for a rule
        # that has not committed any). A malformed `targets/` entry - an unknown
        # target name, or a case with neither side - is its own refusal and does
        # not stop the base pair above from having already been reported.
        if isinstance(rule, checks.Rule):
            target_dirs, malformed = _target_dirs(root / rule.id)
            if malformed:
                print(f"MALFORMED {rule.id:{width}}  {malformed}")
                target_failures += 1
            for target_dir in target_dirs:
                label = f"{rule.id}[{target_dir.name}]"
                for verdict, detail in _target_case(rule, target_dir):
                    print(f"{verdict:8} {label:{width}}  {detail}")
                    if verdict != "ok":
                        target_failures += 1

    total = len(checks.ALL_RULES)
    print(f"\nskillc selftest: {total - failures - unproven}/{total} rule(s) discriminate", end="")
    if unproven:
        print(f", {unproven} unproven", end="")
    if target_failures:
        print(f", {target_failures} target-case failing", end="")
    print(f", {failures} failing" if failures else "")
    return 1 if (failures or unproven or target_failures) else 0


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
    p_check.add_argument(
        "--manifest",
        help="scope to a plugin manifest's declared skills (e.g. .claude-plugin/plugin.json)",
    )
    p_check.add_argument(
        "--json",
        action="store_true",
        help="one JSON document on stdout (stable rule/severity/path/detail per finding) instead of the human report",
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
