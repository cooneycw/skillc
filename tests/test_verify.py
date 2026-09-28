"""Tests for independent grading and result assembly (#9).

Every case runs end to end: a real experiment planned by skillc/trial.py, a fake
subject that writes a slug candidate (and whatever else a hostile subject might
leave), a confirmed stop, a capture, and then `verify.grade` with the real
Level 1 grader. Each protection is shown refusing the input it exists for, beside
the input it must accept (ADR 0001).

The acceptance items of #9, and the case that proves each:

  known-good / known-bad output ....... test_a_correct_candidate_passes_and_a_wrong_one_fails
  forged prose / JSON / echo / framing  test_forged_success_claims_do_not_change_the_verdict
  modified local tests and grader ..... test_replaced_local_tests_and_grader_do_not_change_the_verdict
  verifier-output writes .............. test_a_forged_verdict_on_the_probe_channel_is_not_a_verdict,
                                        test_a_write_into_the_evidence_store_refuses_the_result,
                                        test_a_write_to_the_grader_definition_refuses_the_result,
                                        test_a_process_that_leaves_its_session_is_swept_before_the_judge
  evaluator credentials ............... test_candidate_code_does_not_inherit_the_evaluators_environment
                                        (and its limit: test_an_ancestors_environment_is_NOT_hidden)
  stale receipts, missing digests ..... test_*_receipt_*, test_*_pin_*, test_a_modified_artifact_is_not_graded
  broken graders ...................... test_a_grader_that_gives_no_verdict_stores_INCONCLUSIVE, ...
  deterministic regrading lineage ..... test_a_regrade_repeats_the_outcomes_and_keeps_the_original
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from skillc import cli, verify
from skillc import trial as t

HERE = Path(__file__).resolve().parent
FAKE = HERE / "fixtures" / "trial-subject" / "fake_subject.py"
TASK = HERE.parent / "evals" / "level1" / "slug-small-fix"
REFERENCE = TASK / "reference" / "src" / "slugify.py"
WRONG = TASK / "wrong" / "no-collapse" / "src" / "slugify.py"
GRADER = verify.GraderDef.load(TASK)

RECEIPT = json.loads((HERE.parent / "controls" / "installation-receipt" / "good" / "receipt.json")
                     .read_text(encoding="utf-8"))

#: A candidate body that is correct, for sources that add hostile behaviour to it.
CORRECT = REFERENCE.read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _no_quarantine_leaks() -> object:
    """A test that loses containment on purpose must not quarantine the next one."""
    verify.clear_quarantine()
    yield
    verify.clear_quarantine()


@pytest.fixture
def store(tmp_path: Path) -> Path:
    return t.open_store(tmp_path / "store", forbidden=[])


@pytest.fixture
def base(tmp_path: Path) -> Path:
    path = tmp_path / "work"
    path.mkdir()
    return path


@pytest.fixture
def grading(tmp_path: Path) -> Path:
    path = tmp_path / "grade"
    path.mkdir()
    return path


def _plan(store: Path, grader: dict[str, str] | None = None) -> tuple[t.Experiment, str]:
    spec: dict[str, object] = {"experiment": "verify", "trials": [{
        "label": "slug",
        "case": {"id": "slug-small-fix", "revision": "1"},
        "grader": grader if grader is not None else GRADER.identity(),
        "subject": {"digest": "sha256:5a"},
        "client": {"name": "fake", "version": "1"},
        "image": {"digest": "sha256:1a"},
        "config": {"model": "fake-1"},
        "attempts": 1,
    }]}
    experiment = t.plan(spec, store)
    [(_trial, attempt)] = list(experiment.attempts())
    return experiment, str(attempt["attempt_id"])


def _receipt(experiment: t.Experiment, attempt_id: str, **extra: object) -> dict[str, object]:
    return {**RECEIPT, "attempt_id": attempt_id, "trial_id": experiment.trial_of(attempt_id)["trial_id"],
            "client": {"name": "fake", "version": "1"}, **extra}


def _captured(store: Path, base: Path, source: Path, mode: str = "slug-from",
              grader: dict[str, str] | None = None, receipt: bool = True,
              **receipt_extra: object) -> tuple[t.Experiment, str]:
    """Plan, install, run the fake subject, confirm its stop, capture, finalize."""
    experiment, attempt_id = _plan(store, grader)
    if receipt:
        t.add_receipt(experiment, _receipt(experiment, attempt_id, **receipt_extra))
    workspace = t.allocate_workspace(experiment, attempt_id, base, forbidden=[])
    stop = t.run_attempt(experiment, attempt_id, [sys.executable, str(FAKE), mode, str(source)],
                         cwd=workspace, timeout=20, grace=0.5)
    assert stop["confirmed"] is True
    t.capture(experiment, attempt_id, workspace)
    t.cleanup_workspace(experiment, attempt_id)
    assert t.finalize(experiment, attempt_id)["disposition"] == "captured"
    return experiment, attempt_id


def _source(tmp_path: Path, body: str, name: str = "candidate.py") -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def _outcomes(result: dict[str, object]) -> dict[str, str]:
    criteria = result["criteria"]
    assert isinstance(criteria, list)
    return {c["id"]: c["outcome"] for c in criteria}


def _check_records(path: Path) -> int:
    return cli.cmd_check_records(argparse.Namespace(path=str(path), rule=None))


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:
        state = Path(f"/proc/{pid}/stat").read_text().split(")")[-1].split()[0]
    except OSError:
        return False
    return state != "Z"


def _wait_for(path: Path, seconds: float = 10) -> None:
    deadline = time.monotonic() + seconds
    while not path.exists() and time.monotonic() < deadline:
        time.sleep(0.02)


def _task_copy(tmp_path: Path, edit: Callable[[Path], None] | None = None) -> verify.GraderDef:
    root = tmp_path / "task"
    shutil.copytree(TASK, root, ignore=shutil.ignore_patterns("__pycache__"))
    if edit:
        edit(root)
    return verify.GraderDef.load(root)


# ---------------------------------------------------------- outcome controls


def test_a_correct_candidate_passes_and_a_wrong_one_fails(store: Path, base: Path, grading: Path,
                                                          tmp_path: Path) -> None:
    experiment, attempt_id = _captured(store, base, REFERENCE)
    good = verify.grade(experiment, attempt_id, GRADER, grading)
    assert good["status"] == "PASS"
    assert good["producer"] == "assembler"
    assert set(_outcomes(good)) == {*GRADER.criteria, verify.READINESS_CRITERION}
    assert _check_records(experiment.root) == 0

    experiment, attempt_id = _captured(t.open_store(tmp_path / "store2", forbidden=[]), base, WRONG)
    bad = verify.grade(experiment, attempt_id, GRADER, grading)
    assert bad["status"] == "FAIL"
    assert {k for k, v in _outcomes(bad).items() if v == "VIOLATED"} == {"reported-example", "R2"}
    assert _check_records(experiment.root) == 0


def test_the_status_is_derived_not_taken_from_the_judge(store: Path, base: Path, grading: Path,
                                                        tmp_path: Path) -> None:
    # A judge that says "status": "PASS" beside violated criteria: the claim is
    # dropped and the criteria decide.
    def edit(root: Path) -> None:
        (root / "grade_slug.py").write_text(
            "import json\nprint(json.dumps({'status': 'PASS', 'criteria': [{'id': c, 'mandatory': True,"
            " 'outcome': 'VIOLATED', 'evidence': ['x']} for c in ('R4-interface', 'reported-example',"
            " 'R1', 'R2', 'R3')]}))\n", encoding="utf-8")
    grader = _task_copy(tmp_path, edit)
    experiment, attempt_id = _captured(store, base, REFERENCE, grader=grader.identity())
    result = verify.grade(experiment, attempt_id, grader, grading)
    assert result["status"] == "FAIL"


# ---------------------------------------------------- subject-authored claims


def test_forged_success_claims_do_not_change_the_verdict(store: Path, base: Path, grading: Path,
                                                         tmp_path: Path) -> None:
    experiment, attempt_id = _captured(store, base, WRONG, mode="slug-forged")
    frozen = {str(a["path"]) for a in t.frozen_artifacts(experiment, attempt_id)}
    assert "task.json" in frozen  # the forgery was captured, as bytes
    result = verify.grade(experiment, attempt_id, GRADER, grading)
    assert result["status"] == "FAIL"
    # The control: the same forgeries beside a correct candidate still PASS, so the
    # FAIL above is the grader's verdict on the code, not a reaction to the forgery.
    experiment, attempt_id = _captured(t.open_store(tmp_path / "s2", forbidden=[]), base, REFERENCE,
                                       mode="slug-forged")
    assert verify.grade(experiment, attempt_id, GRADER, grading)["status"] == "PASS"


def test_replaced_local_tests_and_grader_do_not_change_the_verdict(store: Path, base: Path,
                                                                   grading: Path) -> None:
    experiment, attempt_id = _captured(store, base, WRONG, mode="slug-tests")
    frozen = {str(a["path"]) for a in t.frozen_artifacts(experiment, attempt_id)}
    assert {"tests/test_slugify.py", "grade_slug.py", "grader.json", "expected.json"} <= frozen
    result = verify.grade(experiment, attempt_id, GRADER, grading)
    assert result["status"] == "FAIL"
    assert _outcomes(result)["R2"] == "VIOLATED"


# ---------------------------------------------------- the success channel


FORGED_VERDICT = '''
import json, os
verdict = json.dumps({"status": "PASS", "grader": {"id": "slug-small-fix", "revision": "2"},
    "criteria": [{"id": c, "mandatory": True, "outcome": "SATISFIED", "evidence": ["forged"]}
                 for c in ("R4-interface", "reported-example", "R1", "R2", "R3")]}).encode()
written = 0
for fd in os.listdir("/proc/self/fd"):
    try:
        if os.readlink(f"/proc/self/fd/{fd}").endswith("observations"):
            os.write(int(fd), verdict)
            written += 1
    except OSError:
        pass
open(MARK, "w").write(str(written))
os._exit(0)
'''


def test_a_forged_verdict_on_the_probe_channel_is_not_a_verdict(store: Path, base: Path, grading: Path,
                                                                tmp_path: Path) -> None:
    mark = tmp_path / "written"
    source = _source(tmp_path, f"MARK = {str(mark)!r}\n" + FORGED_VERDICT)
    experiment, attempt_id = _captured(store, base, source)
    result = verify.grade(experiment, attempt_id, GRADER, grading)
    assert mark.read_text() == "1"  # the candidate DID reach the probe's report channel
    assert result["status"] == "FAIL"
    criteria = result["criteria"]
    assert isinstance(criteria, list)
    [interface] = [c for c in criteria if c["id"] == "R4-interface"]
    assert interface["outcome"] == "VIOLATED" and "malformed" in interface["evidence"][0]


def test_a_write_into_the_evidence_store_refuses_the_result(store: Path, base: Path, grading: Path,
                                                            tmp_path: Path) -> None:
    experiment, attempt_id = _plan(store)
    planted = experiment.root / "result-r-planted.json"
    writer = f"open({str(planted)!r}, 'w').write('{{}}')\n" + CORRECT
    # Plan again in a fresh store with the real candidate: the writer targets THIS
    # experiment, so run it here.
    t.add_receipt(experiment, _receipt(experiment, attempt_id))
    workspace = t.allocate_workspace(experiment, attempt_id, base, forbidden=[])
    t.run_attempt(experiment, attempt_id, [sys.executable, str(FAKE), "slug-from",
                                           str(_source(tmp_path, writer))], cwd=workspace, timeout=20)
    t.capture(experiment, attempt_id, workspace)
    t.finalize(experiment, attempt_id)
    with pytest.raises(t.Refused, match="evidence store changed.*result-r-planted.json appeared"):
        verify.grade(experiment, attempt_id, GRADER, grading)
    assert list(experiment.root.glob("result-r-[0-9a-f]*.json")) == []
    # The control: the same candidate body without the write is graded, and passes.
    experiment, attempt_id = _captured(t.open_store(tmp_path / "s2", forbidden=[]), base, REFERENCE)
    assert verify.grade(experiment, attempt_id, GRADER, grading)["status"] == "PASS"


def test_a_write_to_the_ledger_refuses_the_result(store: Path, base: Path, grading: Path,
                                                  tmp_path: Path) -> None:
    experiment, attempt_id = _plan(store)
    ledger = experiment.root / t.LEDGER
    writer = (f"import os\nos.chmod({str(ledger)!r}, 0o600)\n"
              f"open({str(ledger)!r}, 'a').write(' ')\n" + CORRECT)
    t.add_receipt(experiment, _receipt(experiment, attempt_id))
    workspace = t.allocate_workspace(experiment, attempt_id, base, forbidden=[])
    t.run_attempt(experiment, attempt_id, [sys.executable, str(FAKE), "slug-from",
                                           str(_source(tmp_path, writer))], cwd=workspace, timeout=20)
    t.capture(experiment, attempt_id, workspace)
    t.finalize(experiment, attempt_id)
    with pytest.raises(t.Refused, match="evidence store changed.*ledger.json changed"):
        verify.grade(experiment, attempt_id, GRADER, grading)


def test_a_write_to_the_grader_definition_refuses_the_result(store: Path, base: Path, grading: Path,
                                                             tmp_path: Path) -> None:
    grader = _task_copy(tmp_path)
    writer = f"open({str(grader.judge)!r}, 'a').write('# edited\\n')\n" + CORRECT
    experiment, attempt_id = _captured(store, base, _source(tmp_path, writer), grader=grader.identity())
    with pytest.raises(t.Refused, match="grader definition changed while it was grading"):
        verify.grade(experiment, attempt_id, grader, grading)


ESCAPER = '''
import os, subprocess, sys, time
loop = ("import os, time\\n"
        "open(%r, 'w').write(f'{os.getpid()} {os.getsid(0)}')\\n"
        "while True:\\n    time.sleep(0.05)\\n") % (PIDFILE + ".tmp",)
subprocess.Popen([sys.executable, "-c", loop], start_new_session=True,
                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
deadline = time.monotonic() + 10
while not os.path.exists(PIDFILE + ".tmp") and time.monotonic() < deadline:
    time.sleep(0.02)
time.sleep(0.1)
os.rename(PIDFILE + ".tmp", PIDFILE)
'''


def test_a_process_that_leaves_its_session_is_swept_before_the_judge(store: Path, base: Path,
                                                                     grading: Path, tmp_path: Path) -> None:
    # trial.run_attempt cannot see a process that calls setsid (#8 pins that). The
    # verifier's supervisor is a child subreaper, so this one stays its child and is
    # killed before the judge starts.
    pidfile = tmp_path / "escaped.pid"
    source = _source(tmp_path, f"PIDFILE = {str(pidfile)!r}\n" + ESCAPER + CORRECT)
    experiment, attempt_id = _plan(store)
    t.add_receipt(experiment, _receipt(experiment, attempt_id))
    workspace = t.allocate_workspace(experiment, attempt_id, base, forbidden=[])
    # The subject writes the source; it does not import it, so nothing escapes yet.
    t.run_attempt(experiment, attempt_id, [sys.executable, str(FAKE), "slug-from", str(source)],
                  cwd=workspace, timeout=20)
    t.capture(experiment, attempt_id, workspace)
    t.finalize(experiment, attempt_id)
    assert not pidfile.exists()

    result = verify.grade(experiment, attempt_id, GRADER, grading)
    _wait_for(pidfile)
    pid, sid = map(int, pidfile.read_text().split())
    assert sid == pid  # it led its own session: outside any process group the probe had
    assert not _alive(pid)
    verification = result["verification"]
    assert isinstance(verification, dict)
    assert verification["containment"]["confirmed"] is True
    assert result["status"] == "PASS"


def test_killing_the_supervisor_is_INCONCLUSIVE_never_a_verdict(store: Path, base: Path, grading: Path,
                                                                tmp_path: Path) -> None:
    killer = "import os, signal\nos.kill(os.getppid(), signal.SIGKILL)\n" + CORRECT
    experiment, attempt_id = _captured(store, base, _source(tmp_path, killer))
    result = verify.grade(experiment, attempt_id, GRADER, grading)
    assert result["status"] == "INCONCLUSIVE"
    verification = result["verification"]
    assert isinstance(verification, dict)
    assert verification["category"] == "containment"
    assert verification["containment"]["confirmed"] is False
    assert all(o == "UNKNOWN" for k, o in _outcomes(result).items() if k != verify.READINESS_CRITERION)


def test_candidate_code_does_not_inherit_the_evaluators_environment(store: Path, base: Path, grading: Path,
                                                              tmp_path: Path,
                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SKILLC_EVALUATOR_TOKEN", "evaluator-secret-value")
    dump = tmp_path / "env.json"
    writer = f"import json, os\nopen({str(dump)!r}, 'w').write(json.dumps(dict(os.environ)))\n" + CORRECT
    experiment, attempt_id = _captured(store, base, _source(tmp_path, writer))
    verify.grade(experiment, attempt_id, GRADER, grading)
    seen = json.loads(dump.read_text())
    assert "PATH" in seen  # the dump is real: the candidate ran and wrote it
    assert "SKILLC_EVALUATOR_TOKEN" not in seen
    assert "evaluator-secret-value" not in dump.read_text()
    assert Path(seen["HOME"]).name == "home" and not Path(seen["HOME"]).exists()  # disposable, gone


def test_a_hanging_candidate_is_a_violation_after_a_confirmed_sweep(store: Path, base: Path, grading: Path,
                                                                    tmp_path: Path) -> None:
    def edit(root: Path) -> None:
        data = json.loads((root / "grader.json").read_text())
        data["probe"]["timeout"] = 2
        (root / "grader.json").write_text(json.dumps(data))
    grader = _task_copy(tmp_path, edit)
    hang = "while True:\n    pass\n"
    experiment, attempt_id = _captured(store, base, _source(tmp_path, hang), grader=grader.identity())
    result = verify.grade(experiment, attempt_id, grader, grading)
    assert result["status"] == "FAIL"
    assert _outcomes(result)["R4-interface"] == "VIOLATED"
    verification = result["verification"]
    assert isinstance(verification, dict)
    assert verification["containment"]["timed_out"] is True


# ---------------------------------------------------- receipts and digests


def test_an_attempt_without_a_receipt_is_not_graded(store: Path, base: Path, grading: Path) -> None:
    experiment, attempt_id = _captured(store, base, REFERENCE, receipt=False)
    with pytest.raises(t.Refused, match="no installation receipt"):
        verify.grade(experiment, attempt_id, GRADER, grading)


def test_a_stale_receipt_is_not_graded(store: Path, base: Path, grading: Path) -> None:
    experiment, attempt_id = _captured(store, base, REFERENCE, receipt=False)
    # Admission refuses a stale receipt (#8), so plant one the way an intruder would.
    stale = _receipt(experiment, attempt_id, subject={**RECEIPT["subject"], "digest": "sha256:0ld"})
    (experiment.root / f"receipt-{attempt_id}.json").write_text(json.dumps(stale))
    with pytest.raises(t.Refused, match="stale receipt"):
        verify.grade(experiment, attempt_id, GRADER, grading)


def test_a_ledger_without_a_grader_pin_is_refused_not_trusted(store: Path, base: Path, grading: Path) -> None:
    unpinned = {"id": GRADER.id, "revision": GRADER.revision}
    experiment, attempt_id = _captured(store, base, REFERENCE, grader=unpinned)
    with pytest.raises(t.Refused, match="pins no grader digest"):
        verify.grade(experiment, attempt_id, GRADER, grading)


def test_a_grader_that_is_not_the_pinned_one_is_refused(store: Path, base: Path, grading: Path) -> None:
    experiment, attempt_id = _captured(store, base, REFERENCE, grader={**GRADER.identity(), "digest": "sha256:00"})
    with pytest.raises(t.Refused, match="does not match the digest the ledger pinned"):
        verify.grade(experiment, attempt_id, GRADER, grading)


def test_a_modified_artifact_is_not_graded(store: Path, base: Path, grading: Path) -> None:
    experiment, attempt_id = _captured(store, base, REFERENCE)
    [source] = [a for a in t.frozen_artifacts(experiment, attempt_id) if a["path"] == "src/slugify.py"]
    obj = experiment.object_path(str(source["digest"]))
    obj.chmod(0o600)
    obj.write_bytes(obj.read_bytes() + b"\n")
    with pytest.raises(t.Refused, match="modified"):
        verify.grade(experiment, attempt_id, GRADER, grading)


def test_an_uncaptured_attempt_is_not_graded(store: Path, grading: Path) -> None:
    experiment, attempt_id = _plan(store)
    t.close(experiment)
    with pytest.raises(t.Refused, match="not a finalized capture"):
        verify.grade(experiment, attempt_id, GRADER, grading)


def test_readiness_that_is_not_established_prevents_PASS_but_not_FAIL(store: Path, base: Path, grading: Path,
                                                                     tmp_path: Path) -> None:
    unready = {"discovery_canary": "VIOLATED", "baseline_absence": "SATISFIED"}
    experiment, attempt_id = _captured(store, base, REFERENCE, readiness=unready)
    result = verify.grade(experiment, attempt_id, GRADER, grading)
    assert result["status"] == "INCONCLUSIVE"
    assert _outcomes(result)[verify.READINESS_CRITERION] == "UNKNOWN"
    experiment, attempt_id = _captured(t.open_store(tmp_path / "s2", forbidden=[]), base, WRONG,
                                       readiness=unready)
    assert verify.grade(experiment, attempt_id, GRADER, grading)["status"] == "FAIL"


# ---------------------------------------------------- broken graders


@pytest.mark.parametrize(("control", "category"), [("crash", "exit-nonzero"), ("no_output", "no-output"),
                                                    ("omits_criterion", "criteria-set")])
def test_a_grader_that_gives_no_verdict_stores_INCONCLUSIVE(store: Path, base: Path, grading: Path,
                                                            control: str, category: str) -> None:
    grader = GRADER.with_judge(TASK / "grader-controls" / f"{control}.py")
    experiment, attempt_id = _captured(store, base, WRONG, grader=grader.identity())
    result = verify.grade(experiment, attempt_id, grader, grading)
    # Not FAIL: a grader that said nothing did not detect the wrong candidate.
    assert result["status"] == "INCONCLUSIVE"
    verification = result["verification"]
    assert isinstance(verification, dict) and verification["category"] == category
    assert {o for k, o in _outcomes(result).items() if k != verify.READINESS_CRITERION} == {"UNKNOWN"}
    assert _check_records(experiment.root) == 0


def test_blind_graders_are_the_certification_gates_to_catch(store: Path, base: Path, grading: Path,
                                                             tmp_path: Path) -> None:
    # The verifier cannot tell a blind grader from a working one on one candidate:
    # always_pass passes a wrong candidate and always_fail fails a correct one. That
    # is why the ledger pins a digest and qualify.py certifies the grader first;
    # tests/test_level1_slug.py shows qualify refusing both through this same path.
    always_pass = GRADER.with_judge(TASK / "grader-controls" / "always_pass.py")
    experiment, attempt_id = _captured(store, base, WRONG, grader=always_pass.identity())
    assert verify.grade(experiment, attempt_id, always_pass, grading)["status"] == "PASS"
    always_fail = GRADER.with_judge(TASK / "grader-controls" / "always_fail.py")
    experiment, attempt_id = _captured(t.open_store(tmp_path / "s2", forbidden=[]), base, REFERENCE,
                                       grader=always_fail.identity())
    assert verify.grade(experiment, attempt_id, always_fail, grading)["status"] == "FAIL"
    # And a control's digest is not the certified grader's, so a ledger pinned to
    # the real grader refuses to grade with it.
    assert always_pass.digest() != GRADER.digest()


# ---------------------------------------------------- regrading


def test_a_regrade_repeats_the_outcomes_and_keeps_the_original(store: Path, base: Path, grading: Path) -> None:
    experiment, attempt_id = _captured(store, base, WRONG)
    first = verify.grade(experiment, attempt_id, GRADER, grading)
    second = verify.regrade(experiment, str(first["result_id"]), GRADER, grading)
    assert second["regrade_of"] == first["result_id"]
    assert second["result_id"] != first["result_id"]
    assert second["criteria"] == first["criteria"]
    assert second["graded_digests"] == first["graded_digests"]
    assert (experiment.root / f"result-{first['result_id']}.json").exists()
    assert _check_records(experiment.root) == 0
    # A regrade with a different grader is not a regrade of this pinned one.
    with pytest.raises(t.Refused, match="pinned"):
        verify.regrade(experiment, str(first["result_id"]),
                       GRADER.with_judge(TASK / "grader-controls" / "always_pass.py"), grading)


_OBSERVED = json.loads((Path(__file__).resolve().parent.parent / "controls" / "agent-observation" / "good"
                        / "observed.json").read_text(encoding="utf-8"))
_CONFIRMED = {"status": "observed", "prompt_delivered": True, "canary_satisfied": True, "grading_eligible": True}


def test_an_agent_attempt_is_graded_on_its_observation_and_never_readied_by_it(
        store: Path, base: Path, grading: Path) -> None:
    """#139: no receipt, the observation stands in - and readiness is UNKNOWN
    (owner decision B1), so a task PASS is stored as INCONCLUSIVE."""
    experiment, attempt_id = _captured(store, base, REFERENCE, receipt=False)
    result, graded = verify.grade_agent_attempt(experiment, attempt_id, GRADER, grading, _CONFIRMED)
    assert graded.status == "PASS"
    assert result["status"] == "INCONCLUSIVE"
    assert _outcomes(result)[verify.READINESS_CRITERION] == "UNKNOWN"
    assert result["verification"]["readiness_source"] == "agent-observation"  # type: ignore[index]
    assert (experiment.root / f"result-{result['result_id']}.json").is_file()


@pytest.mark.parametrize("observation", [
    {**_CONFIRMED, "canary_satisfied": False, "grading_eligible": False},
    {**_CONFIRMED, "prompt_delivered": False, "grading_eligible": False},
    {**_CONFIRMED, "grading_eligible": False},
    {"status": "unknown", "reason": "hook failed"},
    {},
])
def test_an_unconfirmed_observation_stands_in_for_nothing(
        observation: dict[str, object], store: Path, base: Path, grading: Path) -> None:
    experiment, attempt_id = _captured(store, base, REFERENCE, receipt=False)
    with pytest.raises(verify.Refused):
        verify.grade_agent_attempt(experiment, attempt_id, GRADER, grading, observation)
    assert not list(experiment.root.glob("result-*.json"))


def test_an_agent_result_is_never_regraded_on_the_bare_host(store: Path, base: Path, grading: Path) -> None:
    """Codex re-review, red before the fix: an agent result's regrade took the
    bare-subprocess path, running agent-written code on the host that the
    original grade ran in a separate backend. With no backend it is refused
    BEFORE any candidate code runs - no new result is stored."""
    experiment, attempt_id = _captured(store, base, REFERENCE, receipt=False)
    original, _graded = verify.grade_agent_attempt(experiment, attempt_id, GRADER, grading, _CONFIRMED)
    (experiment.root / verify.observation_record_name(attempt_id)).write_text(json.dumps(
        {**_OBSERVED, "attempt_id": attempt_id, "trial_id": experiment.trial_of(attempt_id)["trial_id"]},
    ), encoding="utf-8")
    with pytest.raises(verify.Refused, match="explicit grading backend"):
        verify.regrade(experiment, str(original["result_id"]), GRADER, grading)
    assert len(list(experiment.root.glob("result-*.json"))) == 1


def test_a_regrade_of_nothing_stored_is_refused(store: Path, grading: Path) -> None:
    experiment, _attempt_id = _plan(store)
    with pytest.raises(t.Refused, match="no stored result"):
        verify.regrade(experiment, "r-missing", GRADER, grading)


# ---------------------------------------------------- the grader definition


def test_the_committed_grader_definition_loads_and_pins(tmp_path: Path) -> None:
    assert GRADER.criteria == ("R4-interface", "reported-example", "R1", "R2", "R3")
    assert GRADER.identity()["digest"].startswith("sha256:")
    def edit(root: Path) -> None:
        (root / "inputs.json").write_text("[]")
    edited = _task_copy(tmp_path, edit)
    assert edited.digest() != GRADER.digest()  # the inputs are inside the pin


@pytest.mark.parametrize("change", [
    {"extra": 1},
    {"criteria": []},
    {"criteria": ["R1", "R1"]},
    {"criteria": ["installation-ready"]},
    {"probe": {"file": "../probe.py", "inputs": "inputs.json", "timeout": 30}},
    {"probe": {"file": "probe.py", "inputs": "inputs.json", "timeout": True}},
    {"judge": {"file": "grade_slug.py", "timeout": 60, "argv": ["sh"]}},
])
def test_a_loose_grader_definition_is_refused(tmp_path: Path, change: dict[str, object]) -> None:
    def edit(root: Path) -> None:
        data = json.loads((root / "grader.json").read_text())
        (root / "grader.json").write_text(json.dumps({**data, **change}))
    with pytest.raises(t.Refused):
        _task_copy(tmp_path, edit)


def test_a_grader_file_that_is_a_link_is_refused(tmp_path: Path) -> None:
    def edit(root: Path) -> None:
        (root / "grade_slug.py").unlink()
        (root / "grade_slug.py").symlink_to(TASK / "grade_slug.py")
    with pytest.raises(t.Refused):
        _task_copy(tmp_path, edit)


def test_an_artifact_path_that_climbs_out_is_refused(grading: Path) -> None:
    with pytest.raises(t.Refused, match="could leave"):
        verify.grade_files(GRADER, [("../escape.py", b"x", False)], grading)


def test_an_empty_candidate_is_refused(grading: Path) -> None:
    with pytest.raises(t.Refused, match="empty"):
        verify.grade_files(GRADER, [], grading)


SELF_RESTORING = '''
import os, shutil
judge = JUDGE
shutil.copy2(judge, judge + ".orig")
always = ("import json, os, shutil\\n"
          "shutil.move(%r, %r)\\n"
          "print(json.dumps({'criteria': [{'id': c, 'mandatory': True, 'outcome': 'SATISFIED', "
          "'evidence': ['forged']} for c in ('R4-interface', 'reported-example', 'R1', 'R2', 'R3')]}))\\n"
          ) % (judge + ".orig", judge)
os.chmod(judge, 0o600)
open(judge, "w").write(always)
'''


def test_a_self_restoring_judge_is_never_what_runs(store: Path, base: Path, grading: Path,
                                                  tmp_path: Path) -> None:
    # Codex review: the candidate swaps in a judge that prints PASS and puts the
    # real one back. Were the judge re-read from disk after the probe, it would run,
    # restore the file, and the post-grading digest check would match. The verifier
    # runs the bytes it pinned before any candidate code, so the wrong candidate FAILs.
    grader = _task_copy(tmp_path)
    body = f"JUDGE = {str(grader.judge)!r}\n" + SELF_RESTORING + WRONG.read_text(encoding="utf-8")
    experiment, attempt_id = _captured(store, base, _source(tmp_path, body), grader=grader.identity())
    with pytest.raises(t.Refused, match="grader definition changed"):
        verify.grade(experiment, attempt_id, grader, grading)
    # The swapped judge never ran: had it, it would have restored the original.
    assert "forged" in grader.judge.read_text()


def test_a_fifo_in_place_of_the_report_does_not_hang_the_verifier(store: Path, base: Path, grading: Path,
                                                                 tmp_path: Path) -> None:
    fifo = ("import os\n"
            "path = os.path.join(os.path.dirname(os.getcwd()), 'observations')\n"
            "os.unlink(path)\nos.mkfifo(path)\nos._exit(0)\n")
    experiment, attempt_id = _captured(store, base, _source(tmp_path, fifo))
    result = verify.grade(experiment, attempt_id, GRADER, grading)
    assert result["status"] == "FAIL"
    assert _outcomes(result)["R4-interface"] == "VIOLATED"


STAYS_ALIVE = '''
import os, signal, time
if os.fork() == 0:
    open(PIDFILE + ".tmp", "w").write(str(os.getpid()))
    os.rename(PIDFILE + ".tmp", PIDFILE)
    while True:
        time.sleep(0.05)
deadline = time.monotonic() + 10
while not os.path.exists(PIDFILE) and time.monotonic() < deadline:
    time.sleep(0.02)
os.kill(os.getppid(), signal.SIGKILL)
'''


def test_a_candidate_that_kills_the_supervisor_and_stays_alive_is_killed_and_quarantines(
        store: Path, base: Path, grading: Path, tmp_path: Path) -> None:
    pidfile = tmp_path / "survivor.pid"
    body = f"PIDFILE = {str(pidfile)!r}\n" + STAYS_ALIVE + CORRECT
    experiment, attempt_id = _captured(store, base, _source(tmp_path, body))
    result = verify.grade(experiment, attempt_id, GRADER, grading)
    assert result["status"] == "INCONCLUSIVE"
    verification = result["verification"]
    assert isinstance(verification, dict)
    assert verification["containment"]["fallback_killed"] >= 1
    pid = int(pidfile.read_text())
    deadline = time.monotonic() + 5
    while _alive(pid) and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not _alive(pid)
    # Nothing established that EVERY process is gone, so grading stops until an
    # operator says otherwise.
    with pytest.raises(t.Refused, match="quarantined"):
        verify.grade_directory(GRADER, TASK / "reference", grading)
    verify.clear_quarantine()
    assert verify.grade_directory(GRADER, TASK / "reference", grading).status == "PASS"


ANCESTORS = '''
import os
found, pid = False, os.getpid()
while pid > 1:
    try:
        stat = open(f"/proc/{pid}/stat", "rb").read()
        pid = int(stat[stat.rfind(b")") + 2:].split()[1])
        if b"SKILLC_EVALUATOR_TOKEN=" in open(f"/proc/{pid}/environ", "rb").read():
            found = True
            break
    except OSError:
        break
open(MARK, "w").write("found" if found else "hidden")
'''


def test_an_ancestors_environment_is_NOT_hidden(store: Path, base: Path, grading: Path, tmp_path: Path,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    """Pins a LIMIT, as #8 pins the setsid one. The verifier does not hand its
    environment to candidate code, but same-user code can read an ancestor's
    through /proc. Confidentiality needs a separate user: the Docker lane (#10).
    If this ever reports "hidden", the host added a boundary; update the docs."""
    mark = tmp_path / "ancestors"
    # The token must be in the environment the verifier's ANCESTORS started with,
    # so run the grading in a child process that carries it from birth.
    monkeypatch.setenv("SKILLC_EVALUATOR_TOKEN", "evaluator-secret-value")
    body = f"MARK = {str(mark)!r}\n" + ANCESTORS + CORRECT
    experiment, attempt_id = _captured(store, base, _source(tmp_path, body))
    script = (
        "import sys; from pathlib import Path; from skillc import verify, trial\n"
        f"e = trial.Experiment.open(Path({str(experiment.root)!r}))\n"
        f"verify.grade(e, {attempt_id!r}, verify.GraderDef.load(Path({str(TASK)!r})), Path({str(grading)!r}))\n"
    )
    import subprocess
    subprocess.run([sys.executable, "-c", script], check=True, env=dict(os.environ))
    if not mark.exists():
        pytest.skip("the candidate could not report; /proc is not readable here")
    assert mark.read_text() == "found"


def test_a_change_to_the_definition_file_alone_refuses_the_result(store: Path, base: Path, grading: Path,
                                                                  tmp_path: Path) -> None:
    # Counter-model re-review: the pin once covered only the three files grader.json
    # names, so rewriting grader.json itself went unnoticed.
    grader = _task_copy(tmp_path)
    definition = grader.root / verify.GRADER_FILE
    writer = (f"import os\nos.chmod({str(definition)!r}, 0o600)\n"
              f"open({str(definition)!r}, 'w').write('{{}}')\n" + CORRECT)
    experiment, attempt_id = _captured(store, base, _source(tmp_path, writer), grader=grader.identity())
    with pytest.raises(t.Refused, match="grader definition changed"):
        verify.grade(experiment, attempt_id, grader, grading)


def test_the_pin_covers_the_names_of_the_files_it_runs(tmp_path: Path) -> None:
    renamed = tmp_path / "judge_copy.py"
    shutil.copy2(GRADER.judge, renamed)
    assert GRADER.with_judge(renamed).digest() != GRADER.digest()


def test_a_fifo_in_place_of_the_judge_file_is_refused_not_waited_on(store: Path, base: Path, grading: Path,
                                                                    tmp_path: Path) -> None:
    # Counter-model re-review: the post-grading re-read of the grader files opened
    # without O_NONBLOCK, so a FIFO planted there hung the verifier after every
    # deadline had passed.
    grader = _task_copy(tmp_path)
    writer = f"import os\nos.unlink({str(grader.judge)!r})\nos.mkfifo({str(grader.judge)!r})\n" + CORRECT
    experiment, attempt_id = _captured(store, base, _source(tmp_path, writer), grader=grader.identity())
    with pytest.raises(t.Refused, match="not a (readable )?regular file"):
        verify.grade(experiment, attempt_id, grader, grading)


def test_a_fifo_in_place_of_the_ownership_marker_does_not_hang_cleanup(store: Path, base: Path, grading: Path,
                                                                       tmp_path: Path) -> None:
    marker = ("import os\n"
              "path = os.path.join(os.path.dirname(os.path.dirname(os.getcwd())), '.skillc-owned')\n"
              "os.unlink(path)\nos.mkfifo(path)\n") + CORRECT
    experiment, attempt_id = _captured(store, base, _source(tmp_path, marker))
    result = verify.grade(experiment, attempt_id, GRADER, grading)
    verification = result["verification"]
    assert isinstance(verification, dict)
    # Not removed - the marker no longer proves ownership - but recorded, not hung.
    assert verification["containment"]["cleanup"] == "refused-not-owned"
    assert result["status"] == "PASS"


def test_grading_inside_the_evidence_store_is_refused(store: Path, base: Path) -> None:
    experiment, attempt_id = _captured(store, base, REFERENCE)
    with pytest.raises(t.Refused, match="inside the evidence store"):
        verify.grade(experiment, attempt_id, GRADER, store / "grading")


@pytest.mark.parametrize(("body", "category"), [
    ("import time\ntime.sleep(30)\n", "timeout"),
    ("print('not json')\n", "unparseable"),
    ("print('[]')\n", "unparseable"),
])
def test_a_judge_that_hangs_or_prints_no_object_is_INCONCLUSIVE(tmp_path: Path, grading: Path,
                                                                 body: str, category: str) -> None:
    def edit(root: Path) -> None:
        data = json.loads((root / "grader.json").read_text())
        data["judge"]["timeout"] = 1
        (root / "grader.json").write_text(json.dumps(data))
        (root / "grade_slug.py").write_text(body)
    graded = verify.grade_directory(_task_copy(tmp_path, edit), TASK / "wrong" / "no-collapse", grading)
    assert (graded.status, graded.category) == ("INCONCLUSIVE", category)


# ----------------------------------------------- concurrent attempts (#12)


def _plan_two(store: Path) -> tuple[t.Experiment, str, str]:
    spec: dict[str, object] = {"experiment": "verify", "trials": [{
        "label": "slug", "case": {"id": "slug-small-fix", "revision": "1"}, "grader": GRADER.identity(),
        "subject": {"digest": "sha256:5a"}, "client": {"name": "fake", "version": "1"},
        "image": {"digest": "sha256:1a"}, "config": {"model": "fake-1"}, "attempts": 2,
    }]}
    experiment = t.plan(spec, store)
    first, second = (str(a["attempt_id"]) for _trial, a in experiment.attempts())
    return experiment, first, second


def _run(experiment: t.Experiment, attempt_id: str, base: Path, source: Path) -> Path:
    t.add_receipt(experiment, _receipt(experiment, attempt_id))
    workspace = t.allocate_workspace(experiment, attempt_id, base, forbidden=[])
    stop = t.run_attempt(experiment, attempt_id, [sys.executable, str(FAKE), "slug-from", str(source)],
                         cwd=workspace, timeout=20, grace=0.5)
    assert stop["confirmed"] is True
    return workspace


def _freeze(experiment: t.Experiment, attempt_id: str, workspace: Path) -> None:
    t.capture(experiment, attempt_id, workspace)
    t.cleanup_workspace(experiment, attempt_id)
    assert t.finalize(experiment, attempt_id)["disposition"] == "captured"


def test_a_sibling_that_runs_and_is_captured_mid_grade_does_not_refuse_the_grade(
    store: Path, base: Path, grading: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The red case #12 names: attempt A is graded while sibling B runs (its
    journal and spool grow) and is then captured. Before #12 A's grade was
    refused as tampering; now B's run is scoped out of A's snapshot and B's
    capture waits for the experiment lock A's grade holds."""
    import threading

    experiment, first, second = _plan_two(store)
    _freeze(experiment, first, _run(experiment, first, base, REFERENCE))
    t.add_receipt(experiment, _receipt(experiment, second))
    sibling: dict[str, object] = {}
    ran = threading.Event()
    real_grade_files = verify.grade_files

    def sibling_b() -> None:
        # A separate thread, as a real sibling controller is: nothing it does
        # shares the grading thread's hold on the lock.
        workspace = t.allocate_workspace(experiment, second, base, forbidden=[])
        t.run_attempt(experiment, second, [sys.executable, str(FAKE), "slug-from", str(REFERENCE)],
                      cwd=workspace, timeout=20, grace=0.5)
        ran.set()  # B's journal and spool changed mid-grade
        _freeze(experiment, second, workspace)
        sibling["done_at"] = time.monotonic()

    def during_grade(*args: object, **kwargs: object) -> verify.Graded:
        graded = real_grade_files(*args, **kwargs)  # type: ignore[arg-type]
        thread = threading.Thread(target=sibling_b)
        thread.start()
        sibling["thread"] = thread
        assert ran.wait(timeout=30)
        time.sleep(0.5)  # long enough for an unlocked capture to land mid-grade
        sibling["grade_returning_at"] = time.monotonic()
        return graded

    monkeypatch.setattr(verify, "grade_files", during_grade)
    result = verify.grade(experiment, first, GRADER, grading)
    thread = sibling["thread"]
    assert isinstance(thread, threading.Thread)
    thread.join(timeout=30)
    assert result["status"] == "PASS"
    # B waited for A's grade to store its result, and was then captured normally.
    assert isinstance(sibling.get("done_at"), float)
    assert sibling["done_at"] > sibling["grade_returning_at"]  # type: ignore[operator]
    assert (experiment.root / f"lifecycle-{second}.json").exists()


def _graded_with_write(store: Path, base: Path, grading: Path, tmp_path: Path,
                       target: Callable[[t.Experiment, str, str], Path],
                       finish_sibling: bool) -> tuple[t.Experiment, str]:
    """Attempt A's candidate appends to `target` while it is graded. B is
    captured first when `finish_sibling`, otherwise left planned and unrun."""
    experiment, first, second = _plan_two(store)
    if finish_sibling:
        _freeze(experiment, second, _run(experiment, second, base, REFERENCE))
    path = target(experiment, first, second)
    writer = (f"import os\np = {str(path)!r}\n"
              "if os.path.exists(p): os.chmod(p, 0o600)\n"
              "open(p, 'a').write('x')\n" + CORRECT)
    _freeze(experiment, first, _run(experiment, first, base, _source(tmp_path, writer)))
    return experiment, first


def test_a_write_into_an_unfinished_siblings_spool_is_the_one_thing_scoped_out(
    store: Path, base: Path, grading: Path, tmp_path: Path,
) -> None:
    """The stated narrowing, pinned so it cannot silently grow: an unfinished
    planned sibling's spool is not compared by this grade."""
    experiment, first = _graded_with_write(
        store, base, grading, tmp_path,
        lambda e, _a, b: e.root / t.SPOOL / f"{b}.stdout", finish_sibling=False)
    assert verify.grade(experiment, first, GRADER, grading)["status"] == "PASS"


@pytest.mark.parametrize(("where", "finish_sibling"), [
    ("finished-sibling-journal", True),
    ("own-journal", False),
    ("unplanned-journal", False),
    ("object", False),
])
def test_every_other_write_still_refuses_the_grade(
    store: Path, base: Path, grading: Path, tmp_path: Path, where: str, finish_sibling: bool,
) -> None:
    """The negative controls for the narrowing: a finalized sibling, this
    attempt's own journal, an attempt the ledger does not plan, and the object
    store are all still compared."""
    targets: dict[str, Callable[[t.Experiment, str, str], Path]] = {
        "finished-sibling-journal": lambda e, _a, b: e.root / t.JOURNAL / f"{b}.jsonl",
        "own-journal": lambda e, a, _b: e.root / t.JOURNAL / f"{a}.jsonl",
        "unplanned-journal": lambda e, _a, _b: e.root / t.JOURNAL / "a-000000000000beef.jsonl",
        "object": lambda e, _a, _b: e.root / t.OBJECTS / "planted",
    }
    experiment, first = _graded_with_write(store, base, grading, tmp_path, targets[where], finish_sibling)
    with pytest.raises(t.Refused, match="evidence store changed"):
        verify.grade(experiment, first, GRADER, grading)


def test_the_experiment_lock_excludes_another_process(store: Path) -> None:
    """`flock` across processes, not only the in-process re-entrant hold: a
    child holding the lock makes this process wait; a different experiment's
    lock does not."""
    import subprocess

    experiment, _attempt = _plan(store)
    other, _other_attempt = _plan(t.open_store(store.parent / "other-store", forbidden=[]))
    holder = subprocess.Popen(
        [sys.executable, "-c",
         ("import sys, time\nfrom pathlib import Path\nfrom skillc import trial\n"
          "with trial.experiment_lock(Path(sys.argv[1])):\n"
          "    print('held', flush=True)\n    time.sleep(1.5)\n"),
         str(experiment.root)],
        stdout=subprocess.PIPE, text=True,
    )
    try:
        assert holder.stdout is not None and holder.stdout.readline().strip() == "held"
        started = time.monotonic()
        with t.experiment_lock(other.root):
            assert time.monotonic() - started < 0.5  # the control: an unrelated lock is free
        started = time.monotonic()
        with t.experiment_lock(experiment.root):
            waited = time.monotonic() - started
        assert waited > 0.7
    finally:
        holder.wait(timeout=10)
    assert not any(p.name.endswith(".lock") for p in store.parent.rglob("*"))  # the lock leaves no file


def test_two_independently_opened_controllers_both_keep_their_retry(store: Path, base: Path) -> None:
    """Counter-model finding (#12): the lock serialized retries, but each
    controller revised the ledger it had loaded BEFORE taking the lock, so the
    second retry dropped the first's attempt. Each must build on the stored
    ledger it finds once it holds the lock."""
    experiment, first, second = _plan_two(store)
    _freeze(experiment, first, _run(experiment, first, base, REFERENCE))
    _freeze(experiment, second, _run(experiment, second, base, REFERENCE))
    one, two = t.Experiment.open(experiment.root), t.Experiment.open(experiment.root)
    retried_first = t.retry(one, first)
    retried_second = t.retry(two, second)
    planned = {str(a["attempt_id"]) for _trial, a in t.Experiment.open(experiment.root).attempts()}
    assert {retried_first, retried_second} <= planned


def test_a_grade_after_a_siblings_retry_is_not_refused(store: Path, base: Path, grading: Path) -> None:
    """The grading side of the same finding: a sibling retry committed by
    another controller before this grade took the lock is the stored ledger,
    not a change made while candidate code ran."""
    experiment, first, second = _plan_two(store)
    _freeze(experiment, first, _run(experiment, first, base, REFERENCE))
    _freeze(experiment, second, _run(experiment, second, base, REFERENCE))
    t.retry(t.Experiment.open(experiment.root), second)  # another controller's instance
    assert verify.grade(experiment, first, GRADER, grading)["status"] == "PASS"
