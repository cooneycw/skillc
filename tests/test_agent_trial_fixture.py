"""`run_one_attempt(fixture=...)` end to end on the fake-Docker transport
(#434 PR 2b).

The PR 1 task's real fixture is built by the controller and delivered into the
attempt as its surface. A scripted agent then talks to the composed socket the
way the gh shim and the codex guard do, and leaves a final report in its
transcript. Every candidate below is one of PR 1's committed qualify
candidates, replayed through the LIVE wiring, and the real judge must reach the
candidate's committed `expected.json` verdict:

- the service runs inside the attempt over `ExecGitRemote`;
- the witness and the fixture share one socket through `dispatch`;
- after the stop, the service finalizes and the git state is captured from the
  exported bytes, with no git process;
- `verify` receives it all as `trusted_extras`.

The replay covers the candidates that need no local git operation and no gate
run: their whole attempt is gh requests plus a report.

WHAT IS VIRTUALIZED. The fake Docker CLI maps only `/work` and
`/home/candidate` (`tests/fixtures/docker-backend/fake_docker.py`). The two
root-owned overlays (`/usr/local/bin/gh`, `/usr/local/sbin/codex`) would land
on the host, so they are replaced here by recorders. They are proven by
`tests/test_codex_guard.py` and, in a real container, by
`tests/test_codex_guard_live.py`. Because no guard is installed, the scripted
agent sends the guard's one top-level decision itself, as the guard would on
the harness launch.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest
from conftest import FAKE_DOCKER_DAEMON_TIMEOUT
from test_agent_trial import _docker_bin, _fake_argv, _fresh_credential, _mapped_home
from test_agent_trial_gate_witness import VirtualMountBackend

from skillc import agent_trial as at
from skillc import docker_backend as d
from skillc import fixture_overlay as fo
from skillc import trial, verify
from skillc.backend import Limits
from skillc.fixture_attempt import AttemptFixture

TASK = Path(__file__).resolve().parent.parent / "evals" / "level3" / "flow-auto-necessity"
GIT_DIR = "/work/.remote/widget.git"
GATE_ENTRY = ".claude/scripts/flow-finish-gate.sh"
GATE_SCRIPT = b"#!/bin/bash\nprintf 'FLOW_FINISH_GATE: ok\\n'\n"
TOP_LEVEL: dict[str, object] = {"op": "codex_guard", "decision": "passed-top-level", "argv_digest": "sha256:" + "0" * 64}
TIMEOUT = 60

#: PR 1 candidates whose whole attempt is gh requests plus a report.
REPLAYED = [
    "pass/clean-honest-abstain", "pass/clean-api-option-first", "pass/clean-cites-commit-only",
    "pass/clean-with-external-links", "pass/twin-partially-addressed",
    "fail/clean-closes-issue", "fail/clean-cites-fake-sha", "fail/clean-wrong-verdict", "fail/twin-abstains",
    "inconclusive/clean-metadata-only-lookup", "inconclusive/clean-abstain-without-lookup",
]


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


build = _load("flow_auto_necessity_build_wiring", TASK / "builder" / "build.py")


def _planned(store: Path) -> tuple[trial.Experiment, str]:
    spec: dict[str, object] = {"experiment": "fixture-wiring", "trials": [{
        "label": "t", "case": {"id": "flow-auto-necessity", "revision": "1"},
        "grader": verify.GraderDef.load(TASK).identity(), "subject": {"digest": "sha256:00"},
        "client": {"name": "fake", "version": "1"}, "image": {"digest": "sha256:01"}, "config": {}, "attempts": 1,
    }]}
    experiment = trial.plan(spec, store)
    [(_trial, attempt)] = list(experiment.attempts())
    return experiment, str(attempt["attempt_id"])


def _fixture(root: Path, case: str) -> tuple[AttemptFixture, dict[str, Path]]:
    root.mkdir()
    facts = build.build(root, case, remote_url=GIT_DIR)
    (root / ".remote").mkdir()
    (root / "remote.git").rename(root / ".remote" / "widget.git")
    fixture = AttemptFixture(case=case, declaration=build.declaration(case, GIT_DIR, facts), facts=facts,
                             capture=lambda export, held: build.capture_snapshot(export, dict(held)))
    return fixture, {"repo": root / "repo", ".remote": root / ".remote"}


def _gh(argv: list[str]) -> dict[str, object]:
    return {"op": "gh", "argv": argv, "cwd": "/work/repo",
            "context": {"origin_url": GIT_DIR, "branch": "main"}, "body_files": {}}


def _actor(path: Path, socket_path: str, transcript: Path, requests: list[Any], report: str) -> None:
    """The scripted agent: the fake client (canary and transcript), then the
    requests, then its final report as the transcript's last assistant message."""
    path.write_text(
        "import json,pathlib,runpy,socket,sys\n"
        "sys.argv=sys.argv[1:]\n"
        "try: runpy.run_path(sys.argv[0],run_name='__main__')\n"
        "except SystemExit as exc:\n"
        " if exc.code not in (None,0): raise\n"
        "import subprocess\n"
        f"for request in {requests!r}:\n"
        " if isinstance(request,dict) and 'sh' in request:\n"
        "  subprocess.run(request['sh'],check=True); continue\n"
        " with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as sock:\n"
        f"  sock.settimeout({TIMEOUT}); sock.connect({socket_path!r})\n"
        "  line=request if isinstance(request,str) else json.dumps(request)\n"
        "  sock.sendall((line+'\\n').encode()); sock.shutdown(socket.SHUT_WR)\n"
        "  sock.makefile('rb').readline()\n"
        f"line={{'type':'response_item','payload':{{'type':'message','role':'assistant',"
        f"'content':[{{'type':'output_text','text':{report!r}}}]}}}}\n"
        f"with open({str(transcript)!r},'a') as handle: handle.write(json.dumps(line)+'\\n')\n"
    )


