"""#505: installed subject files arrive with their SOURCE mode.

Every `extra_home_files` entry used to land at `deliver_home_file`'s default
0600, so a subject's helper scripts were not executable in a live trial: 9 of
10 attempts of the #434 revision-5 campaign hit `Permission denied`, and one
stopped at flow:auto's Step 1 for it. A file now arrives at the OWNER-ONLY
bits of its source mode (100755 -> 0700, 100644 -> 0600) - never broader than
the source - and the in-container preflight reads each verified file's
executable bit back.
"""

from __future__ import annotations

import stat
from pathlib import Path
from typing import Any, ClassVar

import pytest
from conftest import FAKE_DOCKER_DAEMON_TIMEOUT
from test_agent_trial import _docker_bin, _fake_argv, _fresh_credential, _mapped_home, _planned
from test_agent_trial_preflight import LIMITS, _StubBackend

from skillc import agent_trial as at
from skillc import docker_backend as d
from skillc import profile, trial
from skillc.backend import Limits

HELPER = ".claude/scripts/flow-start-resolve.sh"
DOC = ".claude/scripts/README.md"
FILES = {HELPER: b"#!/bin/sh\necho resolved\n", DOC: b"docs\n"}
MODES = {HELPER: "100755", DOC: "100644"}


# ------------------------------------------------------------ the delivery mode

@pytest.mark.parametrize("modes,relpath,want", [
    (MODES, HELPER, 0o700),        # executable source: owner rwx, never group/other
    (MODES, DOC, 0o600),           # non-executable source stays non-executable
    ({}, HELPER, 0o600),           # no recorded mode: as narrow as before
    (None, HELPER, 0o600),         # no modes at all: byte-identical to before #505
])
def test_a_file_is_delivered_at_the_owner_bits_of_its_source_mode(modes: Any, relpath: str, want: int) -> None:
    assert at.delivery_mode(relpath, modes) == want


@pytest.mark.parametrize("mode", ["120000", "100775", "755", ""])
def test_a_mode_that_is_not_a_git_file_mode_is_refused(mode: str) -> None:
    with pytest.raises(at.HomeFileVerificationRefused, match="unsupported source mode"):
        at.delivery_mode(HELPER, {HELPER: mode})


class _Recording(d.DockerBackend):
    """Records each home delivery's mode, and the mode the file has in the
    container (the fake docker's mapped home) right after delivery."""

    deliveries: ClassVar[dict[str, tuple[int, int]]] = {}
    home: ClassVar[Path] = Path("/nonexistent")

    def deliver_home_file(self, handle: object, container_relpath: str, data: bytes, *, mode: int = 0o600) -> None:
        super().deliver_home_file(handle, container_relpath, data, mode=mode)
        landed = stat.S_IMODE((type(self).home / container_relpath).stat().st_mode)
        type(self).deliveries[container_relpath] = (mode, landed)


def _attempt(tmp_path: Path, modes: dict[str, str] | None) -> dict[str, tuple[int, int]]:
    store = trial.open_store(tmp_path / "store", forbidden=[])
    base, state = tmp_path / "work", tmp_path / "docker-state"
    base.mkdir()
    experiment, attempt_id = _planned(store)
    _Recording.deliveries, _Recording.home = {}, _mapped_home(state, attempt_id)
    backend = _Recording(image="fake-image:1", base_dir=base, docker_bin=_docker_bin(state),
                         daemon_timeout=FAKE_DOCKER_DAEMON_TIMEOUT)
    at.run_one_attempt(
        backend=backend, experiment=experiment, attempt_id=attempt_id, client="codex",
        base_argv=_fake_argv(fmt="codex-fake", home=_mapped_home(state, attempt_id),
                             transcript_relpath=".codex/sessions/2026/01/01/rollout-x.jsonl"),
        prompt="Fix the slug helper.", skill_name=None, surface={}, limits=Limits(timeout=5), base=base,
        credential_explicit_path=_fresh_credential(tmp_path, "codex"),
        extra_home_files=FILES, extra_home_modes=modes)
    return dict(_Recording.deliveries)


