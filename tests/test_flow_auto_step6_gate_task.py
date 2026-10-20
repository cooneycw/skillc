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
import importlib.util
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
    """#434's approved revision-4 campaign still binds its task: the import
    changed nothing the declaration's builder digest covers."""
    declaration = fl.load_declaration(ROOT / "evals" / "level3" / "campaign-434-live" / "campaign-declaration-rev4.json")
    fl.require_approved(declaration, ROOT)
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
    """The necessity builder's functions, by name (`fixture_campaign._builder`
    caches ONE builder under a fixed module name, so it cannot load this one
    beside #434's yet: PR-2's blocker, recorded in DESIGN.md)."""
    for name in ("build", "declaration", "capture", "capture_snapshot", "read_files", "blob_id", "CASES"):
        assert callable(getattr(build, name)) or name == "CASES", name
    assert fc._builder.__code__.co_consts.count("flow_auto_necessity_builder_campaign") == 1


def _pinned_gate(tmp_path: Path, repo: Path) -> list[str]:
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
    return [line for line in done.stdout.splitlines() if _GATE_LINES.match(line)]


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
    assert _pinned_gate(tmp_path, repo) == want
    assert want[-1] == ("FLOW_FINISH_GATE_EXIT=1" if tree == "fixed-red" else "FLOW_FINISH_GATE_EXIT=0")
