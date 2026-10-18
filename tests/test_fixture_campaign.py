"""`skillc.fixture_campaign` (#434 PR 3): the deterministic campaign's actor,
manifest, settings and report, without a container. The run itself is on
evals26 (`evals/level3/campaign-434/RESULTS.md`).

The instruments here, each with its committed red:

- the ACTOR'S OP INTERPRETER plays every PR 1 candidate's git operations to the
  same capture as `qualify._apply_git` (a dropped op is reported);
- the PER-ATTEMPT SETTINGS equal what `collection_conformance.
  run_level1_agent_attempt` passes for the same inputs (a perturbed limit is
  reported), so the two loops cannot drift;
- the committed manifest is `freeze.py`'s output (a flipped expectation is not);
- the report counts UNKNOWN-by-unreadable apart, and raises the pack trigger
  only for a scored row.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import re
import sys
import types
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from skillc import agent_trial, trial
from skillc import collection_conformance as cc
from skillc import fixture_campaign as fc
from skillc import level3_campaign as lc
from skillc import runtime_supply as rs

ROOT = Path(__file__).resolve().parent.parent
TASK_ROOT = ROOT / "evals" / "level3" / fc.TASK
CAMPAIGN = ROOT / "evals" / "level3" / "campaign-434"
MANIFEST = CAMPAIGN / "manifest.json"


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


build = _load("flow_auto_necessity_build_fc", TASK_ROOT / "builder" / "build.py")
qualify = _load("flow_auto_necessity_qualify_fc", TASK_ROOT / "qualify.py")
FREEZE = _load("campaign_434_freeze", CAMPAIGN / "freeze.py")


def _actor() -> Any:
    """The actor source as a module, its `main()` not run."""
    module = types.ModuleType("fixture_campaign_actor")
    exec(compile(fc.ACTOR_SOURCE, "actor.py", "exec"), module.__dict__)  # noqa: S102 - our own committed source
    return module


@pytest.fixture(autouse=True)
def _umask() -> Iterator[None]:
    previous = os.umask(0o022)
    yield
    os.umask(previous)


# --- the actor's op interpreter ------------------------------------------------------

def _with_ops() -> list[str]:
    return sorted(p.relative_to(TASK_ROOT / "candidates").as_posix()
                  for p in (TASK_ROOT / "candidates").glob("*/*")
                  if json.loads((p / "actions.json").read_text()).get("git"))


def _normalized(capture: dict[str, Any], root: Path) -> str:
    return json.dumps(capture, sort_keys=True).replace(str(root), "<root>")


def _qualify_capture(tmp: Path, actions: dict[str, Any]) -> str:
    root = tmp / "q"
    root.mkdir()
    facts = build.build(root, actions["case"])
    qualify._apply_git(root, actions["git"])
    capture = build.capture(lambda a, c: build.host_git(list(a), c), root / "repo", root / "remote.git",
                            facts["base_commit"])
    return _normalized(capture, root)


def _actor_capture(tmp: Path, actions: dict[str, Any], actor: Any) -> str:
    """The container's layout (`.remote/widget.git`), played by the actor."""
    root = tmp / "a"
    root.mkdir()
    remote = root / ".remote" / "widget.git"
    facts = build.build(root, actions["case"], remote_url=str(remote))
    (root / ".remote").mkdir()
    (root / "remote.git").rename(remote)
    actor.apply_ops(str(root), str(remote), actions["git"])
    capture = build.capture(lambda a, c: build.host_git(list(a), c), root / "repo", remote, facts["base_commit"])
    return _normalized(capture, root).replace("<root>/.remote/widget.git", "<root>/remote.git")


@pytest.mark.parametrize("candidate", _with_ops())
def test_the_actor_plays_each_candidates_git_ops_exactly_as_qualify_does(tmp_path: Path, candidate: str) -> None:
    actions = json.loads((TASK_ROOT / "candidates" / candidate / "actions.json").read_text())
    assert _actor_capture(tmp_path, actions, _actor()) == _qualify_capture(tmp_path, actions)


