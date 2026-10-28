"""Committed input controls for the attempt-local v1 admission boundary."""
from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from skillc import gate_state as gs
from skillc import stage_capture
from skillc.backend import ExecuteResult

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "sha256:" + "a" * 64
CONFIG: dict[str, Any] = {"version": 1, "family": "cpp-run-state", "plan": "check",
          "operations": {"flow-check-plan": "runner", "flow-check-summary": "inspection"},
          "state_path": ".git/cpp-runs"}
PROTOCOL = gs.Protocol(family=CONFIG["family"], state_path=CONFIG["state_path"], plan="check",
                       operations=tuple(sorted(CONFIG["operations"].items())), profile_digest=SOURCE,
                       inventory_digest=SOURCE, producer_revision="b" * 40)
IDENTITY = gs.Identity("check-12345678.json", gs.digest(b"state"), 5)


def snap(*, populated: bool = False, **kwargs: Any) -> gs.Snapshot:
    return gs.Snapshot(kwargs.get("repository", "repo"), kwargs.get("source", SOURCE),
                       {IDENTITY.file: IDENTITY} if populated else {}, kwargs.get("reason"))


def wire(*, carried: bool = False, consumed: bool = False, final: str = "present") -> dict[str, Any]:
    def identity(kind: str, yes: bool) -> dict[str, Any]:
        return {"status": kind if yes else "none", **(IDENTITY.json() if yes else
                {"file": None, "sha256": None, "bytes": None}),
                "reason": None if yes else "no-selected-state" if kind == "loaded" else "no-save"}
    return {"run_id": "check-12345678", "plan": "check", "success": True, "failed_step": None,
            "step_details": [{"id": "lint", "status": "success", "executed_in_this_run": not carried,
                              "carried_from_previous_run": carried}],
            "resume_state_evidence": {"version": 1, "family": "cpp-run-state", "plan": "check",
                                      "consumed": identity("loaded", consumed),
                                      "generated": identity("written", True),
                                      "final_state": {"status": final, "reason": None}}}


def output(doc: dict[str, Any]) -> ExecuteResult:
    return ExecuteResult(reason="exited", exit_code=0,
                         stdout=(json.dumps(doc, indent=2) + "\nFLOW_FINISH_GATE: ok\n").encode(), stderr=b"")


def finish(ledger: gs.Ledger, execution: gs.Execution, result: ExecuteResult,
           after: gs.Snapshot, gate: str = "flow-check-plan") -> tuple[Any, dict[str, object]]:
    retained = {s: {"coverage": "complete", "digest": gs.digest(getattr(result, s) or b""),
                    "size": len(getattr(result, s) or b"")} for s in ("stdout", "stderr")}
    return ledger.finish(execution, gate, result, retained, after,
                         stage_capture.capture_stages(result.stdout, result.exit_code))


def admitted() -> gs.Ledger:
    ledger = gs.Ledger(PROTOCOL, "a-1")
    stages, evidence = finish(ledger, ledger.begin("/work/repo", snap()), output(wire()), snap(populated=True))
    assert evidence["admission"] == "admitted"
    assert stages["stages"]["lint"]["outcome"] == "passed"
    return ledger


def test_fresh_and_exact_join_have_real_controller_stage_origin() -> None:
    ledger = admitted()
    stages, evidence = finish(ledger, ledger.begin("/work/repo", snap(populated=True)),
                              output(wire(carried=True, consumed=True)), snap(populated=True))
    assert evidence["admission"] == "preserved"
    assert next(iter(ledger.leases.values())).sequence == 1
    assert stages["stages"]["lint"]["outcome"] == "passed"
    assert stages["stages"]["lint"]["origin_execution"] == 1


CASES = json.loads((ROOT / "tests/fixtures/gate-state/cases.json").read_text())


