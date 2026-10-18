"""Real Docker acceptance of baseline-aware deploy verification (skillc#282).

#280 proved CPP's local CI/CD profile end to end, including that a healthy
deploy verifies PROCEED and a stopped service ROLLBACK. This file certifies
the part that makes `lib.cicd verify` worth having: the comparison with a
PRE-deploy baseline. In the same cold `--network none` cicd-runtime container
and installed `cpp-codex-cicd-86641e8` closure as #280, a release-aware
loopback service (tests/fixtures/cicd-deploy/) is "deployed" by a fixed
script: stop the old process (bounded wait), point `current` at the release,
start the new one, poll /health (bounded). Each release carries a FIXED fault,
never a timing one, so every verdict is known in advance:

- healthy r1 -> r2: PROCEED; the service restarted and serves r2;
- regression r1 -> r2-calc-wrong: ROLLBACK, `regression` on the calc smoke
  test, while /health still PASSES - a health check alone would have waved
  it through. Afterwards the regressed release is STILL served: verify only
  recommends, nothing rolls back;
- pre-existing failure (metrics-500 in both): REVIEW, `preexisting_failure`;
- recovery r1-calc-wrong -> r2: PROCEED, `recovered`;
- absent baseline: a regressed deploy ROLLBACKs (`new_failure`), a healthy
  one PROCEEDs with has_baseline false, and REVIEWs under require_baseline;
- mismatched release: the restart is skipped, so r1 keeps serving while r2
  was intended. The certified config's release-identity probe (it expects the
  intended release) keeps that from reading PROCEED;
- zero probes in project:init's real shape: the installed closure's own
  `templates/cicd.yml.example` bytes, verbatim (everything commented) and
  uncommented the way the template shows, both configure no probe (CPP#1476):
  `health` prints "no checks configured" and EXITS 0, `verify` says REVIEW,
  and the judge reads `no_probes`, never healthy.

Every verdict is read by `skillc.deploy_verdict` from what the run printed;
UNKNOWN is a failure here, never a pass. Release identity, restart and
baseline order are this test's own observations (pid file, /proc, /version,
the deploy's start stamp), not CPP's. Latency is ignored in both configs
(`on_latency_regression: ignore`): timing in a shared container is not
deterministic. /project:init itself is not run - that needs a model (ADR
0005); the template bytes are what it writes.

KNOWN GAP (claude-power-pack#1479): under a health-only config, CPP's verify
PROCEEDs for a deploy whose new release never started, because its only
identity is the project's git HEAD. `test_known_gap_cpp_1479_verify_proceeds_
on_unrestarted_release` PINS that behaviour after asserting its preconditions;
a CPP fix turns it red by design, for a deliberate update.

BREAK MODES (`SKILLC_CICD_DEPLOY_VERIFY_LIVE_BREAK`, ci/real-docker/break-lib.sh's
`cicdverify:` family). Each plants exactly one input and is strict-xfail on
its own property exception:

    none                   the full run above.
    regression-unprobed    the certified config without the calc smoke test ->
                           the regressed deploy PROCEEDs -> "a regression never
                           PROCEEDs" fails.
    baseline-after-deploy  the regression's baseline is taken AFTER the deploy ->
                           the regression reads as pre-existing (REVIEW) and the
                           judge sees the order -> "a regression ROLLBACKs
                           against a pre-deploy baseline" fails.
    restart-skipped        the healthy deploy's restart is skipped -> "a deploy
                           serves the release it meant to" fails.

SKIPPED, NOT FAILED, without a reachable Docker daemon; real-daemon runs are
the #315 runner's (ci/check_real_docker_ran.py floor).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml
from conftest import LIVE_DOCKER_DAEMON_TIMEOUT
from test_cicd_profile_live import (
    _LIMITS,
    _PROJECT_DIR,
    PROJECT,
    ROOT,
    _closure,
    _host_image_ids,
    _load_builder,
    _locate_block,
    _release_images,
    _sh,
    _skill_line,
)

from skillc import agent_trial as at
from skillc import deploy_verdict as dv
from skillc import docker_backend as d
from skillc import runtime_supply as rs
from skillc.backend import Confirmation

FIXTURE = ROOT / "tests" / "fixtures" / "cicd-deploy"
RELEASE_PROBE = (FIXTURE / "release-probe.cicd.yml").read_text(encoding="utf-8")
HEALTH_ONLY = (FIXTURE / "health-only.cicd.yml").read_text(encoding="utf-8")
TEMPLATE_HOME_PATH = "Projects/claude-power-pack/templates/cicd.yml.example"
CPP_PIN = "86641e817711d8a7746270745a5dfa7cacf04b0c"
CPP_1479 = "https://github.com/cooneycw/claude-power-pack/issues/1479"

BREAK_MODE = os.environ.get("SKILLC_CICD_DEPLOY_VERIFY_LIVE_BREAK", "none")
_VALID_BREAK_MODES = ("none", "regression-unprobed", "baseline-after-deploy", "restart-skipped")
if BREAK_MODE not in _VALID_BREAK_MODES:
    raise RuntimeError(f"SKILLC_CICD_DEPLOY_VERIFY_LIVE_BREAK={BREAK_MODE!r} must be one of {_VALID_BREAK_MODES}")

_DOCKER_BIN_PRESENT = shutil.which("docker") is not None
pytestmark = [
    pytest.mark.real_docker,
    pytest.mark.skipif(
        not _DOCKER_BIN_PRESENT or d.probe_daemon(["docker"]) is None,
        reason="no reachable Docker daemon in this environment (binary "
               + ("present" if _DOCKER_BIN_PRESENT else "absent")
               + ") - real-daemon execution is owed to the real-Docker runner (#315)",
    ),
]

_DEPLOY_DIR = f"{_PROJECT_DIR}/deploy"
_VERSION_URL = "http://127.0.0.1:18080/version"
_CALC_SMOKE = re.compile(r"    - name: calc answers 5\n(?:      .*\n)+")


class _PropertyHeld(Exception):
    """Base for the per-property exceptions; never raised directly."""


class _ServedReleasePropertyHeld(_PropertyHeld):
    """A deploy that restarted the service serves the release it meant to."""


class _RegressionNeverProceedsPropertyHeld(_PropertyHeld):
    """A deploy that broke a probed behaviour never verifies PROCEED."""


class _RegressionRollsBackPropertyHeld(_PropertyHeld):
    """Against a PRE-deploy baseline, a regression is classified `regression` and ROLLBACKs."""


_MODE_PROPERTY: dict[str, type[_PropertyHeld]] = {
    "regression-unprobed": _RegressionNeverProceedsPropertyHeld,
    "baseline-after-deploy": _RegressionRollsBackPropertyHeld,
    "restart-skipped": _ServedReleasePropertyHeld,
}


def _require(cls: type[_PropertyHeld], condition: bool, message: str) -> None:
    if not condition:
        raise cls(message)


# --------------------------------------------------------------------------- #
# The known gap's own instrument (claude-power-pack#1479). Pure, so its red
# cases are committed in tests/test_deploy_verdict.py.
# --------------------------------------------------------------------------- #


class _GapPreconditionFailed(AssertionError):
    """The setup is not the one the known gap is about; its verdict means nothing."""


class GapConfigNotHealthOnly(_GapPreconditionFailed):
    pass


class GapRestartNotSkipped(_GapPreconditionFailed):
    pass


class GapReleaseNotMismatched(_GapPreconditionFailed):
    pass


class KnownGap1479Closed(AssertionError):
    """CPP's verify no longer PROCEEDs on an unrestarted release."""


