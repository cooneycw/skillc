"""The task-protocol mount in `compose_run_argv` (#620 PR-B, B5b), checked
against argv captured from the PARENT commit.

This module imports only `compose_run_argv` and names the mount target as a
literal, so it collects against the parent's docker_backend.py. There, the
no-keyword calls must equal the goldens (proving they are the parent's
argv), and every call with the new keyword fails with TypeError: a real red
on the parent, not a collection error."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from skillc import docker_backend
from skillc.docker_backend import compose_run_argv

ROOT = Path(__file__).resolve().parent.parent
GOLDENS = json.loads((ROOT / "tests/fixtures/task-protocol-argv/goldens.json").read_text())[
    "goldens"]
TARGET = "/run/skillc-task-protocol"
TRIGGER_TARGET = "/run/skillc/trigger.sock"


def _inputs(golden: dict[str, Any]) -> dict[str, Any]:
    inputs = dict(golden["inputs"])
    if inputs.get("trigger_socket_host_path") is not None:
        inputs["trigger_socket_host_path"] = Path(inputs["trigger_socket_host_path"])
    return inputs


@pytest.mark.parametrize("golden", GOLDENS, ids=lambda g: g["name"])
def test_the_goldens_are_the_parent_argv(golden: dict[str, Any]) -> None:
    """Passes on the parent and on this change: the no-keyword argv."""
    assert compose_run_argv(**_inputs(golden)) == golden["argv"]


@pytest.mark.parametrize("golden", GOLDENS, ids=lambda g: g["name"])
def test_the_argv_is_byte_identical_when_the_mount_is_unused(golden: dict[str, Any]) -> None:
    assert compose_run_argv(**_inputs(golden), task_protocol_host_dir=None) == golden["argv"]


@pytest.mark.parametrize("golden", GOLDENS, ids=lambda g: g["name"])
def test_the_mount_is_one_readonly_bind_at_the_fixed_target(golden: dict[str, Any]) -> None:
    argv = compose_run_argv(**_inputs(golden), task_protocol_host_dir=Path("/srv/lease/ep-1"))
    mount = f"type=bind,source=/srv/lease/ep-1,target={TARGET},readonly"
    assert argv.count(mount) == 1 and argv[argv.index(mount) - 1] == "--mount"
    position = argv.index(mount)
    assert argv[:position - 1] + argv[position + 1:] == golden["argv"]
    assert position < argv.index("-w")
    trigger = [a for a in argv if a.endswith(f"target={TRIGGER_TARGET}")]
    if trigger:
        assert argv.index(trigger[0]) < position


def test_the_target_is_not_a_parameter() -> None:
    import inspect
    params = inspect.signature(compose_run_argv).parameters
    assert "task_protocol_host_dir" in params
    assert not any("target" in name for name in params)


_BAD_SOURCES: list[tuple[str, Any, type[Exception]]] = [
    ("comma-adds-option", Path("/srv/lease/x,readonly=false"), ValueError),
    ("comma-retargets", Path("/srv/lease/x,dst=/etc"), ValueError),
    ("equals", Path("/srv/lease/x=y"), ValueError),
    ("double-quote", Path('/srv/lease/"x"'), ValueError),
    ("newline", Path("/srv/lease/x\ny"), ValueError),
    ("carriage-return", Path("/srv/lease/x\ry"), ValueError),
    ("nul", Path("/srv/lease/x\x00y"), ValueError),
    ("relative", Path("srv/lease/x"), ValueError),
    ("not-normalized", Path("/srv/lease/../etc"), ValueError),
    ("not-a-path", "/srv/lease/x", TypeError),
]


@pytest.mark.parametrize("source,error", [(s, e) for _, s, e in _BAD_SOURCES],
                         ids=[n for n, _, _ in _BAD_SOURCES])
def test_a_mount_source_that_could_alter_the_spec_is_refused(source: Any,
                                                            error: type[Exception]) -> None:
    with pytest.raises(error):
        compose_run_argv(**_inputs(GOLDENS[0]), task_protocol_host_dir=source)


def test_a_composer_without_the_source_check_is_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(docker_backend, "_mount_source", lambda path: str(path))
    argv = compose_run_argv(**_inputs(GOLDENS[0]),
                            task_protocol_host_dir=Path("/srv/lease/x,readonly=false"))
    assert any("readonly=false" in a for a in argv)  # the injection the check exists to stop
