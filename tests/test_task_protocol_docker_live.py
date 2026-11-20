"""#620 PR-B B5b against a real daemon: mount shape B, the exclusivity audit,
the Docker peer verifier and the installed client, model-free.

Runs on the real-Docker CI lane as its NON-ROOT service account, where the
peer verifier stands on the cgroup v2 basis (B0's non-root reading). Under a
root controller the PID-namespace basis must also hold on its own. Nothing
here needs sudo, and no model is started.
"""

from __future__ import annotations

import itertools
import json
import os
import shutil
import subprocess
import tempfile
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from conftest import LIVE_DOCKER_DAEMON_TIMEOUT
from test_codex_guard_live import _trial_image

from skillc import task_protocol_client as client
from skillc import task_protocol_docker as tpd
from skillc import task_protocol_journal as tj
from skillc.backend import Limits
from skillc.docker_backend import DockerBackend
from skillc.task_protocol_lease import Inventory, Leases, Slot
from skillc.task_protocol_receiver import Receiver
from skillc.task_protocol_state import Machine, Offer, Plan

pytestmark = [pytest.mark.real_docker,
              pytest.mark.skipif(shutil.which("docker") is None, reason="real-Docker CI lane only"),
              pytest.mark.timeout(1800)]
E = "sha256:" + "e" * 64


@pytest.fixture(scope="module")
def image() -> Iterator[str]:
    tag, built = _trial_image()
    try:
        yield tag
    finally:
        if built:
            subprocess.run(["docker", "image", "rm", "-f", tag], capture_output=True, timeout=60,
                           check=False)


def _inspect(name: str) -> dict[str, Any] | None:
    done = subprocess.run(["docker", "inspect", "--format", "{{json .}}", name],
                          capture_output=True, text=True, timeout=LIVE_DOCKER_DAEMON_TIMEOUT,
                          check=False)
    if done.returncode != 0:
        return None
    value = json.loads(done.stdout)
    return value if isinstance(value, dict) else None


class _Sandboxes:
    def __init__(self, image: str, work: Path) -> None:
        self.image, self.work = image, work
        self.started: list[tuple[DockerBackend, object]] = []

    def start(self, label: str, lease: Path) -> tuple[DockerBackend, Any]:
        backend = DockerBackend(image=self.image, base_dir=self.work / label,
                                daemon_timeout=LIVE_DOCKER_DAEMON_TIMEOUT,
                                task_protocol_host_dir=lease)
        handle = backend.prepare(f"tp-live-{label}-{uuid.uuid4().hex[:8]}")
        self.started.append((backend, handle))
        return backend, handle

    def close(self) -> list[str]:
        left = []
        for backend, handle in self.started:
            backend.destroy(handle)
            if backend.confirm_absent(handle).name != "CONFIRMED":
                left.append(str(handle))
        return left


def _call(backend: DockerBackend, handle: Any, path: str, *args: str) -> tuple[int | None, Any]:
    result = backend.exec_in_attempt(handle, ["python3", "-I", "-S", path, *args], Limits(60))
    receipt = client.parse_receipt(result.stdout or b"")
    return result.exit_code, receipt


