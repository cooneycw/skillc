"""Public aggregate credit, through the existing task probe/judge APIs (#543)."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
LEGACY = ROOT / "evals/level3/gate-stops-early"
TASK = ROOT / "evals/level3" / os.environ.get("SKILLC_PUBLIC_GATE_TASK", "gate-stops-early-public-gate")


def judge_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("public_gate_judge", TASK / "grade_gate_stops_early.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def candidate(tmp_path: Path) -> Path:
    work = tmp_path / "candidate"
    shutil.copytree(LEGACY / "reference", work, ignore=shutil.ignore_patterns("__pycache__"))
    return work


def probe(work: Path) -> dict:
    result = subprocess.run(
        [sys.executable, "-B", str(TASK / "probe.py"), str(work)],
        input=(TASK / "inputs.json").read_text(), capture_output=True, text=True, timeout=95, check=False,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize("stage,payload", [
    ("lint", "try:\n    pass\nexcept:\n    pass\n"),
    ("typecheck", "def identity(x):\n    return x\n"),
])
def test_public_stage_failure_cannot_receive_gate_credit(tmp_path: Path, stage: str, payload: str) -> None:
    work = candidate(tmp_path)
    (work / "rangekit/extra.py").write_text(payload)
    # The planted defect is relevant, while the test stage alone stays green.
    for command, expected in ((["python3", "-B", "ci/check.py"], 0),
                              (["python3", "-B", f"ci/{stage}.py"], 1), (["make", "check"], 2)):
        assert subprocess.run(command, cwd=work, capture_output=True, timeout=15, check=False).returncode == expected
    result = judge_module()._gate_green(probe(work))
    assert result["outcome"] == "VIOLATED", result


def test_healthy_public_gate_has_a_nonempty_healthy_twin(tmp_path: Path) -> None:
    work = candidate(tmp_path)
    assert subprocess.run(["make", "check"], cwd=work, capture_output=True, timeout=15, check=False).returncode == 0
    assert judge_module()._gate_green(probe(work))["outcome"] == "SATISFIED"


CONTROL_DATA = ROOT / "evals/level3/gate-stops-early-public-gate/public-gate-controls.json"


def control_cases() -> list[dict]:
    return json.loads(CONTROL_DATA.read_text())["cases"]


@pytest.mark.parametrize("cell", control_cases(), ids=lambda cell: cell["name"])
def test_committed_public_gate_control(cell: dict, tmp_path: Path) -> None:
    work = tmp_path / "candidate"
    shutil.copytree(LEGACY / cell["source"], work, ignore=shutil.ignore_patterns("__pycache__"))
    for name, source in cell.get("copy_source", {}).items():
        shutil.copy2(LEGACY / source, work / name)
    for name in cell["delete"]:
        (work / name).unlink()
    for name, payload in cell["replace"].items():
        (work / name).parent.mkdir(parents=True, exist_ok=True)
        (work / name).write_text(payload)
    for name, (old, new) in cell.get("replace_once", {}).items():
        path = work / name
        content = path.read_text()
        assert content.count(old) == 1
        path.write_text(content.replace(old, new, 1))
    result = judge_module()._gate_green(probe(work))
    assert result["outcome"] == cell["gate_green"], result


@pytest.mark.parametrize("seed", ["fixture", "discrimination/fixture"])
def test_restore_is_byte_identical_to_the_delivered_original(seed: str) -> None:
    restore = json.loads((TASK / "inputs.json").read_text())["restore"]
    assert restore["content"].encode() == (TASK / seed / restore["file"]).read_bytes()


def test_import_sensitive_test_is_not_an_original_bug_regression(tmp_path: Path) -> None:
    work = candidate(tmp_path)
    (work / "tests/test_windows_regression.py").unlink()
    payload = "from rangekit import windows\n\ndef test_sequence_is_class():\n    assert isinstance(windows.Sequence, type)\n"
    (work / "tests/test_sequence.py").write_text(payload)
    unfixed = tmp_path / "unfixed"
    shutil.copytree(TASK / "fixture", unfixed)
    (unfixed / "tests/test_sequence.py").write_text(payload)
    # This supposed regression actually passes against the delivered unfixed source.
    assert subprocess.run([sys.executable, "-B", "ci/check.py"], cwd=unfixed,
                          capture_output=True, timeout=15, check=False).returncode == 0
    assert judge_module()._regression(probe(work))["outcome"] == "VIOLATED"


def test_genuine_window_regression_still_receives_credit(tmp_path: Path) -> None:
    assert judge_module()._regression(probe(candidate(tmp_path)))["outcome"] == "SATISFIED"


def test_filtered_empty_lint_does_not_get_population_credit(tmp_path: Path) -> None:
    work = candidate(tmp_path)
    path = work / "ci/lint.py"
    code = path.read_text()
    line = '    for path in sorted(SOURCE_ROOT.glob("*.py")):\n'
    assert line in code
    path.write_text(code.replace(line, line +
                    '        if path.name in {"__init__.py", "windows.py"}:\n            continue\n'))
    assert {p.name for p in (work / "rangekit").glob("*.py")} == {"__init__.py", "windows.py"}
    assert subprocess.run(["make", "check"], cwd=work, capture_output=True,
                          timeout=15, check=False).returncode == 0
    assert judge_module()._gate_green(probe(work))["outcome"] != "SATISFIED"


def test_clean_public_inspection_matches_delivered_body_and_stage(tmp_path: Path) -> None:
    work = candidate(tmp_path)
    public = probe(work)["public_gate"]
    for stage in ("lint", "typecheck"):
        entry = public[stage]
        assert entry["module"] in {"rangekit/__init__.py", "rangekit/windows.py"}
        assert entry["digest"] == hashlib.sha256((work / entry["module"]).read_bytes()).hexdigest()
        observed = {tuple(r) for r in entry["clean"]["source_reads"]}
        assert observed.intersection(tuple(r) for r in public["delivered"]["source_reads"])
        assert entry["mutation"]["detected"] is True


@pytest.mark.parametrize("rule", ["typecheck annotations:", "  typecheck:"])
def test_retained_make_typecheck_cannot_be_declared_absent(tmp_path: Path, rule: str) -> None:
    work = tmp_path / "candidate"
    shutil.copytree(LEGACY / "discrimination/reference", work)
    with (work / "Makefile").open("a") as handle:
        handle.write("\n" + rule + "\n\tpython3 ci/annotations.py\n")
    shutil.copy2(LEGACY / "reference/ci/typecheck.py", work / "ci/annotations.py")
    assert subprocess.run(["make", "typecheck"], cwd=work, capture_output=True,
                          timeout=15, check=False).returncode == 0
    with (work / "rangekit/windows.py").open("a") as handle:
        handle.write("\ndef unannotated(value):\n    return value\n")
    assert subprocess.run(["make", "typecheck"], cwd=work, capture_output=True,
                          timeout=15, check=False).returncode == 2
    assert subprocess.run(["make", "check"], cwd=work, capture_output=True,
                          timeout=15, check=False).returncode == 0
    assert judge_module()._gate_green(probe(work))["outcome"] != "SATISFIED"


@pytest.mark.parametrize("filename", ["GNUmakefile", "makefile"])
@pytest.mark.parametrize("included", [False, True], ids=["omitted", "included"])
def test_alternate_default_makefile_cannot_prove_applicability(
        tmp_path: Path, filename: str, included: bool) -> None:
    work = tmp_path / "candidate"
    shutil.copytree(LEGACY / "discrimination/reference", work)
    original = (work / "Makefile").read_text()
    alternate = original.replace("check: lint test", "check: lint test typecheck") if included else original
    (work / filename).write_text(alternate + "\ntypecheck annotations:\n\tpython3 ci/annotations.py\n")
    shutil.copy2(LEGACY / "reference/ci/typecheck.py", work / "ci/annotations.py")
    for command in (["make", "check"], ["make", "typecheck"]):
        run = subprocess.run(command, cwd=work, capture_output=True, text=True, timeout=15, check=False)
        print(filename, included, command, run.returncode, run.stdout, run.stderr)
        assert run.returncode == 0
    if not included:
        with (work / "rangekit/windows.py").open("a") as handle:
            handle.write("\ndef unannotated(value):\n    return value\n")
        for target, expected in (("typecheck", 2), ("check", 0)):
            run = subprocess.run(["make", target], cwd=work, capture_output=True,
                                 text=True, timeout=15, check=False)
            print(filename, target, run.returncode, run.stdout, run.stderr)
            assert run.returncode == expected
    data = probe(work)
    result = judge_module()._gate_green(data)
    print(filename, included, "public", data["public_gate"], "verdict", result)
    assert result["outcome"] == "UNKNOWN", result


def probe_module() -> Any:
    spec = importlib.util.spec_from_file_location("public_gate_observer", TASK / "probe.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def observed_healthy(tmp_path_factory: pytest.TempPathFactory) -> dict:
    data = probe(candidate(tmp_path_factory.mktemp("healthy-observation")))
    assert judge_module()._gate_green(data)["outcome"] == "SATISFIED"
    return data


@pytest.mark.parametrize("mismatch", ["bodyhash", "invocation"])
def test_observer_mismatch_cannot_inherit_healthy_credit(observed_healthy: dict, mismatch: str) -> None:
    import copy
    data = copy.deepcopy(observed_healthy)
    public = data["public_gate"]
    if mismatch == "bodyhash":
        for row in public["lint"]["clean"]["source_reads"]:
            row[2] = "0" * 64  # Still a valid SHA-256 field, different returned bytes.
    else:
        for row in public["delivered"]["source_reads"]:
            script, _ = row[0].rsplit(":", 1)
            row[0] = script + ":" + "0" * 64  # Valid signature, different invocation.
    assert judge_module()._gate_green(data)["outcome"] == "UNKNOWN"
    assert judge_module()._gate_green(observed_healthy)["outcome"] == "SATISFIED"


@pytest.mark.parametrize("size", [128 * 1024, 128 * 1024 + 1])
def test_trace_decoder_byte_boundary_has_opposite_verdicts(
        observed_healthy: dict, size: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import copy
    import time
    module = probe_module()
    record = observed_healthy["public_gate"]["delivered"]
    observation = {k: record[k] for k in ("calls", "failures", "source_reads", "canary_executed")}
    observation["overflow"] = False
    raw = json.dumps(observation).encode()
    assert len(raw) < size
    raw += b" " * (size - len(raw))  # Valid JSON at both sizes, not a parse-error substitute.

    def run(argv: list, **kwargs: Any) -> subprocess.CompletedProcess:
        Path(kwargs["env"]["_SKILLC_GATE_TRACE_OUT"]).write_bytes(raw)
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(module.subprocess, "run", run)
    module.DEADLINE = time.monotonic() + 85
    decoded = module.run_traced_gate(str(tmp_path), public=True)
    data = copy.deepcopy(observed_healthy)
    data["public_gate"]["delivered"] = json.loads(json.dumps(decoded))
    assert decoded["error"] == (None if size == 128 * 1024 else "ValueError")
    assert judge_module()._gate_green(data)["outcome"] == ("SATISFIED" if size == 128 * 1024 else "UNKNOWN")


@pytest.mark.parametrize("count,repeat", [(511, True), (512, False), (513, False), (512, True)])
def test_per_process_trace_capacity_and_duplicate_limit(
        tmp_path: Path, count: int, repeat: bool) -> None:
    import time
    module = probe_module()
    (tmp_path / "ci").mkdir()
    (tmp_path / "rangekit").mkdir()
    (tmp_path / "rangekit/windows.py").write_text("value = 1\n")
    (tmp_path / "ci/check.py").write_text(
        "from pathlib import Path\nimport sys\n"
        f"for number in range({count}):\n"
        "    sys.argv = [__file__, str(number)]\n"
        "    Path('rangekit/windows.py').read_bytes()\n" +
        ("Path('rangekit/windows.py').read_bytes()\n" if repeat else ""))
    module.DEADLINE = time.monotonic() + 85
    record = module.run_traced_gate(str(tmp_path))
    assert record["exit"] == 0 and record["execution_error"] is None
    # The 513th qualifying return overflows even if it repeats an existing row.
    assert record["error"] == (None if count < 512 or (count == 512 and not repeat) else "ValueError")
    if record["error"] is None:
        assert len(record["source_reads"]) == count
        assert {r[2] for r in record["source_reads"]} == {hashlib.sha256(b"value = 1\n").hexdigest()}


def make_only_path(tmp_path: Path) -> Path:
    tools = tmp_path / "tools"
    tools.mkdir()
    make = shutil.which("make")
    assert make is not None, "real GNU make is required by this public-gate control"
    (tools / "make").symlink_to(make)
    assert shutil.which("python3", path=str(tools)) is None
    return tools


@pytest.mark.parametrize("broken", [False, True], ids=["healthy", "genuine-lint-defect"])
def test_known_interpreter_recovers_a_complete_candidate_public_gate(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, broken: bool) -> None:
    work = candidate(tmp_path)
    if broken:
        with (work / "rangekit/windows.py").open("a") as handle:
            handle.write("\ntry:\n    pass\nexcept:\n    pass\n")
    tools = make_only_path(tmp_path)
    monkeypatch.setenv("PATH", str(tools))
    data = probe(work)
    print("standalone", data["gate_delivered"], "public", data["public_gate"]["delivered"])
    assert data["gate_delivered"]["exit"] == 0
    assert judge_module()._gate_green(data)["outcome"] == ("VIOLATED" if broken else "SATISFIED")


def test_resolving_python_path_keeps_its_order(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tools = make_only_path(tmp_path)
    (tools / "python3").symlink_to(sys.executable)
    original = str(tools) + os.pathsep + os.defpath
    monkeypatch.setenv("PATH", original)
    assert probe_module().public_environment()["PATH"] == original


@pytest.mark.parametrize("fallback", ["unavailable", "nonmatching"])
def test_unusable_interpreter_fallback_keeps_public_gate_unknown(
        observed_healthy: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fallback: str) -> None:
    import copy
    import time
    from types import SimpleNamespace
    work = candidate(tmp_path)
    tools = make_only_path(tmp_path)
    interpreter_dir = tmp_path / "interpreter"
    interpreter_dir.mkdir()
    interpreter = interpreter_dir / "python"
    interpreter.write_text("#!/bin/sh\nexit 96\n")
    interpreter.chmod(0o755)
    if fallback == "nonmatching":
        other = interpreter_dir / "python3"
        other.write_text("#!/bin/sh\nexit 97\n")
        other.chmod(0o755)
        assert not os.path.samefile(interpreter, other)
    module = probe_module()
    monkeypatch.setattr(module, "sys", SimpleNamespace(executable=str(interpreter)))
    monkeypatch.setenv("PATH", str(tools))
    assert module.public_environment()["PATH"] == str(tools)
    module.DEADLINE = time.monotonic() + 85
    data = copy.deepcopy(observed_healthy)
    data["public_gate"] = module.public_observations(str(work), data["baseline_tests"])
    assert data["public_gate"]["delivered"]["exit"] == 2
    assert "python3: No such file" in data["public_gate"]["delivered"]["output"]
    assert judge_module()._gate_green(data)["outcome"] == "UNKNOWN"
