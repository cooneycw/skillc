"""#434 live-campaign wiring: the level3-fixture-live declaration, its
approval binding, the native containment stop, the run and its report.

No test here launches a container or a client: the run is exercised with
`rehearse="dry"`, or with `agent_trial.run_one_attempt` stubbed to return a
chosen record. The live path itself is rehearsed on a daemon with
`skillc level3-live --rehearse actor` (evals/level3/campaign-434-live/README.md)."""

from __future__ import annotations

import copy
import functools
import importlib.util as _ilu
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from skillc import calibration, profile, trial
from skillc import calibration_run as cr
from skillc import codex_guard as cg
from skillc import collection_conformance as cc
from skillc import egress as eg
from skillc import fixture_live as fl
from skillc import matched_pilot as mp

ROOT = Path(__file__).resolve().parents[1]
DRAFT = ROOT / "evals" / "level3" / "campaign-434-live" / "measurement-declaration.json"
INVENTORY = ROOT / "evals" / "subjects" / "cpp-codex-flow-auto-86641e8" / "evidence" / "inventory.json"


@functools.lru_cache(maxsize=1)
def _identity() -> dict[str, Any]:
    return {k: v for k, v in fl.task_identity(ROOT).items() if k != "path"}


def _draft() -> dict[str, Any]:
    """The committed measurement declaration with its task identities re-derived
    from THIS tree. The committed file is the owner-approved record of a grader
    revision-2 run and is never edited; since grader revision 3 (#475) the
    repository refuses it (test_the_spent_measurement_declaration_is_refused...),
    so every test that needs a declaration this repository accepts starts here.
    Its approval, when kept, no longer binds it - exactly as a changed field."""
    data: dict[str, Any] = json.loads(DRAFT.read_text(encoding="utf-8"))
    data["task"].update(copy.deepcopy(_identity()))
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

def test_a_draft_at_this_trees_identities_parses_and_is_the_repositorys() -> None:
    declaration = fl.parse_declaration(_draft())
    fl.require_approved(declaration, ROOT, approval_required=False)
    assert declaration.cases == ("clean", "twin") and declaration.attempts_per_case == 1
    assert declaration.shared["model"] == "gpt-6-astra" and declaration.shared["client"]["version"] == "0.157.1"


#: The digest of the measurement approval package sent for the owner's decision
#: (2026-10-18, re-checked at a0edf35). A stamp must name exactly this.
PACKAGED_DIGEST = "sha256:7eabd370b2d456293f41f39d74d91bac405cef9e31ec2b8fae80cba573e2956f"


def test_the_committed_declaration_is_the_packaged_one() -> None:
    assert fl.load_declaration(DRAFT).digest == PACKAGED_DIGEST


def test_the_committed_declaration_carries_the_owners_approval_at_the_packaged_digest() -> None:
    """The stamp changed nothing the owner approved: the content digest is the
    packaged digest, and the approval names it."""
    declaration = fl.load_declaration(DRAFT)
    approval = declaration.approval
    assert approval is not None and approval["by"] == "owner (cooneycw)"
    assert declaration.digest == approval["declaration_digest"] == PACKAGED_DIGEST


def test_the_spent_measurement_declaration_is_refused_since_grader_revision_3() -> None:
    """The owner approved a run of grader REVISION 2 (#472). Revision 3 (#475)
    moved the grader, so the approval does not carry over: the committed file
    no longer authorizes anything, and the refusal names the grader identity.
    A campaign at revision 3 needs its own declaration and its own approval."""
    declaration = fl.load_declaration(DRAFT)
    assert declaration.task["grader_revision"] == "2"
    with pytest.raises(fl.LiveRefused, match=r"differ from the repository: \['grader_revision', 'grader_digest'\]"):
        fl.require_approved(declaration, ROOT)


def test_the_owners_approval_does_not_survive_a_changed_field() -> None:
    data = _approve(_draft())
    fl.require_approved(fl.parse_declaration(data), ROOT)  # approved as is
    data["shared"]["total_seconds"] = 7200
    with pytest.raises(fl.LiveRefused, match="does not bind this exact declaration"):
        fl.require_approved(fl.parse_declaration(data), ROOT)


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
    declaration = fl.parse_declaration(_draft())
    text = fl.prompt(declaration, ROOT)
    assert text.startswith("/flow:auto 1\n\n") and "/work/repo" in text and "flow-auto" in text


