"""Real captured patches, controller Git, and existing supervised verification."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest

from skillc import trial

ROOT = Path(__file__).resolve().parents[1] / "evals/coordination/register-wave-completion"
spec = importlib.util.spec_from_file_location("quote_task_fixture", ROOT / "quote_task.py")
assert spec and spec.loader
task: Any = importlib.util.module_from_spec(spec)
spec.loader.exec_module(task)


def retain(base: Path, report: dict[str, Any], label: str) -> None:
    output = Path(os.environ.get("PYTEST_REPORT_DIR", "reports"))
    target = output / f"quote-{label}-{report['rows'][0]['experiment']}"
    target.mkdir(parents=True)
    (target / "qualification.json").write_text(json.dumps(report, indent=2))
    shutil.copytree(base / "store", target / "store")


@pytest.fixture(scope="module")
def qualified(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, Any]]:
    base = tmp_path_factory.mktemp("quote-real")
    report = task.qualify(base)
    (base / "qualification.json").write_text(json.dumps(report, indent=2))
    retain(base, report, "real")
    return base, report


def absent(experiment: trial.Experiment, row: dict[str, Any]) -> None:
    assert len(row["attempts"]) == 3
    for record in row["attempts"].values():
        aid = record["id"]
        assert record["cleanup"]["status"] in {"removed", "not-needed"}
        assert (experiment.root / f"lifecycle-{aid}.json").is_file()
        for event in experiment.events(aid):
            if event["event"] == "workspace":
                assert not Path(str(event["path"])).exists()
            if event["event"] == "started":
                with pytest.raises(ProcessLookupError):
                    os.killpg(int(str(event["pid"])), 0)


@pytest.mark.parametrize("name", task.CASE_IDS)
def test_committed_population(qualified: tuple[Path, dict[str, Any]], name: str) -> None:
    base, report = qualified
    row = next(r for r in report["rows"] if r["id"] == name)
    assert row["matches"], row
    absent(trial.Experiment.open(base / "store" / row["experiment"]), row)
    if row["oracle_executed"]:
        assert row["vectors"] == 100
        assert row["containment"]["confirmed"] is True
        assert row["containment"]["cleanup"] == "removed"


def test_qualification_is_complete(qualified: tuple[Path, dict[str, Any]]) -> None:
    _, report = qualified
    assert report["certified"], report
    assert report["planned"] == report["executed"] == 16
    assert report["oracle_executed"] == 13
    assert {r["id"] for r in report["rows"]} == set(task.CASE_IDS)


@pytest.mark.parametrize("names", [[], list(task.CASE_IDS[:-1]), [*task.CASE_IDS, "extra"],
                                  [*task.CASE_IDS[:-1], task.CASE_IDS[0]]])
def test_incomplete_population_cannot_certify(tmp_path: Path, names: list[str]) -> None:
    with pytest.raises(ValueError, match="exact nonempty unique"):
        task.qualify(tmp_path, cases=names)
    assert not (tmp_path / "store").exists()


@pytest.mark.parametrize("control,want,category", [("always-pass", "PASS", "verdict"),
                                                  ("always-fail", "FAIL", "verdict"),
                                                  ("crash", "UNKNOWN", "exit-nonzero"),
                                                  ("no-output", "UNKNOWN", "no-output")])
def test_blind_graders_are_refused(tmp_path: Path, control: str, want: str, category: str) -> None:
    source = "raise SystemExit(7)" if control == "crash" else "pass"
    if control.startswith("always-"):
        outcome = "SATISFIED" if control == "always-pass" else "VIOLATED"
        report = {"grader": {"id": "coordination-quote", "revision": "1"}, "criteria": [
            {"id": cid, "mandatory": True, "outcome": outcome, "evidence": ["blind control"]}
            for cid in ("delivery", "behavior")]}
        source = "import json\nprint(json.dumps(" + repr(report) + "))\n"
    judge = tmp_path / "bad_judge.py"
    judge.write_text(source)
    result = task.qualify(tmp_path, judge=judge)
    (tmp_path / "qualification.json").write_text(json.dumps(result, indent=2))
    retain(tmp_path, result, control)
    assert result["certified"] is False
    assert result["executed"] == result["planned"] == 16
    executed = [r for r in result["rows"] if r["oracle_executed"]]
    assert len(executed) == 13
    assert {(r["status"], r["grade_category"]) for r in executed} == {(want, category)}


def test_remote_not_local_files_supplies_delivery(qualified: tuple[Path, dict[str, Any]]) -> None:
    base, report = qualified
    for name, status in (("correct-remote-wrong-local", "PASS"), ("wrong-remote-correct-local", "FAIL")):
        row = next(r for r in report["rows"] if r["id"] == name)
        assert row["status"] == status
        experiment = trial.Experiment.open(base / "store" / row["experiment"])
        aid = row["attempts"]["service"]["id"]
        local = next(a for a in trial.frozen_artifacts(experiment, aid) if a["path"] == "repo/src/subtotal.py")
        text = trial.read_object(experiment, str(local["digest"])).decode()
        assert ("-999" in text) == (status == "PASS")


def test_oracle_adapter_uses_no_git(qualified: tuple[Path, dict[str, Any]], tmp_path: Path,
                                  monkeypatch: pytest.MonkeyPatch) -> None:
    base, report = qualified
    row = next(r for r in report["rows"] if r["id"] == "healthy")
    experiment = trial.Experiment.open(base / "store" / row["experiment"])
    trusted = json.loads(next(c for c in row["criteria"] if c["id"] == "delivery")["evidence"][0])

    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("post-stop host Git is forbidden")

    monkeypatch.setattr(task, "git", forbidden)
    monkeypatch.setattr(task.subprocess, "run", forbidden)
    files, raw = task.oracle_inputs(experiment, {r: v["id"] for r, v in row["attempts"].items()},
                                   task.definition()["seed"], trusted["seed"], tmp_path)
    facts = json.loads(raw)
    assert facts == trusted
    assert {name: task.digest(data) for name, data, _ in files} == facts["source"]


def test_expired_case_budget_does_not_restart(tmp_path: Path) -> None:
    row, experiment = task.run_case("healthy", tmp_path, budget=0.000001)
    assert row["status"] == "FAIL" and row["violated"] == ["deadline"]
    absent(experiment, row)


@pytest.mark.parametrize("role,change", [("worker-a", {"path": ".git/config"}),
                                        ("worker-a", {"role": "worker-b"}),
                                        ("worker-b", {"base": "obsolete"})])
def test_closed_patch_identity(role: str, change: dict[str, str]) -> None:
    data = task.definition()
    value = {"role": role, "path": task.PATHS[role],
             "base": task.digest(data["seed"][task.PATHS[role]].encode()), "content": "replacement"}
    assert task.valid_patch(value, role, data["seed"])
    assert not task.valid_patch({**value, **change}, role, data["seed"])


def test_oracle_cleanup_uncertainty_cannot_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    remove = task.verify.remove_owned

    def uncertain(*args: Any, **kwargs: Any) -> dict[str, Any]:
        result = remove(*args, **kwargs)
        assert result["status"] == "removed"
        return {"status": "partial", "errors": ["injected confirmation loss after real cleanup"]}

    monkeypatch.setattr(task.verify, "remove_owned", uncertain)
    row, experiment = task.run_case("healthy", tmp_path)
    absent(experiment, row)
    assert row["containment"]["cleanup"] == "partial"
    assert row["status"] == "UNKNOWN", row
    assert row["matches"] is False


def test_partial_allocation_accounts_for_every_attempt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    allocate = trial.allocate_workspace
    calls = []

    def interrupted(*args: Any, **kwargs: Any) -> Path:
        work = allocate(*args, **kwargs)
        calls.append(work)
        if len(calls) == 2:
            raise OSError("injected post-ownership allocation failure")
        return work

    monkeypatch.setattr(trial, "allocate_workspace", interrupted)
    row, experiment = task.run_case("healthy", tmp_path)
    assert row["status"] == "UNKNOWN"
    absent(experiment, row)
    assert all(v["lifecycle"] == "not-run" for v in row["attempts"].values())


def test_clock_policy_rejects_late_failure_as_qualification_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    grade, clock = task.verify.grade_files, task.time.monotonic

    def late(*args: Any, **kwargs: Any) -> Any:
        result = grade(*args, **kwargs)
        monkeypatch.setattr(task.time, "monotonic", lambda: clock() + 31)
        return result

    monkeypatch.setattr(task.verify, "grade_files", late)
    row, experiment = task.run_case("wrong-tax", tmp_path)
    absent(experiment, row)
    assert row["status"] == "FAIL" and row["violated"] == ["behavior"]
    assert row["matches"] is False


def test_unrelated_unavailability_cannot_substitute_for_injected_fault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    popen = trial.subprocess.Popen

    def unavailable(argv: Any, *args: Any, **kwargs: Any) -> Any:
        if len(argv) > 2 and str(argv[2]).endswith("service.py"):
            raise FileNotFoundError("injected service launch loss before snapshot corruption")
        return popen(argv, *args, **kwargs)

    monkeypatch.setattr(trial.subprocess, "Popen", unavailable)
    row, experiment = task.run_case("corrupt-snapshot", tmp_path)
    absent(experiment, row)
    assert row["status"] == "UNKNOWN"
    assert row["attempts"]["service"]["lifecycle"] == "unavailable"
    assert row["matches"] is False


def test_readable_snapshot_missing_delivered_ref_is_task_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    capture = trial.capture

    def remove_ref(experiment: Any, aid: str, output: Path, **kwargs: Any) -> Any:
        if str(experiment.trial_of(aid)["trial_id"]).endswith("service"):
            task.git(output / "fixture-remote.git", task.time.monotonic() + 10,
                     "update-ref", "-d", "refs/heads/delivered")
        return capture(experiment, aid, output, **kwargs)

    monkeypatch.setattr(trial, "capture", remove_ref)
    row, experiment = task.run_case("healthy", tmp_path)
    absent(experiment, row)
    assert row["status"] == "FAIL" and "delivery" in row["violated"], row


@pytest.mark.parametrize("mode", ["120000", "100755", "wrong-kind"])
def test_nonregular_git_entry_is_not_executed_as_regular_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    capture = trial.capture

    def symlink_tree(experiment: Any, aid: str, output: Path, **kwargs: Any) -> Any:
        if str(experiment.trial_of(aid)["trial_id"]).endswith("service"):
            repo, limit = output / "fixture-remote.git", task.time.monotonic() + 10
            head = task.git(repo, limit, "rev-parse", "refs/heads/delivered")
            entries = task.git(repo, limit, "ls-tree", head + ":src").splitlines()
            if mode == "wrong-kind":
                code = task.definition()["implementations"]["worker-a"][0].encode()
                wrong = task.git(repo, limit, "hash-object", "-t", "tree", "--literally", "-w", "--stdin", stdin=code)
                raw = b""
                for line in entries:
                    meta, name = line.split("\t")
                    filemode, _, oid = meta.split()
                    raw += filemode.encode() + b" " + name.encode() + b"\0" + bytes.fromhex(wrong if name == "subtotal.py" else oid)
                src = task.git(repo, limit, "hash-object", "-t", "tree", "--literally", "-w", "--stdin", stdin=raw)
            else:
                entries = [line.replace("100644", mode, 1) if line.endswith("\tsubtotal.py") else line for line in entries]
                src = task.git(repo, limit, "mktree", stdin=("\n".join(entries) + "\n").encode())
            tree = task.git(repo, limit, "mktree", stdin=f"040000 tree {src}\tsrc\n".encode())
            commit = task.git(repo, limit, "commit-tree", tree, "-p", head, stdin=b"controlled nonregular source\n")
            task.git(repo, limit, "update-ref", "refs/heads/delivered", commit)
        return capture(experiment, aid, output, **kwargs)

    monkeypatch.setattr(trial, "capture", symlink_tree)
    row, experiment = task.run_case("healthy", tmp_path)
    absent(experiment, row)
    assert row["status"] == "FAIL" and "delivery" in row["violated"], row
    facts = json.loads(next(c for c in row["criteria"] if c["id"] == "delivery")["evidence"][0])
    assert facts["entries"]["src/subtotal.py"]["mode"] == ("100644" if mode == "wrong-kind" else mode)
    assert facts["entries"]["src/subtotal.py"]["kind"] == ("tree" if mode == "wrong-kind" else "blob" if mode == "100755" else "not-read")
    assert ("src/subtotal.py" in facts["source"]) == (mode == "100755")


def test_patch_bound_covers_whole_object_with_exact_twin() -> None:
    data = task.definition()
    role = "worker-a"
    value = {"role": role, "path": task.PATHS[role],
             "base": task.digest(data["seed"][task.PATHS[role]].encode()), "content": ""}
    value["content"] = "x" * (4096 - len(trial.canonical(value)))
    assert len(trial.canonical(value)) == 4096 and task.valid_patch(value, role, data["seed"])
    assert not task.valid_patch({**value, "content": value["content"] + "x"}, role, data["seed"])


def test_raw_captured_patch_bound_includes_whitespace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    capture = trial.capture

    def oversized(experiment: Any, aid: str, output: Path, **kwargs: Any) -> Any:
        if str(experiment.trial_of(aid)["trial_id"]).endswith("worker-a"):
            path = output / "patch.json"
            raw = path.read_bytes()
            path.write_bytes(raw + b" " * (4097 - len(raw)))
        return capture(experiment, aid, output, **kwargs)

    monkeypatch.setattr(trial, "capture", oversized)
    row, experiment = task.run_case("healthy", tmp_path)
    absent(experiment, row)
    assert row["status"] == "FAIL" and "delivery" in row["violated"], row
