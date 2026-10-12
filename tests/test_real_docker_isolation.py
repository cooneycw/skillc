"""Tests for `ci/real_docker_isolation.py` (#315, R6 + B2's tri-state
correction): the preflight isolation DETECTOR's pure classifier. Covers
every meaningful combination of the three inputs, plus the mutation checks
the orchestrator review explicitly required."""

from __future__ import annotations

import errno
import socket
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from ci import real_docker_isolation as iso


def _installed_probe_script() -> str:
    runner = Path(__file__).resolve().parents[1] / "ci" / "real-docker" / "run-real-docker"
    return runner.read_text().split("_PROBE_SCRIPT='", 1)[1].split("\n'", 1)[0]


def _run_probe(
    script: str, error: Exception | None, capsys: pytest.CaptureFixture[str],
) -> str:
    """Run the shipped snippet, replacing only socket I/O; no Docker or network.

    A nonzero probe exit becomes probe_error in the shell's run_probe wrapper.
    Do not replace the exception classification we are trying to certify.
    """
    with (
        patch.object(socket, "create_connection", side_effect=error) as connect,
        patch.object(sys, "argv", ["probe", "target.invalid", "443", "3"]),
    ):
        try:
            exec(compile(script, "installed-runner-probe", "exec"), {})  # noqa: S102 - tracked probe under test
        except SystemExit as exc:
            assert exc.code == 2
            capsys.readouterr()
            return iso.PROBE_ERROR
        if error is None:
            connect.return_value.close.assert_called_once()
    return capsys.readouterr().out.strip()


@pytest.mark.parametrize(("error", "expected"), [
    (None, iso.REACHABLE),
    (ConnectionRefusedError(errno.ECONNREFUSED, "control"), iso.REACHABLE),
    (TimeoutError(), iso.UNREACHABLE),
    (OSError(errno.ETIMEDOUT, "control"), iso.UNREACHABLE),
    (OSError(errno.ENETUNREACH, "control"), iso.UNREACHABLE),
    (OSError(errno.EHOSTUNREACH, "control"), iso.UNREACHABLE),
    (socket.gaierror(socket.EAI_NONAME, "control"), iso.PROBE_ERROR),
    (socket.gaierror(socket.EAI_AGAIN, "control"), iso.PROBE_ERROR),
    (PermissionError(errno.EACCES, "control"), iso.PROBE_ERROR),
    (PermissionError(errno.EPERM, "control"), iso.PROBE_ERROR),
    (OSError(errno.EIO, "control"), iso.PROBE_ERROR),
    (ConnectionResetError(errno.ECONNRESET, "control"), iso.PROBE_ERROR),
    (ValueError("control"), iso.PROBE_ERROR),
])
def test_actual_probe_distinguishes_isolation_from_probe_errors(
    error: Exception | None, expected: str, capsys: pytest.CaptureFixture[str],
) -> None:
    observed = _run_probe(_installed_probe_script(), error, capsys)
    assert observed == expected
    result = iso.classify(lan_probe=observed, lan_configured=True, github_probe=iso.REACHABLE)
    assert result.status == (iso.PROCEED if expected == iso.UNREACHABLE else iso.REFUSED)
    # The same error on the positive control cannot establish a working probe.
    if expected == iso.PROBE_ERROR:
        assert iso.classify(
            lan_probe=iso.UNREACHABLE, lan_configured=True, github_probe=observed,
        ).status == iso.REFUSED


