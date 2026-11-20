"""The #620 PR-B verified adapter (skillc/task_protocol_adapter.py, B6), over
REAL sealed journals built from the merged journal, machine and lease
modules (tests/task_protocol_fixture.py)."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
import task_protocol_fixture as tpf

from skillc import live_wave, wave_wake_capture
from skillc import task_protocol_adapter as adapter
from skillc import task_protocol_journal as tj

DECL = "sha256:" + "d" * 64
DEADLINE = "sha256:" + "ab" * 32
ROLES = ("integrator", "worker")
#: A deadline whose float and integer cutoffs disagree at round(d * 1e9) ns.
#: It is a value compared, never waited on.
FLIP_DEADLINE = 0.0011234567  # timing: must-fire - the float/integer cutoff disagreement under test
HEALTHY = [("integrator", "offer", 1, 500_000_000), ("worker", "offer", 1, 600_000_000),
           ("integrator", "ack", 2, 1_000_000_000), ("worker", "ack", 2, 1_100_000_000),
           ("worker", "complete", 3, 2_100_000_000), ("integrator", "complete", 3, 4_000_000_000)]


def _join(built: tpf.Built, wake: wave_wake_capture.Context | None = None) -> adapter.ClockJoin:
    return adapter.ClockJoin(built.inventory.digest, wake.digest if wake else None,
                             built.inventory.clock_origin_ns)


def _adapt(built: tpf.Built, plan: live_wave.WavePlan, **changes: Any) -> dict[str, Any]:
    args: dict[str, Any] = {"root": built.root, "reference": built.reference,
                            "context": built.context, "inventory": built.inventory, "plan": plan,
                            "deadline_ns": built.deadline_ns, "join": _join(built)}
    args.update(changes)
    return adapter.adapt(**args)


def _rows(result: dict[str, Any], role: str) -> list[dict[str, Any]] | None:
    raw = result["projections"][role]
    return None if raw is None else [json.loads(line) for line in raw.splitlines()]


def test_a_healthy_journal_projects_exactly_the_pr_a_rows(tmp_path: Path) -> None:
    plan = tpf.plan_of(ROLES)
    built = tpf.build(tmp_path / "j", plan, DECL, DEADLINE, HEALTHY)
    result = _adapt(built, plan)
    assert result["status"] == "CAPTURED" and result["reasons"] == []
    for role, ack, complete in (("integrator", 1.0, 4.0), ("worker", 1.1, 2.1)):
        binding = next(r for r in plan.roles if r.role == role)
        identity = {"wave_id": plan.wave_id, "role": role, "attempt_id": binding.attempt_id,
                    "session_id": binding.session_id, "task": binding.task,
                    "generation": binding.generation, "revision": binding.revision,
                    "nonce": binding.nonce}
        assert _rows(result, role) == [{**identity, "op": "ack", "elapsed": ack},
                                       {**identity, "op": "complete", "elapsed": complete}]
        assert result["diagnostic"]["roles"][role]["coverage"] == "complete"
    assert result["diagnostic"]["primary_effect"] == "none (decision 5)"


def test_a_retry_is_never_a_second_semantic_completion(tmp_path: Path) -> None:
    plan = tpf.plan_of(ROLES)
    steps = HEALTHY + [("worker", "complete", 3, 5_000_000_000)]
    result = _adapt(tpf.build(tmp_path / "j", plan, DECL, DEADLINE, steps), plan)
    assert [r["op"] for r in _rows(result, "worker") or []] == ["ack", "complete"]
    assert result["diagnostic"]["roles"]["worker"]["retries"] == 1


def test_violations_are_diagnostic_and_attributed_to_the_sender(tmp_path: Path) -> None:
    plan = tpf.plan_of(ROLES)
    steps = HEALTHY + [("worker", "complete", 4, 5_000_000_000),
                       ("worker", "ack", 3, 5_500_000_000)]
    result = _adapt(tpf.build(tmp_path / "j", plan, DECL, DEADLINE, steps), plan)
    worker = result["diagnostic"]["roles"]["worker"]
    assert worker["violations"] == {"after-complete": 1, "protocol-conflict": 1}
    assert result["diagnostic"]["roles"]["integrator"]["violations"] == {}
    # The projection keeps exactly the first ack and first completion.
    assert [r["op"] for r in _rows(result, "worker") or []] == ["ack", "complete"]
    assert adapter.violation_counts(result) == {"after-complete": 1, "protocol-conflict": 1}


def test_refusals_late_and_offers_are_counted(tmp_path: Path) -> None:
    plan = tpf.plan_of(ROLES)
    steps = [("integrator", "offer", 1, 1), ("integrator", "refuse", 2, 2, "blocked"),
             ("worker", "offer", 1, 3), ("worker", "ack", 2, 10_000_000_001)]
    result = _adapt(tpf.build(tmp_path / "j", plan, DECL, DEADLINE, steps), plan)
    integrator, worker = (result["diagnostic"]["roles"][r] for r in ROLES)
    assert integrator["offers"] == 1 and integrator["refusals"] == {"blocked": 1}
    assert worker["late"] == 1 and worker["rejections"] == {"late": 1}
    assert result["projections"] == {"integrator": None, "worker": None}


# -- the integer cutoff ---------------------------------------------------------


@pytest.mark.parametrize("offset,projected", [(-1, True), (0, True), (1, False)])
def test_the_integer_deadline_boundary(tmp_path: Path, offset: int, projected: bool) -> None:
    plan = tpf.plan_of(ROLES)
    at = 10_000_000_000 + offset
    steps = [("worker", "offer", 1, 1), ("worker", "ack", 2, at)]
    result = _adapt(tpf.build(tmp_path / "j", plan, DECL, DEADLINE, steps), plan)
    rows = _rows(result, "worker")
    assert (rows is not None and rows[0]["op"] == "ack") is projected


def test_a_real_float_cutoff_flip_is_refused_not_rounded(tmp_path: Path) -> None:
    deadline = FLIP_DEADLINE
    plan = tpf.plan_of(ROLES, deadline=deadline)
    deadline_ns = round(deadline * 1e9)
    at = deadline_ns
    # The case must stay a REAL flip: integer says on time, float says late.
    assert at <= deadline_ns
    assert not (at / 1e9 <= deadline)
    steps = [("worker", "offer", 1, 1), ("worker", "ack", 2, at)]
    result = _adapt(tpf.build(tmp_path / "j", plan, DECL, DEADLINE, steps), plan)
    assert result["projections"]["worker"] is None
    assert result["reasons"] == ["float-cutoff-flip"]
    assert result["diagnostic"]["roles"]["worker"]["refused"] == "float-cutoff-flip"


def test_a_float_only_cutoff_is_caught(tmp_path: Path) -> None:
    """Blind variant: compare in float seconds only, as the old seam would."""
    deadline = FLIP_DEADLINE
    plan = tpf.plan_of(ROLES, deadline=deadline)
    at = round(deadline * 1e9)
    built = tpf.build(tmp_path / "j", plan, DECL, DEADLINE,
                      [("worker", "offer", 1, 1), ("worker", "ack", 2, at)])
    honest = _adapt(built, plan)
    float_only_on_time = at / 1e9 <= deadline
    assert float_only_on_time is False and honest["reasons"] == ["float-cutoff-flip"]


def test_a_deadline_that_does_not_match_the_plan_is_refused(tmp_path: Path) -> None:
    plan = tpf.plan_of(ROLES)
    built = tpf.build(tmp_path / "j", plan, DECL, DEADLINE, HEALTHY)
    assert _adapt(built, plan, deadline_ns=built.deadline_ns + 1)["reasons"] == ["deadline-differs"]


# -- coverage and binding --------------------------------------------------------------


def test_an_unbound_role_or_capacity_event_gets_no_projection(tmp_path: Path) -> None:
    plan = tpf.plan_of(ROLES)
    steps = [s for s in HEALTHY if s[0] == "integrator"]
    built = tpf.build(tmp_path / "a", plan, DECL, DEADLINE, steps, unbound=["worker"])
    result = _adapt(built, plan)
    assert result["projections"]["worker"] is None and result["projections"]["integrator"]
    capped = _adapt(tpf.build(tmp_path / "b", plan, DECL, DEADLINE, HEALTHY,
                              capacity_for=["integrator"]), plan)
    assert capped["projections"]["integrator"] is None and capped["projections"]["worker"]
    assert capped["diagnostic"]["roles"]["integrator"]["coverage"] == "unknown"


def test_unauthenticated_ingress_is_counted_against_nobody(tmp_path: Path) -> None:
    plan = tpf.plan_of(ROLES)

    def stranger(journal: tj.Journal, _leases: Any) -> None:
        journal.append("rejection", principal=None, reason="unauthenticated-peer", length=12,
                       content_digest="sha256:" + "3" * 64)

    result = _adapt(tpf.build(tmp_path / "j", plan, DECL, DEADLINE, HEALTHY, extra=stranger), plan)
    assert result["diagnostic"]["unauthenticated_ingress"] == 1
    assert all(not r["rejections"] for r in result["diagnostic"]["roles"].values())


@pytest.mark.parametrize("change", ["population", "attempt", "slot", "role-order"])
def test_a_journal_bound_to_something_else_projects_nothing(tmp_path: Path, change: str) -> None:
    plan = tpf.plan_of(ROLES)
    built = tpf.build(tmp_path / "j", plan, DECL, DEADLINE, HEALTHY)
    if change == "population":
        other = tpf.inventory_for(plan, DECL, origin_ns=1)
        result = _adapt(built, plan, inventory=other, join=adapter.ClockJoin(other.digest, None, 1))
    elif change == "attempt":
        result = _adapt(built, replace(plan, wave_id="wave-0002"))
    elif change == "slot":
        roles = tuple(replace(r, nonce="other-nonce") if r.role == "worker" else r
                      for r in plan.roles)
        result = _adapt(built, replace(plan, roles=roles))
    else:
        result = _adapt(built, replace(plan, roles=tuple(reversed(plan.roles))))
    assert result["status"] == "UNKNOWN" and set(result["projections"].values()) == {None}


@pytest.mark.parametrize("join", ["missing", "inventory", "origin", "wake-digest",
                                  "wake-unexpected"])
def test_the_clock_join_must_match_every_held_binding(tmp_path: Path, join: str) -> None:
    plan = tpf.plan_of(ROLES)
    built = tpf.build(tmp_path / "j", plan, DECL, DEADLINE, HEALTHY)
    wake = wave_wake_capture.Context(plan.wave_id, DECL, "sha256:" + "f" * 64, ROLES, DEADLINE,
                                     "monotonic", origin_ns=built.inventory.clock_origin_ns)
    good = _join(built, wake)
    assert _adapt(built, plan, join=good, wake=wake)["status"] == "CAPTURED"
    bad: Any = {"missing": None, "inventory": replace(good, inventory_digest="sha256:" + "0" * 64),
                "origin": replace(good, origin_ns=7),
                "wake-digest": replace(good, wake_context_digest="sha256:" + "0" * 64),
                "wake-unexpected": good}[join]
    result = _adapt(built, plan, join=bad, wake=None if join == "wake-unexpected" else wake)
    assert result["reasons"] == ["clock-join-unavailable"]
    assert set(result["projections"].values()) == {None}


def test_an_unverifiable_journal_projects_nothing(tmp_path: Path) -> None:
    plan = tpf.plan_of(ROLES)
    built = tpf.build(tmp_path / "j", plan, DECL, DEADLINE, HEALTHY)
    held = replace(built.reference, digest="sha256:" + "0" * 64)
    assert _adapt(built, plan, reference=held)["reasons"] == ["journal-unverifiable"]


def test_every_journal_kind_is_accounted() -> None:
    assert set(adapter.ACCOUNTED) == set(tj.KINDS) - {"capture-start", "capture-seal"}


def test_an_adapter_that_drops_unknown_kinds_silently_is_caught(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plan = tpf.plan_of(ROLES)
    built = tpf.build(tmp_path / "j", plan, DECL, DEADLINE, HEALTHY)
    monkeypatch.delitem(adapter.ACCOUNTED, "binding")
    assert _adapt(built, plan)["reasons"] == ["unaccounted-record-kind"]


def test_an_adapter_ignoring_coverage_is_caught(tmp_path: Path) -> None:
    plan = tpf.plan_of(ROLES)
    built = tpf.build(tmp_path / "j", plan, DECL, DEADLINE, HEALTHY, capacity_for=["worker"])
    honest = _adapt(built, plan)
    assert honest["projections"]["worker"] is None
    blind_rows = [r for r in tj.verify(built.root, built.reference, built.context)["records"]
                  if r["kind"] == "decision" and r["decision"] in adapter.PROJECTED
                  and r["principal"] == tpf.principal_of("worker")]
    assert len(blind_rows) == 2  # what a coverage-blind projection would have emitted


# -- the remaining planned blind variants (#811 review) --------------------------------


def test_a_projection_counting_retries_as_completions_is_caught(tmp_path: Path) -> None:
    """Blind variant: replay each retry as its original decision."""
    plan = tpf.plan_of(ROLES)
    steps = HEALTHY + [("worker", "complete", 3, 5_000_000_000)]
    built = tpf.build(tmp_path / "j", plan, DECL, DEADLINE, steps)
    records = tj.verify(built.root, built.reference, built.context)["records"]
    by_seq = {r["seq"]: r for r in records}
    replayed = [by_seq[r["original_seq"]] if r["kind"] == "retry" else r for r in records]
    blind = [r for r in replayed if r["kind"] == "decision"
             and r["decision"] == "completion-claimed"
             and r["principal"] == tpf.principal_of("worker")]
    honest = [r for r in _rows(_adapt(built, plan), "worker") or [] if r["op"] == "complete"]
    assert len(blind) == 2 and len(honest) == 1


def test_a_projection_taking_identity_from_the_journal_is_caught(tmp_path: Path) -> None:
    """Blind variant: name the row by the journal's principal, not the plan's
    role binding. The kernel would read it as the wrong assignment."""
    plan = tpf.plan_of(ROLES)
    built = tpf.build(tmp_path / "j", plan, DECL, DEADLINE, HEALTHY)
    honest = _rows(_adapt(built, plan), "worker") or []
    records = tj.verify(built.root, built.reference, built.context)["records"]
    blind_roles = {r["principal"] for r in records
                   if r["kind"] == "decision" and r["decision"] in adapter.PROJECTED}
    assert {r["role"] for r in honest} == {"worker"}
    assert "worker" not in blind_roles and tpf.principal_of("worker") in blind_roles
    binding = next(r for r in plan.roles if r.role == "worker")
    assert {r["attempt_id"] for r in honest} == {binding.attempt_id}
    assert all("attempt_id" not in r for r in records)  # the journal cannot supply it


def test_an_adapter_without_the_clock_join_is_caught(tmp_path: Path,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    plan = tpf.plan_of(ROLES)
    built = tpf.build(tmp_path / "j", plan, DECL, DEADLINE, HEALTHY)
    bad = replace(_join(built), origin_ns=7)
    assert _adapt(built, plan, join=bad)["reasons"] == ["clock-join-unavailable"]
    real = adapter._check_bindings

    def joinless(*args: Any) -> str | None:
        problem = real(*args)
        return None if problem == "clock-join-unavailable" else problem

    monkeypatch.setattr(adapter, "_check_bindings", joinless)
    assert _adapt(built, plan, join=bad)["status"] == "CAPTURED"
