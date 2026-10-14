"""The #375 production-path campaign harness (`skillc/level3_campaign.py`).

The real-Docker run is the integration proof and happens on #315's runner.
These tests hold what can be held without Docker:

- the committed manifest is exactly the freeze script's derivation, and it
  differs from qualification's per-candidate contract only where a
  production delta is declared;
- every frozen identity is checked, and each one can report a move;
- the per-row comparison names every difference, including "not graded";
- delivery keeps answer keys out and file modes in;
- the real actor, run as a process, sequences edit and gate calls per mode;
- the safety rails: the actor is not a real agent, the credential is a
  dummy, the command has no credential option, the agent runs on `none`;
- `run_rows` hands the production treatment through unchanged.
"""

from __future__ import annotations

import copy
import importlib.util
import io
import json
import subprocess
import sys
import tarfile
import types
from pathlib import Path
from typing import Any

import pytest

from skillc import calibration_run as cr
from skillc import cli, credential, lifecycle, trial_bootstrap
from skillc import collection_conformance as cc
from skillc import level3_campaign as lc

ROOT = Path(__file__).resolve().parent.parent
CAMPAIGN = ROOT / "evals" / "level3" / "campaign-375"
MANIFEST = CAMPAIGN / "manifest.json"


def _module(path: Path, name: str) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


FREEZE = _module(CAMPAIGN / "freeze.py", "campaign_375_freeze")


def _committed() -> dict[str, Any]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


# --------------------------------------------------------------- the freeze


def test_the_committed_manifest_is_the_freeze_scripts_output() -> None:
    derived = FREEZE.manifest()
    assert _committed() == derived
    # Red case: one flipped expectation is no longer the derivation.
    tampered = copy.deepcopy(derived)
    tampered["rows"][0]["expected"]["criteria"]["gate-green"] = "VIOLATED"
    assert tampered != derived


def test_the_population_is_both_tasks_times_every_declared_candidate() -> None:
    manifest = lc.load_manifest(MANIFEST)
    assert len(manifest.rows) == 2 * len(FREEZE.POPULATION) == 42
    for task in FREEZE.TASKS:
        assert [(r.candidate, r.actor) for r in manifest.rows if r.task == task] == FREEZE.POPULATION


def test_expectations_differ_from_qualification_only_where_a_delta_is_declared() -> None:
    for row in _committed()["rows"]:
        task_root = ROOT / "evals" / "level3" / row["task"]
        committed = json.loads((task_root / row["candidate"] / "expected.json").read_text(encoding="utf-8"))
        unknown = FREEZE._qualify(row["task"])._EXPECTED_UNKNOWN.get(row["candidate"], frozenset())
        contract = {c: "VIOLATED" if c in committed["violated"] else "UNKNOWN" if c in unknown else "SATISFIED"
                    for c in row["expected"]["criteria"]}
        changed = {c for c, v in row["expected"]["criteria"].items() if contract[c] != v}
        delta = FREEZE.PRODUCTION_DELTAS.get(row["candidate"], ({}, None))[0]
        assert changed == set(delta), row["id"]
        assert ("production_delta" in row) == bool(delta), row["id"]


def test_frozen_identities_hold_on_this_tree() -> None:
    assert lc.check_frozen(lc.load_manifest(MANIFEST), ROOT) == []


@pytest.mark.parametrize("mutate, named", [
    (lambda m: m["frozen"]["tasks"]["gate-stops-early"].update(grader_digest="sha256:00"), "task gate-stops-early"),
    (lambda m: m["frozen"]["subject"].update(inventory_digest="sha256:00"), "inventory digest moved"),
    (lambda m: m["frozen"]["subject"].update(revision="0" * 40), "revision"),
    (lambda m: m["frozen"]["runtime"].update(runtime_id="cpp-codex-flow-check-ea6dbfa"), "runtime policy runtime_id"),
    (lambda m: m["frozen"].update(harness_digest="sha256:00"), "scripted actor"),
    (lambda m: m["rows"][0].update(candidate="alternatives/does-not-exist"), "does not exist"),
    (lambda m: m["rows"][0].update(candidate_digest="sha256:00"), "bytes or modes moved"),
    (lambda m: m["frozen"]["caps"].update(gate_seconds=1), "cap gate_seconds"),
    (lambda m: m["frozen"]["caps"].update(per_attempt_seconds=60), "cap per_attempt_seconds"),
    (lambda m: m["frozen"]["caps"].update(agent_network="bridge"), "cap agent_network"),
    (lambda m: m["frozen"]["caps"]["container"].update(memory="2g"), "cap container"),
])
def test_red_case_each_frozen_identity_can_report_a_move(tmp_path: Path, mutate: Any, named: str) -> None:
    data = _committed()
    mutate(data)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    problems = lc.check_frozen(lc.load_manifest(path), ROOT)
    assert any(named in p for p in problems), problems