def is_health_only(config_text: str) -> bool:
    """One health endpoint, on /health, and nothing else that could see the release."""
    health = (yaml.safe_load(config_text) or {}).get("health") or {}
    endpoints = health.get("endpoints") or []
    return ([e.get("url") for e in endpoints] == ["http://127.0.0.1:18080/health"]
            and not health.get("smoke_tests") and not health.get("processes"))


def check_known_gap_1479(config_text: str, restart: str, identity: str, reading: dv.VerifyReading) -> None:
    """Raise unless this observation still shows claude-power-pack#1479.

    Preconditions first, each its own class, so a misconfigured run can never
    pass as "the gap": the config is health-only, the restart was OBSERVED
    skipped, and the served release is OBSERVED to differ from the intended.
    Only then is PROCEED the gap.
    """
    if not is_health_only(config_text):
        raise GapConfigNotHealthOnly("the known-gap config is not health-only; this is not #1479's setup")
    if restart != "skipped":
        raise GapRestartNotSkipped(f"the deploy's restart was observed {restart!r}, not skipped")
    if identity != "mismatched":
        raise GapReleaseNotMismatched(f"the served release is {identity!r}, not mismatched")
    if reading.verdict != dv.PROCEED:
        raise KnownGap1479Closed(
            f"claude-power-pack#1479 gap closed or moved; update deliberately: under a health-only config "
            f"a deploy whose new release never started now verifies {reading.verdict} "
            f"(pinned PROCEED at CPP {CPP_PIN}; {CPP_1479})")


