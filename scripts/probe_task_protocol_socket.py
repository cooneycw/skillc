#!/usr/bin/env python3
"""Physical facts behind the #620 PR-B task-protocol socket (B0).

The accepted design (`docs/specs/evaluation-facility/task-protocol-stream.md`,
section 2) depends on three deployment facts it marks UNVERIFIED. This probe
measures them against a REAL Docker daemon. It does not qualify the controller,
which does not exist yet; it qualifies what the kernel and daemon do.

- F1 `ro-mount`: a candidate in its sandbox can connect to a read-only
  controller-mounted socket and cannot replace, rename or add to it. Both mount
  shapes are measured, because the shape is an open owner decision: the socket
  FILE bound read-only (`file`) and its parent DIRECTORY bound read-only (`dir`).
- F2 `peercred`: from `SO_PEERCRED`'s pid, the controller identifies the owned
  sandbox, and does NOT identify a host process or a second sandbox running
  under the same candidate uid. Two bases are reported separately: the peer's
  PID-namespace inode (needs ptrace-level access to another uid's /proc, so a
  root controller) and its cgroup v2 membership under the systemd driver
  (world-readable). A start-time check around every read refuses a pid that
  exited or was reused. A uid never identifies on its own.
- F1 recreate (`recreate:file`, `recreate:dir`): the host unlinks and re-binds
  a lease socket while the sandbox lives. This is a characterization, not a
  gate: it reports `reaches-new` or `dead-end` per shape, because a single-file
  bind pins the old inode. The owner's 2026-11-20 ruling uses it to choose the
  mount shape.
- F3 `exclusive`: with one endpoint per sandbox, each sandbox reaches only its
  own listener, and an audit of the daemon's own mount records refuses a
  deliberate mis-mount.

Every fact has three outcomes, and they are never merged:

- `holds` - the built-in control disagreed as required, every reading was
  readable, and the fact is true;
- `fails` - the control disagreed as required, every reading was readable, and
  the fact is FALSE (the most important answer this probe can give);
- `not-covered` - the control did not disagree, or something was unreadable.
  This is UNKNOWN, never a pass and never a failure of the fact.

Each fact runs its built-in control FIRST and reports it. Exit codes: 0 every
requested fact holds; 4 at least one fact fails; 3 nothing fails but at least
one fact is not covered; 2 usage. An unreadable environment record (image
digest, daemon security options, kernel) makes every fact not covered.

Stdlib only, and it imports nothing from `skillc` (a committed test checks
both). It never pulls an image: the image must already be present. Every
container it starts is labelled, removed on exit, and confirmed absent.

    python3 -I scripts/probe_task_protocol_socket.py all --image <present image>
    python3 -I scripts/probe_task_protocol_socket.py selftest

`selftest` needs no Docker. It classifies the committed readings in
`controls/task-protocol-probe/cases.json` and checks each against its expected
outcome. It is the only part CI runs; physical readings come from a separate,
authorized run of the subcommands above.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import secrets
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
from collections.abc import Callable, Mapping
from pathlib import Path, PurePosixPath
from typing import Any

PROBE = "task-protocol-socket"
VERSION = 1
HOLDS, FAILS, NOT_COVERED = "holds", "fails", "not-covered"
#: Recreate is a characterization, not a gate: which shape survives the
#: controller re-binding a lease's socket while the sandbox lives.
REACHES_NEW, DEAD_END = "reaches-new", "dead-end"
EXIT = {HOLDS: 0, FAILS: 4, NOT_COVERED: 3}

#: The candidate identity of `skillc.backend` (tests pin the two together; this
#: script may not import skillc).
CANDIDATE_UID = 10001
CANDIDATE_GID = 10001
#: The accepted design's fixed in-sandbox endpoint.
TARGET_DIR = "/run/skillc-task-protocol"
TARGET_SOCKET = TARGET_DIR + "/channel.sock"
LABEL = "skillc.probe=" + PROBE
DOCKER_TIMEOUT = 60.0
HOLD_SECONDS = 120
REPLACE_OPS = ("unlink", "rename-away", "rename-over", "create-file", "bind-socket", "mkdir")
ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CASES = ROOT / "controls" / "task-protocol-probe" / "cases.json"

# ---------------------------------------------------------------- classifiers
# Pure functions of readings. Any malformed reading is NOT_COVERED, never an
# exception and never a verdict about the fact.


def _verdict(outcome: str, reasons: list[str]) -> dict[str, Any]:
    return {"verdict": outcome, "reasons": sorted(set(reasons))}


def _is_bool(value: object) -> bool:
    return type(value) is bool


def _int(value: object) -> bool:
    return type(value) is int


def classify_environment(env: object) -> dict[str, Any]:
    """The receipt must name what was measured. Unreadable is not covered."""
    if not isinstance(env, Mapping):
        return _verdict(NOT_COVERED, ["environment-unreadable"])
    reasons = []
    for key in ("image_id", "kernel", "daemon_kernel", "server_version", "cgroup_driver"):
        if not isinstance(env.get(key), str) or not env[key]:
            reasons.append("unreadable:" + key)
    if not isinstance(env.get("security_options"), list):
        reasons.append("unreadable:security_options")
    if env.get("daemon_local") is not True:
        reasons.append("daemon-not-local")
    return _verdict(NOT_COVERED if reasons else HOLDS, reasons)


def _replaced(attempts: object) -> list[str] | None:
    if not isinstance(attempts, Mapping) or set(attempts) != set(REPLACE_OPS):
        return None
    if not all(isinstance(v, str) and v for v in attempts.values()):
        return None
    return [op for op in REPLACE_OPS if attempts[op] == "ok"]


def _sandbox_reading(reading: object) -> dict[str, Any] | None:
    if not isinstance(reading, Mapping):
        return None
    needed = ("connect", "reply", "mount", "attempts", "reconnect", "reply_after")
    if any(key not in reading for key in needed):
        return None
    if not _is_bool(reading["connect"]) or not _is_bool(reading["reconnect"]):
        return None
    if reading["mount"] not in ("ro", "rw", "absent"):
        return None
    replaced = _replaced(reading["attempts"])
    if replaced is None:
        return None
    return {**reading, "replaced": replaced}


def classify_f1_control(control: object, tag: object) -> dict[str, Any]:
    """Run FIRST. With no mount the probe must see no endpoint; with a
    writable, world-writable mount it must see the endpoint as replaceable.
    If it cannot see either, its later 'cannot replace' means nothing."""
    if not isinstance(control, Mapping) or not isinstance(tag, str):
        return _verdict(NOT_COVERED, ["control-unreadable"])
    absent = _sandbox_reading(control.get("absent"))
    writable = _sandbox_reading(control.get("writable"))
    if absent is None or writable is None:
        return _verdict(NOT_COVERED, ["control-unreadable"])
    reasons = []
    if absent["connect"] or absent["mount"] != "absent":
        reasons.append("control-blind:absent-endpoint-seen")
    if not writable["connect"] or writable["reply"] != tag:
        reasons.append("control-blind:writable-endpoint-unreachable")
    if writable["mount"] != "rw" or not writable["replaced"]:
        reasons.append("control-blind:writable-endpoint-not-replaceable")
    return _verdict(NOT_COVERED if reasons else HOLDS, reasons)


def classify_f1_shape(reading: object, tag: object) -> dict[str, Any]:
    sandbox = _sandbox_reading(reading)
    if sandbox is None or not isinstance(tag, str):
        return _verdict(NOT_COVERED, ["reading-unreadable"])
    reasons = []
    if sandbox["mount"] == "absent":
        return _verdict(NOT_COVERED, ["mount-not-found-in-mountinfo"])
    if not sandbox["connect"]:
        reasons.append("connect-refused-with-mount-present")
    elif sandbox["reply"] != tag:
        reasons.append("reached-another-listener")
    if sandbox["mount"] != "ro":
        reasons.append("mount-rw")
    reasons.extend("replace-succeeded:" + op for op in sandbox["replaced"])
    if sandbox["connect"] and (not sandbox["reconnect"] or sandbox["reply_after"] != tag):
        reasons.append("endpoint-lost-after-replace-attempts")
    return _verdict(FAILS if reasons else HOLDS, reasons)


def _peer(reading: object) -> dict[str, Any] | None:
    if not isinstance(reading, Mapping):
        return None
    if not all(_int(reading.get(k)) for k in ("pid", "uid", "gid")):
        return None
    ns, cgroup, stable = reading.get("ns_inode"), reading.get("cgroup"), reading.get("start_stable")
    if ns is not None and not _int(ns):
        return None
    if cgroup is not None and not isinstance(cgroup, str):
        return None
    if stable is not None and not _is_bool(stable):
        return None
    return {**reading, "ns_inode": ns, "cgroup": cgroup, "start_stable": stable}


_SCOPE = re.compile(r"docker-([0-9a-f]{64})\.scope")


def container_of(cgroup: object) -> str | None:
    """The container id in a cgroup v2 file under the systemd driver, `""`
    for a readable v2 file in no docker scope, or None when unreadable or in
    any other layout (cgroupfs, v1, hybrid). Only the first form identifies."""
    if not isinstance(cgroup, str):
        return None
    lines = cgroup.splitlines()
    if len(lines) != 1 or not lines[0].startswith("0::/"):
        return None
    found = [m.group(1) for part in lines[0][4:].split("/") if (m := _SCOPE.fullmatch(part))]
    if len(found) > 1 or (not found and "/docker" in lines[0]):
        return None
    return found[0] if found else ""


def identify_ns(peer: Mapping[str, Any], owned: object, uid: int, gid: int) -> str:
    """'yes', 'no' or 'unknown' on the PID-namespace basis."""
    if (not _int(owned) or peer["pid"] <= 0 or peer["ns_inode"] is None
            or peer["start_stable"] is not True):
        return "unknown"
    if peer["ns_inode"] != owned:
        return "no"
    return "yes" if (peer["uid"], peer["gid"]) == (uid, gid) else "no"


def identify_cgroup(peer: Mapping[str, Any], owned: object, uid: int, gid: int) -> str:
    """'yes', 'no' or 'unknown' on the cgroup-membership basis. `owned` is
    the owned container's id, already confirmed against its init process."""
    if not isinstance(owned, str) or peer["pid"] <= 0 or peer["start_stable"] is not True:
        return "unknown"
    found = container_of(peer["cgroup"])
    if found is None:
        return "unknown"
    if found != owned:
        return "no"
    return "yes" if (peer["uid"], peer["gid"]) == (uid, gid) else "no"