@pytest.mark.parametrize("mutate", [
    lambda m: m["rows"].append(dict(m["rows"][0])),
    lambda m: m["rows"][0].update(actor="improvise"),
    lambda m: m["rows"][0].update(actor="noop"),
    lambda m: m["rows"][8].update(actor="fresh"),
    lambda m: m.update(rows=[]),
    lambda m: m["rows"][0].update(task="gate-ran-nothing"),
    lambda m: m["rows"][0]["expected"]["criteria"].update({"gate-green": "PROBABLY"}),
    lambda m: m.update(kind="calibration-declaration"),
    lambda m: m["rows"][0].update(candidate_digest=None),
    lambda m: m["rows"][8].update(candidate_digest="sha256:00"),
])
def test_malformed_manifests_are_refused(tmp_path: Path, mutate: Any) -> None:
    data = _committed()
    mutate(data)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(lc.CampaignRefused):
        lc.load_manifest(path)


# --------------------------------------------------------------- comparison


def _row(**expected: str) -> lc.Row:
    criteria = {"functional-windows-fix": "SATISFIED", "regression-fails-on-original": "SATISFIED",
                "gate-green": "SATISFIED", "flow-check-honest": "SATISFIED", **expected}
    return lc.Row("gse.reference", "gate-stops-early", "reference", "fresh", "sha256:00", "PASS", criteria)


def _graded(status: str = "PASS", **outcomes: str) -> dict[str, Any]:
    criteria = {"functional-windows-fix": "SATISFIED", "regression-fails-on-original": "SATISFIED",
                "gate-green": "SATISFIED", "flow-check-honest": "SATISFIED", **outcomes}
    return {"status": status, "criteria": [{"id": k, "outcome": v} for k, v in criteria.items()]}


def test_compare_matches_only_an_identical_outcome() -> None:
    assert lc.compare(_row(), _graded()) == []
    assert lc.compare(_row(), _graded("FAIL", **{"gate-green": "VIOLATED"})) == [
        "status 'FAIL' != expected 'PASS'", "gate-green: 'VIOLATED' != expected 'SATISFIED'"]
    missing = _graded()
    missing["criteria"] = missing["criteria"][:-1]
    assert lc.compare(_row(), missing) == ["flow-check-honest: None != expected 'SATISFIED'"]
    extra = _graded()
    extra["criteria"].append({"id": "installation-ready", "outcome": "UNKNOWN"})
    assert lc.compare(_row(), extra) == ["installation-ready: 'UNKNOWN' != expected None"]
    assert lc.compare(_row(), None) == ["the attempt was not graded"]


# --------------------------------------------------------------- delivery


def test_candidate_delivery_excludes_answer_keys_and_keeps_modes() -> None:
    manifest = lc.load_manifest(MANIFEST)
    row = next(r for r in manifest.rows if r.id == "gse.wrong.unconditional-green")
    task_root = ROOT / "evals" / "level3" / row.task
    files = lc.row_home_files(row, task_root)
    assert set(files) == {f"{lc.HOME_DIR}/actor.py", f"{lc.HOME_DIR}/fake_agent_client.py",
                          f"{lc.HOME_DIR}/candidate.tar"}
    with tarfile.open(fileobj=io.BytesIO(files[f"{lc.HOME_DIR}/candidate.tar"])) as archive:
        members = {m.name: m for m in archive.getmembers()}
    surface = cc.task_surface(task_root / row.candidate)
    assert set(members) == {path for path, _, _ in surface}
    assert not any(Path(name).name == "expected.json" for name in members)
    for path, _, executable in surface:
        assert members[path].mode == (0o755 if executable else 0o644), path
    assert any(executable for _, _, executable in surface), "the population must exercise a mode"


