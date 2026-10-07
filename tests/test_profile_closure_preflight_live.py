"""The live-Docker conformance test for skillc#334's own acceptance line:
"a deterministic subject running the gate command reaches the real
`lib.cicd` runner... not exit 127" - proved against a REAL daemon, never
the fake `docker` CLI's host-process simulation.

TARGET PROFILE: `evals/subjects/cpp-codex-flow-check-ea6dbfa/` - the same
pin `tests/test_profile_install_cold_container_live.py` (#340/#266) uses,
and the same committed fixture checkout
(`tests/fixtures/profile-cpp-codex-flow-check-ea6dbfa/`), so this file
needs no network to build the closure's own inputs.

TWO PHASES, mirroring #340's own split:

- HOST PHASE (no network): `profile.validate()` +
  `profile.installed_home_files()` against the committed fixture snapshot
  via `DirTree` - the exact closure `agent_trial._preflight_in_container`
  would be asked to verify in a real live attempt.
- CONTAINER PHASE: a REAL container built from `docker/trial` - the
  SAME image every live attempt actually runs in (orchestrator ruling:
  "#334's acceptance line is about production, and a test
  image would let #334 claim something the production path can't do" -
  rejecting a dedicated test image, unlike #340's own `--network none`
  cold-install proof, which deliberately scoped itself to a narrower,
  image-agnostic claim). The closure is delivered via
  `DockerBackend.deliver_home_file`, the SAME seam
  `agent_trial._make_before_execute`'s hook uses, then the REAL,
  unmodified `agent_trial._preflight_in_container` AND
  `agent_trial._make_before_execute`'s own overlay call
  (`gate_overlay.apply_flow_check_gate_overlay`, with the real two-root
  signature #342 landed) are driven directly against the real backend -
  never a re-implementation of either's logic. The `none` mode therefore
  exercises the FULL production order #334 defines: install, verify,
  preflight, overlay, (agent) gate - with the witnessing-fact
  revision described below.

GATE_ENTRYPOINT IS AN EXPLICIT FACT, NEVER INFERRED (the orchestrator's
correction): the profile's own `gate_entrypoint` field - this test's
fixture profile declares `.claude/scripts/flow-finish-gate.sh`, exactly
matching the real `evals/subjects/cpp-codex-flow-check-ea6dbfa/
profile.json` - is what decides whether the overlay runs, never whether
`verify_home_files` happens to carry that path. `_TARGET_RELPATH` (the
break modes' own target) is a DIFFERENT file specifically so breaking it
can never be confused with breaking the entrypoint declaration itself.

ONCE THE OVERLAY HAS RUN, the agent's own gate invocation goes through
the REAL forwarding shim (`docker/trial/flow-check-gate-shim.py`, the
exact staged file, read from this repository's own tracked copy - never
a stand-in, unlike #332's own mechanism-only live test), which only
answers two prescribed invocations (`reference.md`'s Step 2 and Step 5).
This file drives Step 2's invocation (`--plan check --evidence flow-
check`, the ONLY one of the two that runs through `flow-finish-gate.sh`'s
"run" code path and so the only one that can ever print the classifier's
own REAL string - `--check-summary` runs a separate `lib.cicd check
--summary` branch that never prints it, confirmed by reading the fixture
script directly), over a real `GateWitness`/decide-reply channel wired
the same way `test_gate_overlay_live.py` wires it - the controller executes the REAL script
(now moved to the harness root) via `exec_in_attempt()`, and the shim
forwards that real result byte-for-byte. `gate_path.classify_gate_
output` is then asked of THAT forwarded result, not of a directly-run
script - proving the closure, the preflight, the overlay and the
witness all compose correctly, together, end to end.

#343 LANDED FIRST, AS SEQUENCED: before it merged, `docker/trial/Dockerfile`
had no `uv` and no `make`, so the `none` mode's preflight would have
refused - correctly, since the tool probes genuinely failed, which was
this file's own evidence that they were not a blind instrument. Now that
#343 has landed (pinning both), `none` is expected to be accepted and
reach the real runner - but this has not yet been exercised against a
real Docker daemon (this environment has none); that run is still owed
to the #315 real-Docker VM runner.

TWO INDEPENDENT PROPERTIES, each with its own `_PropertyHeld` subtype
from the start (issue #341's design, not retrofitted): a break targeting
one property must never be satisfiable by a neighbouring property's
unrelated failure.

- `_PreflightVerdictPropertyHeld`: the install→verify→overlay pipeline's
  accept/refuse decision is correct for the closure it was actually
  given - both `agent_trial.HomeFileVerificationRefused` (preflight) and
  `gate_overlay.OverlayRefused` (the overlay's own independent digest
  re-check) are the SAME property from this test's outside view: "could
  the attempt proceed to running the agent at all". The INPUT varies by
  mode (a complete closure for `none`; one file omitted for `missing-
  closure`; one file's bytes corrupted for `tampered-closure`) - for
  `none` the check stays the plain "no refusal", matching #340's own
  `mounts == []`/`sync.returncode == 0` shape. For the two break modes
  the check additionally requires the refusal to NAME `_TARGET_RELPATH`
  and its own documented symptom ("was not read back" / "disagrees with
  the expected") - counter-model review (codex `gpt-6.1-sol`) caught
  that a bare "was it refused at all" check cannot tell this mode's own
  targeted file check firing apart from an UNRELATED refusal (e.g.
  today's own missing-uv/make tool failure, pending #343) - exactly the
  "a neighbour changed" collapse #341's design exists to rule out. This
  still never branches to expect a different BOOLEAN outcome from the
  input construction above; it tightens what counts as "the refusal" to
  the one each mode's own input actually targets, which
  `xfail(strict=True, raises=_PreflightVerdictPropertyHeld)` then
  credits as the mode's own evidence.
- `_GateReachesRealRunnerPropertyHeld`: once the pipeline accepts the
  closure and applies the overlay, invoking the shim through a real
  `GateWitness` reaches the real `lib.cicd` runner
  (`gate_path.classify_gate_output`), not the Makefile fallback. Only
  reachable when property 1 held - #334's own constraint ("the attempt
  is refused before any spend; it never runs with a partial closure")
  means there is no gate run to observe once refused, so `missing-
  closure`/`tampered-closure` never exercise this property at all, and
  their `xfail` is wired to the OTHER subtype only.

    none              (default) the full intact run: complete closure,
                       preflight accepts, gate reaches the real runner.
    missing-closure    one closure-only file (`lib/cicd/__init__.py`,
                       part of the `checkout-libraries` dependency) is
                       never delivered at all - #334's own first named
                       red case ("a profile whose closure is not
                       installed gives a refused attempt").
    tampered-closure   the same file is delivered, but with different
                        bytes than `verify_home_files` expects - #334's
                       own second named red case ("a closure that does
                       not match the bound inventory gives a refused
                       attempt").

Every container and image this file builds is removed in a `finally`.
Built under a DISTINCT tag, matching `test_trial_image_build_live.py`'s
own convention - never `:latest`.

SKIPPED, NOT FAILED, when no Docker daemon is reachable - same
`probe_daemon` pattern every other live test in this repository uses.
Written and reviewed WITHOUT EVER RUNNING IT against a real daemon - no
`docker` binary at all in the implementation environment, confirmed and
reported, matching every other live test in this repository. Real-daemon
execution, including confirming the documented `none`-mode refusal and
the two XFAILs, is owed to the operator's real-Docker runner (#315).

LEAK SAFETY: no host path or raw container name is ever printed into an
assertion message; every assertion compares in-memory booleans, digests,
or the classifier's own fixed string return values.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from skillc import agent_trial as at
from skillc import docker_backend as d
from skillc import gate_overlay
from skillc import materialize as m
from skillc import profile as p
from skillc.backend import Limits
from skillc.gate_witness import GateWitness, _read_observations

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
_VALID_BREAK_MODES = ("none", "missing-closure", "tampered-closure")

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
    """The preflight's accept/refuse decision was wrong for the closure it
    was actually given."""


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


def _build_trial_image(tag: str) -> None:
    # Explicit `--target trial`, not relying on it being the last-declared
    # (default) stage: docker/trial/Dockerfile now has three stages (base,
    # no-uv, trial - #343), and this test's claim is specifically about the
    # production `trial` stage, not about whichever stage happens to be last.
    build = subprocess.run(
        ["docker", "build", "--target", "trial", "-t", tag, str(TRIAL_DOCKERFILE_DIR)],
        capture_output=True, text=True, timeout=600, check=False,
    )
    assert build.returncode == 0, f"trial image build failed: {build.stderr}"


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

    _build_trial_image(IMAGE_TAG)
    base = Path(tempfile.mkdtemp(prefix="sk-334-live-base-"))
    trigger_dir = Path(tempfile.mkdtemp(prefix="sk-334-live-trig-"))
    witness_holder: list[GateWitness] = []

    def decide(request: Mapping[str, object]) -> Mapping[str, object]:
        return witness_holder[0].decide(request)

    backend = d.DockerBackend(
        image=IMAGE_TAG, base_dir=base, network="bridge",
        trigger_decide=decide, trigger_socket_dir=trigger_dir,
    )
    handle = backend.prepare("a-334-closure-preflight-0000001")
    try:
        surface = {
            f"tiny-project/{f.relative_to(TINY_PROJECT).as_posix()}": f
            for f in TINY_PROJECT.rglob("*") if f.is_file()
        }
        backend.install(handle, surface)

        for relpath, data in delivered.items():
            backend.deliver_home_file(handle, relpath, data)

        refused = False
        refusal_reason = ""
        try:
            at._preflight_in_container(backend, handle, Limits(timeout=120.0), verify_home_files, preflight_tools)
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

        # THE REAL ORACLE for property 1. `none` keeps the plain "not
        # refused" shape (a correct closure is never refused, and the
        # overlay's own independent digest re-check agrees). The two
        # break modes additionally require the refusal to NAME
        # `_TARGET_RELPATH` and its own documented symptom - counter-
        # model review (codex `gpt-6.1-sol`): without this, an UNRELATED
        # refusal (today's own missing-uv/make tool failure pending
        # #343, say) would be wrongly credited as evidence that THIS
        # mode's own targeted file check fired, exactly the "a neighbour
        # changed" failure #341 exists to rule out. This still never
        # branches to expect a different BOOLEAN outcome from the input
        # construction above - it tightens what counts as "the
        # refusal" to the one each mode's own input actually targets.
        if BREAK_MODE == "missing-closure":
            _require(
                _PreflightVerdictPropertyHeld,
                refused and _TARGET_RELPATH in refusal_reason and "was not read back" in refusal_reason,
                f"expected a refusal naming {_TARGET_RELPATH!r} as missing, not: refused={refused} "
                f"reason={refusal_reason!r}",
            )
        elif BREAK_MODE == "tampered-closure":
            _require(
                _PreflightVerdictPropertyHeld,
                refused and _TARGET_RELPATH in refusal_reason and "disagrees with the expected" in refusal_reason,
                f"expected a refusal naming {_TARGET_RELPATH!r} as digest-mismatched, not: refused={refused} "
                f"reason={refusal_reason!r}",
            )
        else:
            _require(_PreflightVerdictPropertyHeld, not refused, f"the attempt was refused: {refusal_reason}")

        # Property 2 is only reachable once property 1 holds - #334's own
        # constraint is that a refused attempt never runs at all, so
        # there is no gate run to observe for either break mode. The
        # overlay has replaced the subject path with the real forwarding
        # shim, so the agent's own invocation now goes through a real
        # GateWitness/decide-reply channel rather than running the real
        # script directly.
        witness = GateWitness(
            declared_gates={_GATE_NAME: (subject_abs, *_GATE_ARGV_TAIL)},
            tree_digest_fn=lambda: "live-conformance-digest",
            backend=backend, handle=handle, limits=Limits(timeout=120.0),
            gate_exclusivity=False, exclusivity_basis="#334 live conformance test - no exclusivity claim exercised here",
            workspace_root=d.CONTAINER_WORKSPACE,
        )
        witness_holder.append(witness)

        gate_argv = " ".join(_GATE_ARGV_TAIL)
        gate = backend.execute(
            handle,
            ["bash", "-c", f"cd {d.CONTAINER_WORKSPACE}/tiny-project && exec {subject_abs} {gate_argv}"],
            Limits(timeout=120.0),
        )
        assert gate.reason == "exited", f"the gate process itself never completed (reason={gate.reason!r})"
        output = _read_observations(backend, handle, cap=1_000_000)
        classification = gate_path.classify_gate_output(output)
        _require(
            _GateReachesRealRunnerPropertyHeld, classification == "real-runner",
            f"flow-finish-gate.sh must reach the real lib.cicd runner, not the Makefile fallback or "
            f"something unclassifiable - classified as {classification!r}",
        )
    finally:
        backend.destroy(handle)
        subprocess.run(["docker", "image", "rm", "-f", IMAGE_TAG], capture_output=True, check=False)