def test_equivalence_control_a_dropped_op_is_reported(tmp_path: Path) -> None:
    """The instrument's committed red: an interpreter that skips `chmod`."""
    candidate = "fail/clean-mode-change"
    actions = json.loads((TASK_ROOT / "candidates" / candidate / "actions.json").read_text())
    assert any(op["op"] == "chmod" for op in actions["git"])
    actor = _actor()
    actor.os = types.SimpleNamespace(**{**{k: getattr(os, k) for k in dir(os) if not k.startswith("__")},
                                        "chmod": lambda *a, **k: None})
    assert _actor_capture(tmp_path, actions, actor) != _qualify_capture(tmp_path, actions)


def test_the_actor_uses_the_builders_identity_and_qualifys_dates() -> None:
    actor = _actor()
    assert actor.IDENTITY == list(build._IDENTITY)
    source = (TASK_ROOT / "qualify.py").read_text()
    assert f'date="{actor.DATE}"' in source and f'date="{actor.PARK_DATE}"' in source
    body = source[source.index("def _apply_git"):source.index("def run_attempt")]
    ops = set(re.findall(r'kind == "([a-z-]+)"', body))
    assert len(ops) >= 15  # the scan read qualify's interpreter, not nothing
    assert ops <= set(re.findall(r'kind == "([a-z-]+)"', fc.ACTOR_SOURCE)), "the actor lacks an op qualify knows"


# --- the per-attempt settings --------------------------------------------------------

