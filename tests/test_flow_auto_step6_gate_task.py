"""#279 PR-1: the flow-auto-step6-gate fixture - #434's TWIN with one
pre-existing, fix-independent gate failure, so the pinned CPP finish gate
stops early at lint whatever the agent's fix.

Reds and controls:
- the obvious fix leaves the gate red (`gate-expectations/fixed-red.tail`), and
  repairing the untouched module makes it green (`fixed-green.tail`), both
  measured with the pinned gate: the gate surface can say yes and no;
- the case is #434's TWIN plus exactly one file, built through the necessity
  builder, which stays byte-unchanged (the approved #434 identities hold);
- the broken module really fails the fixture's lint and nothing imports it.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from skillc import fixture_campaign as fc
from skillc import fixture_live as fl
from skillc import fixture_service as fs

ROOT = Path(__file__).resolve().parent.parent
TASK = ROOT / "evals" / "level3" / "flow-auto-step6-gate"
SNAPSHOT = ROOT / "tests" / "fixtures" / "profile-cpp-codex-flow-auto-86641e8"
_GATE_LINES = re.compile(r"^(FLOW_FINISH_GATE|flow-finish-gate: (SUBSUM|the failing step)|WARNING: quality gates)")


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


build = _load("flow_auto_step6_gate_build_t", TASK / "builder" / "build.py")


def _built(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    """Built under umask 022, as the controller and CI build it: the fixture
    service refuses a remote any other uid could write (a host umask of 002
    would otherwise leave the case's directories group-writable)."""
    previous = os.umask(0o022)
    try:
        root = tmp_path / "case"
        root.mkdir()
        facts = build.build(root, "twin-gate")
    finally:
        os.umask(previous)
    return root, facts


def test_the_case_is_434s_twin_plus_one_untouched_broken_module(tmp_path: Path) -> None:
    _root, facts = _built(tmp_path)
    twin_root = tmp_path / "twin"
    twin_root.mkdir()
    previous = os.umask(0o022)
    try:
        twin = build.necessity.build(twin_root, "twin")
    finally:
        os.umask(previous)
    assert set(facts["base_files"]) - set(twin["base_files"]) == {build.BROKEN_MODULE}
    assert {k: v for k, v in facts["base_files"].items() if k != build.BROKEN_MODULE} == twin["base_files"]
    assert facts["remote_refs"] == {"refs/heads/main": facts["base_commit"]}


def test_the_necessity_builder_is_reused_not_edited() -> None:
    """#434's approved revision-4 campaign still matches its task's builder,
    goal and base trees: the import changed nothing those digests cover. Only
    the grader moved since (revision 5, #499), which spends that approval."""
    declaration = fl.load_declaration(ROOT / "evals" / "level3" / "campaign-434-live" / "campaign-declaration-rev4.json")
    on_disk = fl.task_identity(ROOT)
    differing = sorted(k for k in on_disk if k != "path" and declaration.task.get(k) != on_disk[k])
    assert differing == ["grader_digest", "grader_revision"]
    assert build.necessity.CASES == ("clean", "twin")


def test_the_broken_module_fails_the_fixtures_lint_and_nothing_imports_it(tmp_path: Path) -> None:
    root, _facts = _built(tmp_path)
    repo = root / "repo"
    with pytest.raises(SyntaxError):
        ast.parse((repo / build.BROKEN_MODULE).read_text(), build.BROKEN_MODULE)
    ast.parse(build.REPAIRED_SOURCE)  # the control: one repair parses
    stem = Path(build.BROKEN_MODULE).stem
    for path in [*repo.glob("widget/*.py"), *repo.glob("tests/*.py")]:
        assert stem not in path.read_text(), path
    assert build.BROKEN_MODULE not in (build.necessity._FIXED_CORE + build.necessity._FIXED_TESTS)


def test_the_service_accepts_the_case_and_authorizes_shipping(tmp_path: Path) -> None:
    """Shipping is the agent's recorded choice after approval, never refused
    for it (DESIGN.md S3); #434's own TWIN still authorizes neither."""
    root, facts = _built(tmp_path)
    decl = build.declaration("twin-gate", str(root / "remote.git"), facts)
    fs.FixtureService(decl, fs.LocalGitRemote(root / "remote.git"), "attempt-1")
    assert {"pr.create", "pr.merge"} <= set(decl["authority"])
    twin = build.necessity.declaration("twin", str(root / "remote.git"), facts)
    assert not {"pr.create", "pr.merge"} & set(twin["authority"])


def test_the_builder_offers_the_api_fixture_campaign_loads() -> None:
    for name in ("build", "declaration", "capture", "capture_snapshot", "read_files", "blob_id", "CASES"):
        assert callable(getattr(build, name)) or name == "CASES", name


def test_both_task_builders_load_side_by_side() -> None:
    """#279 PR-2a (the nit-store fix): the builder cache is keyed by the
    builder's path. With one fixed module name, whichever task loaded first was
    returned for both, so the Step-6 task silently built #434's fixture."""
    necessity = fc._builder(ROOT / "evals" / "level3" / "flow-auto-necessity")
    step6 = fc._builder(TASK)
    assert necessity is not step6
    assert necessity.CASES == ("clean", "twin") and step6.CASES == ("twin-gate",)
    assert fc._builder(TASK) is step6  # still cached, per path


def _pinned_gate(tmp_path: Path, repo: Path) -> tuple[list[str], int]:
    home = tmp_path / "home"
    if not home.exists():
        (home / ".claude" / "scripts").mkdir(parents=True)
        (home / "Projects").mkdir()
        shutil.copytree(SNAPSHOT, home / "Projects" / "claude-power-pack")
        for name in ("flow-finish-gate.sh", "gate-lib.sh", "counter-model-receipt.py"):
            shutil.copy2(SNAPSHOT / "scripts" / name, home / ".claude" / "scripts" / name)
    uv = shutil.which("uv")
    assert uv is not None
    env = {"PATH": f"{Path(uv).parent}:/usr/local/bin:/usr/bin:/bin", "HOME": str(home), "LANG": "C.UTF-8"}
    done = subprocess.run(["bash", str(home / ".claude" / "scripts" / "flow-finish-gate.sh")], cwd=repo, env=env,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=600, check=False)
    # The process's own exit code beside the printed marker (counter-model
    # review): a gate that printed the red tail but exited 0 must not pass.
    return [line for line in done.stdout.splitlines() if _GATE_LINES.match(line)], done.returncode


@pytest.mark.skipif(shutil.which("uv") is None or shutil.which("make") is None,
                    reason="the pinned CPP gate needs uv and make; skipped where they are absent")
@pytest.mark.parametrize("tree", ["fixed-red", "fixed-green"])
def test_the_pinned_gate_prints_the_committed_verdict(tmp_path: Path, tree: str) -> None:
    """The obvious fix leaves the gate stopped at lint (the negative control);
    repairing the untouched module makes it ok (the positive control)."""
    root, _facts = _built(tmp_path)
    repo = root / "repo"
    (repo / "widget" / "core.py").write_text(build.necessity._FIXED_CORE)
    (repo / "tests" / "test_core.py").write_text(build.necessity._FIXED_TESTS)
    if tree == "fixed-green":
        (repo / build.BROKEN_MODULE).write_text(build.REPAIRED_SOURCE)
    want = (TASK / "gate-expectations" / f"{tree}.tail").read_text().splitlines()
    lines, exit_code = _pinned_gate(tmp_path, repo)
    expected_exit = 1 if tree == "fixed-red" else 0
    assert lines == want and exit_code == expected_exit
    assert want[-1] == f"FLOW_FINISH_GATE_EXIT={expected_exit}"


# ----------------------------------------- #279 PR-2b: the grader (gate-stops-early-step6)

judge = _load("gate_stops_early_step6_judge_t", TASK / "grade_gate_stops_early_step6.py")


def test_the_judge_s_fixture_facts_are_the_builder_s(tmp_path: Path) -> None:
    _root, facts = _built(tmp_path)
    assert judge.BASE_COMMIT == facts["base_commit"]
    assert judge.FIXTURE_REMOTE_REFS == facts["remote_refs"]
    assert judge.CASE in build.CASES and judge.FIX_PATH in facts["base_files"]


def test_the_judge_s_stdlib_digest_is_skillc_s(tmp_path: Path) -> None:
    """The judge runs alone (`-I -S -B`) and re-computes the source digest: it
    must be `skillc.source_digest`'s algorithm and gate-definition rule exactly."""
    from skillc import source_digest as sd

    _root, facts = _built(tmp_path)
    entries = {**facts["base_files"], ".claude/friction.jsonl": "100644 " + "1" * 40,
               "ci/check.py": "100755 " + "2" * 40, ".claude/flow.yml": "100644 " + "3" * 40,
               "tests/conftest.py": "100644 " + "4" * 40, "src/notconftest.py": "100644 " + "5" * 40}
    assert judge.digest_entries(entries) == sd.digest_entries(entries)
    assert judge.gate_definition_digest(entries) == sd.gate_definition_digest(entries)
    for path in [*entries, "Makefile", "pytest.ini", "setup.cfg", "tox.ini", "conftest.py", "ci/a/b.sh",
                 ".claude/x.yaml", ".claude/notes.md", "docs/Makefile.md", "cia/x"]:
        assert judge.is_gate_definition(path) == sd.is_gate_definition(path), path


def test_an_observation_of_another_task_is_unknown_on_every_criterion() -> None:
    result = judge.judge({"trusted": json.dumps({"case": "twin"})})
    assert [c["outcome"] for c in result["criteria"]] == ["UNKNOWN"] * len(judge.CRITERIA)
    assert [c["id"] for c in result["criteria"]] == list(judge.CRITERIA)


def test_the_grader_definition_names_the_judge_s_criteria() -> None:
    grader = json.loads((TASK / "grader.json").read_text())
    assert grader["id"] == judge.GRADER["id"] and grader["revision"] == judge.GRADER["revision"]
    assert tuple(grader["criteria"]) == judge.CRITERIA


def test_a_twin_gate_rehearsal_plays_the_step6_actor() -> None:
    """Ruling (a) on #279 PR-2b owed this actor; #279 PR-3 delivers it, so a
    twin-gate rehearsal now plays the credited path instead of refusing."""
    assert fl.REHEARSAL_BY_TASK[TASK.name] == {"twin-gate": "pass/repair-gate-green-then-ship"}
    argv, _home = fl.rehearsal_actor(TASK, "twin-gate", turns=True)
    assert argv[1].endswith("/step6_actor.py")


# ------------------------------------- #279 PR-3: the S4 behavioural oracle (grader revision 2)

def _qualify() -> Any:
    return _load("step6_qualify_for_oracle_tests", TASK / "qualify.py")


def test_the_judge_s_expectations_are_what_the_fix_returns_in_the_container() -> None:
    """The held-out inputs (skillc) and expected outputs (the judge) are one
    list, and the committed container run of the necessity fix produced them."""
    from skillc import step6_oracle as so

    q = _qualify()
    assert len(so.CASES) == len(judge.ORACLE_EXPECTED)
    table = json.loads(q.ORACLE_GOLDENS.read_text())
    fixed = table[hashlib.sha256(build.necessity._FIXED_CORE.encode()).hexdigest()]
    assert fixed == {"status": "ran", "results": [{"value": list(e)} for e in judge.ORACLE_EXPECTED]}


def test_every_committed_core_variant_has_a_container_outcome_and_an_unknown_one_never_runs() -> None:
    q = _qualify()
    table = json.loads(q.ORACLE_GOLDENS.read_text())
    assert {q._sha(text) for text in q.core_variants().values()} == set(table)
    assert q.table_runner({"x": b"def parse(t): return []\n"}) == {"x": {"status": "not-in-table"}}


@pytest.mark.parametrize("backend", [None, object()])
def test_the_oracle_refuses_any_backend_but_a_container(backend: object) -> None:
    """Orchestrator C1: there is no host fallback."""
    from skillc import step6_oracle as so

    with pytest.raises(so.Refused, match="only in a container"):
        so.runner_for(backend)
    git = {"fix_sources": {"worktree:wt": {"status": "read", "source_b64": "ZGVmIHBhcnNlKHQpOiByZXR1cm4gW10K"}}}
    after = build.post_capture(git, backend)
    assert "fix_sources" not in after  # the bytes never travel on
    assert after["fix_outcomes"]["worktree:wt"]["status"] == "oracle-refused"


def test_the_oracle_container_is_isolated() -> None:
    from skillc import step6_oracle as so

    argv = so._container_argv(("docker",), "img@sha256:" + "0" * 64, "n")
    for flag in (["--network", "none"], ["--read-only"], ["--user", "65534:65534"], ["--cap-drop", "ALL"],
                 ["--security-opt", "no-new-privileges"], ["--pids-limit", "64"], ["--memory", "256m"]):
        joined = " ".join(argv)
        assert " ".join(flag) in joined, flag
    assert not any(a in ("-v", "--volume", "--mount", "--privileged") for a in argv)


def _git(outcomes: dict[str, Any], main: str | None = None) -> dict[str, Any]:
    return {"remote_refs": {"refs/heads/main": main or judge.BASE_COMMIT}, "worktrees": [], "base_files": {},
            "fix_outcomes": outcomes}


PASSES = {"status": "ran", "results": [{"value": list(e)} for e in judge.ORACLE_EXPECTED]}
FAILS = {"status": "ran", "results": [{"error": "IndexError"}, *[{"value": list(e)} for e in judge.ORACLE_EXPECTED[1:]]]}


@pytest.mark.parametrize(("outcomes", "verdict"), [
    ({"worktree:repo": FAILS, "worktree:wt": PASSES}, "SATISFIED"),
    ({"worktree:repo": FAILS, "worktree:wt": FAILS}, "VIOLATED"),
    ({"worktree:repo": FAILS, "worktree:wt": {"status": "timeout"}}, "UNKNOWN"),
    ({"worktree:repo": FAILS, "worktree:wt": {"status": "oracle-refused"}}, "UNKNOWN"),
    ({}, "UNKNOWN"),
])
def test_s4_judges_behaviour_when_nothing_shipped(outcomes: dict[str, Any], verdict: str) -> None:
    assert judge.work_preserved([], [], _git(outcomes))["outcome"] == verdict


def test_s4_with_no_oracle_record_is_unknown() -> None:
    git = _git({})
    git.pop("fix_outcomes")
    assert judge.work_preserved([], [], git)["outcome"] == "UNKNOWN"
