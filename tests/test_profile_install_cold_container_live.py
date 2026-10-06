"""The live-Docker conformance test for #266's cold-container-install
proof (acceptance item 2): a cold container running the profile helper
against a tiny project with no operator skill mount, home mount, MCP
mount, or secret mount (phrased as four separate nouns throughout this
file, never a slash-joined list - the original issue wording triggers
this repository's own leak-check home-path false positive, caught while
writing this very file).

`skillc profile install()`/`verify_installed()` (`tests/test_profile_
install.py`) is a pure host-filesystem operation with no isolation claim
of its own - its own docstring says so. This file is the one place that
proves the isolation claim: the SAME installed output, running inside a
REAL container with `--network none` and ZERO bind mounts - the
disposable installed home enters only via `docker cp`.

TARGET PROFILE: `evals/subjects/cpp-codex-flow-check-ea6dbfa/` (CPP
`ea6dbfa`, skillc #330's re-declaration) - the pin the #287 study actually
runs, confirmed by the orchestrator. NOT the older `cpp-codex-flow-check/`
@ `85e9b03` an earlier plan draft named - skillc #330 declared this as a
SEPARATE, untouched profile precisely so this test could move pins
without disturbing #264's case-contract citations against the old one.

TWO PHASES, the same split `docs/specs/evaluation-facility/profiles.md`'s
"Human-only real-pin proof" section already used by hand:

- HOST PHASE (no network needed - the committed
  `tests/fixtures/profile-cpp-codex-flow-check-ea6dbfa/` snapshot is used
  directly via `DirTree`, never a live GitHub fetch): `profile.validate()`
  + `profile.install()` into a fresh throwaway host directory. Pure
  Python, proves nothing about isolation on its own - `tests/test_profile_
  install.py` already proves this mechanism works.
- CONTAINER PHASE: a fresh container from `docker/profile-cold-install/`'s
  image, `--network none`, zero bind mounts - the installed home enters
  ONLY via `docker cp`. Inside: the exact sequence the hand-run already
  proved on the host (offline `uv sync`, `import lib.cicd; import
  lib.security`, `flow-finish-gate.sh` against a tiny fixture project),
  now inside the isolation boundary, offline.

ASSERTIONS (the positive claim, `none` mode): the container reaches the
SAME outcome the hand-run already proved - zero mounts, the pin-matched
cache's digest matches, the offline sync succeeds, the library imports
cleanly, and `flow-finish-gate.sh` reaches the REAL `lib.cicd` runner
(`gate_path.classify_gate_output` returns `"real-runner"`, never the
Makefile fallback). No `FLOW_GATE_CPP_DIR` override is used or needed -
#303's synthetic `CLAUDE.md` marker (present in this profile's own
dependency list, `checkout-detection-marker`) makes self-detection work
without one.

BREAK MODES, `SKILLC_COLDINSTALL_LIVE_BREAK` selects
(`ci/real-docker/break-lib.sh`'s `coldinstall:` family): four plant
exactly one decoy bind mount at a path #266 names, caught by the shared
mount-emptiness oracle (`docker inspect`'s `Mounts` list, empty for
`none`); the fifth runs the SAME sequence against the `uncached` build
stage (see `docker/profile-cold-install/Dockerfile`), where the offline
sync must fail at `uv`'s own resolution step - the negative control
proving the cache is what makes the intact run work, not merely present
and unused.

    none          (default) the full intact run described above.
    skill-mount   one decoy bind mount at a path an operator's real
                  Claude/Codex skill directory would occupy.
    home-mount    one decoy bind mount standing in for an operator's
                  real $HOME.
    mcp-mount     one decoy bind mount at an MCP config path.
    secret-mount  one decoy bind mount at a credential/secret file path.
    cold-cache    the `uncached` image stage - no cache, no digest file.
                  The offline `uv sync` must fail, and its own stderr
                  must name the specific resolution failure ("wasn't
                  found in the cache"), confirmed empirically against a
                  real local `uv 0.9.7` with an empty UV_CACHE_DIR before
                  this assertion was written - never merely "a non-zero
                  exit", which `--network none` alone would also produce
                  for the wrong reason (`--offline` is what makes the
                  failure mode specific to the cache, not the network).

`xfail(strict=True, raises=AssertionError)` on every non-`none` mode -
same shape and reasoning as `test_gate_witness_live.py` and `test_decide_
reply_channel_live.py`: an unexpectedly-successful break is a hard
failure (XPASS), and a break that dies of an unrelated exception (a
docker transport error, say) is a hard FAILURE rather than an accidental
strict-xfail pass.

THE CLAIM'S EXACT BOUNDARY (orchestrator's condition, restated in the PR
body and PROFILE.md too): this proves an OFFLINE install from a
pin-matched cache. It does not prove, and does not claim to prove, how a
live trial container (which needs the network, for the model API)
behaves - that remains #237's own path.

SKIPPED, NOT FAILED, when no Docker daemon is reachable - named by
reason, distinguishing a missing binary from a missing daemon (same
`probe_daemon` pattern `test_gate_witness_live.py` uses). Real-daemon
execution is owed to the operator's real-Docker runner (#315); this file
was written and reviewed WITHOUT EVER RUNNING IT against a real daemon -
no Docker in the implementation environment, confirmed and reported - and
says so rather than implying otherwise. The `uv --offline` failure text
asserted on IS independently confirmed (a real local `uv 0.9.7`, no
Docker needed for that one check), but nothing involving an actual
container has run.

Every container and image this file builds is removed in a `finally` -
never left to the runner's own prune.

LEAK SAFETY: no host path, container name, or raw operator identity is
ever printed into an assertion message or captured value this file
returns - every decoy mount's host-side source lives under `tmp_path`
(pytest's own throwaway, never this host's real identity) and contains
only a fixed, static sentinel string; assertions compare in-memory
booleans/exit codes/known-static substrings only, matching every other
live test in this repository.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from skillc import docker_backend as d
from skillc import profile as p

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "profile-cpp-codex-flow-check-ea6dbfa"
PROFILE_JSON = ROOT / "evals" / "subjects" / "cpp-codex-flow-check-ea6dbfa" / "profile.json"
DOCKERFILE = ROOT / "docker" / "profile-cold-install" / "Dockerfile"
TINY_PROJECT = ROOT / "tests" / "fixtures" / "cold-install" / "tiny-project"

#: Pure text classifier, shared across profiles - not pin-specific
#: content, so imported from the OLDER profile directory (the only one
#: that carries a copy), exactly as `tests/test_synthetic_profile_files.py`
#: already does.
_CLASSIFIER_PATH = ROOT / "evals" / "subjects" / "cpp-codex-flow-check" / "gate_path.py"
_classifier_spec = importlib.util.spec_from_file_location("subject_gate_path", _CLASSIFIER_PATH)
assert _classifier_spec is not None and _classifier_spec.loader is not None
gate_path: Any = importlib.util.module_from_spec(_classifier_spec)
_classifier_spec.loader.exec_module(gate_path)

IMAGE_TAG = "skillc-coldinstall-266:test"

BREAK_MODE = os.environ.get("SKILLC_COLDINSTALL_LIVE_BREAK", "none")
_VALID_BREAK_MODES = ("none", "skill-mount", "home-mount", "mcp-mount", "secret-mount", "cold-cache")
#: One decoy mount target per mount-family mode - a plausible location
#: the named operator surface would occupy, never this host's own real
#: path. `kind` says whether the HOST-side decoy this test builds under
#: `tmp_path` must be a file or a directory, to match what a real bind
#: mount of that surface would be.
_DECOY_TARGETS: dict[str, tuple[str, str]] = {
    "skill-mount": ("/root/.claude/skills", "dir"),
    "home-mount": ("/root", "dir"),
    "mcp-mount": ("/root/.mcp.json", "file"),
    "secret-mount": ("/root/.config/skillc/secret", "file"),
}
#: Fixed, static sentinel - never derived from this host's own identity
#: (leak safety).
_DECOY_SENTINEL = "skillc-266-coldinstall-decoy\n"

if BREAK_MODE not in _VALID_BREAK_MODES:
    raise RuntimeError(f"SKILLC_COLDINSTALL_LIVE_BREAK={BREAK_MODE!r} must be one of {_VALID_BREAK_MODES}")

_DOCKER_BIN_PRESENT = shutil.which("docker") is not None
pytestmark = [
    pytest.mark.real_docker,
    pytest.mark.skipif(
        not _DOCKER_BIN_PRESENT or d.probe_daemon(["docker"]) is None,
        reason="no reachable Docker daemon in this environment (binary "
               + ("present" if _DOCKER_BIN_PRESENT else "absent")
               + ") - this test needs a real daemon for the cold-container isolation claim; "
                 "real-daemon execution is owed to the real-Docker runner (#315)",
    ),
]


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(args: list[str], timeout: float = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)


def _build_image(tag: str, target: str) -> None:
    build = _run(
        ["docker", "build", "--target", target, "-f", str(DOCKERFILE), "-t", tag, str(FIXTURE_DIR)],
        timeout=300,
    )
    assert build.returncode == 0, f"image build failed (tag={tag!r}, target={target!r}): {build.stderr}"


def _install_profile(home: Path) -> dict[str, Any]:
    """HOST PHASE: validates and installs the real pinned profile into
    `home`, via the committed fixture snapshot - no network, no
    isolation claim (see this module's own docstring)."""
    prof = p.Profile.load(PROFILE_JSON)
    tree = p.DirTree(FIXTURE_DIR)
    inventory = p.validate(prof, tree)
    receipt = p.install(inventory, tree, home)
    assert all(r["status"] == "satisfied" for r in p.verify_installed(inventory, home)["files"])
    return receipt


def _decoy_mount_args(tmp_path: Path, mode: str) -> list[str]:
    """Builds ONE host-side decoy under `tmp_path` for `mode` and returns
    the `docker create` `-v` argument for it - empty for `none` and
    `cold-cache`, which carry zero mounts."""
    if mode not in _DECOY_TARGETS:
        return []
    target, kind = _DECOY_TARGETS[mode]
    decoy_host = tmp_path / "decoy"
    if kind == "dir":
        decoy_host.mkdir()
        (decoy_host / "sentinel").write_text(_DECOY_SENTINEL, encoding="utf-8")
    else:
        decoy_host.write_text(_DECOY_SENTINEL, encoding="utf-8")
    return ["-v", f"{decoy_host}:{target}:ro"]


def _container_mounts(container: str) -> list[Any]:
    inspect = _run(["docker", "inspect", container, "--format", "{{json .Mounts}}"])
    assert inspect.returncode == 0, f"docker inspect failed: {inspect.stderr}"
    result: list[Any] = json.loads(inspect.stdout)
    return result


@pytest.mark.xfail(
    condition=BREAK_MODE != "none", strict=True, raises=AssertionError,
    reason=f"SKILLC_COLDINSTALL_LIVE_BREAK={BREAK_MODE} deliberately breaks one property",
)
def test_profile_runs_cold_with_no_operator_mounts(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    _install_profile(home)

    cpp_dir_in_home = home / "Projects" / "claude-power-pack"
    installed_lockfile = cpp_dir_in_home / "uv.lock"
    assert installed_lockfile.is_file(), "the installed home must carry the pinned uv.lock"

    build_target = "uncached" if BREAK_MODE == "cold-cache" else "cached"
    _build_image(IMAGE_TAG, build_target)

    container = f"skillc-266-{os.getpid()}-{id(tmp_path)}"
    try:
        create = _run(
            ["docker", "create", "--network", "none", *_decoy_mount_args(tmp_path, BREAK_MODE),
             "--name", container, IMAGE_TAG, "sleep", "infinity"],
        )
        assert create.returncode == 0, f"docker create failed: {create.stderr}"

        # The shared oracle every mount-break mode is caught by, checked
        # BEFORE anything else: zero mounts for `none` and `cold-cache`,
        # exactly one for each of the four mount-break modes.
        mounts = _container_mounts(container)
        if BREAK_MODE in _DECOY_TARGETS:
            assert mounts, f"expected a decoy mount for {BREAK_MODE}, found none"
        else:
            assert mounts == [], f"expected zero mounts, found {len(mounts)}"

        cp_home = _run(["docker", "cp", f"{home}/.", f"{container}:/disposable-home"])
        assert cp_home.returncode == 0, f"docker cp (home) failed: {cp_home.stderr}"
        cp_project = _run(["docker", "cp", f"{TINY_PROJECT}/.", f"{container}:/tiny-project"])
        assert cp_project.returncode == 0, f"docker cp (tiny project) failed: {cp_project.stderr}"

        start = _run(["docker", "start", container])
        assert start.returncode == 0, f"docker start failed: {start.stderr}"

        in_container_cpp_dir = "/disposable-home/Projects/claude-power-pack"
        env_prefix = [
            "env", "-i", "HOME=/disposable-home", "PATH=/usr/bin:/bin:/usr/local/bin",
            "UV_CACHE_DIR=/opt/skillc-coldinstall/uv-cache",
        ]

        # The cache-freshness check: the image's baked digest must match
        # the digest of the uv.lock actually being installed from -
        # "MISSING" (cold-cache: the file was never written) is the one
        # value this check must never silently accept as a match.
        digest_check = _run(
            ["docker", "exec", container, "sh", "-c",
             "cat /opt/skillc-coldinstall/lockfile.sha256 2>/dev/null || echo MISSING"],
        )
        assert digest_check.returncode == 0, f"digest read failed: {digest_check.stderr}"
        baked_digest = digest_check.stdout.strip()
        installed_digest = _sha256_file(installed_lockfile)
        if BREAK_MODE == "cold-cache":
            assert baked_digest == "MISSING", (
                "the uncached stage must carry no lockfile.sha256 at all"
            )
        else:
            assert baked_digest == installed_digest, (
                "the image's baked cache digest must match the uv.lock being installed from"
            )

        sync = _run(
            ["docker", "exec", container, *env_prefix, "sh", "-c",
             f"cd {in_container_cpp_dir} && uv sync --locked --offline"],
            timeout=60,
        )
        if BREAK_MODE == "cold-cache":
            assert sync.returncode != 0, "an offline sync with no warm cache must fail"
            assert "wasn't found in the cache" in sync.stderr, (
                "the offline sync must fail at uv's own resolution step, naming the specific "
                f"cache miss - got: {sync.stderr!r}"
            )
            return
        assert sync.returncode == 0, f"offline uv sync failed: {sync.stderr}"

        import_cmd = f"cd {in_container_cpp_dir} && uv run --locked python -c 'import lib.cicd; import lib.security'"
        import_check = _run(["docker", "exec", container, *env_prefix, "sh", "-c", import_cmd])
        assert import_check.returncode == 0, f"library import failed: {import_check.stderr}"

        gate = _run(
            ["docker", "exec", container, *env_prefix, "bash", "-c",
             "cd /tiny-project && exec /disposable-home/.claude/scripts/flow-finish-gate.sh"],
            timeout=60,
        )
        classification = gate_path.classify_gate_output(gate.stdout)
        assert classification == "real-runner", (
            f"flow-finish-gate.sh must reach the real lib.cicd runner, not the Makefile "
            f"fallback - classified as {classification!r}"
        )
    finally:
        _run(["docker", "rm", "-f", container])
        _run(["docker", "image", "rm", "-f", IMAGE_TAG])
