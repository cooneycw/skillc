"""The live-Docker conformance test for #332's flow-check gate-witness
shim: proves the shim FORWARDS a real controller-executed result rather
than fabricating one, against a REAL daemon rather than the fake `docker`
CLI's host-process simulation - the same evidence class `test_gate_witness_
live.py` supplies for #269, reused here for the forwarding mechanism.

A STAND-IN script plays the role of the real `flow-finish-gate.sh`
(orchestrator guidance): its claim is about the shim's forwarding, never
about CPP's own gate logic, so a trivial constant-output script would do
for that claim alone - but a constant output cannot
DETECT a dropped cwd or a wrong $HOME, which are exactly the properties
this test exists to catch. The stand-in is therefore made SENSITIVE to
everything the shim must preserve: its own argv, its own `os.getcwd()`,
and a digest of its own `$HOME`, plus an argv-dependent exit code (3 for
`--plan ...`, matching `flow-finish-gate.sh`'s real "warn" exit; 0 for
`--check-summary`). #332's own acceptance item 1 (byte-identity against
the REAL script on `gate-stops-early/discrimination/`) needs the real CPP
checkout installed in a live attempt, which is #334's scope, not this
file's - this test proves the mechanism the real script will later run
through, not CPP's own gate behaviour.

EXPECTED OUTPUT IS COMPUTED, NEVER RE-DERIVED BY RUNNING A SECOND
REFERENCE INSTANCE. The stand-in's output is a fully deterministic
function of (argv, cwd, HOME) all three of which this test already
controls and knows in advance, so the expected string is built directly
from those inputs rather than by executing a second "reference" copy of
the stand-in and diffing against it - a second execution would only add a
second thing that could itself be wrong, not strengthen the claim.

ONE TEST FUNCTION, SKILLC_GATE_SHIM_LIVE_BREAK SELECTS THE MODE - same
shape as `test_gate_witness_live.py`'s own `SKILLC_GATE_WITNESS_LIVE_
BREAK`. `xfail(strict=True)` on every non-`none` mode, `raises=` looked
up per mode: a break that fails to actually break anything surfaces as
XPASS, not a silent pass.

`raises=` a PER-PROPERTY `_PropertyHeld` subtype, not one shared type
(issue #341, counter-model review): an earlier draft of this file gave
BOTH of the two properties below the same single `_PropertyHeld` type -
dedicated and not an `AssertionError` subclass, but still too WIDE
within a single run, since a neighboring property's own failure could
satisfy either mode's marker. Fixed with `_ForwardingPropertyHeld`
(property 1) and `_ChannelFailurePropertyHeld` (property 2), each
asserted via a `_require()` helper that takes WHICH subtype to raise,
UNCONDITIONALLY and IDENTICALLY in every mode - never branched by
`BREAK_MODE` to check "the break occurred" instead of "the real
property held," which would XPASS by construction. Every other check
in this file (the driver process completing, the result marker being
readable) stays a plain `assert` (base `AssertionError`), which no
`_PropertyHeld` subtype's `xfail` marker matches - so an unrelated
infra failure (a Docker flake during a break run) is reported as an
ordinary hard FAILURE, never masked as "the break worked." An earlier
draft of this file used `raises=AssertionError` for everything, which
could not tell infra apart from property at all.

TWO INDEPENDENT PROPERTIES, both forced identically in EVERY mode
(counter-model review): (1) forwarding fidelity - both prescribed
invocations, over a REACHABLE channel, forward byte-identical stdout
and exit code; (2) a genuinely UNREACHABLE channel (`SKILLC_TRIGGER_
SOCKET` pointed at a path that cannot exist, forced in every mode, not
only `exits-zero-on-channel-failure`) must make the shim report exit 125
- never something else. An earlier draft forced the channel-unreachable
condition only inside `exits-zero-on-channel-failure` and compared
against the NORMAL-forwarding expected exit code, so the check could
not tell "the shim's own bug fired" apart from "the forced outage alone
would have failed this comparison regardless" - fixed by making
property (2) its own unconditional check, run identically whether or not
BREAK_MODE targets it, so only that mode's own shim mutation can make it
fail.

    none                        (default) both prescribed invocations
                                 (`--plan check --evidence flow-check` and
                                 `--check-summary`) forward byte-identical
                                 stdout and exit code; the unreachable-
                                 channel check also reports exit 125.
    synthesizes-output          the shim never asks the channel at all -
                                 it fabricates a fixed "ok" line and exits
                                 0 regardless of which gate was invoked.
                                 Caught by property (1).
    drops-cwd                   the shim forwards a FIXED cwd
                                 (`CONTAINER_WORKSPACE`) instead of its own
                                 `os.getcwd()` - still inside the declared
                                 workspace root, so the controller's own
                                 confinement accepts it; only the WRONG
                                 value forwarded is the defect. Caught by
                                 property (1).
    exits-zero-on-channel-failure
                                 every one of the shim's own `return
                                 EXIT_CHANNEL_FAILURE` paths is replaced
                                 with `return 0`. Invisible to property
                                 (1) - the mutation only touches FAILURE
                                 paths, so with a reachable channel this
                                 variant forwards normally - and caught
                                 instead by property (2), which forces the
                                 one condition that exercises it.
    wrong-env                   the shim is untouched; the WITNESS is
                                 constructed with an empty `declared_env`,
                                 so the real exec carries whatever ambient
                                 HOME the container's default exec
                                 environment has, not the declared one.
                                 Caught by property (1).

Every container this file starts is removed in a `finally`.

LEAK SAFETY: matching `test_gate_witness_live.py` - no host `base_dir`
path or raw container name is ever printed into an assertion message;
every assertion compares in-memory strings/integers this file itself
constructed or read back through a known marker file.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Mapping
from pathlib import Path

import pytest

from skillc import docker_backend as d
from skillc.backend import Limits
from skillc.gate_overlay import apply_flow_check_gate_overlay
from skillc.gate_witness import GateWitness
from skillc.verify import SURFACE_EXECUTABLE_KEY

LIVE_TEST_IMAGE = os.environ.get("SKILLC_LIVE_TEST_IMAGE", "python:3.12-slim")
BREAK_MODE = os.environ.get("SKILLC_GATE_SHIM_LIVE_BREAK", "none")
_VALID_BREAK_MODES = ("none", "synthesizes-output", "drops-cwd", "exits-zero-on-channel-failure", "wrong-env")

if BREAK_MODE not in _VALID_BREAK_MODES:
    raise RuntimeError(f"SKILLC_GATE_SHIM_LIVE_BREAK={BREAK_MODE!r} must be one of {_VALID_BREAK_MODES}")

#: Mirrors `docker/trial/flow-check-gate-shim.py`'s own `EXIT_CHANNEL_
#: FAILURE` - duplicated rather than imported, since the shim is a
#: standalone staged script read as bytes (`_REAL_SHIM_SOURCE`), never a
#: package module this test can import.
_SHIM_EXIT_CHANNEL_FAILURE = 125

_DOCKER_BIN_PRESENT = shutil.which("docker") is not None
pytestmark = [
    pytest.mark.real_docker,
    pytest.mark.skipif(
        not _DOCKER_BIN_PRESENT or d.probe_daemon(["docker"]) is None,
        reason="no reachable Docker daemon in this environment (binary "
               + ("present" if _DOCKER_BIN_PRESENT else "absent")
               + ") - this test needs a real daemon for the shim's own owed evidence; "
                 "real-daemon execution is owed to the real-Docker runner (#315)",
    ),
]

#: `reference.md`'s own exact subject path, resolved against `SUBJECT_
#: ROOT` - `CONTAINER_HOME` (#332 follow-up), matching where #334 actually
#: delivers the real script in a live attempt, never `CONTAINER_WORKSPACE`
#: as an earlier draft of this file used. `HARNESS_ROOT` is a SEPARATE,
#: dedicated directory the overlay itself creates root-owned - never under
#: the candidate's home, which would let the subject edit the "real"
#: script the controller later executes (orchestrator review: "a
#: laundering channel").
SUBJECT_PATH = ".claude/scripts/flow-finish-gate.sh"
HARNESS_PATH = "flow-finish-gate.sh"
SUBJECT_ROOT = d.CONTAINER_HOME
HARNESS_ROOT = "/opt/skillc-harness"
SUBJECT_ABS = f"{SUBJECT_ROOT}/{SUBJECT_PATH}"
HARNESS_ABS = f"{HARNESS_ROOT}/{HARNESS_PATH}"
TINY_PROJECT_DIR = f"{d.CONTAINER_WORKSPACE}/tiny-project"

#: The real shim's own source - read from the host file this test does
#: NOT edit, matching `docker/trial/Dockerfile`'s own staged copy byte for
#: byte (this file reads the repository source directly rather than the
#: image's staged copy, since no live container exists yet to export it
#: from - both are the same tracked file).
_REAL_SHIM_SOURCE = (
    Path(__file__).resolve().parent.parent / "docker" / "trial" / "flow-check-gate-shim.py"
).read_bytes()

#: A fixed, non-ambient HOME this test declares for BOTH gates - chosen to
#: be unlike anything a bare `python:3.12-slim` exec would carry by
#: default (typically `/root`), so `wrong-env` cannot coincidentally pass.
_DECLARED_HOME = "/opt/declared-test-home"
#: `/usr/local/bin` is load-bearing (counter-model review finding): the
#: `python:3.12-slim` image installs `python3` there, never in `/usr/bin`
#: or `/bin`, and `exec_in_attempt()`'s env-pinning is a FULL replacement
#: (`env -i`), not an addition - a declared PATH that omits it makes the
#: bare `python3` in every declared gate argv unresolvable, so even the
#: INTACT (`none`) run would fail to launch the gate at all.
_DECLARED_ENV = {"HOME": _DECLARED_HOME, "PATH": "/usr/local/bin:/usr/bin:/bin"}


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _home_digest(home: str) -> str:
    return hashlib.sha256(home.encode("utf-8")).hexdigest()


def _stand_in_real_script() -> bytes:
    """Plays the role of the real, pinned `flow-finish-gate.sh` for this
    test's claim (forwarding fidelity, never CPP's own gate logic -
    orchestrator guidance). Prints exactly what the shim
    must preserve byte-for-byte - its own argv, its own `os.getcwd()`,
    and a digest of its own `$HOME` - then exits 3 for a `--plan` call
    (matching the real script's documented "warn" exit) or 0 for
    `--check-summary`. A stand-in that printed a constant could not
    detect a dropped cwd or a wrong HOME; this one is built specifically
    so that it can."""
    return (
        b"import sys, os, hashlib\n"
        b"print('ARGV:' + ' '.join(sys.argv[1:]))\n"
        b"print('CWD:' + os.getcwd())\n"
        b"print('HOME:' + hashlib.sha256(os.environ.get('HOME', '').encode('utf-8')).hexdigest())\n"
        b"if '--check-summary' in sys.argv:\n"
        b"    print('FLOW_FINISH_GATE: ok')\n"
        b"    sys.exit(0)\n"
        b"else:\n"
        b"    print('FLOW_FINISH_GATE: warn (skipped gates: typecheck)')\n"
        b"    sys.exit(3)\n"
    )


def _expected_output(argv_tail: list[str], home: str) -> str:
    """The stand-in's output is a pure function of (argv, cwd, HOME); this
    builds the expected string directly from those inputs rather than by
    executing a second reference copy of the stand-in (see module
    docstring) - `cwd` is always `TINY_PROJECT_DIR` in this file, since
    every invocation below runs the shim from there."""
    lines = [
        "ARGV:" + " ".join(argv_tail),
        "CWD:" + TINY_PROJECT_DIR,
        "HOME:" + _home_digest(home),
    ]
    if "--check-summary" in argv_tail:
        lines.append("FLOW_FINISH_GATE: ok")
    else:
        lines.append("FLOW_FINISH_GATE: warn (skipped gates: typecheck)")
    return "\n".join(lines) + "\n"


def _expected_exit_code(argv_tail: list[str]) -> int:
    return 0 if "--check-summary" in argv_tail else 3


def _broken_shim_synthesizes_output() -> bytes:
    """Never asks the channel at all - fabricates a fixed "ok" line and
    exits 0 regardless of which gate was invoked, the exact defect #332's
    own `reference.md`-docstring names as never allowed ("the shim never
    formats its own verdict")."""
    return b"import sys\nprint('FLOW_FINISH_GATE: ok')\nsys.exit(0)\n"


def _broken_shim_drops_cwd() -> bytes:
    """Identical to the real shim except the one line that forwards
    `os.getcwd()` is replaced with a FIXED `CONTAINER_WORKSPACE` - still
    inside the declared workspace root (so the controller's own
    confinement check accepts it), but the WRONG value, which only the
    stand-in's own printed CWD line can catch."""
    source = _REAL_SHIM_SOURCE.decode("utf-8")
    broken = source.replace('"cwd": os.getcwd()', f'"cwd": {d.CONTAINER_WORKSPACE!r}')
    assert broken != source, "fixture bug: the os.getcwd() substitution found nothing to replace"
    return broken.encode("utf-8")


def _broken_shim_exits_zero_on_channel_failure() -> bytes:
    """Every one of the real shim's own `return EXIT_CHANNEL_FAILURE`
    paths becomes `return 0` - the driver additionally points
    `SKILLC_TRIGGER_SOCKET` at an unreachable path for this mode so a
    real channel failure is actually forced (see `_driver_script`), never
    merely implied by the substitution alone."""
    source = _REAL_SHIM_SOURCE.decode("utf-8")
    broken = source.replace("return EXIT_CHANNEL_FAILURE", "return 0")
    assert broken != source, "fixture bug: the EXIT_CHANNEL_FAILURE substitution found nothing to replace"
    return broken.encode("utf-8")


def _driver_script(result_path: str, shim_env_override: Mapping[str, str] | None) -> str:
    """Plays the role of the agent invoking the shim exactly as
    `reference.md` prescribes: creates and moves into a tiny project
    directory (never the workspace root itself, so a cwd forwarded
    correctly is distinguishable from one silently defaulted to the
    root), invokes the shim with whatever argv tail this process itself
    received, and writes the shim's own stdout/stderr/exit code back to
    `result_path` as JSON - an atomic temp-write-then-`os.replace`, same
    convention `test_gate_witness_live.py`'s own `_primary_script` uses,
    so a concurrent poll can never observe a half-written file.

    `shim_env_override` is layered onto this driver's OWN ambient
    environment for the shim subprocess only - used by
    `exits-zero-on-channel-failure` to force a real, deterministic
    channel failure by pointing `SKILLC_TRIGGER_SOCKET` somewhere that
    cannot exist; every other mode passes `None` and the shim inherits
    this driver's own environment unchanged, reaching the real trigger
    socket exactly as a genuine agent invocation would."""
    env_lines = (
        "env = dict(os.environ)\n" + "\n".join(f"env[{k!r}] = {v!r}" for k, v in shim_env_override.items()) + "\n"
        if shim_env_override
        else "env = None\n"
    )
    return (
        "import json, os, subprocess, sys\n"
        f"os.makedirs({TINY_PROJECT_DIR!r}, exist_ok=True)\n"
        f"os.chdir({TINY_PROJECT_DIR!r})\n"
        f"{env_lines}"
        "proc = subprocess.run(\n"
        f"    [sys.executable, {SUBJECT_ABS!r}, *sys.argv[1:]],\n"
        "    capture_output=True, text=True, env=env,\n"
        ")\n"
        "payload = json.dumps({'stdout': proc.stdout, 'stderr': proc.stderr, 'exit_code': proc.returncode})\n"
        f"tmp = {result_path!r} + '.tmp'\n"
        "with open(tmp, 'w') as f:\n"
        "    f.write(payload)\n"
        f"os.replace(tmp, {result_path!r})\n"
    )


def _image_available(image: str) -> bool:
    """Bounded, best-effort - matching `test_gate_witness_live.py`'s own
    helper exactly."""
    inspect = subprocess.run(["docker", "image", "inspect", image], capture_output=True, timeout=10, check=False)
    if inspect.returncode == 0:
        return True
    pull = subprocess.run(["docker", "pull", image], capture_output=True, timeout=120, check=False)
    return pull.returncode == 0


def _read_result_via_exec(backend: d.DockerBackend, handle: d._Handle, path: str) -> dict[str, object]:
    """Setup/infra read, not the property under test - a failure here
    (an unreadable marker, malformed JSON) is a plain `AssertionError`,
    which `_PropertyHeld`'s narrower `xfail(raises=...)` below does NOT
    match, so it is reported as an ordinary hard failure rather than
    credited as a working break."""
    proc = subprocess.run(
        [*backend.docker_bin, "exec", "--", handle.name, "cat", path],
        capture_output=True, text=True, timeout=backend.daemon_timeout, check=False,
    )
    assert proc.returncode == 0, f"could not read the driver's own result marker: {proc.stderr!r}"
    result = json.loads(proc.stdout)
    assert isinstance(result, dict)
    return result


class _PropertyHeld(Exception):
    """Shared base for the two property-specific exceptions below (issue
    #341: one subtype per independently-targeted property, so a
    NEIGHBORING property's own failure cannot satisfy a break mode's own
    `xfail(raises=...)` - counter-model review finding: an earlier draft
    of this file gave both properties the same single type). Never
    raised directly."""


class _ForwardingPropertyHeld(_PropertyHeld):
    """Property 1's own targeted property: forwarding fidelity (exit
    code, byte-identical stdout) over a REACHABLE channel. Targeted by
    `synthesizes-output`, `drops-cwd`, and `wrong-env` - three different
    mechanisms, the same targeted check."""


class _ChannelFailurePropertyHeld(_PropertyHeld):
    """Property 2's own targeted property: a genuinely unreachable
    channel reports exit 125, forced identically in every mode.
    `exits-zero-on-channel-failure`'s own target - invisible to property
    1, since that mutation only touches FAILURE paths."""


#: Issue #341: which subtype a given `BREAK_MODE` is expected to raise -
#: looked up by the `xfail` marker below instead of one static type.
#: `.get(BREAK_MODE, _PropertyHeld)` is irrelevant for `none` (the
#: marker's `condition` is `False` there).
_EXPECTED_PROPERTY_EXCEPTION: dict[str, type[Exception]] = {
    "synthesizes-output": _ForwardingPropertyHeld,
    "drops-cwd": _ForwardingPropertyHeld,
    "wrong-env": _ForwardingPropertyHeld,
    "exits-zero-on-channel-failure": _ChannelFailurePropertyHeld,
}


def _require(condition: bool, message: str, exc_type: type[Exception] = _PropertyHeld) -> None:
    """The property under test for the current `BREAK_MODE` - asserted
    UNCONDITIONALLY, the identical check for `none` and every break mode
    alike (never branched by `BREAK_MODE`), so it fails naturally when,
    and only when, a break actually changed the real forwarded result -
    never because the test branched its own expectation. `exc_type`
    names WHICH property this particular check is (issue #341) -
    defaults to the shared base, which no real call site should still be
    using. Confirmed directly, no pytest or Docker needed: `_require(
    True, ...)` returns; `_require(False, ...)` raises `exc_type`, which
    is always a subclass of `_PropertyHeld`, never of `AssertionError`."""
    if not condition:
        raise exc_type(message)


@pytest.mark.xfail(
    condition=BREAK_MODE != "none", strict=True,
    raises=_EXPECTED_PROPERTY_EXCEPTION.get(BREAK_MODE, _PropertyHeld),
    reason=f"SKILLC_GATE_SHIM_LIVE_BREAK={BREAK_MODE} deliberately breaks one forwarding property",
)
def test_the_shim_forwards_the_controllers_real_result_against_a_real_daemon() -> None:
    if not _image_available(LIVE_TEST_IMAGE):
        pytest.skip(f"image {LIVE_TEST_IMAGE!r} is not available locally and could not be pulled")

    base = Path(tempfile.mkdtemp(prefix="sk-go-live-base-"))
    trigger_dir = Path(tempfile.mkdtemp(prefix="sk-go-live-trig-"))
    witness_holder: list[GateWitness] = []

    def tree_digest_fn() -> str:
        return "live-conformance-digest"

    def decide(request: Mapping[str, object]) -> Mapping[str, object]:
        return witness_holder[0].decide(request)

    backend = d.DockerBackend(
        image=LIVE_TEST_IMAGE, base_dir=base, network="none",
        trigger_decide=decide, trigger_socket_dir=trigger_dir,
    )
    handle = backend.prepare("a-go-live-conformance-000000001")
    assert isinstance(handle, d._Handle)
    assert handle.trigger_channel is not None

    # CONTAINER_HOME does not pre-exist on a bare python:3.12-slim (no
    # "candidate" user/home is created outside the real trial image) -
    # created here directly, matching the one explicit setup step a real
    # deployment's own profile-closure delivery (#334) would already have
    # performed before this overlay ever runs.
    mkdir_home = subprocess.run(
        [*backend.docker_bin, "exec", "--", handle.name, "mkdir", "-p", SUBJECT_ROOT],
        capture_output=True, timeout=backend.daemon_timeout, check=False,
    )
    assert mkdir_home.returncode == 0, f"could not create {SUBJECT_ROOT!r}: {mkdir_home.stderr!r}"

    stand_in = _stand_in_real_script()
    backend.install(
        handle, {SUBJECT_PATH: stand_in, SURFACE_EXECUTABLE_KEY: [SUBJECT_PATH]}, root=SUBJECT_ROOT,
    )

    if BREAK_MODE == "synthesizes-output":
        shim_content = _broken_shim_synthesizes_output()
    elif BREAK_MODE == "drops-cwd":
        shim_content = _broken_shim_drops_cwd()
    elif BREAK_MODE == "exits-zero-on-channel-failure":
        shim_content = _broken_shim_exits_zero_on_channel_failure()
    else:
        # `none` and `wrong-env` both run the REAL, unmodified shim -
        # `wrong-env`'s break is entirely on the witness's own
        # `declared_env`, never on the shim itself.
        shim_content = _REAL_SHIM_SOURCE

    try:
        apply_flow_check_gate_overlay(
            backend, handle, subject_path=SUBJECT_PATH, harness_path=HARNESS_PATH,
            expected_real_digest=_digest(stand_in), expected_shim_digest=_digest(shim_content),
            shim_content=shim_content, subject_root=SUBJECT_ROOT, harness_root=HARNESS_ROOT,
        )

        declared_env = {} if BREAK_MODE == "wrong-env" else {
            "flow-check-plan": _DECLARED_ENV, "flow-check-summary": _DECLARED_ENV,
        }
        witness = GateWitness(
            declared_gates={
                "flow-check-plan": (
                    "python3", HARNESS_ABS, "--plan", "check", "--evidence", "flow-check",
                ),
                "flow-check-summary": ("python3", HARNESS_ABS, "--check-summary"),
            },
            tree_digest_fn=tree_digest_fn,
            backend=backend,
            handle=handle,
            limits=Limits(timeout=20.0),
            gate_exclusivity=False,
            exclusivity_basis="live conformance test - no exclusivity claim exercised here",
            declared_env=declared_env,
            workspace_root=d.CONTAINER_WORKSPACE,
        )
        witness_holder.append(witness)

        # Property 1: forwarding fidelity. The channel is always reachable
        # here - `exits-zero-on-channel-failure`'s shim mutation only
        # touches its FAILURE paths, so with a reachable channel it
        # forwards normally, same as the real shim, and is caught instead
        # by the channel-failure property below (counter-model review:
        # forcing the outage here would have made this check indistinguishable
        # from a forced-failure artifact for every mode, never proof the
        # mutation itself mattered).
        for gate, argv_tail, result_name in (
            ("flow-check-plan", ["--plan", "check", "--evidence", "flow-check"], "result-plan.json"),
            ("flow-check-summary", ["--check-summary"], "result-summary.json"),
        ):
            result_path = f"{d.CONTAINER_WORKSPACE}/{result_name}"
            driver_src = _driver_script(result_path, None)
            driver_outcome = backend.execute(
                handle, ["python3", "-c", driver_src, *argv_tail], Limits(timeout=30.0),
            )
            assert driver_outcome.reason == "exited", f"the driver process itself never completed for {gate!r}"

            result = _read_result_via_exec(backend, handle, result_path)
            _require(
                result["exit_code"] == _expected_exit_code(argv_tail),
                f"{gate}: the shim's forwarded exit code did not match the controller's real result",
                _ForwardingPropertyHeld,
            )
            _require(
                result["stdout"] == _expected_output(argv_tail, _DECLARED_HOME),
                f"{gate}: the shim's forwarded stdout was not byte-identical to the controller's real result",
                _ForwardingPropertyHeld,
            )

        # Property 2: a genuinely unreachable channel. Forced UNCONDITIONALLY
        # in every mode, not only `exits-zero-on-channel-failure` (counter-
        # model review) - this is what makes it a discriminator: under every
        # OTHER mode the shim in play (real, or broken in some OTHER way)
        # still reaches this path correctly and must still report
        # `_SHIM_EXIT_CHANNEL_FAILURE`, so only `exits-zero-on-channel-
        # failure`'s own mutation can make this specific check fail.
        channel_failure_result_path = f"{d.CONTAINER_WORKSPACE}/result-channel-failure.json"
        channel_failure_driver_src = _driver_script(
            channel_failure_result_path, {"SKILLC_TRIGGER_SOCKET": "/does/not/exist/trigger.sock"},
        )
        channel_failure_outcome = backend.execute(
            handle,
            ["python3", "-c", channel_failure_driver_src, "--plan", "check", "--evidence", "flow-check"],
            Limits(timeout=30.0),
        )
        assert channel_failure_outcome.reason == "exited", "the driver process itself never completed for the channel-failure check"
        channel_failure_result = _read_result_via_exec(backend, handle, channel_failure_result_path)
        _require(
            channel_failure_result["exit_code"] == _SHIM_EXIT_CHANNEL_FAILURE,
            "a genuinely unreachable channel must make the shim report exit "
            f"{_SHIM_EXIT_CHANNEL_FAILURE}, never something else",
            _ChannelFailurePropertyHeld,
        )
    finally:
        backend.destroy(handle)
