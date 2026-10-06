"""The real-Docker runner's preflight isolation DETECTOR (#315, R6).

**This module does not prove isolation.** The enforced boundary is a
hypervisor-level firewall on `<agent-host>`'s network interface, set up by
the operator from a private runbook outside this repository - a privileged
container is root on the VM and can flush any firewall running inside it,
so an in-VM firewall (nftables/ufw, including the `DOCKER-USER` chain
Docker's own rules would otherwise bypass) is defence in depth, never the
boundary itself. What this module provides is the thing a defence-in-depth
layer cannot: a per-run check from **inside a throwaway container**, run
before any checkout or test, that the network looks isolated RIGHT NOW. A
passing result means "the LAN was unreachable from this container at this
moment"; it never means "isolation is proven" - wording in the runner or its
docs must not claim the stronger thing.

Two probes feed the classifier, each a TRI-STATE result, not a boolean
(orchestrator review, B2): `REACHABLE`, `UNREACHABLE`, or `PROBE_ERROR`.
The distinction matters because "the probe could not run at all" (missing
tool in the preflight image, the throwaway container itself failing to
start) is a DIFFERENT fact than "the probe ran and found nothing" - folding
both into one boolean let an unreachable-by-ACCIDENT result (the probe
itself broke) look identical to an unreachable-by-ISOLATION result, which
is exactly backwards for a target where "reachable" should refuse: a probe
that cannot run must refuse too, not silently count as evidence of
isolation.

A CONNECTION REFUSED on the LAN probe counts as `REACHABLE`, not
`UNREACHABLE`: a refused TCP connection still proves a host answered at
that address, so the LAN is not isolated even though nothing is listening
on the probed port. Only a timeout or routing failure (nothing answers at
all) is `UNREACHABLE`. The probe script (not this module - see
`ci/real-docker/run-real-docker`) is what tells these apart; this module
only interprets the resulting tri-state string.

PURE: `classify()` takes three already-measured values (the two tri-state
probe results and whether a LAN target was configured) and returns a
verdict - no sockets, no subprocess, no I/O.

Stdlib only (AGENTS.md).
"""

from __future__ import annotations

from dataclasses import dataclass

PROCEED = "PROCEED"
REFUSED = "REFUSED"

#: The three probe outcomes a single TCP-connect attempt can report.
REACHABLE = "reachable"
UNREACHABLE = "unreachable"
PROBE_ERROR = "probe_error"
_VALID_PROBE_RESULTS = frozenset({REACHABLE, UNREACHABLE, PROBE_ERROR})


@dataclass(frozen=True)
class IsolationVerdict:
    status: str  # PROCEED | REFUSED
    reason: str


def classify(*, lan_probe: str, lan_configured: bool, github_probe: str) -> IsolationVerdict:
    """Refuses (never proceeds) unless ALL of the following hold: the LAN
    target was configured, BOTH probes actually ran (neither is
    `PROBE_ERROR`), the LAN probe found nothing reachable, and the GitHub
    probe DID find something reachable (the probe mechanism's own positive
    control). Any other combination refuses, each with its own distinct
    reason - checked in an order chosen for the clearest message when more
    than one thing is wrong at once, never affecting the PROCEED/REFUSED
    result itself."""
    if lan_probe not in _VALID_PROBE_RESULTS:
        raise ValueError(f"lan_probe must be one of {sorted(_VALID_PROBE_RESULTS)}, not {lan_probe!r}")
    if github_probe not in _VALID_PROBE_RESULTS:
        raise ValueError(f"github_probe must be one of {sorted(_VALID_PROBE_RESULTS)}, not {github_probe!r}")

    if not lan_configured:
        return IsolationVerdict(
            REFUSED,
            "the LAN probe target is not configured on this host - unconfigured is not isolated, "
            "never treated as an inconclusive pass",
        )
    if lan_probe == PROBE_ERROR:
        return IsolationVerdict(
            REFUSED,
            "the LAN probe itself could not run (missing tool, throwaway container failed to start) - "
            "an unrun probe is never evidence of isolation",
        )
    if github_probe == PROBE_ERROR:
        return IsolationVerdict(
            REFUSED,
            "the GitHub probe itself could not run - the positive control is unavailable, so an "
            "unreachable LAN result cannot be trusted either",
        )
    if lan_probe == REACHABLE:
        return IsolationVerdict(
            REFUSED,
            "the configured LAN target was reachable from inside the throwaway container (connected, "
            "or connection refused - either proves a host answered) - isolation not verified",
        )
    if github_probe != REACHABLE:
        return IsolationVerdict(
            REFUSED,
            "github.com was not reachable from inside the throwaway container - the positive "
            "control failed, so an unreachable LAN cannot be trusted as isolation either "
            "(it may just be a broken network stack)",
        )
    return IsolationVerdict(PROCEED, "LAN target configured and unreachable; GitHub reachable")