def uncommented_template(text: str) -> str:
    """templates/cicd.yml.example with its Health Checks and Smoke Tests
    examples uncommented, the way a user following the template would -
    pointed at the loopback service. Both keys are ones lib.cicd ignores
    (CPP#1476). Only the FIRST `# health:` block: the template's second one is
    the deploy_verification example, and uncommenting both would repeat the
    `health` key."""
    out, live, seen = [], False, set()
    for line in text.splitlines():
        if line in ("# health:", "# smoke:") and line not in seen:
            seen.add(line)
            live = True
        elif live and not line.startswith("#   "):
            live = False
        out.append(line[2:] if live else line)
    result = "\n".join(out).replace("https://your-app.com", "http://127.0.0.1:18080") + "\n"
    assert "\nhealth:\n" in result and "\nsmoke:\n" in result, "the template's health/smoke examples moved"
    return result


# --------------------------------------------------------------------------- #
# The attempt: one container for the whole module.
# --------------------------------------------------------------------------- #


@dataclass
class _Attempt:
    run: Callable[[str], tuple[int | None, str]]
    cicd: Callable[..., tuple[int | None, str]]  # (skill key, extra args="")
    install_text: Callable[[str, str], None]
    template: str


@dataclass(frozen=True)
class _Outcome:
    reading: dv.VerifyReading
    pre: str | None
    served: str | None
    identity: str
    restart: str
    order: str
    pid_after: str | None


