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

from skillc import agent_trial as at
from skillc import calibration, profile, trial, verify
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


def test_the_spent_campaign_declaration_is_refused_since_grader_revision_4() -> None:
    """The owner approved a campaign at grader REVISION 3, and it ran
    (20261020T141529Z-3585c9). Revision 4 (#487) moved the grader, so the
    approval does not carry over: the committed file is the historical record
    and authorizes nothing. A campaign at revision 4 needs its own declaration
    and its own approval."""
    declaration = fl.load_declaration(CAMPAIGN)
    assert declaration.task["grader_revision"] == "3"
    with pytest.raises(fl.LiveRefused, match=r"differ from the repository: \['grader_revision', 'grader_digest'\]"):
        fl.require_approved(declaration, ROOT)


def _campaign_draft() -> dict[str, Any]:
    """The committed campaign declaration with its task identities re-derived
    from THIS tree (the `_draft()` pattern): the committed file is never
    edited, and since grader revision 4 (#487) the repository refuses it."""
    data: dict[str, Any] = json.loads(CAMPAIGN.read_text(encoding="utf-8"))
    data["task"].update(copy.deepcopy(_identity()))
    return data


def test_the_campaign_approval_does_not_survive_a_changed_field() -> None:
    data = _approve(_campaign_draft())
    fl.require_approved(fl.parse_declaration(data), ROOT)  # approved as is
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
    data = _campaign_draft()
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


def _dry_run_with_report(tmp_path: Path, data: dict[str, Any] | None = None) -> tuple[fl.LiveDeclaration, Path]:
    declaration = fl.parse_declaration(data if data is not None else _draft())
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
                    extras_copies: int = 1, extras_as_artifact: bool = False,
                    prompt_delivered: bool | None = True, guard_policy: str | None = None,
                    guard_channel_unavailable: bool = False) -> str:
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
                                          else [{"decision": "passed-top-level"}], guard_channel_unavailable,
                                          nested_policy=guard_policy)}
    extras_digests = [trial.put_object(experiment, trial.canonical(extras))]
    for k in range(1, extras_copies):
        extras_digests.append(trial.put_object(experiment, trial.canonical({**extras, "final_report": f"copy {k}"})))
    # The live prompt carries a canary instruction with a nonce no record keeps;
    # the planted transcript carries one too, so the replay cannot match it -
    # it must carry the live run's own verdict instead.
    live_prompt = f"{fl.prompt(declaration, ROOT)}\n\nBefore doing anything else, write 'touched:{position:032x}'."
    transcript = trial.put_object(experiment, _transcript(live_prompt, report_text))
    _overwrite(experiment.root / f"manifest-{attempt_id}.json", ({
        "observations": [{"stream": "client-transcript", "coverage": "complete", "digest": transcript}],
        "artifacts": [{"path": "evidence.json", "digest": d} for d in extras_digests] if extras_as_artifact else [],
    }))
    _overwrite(experiment.root / f"lifecycle-{attempt_id}.json", ({
        "disposition": "captured", "reason": None, "events": [
            {"event": "dispatched", "at": "2026-10-20T00:00:00+00:00"},
            {"event": "captured", "at": "2026-10-20T00:01:40+00:00"}]}))
    _overwrite(experiment.root / f"observation-{attempt_id}.json", ({
        "grading": {"blocked_reason": original_reason, "graded_status": None},
        **({"transcript": {"prompt_delivered": prompt_delivered,
                           "prompt_delivery_reason": None if prompt_delivered else "first message differs"}}
           if prompt_delivered is not None else {})}))
    return attempt_id


def _replay(run_dir: Path, declaration: fl.LiveDeclaration, stamp: str = "T1", *,
            assume: bool = True) -> tuple[Path, dict[str, Any]]:
    return fl.judge_replay(run_dir, declaration, root=ROOT, adapter_revision="test-rev", stamp=stamp,
                           assume_fixture_finalized=assume)


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


def test_by_default_an_unestablished_fixture_finalization_is_not_judged(tmp_path: Path) -> None:
    """Counter-model review, scoped pass: a live fixture session can latch a
    finalization failure no retained record holds. Not assumed, it fails closed."""
    declaration, run_dir = _dry_run_with_report(tmp_path)
    attempt_id = _plant_captured(run_dir, declaration)
    _path, report = _replay(run_dir, declaration, assume=False)
    [entry] = [a for a in report["attempts"] if a["attempt_id"] == attempt_id]
    assert entry["re_decided"] is True and entry["replay_status"] == fl.UNKNOWN
    assert "finalization failure state was not retained" in str(entry["replay_blocked_reason"])
    assert report["judge_replay"]["fixture_finalization"].startswith("not assumed")
    assumed = _replay(run_dir, declaration, stamp="T2", assume=True)[1]
    assert assumed["judge_replay"]["fixture_finalization"].startswith("ASSUMED clean")


