"""Real Docker acceptance of the pinned offline CPP runtime (#334/#348/#360).

Build the normal profile-runtime image using its external immutable receipt;
validate baseline and treated containers through the real runtime_environment
API without warming uv. Deliver the closure through candidate-user delivery,
then run the actual selected preflight, overlay, shim and controller witness.
The controller's actual bounded per-call bytes feed the real runner classifier.
The baseline gets the same image/policy and no source, skills or prepared venv.

File faults retain #341's exact path/symptom oracle. Runtime faults are planted
only AFTER normal receipt/image/environment and project-writability validation,
BEFORE the first consuming preflight. Each fault has its own typed property
exception; unrelated failures cannot receive XFAIL credit. Every mode tests
the same healthy predicate. A missed fault produces strict XPASS.

Preflight suppresses import diagnostics. A separate fresh attempt repeats the
same declared import, policy and planted fault with stderr retained. That
repeat never establishes the positive cold path. No model is called. Package
networking is disabled; the real image/helper behavior still requires an
explicitly coordinated daemon run. Offline tests establish discrimination and
wiring only, never runtime availability or the historical bridge failure cause.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import pytest

from skillc import agent_trial as at
from skillc import docker_backend as d
from skillc import gate_overlay
from skillc import materialize as m
from skillc import profile as p
from skillc import runtime_supply as rs
from skillc.backend import ExecuteResult, Limits
from skillc.gate_witness import GateWitness

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "profile-cpp-codex-flow-check-ea6dbfa"
PROFILE_JSON = ROOT / "evals" / "subjects" / "cpp-codex-flow-check-ea6dbfa" / "profile.json"
TRIAL_DOCKERFILE_DIR = ROOT / "docker" / "trial"
TINY_PROJECT = ROOT / "tests" / "fixtures" / "cold-install" / "tiny-project"

#: Pure text classifier, pin-agnostic - imported the SAME way
#: `test_profile_install_cold_container_live.py` already does (from the
#: OLDER profile directory, the only one that carries a copy).
_CLASSIFIER_PATH = ROOT / "evals" / "subjects" / "cpp-codex-flow-check" / "gate_path.py"
_classifier_spec = importlib.util.spec_from_file_location("subject_gate_path_334", _CLASSIFIER_PATH)
assert _classifier_spec is not None and _classifier_spec.loader is not None
gate_path: Any = importlib.util.module_from_spec(_classifier_spec)
_classifier_spec.loader.exec_module(gate_path)

IMAGE_TAG = f"skillc-trial-test:334-closure-preflight-{int(time.time())}"

BREAK_MODE = os.environ.get("SKILLC_CLOSURE_PREFLIGHT_LIVE_BREAK", "none")
_VALID_BREAK_MODES = ("none", "missing-closure", "tampered-closure",
                      "empty-runtime-cache", "runtime-cache-permissions", "project-venv-permissions")

if BREAK_MODE not in _VALID_BREAK_MODES:
    raise RuntimeError(f"SKILLC_CLOSURE_PREFLIGHT_LIVE_BREAK={BREAK_MODE!r} must be one of {_VALID_BREAK_MODES}")

#: The one closure-only file both break modes target - part of the
#: `checkout-libraries` dependency (`destination: "Projects/claude-power-
#: pack"`), never a skill-surface file, so breaking it cannot be confused
#: with a skill-delivery defect.
_TARGET_RELPATH = "Projects/claude-power-pack/lib/cicd/__init__.py"
_TAMPERED_BYTES = b"# skillc#334 live-test tamper marker - not the real file\n"

#: The real shim's own source - read from the host file this test does
#: NOT edit, matching `agent_trial._FLOW_CHECK_GATE_SHIM_SOURCE`'s own
#: convention exactly (both read the one tracked file `docker/trial/
#: Dockerfile` stages into the image).
_SHIM_SOURCE = at._FLOW_CHECK_GATE_SHIM_SOURCE.read_bytes()
_HARNESS_ABS = f"{at._FLOW_CHECK_GATE_HARNESS_ROOT}/{at._FLOW_CHECK_GATE_HARNESS_PATH}"
#: `--plan check --evidence flow-check`, never `--check-summary` - the
#: REAL classifier string (`gate_path.REAL`, "running deterministic gate
#: (lib.cicd run --plan") is printed only by the "run" code path
#: (`flow-finish-gate.sh`'s bare/`--plan` invocation, confirmed by
#: reading the fixture script directly), never by `--check-summary`'s
#: own, separate `lib.cicd check --summary` branch - using the wrong one
#: here would make `classify_gate_output` report "unknown" even on a
#: fully correct run, for a reason that has nothing to do with this
#: test's own claim.
_GATE_NAME = "flow-check-plan"
_GATE_ARGV_TAIL = ("--plan", "check", "--evidence", "flow-check")

_DOCKER_BIN_PRESENT = shutil.which("docker") is not None
pytestmark = [
    pytest.mark.real_docker,
    pytest.mark.skipif(
        not _DOCKER_BIN_PRESENT or d.probe_daemon(["docker"]) is None,
        reason="no reachable Docker daemon in this environment (binary "
               + ("present" if _DOCKER_BIN_PRESENT else "absent")
               + ") - this test needs a real daemon for #334's own live-attempt evidence; "
                 "real-daemon execution is owed to the real-Docker runner (#315)",
    ),
]


class _PropertyHeld(Exception):
    """Shared base, never raised directly and never named in an `xfail`
    marker's own `raises=` - see the two subtypes below (issue #341)."""


