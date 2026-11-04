"""Focused trusted actor preparation; no Docker/full-wave qualification claim."""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "fixtures/wave-rehearsal"
HELPERS = ROOT / "fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-wave/scripts"
ROLES = ("orchestrator", "worker-a", "worker-b")
CASES = json.loads((SOURCE / "cases.json").read_text())


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-c", "user.name=Fixture", "-c",
        "user.email=fixture@example.invalid", *args], cwd=root, stderr=subprocess.PIPE,
        text=True, timeout=10).strip()


@pytest.fixture
def world(tmp_path: Path) -> dict[str, Any]:
    seed, scripts = tmp_path / "seed", tmp_path / "scripts"
    seed.mkdir()
    shutil.copytree(SOURCE, scripts, ignore=shutil.ignore_patterns("__pycache__"))
    for helper in HELPERS.glob("*.sh"):
        shutil.copyfile(helper, scripts / helper.name)
    task = json.loads((SOURCE / "task.json").read_text())
    for name, text in task["seed"].items():
        p = seed / name
        p.parent.mkdir(exist_ok=True)
        p.write_text(text)
    git(seed, "init", "-b", "main")
    git(seed, "add", ".")
    git(seed, "commit", "-m", "fixture seed")
    first = git(seed, "rev-parse", "HEAD")
    remote = tmp_path / "remote.git"
    git(tmp_path, "clone", "--bare", "--no-hardlinks", str(seed), str(remote))
    projects, homes = {}, {}
    shared = tmp_path / "shared"
    shared.mkdir()
    for role in ROLES:
        projects[role] = tmp_path / role
        homes[role] = tmp_path / (role + "-home")
        homes[role].mkdir()
        git(tmp_path, "clone", str(remote), str(projects[role]))
    config = {"wave_id": "quote-rehearsal", "bindings": {role: {
        "attempt_id": "attempt-" + role, "task": "quote-" + role,
        "revision": 1, "generation": 0, "nonce": "nonce-" + role} for role in ROLES}}
    return {"seed": first, "remote": remote, "scripts": scripts, "projects": projects,
            "homes": homes, "shared": shared, "config": config, "sessions": {}}


def turn(world: dict[str, Any], role: str, mode: str = "healthy", *, session: str | None = None) -> subprocess.CompletedProcess[str]:
    if role in world["sessions"]:
        tail = ["resume", session or world["sessions"][role], "Read shared work and continue."]
    else:
        tail = [json.dumps(world["config"])]
    env = dict(os.environ, HOME=str(world["homes"][role]),
               FLOW_WAVE_MAILBOX_DIR=str(world["shared"]), FLOW_WAVE_REGISTRY_DIR=str(world["shared"]))
    result = subprocess.run([sys.executable, "-I", str(world["scripts"] / "role_actor.py"), role, mode, *tail],
                            cwd=world["projects"][role], env=env, capture_output=True, text=True,
                            timeout=15, check=False)
    state = world["projects"][role] / ".rehearsal-state.json"
    if state.exists():
        world["sessions"][role] = json.loads(state.read_text())["session"]
    return result