@pytest.mark.parametrize("case", CASES["refused"], ids=lambda c: c["id"])
def test_committed_refusal_inputs(case: dict[str, Any]) -> None:
    ledger = admitted()
    before, after = snap(populated=True), snap(populated=True)
    doc = wire(carried=True, consumed=True)
    result = output(doc)
    cwd: str | None = "/work/repo"
    op = case["id"]
    if op == "seeded":
        ledger = gs.Ledger(PROTOCOL, "a-1")
    elif op == "other-attempt":
        ledger = gs.Ledger(PROTOCOL, "a-2")
    elif op == "other-profile":
        ledger.protocol = replace(PROTOCOL, profile_digest="sha256:" + "c" * 64)
    elif op == "other-inventory":
        ledger.protocol = replace(PROTOCOL, inventory_digest="sha256:" + "c" * 64)
    elif op == "other-producer":
        ledger.protocol = replace(PROTOCOL, producer_revision="c" * 40)
    elif op == "other-plan":
        ledger.protocol = replace(PROTOCOL, plan="finish")
    elif op == "other-repository":
        before = after = snap(populated=True, repository="elsewhere")
    elif op == "other-source":
        before = after = snap(populated=True, source="sha256:" + "c" * 64)
    elif op == "other-cwd":
        cwd = "/work/repo/subdir"
    elif op == "missing-cwd":
        cwd = None
    elif op == "tampered":
        before = replace(before, files={IDENTITY.file: replace(IDENTITY, sha256=SOURCE)})
    elif op == "end-mismatch":
        after = snap()
    elif op == "source-mutated":
        after = snap(populated=True, source="sha256:" + "c" * 64)
    elif op == "export-unreadable":
        after = snap(reason="state-export-unreadable")
    elif op in ("timeout-none", "timeout-false", "timeout-true"):
        result = replace(result, reason="timeout", stop_confirmed={"none": None, "false": False, "true": True}[op.split("-")[1]])
    elif op == "stop-false":
        result = replace(result, stop_confirmed=False)
    elif op == "stop-malformed":
        result = replace(result, stop_confirmed=1)  # type: ignore[arg-type]
    elif op == "bool-exit":
        result = replace(result, exit_code=True)
    elif op == "missing-exit":
        result = replace(result, exit_code=None)
    elif op == "missing-output":
        result = replace(result, stdout=None)
    elif op == "partial-output":
        result = replace(result, stderr_incomplete=True)
    elif op == "truncated-output":
        result = replace(result, stdout_truncated=True)
    elif op == "duplicate-key":
        result = replace(result, stdout=result.stdout.replace(b'"plan": "check",', b'"plan": "check", "plan": "check",', 1))  # type: ignore[union-attr]
    elif op == "compact-document":
        result = replace(result, stdout=b'{"error":"second-document"}\n' + result.stdout)  # type: ignore[operator]
    elif op == "indented-document":
        result = replace(result, stdout=b'  {\n    "error": "second"\n  }\n' + result.stdout)  # type: ignore[operator]
    elif op == "duplicate-verdict":
        result = replace(result, stdout=b"FLOW_FINISH_GATE: fail\n" + result.stdout)  # type: ignore[operator]
    elif op == "duplicate-document":
        result = replace(result, stdout=result.stdout + result.stdout)  # type: ignore[operator]
    else:
        meta = doc["resume_state_evidence"]
        if op == "missing-run-id": doc.pop("run_id")
        elif op == "unsafe-run-id": doc["run_id"] = "../check-12345678"
        elif op == "mismatched-run-id": doc["run_id"] = "check-87654321"
        elif op == "unknown-version": meta["version"] = 2
        elif op == "wrong-family": meta["family"] = "other"
        elif op == "unknown-field": meta["extra"] = True
        elif op == "unsafe-file": meta["consumed"]["file"] = "../state"
        elif op == "unreadable-generated": meta["generated"] = {"status": "unreadable", "file": None, "sha256": None, "bytes": None, "reason": "write-failed"}
        elif op == "contradictory-carry": doc["step_details"][0]["executed_in_this_run"] = True
        elif op == "malformed-carry": doc["step_details"][0]["carried_from_previous_run"] = 1
        elif op == "error-envelope": doc = {"error": "failure", "resume_state_evidence": meta}
        else: raise AssertionError(op)
        result = output(doc)
    stages, evidence = finish(ledger, ledger.begin(cwd, before), result, after)
    assert evidence["admission"] == "refused", (case, evidence)
    assert stages["status"] == "unavailable", (case, stages)