def _basis(identify_fn: Callable[[Mapping[str, Any], object, int, int], str], owned: object,
           peers: Mapping[str, Mapping[str, Any]], uid: int, gid: int) -> dict[str, Any]:
    """One basis: its own control (a host process must read 'no'), then the
    owned sandbox must read 'yes' and the same-uid sibling 'no'."""
    seen = identify_fn(peers["host"], owned, uid, gid)
    control = _verdict(HOLDS if seen == "no" else NOT_COVERED,
                       [] if seen == "no" else ["control-blind:host-peer-" + seen])
    if control["verdict"] != HOLDS:
        return {**control, "control": control}
    reasons = []
    for name, expected in (("owned", "yes"), ("sibling", "no")):
        got = identify_fn(peers[name], owned, uid, gid)
        if got == "unknown":
            return {**_verdict(NOT_COVERED, [name + "-peer-unknown"]), "control": control}
        if got != expected:
            reasons.append(f"{name}-peer-identified-{got}")
    if (peers["owned"]["uid"], peers["owned"]["gid"]) != (uid, gid):
        reasons.append("owned-peer-credentials-mapped")
    return {**_verdict(FAILS if reasons else HOLDS, reasons), "control": control}


def classify_f2(reading: object) -> dict[str, Any]:
    """Two bases, reported separately: the peer's PID-namespace inode (needs
    ptrace-level access to another uid's /proc entries) and its cgroup v2
    membership (world-readable). The fact holds only if a READABLE basis
    discriminates; if no basis is readable it is not covered; if any readable
    basis fails, including a disagreement, it fails. A uid never suffices."""
    if not isinstance(reading, Mapping):
        return _verdict(NOT_COVERED, ["reading-unreadable"])
    uid, gid = reading.get("uid"), reading.get("gid")
    peers = {k: _peer(reading.get(k + "_peer")) for k in ("host", "owned", "sibling")}
    if not (_int(uid) and _int(gid)) or any(v is None for v in peers.values()):
        return _verdict(NOT_COVERED, ["reading-unreadable"])
    assert isinstance(uid, int) and isinstance(gid, int)
    checked = {k: v for k, v in peers.items() if v is not None}
    owned_id = reading.get("owned_id")
    init = container_of(reading.get("owned_init_cgroup"))
    cgroup_owned = owned_id if isinstance(owned_id, str) and init == owned_id else None
    bases = {"ns": _basis(identify_ns, reading.get("owned_ns_inode"), checked, uid, gid),
             "cgroup": _basis(identify_cgroup, cgroup_owned, checked, uid, gid)}
    if cgroup_owned is None:
        bases["cgroup"] = {**_verdict(NOT_COVERED, ["owned-container-not-in-docker-scope"]),
                           "control": _verdict(NOT_COVERED, ["control-unreadable"])}
    verdicts = [b["verdict"] for b in bases.values()]
    if FAILS in verdicts:
        outcome = _verdict(FAILS, [f"{k}:{r}" for k, b in bases.items() for r in b["reasons"]
                                   if b["verdict"] == FAILS])
    elif HOLDS in verdicts:
        outcome = _verdict(HOLDS, [])
    else:
        outcome = _verdict(NOT_COVERED, [f"{k}:{r}" for k, b in bases.items()
                                         for r in b["reasons"]])
    control = _verdict(HOLDS if any(b["control"]["verdict"] == HOLDS for b in bases.values())
                       else NOT_COVERED, [])
    return {**outcome, "bases": bases, "control": control}