def test_red_a_helper_script_is_executable_in_the_container(tmp_path: Path) -> None:
    """The issue's first red: a 100755 helper arrives executable (0700)."""
    mode, landed = _attempt(tmp_path, MODES)[HELPER]
    assert mode == 0o700 and landed == 0o700 and landed & stat.S_IXUSR


def test_red_a_non_executable_source_stays_non_executable(tmp_path: Path) -> None:
    """The issue's second red: a 100644 file is not made executable."""
    mode, landed = _attempt(tmp_path, MODES)[DOC]
    assert mode == 0o600 and landed == 0o600 and not landed & stat.S_IXUSR


def test_without_modes_the_delivery_is_the_0600_of_before(tmp_path: Path) -> None:
    """What main did for EVERY file: the control for both reds above."""
    deliveries = _attempt(tmp_path, None)
    assert deliveries[HELPER] == (0o600, 0o600) and deliveries[DOC] == (0o600, 0o600)


@pytest.mark.parametrize("modes,match", [
    ({".claude/scripts/not-delivered.sh": "100755"}, "not delivered"),
    ({HELPER: "120000"}, "unsupported source mode"),
])
def test_bad_modes_are_refused_before_any_container(tmp_path: Path, modes: dict[str, str], match: str) -> None:
    with pytest.raises(at.HomeFileVerificationRefused, match=match):
        at.run_one_attempt(backend=object(), experiment=None, attempt_id="a", client="codex",  # type: ignore[arg-type]
                           base_argv=[], prompt="p", skill_name=None, surface={}, limits=Limits(timeout=1),
                           base=tmp_path, extra_home_files=FILES, extra_home_modes=modes)


# ------------------------------------------ the in-container read-back

_DIGEST = "a" * 64
_PATH = f"{at.CONTAINER_HOME}/{HELPER}"


def _preflight(observations: str, modes: dict[str, str] | None) -> _StubBackend:
    backend: Any = _StubBackend(observations=observations)
    at._preflight_in_container(backend, object(), LIMITS, {HELPER: f"sha256:{_DIGEST}"}, (),
                               verify_home_modes=modes)
    return backend


def test_an_executable_helper_read_back_as_executable_passes() -> None:
    backend = _preflight(f"{_DIGEST}  {_PATH}\n{at._XMODE_PREFIX}1 {_PATH}\n{at._TOOLS_MARKER}\n", {HELPER: "100755"})
    assert "test -x" in backend.exec_calls[0][-1]


@pytest.mark.parametrize("readback,mode,match", [
    ("0", "100755", "is not executable in the container"),   # the #505 install itself
    ("1", "100644", "is executable in the container"),        # broader than the source
    (None, "100755", "was not read back"),
])
def test_red_a_mode_the_container_does_not_have_refuses_the_attempt(readback: str | None, mode: str,
                                                                     match: str) -> None:
    line = f"{at._XMODE_PREFIX}{readback} {_PATH}\n" if readback is not None else ""
    with pytest.raises(at.HomeFileVerificationRefused, match=match):
        _preflight(f"{_DIGEST}  {_PATH}\n{line}{at._TOOLS_MARKER}\n", {HELPER: mode})


def test_without_modes_the_preflight_script_is_unchanged() -> None:
    backend = _preflight(f"{_DIGEST}  {_PATH}\n{at._TOOLS_MARKER}\n", None)
    assert "test -x" not in backend.exec_calls[0][-1] and at._XMODE_PREFIX not in backend.exec_calls[0][-1]


# ------------------------------------------------- the pinned source modes

def test_the_installed_modes_are_the_inventory_s_own() -> None:
    """`installed_home_modes` reads the SAME verified records as
    `installed_home_files`: one mode per delivered file, and the pinned
    subject's helper scripts are executable at the source."""
    from test_profile_installed_home_files import _inventory_and_tree

    inventory, tree = _inventory_and_tree()
    files = profile.installed_home_files(inventory, tree)
    modes = profile.installed_home_modes(inventory, tree)
    assert set(modes) == set(files) and set(modes.values()) <= {"100644", "100755"}
    assert any(dest.endswith(".sh") and mode == "100755" for dest, mode in modes.items())