def test_shape_b_audit_verifier_and_client_meet_a_real_daemon(image: str, tmp_path: Path) -> None:
    short = Path(tempfile.mkdtemp(prefix="tpl-", dir="/tmp"))
    sandboxes = _Sandboxes(image, tmp_path)
    receiver: Receiver | None = None
    try:
        inventory = Inventory("attempt-live", "sha256:" + "a" * 64,
                              (Slot("p-a", "worker-a", "task-a", 0, 1, "n-a"),
                               Slot("p-b", "worker-b", "task-b", 0, 1, "n-b")), 0)
        count = itertools.count(1)
        leases = Leases(inventory, token=lambda: f"ep-{next(count)}")
        lease_a, lease_b = leases.issue("p-a"), leases.issue("p-b")
        root = short / "leases"
        dir_a = tpd.lease_dir(root, lease_a.endpoint_id)
        dir_b = tpd.lease_dir(root, lease_b.endpoint_id)

        context = tj.Context("attempt-live", "sha256:" + "a" * 64, inventory.digest,
                             "sha256:" + "c" * 64, "skillc-live", inventory.principals)
        journal = tj.Journal(tmp_path / "journal", context, 0)
        machine = Machine(Plan((Offer("p-a", "o-a"), Offer("p-b", "o-b")), 1 << 62))

        backend_a, handle_a = sandboxes.start("a", dir_a)
        backend_b, handle_b = sandboxes.start("b", dir_b)
        # A deliberately mis-mounted sandbox: A's lease directory again.
        backend_m, handle_m = sandboxes.start("m", dir_a)
        records = {p: _inspect(h.name) for p, h in (("p-a", handle_a), ("p-b", handle_b),
                                                     ("p-m", handle_m))}
        ids = {p: r["Id"] for p, r in records.items() if r is not None}
        assert set(ids) == {"p-a", "p-b", "p-m"}

        # The audit reads the daemon's own records, before any offer.
        real = {p: os.path.realpath(d) for p, d in (("p-a", dir_a), ("p-b", dir_b))}
        ok, reasons, digest = tpd.audit({p: records[p] for p in ("p-a", "p-b")},
                                        {p: (ids[p], real[p]) for p in ("p-a", "p-b")})
        assert ok, reasons
        mis_ok, mis_reasons, _ = tpd.audit(
            {"p-a": records["p-a"], "p-m": records["p-m"]},
            {"p-a": (ids["p-a"], real["p-a"]), "p-m": (ids["p-m"], str(short / "unused"))})
        assert not mis_ok and any("reaches-lease-of" in r for r in mis_reasons), mis_reasons

        for principal in ("p-a", "p-b"):
            journal.append("binding", **leases.bind(principal, runtime_instance=ids[principal],
                                                     session_id=f"sess-{principal}",
                                                     evidence_digest=digest))
        journal.append("barrier", **leases.barrier())

        verifier = tpd.DockerPeerVerifier([handle_a.name, handle_b.name, handle_m.name], _inspect)
        receiver = Receiver(leases, machine, journal, verifier)
        receiver.serve(lease_a, dir_a / tpd.SOCKET_NAME)
        receiver.serve(lease_b, dir_b / tpd.SOCKET_NAME)

        paths = {}
        for label, (backend, handle) in (("a", (backend_a, handle_a)), ("b", (backend_b, handle_b)),
                                         ("m", (backend_m, handle_m))):
            installed = tpd.install_client(backend, handle)
            assert installed is not None, f"client install failed in {label}"
            paths[label] = installed
        assert len(set(paths.values())) == 1  # the same bytes in every sandbox

        code, receipt = _call(backend_a, handle_a, paths["a"], "offer", "--request", "1")
        assert code == client.EXIT_DECIDED and receipt and receipt["decision"] == "offered"
        code, receipt = _call(backend_b, handle_b, paths["b"], "offer", "--request", "1")
        assert code == client.EXIT_DECIDED and receipt and receipt["decision"] == "offered"
        # The mis-mounted sandbox reaches A's endpoint but is not A.
        code, receipt = _call(backend_m, handle_m, paths["m"], "offer", "--request", "1")
        assert code == client.EXIT_REJECTED and receipt["reason"] == "unauthenticated-peer"

        if os.geteuid() == 0:
            class NsOnly(tpd.HostProc):
                def cgroup(self, pid: int) -> str | None:
                    return None

            alone = tpd.DockerPeerVerifier([handle_a.name], _inspect, proc=NsOnly())
            receiver.verifier = alone
            code, receipt = _call(backend_a, handle_a, paths["a"], "offer", "--request", "1")
            assert receipt and receipt["decision"] == "offered", "ns basis alone must hold as root"

        receiver.fence()
        assert receiver.stop()
        result = tj.verify(tmp_path / "journal", receiver.seal(), context)
        assert result["status"] == "CAPTURED"
        rejected = [r for r in result["records"] if r["kind"] == "rejection"]
        assert [(r["principal"], r["reason"]) for r in rejected] == [(None, "unauthenticated-peer")]
        assert result["coverage"]["p-a"] == "unknown" and result["coverage"]["p-b"] == "complete"
    finally:
        if receiver is not None:
            receiver.stop()
        left = sandboxes.close()
        shutil.rmtree(short, ignore_errors=True)
    assert left == []
