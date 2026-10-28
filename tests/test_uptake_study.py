"""Tests for the two-arm skill-uptake study (#237): the declaration, the
rewritten-snapshot guard, the exact Fisher test, and the runner end to end
against the fake docker CLI and a scripted client (no real agent)."""

from __future__ import annotations

import copy
import dataclasses
import json
import math
import shutil
import sys
import time
from collections.abc import Sequence
from pathlib import Path

import pytest
from test_calibration_run import (
    _FAKE_DAEMON_TIMEOUT,
    _IMAGE,
    _IMAGE_DIGEST,
    CODEX_FIXTURE,
    FAKE_CLIENT,
    _docker_bin,
    _fresh_codex_credential,
)

from skillc import agent_trial, demo, materialize, trial, verify
from skillc import calibration_run as cr
from skillc import collection_conformance as cc
from skillc import docker_backend as d
from skillc import matched_pilot as mp
from skillc import uptake_study as us

ROOT = Path(__file__).resolve().parent.parent
TASK = ROOT / "evals" / "level1" / "slug-small-fix"
NEW = "Use before you report a change as done: run this project's quality checks in one step."
SUBJECT = {"name": "cpp-codex", "locator": "github.com/cooneycw/claude-power-pack",
           "revision": "85e9b03ad2af1c41020ff6d92d36fa257bdacd2b"}


def _data(*, n_primary: int = 3, n_secondary: int = 3, approved: bool = True) -> dict[str, object]:
    grader = verify.GraderDef.load(TASK)
    cases = [
        {"id": "intended-use", "prompt_addendum": "Before finishing, run this project's quality checks.",
         "attempts_per_arm": n_primary, "primary": True},
        {"id": "near-miss", "prompt_addendum": "", "attempts_per_arm": n_secondary, "primary": False},
    ]
    parsed = [us.Case(c["id"], c["prompt_addendum"], c["attempts_per_arm"], c["primary"]) for c in cases]  # type: ignore[arg-type]
    return {
        "kind": "uptake-study", "issue": 237,
        "approval": {"by": "owner", "at": "2026-10-04"} if approved else None,
        "task": {"path": "evals/level1/slug-small-fix", "grader_id": grader.id, "grader_revision": grader.revision},
        "arms": [{"name": "published", "subject": dict(SUBJECT)},
                 {"name": "rewritten", "subject": dict(SUBJECT), "target_skill": "flow-check", "description": NEW}],
        "shared": {"client": {"name": "codex", "version": "0.157.1"}, "model": "gpt-6-astra",
                   "reasoning_effort": "high", "tools": "defaults", "permissions": "the same for every attempt",
                   "public_requirements": "goal.md plus each case's addendum",
                   "image": {"tag": "skillc-trial:latest", "digest": _IMAGE_DIGEST},
                   "per_attempt_seconds": 600, "total_seconds": (600 + 16) * 2 * (n_primary + n_secondary)},
        "cases": cases,
        "test": {"kind": "fisher-exact-one-sided", "direction": "rewritten > published", "alpha": 0.05},
        "arm_order": {"seed": 7, "sequence": [list(x) for x in us.derive_order(7, parsed)]},
    }


# --------------------------------------------------------------- declaration


def test_a_well_formed_declaration_parses_and_authorizes() -> None:
    declaration = us.parse_declaration(_data())
    assert declaration.primary.id == "intended-use"
    assert len(declaration.arm_order) == 12
    us.require_approved(declaration, ROOT)


def test_red_without_its_approval_it_is_refused() -> None:
    with pytest.raises(us.StudyRefused, match="not approved"):
        us.require_approved(us.parse_declaration(_data(approved=False)), ROOT)


def _mutate(path: tuple[object, ...], value: object) -> dict[str, object]:
    data = copy.deepcopy(_data())
    node: object = data
    for key in path[:-1]:
        node = node[key]  # type: ignore[index]
    node[path[-1]] = value  # type: ignore[index]
    return data


@pytest.mark.parametrize(("path", "value", "match"), [
    (("kind",), "calibration-declaration", "kind is"),
    (("arms", 1, "subject"), {"name": "another"}, "different subjects"),
    (("arms", 1, "model"), "x", "may carry only"),
    (("arms", 1, "description"), "two\nlines", "one non-empty line"),
    (("arms", 1, "description"), "Use checks\rdisable-model-invocation: true", "printable"),
    (("arms", 1, "description"), "Use checks\u2028more", "printable"),
    (("arms", 1, "target_skill"), "", "same, non-empty target_skill"),
    (("cases", 0, "attempts_per_arm"), 31, "3-30"),
    (("cases", 0, "attempts_per_arm"), 2, "3-30"),
    (("cases", 1, "primary"), True, "exactly one case is primary"),
    (("cases", 1, "id"), "intended-use", "distinct"),
    (("test", "alpha"), 1.5, "between 0 and 1"),
    (("test", "kind"), "t-test", "fisher-exact-one-sided"),
    (("arm_order", "seed"), 8, "chosen by hand"),
    (("shared", "total_seconds"), 600, "cannot cover"),
])
def test_a_declaration_that_breaks_the_design_is_refused(path: tuple[object, ...], value: object, match: str) -> None:
    with pytest.raises(us.StudyRefused, match=match):
        us.parse_declaration(_mutate(path, value))


# ------------------------------------------------------------ Fisher's exact


def _brute(r: int, nr: int, p: int, np_: int) -> float:
    total, population = r + p, nr + np_
    return sum(math.comb(nr, k) * math.comb(np_, total - k) for k in range(r, min(total, nr) + 1)) / math.comb(
        population, total)