@pytest.fixture(scope="module")
def attempt() -> Iterator[_Attempt]:
    home_files, verify_home_files, tools = _closure()
    locate = _locate_block(home_files)
    lines = {key: _skill_line(home_files, key) for key in ("health", "baseline", "verify")}

    profile_builder = _load_builder("profile_runtime_builder_live_282", "docker/profile-trial/build.py")
    cicd_builder = _load_builder("cicd_runtime_builder_live_282", "docker/cicd-trial/build.py")
    scratch = Path(tempfile.mkdtemp(prefix="sk-282-live-"))
    preexisting = _host_image_ids()
    base_receipt, cicd_receipt = scratch / "base.json", scratch / "cicd.json"
    profile_builder.build_image(ROOT, base_receipt)
    cicd_builder.build_image(base_receipt, cicd_receipt)
    supply = rs.RuntimeSupply.from_path(cicd_receipt)
    rs.require_kind(supply, rs.CICD_RUNTIME)

    surface: dict[str, object] = {
        f"project/{f.relative_to(PROJECT).as_posix()}": f for f in PROJECT.rglob("*") if f.is_file()
    }
    deploy_root = FIXTURE / "deploy"
    surface.update({f"project/deploy/{f.relative_to(deploy_root).as_posix()}": f
                    for f in deploy_root.rglob("*") if f.is_file()})

    backend = d.DockerBackend(image=supply.image_id, base_dir=scratch, network="none", runtime_supply=supply,
                              witness_io=True, daemon_timeout=LIVE_DOCKER_DAEMON_TIMEOUT)
    handle = backend.prepare("a-282-verify-" + uuid.uuid4().hex)
    try:
        backend.install(handle, surface)
        for relpath, data in home_files.items():
            backend.deliver_home_file(handle, relpath, data)
        backend.runtime_environment(handle, _LIMITS, verify_home_files)
        at._preflight_in_container(backend, handle, _LIMITS, verify_home_files, tools)

        def run(script: str) -> tuple[int | None, str]:
            return _sh(backend, handle, f"cd {_PROJECT_DIR}\n{script}")

        def cicd(key: str, extra: str = "") -> tuple[int | None, str]:
            return run(f"{locate}\n{lines[key]}{extra}")

        def install_text(relpath: str, text: str) -> None:
            done = backend.exec_in_attempt(handle, ["bash", "-c", f"cat > {_PROJECT_DIR}/{relpath}"],
                                           _LIMITS, stdin=text.encode())
            assert done.reason == "exited" and done.exit_code == 0, f"could not write {relpath}"

        code, _ = run("chmod 755 deploy/deploy.sh")
        assert code == 0
        yield _Attempt(run=run, cicd=cicd, install_text=install_text,
                       template=home_files[TEMPLATE_HOME_PATH].decode("utf-8"))
    finally:
        backend.destroy(handle)
        absent = backend.confirm_absent(handle)
        built = [supply.image_id, json.loads(base_receipt.read_bytes())["image_id"]]
        _release_images(preexisting, built, lock_held=os.environ.get("SKILLC_REAL_DOCKER_RUN_LOCK_HELD") == "1",
                        remove=lambda image: subprocess.run(["docker", "image", "rm", "-f", image],
                                                            capture_output=True, check=False))
        shutil.rmtree(scratch, ignore_errors=True)
        assert absent is Confirmation.CONFIRMED, f"the attempt container's removal is {absent.name}"


def _served(a: _Attempt) -> str | None:
    _code, out = a.run(f"curl -s --max-time 5 {_VERSION_URL} || true")
    return dv.served_release(out)


def _pid(a: _Attempt) -> tuple[str | None, bool | None]:
    code, out = a.run("pid=$(cat deploy/service.pid 2>/dev/null) || exit 3\n"
                      "echo \"$pid\"; if [ -e /proc/$pid ]; then echo alive; else echo dead; fi")
    if code != 0:
        return None, None
    pid, state = out.split()
    return pid, state == "alive"


def _deploy(a: _Attempt, release: str, *, skip_restart: bool = False) -> None:
    env = "DEPLOY_SKIP_RESTART=1 " if skip_restart else ""
    code, out = a.run(f"{env}deploy/deploy.sh {release}")
    assert code == 0, f"deploy.sh {release} failed (exit {code}): {out}"


def _fresh(a: _Attempt, release: str) -> None:
    """Stop whatever runs, forget the baseline, and start `release` cleanly."""
    code, out = a.run("rm -f .claude/deploy-baseline.json\n"
                      "if [ -f deploy/service.pid ]; then pid=$(cat deploy/service.pid); kill $pid 2>/dev/null\n"
                      "  for _ in $(seq 50); do [ -e /proc/$pid ] || break; sleep 0.1; done\n"
                      "  [ -e /proc/$pid ] && exit 3; rm -f deploy/service.pid; fi")
    assert code == 0, f"the previous service outlived its stop: {out}"
    _deploy(a, release)


def _configure(a: _Attempt, text: str, *, intended: str, require_baseline: bool = False) -> str:
    text = text.replace("@INTENDED@", intended).replace("@REQUIRE_BASELINE@", str(require_baseline).lower())
    a.install_text(".claude/cicd.yml", text)
    return text


def _take_baseline(a: _Attempt) -> dict[str, object]:
    code, out = a.cicd("baseline")
    assert code == 0 and "Saved baseline" in out, f"verify --baseline did not capture: {out}"
    code, out = a.run("cat .claude/deploy-baseline.json")
    assert code == 0, "no baseline file after verify --baseline"
    snapshot: dict[str, object] = json.loads(out)
    return snapshot


