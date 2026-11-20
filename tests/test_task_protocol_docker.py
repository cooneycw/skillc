"""Docker placement for the task-protocol stream (#620 PR-B, B5b), without a
daemon: the mount argv, the exclusivity audit over committed inspect records,
the peer verifier over a fake /proc, and the client install over a fake
backend. tests/test_task_protocol_docker_live.py meets a real daemon."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest

from skillc import docker_backend as db
from skillc import task_protocol_docker as tpd

ROOT = Path(__file__).resolve().parent.parent
AUDIT = json.loads((ROOT / "controls/task-protocol-exclusivity/cases.json").read_text())["cases"]
A, B = "a" * 64, "b" * 64


def test_the_backend_threads_its_lease_dir_into_the_keepalive_argv(tmp_path: Path) -> None:
    lease = tmp_path / "ep-1"
    backend = db.DockerBackend(image="img", base_dir=tmp_path / "base",
                               task_protocol_host_dir=lease)
    argv = backend._keepalive_run_argv("skillc-n", "attempt-1")
    assert f"type=bind,source={lease},target=/run/skillc-task-protocol,readonly" in argv
    plain = db.DockerBackend(image="img", base_dir=tmp_path / "base")
    assert not any("skillc-task-protocol" in a for a in plain._keepalive_run_argv("skillc-n", "a"))


# -- lease directories --------------------------------------------------------------


def test_a_lease_dir_is_new_under_a_private_root(tmp_path: Path) -> None:
    root = tmp_path / "leases"
    path = tpd.lease_dir(root, "ep-1")
    assert path == root / "ep-1" and oct(os.stat(path).st_mode & 0o777) == "0o755"
    assert oct(os.stat(root).st_mode & 0o777) == "0o700"
    with pytest.raises(FileExistsError):
        tpd.lease_dir(root, "ep-1")
    with pytest.raises(tpd.PlacementError):
        tpd.lease_dir(root, "../escape")
    os.chmod(root, 0o755)
    with pytest.raises(tpd.PlacementError):
        tpd.lease_dir(root, "ep-2")


# -- exclusivity audit ---------------------------------------------------------------


def _audit(case: dict[str, Any]) -> tuple[bool, list[str], str]:
    expected = {p: (cid, src) for p, (cid, src) in case["expected"].items()}
    return tpd.audit(case["records"], expected)


@pytest.mark.parametrize("case", AUDIT, ids=lambda c: c["name"])
def test_each_committed_inspect_set_audits_as_declared(case: dict[str, Any]) -> None:
    ok, reasons, digest = _audit(case)
    assert ok is case["expect"], reasons
    assert bool(digest) is ok and bool(reasons) is not ok


def test_the_cases_cover_both_verdicts_and_a_legitimate_trigger_socket() -> None:
    assert {c["expect"] for c in AUDIT} == {True, False}
    trigger = next(c for c in AUDIT if c["name"] == "healthy-with-trigger-socket-and-wave-volume")
    assert trigger["expect"] is True


def test_the_mapping_digest_binds_the_actual_mounts() -> None:
    healthy = next(c for c in AUDIT if c["name"] == "healthy-two-sandboxes")
    trigger = next(c for c in AUDIT if c["name"] == "healthy-with-trigger-socket-and-wave-volume")
    assert _audit(healthy)[2] == _audit(trigger)[2]
    other = json.loads(json.dumps(healthy))
    other["records"]["a"]["Id"] = other["expected"]["a"][0] = "c" * 64
    assert _audit(other)[0] and _audit(other)[2] != _audit(healthy)[2]


def _disagrees(audit_fn: Any) -> set[str]:
    original = tpd.audit
    try:
        tpd.audit = audit_fn
        return {c["name"] for c in AUDIT if _audit(c)[0] is not c["expect"]}
    finally:
        tpd.audit = original


def test_an_audit_that_accepts_everything_is_caught() -> None:
    assert "deliberate-mismount-a-in-b" in _disagrees(lambda *_a: (True, [], "sha256:x"))


def test_an_audit_blind_to_other_leases_is_caught() -> None:
    real = tpd.audit

    def blind(records: Any, expected: Any) -> tuple[bool, list[str], str]:
        _, reasons, digest = real(records, expected)
        kept = [r for r in reasons if "reaches-lease-of" not in r and "aliased" not in r]
        return not kept, kept, digest

    assert {"deliberate-mismount-a-in-b", "shared-parent-of-leases"} <= _disagrees(blind)


# -- peer verifier -----------------------------------------------------------------------


class FakeProc:
    def __init__(self) -> None:
        self.table: dict[int, dict[str, Any]] = {}
        self.moving: set[int] = set()
        self.calls: dict[int, int] = {}

    def add(self, pid: int, *, ns: int | None, cgroup: str | None, start: str = "100") -> None:
        self.table[pid] = {"ns": ns, "cgroup": cgroup, "start": start}

    def start(self, pid: int) -> str | None:
        row = self.table.get(pid)
        if row is None:
            return None
        self.calls[pid] = self.calls.get(pid, 0) + 1
        if pid in self.moving and self.calls[pid] > 1:
            return "reused"
        return str(row["start"])

    def ns_inode(self, pid: int) -> int | None:
        row = self.table.get(pid)
        return None if row is None else row["ns"]

    def cgroup(self, pid: int) -> str | None:
        row = self.table.get(pid)
        return None if row is None else row["cgroup"]


def _scope(cid: str) -> str:
    return f"0::/system.slice/docker-{cid}.scope\n"


def _inspect(records: dict[str, dict[str, Any]]) -> Any:
    return lambda name: records.get(name)


def _world(*, root: bool) -> tuple[tpd.DockerPeerVerifier, FakeProc]:
    proc = FakeProc()
    # Container inits; a non-root controller cannot read their ns inode.
    proc.add(1001, ns=4026532001 if root else None, cgroup=_scope(A))
    proc.add(2001, ns=4026532002 if root else None, cgroup=_scope(B))
    # Peers: a process in A, one in B (same candidate uid), a host process.
    proc.add(1050, ns=4026532001 if root else None, cgroup=_scope(A))
    proc.add(2050, ns=4026532002 if root else None, cgroup=_scope(B))
    proc.add(900, ns=4026531836, cgroup="0::/user.slice/user-999.slice/session-1.scope\n")
    records = {"sbx-a": {"Id": A, "State": {"Pid": 1001}},
               "sbx-b": {"Id": B, "State": {"Pid": 2001}}}
    return tpd.DockerPeerVerifier(["sbx-a", "sbx-b"], _inspect(records), proc=proc), proc


@pytest.mark.parametrize("root", [True, False], ids=["root-controller", "non-root-controller"])
def test_each_sandbox_is_identified_and_nothing_else(root: bool) -> None:
    verifier, _ = _world(root=root)
    uid, gid = db.CANDIDATE_UID, db.CANDIDATE_GID
    assert verifier.runtime_instance(1050, uid, gid) == A
    assert verifier.runtime_instance(2050, uid, gid) == B
    assert verifier.runtime_instance(900, uid, gid) is None
    assert verifier.runtime_instance(1050, 999, 999) is None
    assert verifier.runtime_instance(4242, uid, gid) is None
    assert verifier.runtime_instance(0, uid, gid) is None


def test_a_pid_reused_during_the_reads_is_no_identity() -> None:
    verifier, proc = _world(root=True)
    proc.moving.add(1050)
    assert verifier.runtime_instance(1050, db.CANDIDATE_UID, db.CANDIDATE_GID) is None


def test_two_bases_that_disagree_are_no_identity() -> None:
    verifier, proc = _world(root=True)
    proc.add(1060, ns=4026532001, cgroup=_scope(B))
    assert verifier.runtime_instance(1060, db.CANDIDATE_UID, db.CANDIDATE_GID) is None


@pytest.mark.parametrize("cgroup", [f"0::/docker/{A}\n",
                                    f"12:pids:/docker/{A}\n1:name=systemd:/x\n",
                                    None, f"0::/system.slice/docker-{A}.scope/docker-{A}.scope\n"])
def test_a_non_root_controller_refuses_other_cgroup_layouts(cgroup: str | None) -> None:
    verifier, proc = _world(root=False)
    proc.add(1070, ns=None, cgroup=cgroup)
    assert verifier.runtime_instance(1070, db.CANDIDATE_UID, db.CANDIDATE_GID) is None


def test_an_init_outside_its_own_scope_disables_the_cgroup_basis() -> None:
    proc = FakeProc()
    proc.add(1001, ns=None, cgroup=_scope(B))
    proc.add(1050, ns=None, cgroup=_scope(A))
    records = {"sbx-a": {"Id": A, "State": {"Pid": 1001}}}
    verifier = tpd.DockerPeerVerifier(["sbx-a"], _inspect(records), proc=proc)
    assert verifier.runtime_instance(1050, db.CANDIDATE_UID, db.CANDIDATE_GID) is None


def test_a_uid_only_verifier_is_caught() -> None:
    _, proc = _world(root=False)

    class UidOnly(tpd.DockerPeerVerifier):
        def runtime_instance(self, pid: int, uid: int, gid: int) -> str | None:
            return A if (uid, gid) == (self.uid, self.gid) else None

    blind = UidOnly(["sbx-a"], _inspect({}), proc=proc)
    assert blind.runtime_instance(2050, db.CANDIDATE_UID, db.CANDIDATE_GID) == A  # B's process
    honest, _ = _world(root=False)
    assert honest.runtime_instance(2050, db.CANDIDATE_UID, db.CANDIDATE_GID) == B


def test_a_verifier_without_the_start_check_is_caught() -> None:
    verifier, proc = _world(root=True)
    proc.moving.add(1050)
    proc.start = lambda pid: "100" if pid in proc.table else None  # type: ignore[method-assign]
    assert verifier.runtime_instance(1050, db.CANDIDATE_UID, db.CANDIDATE_GID) == A
    honest, honest_proc = _world(root=True)
    honest_proc.moving.add(1050)
    assert honest.runtime_instance(1050, db.CANDIDATE_UID, db.CANDIDATE_GID) is None


def test_an_any_scope_layout_reader_is_caught() -> None:
    real = tpd.container_of

    def lenient(cgroup: object) -> str | None:
        if isinstance(cgroup, str) and "/docker/" in cgroup:
            return cgroup.strip().rsplit("/", 1)[1]
        return real(cgroup)

    try:
        tpd.container_of = lenient
        verifier, proc = _world(root=False)
        proc.add(1080, ns=None, cgroup=f"0::/docker/{A}\n")
        proc.add(1001, ns=None, cgroup=f"0::/docker/{A}\n")
        assert verifier.runtime_instance(1080, db.CANDIDATE_UID, db.CANDIDATE_GID) == A
    finally:
        tpd.container_of = real


# -- client install -------------------------------------------------------------------------


class FakeBackend:
    def __init__(self, *, write: bool = True, writable: str | None = None,
                 digest: str | None = None) -> None:
        self.files: dict[str, bytes] = {}
        self.write, self.writable, self.digest = write, writable, digest

    def write_root_owned_file_in_attempt(self, handle: object, path: str, content: bytes,
                                         mode: int = 0o755, timeout: float | None = None) -> bool:
        assert mode == 0o555
        if self.write:
            self.files[path] = content
        return self.write

    def candidate_can_write_in_attempt(self, handle: object, path: str,
                                       timeout: float | None = None) -> bool | None:
        return path == self.writable

    def root_output_in_attempt(self, handle: object, argv: list[str], timeout: float | None = None,
                               max_bytes: int = 1 << 20) -> bytes | None:
        if self.digest is not None:
            return self.digest.encode() + b"\n"
        data = self.files.get(argv[-1])
        return None if data is None else hashlib.sha256(data).hexdigest().encode() + b"\n"


def test_the_client_installs_at_a_root_owned_digest_path() -> None:
    backend = FakeBackend()
    path = tpd.install_client(backend, object())
    data = tpd.client_bytes()
    digest = hashlib.sha256(data).hexdigest()
    assert path == f"/opt/skillc-task-protocol/{digest}/skillc-task-protocol"
    assert backend.files[path] == data


@pytest.mark.parametrize("backend", [
    FakeBackend(write=False),
    FakeBackend(writable="FILE"),
    FakeBackend(writable="DIR"),
    FakeBackend(writable="/opt/skillc-task-protocol"),
    FakeBackend(digest="0" * 64),
], ids=["write-fails", "file-writable", "dir-writable", "root-writable", "digest-differs"])
def test_any_failed_install_check_returns_none(backend: FakeBackend) -> None:
    digest = hashlib.sha256(tpd.client_bytes()).hexdigest()
    directory = f"/opt/skillc-task-protocol/{digest}"
    backend.writable = {"FILE": f"{directory}/skillc-task-protocol", "DIR": directory}.get(
        backend.writable or "", backend.writable)
    assert tpd.install_client(backend, object()) is None


def test_an_install_that_skips_the_writability_check_is_caught() -> None:
    def blind(backend: Any, handle: object) -> str | None:
        data = tpd.client_bytes()
        path = f"/opt/skillc-task-protocol/{hashlib.sha256(data).hexdigest()}/skillc-task-protocol"
        written = backend.write_root_owned_file_in_attempt(handle, path, data, mode=0o555)
        return path if written else None

    digest = hashlib.sha256(tpd.client_bytes()).hexdigest()
    writable = FakeBackend(writable=f"/opt/skillc-task-protocol/{digest}/skillc-task-protocol")
    assert blind(writable, object()) is not None
    assert tpd.install_client(FakeBackend(writable=writable.writable), object()) is None


def test_a_lease_root_that_could_not_be_mounted_is_refused(tmp_path: Path) -> None:
    with pytest.raises(tpd.PlacementError):
        tpd.lease_dir(tmp_path / "a,readonly=false", "ep-1")
    with pytest.raises(tpd.PlacementError):
        tpd.lease_dir(Path("relative-root"), "ep-1")
    assert not (tmp_path / "a,readonly=false").exists()
