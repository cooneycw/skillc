"""#530: the flow-check route actor, run for real on the host (no container,
no model) against the real placed shims - each ROUTE reaches the witness it
should, and its real exit lands in the transcript in the shape
`launch_evidence.scan` reads:

- `anchored` (CPP_SKILL_DIR set): the bundled shim, `via=bundled:flow-check`;
- `absolute`: the bundled shim too;
- `checkout`: the checkout shim, `via=checkout:flow-check`;
- `anchored-unset`: nothing reaches a shim; the shell's real 126 is evidence.
Plus the actor's refusals: no bundled gate, or `actor-checkout` with no
checkout copy, and the flow-check-only rehearsals on another task.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from skillc import agent_trial as at
from skillc import calibration_run as cr
from skillc import fixture_campaign as fc
from skillc import fixture_live as fl
from skillc import launch_evidence as le

ROOT = Path(__file__).resolve().parent.parent
TASK = ROOT / fl.FLOW_CHECK_TASK_PATH
BUNDLED = ".codex/skills/flow-check/scripts/flow-finish-gate.sh"
CHECKOUT = "Projects/claude-power-pack/scripts/flow-finish-gate.sh"


def _treatment(bundled: tuple[str, ...] = (BUNDLED,), checkout: dict[str, str] | None = None) -> cr.Treatment:
    return cr.Treatment(home_files={}, digest="sha256:" + "0" * 64, receipt_context=None, gate_entrypoint=BUNDLED,
                        bundled_gate_entrypoints=bundled,
                        checkout_gate_entrypoints=checkout if checkout is not None else {CHECKOUT: "flow-check"})


def test_the_actor_s_routes_come_from_the_treatment() -> None:
    argv, home = fl.flow_check_actor(TASK, "rangekit-green", "actor-checkout", _treatment())
    routes = json.loads(home[f"{fc.HOME_DIR}/flow-check-routes.json"])
    assert routes == {"skill_dir": f"{fc.CONTAINER_HOME}/.codex/skills/flow-check",
                      "bundled": f"{fc.CONTAINER_HOME}/{BUNDLED}", "checkout": f"{fc.CONTAINER_HOME}/{CHECKOUT}",
                      "gate": "flow-finish-gate.sh", "anchor_variable": "CPP_SKILL_DIR"}  # the task's declared variable
    assert json.loads(home[f"{fc.HOME_DIR}/actions.json"])["steps"][0]["route"] == "checkout"
    assert argv[1] == f"{fc.CONTAINER_HOME}/{fc.HOME_DIR}/flow_check_actor.py"


@pytest.mark.parametrize("rehearse,route", [("actor", "anchored"), ("actor-nested", "anchored"),
                                            ("actor-bundled", "absolute"), ("actor-checkout", "checkout"),
                                            ("actor-unset", "anchored-unset")])
def test_each_rehearsal_plays_one_route(rehearse: str, route: str) -> None:
    _argv, home = fl.flow_check_actor(TASK, "rangekit-green", rehearse, _treatment())
    assert {s["route"] for s in json.loads(home[f"{fc.HOME_DIR}/actions.json"])["steps"]} == {route}
    assert (f"{fc.HOME_DIR}/{fl.NESTED_REHEARSAL_FILE}" in home) == (rehearse == "actor-nested")


def test_red_the_actor_refuses_without_the_copies_it_needs() -> None:
    with pytest.raises(fl.LiveRefused, match="bundled gate"):
        fl.flow_check_actor(TASK, "rangekit-green", "actor", _treatment(bundled=()))
    with pytest.raises(fl.LiveRefused, match="checkout gate copy"):
        fl.flow_check_actor(TASK, "rangekit-green", "actor-checkout", _treatment(checkout={}))


# --- the actor, run --------------------------------------------------------------------

class _Controller:
    def __init__(self, path: Path) -> None:
        self.requests: list[dict[str, Any]] = []
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(str(path))
        self.server.listen(4)
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self) -> None:
        while True:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            with conn:
                data = b""
                while chunk := conn.recv(65536):
                    data += chunk
                self.requests.append(json.loads(data))
                conn.sendall(json.dumps({"ok": True, "result": {"exit_code": 0, "stdout": "FLOW_FINISH_GATE: ok\n",
                                                                "stderr": ""}}).encode() + b"\n")


@pytest.fixture
def controller(tmp_path: Path) -> Iterator[tuple[_Controller, Path]]:
    sock = tmp_path / "trigger.sock"
    ctl = _Controller(sock)
    yield ctl, sock
    ctl.server.close()


def _run_actor(tmp_path: Path, sock: Path, rehearse: str) -> tuple[Path, Path]:
    """Lay out a home and a /work as the container would, with the real placed
    shims, and run the actor. Paths under the container home are remapped."""
    home, work = tmp_path / "home", tmp_path / "work"
    for rel, via in ((BUNDLED, "bundled:flow-check"), (CHECKOUT, "checkout:flow-check")):
        gate = home / rel
        gate.parent.mkdir(parents=True)
        gate.write_bytes(b"#!" + sys.executable.encode() + b"\n"
                         + at.bundled_gate_shim(at.FLOW_CHECK_BUNDLED_GATE_SHIM_SOURCE.read_bytes(), via))
        gate.chmod(0o755)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "codex").write_text("#!/bin/sh\nexit 0\n")
    (bin_dir / "codex").chmod(0o755)
    (work / "repo").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(work / "repo")], check=True)
    _argv, files = fl.flow_check_actor(TASK, "rangekit-green", rehearse, _treatment())
    for rel, data in files.items():
        text = data.replace(fc.CONTAINER_HOME.encode(), str(home).encode())
        (home / rel).parent.mkdir(parents=True, exist_ok=True)
        (home / rel).write_bytes(text)
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(home), "SKILLC_TRIGGER_SOCKET": str(sock)}
    prompt = ("Write the exact text 'touched:6f40d893a5ef' to a file named '.skillc-canary-result' "
              "in the working directory.")
    done = subprocess.run([sys.executable, str(home / fc.HOME_DIR / "flow_check_actor.py"), prompt],
                          cwd=work, env=env, capture_output=True, text=True, timeout=120, check=False)
    assert done.returncode == 0, done.stderr
    return home, work


def _scan(home: Path) -> dict[str, Any]:
    return le.scan((home / fc.TRANSCRIPT_RELPATH).read_text(), "flow-finish-gate.sh")


@pytest.mark.parametrize("rehearse,via", [("actor", "bundled:flow-check"), ("actor-bundled", "bundled:flow-check"),
                                          ("actor-checkout", "checkout:flow-check")])
def test_a_route_that_reaches_a_copy_is_witnessed_and_leaves_no_launch_evidence(
        controller: tuple[_Controller, Path], tmp_path: Path, rehearse: str, via: str) -> None:
    ctl, sock = controller
    home, work = _run_actor(tmp_path, sock, rehearse)
    assert [(r["gate"], r["via"]) for r in ctl.requests] == [("flow-check-plan", via), ("flow-check-summary", via)]
    assert _scan(home)["failures"] == []
    assert json.loads((work / "repo" / "report.json").read_text())["checks"]["lint"]["status"] == "PASS"


def test_the_unset_route_reaches_no_shim_and_is_launch_evidence(
        controller: tuple[_Controller, Path], tmp_path: Path) -> None:
    ctl, sock = controller
    home, work = _run_actor(tmp_path, sock, "actor-unset")
    assert ctl.requests == []
    [failure] = _scan(home)["failures"]
    assert (failure["exit_code"], failure["phrase"]) == (126, "Not a directory")
    assert {c["status"] for c in json.loads((work / "repo" / "report.json").read_text())["checks"].values()} == {
        "DID-NOT-RUN"}


def test_red_the_flow_check_only_rehearsals_are_refused_on_another_task() -> None:
    assert set(fl.FLOW_CHECK_ONLY_REHEARSALS) <= set(fl.ACTOR_REHEARSALS) <= set(fl.REHEARSALS)
    assert os.path.basename(fl.FLOW_CHECK_TASK_PATH) == "flow-check-route"
