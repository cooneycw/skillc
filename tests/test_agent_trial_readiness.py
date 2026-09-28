"""Tests for `agent_trial.readiness_from_discovery_listings` and
`_build_discovery_receipt`'s early-return paths (#150-D).

Pure/fast tests: no fake docker, no backend, no container - `_build_discovery_receipt`
never touches its `backend`/`experiment` arguments until AFTER the checks this
file exercises, so a dummy placeholder is enough. The full end-to-end path
(a real receipt through a real fake-docker container, all three of ADR 0005's
named red cases) lives in `tests/test_collection_conformance.py`.

ADR 0005's "yes, narrow B1" ruling names three required red cases; this file
carries red case 3's pure-logic half (an unobtainable listing is UNKNOWN) and
red case 2 (an empty declared set, or a non-codex client, never builds a
receipt at all - the CALLER decision that keeps the B1 stand-in). Red case 1
(a canary-failing installing arm is not PASS) and the full re-derivation of
case 2 and 3 through a real fake-docker attempt are in
`tests/test_collection_conformance.py`.
"""

from __future__ import annotations

from pathlib import Path

from skillc import trial
from skillc.agent_trial import (
    DiscoveryCache,
    InstallationReceiptContext,
    _build_discovery_receipt,
    readiness_from_discovery_listings,
)
from skillc.backend import Limits
from skillc.docker_backend import DockerBackend

DECLARED = frozenset({"flow-finish"})


def _context(*, declared: frozenset[str] = DECLARED, cache: DiscoveryCache | None = None) -> InstallationReceiptContext:
    return InstallationReceiptContext(
        declared=declared, tree_digest="sha256:tree", subject_locator="test/test",
        subject_revision="v1", surface_name="codex-skills", cache=cache if cache is not None else {},
    )


def _unreachable_backend() -> DockerBackend:
    """Never actually called in the paths this file tests - `_build_discovery_receipt`
    returns before touching `backend` for a non-codex client or an empty
    `declared` set. A real (but never-invoked) instance, not a bare `None`,
    so a bug that DID reach further would fail loudly on a real method call
    rather than an unrelated `AttributeError` on `None`."""
    return DockerBackend(image="unused", base_dir=Path("."), docker_bin=["/bin/false"], daemon_timeout=1)


def test_a_claude_arm_never_builds_a_receipt() -> None:
    """Red case 2, half A: only codex has a model-free listing - a Claude
    Code arm must keep the B1 stand-in, whatever `declared` says."""
    result = _build_discovery_receipt(
        backend=_unreachable_backend(), experiment=trial.Experiment(root=Path("/nonexistent"), ledger={"trials": []}),
        attempt_id="a-x", client="claude", client_version="1.0", client_argv=["claude"],
        extra_home_files={"whatever": b"x"}, limits=Limits(timeout=1), base=Path("."),
        context=_context(),
    )
    assert result is None


def test_an_empty_declared_set_never_builds_a_receipt() -> None:
    """Red case 2, half B: nothing declared (an empty baseline arm) must
    keep the B1 stand-in, even on a codex client."""
    result = _build_discovery_receipt(
        backend=_unreachable_backend(), experiment=trial.Experiment(root=Path("/nonexistent"), ledger={"trials": []}),
        attempt_id="a-x", client="codex", client_version="1.0", client_argv=["codex"],
        extra_home_files={}, limits=Limits(timeout=1), base=Path("."),
        context=_context(declared=frozenset()),
    )
    assert result is None

#: A clean `demo.run_subject_discovery` result: no reason, no undeclared
#: skill listed alongside it.
NO_UNEXPECTED: frozenset[str] = frozenset()


def test_satisfied_when_every_declared_skill_is_discovered_after_and_absent_before() -> None:
    before = ({"flow-finish": "not-discovered"}, NO_UNEXPECTED, None)
    after = ({"flow-finish": "discovered"}, NO_UNEXPECTED, None)
    readiness = readiness_from_discovery_listings(DECLARED, before, after)
    assert readiness["discovery_canary"] == "SATISFIED"
    assert readiness["baseline_absence"] == "SATISFIED"


def test_red_case_a_missing_declared_skill_after_delivery_violates_discovery() -> None:
    """ADR 0005 red case 1: an installing arm whose listing omits a declared
    skill must not read SATISFIED - the result must not be able to PASS on
    it."""
    before = ({"flow-finish": "not-discovered"}, NO_UNEXPECTED, None)
    after = ({"flow-finish": "not-discovered"}, NO_UNEXPECTED, None)  # copy or discovery failed
    readiness = readiness_from_discovery_listings(DECLARED, before, after)
    assert readiness["discovery_canary"] == "VIOLATED", readiness
    assert readiness["discovery_canary"] != "SATISFIED"


