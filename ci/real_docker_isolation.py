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

Two probes feed the classifier:
- a LAN probe (must FAIL - reaching the configured LAN target would mean
  the VM is not isolated);
- a GitHub probe (must SUCCEED - this is the probe's own positive control:
  it shows the probe mechanism can detect reachability at all, so a failed
  LAN probe is not just a broken network stack that fails everything).

The LAN target itself is read from the VM-LOCAL runner config, never from
this repository (so no address of any kind appears in skillc, public).

PURE: `classify()` takes three already-measured booleans (lan_reachable,
lan_configured, github_reachable) and returns a verdict - no sockets, no
subprocess, no I/O. The runner script does the actual probing (inside a
throwaway container) and passes the results in; this module only decides
what they mean, which is what makes it trivially testable.

Stdlib only (AGENTS.md).
"""

from __future__ import annotations

from dataclasses import dataclass

PROCEED = "PROCEED"
REFUSED = "REFUSED"


@dataclass(frozen=True)
class IsolationVerdict:
    status: str  # PROCEED | REFUSED
    reason: str


def classify(*, lan_reachable: bool, lan_configured: bool, github_reachable: bool) -> IsolationVerdict:
    """Refuses (never proceeds) unless ALL THREE conditions hold at once:
    the LAN target was configured, the LAN probe failed (unreachable), and
    the GitHub probe succeeded. Order of checks does not matter for
    correctness, but IS chosen for the clearest reason when more than one
    thing is wrong at once: an unconfigured target is reported as
    "unconfigured", never silently folded into "LAN reachable" just because
    an unconfigured probe may happen to return False for unrelated reasons."""
    if not lan_configured:
        return IsolationVerdict(
            REFUSED,
            "the LAN probe target is not configured on this host - unconfigured is not isolated, "
            "never treated as an inconclusive pass",
        )
    if lan_reachable:
        return IsolationVerdict(
            REFUSED,
            "the configured LAN target was reachable from inside the throwaway container - "
            "isolation not verified",
        )
    if not github_reachable:
        return IsolationVerdict(
            REFUSED,
            "github.com was not reachable from inside the throwaway container - the positive "
            "control failed, so an unreachable LAN cannot be trusted as isolation either "
            "(it may just be a broken network stack)",
        )
    return IsolationVerdict(PROCEED, "LAN target configured and unreachable; GitHub reachable")