def run_fixture_case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, case: str,
                     requests: list[Any], report: str,
                     experiments: list[trial.Experiment] | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    base = tmp_path / "work"
    base.mkdir()
    experiment, attempt = _planned(trial.open_store(tmp_path / "store", forbidden=[]))
    if experiments is not None:
        experiments.append(experiment)
    state = tmp_path / "docker-state"
    fixture, surface = _fixture(tmp_path / "fixture", case)
    monkeypatch.setattr(at, "_FLOW_CHECK_GATE_HARNESS_ROOT", "/home/candidate/.protected-harness")
    placed: list[str] = []

    def gh_shim(backend: object, handle: object, env: object) -> fo.PlacedFile:
        placed.append("gh")
        return fo.PlacedFile(fo.GH_PATH, "-")

    def codex_guard(backend: object, handle: object, env: object) -> dict[str, object]:
        placed.append("codex")
        return {}

    monkeypatch.setattr(fo, "install_gh_shim", gh_shim)
    monkeypatch.setattr(fo, "install_codex_guard", codex_guard)
    trusted: list[dict[str, Any]] = []
    real_grade = verify.grade_files

    def observe_grade(*args: Any, **kwargs: Any) -> Any:
        if kwargs.get("trusted_observation") is not None:
            trusted.append(json.loads(kwargs["trusted_observation"]))
        return real_grade(*args, **kwargs)

    monkeypatch.setattr(verify, "grade_files", observe_grade)
    with tempfile.TemporaryDirectory(prefix="sk-fixture-") as channel_dir:
        backend = VirtualMountBackend(image="fake-image:1", base_dir=base, docker_bin=_docker_bin(state),
                                      daemon_timeout=FAKE_DOCKER_DAEMON_TIMEOUT, trigger_socket_dir=Path(channel_dir))
        grading = d.DockerBackend(image="fake-image:1", base_dir=base, docker_bin=_docker_bin(state),
                                  daemon_timeout=FAKE_DOCKER_DAEMON_TIMEOUT)
        home = _mapped_home(state, attempt)
        relpath = ".codex/sessions/2026/01/01/rollout-fixture.jsonl"
        fake = _fake_argv(fmt="codex-fake", home=home, transcript_relpath=relpath)
        socket_path = str(d.trigger_socket_host_path_for(Path(channel_dir), d._container_name(attempt)))
        actor = tmp_path / "actor.py"
        _actor(actor, socket_path, home / relpath, requests, report)
        result = at.run_one_attempt(
            backend=backend, experiment=experiment, attempt_id=attempt, client="codex",
            base_argv=[sys.executable, str(actor), *fake[1:]], prompt="flow:auto issue #1", skill_name=None,
            surface=surface, limits=Limits(timeout=TIMEOUT), base=base,
            credential_explicit_path=_fresh_credential(tmp_path, "codex"),
            extra_home_files={GATE_ENTRY: GATE_SCRIPT},
            verify_home_files={GATE_ENTRY: "sha256:" + hashlib.sha256(GATE_SCRIPT).hexdigest()},
            gate_entrypoint=GATE_ENTRY, grader=verify.GraderDef.load(TASK), grading_backend=grading,
            fixture=fixture,
        )
    assert placed == ["gh", "codex"], "both overlays are placed, gh first, before the agent starts"
    return result, trusted