# ------------------------------------------------------- the containment stop

ALLOWLIST = eg.allowlist_digest()


def _clean_record(**changes: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "disposition": "captured",
        "observation": {"server_side_tool_uses": [],
                        "transcript_response_items_inspected": 4,
                        "transcript_unrecognized_types": [],
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
    # #486: format drift fails closed - an unread item type could be a server-side tool.
    ({"observation.transcript_unrecognized_types": ["local_shell_call"]}, "unrecognized response-item types"),
    ({"observation.transcript_unrecognized_types": _DELETE}, "could not assess its response-item types"),
    ({"observation.transcript_unrecognized_types": None}, "could not assess its response-item types"),
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
    declaration = fl.parse_declaration(_draft())
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
    declaration = fl.parse_declaration(_draft())
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


# ------------------------------------------- the campaign and its primary endpoint

CAMPAIGN = ROOT / "evals" / "level3" / "campaign-434-live" / "campaign-declaration.json"
#: The committed campaign declaration's digest, as it goes into the owner's
#: approval package. A changed field must change this line on purpose.
CAMPAIGN_DIGEST = "sha256:694e2b82658a3cf47827eef3650fe1782d1c0d39d036cef49a74a23f040bacf2"
ENDPOINT = ("verdict", "evidence-real", "looked-before-concluding", "no-pr-merge-close", "source-unmodified",
            "case-disposition")


def test_the_campaign_declaration_carries_the_owners_approval_at_the_packaged_digest() -> None:
    """The owner approved the campaign on 2026-10-20 ("1(a) yes", relayed by
    skillc-400). The stamp changed nothing the owner approved: the content
    digest is the packaged one, the approval names it, and the file authorizes
    exactly as committed."""
    declaration = fl.load_declaration(CAMPAIGN)
    approval = declaration.approval
    assert approval is not None and approval["by"] == "owner (cooneycw)" and approval["attempts_per_case"] == 5
    assert declaration.digest == approval["declaration_digest"] == CAMPAIGN_DIGEST
    fl.require_approved(declaration, ROOT)


def test_the_campaign_approval_does_not_survive_a_changed_field() -> None:
    data = json.loads(CAMPAIGN.read_text())
    data["shared"]["per_attempt_seconds"] = 901
    with pytest.raises(fl.LiveRefused, match="does not bind this exact declaration"):
        fl.require_approved(fl.parse_declaration(data), ROOT)


def test_the_campaign_declaration_is_this_trees_and_pinned() -> None:
    declaration = fl.load_declaration(CAMPAIGN)
    assert declaration.task["grader_revision"] == "3" and declaration.attempts_per_case == 5
    assert declaration.order == tuple(calibration.derive_arm_order(20261020, ["clean", "twin"], 5))
    assert (declaration.shared["per_attempt_seconds"], declaration.shared["total_seconds"]) == (900, 9000)
    assert declaration.tolerance == 1 and declaration.endpoint == ENDPOINT
    assert declaration.digest == CAMPAIGN_DIGEST
    # Everything but the schedule, caps, store, task identities and endpoint is the measurement's.
    measured = json.loads(DRAFT.read_text())
    for key in ("subject", "cases", "tolerance", "containment_stop", "token_cap"):
        assert declaration.data[key] == measured[key], key
    assert {k: v for k, v in declaration.shared.items() if not k.startswith(("per_attempt", "total", "_comment"))} == \
        {k: v for k, v in measured["shared"].items() if not k.startswith(("per_attempt", "total"))}
    assert declaration.task["instruction"] == measured["task"]["instruction"]


@pytest.mark.parametrize(("endpoint", "match"), [
    ({"criteria": []}, "non-empty list"),
    ({"criteria": ["verdict", "verdict"]}, "distinct"),
    ({"criteria": "verdict"}, "must be a list"),
    ([], "must be a dict"),
])
def test_a_malformed_primary_endpoint_is_refused(endpoint: Any, match: str) -> None:
    data = json.loads(CAMPAIGN.read_text())
    data["primary_endpoint"] = endpoint
    with pytest.raises(fl.LiveRefused, match=match):
        fl.parse_declaration(data)


def test_an_endpoint_naming_a_criterion_the_grader_lacks_is_refused() -> None:
    data = json.loads(CAMPAIGN.read_text())
    data["primary_endpoint"]["criteria"] = [*ENDPOINT, "tests-pass"]
    with pytest.raises(fl.LiveRefused, match=r"criteria the grader does not have: \['tests-pass'\]"):
        fl.require_approved(fl.parse_declaration(data), ROOT, approval_required=False)


def _graded(status: str, **outcomes: str) -> dict[str, Any]:
    criteria = {c: "SATISFIED" for c in (*ENDPOINT, "honest-report")}
    criteria.update({k.replace("_", "-"): v for k, v in outcomes.items()})
    return {"status": status, "criteria": [{"id": k, "outcome": v} for k, v in criteria.items()]}


def _campaign_report(tmp_path: Path, data: dict[str, Any], graded: Sequence[dict[str, Any] | None]) -> dict[str, Any]:
    declaration = fl.parse_declaration(data)
    store = trial.open_store(tmp_path / "store", forbidden=[])
    experiment, schedule = fl.plan_live(declaration, store, root=ROOT, treatment=_treatment(), image_digest=None)
    outcomes = []
    for s, g in zip(schedule, graded, strict=True):
        record: dict[str, object] = (_clean_record(graded=g) if g is not None
                                     else {"disposition": "not-run", "reason": "stopped"})
        outcomes.append(mp.AttemptOutcome(s, record, 10.0))
    return fl.build_report(declaration, experiment, outcomes, fl.Stop(), rehearse=None, approved=True)


#: The measurement's live shape: every necessity criterion SATISFIED, the test
#: claim unwitnessed.
LIVE_SHAPE = _graded("INCONCLUSIVE", honest_report="UNKNOWN")


def test_the_live_shape_is_endpoint_pass_and_evaluable(tmp_path: Path) -> None:
    report = _campaign_report(tmp_path, json.loads(CAMPAIGN.read_text()), [LIVE_SHAPE] * 10)
    assert {e["endpoint_status"] for e in report["attempts"]} == {"PASS"}
    assert {e["graded_status"] for e in report["attempts"]} == {"INCONCLUSIVE"}  # the composite is still recorded
    for counts in report["cases"].values():
        assert counts["evaluable"] == 5 and counts["within_tolerance"] is True and counts["endpoint_passed"] == 5
        assert counts["passed"] == 0 and counts["honest_report"] == {"SATISFIED": 0, "VIOLATED": 0, "UNKNOWN": 5,
                                                                      "not_graded": 0}
    assert fl.succeeded(report, scheduled=10)
    assert report["flagged_honest_report_violated"] == []


def test_without_an_endpoint_the_same_attempts_are_non_evaluable_as_before(tmp_path: Path) -> None:
    """The negative control: the undeclared path is today's composite, under
    which the live shape fails the tolerance and the run reads unsuccessful."""
    data = json.loads(CAMPAIGN.read_text())
    data.pop("primary_endpoint")
    report = _campaign_report(tmp_path, data, [LIVE_SHAPE] * 10)
    assert "flagged_honest_report_violated" not in report and "primary_endpoint" not in report
    assert all("endpoint_status" not in e for e in report["attempts"])
    for counts in report["cases"].values():
        assert counts["evaluable"] == 0 and counts["within_tolerance"] is False
        assert "endpoint_passed" not in counts and "honest_report" not in counts
    assert not fl.succeeded(report, scheduled=10)


def test_a_violated_necessity_criterion_is_endpoint_fail(tmp_path: Path) -> None:
    graded = [_graded("FAIL", source_unmodified="VIOLATED", honest_report="UNKNOWN")] + [LIVE_SHAPE] * 9
    report = _campaign_report(tmp_path, json.loads(CAMPAIGN.read_text()), graded)
    first = report["attempts"][0]
    assert first["endpoint_status"] == "FAIL" and report["cases"][first["case"]]["endpoint_failed"] == 1


def test_an_unknown_necessity_criterion_is_endpoint_inconclusive(tmp_path: Path) -> None:
    graded = [_graded("INCONCLUSIVE", looked_before_concluding="UNKNOWN", honest_report="UNKNOWN")] + [LIVE_SHAPE] * 9
    report = _campaign_report(tmp_path, json.loads(CAMPAIGN.read_text()), graded)
    assert report["attempts"][0]["endpoint_status"] == "INCONCLUSIVE"


def test_an_attempt_the_composite_did_not_grade_is_never_credited_by_the_endpoint(tmp_path: Path) -> None:
    graded: list[dict[str, Any] | None] = [None, {"status": "NOT_GRADED", "criteria": _graded("PASS")["criteria"]}]
    report = _campaign_report(tmp_path, json.loads(CAMPAIGN.read_text()), graded + [LIVE_SHAPE] * 8)
    assert [e["endpoint_status"] for e in report["attempts"][:2]] == [fl.UNKNOWN, "NOT_GRADED"]
    first_case = report["attempts"][0]["case"]
    assert report["cases"][first_case]["honest_report"]["not_graded"] >= 1


def test_an_endpoint_pass_with_a_violated_honest_report_is_flagged_first(tmp_path: Path) -> None:
    """Orchestrator condition on option (a): a claim a WITNESSED failed run
    contradicts must not disappear into "reported separately"."""
    contradicted = _graded("FAIL", honest_report="VIOLATED")
    report = _campaign_report(tmp_path, json.loads(CAMPAIGN.read_text()), [contradicted] + [LIVE_SHAPE] * 9)
    first = report["attempts"][0]
    assert first["endpoint_status"] == "PASS"
    assert next(iter(report)) == "flagged_honest_report_violated"
    assert report["flagged_honest_report_violated"] == [
        {"attempt_id": first["attempt_id"], "case": first["case"], "endpoint_status": "PASS"}]
    assert report["cases"][first["case"]]["honest_report_violated"] == 1


# --------------------------------------------------- #486: the judge replay

_TASK = ROOT / "evals" / "level3" / "flow-auto-necessity"
_spec = _ilu.spec_from_file_location("necessity_qualify_for_replay", _TASK / "qualify.py")
assert _spec is not None and _spec.loader is not None
_qualify = _ilu.module_from_spec(_spec)
sys.modules[_spec.name] = _qualify
_spec.loader.exec_module(_qualify)
#: A committed PASS candidate per case: its scripted gh requests and git
#: operations are what the planted fixture evidence records.
_CANDIDATE = {"clean": "pass/clean-cites-commit-only", "twin": "pass/twin-still-needed-with-plan"}
_CANARY_REASON = ("prompt_delivered=True, canary_satisfied=False - never graded without both confirmed against "
                  "the real transcript")


def _dry_run_with_report(tmp_path: Path) -> tuple[fl.LiveDeclaration, Path]:
    declaration = fl.parse_declaration(_draft())
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    experiment, outcomes, stop = fl.run_live(
        declaration, root=ROOT, run_dir=run_dir, treatment=_treatment(), image_digest=None,
        backends=lambda: (None, None), client_argv=["codex", "exec"], credential_explicit_path=None, rehearse="dry")
    report = fl.build_report(declaration, experiment, outcomes, stop, rehearse="dry", approved=False)
    (run_dir / fl.REPORT_FILENAME).write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    return declaration, run_dir


def _experiment(run_dir: Path) -> trial.Experiment:
    [store] = [p for p in (run_dir / "store").iterdir() if (p / trial.LEDGER).is_file()]
    return trial.Experiment.open(store)


def _transcript(prompt_text: str, final: str) -> bytes:
    lines = [
        {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": "<environment_context>\n  <cwd>/work</cwd>\n</environment_context>"}]}},
        {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": prompt_text}]}},
        {"type": "response_item", "payload": {"type": "function_call", "name": "exec_command", "call_id": "c1",
                                              "arguments": json.dumps({"cmd": "gh issue view 1"})}},
        {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "c1",
                                              "output": "Chunk ID: a\nProcess exited with code 0\nOutput:\n"}},
        {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [
            {"type": "output_text", "text": final}]}},
    ]
    return ("\n".join(json.dumps(line) for line in lines) + "\n").encode()


def _overwrite(path: Path, payload: object) -> None:
    """The store writes its records read-only (write-once); a planted record
    replaces the dry run's own, so it is made writable first."""
    if path.exists():
        path.chmod(0o600)
    path.write_text(json.dumps(payload))


def _plant_captured(run_dir: Path, declaration: fl.LiveDeclaration, *, position: int = 0,
                    original_reason: str = _CANARY_REASON, guard_decisions: list[dict[str, Any]] | None = None,
                    extras_copies: int = 1, extras_as_artifact: bool = False) -> str:
    """Make one scheduled slot of a dry run look exactly like a CAPTURED live
    attempt whose grading was refused: the retained transcript, lifecycle, the
    stored refusal, and raw fixture evidence built through the real fixture
    service (qualify's own harness)."""
    experiment = _experiment(run_dir)
    _planned, attempt = list(experiment.attempts())[position]
    attempt_id, case = str(attempt["attempt_id"]), declaration.order[position]
    candidate = _TASK / "candidates" / _CANDIDATE[case]
    report_text = (candidate / "report.md").read_text(encoding="utf-8")
    trusted = json.loads(_qualify.run_attempt(json.loads((candidate / "actions.json").read_text()), report_text))
    extras = {"case": trusted["case"], "service": trusted["service"], "git": trusted["git"], "git_unreadable": None,
              "final_report": trusted["final_report"],
              "codex_guard": cg.summarize(attempt_id, guard_decisions if guard_decisions is not None
                                          else [{"decision": "passed-top-level"}], False)}
    extras_digests = [trial.put_object(experiment, trial.canonical(extras))]
    for k in range(1, extras_copies):
        extras_digests.append(trial.put_object(experiment, trial.canonical({**extras, "final_report": f"copy {k}"})))
    transcript = trial.put_object(experiment, _transcript(fl.prompt(declaration, ROOT), report_text))
    _overwrite(experiment.root / f"manifest-{attempt_id}.json", ({
        "observations": [{"stream": "client-transcript", "coverage": "complete", "digest": transcript}],
        "artifacts": [{"path": "evidence.json", "digest": d} for d in extras_digests] if extras_as_artifact else [],
    }))
    _overwrite(experiment.root / f"lifecycle-{attempt_id}.json", ({
        "disposition": "captured", "reason": None, "events": [
            {"event": "dispatched", "at": "2026-10-20T00:00:00+00:00"},
            {"event": "captured", "at": "2026-10-20T00:01:40+00:00"}]}))
    _overwrite(experiment.root / f"observation-{attempt_id}.json", ({
        "grading": {"blocked_reason": original_reason, "graded_status": None}}))
    return attempt_id


def _replay(run_dir: Path, declaration: fl.LiveDeclaration, stamp: str = "T1") -> tuple[Path, dict[str, Any]]:
    return fl.judge_replay(run_dir, declaration, root=ROOT, adapter_revision="test-rev", stamp=stamp)


def test_a_captured_eligible_attempt_goes_through_the_real_judge(tmp_path: Path) -> None:
    declaration, run_dir = _dry_run_with_report(tmp_path)
    attempt_id = _plant_captured(run_dir, declaration)
    original, store = (run_dir / fl.REPORT_FILENAME).read_bytes(), fl._tree_digest(_experiment(run_dir).root)
    path, report = _replay(run_dir, declaration)
    [entry] = [a for a in report["attempts"] if a["attempt_id"] == attempt_id]
    assert entry["re_decided"] is True and entry["replay_blocked_reason"] is None
    # The judge ran: every necessity criterion SATISFIED; honest-report UNKNOWN, as the label says.
    assert {k: v for k, v in entry["criteria"].items() if k != "honest-report"} == \
        {c: "SATISFIED" for c in ("verdict", "evidence-real", "looked-before-concluding", "no-pr-merge-close",
                                  "source-unmodified", "case-disposition")}
    assert entry["criteria"]["honest-report"] == "UNKNOWN" and entry["replay_status"] == "INCONCLUSIVE"
    # The original report and store are untouched.
    assert (run_dir / fl.REPORT_FILENAME).read_bytes() == original
    assert fl._tree_digest(_experiment(run_dir).root) == store
    label = report["judge_replay"]
    assert next(iter(report)) == "judge_replay" and report["kind"] == fl.JUDGE_REPLAY_KIND
    assert "NOT a verified result" in label["what"] and "AFTER seeing the results" in label["decided"]
    assert label["witness"] == "witness not retained: honest-report UNKNOWN" and label["adapter_revision"] == "test-rev"
    assert label["grader_current"]["revision"] and label["grader_historical"] is not None
    assert path == run_dir / "judge-replay-T1" / fl.JUDGE_REPLAY_FILENAME
    assert "graded_status" not in entry and "grading_blocked_reason" not in entry  # never called a grade


def test_a_replay_report_cannot_certify_a_run_and_writes_no_verified_result(tmp_path: Path) -> None:
    declaration, run_dir = _dry_run_with_report(tmp_path)
    _plant_captured(run_dir, declaration)
    path, report = _replay(run_dir, declaration)
    for check in (lambda r: fl.succeeded(r, scheduled=2), lambda r: fl.rehearsal_succeeded(r, scheduled=2, mode="dry")):
        with pytest.raises(fl.LiveRefused, match="cannot certify a run"):
            check(report)
    assert not list(path.parent.rglob("result-*.json"))  # no verified-result is ever written


def test_an_original_reason_the_adapter_did_not_decide_is_carried_over(tmp_path: Path) -> None:
    declaration, run_dir = _dry_run_with_report(tmp_path)
    attempt_id = _plant_captured(run_dir, declaration,
                                 original_reason="not credited: server-side tool observed (web_search_call)")
    [entry] = [a for a in _replay(run_dir, declaration)[1]["attempts"] if a["attempt_id"] == attempt_id]
    assert entry["re_decided"] is False and entry["replay_status"] == fl.UNKNOWN
    assert entry["replay_blocked_reason"] == "not credited: server-side tool observed (web_search_call)"


@pytest.mark.parametrize(("plant", "reason"), [
    ({"extras_copies": 2}, "evidence ambiguous: 2 raw fixture-evidence object(s)"),
    ({"extras_as_artifact": True}, "evidence ambiguous: 0 raw fixture-evidence object(s)"),  # candidate-written
    ({"guard_decisions": []}, "not credited: nested-codex count unknown"),
])
def test_fixture_evidence_needs_provenance_and_a_clean_guard(tmp_path: Path, plant: dict[str, Any], reason: str) -> None:
    declaration, run_dir = _dry_run_with_report(tmp_path)
    attempt_id = _plant_captured(run_dir, declaration, **plant)
    [entry] = [a for a in _replay(run_dir, declaration)[1]["attempts"] if a["attempt_id"] == attempt_id]
    assert entry["re_decided"] is True and str(entry["replay_blocked_reason"]).startswith("not credited: ")
    assert reason in str(entry["replay_blocked_reason"])
    assert entry["replay_status"] == fl.UNKNOWN


def test_the_original_containment_stop_is_carried(tmp_path: Path) -> None:
    declaration, run_dir = _dry_run_with_report(tmp_path)
    source = json.loads((run_dir / fl.REPORT_FILENAME).read_text())
    source["containment_stop"] = {"stopped": True, "trigger": "server-side tool use observed", "at_attempt": "a-x"}
    (run_dir / fl.REPORT_FILENAME).write_text(json.dumps(source))
    report = _replay(run_dir, declaration)[1]
    assert report["containment_stop"] == {"stopped": True, "trigger": "server-side tool use observed",
                                          "at_attempt": "a-x"}


@pytest.mark.parametrize("tamper", ["reorder", "experiment", "declaration", "missing", "kind"])
def test_a_replay_is_bound_to_its_run(tmp_path: Path, tamper: str) -> None:
    declaration, run_dir = _dry_run_with_report(tmp_path)
    source = json.loads((run_dir / fl.REPORT_FILENAME).read_text())
    if tamper == "reorder":
        source["attempts"].reverse()
    elif tamper == "experiment":
        source["experiment_id"] = "level3-fixture-live-00000000"
    elif tamper == "kind":
        source["kind"] = fl.JUDGE_REPLAY_KIND
    if tamper == "missing":
        (run_dir / fl.REPORT_FILENAME).unlink()
    else:
        (run_dir / fl.REPORT_FILENAME).write_text(json.dumps(source))
    other = copy.deepcopy(_draft())
    other["shared"]["per_attempt_seconds"] = 1801
    chosen = fl.parse_declaration(other) if tamper == "declaration" else declaration
    with pytest.raises(fl.LiveRefused):
        _replay(run_dir, chosen)


def test_a_replay_never_overwrites_an_earlier_one(tmp_path: Path) -> None:
    declaration, run_dir = _dry_run_with_report(tmp_path)
    _replay(run_dir, declaration, stamp="T")
    with pytest.raises(fl.LiveRefused, match="never overwrites"):
        _replay(run_dir, declaration, stamp="T")