def _is_within(path: str, root: str) -> bool:
    p, r = PurePosixPath(path), PurePosixPath(root)
    return p == r or r in p.parents


def audit(inspected: object, leases: object) -> tuple[bool | None, list[str]]:
    """Exclusivity from the daemon's OWN mount records, never the requested
    launch options. Returns (exclusive, reasons); None means unreadable."""
    if not isinstance(inspected, Mapping) or not isinstance(leases, Mapping) or not leases:
        return None, ["audit-unreadable"]
    if set(inspected) != set(leases):
        return None, ["audit-population-mismatch"]
    reasons: list[str] = []
    for name, record in inspected.items():
        source = leases[name]
        if not isinstance(record, Mapping) or not isinstance(source, str):
            return None, ["audit-unreadable"]
        mounts, host = record.get("Mounts"), record.get("HostConfig")
        if not isinstance(mounts, list) or not isinstance(host, Mapping):
            return None, ["audit-unreadable"]
        endpoint = []
        for mount in mounts:
            if not isinstance(mount, Mapping):
                return None, ["audit-unreadable"]
            src, dst = mount.get("Source"), mount.get("Destination")
            if not isinstance(src, str) or not isinstance(dst, str):
                return None, ["audit-unreadable"]
            if src.endswith("docker.sock") or "docker.sock" in dst:
                reasons.append(f"{name}:docker-socket-mounted")
            for other, other_source in leases.items():
                if other != name and (_is_within(src, other_source)
                                      or _is_within(other_source, src)):
                    reasons.append(f"{name}:reaches-lease-of:{other}")
            if _is_within(dst, TARGET_DIR) or _is_within(TARGET_DIR, dst):
                endpoint.append(mount)
        if len(endpoint) != 1:
            reasons.append(f"{name}:endpoint-mounts:{len(endpoint)}")
        elif endpoint[0].get("Source") != source or endpoint[0].get("RW") is not False:
            reasons.append(f"{name}:endpoint-not-own-readonly")
        if host.get("Privileged") is not False:
            reasons.append(f"{name}:privileged")
        for key in ("PidMode", "IpcMode", "NetworkMode", "UsernsMode"):
            value = host.get(key)
            if not isinstance(value, str):
                return None, ["audit-unreadable"]
            if value == "host" or value.startswith("container:"):
                reasons.append(f"{name}:{key}:{value}")
    return not reasons, reasons