class _PreflightVerdictPropertyHeld(_PropertyHeld):
    """The supplied closure was refused for the verified targeted reason."""


class _GateReachesRealRunnerPropertyHeld(_PropertyHeld):
    """Once accepted, the gate did not reach the real `lib.cicd` runner."""


#: Which property THIS mode's xfail credits - computed once, at module
#: load, from the single BREAK_MODE this process was invoked with (issue
#: #341: a mode's own marker must name its OWN specific subtype, never
#: the shared base, so a neighbouring property's unrelated failure can
#: never satisfy it).
_MODE_PROPERTY: dict[str, type[_PropertyHeld]] = {
    "missing-closure": _PreflightVerdictPropertyHeld,
    "tampered-closure": _PreflightVerdictPropertyHeld,
}
_EXPECTED_RAISE = _MODE_PROPERTY.get(BREAK_MODE, _PropertyHeld)


def _require(cls: type[_PropertyHeld], condition: bool, message: str) -> None:
    if not condition:
        raise cls(message)


def _build_trial_image(tag: str) -> rs.RuntimeSupply:
    del tag  # Selection is the receipt's immutable ID, never a mutable tag.
    spec = importlib.util.spec_from_file_location("profile_runtime_builder", ROOT / "docker/profile-trial/build.py")
    assert spec is not None and spec.loader is not None
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    with tempfile.TemporaryDirectory(prefix="sk-360-receipt-") as temp:
        receipt = Path(temp) / "receipt.json"
        builder.build_image(ROOT, receipt)
        return rs.RuntimeSupply.from_path(receipt)


_REFUSAL_SYMPTOMS = {
    "missing-closure": "was not read back",
    "tampered-closure": "disagrees with the expected",
}


def _check_preflight(refused: bool, reason: str, *, expected_symptom: str | None) -> None:
    """Validate the refusal's identity before testing the healthy invariant.

    The diagnostic may depend on the planted input; the healthy predicate
    and its exception never do. A missed refusal must reach strict XPASS.
    """
    if refused:
        assert expected_symptom is not None, "intact closure was unexpectedly refused"
        assert reason.startswith(_TARGET_RELPATH + " ") and expected_symptom in reason, (
            "preflight refusal did not identify the targeted path and symptom"
        )
    _require(_PreflightVerdictPropertyHeld, not refused, "preflight did not accept the closure")


def _check_gate_classification(classification: str) -> None:
    _require(
        _GateReachesRealRunnerPropertyHeld, classification == "real-runner",
        f"flow-finish-gate.sh must reach the real lib.cicd runner, not the Makefile fallback or "
        f"something unclassifiable - classified as {classification!r}",
    )