def test_without_the_flag_a_fully_captured_run_judges_nothing(tmp_path: Path) -> None:
    """Orchestrator ruling (#486): strict is the default, so a replay of a run
    whose every attempt was captured judges NONE of them; and a flagged replay
    names its assumption in the label's first line."""
    declaration, run_dir = _dry_run_with_report(tmp_path)
    planted = {_plant_captured(run_dir, declaration, position=k) for k in range(len(declaration.order))}
    _path, strict = _replay(run_dir, declaration, assume=False)
    entries = [a for a in strict["attempts"] if a["attempt_id"] in planted]
    assert len(entries) == len(declaration.order) and all(a["re_decided"] for a in entries)
    assert all(a["replay_status"] == fl.UNKNOWN for a in entries)
    assert all("finalization failure state was not retained" in str(a["replay_blocked_reason"]) for a in entries)
    assert not strict["judge_replay"]["what"].startswith("ASSUMES")
    assumed = _replay(run_dir, declaration, stamp="T2", assume=True)[1]
    first_line = next(iter(assumed["judge_replay"].values()))
    assert first_line.startswith("ASSUMES fixture finalization was clean (--assume-fixture-finalized)")
    assert any(a["replay_status"] != fl.UNKNOWN for a in assumed["attempts"] if a["attempt_id"] in planted)


@pytest.mark.parametrize("delivered", [False, None])
def test_prompt_delivery_is_the_live_runs_own_verdict(tmp_path: Path, delivered: bool | None) -> None:
    """Counter-model review: the live prompt carries a per-attempt canary nonce
    that no record keeps, so the replay carries the live run's verdict. A
    refusal stays a refusal, and an unrecorded verdict is not delivered."""
    declaration, run_dir = _dry_run_with_report(tmp_path)
    attempt_id = _plant_captured(run_dir, declaration, prompt_delivered=delivered)
    [entry] = [a for a in _replay(run_dir, declaration)[1]["attempts"] if a["attempt_id"] == attempt_id]
    assert str(entry["replay_blocked_reason"]).startswith("prompt_delivered=False")


def test_rejected_judge_output_is_never_scored() -> None:
    grader = verify.GraderDef.load(_TASK).with_judge(_TASK / "grader-controls" / "omits_criterion.py")
    out = fl._run_judge(grader, {"case": "clean"})
    assert out["status"] == "INCONCLUSIVE" and out["category"] == "criteria-set"
    assert out["criteria"] is None and out["rejected_criteria"]


def test_a_corrupted_object_is_refused(tmp_path: Path) -> None:
    declaration, run_dir = _dry_run_with_report(tmp_path)
    _plant_captured(run_dir, declaration)
    experiment = _experiment(run_dir)
    target = next(p for p in (experiment.root / trial.OBJECTS).iterdir()
                  if p.stat().st_size < 1_000_000 and b'"final_report"' in p.read_bytes())
    target.chmod(0o600)
    target.write_bytes(target.read_bytes().replace(b'"final_report"', b'"final_report" ', 1))
    with pytest.raises(fl.LiveRefused, match="content-address check"):
        _replay(run_dir, declaration)


def test_a_missing_manifest_makes_provenance_unknown(tmp_path: Path) -> None:
    declaration, run_dir = _dry_run_with_report(tmp_path)
    attempt_id = _plant_captured(run_dir, declaration)
    sibling = _plant_captured(run_dir, declaration, position=1)
    (_experiment(run_dir).root / f"manifest-{sibling}.json").unlink()
    [entry] = [a for a in _replay(run_dir, declaration)[1]["attempts"] if a["attempt_id"] == attempt_id]
    assert "provenance unknown - no artifact manifest retained" in str(entry["replay_blocked_reason"])


# ------------------------------- the revision-4 campaign (#434, after #487)

CAMPAIGN_REV4 = ROOT / "evals" / "level3" / "campaign-434-live" / "campaign-declaration-rev4.json"
#: The draft's content digest, as it goes into the owner's approval package. A
#: changed field must change this line on purpose.
CAMPAIGN_REV4_DIGEST = "sha256:90accda59cc7d5a377e32db8cff02856cad4204315d0faa25435cc57cb017f08"
#: The ONLY fields the revision-4 draft may differ in from the owner-approved
#: revision-3 campaign (694e2b82), as (path...) tuples. Orchestrator condition:
#: an allow-list, so ANY other difference fails.
_REV4_MAY_DIFFER = {("_comment",), ("run_store",), ("approval",), ("task", "grader_revision"),
                    ("task", "grader_digest"), ("task", "goal_sha256"), ("task", "builder_sha256"),
                    ("task", "base_trees")}


def _differences(a: Any, b: Any, path: tuple[str, ...] = ()) -> set[tuple[str, ...]]:
    if isinstance(a, dict) and isinstance(b, dict) and path not in _REV4_MAY_DIFFER:
        return {d for k in set(a) | set(b) for d in _differences(a.get(k, _ABSENT), b.get(k, _ABSENT), (*path, k))}
    return set() if a == b else {path}


_ABSENT = object()


def test_the_revision_4_campaign_differs_from_the_approved_one_only_where_allowed() -> None:
    approved, draft = json.loads(CAMPAIGN.read_text()), json.loads(CAMPAIGN_REV4.read_text())
    differences = _differences(approved, draft)
    assert differences <= _REV4_MAY_DIFFER, sorted(differences - _REV4_MAY_DIFFER)
    # Each allowed difference is real, not a field quietly dropped.
    assert ("approval",) in differences and draft["approval"]["declaration_digest"] == CAMPAIGN_REV4_DIGEST
    assert draft["task"]["grader_revision"] == "4" and draft["run_store"] != approved["run_store"]


def test_the_allow_list_catches_any_other_difference() -> None:
    """The instrument's own red: a changed term outside the allow-list is named."""
    draft = json.loads(CAMPAIGN_REV4.read_text())
    for path, value in ((("shared", "per_attempt_seconds"), 901), (("case_order", "seed"), 1),
                        (("tolerance", "non_evaluable_per_case"), 2), (("task", "instruction"), "x")):
        tampered = copy.deepcopy(draft)
        tampered[path[0]][path[1]] = value
        # Rejected, not merely named (review): the path must survive the allow-list.
        assert path in _differences(json.loads(CAMPAIGN.read_text()), tampered) - _REV4_MAY_DIFFER, path