@pytest.mark.parametrize(("r", "nr", "p", "np_"), [(8, 20, 1, 20), (3, 20, 1, 20), (0, 20, 0, 20), (20, 20, 0, 20)])
def test_fisher_matches_the_hypergeometric_tail(r: int, nr: int, p: int, np_: int) -> None:
    assert us.fisher_one_sided(r, nr, p, np_) == pytest.approx(_brute(r, nr, p, np_))


def test_fisher_extremes() -> None:
    assert us.fisher_one_sided(0, 20, 0, 20) == 1.0  # nothing selected anywhere: no evidence
    assert us.fisher_one_sided(20, 20, 0, 20) < 1e-10
    assert us.fisher_one_sided(1, 20, 1, 20) > 0.5  # equal arms are never "significant"
    assert us.fisher_one_sided(0, 0, 0, 0) == 1.0


# ------------------------------------------------- the rewritten-snapshot guard


def _skill(description: str, body: str = "Body.\n") -> bytes:
    return f'---\nname: "flow-check"\ndescription: {json.dumps(description)}\n---\n{body}'.encode()


_PUBLISHED = {".codex/skills/flow-check/SKILL.md": _skill("Run quality checks"),
              ".codex/skills/qa-test/SKILL.md": b"---\nname: qa-test\ndescription: web\n---\n"}


def test_only_the_target_description_may_differ() -> None:
    rewritten = {**_PUBLISHED, ".codex/skills/flow-check/SKILL.md": _skill(NEW)}
    assert us.check_rewritten_files(_PUBLISHED, rewritten, "flow-check", NEW) == ".codex/skills/flow-check/SKILL.md"


@pytest.mark.parametrize(("rewritten", "match"), [
    ({".codex/skills/flow-check/SKILL.md": _skill("something else")}, "not the declared one"),
    ({".codex/skills/flow-check/SKILL.md": _skill(NEW, "Changed body.\n")}, "more than its description line"),
    ({".codex/skills/qa-test/SKILL.md": b"---\nname: qa-test\ndescription: changed\n---\n"}, "is not flow-check"),
    ({".codex/skills/flow-check/SKILL.md": _skill(NEW), ".codex/skills/qa-test/SKILL.md": b"x"}, "2 file"),
    ({}, "0 file"),
    # A nested file of the target's name inside another skill is not its entry point.
    ({".codex/skills/qa-test/references/flow-check/SKILL.md": _skill(NEW)}, "entry point"),
])
def test_red_any_other_difference_is_refused(rewritten: dict[str, bytes], match: str) -> None:
    with pytest.raises(us.StudyRefused, match=match):
        us.check_rewritten_files(_PUBLISHED, {**_PUBLISHED, **rewritten}, "flow-check", NEW)


# ---------------------------------------------------------- end to end (fake)


def _treatment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str, description: str) -> cr.Treatment:
    collection = tmp_path / f"collection-{name}"
    skill = collection / "skills" / "flow-check"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_bytes(_skill(description))
    subject = materialize.Subject.from_dict({
        "subject_schema": 1, "locator": "test/test", "revision": "v1", "surface": "codex-skills",
        "skills_root": "skills", "select": ["flow-check"], "client": {"name": "codex", "version": "0.157.1"},
    })
    monkeypatch.setattr(demo, "load_demo_subject", lambda _name: subject)
    base = tmp_path / f"acquire-{name}"
    base.mkdir()
    acquired = cc.acquire_collection("whatever", base, checkout=collection)
    script = tmp_path / f"listing-{name}" / "fake_codex.py"
    script.parent.mkdir()
    shutil.copy(CODEX_FIXTURE / "fake_codex.py", script)
    script.with_suffix(".mode").write_text(json.dumps({"mode": "normal"}), encoding="utf-8")
    return cr.build_treatment(acquired, listing_client_argv=[sys.executable, str(script)])


