"""#620 PR-B B8c: the producer lifecycle on a REAL daemon, model-free.

B8c qualifies the producer lifecycle and the projection feeding assembly v2;
the v2 verdict through a real export is #626's rehearsal.

Two scripted roles run the whole ProtocolWave lifecycle as the real-Docker
lane's NON-ROOT service account (the peer verifier's cgroup basis), with no
sudo and no skip. The parametrized pair is IDENTICAL except for one argument:
in "residue" the worker plants a leftover branch and a stash. The clean run
must read CLEAN and the residue run NOT_CLEAN, with exactly the planted
items as the added clutter, so the census verdict differs only by the plant.

The census models DockerWave's topology honestly. The fixture remote lives in
its own controller container, so it is a census role ("fixture") whose bare
repository is read where it actually is. Each worker role names its own
clone's git directory as its remote scope, since the network remote is not on
its filesystem. The `observations` write-back is skillc's own harness residue
(#549, #761), declared allowed rather than called clean.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from conftest import LIVE_DOCKER_DAEMON_TIMEOUT
from test_codex_guard_live import _trial_image

from skillc import clutter, clutter_controller, live_wave
from skillc import docker_wave as dw
from skillc import task_protocol_adapter as adapter
from skillc import task_protocol_journal as tj
from skillc import wave_protocol_run as wpr
from skillc.task_protocol_lease import Slot
from skillc.wave_attachment import WAVE_ROOT

pytestmark = [pytest.mark.real_docker,
              pytest.mark.skipif(shutil.which("docker") is None, reason="real-Docker CI lane only"),
              pytest.mark.timeout(1800)]
ROLES = ("integrator", "worker")
ACTOR = Path(__file__).parent / "fixtures" / "wave-protocol-live" / "protocol_actor.py"
DECL = "sha256:" + "d" * 64
DEADLINE = "sha256:" + "ab" * 32
SECONDS = 300
HEALTHY_EVENTS = ["leased", "prepared", "census-setup", "audited", "bootstrapped", "barrier",
                  "frozen", "serving", "turns-done", "fenced", "census-after", "closed",
                  "sealed", "census-final"]


@pytest.fixture(scope="module")
def image() -> Iterator[str]:
    tag, built = _trial_image()
    try:
        yield tag
    finally:
        if built:
            subprocess.run(["docker", "image", "rm", "-f", tag], capture_output=True, timeout=60,
                           check=False)


def _fixture(root: Path) -> Path:
    root.mkdir()
    shutil.copyfile(ACTOR, root / ACTOR.name)
    for argv in (["git", "init", "-b", "main"], ["git", "add", "."],
                 ["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                  "commit", "-m", "protocol fixture"]):
        subprocess.run(argv, cwd=root, check=True, capture_output=True, timeout=20)
    return root


def _scope(checkout: str, gitdir: str, remote: str) -> dict[str, Any]:
    return {"checkout": checkout, "gitdir": gitdir, "remotes": {"origin": remote},
            "coordination": {kind: [WAVE_ROOT + "/" + kind] for kind in clutter.COORDINATION_KINDS},
            "mailbox_marker": "cc-flow-wave-msg", "temp_roots": ["/tmp"]}


def _policy() -> clutter.Policy:
    roles = {r: _scope("/work", "/work/.git", "/work/.git") for r in ROLES}
    roles["fixture"] = _scope("/fixture/seed", "/fixture/seed/.git", "/fixture/repo.git")
    allowed = [{"surface": r + "/workspace", "key": "file:/work/observations"} for r in ROLES]
    return clutter.parse_policy({"schema_version": 1, "daemon_scope": "controller-isolated",
                                 "roles": roles, "shared_roots": [WAVE_ROOT],
                                 "settle_point": clutter.SETTLE_POINT, "settle_seconds": 0,
                                 "delivered": [], "declared_allowed": allowed})


class _Census:
    """clutter_controller.Session over the wave's REAL containers, built at
    setup time when the handles exist."""

    def __init__(self, wave: dw.DockerWave) -> None:
        self.wave = wave
        self.session: Any = None
        self.policy = _policy()

    def setup(self) -> None:
        sources = {name: (state.backend, state.handle) for name, state in self.wave.states.items()}
        assert self.wave.remote_backend is not None and self.wave.remote is not None
        sources["fixture"] = (self.wave.remote_backend, self.wave.remote)
        inventory = clutter_controller.docker_inventory(self.policy, sources, shared_role="fixture")
        self.session = clutter_controller.Session(inventory)
        self.session.setup()

    def completion(self, role: str) -> None:
        self.session.completion(role)
        if role == ROLES[-1]:
            self.session.completion("fixture")

    def capture_after(self) -> None:
        self.session.capture_after()

    def finalize(self, **kwargs: Any) -> dict[str, Any]:
        report: dict[str, Any] = self.session.finalize(**kwargs)
        return report


def _run(image: str, tmp_path: Path, short: Path, mode: str) -> tuple[dict[str, Any], float]:
    roles = [dw.Role(r, ("python3", ACTOR.name, r, mode if r == "worker" else "clean"), "start",
                     90, ("offer", "ack", "complete")) for r in ROLES]
    wave = dw.DockerWave(attempt_id="tp-live-" + uuid.uuid4().hex[:10], image=image,
                         root=tmp_path / "evidence", fixture=_fixture(tmp_path / "fixture"),
                         roles=roles, seconds=SECONDS, daemon_timeout=LIVE_DOCKER_DAEMON_TIMEOUT)
    slots = [Slot("slot-" + r, r, "task-" + r, 0, 1, "nonce-" + r) for r in ROLES]
    run = wpr.ProtocolWave(wave, slots=slots, declaration_digest=DECL, deadline_digest=DEADLINE,
                           deadline_seconds=SECONDS, lease_root=short / "leases",
                           journal_root=tmp_path / "journal", census=_Census(wave),
                           freeze=lambda sessions: dict(sessions))
    started = time.monotonic()
    report = run.run()
    return report, time.monotonic() - started


def _projection(report: dict[str, Any]) -> dict[str, Any]:
    bound = report["protocol_v2"]
    plan = live_wave.WavePlan(report["wave"]["attempt_id"], tuple(
        live_wave.RoleBinding(r, report["wave"]["attempt_id"] + "-" + r, report["sessions"][r],
                              "task-" + r, 0, 1, "nonce-" + r, ("output.json",)) for r in ROLES),
        ROLES[0], float(SECONDS))
    return adapter.adapt(Path(bound["root"]), tj.parse_reference(bound["reference"]),
                         tj.parse_context(bound["context"]),
                         adapter.parse_inventory(bound["inventory"]), plan,
                         round(plan.deadline * 1e9), adapter.parse_clock_join(bound["clock_join"]))


@pytest.fixture
def short() -> Iterator[Path]:
    path = Path(tempfile.mkdtemp(prefix="tpl8-", dir="/tmp"))
    yield path
    shutil.rmtree(path, ignore_errors=True)


@pytest.mark.parametrize("mode", ["clean", "residue"])
def test_the_producer_lifecycle_on_a_real_daemon(image: str, tmp_path: Path, short: Path,
                                                 mode: str) -> None:
    report, seconds = _run(image, tmp_path, short, mode)
    print(json.dumps({"mode": mode, "wall_seconds": round(seconds, 1)}))  # for the PR body
    # 1. The lifecycle order, with nothing unknown on the protocol side.
    assert report["events"] == HEALTHY_EVENTS, report["unknown"]
    assert report["unknown"] == []
    # 2. The audit passed on the daemon's own inspect records.
    assert report["audit"]["ok"] is True and report["audit"]["digest"].startswith("sha256:")
    # 3. The real journal sealed CLOSED and projects ack + complete for both roles.
    result = _projection(report)
    assert result["status"] == "CAPTURED" and result["diagnostic"]["seal_outcome"] == "CLOSED"
    for role in ROLES:
        rows = [json.loads(x) for x in (result["projections"][role] or b"").splitlines()]
        assert [r["op"] for r in rows] == ["ack", "complete"], role
    # 4/5. The real census, bound to confirmed stops: CLEAN, or NOT_CLEAN by the plant.
    census = report["census"]
    assert all(s["stop"] == "confirmed" for s in report["wave"]["roles"].values())
    clutter_items = {(i["surface"], i["key"]) for i in census["additions"]["clutter"]}
    if mode == "clean":
        assert census["status"] == "CLEAN", census.get("unknown")
        assert clutter_items == set()
    else:
        assert census["status"] == "NOT_CLEAN"
        planted = {s for s in clutter_items if "leftover-worker" in s[1]}
        stashes = {s for s in clutter_items if s[0] == "worker/stashes"}
        assert planted and stashes, clutter_items
        # Only the worker's planted branch and stash are clutter.
        assert {s[0] for s in clutter_items} <= {"worker/local-branches", "worker/remote-branches",
                                                 "worker/stashes"}, clutter_items