def test_the_revision_4_campaign_carries_the_owners_approval_and_is_pinned() -> None:
    """The owner approved the revision-4 campaign on 2026-10-20 ("Approve 434",
    relayed by skillc-400). The stamp changed nothing the owner approved: the
    content digest is the packaged one, and the file authorizes as committed."""
    declaration = fl.load_declaration(CAMPAIGN_REV4)
    approval = declaration.approval
    assert approval is not None and approval["by"] == "owner (cooneycw)" and approval["attempts_per_case"] == 5
    assert "Approve 434" in approval["source"] and approval["declaration_digest"] == CAMPAIGN_REV4_DIGEST
    assert declaration.task["grader_revision"] == "4" and declaration.attempts_per_case == 5
    assert declaration.order == tuple(calibration.derive_arm_order(20261020, ["clean", "twin"], 5))
    assert declaration.order == fl.load_declaration(CAMPAIGN).order   # the same order, kept on purpose
    assert declaration.endpoint == ENDPOINT and declaration.tolerance == 1
    assert declaration.digest == CAMPAIGN_REV4_DIGEST


def test_the_spent_revision_4_campaign_declaration_is_refused_since_grader_revision_5() -> None:
    """The owner approved the revision-4 campaign and it ran
    (20261020T195431Z-fab3ce). Revision 5 (#499) moved the grader, so the
    approval does not carry over: the committed file is the historical record
    and authorizes nothing. A revision-5 campaign needs its own declaration
    and its own approval."""
    declaration = fl.load_declaration(CAMPAIGN_REV4)
    assert declaration.task["grader_revision"] == "4"
    with pytest.raises(fl.LiveRefused, match=r"differ from the repository: \['grader_revision', 'grader_digest'\]"):
        fl.require_approved(declaration, ROOT)


def test_the_revision_4_approval_does_not_survive_a_changed_field(monkeypatch: pytest.MonkeyPatch) -> None:
    """The approval binds the exact declaration. Since grader revision 5 (#499)
    the repository refuses the spent file on its identities first, so the
    repository's identities are pinned to the file's own (counter-model review):
    the unchanged file then authorizes, and only the changed field refuses."""
    data = json.loads(CAMPAIGN_REV4.read_text())
    real = fl.task_identity

    def as_declared(root: Path, task_path: str = fl.TASK_PATH) -> dict[str, object]:
        return {k: data["task"][k] for k in real(root, task_path)}

    monkeypatch.setattr(fl, "task_identity", as_declared)
    fl.require_approved(fl.parse_declaration(copy.deepcopy(data)), ROOT)
    data["shared"]["per_attempt_seconds"] = 901
    with pytest.raises(fl.LiveRefused, match="does not bind this exact declaration"):
        fl.require_approved(fl.parse_declaration(data), ROOT)


#: The owner-approved revision-3 campaign run (20261020T141529Z-3585c9). Its
#: records are the owner's evidence and are NOT committed (skillc is public): the
#: check below reads them as plain files by manifest digest - never through
#: Experiment.open - on the host that holds them, and skips loudly elsewhere.
CAMPAIGN_RUN_STORE = (Path.home() / "skillc-evidence" / "campaign-434-live" / "campaign" / "20261020T141529Z-3585c9"
                      / "store" / "level3-fixture-live-ec3d4e35")
CAMPAIGN_RUN_ATTEMPTS = ("a-103b50d6d776", "a-5f554edfaee4", "a-6dbfa1eb1db5", "a-96c8263722f6", "a-9975917f3c94",
                         "a-a3f256d70fd7", "a-af20400ffabb", "a-be1a469503e8", "a-c403275ce730", "a-ef44b344fbf6")
#: A response item the adapter has never seen: the census must stop on it.
_UNKNOWN_ITEM = b'{"type": "response_item", "payload": {"type": "future_item_type"}}\n'


def _retained_object(store: Path, digest: str) -> bytes:
    raw = (store / "objects" / digest.removeprefix("sha256:")).read_bytes()
    assert trial.sha256_bytes(raw) == digest, f"content-address mismatch: {digest}"
    return raw


def _retained_guard(store: Path, attempt_id: str) -> Any:
    """The attempt's nested-codex summary from its controller-held raw fixture
    extras, by provenance (review): a content-verified object with exactly the
    raw-extras keys, never a candidate artifact, unique for the attempt."""
    artifacts = {a["digest"] for m in store.glob("manifest-*.json")
                 for a in json.loads(m.read_text()).get("artifacts", [])}
    found = []
    for path in sorted((store / "objects").iterdir()):
        raw = path.read_bytes()
        try:
            data = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            continue
        if not isinstance(data, dict) or set(data) != set(fl._RAW_EXTRAS_KEYS):
            continue
        guard = data.get("codex_guard")
        if not isinstance(guard, dict) or guard.get("attempt_id") != attempt_id:
            continue
        digest = "sha256:" + path.name
        assert trial.sha256_bytes(raw) == digest, f"content-address mismatch: {digest}"
        if digest not in artifacts:
            found.append(guard["nested"])
    assert len(found) == 1, f"{attempt_id}: {len(found)} controller-held guard records"
    return found[0]