def _reached(value: object) -> list[str] | None:
    if not isinstance(value, list) or not all(isinstance(t, str) for t in value):
        return None
    return sorted(set(value))


def classify_f3(reading: object, audit_fn: Callable[[object, object], tuple[bool | None, list[str]]]
                = audit) -> dict[str, Any]:
    """Control FIRST: the deliberate mis-mount (A's endpoint also mounted in
    B) must be refused by the audit and must be SEEN by B's reach scan.
    Then the healthy pair must audit exclusive and reach only its own."""
    if not isinstance(reading, Mapping):
        return _verdict(NOT_COVERED, ["reading-unreadable"])
    mis, healthy = reading.get("mismount"), reading.get("healthy")
    if not isinstance(mis, Mapping) or not isinstance(healthy, Mapping):
        return _verdict(NOT_COVERED, ["reading-unreadable"])
    exclusive, _ = audit_fn(mis.get("inspect"), mis.get("leases"))
    mis_reached = mis.get("reached")
    reach_b = _reached(mis_reached.get("b") if isinstance(mis_reached, Mapping) else None)
    if exclusive is None or reach_b is None:
        control = _verdict(NOT_COVERED, ["control-unreadable"])
        return {**control, "control": control}
    reasons = []
    if exclusive:
        reasons.append("control-blind:audit-accepted-mismount")
    if "a" not in reach_b:
        reasons.append("control-blind:reach-scan-missed-mismount")
    control = _verdict(NOT_COVERED if reasons else HOLDS, reasons)
    if reasons:
        return {**control, "control": control}
    exclusive, audit_reasons = audit_fn(healthy.get("inspect"), healthy.get("leases"))
    reached = healthy.get("reached")
    if exclusive is None or not isinstance(reached, Mapping):
        return {**_verdict(NOT_COVERED, ["reading-unreadable"]), "control": control}
    reasons = [] if exclusive else ["audit-refused-healthy:" + r for r in audit_reasons]
    for role in ("a", "b"):
        got = _reached(reached.get(role))
        if got is None:
            return {**_verdict(NOT_COVERED, ["reading-unreadable"]), "control": control}
        if got != [role]:
            reasons.append(f"{role}-reached:{','.join(got) or 'nothing'}")
    return {**_verdict(FAILS if reasons else HOLDS, reasons), "control": control}


def classify_recreate(reading: object) -> dict[str, Any]:
    """The host unlinks and re-binds the lease socket while the sandbox lives.
    Control FIRST: the sandbox reached the original listener, and a host-side
    connect reaches the new one. Only then is the sandbox's reconnect read:
    the new listener (`reaches-new`) or nothing (`dead-end`)."""
    if not isinstance(reading, Mapping):
        return _verdict(NOT_COVERED, ["reading-unreadable"])
    before, host_after = reading.get("before"), reading.get("host_after")
    after = reading.get("after")
    reasons = []
    if before != "m":
        reasons.append("control:sandbox-never-reached-original")
    if host_after != "m2":
        reasons.append("control:new-listener-not-up")
    control = _verdict(NOT_COVERED if reasons else HOLDS, reasons)
    if reasons:
        return {**control, "control": control}
    if not isinstance(after, Mapping) or not _is_bool(after.get("connect")):
        outcome = _verdict(NOT_COVERED, ["reading-unreadable"])
    elif not after["connect"]:
        outcome = _verdict(DEAD_END, [])
    elif after.get("reply") == "m2":
        outcome = _verdict(REACHES_NEW, [])
    else:
        outcome = _verdict(NOT_COVERED, ["reached-unexpected-listener"])
    return {**outcome, "control": control}


def classify(fact: str, readings: object) -> dict[str, Any]:
    """Dispatch used by both the live run and `selftest`."""
    if not isinstance(readings, Mapping):
        return _verdict(NOT_COVERED, ["reading-unreadable"])
    if fact == "environment":
        return classify_environment(readings)
    if fact.startswith("ro-mount:"):
        control = classify_f1_control(readings.get("control"), readings.get("tag"))
        if control["verdict"] != HOLDS:
            return {**control, "control": control}
        measured = classify_f1_shape(readings.get("measured"), readings.get("tag"))
        return {**measured, "control": control}
    if fact.startswith("recreate:"):
        return classify_recreate(readings)
    if fact == "peercred":
        return classify_f2(readings)
    if fact.startswith("exclusive:"):
        return classify_f3(readings)
    return _verdict(NOT_COVERED, ["unknown-fact"])