def _baseline_saw_intended(snapshot: dict[str, object]) -> bool | None:
    probes = snapshot.get("probes")
    found = [p for p in probes if isinstance(p, dict) and p.get("name") == "release identity"] \
        if isinstance(probes, list) else []
    return bool(found[0].get("passed")) if len(found) == 1 else None


def _scenario(a: _Attempt, *, start: str, deploy_to: str, config: str = RELEASE_PROBE,
              take_baseline: bool = True, baseline_after: bool = False, skip_restart: bool = False,
              require_baseline: bool = False) -> _Outcome:
    _fresh(a, start)
    _configure(a, config, intended=deploy_to, require_baseline=require_baseline)
    pre = _served(a)
    assert pre == start, f"the fresh start serves {pre!r}, not {start!r}"
    snapshot = _take_baseline(a) if take_baseline and not baseline_after else None
    pid_before, _ = _pid(a)
    _deploy(a, deploy_to, skip_restart=skip_restart)
    if take_baseline and baseline_after:
        snapshot = _take_baseline(a)
    pid_after, alive = _pid(a)
    code, out = a.cicd("verify", " --json")
    reading = dv.read_verify(code, out)
    assert reading.verdict != dv.UNKNOWN, f"verify established no verdict: {reading.why_unknown}"
    _code, started = a.run("cat deploy/deploy.started")
    served = _served(a)
    order = "none"
    if snapshot is not None:
        captured = snapshot.get("captured_at")
        order = dv.baseline_order(
            baseline_saw_intended=_baseline_saw_intended(snapshot), pre_deploy_release=pre, intended=deploy_to,
            baseline_captured_at=captured if isinstance(captured, str) else None,
            deploy_started=float(started) if re.fullmatch(r"\d+(\.\d+)?\s*", started) else None)
    return _Outcome(reading=reading, pre=pre, served=served, identity=dv.release_identity(served, deploy_to),
                    restart=dv.restart_observed(pid_before, pid_after, alive), order=order, pid_after=pid_after)