def _require_complete(store: Path) -> None:
    """Present means complete (review): a store holding fewer than the ten
    attempts fails, never quietly checks fewer."""
    missing = [a for a in CAMPAIGN_RUN_ATTEMPTS if not (store / f"manifest-{a}.json").is_file()]
    assert not missing, f"the retained campaign store is incomplete: {missing}"


def _complete_stream(manifest: dict[str, Any], stream: str) -> str:
    """The digest of the ONE complete observation of `stream` (review pass 2):
    a partial or duplicated stream is not evidence the replay would accept."""
    matches = [o for o in manifest.get("observations", []) if o.get("stream") == stream]
    assert len(matches) == 1 and matches[0].get("coverage") == "complete", f"{stream}: {matches!r}"
    return str(matches[0]["digest"])


def _retained_record(attempt_id: str, *, transcript_suffix: bytes = b"") -> dict[str, Any]:
    """The containment record the live run builds, rebuilt from the retained
    transcript (with THIS tree's adapter and census), proxy log and guard."""
    manifest = json.loads((CAMPAIGN_RUN_STORE / f"manifest-{attempt_id}.json").read_text())
    transcript = (_retained_object(CAMPAIGN_RUN_STORE, _complete_stream(manifest, "client-transcript"))
                  + transcript_suffix)
    observation, census, metadata = at.observe_transcript_bytes(
        at.CLIENT_SPECS[fl.CLIENT], transcript, expected_prompt=fl.prompt(fl.load_declaration(CAMPAIGN_REV4), ROOT),
        skill_name=None)
    proxy = _retained_object(CAMPAIGN_RUN_STORE, _complete_stream(manifest, eg.PROXY_LOG_STREAM))
    return {"disposition": "captured", "fixture": {"codex_guard": _retained_guard(CAMPAIGN_RUN_STORE, attempt_id)},
            "observation": {"status": "observed", **observation.to_fields(), **census, "run_metadata": metadata,
                            "egress": {"status": "read", "digest": trial.sha256_bytes(proxy), **eg.summarize_log(proxy)}}}


@pytest.mark.parametrize("attempt_id", CAMPAIGN_RUN_ATTEMPTS)
def test_the_fail_closed_census_does_not_stop_on_the_retained_campaign(attempt_id: str) -> None:
    """Orchestrator condition on the revision-4 campaign: #486's fail-closed
    census must not false-stop on real codex output. Every retained attempt
    passes the containment trigger; the same transcript with one unknown
    response item appended stops it (the control: the check can say STOP)."""
    if not CAMPAIGN_RUN_STORE.is_dir():
        pytest.skip(f"PRIVATE EVIDENCE ABSENT: {CAMPAIGN_RUN_STORE} is not on this host; "
                    "the #434 no-false-stop check did not run")
    _require_complete(CAMPAIGN_RUN_STORE)
    allowlist = str(fl.load_declaration(CAMPAIGN_REV4).shared["agent_network"]["allowlist_digest"])
    assert fl.containment_trigger(_retained_record(attempt_id), allowlist_digest=allowlist) is None
    stopped = fl.containment_trigger(_retained_record(attempt_id, transcript_suffix=_UNKNOWN_ITEM),
                                     allowlist_digest=allowlist)
    assert stopped is not None and "future_item_type" in stopped


def _guard_store(tmp_path: Path, guard_attempt: str = "a-1") -> Path:
    store = tmp_path / "store"
    (store / "objects").mkdir(parents=True)
    extras: dict[str, Any] = {k: None for k in fl._RAW_EXTRAS_KEYS}
    extras["codex_guard"] = {"attempt_id": guard_attempt, "nested": {"status": "zero"}}
    raw = json.dumps(extras).encode()
    (store / "objects" / trial.sha256_bytes(raw).removeprefix("sha256:")).write_bytes(raw)
    (store / "manifest-a-1.json").write_text(json.dumps({"observations": [], "artifacts": []}))
    return store


def test_the_retained_guard_is_read_by_provenance(tmp_path: Path) -> None:
    """Controls for the no-false-stop check's evidence reads (review)."""
    store = _guard_store(tmp_path)
    assert _retained_guard(store, "a-1") == {"status": "zero"}
    # An unrelated object naming the attempt (not the raw-extras shape) is ignored.
    other = json.dumps({"codex_guard": {"attempt_id": "a-1", "nested": {"status": "observed"}}}).encode()
    (store / "objects" / trial.sha256_bytes(other).removeprefix("sha256:")).write_bytes(other)
    assert _retained_guard(store, "a-1") == {"status": "zero"}
    # The same shape as a candidate ARTIFACT is not controller evidence.
    [obj] = [p for p in (store / "objects").iterdir() if json.loads(p.read_bytes()).keys() == set(fl._RAW_EXTRAS_KEYS)]
    (store / "manifest-a-1.json").write_text(json.dumps({"artifacts": [{"digest": "sha256:" + obj.name}]}))
    with pytest.raises(AssertionError, match="0 controller-held guard records"):
        _retained_guard(store, "a-1")
    # Corrupted bytes under the old content address are refused.
    store = _guard_store(tmp_path / "corrupt")
    [obj] = list((store / "objects").iterdir())
    obj.write_bytes(obj.read_bytes().replace(b'"zero"', b'"zerO"'))
    with pytest.raises(AssertionError, match="content-address mismatch"):
        _retained_guard(store, "a-1")