def overall(verdicts: list[str]) -> str:
    """Characterizations (`reaches-new`, `dead-end`) are covered readings and
    gate nothing; any other value than the three outcomes is not covered."""
    verdicts = [v for v in verdicts if v not in (REACHES_NEW, DEAD_END)] or (
        [HOLDS] if verdicts else [])
    if not verdicts or any(v not in EXIT for v in verdicts):
        return NOT_COVERED
    if FAILS in verdicts:
        return FAILS
    return NOT_COVERED if NOT_COVERED in verdicts else HOLDS


# --------------------------------------------------------------- measurement

#: Runs inside the sandbox as the candidate uid; stdlib, prints one JSON line.
_IN_SANDBOX = r'''
import errno, json, os, socket, sys
cfg = json.loads(sys.argv[1])
sock_path, target, scan = cfg["socket"], cfg["mount_target"], cfg.get("scan", False)
def ping(path):
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.settimeout(5)
        s.connect(path); s.sendall(b"ping\n"); data = s.recv(256); s.close()
        return True, data.decode("ascii", "replace").strip()
    except OSError:
        return False, None
def mount_state():
    try:
        with open("/proc/self/mountinfo") as f:
            for line in f:
                parts = line.split()
                if len(parts) > 5 and parts[4] == target:
                    return "ro" if "ro" in parts[5].split(",") else "rw"
        return "absent"
    except OSError:
        return None
def attempt(fn):
    try:
        fn(); return "ok"
    except OSError as exc:
        return errno.errorcode.get(exc.errno, "E?")
out = {}
out["connect"], out["reply"] = ping(sock_path)
out["mount"] = mount_state()
d = os.path.dirname(sock_path)
def bind_new():
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try: s.bind(os.path.join(d, "probe.sock"))
    finally: s.close()
def rename_over():
    tmp = "/tmp/probe-replacement"
    with open(tmp, "w"): pass
    os.rename(tmp, sock_path)
def create():
    os.close(os.open(os.path.join(d, "probe-file"), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
ops = {"unlink": lambda: os.unlink(sock_path),
       "rename-away": lambda: os.rename(sock_path, os.path.join(d, "probe-moved")),
       "rename-over": rename_over, "create-file": create, "bind-socket": bind_new,
       "mkdir": lambda: os.mkdir(os.path.join(d, "probe-dir"))}
out["attempts"] = {k: attempt(v) for k, v in ops.items()} if cfg.get("attempts", True) else None
out["reconnect"], out["reply_after"] = ping(sock_path)
if scan:
    # A host listener can only appear through a mount, so walk every mount
    # point except the image root and the kernel filesystems.
    import stat as st
    seen, budget, points = set(), 20000, []
    try:
        with open("/proc/self/mountinfo") as f:
            for line in f:
                point = line.split()[4]
                if point != "/" and not point.startswith(("/proc", "/sys", "/dev")):
                    points.append(point)
    except (OSError, IndexError):
        points = None
    def probe(p):
        try:
            if st.S_ISSOCK(os.lstat(p).st_mode):
                ok, tag = ping(p)
                if ok and tag: seen.add(tag)
        except OSError:
            pass
    for point in points or []:
        probe(point)
        for root, dirs, files in os.walk(point, onerror=lambda e: None):
            for name in files + dirs:
                budget -= 1
                probe(os.path.join(root, name))
            if budget <= 0: break
    out["reached"] = sorted(seen) if points is not None and budget > 0 else None
print(json.dumps(out, sort_keys=True))
'''


def read_cgroup(pid: int) -> str | None:
    try:
        with open(f"/proc/{pid}/cgroup") as stream:
            return stream.read(4096)
    except (OSError, UnicodeDecodeError):
        return None