@pytest.mark.timeout(1800)
@pytest.mark.xfail(
    condition=BREAK_MODE != "none", strict=True, raises=_MODE_PROPERTY.get(BREAK_MODE, _PropertyHeld),
    reason=f"SKILLC_CICD_DEPLOY_VERIFY_LIVE_BREAK={BREAK_MODE} deliberately breaks one property",
)
def test_deploy_verification_compares_against_a_pre_deploy_baseline(attempt: _Attempt) -> None:
    a = attempt
    calc, health, release, metrics = ("smoke:calc answers 5", "health:service health",
                                      "health:release identity", "smoke:metrics")

    # Healthy deploy: restarted, serves what it meant to, PROCEED.
    out = _scenario(a, start="r1", deploy_to="r2", skip_restart=BREAK_MODE == "restart-skipped")
    _require(_ServedReleasePropertyHeld, out.restart == "restarted" and out.identity == "matched",
             f"the healthy deploy's restart was {out.restart} and it serves {out.served!r}, not r2")
    assert out.reading.verdict == dv.PROCEED and out.order == "before_deploy", out
    assert out.reading.classes == {health: "ok", release: "recovered", calc: "ok", metrics: "ok"}, out

    # Regression that /health cannot see: ROLLBACK, and nothing executes it.
    regressed_config = RELEASE_PROBE
    if BREAK_MODE == "regression-unprobed":
        regressed_config, removed = _CALC_SMOKE.subn("", RELEASE_PROBE)
        assert removed == 1, "the certified config's calc smoke test moved; update this break mode"
    out = _scenario(a, start="r1", deploy_to="r2-calc-wrong", config=regressed_config,
                    baseline_after=BREAK_MODE == "baseline-after-deploy")
    _require(_RegressionNeverProceedsPropertyHeld, out.reading.verdict != dv.PROCEED,
             f"the regressed deploy verified PROCEED: {out.reading}")
    _require(_RegressionRollsBackPropertyHeld,
             out.order == "before_deploy" and out.reading.verdict == dv.ROLLBACK
             and out.reading.classes.get(calc) == "regression",
             f"baseline {out.order}; verdict {out.reading.verdict}; calc {out.reading.classes.get(calc)!r}")
    assert out.reading.classes.get(health) == "ok", f"/health should still pass on the regression: {out}"
    assert out.served == "r2-calc-wrong" and _pid(a)[0] == out.pid_after, (
        "verify ROLLBACK must only recommend: the regressed release is no longer the one served")

    # Pre-existing failure: REVIEW, not ROLLBACK.
    out = _scenario(a, start="r1-metrics-500", deploy_to="r2-metrics-500")
    assert out.reading.verdict == dv.REVIEW and out.reading.classes.get(metrics) == "preexisting_failure", out

    # Recovery: PROCEED, with the calc probe recovered.
    out = _scenario(a, start="r1-calc-wrong", deploy_to="r2")
    assert out.reading.verdict == dv.PROCEED and out.reading.classes.get(calc) == "recovered", out

    # Absent baseline: absolute pass/fail only, and visibly so.
    out = _scenario(a, start="r1", deploy_to="r2-calc-wrong", take_baseline=False)
    assert out.reading.verdict == dv.ROLLBACK and out.reading.has_baseline is False, out
    assert out.reading.classes.get(calc) == "new_failure", out
    out = _scenario(a, start="r1", deploy_to="r2", take_baseline=False)
    assert out.reading.verdict == dv.PROCEED and out.reading.has_baseline is False, out
    out = _scenario(a, start="r1", deploy_to="r2", take_baseline=False, require_baseline=True)
    assert out.reading.verdict == dv.REVIEW and out.reading.has_baseline is False, out

    # Mismatched release under the certified config: never PROCEED.
    out = _scenario(a, start="r1", deploy_to="r2", skip_restart=True)
    assert out.restart == "skipped" and out.identity == "mismatched" and out.served == "r1", out
    assert out.reading.verdict != dv.PROCEED, f"an unrestarted release verified PROCEED: {out}"
    assert out.reading.classes.get(release) == "preexisting_failure", out

    # project:init's real shape: the installed template, verbatim and uncommented.
    for label, text in (("verbatim", a.template), ("uncommented", uncommented_template(a.template))):
        _fresh(a, "r2")
        a.install_text(".claude/cicd.yml", text)
        code, health_text = a.cicd("health")
        assert code == 0 and dv.read_health(code, health_text).status == "no_probes", (
            f"{label} template: expected CPP#1476's exit-0 'no checks configured', got exit {code}")
        code, baseline_text = a.cicd("baseline")
        assert code == 0 and "(no probes configured" in baseline_text, f"{label} template baseline: {baseline_text}"
        code, verify_json = a.cicd("verify", " --json")
        reading = dv.read_verify(code, verify_json)
        assert reading.verdict == dv.REVIEW and not reading.classes, f"{label} template verify: {reading}"


@pytest.mark.timeout(900)
def test_known_gap_cpp_1479_verify_proceeds_on_unrestarted_release(attempt: _Attempt) -> None:
    """PINNED KNOWN GAP, claude-power-pack#1479, at CPP 86641e817711d8a7746270745a5dfa7cacf04b0c.

    Under a health-only cicd.yml, CPP's verify PROCEEDs for a deploy whose new
    release never started: its only release identity is the project's git
    HEAD (lib/cicd/verify.py:243, 436-450). The preconditions are asserted
    first - health-only, restart observed skipped, served release observed
    mismatched - so this passes only as THAT gap. When CPP fixes #1479 (or the
    pin moves) the verdict changes and this fails on purpose: update it
    deliberately.
    """
    out = _scenario(attempt, start="r1", deploy_to="r2", config=HEALTH_ONLY, skip_restart=True)
    check_known_gap_1479(HEALTH_ONLY, out.restart, out.identity, out.reading)
