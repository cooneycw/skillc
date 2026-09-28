"""Tests for `agent_trial.readiness_from_discovery_listings` (#150-D).

Pure-function tests: no fake docker, no backend, no container. This is
deliberate - `readiness_from_discovery_listings` takes two already-obtained
listing results (`demo.run_subject_discovery`'s own return shape) and scores
them; it does not itself talk to a container. `tests/test_agent_trial.py`
(the fake-docker end-to-end suite) is where the eventual wiring that
actually calls the listing inside a container belongs, once #150-C and
#150-B2 land (Refs #150-D).

ADR 0005's "yes, narrow B1" ruling names three required red cases; this file
carries the two that are expressible purely from listing results (the third,
"an empty baseline arm still yields the B1 stand-in, not a receipt", is a
CALLER decision - whether to call this function at all - not something this
function itself can fail on, since it is never given an empty `declared`
set by a caller that made that decision correctly. It belongs with the
eventual `run_one_attempt` wiring, not here.).
"""

from __future__ import annotations

from skillc.agent_trial import readiness_from_discovery_listings

DECLARED = frozenset({"flow-finish"})

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