def grade(world: dict[str, Any], base: Path) -> dict[str, Any]:
    spec = importlib.util.spec_from_file_location("rehearsal_delivery", world["scripts"] / "grade_delivery.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    snapshot = base / "snapshot.git"
    shutil.copytree(world["remote"], snapshot)
    return module.grade(snapshot, world["seed"], base)


@pytest.mark.parametrize("order", [["worker-a", "worker-b"], ["worker-b", "worker-a"]])
def test_real_helpers_resume_and_independent_remote_quote(world: dict[str, Any], tmp_path: Path, order: list[str]) -> None:
    # Start workers before the assigning orchestrator, while keeping the actual
    # helper operations and measured argv. This is not the dynamic wake driver.
    for role in (*order, "orchestrator"):
        result = turn(world, role)
        assert result.returncode == 0, result.stderr
    for role in (*order, "orchestrator"):
        result = turn(world, role)
        assert result.returncode == 0, result.stderr
    # A broken local checkout cannot invalidate correct independently delivered
    # remote bytes; the oracle must not borrow this checkout in either direction.
    (world["projects"]["orchestrator"] / "src/tax.py").write_text("raise RuntimeError('local-only')\n")
    observed = grade(world, tmp_path)
    assert observed["status"] == "PASS", observed
    assert observed["oracle_executed"]
    assert observed["containment"]["confirmed"] is True
    assert observed["containment"]["cleanup"] == "removed"
    for role in ROLES:
        rows = [json.loads(line) for line in (world["homes"][role] / ".codex/sessions" / (role + ".jsonl")).read_text().splitlines()]
        assert rows[0] == {"type": "session_meta", "payload": {"id": world["sessions"][role]}}
        assert len(rows) == 3
    mailbox = world["shared"] / "quote-rehearsal"
    assert (mailbox / "outbox-worker-a.md").is_file()
    assert (mailbox / ".ack-outbox-worker-a.md").read_text().strip() == "1"


@pytest.mark.parametrize("mode", ["wrong-tax", "unfinished-integration", "disappear"])
def test_remote_outcome_cannot_borrow_local_success(world: dict[str, Any], tmp_path: Path, mode: str) -> None:
    # Prime worker sessions before assigning, as in the healthy opposite.
    for role in ("worker-a", "worker-b", "orchestrator"):
        assert turn(world, role, mode).returncode == 0
    for role in ("worker-a", "worker-b", "orchestrator"):
        result = turn(world, role, mode)
        assert result.returncode == (7 if role == "worker-a" and mode == "disappear" else 0), result.stderr
    task = json.loads((SOURCE / "task.json").read_text())
    for role, path in (("worker-a", "src/subtotal.py"), ("worker-b", "src/tax.py")):
        (world["projects"]["orchestrator"] / path).write_text(task["implementations"][role])
    (world["projects"]["orchestrator"] / "success.json").write_text('{"success":true}')
    observed = grade(world, tmp_path)
    assert observed["status"] == "FAIL", observed


@pytest.mark.parametrize("mode,field", [("stale-ack", "revision"), ("wrong-role-ack", "role"),
                                      ("duplicate-completion", "op")])
def test_closed_actor_faults_reach_actual_mailboxes(world: dict[str, Any], mode: str, field: str) -> None:
    for role in ("worker-a", "worker-b", "orchestrator"):
        assert turn(world, role, mode).returncode == 0
    assert turn(world, "worker-a", mode).returncode == 0
    text = (world["shared"] / "quote-rehearsal/inbox-worker-a.md").read_text()
    rows = [json.loads(line) for line in text.splitlines() if line.startswith("{")]
    if field == "revision":
        assert rows[0][field] == 2
    elif field == "role":
        assert rows[0][field] == "worker-b"
    else:
        assert [r["op"] for r in rows] == ["ack", "complete", "complete"]


def test_stale_resume_refuses_before_shared_mutation(world: dict[str, Any]) -> None:
    assert turn(world, "worker-a").returncode == 0
    before = (world["shared"] / "registry.json").read_bytes()
    result = turn(world, "worker-a", session="obsolete-session")
    assert result.returncode != 0
    assert (world["shared"] / "registry.json").read_bytes() == before


def test_orchestrator_can_start_before_its_workers(world: dict[str, Any]) -> None:
    first = turn(world, "orchestrator")
    assert first.returncode == 0, first.stderr
    assert not (world["shared"] / "quote-rehearsal/outbox-worker-a.md").exists()
    for role in ("worker-a", "worker-b", "orchestrator"):
        result = turn(world, role)
        assert result.returncode == 0, result.stderr
    assert (world["shared"] / "quote-rehearsal/outbox-worker-a.md").is_file()


def test_missing_snapshot_is_unknown(world: dict[str, Any], tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location("missing_delivery", world["scripts"] / "grade_delivery.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.grade(tmp_path / "missing", world["seed"], tmp_path)["status"] == "UNKNOWN"
    (tmp_path / "empty-export").mkdir()
    assert module.grade(tmp_path / "empty-export", world["seed"], tmp_path)["status"] == "UNKNOWN"


def test_case_declaration_preserves_every_required_fault() -> None:
    assert len(CASES) == len({c["id"] for c in CASES}) == 13
    assert {"lost-poke", "worker-disappears", "stale-acknowledgement", "wrong-role-acknowledgement",
            "duplicate-completion", "unfinished-integration", "missed-deadline", "unretired-wave",
            "capture-unavailable", "non-start"} <= {c["id"] for c in CASES}
