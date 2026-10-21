"""#508: the project-gate witness against a REAL daemon and the REAL trial
image. No model is called: the container's network is `none`, and the
"agent" here is a plain exec carrying the agent's PATH.

`tests/test_project_gate_witness.py` and `tests/test_make_gate_shim.py` cover
the pieces with fakes; this is the evidence that, in a real container:

1. the shim is placed root-owned and verified, its directory holds only
   `make`, and under the agent's PATH `codex` still resolves to the
   nested-codex guard;
2. the agent's `make check` reaches the controller, which runs each stage
   itself: the reply is byte-identical to the real make's (the committed
   golden), and the record holds the controller's own stage outcomes;
3. a non-gate invocation runs the image's real make and is logged
   subject-reported, with no gate run;
4. the nested-gate red: a controller exec running `make lint` adds ZERO runs,
   and the same exec with the shim directory first on PATH adds one.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import uuid
from collections.abc import Mapping
from pathlib import Path

import pytest
from conftest import LIVE_DOCKER_DAEMON_TIMEOUT
from test_codex_guard_live import LIMITS, _trial_image
from test_codex_guard_live import pytestmark as _live_marks
from test_make_gate_shim import CELLS, MAKEFILE, SCRIPTS, _err, _goldens, _out, declaration

from skillc import attempt_guard as ag
from skillc import docker_backend as d
from skillc import fixture_overlay as fo
from skillc import project_gate as pg
from skillc.fixture_service import dispatch
from skillc.gate_witness import GateWitness

#: real_docker, and skipped only where no Docker daemon is reachable (the PR
#: CI runner has none) - the guard's own live marks.
pytestmark = _live_marks


@pytest.mark.timeout(1800)
def test_the_project_gate_is_witnessed_in_a_real_trial_container() -> None:
    image, built = _trial_image()
    try:
        _run(image)
    finally:
        if built:
            subprocess.run(["docker", "image", "rm", "-f", image], capture_output=True, check=False)


def _run(image: str) -> None:
    guard = ag.AttemptGuard("a-live")
    log: list[Mapping[str, object]] = []
    holder: dict[str, GateWitness] = {}

    def run_gate(request: Mapping[str, object]) -> Mapping[str, object]:
        return holder["w"].decide(request)

    def passthrough(request: Mapping[str, object]) -> Mapping[str, object]:
        log.append(dict(request))
        return {"logged": True}

    base = Path(tempfile.mkdtemp(prefix="sk-project-gate-live-"))
    trigger_dir = Path(tempfile.mkdtemp(prefix="sk-pg-trig-"))
    backend = d.DockerBackend(
        image=image, base_dir=base, network="none", witness_io=True, daemon_timeout=LIVE_DOCKER_DAEMON_TIMEOUT,
        trigger_decide=guard.watch(dispatch({
            "run_gate": (run_gate, frozenset({"op", "gate", "cwd", "make_args", "make_env"})),
            pg.PASSTHROUGH_OP: (passthrough, frozenset({"op", "argv", "cwd", "exit_code", "why"})),
            **guard.routes()})),
        trigger_socket_dir=trigger_dir,
    )
    handle = backend.prepare(f"a-project-gate-live-{uuid.uuid4().hex[:12]}")
    try:
        env_raw = backend.controller_output(handle, ["env", "-0"], LIMITS)
        env: Mapping[str, str] = dict(e.split("=", 1) for e in env_raw.decode().split("\0") if e)
        _args, codes = CELLS["test-fails"]
        surface: dict[str, object] = {"Makefile": MAKEFILE}
        for sid, script in SCRIPTS.items():
            surface[script] = (f"import sys\nprint({_out(sid).decode()[:-1]!r})\n"
                               f"print({_err(sid).decode()[:-1]!r}, file=sys.stderr)\nsys.exit({codes[sid]})\n").encode()
        backend.install(handle, surface)
        holder["w"] = GateWitness(
            declared_gates={pg.GATE: [pg.REAL_MAKE, "check"]},
            tree_digest_fn=lambda: "sha256:" + "0" * 64, backend=backend, handle=handle, limits=LIMITS,
            gate_exclusivity=False, exclusivity_basis="bypass is not excluded",
            declared_env={pg.GATE: dict(env)}, workspace_root=d.CONTAINER_WORKSPACE,
            staged={pg.GATE: pg.StagedRunner(declaration())})

        # 1. placement, after the guard, as agent_trial orders it
        guard.bind(backend, handle, env)
        pg.install_make_shim(backend, handle, env)
        pg.verify_agent_path(backend, handle, env, codex_guard=fo.CODEX_GUARD_PATH)
        agent_env = {**env, "PATH": pg.agent_path(env)}

        # 2. the agent's own `make check`
        reply = backend.exec_in_attempt(handle, ["make", "check"], LIMITS, env=agent_env, cwd=d.CONTAINER_WORKSPACE)
        golden = _goldens()["test-fails"]
        assert reply.reason == "exited", reply
        assert ((reply.stdout or b"").decode(), (reply.stderr or b"").decode(), reply.exit_code) == (
            golden["stdout"], golden["stderr"], golden["exit"])
        [run] = json.loads(holder["w"].finalize("peek").to_json_bytes())["gates"][pg.GATE]["runs"]
        assert {k: v["outcome"] for k, v in run["stages"]["stages"].items()} == {
            "lint": "passed", "test": "failed", "typecheck": "not-run"}

        # 3. a non-gate invocation: the real make, logged, no run
        dry = backend.exec_in_attempt(handle, ["make", "-n", "check"], LIMITS, env=agent_env,
                                      cwd=d.CONTAINER_WORKSPACE)
        assert dry.reason == "exited" and dry.exit_code == 0, dry
        assert b"python3 ci/lint.py" in (dry.stdout or b"")
        assert [(e["argv"], e["why"]) for e in log] == [(["-n", "check"], "not-a-gate-invocation")]

        # 4. nested: the controller's env never re-enters; the shim's PATH does
        before = len(json.loads(holder["w"].finalize("peek").to_json_bytes())["gates"][pg.GATE]["runs"])
        plan = ["sh", "-c", "make lint >/dev/null 2>&1; true"]
        backend.exec_in_attempt(handle, plan, LIMITS, env=dict(env), cwd=d.CONTAINER_WORKSPACE)
        after_controller = len(json.loads(holder["w"].finalize("peek").to_json_bytes())["gates"][pg.GATE]["runs"])
        backend.exec_in_attempt(handle, plan, LIMITS, env=agent_env, cwd=d.CONTAINER_WORKSPACE)
        after_shim = len(json.loads(holder["w"].finalize("peek").to_json_bytes())["gates"][pg.GATE]["runs"])
        assert (after_controller - before, after_shim - after_controller) == (0, 1)
    finally:
        guard.finish(backend, handle)
        backend.destroy(handle)
