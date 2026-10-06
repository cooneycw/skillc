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
import dataclasses
import json
import os
import re
import signal
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import (
    __version__,
    checks,
    configuration_compare,
    exposure,
    leak,
    materialize,
    profile,
    records,
)

# `demo` is NOT imported here at module load (EF-11, #80's own no-Docker-
# required proof: `skillc.cli` must not import `skillc.docker_backend` at
# load time, even transitively) - `demo.py` genuinely needs Docker, by
# definition, but `skillc check`/`selftest`/every other static command does
# not, and must keep working with no `docker` binary anywhere on PATH.
# `cmd_demo` below imports it lazily, inside the one function that actually
# needs it.
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
        skills.sort(key=lambda s: s.path)
        # Issue #131 item 3: routed through `checks.manifest_entry` - the
        # SAME function `checks.ManifestRule`/`selftest` exercise via its
        # committed control (`controls/manifest-entry/{bad,good}`) - rather
        # than a second, ad-hoc "declared but no SKILL.md" check built here.
        # A dangling entry must never read as a clean skill - it is an error
        # even though nothing here was checked, not silence. The dangling
        # path itself is named in the detail text (`checks.manifest_entry`'s
        # own wording); `manifest_path` is the Finding's own path, matching
        # `checks.run_manifest`'s identical choice for the same rule.
        findings.extend(
            Finding("manifest-entry", ERROR, manifest_path, detail)
            for detail in checks.manifest_entry(manifest)
        )
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

    # Issue #131 item 2: a record rule's own `record.kind != ...` guard is
    # invisible from here, so a `--rule` selection with nothing of its kind
    # to read used to run, find every guard silently declining, and report
    # "0 error(s)" - indistinguishable from a population that WAS examined
    # and found clean. Declared per-rule `kinds` makes the applicable
    # population visible and refuses on zero, exactly as the bundle-rule
    # case above already does for its own family.
    selected_record_rule = checks.record_rule_by_id(args.rule) if args.rule else None
    applicable = None
    if selected_record_rule is not None:
        applicable = checks.applicable_population(selected_record_rule, found)
        if applicable == 0:
            print(f"skillc: no {selected_record_rule.id}-applicable record "
                  f"(kind in {list(selected_record_rule.kinds)}) under {root} - "
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
    if applicable is not None:
        print(f"skillc: {applicable} of {len(found)} record(s) were {args.rule}-applicable")
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
    rule: checks.Rule | checks.RecordRule | checks.BundleRule | checks.ManifestRule,
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
    if isinstance(rule, checks.ManifestRule):
        # Same shape as BundleRule: every CASE DIRECTORY is a subject (issue
        # #131 item 3), whether or not its manifest loads.
        subjects = []
        for case in sorted(p for p in where.iterdir() if p.is_dir()):
            case_findings, load_error = checks.run_manifest(case, only=rule.id)
            own = sum(1 for f in case_findings if f.rule == rule.id)
            subjects.append(_Subject(case, load_error, own))
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
    rule: checks.Rule | checks.RecordRule | checks.BundleRule | checks.ManifestRule,
    bad: list[_Subject], good: list[_Subject],
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


def cmd_exposure(args: argparse.Namespace) -> int:
    """Measure what a client's session-start input actually contains, per
    declared marker and skill. Exit 0 only when every declared item was
    actually observed (EXPOSED, TRUNCATED or a named HIDDEN cause) - a
    single UNMEASURED item, or a refused run, is never zero findings."""
    out = Path(args.out).resolve()
    if (out / "report.json").exists():
        print(f"skillc: {out} already holds evidence; refusing to overwrite it", file=sys.stderr)
        return 2
    try:
        surface = exposure.ExposureSurface.load(Path(args.surface))
    except exposure.Refused as exc:
        print(f"skillc: {exc}", file=sys.stderr)
        return 2
    client_bin = materialize.find_client(args.client_bin) if args.client == "codex" else None
    try:
        origin = Path(args.repo or args.snapshot).resolve()
        materialize.refuse_protected(out, materialize.forbidden_roots(origin), "write evidence")
        report = exposure.check_exposure(
            surface,
            base=Path(args.base) if args.base else Path(tempfile.gettempdir()),
            repo=Path(args.repo) if args.repo else None,
            snapshot=Path(args.snapshot) if args.snapshot else None,
            client=client_bin,
            client_name=args.client,
            timeout=args.timeout,
            keep=args.keep,
        )
    except exposure.Refused as exc:
        print(f"skillc: {exc}", file=sys.stderr)
        return 2

    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report.to_dict(), indent=1) + "\n", encoding="utf-8")

    if report.status == "refused":
        print(f"skillc: REFUSED - {report.reason}", file=sys.stderr)
        return 2
    for item in report.markers:
        print(f"{item['verdict']:10} marker  {item['layer']:30} {item.get('note', '')}")
    for item in report.skills:
        cause = f" ({item['cause']})" if item.get("cause") else ""
        print(f"{item['verdict']:10} skill   {item['skill']}{cause}")
    unmeasured = [i for i in [*report.markers, *report.skills] if i["verdict"] == exposure.UNMEASURED]
    if unmeasured:
        print(f"\nskillc: UNMEASURED - {len(unmeasured)} declared item(s) could not be observed")
        return 1
    print(f"\nskillc: measured - evidence in {out}")
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    """The operator demo (#81, Refs #10): a real Docker trial lifecycle, end
    to end, on the operator's OWN machine. #10 closes on THIS run, against a
    real daemon - never on this command's own tests passing, never on CI.

    `--control` inverts the verdict: it exits 0 only when every SEEDED
    failure was actually caught, never when the run itself looked clean.

    EXIT CODES, pinned to the runbook (issue #118): `0` success (or, under
    `--control`, every seeded failure was caught); `1` NOT MET, or the run
    could not even complete (a refused subject, a backend that never came
    up, an interruption, or any other failure this command did not
    anticipate); `2` ONLY a leak-check refusal of the paste-back block
    itself - never any other meaning. Every branch below returns one of
    exactly these three, and the top-level `except Exception` (plus the
    separate `except KeyboardInterrupt`, below) is what makes that a
    structural guarantee rather than a hope: NOTHING this command does not
    explicitly handle can produce a fourth exit code, or a raw traceback, or
    unscanned text on stdout/stderr (issue #118's own finding: an uncaught
    `BackendUnavailable` used to print a traceback carrying the operator's
    home directory and username - `demo.py`'s own entry points no longer let
    that kind of failure escape uncaught, and this is the second,
    independent layer for whatever they still miss).

    `KeyboardInterrupt` NEEDS ITS OWN CLAUSE (found by cross-model review of
    this exact fix): it is a `BaseException`, not an `Exception`, so the
    guard above never sees it, and Ctrl-C is exactly what an operator
    watching a slow real daemon actually presses - #118's leak would
    otherwise come back through that one specific route, via Python's own
    default traceback for an uncaught `KeyboardInterrupt`, whose frames name
    the installed `skillc` paths (usually under the operator's home in a
    `uv`/venv layout).

    THE INTERRUPT SWEEP IS SCOPED TO THIS RUN'S OWN ATTEMPT IDS, NEVER
    HOST-GLOBAL (issue #118 review, second pass): an earlier version called a
    `reap_all_owned()` that removed every skillc-owned container on the
    daemon regardless of which run started it - reproduced for real under a
    genuine SIGINT, where it reaped a foreign container from another attempt
    entirely. `recorded_attempt_ids` is built here, before either `run_demo`
    or `run_control` is called, and handed to them so each records its own
    attempt id the instant it exists (see `demo.run_demo`'s own docstring) -
    so if this command has recorded nothing yet when the interrupt lands, it
    sweeps nothing, rather than guessing at what else might be this run's."""
    from . import collection_conformance as cc
    from . import demo

    docker_bin = tuple(args.docker_bin.split()) if args.docker_bin else ("docker",)
    base = Path(args.base) if args.base else Path(tempfile.gettempdir())
    recorded_attempt_ids: list[str] = []

    if args.control and args.task is not None:
        # issue #20 Nit Store: --control's seeded negative controls grade a
        # known-bad candidate (demo.BAD_CANDIDATE) specific to the DEFAULT
        # task's own wrong-answer fixtures - a different task's `wrong/`
        # directory names its own cases differently, and picking one by an
        # arbitrary rule (e.g. sort order) would make the negative control
        # itself an arbitrary instrument whose choice changes silently
        # whenever someone adds a `wrong/` case (orchestrator review).
        # Refused explicitly rather than silently grading the wrong task's
        # candidate against the default task's grader, or the reverse.
        print("skillc: --control only supports the default task; see #20", file=sys.stderr)
        return 1

    try:
        task_root = cc.resolve_task_root(args.task)
        if args.cancel_target is not None:
            # Hidden (issue #122): the child `--control`'s cancellation seed
            # interrupts. Inside this `try` on purpose, so a SIGINT reaches
            # the real handler below, not a copy of it.
            return demo.run_cancel_target(
                image=args.image or demo.DEFAULT_IMAGE, docker_bin=docker_bin, base=base, timeout=args.timeout,
                sleep=args.cancel_target, recorded_attempt_ids=recorded_attempt_ids,
            )
        if args.control:
            control = demo.run_control(
                image=args.image or demo.DEFAULT_IMAGE, docker_bin=docker_bin, base=base, timeout=args.timeout,
                recorded_attempt_ids=recorded_attempt_ids,
            )
            demo.print_paste_back(control.paste_back)
            if control.ok:
                print("skillc: --control - every seeded failure was caught")
                return 0
            print("skillc: --control - at least one seeded failure was NOT caught", file=sys.stderr)
            return 1

        subject_name = None
        if args.subject is not None:
            subject_name = args.subject or demo.DEFAULT_SUBJECT
        result = demo.run_demo(
            image=args.image or demo.DEFAULT_IMAGE, docker_bin=docker_bin, base=base, timeout=args.timeout,
            subject_name=subject_name, recorded_attempt_ids=recorded_attempt_ids, task_root=task_root,
        )
        demo.print_paste_back(result.paste_back)
        return 0 if result.ok else 1
    except demo.PasteBackRefused:
        # Never print `exc` itself here: its own message is built from
        # `leak.scan_text`'s findings, which NAME the leaked value found
        # (issue #118 review) - printing it would be the exact leak this
        # whole mechanism exists to prevent, one level up.
        print(
            "skillc: the paste-back block failed its own leak-check and was refused - nothing was printed",
            file=sys.stderr,
        )
        return 2
    except KeyboardInterrupt:
        # A fixed line, no exception text at all - never anything to scrub,
        # by construction, since KeyboardInterrupt carries none.
        print(demo.INTERRUPT_LINE, file=sys.stderr, flush=True)
        if not recorded_attempt_ids:
            print(
                "skillc: no attempt ids were recorded before the interrupt - nothing to sweep",
                file=sys.stderr,
            )
            return 1
        # A SECOND Ctrl-C during the sweep would raise KeyboardInterrupt
        # here, which `except Exception` does not catch - Python's own
        # traceback, the #118 host-path leak class, would print (issue #122,
        # from the nit store). SIGINT is ignored for the sweep's own bounded
        # duration and restored afterwards. `signal.signal` works only on the
        # main thread; elsewhere the sweep runs unshielded rather than not at all.
        try:
            previous_handler = signal.signal(signal.SIGINT, signal.SIG_IGN)
        except ValueError:
            previous_handler = None
        try:
            report = demo.reap.reap(docker_bin, recorded_attempt_ids, None, timeout=10)
            outcomes = [(o.attempt_id, o.outcome) for o in report.outcomes]
            print(f"skillc: best-effort cleanup - outcomes={outcomes}, daemon_reachable={report.daemon_reachable}", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001 - best-effort: a cleanup failure must not itself crash this handler
            print(f"skillc: best-effort cleanup also failed - {demo.describe_error_safely(exc, base=base)}", file=sys.stderr)
        finally:
            if previous_handler is not None:
                signal.signal(signal.SIGINT, previous_handler)
        return 1
    except Exception as exc:  # noqa: BLE001 - the top-level guard (issue #118), deliberately broad: see the docstring above
        print(f"skillc: demo failed unexpectedly - {demo.describe_error_safely(exc, base=base)}", file=sys.stderr)
        return 1


def cmd_collection_run(args: argparse.Namespace) -> int:
    """Issue #11's remaining acceptance bullet ("the same client, Level 1
    fixture, contract and grader"): one real agent attempt against
    `evals/level1/slug-small-fix`, with `SUBJECT`'s declared, selected skill
    files installed into the same container, in skill-free canary mode.

    Requires `SKILLC_ALLOW_REAL_AGENT=1` (`lifecycle.py`'s own structural
    guard - this command sets no gate of its own) and the operator's own
    subscription login for the client the subject's surface declares
    (issue #124: `~/.codex/auth.json` for codex, `~/.claude/.credentials.json`
    for claude, by default, or `--credential`), per ADR 0005 rule 6, "Normal
    Claude and codex" - never metered API spend.

    Exits 1 unless the attempt is captured AND graded PASS, and also when the
    transcript's own skill listing measurably omits a selected skill
    (`CollectionAgentResult.discovery_failed`, issue #124). UNMEASURED
    discovery is printed, not failed."""
    from . import collection_conformance as cc
    from . import credential, demo, reap, trial, verify

    docker_bin = tuple(args.docker_bin.split()) if args.docker_bin else ("docker",)
    base = Path(args.base) if args.base else Path(tempfile.gettempdir())
    image = args.image or demo.DEFAULT_IMAGE
    credential_path = Path(args.credential) if args.credential else None
    agent_timeout = args.agent_timeout if args.agent_timeout is not None else cc.DEFAULT_AGENT_TIMEOUT
    if getattr(args, "evidence_transcript", False) and not args.evidence:
        print("skillc: --evidence-transcript needs --evidence; there is no export to add it to", file=sys.stderr)
        return 2
    try:
        task_root = cc.resolve_task_root(args.task)
    except demo.SubjectRefused as exc:
        print(f"skillc: {exc}", file=sys.stderr)
        return 2
    try:
        run_root = cc.new_run_root(base, args.subject)
    except demo.SubjectRefused as exc:
        print(f"skillc: {exc}", file=sys.stderr)
        return 2

    try:
        try:
            acquired = (
                cc.acquire_degraded_collection(args.subject, Path(args.degraded))
                if args.degraded else cc.acquire_collection(args.subject, run_root)
            )
        except demo.SubjectRefused as exc:
            print(f"skillc: {exc}", file=sys.stderr)
            return 2
        client_argv = (
            args.client_argv.split() if args.client_argv
            else list(cc.DEFAULT_CLIENT_ARGVS[acquired.subject.client])
        )

        # Resolved BEFORE planning, so the plan's own image.digest reflects the
        # image that actually runs - `demo.run_demo`'s own "resolved before
        # either backend starts" rule, for the same reason (codex review: a
        # placeholder digest here left the planned evidence unable to identify
        # its own inputs).
        image_digest = demo.resolve_image_digest(docker_bin, image, None, args.timeout)
        store_path = run_root / f"{args.subject}-store"
        store = trial.open_store(store_path, forbidden=[])
        experiment, attempt_id = cc.plan_collection_attempt(
            args.subject, acquired, store, image_digest=image_digest, task_root=task_root,
        )

        backend, grading_backend = cc.agent_backends(
            image=image, base=run_root, docker_bin=docker_bin, daemon_timeout=args.timeout,
        )
        # Issue #106's retained evidence, taken AROUND the whole run (agent and
        # grading containers alike): the operator's own credential file, and
        # the daemon's skillc-owned containers. Both are observations only -
        # neither changes what the attempt itself does.
        host_before = cc.read_host_credential(acquired.subject.client, credential_path)
        daemon_before = reap.snapshot(docker_bin, timeout=args.timeout)
        minimum = (
            args.minimum_credential_seconds if args.minimum_credential_seconds is not None
            else credential.MINIMUM_REMAINING_SECONDS
        )
        result = cc.run_collection_agent_attempt(
            subject_name=args.subject, acquired=acquired, experiment=experiment, attempt_id=attempt_id,
            backend=backend, grading_backend=grading_backend, base=run_root,
            base_argv=client_argv, task_root=task_root, timeout=agent_timeout,
            credential_explicit_path=credential_path, minimum_credential_seconds=minimum,
        )
        daemon_after = reap.snapshot(docker_bin, timeout=args.timeout)
        host_after = cc.read_host_credential(acquired.subject.client, credential_path)
    finally:
        cc.discard_acquisition(run_root, args.subject)

    attempt_ids = [*backend.prepared_ids, *grading_backend.prepared_ids]
    result = dataclasses.replace(
        result,
        host_credential=cc.HostCredentialCheck(before=host_before, after=host_after),
        daemon_diff=reap.diff(daemon_before, daemon_after),
        attributable_leftovers=cc.attributable_leftovers(docker_bin, attempt_ids, args.timeout),
        attempts_checked=len(attempt_ids),
        store_display=demo.redact_known_host_paths(str(store_path)),
    )
    # The whole evidence envelope, kept beside the store it describes - only
    # when it passes the leak check (leaves AND serialized text) after the
    # same host-path redaction; one that fails is never written, and the
    # paste-back says so (`record_written=False`).
    envelope = cc.evidence_envelope(result)
    record_text = demo.redact_known_host_paths(
        json.dumps(envelope, indent=2, sort_keys=True, default=str), base=run_root,
    )
    record_written = False
    # Leaves of the REDACTED document: re-parsing un-escapes each string
    # exactly as the reader of the file will see it.
    if not cc.evidence_leak_findings(json.loads(record_text), record_text):
        try:
            store_path.mkdir(parents=True, exist_ok=True)
            (store_path / "collection-run-record.json").write_text(record_text + "\n", encoding="utf-8")
        except OSError:
            pass
        else:
            record_written = True
    result = dataclasses.replace(result, record_written=record_written)

    # Issue #13: best-effort only - a dimensions lookup must never turn a
    # completed run's own paste-back into a crash. The grader already ran
    # successfully against this exact task_root, so a load failure here
    # would be surprising, but graded.dimensions degrading to "unavailable"
    # is a far smaller problem than losing the rest of this report over it.
    # The exception's own message is never propagated into the printed
    # paste-back (leak-checked, but a raw grader.json read/parse error could
    # still name a host path) - only its CLASS, a bounded, path-free reason.
    dimensions: dict[str, str] = {}
    dimensions_unavailable_reason: str | None = None
    try:
        dimensions = verify.GraderDef.load(task_root).dimensions
    except (verify.Refused, OSError) as exc:
        dimensions_unavailable_reason = f"grader load failed ({type(exc).__name__})"
    paste_back = cc.build_collection_paste_back(
        result, dimensions, dimensions_unavailable_reason=dimensions_unavailable_reason,
    )
    try:
        demo.print_paste_back(paste_back)
    except demo.PasteBackRefused as exc:
        print(f"skillc: {exc}", file=sys.stderr)
        return 2

    # Codex review: `graded is None` (grading BLOCKED - a prompt-delivery
    # mismatch or a failed canary, `run_collection_agent_attempt`'s own
    # `grading_blocked_reason`) must never read as success just because
    # nothing contradicted it - a captured-but-ungraded attempt is not the
    # same fact as a passing one. Success requires an ACTUAL PASS verdict.
    graded = result.record.get("graded")
    graded_ok = isinstance(graded, dict) and graded.get("status") == "PASS"
    # Issue #106: a PASS that left a container behind, or could not confirm
    # its own teardown, is not a clean run - the cleanup evidence is part of
    # the verdict, not a footnote to it.
    # Attributed to THIS run's attempt ids only (codex review): the
    # daemon-wide diff is context in the paste-back, never the verdict, since
    # a concurrent run's container would otherwise fail a clean run.
    cleanup_ok = (
        result.record.get("backend_teardown") == "confirmed"
        and result.attributable_leftovers == []
    )
    # Issue #124: a selected skill the transcript's own listing measurably
    # omits fails the run too; UNMEASURED discovery is printed, not failed.
    captured = result.record.get("disposition") == "captured"
    run_ok = captured and graded_ok and cleanup_ok and not result.discovery_failed

    # Issue #150 acceptance item 4: exported regardless of `run_ok` - the
    # DEGRADED arm's own expected verdict is FAIL, and its verified-result
    # still needs to reach the consumer for the discrimination this exists to
    # show. An export refusal (leak check or check-records) is reported
    # distinctly and takes priority over the run's own verdict, because it
    # means the evidence itself could not be trusted to publish, which is a
    # different and more severe failure than an ungraded or failing attempt.
    if args.evidence:
        # #150's own discrimination pair is normal-arm PASS + degraded-arm
        # FAIL, each retained - but only the NORMAL arm belongs in a
        # consumer's real measurements directory. CPP's own
        # `check-behavioral-eval.py` reports any declared FAIL as an error
        # and the flip to blocking is pre-committed, so a degraded arm's
        # export landed there by habit would turn that gate red for good.
        # `result.revision` carries the `degraded:` label (`degrade.py`) the
        # moment a run is over a degraded subject (#150-B2 wires the CLI leg
        # that produces one); `--evidence-role control` is the explicit,
        # named opt-in required to publish one - e.g. as a one-shot negative
        # control for the consumer gate, never the default path.
        degraded_arm = result.revision.startswith("degraded:")
        if degraded_arm and args.evidence_role != "control":
            print(
                f"skillc: refusing to export a degraded-arm result (revision={result.revision!r}) "
                f"with --evidence-role {args.evidence_role!r}; pass --evidence-role control to "
                f"publish a degraded arm's export (e.g. as a negative control), never by habit into "
                f"a measurements directory",
                file=sys.stderr,
            )
            return 2
        export_code = _export_collection_evidence(
            experiment, envelope, Path(args.evidence), transcript=getattr(args, "evidence_transcript", False),
        )
        if export_code:
            return export_code
    return 0 if run_ok else 1


def cmd_selection_probe(args: argparse.Namespace) -> int:
    """Issue #26's live run: every predeclared selection case, both arms, one
    real agent attempt each (`evals/selection-probe/cases.json` and
    `run-manifest.json`), through `selection_probe.agent_trial_runner`. With
    `--detection-control`, the predeclared control instead
    (`detection-control.json`): the intended-use case only, the canary naming
    the skill - a check that the pipeline can see an invocation, never a
    selection result.

    `--task DIR` (default `evals/level1/slug-small-fix`, unchanged behaviour
    without the flag; issue #20 Nit Store, mirroring `collection-run`'s own
    `--task`, #162) is the Level 1 task each attempt's prompt, fixture and
    grading come from - `resolve_task_root`'s own contract. The selection
    CASES themselves (`cases.json`'s `intended-use`/`near-miss`/
    `overlapping-choice`) are unaffected: they are a property of the
    collection being probed, not of which coding task the agent is asked to
    fix.

    Requires `SKILLC_ALLOW_REAL_AGENT=1` (`lifecycle.py`'s own guard) and the
    operator's subscription login, per ADR 0005 rule 6. Each attempt's
    observation is persisted by `run_one_attempt` (#142) in the store; the
    report is written beside it only when it passes the leak check.

    Exits 1 unless `selection_probe.probe_verdict` is ok: every attempt
    captured for a selection run; detected in treatment and absent in
    baseline for the control. Exits 2 when the run is refused before it
    starts."""
    from . import collection_conformance as cc
    from . import credential, demo, trial, verify
    from . import selection_probe as sp

    docker_bin = tuple(args.docker_bin.split()) if args.docker_bin else ("docker",)
    base = Path(args.base) if args.base else Path(tempfile.gettempdir())
    image = args.image or demo.DEFAULT_IMAGE
    agent_timeout = args.agent_timeout if args.agent_timeout is not None else cc.DEFAULT_AGENT_TIMEOUT
    minimum = (
        args.minimum_credential_seconds if args.minimum_credential_seconds is not None
        else credential.MINIMUM_REMAINING_SECONDS
    )
    cases, manifest = sp.load_cases(), sp.load_manifest()
    control = sp.load_detection_control() if args.detection_control else None
    experiment_name = str(control["experiment"]) if control is not None else "selection-probe"
    subject = str(cases["subject"])
    try:
        planned_cases = sp.detection_control_cases(cases, control) if control is not None else cases
        task_root = cc.resolve_task_root(args.task)
        run_root = cc.new_run_root(base, experiment_name)
    except (sp.SelectionProbeRefused, demo.SubjectRefused) as exc:
        print(f"skillc: {exc}", file=sys.stderr)
        return 2

    store_path = run_root / f"{experiment_name}-store"
    try:
        try:
            acquired = cc.acquire_collection(subject, run_root)
        except demo.SubjectRefused as exc:
            print(f"skillc: {exc}", file=sys.stderr)
            return 2
        client_argv = (
            args.client_argv.split() if args.client_argv
            else list(cc.DEFAULT_CLIENT_ARGVS[acquired.subject.client])
        )
        image_digest = demo.resolve_image_digest(docker_bin, image, None, args.timeout)
        experiment = sp.plan_selection_probe(
            planned_cases, manifest, treatment_subject_digest=acquired.source.digest,
            baseline_subject_digest=sp.BASELINE_SUBJECT_DIGEST, image_digest=image_digest or "UNKNOWN",
            store=trial.open_store(store_path, forbidden=[]), experiment_name=experiment_name,
        )
        backend, grading_backend = cc.agent_backends(
            image=image, base=run_root, docker_bin=docker_bin, daemon_timeout=args.timeout,
        )
        runner = sp.agent_trial_runner(
            experiment=experiment, backend=backend, base=run_root, client=acquired.subject.client,
            argv_for=lambda _attempt_id: client_argv,
            treatment_home_files=cc._collection_home_files(acquired.source, acquired.files),
            goal=(task_root / "goal.md").read_text(encoding="utf-8"),
            surface=cc.surface_mapping(cc.task_surface(task_root / "fixture")),
            timeout=agent_timeout, cli_version=acquired.subject.client_version,
            credential_explicit_path=Path(args.credential) if args.credential else None,
            minimum_credential_seconds=minimum,
            skill_name=str(control["skill_name"]) if control is not None else None,
        )
        try:
            report = sp.run_planned_selection_probe(
                experiment, planned_cases, runner, base=run_root,
                grader=verify.GraderDef.load(task_root), grading_backend=grading_backend,
                detection_control=control is not None,
            )
        except sp.SelectionProbeRefused as exc:
            print(f"skillc: {exc}", file=sys.stderr)
            return 2
    finally:
        cc.discard_acquisition(run_root, subject)

    ok, why = sp.probe_verdict(report, detection_control=control is not None)
    document = {
        "experiment": experiment.id, "kind": "detection-control" if control is not None else "selection",
        "control": control["id"] if control is not None else None,
        "subject": subject, "subject_revision": acquired.subject.revision,
        "subject_digest": acquired.source.digest, "image": image, "image_digest": image_digest,
        "client": acquired.subject.client, "client_version": acquired.subject.client_version,
        "verdict": {"ok": ok, "why": why},
        "cases": [
            {
                "case_id": case.case_id, "kind": case.kind, "applicable_skills": list(case.applicable_skills),
                "treatment": {**dataclasses.asdict(case.treatment), "observed": sorted(case.treatment.observed)},
                "baseline": {**dataclasses.asdict(case.baseline), "observed": sorted(case.baseline.observed)},
                "baseline_contaminated": case.baseline_contaminated,
            }
            for case in report.cases
        ],
    }
    text = demo.redact_known_host_paths(json.dumps(document, indent=2, sort_keys=True, default=str), base=run_root)
    written = False
    if not cc.evidence_leak_findings(json.loads(text), text):
        try:
            store_path.mkdir(parents=True, exist_ok=True)
            (store_path / "selection-probe-report.json").write_text(text + "\n", encoding="utf-8")
            written = True
        except OSError:
            pass

    lines = [(
        f"{document['kind']} run: experiment={experiment.id} subject={subject}@{acquired.subject.revision} "
        f"client={acquired.subject.client} {acquired.subject.client_version}"
    )]
    for case in report.cases:
        for arm, result in (("treatment", case.treatment), ("baseline", case.baseline)):
            lines.append(
                f"  {case.case_id} {arm}: disposition={result.disposition} selection={result.selection} "
                f"task_success={result.task_success} invoked={sorted(result.observed)}"
                f"{' (heuristic detection)' if result.codex_best_effort else ''}"
                f"{' - ' + result.detail if result.detail else ''}"
            )
    lines.append(f"  report_written={written} store={store_path}")
    lines.append(f"verdict: {'ok' if ok else 'NOT ok'} - {why}")
    # The console gets the same protection as the report file: redacted, then
    # leak-checked as a whole and refused rather than printed (#26 review - a
    # record's own `reason` can carry a host path or a private address).
    try:
        demo.print_paste_back(demo.redact_known_host_paths("\n".join(lines), base=run_root))
    except demo.PasteBackRefused as exc:
        # Categories only: each finding reads "<line>: <category>: <value>",
        # and the value is exactly what must not be shown (#26 re-review).
        categories = sorted({
            parts[1] for parts in (line.split(": ", 2) for line in str(exc).splitlines()[1:]) if len(parts) == 3
        })
        print(f"skillc: the selection-probe output failed its own leak check and was NOT printed "
              f"({', '.join(categories) or 'unclassified'}); the verdict was {'ok' if ok else 'NOT ok'}",
              file=sys.stderr)
        return 2
    return 0 if ok else 1


def _export_pilot_evidence(experiment: object, report: dict[str, object], evidence: Path) -> int:
    """Publish under an exclusive lock on the destination's PARENT DIRECTORY,
    held from the ownership check through the replacement (#147 counter-model
    review): two exporters racing into one destination would otherwise both
    pass the check, and the later replacement would delete the earlier one's
    bundle. The parent is the one location every publisher of that
    destination shares whatever its environment - a lock file under the temp
    directory was not (a different TMPDIR, a different lock) - and it leaves
    no lock file in the work tree. The second publisher waits, then sees the
    first bundle and refuses."""
    import fcntl

    if evidence.is_symlink():
        print(f"skillc: refusing to publish through a symlink: {evidence}", file=sys.stderr)
        return 2
    parent = evidence.resolve().parent
    parent.mkdir(parents=True, exist_ok=True)
    lock = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _publish_pilot_evidence(experiment, report, evidence)
    finally:
        os.close(lock)  # closing the descriptor releases the lock


def _publish_pilot_evidence(experiment: object, report: dict[str, object], evidence: Path) -> int:
    """Publish the bundle as ONE unit. It is exported into a fresh staging
    directory beside `evidence`, and only that staging copy is leak-checked
    and record-checked - never a neighbouring file already in `evidence`.
    Only when both pass does it replace `evidence` wholesale, so a re-run
    never mixes two runs' records and a failed export leaves the previous
    bundle untouched. Returns a process exit code."""
    import shutil

    from . import matched_pilot as mp

    if evidence.is_symlink():
        print(f"skillc: refusing to publish through a symlink: {evidence}", file=sys.stderr)
        return 2
    evidence = evidence.resolve()
    if evidence.exists():
        # Replacing the destination deletes it, so it must hold nothing but a
        # bundle this exporter could have written - never a README, a claims
        # file or anything else that merely sits there.
        foreign = sorted(p.name for p in evidence.iterdir() if not mp.is_bundle_file(p))
        if foreign or not evidence.is_dir():
            print(
                f"skillc: refusing to replace {evidence}: it holds file(s) this exporter does not own "
                f"({', '.join(foreign) or 'not a directory'}); point --evidence at a bundle-only directory",
                file=sys.stderr,
            )
            return 2
        # A bundle is a published experiment's record. Replacing it is only a
        # re-export of the SAME experiment (merging reviewed claims, say);
        # another experiment's bundle, or one whose ledger cannot say whose it
        # is, is never ours to replace (#147: a default run would otherwise
        # have deleted #12's first-run bundle). An empty directory holds no
        # record and may be written.
        if any(evidence.iterdir()):
            existing = mp.bundle_experiment_id(evidence)
            if existing != report.get("experiment_id"):
                print(
                    f"skillc: refusing to replace {evidence}: it holds the bundle of experiment "
                    f"{existing or '<unidentifiable: no readable ledger>'}, not {report.get('experiment_id')}; "
                    f"publish a new experiment to its own --evidence directory",
                    file=sys.stderr,
                )
                return 2
    evidence.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{evidence.name}.staging-", dir=evidence.parent))
    try:
        written = mp.export_bundle(experiment, report, staging)  # type: ignore[arg-type]
        result = leak.scan_path(
            staging, leak.load_denylist(None), host_paths=leak.default_host_paths()
        )
        if result.findings or result.scanned == 0:
            for finding in result.findings:
                print(finding.render(staging), file=sys.stderr)
            print("skillc: the pilot bundle failed its leak check; nothing was published", file=sys.stderr)
            return 1
        unexpected, known = mp.bundle_findings(staging)
        if unexpected:
            for line in unexpected:
                print(f"skillc: {line}", file=sys.stderr)
            print("skillc: the pilot bundle failed check-records; nothing was published", file=sys.stderr)
            return 1
        if evidence.exists():
            shutil.rmtree(evidence)
        staging.rename(evidence)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    print(f"skillc: published {len(written)} record(s) to {evidence.name}/: leak-checked "
          f"({result.scanned} scanned, 0 found); check-records clean" + (
              f" except {known} known '{mp.KNOWN_GAP_TEXT}' finding(s) (a pre-#139 run: it stored "
              f"no verified-result)" if known else ""))
    return 0


def _export_collection_evidence(
    experiment: object, report: dict[str, object], evidence: Path, *, transcript: bool = False,
) -> int:
    """Issue #150 acceptance item 4: publish one collection-run attempt's
    evidence into `evidence`, under the SAME lock-and-atomic-replace discipline
    `_export_pilot_evidence` already uses for its bundle - held on the
    destination's parent directory for the same reason (#147): two exporters
    racing into one destination must not both pass the gate and have the
    later one delete the earlier bundle."""
    import fcntl

    if evidence.is_symlink():
        print(f"skillc: refusing to publish through a symlink: {evidence}", file=sys.stderr)
        return 2
    parent = evidence.resolve().parent
    parent.mkdir(parents=True, exist_ok=True)
    lock = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _publish_collection_evidence(experiment, report, evidence, transcript=transcript)
    finally:
        os.close(lock)


#: The two things a published behavioral-eval directory may ever hold (issue
#: #150; layout documented in
#: docs/specs/evaluation-facility/behavioral-eval-export.md): a flat
#: `result-*.json` - the verified-result(s) CPP's `check-behavioral-eval.py`
#: reads with an un-recursive `glob("*.json")`, so nothing else may share that
#: level - and the `bundle/` directory beside it, holding the full skillc
#: bundle (ledger, receipts, manifests, the results again) a FUTURE bundle-rule
#: reader needs. `bundle/` itself is not a `*.json` file, so today's consumer
#: never sees it.
_RESULT_FILE_RE = re.compile(r"result-[A-Za-z0-9_.-]+\.json")


def _is_behavioral_eval_export_file(path: Path) -> bool:
    if path.name == "bundle" and path.is_dir():
        return True
    return path.is_file() and not path.is_symlink() and _RESULT_FILE_RE.fullmatch(path.name) is not None


def _stage_transcripts(experiment: object, bundle_dir: Path) -> str | None:
    """Issue #202: copy each bundled attempt's retained transcript object to
    `bundle_dir/transcripts/<attempt>.jsonl`. Returns a refusal reason when an
    attempt retained none - the operator asked for the transcript, and an
    export without it would read as one that had it. The object is re-hashed
    on the way out (`trial._read_object`). `transcripts/` holds no `*.json`,
    so `records.discover_bundles` never reads it as a bundle."""
    from . import agent_trial, trial

    assert isinstance(experiment, trial.Experiment)
    manifests = sorted(bundle_dir.glob("manifest-*.json"))
    if not manifests:
        return "no attempt was captured, so no transcript was retained"
    target_dir = bundle_dir / "transcripts"
    for manifest_path in manifests:
        attempt_id = str(json.loads(manifest_path.read_bytes()).get("attempt_id"))
        retention = agent_trial.transcript_retention(experiment, attempt_id, None)
        if retention["coverage"] not in ("complete", "partial") or not retention["digest"]:
            return f"attempt {attempt_id} retained no transcript ({retention['reason']})"
        data = trial._read_object(experiment.root, str(retention["digest"]))
        # Re-checked on the way out with the retention check itself: the
        # staging scan below reads raw text only, and cannot see a credential
        # a JSONL line escaped (#202, counter-model review).
        findings = agent_trial.transcript_leak_findings(data)
        if findings:
            return f"attempt {attempt_id}'s transcript failed its leak check ({', '.join(findings)})"
        target_dir.mkdir(exist_ok=True)
        (target_dir / f"{attempt_id}.jsonl").write_bytes(data)
    return None


def _publish_collection_evidence(
    experiment: object, report: dict[str, object], evidence: Path, *, transcript: bool = False,
) -> int:
    """Stage the full skillc bundle under `staging/bundle/` (`matched_pilot
    .export_bundle` - the SAME writer `pilot-run` already uses, "as pilot-run
    already does for its bundle"), copy its `result-*.json` file(s) up to
    `staging/` itself, leak-check the WHOLE staging tree, then run
    `check-records`' bundle rules over `staging/bundle/` alone (they need the
    ledger and manifest beside a result; the flat top-level copies are not a
    bundle `records.discover_bundles` would recognise, so they are never given
    to it). Only when both pass does it replace `evidence` wholesale, and only
    when `evidence`, if it already exists, holds nothing this exporter would
    not itself have written."""
    import shutil

    from . import matched_pilot as mp

    if evidence.is_symlink():
        print(f"skillc: refusing to publish through a symlink: {evidence}", file=sys.stderr)
        return 2
    evidence = evidence.resolve()
    if evidence.exists():
        foreign = sorted(p.name for p in evidence.iterdir() if not _is_behavioral_eval_export_file(p))
        if foreign or not evidence.is_dir():
            print(
                f"skillc: refusing to replace {evidence}: it holds file(s) this exporter does not own "
                f"({', '.join(foreign) or 'not a directory'}); point --evidence at an export-only directory",
                file=sys.stderr,
            )
            return 2

    evidence.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{evidence.name}.staging-", dir=evidence.parent))
    try:
        bundle_dir = staging / "bundle"
        mp.export_bundle(experiment, report, bundle_dir)  # type: ignore[arg-type]
        if transcript:
            refusal = _stage_transcripts(experiment, bundle_dir)
            if refusal is not None:
                print(f"skillc: --evidence-transcript: {refusal}; nothing was published", file=sys.stderr)
                return 1
        result_files = sorted(bundle_dir.glob("result-*.json"))
        if not result_files:
            print("skillc: no verified-result was stored for this attempt; nothing was published", file=sys.stderr)
            return 1
        for source in result_files:
            (staging / source.name).write_bytes(source.read_bytes())

        # The leak check scans the WHOLE staged tree, `report.json` included -
        # dropped below, but only after this, so nothing that was briefly
        # staged for publishing can skip the scan by virtue of being removed
        # first. `host_paths=leak.default_host_paths()` (#134 item 5): without
        # it this export is blind to a `/workspace` or `/srv` path on the
        # exporting machine - exactly the layout every session in this fleet
        # runs from - because the static `home-path` pattern only recognizes
        # `/home/` and `/Users/`.
        scan = leak.scan_path(staging, leak.load_denylist(None), host_paths=leak.default_host_paths())
        if scan.findings or scan.scanned == 0:
            for finding in scan.findings:
                print(finding.render(staging), file=sys.stderr)
            print("skillc: the exported evidence failed its leak check; nothing was published", file=sys.stderr)
            return 1
        # `export_bundle` always writes a `report.json` alongside the bundle
        # it copies - fine for pilot-run, whose `report` is itself a
        # schema-legal `pilot-report` record, but a collection-run envelope
        # (`collection_conformance.evidence_envelope`) carries no `kind`/
        # `version` at all, so `check-records` would refuse it as an
        # unversioned record. It names nothing the bundle rules need (they
        # read the ledger, manifest and receipts, never a report summary), so
        # it is dropped here, after the leak check, rather than validated
        # against a schema it was never meant to satisfy.
        (bundle_dir / "report.json").unlink(missing_ok=True)
        unexpected, _known = mp.bundle_findings(bundle_dir)
        if unexpected:
            for line in unexpected:
                print(f"skillc: {line}", file=sys.stderr)
            print("skillc: the exported bundle failed check-records; nothing was published", file=sys.stderr)
            return 1

        if evidence.exists():
            shutil.rmtree(evidence)
        staging.rename(evidence)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    print(
        f"skillc: published {len(result_files)} verified-result(s) to {evidence.name}/: leak-checked "
        f"({scan.scanned} scanned, 0 found); check-records clean; full bundle in {evidence.name}/bundle/"
        + (f"; transcript(s) in {evidence.name}/bundle/transcripts/" if transcript else
           "; transcript not exported (pass --evidence-transcript to include it)")
    )
    return 0


def _print_pilot_summary(report: dict[str, object]) -> int:
    from . import demo
    from . import matched_pilot as mp

    try:
        demo.print_paste_back(json.dumps(mp.summarize(report), indent=1))
    except demo.PasteBackRefused as exc:
        print(f"skillc: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_pilot_run(args: argparse.Namespace) -> int:
    """Issue #12: run the predeclared matched pilot (the current declaration,
    `matched_pilot.CURRENT_MANIFEST_PATH`) end to end and export its
    evidence report. Requires `SKILLC_ALLOW_REAL_AGENT=1` (`lifecycle.py`'s
    own guard) and the operator's own Codex subscription login (ADR 0005
    rule 6). The declared pins are CHECKED against what would actually run -
    the subject revision, the client version, a resolvable image digest, a
    client argv that does not choose its own model - and a mismatch refuses
    the run rather than recording a pilot of something other than what was
    declared. An attempt observed running a model other than the declared
    one (#141) is published as ineligible, and the run exits 1."""
    import secrets
    from datetime import UTC, datetime

    from . import collection_conformance as cc
    from . import demo, trial_bootstrap, verify
    from . import matched_pilot as mp

    try:
        declaration = mp.load_declaration(Path(args.manifest) if args.manifest else mp.CURRENT_MANIFEST_PATH)
    except (mp.ManifestRefused, OSError, KeyError, ValueError) as exc:
        print(f"skillc: the run manifest cannot be run as written: {exc}", file=sys.stderr)
        return 2
    client_argv = args.client_argv.split() if args.client_argv else list(cc.DEFAULT_CLIENT_ARGV)
    try:
        # Checked here, before the image or any run directory: the same
        # refusal `run_pilot` repeats per attempt.
        mp.launch_argv(declaration, client_argv)
    except mp.ModelOverrideRefused as exc:
        print(f"skillc: {exc}", file=sys.stderr)
        return 2
    pinned = trial_bootstrap.pinned_cli_version("codex")
    if declaration.client_name != "codex" or pinned != declaration.client_version:
        print(
            f"skillc: manifest declares {declaration.client_name} {declaration.client_version}, but the trial "
            f"image pins codex {pinned}; refusing a run of a client other than the declared one",
            file=sys.stderr,
        )
        return 2
    docker_bin = tuple(args.docker_bin.split()) if args.docker_bin else ("docker",)
    image = args.image or demo.DEFAULT_IMAGE
    image_digest = demo.resolve_image_digest(docker_bin, image, None, args.timeout)
    if image_digest is None:
        print(f"skillc: could not resolve the digest of image {image!r}; a pilot never runs on an unknown image",
              file=sys.stderr)
        return 2
    if image_digest != declaration.image_digest:
        print(
            f"skillc: image {image!r} resolves to {image_digest}, but the manifest declares "
            f"{declaration.image_digest}; refusing a run on an image other than the declared one",
            file=sys.stderr,
        )
        return 2

    private_root = Path(args.private_dir).expanduser() if args.private_dir else mp.DEFAULT_PRIVATE_ROOT
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = private_root / f"{stamp}-{secrets.token_hex(3)}"
    run_dir.mkdir(parents=True, mode=0o700)
    print(f"skillc: private run directory: {run_dir}", file=sys.stderr)

    try:
        acquired = cc.acquire_collection(declaration.subject_name, run_dir)
    except demo.SubjectRefused as exc:
        print(f"skillc: {exc}", file=sys.stderr)
        return 2
    try:
        if acquired.subject.revision != declaration.subject_revision:
            print(
                f"skillc: subject {declaration.subject_name!r} is pinned at {acquired.subject.revision}, "
                f"but the manifest declares {declaration.subject_revision}; refusing",
                file=sys.stderr,
            )
            return 2
        home_files = cc._collection_home_files(acquired.source, acquired.files)
    finally:
        cc.discard_acquisition(run_dir, declaration.subject_name)

    credential_path = Path(args.credential) if args.credential else None
    experiment, outcomes = mp.run_pilot(
        declaration, run_dir=run_dir, treatment_home_files=home_files,
        treatment_digest=acquired.source.digest, image_digest=image_digest,
        # By the resolved immutable digest, never the tag: a tag re-pointed
        # mid-run would otherwise change the image under later attempts.
        backends=lambda: cc.agent_backends(
            image=image_digest, base=run_dir, docker_bin=docker_bin, daemon_timeout=args.timeout,
        ),
        argv_for=lambda _scheduled: client_argv, credential_explicit_path=credential_path,
    )
    (run_dir / mp.PRIVATE_OBSERVATIONS_FILENAME).write_text(
        json.dumps(mp.private_observations(outcomes), indent=1) + "\n", encoding="utf-8",
    )
    # Issue #13: best-effort, matching cmd_collection_run's own posture - a
    # dimensions lookup must never turn a completed pilot's report into a
    # crash. Degrading to "unavailable" (never a guessed "unclassified") is
    # far smaller than losing the report over it; only the exception's
    # CLASS is kept, never its message, which could name a host path.
    pilot_dimensions: dict[str, str] = {}
    pilot_dimensions_unavailable_reason: str | None = None
    try:
        pilot_dimensions = verify.GraderDef.load(demo.GRADER_ROOT).dimensions
    except (verify.Refused, OSError) as exc:
        pilot_dimensions_unavailable_reason = f"grader load failed ({type(exc).__name__})"
    report = mp.build_report(
        experiment, mp.reconcile(experiment, outcomes),
        declared_model=declaration.model, declared_effort=declaration.reasoning_effort,
        dimensions=pilot_dimensions, dimensions_unavailable_reason=pilot_dimensions_unavailable_reason,
    )
    code = _export_pilot_evidence(experiment, report, Path(args.evidence) if args.evidence else mp.EVIDENCE_DIR)
    code = code or _print_pilot_summary(report)
    return code or _refuse_ineligible(report)


def _refuse_ineligible(report: dict[str, object]) -> int:
    """#141: an attempt that did not run the declared model is recorded,
    published and excluded - and it fails the run. So does a run in which NO
    attempt was observed running it (every one not-run or unavailable): a
    model check with nothing to check is not a pass."""
    from . import matched_pilot as mp

    ineligible = mp.ineligible_attempts(report)
    if not ineligible:
        if not mp.eligible_attempts(report):
            print("skillc: no attempt was launched and observed running the declared model; nothing was compared",
                  file=sys.stderr)
            return 1
        return 0
    print(
        f"skillc: {len(ineligible)} attempt(s) did not run the declared model and are excluded from the "
        f"comparison: {', '.join(ineligible)}",
        file=sys.stderr,
    )
    return 1


def cmd_pilot_report(args: argparse.Namespace) -> int:
    """Rebuild a pilot run's report from its private run directory - the step
    that merges a REVIEWED claims file (`--claims`) once a person has read the
    private final messages. Makes no agent or docker call."""
    from . import demo, verify
    from . import matched_pilot as mp

    # Issue #13: this pilot's grader is fixed (demo.GRADER_ROOT) - every
    # accepted declaration is refused unless its own grader_path resolves to
    # exactly this same root (plan_pilot's own check), so this needs no
    # per-declaration lookup, even when --manifest is not given. Best-effort,
    # matching cmd_pilot_run's own posture - "unavailable" on failure, never
    # a guessed "unclassified", and only the exception's class, never its
    # message.
    pilot_dimensions: dict[str, str] = {}
    pilot_dimensions_unavailable_reason: str | None = None
    try:
        pilot_dimensions = verify.GraderDef.load(demo.GRADER_ROOT).dimensions
    except (verify.Refused, OSError) as exc:
        pilot_dimensions_unavailable_reason = f"grader load failed ({type(exc).__name__})"

    run_dir = Path(args.run_dir).expanduser()
    try:
        recorded = mp.read_declared(run_dir)
        if recorded is None and not args.manifest:
            # #141: a run from before launch pinning recorded no declaration.
            # Defaulting to the CURRENT one would re-score it against a pin it
            # never ran under, so the operator names the one it did.
            print(
                "skillc: this run recorded no declared model (it predates #141); name the declaration it ran "
                f"under with --manifest (#12's run: {mp.MANIFEST_PATH.relative_to(mp.ROOT)})",
                file=sys.stderr,
            )
            return 2
        declared_model: str | None = None
        declared_effort: str | None = None
        if args.manifest:
            declaration = mp.load_declaration(Path(args.manifest))
            declared_model, declared_effort = declaration.model, declaration.reasoning_effort
        if recorded is not None:
            if args.manifest and (recorded["model"], recorded["reasoning_effort"]) != (declared_model, declared_effort):
                print(
                    f"skillc: this run declared model {recorded['model']!r} (effort {recorded['reasoning_effort']!r}) "
                    f"at launch, but --manifest declares {declared_model!r} (effort {declared_effort!r}); refusing",
                    file=sys.stderr,
                )
                return 2
            declared_model, declared_effort = recorded["model"], recorded["reasoning_effort"]
        experiment, outcomes = mp.read_outcomes(run_dir)
        claims = mp.load_claims(Path(args.claims)) if args.claims else None
        reconciled = mp.reconcile(experiment, outcomes)
    except (OSError, KeyError, ValueError) as exc:
        print(f"skillc: {exc}", file=sys.stderr)
        return 2
    report = mp.build_report(
        experiment, reconciled, claims, declared_model=declared_model, declared_effort=declared_effort,
        dimensions=pilot_dimensions, dimensions_unavailable_reason=pilot_dimensions_unavailable_reason,
    )
    code = _export_pilot_evidence(experiment, report, Path(args.evidence) if args.evidence else mp.EVIDENCE_DIR)
    return code or _print_pilot_summary(report)


def cmd_calibration_run(args: argparse.Namespace) -> int:
    """Issue #207: run an APPROVED two- or three-arm (#231) calibration declaration (#204's
    `evals/calibration-204/run-manifest.json`) end to end. Refuses (exit 2),
    before any run directory or container exists, a declaration that is not
    approved or still carries an unrecorded identity, a client argv that
    chooses its own model, a trial image whose pinned client or resolved
    digest is not the declared one, and a subject whose locator or revision
    is not the declared one. Requires `SKILLC_ALLOW_REAL_AGENT=1` and the
    operator's own subscription login (ADR 0005 rule 6). Everything stays in
    a private run directory; only a leak-checked summary is printed. Exits 1
    when any attempt was not observed running the declared model, or none
    was."""
    import secrets
    from datetime import UTC, datetime

    from . import calibration, demo, trial_bootstrap
    from . import calibration_run as cr
    from . import collection_conformance as cc
    from . import matched_pilot as mp

    try:
        declaration = calibration.load_declaration(Path(args.declaration))
        calibration.require_approved(declaration, cr.ROOT)
        model, effort = cr.declared_model(declaration)
        client_name, client_version = cr.declared_client(declaration)
        subject = cr.treatment_subject(declaration)
    except (calibration.DeclarationRefused, cr.CalibrationRefused, OSError, ValueError) as exc:
        print(f"skillc: {exc}", file=sys.stderr)
        return 2
    try:
        client_argv = args.client_argv.split() if args.client_argv else list(cc.DEFAULT_CLIENT_ARGVS[client_name])
        mp.pin_model_argv(model, effort, client_argv)
    except KeyError:
        print(f"skillc: the declared client {client_name!r} has no default invocation; pass --client-argv",
              file=sys.stderr)
        return 2
    except mp.ModelOverrideRefused as exc:
        print(f"skillc: {exc}", file=sys.stderr)
        return 2
    try:
        pinned = trial_bootstrap.pinned_cli_version(client_name)
    except trial_bootstrap.PinnedVersionError as exc:
        print(f"skillc: {exc}", file=sys.stderr)
        return 2
    if pinned != client_version:
        print(f"skillc: the declaration names {client_name} {client_version}, but the trial image pins "
              f"{pinned}; refusing a run of a client other than the declared one", file=sys.stderr)
        return 2
    docker_bin = tuple(args.docker_bin.split()) if args.docker_bin else ("docker",)
    image = args.image or demo.DEFAULT_IMAGE
    declared_digest = cr._shared_str(declaration, "image", "digest")
    image_digest = demo.resolve_image_digest(docker_bin, image, None, args.timeout)
    if image_digest != declared_digest:
        print(f"skillc: image {image!r} resolves to {image_digest or 'nothing'}, but the declaration names "
              f"{declared_digest}; refusing a run on an image other than the declared one", file=sys.stderr)
        return 2

    private_root = Path(args.private_dir).expanduser() if args.private_dir else cr.DEFAULT_PRIVATE_ROOT
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = private_root / f"{stamp}-{secrets.token_hex(3)}"
    run_dir.mkdir(parents=True, mode=0o700)
    print(f"skillc: private run directory: {run_dir}", file=sys.stderr)

    subject_name = str(subject.get("name"))
    try:
        acquired = cc.acquire_collection(subject_name, run_dir)
    except demo.SubjectRefused as exc:
        print(f"skillc: {exc}", file=sys.stderr)
        return 2
    try:
        found = (acquired.subject.locator, acquired.subject.revision, acquired.subject.client)
        wanted = (subject.get("locator"), subject.get("revision"), client_name)
        if found != wanted:
            print(f"skillc: subject {subject_name!r} is (locator, revision, client) {found}, but the "
                  f"declaration names {wanted}; refusing", file=sys.stderr)
            return 2
        treatment = cr.build_treatment(acquired)
    except cr.CalibrationRefused as exc:
        print(f"skillc: {exc}", file=sys.stderr)
        return 2
    finally:
        cc.discard_acquisition(run_dir, subject_name)

    interrupted = False
    try:
        experiment, outcomes = cr.run_calibration(
            declaration, run_dir=run_dir, treatment=treatment, image_digest=image_digest,
            # By the resolved immutable digest, never the tag (pilot-run's rule).
            backends=lambda: cc.agent_backends(
                image=image_digest, base=run_dir, docker_bin=docker_bin, daemon_timeout=args.timeout,
            ),
            argv_for=lambda _scheduled: client_argv,
            credential_explicit_path=Path(args.credential) if args.credential else None,
        )
    except KeyboardInterrupt:
        # The runner already reconciled and persisted every planned attempt.
        print("skillc: interrupted; reporting every planned attempt from the private record", file=sys.stderr)
        interrupted = True
        experiment, outcomes = mp.read_outcomes(run_dir)
    report = cr.build_report(
        experiment, cr.reconcile(experiment, outcomes), declared_model=model, declared_effort=effort,
        named_skills=cr.named_skills_by_arm(declaration),
    )
    (run_dir / cr.REPORT_FILENAME).write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    try:
        demo.print_paste_back(demo.redact_known_host_paths(cr.paste_back(report), base=run_dir))
    except demo.PasteBackRefused as exc:
        print(f"skillc: {exc}", file=sys.stderr)
        return 2
    return 130 if interrupted else _refuse_ineligible(report)


def cmd_uptake_study(args: argparse.Namespace) -> int:
    """Issue #237: run an APPROVED two-arm uptake-study declaration. The
    `published` arm installs the declared subject as acquired; the
    `rewritten` arm installs the `degrade-subject --override-file` snapshot
    at `--rewritten`, which must differ from it in the target SKILL.md's
    description line only (`uptake_study.check_rewritten_files`). Refuses
    (exit 2), before any container exists, an unapproved declaration, a
    client argv that chooses its own model, a client or image other than the
    declared one, a subject other than the declared one, and a rewritten
    snapshot with any other difference. Requires `SKILLC_ALLOW_REAL_AGENT=1`.
    Everything stays in a private run directory; only a leak-checked summary
    is printed. Exits 1 when an attempt did not run the declared model."""
    import secrets
    from datetime import UTC, datetime

    from . import calibration_run as cr
    from . import collection_conformance as cc
    from . import degrade, demo, trial_bootstrap
    from . import matched_pilot as mp
    from . import uptake_study as us

    try:
        declaration = us.load_declaration(Path(args.declaration))
        us.require_approved(declaration, cr.ROOT)
    except (us.StudyRefused, OSError, ValueError) as exc:
        print(f"skillc: {exc}", file=sys.stderr)
        return 2
    model, effort = str(declaration.shared["model"]), str(declaration.shared["reasoning_effort"])
    client = declaration.shared["client"]
    assert isinstance(client, dict)
    client_name, client_version = str(client["name"]), str(client["version"])
    try:
        client_argv = args.client_argv.split() if args.client_argv else list(cc.DEFAULT_CLIENT_ARGVS[client_name])
        mp.pin_model_argv(model, effort, client_argv)
        pinned = trial_bootstrap.pinned_cli_version(client_name)
    except KeyError:
        print(f"skillc: the declared client {client_name!r} has no default invocation; pass --client-argv",
              file=sys.stderr)
        return 2
    except (mp.ModelOverrideRefused, trial_bootstrap.PinnedVersionError) as exc:
        print(f"skillc: {exc}", file=sys.stderr)
        return 2
    if pinned != client_version:
        print(f"skillc: the declaration names {client_name} {client_version}, but the trial image pins {pinned}; "
              "refusing", file=sys.stderr)
        return 2
    docker_bin = tuple(args.docker_bin.split()) if args.docker_bin else ("docker",)
    image = args.image or demo.DEFAULT_IMAGE
    image_field = declaration.shared["image"]
    declared_digest = str(image_field["digest"]) if isinstance(image_field, dict) else ""
    image_digest = demo.resolve_image_digest(docker_bin, image, None, args.timeout)
    if image_digest != declared_digest:
        print(f"skillc: image {image!r} resolves to {image_digest or 'nothing'}, but the declaration names "
              f"{declared_digest}; refusing a run on an image other than the declared one", file=sys.stderr)
        return 2

    private_root = Path(args.private_dir).expanduser() if args.private_dir else us.DEFAULT_PRIVATE_ROOT
    run_dir = private_root / f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(3)}"
    run_dir.mkdir(parents=True, mode=0o700)
    print(f"skillc: private run directory: {run_dir}", file=sys.stderr)

    subject_name = str(declaration.subject.get("name"))
    try:
        published = cc.acquire_collection(subject_name, run_dir)
        rewritten = cc.acquire_degraded_collection(subject_name, Path(args.rewritten))
        for acquired in (published, rewritten):
            found = (acquired.subject.locator, acquired.subject.client)
            wanted = (declaration.subject.get("locator"), client_name)
            if found != wanted:
                print(f"skillc: subject {subject_name!r} is (locator, client) {found}, not the declared {wanted}",
                      file=sys.stderr)
                return 2
        if published.subject.revision != declaration.subject.get("revision"):
            print(f"skillc: the published subject is revision {published.subject.revision!r}, not the declared "
                  f"{declaration.subject.get('revision')!r}; refusing", file=sys.stderr)
            return 2
        treatments = {"published": cr.build_treatment(published), "rewritten": cr.build_treatment(rewritten)}
        us.check_rewritten_files(treatments["published"].home_files, treatments["rewritten"].home_files,
                                 declaration.target_skill, declaration.rewritten_description)
    except (demo.SubjectRefused, degrade.DegradationRefused, cr.CalibrationRefused, us.StudyRefused) as exc:
        print(f"skillc: {exc}", file=sys.stderr)
        return 2
    finally:
        cc.discard_acquisition(run_dir, subject_name)

    interrupted = False
    try:
        experiment, outcomes = us.run_study(
            declaration, run_dir=run_dir, treatments=treatments, image_digest=image_digest, root=cr.ROOT,
            backends=lambda: cc.agent_backends(image=image_digest, base=run_dir, docker_bin=docker_bin,
                                               daemon_timeout=args.timeout),
            argv_for=lambda _scheduled: client_argv,
            credential_explicit_path=Path(args.credential) if args.credential else None,
        )
    except KeyboardInterrupt:
        print("skillc: interrupted; reporting every planned attempt from the private record", file=sys.stderr)
        interrupted = True
        experiment, outcomes = mp.read_outcomes(run_dir)
    report = us.build_report(experiment, us.reconcile(experiment, outcomes), declaration)
    (run_dir / us.REPORT_FILENAME).write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    try:
        demo.print_paste_back(demo.redact_known_host_paths(us.paste_back(report), base=run_dir))
    except demo.PasteBackRefused as exc:
        print(f"skillc: {exc}", file=sys.stderr)
        return 2
    if interrupted:
        return 130
    test = report["primary_test"]
    if isinstance(test, dict) and not test.get("available"):
        # A failed observation instrument is not a completed negative test.
        print(f"skillc: no primary result: {test.get('reason')}", file=sys.stderr)
        return 1
    return _refuse_ineligible(report)


def cmd_configuration_compare(args: argparse.Namespace) -> int:
    """Issue #13's matched-configuration comparison: pure post-hoc analysis
    of two ALREADY-CAPTURED evidence records (`skillc/configuration_compare.py`'s
    own docstring states the input shape) - no agent or docker call of its
    own. Refuses (exit 2) when the two sides are not a matched pair on
    every identity field except `--vary`, naming every mismatch."""
    from .trial import Refused

    try:
        a = configuration_compare.load_record(Path(args.a))
        b = configuration_compare.load_record(Path(args.b))
        result = configuration_compare.compare(a, b, args.vary)
    except Refused as exc:
        print(f"skillc: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=1))
    return 0


def cmd_rules(args: argparse.Namespace) -> int:
    width = max(len(rule.id) for rule in checks.ALL_RULES)
    for rule in checks.ALL_RULES:
        scope = getattr(rule, "target", None)
        # Two SEPARATE claims (issue #132 item 3): `target` says whether a
        # rule runs for a given profile at all; `varies_by_target` says
        # whether a rule that runs for EVERY profile still says something
        # different between them (trigger-shape: target=None, yet its own
        # finding depends on the target it is handed). A `[target: ...]`
        # suffix alone reads the same - empty - for both "does not vary" and
        # "varies but was never declared as scoped", which is exactly what
        # made trigger-shape's own target-dependence invisible here.
        tags = [f"target: {scope}"] if scope else []
        if getattr(rule, "varies_by_target", False):
            tags.append("varies by target")
        suffix = f"  [{', '.join(tags)}]" if tags else ""
        print(f"{rule.severity:5}  {rule.id:{width}}  {rule.summary}{suffix}")
    return 0


def cmd_leak_check(args: argparse.Namespace) -> int:
    """Refuse a tree or a produced bundle that carries a machine identity (#63).

    Three refusal codes, none of them a clean scan:
    - `2`: the path does not exist, OR a `--denylist`/`$SKILLC_LEAK_DENYLIST`
      was configured but does not resolve to a file - a caller error either
      way, never silently read as "no deny-list". Cross-model review: a
      configured-but-missing path used to fall back to zero hostname coverage
      with the SAME message as never configuring one at all, so a typo'd
      `--denylist` path disabled hostname detection without saying so.
    - `3`: the path exists but NOTHING was scanned (every file undecodable, or
      no files at all) - an unscannable target is UNKNOWN, never clean. A scan
      that never opened a file cannot have "found nothing"; it looked at
      nothing (kyle #10 container-lessons, item 59).
    - `1`: a leak was found.
    """
    root = Path(args.path).resolve()
    if not root.exists():
        print(f"skillc: path does not exist: {root}", file=sys.stderr)
        return 2

    configured = args.denylist or os.environ.get(leak.DENYLIST_ENV)
    if configured and not Path(configured).is_file():
        print(f"skillc: configured deny-list not found: {configured}", file=sys.stderr)
        return 2
    denylist = leak.load_denylist(args.denylist)
    result = leak.scan_path(
        root, denylist, exclude=frozenset(args.exclude), host_paths=leak.default_host_paths()
    )
    for finding in result.findings:
        print(finding.render(root))

    if configured:
        plural = "y" if len(denylist) == 1 else "ies"
        print(f"skillc: hostname deny-list: {len(denylist)} entr{plural} from {configured}")
    else:
        print(
            f"skillc: no hostname deny-list configured (--denylist or "
            f"${leak.DENYLIST_ENV}); a hostname not on a list is a class this "
            f"run cannot see",
            file=sys.stderr,
        )
    print(
        f"skillc: {result.scanned} file(s) scanned, {result.skipped} skipped "
        f"(undecodable), {len(result.findings)} leak(s) found"
    )
    if result.scanned == 0:
        print(
            "skillc: nothing was scanned - an unscannable target is UNKNOWN, not clean",
            file=sys.stderr,
        )
        return 3
    return 1 if result.findings else 0


def _parse_remove_file(spec: str) -> tuple[str, str]:
    skill, sep, path = spec.partition(":")
    if not sep or not skill or not path:
        raise ValueError(f"--remove-file wants SKILL:PATH, got {spec!r}")
    return skill, path


def _parse_override_file(spec: str) -> tuple[str, str, str]:
    location, sep, local_path = spec.partition("=")
    if not sep or not local_path:
        raise ValueError(f"--override-file wants SKILL:PATH=LOCAL_FILE, got {spec!r}")
    skill, path = _parse_remove_file(location)
    return skill, path, local_path


def cmd_degrade_subject(args: argparse.Namespace) -> int:
    """Issue #150 acceptance item 2: a degraded CPP subject - the same
    collection with one or more skills or files mutated or removed, in one
    declared mutation - expressible from the operator command line, with its
    identity recorded and never passed off as the subject's real pin.

    Writes `receipt.json` AND `skills/` (the degraded tree itself, so a
    runner has something installable - a receipt describing a tree that was
    then discarded from the disposable staging root could never be run;
    orchestrator review of #155) only on success. A refusal (an unknown
    subject, a malformed `--remove-file`/`--override-file` spec, a mutation
    naming an absent skill or file, or a degradation that would be
    indistinguishable from a normal acquisition) writes nothing and exits 2 -
    the same "no receipt when there is nothing ready to report" contract
    `cmd_materialize` uses."""
    from . import degrade, demo, materialize

    out = Path(args.out).resolve()
    if out.exists() and any(out.iterdir()):
        print(f"skillc: {out} is not empty; refusing to write into it", file=sys.stderr)
        return 2
    base = Path(args.base) if args.base else Path(tempfile.gettempdir())

    try:
        edits = []
        for spec in args.remove_file:
            skill, path = _parse_remove_file(spec)
            edits.append(degrade.FileEdit(skill=skill, path=path, content=None))
        for spec in args.override_file:
            skill, path, local_path = _parse_override_file(spec)
            edits.append(degrade.FileEdit(skill=skill, path=path, content=Path(local_path).read_bytes()))
    except (ValueError, OSError) as exc:
        print(f"skillc: {exc}", file=sys.stderr)
        return 2
    mutation = (
        degrade.Mutation(remove_skills=tuple(args.remove_skill), edits=tuple(edits))
        if args.remove_skill or edits else None
    )

    try:
        subject = demo.load_demo_subject(args.subject)
        degraded = degrade.acquire_degraded(
            args.subject, base, mutation,
            checkout=Path(args.checkout).resolve() if args.checkout else None,
            revision=args.revision,
        )
    except (demo.SubjectRefused, degrade.DegradationRefused, materialize.Refused) as exc:
        print(f"skillc: {exc}", file=sys.stderr)
        return 2

    # `degraded.staging` (issue #199) holds `degraded.source.surface_dir`,
    # which `persist_skills` below still has to read - remove it only once
    # that is done, but on every exit from here, success or not, so a second
    # run against the same --base never finds this run's staging behind it.
    import shutil

    try:
        payload = degrade.receipt(degraded, pinned_revision=subject.revision)
        out.mkdir(parents=True, exist_ok=True)
        (out / "receipt.json").write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
        skills_dir = degrade.persist_skills(degraded, out)
    finally:
        shutil.rmtree(degraded.staging, ignore_errors=True)

    locations = mutation.locations() if mutation is not None else ()
    print(f"subject       {degraded.subject_name}")
    print(f"pinned        {subject.revision}")
    print(f"base          {degraded.base.kind} {degraded.base.revision} {degraded.base.digest}")
    print(f"mutation      {len(locations)} location(s)" if locations else "mutation      none (source override only)")
    for location in locations:
        print(f"  - {location}")
    if degraded.manifest_rewrites:
        print(f"manifests     {len(degraded.manifest_rewrites)} checksum line(s) re-pinned (bookkeeping, #198)")
        for rewrite in degraded.manifest_rewrites:
            print(f"  - {rewrite}")
    print(f"degraded      {degraded.source.kind} {degraded.source.revision} {degraded.source.digest}")
    print(f"\nskillc: degraded subject built - receipt and {skills_dir.name}/ in {out}")
    return 0


def cmd_profile_install(args: argparse.Namespace) -> int:
    """Validate live source, install, then independently check installed files."""
    out = Path(args.out) if args.out else None
    if out is not None and out.exists() and not args.overwrite:
        print(f"skillc: {out} exists; pass --overwrite to replace it", file=sys.stderr)
        return 2
    try:
        prof = profile.Profile.load(Path(args.profile))
        tree = profile.load_tree(prof, Path(args.repo) if args.repo else None,
                                 Path(args.snapshot) if args.snapshot else None)
        inventory = profile.validate(prof, tree)
        receipt = profile.install(inventory, tree, Path(args.home))
        verification = profile.verify_installed(inventory, Path(args.home))
        if any(r["status"] != "satisfied" for r in verification["files"]):
            raise profile.Refused("installed profile verification failed")
        text = json.dumps(receipt, indent=1) + "\n"
        if out is not None:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text, encoding="utf-8")
        else:
            sys.stdout.write(text)
    except (profile.Refused, OSError) as exc:
        print(f"skillc: REFUSED - {exc}", file=sys.stderr)
        return 2
    unavailable = [t["id"] for t in receipt["tools"] if t["status"] != "satisfied"]
    print(f"skillc: profile {prof.name}: {len(receipt['files'])} files installed, "
          f"{len(receipt['tools'])} tools checked; violated/unknown tools: {unavailable}; "
          f"receipt: {out if out is not None else 'stdout'}", file=sys.stderr)
    return 0


def cmd_profile_validate(args: argparse.Namespace) -> int:
    """Validate a transitive installation profile against its pinned source (#265).

    Exit 0 only with a closed inventory; exit 2 on any refusal. Nothing is
    installed: the inventory is a declaration checked against the source, not
    evidence that anything runs.
    """
    try:
        prof = profile.Profile.load(Path(args.profile))
        tree = profile.load_tree(
            prof,
            Path(args.repo) if args.repo else None,
            Path(args.snapshot) if args.snapshot else None,
        )
        inventory = profile.validate(prof, tree)
    except profile.Refused as exc:
        print(f"skillc: REFUSED - {exc}", file=sys.stderr)
        return 2
    text = json.dumps(inventory, indent=1) + "\n"
    if args.out:
        out = Path(args.out)
        if out.exists() and not args.overwrite:
            print(f"skillc: {out} exists; pass --overwrite to replace it", file=sys.stderr)
            return 2
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    deps, unsupported = inventory["dependencies"], inventory["unsupported"]
    selection, subject = inventory["selection"], inventory["subject"]
    assert isinstance(deps, list) and isinstance(unsupported, list)
    assert isinstance(selection, list) and isinstance(subject, dict)
    print(
        f"skillc: profile {prof.name}: {prof.treatment} {prof.treatment_question} treatment, "
        f"{len(selection)} skill(s), {len(deps)} dependencies, {len(unsupported)} unsupported "
        f"reference(s); closed at {subject['revision']}",
        file=sys.stderr,
    )
    print("skillc: nothing was installed; readiness is not established by this inventory",
          file=sys.stderr)
    return 0


def cmd_profile_diagnose(args: argparse.Namespace) -> int:
    """Walk the whole closure and report EVERY problem, attributed to the
    skill(s) whose closure reaches it (issue #295) - a non-certifying
    diagnostic, never a substitute for `profile validate`.

    Exit 0 whenever a diagnostic report was produced, REGARDLESS of
    `problem_count` - a diagnostic is not a verdict, so its exit code must
    not be read as one. `problem_count` is the thing to check, and it is
    printed on its own line precisely so a caller does not have to infer
    cleanliness from the process exit status. Nonzero only when the profile
    or subject declaration itself could not even be loaded (a usage-level
    failure, not a finding this diagnostic exists to report).
    """
    try:
        prof = profile.Profile.load(Path(args.profile))
    except profile.Refused as exc:
        print(f"skillc: REFUSED - {exc}", file=sys.stderr)
        return 2
    tree = profile.load_tree(
        prof,
        Path(args.repo) if args.repo else None,
        Path(args.snapshot) if args.snapshot else None,
    )
    report = profile.diagnose(prof, tree)
    text = json.dumps(report, indent=1) + "\n"
    if args.out:
        out = Path(args.out)
        if out.exists() and not args.overwrite:
            print(f"skillc: {out} exists; pass --overwrite to replace it", file=sys.stderr)
            return 2
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    print(
        f"skillc: profile {prof.name}: diagnostic (NOT a certification) - "
        f"{len(report['selection'])} skill(s) selected, {report['problem_count']} problem(s), "
        f"{len(report['structural'])} structural refusal(s) at {report['revision']}",
        file=sys.stderr,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Separate from `main` so #73's README drift check can introspect the
    real subcommand set (`registered_commands` in `ci/readme_drift.py`)
    instead of a hand-maintained list that could silently fall behind it."""
    parser = argparse.ArgumentParser(
        prog="skillc",
        description="Skills are the new code. Code doesn't ship uncompiled.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}",
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

    p_prof = sub.add_parser(
        "profile",
        help="validate a transitive installation profile against its pinned source",
    )
    prof_sub = p_prof.add_subparsers(dest="profile_command", required=True)
    p_prof_val = prof_sub.add_parser(
        "validate", help="walk the profile's closure and emit its content-addressed inventory",
    )
    p_prof_val.add_argument("profile", help="profile declaration (profile.json)")
    prof_source = p_prof_val.add_mutually_exclusive_group(required=True)
    prof_source.add_argument("--repo", help="git checkout to read the subject's pinned revision from")
    prof_source.add_argument("--snapshot", help="local directory standing in for the source tree")
    p_prof_val.add_argument("--out", help="write the inventory here instead of stdout")
    p_prof_val.add_argument("--overwrite", action="store_true", help="replace an existing --out file")
    p_prof_val.set_defaults(func=cmd_profile_validate)

    p_prof_install = prof_sub.add_parser("install", help="install and verify a validated profile")
    p_prof_install.add_argument("profile", help="profile declaration (profile.json)")
    install_source = p_prof_install.add_mutually_exclusive_group(required=True)
    install_source.add_argument("--repo", help="checkout holding the pinned revision")
    install_source.add_argument("--snapshot", help="local source directory")
    p_prof_install.add_argument("--home", required=True, help="existing disposable home")
    p_prof_install.add_argument("--out", help="write receipt here instead of stdout")
    p_prof_install.add_argument("--overwrite", action="store_true", help="replace existing receipt")
    p_prof_install.set_defaults(func=cmd_profile_install)

    p_prof_diag = prof_sub.add_parser(
        "diagnose",
        help="non-certifying: report EVERY closure problem, per skill, with no truncation (#295)",
    )
    p_prof_diag.add_argument("profile", help="profile declaration (profile.json)")
    diag_source = p_prof_diag.add_mutually_exclusive_group(required=True)
    diag_source.add_argument("--repo", help="git checkout to read the subject's pinned revision from")
    diag_source.add_argument("--snapshot", help="local directory standing in for the source tree")
    p_prof_diag.add_argument("--out", help="write the report here instead of stdout")
    p_prof_diag.add_argument("--overwrite", action="store_true", help="replace an existing --out file")
    p_prof_diag.set_defaults(func=cmd_profile_diagnose)

    p_exp = sub.add_parser(
        "exposure",
        help="measure what actually reaches the model, per client, with no model call",
    )
    p_exp.add_argument("surface", help="exposure surface declaration (extends subject.json)")
    exp_source = p_exp.add_mutually_exclusive_group(required=True)
    exp_source.add_argument("--repo", help="git checkout to read the pinned revision from")
    exp_source.add_argument("--snapshot", help="local directory holding the skills root")
    p_exp.add_argument("--out", required=True, help="directory for report.json")
    p_exp.add_argument(
        "--client", choices=("codex", "claude-code"), default="codex", help="client to measure (default: codex)",
    )
    p_exp.add_argument("--client-bin", help="client executable (default: codex on PATH)")
    p_exp.add_argument("--base", help="where the disposable root is created (default: TMPDIR)")
    p_exp.add_argument("--keep", action="store_true", help="keep the disposable root")
    p_exp.add_argument("--timeout", type=float, default=120, help="per client call, seconds")
    p_exp.set_defaults(func=cmd_exposure)

    p_demo = sub.add_parser(
        "demo",
        help="the operator demo: a real Docker trial lifecycle, end to end (#10 closes on this run)",
    )
    p_demo.add_argument("--image", help="trial image (default: skillc.demo.DEFAULT_IMAGE)")
    p_demo.add_argument("--docker-bin", help="docker executable (repeatable words, space-separated; default: docker)")
    p_demo.add_argument("--base", help="where the disposable root is created (default: TMPDIR)")
    p_demo.add_argument("--timeout", type=float, default=30, help="per-container-call timeout, seconds")
    p_demo.add_argument(
        "--subject", nargs="?", const="", default=None,
        help="install evals/subjects/<name> into a real container's home alongside the lifecycle/grading "
             "demos (issue #101); omit entirely to skip this leg, or give bare with no name for "
             "skillc.demo.DEFAULT_SUBJECT (read from evals/subjects/DEFAULT_SUBJECT)",
    )
    p_demo.add_argument(
        "--control", action="store_true",
        help="run the seeded negative controls instead - exits non-zero unless every one was caught "
             "(only the default task; refused together with --task, see #20)",
    )
    p_demo.add_argument(
        "--task", default=None,
        help="a Level 1 task directory (goal.md, fixture/, grader.json) the grading leg's candidate is "
             "graded against (default: evals/level1/slug-small-fix - behaviour is unchanged without this "
             "flag). Refused together with --control (issue #20 Nit Store): the seeded negative controls "
             "grade a known-bad candidate specific to the default task's own wrong-answer fixtures",
    )
    # Issue #122: the child process `--control`'s cancellation seed runs and
    # interrupts. Not an operator-facing mode, so it is kept out of --help.
    p_demo.add_argument("--cancel-target", type=float, default=None, metavar="SECONDS", help=argparse.SUPPRESS)
    p_demo.set_defaults(func=cmd_demo)

    p_collection_run = sub.add_parser(
        "collection-run",
        help="issue #11's remaining bullet: one real agent attempt on evals/level1/slug-small-fix "
             "per declared skill collection, skill-free canary mode (owed to the operator's live run)",
    )
    p_collection_run.add_argument("subject", help="a name under evals/subjects/<name>/subject.json")
    p_collection_run.add_argument(
        "--task", default=None,
        help="a Level 1 task directory (goal.md, fixture/, grader.json) the agent attempt is graded against "
             "(default: evals/level1/slug-small-fix - behaviour is unchanged without this flag)",
    )
    p_collection_run.add_argument("--image", help="trial image (default: skillc.demo.DEFAULT_IMAGE)")
    p_collection_run.add_argument(
        "--docker-bin", help="docker executable (repeatable words, space-separated; default: docker)",
    )
    p_collection_run.add_argument("--base", help="where the disposable root is created (default: TMPDIR)")
    p_collection_run.add_argument("--timeout", type=float, default=30, help="per-container-call timeout, seconds")
    p_collection_run.add_argument(
        "--agent-timeout", type=float, default=None,
        help="the agent's own wall-clock limit, seconds (default: collection_conformance.DEFAULT_AGENT_TIMEOUT)",
    )
    p_collection_run.add_argument(
        "--credential", help="explicit path to the client credential file (default: the documented standard location)",
    )
    p_collection_run.add_argument(
        "--client-argv", default=None,
        help="the real client invocation, space-separated words (default: "
             "collection_conformance.DEFAULT_CLIENT_ARGVS for the client the subject's surface declares - "
             "codex: the documented no-nested-sandbox mechanism, trial_bootstrap.BWRAP_DECISION, plus "
             "--skip-git-repo-check; claude: -p --dangerously-skip-permissions) - never invented per-run",
    )
    p_collection_run.add_argument(
        "--minimum-credential-seconds", type=float, default=None,
        help="refuse to launch below this remaining credential life "
             "(default: credential.MINIMUM_REMAINING_SECONDS; raise it to run the below-threshold control)",
    )
    p_collection_run.add_argument(
        "--evidence",
        help="issue #150: export the attempt's verified-result(s), plus the bundle a consumer's bundle "
             "rules need, into this LOCAL directory (never a path inside another repository's checkout - "
             "see docs/specs/evaluation-facility/behavioral-eval-export.md); omit to export nothing",
    )
    p_collection_run.add_argument(
        "--evidence-role", choices=("measurement", "control"), default="measurement",
        help="what --evidence is for (default: measurement, a normal subject's export destined for a "
             "consumer's real measurements directory); a degraded-arm export is refused unless this is "
             "'control' - explicit opt-in, e.g. for a one-shot negative control against the consumer gate",
    )
    p_collection_run.add_argument(
        "--evidence-transcript", action="store_true",
        help="issue #202: also publish the attempt's retained transcript into --evidence (as "
             "bundle/transcripts/<attempt>.jsonl). Off by default - a transcript can carry subject content, "
             "so exporting it is a choice made on purpose. The export is refused when no transcript was "
             "retained (none found, or its leak check refused it), and the transcript is leak-checked again "
             "with the rest of the bundle",
    )
    p_collection_run.add_argument(
        "--degraded",
        help="issue #150-B2: install from a persisted degraded subject (a `degrade-subject --out DIR` "
             "directory) instead of SUBJECT's own pinned revision; the digest is re-verified against "
             "its receipt before anything installs, and the run records the degraded identity, never "
             "the pin",
    )
    p_collection_run.set_defaults(func=cmd_collection_run)

    p_selection_probe = sub.add_parser(
        "selection-probe",
        help="issue #26: run the predeclared selection cases (or, with --detection-control, the "
             "predeclared detection control) through a real agent, one attempt per arm",
    )
    p_selection_probe.add_argument(
        "--detection-control", action="store_true",
        help="run evals/selection-probe/detection-control.json instead: the canary names the skill, "
             "so the result shows detection works - it is never a selection result",
    )
    p_selection_probe.add_argument(
        "--task", default=None,
        help="a Level 1 task directory (goal.md, fixture/, grader.json) each attempt is graded against "
             "(default: evals/level1/slug-small-fix - behaviour is unchanged without this flag)",
    )
    p_selection_probe.add_argument("--image", help="trial image (default: skillc.demo.DEFAULT_IMAGE)")
    p_selection_probe.add_argument(
        "--docker-bin", help="docker executable (repeatable words, space-separated; default: docker)",
    )
    p_selection_probe.add_argument("--base", help="where the disposable root is created (default: TMPDIR)")
    p_selection_probe.add_argument("--timeout", type=float, default=30, help="per-container-call timeout, seconds")
    p_selection_probe.add_argument(
        "--agent-timeout", type=float, default=None,
        help="each agent's own wall-clock limit, seconds (default: collection_conformance.DEFAULT_AGENT_TIMEOUT)",
    )
    p_selection_probe.add_argument(
        "--credential", help="explicit path to the client credential file (default: the documented standard location)",
    )
    p_selection_probe.add_argument(
        "--client-argv", default=None,
        help="the real client invocation, space-separated words (default: "
             "collection_conformance.DEFAULT_CLIENT_ARGVS for the subject's client)",
    )
    p_selection_probe.add_argument(
        "--minimum-credential-seconds", type=float, default=None,
        help="refuse to launch below this remaining credential life (default: credential.MINIMUM_REMAINING_SECONDS)",
    )
    p_selection_probe.set_defaults(func=cmd_selection_probe)

    p_calibration_run = sub.add_parser(
        "calibration-run",
        help="issue #207: run an APPROVED two- or three-arm calibration declaration (e.g. "
             "evals/calibration-204/run-manifest.json); evidence stays private, a leak-checked summary is "
             "printed (a real agent run, behind SKILLC_ALLOW_REAL_AGENT=1)",
    )
    p_calibration_run.add_argument("declaration", help="the calibration-declaration JSON to run")
    p_calibration_run.add_argument("--image", help="trial image (default: skillc.demo.DEFAULT_IMAGE)")
    p_calibration_run.add_argument("--docker-bin", help="docker executable (space-separated words; default: docker)")
    p_calibration_run.add_argument("--timeout", type=float, default=30, help="per-container-call timeout, seconds")
    p_calibration_run.add_argument("--credential", help="explicit path to the client credential file")
    p_calibration_run.add_argument(
        "--client-argv", default=None,
        help="the client invocation, space-separated words, WITHOUT a model or effort (the declared ones are "
             "added; default: collection_conformance.DEFAULT_CLIENT_ARGVS for the declared client)",
    )
    p_calibration_run.add_argument(
        "--private-dir",
        help="where the private run directory is created (default: ~/.local/share/skillc/calibration-runs)",
    )
    p_calibration_run.set_defaults(func=cmd_calibration_run)

    p_uptake = sub.add_parser(
        "uptake-study",
        help="issue #237: run an APPROVED two-arm uptake-study declaration (published vs a rewritten "
             "description); evidence stays private, a leak-checked summary is printed (a real agent run, "
             "behind SKILLC_ALLOW_REAL_AGENT=1)",
    )
    p_uptake.add_argument("declaration", help="the uptake-study declaration JSON to run")
    p_uptake.add_argument("--rewritten", required=True,
                          help="a degrade-subject --out directory: the subject with only the target's "
                               "description overridden")
    p_uptake.add_argument("--image", help="trial image (default: skillc.demo.DEFAULT_IMAGE)")
    p_uptake.add_argument("--docker-bin", help="docker executable (space-separated words; default: docker)")
    p_uptake.add_argument("--timeout", type=float, default=30, help="per-container-call timeout, seconds")
    p_uptake.add_argument("--credential", help="explicit path to the client credential file")
    p_uptake.add_argument("--client-argv", help="the client invocation, space-separated words, WITHOUT a model "
                                                "or effort (the declared ones are added)")
    p_uptake.add_argument("--private-dir", help="where the private run directory is created "
                                                "(default: ~/.local/share/skillc/uptake-runs)")
    p_uptake.set_defaults(func=cmd_uptake_study)

    p_pilot_run = sub.add_parser(
        "pilot-run",
        help="issue #12: run the predeclared matched pilot (the current declaration, "
             "evals/matched-pilot/run-manifest-2026-09-27-gpt-6-astra.json) and "
             "export its leak-checked evidence report (a real agent run, behind SKILLC_ALLOW_REAL_AGENT=1)",
    )
    p_pilot_run.add_argument("--manifest", help="run manifest (default: matched_pilot.CURRENT_MANIFEST_PATH)")
    p_pilot_run.add_argument("--image", help="trial image (default: skillc.demo.DEFAULT_IMAGE)")
    p_pilot_run.add_argument("--docker-bin", help="docker executable (space-separated words; default: docker)")
    p_pilot_run.add_argument("--timeout", type=float, default=30, help="per-container-call timeout, seconds")
    p_pilot_run.add_argument("--credential", help="explicit path to the client credential file")
    p_pilot_run.add_argument(
        "--client-argv", default=None,
        help="the real client invocation (default: collection_conformance.DEFAULT_CLIENT_ARGV); the declared "
             "model and effort are appended, and an argv that sets either itself is refused",
    )
    p_pilot_run.add_argument(
        "--private-dir", help="where the private run directory is created (default: ~/.local/share/skillc/pilot-runs)",
    )
    p_pilot_run.add_argument("--evidence", help="where the committed bundle is exported (default: evals/matched-pilot/evidence/records)")
    p_pilot_run.set_defaults(func=cmd_pilot_run)

    p_pilot_report = sub.add_parser(
        "pilot-report",
        help="rebuild a pilot run's evidence report from its private run directory, merging a reviewed claims file",
    )
    p_pilot_report.add_argument("run_dir", help="the private run directory pilot-run printed")
    p_pilot_report.add_argument("--claims", help='JSON {"claims": {attempt_id: claimed-success|claimed-failure|no-claim}}')
    p_pilot_report.add_argument(
        "--manifest",
        help="run manifest (default: the declaration the run recorded; required for a run from before #141)",
    )
    p_pilot_report.add_argument("--evidence", help="where the bundle is exported (default: evals/matched-pilot/evidence/records)")
    p_pilot_report.set_defaults(func=cmd_pilot_report)

    p_config_compare = sub.add_parser(
        "configuration-compare",
        help="issue #13: compare two already-captured evidence records, refusing an unmatched-configuration pair",
    )
    p_config_compare.add_argument("--a", required=True, help="first side's evidence record (JSON)")
    p_config_compare.add_argument("--b", required=True, help="second side's evidence record (JSON)")
    p_config_compare.add_argument(
        "--vary", required=True, choices=list(configuration_compare.IDENTITY_FIELDS),
        help="the one identity field allowed to differ between --a and --b; every other one must match",
    )
    p_config_compare.set_defaults(func=cmd_configuration_compare)

    p_rules = sub.add_parser("rules", help="list the rules")
    p_rules.set_defaults(func=cmd_rules)

    p_leak = sub.add_parser(
        "leak-check", help="refuse a tree or bundle that carries a machine identity"
    )
    p_leak.add_argument("path", nargs="?", default=".", help="file, tree, or produced bundle")
    p_leak.add_argument(
        "--denylist", help=f"hostname deny-list file (default: ${leak.DENYLIST_ENV})"
    )
    p_leak.add_argument(
        "--exclude", action="append", default=[],
        help="path prefix, relative to PATH, to skip entirely (repeatable) - "
             "for a directory that exists to contain seeded fake leaks on purpose",
    )
    p_leak.set_defaults(func=cmd_leak_check)

    p_degrade = sub.add_parser(
        "degrade-subject",
        help="build an operator-expressible degraded subject (issue #150): alternate source, optionally with "
             "one or more skills or files mutated or removed",
    )
    p_degrade.add_argument("subject", help="a name under evals/subjects/<name>/subject.json")
    degrade_source = p_degrade.add_mutually_exclusive_group(required=True)
    degrade_source.add_argument("--checkout", help="local directory holding the skills root")
    degrade_source.add_argument(
        "--revision", help="an explicitly supported revision on the subject's own locator, other than its pin",
    )
    p_degrade.add_argument(
        "--remove-skill", metavar="NAME", action="append", default=[],
        help="a declared skill (subject.json's own naming, not its directory) to remove wholesale; "
             "repeatable; omit entirely, with no --remove-file/--override-file either, for a "
             "source-override-only degradation",
    )
    p_degrade.add_argument(
        "--remove-file", metavar="SKILL:PATH", action="append", default=[],
        help="delete one file inside a skill's own directory (PATH relative to it); repeatable",
    )
    p_degrade.add_argument(
        "--override-file", metavar="SKILL:PATH=LOCAL_FILE", action="append", default=[],
        help="replace one file inside a skill's own directory with LOCAL_FILE's content; repeatable",
    )
    p_degrade.add_argument("--out", required=True, help="directory for receipt.json")
    p_degrade.add_argument("--base", help="where the disposable staging root is created (default: TMPDIR)")
    p_degrade.set_defaults(func=cmd_degrade_subject)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