def _closure_inputs() -> tuple[dict[str, bytes], dict[str, str], tuple[dict[str, object], ...], str]:
    """HOST PHASE: the exact derivation `calibration_run._closure_home_
    files` uses, against the committed fixture snapshot - no network, no
    git. Returns `(home_files, verify_home_files, preflight_tools,
    gate_entrypoint)` - `gate_entrypoint` is the profile's own declared
    fact, asserted non-None here since this fixture's own
    profile.json declares one; a profile that declared none would never
    reach the overlay at all, by construction, not by this test's own
    branching."""
    prof = p.Profile.load(PROFILE_JSON)
    tree = p.DirTree(FIXTURE_DIR)
    inventory = p.validate(prof, tree)
    home_files = p.installed_home_files(inventory, tree)
    assert _TARGET_RELPATH in home_files, "fixture bug: the target closure file is not part of this closure"
    verify_home_files = {relpath: m.sha256_bytes(data) for relpath, data in home_files.items()}
    preflight_tools = tuple(dep for dep in inventory["dependencies"] if dep["kind"] == "tool")
    gate_entrypoint = inventory["gate_entrypoint"]
    assert isinstance(gate_entrypoint, str), "fixture bug: this profile must declare a gate_entrypoint"
    return home_files, verify_home_files, preflight_tools, gate_entrypoint


_RUNTIME_MODES = ("empty-runtime-cache", "runtime-cache-permissions", "project-venv-permissions")
_PROJECT = f"{d.CONTAINER_HOME}/Projects/claude-power-pack"
_CACHE = f"{d.CONTAINER_HOME}/.cache/uv"
_OUTPUT_CAP = 1_000_000
_LIVE_LIMITS = Limits(timeout=120.0, max_captured_stdout_bytes=_OUTPUT_CAP)


class _EmptyRuntimeCachePropertyHeld(_PropertyHeld):
    """The selected runtime dependency is unavailable from an empty offline cache."""


class _RuntimeCachePermissionsPropertyHeld(_PropertyHeld):
    """The selected runtime dependency cannot write its cache."""


class _ProjectVenvPermissionsPropertyHeld(_PropertyHeld):
    """The selected runtime dependency cannot create its project-local venv."""


_MODE_PROPERTY.update(zip(_RUNTIME_MODES, (
    _EmptyRuntimeCachePropertyHeld, _RuntimeCachePermissionsPropertyHeld, _ProjectVenvPermissionsPropertyHeld,
), strict=True))
_EXPECTED_RAISE = _MODE_PROPERTY.get(BREAK_MODE, _PropertyHeld)


def _offline_cache_miss(text: str) -> bool:
    """Whether uv's own offline cache-miss diagnostic is present (#360).

    The phrases are uv 0.9.7's actual wording, captured in
    tests/fixtures/uv-offline-cache-miss-0.9.7.txt. uv wraps its diagnostics,
    so a phrase can span a line break; whitespace is collapsed before matching.
    Both clauses are required: a cache miss alone, or disabled network alone,
    names a different failure.
    """
    flat = " ".join(text.split())
    return "Network connectivity is disabled" in flat and "wasn't found in the cache" in flat


def _complete_output(result: ExecuteResult) -> bytes:
    assert result.reason == "exited", "controller call did not complete"
    assert (result.stdout is not None and len(result.stdout) <= _OUTPUT_CAP
            and not result.stdout_truncated and not result.stdout_incomplete
            and not result.stderr_incomplete), "controller output is unavailable or incomplete"
    return result.stdout


def _check_runtime_preflight(refused: bool, reason: str, *, mode: str, diagnostic: str) -> None:
    assert mode in _RUNTIME_MODES
    if refused:
        assert reason.startswith("tool dependency 'tool-pypi-runtime' "), "wrong refused dependency"
        if mode == "empty-runtime-cache":
            assert _offline_cache_miss(diagnostic), (
                "missing specific offline cache diagnostic"
            )
        else:
            target = _CACHE + "/" if mode == "runtime-cache-permissions" else _PROJECT + "/.venv"
            assert "Permission denied" in diagnostic and target in diagnostic, "wrong permission diagnostic"
            if mode == "project-venv-permissions":
                assert re.search(re.escape(target) + r"(?=$|[/\s\x27\x22`:])", diagnostic), "wrong venv path"
    _require(_MODE_PROPERTY[mode], not refused, "preflight did not accept the selected runtime")


