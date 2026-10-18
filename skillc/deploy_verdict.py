"""Read a deploy verification as observations, never as a tool's say-so (#282).

CPP's `lib.cicd verify` compares post-deploy probes with a pre-deploy baseline
and recommends PROCEED, REVIEW or ROLLBACK. These readers turn what one run
actually printed into a verdict the caller can rely on, and say UNKNOWN when
the output does not establish one. A missing observation is never a pass and
never a failure.

- `read_verify(exit_code, stdout)` reads `verify --json`. UNKNOWN when the run
  has no exit status (timed out, never ran), the stdout is not one JSON object,
  the verdict is not one of the three, or the exit code contradicts it (CPP
  exits 1 exactly for ROLLBACK).
- `read_health(exit_code, stdout)` reads `health` in its default text mode.
  At the pin that mode prints "no checks configured" and EXITS 0 for a config
  with no probes (claude-power-pack#1476), so the exit code is never read as
  health: zero probes is `no_probes`, and only a printed `N/N checks passed`
  with N >= 1 is `healthy`.
- `release_identity(served, intended)` compares the release the service says
  it serves with the one the deploy meant to start. CPP's verify has no such
  notion (claude-power-pack#1479), so this is the caller's own check.
- `restart_observed(pid_before, pid_after, after_alive)` reads whether a deploy
  restarted the service from its pid file and /proc, not from the deploy
  script's own report.
- `baseline_order(...)` says whether a baseline was captured before the deploy
  it is compared with. A baseline taken after a bad deploy turns a regression
  into a "pre-existing failure", and CPP cannot tell.

Recommendation is not execution: nothing here acts on a verdict.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime

PROCEED, REVIEW, ROLLBACK, UNKNOWN = "PROCEED", "REVIEW", "ROLLBACK", "UNKNOWN"
_VERDICTS = (PROCEED, REVIEW, ROLLBACK)


@dataclass(frozen=True)
class VerifyReading:
    verdict: str  # PROCEED | REVIEW | ROLLBACK | UNKNOWN
    has_baseline: bool | None = None
    #: "<kind>:<name>" -> CPP's classification (regression, preexisting_failure, ...)
    classes: dict[str, str] = field(default_factory=dict)
    reasons: tuple[str, ...] = ()
    why_unknown: str = ""


def _unknown(why: str) -> VerifyReading:
    return VerifyReading(verdict=UNKNOWN, why_unknown=why)


def read_verify(exit_code: int | None, stdout: str | None) -> VerifyReading:
    if exit_code is None:
        return _unknown("no exit status: the verify run timed out or never ran")
    if not stdout or not stdout.strip():
        return _unknown(f"verify printed nothing (exit {exit_code})")
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        return _unknown(f"verify output is not one JSON document: {exc}")
    if not isinstance(data, dict):
        return _unknown("verify output is not a JSON object")
    raw = data.get("verdict")
    verdict = raw.upper() if isinstance(raw, str) else None
    if verdict not in _VERDICTS:
        return _unknown(f"verify reported no known verdict: {raw!r}")
    if (exit_code == 1) != (verdict == ROLLBACK) or exit_code not in (0, 1):
        return _unknown(f"exit {exit_code} contradicts the verdict {verdict}")
    classes: dict[str, str] = {}
    for diff in data.get("diffs") or []:
        if not isinstance(diff, dict) or not all(isinstance(diff.get(k), str)
                                                 for k in ("kind", "name", "classification")):
            return _unknown(f"verify reported an unreadable probe diff: {diff!r}")
        classes[f"{diff['kind']}:{diff['name']}"] = diff["classification"]
    has_baseline = data.get("has_baseline")
    reasons = data.get("reasons") or []
    return VerifyReading(
        verdict=verdict,
        has_baseline=has_baseline if isinstance(has_baseline, bool) else None,
        classes=classes,
        reasons=tuple(str(r) for r in reasons) if isinstance(reasons, list) else (),
    )


@dataclass(frozen=True)
class HealthReading:
    status: str  # healthy | unhealthy | no_probes | unknown
    passed: int | None = None
    total: int | None = None


_NO_CHECKS = "Health Check: no checks configured"
_SUMMARY = re.compile(r"^Result: Health: (\d+)/(\d+) checks passed\b", re.MULTILINE)


def read_health(exit_code: int | None, stdout: str | None) -> HealthReading:
    if exit_code is None or stdout is None:
        return HealthReading("unknown")
    if _NO_CHECKS in stdout:
        return HealthReading("no_probes", 0, 0)  # whatever the exit code says (#1476)
    found = _SUMMARY.findall(stdout)
    if len(found) != 1:
        return HealthReading("unknown")
    passed, total = int(found[0][0]), int(found[0][1])
    if total == 0:
        return HealthReading("no_probes", 0, 0)
    if passed == total and exit_code == 0:
        return HealthReading("healthy", passed, total)
    if passed < total and exit_code == 1:
        return HealthReading("unhealthy", passed, total)
    return HealthReading("unknown", passed, total)  # the summary and the exit code disagree


def release_identity(served: str | None, intended: str) -> str:
    """matched | mismatched | unknown (nothing readable was served)."""
    if served is None:
        return "unknown"
    return "matched" if served == intended else "mismatched"


def served_release(version_body: str | None) -> str | None:
    """The `release` a /version response names, or None when it names none."""
    try:
        data = json.loads(version_body or "")
    except json.JSONDecodeError:
        return None
    release = data.get("release") if isinstance(data, dict) else None
    return release if isinstance(release, str) and release else None


def restart_observed(pid_before: str | None, pid_after: str | None, after_alive: bool | None) -> str:
    """restarted | skipped | unknown, from the service's pid file and /proc."""
    if not pid_before or not pid_after or after_alive is None:
        return "unknown"
    if pid_before == pid_after:
        return "skipped" if after_alive else "unknown"
    return "restarted" if after_alive else "unknown"


def _captured_epoch(captured_at: str | None) -> float | None:
    try:
        return datetime.strptime(captured_at or "", "%Y-%m-%dT%H:%M:%S%z").timestamp()
    except ValueError:
        return None


def baseline_order(*, baseline_saw_intended: bool | None, pre_deploy_release: str | None, intended: str,
                   baseline_captured_at: str | None, deploy_started: float | None) -> str:
    """before_deploy | after_deploy | unknown.

    Two independent kinds of evidence:
      - the baseline's own release-identity probe: if the INTENDED release was
        already being served when the baseline was captured (and it was not
        already serving before the deploy), the baseline came after;
      - CPP's `captured_at` (whole seconds) against the deploy's start stamp;
        the same second is no evidence either way.
    Any evidence of "after" wins; "before" needs at least one piece and no
    contradiction.
    """
    evidence: list[str] = []
    if baseline_saw_intended is not None and pre_deploy_release is not None and pre_deploy_release != intended:
        evidence.append("after_deploy" if baseline_saw_intended else "before_deploy")
    captured = _captured_epoch(baseline_captured_at)
    if captured is not None and deploy_started is not None:
        if captured + 1 <= deploy_started:
            evidence.append("before_deploy")
        elif captured > deploy_started:
            evidence.append("after_deploy")
    if "after_deploy" in evidence:
        return "after_deploy"
    return "before_deploy" if evidence else "unknown"