def test_missing_prior_stage_never_inherits_from_bytes_alone() -> None:
    ledger = admitted()
    key = next(iter(ledger.leases))
    ledger.leases[key] = replace(ledger.leases[key], facts={})
    stages, _ = finish(ledger, ledger.begin("/work/repo", snap(populated=True)),
                       output(wire(carried=True, consumed=True)), snap(populated=True))
    assert stages["stages"]["lint"]["outcome"] is None


def test_cleanup_clears_lease_but_keeps_completed_stage_facts() -> None:
    ledger = admitted()
    stages, evidence = finish(ledger, ledger.begin("/work/repo", snap(populated=True)),
                              output(wire(carried=True, consumed=True, final="absent")), snap())
    assert evidence["admission"] == "absent" and not ledger.leases
    assert stages["stages"]["lint"]["outcome"] == "passed"


def test_inspection_preserves_only_unchanged_prior_lease() -> None:
    result = ExecuteResult(reason="exited", exit_code=0, stdout=b"Makefile OK\nFLOW_FINISH_GATE: ok\n", stderr=b"")
    ledger = admitted()
    stages, evidence = finish(ledger, ledger.begin("/work/repo", snap(populated=True)), result,
                              snap(populated=True), "flow-check-summary")
    assert stages is None and evidence["admission"] == "preserved"
    empty = gs.Ledger(PROTOCOL, "a-1")
    stages, evidence = finish(empty, empty.begin("/work/repo", snap(populated=True)), result,
                              snap(populated=True), "flow-check-summary")
    assert stages is None and evidence["admission"] == "refused" and not empty.leases


def test_stale_completion_cannot_publish_or_erase_newer_generation() -> None:
    ledger = admitted()
    old = ledger.begin("/work/repo", snap(populated=True))
    new = ledger.begin("/work/repo", snap(populated=True))
    finish(ledger, new, output(wire(carried=True, consumed=True)), snap(populated=True))
    prior = copy.deepcopy(ledger.leases)
    stages, evidence = finish(ledger, old, output(wire(carried=True, consumed=True)), snap(populated=True))
    assert stages["status"] == "unavailable" and evidence["reason"] == "stale-execution"
    assert ledger.leases == prior


@pytest.mark.parametrize("defect", ["symlink-parent", "symlink-file", "directory", "two", "unsafe", "overflow"])
def test_snapshot_refuses_unsafe_or_oversize_population(tmp_path: Path, defect: str) -> None:
    state = tmp_path / ".git/cpp-runs"
    state.mkdir(parents=True)
    if defect == "symlink-parent":
        state.rmdir(); state.symlink_to(tmp_path, target_is_directory=True)
    elif defect == "symlink-file":
        (state / "state").symlink_to(tmp_path / "elsewhere")
    elif defect == "directory": (state / "state").mkdir()
    elif defect == "two": (state / "one").touch(); (state / "two").touch()
    elif defect == "unsafe": (state / "bad name").touch()
    elif defect == "overflow":
        with (state / "state").open("wb") as stream: stream.truncate(gs.MAX_BYTES + 1)
    assert not gs.snapshot(tmp_path, (".git/cpp-runs",), repository="repo", source=SOURCE).complete