def test_an_incomplete_retained_store_fails_not_skips(tmp_path: Path) -> None:
    for attempt in CAMPAIGN_RUN_ATTEMPTS[:-1]:
        (tmp_path / f"manifest-{attempt}.json").write_text("{}")
    with pytest.raises(AssertionError, match=CAMPAIGN_RUN_ATTEMPTS[-1]):
        _require_complete(tmp_path)
    (tmp_path / f"manifest-{CAMPAIGN_RUN_ATTEMPTS[-1]}.json").write_text("{}")
    _require_complete(tmp_path)


@pytest.mark.parametrize("observations", [
    [{"stream": "client-transcript", "coverage": "partial", "digest": "sha256:aa"}],
    [{"stream": "client-transcript", "coverage": "complete", "digest": "sha256:aa"}] * 2,
    [],
])
def test_only_one_complete_stream_is_read(observations: list[dict[str, str]]) -> None:
    with pytest.raises(AssertionError, match="client-transcript"):
        _complete_stream({"observations": observations}, "client-transcript")
    assert _complete_stream({"observations": [{"stream": "client-transcript", "coverage": "complete",
                                               "digest": "sha256:aa"}]}, "client-transcript") == "sha256:aa"


# --------------------------- #279: controller turns and the nested-codex policy

TURNS = {"version": 1, "by_case": {"clean": [], "twin": [{"text": "Approved. Proceed with the plan."}]}}


def _with_turns(data: dict[str, Any], turns: object = TURNS) -> dict[str, Any]:
    out = copy.deepcopy(data)
    out["task"]["turns"] = copy.deepcopy(turns)
    return out


def _guard(decisions: list[str], expected: int, *, policy: str | None = "refusal-expected",
           channel_unavailable: bool = False) -> dict[str, Any]:
    record = cg.summarize("a-1", [{"decision": d, "argv_digest": "sha256:" + "0" * 64, "seq": i}
                                  for i, d in enumerate(decisions)],
                          channel_unavailable, expected_top_level=expected, nested_policy=policy)
    return dict(record["nested"])


def test_turns_are_parsed_per_case_and_bound_by_the_digest() -> None:
    plain = fl.parse_declaration(_draft())
    assert plain.turns is None and plain.nested_policy is None
    turned = fl.parse_declaration(_with_turns(_draft()))
    assert turned.turns is not None and turned.turns.for_case("twin").texts == ("Approved. Proceed with the plan.",)
    assert len(turned.turns.for_case("clean")) == 0  # CLEAN never receives an approval
    edited = _with_turns(_draft(), {**TURNS, "by_case": {"clean": [], "twin": [{"text": "Approved."}]}})
    assert len({plain.digest, turned.digest, fl.parse_declaration(edited).digest}) == 3


@pytest.mark.parametrize("turns", [
    {"version": 1, "by_case": {"twin": [{"text": "Approved."}]}},                 # a declared case is missing
    {"version": 1, "by_case": {"clean": [], "twin": [{"text": "--sandbox x"}]}},  # reads as a flag
    {"version": 2, "by_case": {"clean": [], "twin": []}},
])
def test_malformed_turns_are_refused(turns: object) -> None:
    with pytest.raises(fl.LiveRefused, match="task.turns"):
        fl.parse_declaration(_with_turns(_draft(), turns))


@pytest.mark.parametrize("block", [{"nested_codex": "anything"}, {"nested_codex": "refusal-expected", "x": 1},
                                   {}, "refusal-expected"])
def test_the_containment_block_is_closed(block: object) -> None:
    data = _draft()
    data["containment"] = block
    with pytest.raises(fl.LiveRefused, match="containment"):
        fl.parse_declaration(data)


def test_without_turns_or_policy_an_approved_declaration_is_byte_identical() -> None:
    """The control: the owner-approved revision-4 campaign declares neither, so
    its digest and its parse are exactly what they were."""
    declaration = fl.load_declaration(CAMPAIGN_REV4)
    assert declaration.digest == CAMPAIGN_REV4_DIGEST
    assert declaration.turns is None and declaration.nested_policy is None


def test_delivered_turns_count_as_legitimate_top_level_launches() -> None:
    """Parking note's owed red: 1 + turns top-level launches is no stop; one
    extra launch beyond that is the nested stop."""
    zero = _clean_record(**{"fixture.codex_guard": _guard(["passed-top-level"] * 2, 2, policy=None)})
    assert fl.containment_trigger(zero, allowlist_digest=ALLOWLIST) is None
    extra = _clean_record(**{"fixture.codex_guard": _guard(["passed-top-level"] * 3, 2, policy=None)})
    assert "nested codex observed" in str(fl.containment_trigger(extra, allowlist_digest=ALLOWLIST))


@pytest.mark.parametrize(("decisions", "expected", "channel", "stops"), [
    (["passed-top-level", "passed-top-level", "refused-nested"], 2, False, False),  # refused: contained
    (["passed-top-level", "passed-top-level", "passed-top-level", "refused-nested"], 2, False, True),  # passed through
    (["passed-top-level", "passed-top-level", "refused-ancestry-unknown"], 2, False, True),
    (["passed-top-level", "refused-nested"], 2, False, True),   # a delivered turn the guard never saw
    (["passed-top-level", "passed-top-level", "refused-nested"], 2, True, True),    # untrusted channel
])
def test_the_refusal_expected_policy_stops_on_everything_but_a_refusal(
        decisions: list[str], expected: int, channel: bool, stops: bool) -> None:
    """Orchestrator ruling G1: under the declared policy only a confirmed
    REFUSED nested launch is contained; suspected, unknown-ancestry, a launch
    passed through (beyond the expected top-level count), a missing turn launch
    and an untrusted channel all still stop. Without the policy, all stop."""
    record = _clean_record(**{"fixture.codex_guard": _guard(decisions, expected, channel_unavailable=channel)})
    trigger = fl.containment_trigger(record, allowlist_digest=ALLOWLIST, nested_policy="refusal-expected")
    assert (trigger is not None) is stops, trigger
    assert fl.containment_trigger(record, allowlist_digest=ALLOWLIST) is not None


