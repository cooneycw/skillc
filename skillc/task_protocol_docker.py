"""Docker placement for the task-protocol stream (#620 PR-B, B5b).

See `docs/specs/evaluation-facility/task-protocol-stream.md`, section 2, and
`task-protocol-qualification.md` for the physical readings this rests on.

- `lease_dir` makes one controller-owned directory per endpoint lease. It holds
  only the receiver's `channel.sock` and is bind-mounted READ-ONLY at
  `docker_backend.TASK_PROTOCOL_DIR`. This is shape B, chosen by the owner's
  2026-11-20 ruling from B0's recreate readings.
- `DockerPeerVerifier` is B5a's `PeerVerifier` for real containers. It maps a
  peer's kernel pid, uid and gid to the full id of the planned container it
  lives in, on two bases B0 qualified:
  - the PID-namespace inode, readable by a root controller;
  - cgroup v2 `docker-<id>.scope` membership under the systemd driver, which
    is world-readable, so it also works for a non-root controller.

  It never identifies on uid alone, since the sandboxes share one candidate
  uid. It refuses a peer whose start time moved during the reads. Two
  readable bases that disagree are no identity.
- `audit` checks the daemon's OWN `docker inspect` records, never the
  requested launch options. Each lease's directory must be mounted read-only
  in its own sandbox only, and nothing else may reach the endpoint or any
  lease directory. The digest it returns is the binding evidence B4 records
  at bind time; B8 wires that.
- `install_client` copies the exact bytes of `task_protocol_client.py` into a
  sandbox through the backend's existing root-owned install primitive. It
  then verifies that the candidate cannot write the file and that the file's
  digest matches. Both arms get the same bytes. There is no image change and
  no new mount.

Only `Id`, `State.Pid`, `Mounts` and `HostConfig` are read from inspect. The
evaluation daemon uses the containerd image store, so no `GraphDriver` /
overlay2 field is assumed to exist.

Stdlib only, per AGENTS.md.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from .backend import CANDIDATE_GID, CANDIDATE_UID
from .docker_backend import TASK_PROTOCOL_DIR

SOCKET_NAME = "channel.sock"
CLIENT_ROOT = "/opt/skillc-task-protocol"
CLIENT_NAME = "skillc-task-protocol"
_SCOPE = re.compile(r"docker-([0-9a-f]{64})\.scope")
_ID = re.compile(r"[0-9a-f]{64}")
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")


class PlacementError(ValueError):
    """A lease directory or install that cannot be established safely."""


# -- lease directories ------------------------------------------------------


def lease_dir(private_root: Path, endpoint_id: str) -> Path:
    """Create this lease's endpoint directory under a private (0700) root
    owned by this process. The directory is 0755, so the candidate can reach
    the socket through the read-only mount, and it is new: an existing path or
    a symlink is refused, never reused."""
    if not _TOKEN.fullmatch(endpoint_id):
        raise PlacementError("bounded endpoint id required")
    private_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = os.lstat(private_root)
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077):
        raise PlacementError("lease root must be a private directory owned by the controller")
    path = private_root / endpoint_id
    path.mkdir(mode=0o755)
    os.chmod(path, 0o755)
    return path


# -- peer identity --------------------------------------------------------------


def container_of(cgroup: object) -> str | None:
    """The container id in a cgroup v2 file under the systemd driver; `""` for
    a readable v2 file in no docker scope; None when unreadable or in any other
    layout (cgroupfs, v1, hybrid, nested scopes). The same rule B0's probe
    qualified."""
    if not isinstance(cgroup, str):
        return None
    lines = cgroup.splitlines()
    if len(lines) != 1 or not lines[0].startswith("0::/"):
        return None
    found = [m.group(1) for part in lines[0][4:].split("/") if (m := _SCOPE.fullmatch(part))]
    if len(found) > 1 or (not found and "/docker" in lines[0]):
        return None
    return found[0] if found else ""


@dataclass(frozen=True)
class _Planned:
    container_id: str
    ns_inode: int | None
    scope: str | None


class Proc(Protocol):
    """The three /proc reads, so tests can supply a fake tree."""

    def start(self, pid: int) -> str | None: ...

    def ns_inode(self, pid: int) -> int | None: ...

    def cgroup(self, pid: int) -> str | None: ...


class HostProc:
    def __init__(self, root: Path = Path("/proc")) -> None:
        self.root = root

    def start(self, pid: int) -> str | None:
        try:
            return (self.root / str(pid) / "stat").read_text().rsplit(")", 1)[1].split()[19]
        except (OSError, IndexError):
            return None

    def ns_inode(self, pid: int) -> int | None:
        try:
            return os.stat(self.root / str(pid) / "ns" / "pid").st_ino
        except OSError:
            return None

    def cgroup(self, pid: int) -> str | None:
        try:
            with open(self.root / str(pid) / "cgroup") as stream:
                return stream.read(4096)
        except (OSError, UnicodeDecodeError):
            return None


Inspect = Callable[[str], Mapping[str, Any] | None]


class DockerPeerVerifier:
    """`runtime_instance(pid, uid, gid)` -> the planned container's full id,
    or None. `containers` names the planned sandboxes, by container name or
    id, as the caller launched them."""

    def __init__(self, containers: list[str], inspect: Inspect, *, proc: Proc | None = None,
                 uid: int = CANDIDATE_UID, gid: int = CANDIDATE_GID) -> None:
        self.names, self.inspect = list(containers), inspect
        self.proc: Proc = proc or HostProc()
        self.uid, self.gid = uid, gid
        self._planned: list[_Planned] | None = None

    def _plan(self) -> list[_Planned]:
        if self._planned is None:
            planned = []
            for name in self.names:
                record = self.inspect(name)
                cid = record.get("Id") if isinstance(record, Mapping) else None
                state = record.get("State") if isinstance(record, Mapping) else None
                pid = state.get("Pid") if isinstance(state, Mapping) else None
                if not (isinstance(cid, str) and _ID.fullmatch(cid)
                        and type(pid) is int and pid > 0):
                    continue
                scope = container_of(self.proc.cgroup(pid))
                planned.append(_Planned(cid, self.proc.ns_inode(pid),
                                        cid if scope == cid else None))
            self._planned = planned
        return self._planned

    def runtime_instance(self, pid: int, uid: int, gid: int) -> str | None:
        if pid <= 0 or (uid, gid) != (self.uid, self.gid):
            return None
        before = self.proc.start(pid)
        if before is None:
            return None
        ns, scope = self.proc.ns_inode(pid), container_of(self.proc.cgroup(pid))
        if self.proc.start(pid) != before:
            return None
        planned = self._plan()
        answers = []
        if ns is not None and any(p.ns_inode is not None for p in planned):
            answers.append(next((p.container_id for p in planned if p.ns_inode == ns), ""))
        if scope is not None and any(p.scope is not None for p in planned):
            answers.append(next((p.container_id for p in planned
                                 if p.scope is not None and p.scope == scope), ""))
        if not answers or len(set(answers)) != 1 or not answers[0]:
            return None
        return answers[0]


# -- exclusivity audit -------------------------------------------------------------


def _within(path: str, root: str) -> bool:
    p, r = PurePosixPath(path), PurePosixPath(root)
    return p == r or r in p.parents


def audit(records: Mapping[str, Mapping[str, Any] | None],
          expected: Mapping[str, tuple[str, str]]) -> tuple[bool, list[str], str]:
    """`records` maps each principal to its container's `docker inspect`
    object; `expected` maps it to (container id, lease dir). Returns
    (exclusive, reasons, mapping digest). Anything unreadable is not
    exclusive."""
    reasons: list[str] = []
    mapping = []
    sources = {p: str(PurePosixPath(d)) for p, (_, d) in expected.items()}
    if set(records) != set(expected) or not expected:
        return False, ["audit-population-mismatch"], ""
    for principal in sorted(expected):
        record, (cid, lease) = records[principal], expected[principal]
        if not isinstance(record, Mapping):
            reasons.append(f"{principal}:inspect-unreadable")
            continue
        mounts, host = record.get("Mounts"), record.get("HostConfig")
        if record.get("Id") != cid:
            reasons.append(f"{principal}:container-id-differs")
        if not isinstance(mounts, list) or not isinstance(host, Mapping):
            reasons.append(f"{principal}:inspect-unreadable")
            continue
        endpoint = []
        for mount in mounts:
            src = mount.get("Source") if isinstance(mount, Mapping) else None
            dst = mount.get("Destination") if isinstance(mount, Mapping) else None
            if not isinstance(src, str) or not isinstance(dst, str):
                reasons.append(f"{principal}:mount-unreadable")
                continue
            if src.endswith("docker.sock") or dst.endswith("docker.sock"):
                reasons.append(f"{principal}:docker-socket-mounted")
            if _within(dst, TASK_PROTOCOL_DIR) or _within(TASK_PROTOCOL_DIR, dst):
                endpoint.append(mount)
            for other, other_src in sources.items():
                if other != principal and (_within(src, other_src) or _within(other_src, src)):
                    reasons.append(f"{principal}:reaches-lease-of:{other}")
            if src != sources[principal] and (_within(src, sources[principal])
                                              or _within(sources[principal], src)):
                reasons.append(f"{principal}:own-lease-aliased")
        if len(endpoint) != 1:
            reasons.append(f"{principal}:endpoint-mounts:{len(endpoint)}")
        else:
            mount = endpoint[0]
            if (mount.get("Source") != sources[principal]
                    or mount.get("Destination") != TASK_PROTOCOL_DIR
                    or mount.get("RW") is not False or mount.get("Type") != "bind"):
                reasons.append(f"{principal}:endpoint-not-own-readonly-bind")
            mapping.append({"principal": principal, "container_id": cid,
                            "source": sources[principal], "destination": TASK_PROTOCOL_DIR})
        if host.get("Privileged") is not False:
            reasons.append(f"{principal}:privileged")
        for key in ("PidMode", "IpcMode", "NetworkMode", "UsernsMode"):
            value = host.get(key)
            if not isinstance(value, str):
                reasons.append(f"{principal}:{key}-unreadable")
            elif value == "host" or value.startswith("container:"):
                reasons.append(f"{principal}:{key}:{value}")
    raw = json.dumps(mapping, sort_keys=True, separators=(",", ":")).encode()
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    return not reasons, sorted(set(reasons)), digest if not reasons else ""


# -- client install ------------------------------------------------------------------


class InstallBackend(Protocol):
    def write_root_owned_file_in_attempt(
            self, handle: object, path: str, content: bytes, mode: int = 0o755,
            timeout: float | None = None) -> bool: ...

    def candidate_can_write_in_attempt(self, handle: object, path: str,
                                       timeout: float | None = None) -> bool | None: ...

    def root_output_in_attempt(self, handle: object, argv: list[str], timeout: float | None = None,
                               max_bytes: int = 1 << 20) -> bytes | None: ...


_DIGEST_PROBE = ("import hashlib,sys\n"
                 "print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())")


def client_bytes() -> bytes:
    return (Path(__file__).resolve().parent / "task_protocol_client.py").read_bytes()


def install_client(backend: InstallBackend, handle: object, content: bytes | None = None,
                   ) -> str | None:
    """Install the client at a root-owned, digest-addressed path and verify
    it; return the in-sandbox path, or None on any failure.

    Stated limit: the digest is read back AS ROOT inside the sandbox
    (`root_output_in_attempt`). The backend has no primitive that returns a
    candidate-side read without `exec_in_attempt`'s workspace write-back,
    which would leave an `observations` file in the candidate's workspace.
    What the candidate can do is checked empirically: it cannot write the file
    or its directory."""
    data = client_bytes() if content is None else content
    digest = hashlib.sha256(data).hexdigest()
    directory = f"{CLIENT_ROOT}/{digest}"
    path = f"{directory}/{CLIENT_NAME}"
    if not backend.write_root_owned_file_in_attempt(handle, path, data, mode=0o555):
        return None
    for target in (path, directory, CLIENT_ROOT):
        if backend.candidate_can_write_in_attempt(handle, target) is not False:
            return None
    read = backend.root_output_in_attempt(handle,
                                          ["python3", "-I", "-S", "-c", _DIGEST_PROBE, path])
    if read is None or read.strip().decode("ascii", "replace") != digest:
        return None
    return path