def test_snapshot_empty_and_exact_file_identity(tmp_path: Path) -> None:
    assert gs.snapshot(tmp_path, (".git/cpp-runs",), repository="repo", source=SOURCE).files == {}
    state = tmp_path / ".git/cpp-runs"; state.mkdir(parents=True); (state / IDENTITY.file).write_bytes(b"state")
    assert gs.snapshot(tmp_path, (".git/cpp-runs",), repository="repo", source=SOURCE).files == {IDENTITY.file: IDENTITY}


@pytest.mark.parametrize("mutation", ["plan", "operation", "unknown", "null", "empty"])
def test_declared_protocol_is_closed_and_exact(mutation: str) -> None:
    cfg: Any = copy.deepcopy(CONFIG)
    if mutation == "plan": cfg["plan"] = "finish"
    elif mutation == "operation": cfg["operations"]["flow-check-summary"] = "runner"
    elif mutation == "unknown": cfg["extra"] = True
    elif mutation == "null": cfg = None
    elif mutation == "empty": cfg = {}
    with pytest.raises(ValueError): gs.configuration(cfg)
    assert gs.configuration(CONFIG) == CONFIG


def test_no_save_and_duplicate_output_cannot_mint_new_facts() -> None:
    ledger = admitted()
    doc = wire(carried=True, consumed=True)
    doc["resume_state_evidence"]["generated"] = {
        "status": "none", "file": None, "sha256": None, "bytes": None, "reason": "no-save"}
    stages, evidence = finish(ledger, ledger.begin("/work/repo", snap(populated=True)), output(doc), snap(populated=True))
    assert evidence["admission"] == "preserved" and stages["stages"]["lint"]["origin_execution"] == 1
    # Identical complete carried stream is conservatively not a new invocation.
    stages, evidence = finish(ledger, ledger.begin("/work/repo", snap(populated=True)), output(doc), snap(populated=True))
    assert evidence["admission"] == "preserved" and stages["stages"]["lint"]["origin_execution"] == 1
    fresh = wire()
    fresh["resume_state_evidence"]["generated"] = doc["resume_state_evidence"]["generated"]
    empty = gs.Ledger(PROTOCOL, "a-1")
    stages, evidence = finish(empty, empty.begin("/work/repo", snap()), output(fresh), snap())
    assert evidence["admission"] == "refused" and stages["status"] == "unavailable" and not empty.leases


@pytest.mark.parametrize("alias", ["cwd", "source"])
@pytest.mark.parametrize("failure", ["backend", "cleanup"])
def test_failure_or_cleanup_invalidates_same_state_namespace_across_keys(alias: str, failure: str) -> None:
    ledger = admitted()
    before = snap(populated=True, source=("sha256:" + "c" * 64) if alias == "source" else SOURCE)
    cwd = "/work/repo/subdir" if alias == "cwd" else "/work/repo"
    after = before if failure == "backend" else replace(before, files={})
    result = (replace(output(wire(carried=True, consumed=True)), reason="timeout") if failure == "backend"
              else output(wire(carried=True, consumed=True, final="absent")))
    finish(ledger, ledger.begin(cwd, before), result, after)
    assert not ledger.leases
    # Restoring the original source/cwd/file cannot resurrect disposed history.
    stages, evidence = finish(ledger, ledger.begin("/work/repo", snap(populated=True)),
                              output(wire(carried=True, consumed=True)), snap(populated=True))
    assert evidence["admission"] == "refused" and stages["status"] == "unavailable"


def test_mismatching_prior_controller_stage_status_is_not_inherited() -> None:
    ledger = admitted()
    key = next(iter(ledger.leases))
    ledger.leases[key] = replace(ledger.leases[key], facts={"lint": {
        "outcome": "failed", "runner_status": "failed", "reason": None, "origin_execution": 1}})
    stages, _ = finish(ledger, ledger.begin("/work/repo", snap(populated=True)),
                       output(wire(carried=True, consumed=True)), snap(populated=True))
    assert stages["stages"]["lint"]["outcome"] is None