def test_red_case_an_unobtainable_listing_is_unknown_never_satisfied() -> None:
    """ADR 0005 red case 3: a listing that could not be obtained (non-zero
    exit, empty or unparseable output - demo.run_subject_discovery's own
    UNMEASURED-with-a-reason shape) must read UNKNOWN, never SATISFIED and
    never silently absent."""
    before = ({"flow-finish": "not-discovered"}, NO_UNEXPECTED, None)
    after = (
        {"flow-finish": "UNMEASURED"}, NO_UNEXPECTED,
        "listing did not complete cleanly: reason=timeout exit_code=None",
    )
    readiness = readiness_from_discovery_listings(DECLARED, before, after)
    assert readiness["discovery_canary"] == "UNKNOWN", readiness
    assert readiness["discovery_canary"] != "SATISFIED"


def test_an_unobtainable_before_listing_is_unknown_baseline_absence() -> None:
    before = (
        {"flow-finish": "UNMEASURED"}, NO_UNEXPECTED,
        "listing did not complete cleanly: reason=exited exit_code=1",
    )
    after = ({"flow-finish": "discovered"}, NO_UNEXPECTED, None)
    readiness = readiness_from_discovery_listings(DECLARED, before, after)
    assert readiness["baseline_absence"] == "UNKNOWN", readiness
    assert readiness["baseline_absence"] != "SATISFIED"


def test_a_declared_skill_already_listed_before_delivery_is_contamination() -> None:
    """A declared skill already discovered BEFORE delivery is contamination
    (an earlier attempt's leftover state, or a container that did not start
    clean) - baseline_absence must read VIOLATED, not SATISFIED."""
    before = ({"flow-finish": "discovered"}, NO_UNEXPECTED, None)
    after = ({"flow-finish": "discovered"}, NO_UNEXPECTED, None)
    readiness = readiness_from_discovery_listings(DECLARED, before, after)
    assert readiness["baseline_absence"] == "VIOLATED", readiness


def test_an_undeclared_skill_already_listed_before_delivery_is_also_contamination() -> None:
    """Cross-model review on #150-D's predecessor: a baseline that already
    lists some OTHER, undeclared skill - an image-shipped or leftover one -
    is exactly the hazard that could make a degraded arm pass for the wrong
    reason (crediting the trial's own instructions for behaviour the
    baseline environment already supplied). Must VIOLATE baseline_absence
    even though every DECLARED skill is correctly absent."""
    before = ({"flow-finish": "not-discovered"}, frozenset({"some-other-skill"}), None)
    after = ({"flow-finish": "discovered"}, NO_UNEXPECTED, None)
    readiness = readiness_from_discovery_listings(DECLARED, before, after)
    assert readiness["baseline_absence"] == "VIOLATED", readiness
    assert "some-other-skill" in str(readiness["baseline_absence_detail"])


def test_an_undeclared_skill_only_seen_after_delivery_does_not_affect_discovery() -> None:
    """`after`'s own `unexpected` plays no part in discovery_canary - an
    undeclared skill appearing alongside a freshly-delivered one says
    nothing about whether delivery of the DECLARED skill worked."""
    before = ({"flow-finish": "not-discovered"}, NO_UNEXPECTED, None)
    after = ({"flow-finish": "discovered"}, frozenset({"some-other-skill"}), None)
    readiness = readiness_from_discovery_listings(DECLARED, before, after)
    assert readiness["discovery_canary"] == "SATISFIED", readiness


def test_multiple_declared_skills_all_must_be_discovered_to_satisfy() -> None:
    declared = frozenset({"flow-finish", "second-skill"})
    before = (
        {"flow-finish": "not-discovered", "second-skill": "not-discovered"}, NO_UNEXPECTED, None,
    )
    after = ({"flow-finish": "discovered", "second-skill": "not-discovered"}, NO_UNEXPECTED, None)
    readiness = readiness_from_discovery_listings(declared, before, after)
    assert readiness["discovery_canary"] == "VIOLATED", readiness


def test_a_degraded_arms_mutated_but_still_present_skill_still_satisfies_discovery() -> None:
    """A degraded arm mutates a skill's CONTENT but the file stays in place
    and still lists - readiness cannot and must not discriminate normal vs
    degraded (that is the grader's job). Confirms #133 item 4's per-entry
    concern is moot for this path: this readiness is already per-entry,
    independent of whatever DockerBackend.install() itself would report."""
    before = ({"flow-finish": "not-discovered"}, NO_UNEXPECTED, None)
    after = ({"flow-finish": "discovered"}, NO_UNEXPECTED, None)  # mutated content, same filename, still listed
    readiness = readiness_from_discovery_listings(DECLARED, before, after)
    assert readiness["discovery_canary"] == "SATISFIED", readiness
