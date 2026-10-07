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
  SAME image every live attempt actually runs in (orchestrator ruling,
  mailbox 5997: "#334's acceptance line is about production, and a test
  image would let #334 claim something the production path can't do" -
  rejecting a dedicated test image, unlike #340's own `--network none`
  cold-install proof, which deliberately scoped itself to a narrower,
  image-agnostic claim). The closure is delivered via
  `DockerBackend.deliver_home_file`, the SAME seam
  `agent_trial._make_before_execute`'s hook uses, then the REAL,
  unmodified `agent_trial._preflight_in_container` is called directly
  against the real backend - never a re-implementation of its logic.

KNOWN, DOCUMENTED, CURRENT FAILURE (orchestrator ruling, mailbox 5997):
`docker/trial/Dockerfile` has no `uv` and no `make` as of this writing,
so the `none` mode's preflight refuses TODAY, correctly - the tool
probes genuinely fail, which is this file's own evidence that they are
not a blind instrument. skillc#343 adds both, pinned; merge order is
#343 first, then #334, so by the time this file's CI run actually
counts, the image carries what the profile declares. This is not a gap
in this test - it is the test correctly observing a real, already-filed,
already-sequenced gap in a DIFFERENT file.

TWO INDEPENDENT PROPERTIES, each with its own `_PropertyHeld` subtype
from the start (issue #341's design, not retrofitted): a break targeting
one property must never be satisfiable by a neighbouring property's
unrelated failure.

- `_PreflightVerdictPropertyHeld`: the preflight's accept/refuse decision
  is correct for the closure it was actually given. Checked
  UNCONDITIONALLY, identically, in every mode: `_require_preflight(not
  refused, ...)`. The INPUT varies by mode (a complete closure for
  `none`; one file omitted for `missing-closure`; one file's bytes
  corrupted for `tampered-closure`) - never the assertion itself, which
  stays "no refusal" in every mode (counter-model review doctrine,
  matching #340's own `mounts == []`/`sync.returncode == 0` shape): for
  `none` the input is correct, so the assertion naturally holds; for the
  other two the deliberately broken input naturally violates it, which
  `xfail(strict=True, raises=_PreflightVerdictPropertyHeld)` then
  credits as the mode's own evidence.
- `_GateReachesRealRunnerPropertyHeld`: once the preflight accepts the
  closure, running `flow-finish-gate.sh` reaches the real `lib.cicd`
  runner (`gate_path.classify_gate_output`), not the Makefile fallback.
  Only reachable when the preflight did not refuse - #334's own
  constraint ("the attempt is refused before any spend; it never runs
  with a partial closure") means there is no gate run to observe once
  refused, so `missing-closure`/`tampered-closure` never exercise this
  property at all, and their `xfail` is wired to the OTHER subtype only.

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

import importlib.util
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

import pytest

from skillc import agent_trial as at
from skillc import docker_backend as d
from skillc import materialize as m
from skillc import profile as p
from skillc.backend import Limits
from skillc.gate_witness import _read_observations

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
    build = subprocess.run(
        ["docker", "build", "-t", tag, str(TRIAL_DOCKERFILE_DIR)],
        capture_output=True, text=True, timeout=600, check=False,
    )
    assert build.returncode == 0, f"trial image build failed: {build.stderr}"


def _closure_inputs() -> tuple[dict[str, bytes], dict[str, str], tuple[dict[str, object], ...]]:
    """HOST PHASE: the exact derivation `calibration_run._closure_home_
    files` uses, against the committed fixture snapshot - no network, no
    git. Returns `(home_files, verify_home_files, preflight_tools)`."""
    prof = p.Profile.load(PROFILE_JSON)
    tree = p.DirTree(FIXTURE_DIR)
    inventory = p.validate(prof, tree)
    home_files = p.installed_home_files(inventory, tree)
    assert _TARGET_RELPATH in home_files, "fixture bug: the target closure file is not part of this closure"
    verify_home_files = {relpath: m.sha256_bytes(data) for relpath, data in home_files.items()}
    preflight_tools = tuple(dep for dep in inventory["dependencies"] if dep["kind"] == "tool")
    return home_files, verify_home_files, preflight_tools


@pytest.mark.xfail(
    condition=BREAK_MODE != "none", strict=True, raises=_EXPECTED_RAISE,
    reason=f"SKILLC_CLOSURE_PREFLIGHT_LIVE_BREAK={BREAK_MODE} deliberately breaks one property",
)
def test_a_treated_attempts_closure_is_verified_and_the_gate_reaches_the_real_runner() -> None:
    home_files, verify_home_files, preflight_tools = _closure_inputs()

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
    backend = d.DockerBackend(image=IMAGE_TAG, base_dir=base, network="bridge")
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
        except at.HomeFileVerificationRefused as exc:
            refused = True
            refusal_reason = str(exc)

        # THE REAL ORACLE for property 1, asserted UNCONDITIONALLY - the
        # SAME check in every mode. It holds for `none` (a correct
        # closure is never refused) and fails naturally for the other two
        # (a genuinely broken closure IS refused) - never branched to
        # expect a different outcome by mode.
        _require(_PreflightVerdictPropertyHeld, not refused, f"the attempt was refused: {refusal_reason}")

        # Property 2 is only reachable once property 1 holds - #334's own
        # constraint is that a refused attempt never runs at all, so
        # there is no gate run to observe for either break mode.
        gate = backend.execute(
            handle,
            ["bash", "-c", f"cd {d.CONTAINER_WORKSPACE}/tiny-project && exec {d.CONTAINER_HOME}/.claude/scripts/flow-finish-gate.sh"],
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