class Listener:
    """One host-side endpoint. Replies with its tag, and records each peer's
    kernel credentials, PID-namespace inode and start-time stability, all read
    BEFORE the reply so the peer is still blocked in recv()."""

    def __init__(self, path: Path, tag: str) -> None:
        self.path, self.tag = path, tag
        self.peers: list[dict[str, Any]] = []
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.bind(str(path))
        os.chmod(path, 0o666)
        self.sock.listen(64)
        self.sock.settimeout(0.2)
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    @staticmethod
    def _start(pid: int) -> str | None:
        try:
            return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
        except (OSError, IndexError):
            return None

    def _serve(self) -> None:
        while not self.stop.is_set():
            try:
                conn, _ = self.sock.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            with conn:
                conn.settimeout(5)
                try:
                    pid, uid, gid = struct.unpack(
                        "3i", conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                    before = self._start(pid)
                    try:
                        ns: int | None = os.stat(f"/proc/{pid}/ns/pid").st_ino
                    except OSError:
                        ns = None
                    cgroup = read_cgroup(pid)
                    conn.recv(256)
                    after = self._start(pid)
                    # A pid that exited or was reused between SO_PEERCRED and
                    # these reads changes or loses its start time.
                    stable = None if before is None or after is None else before == after
                    self.peers.append({"pid": pid, "uid": uid, "gid": gid, "ns_inode": ns,
                                       "cgroup": cgroup, "start_before": before,
                                       "start_after": after, "start_stable": stable})
                    conn.sendall(self.tag.encode() + b"\n")
                except OSError:
                    continue

    def close(self) -> None:
        self.stop.set()
        self.sock.close()
        self.thread.join(timeout=5)


class Docker:
    def __init__(self, image: str, runner: Callable[..., subprocess.CompletedProcess[str]]
                 = subprocess.run) -> None:
        self.image, self.runner = image, runner
        self.started: list[str] = []

    def call(self, *args: str) -> str | None:
        try:
            done = self.runner(["docker", *args], capture_output=True, text=True,
                               timeout=DOCKER_TIMEOUT, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return done.stdout if done.returncode == 0 else None

    def start(self, mounts: list[str]) -> str | None:
        name = "skillc-probe-tp-" + secrets.token_hex(6)
        self.started.append(name)
        out = self.call(*run_argv(name, self.image, mounts))
        return name if out is not None else None

    def exec_json(self, name: str, cfg: Mapping[str, Any]) -> dict[str, Any] | None:
        out = self.call("exec", "--user", f"{CANDIDATE_UID}:{CANDIDATE_GID}", name,
                        "python3", "-I", "-S", "-c", _IN_SANDBOX, json.dumps(dict(cfg)))
        try:
            value = json.loads(out) if out is not None else None
        except ValueError:
            return None
        return value if isinstance(value, dict) else None

    def inspect(self, name: str) -> Any:
        out = self.call("inspect", "--format", "{{json .}}", name)
        try:
            return json.loads(out) if out is not None else None
        except ValueError:
            return None

    def cleanup(self) -> list[str]:
        """Remove every started container and CONFIRM it is gone."""
        left = []
        for name in self.started:
            self.call("rm", "-f", name)
            if self.call("inspect", "--format", "{{.Id}}", name) is not None:
                left.append(name)
        return left


def run_argv(name: str, image: str, mounts: list[str]) -> list[str]:
    """A held, unprivileged, network-less sandbox; never pulls."""
    argv = ["run", "-d", "--pull", "never", "--name", name, "--label", LABEL,
            "--network", "none", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--user", f"{CANDIDATE_UID}:{CANDIDATE_GID}"]
    for mount in mounts:
        argv += ["--mount", mount]
    return argv + ["--entrypoint", "python3", image, "-I", "-S", "-c",
                   f"import time; time.sleep({HOLD_SECONDS})"]


def bind(source: Path, target: str, readonly: bool) -> str:
    return f"type=bind,source={source},target={target}" + (",readonly" if readonly else "")


def shape_mount(shape: str, lease_dir: Path, readonly: bool = True) -> str:
    if shape == "dir":
        return bind(lease_dir, TARGET_DIR, readonly)
    return bind(lease_dir / "channel.sock", TARGET_SOCKET, readonly)


def shape_target(shape: str) -> str:
    return TARGET_DIR if shape == "dir" else TARGET_SOCKET


def environment(docker: Docker) -> dict[str, Any]:
    # Only the scheme is recorded: a receipt must not carry a host name.
    docker_host = os.environ.get("DOCKER_HOST", "")
    env: dict[str, Any] = {"kernel": platform.release() or None,
                           "docker_host_scheme": docker_host.split("://", 1)[0] or None}
    endpoint = docker.call("context", "inspect", "--format", "{{.Endpoints.docker.Host}}")
    env["daemon_endpoint_scheme"] = (endpoint or "").strip().split("://", 1)[0] or None
    # Bind mounts and SO_PEERCRED only mean something beside the daemon.
    env["daemon_local"] = (env["daemon_endpoint_scheme"] == "unix"
                           and (not docker_host or docker_host.startswith("unix://")))
    image = docker.call("image", "inspect", "--format", "{{json .}}", docker.image)
    info = docker.call("info", "--format", "{{json .}}")
    try:
        img = json.loads(image) if image else {}
        inf = json.loads(info) if info else {}
    except ValueError:
        img, inf = {}, {}
    env["image_id"] = img.get("Id") if isinstance(img, dict) else None
    env["image_repo_digests"] = img.get("RepoDigests") if isinstance(img, dict) else None
    if isinstance(inf, dict):
        env.update({"security_options": inf.get("SecurityOptions"),
                    "cgroup_driver": inf.get("CgroupDriver"),
                    "cgroup_version": inf.get("CgroupVersion"),
                    "server_version": inf.get("ServerVersion"),
                    "daemon_kernel": inf.get("KernelVersion")})
    return env


class Lab:
    """Host side of one run: a private base directory with one lease
    directory per sandbox. Removed on exit."""

    def __init__(self) -> None:
        self.base = Path(tempfile.mkdtemp(prefix="skillc-tp-"))
        os.chmod(self.base, 0o700)
        self.listeners: list[Listener] = []

    def lease(self, tag: str, mode: int = 0o755) -> Path:
        lease_dir = self.base / tag
        lease_dir.mkdir()
        os.chmod(lease_dir, mode)
        self.listeners.append(Listener(lease_dir / "channel.sock", tag))
        return lease_dir

    def close(self) -> None:
        for listener in self.listeners:
            listener.close()
        shutil.rmtree(self.base, ignore_errors=True)


def _sandbox(docker: Docker, mounts: list[str], cfg: Mapping[str, Any]) -> dict[str, Any] | None:
    name = docker.start(mounts)
    return None if name is None else docker.exec_json(name, cfg)


def measure_ro_mount(docker: Docker, shape: str) -> dict[str, Any]:
    lab = Lab()
    try:
        cfg = {"socket": TARGET_SOCKET, "mount_target": shape_target(shape)}
        absent = _sandbox(docker, [], cfg)
        writable_dir = lab.lease("w", mode=0o777)
        writable = _sandbox(docker, [shape_mount("dir", writable_dir, readonly=False)],
                            {**cfg, "mount_target": TARGET_DIR})
        measured_dir = lab.lease("m")
        measured = _sandbox(docker, [shape_mount(shape, measured_dir)], cfg)
        return {"tag": "m", "control": {"absent": absent, "writable": _retag(writable, "w", "m")},
                "measured": measured}
    finally:
        lab.close()


def measure_recreate(docker: Docker, shape: str) -> dict[str, Any]:
    """Revocation-by-replace, measured: re-bind the lease socket on the host
    while the sandbox lives, then reconnect from inside."""
    lab = Lab()
    try:
        lease_dir = lab.lease("m")
        cfg = {"socket": TARGET_SOCKET, "mount_target": shape_target(shape), "attempts": False}
        name = docker.start([shape_mount(shape, lease_dir)])
        if name is None:
            return {}
        first = docker.exec_json(name, cfg)
        path = lease_dir / "channel.sock"
        lab.listeners.pop().close()
        path.unlink()
        lab.listeners.append(Listener(path, "m2"))
        second = docker.exec_json(name, cfg)
        return {"before": (first or {}).get("reply"), "host_after": _host_ping(path),
                "after": None if second is None else {"connect": second.get("connect"),
                                                       "reply": second.get("reply")}}
    finally:
        lab.close()


def _retag(reading: dict[str, Any] | None, old: str, new: str) -> dict[str, Any] | None:
    """The writable control's listener has its own tag; compare it as `m`."""
    if reading is None:
        return None
    return {**reading, **{k: new for k in ("reply", "reply_after") if reading.get(k) == old}}


def measure_peercred(docker: Docker) -> dict[str, Any]:
    lab = Lab()
    try:
        lease_dir = lab.lease("a")
        listener = lab.listeners[0]
        mount = [shape_mount("file", lease_dir)]
        owned = docker.start(mount)
        sibling = docker.start(mount)
        reading: dict[str, Any] = {"uid": CANDIDATE_UID, "gid": CANDIDATE_GID}
        if owned is None or sibling is None:
            return reading
        pid = docker.call("inspect", "--format", "{{.State.Pid}}", owned)
        ident = docker.call("inspect", "--format", "{{.Id}}", owned)
        sibling_ident = docker.call("inspect", "--format", "{{.Id}}", sibling)
        reading["owned_id"] = ident.strip() if ident else None
        reading["sibling_id"] = sibling_ident.strip() if sibling_ident else None
        try:
            init = int(pid or "0")
        except ValueError:
            init = 0
        try:
            reading["owned_ns_inode"] = os.stat(f"/proc/{init}/ns/pid").st_ino if init else None
        except OSError:
            reading["owned_ns_inode"] = None
        reading["owned_init_cgroup"] = read_cgroup(init) if init > 0 else None
        cfg = {"socket": TARGET_SOCKET, "mount_target": TARGET_SOCKET, "attempts": False}
        for key, run in (("host_peer", lambda: _host_ping(lease_dir / "channel.sock")),
                         ("owned_peer", lambda: docker.exec_json(owned, cfg)),
                         ("sibling_peer", lambda: docker.exec_json(sibling, cfg))):
            count = len(listener.peers)
            run()
            reading[key] = listener.peers[count] if len(listener.peers) > count else None
        return reading
    finally:
        lab.close()


def _host_ping(path: Path) -> str | None:
    """A separate host process, so its PID is not this probe's."""
    try:
        code = ("import socket,sys;s=socket.socket(socket.AF_UNIX);s.settimeout(5);"
                "s.connect(sys.argv[1]);s.sendall(b'ping\\n');"
                "print(s.recv(64).decode().strip())")
        done = subprocess.run([sys.executable, "-I", "-S", "-c", code, str(path)],
                              capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return (done.stdout.strip() or None) if done.returncode == 0 else None


def measure_exclusive(docker: Docker, shape: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for case, mismount in (("mismount", True), ("healthy", False)):
        lab = Lab()
        try:
            dir_a, dir_b = lab.lease("a"), lab.lease("b")
            mounts_a = [shape_mount(shape, dir_a)]
            mounts_b = [shape_mount(shape, dir_b)]
            if mismount:
                mounts_b.append(bind(dir_a if shape == "dir" else dir_a / "channel.sock",
                                     "/run/probe-misplaced" + ("" if shape == "dir" else ".sock"),
                                     True))
            names = {"a": docker.start(mounts_a), "b": docker.start(mounts_b)}
            cfg = {"socket": TARGET_SOCKET, "mount_target": shape_target(shape),
                   "attempts": False, "scan": True}
            reached = {role: (docker.exec_json(n, cfg) or {}).get("reached") if n else None
                       for role, n in names.items()}
            inspected = {role: docker.inspect(n) if n else None for role, n in names.items()}
            source = {"a": dir_a, "b": dir_b} if shape == "dir" else {
                "a": dir_a / "channel.sock", "b": dir_b / "channel.sock"}
            result[case] = {"inspect": {r: _audit_view(v) for r, v in inspected.items()},
                            "leases": {r: os.path.realpath(p) for r, p in source.items()},
                            "reached": reached}
        finally:
            lab.close()
    return result


def _audit_view(record: object) -> object:
    """Keep only what the audit reads, so a receipt carries no environment."""
    if not isinstance(record, Mapping):
        return None
    host = record.get("HostConfig") if isinstance(record.get("HostConfig"), Mapping) else {}
    mounts = record.get("Mounts") if isinstance(record.get("Mounts"), list) else None
    return {"Mounts": None if mounts is None else [
                {k: m.get(k) for k in ("Type", "Source", "Destination", "RW")}
                for m in mounts if isinstance(m, Mapping)],
            "HostConfig": {k: host.get(k) for k in
                           ("Privileged", "PidMode", "IpcMode", "NetworkMode", "UsernsMode")}}


FACTS: dict[str, Callable[[Docker], dict[str, Any]]] = {
    "ro-mount:file": lambda d: measure_ro_mount(d, "file"),
    "ro-mount:dir": lambda d: measure_ro_mount(d, "dir"),
    "recreate:file": lambda d: measure_recreate(d, "file"),
    "recreate:dir": lambda d: measure_recreate(d, "dir"),
    "peercred": measure_peercred,
    "exclusive:file": lambda d: measure_exclusive(d, "file"),
    "exclusive:dir": lambda d: measure_exclusive(d, "dir"),
}
SUBCOMMANDS = {"ro-mount": ["ro-mount:file", "ro-mount:dir", "recreate:file", "recreate:dir"],
               "peercred": ["peercred"],
               "exclusive": ["exclusive:file", "exclusive:dir"], "all": list(FACTS)}


def live(image: str, facts: list[str], docker: Docker | None = None) -> dict[str, Any]:
    docker = docker or Docker(image)
    script = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    receipt: dict[str, Any] = {"probe": PROBE, "version": VERSION, "script_sha256": script}
    env = environment(docker)
    receipt["environment"] = {"readings": env, **classify_environment(env)}
    results: dict[str, Any] = {}
    try:
        for fact in facts:
            try:
                readings = FACTS[fact](docker)
            except Exception as exc:  # noqa: BLE001 - a crashed measurement is not covered
                readings = {"measurement_error": type(exc).__name__}
            verdict = classify(fact, readings)
            if receipt["environment"]["verdict"] != HOLDS:
                verdict = {**verdict, "verdict": NOT_COVERED,
                           "reasons": sorted(set(verdict["reasons"]) | {"environment-not-covered"})}
            results[fact] = {**verdict, "readings": readings}
    finally:
        left = docker.cleanup()
    receipt["facts"] = results
    receipt["containers_left"] = left
    outcome = overall([r["verdict"] for r in results.values()])
    if left and outcome == HOLDS:
        outcome = NOT_COVERED
    receipt["outcome"] = outcome
    return receipt


def selftest(cases_path: Path) -> dict[str, Any]:
    try:
        cases = json.loads(cases_path.read_text())
        assert isinstance(cases, list) and cases
    except (OSError, ValueError, AssertionError):
        return {"selftest": "unreadable", "outcome": NOT_COVERED}
    results, seen = [], set()
    for case in cases:
        got = classify(case["fact"], case["readings"])["verdict"]
        results.append({"name": case["name"], "expect": case["expect"], "got": got})
        seen.add(case["expect"])
    ok = (all(r["got"] == r["expect"] for r in results)
          and seen == {HOLDS, FAILS, NOT_COVERED, REACHES_NEW, DEAD_END})
    return {"selftest": "pass" if ok else "fail", "cases": results,
            "outcome": HOLDS if ok else FAILS}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in SUBCOMMANDS:
        p = sub.add_parser(name)
        p.add_argument("--image", required=True, help="an image ALREADY present; never pulled")
    st = sub.add_parser("selftest")
    st.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    args = parser.parse_args(argv)
    if args.command == "selftest":
        report = selftest(args.cases)
        print(json.dumps(report, sort_keys=True))
        return {HOLDS: 0, NOT_COVERED: 3}.get(report["outcome"], 1)
    receipt = live(args.image, SUBCOMMANDS[args.command])
    print(json.dumps(receipt, sort_keys=True))
    return EXIT[receipt["outcome"]]


if __name__ == "__main__":
    sys.exit(main())
