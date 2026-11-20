"""DockerWave's task-protocol hook (#620 PR-B, B8b) is ADDITIVE.

Imports only names the parent commit has, so it collects there. With the
protocol unused, every role and remote backend is constructed with exactly
the parent's keywords (committed goldens, hand-derived from the parent
source; they must pass on the parent too). With lease directories set, only
the role backends gain exactly the one task-protocol keyword, which fails on
the parent, where the hook does not exist."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from test_docker_wave import ModelBackend

from skillc import docker_wave as wave
from skillc.backend import Confirmation

GOLDENS = json.loads((Path(__file__).parent / "fixtures/docker-wave-protocol-hook/goldens.json")
                     .read_text())
ROLES = ("orchestrator", "worker-a", "worker-b")


@pytest.fixture
def controller(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> wave.DockerWave:
    ModelBackend.instances = []
    ModelBackend.result_modes = {}
    ModelBackend.stop_observation = Confirmation.CONFIRMED
    ModelBackend.absent_observation = Confirmation.CONFIRMED
    monkeypatch.setattr(wave, "DockerBackend", ModelBackend)
    monkeypatch.setattr(wave.fixture_overlay, "install_codex_guard", lambda *args: {})
    monkeypatch.setattr(wave.DockerWave, "_call", lambda self, argv, **kw: b"")
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    roles = [wave.Role(n, ("python3", "actor.py"), "start", 4) for n in ROLES]
    return wave.DockerWave(attempt_id="hook-wave", image="scripted-image",
                           root=tmp_path / "evidence", fixture=fixture, roles=roles, seconds=30)


def _configs() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    remote = next(b.config for b in ModelBackend.instances if "network" in b.config)
    roles = [b.config for b in ModelBackend.instances if "egress" in b.config]
    return remote, roles


def test_unused_hook_constructs_every_backend_exactly_as_the_parent(
        controller: wave.DockerWave) -> None:
    controller.prepare()
    remote, roles = _configs()
    assert sorted(remote) == GOLDENS["remote"]
    assert len(roles) == len(ROLES)
    for config in roles:
        assert sorted(config) == GOLDENS["role"]
        for key, value in GOLDENS["role_values"].items():
            assert (list(config[key]) if key == "docker_bin" else config[key]) == value
    controller.close()


def test_set_lease_dirs_reach_only_the_role_backends(controller: wave.DockerWave,
                                                     tmp_path: Path) -> None:
    dirs = {name: tmp_path / "leases" / name for name in ROLES}
    controller.task_protocol_dirs = dict(dirs)
    controller.prepare()
    remote, roles = _configs()
    assert sorted(remote) == GOLDENS["remote"]
    assert sorted(config["task_protocol_host_dir"] for config in roles) == sorted(dirs.values())
    for config in roles:
        assert sorted(set(config) - {"task_protocol_host_dir"}) == GOLDENS["role"]
    controller.close()
