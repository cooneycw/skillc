"""The #620 PR-B physical-fact probe (scripts/probe_task_protocol_socket.py).

Its physical readings need a real daemon and an authorized run; these tests
cover what CI can: the committed readings classify to their declared outcomes,
each classifier made blind disagrees with them, the script stays stdlib-only
and skillc-free, and a run that cannot reach a daemon is never a pass."""

from __future__ import annotations

import ast
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from skillc import backend

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "probe_task_protocol_socket.py"
CASES = ROOT / "controls" / "task-protocol-probe" / "cases.json"
_spec = importlib.util.spec_from_file_location("probe_task_protocol_socket", SCRIPT)
assert _spec is not None and _spec.loader is not None
probe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(probe)


def _cases() -> list[dict[str, Any]]:
    cases = json.loads(CASES.read_text())
    assert isinstance(cases, list) and cases
    return cases


def _disagreements() -> set[str]:
    return {c["name"] for c in _cases()
            if probe.classify(c["fact"], c["readings"])["verdict"] != c["expect"]}


def test_every_committed_reading_classifies_to_its_declared_outcome() -> None:
    report = probe.selftest(CASES)
    assert report["selftest"] == "pass", [c for c in report["cases"] if c["got"] != c["expect"]]


def test_the_committed_cases_cover_every_outcome_for_every_fact() -> None:
    by_fact: dict[str, set[str]] = {}
    for case in _cases():
        by_fact.setdefault(case["fact"].split(":")[0], set()).add(case["expect"])
    gated = {probe.HOLDS, probe.FAILS, probe.NOT_COVERED}
    assert by_fact["environment"] == {probe.HOLDS, probe.NOT_COVERED}
    for fact in ("ro-mount", "peercred", "exclusive"):
        assert by_fact[fact] == gated, fact
    assert by_fact["recreate"] == {probe.REACHES_NEW, probe.DEAD_END, probe.NOT_COVERED}