def test_a_mode_change_alone_moves_the_surface_digest() -> None:
    files = [("ci/check.py", b"print(1)\n", True), ("Makefile", b"check:\n", False)]
    flipped = [("ci/check.py", b"print(1)\n", False), ("Makefile", b"check:\n", False)]
    assert lc.surface_digest(files) != lc.surface_digest(flipped)
    assert lc.surface_digest(files) == lc.surface_digest(list(reversed(files)))


def test_delivery_refuses_a_candidate_that_differs_from_its_frozen_digest() -> None:
    manifest = lc.load_manifest(MANIFEST)
    row = next(r for r in manifest.rows if r.id == "gse.reference")
    task_root = ROOT / "evals" / "level3" / row.task
    assert f"{lc.HOME_DIR}/candidate.tar" in lc.row_home_files(row, task_root)
    moved = lc.Row(row.id, row.task, row.candidate, row.actor, "sha256:00", row.expected_status, row.expected_criteria)
    with pytest.raises(lc.CampaignRefused, match="frozen surface digest"):
        lc.row_home_files(moved, task_root)


def test_a_noop_row_delivers_no_candidate() -> None:
    manifest = lc.load_manifest(MANIFEST)
    row = next(r for r in manifest.rows if r.actor == "noop")
    assert f"{lc.HOME_DIR}/candidate.tar" not in lc.row_home_files(row, ROOT / "evals" / "level3" / row.task)


# --------------------------------------------------------------- the actor


_GATE = """#!/bin/sh
if [ -f placed.txt ]; then state=placed; else state=unplaced; fi
echo "$* $state" >> "$HOME/gate.log"
"""


@pytest.mark.parametrize("mode, calls, placed", [
    ("fresh", ["--plan check --evidence flow-check placed", "--check-summary placed"], True),
    ("stale", ["--plan check --evidence flow-check unplaced", "--check-summary unplaced"], True),
    ("plan-only", ["--plan check --evidence flow-check placed"], True),
    ("noop", [], False),
])
def test_the_actor_sequences_edits_and_gate_calls(tmp_path: Path, mode: str, calls: list[str], placed: bool) -> None:
    home, work = tmp_path / "home", tmp_path / "work"
    (home / lc.HOME_DIR).mkdir(parents=True)
    work.mkdir()
    (work / "fixture.txt").write_text("fixture\n")
    entry = ".claude/scripts/flow-finish-gate.sh"
    (home / entry).parent.mkdir(parents=True)
    (home / entry).write_text(_GATE)
    (home / entry).chmod(0o755)
    (home / lc.HOME_DIR / "actor.py").write_text(lc.ACTOR_SOURCE)
    (home / lc.HOME_DIR / "fake_agent_client.py").write_bytes(lc.FAKE_CLIENT.read_bytes())
    (home / lc.HOME_DIR / "candidate.tar").write_bytes(lc._tarball([("placed.txt", b"candidate\n", False)]))
    prompt = "Fix it.\n\n" + trial_bootstrap.compose_canary_instruction(None, "0123abcd")
    row = lc.Row("r", "gate-stops-early", "fixture" if mode == "noop" else "x", mode, None, "PASS", {"g": "SATISFIED"})
    argv = lc.actor_argv(row, entry, interpreter=sys.executable)
    argv[1] = str(home / lc.HOME_DIR / "actor.py")
    subprocess.run([*argv, prompt], cwd=work, env={"HOME": str(home), "PATH": "/usr/bin:/bin"}, check=True)

    log = (home / "gate.log").read_text().splitlines() if (home / "gate.log").exists() else []
    assert log == calls
    assert (work / "placed.txt").exists() is placed
    assert (work / "fixture.txt").read_text() == "fixture\n"
    assert (work / "agent-touched.txt").exists(), "the liveness marker is the no-op's only change"
    assert (home / lc.TRANSCRIPT_RELPATH).is_file()


# --------------------------------------------------------------- safety rails


def test_the_actor_is_not_a_real_agent_and_the_guard_is_live() -> None:
    row = lc.load_manifest(MANIFEST).rows[0]
    lifecycle._refuse_real_agent(lc.actor_argv(row, ".claude/scripts/flow-finish-gate.sh"))
    with pytest.raises(lifecycle.RealAgentBlocked):
        lifecycle._refuse_real_agent(["codex", "exec"])


