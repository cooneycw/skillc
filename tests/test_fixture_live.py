"""#434 live-campaign wiring: the level3-fixture-live declaration, its
approval binding, the native containment stop, the run and its report.

No test here launches a container or a client: the run is exercised with
`rehearse="dry"`, or with `agent_trial.run_one_attempt` stubbed to return a
chosen record. The live path itself is rehearsed on a daemon with
`skillc level3-live --rehearse actor` (evals/level3/campaign-434-live/README.md)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from skillc import calibration, profile, trial
from skillc import calibration_run as cr
from skillc import collection_conformance as cc
from skillc import egress as eg
from skillc import fixture_live as fl
from skillc import matched_pilot as mp

ROOT = Path(__file__).resolve().parents[1]
DRAFT = ROOT / "evals" / "level3" / "campaign-434-live" / "measurement-declaration.json"
INVENTORY = ROOT / "evals" / "subjects" / "cpp-codex-flow-auto-86641e8" / "evidence" / "inventory.json"


def _draft() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(DRAFT.read_text(encoding="utf-8"))
    return data


def _approve(data: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(data)
    out["approval"] = {"by": "owner", "at": "2026-10-18", "source": "test", "attempts_per_case": out["attempts_per_case"],
                       "profile_inventory_digest": profile.inventory_digest(json.loads(INVENTORY.read_text()))}
    out["approval"]["declaration_digest"] = calibration.declaration_digest(out)
    return out


def _with_attempts(data: dict[str, Any], n: int) -> dict[str, Any]:
    out = copy.deepcopy(data)
    out["attempts_per_case"] = n
    out["case_order"]["sequence"] = calibration.derive_arm_order(out["case_order"]["seed"], out["cases"], n)
    out["shared"]["total_seconds"] = out["shared"]["per_attempt_seconds"] * 2 * n
    return out


# ------------------------------------------------------------- the declaration

def test_the_committed_draft_parses_and_its_identities_are_the_repositorys() -> None:
    declaration = fl.load_declaration(DRAFT)
    fl.require_approved(declaration, ROOT, approval_required=False)
    assert declaration.cases == ("clean", "twin") and declaration.attempts_per_case == 1
    assert declaration.shared["model"] == "gpt-6-astra" and declaration.shared["client"]["version"] == "0.157.1"


#: The digest of the measurement approval package sent for the owner's decision
#: (2026-10-18, re-checked at a0edf35). A stamp must name exactly this.
PACKAGED_DIGEST = "sha256:7eabd370b2d456293f41f39d74d91bac405cef9e31ec2b8fae80cba573e2956f"


def test_the_committed_declaration_is_the_packaged_one() -> None:
    assert fl.load_declaration(DRAFT).digest == PACKAGED_DIGEST


def test_the_committed_draft_is_not_approved() -> None:
    """It is a DRAFT: nothing may spend on it until the owner approves its digest."""
    with pytest.raises(fl.LiveRefused, match="no approval record"):
        fl.require_approved(fl.load_declaration(DRAFT), ROOT)


@pytest.mark.parametrize(("mutate", "match"), [
    (lambda d: d.update(kind="calibration-declaration"), "not a level3-fixture-live"),
    (lambda d: d["case_order"]["sequence"].reverse(), "derived, not chosen"),
    (lambda d: d.update(cases=["clean", "clean"]), "distinct"),
    (lambda d: d["tolerance"].pop("non_evaluable_per_case"), "tolerance"),  # C2
    (lambda d: d["shared"]["client"].update(name="claude"), "codex"),
    (lambda d: d["shared"]["agent_network"].update(allowlist_digest="sha256:" + "0" * 64), "agent_network"),  # C4
    (lambda d: d["shared"]["image"].update(receipt_sha256="85d48b0f"), "receipt_sha256"),  # C3
    (lambda d: d.update(run_store="/tmp/skillc-live"), "not durable"),  # C5
    (lambda d: d["shared"].update(total_seconds=60), "less than one attempt"),
])
def test_a_malformed_declaration_is_refused(mutate: Any, match: str) -> None:
    data = _draft()
    mutate(data)
    with pytest.raises(fl.LiveRefused, match=match):
        fl.parse_declaration(data)


@pytest.mark.parametrize(("mutate", "match"), [
    (lambda d: d["shared"].update(model="gpt-6-astra (PENDING)"), "placeholder"),  # C1
    (lambda d: d["shared"].update(model=""), "identities not recorded"),
    (lambda d: d["task"].update(goal_sha256="0" * 64), "differ from the repository"),
    (lambda d: d["task"]["base_trees"].update(clean="0" * 40), "differ from the repository"),
    (lambda d: d["task"].update(path="evals/level3/gate-stops-early"), "task.path"),
])
def test_an_identity_that_is_not_recorded_or_not_the_repositorys_is_refused(mutate: Any, match: str) -> None:
    data = _draft()
    mutate(data)
    with pytest.raises(fl.LiveRefused, match=match):
        fl.require_approved(fl.parse_declaration(data), ROOT, approval_required=False)


def test_an_approval_binds_the_exact_declaration() -> None:
    approved = _approve(_draft())
    fl.require_approved(fl.parse_declaration(approved), ROOT)  # the green case
    changed = copy.deepcopy(approved)
    changed["task"]["instruction"] += " Be brief."  # the prompt is an identity
    with pytest.raises(fl.LiveRefused, match="does not bind this exact declaration"):
        fl.require_approved(fl.parse_declaration(changed), ROOT)


@pytest.mark.parametrize(("mutate", "match"), [
    (lambda a: a.update(attempts_per_case=5), "attempts_per_case"),
    (lambda a: a.update(profile_inventory_digest="sha256:" + "0" * 64), "profile_inventory_digest"),
    (lambda a: a.pop("by"), "approval.by"),
])
def test_an_approval_that_does_not_name_this_schedule_or_closure_is_refused(mutate: Any, match: str) -> None:
    approved = _approve(_draft())
    mutate(approved["approval"])
    with pytest.raises(fl.LiveRefused, match=match):
        fl.require_approved(fl.parse_declaration(approved), ROOT)


def test_the_prompt_is_goal_then_the_declared_instruction() -> None:
    declaration = fl.load_declaration(DRAFT)
    text = fl.prompt(declaration, ROOT)
    assert text.startswith("/flow:auto 1\n\n") and "/work/repo" in text and "flow-auto" in text


# ------------------------------------------------------- the containment stop

ALLOWLIST = eg.allowlist_digest()


def _clean_record(**changes: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "disposition": "captured",
        "observation": {"server_side_tool_uses": [],
                        "transcript_response_items_inspected": 4,
                        "transcript_line_types": {"response_item/message": 4, "session_meta": 1},
                        "egress": {"status": "read", "allowlist_digest": ALLOWLIST, "unparsed_lines": 0,
                                   "allowed": {"chatgpt.com:443": 12, "auth.openai.com:443": 1}, "denied": {}},
                        "run_metadata": {"model": "gpt-6-astra", "reasoning_effort": "high",
                                         "token_usage": {"total_tokens": 1000, "input_tokens": 900}}},
        "fixture": {"codex_guard": {"status": "zero", "top_level": 1, "confirmed": 0, "suspected": 0}},
        "graded": {"status": "PASS", "criteria": [{"id": "source-unmodified", "outcome": "SATISFIED"}]},
    }
    for path, value in changes.items():
        node = record
        *parents, last = path.split(".")
        for key in parents:
            node = node[key]
        if value is _DELETE:
            node.pop(last)
        else:
            node[last] = value
    return record


_DELETE = object()


def test_a_clean_dispatched_attempt_triggers_no_stop() -> None:
    assert fl.containment_trigger(_clean_record(), allowlist_digest=ALLOWLIST) is None


@pytest.mark.parametrize(("change", "match"), [
    ({"observation.server_side_tool_uses": ["web_search_call"]}, "server-side tool use observed"),
    ({"observation.server_side_tool_uses": _DELETE}, "census is unavailable"),
    ({"observation.transcript_response_items_inspected": 0}, "census is incomplete"),
    ({"observation.transcript_line_types": {"<unparseable>": 1, "response_item/message": 3}}, "census is incomplete"),
    ({"observation.transcript_census_error": "ValueError: x"}, "census is incomplete"),
    ({"observation.egress": {"status": "unread", "reason": "gone"}}, "egress proxy log was not read"),
    ({"observation.egress.allowlist_digest": "sha256:" + "1" * 64}, "the proxy recorded allowlist"),
    ({"observation.egress.allowed": {"chatgpt.com:443": 3, "github.com:443": 1}}, "outside #442's allowlist"),
    ({"observation.egress.allowed": {"chatgpt.com:80": 1}}, "outside #442's allowlist"),
    ({"observation.egress.allowed": {"chatgpt.com": 1}}, "outside #442's allowlist"),
    ({"observation.egress.unparsed_lines": 1}, "census is incomplete"),
    ({"observation.egress.allowed": _DELETE}, "census is incomplete"),
    ({"fixture.codex_guard": {"status": "observed", "confirmed": 1, "suspected": 0}}, "nested codex observed"),
    ({"fixture.codex_guard": {"status": "unknown"}}, "nested-codex count is unknown"),
    ({"fixture": _DELETE}, "nested-codex count is unknown"),
])
def test_each_trigger_stops_the_schedule(change: dict[str, Any], match: str) -> None:
    """One committed red per trigger: the stop is a gate nothing downstream re-derives."""
    trigger = fl.containment_trigger(_clean_record(**change), allowlist_digest=ALLOWLIST)
    assert trigger is not None and match in trigger


def test_an_attempt_that_never_launched_triggers_nothing() -> None:
    record = _clean_record(**{"observation.server_side_tool_uses": ["web_search_call"]})
    record["disposition"] = "unavailable"
    assert fl.containment_trigger(record, allowlist_digest=ALLOWLIST) is None


# ------------------------------------------------------------------- the run

def _treatment() -> cr.Treatment:
    return cr.Treatment(home_files={}, digest="sha256:" + "a" * 64, receipt_context=None,
                        gate_entrypoint=".claude/scripts/flow-finish-gate.sh",
                        skill_digests=({"path": ".codex/skills/flow-auto/SKILL.md",
                                        "body_digest": "sha256:" + "b" * 64,
                                        "description_digest": "sha256:" + "c" * 64},))


def test_a_dry_rehearsal_accounts_for_every_slot_and_reports_unapproved(tmp_path: Path) -> None:
    declaration = fl.load_declaration(DRAFT)
    experiment, outcomes, stop = fl.run_live(
        declaration, root=ROOT, run_dir=tmp_path, treatment=_treatment(), image_digest=None,
        backends=lambda: (None, None), client_argv=["codex", "exec"], credential_explicit_path=None, rehearse="dry")
    assert [o.scheduled.arm for o in outcomes] == list(declaration.order)
    assert {o.record["disposition"] for o in outcomes} == {"unavailable"} and stop.trigger is None
    report = fl.build_report(declaration, experiment, outcomes, stop, rehearse="dry", approved=False)
    assert report["approved"] is False and report["token_cap"] == fl.TOKEN_CAP_STATEMENT
    assert report["cases"]["clean"]["non_evaluable"] == 1  # nothing ran, nothing evaluable


def test_a_live_run_needs_an_approved_declaration(tmp_path: Path) -> None:
    unapproved = _draft()
    unapproved.pop("approval", None)
    with pytest.raises(fl.LiveRefused, match="no approval record"):
        fl.run_live(fl.parse_declaration(unapproved), root=ROOT, run_dir=tmp_path, treatment=_treatment(),
                    image_digest=None, backends=lambda: (None, None), client_argv=["codex", "exec"],
                    credential_explicit_path=None)
    assert not (tmp_path / "store").exists()  # ADR 0005: nothing before authorization


def test_a_containment_stop_finalizes_every_later_attempt_not_run(tmp_path: Path,
                                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    declaration = fl.parse_declaration(_approve(_with_attempts(_draft(), 2)))
    records = iter([_clean_record(), _clean_record(**{"observation.server_side_tool_uses": ["web_search_call"]})])
    from skillc import agent_trial
    seen: list[dict[str, Any]] = []

    def fake_attempt(**kwargs: Any) -> dict[str, Any]:
        seen.append(kwargs)
        return next(records)

    monkeypatch.setattr(agent_trial, "run_one_attempt", fake_attempt)
    experiment, outcomes, stop = fl.run_live(
        declaration, root=ROOT, run_dir=tmp_path, treatment=_treatment(), image_digest=None,
        backends=lambda: (None, None), client_argv=list(cc.DEFAULT_CLIENT_ARGVS["codex"]),
        credential_explicit_path=None)
    assert len(seen) == 2 and len(outcomes) == 4
    assert stop.trigger is not None and "server-side" in stop.trigger and stop.at_attempt == outcomes[1].scheduled.attempt_id
    assert [o.record["disposition"] for o in outcomes[2:]] == ["not-run", "not-run"]
    assert all("containment stop" in str(o.record["reason"]) for o in outcomes[2:])
    # The model is pinned at launch, and the prompt is the declared one.
    argv = seen[0]["base_argv"]
    assert argv[-4:] == ["-m", "gpt-6-astra", "-c", 'model_reasoning_effort="high"']
    assert eg.missing_server_side_flags(argv) == []
    assert seen[0]["prompt"] == fl.prompt(declaration, ROOT) and seen[0]["fixture"] is not None
    report = fl.build_report(declaration, experiment, outcomes, stop, rehearse=None, approved=True)
    assert report["containment_stop"]["stopped"] is True and not fl.succeeded(report, scheduled=4)
    entry = report["attempts"][0]
    assert entry["tokens"] == {"total_tokens": 1000, "input_tokens": 900} and entry["source_unmodified"] == "SATISFIED"
    first_case = outcomes[0].scheduled.arm
    assert report["cases"][first_case]["tokens_total_known"] >= 1000


def test_a_live_run_cannot_override_the_total_cap(tmp_path: Path) -> None:
    declaration = fl.parse_declaration(_approve(_draft()))
    with pytest.raises(fl.LiveRefused, match="total_seconds"):
        fl.run_live(declaration, root=ROOT, run_dir=tmp_path, treatment=_treatment(), image_digest=None,
                    backends=lambda: (None, None), client_argv=["codex", "exec"], credential_explicit_path=None,
                    total_seconds=1.0)


def test_the_rehearsal_actor_keeps_its_arguments_and_carries_the_server_side_off_flags() -> None:
    task_root = ROOT / fl.TASK_PATH
    for case in fl.CASES:
        argv, home = fl.rehearsal_actor(task_root, case)
        assert argv[2:4] == ["top-level", "no-gate"]  # actor.py's argv[1], argv[2]
        assert eg.missing_server_side_flags(argv) == []
        assert any(name.endswith("actions.json") for name in home)


def test_report_tokens_are_unknown_when_the_rollout_has_none(tmp_path: Path) -> None:
    declaration = fl.load_declaration(DRAFT)
    store = trial.open_store(tmp_path / "store", forbidden=[])
    experiment, schedule = fl.plan_live(declaration, store, root=ROOT, treatment=_treatment(), image_digest=None)
    record = _clean_record(**{"observation.run_metadata": {}})
    outcomes = [mp.AttemptOutcome(s, record, 10.0) for s in schedule]
    report = fl.build_report(declaration, experiment, outcomes, fl.Stop(), rehearse=None, approved=True)
    assert {e["tokens"] for e in report["attempts"]} == {fl.UNKNOWN}
    assert report["cases"]["clean"]["tokens_unknown_attempts"] == 1


def _report(dispositions: list[tuple[str, str]], *, stopped: bool = False, tolerance_ok: bool = True) -> dict[str, Any]:
    attempts = [{"case": c, "disposition": d, "model_eligible": True if d in mp.DISPATCHED else "n/a",
                 "graded_status": "PASS" if d == "captured" else "UNKNOWN"} for c, d in dispositions]
    return {"attempts": attempts, "containment_stop": {"stopped": stopped},
            "cases": {c: {"within_tolerance": tolerance_ok} for c in {c for c, _ in dispositions}}}


def test_live_success_needs_attempts_that_ran() -> None:
    good = [("clean", "captured"), ("twin", "captured")]
    assert fl.succeeded(_report(good), scheduled=2)
    assert not fl.succeeded({"attempts": [], "containment_stop": {"stopped": False}, "cases": {}}, scheduled=2)
    assert not fl.succeeded(_report([("clean", "unavailable"), ("twin", "unavailable")]), scheduled=2)
    assert not fl.succeeded(_report([("clean", "captured"), ("twin", "unavailable")]), scheduled=2)
    assert not fl.succeeded(_report(good, tolerance_ok=False), scheduled=2)
    assert not fl.succeeded(_report(good, stopped=True), scheduled=2)
    assert not fl.succeeded(_report(good[:1]), scheduled=2)


def test_rehearsal_success_is_mode_specific() -> None:
    unavailable = _report([("clean", "unavailable"), ("twin", "unavailable")])
    captured = _report([("clean", "captured"), ("twin", "captured")])
    assert fl.rehearsal_succeeded(unavailable, scheduled=2, mode="dry")
    assert not fl.rehearsal_succeeded(unavailable, scheduled=2, mode="actor")
    assert fl.rehearsal_succeeded(captured, scheduled=2, mode="actor")
    assert not fl.rehearsal_succeeded(captured, scheduled=2, mode="dry")


def _record_from_raw(raw: bytes) -> dict[str, Any]:
    """A clean record whose census comes from `raw` through the production parser."""
    from skillc import agent_trial as at
    census = at.transcript_census("codex", raw.decode("utf-8", errors="replace"))
    census["server_side_tool_uses"] = at.server_side_tool_uses(raw, census.get("transcript_line_types"))  # type: ignore[arg-type]
    record = _clean_record()
    for key in ("transcript_response_items_inspected", "transcript_line_types"):
        record["observation"].pop(key)
    record["observation"].update(census)
    return record


_SESSION = json.dumps({"type": "session_meta", "payload": {"cli_version": "0.157.1"}})
_MESSAGE = json.dumps({"type": "response_item", "payload": {"type": "message", "role": "assistant",
                                                            "content": [{"type": "output_text", "text": "done"}]}})


@pytest.mark.parametrize(("raw", "stops"), [
    ((_SESSION + "\n" + _MESSAGE + "\n").encode(), False),  # the green case
    (b"", True),  # an empty transcript inspects nothing
    ((_SESSION + "\n" + _MESSAGE + '\n{"type":"response_item","payload":{"type":"web_search_call"').encode(), True),
])
def test_the_census_must_cover_the_transcript_through_the_production_parser(raw: bytes, stops: bool) -> None:
    trigger = fl.containment_trigger(_record_from_raw(raw), allowlist_digest=ALLOWLIST)
    assert (trigger is not None) is stops, trigger


def test_a_rehearsal_is_identifiable_in_the_ledger_before_any_report(tmp_path: Path) -> None:
    unapproved = _draft()
    unapproved.pop("approval", None)
    declaration = fl.parse_declaration(unapproved)
    experiment, _, _ = fl.run_live(declaration, root=ROOT, run_dir=tmp_path, treatment=_treatment(),
                                   image_digest=None, backends=lambda: (None, None), client_argv=["codex", "exec"],
                                   credential_explicit_path=None, rehearse="dry")
    ledger = json.loads((experiment.root / trial.LEDGER).read_text())
    assert ledger["experiment_id"].startswith(f"{fl.EXPERIMENT_LABEL}-rehearsal-dry-")
    configs = [json.loads(trial.read_object(experiment, t["config"]["digest"])) for t in ledger["trials"]]
    assert {(c["mode"], c["approved"]) for c in configs} == {("dry", False)}


def _one_case(n: int) -> dict[str, Any]:
    out = copy.deepcopy(_draft())
    out["cases"] = ["clean"]
    out["attempts_per_case"] = n
    out["case_order"]["sequence"] = calibration.derive_arm_order(out["case_order"]["seed"], ["clean"], n)
    out["shared"]["total_seconds"] = out["shared"]["per_attempt_seconds"] * n
    return out


def test_a_trigger_on_attempt_1_of_3_halts_the_schedule_not_just_the_attempt(tmp_path: Path,
                                                                             monkeypatch: pytest.MonkeyPatch) -> None:
    """The failure #287 met with an external watcher: the attempt ended, the
    schedule went on. Here attempts 2 and 3 are never dispatched."""
    declaration = fl.parse_declaration(_approve(_one_case(3)))
    from skillc import agent_trial
    calls: list[str] = []

    def fake_attempt(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs["attempt_id"])
        return _clean_record(**{"fixture.codex_guard": {"status": "observed", "confirmed": 1, "suspected": 0}})

    monkeypatch.setattr(agent_trial, "run_one_attempt", fake_attempt)
    _, outcomes, stop = fl.run_live(
        declaration, root=ROOT, run_dir=tmp_path, treatment=_treatment(), image_digest=None,
        backends=lambda: (None, None), client_argv=list(cc.DEFAULT_CLIENT_ARGVS["codex"]),
        credential_explicit_path=None)
    assert calls == [outcomes[0].scheduled.attempt_id]  # dispatched once
    assert [o.record["disposition"] for o in outcomes] == ["captured", "not-run", "not-run"]
    assert stop.at_attempt == outcomes[0].scheduled.attempt_id and "nested codex" in str(stop.trigger)


def test_an_operator_interrupt_halts_the_schedule_and_accounts_for_every_slot(tmp_path: Path,
                                                                            monkeypatch: pytest.MonkeyPatch) -> None:
    declaration = fl.parse_declaration(_approve(_one_case(3)))
    from skillc import agent_trial
    calls: list[str] = []

    def interrupted(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs["attempt_id"])
        raise KeyboardInterrupt

    monkeypatch.setattr(agent_trial, "run_one_attempt", interrupted)
    _, outcomes, stop = fl.run_live(
        declaration, root=ROOT, run_dir=tmp_path, treatment=_treatment(), image_digest=None,
        backends=lambda: (None, None), client_argv=list(cc.DEFAULT_CLIENT_ARGVS["codex"]),
        credential_explicit_path=None)
    assert len(calls) == 1 and len(outcomes) == 3 and stop.trigger == "operator interrupt"
    assert all(o.record["disposition"] in ("not-run", "inconclusive", "unavailable") for o in outcomes)


def test_editing_the_instruction_changes_the_declaration_digest() -> None:
    """The prompt's instruction is an identity: any edit moves the digest an approval binds."""
    data = _draft()
    before = fl.parse_declaration(data).digest
    data["task"]["instruction"] = data["task"]["instruction"].replace("/work/repo", "/work/other")
    assert fl.parse_declaration(data).digest != before