def test_run_attempt_passes_the_cases_turns_and_the_policy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = _with_turns(_draft())
    data["containment"] = {"nested_codex": "refusal-expected"}
    declaration = fl.parse_declaration(_approve(data))
    from skillc import agent_trial
    seen: list[dict[str, Any]] = []
    contained = _clean_record(**{"fixture.codex_guard": _guard(["passed-top-level"] * 2 + ["refused-nested"], 2)})

    def fake_attempt(**kwargs: Any) -> dict[str, Any]:
        seen.append(kwargs)
        return contained
    monkeypatch.setattr(agent_trial, "run_one_attempt", fake_attempt)
    experiment, outcomes, stop = fl.run_live(
        declaration, root=ROOT, run_dir=tmp_path, treatment=_treatment(), image_digest=None,
        backends=lambda: (None, None), client_argv=list(cc.DEFAULT_CLIENT_ARGVS["codex"]),
        credential_explicit_path=None)
    by_case = {kw["fixture"].case: kw for kw in seen}
    assert by_case["twin"]["turns"].texts == ("Approved. Proceed with the plan.",)
    assert len(by_case["clean"]["turns"]) == 0
    assert all(kw["nested_codex_policy"] == "refusal-expected" for kw in seen)
    assert stop.trigger is None and len(seen) == len(declaration.order)  # refusals did not stop the schedule
    report = fl.build_report(declaration, experiment, outcomes, stop, rehearse=None, approved=True)
    assert all("controller_turns" in entry for entry in report["attempts"])