# Run the SAME scanner in the baseline and in the committed local SKILL.md
# decoy control. Missing roots, symlinks and walk errors fail rather than
# manufacture an empty population. Only fixed root counts/hits leave the scan.
_BASELINE_SCAN = r'''
import json, os, pathlib, sys
roots = [pathlib.Path(p) for p in sys.argv[1:]]
assert roots and all(p.is_dir() and not p.is_symlink() for p in roots)
hits = []
def fail(error):
    raise error
for root in roots:
    for current, dirs, files in os.walk(root, onerror=fail, followlinks=False):
        # uv's allowed dependency cache contains its own internal symlinks.
        # Scan declared source/skill roots; cache payload is the separately
        # constrained image capability, not an installed CPP surface.
        if pathlib.Path(current) == roots[0] / '.cache' and 'uv' in dirs:
            assert not (pathlib.Path(current) / 'uv').is_symlink(), 'unscanned cache symlink'
            dirs.remove('uv')
        for name in dirs + files:
            path = pathlib.Path(current) / name
            assert not path.is_symlink(), 'unscanned baseline symlink'
            if name in ('SKILL.md', '.venv', 'claude-power-pack', 'flow-finish-gate.sh'):
                hits.append(name)
print(json.dumps(dict(roots=len(roots), hits=hits)))
'''


def _check_baseline_scan(raw: bytes) -> None:
    report = json.loads(raw)
    assert (type(report.get("roots")) is int and report["roots"] > 0
            and report.get("hits") == []), "baseline is not a measured empty surface"


@dataclass(frozen=True)
class _RuntimeBackend(d.DockerBackend):
    fault: str = "none"
    frozen_preflight: bool = False
    gate_outputs: list[ExecuteResult] = field(default_factory=list, repr=False)
    frozen_env: dict[str, str] = field(default_factory=dict, repr=False)

    def runtime_environment(self, handle: object, limits: Limits,
                            verified_files: Mapping[str, str]) -> Mapping[str, str]:
        env = super().runtime_environment(handle, limits, verified_files)
        # The production validator has established normal image/receipt/tool
        # identity and a writable project with no .venv. No uv command ran.
        if verified_files:
            self.frozen_env.clear()
            self.frozen_env.update(env)
            _plant_runtime_fault(self, handle, self.fault)
        return env

    def exec_in_attempt(self, handle: object, argv: Sequence[str], limits: Limits,
                        cancel: Callable[[], bool] | None = None, stdin: bytes | None = None,
                        cwd: str | None = None, env: Mapping[str, str] | None = None,
                        confine_root: str | None = None) -> ExecuteResult:
        if self.frozen_preflight and len(argv) == 3 and argv[:2] == ["sh", "-c"] and at._TOOLS_MARKER in argv[2]:
            assert self.frozen_env and env is None, "cold frozen preflight has no measured environment"
            env = self.frozen_env
        result = super().exec_in_attempt(handle, argv, limits, cancel, stdin, cwd, env, confine_root)
        if argv and argv[0] == _HARNESS_ABS:
            assert not self.gate_outputs, "unexpected repeated controller gate call"
            assert env is not None and dict(env) == self.frozen_env, "witness environment drift"
            _complete_output(result)
            self.gate_outputs.append(result)  # one bounded actual controller result only
        return result


def _plant_runtime_fault(backend: d.DockerBackend, handle: object, mode: str) -> None:
    if mode not in _RUNTIME_MODES:
        assert mode in ("none", "missing-closure", "tampered-closure")
        return
    if mode == "empty-runtime-cache":
        command = ["/usr/bin/python3", "-c", "import shutil,sys; shutil.rmtree(sys.argv[1])", _CACHE]
    elif mode == "runtime-cache-permissions":
        command = ["chmod", "-R", "a-w", _CACHE]
    else:
        command = ["chmod", "a-w", _PROJECT]
    backend.controller_output(handle, command, _LIVE_LIMITS)


def _baseline_acceptance(backend: _RuntimeBackend, supply: rs.RuntimeSupply) -> None:
    handle = backend.prepare("a-360-baseline-" + uuid.uuid4().hex)
    try:
        assert backend.image_id(handle) == supply.image_id
        backend.runtime_environment(handle, _LIVE_LIMITS, {})
        raw = backend.controller_output(handle, ["/usr/bin/python3", "-c", _BASELINE_SCAN,
                                                 d.CONTAINER_HOME, d.CONTAINER_WORKSPACE], _LIVE_LIMITS)
        _check_baseline_scan(raw)
        # These do not run uv or create a project environment.
        backend.controller_output(handle, ["/usr/bin/python3", "-c", "import json,pathlib"], _LIVE_LIMITS)
        missing = backend.exec_in_attempt(handle, ["/usr/bin/python3", "-c",
                                          "import skillc_deliberately_nonexistent_360"], _LIVE_LIMITS)
        _complete_output(missing)
        assert missing.exit_code != 0, "missing-module control unexpectedly imported"
    finally:
        backend.destroy(handle)


