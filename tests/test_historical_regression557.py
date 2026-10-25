"""The public historical replay must distinguish good, bad, and blind graders."""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "evals/development-regressions/calibration-557-helper"
ARCHIVE = ROOT / "evals/calibration-557-repeat/historical-task-v1"


def replay(*args: str) -> tuple[int, dict]:
    completed = subprocess.run(
        [sys.executable, str(CASE / "replay.py"), *args], cwd=ROOT,
        capture_output=True, text=True, timeout=150, check=False,
    )
    assert completed.stderr == "", completed.stderr
    return completed.returncode, json.loads(completed.stdout)


def test_observed_failure_and_qualified_good_distinguished() -> None:
    code, result = replay()
    assert code == 0
    assert result["verdict"] == "PASS"
    assert result["results"] == {
        "bad": {"status": "FAIL", "violated": ["one-section-per-step", "report-verdict"]},
        "good": {"status": "PASS", "violated": []},
    }


@pytest.mark.parametrize("control", ["always-pass", "always-fail"])
def test_blind_grader_refused(control: str) -> None:
    code, result = replay("--control", control)
    assert code == 1
    assert result["verdict"] == "REFUSED"
    # These are real judge executions through the contained verifier.
    assert result["complete"] is True
    violated = [] if control == "always-pass" else [
        "approved-content-present", "one-section-per-step",
        "other-content-preserved", "report-verdict",
    ]
    expected = {"status": "PASS" if control == "always-pass" else "FAIL",
                "violated": violated}
    assert result["results"] == {"bad": expected, "good": expected}


@pytest.mark.parametrize("mutation", ["bytes", "missing", "extra", "symlink", "source", "source-missing", "mode"])
def test_drifted_candidate_refused(tmp_path: Path, mutation: str) -> None:
    case = tmp_path / "case"
    shutil.copytree(CASE, case)
    target = case / "bad/report.json"
    if mutation == "bytes":
        target.write_text("{}\n")
    elif mutation == "missing":
        target.unlink()
    elif mutation == "extra":
        (case / "bad/extra.txt").write_text("extra\n")
    elif mutation == "symlink":
        target.unlink()
        target.symlink_to(CASE / "bad/report.json")
    elif mutation == "source-missing":
        (case / "source.json").unlink()
    elif mutation == "mode":
        (case / "bad/tools/verify-change.py").chmod(0o644)
    else:
        (case / "source.json").write_text("{}\n")
    code, result = replay("--case", str(case))
    assert code == 1
    assert result["verdict"] == "REFUSED"
    assert "results" not in result


@pytest.mark.parametrize("member", ["grade_helper_different_question.py", "grader-controls/always_pass.py",
    "grader-controls/always_fail.py", "grader.json", "probe.py", "inputs.json", "missing-inputs"])
def test_drifted_grader_refused(tmp_path: Path, member: str) -> None:
    archive = tmp_path / "grader"
    shutil.copytree(ARCHIVE, archive)
    if member == "missing-inputs":
        (archive / "inputs.json").unlink()
    else:
        with (archive / member).open("a") as stream:
            stream.write("\n# drift\n")
    code, result = replay("--grader-root", str(archive))
    assert code == 1
    assert result["verdict"] == "REFUSED"
    assert "results" not in result


@pytest.mark.parametrize("fault", ["containment", "cleanup", "unknown"])
def test_incomplete_measurement_refused(monkeypatch: pytest.MonkeyPatch, fault: str) -> None:
    from skillc import verify

    spec = importlib.util.spec_from_file_location("historical_replay557", CASE / "replay.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    real_grade = verify.grade_files

    def inject(*args, **kwargs):
        result = real_grade(*args, **kwargs)
        # Fault injection into real verifier output; neither expected verdicts
        # nor the public always-pass/always-fail judge controls are stubbed.
        if fault == "containment":
            result.containment["confirmed"] = False
        elif fault == "cleanup":
            result.containment["cleanup"] = "partial"
        else:
            for criterion in result.criteria:
                if criterion["id"] == "other-content-preserved":
                    criterion["outcome"] = "UNKNOWN"
        return result

    monkeypatch.setattr(verify, "grade_files", inject)
    result = module.run(CASE, None, None)
    assert result["complete"] is False
    assert result["verdict"] == "REFUSED"