def _recorded(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []

    def record(**kwargs: Any) -> dict[str, Any]:
        seen.append(kwargs)
        return {}

    monkeypatch.setattr(agent_trial, "run_one_attempt", record)
    return seen


def _inputs(tmp_path: Path) -> dict[str, Any]:
    treatment = types.SimpleNamespace(receipt_context="RC", verify_home_files={"a": "sha256:0"},
                                      preflight_tools=[{"id": "t"}], gate_entrypoint=".claude/scripts/g.sh")
    return {"experiment": "EXP", "attempt_id": "A1", "backend": "AGENT", "grading_backend": "GRADING",
            "base": tmp_path, "base_argv": ["python3", "actor.py"], "extra_home_files": {"x": b"y"},
            "cli_version": "0.157.1", "task_root": TASK_ROOT, "surface": {"repo": "R"},
            "credential_explicit_path": tmp_path / "cred.json", "timeout": lc.PER_ATTEMPT_SECONDS,
            "treatment": treatment}


def _both(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[dict[str, Any], dict[str, Any]]:
    seen = _recorded(monkeypatch)
    i = _inputs(tmp_path)
    t = i["treatment"]
    cc.run_level1_agent_attempt(
        experiment=i["experiment"], attempt_id=i["attempt_id"], backend=i["backend"],
        grading_backend=i["grading_backend"], base=i["base"], base_argv=i["base_argv"],
        extra_home_files=i["extra_home_files"], cli_version=i["cli_version"], client="codex",
        surface=i["surface"], task_root=i["task_root"], timeout=i["timeout"],
        credential_explicit_path=i["credential_explicit_path"], receipt_context=t.receipt_context,
        verify_home_files=t.verify_home_files, preflight_tools=t.preflight_tools,
        gate_entrypoint=t.gate_entrypoint)
    ours = fc.attempt_kwargs(**i, fixture="FIXTURE")  # type: ignore[arg-type]
    assert ours.pop("fixture") == "FIXTURE"
    return seen[0], ours


def test_the_campaigns_attempt_settings_are_the_wrappers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Orchestrator condition: limits, credential handling, grader, treatment
    fields and every other setting equal run_level1_agent_attempt's for the same
    inputs. The backends (and so the network) come from the same
    level3_campaign.campaign_backends #375 uses."""
    theirs, ours = _both(tmp_path, monkeypatch)
    assert set(ours) == set(theirs)
    for key in theirs:
        if key == "grader":
            assert ours[key].identity() == theirs[key].identity()
        else:
            assert ours[key] == theirs[key], key


def test_settings_control_one_perturbed_setting_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The committed red: the campaign's limits drifting from the wrapper's."""
    real = fc.Limits
    monkeypatch.setattr(fc, "Limits", lambda timeout: real(timeout=timeout, grace=9.0))
    theirs, ours = _both(tmp_path, monkeypatch)
    assert ours["limits"] != theirs["limits"]


def test_the_campaign_reuses_level3s_network_free_backends() -> None:
    source = (ROOT / "skillc" / "cli.py").read_text()
    assert "fc.run_rows" in source and "lc.campaign_backends" in source
    assert lc.AGENT_NETWORK == "none"


# --- the runtime --------------------------------------------------------------------

def test_the_flow_auto_closure_selects_the_existing_profile_runtime() -> None:
    """Reused, not added: the closure carries the policy's own project
    metadata, at the same pin and gate entrypoint."""
    snapshot = ROOT / "tests" / "fixtures" / "profile-cpp-codex-flow-auto-86641e8"
    policy = rs.supported_policy()
    files = {f"{policy['project']}/{name}": trial.sha256_bytes((snapshot / name).read_bytes())
             for name in ("pyproject.toml", "uv.lock")}
    declared = json.loads((ROOT / "evals" / "subjects" / "cpp-codex-flow-auto-86641e8" / "profile.json").read_text())
    tools = [d for d in declared["dependencies"] if d["kind"] == "tool"]
    subject = json.loads((ROOT / "evals" / "subjects" / "cpp-codex-flow-auto-86641e8" / "subject.json").read_text())
    selected = rs.selected_runtime(locator=subject["locator"], revision=subject["revision"],
                                   gate_entrypoint=declared["gate_entrypoint"], files=files, tools=tools)
    assert selected == rs.PROFILE_RUNTIME
    # Red: one changed lock digest is a refusal, never a quiet reuse.
    with pytest.raises(rs.Refused):
        rs.selected_runtime(locator=subject["locator"], revision=subject["revision"],
                            gate_entrypoint=declared["gate_entrypoint"],
                            files={**files, f"{policy['project']}/uv.lock": "sha256:" + "0" * 64}, tools=tools)


# --- the manifest -------------------------------------------------------------------

def test_the_committed_manifest_is_the_freeze_scripts_output() -> None:
    derived = FREEZE.manifest()
    assert json.loads(MANIFEST.read_text()) == derived
    tampered = copy.deepcopy(derived)
    scored = next(r for r in tampered["rows"] if r["kind"] == "scored")
    scored["expected"]["criteria"]["verdict"] = "VIOLATED" if scored["expected"]["criteria"]["verdict"] != "VIOLATED" \
        else "SATISFIED"
    assert tampered != derived


def test_the_population_is_every_candidate_plus_three_guard_rows() -> None:
    manifest = fc.load_manifest(MANIFEST)
    candidates = sorted(p.relative_to(TASK_ROOT / "candidates").as_posix() for p in (TASK_ROOT / "candidates").glob("*/*"))
    assert sorted(r.candidate for r in manifest.rows if r.kind != "guard") == candidates
    assert [r.guard for r in manifest.rows if r.kind == "guard"] == ["nested", "suspected", "none"]
    observed = {r.candidate for r in manifest.rows if r.kind == "observed"}
    for candidate in candidates:
        witness = json.loads((TASK_ROOT / "candidates" / candidate / "actions.json").read_text()).get("witness", "no-runs")
        assert (candidate in observed) == (witness in fc.OBSERVED_WITNESSES), candidate


def test_frozen_identities_hold_on_this_tree() -> None:
    assert fc.check_frozen(fc.load_manifest(MANIFEST), ROOT) == []


@pytest.mark.parametrize("mutate, named", [
    (lambda m: m["frozen"].update(harness_digest="sha256:" + "0" * 64), "actor or fake client"),
    (lambda m: m["frozen"]["task"].update(builder_sha256="0" * 64), "frozen identity"),
    (lambda m: m["frozen"]["subject"].update(inventory_digest="sha256:" + "0" * 64), "inventory digest"),
    (lambda m: m["rows"][0].update(candidate_digest="sha256:" + "0" * 64), "bytes moved"),
])
def test_each_frozen_identity_can_report_a_move(tmp_path: Path, mutate: Any, named: str) -> None:
    data = json.loads(MANIFEST.read_text())
    mutate(data)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(data))
    problems = fc.check_frozen(fc.load_manifest(path), ROOT)
    assert any(named in p for p in problems), problems


@pytest.mark.parametrize("mutate", [
    lambda m: m["rows"].append(dict(m["rows"][0])),                                    # duplicate id
    lambda m: next(r for r in m["rows"] if r["kind"] == "scored").update(guard="nested"),
    lambda m: next(r for r in m["rows"] if r["kind"] == "guard").update(expected={"blocked_reason": "x"}),
    lambda m: next(r for r in m["rows"] if r["kind"] == "observed").update(expected={"status": "PASS"}),
    lambda m: m.update(rows=[r for r in m["rows"] if r["kind"] != "scored"]),           # nothing scored
    lambda m: m.update(kind="level3-production-campaign"),
])
def test_malformed_manifests_are_refused(tmp_path: Path, mutate: Any) -> None:
    data = json.loads(MANIFEST.read_text())
    mutate(data)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(data))
    with pytest.raises(fc.CampaignRefused):
        fc.load_manifest(path)


# --- judging and the report ---------------------------------------------------------

def _row(kind: str, guard: str = "top-level", **expected: Any) -> fc.Row:
    return fc.Row("r", kind, "pass/x", guard, "d", expected.get("status"), expected.get("criteria", {}),
                  expected.get("reason"))


def test_a_guard_row_matches_only_its_blocked_reason() -> None:
    row = _row("guard", "nested", reason=fc.GUARD_REASONS["nested"])
    assert fc.judge_row(row, {"graded": None, "grading_blocked_reason": fc.GUARD_REASONS["nested"]}) == []
    assert fc.judge_row(row, {"graded": None, "grading_blocked_reason": fc.GUARD_REASONS["none"]})
    assert fc.judge_row(row, {"graded": {"status": "PASS"}, "grading_blocked_reason": fc.GUARD_REASONS["nested"]})


def test_an_observed_row_is_never_a_mismatch() -> None:
    assert fc.judge_row(_row("observed"), {"graded": {"status": "FAIL", "criteria": []}}) == []


def _result(row: str, kind: str, case: str, verdict: str, unreadable: str | None = None) -> dict[str, Any]:
    return {"row": row, "kind": kind, "case": case, "verdict": verdict, "unreadable": unreadable}


def test_the_report_sets_clean_and_twin_side_by_side_and_counts_unreadable_apart() -> None:
    results = [_result("c1", "scored", "clean", "MATCH"), _result("c2", "scored", "clean", "MISMATCH"),
               _result("t1", "scored", "twin", "MATCH"), _result("g1", "guard", "clean", "MATCH"),
               _result("o1", "observed", "clean", "OBSERVED", unreadable="capture: not loose")]
    report = fc.report(results, experiment_id="e", image_digest="i", treatment_digest="t")
    assert (report["clean"]["population"], report["clean"]["matched"]) == (2, 1)
    assert (report["twin"]["population"], report["twin"]["matched"]) == (1, 1)
    assert report["guard"]["matched"] == 1 and [r["row"] for r in report["observed"]["rows"]] == ["o1"]
    assert report["unreadable"] == {"count": 1, "rows": ["o1"], "scored_rows": [], "trigger": None}
    assert report["scored_population"] == 4 and "actor, not the agent" in report["top_level_process"]


def test_an_unreadable_scored_row_raises_the_pack_trigger() -> None:
    """The orchestrator's PR 2a condition: any necessity or must-act row there
    blocks #434's results until pack support exists."""
    report = fc.report([_result("t1", "scored", "twin", "MATCH", unreadable="remote: not loose")],
                       experiment_id="e", image_digest="i", treatment_digest="t")
    assert report["unreadable"]["scored_rows"] == ["t1"] and report["unreadable"]["trigger"]


@pytest.mark.parametrize("evidence, why", [
    (None, "no fixture evidence"),
    ({"git_unreadable": "not loose"}, "capture: not loose"),
    ({"git_unreadable": None, "service": {"divergence": [{"kind": "remote-unreadable", "detail": "packed"}]}},
     "remote: packed"),
    ({"git_unreadable": None, "service": {"divergence": [{"kind": "default-branch-moved-outside-service"}]}}, None),
])
def test_unreadable_names_only_a_read_that_failed(evidence: Any, why: str | None) -> None:
    found = fc.unreadable(evidence)
    assert (found is None) == (why is None) and (why is None or why in str(found))


def test_the_actor_argv_runs_the_gate_only_for_an_observed_gate_run() -> None:
    observed, scored = _row("observed"), _row("scored")
    assert fc.actor_argv(observed, {"witness": "passed-run"})[-1] == "run-gate"
    assert fc.actor_argv(observed, {"witness": "none"})[-1] == "no-gate"
    # Revision 2: a scored passed-run row runs the real gate too (its exit 0 is earned).
    assert fc.actor_argv(scored, {"witness": "passed-run"})[-1] == "run-gate"
    assert fc.actor_argv(scored, {"witness": "no-runs"})[-1] == "no-gate"


def test_the_command_routes_a_fixture_manifest_to_the_fixture_harness(tmp_path: Path, capsys: Any) -> None:
    """A moved harness digest in a fixture manifest is refused with the
    fixture harness's OWN message, before any container exists: the command
    read it through fixture_campaign, not level3_campaign."""
    from skillc import cli
    data = json.loads(MANIFEST.read_text())
    data["frozen"]["harness_digest"] = "sha256:" + "0" * 64
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(data))
    code = cli.main(["level3-campaign", "--manifest", str(path), "--runtime-supply-receipt", str(tmp_path / "r.json")])
    assert code == 2
    assert "the fixture-campaign actor or fake client changed" in capsys.readouterr().err


# --- counter-model review, PR 3 pass 1 ---------------------------------------------

@pytest.mark.parametrize("runtime", [{}, "drop-one"])
def test_an_empty_or_partial_runtime_identity_is_refused(tmp_path: Path, runtime: Any) -> None:
    """An empty runtime block made check_frozen compare nothing."""
    data = json.loads(MANIFEST.read_text())
    data["frozen"]["runtime"] = {} if runtime == {} else dict(list(data["frozen"]["runtime"].items())[1:])
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(data))
    with pytest.raises(fc.CampaignRefused, match="frozen.runtime"):
        fc.load_manifest(path)