_DELIVERY_SCAN = r'''
import json, os, pathlib, stat, sys
project = pathlib.Path(sys.argv[1])
paths = [project.parent, project]
print(json.dumps(dict(candidate=os.getuid(), paths=[
    dict(uid=p.stat().st_uid, gid=p.stat().st_gid, mode=stat.S_IMODE(p.stat().st_mode),
         writable=os.access(p, os.W_OK), symlink=p.is_symlink()) for p in paths],
    venv=(project / '.venv').exists())))
'''


def _check_delivery(raw: bytes) -> None:
    report = json.loads(raw)
    assert report["candidate"] == d.CANDIDATE_UID and report["venv"] is False
    assert len(report["paths"]) == 2
    for item in report["paths"]:
        assert (item["uid"] == d.CANDIDATE_UID and item["gid"] == d.CANDIDATE_GID
                and item["writable"] is True and item["symlink"] is False
                and item["mode"] & 0o700 == 0o700), "delivery parent is not candidate-owned and writable"


def _observe_delivery(backend: d.DockerBackend, handle: object) -> None:
    _check_delivery(backend.controller_output(handle, ["/usr/bin/python3", "-c", _DELIVERY_SCAN, _PROJECT], _LIVE_LIMITS))


def _check_metadata(backend: d.DockerBackend, handle: object, verified: Mapping[str, str]) -> None:
    for name in ("pyproject.toml", "uv.lock"):
        path = "Projects/claude-power-pack/" + name
        digest = verified[path]
        assert m.sha256_bytes(backend.read_home_file(handle, path)) == digest, "runtime metadata changed"


def _environment_controls(backend: _RuntimeBackend) -> None:
    for override, symptom in (({"UV_OFFLINE": ""}, "differs"), ({"UV_OFFLINE": "0"}, "differs"),
                              ({"UV_PROJECT_ENVIRONMENT": d.CONTAINER_HOME + "/dev-venv"}, "external venv")):
        decoy = replace(backend, env=override, trigger_decide=None, fault="none")
        handle = decoy.prepare("a-360-env-control-" + uuid.uuid4().hex)
        try:
            if "UV_PROJECT_ENVIRONMENT" in override:
                # A real external venv exists, but is not the selected CPP
                # project's environment. It cannot satisfy readiness.
                decoy.controller_output(handle, ["uv", "venv", "--python", "/usr/bin/python3",
                                                override["UV_PROJECT_ENVIRONMENT"]], _LIVE_LIMITS)
            with pytest.raises(rs.Refused, match=symptom):
                decoy.runtime_environment(handle, _LIVE_LIMITS, {})
        finally:
            decoy.destroy(handle)


def _import_command(tools: Sequence[Mapping[str, Any]]) -> str:
    dep, = [dep for dep in tools if dep["id"] == "tool-pypi-runtime"]
    probe, = [probe for probe in dep["probes"] if probe["kind"] == "python-import"]
    assert probe["uv_project"] == "Projects/claude-power-pack"
    script = "; ".join(f"import {module}" for module in probe["modules"])
    return (f"PYTHONPATH={shlex.quote(_PROJECT)}:${{PYTHONPATH:-}} "
            f"uv run --offline --locked --project {shlex.quote(_PROJECT)} "
            f"python -c {shlex.quote(script)} 2>&1")


def _generic_offline_control(home_files: Mapping[str, bytes], tools: Sequence[Mapping[str, Any]]) -> None:
    """Observe the generic image's missing offline supply with actual delivery.

    This current generic image plus current delivery path cannot recover the
    historical bridge failure's suppressed stderr or prove its ownership cause.
    """
    tag = "skillc-trial-test:360-generic-" + uuid.uuid4().hex
    try:
        build = subprocess.run(["docker", "build", "--target", "trial", "-t", tag, str(TRIAL_DOCKERFILE_DIR)],
                               capture_output=True, timeout=600, check=False)
        assert build.returncode == 0, "generic image build failed"
        with tempfile.TemporaryDirectory(prefix="sk-360-generic-") as temp:
            backend = d.DockerBackend(image=tag, base_dir=Path(temp), network="none", witness_io=True,
                                      env={"UV_PYTHON": "/usr/bin/python3", "UV_PYTHON_DOWNLOADS": "never"})
            handle = backend.prepare("a-360-generic-" + uuid.uuid4().hex)
            try:
                for path, data in home_files.items():
                    backend.deliver_home_file(handle, path, data)
                _observe_delivery(backend, handle)
                result = backend.exec_in_attempt(handle, ["sh", "-c", _import_command(tools)], _LIVE_LIMITS)
                output = _complete_output(result).decode("utf-8", errors="strict")
                assert result.exit_code not in (None, 0)
                assert _offline_cache_miss(output), (
                    "generic image did not demonstrate the expected offline cache miss"
                )
            finally:
                backend.destroy(handle)
    finally:
        subprocess.run(["docker", "image", "rm", "-f", tag], capture_output=True, check=False)