@pytest.mark.parametrize("defect", ["bool-version", "bool-bytes", "oversized-bytes", "missing-metadata"])
def test_additional_closed_metadata_controls(defect: str) -> None:
    ledger = admitted()
    doc = wire(carried=True, consumed=True)
    meta = doc["resume_state_evidence"]
    if defect == "bool-version": meta["version"] = True
    elif defect == "bool-bytes": meta["consumed"]["bytes"] = True
    elif defect == "oversized-bytes": meta["consumed"]["bytes"] = gs.MAX_BYTES + 1
    elif defect == "missing-metadata": del doc["resume_state_evidence"]
    stages, evidence = finish(ledger, ledger.begin("/work/repo", snap(populated=True)), output(doc), snap(populated=True))
    assert stages["status"] == "unavailable" and evidence["admission"] == "refused" and not ledger.leases


@pytest.mark.parametrize("changed", ["source", "cwd", "repository"])
def test_previously_accepted_fresh_output_cannot_replay_under_another_key(changed: str) -> None:
    ledger = admitted()
    before = snap(source=("sha256:" + "c" * 64) if changed == "source" else SOURCE,
                  repository="other-repo" if changed == "repository" else "repo")
    after = replace(before, files={IDENTITY.file: IDENTITY})
    cwd = "/work/repo/subdir" if changed == "cwd" else "/work/repo"
    stages, evidence = finish(ledger, ledger.begin(cwd, before), output(wire()), after)
    assert evidence["admission"] == "refused" and stages["status"] == "unavailable"


@pytest.mark.parametrize("changed", ["source", "cwd", "repository"])
def test_distinct_fresh_stream_can_admit_under_another_key(changed: str) -> None:
    ledger = admitted()
    before = snap(source=("sha256:" + "c" * 64) if changed == "source" else SOURCE,
                  repository="other-repo" if changed == "repository" else "repo")
    fresh = gs.Identity("check-87654321.json", gs.digest(b"fresh"), 5)
    doc = wire()
    doc["run_id"] = "check-87654321"
    doc["resume_state_evidence"]["generated"].update(fresh.json())
    after = replace(before, files={fresh.file: fresh})
    cwd = "/work/repo/subdir" if changed == "cwd" else "/work/repo"
    stages, evidence = finish(ledger, ledger.begin(cwd, before), output(doc), after)
    assert evidence["admission"] == "admitted" and stages["stages"]["lint"]["origin_execution"] == 2


@pytest.mark.parametrize("value", [None, "", [], "/tmp/state", "state", ".git", ".git/", ".git/..",
                                   ".git/../state", ".git/cache/child", ".git/bad name", ".git/link\\child"])
def test_declared_state_path_is_mandatory_and_one_safe_git_directory(value: object) -> None:
    cfg = copy.deepcopy(CONFIG)
    cfg["state_path"] = value
    with pytest.raises(ValueError, match="state_path"):
        gs.configuration(cfg)
    del cfg["state_path"]
    with pytest.raises(ValueError): gs.configuration(cfg)


@pytest.mark.parametrize("value", [None, "", [], "unsafe/name", "a" * 65])
def test_declared_family_is_mandatory_and_safe(value: object) -> None:
    cfg = copy.deepcopy(CONFIG)
    cfg["family"] = value
    with pytest.raises(ValueError, match="family"):
        gs.configuration(cfg)


def test_family_and_state_path_are_in_immutable_protocol_identity() -> None:
    assert replace(PROTOCOL, family="other-family").identity != PROTOCOL.identity
    assert replace(PROTOCOL, state_path=".git/other-state").identity != PROTOCOL.identity
    ledger = gs.Ledger(replace(PROTOCOL, family="other-family"), "a-1")
    stages, evidence = finish(ledger, ledger.begin("/work/repo", snap()), output(wire()), snap(populated=True))
    assert stages["status"] == "unavailable" and evidence["admission"] == "refused"