def test_selftest_refuses_an_unreadable_case_file(tmp_path: Path) -> None:
    missing = tmp_path / "absent.json"
    assert probe.selftest(missing)["outcome"] == probe.NOT_COVERED
    done = subprocess.run([sys.executable, "-I", str(SCRIPT), "selftest", "--cases", str(missing)],
                          capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 3


def test_selftest_runs_as_an_isolated_script() -> None:
    done = subprocess.run([sys.executable, "-I", str(SCRIPT), "selftest"],
                          capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0 and json.loads(done.stdout)["selftest"] == "pass"


# Blind variants: each one must disagree with a committed case, or the cases
# could not tell a working classifier from a broken one.


@pytest.mark.parametrize("constant", ["holds", "fails", "not-covered"])
def test_a_constant_classifier_disagrees(monkeypatch: pytest.MonkeyPatch, constant: str) -> None:
    def blind(*_a: object, **_k: object) -> dict[str, Any]:
        return {"verdict": constant, "reasons": []}

    for name in ("classify_environment", "classify_f2", "classify_recreate", "classify_f1_shape",
                 "classify_f3"):
        monkeypatch.setattr(probe, name, blind)
    assert _disagreements()


def test_a_uid_only_identifier_is_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    """The named F2 red case: a peer sharing the candidate uid must not
    identify as the owned sandbox."""
    def uid_only(peer: dict[str, Any], _ns: int, uid: int, gid: int) -> str:
        return "yes" if (peer["uid"], peer["gid"]) == (uid, gid) else "no"

    monkeypatch.setattr(probe, "identify", uid_only)
    assert {"peercred-healthy", "peercred-host-peer-with-candidate-uid"} <= _disagreements()


def test_an_audit_that_accepts_everything_is_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    """The named F3 red case: the deliberate mis-mount must be refused."""
    monkeypatch.setattr(probe, "audit", lambda *_a: (True, []))
    monkeypatch.setattr(probe.classify_f3, "__defaults__", (probe.audit,))
    assert {"exclusive-file-healthy", "exclusive-dir-healthy"} <= _disagreements()


def test_a_classifier_blind_to_replacement_is_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    """The named F1 red case: a writable or replaceable mount must FAIL."""
    monkeypatch.setattr(probe, "_replaced",
                        lambda attempts: [] if isinstance(attempts, dict) else None)
    assert "file-healthy" in _disagreements()


def test_a_recreate_reader_that_always_reaches_is_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(probe, "classify_recreate",
                        lambda _r: {"verdict": probe.REACHES_NEW, "reasons": []})
    assert "recreate-file-dead-end" in _disagreements()


def test_a_real_fact_failure_is_never_reported_as_not_covered() -> None:
    assert probe.overall([probe.HOLDS, probe.FAILS, probe.NOT_COVERED]) == probe.FAILS
    assert probe.overall([probe.HOLDS, probe.NOT_COVERED]) == probe.NOT_COVERED
    assert probe.overall([probe.HOLDS, probe.DEAD_END, probe.REACHES_NEW]) == probe.HOLDS
    assert probe.overall([probe.DEAD_END]) == probe.HOLDS
    assert probe.overall([]) == probe.NOT_COVERED
    assert probe.overall(["something-else"]) == probe.NOT_COVERED
    assert probe.EXIT == {probe.HOLDS: 0, probe.FAILS: 4, probe.NOT_COVERED: 3}


def test_every_fact_reports_its_control() -> None:
    for case in _cases():
        if case["fact"] == "environment":
            continue
        verdict = probe.classify(case["fact"], case["readings"])
        if verdict["reasons"] != ["reading-unreadable"]:
            assert "control" in verdict, case["name"]


# Stdlib only, and never skillc: checked, with its own red case.


def _foreign_imports(source: str) -> set[str]:
    found = set()
    for node in ast.walk(ast.parse(source)):
        names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                 else [node.module or ""] if isinstance(node, ast.ImportFrom) and node.level == 0
                 else [])
        for name in names:
            top = name.split(".")[0]
            if top == "skillc" or top not in sys.stdlib_module_names:
                found.add(top)
        if isinstance(node, ast.ImportFrom) and node.level:
            found.add("." * node.level + (node.module or ""))
    return found


def test_the_import_check_can_fail() -> None:
    assert _foreign_imports("import skillc") == {"skillc"}
    assert _foreign_imports("from skillc.backend import CANDIDATE_UID") == {"skillc"}
    assert _foreign_imports("import requests") == {"requests"}
    assert _foreign_imports("from . import backend") == {"."}
    assert _foreign_imports("import json, socket\nfrom pathlib import Path") == set()


def test_the_probe_and_its_sandbox_code_import_only_the_stdlib() -> None:
    assert _foreign_imports(SCRIPT.read_text()) == set()
    assert _foreign_imports(probe._IN_SANDBOX) == set()


def test_the_candidate_identity_matches_skillc() -> None:
    assert (probe.CANDIDATE_UID, probe.CANDIDATE_GID) == (backend.CANDIDATE_UID,
                                                          backend.CANDIDATE_GID)


# Launch shape and the no-daemon run.


def test_a_probe_sandbox_never_pulls_and_holds_no_privilege() -> None:
    argv = probe.run_argv("n", "img", ["type=bind,source=/s,target=/t,readonly"])
    joined = " ".join(argv)
    assert ["--pull", "never"] == argv[argv.index("--pull"):argv.index("--pull") + 2]
    for flag in ("--network none", "--cap-drop ALL", "--security-opt no-new-privileges",
                 f"--user {backend.CANDIDATE_UID}:{backend.CANDIDATE_GID}",
                 "--label skillc.probe="):
        assert flag in joined
    assert "--privileged" not in argv and "docker.sock" not in joined
    assert argv.count("--mount") == 1


def test_the_two_mount_shapes_are_readonly_at_the_fixed_target(tmp_path: Path) -> None:
    assert probe.shape_mount("file", tmp_path) == (
        f"type=bind,source={tmp_path}/channel.sock,target=/run/skillc-task-protocol/channel.sock,"
        "readonly")
    assert probe.shape_mount("dir", tmp_path) == (
        f"type=bind,source={tmp_path},target=/run/skillc-task-protocol,readonly")
    writable = probe.shape_mount("dir", tmp_path, readonly=False)
    assert writable.endswith("target=/run/skillc-task-protocol")


def _no_daemon(calls: list[list[str]]) -> Any:
    def runner(argv: list[str], **_k: Any) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 1, "", "no daemon")
    return probe.Docker("img", runner)


def test_a_run_without_a_daemon_is_not_covered_never_a_pass(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKER_HOST", "tcp://private-name.invalid:2375")
    calls: list[list[str]] = []
    receipt = probe.live("img", list(probe.FACTS), docker=_no_daemon(calls))
    assert receipt["outcome"] == probe.NOT_COVERED
    assert receipt["environment"]["verdict"] == probe.NOT_COVERED
    assert all(r["verdict"] == probe.NOT_COVERED for r in receipt["facts"].values())
    assert receipt["containers_left"] == []
    assert "private-name" not in json.dumps(receipt)
    assert calls and not any(a[:2] == ["docker", "pull"] for a in calls)


def test_a_crashed_measurement_is_not_covered(monkeypatch: pytest.MonkeyPatch) -> None:
    def crash(_docker: object) -> dict[str, Any]:
        raise OSError("boom")

    monkeypatch.setitem(probe.FACTS, "peercred", crash)
    receipt = probe.live("img", ["peercred"], docker=_no_daemon([]))
    assert receipt["facts"]["peercred"]["verdict"] == probe.NOT_COVERED
    assert receipt["facts"]["peercred"]["readings"] == {"measurement_error": "OSError"}