def test_the_delivered_credential_is_a_dummy_that_meets_the_precondition(tmp_path: Path) -> None:
    path = lc.dummy_credential(tmp_path / "credential.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["skillc_campaign"] == "dummy"
    assert data["tokens"]["access_token"].endswith(".unsigned")
    assert set(data["tokens"]) == {"access_token"}, "no refresh token: it can authorise nothing"
    assert credential.check_remaining_life_or_refuse("codex", credential.read_fresh(path)) > 7 * 86400


def test_the_command_accepts_no_credential_and_refuses_moved_identities(tmp_path: Path, capsys: Any) -> None:
    parser = cli.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["level3-campaign", "--runtime-supply-receipt", "r.json", "--credential", "c.json"])
    data = _committed()
    data["frozen"]["harness_digest"] = "sha256:00"
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    code = cli.main(["level3-campaign", "--manifest", str(path), "--runtime-supply-receipt", "r.json"])
    assert code == 2
    assert "frozen identity moved" in capsys.readouterr().err


def test_the_campaign_backends_give_the_agent_no_network(tmp_path: Path) -> None:
    agent, grading = lc.campaign_backends(image="img", base=tmp_path, docker_bin=("docker",),
                                          daemon_timeout=30, runtime_supply=None)
    assert agent.network == "none" and grading.network == "none"
    assert cc.AGENT_NETWORK != "none", "the production default this deliberately overrides"
    body = Path(cli.__file__).read_text(encoding="utf-8").split("def cmd_level3_campaign", 1)[1].split("\ndef ", 1)[0]
    assert "lc.campaign_backends(" in body and "TrackingDockerBackend(" not in body


# --------------------------------------------------------------- wiring


def test_run_rows_hands_the_production_treatment_through(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = lc.load_manifest(MANIFEST)
    rows = [r for r in manifest.rows if r.id in ("gse.reference", "vse.wrong.unconditional-green")]
    treatment = cr.Treatment(home_files={"a": b"1"}, digest="sha256:tt", gate_entrypoint=".claude/scripts/gate",
                             receipt_context=None, verify_home_files={"a": "sha256:aa"},
                             preflight_tools=({"id": "tool-x"},))
    calls: list[dict[str, Any]] = []

    def fake_attempt(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        # Both attempts grade PASS: right for gse.reference, wrong for the
        # second row, whose frozen expectation is FAIL.
        return {"disposition": "captured", "graded": _graded()}

    monkeypatch.setattr(cc, "run_level1_agent_attempt", fake_attempt)
    made: list[str] = []

    def backends() -> tuple[Any, Any]:
        made.append("pair")
        return object(), object()

    report = lc.run_rows(manifest, root=ROOT, run_dir=tmp_path, treatment=treatment, backends=backends,  # type: ignore[arg-type]
                         image_digest="sha256:img", rows=rows)
    assert made == ["pair", "pair"], "a fresh backend pair per attempt"
    for call, row in zip(calls, rows, strict=True):
        assert call["verify_home_files"] == treatment.verify_home_files
        assert call["preflight_tools"] == treatment.preflight_tools
        assert call["gate_entrypoint"] == treatment.gate_entrypoint
        assert call["receipt_context"] is treatment.receipt_context
        assert call["extra_home_files"]["a"] == b"1"
        assert f"{lc.HOME_DIR}/actor.py" in call["extra_home_files"]
        assert call["base_argv"] == lc.actor_argv(row, treatment.gate_entrypoint)
        assert call["task_root"] == ROOT / "evals" / "level3" / row.task
        assert json.loads(Path(call["credential_explicit_path"]).read_text())["skillc_campaign"] == "dummy"
        assert call["client"] == "codex" and call["timeout"] == lc.PER_ATTEMPT_SECONDS
    assert [r["verdict"] for r in report["rows"]] == ["MATCH", "MISMATCH"]
    assert report["matched"] == 1 and report["population"] == 2


def test_run_rows_refuses_a_treatment_that_witnesses_nothing(tmp_path: Path) -> None:
    treatment = cr.Treatment(home_files={}, digest="sha256:tt", gate_entrypoint=None, receipt_context=None)
    with pytest.raises(lc.CampaignRefused, match="gate_entrypoint"):
        lc.run_rows(lc.load_manifest(MANIFEST), root=ROOT, run_dir=tmp_path, treatment=treatment,
                    backends=lambda: (object(), object()), image_digest="sha256:img")  # type: ignore[arg-type,return-value]