def test_an_observation_only_selection_certifies_nothing(tmp_path: Path, capsys: Any) -> None:
    """`--rows <observed>` used to read 0/0 matched and exit 0."""
    from skillc import cli
    manifest = fc.load_manifest(MANIFEST)
    observed = [r for r in manifest.rows if r.kind == "observed"]
    assert fc.certifying_selection(observed) and fc.certifying_selection(list(manifest.rows)) is None
    code = cli.main(["level3-campaign", "--manifest", str(MANIFEST), "--rows", observed[0].id,
                     "--runtime-supply-receipt", str(tmp_path / "r.json")])
    assert code == 2 and "certifies nothing" in capsys.readouterr().err


def test_an_unreadable_scored_row_fails_the_run_even_when_it_matched() -> None:
    """The pack trigger used to leave the exit code at success."""
    matched = [_result("t1", "scored", "twin", "MATCH")]
    assert fc.succeeded(fc.report(matched, experiment_id="e", image_digest="i", treatment_digest="t"))
    unreadable = [_result("t1", "scored", "twin", "MATCH", unreadable="remote: not loose")]
    assert not fc.succeeded(fc.report(unreadable, experiment_id="e", image_digest="i", treatment_digest="t"))


def test_the_campaign_kwargs_bind_to_run_one_attempt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`fixture_live.run_attempt` passes `attempt_kwargs(...)` straight to
    `agent_trial.run_one_attempt(**kwargs)`, and its own test stubs that call, so
    a key the real function does not accept (e.g. #287 auto6's `gate_witness`)
    would only fail live. Bind the produced dict to the real signature."""
    import inspect

    i = _inputs(tmp_path)
    ours = fc.attempt_kwargs(**i, fixture="FIXTURE")  # type: ignore[arg-type]
    assert "gate_witness" in ours and ours["gate_witness"] is None
    inspect.signature(agent_trial.run_one_attempt).bind(**ours)