def test_without_turns_run_attempt_passes_neither(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    declaration = fl.parse_declaration(_approve(_draft()))
    from skillc import agent_trial
    seen: list[dict[str, Any]] = []
    def fake_attempt(**kwargs: Any) -> dict[str, Any]:
        seen.append(kwargs)
        return _clean_record()
    monkeypatch.setattr(agent_trial, "run_one_attempt", fake_attempt)
    experiment, outcomes, stop = fl.run_live(
        declaration, root=ROOT, run_dir=tmp_path, treatment=_treatment(), image_digest=None,
        backends=lambda: (None, None), client_argv=list(cc.DEFAULT_CLIENT_ARGVS["codex"]),
        credential_explicit_path=None)
    assert seen and all("turns" not in kw and "nested_codex_policy" not in kw for kw in seen)
    report = fl.build_report(declaration, experiment, outcomes, stop, rehearse=None, approved=True)
    assert all("controller_turns" not in entry for entry in report["attempts"])


def test_the_turn_actor_wraps_only_a_case_with_turns() -> None:
    task_root = ROOT / fl.TASK_PATH
    plain_argv, plain_home = fl.rehearsal_actor(task_root, "twin")
    argv, home = fl.rehearsal_actor(task_root, "twin", turns=True)
    assert argv[0] == plain_argv[0] and argv[1].endswith("/turn_actor.py") and argv[2:] == plain_argv[2:]
    assert set(home) - set(plain_home) == {".skillc-fixture-campaign/turn_actor.py"}
    header = fl.TURN_ACTOR_SOURCE.split("sys.stderr.write(")[1].split(")")[0]
    assert fl.TURN_ACTOR_SESSION_ID in header


def test_the_service_clock_is_the_fixtures_not_the_witnesss() -> None:
    """The clock dependency (ruling R4): a fixture-service event's `at` is the
    fixture's DECLARED synthetic clock (start + step x seq), while a gate
    witness run is stamped with the controller's wall clock. They are NOT one
    clock, so Step-6 ordering may never compare them; it uses the service seq,
    the turn boundary and tree identity instead (DESIGN.md)."""
    import inspect

    from skillc import fixture_service, gate_witness
    service_src = inspect.getsource(fixture_service)
    assert "self._clock_start + timedelta(seconds=self._clock_step * seq)" in service_src
    assert "requested_at=time.time()" in inspect.getsource(gate_witness)


_REFUSED_ONE_TURN = [{"decision": "passed-top-level"}, {"decision": "refused-nested"}]


@pytest.mark.parametrize(("declare", "channel", "blocked"), [
    (True, False, False),   # the opt-in: a refused nested launch replays as the live gate credits it
    (False, False, True),   # no opt-in: blocked, as before
    (True, True, True),     # the opt-in with an untrusted channel: still blocked
])
def test_the_judge_replay_applies_the_declared_nested_policy(tmp_path: Path, declare: bool, channel: bool,
                                                             blocked: bool) -> None:
    """Counter-model review pass 2: the replay's credit gate is the live one,
    policy included."""
    data = _draft()
    if declare:
        data["containment"] = {"nested_codex": "refusal-expected"}
    declaration, run_dir = _dry_run_with_report(tmp_path, data)
    attempt_id = _plant_captured(run_dir, declaration, guard_decisions=_REFUSED_ONE_TURN,
                                 guard_policy="refusal-expected" if declare else None,
                                 guard_channel_unavailable=channel)
    [entry] = [a for a in _replay(run_dir, declaration)[1]["attempts"] if a["attempt_id"] == attempt_id]
    assert entry["re_decided"] is True
    assert ("nested codex observed" in str(entry["replay_blocked_reason"])) is blocked, entry["replay_blocked_reason"]


# ------------------------------- #279 PR-2a: the task registry and extras

def test_the_task_registry_selects_cases_and_keeps_434_byte_identical() -> None:
    assert fl.TASKS[fl.TASK_PATH] == fl.CASES == ("clean", "twin")
    for path, digest in ((CAMPAIGN, CAMPAIGN_DIGEST), (CAMPAIGN_REV4, CAMPAIGN_REV4_DIGEST), (DRAFT, PACKAGED_DIGEST)):
        declaration = fl.load_declaration(path)
        assert declaration.digest == digest and declaration.task_path == fl.TASK_PATH
    assert fl.required_identities(fl.TASK_PATH) == fl.REQUIRED_IDENTITIES


def test_a_step6_declaration_takes_its_own_cases() -> None:
    data = _draft()
    data["task"]["path"] = fl.STEP6_TASK_PATH
    with pytest.raises(fl.LiveRefused, match="cases must be distinct names from"):
        fl.parse_declaration(data)  # #434's cases are not this task's
    data["cases"] = ["twin-gate"]
    data["attempts_per_case"] = 1
    data["case_order"] = {"seed": 1, "sequence": calibration.derive_arm_order(1, ["twin-gate"], 1)}
    assert fl.parse_declaration(data).task_path == fl.STEP6_TASK_PATH
    assert ("task", "base_trees", "twin-gate") in fl.required_identities(fl.STEP6_TASK_PATH)
    with pytest.raises(fl.LiveRefused, match="no loadable grader"):
        fl.task_identity(ROOT, fl.STEP6_TASK_PATH)  # until #279 PR-2b builds it


def test_an_unregistered_task_path_is_refused(tmp_path: Path) -> None:
    data = _draft()
    data["task"]["path"] = "evals/level3/somewhere-else"
    with pytest.raises(fl.LiveRefused, match="must be one of"):
        fl.require_approved(fl.parse_declaration(data), ROOT, approval_required=False)
    with pytest.raises(fl.LiveRefused, match="must be one of"):
        fl.task_identity(ROOT, "evals/level3/somewhere-else")


def test_raw_extras_with_ordered_turns_keep_their_provenance() -> None:
    assert fl._RAW_EXTRAS_KEYS | {"controller_turns"} in fl._RAW_EXTRAS_KEY_SETS
    assert fl._RAW_EXTRAS_KEYS | {"anything"} not in fl._RAW_EXTRAS_KEY_SETS


# ------------------------------- the revision-5 campaign (#434, after #499)

CAMPAIGN_REV5 = ROOT / "evals" / "level3" / "campaign-434-live" / "campaign-declaration-rev5.json"
#: The draft's content digest, as it goes into the owner's approval package. A
#: changed field must change this line on purpose.
CAMPAIGN_REV5_DIGEST = "sha256:15343e09690b7d290b9bc9740daf1536b76d277752eb03997fa5b4c9335326b0"
#: The ONLY fields the revision-5 draft may differ in from the owner-approved
#: revision-4 campaign (90accda5): its identities moved with the grader (#499),
#: its store and comment are its own, and it carries no approval. Orchestrator
#: condition, as for revision 4: an allow-list, so ANY other difference fails.
_REV5_MAY_DIFFER = {("_comment",), ("run_store",), ("approval",), ("task", "grader_revision"),
                    ("task", "grader_digest")}


def _rev5_differences(a: Any, b: Any, path: tuple[str, ...] = ()) -> set[tuple[str, ...]]:
    if isinstance(a, dict) and isinstance(b, dict) and path not in _REV5_MAY_DIFFER:
        return {d for k in set(a) | set(b) for d in _rev5_differences(a.get(k, _ABSENT), b.get(k, _ABSENT), (*path, k))}
    return set() if a == b else {path}


def test_the_revision_5_campaign_differs_from_the_approved_revision_4_only_where_allowed() -> None:
    approved, draft = json.loads(CAMPAIGN_REV4.read_text()), json.loads(CAMPAIGN_REV5.read_text())
    differences = _rev5_differences(approved, draft)
    assert differences <= _REV5_MAY_DIFFER, sorted(differences - _REV5_MAY_DIFFER)
    # Each allowed difference is real, not a field quietly dropped.
    assert ("approval",) in differences and draft["approval"]["declaration_digest"] == CAMPAIGN_REV5_DIGEST
    assert draft["task"]["grader_revision"] == "5" and draft["run_store"] != approved["run_store"]
    # Only the grader moved: the goal, builder and base trees are revision 4's exactly.
    for key in ("goal_sha256", "builder_sha256", "base_trees"):
        assert draft["task"][key] == approved["task"][key], key


def test_the_revision_5_allow_list_catches_any_other_difference() -> None:
    """The instrument's own red: a changed term outside the allow-list is
    REJECTED, not merely named - including the identities revision 4 was
    allowed to move but revision 5 is not."""
    draft = json.loads(CAMPAIGN_REV5.read_text())
    approved = json.loads(CAMPAIGN_REV4.read_text())
    for path, value in ((("shared", "per_attempt_seconds"), 901), (("case_order", "seed"), 1),
                        (("tolerance", "non_evaluable_per_case"), 2), (("task", "instruction"), "x"),
                        (("task", "builder_sha256"), "0" * 64), (("task", "goal_sha256"), "0" * 64)):
        tampered = copy.deepcopy(draft)
        tampered[path[0]][path[1]] = value
        assert path in _rev5_differences(approved, tampered) - _REV5_MAY_DIFFER, path


def test_the_revision_5_campaign_carries_the_owners_approval_and_is_pinned() -> None:
    """The owner approved the revision-5 campaign on 2026-10-21 ("Yes",
    replying to the package skillc-400 relayed). The stamp changed nothing the
    owner approved: the content digest is the packaged one, and the file
    authorizes as committed."""
    declaration = fl.load_declaration(CAMPAIGN_REV5)
    assert declaration.digest == CAMPAIGN_REV5_DIGEST
    approval = declaration.approval
    assert approval is not None and approval["by"] == "owner (cooneycw)" and approval["attempts_per_case"] == 5
    assert "'Yes'" in approval["source"] and CAMPAIGN_REV5_DIGEST in approval["source"]
    assert approval["declaration_digest"] == CAMPAIGN_REV5_DIGEST
    fl.require_approved(declaration, ROOT)
    assert declaration.task["grader_revision"] == "5" and declaration.attempts_per_case == 5
    assert declaration.order == fl.load_declaration(CAMPAIGN_REV4).order   # the same order, kept on purpose
    assert declaration.endpoint == ENDPOINT and declaration.tolerance == 1


#: The owner-approved revision-4 campaign run (20261020T195431Z-fab3ce): the
#: revision-5 campaign's no-false-stop check reads its retained evidence the
#: same way as the revision-3 run's above - plain files by manifest digest,
#: never committed, skipping loudly only where the store is absent.
REV4_RUN_STORE = (Path.home() / "skillc-evidence" / "campaign-434-live" / "campaign-rev4" / "20261020T195431Z-fab3ce"
                  / "store" / "level3-fixture-live-1895ef73")
REV4_RUN_ATTEMPTS = ("a-2f11075c6f7e", "a-4bfc6b07d64c", "a-6e9b5c523500", "a-911dd78a056f", "a-9b1435266f4b",
                     "a-b50b7e7890e5", "a-c9c21147fd2b", "a-eecda7b2282c", "a-f538f3cabf2c", "a-fbdd03ea5fbc")


def _rev4_run_record(attempt_id: str, *, transcript_suffix: bytes = b"") -> dict[str, Any]:
    """`_retained_record`'s rebuild, over the revision-4 run, prompted as the
    revision-5 declaration prompts (the same instruction, by the allow-list)."""
    manifest = json.loads((REV4_RUN_STORE / f"manifest-{attempt_id}.json").read_text())
    transcript = (_retained_object(REV4_RUN_STORE, _complete_stream(manifest, "client-transcript"))
                  + transcript_suffix)
    observation, census, metadata = at.observe_transcript_bytes(
        at.CLIENT_SPECS[fl.CLIENT], transcript, expected_prompt=fl.prompt(fl.load_declaration(CAMPAIGN_REV5), ROOT),
        skill_name=None)
    proxy = _retained_object(REV4_RUN_STORE, _complete_stream(manifest, eg.PROXY_LOG_STREAM))
    return {"disposition": "captured", "fixture": {"codex_guard": _retained_guard(REV4_RUN_STORE, attempt_id)},
            "observation": {"status": "observed", **observation.to_fields(), **census, "run_metadata": metadata,
                            "egress": {"status": "read", "digest": trial.sha256_bytes(proxy), **eg.summarize_log(proxy)}}}


@pytest.mark.parametrize("attempt_id", REV4_RUN_ATTEMPTS)
def test_the_revision_5_campaign_does_not_false_stop_on_the_revision_4_run(attempt_id: str) -> None:
    """The no-false-stop check for the revision-5 package: every attempt of the
    owner-approved revision-4 run passes this tree's containment trigger under
    the revision-5 declaration's allowlist and policy; the same transcript with
    one unknown response item appended STOPS (the control)."""
    if not REV4_RUN_STORE.is_dir():
        pytest.skip(f"PRIVATE EVIDENCE ABSENT: {REV4_RUN_STORE} is not on this host; "
                    "the revision-5 no-false-stop check did not run")
    missing = [a for a in REV4_RUN_ATTEMPTS if not (REV4_RUN_STORE / f"manifest-{a}.json").is_file()]
    assert not missing, f"the retained revision-4 store is incomplete: {missing}"
    declaration = fl.load_declaration(CAMPAIGN_REV5)
    allowlist = str(declaration.shared["agent_network"]["allowlist_digest"])
    assert fl.containment_trigger(_rev4_run_record(attempt_id), allowlist_digest=allowlist,
                                  nested_policy=declaration.nested_policy) is None
    stopped = fl.containment_trigger(_rev4_run_record(attempt_id, transcript_suffix=_UNKNOWN_ITEM),
                                     allowlist_digest=allowlist, nested_policy=declaration.nested_policy)
    assert stopped is not None and "future_item_type" in stopped


def test_the_revision_5_approval_does_not_survive_a_changed_field() -> None:
    data = json.loads(CAMPAIGN_REV5.read_text())
    data["shared"]["per_attempt_seconds"] = 901
    with pytest.raises(fl.LiveRefused, match="does not bind this exact declaration"):
        fl.require_approved(fl.parse_declaration(data), ROOT)


def test_no_rehearsal_stamp_reaches_the_revision_5_declaration() -> None:
    assert "REHEARSAL" not in CAMPAIGN_REV5.read_text(encoding="utf-8")