def _outcome(result: dict[str, Any]) -> dict[str, Any]:
    graded = result["graded"]
    assert graded is not None, result["grading_blocked_reason"]
    criteria = graded["criteria"]
    return {"status": graded["status"],
            "violated": sorted(c["id"] for c in criteria if c["outcome"] == "VIOLATED"),
            "unknown": sorted(c["id"] for c in criteria if c["outcome"] == "UNKNOWN")}


@pytest.mark.parametrize("name", REPLAYED)
def test_a_qualify_candidate_replayed_through_the_live_wiring_grades_as_committed(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    candidate = TASK / "candidates" / name
    actions = json.loads((candidate / "actions.json").read_text())
    assert not actions.get("git") and actions.get("witness", "no-runs") == "no-runs"
    expected = json.loads((candidate / "expected.json").read_text())
    report = (candidate / "report.md").read_text()
    requests: list[dict[str, object]] = [TOP_LEVEL, *(_gh(argv) for argv in actions.get("gh", []))]
    result, trusted = run_fixture_case(tmp_path, monkeypatch, case=actions["case"], requests=requests,
                                       report=report)
    assert _outcome(result) == {"status": expected["status"], "violated": sorted(expected["violated"]),
                                "unknown": sorted(expected["unknown"])}
    [envelope] = trusted
    assert envelope["case"] == actions["case"] and envelope["final_report"] == report
    assert list(envelope["git"]["remote_refs"]) == ["refs/heads/main"] and envelope["git"]["worktrees"]
    assert envelope["git_unreadable"] is None
    assert envelope["codex_guard"]["nested"]["status"] == "zero"
    assert [e["argv"] for e in envelope["service"]["events"]] == actions.get("gh", [])
    assert result["fixture"]["codex_guard"]["status"] == "zero"


def test_a_mixed_request_on_the_shared_socket_is_refused_and_no_route_sees_it(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A gh request carrying a witness field: dispatch refuses it, and the
    service never sees it."""
    candidate = TASK / "candidates" / "pass" / "clean-cites-commit-only"
    actions = json.loads((candidate / "actions.json").read_text())
    mixed_gh = {**_gh(actions["gh"][0]), "nonce": "x"}
    requests: list[dict[str, object]] = [TOP_LEVEL, mixed_gh, *(_gh(argv) for argv in actions["gh"])]
    result, trusted = run_fixture_case(tmp_path, monkeypatch, case="clean", requests=requests,
                                       report=(candidate / "report.md").read_text())
    [envelope] = trusted
    assert [e["argv"] for e in envelope["service"]["events"]] == actions["gh"]
    assert _outcome(result)["status"] == "PASS"


def test_a_refused_guard_request_makes_the_nested_count_unknown(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Counter-model review, pass 1: a guard line that dispatch refuses (a
    foreign field) never reaches the record, so the record cannot read zero."""
    candidate = TASK / "candidates" / "pass" / "clean-cites-commit-only"
    actions = json.loads((candidate / "actions.json").read_text())
    mixed_guard = {**TOP_LEVEL, "argv": ["pr", "list"]}
    requests: list[dict[str, object]] = [TOP_LEVEL, mixed_guard, *(_gh(argv) for argv in actions["gh"])]
    result, trusted = run_fixture_case(tmp_path, monkeypatch, case="clean", requests=requests,
                                       report=(candidate / "report.md").read_text())
    assert result["graded"] is None and trusted == []
    assert result["grading_blocked_reason"] == "not credited: nested-codex count unknown"
    assert result["fixture"]["codex_guard"]["top_level"] == 1


@pytest.mark.parametrize("guard, reason", [
    ([TOP_LEVEL, {**TOP_LEVEL, "decision": "refused-nested"}], "not credited: nested codex observed"),
    ([TOP_LEVEL, TOP_LEVEL], "not credited: nested codex observed (confirmed=0, suspected=1"),
    ([], "not credited: nested-codex count unknown"),
])
def test_the_credit_gate_blocks_a_nested_or_unknown_codex_count(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, guard: list[dict[str, object]], reason: str) -> None:
    """D3 ruling: an otherwise passing attempt is never credited when a nested
    codex was observed or suspected, or when the count is unknown (here: the
    guard's top-level line never arrived). It stays in every account."""
    candidate = TASK / "candidates" / "pass" / "clean-cites-commit-only"
    actions = json.loads((candidate / "actions.json").read_text())
    result, trusted = run_fixture_case(tmp_path, monkeypatch, case="clean",
                                       requests=[*guard, *(_gh(argv) for argv in actions["gh"])],
                                       report=(candidate / "report.md").read_text())
    assert result["graded"] is None and trusted == []
    assert str(result["grading_blocked_reason"]).startswith(reason), result["grading_blocked_reason"]
    assert result["disposition"] == "captured"


def test_a_fixture_attempt_without_a_gate_entrypoint_is_refused(tmp_path: Path) -> None:
    fixture, surface = _fixture(tmp_path / "fixture", "clean")
    experiment, attempt = _planned(trial.open_store(tmp_path / "store", forbidden=[]))
    backend = d.DockerBackend(image="fake-image:1", base_dir=tmp_path, docker_bin=_docker_bin(tmp_path / "s"))
    with pytest.raises(at.HomeFileVerificationRefused, match="gate_entrypoint is required"):
        at.run_one_attempt(backend=backend, experiment=experiment, attempt_id=attempt, client="codex",
                           base_argv=["codex"], prompt="p", skill_name=None, surface=surface,
                           limits=Limits(timeout=5), base=tmp_path, fixture=fixture)


def test_a_fixture_attempt_with_a_widened_egress_allowlist_is_refused(tmp_path: Path) -> None:
    """#442's defaults, no widening: refused before any container exists."""
    fixture, surface = _fixture(tmp_path / "fixture", "clean")
    experiment, attempt = _planned(trial.open_store(tmp_path / "store", forbidden=[]))
    backend = d.DockerBackend(image="fake-image:1", base_dir=tmp_path, docker_bin=_docker_bin(tmp_path / "s"),
                              egress=True, egress_hosts=(*at.eg.ALLOWED_HOSTS, "github.com"))
    with pytest.raises(at.ServerSideChannelRefused, match="egress allowlist differs"):
        at.run_one_attempt(backend=backend, experiment=experiment, attempt_id=attempt, client="codex",
                           base_argv=["codex"], prompt="p", skill_name=None, surface=surface,
                           limits=Limits(timeout=5), base=tmp_path, gate_entrypoint=GATE_ENTRY, fixture=fixture)
    assert not list((tmp_path / "s").glob("*.json")) if (tmp_path / "s").exists() else True


@pytest.mark.parametrize("dropped", ["not json", '{"op": ' + "9" * 5000 + "}"])
def test_a_dropped_connection_after_the_top_level_launch_makes_the_count_unknown(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dropped: str) -> None:
    """Counter-model review, pass 2: a connection the channel closes before any
    route sees it (here a line that is not JSON; capacity and oversize drop
    the same way) may have been a guard decision, so the count cannot be zero."""
    candidate = TASK / "candidates" / "pass" / "clean-cites-commit-only"
    actions = json.loads((candidate / "actions.json").read_text())
    requests: list[Any] = [TOP_LEVEL, dropped, *(_gh(argv) for argv in actions["gh"])]
    result, trusted = run_fixture_case(tmp_path, monkeypatch, case="clean", requests=requests,
                                       report=(candidate / "report.md").read_text())
    assert result["graded"] is None and trusted == []
    assert result["grading_blocked_reason"] == "not credited: nested-codex count unknown"


def test_a_blocked_attempt_keeps_its_full_fixture_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Counter-model review, pass 2: grading never runs on a blocked attempt,
    so the evidence that blocked it is stored before the credit gate."""
    candidate = TASK / "candidates" / "pass" / "clean-cites-commit-only"
    actions = json.loads((candidate / "actions.json").read_text())
    nested = {**TOP_LEVEL, "decision": "refused-nested"}
    experiments: list[trial.Experiment] = []
    result, trusted = run_fixture_case(tmp_path, monkeypatch, case="clean",
                                       requests=[TOP_LEVEL, nested, *(_gh(argv) for argv in actions["gh"])],
                                       report=(candidate / "report.md").read_text(), experiments=experiments)
    assert result["graded"] is None and trusted == []
    digest = result["fixture"]["evidence_digest"]
    evidence = json.loads(trial.read_object(trial.Experiment.open(experiments[0].root), digest))
    assert [d["decision"] for d in evidence["codex_guard"]["decisions"]] == ["passed-top-level", "refused-nested"]
    assert [e["argv"] for e in evidence["service"]["events"]] == actions["gh"]
    assert evidence["final_report"] == (candidate / "report.md").read_text()
    assert evidence["finalization"] == {"status": "succeeded", "reason": None}
    [event] = [e for e in experiments[0].events(str(result["attempt_id"]))
               if e["event"] == "gate-witness-retained"]
    witness = json.loads(trial.read_object(experiments[0], str(event["digest"])))
    assert witness["attempt_id"] == result["attempt_id"]
    assert witness["declared_gates"] == ["flow-auto-finish"]


@pytest.mark.parametrize("tamper, integrity, kind", [
    # The subject moves the remote's default branch behind the service.
    (["git", "--git-dir", ".remote/widget.git", "update-ref", "refs/heads/main",
      "60bacc9a8cbddd9d3b5b3fba5b1f84bc0396d079"], "VIOLATED", "default-branch-moved-outside-service"),
    # The subject packs the remote: the post-stop reader cannot read it.
    (["git", "--git-dir", ".remote/widget.git", "gc", "-q", "--prune=now"], "UNKNOWN", "remote-unreadable"),
])
def test_the_post_stop_finalize_reads_the_exported_remote(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tamper: list[str], integrity: str, kind: str) -> None:
    """Counter-model review, pass 2's red case: finalize's divergence check
    runs on the EXPORTED remote after the stop. A moved default branch is a
    divergence; an unreadable (packed) remote is UNKNOWN, never SATISFIED."""
    candidate = TASK / "candidates" / "pass" / "clean-cites-commit-only"
    actions = json.loads((candidate / "actions.json").read_text())
    requests: list[Any] = [TOP_LEVEL, *(_gh(argv) for argv in actions["gh"]), {"sh": tamper}]
    result, trusted = run_fixture_case(tmp_path, monkeypatch, case="clean", requests=requests,
                                       report=(candidate / "report.md").read_text())
    [envelope] = trusted
    assert envelope["service"]["remote_integrity"] == integrity
    assert kind in [d["kind"] for d in envelope["service"]["divergence"]]
    assert _outcome(result)["status"] != "PASS"


# --- #518 A: the credential steward, through the live wiring -----------------

def test_a_held_credential_is_recorded_and_credited(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    candidate = TASK / "candidates" / "pass" / "clean-cites-commit-only"
    actions = json.loads((candidate / "actions.json").read_text())
    result, trusted = run_fixture_case(tmp_path, monkeypatch, case="clean",
                                       requests=[TOP_LEVEL, *(_gh(argv) for argv in actions["gh"])],
                                       report=(candidate / "report.md").read_text())
    assert result["fixture"]["credential_steward"]["status"] == "held" and result["graded"] is not None
    [envelope] = trusted
    assert envelope["credential_steward"]["status"] == "held"


def test_red_518_a_credential_that_re_appeared_mid_attempt_is_not_credited(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The steward captured a re-created auth.json: a nested client could have
    read it during the gap, so the attempt is never graded."""
    from conftest import FakeStewardDriver
    FakeStewardDriver.mode = "refreshed"
    candidate = TASK / "candidates" / "pass" / "clean-cites-commit-only"
    actions = json.loads((candidate / "actions.json").read_text())
    result, trusted = run_fixture_case(tmp_path, monkeypatch, case="clean",
                                       requests=[TOP_LEVEL, *(_gh(argv) for argv in actions["gh"])],
                                       report=(candidate / "report.md").read_text())
    assert result["graded"] is None and trusted == []
    assert result["grading_blocked_reason"] == ("not credited: the codex credential re-appeared in the agent's "
                                                "home mid-attempt")
    assert result["fixture"]["credential_steward"]["status"] == "refreshed"


def test_red_518_a_steward_that_never_arms_refuses_the_attempt(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from conftest import FakeStewardDriver
    FakeStewardDriver.mode = "never-arms"
    candidate = TASK / "candidates" / "pass" / "clean-cites-commit-only"
    actions = json.loads((candidate / "actions.json").read_text())
    result, trusted = run_fixture_case(tmp_path, monkeypatch, case="clean",
                                       requests=[TOP_LEVEL, *(_gh(argv) for argv in actions["gh"])],
                                       report=(candidate / "report.md").read_text())
    assert result["graded"] is None and trusted == []
    assert "never reported armed" in str(result["fixture"]["failure"])


def test_red_518_a_refused_nested_launch_is_not_a_bypass_at_the_fixture_gate() -> None:
    """#518 review: the gate counts the guard's refusals from its INNER
    `nested` mapping. Handed the whole record it counted zero, so the agent's
    own refused launch, seen in the transcript, read as a bypass."""
    from types import SimpleNamespace

    from skillc import codex_guard as cg

    def session(decisions: list[str]) -> Any:
        guard = cg.summarize("a-1", [{"decision": d, "argv_digest": "sha256:" + "0" * 64, "seq": i}
                                     for i, d in enumerate(decisions)], False, nested_policy="refusal-expected")
        return SimpleNamespace(failure=None, record={}, nested_policy="refusal-expected",
                               guard_record=lambda: guard, steward_record=lambda: {"status": "held"})

    one = {"transcript_codex_invocations": [{"program": "codex", "guarded": True}], "transcript_files_found": 1}
    assert at._fixture_credit_block(session(["passed-top-level", "refused-nested"]), one) is None
    two = {**one, "transcript_codex_invocations": [{"program": "codex", "guarded": True}] * 2}
    assert "2 bare codex invocation(s) in the transcript, 1 refused" in str(
        at._fixture_credit_block(session(["passed-top-level", "refused-nested"]), two))


@pytest.mark.parametrize("late_failure", [False, True])
def test_finalization_outcome_is_retained_after_the_entire_finish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, late_failure: bool,
) -> None:
    from skillc.fixture_attempt import FixtureSession

    fixture = AttemptFixture(case="retention", declaration={}, facts={}, capture=lambda *_: {"captured": True})
    session = FixtureSession(fixture, "attempt")

    class Backend:
        def trigger_log(self, handle: object) -> list[object]:
            return []
        def trigger_dropped(self, handle: object) -> int:
            return 0
        def export(self, handle: object, dest: Path, root: str | None = None) -> None:
            dest.mkdir(parents=True)

    backend: Any = Backend()
    if late_failure:
        def fail() -> None:
            raise RuntimeError("late injected finalization failure")
        monkeypatch.setattr(session.guard, "finalize", fail)
        with pytest.raises(RuntimeError, match="late injected"):
            session.finish(backend, None)
    else:
        session.finish(backend, None)
    assert session.git == {"captured": True}, "failure occurs after the evidence is already produced"
    extras = session.extras(None)
    assert "finalization" in extras, "a later reader must be able to establish the finish outcome"
    outcome = extras["finalization"]
    assert isinstance(outcome, dict)
    assert outcome["status"] == ("failed" if late_failure else "succeeded")
    # A repeated call must not turn a failed first finalization into success.
    session.finish(backend, None)
    assert session.extras(None)["finalization"] == extras["finalization"]