def _run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, select_in: Sequence[str]) -> tuple[
        trial.Experiment, list[mp.AttemptOutcome], list[dict[str, object]]]:
    """Plant a `flow-check` invocation in every attempt whose `case__arm`
    label is in `select_in`; the rest invoke nothing."""
    declaration = us.parse_declaration(_data())
    treatments = {"published": _treatment(tmp_path, monkeypatch, "published", "Run quality checks"),
                  "rewritten": _treatment(tmp_path, monkeypatch, "rewritten", NEW)}
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    state = tmp_path / "docker-state"
    seen: list[dict[str, object]] = []
    real = cc.run_level1_agent_attempt

    def spy(**kwargs: object) -> dict[str, object]:
        seen.append(dict(kwargs))
        return real(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(cc, "run_level1_agent_attempt", spy)

    def backends() -> tuple[object, object]:
        make = lambda: d.DockerBackend(image=_IMAGE, base_dir=run_dir, docker_bin=_docker_bin(state),
                                       daemon_timeout=_FAKE_DAEMON_TIMEOUT)
        return make(), make()

    def argv_for(scheduled: mp.ScheduledAttempt) -> list[str]:
        home = state / f"{d._container_name(scheduled.attempt_id)}.fsroot" / "home" / "candidate"
        argv = [sys.executable, str(FAKE_CLIENT), "--format", "codex-fake", "--home", str(home),
                "--transcript-relpath", f".codex/sessions/2026/01/01/rollout-{scheduled.attempt_id}.jsonl",
                "--copy-solution", str(TASK / "reference")]
        if scheduled.arm in select_in:
            argv += ["--plant-skill", "flow-check"]
        return argv

    experiment, outcomes = us.run_study(
        declaration, run_dir=run_dir, treatments=treatments, image_digest=_IMAGE_DIGEST, backends=backends,
        argv_for=argv_for, root=ROOT, credential_explicit_path=_fresh_codex_credential(tmp_path),
        clock=time.monotonic,
    )
    return experiment, outcomes, seen


def test_the_arms_differ_only_in_the_install_and_selection_is_counted_and_tested(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    experiment, outcomes, seen = _run(tmp_path, monkeypatch, select_in=("intended-use__rewritten",))
    declaration = us.parse_declaration(_data())
    assert len(seen) == 12
    goal = (TASK / "goal.md").read_text(encoding="utf-8")
    arm_of = {o.scheduled.attempt_id: o.scheduled.arm for o in outcomes}
    for call in seen:
        case, _arm = arm_of[str(call["attempt_id"])].split("__")
        want = goal if case == "near-miss" else f"{goal.rstrip()}\n\nBefore finishing, run this project's quality checks.\n"
        assert call["prompt"] == want
    report = us.build_report(experiment, us.reconcile(experiment, outcomes), declaration)
    cells = report["cells"]
    assert cells["intended-use"]["rewritten"] == {"scheduled": 3, "observed": 3, "selected": 3}  # type: ignore[index]
    assert cells["intended-use"]["published"] == {"scheduled": 3, "observed": 3, "selected": 0}  # type: ignore[index]
    assert cells["near-miss"]["rewritten"]["selected"] == 0  # type: ignore[index]
    test = report["primary_test"]
    assert test["rewritten"] == "3/3" and test["published"] == "0/3"  # type: ignore[index]
    assert test["p_value"] == pytest.approx(us.fisher_one_sided(3, 3, 0, 3))  # type: ignore[index]
    assert all(e["model_eligible"] is not False for e in report["attempts"])  # type: ignore[union-attr,attr-defined]
    assert "rewritten 3/3 vs published 0/3" in us.paste_back(report)


@pytest.mark.parametrize("profile_arm", ["published", "rewritten"])
def test_profile_closure_fields_reach_run_one_attempt_for_the_selected_arm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, profile_arm: str,
) -> None:
    """#346: observe beyond the real collection wrapper, without starting an
    agent. The other uptake arm has no profile, not an empty-install baseline.
    Closure construction and verification have their own tests; sentinel
    fields here isolate the production callers' forwarding contract."""
    declaration = us.parse_declaration(_data())
    treatments = {"published": _treatment(tmp_path, monkeypatch, "published", "Run quality checks"),
                  "rewritten": _treatment(tmp_path, monkeypatch, "rewritten", NEW)}
    gate = ".claude/scripts/flow-finish-gate.sh"
    gate_bytes = b"#!/bin/sh\nexit 0\n"
    checks = {gate: materialize.sha256_bytes(gate_bytes)}
    tools: tuple[dict[str, object], ...] = ({"id": "shell", "probes": [{"argv": ["sh", "--version"]}]},)
    treatments[profile_arm] = dataclasses.replace(
        treatments[profile_arm],
        home_files={**treatments[profile_arm].home_files, gate: gate_bytes},
        verify_home_files=checks, preflight_tools=tools, gate_entrypoint=gate,
    )
    seen: dict[str, dict[str, object]] = {}

    def observe_attempt(**kwargs: object) -> dict[str, object]:
        attempt_id = str(kwargs["attempt_id"])
        seen[attempt_id] = kwargs
        experiment = kwargs["experiment"]
        assert isinstance(experiment, trial.Experiment)
        return trial.finalize(experiment, attempt_id, disposition="unavailable",
                              reason="forwarding test stops at the agent boundary")

    monkeypatch.setattr(agent_trial, "run_one_attempt", observe_attempt)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _, outcomes = us.run_study(
        declaration, run_dir=run_dir, treatments=treatments, image_digest=_IMAGE_DIGEST,
        backends=lambda: (object(), object()), argv_for=lambda _: [], root=ROOT,
    )
    assert len(seen) == len(outcomes) == 12
    assert all(outcome.runner_note is None for outcome in outcomes)
    for outcome in outcomes:
        arm = outcome.scheduled.arm.split("__")[1]
        call = seen[outcome.scheduled.attempt_id]
        assert call["extra_home_files"] == treatments[arm].home_files
        assert call["receipt_context"] is treatments[arm].receipt_context
        assert call["verify_home_files"] == (checks if arm == profile_arm else {})
        assert call["preflight_tools"] == (tools if arm == profile_arm else ())
        assert call["gate_entrypoint"] == (gate if arm == profile_arm else None)


def test_red_an_unapproved_declaration_leaves_no_store(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    with pytest.raises(us.StudyRefused, match="not approved"):
        us.run_study(us.parse_declaration(_data(approved=False)), run_dir=run_dir, treatments={},
                     image_digest=_IMAGE_DIGEST, backends=lambda: (None, None), argv_for=lambda s: [], root=ROOT)
    assert list(run_dir.iterdir()) == []


def test_the_committed_declaration_is_authorized() -> None:
    """evals/uptake-study/run-manifest.json: flow-check, n=20/10, approved by
    the owner 2026-10-04."""
    declaration = us.load_declaration(ROOT / "evals" / "uptake-study" / "run-manifest.json")
    assert declaration.target_skill == "flow-check"
    assert [(c.id, c.attempts_per_arm, c.primary) for c in declaration.cases] == [
        ("intended-use", 20, True), ("near-miss", 10, False)]
    us.require_approved(declaration, ROOT)


def test_red_the_committed_declaration_without_its_approval_is_refused() -> None:
    data = json.loads((ROOT / "evals" / "uptake-study" / "run-manifest.json").read_text(encoding="utf-8"))
    data["shared"]["total_seconds"] += 16 * len(data["arm_order"]["sequence"])
    data["approval"] = None
    with pytest.raises(us.StudyRefused, match="not approved"):
        us.require_approved(us.parse_declaration(data), ROOT)


def test_the_committed_rewritten_skill_md_is_the_declared_description() -> None:
    """The override file carries the declared description verbatim."""
    declaration = us.load_declaration(ROOT / "evals" / "uptake-study" / "run-manifest.json")
    lines, at = us._description_of((ROOT / "evals" / "uptake-study" / "flow-check-SKILL.md").read_bytes())
    assert us._unquote(lines[at].split(":", 1)[1]) == declaration.rewritten_description


def test_red_a_nested_neighbour_cannot_impersonate_the_target() -> None:
    published = {**_PUBLISHED, ".codex/skills/qa-test/references/flow-check/SKILL.md": _skill("old")}
    rewritten = {**published, ".codex/skills/qa-test/references/flow-check/SKILL.md": _skill(NEW)}
    with pytest.raises(us.StudyRefused, match="entry point"):
        us.check_rewritten_files(published, rewritten, "flow-check", NEW)


@pytest.mark.parametrize("line", [
    'description: "Run quality checks"  ',  # whitespace only
    "description: \"Run quality checks\"".replace("\\", ""),  # identical after decoding
])
def test_red_a_rewrite_that_changes_nothing_meaningful_is_refused(line: str) -> None:
    rewritten = {**_PUBLISHED, ".codex/skills/flow-check/SKILL.md":
                 f'---\nname: "flow-check"\n{line}\n---\nBody.\n'.encode()}
    with pytest.raises(us.StudyRefused, match="unchanged in meaning|0 file"):
        us.check_rewritten_files(_PUBLISHED, rewritten, "flow-check", "Run quality checks")


def test_red_an_unquoted_description_with_a_comment_is_refused() -> None:
    rewritten = {**_PUBLISHED, ".codex/skills/flow-check/SKILL.md":
                 b'---\nname: "flow-check"\ndescription: Use checks # extra\n---\nBody.\n'}
    with pytest.raises(us.StudyRefused, match="double-quoted"):
        us.check_rewritten_files(_PUBLISHED, rewritten, "flow-check", "Use checks # extra")


def test_red_a_carriage_return_in_the_file_is_refused() -> None:
    rewritten = {**_PUBLISHED, ".codex/skills/flow-check/SKILL.md":
                 _skill(NEW).replace(b"---\nBody", b"---\r\nBody")}
    with pytest.raises(us.StudyRefused, match="carriage return"):
        us.check_rewritten_files(_PUBLISHED, rewritten, "flow-check", NEW)


def _fake_outcome(case: str, arm: str, *, selected: bool, model: str, prompt_ok: bool = True) -> mp.AttemptOutcome:
    record: dict[str, object] = {"disposition": "captured", "graded": {"status": "PASS"}, "observation": {
        "transcript_files_found": 1, "prompt_delivered": prompt_ok,
        "skill_invocations": ["flow-check"] if selected else [], "run_metadata": {"model": model}}}
    return mp.AttemptOutcome(mp.ScheduledAttempt(f"a-{case}-{arm}-{selected}-{model}", "t", f"{case}__{arm}", 1),
                             record, None)


class _Experiment:
    id = "exp-test"


def test_red_wrong_model_attempts_are_not_margins_of_the_test() -> None:
    """Counter-model review: 3 wrong-model rewritten selections against 3
    declared-model published non-selections must not produce significance."""
    declaration = us.parse_declaration(_data())
    outcomes = ([_fake_outcome("intended-use", "rewritten", selected=True, model="other-model")] * 3
                + [_fake_outcome("intended-use", "published", selected=False, model="gpt-6-astra")] * 3)
    report = us.build_report(_Experiment(), outcomes, declaration)  # type: ignore[arg-type]
    test = report["primary_test"]
    assert test["available"] is False and test["significant"] is None  # type: ignore[index]
    assert report["cells"]["intended-use"]["rewritten"] == {"scheduled": 3, "observed": 0, "selected": 0}  # type: ignore[index]


def test_red_no_confirmed_observations_is_no_result_not_a_negative_one() -> None:
    declaration = us.parse_declaration(_data())
    outcomes = [_fake_outcome("intended-use", arm, selected=False, model="gpt-6-astra", prompt_ok=False)
                for arm in ("rewritten", "published")]
    report = us.build_report(_Experiment(), outcomes, declaration)  # type: ignore[arg-type]
    test = report["primary_test"]
    assert test["available"] is False and test["p_value"] is None  # type: ignore[index]
    assert "NO RESULT" in us.paste_back(report)


def test_the_committed_selective_declaration_is_authorized_and_its_file_matches() -> None:
    """#237 follow-up: the selective rewrite, approved 2026-10-05."""
    root = ROOT / "evals" / "uptake-study" / "selective"
    declaration = us.load_declaration(root / "run-manifest.json")
    us.require_approved(declaration, ROOT)
    lines, at = us._description_of((root / "flow-check-SKILL.md").read_bytes())
    assert us._unquote(lines[at].split(":", 1)[1]) == declaration.rewritten_description
    data = json.loads((root / "run-manifest.json").read_text(encoding="utf-8"))
    data["shared"]["total_seconds"] += 16 * len(data["arm_order"]["sequence"])
    data["approval"] = None
    with pytest.raises(us.StudyRefused, match="not approved"):
        us.require_approved(us.parse_declaration(data), ROOT)


# ------------------------------------------------- screening probe (#238)


def _probe_data(cutoff: object = 45, per_attempt: object = 45) -> dict[str, object]:
    data = _data()
    data["probe"] = {"cutoff_seconds": cutoff}
    data["shared"]["per_attempt_seconds"] = per_attempt  # type: ignore[index]
    return data


def test_a_probe_declaration_parses_with_its_cutoff() -> None:
    assert us.parse_declaration(_probe_data()).probe_seconds == 45.0
    assert us.parse_declaration(_data()).probe_seconds is None


@pytest.mark.parametrize(("cutoff", "per_attempt", "match"), [
    (45, 600, "must equal probe.cutoff_seconds"),
    (10, 10, "20-300"),
    (400, 400, "20-300"),
    (True, 45, "20-300"),
])
def test_a_malformed_probe_is_refused(cutoff: object, per_attempt: object, match: str) -> None:
    with pytest.raises(us.StudyRefused, match=match):
        us.parse_declaration(_probe_data(cutoff, per_attempt))


def _probe_outcome(arm: str, *, selected: bool, calls: int | None) -> mp.AttemptOutcome:
    obs: dict[str, object] = {"transcript_files_found": 1, "prompt_delivered": True,
                              "skill_invocations": ["flow-check"] if selected else [],
                              "run_metadata": {"model": "gpt-6-astra"}}
    if calls is not None:
        obs["transcript_line_types"] = {"response_item/custom_tool_call": calls,
                                        "response_item/custom_tool_call_output": calls, "response_item/message": 2}
    record: dict[str, object] = {"disposition": "captured", "graded": {"status": "FAIL"}, "observation": obs}
    return mp.AttemptOutcome(mp.ScheduledAttempt(f"a-{arm}-{selected}-{calls}", "t", f"intended-use__{arm}", 1),
                             record, None)


def test_a_probe_attempt_that_never_acted_is_undecided_not_unselected() -> None:
    """#238: a cut-off before the first tool call decides nothing. Red case:
    counted as 'not selected', it would make a probe read zero uptake."""
    declaration = us.parse_declaration(_probe_data())
    outcomes = [_probe_outcome("rewritten", selected=False, calls=0),
                _probe_outcome("rewritten", selected=False, calls=None),
                _probe_outcome("rewritten", selected=True, calls=2),
                _probe_outcome("published", selected=False, calls=3)]
    report = us.build_report(_Experiment(), outcomes, declaration)  # type: ignore[arg-type]
    assert report["undecided"] == 2
    assert report["cells"]["intended-use"]["rewritten"] == {"scheduled": 3, "observed": 1, "selected": 1}  # type: ignore[index]
    assert report["cells"]["intended-use"]["published"] == {"scheduled": 1, "observed": 1, "selected": 0}  # type: ignore[index]
    assert all(e["task_status"] == "NOT_MEASURED (probe)" for e in report["attempts"])  # type: ignore[union-attr,attr-defined]
    assert "PROBE cut-off 45s, undecided=2" in us.paste_back(report)


def test_a_full_attempt_with_no_tool_call_is_still_decided() -> None:
    """Outside probe mode an attempt is decided by finishing: no change."""
    declaration = us.parse_declaration(_data())
    report = us.build_report(_Experiment(), [_probe_outcome("rewritten", selected=False, calls=0)], declaration)  # type: ignore[arg-type]
    assert report["cells"]["intended-use"]["rewritten"]["observed"] == 1  # type: ignore[index]


def test_tool_calls_counts_calls_not_outputs() -> None:
    assert us.tool_calls({"transcript_line_types": {"response_item/custom_tool_call": 2,
                                                    "response_item/custom_tool_call_output": 2,
                                                    "response_item/function_call": 1}}) == 3
    assert us.tool_calls({}) is None


@pytest.mark.parametrize("name", ["agreement-broad", "agreement-selective"])
def test_the_committed_probe_declarations_are_authorized(name: str) -> None:
    declaration = us.load_declaration(ROOT / "evals" / "description-probe" / name / "run-manifest.json")
    assert declaration.probe_seconds == 45.0
    assert [(c.id, c.attempts_per_arm) for c in declaration.cases] == [("intended-use", 5), ("near-miss", 5)]
    us.require_approved(declaration, ROOT)


def test_red_a_call_still_pending_at_the_cutoff_is_undecided() -> None:
    """Counter-model review: cut off after requesting SKILL.md but before its
    output arrives, the parser has not yet emitted the invocation - a decided
    'not selected' would undercount near the cut-off."""
    declaration = us.parse_declaration(_probe_data())
    outcome = _probe_outcome("rewritten", selected=False, calls=2)
    obs = outcome.record["observation"]
    assert isinstance(obs, dict)
    obs["transcript_line_types"] = {"response_item/custom_tool_call": 2, "response_item/custom_tool_call_output": 1}
    report = us.build_report(_Experiment(), [outcome], declaration)  # type: ignore[arg-type]
    assert report["undecided"] == 1
    assert report["cells"]["intended-use"]["rewritten"]["observed"] == 0  # type: ignore[index]


@pytest.mark.parametrize("probe", [True, False])
def test_red_an_unrecognized_call_type_makes_a_negative_undecided(probe: bool) -> None:
    """Counter-model review: a skill read in a call format the parser ignores
    is invisible - an empty invocation list is then not a negative, in a
    probe or a full run. A positive selection stays decided."""
    declaration = us.parse_declaration(_probe_data() if probe else _data())
    negative = _probe_outcome("rewritten", selected=False, calls=2)
    positive = _probe_outcome("published", selected=True, calls=2)
    for outcome in (negative, positive):
        obs = outcome.record["observation"]
        assert isinstance(obs, dict)
        obs["transcript_unrecognized_types"] = ["function_call"]
    report = us.build_report(_Experiment(), [negative, positive], declaration)  # type: ignore[arg-type]
    cells = report["cells"]["intended-use"]  # type: ignore[index]
    assert cells["rewritten"]["observed"] == 0
    assert cells["published"] == {"scheduled": 1, "observed": 1, "selected": 1}


# --------------------------------------------- multi-variant screen (#238)


def _screen_data(variants: Sequence[str] = ("variant-a", "variant-b"), **case_extra: object) -> dict[str, object]:
    grader = verify.GraderDef.load(TASK)
    cases = [
        {"id": "asked", "prompt_addendum": "Before finishing, run this project's quality checks.",
         "attempts_per_arm": 3, "primary": False, "expect": "select"},
        {"id": "not-asked", "prompt_addendum": "", "attempts_per_arm": 3, "primary": False, "expect": "abstain"},
    ]
    for c in cases:
        c.update(case_extra)
    arms = [{"name": "published", "subject": dict(SUBJECT)}] + [
        {"name": v, "subject": dict(SUBJECT), "target_skill": "flow-check", "description": f"{NEW} ({v})"}
        for v in variants]
    parsed = [us.Case(c["id"], c["prompt_addendum"], c["attempts_per_arm"], c["primary"], c.get("expect"))  # type: ignore[arg-type]
              for c in cases]
    names = ["published", *variants]
    return {
        "kind": "uptake-study", "issue": 238, "approval": {"by": "owner", "at": "2026-10-06"},
        "task": {"path": "evals/level1/slug-small-fix", "grader_id": grader.id, "grader_revision": grader.revision},
        "arms": arms, "cases": cases, "probe": {"cutoff_seconds": 45},
        "shared": {**_data()["shared"], "per_attempt_seconds": 45,  # type: ignore[dict-item]
                   "total_seconds": (45 + 16) * len(names) * 6},
        "arm_order": {"seed": 3, "sequence": [list(x) for x in us.derive_order(3, parsed, names)]},
    }


def test_a_screen_declaration_parses() -> None:
    declaration = us.parse_declaration(_screen_data(("variant-a", "variant-b", "variant-c")))
    assert declaration.arms == ("published", "variant-a", "variant-b", "variant-c")
    assert not declaration.tested
    assert set(declaration.variants or {}) == {"variant-a", "variant-b", "variant-c"}
    us.require_approved(declaration, ROOT)


@pytest.mark.parametrize(("mutate", "match"), [
    (lambda d: d["arms"][2].update(description=d["arms"][1]["description"]), "same description"),
    (lambda d: d["arms"][2].update(name="rewritten"), "arms must be exactly"),
    (lambda d: d["arms"][2].update(target_skill="qa-test"), "same, non-empty target_skill"),
    (lambda d: d["cases"][0].pop("expect"), "must declare expect"),
    (lambda d: d["cases"][0].update(expect="maybe"), "expect must be one of"),
    (lambda d: d["cases"][0].update(primary=True), "declares no primary"),
    (lambda d: d["cases"][1].update(expect="select"), "one 'abstain' case"),
    (lambda d: d.update(test={"kind": "fisher-exact-one-sided"}), "carries no test"),
])
def test_a_malformed_screen_is_refused(mutate: object, match: str) -> None:
    data = copy.deepcopy(_screen_data())
    mutate(data)  # type: ignore[operator]
    with pytest.raises(us.StudyRefused, match=match):
        us.parse_declaration(data)


def test_a_screen_scores_selectivity_not_just_recall(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """variant-a selects only when asked (+1.00); variant-b selects everywhere
    (0.00, no better than published's 0.00). Red case: a recall-only score
    would rank variant-b level with variant-a.

    Two attempts per cell, not the production floor of three (#410): every
    attempt runs the real install and grading path through the fake docker
    CLI, about 2 s each, so 18 attempts measured 37 s quiet and passed the
    120 s pytest-timeout under host load. Twelve keep every arm and case, and
    2/2 still distinguishes a per-attempt count from "any attempt selected".
    The floor itself stays pinned by the 3-30 refusal case above."""
    monkeypatch.setattr(us, "MIN_ATTEMPTS", 2)
    declaration = us.parse_declaration(_screen_data(attempts_per_arm=2))
    assert all(c.attempts_per_arm == 2 for c in declaration.cases)
    treatments = {"published": _treatment(tmp_path, monkeypatch, "published", "Run quality checks"),
                  "variant-a": _treatment(tmp_path, monkeypatch, "variant-a", f"{NEW} (variant-a)"),
                  "variant-b": _treatment(tmp_path, monkeypatch, "variant-b", f"{NEW} (variant-b)")}
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    state = tmp_path / "docker-state"

    def backends() -> tuple[object, object]:
        make = lambda: d.DockerBackend(image=_IMAGE, base_dir=run_dir, docker_bin=_docker_bin(state),
                                       daemon_timeout=_FAKE_DAEMON_TIMEOUT)
        return make(), make()

    def argv_for(scheduled: mp.ScheduledAttempt) -> list[str]:
        home = state / f"{d._container_name(scheduled.attempt_id)}.fsroot" / "home" / "candidate"
        argv = [sys.executable, str(FAKE_CLIENT), "--format", "codex-fake", "--home", str(home),
                "--transcript-relpath", f".codex/sessions/2026/01/01/rollout-{scheduled.attempt_id}.jsonl"]
        if scheduled.arm in ("asked__variant-a", "asked__variant-b", "not-asked__variant-b"):
            argv += ["--plant-skill", "flow-check"]
        return argv

    experiment, outcomes = us.run_study(
        declaration, run_dir=run_dir, treatments=treatments, image_digest=_IMAGE_DIGEST, backends=backends,
        argv_for=argv_for, root=ROOT, credential_explicit_path=_fresh_codex_credential(tmp_path),
    )
    report = us.build_report(experiment, us.reconcile(experiment, outcomes), declaration)
    scores = report["scores"]
    assert report["primary_test"] is None and report["screen"] is True
    assert scores["variant-a"] == {"select": "2/2", "abstain": "0/2", "score": 1.0}  # type: ignore[index]
    assert scores["variant-b"] == {"select": "2/2", "abstain": "2/2", "score": 0.0}  # type: ignore[index]
    assert scores["published"] == {"select": "0/2", "abstain": "0/2", "score": 0.0}  # type: ignore[index]
    assert "score [variant-a] select=2/2 abstain=0/2 score=+1.00" in us.paste_back(report)


@pytest.mark.parametrize("value", [[], {}, None])
def test_red_a_non_string_target_is_refused_not_crashed(value: object) -> None:
    """Counter-model review: a list or dict target raised TypeError."""
    with pytest.raises(us.StudyRefused, match="same, non-empty target_skill"):
        us.parse_declaration(_mutate(("arms", 1, "target_skill"), value))



# ---------------------------------------------- #424: each arm pins its own skill

def test_each_arm_is_planned_with_its_own_installed_skill_digests(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """#424 RED on main: the uptake planner created every trial unpinned. Each
    arm now pins the description IT installs - published and rewritten differ
    there and nowhere else - so evidence crediting the other arm's bytes is stale."""
    declaration = us.parse_declaration(_data())
    treatments = {"published": _treatment(tmp_path, monkeypatch, "published", "Run quality checks"),
                  "rewritten": _treatment(tmp_path, monkeypatch, "rewritten", NEW)}
    store = trial.open_store(tmp_path / "store", forbidden=[])
    experiment, schedule = us.plan_study(
        declaration, store, root=ROOT, image_digest=_IMAGE_DIGEST,
        digests={arm: t.digest for arm, t in treatments.items()},
        skill_digests={arm: t.skill_digests for arm, t in treatments.items()},
    )
    pub, rew = treatments["published"].skill_digests, treatments["rewritten"].skill_digests
    assert [p["path"] for p in pub] == [p["path"] for p in rew] == [".codex/skills/flow-check/SKILL.md"]
    assert pub[0]["description_digest"] != rew[0]["description_digest"]
    assert pub[0]["body_digest"] == rew[0]["body_digest"]
    trials = experiment.ledger["trials"]
    assert isinstance(trials, list) and len(trials) == len(schedule)
    for planned, scheduled in zip(trials, schedule, strict=True):
        arm = scheduled.arm.split("__")[-1]
        assert planned.get("skill_digests") == [dict(p) for p in treatments[arm].skill_digests], scheduled.arm


def test_red_an_arm_with_no_skill_digests_is_refused_not_planned_unpinned(tmp_path: Path) -> None:
    declaration = us.parse_declaration(_data())
    store = trial.open_store(tmp_path / "store", forbidden=[])
    with pytest.raises(us.StudyRefused, match="no skill_digests to pin"):
        us.plan_study(declaration, store, root=ROOT, image_digest=_IMAGE_DIGEST,
                      digests={"published": "sha256:" + "a" * 64, "rewritten": "sha256:" + "b" * 64})


def test_every_uptake_attempt_receives_its_arm_s_source_modes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#505 (counter-model review): the study builds its treatments with
    `home_modes`, and every attempt is delivered with them, so an installed
    helper keeps its source executable bit."""
    _experiment, _outcomes, seen = _run(tmp_path, monkeypatch, select_in=())
    assert seen
    for call in seen:
        modes = call.get("extra_home_modes")
        assert isinstance(modes, dict) and modes, call["attempt_id"]
        delivered = call["extra_home_files"]
        assert isinstance(delivered, dict) and set(modes) <= set(delivered)
        assert {str(v) for v in modes.values()} <= {"100644", "100755"}


def test_uptake_refuses_any_reused_protocol_arm_before_approval_or_store(tmp_path: Path) -> None:
    from test_gate_state import PROTOCOL

    from skillc import calibration_run as cr
    t = cr.Treatment({}, "digest", None, gate_state_protocol=PROTOCOL)
    with pytest.raises(us.StudyRefused, match="fixture-only"):
        us.run_study(None, run_dir=tmp_path / "run", treatments={"second-arm": t},  # type: ignore[arg-type]
                     image_digest=None, backends=lambda: pytest.fail("backend"), argv_for=lambda _: [], root=tmp_path)
    assert not (tmp_path / "run").exists()


# #546: public report/text accounting, including slots that never started.
def _accounting_twin() -> list[mp.AttemptOutcome]:
    return [_probe_outcome("rewritten", selected=False, calls=0),
            _probe_outcome("published", selected=True, calls=2)]


def test_not_run_is_excluded_from_public_probe_undecided() -> None:
    outcomes = _accounting_twin()
    outcomes.append(mp.AttemptOutcome(mp.ScheduledAttempt("a-not-run", "t", "intended-use__rewritten", 2),
                                      {"disposition": "not-run"}, None))
    report = us.build_report(_Experiment(), outcomes, us.parse_declaration(_probe_data()))  # type: ignore[arg-type]
    assert report["undecided"] == 1
    assert "undecided=1" in us.paste_back(report)


def test_all_captured_public_probe_accounting_healthy_twin() -> None:
    report = us.build_report(_Experiment(), _accounting_twin(),  # type: ignore[arg-type]
                             us.parse_declaration(_probe_data()))
    assert report["undecided"] == 1
    assert "undecided=1" in us.paste_back(report)


@pytest.mark.parametrize("screen", [False, True])
@pytest.mark.parametrize("probe", [False, True])
def test_disposition_partition_preserves_report_consumers(screen: bool, probe: bool) -> None:
    data = _screen_data() if screen else _probe_data()
    if not probe:
        data.pop("probe")
    declaration = us.parse_declaration(data)
    captured = [dataclasses.replace(o, scheduled=dataclasses.replace(
        o.scheduled, arm=f"{declaration.cases[0].id}__{declaration.arms[i]}"))
        for i, o in enumerate(_accounting_twin())]
    baseline = us.build_report(_Experiment(), captured, declaration)  # type: ignore[arg-type]
    dispositions: list[object] = ["not-run", "unavailable", "inconclusive", None, "future", {}, []]
    extra = [mp.AttemptOutcome(mp.ScheduledAttempt(f"a-extra-{i}", "t", captured[0].scheduled.arm, i + 2),
                               {"disposition": value}, None) for i, value in enumerate(dispositions)]
    report = us.build_report(_Experiment(), captured + extra, declaration)  # type: ignore[arg-type]
    assert [report[k] for k in ("not_run", "unavailable", "unknown_disposition")] == [1, 1, 4]
    assert report["undecided"] == (2 if probe else 0)
    rows = report["attempts"]
    assert isinstance(rows, list) and rows
    assert [r["decision_applicable"] for r in rows] == [True, True, False, False, True, None, None, None, None]
    assert [r["disposition"] for r in rows[2:]] == dispositions
    assert all(isinstance(r["decided"], bool) for r in rows)
    assert [r["decided"] for r in rows[2:]] == [not probe] * len(extra)
    assert len(rows) == len(captured) + len(extra)
    expected_cells = copy.deepcopy(baseline["cells"])
    assert isinstance(expected_cells, dict) and expected_cells
    expected_cells[declaration.cases[0].id][declaration.arms[0]]["scheduled"] += len(extra)
    assert report["cells"] == expected_cells
    assert report["primary_test"] == baseline["primary_test"]
    assert report["scores"] == baseline["scores"]
    assert report["version"] == 1
    text = us.paste_back(report)
    for case, arms in expected_cells.items():
        for arm, cell in arms.items():
            assert f"[{case} / {arm}] selected={cell['selected']}/{cell['observed']} (scheduled {cell['scheduled']})" in text
    assert "not_run=1, unavailable=1, unknown_disposition=4" in text
    assert ("PROBE cut-off" in text) is probe
    assert ("undecided=2" in text) is probe


@pytest.mark.parametrize("failure", ["wrong-model", "unconfirmed"])
def test_accounting_does_not_expand_model_or_confirmation_eligibility(failure: str) -> None:
    outcome = _probe_outcome("published", selected=True, calls=2)
    obs = outcome.record["observation"]
    assert isinstance(obs, dict) and obs
    if failure == "wrong-model":
        obs["run_metadata"] = {"model": "another-model"}
    else:
        obs["transcript_files_found"] = 0
    report = us.build_report(_Experiment(), [outcome], us.parse_declaration(_probe_data()))  # type: ignore[arg-type]
    cells, rows = report["cells"], report["attempts"]
    assert isinstance(cells, dict) and isinstance(rows, list) and rows
    assert cells["intended-use"]["published"] == {"scheduled": 1, "observed": 0, "selected": 0}
    assert rows[0]["decision_applicable"] is True


@pytest.mark.parametrize("value", [None, "future", {}, [], ["captured"], 1, False])
def test_unknown_or_missing_raw_disposition_is_not_guessed(value: object) -> None:
    record = {} if value is None else {"disposition": value}
    outcome = mp.AttemptOutcome(mp.ScheduledAttempt("a-unknown", "t", "intended-use__rewritten", 1), record, None)
    report = us.build_report(_Experiment(), [outcome], us.parse_declaration(_probe_data()))  # type: ignore[arg-type]
    assert report["unknown_disposition"] == 1 and report["undecided"] == 0
    rows = report["attempts"]
    assert isinstance(rows, list) and len(rows) == 1
    row = rows[0]
    assert row["disposition"] == value and row["decision_applicable"] is None
    assert row["decided"] is False
    assert record == ({} if value is None else {"disposition": value})


def test_text_preserves_legacy_json_without_inventing_zero_counters() -> None:
    report = us.build_report(_Experiment(), _accounting_twin(),  # type: ignore[arg-type]
                             us.parse_declaration(_probe_data()))
    for key in ("not_run", "unavailable", "unknown_disposition"):
        report.pop(key)
    text = us.paste_back(report)
    assert "PROBE cut-off 45s, undecided=1" in text
    assert "not_run=" not in text and "unavailable=" not in text and "unknown_disposition=" not in text


@pytest.mark.parametrize("bad", [{"not_run": 0}, {"not_run": 0, "unavailable": 0},
    {"not_run": -1, "unavailable": 0, "unknown_disposition": 0},
    {"not_run": False, "unavailable": 0, "unknown_disposition": 0},
    {"not_run": 0, "unavailable": None, "unknown_disposition": 0},
    {"not_run": 0, "unavailable": 0, "unknown_disposition": "0"},
    {"not_run": [], "unavailable": 0, "unknown_disposition": 0}])
def test_partial_or_malformed_text_counters_refuse(bad: dict[str, object]) -> None:
    with pytest.raises(us.StudyRefused, match="incomplete or malformed"):
        us.paste_back({"experiment_id": "controlled", **bad})


def test_not_run_partition_reaches_public_text_consumer() -> None:
    outcomes = _accounting_twin() + [mp.AttemptOutcome(
        mp.ScheduledAttempt("a-text-not-run", "t", "intended-use__rewritten", 2), {"disposition": "not-run"}, None)]
    report = us.build_report(_Experiment(), outcomes, us.parse_declaration(_probe_data()))  # type: ignore[arg-type]
    assert "undecided=1" in us.paste_back(report)
    assert "not_run=1" in us.paste_back(report)