def test_broad_oserror_mutation_of_actual_probe_is_detected(
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _installed_probe_script()
    start = script.index("except OSError")
    end = script.index("except Exception", start)
    mutant = script[:start] + 'except OSError:\n    print("unreachable")\n' + script[end:]
    for error in (socket.gaierror(socket.EAI_NONAME, "control"), PermissionError("control")):
        assert _run_probe(script, error, capsys) == iso.PROBE_ERROR
        observed = _run_probe(mutant, error, capsys)
        assert observed == iso.UNREACHABLE
        assert iso.classify(
            lan_probe=observed, lan_configured=True, github_probe=iso.REACHABLE,
        ).status == iso.PROCEED


@pytest.mark.parametrize(("errors", "expected"), [
    ([ConnectionRefusedError(), TimeoutError()], iso.REACHABLE),
    ([TimeoutError(), ConnectionRefusedError()], iso.REACHABLE),
    ([PermissionError(), TimeoutError()], iso.PROBE_ERROR),
    ([TimeoutError(), PermissionError()], iso.PROBE_ERROR),
    ([PermissionError(), ConnectionRefusedError()], iso.REACHABLE),
    ([ConnectionRefusedError(), PermissionError()], iso.REACHABLE),
    ([TimeoutError(), OSError(errno.ENETUNREACH, "control")], iso.UNREACHABLE),
    ([OSError(errno.EHOSTUNREACH, "control"), TimeoutError()], iso.UNREACHABLE),
    ([TimeoutError(), None], iso.REACHABLE),
])
def test_actual_connection_keeps_every_resolved_address_outcome(
    errors: list[Exception | None], expected: str, capsys: pytest.CaptureFixture[str],
) -> None:
    """Exercise stdlib create_connection, replacing only DNS and sockets."""
    sockets = []
    for error in errors:
        sock = Mock()
        sock.connect.side_effect = error
        sockets.append(sock)
    addresses = [
        (socket.AF_INET, socket.SOCK_STREAM, 0, "", (f"192.0.2.{i + 1}", 443))
        for i in range(len(errors))
    ]
    with (
        patch.object(socket, "getaddrinfo", return_value=addresses),
        patch.object(socket, "socket", side_effect=sockets),
        patch.object(sys, "argv", ["probe", "target.invalid", "443", "3"]),
    ):
        exec(compile(_installed_probe_script(), "installed-runner-probe", "exec"), {})  # noqa: S102
    observed = capsys.readouterr().out.strip()
    assert observed == expected
    assert iso.classify(
        lan_probe=observed, lan_configured=True, github_probe=iso.REACHABLE,
    ).status == (iso.PROCEED if expected == iso.UNREACHABLE else iso.REFUSED)
    for sock in sockets:
        sock.close.assert_called_once()


def test_lan_reachable_by_successful_connect_refuses() -> None:
    result = iso.classify(lan_probe=iso.REACHABLE, lan_configured=True, github_probe=iso.REACHABLE)
    assert result.status == iso.REFUSED
    assert "reachable" in result.reason


def test_lan_connection_refused_also_refuses() -> None:
    """B2: a connection REFUSED still proves a host answered at that
    address - the probe script reports this as REACHABLE (not UNREACHABLE,
    and not an error), and the classifier must refuse on it exactly as it
    would for a fully successful connection."""
    result = iso.classify(lan_probe=iso.REACHABLE, lan_configured=True, github_probe=iso.REACHABLE)
    assert result.status == iso.REFUSED


def test_lan_unconfigured_refuses_even_if_everything_else_looks_fine() -> None:
    result = iso.classify(lan_probe=iso.UNREACHABLE, lan_configured=False, github_probe=iso.REACHABLE)
    assert result.status == iso.REFUSED
    assert "unconfigured" in result.reason


def test_lan_probe_error_refuses() -> None:
    """B2's central new case: the LAN probe itself failing to run (missing
    tool, throwaway container never started) must REFUSE, never be
    silently treated as 'unreachable' (which is what the old boolean
    design's `|| echo unreachable` fallback effectively did)."""
    result = iso.classify(lan_probe=iso.PROBE_ERROR, lan_configured=True, github_probe=iso.REACHABLE)
    assert result.status == iso.REFUSED
    assert "could not run" in result.reason


def test_github_probe_error_refuses() -> None:
    result = iso.classify(lan_probe=iso.UNREACHABLE, lan_configured=True, github_probe=iso.PROBE_ERROR)
    assert result.status == iso.REFUSED
    assert "could not run" in result.reason


def test_github_unreachable_refuses() -> None:
    result = iso.classify(lan_probe=iso.UNREACHABLE, lan_configured=True, github_probe=iso.UNREACHABLE)
    assert result.status == iso.REFUSED
    assert "positive control" in result.reason


def test_only_lan_unreachable_plus_github_reachable_proceeds() -> None:
    result = iso.classify(lan_probe=iso.UNREACHABLE, lan_configured=True, github_probe=iso.REACHABLE)
    assert result.status == iso.PROCEED


def test_an_invalid_probe_value_is_rejected_outright() -> None:
    """Never silently coerced - a typo'd probe result string must raise,
    not be treated as some default state."""
    with pytest.raises(ValueError, match="lan_probe"):
        iso.classify(lan_probe="maybe", lan_configured=True, github_probe=iso.REACHABLE)
    with pytest.raises(ValueError, match="github_probe"):
        iso.classify(lan_probe=iso.UNREACHABLE, lan_configured=True, github_probe="maybe")


def test_red_case_a_classifier_that_ignores_the_lan_probe_must_fail_a_case() -> None:
    """Mutation check (R6's explicit requirement): a classifier that never
    reads `lan_probe` at all - treating configuration and GitHub
    reachability as the whole story - would wrongly PROCEED when the LAN
    is actually reachable. Proves this suite would catch that mistake."""

    def ignores_lan_probe(*, lan_probe: str, lan_configured: bool, github_probe: str) -> str:
        del lan_probe  # the planted defect: never consulted
        if not lan_configured:
            return iso.REFUSED
        if github_probe != iso.REACHABLE:
            return iso.REFUSED
        return iso.PROCEED

    correct = iso.classify(lan_probe=iso.REACHABLE, lan_configured=True, github_probe=iso.REACHABLE).status
    mutated = ignores_lan_probe(lan_probe=iso.REACHABLE, lan_configured=True, github_probe=iso.REACHABLE)
    assert correct == iso.REFUSED
    assert mutated != correct, "the LAN-blind mutation accidentally agrees - this red case is inert"


def test_red_case_b2_folding_probe_error_into_unreachable_would_miss_this() -> None:
    """Mutation check for B2 specifically: the OLD design's
    `|| echo unreachable` fallback folded 'the probe could not run' into
    the SAME value as 'the probe ran and found nothing' - which would
    wrongly PROCEED on a LAN probe that never actually executed. Proves
    the tri-state distinction is load-bearing, not cosmetic."""

    def folds_error_into_unreachable(*, lan_probe: str, lan_configured: bool, github_probe: str) -> str:
        # The planted defect: PROBE_ERROR is treated exactly like UNREACHABLE.
        lan_ok = lan_probe != iso.REACHABLE
        github_ok = github_probe == iso.REACHABLE or github_probe == iso.PROBE_ERROR
        if not lan_configured:
            return iso.REFUSED
        if not lan_ok:
            return iso.REFUSED
        if not github_ok:
            return iso.REFUSED
        return iso.PROCEED

    correct = iso.classify(lan_probe=iso.PROBE_ERROR, lan_configured=True, github_probe=iso.REACHABLE).status
    mutated = folds_error_into_unreachable(lan_probe=iso.PROBE_ERROR, lan_configured=True, github_probe=iso.REACHABLE)
    assert correct == iso.REFUSED
    assert mutated != correct, "the error-folding mutation accidentally agrees - this red case is inert"