def _runtime_diagnostic(backend: _RuntimeBackend, home_files: Mapping[str, bytes],
                        verified: Mapping[str, str], tools: Sequence[Mapping[str, Any]]) -> str:
    # Preflight deliberately suppresses import stderr. Repeat only in another
    # fresh attempt, using the actual declared dependency/modules and policy.
    command = _import_command(tools)
    handle = backend.prepare("a-360-diagnostic-" + uuid.uuid4().hex)
    try:
        for path, data in home_files.items():
            backend.deliver_home_file(handle, path, data)
        backend.runtime_environment(handle, _LIVE_LIMITS, verified)
        result = backend.exec_in_attempt(handle, ["sh", "-c", command], _LIVE_LIMITS)
        output = _complete_output(result).decode("utf-8", errors="strict")
        assert result.exit_code not in (None, 0), "diagnostic did not reproduce the refusal"
        return output
    finally:
        backend.destroy(handle)


@pytest.mark.timeout(1800)
@pytest.mark.xfail(
    condition=BREAK_MODE != "none", strict=True, raises=_EXPECTED_RAISE,
    reason=f"SKILLC_CLOSURE_PREFLIGHT_LIVE_BREAK={BREAK_MODE} deliberately breaks one property",
)
def test_a_treated_attempts_closure_is_verified_and_the_gate_reaches_the_real_runner() -> None:
    home_files, verify_home_files, preflight_tools, gate_entrypoint = _closure_inputs()
    subject_abs = f"{d.CONTAINER_HOME}/{gate_entrypoint}"

    # Diagnostic, not the property under test - confirms THIS mode's own
    # input construction did what it means to, via a plain `assert`
    # (never `_require`, so a fixture bug here is an ordinary failure,
    # not credited as a working break).
    if BREAK_MODE == "missing-closure":
        delivered = {k: v for k, v in home_files.items() if k != _TARGET_RELPATH}
        assert _TARGET_RELPATH not in delivered
    elif BREAK_MODE == "tampered-closure":
        delivered = dict(home_files)
        delivered[_TARGET_RELPATH] = _TAMPERED_BYTES
        assert delivered[_TARGET_RELPATH] != home_files[_TARGET_RELPATH]
    else:
        delivered = dict(home_files)

    _generic_offline_control(home_files, preflight_tools)
    supply = _build_trial_image(IMAGE_TAG)
    base = Path(tempfile.mkdtemp(prefix="sk-334-live-base-"))
    trigger_dir = Path(tempfile.mkdtemp(prefix="sk-334-live-trig-"))
    witness_holder: list[GateWitness] = []

    def decide(request: Mapping[str, object]) -> Mapping[str, object]:
        return witness_holder[0].decide(request)

    backend = _RuntimeBackend(
        image=supply.image_id, base_dir=base, network="none",
        runtime_supply=supply, witness_io=True, fault=BREAK_MODE,
        trigger_decide=decide, trigger_socket_dir=trigger_dir,
    )
    try:
        _baseline_acceptance(backend, supply)
        _environment_controls(backend)
        for frozen in (False, True):
            backend = replace(backend, frozen_preflight=frozen, gate_outputs=[], frozen_env={})
            witness_holder.clear()
            handle = backend.prepare("a-360-treated-" + uuid.uuid4().hex)
            try:
                surface = {
                    f"tiny-project/{f.relative_to(TINY_PROJECT).as_posix()}": f
                    for f in TINY_PROJECT.rglob("*") if f.is_file()
                }
                backend.install(handle, surface)

                for relpath, data in delivered.items():
                    backend.deliver_home_file(handle, relpath, data)

                assert backend.image_id(handle) == supply.image_id
                _observe_delivery(backend, handle)
                frozen_env = backend.runtime_environment(handle, _LIVE_LIMITS, verify_home_files)

                refused = False
                refusal_reason = ""
                try:
                    at._preflight_in_container(backend, handle, _LIVE_LIMITS, verify_home_files, preflight_tools)
                    # skillc#334 step 4: the LAST setup step before
                    # the agent starts, using the real two-root signature #342
                    # landed. `gate_entrypoint` is the profile's own EXPLICIT
                    # declared fact (`_TARGET_RELPATH` is a DIFFERENT file; the
                    # break modes never reach this line at all, since the
                    # preflight call above already raised for them) - never
                    # inferred from `verify_home_files`' own membership, matching
                    # `agent_trial`'s own corrected wiring exactly.
                    real_digest = verify_home_files[gate_entrypoint]
                    assert real_digest.startswith("sha256:")
                    gate_overlay.apply_flow_check_gate_overlay(
                        backend, handle,
                        subject_root=d.CONTAINER_HOME,
                        harness_root=at._FLOW_CHECK_GATE_HARNESS_ROOT,
                        subject_path=gate_entrypoint,
                        harness_path=at._FLOW_CHECK_GATE_HARNESS_PATH,
                        expected_real_digest=real_digest[len("sha256:"):],
                        expected_shim_digest=hashlib.sha256(_SHIM_SOURCE).hexdigest(),
                        shim_content=_SHIM_SOURCE,
                    )
                except (at.HomeFileVerificationRefused, gate_overlay.OverlayRefused) as exc:
                    refused = True
                    refusal_reason = str(exc)

                if BREAK_MODE in _RUNTIME_MODES:
                    diagnostic = _runtime_diagnostic(backend, home_files, verify_home_files, preflight_tools) if refused else ""
                    _check_runtime_preflight(refused, refusal_reason, mode=BREAK_MODE, diagnostic=diagnostic)
                else:
                    _check_preflight(refused, refusal_reason, expected_symptom=_REFUSAL_SYMPTOMS.get(BREAK_MODE))

                # Property 2 is only reachable once property 1 holds - #334's own
                # constraint is that a refused attempt never runs at all, so
                # there is no gate run to observe for either break mode. The
                # overlay has replaced the subject path with the real forwarding
                # shim, so the agent's own invocation now goes through a real
                # GateWitness/decide-reply channel rather than running the real
                # script directly.
                witness = GateWitness(
                    declared_gates={_GATE_NAME: (_HARNESS_ABS, *_GATE_ARGV_TAIL)},
                    declared_env={_GATE_NAME: frozen_env}, reply_byte_cap=_OUTPUT_CAP,
                    tree_digest_fn=lambda: "live-conformance-digest",
                    backend=backend, handle=handle, limits=_LIVE_LIMITS,
                    gate_exclusivity=False, exclusivity_basis="#334 live conformance test - no exclusivity claim exercised here",
                    workspace_root=d.CONTAINER_WORKSPACE,
                )
                witness_holder.append(witness)

                gate_argv = " ".join(_GATE_ARGV_TAIL)
                gate = backend.execute(
                    handle,
                    ["bash", "-c", f"cd {d.CONTAINER_WORKSPACE}/tiny-project && exec {subject_abs} {gate_argv}"],
                    _LIVE_LIMITS,
                )
                assert gate.reason == "exited", f"the gate process itself never completed (reason={gate.reason!r})"
                assert (gate.stdout is not None and not gate.stdout_truncated
                        and not gate.stdout_incomplete and not gate.stderr_incomplete), "gate output is unavailable or incomplete"
                assert len(backend.gate_outputs) == 1, "missing actual controller gate call"
                controller = backend.gate_outputs[0]
                output = _complete_output(controller).decode("utf-8", errors="strict")
                assert gate.stdout == controller.stdout and gate.exit_code == controller.exit_code, "shim forwarding differs"
                _check_metadata(backend, handle, verify_home_files)
                classification = gate_path.classify_gate_output(output)
                _check_gate_classification(classification)
            finally:
                backend.destroy(handle)
    finally:
        subprocess.run(["docker", "image", "rm", "-f", supply.image_id], capture_output=True, check=False)
        shutil.rmtree(base)
        shutil.rmtree(trigger_dir)
