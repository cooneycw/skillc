"""Tests for `ci/real-docker/break-lib.sh` (#315 follow-up, orchestrator
review during #269's merge): the pure, sourceable break-mode parsing and
context-routing functions `run-real-docker` uses.

Before this file, the witness break modes (#269's `stale-confirm-lie`,
`kill-wrong-pid`, `gate-in-fresh-container`) could not be driven through
the runner at all - `run-real-docker` only ever set `SKILLC_LIVE_TEST_
BREAK` (#183's channel modes). These functions are tested directly by
`source`-ing the lib, not by running the whole runner: the parsing and
context decisions happen before any of the runner's own infra (a config
file, docker, git, curl) is touched, so nothing here needs any of that -
confirmed by the end-to-end subprocess tests below, which run the REAL
`run-real-docker` script with a syntactically-valid but nonexistent sha
and no config file present, and observe that an invalid --break argument
is refused before the config-file check ever runs, while a valid one
reaches it."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_REAL_DOCKER_DIR = Path(__file__).resolve().parent.parent / "ci" / "real-docker"
LIB_PATH = _REAL_DOCKER_DIR / "break-lib.sh"
RUNNER_PATH = _REAL_DOCKER_DIR / "run-real-docker"
DUMMY_SHA = "0" * 40


def _resolve(spec: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", 'source "$1"; resolve_break_spec "$2"', "_", str(LIB_PATH), spec],
        capture_output=True, text=True, timeout=10, check=False,
    )


def _context_for(normalized_spec: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", 'source "$1"; context_for_break_mode "$2"', "_", str(LIB_PATH), normalized_spec],
        capture_output=True, text=True, timeout=10, check=False,
    )


def _run_runner(*args: str) -> subprocess.CompletedProcess[str]:
    """Invokes the REAL run-real-docker script, not a mock - the parsing
    stage runs before CONFIG_FILE is read, so this needs no setup at all.
    A `/etc/skillc-real-docker/config.env`-absent error for a VALID
    --break argument is success for this test's purposes: it proves
    parsing accepted the argument and execution moved past it."""
    return subprocess.run(
        [str(RUNNER_PATH), *args], capture_output=True, text=True, timeout=10, check=False,
        env={"SKILLC_REAL_DOCKER_CONFIG": "/nonexistent-for-tests/config.env"},
    )


# --------------------------------------------------------------- resolve_break_spec

def test_none_resolves_to_the_none_sentinel_with_no_env_var() -> None:
    result = _resolve("none")
    assert result.returncode == 0
    assert result.stdout.splitlines() == ["none", "", ""]


@pytest.mark.parametrize(
    ("mode", "expected_env"),
    [
        ("omit-mount", "SKILLC_LIVE_TEST_BREAK"),
        ("wrong-uid", "SKILLC_LIVE_TEST_BREAK"),
        ("flip-decision", "SKILLC_LIVE_TEST_BREAK"),
    ],
)
def test_namespaced_channel_modes_resolve_to_the_channel_env_var(mode: str, expected_env: str) -> None:
    result = _resolve(f"channel:{mode}")
    assert result.returncode == 0
    assert result.stdout.splitlines() == [f"channel:{mode}", expected_env, mode]


@pytest.mark.parametrize(
    ("mode", "expected_env"),
    [
        ("stale-confirm-lie", "SKILLC_GATE_WITNESS_LIVE_BREAK"),
        ("kill-wrong-pid", "SKILLC_GATE_WITNESS_LIVE_BREAK"),
        ("gate-in-fresh-container", "SKILLC_GATE_WITNESS_LIVE_BREAK"),
    ],
)
def test_namespaced_witness_modes_resolve_to_the_witness_env_var(mode: str, expected_env: str) -> None:
    result = _resolve(f"witness:{mode}")
    assert result.returncode == 0
    assert result.stdout.splitlines() == [f"witness:{mode}", expected_env, mode]


@pytest.mark.parametrize("mode", ["omit-mount", "wrong-uid", "flip-decision"])
def test_bare_legacy_channel_modes_are_still_accepted_and_normalized(mode: str) -> None:
    """R2 compatibility (orchestrator review): the README already
    documented these bare spellings to the operator before family
    prefixes existed, so they must keep working - normalized to their
    `channel:<mode>` form, never left as the bare spelling, so every
    downstream comparison against "none" has exactly one non-none shape
    per mode to deal with."""
    result = _resolve(mode)
    assert result.returncode == 0
    assert result.stdout.splitlines() == [f"channel:{mode}", "SKILLC_LIVE_TEST_BREAK", mode]


def test_a_bare_witness_mode_is_refused_not_silently_accepted() -> None:
    """Red case: a witness mode has NO documented bare form (unlike the
    three legacy channel modes), so a bare spelling must be refused, not
    silently treated as a channel mode of the same name."""
    result = _resolve("kill-wrong-pid")
    assert result.returncode == 2
    assert "unknown channel break mode 'kill-wrong-pid'" in result.stderr


def test_an_unknown_mode_in_a_known_family_is_refused() -> None:
    result = _resolve("channel:bogus")
    assert result.returncode == 2
    assert "unknown channel break mode 'bogus'" in result.stderr


def test_an_unknown_family_is_refused() -> None:
    result = _resolve("bogus:foo")
    assert result.returncode == 2
    assert "unknown break family 'bogus'" in result.stderr


def test_red_case_a_table_that_accepts_everything_would_miss_both_refusals() -> None:
    """Mutation check: a plausible-but-wrong resolver that only checks for
    a ':' separator and accepts ANY family/mode pair would wrongly accept
    both red cases above. This test exists so a future edit to the table
    that accidentally widens it (e.g. a bare `*) return 0 ;;` fallthrough)
    is caught by disagreement with the real function, not just inspected
    by eye."""
    def accepts_anything(spec: str) -> bool:
        return ":" in spec or spec == "none"

    real_rejects_bare_witness = _resolve("kill-wrong-pid").returncode != 0
    real_rejects_unknown_family = _resolve("bogus:foo").returncode != 0
    assert real_rejects_bare_witness, "the real function should refuse this"
    assert real_rejects_unknown_family, "the real function should refuse this"
    assert accepts_anything("kill-wrong-pid") is False or accepts_anything("bogus:foo") is True, (
        "the naive mutation should disagree with the real function on at least one of these - "
        "if it agrees on both, this red case is inert"
    )


# ------------------------------------------------------------ context_for_break_mode

def test_none_resolves_to_the_certifying_context() -> None:
    result = _context_for("none")
    assert result.returncode == 0
    assert result.stdout.strip() == "skillc/real-docker"


@pytest.mark.parametrize(
    "normalized_spec",
    [
        "channel:omit-mount",
        "channel:wrong-uid",
        "channel:flip-decision",
        "witness:stale-confirm-lie",
        "witness:kill-wrong-pid",
        "witness:gate-in-fresh-container",
    ],
)
def test_every_break_mode_resolves_to_the_control_context_never_the_certifying_one(normalized_spec: str) -> None:
    """The red case orchestrator review named explicitly: a break run must
    NEVER resolve to the certifying context - a run that found a real
    failure under a deliberately broken implementation must not be
    mistaken, by GitHub or by a human skimming commit statuses, for the
    normal certifying signal."""
    result = _context_for(normalized_spec)
    assert result.returncode == 0
    assert result.stdout.strip() == "skillc/real-docker-control"


# --------------------------------------------------- end-to-end: the real runner

def test_the_real_runner_refuses_an_unknown_break_spec_before_touching_any_config() -> None:
    """Confirms the wiring, not just the lib in isolation: a syntactically
    invalid --break argument must be refused by the REAL run-real-docker
    script before it ever reads SKILLC_REAL_DOCKER_CONFIG - demonstrated
    by pointing that variable at a path that does not exist and observing
    the parsing error, not a config-file error."""
    result = _run_runner(DUMMY_SHA, "--break", "bogus:foo")
    assert result.returncode == 2
    assert "unknown break family 'bogus'" in result.stderr
    assert "config file" not in result.stderr


@pytest.mark.parametrize(
    "break_arg",
    ["none", "channel:omit-mount", "omit-mount", "witness:kill-wrong-pid"],
)
def test_the_real_runner_accepts_valid_break_specs_and_reaches_the_config_check(break_arg: str) -> None:
    """A VALID --break argument must be accepted by parsing and reach the
    next stage (the config-file check) - proven by getting that stage's
    own error, not a parsing error, for every family and for the legacy
    bare form."""
    args = (DUMMY_SHA,) if break_arg == "none" else (DUMMY_SHA, "--break", break_arg)
    result = _run_runner(*args)
    assert result.returncode == 2
    assert "config file" in result.stderr
    assert "unknown break" not in result.stderr
    assert "--break must be" not in result.stderr
