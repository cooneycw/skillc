"""Installed-only opt-in policy, execution, exact population and private custody (#576)."""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class OptIn:
    env: tuple[str, str]
    nodes: tuple[str, ...]
    seconds: int = 2400
    free_bytes: int = 10 * 1024**3
    free_inodes: int = 100_000


# Never load declarations or Python from the requested checkout.
FLOW_AUTO_COLD = OptIn(("SKILLC_FLOW_AUTO_COLD", "1"),
                      ("tests/test_profile_flow_auto_87ecb097_cold.py::test_actual_cold_profile",))


def entry(name: str) -> OptIn:
    if name != "flow-auto-cold":
        raise ValueError("unknown opt-in")
    return FLOW_AUTO_COLD


def context(name: str) -> str:
    return "skillc/real-docker-optin/" + (name if re.fullmatch(r"[a-z0-9-]{1,40}", name) else "invalid")


def headroom(paths: tuple[Path, ...], policy: OptIn) -> None:
    for path in paths:
        # Work checkout may not exist until clone; its parent must exist.
        probe = path if path.exists() else path.parent
        stats = os.statvfs(probe)
        if stats.f_bavail * stats.f_frsize < policy.free_bytes or stats.f_favail < policy.free_inodes:
            raise ValueError("insufficient disk or inode headroom")


class Cancelled(Exception):
    """A termination signal enters the owned cleanup path."""


def owned_children() -> list[int]:
    return [int(pid) for pid in Path(f"/proc/self/task/{os.getpid()}/children").read_text().split()]


def sweep() -> bool:
    """Only a dedicated subreaper's direct/adopted children, never a global scan."""
    end = time.monotonic() + 10
    try:
        while True:
            while True:
                try:
                    if os.waitpid(-1, os.WNOHANG)[0] == 0:
                        break
                except ChildProcessError:
                    break
            children = owned_children()
            if not children:
                return True
            for pid in children:
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if time.monotonic() >= end:
                return False
            time.sleep(0.01)
    except (OSError, ValueError):
        return False


def execute(work: Path, report: Path, policy: OptIn) -> int:
    """Run ONLY in a dedicated helper process; one endpoint includes confirmed sweep."""
    deadline = time.monotonic() + policy.seconds
    old = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
    cancelled = False
    def cancel(_sig: int, _frame: object) -> None:
        nonlocal cancelled
        if not cancelled:
            cancelled = True
            raise Cancelled()
    result, confirmed = 2, False
    try:
        for sig in old:
            signal.signal(sig, cancel)
        if ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) != 0:
            return 2
        owned_children()  # Unreadable ownership refuses before any launch.
        report.unlink(missing_ok=True)
        env = dict(os.environ)
        env[policy.env[0]] = policy.env[1]
        env["SKILLC_REAL_DOCKER_RUN_LOCK_HELD"] = "1"
        for key in ("SKILLC_LIVE_TEST_BREAK", "SKILLC_GATE_WITNESS_LIVE_BREAK", "SKILLC_GATE_SHIM_LIVE_BREAK",
                    "SKILLC_COLDINSTALL_LIVE_BREAK", "SKILLC_TRIAL_IMAGE_BREAK", "SKILLC_CLOSURE_PREFLIGHT_LIVE_BREAK",
                    "SKILLC_CWD_CONFINEMENT_LIVE_BREAK", "SKILLC_EGRESS_LIVE_BREAK", "SKILLC_CICD_PROFILE_LIVE_BREAK",
                    "SKILLC_CICD_DEPLOY_VERIFY_LIVE_BREAK"):
            env[key] = "none"
        for args in (["uv", "sync", "--locked", "--extra", "dev", "--quiet"],
                     ["uv", "run", "--no-sync", "pytest", "-m", "real_docker", *policy.nodes,
                      f"--junit-xml={report}"]):
            if deadline - time.monotonic() <= 0:
                result = 124
                break
            process = subprocess.Popen(args, cwd=work, env=env, start_new_session=True)
            try:
                result = process.wait(timeout=max(0.001, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                result = 124
            if not sweep():
                result = 2
                break
            if result != 0:
                break
    except Cancelled:
        result = 143
    except (OSError, ValueError, AttributeError):
        result = 2
    finally:
        for sig in old:
            signal.signal(sig, signal.SIG_IGN)
        confirmed = sweep()
        for sig, handler in old.items():
            signal.signal(sig, handler)
    if not confirmed:
        return 2
    return 124 if result == 0 and time.monotonic() > deadline else result


def population(raw: bytes, policy: OptIn) -> tuple[str, int]:
    tree = ET.fromstring(raw)
    executed = 0
    failed = False
    complete = True
    for node in policy.nodes:
        file, test = node.split("::", 1)
        module = file.removesuffix(".py").replace("/", ".")
        matches = [case for case in tree.iter("testcase")
                   if case.get("classname") == module and case.get("name") == test]
        if len(matches) != 1 or (matches[0].find("skipped") is not None or matches[0].find("error") is not None):
            complete = False
            continue
        executed += 1
        failed |= matches[0].find("failure") is not None or matches[0].find("error") is not None
    return ("ERROR" if not complete else "FAILURE" if failed else "SUCCESS"), executed


def publish(report: Path, *, name: str, sha: str, runner_sha: str,
            evidence: Path, run_code: int) -> tuple[str, str, str]:
    policy = entry(name)
    if evidence.resolve().is_relative_to(report.parent.parent.resolve()):
        raise ValueError("private evidence must be outside the work checkout")
    raw: bytes | None = None
    status, executed = "ERROR", 0
    try:
        raw = report.read_bytes()
        status, executed = population(raw, policy)
    except (OSError, ValueError, ET.ParseError):
        pass
    # A setup/timeout/collection failure cannot be rescued by a passing report.
    if run_code not in (0, 1) or (run_code == 1 and status == "SUCCESS"):
        status = "ERROR"
    report_digest = hashlib.sha256(raw).hexdigest() if raw is not None else None
    binding = {"sha": sha, "runner_sha": runner_sha, "optin": name, "nodes": policy.nodes,
               "context": context(name), "executed": executed, "expected": len(policy.nodes),
               "status": status, "report_sha256": report_digest, "run_exit": run_code}
    evidence.mkdir(parents=True, exist_ok=True, mode=0o700)
    custody = Path(tempfile.mkdtemp(prefix="optin-", dir=evidence))
    if raw is not None:
        with (custody / "junit.xml").open("xb") as stream:
            stream.write(raw)
        (custody / "junit.xml").chmod(0o600)
    with (custody / "binding.json").open("x") as stream:
        json.dump(binding, stream, sort_keys=True)
    (custody / "binding.json").chmod(0o600)
    node = policy.nodes[0]
    description = f"{executed}/{len(policy.nodes)} {node} {report_digest or 'unavailable'}"
    if len(description) > 140:
        raise ValueError("opt-in status metadata exceeds GitHub description limit")
    body = (f"**real-Docker opt-in `{name}`: {status}**\n\n"
            f"- Commit: `{sha}`\n- Installed runner: `{runner_sha}`\n"
            f"- Context: `{context(name)}`\n- Node: `{node}`\n"
            f"- Executed/expected: {executed}/{len(policy.nodes)}\n"
            f"- JUnit SHA256: `{report_digest or 'unavailable'}`\n"
            f"- Private evidence identifier: `{custody.name}`\n\n"
            "Raw JUnit is retained privately on the runner for operator retrieval.\n"
            "This opt-in does not certify skillc/real-docker.")
    return status, description, body


def main(argv: list[str]) -> int:
    try:
        op, name = argv[1:3]
        policy = entry(name)
        if op == "precheck":
            docker = subprocess.run(["docker", "info", "--format", "{{.DockerRootDir}}"],
                                    capture_output=True, text=True, timeout=15, check=True)
            root = Path(docker.stdout.strip())
            if not root.is_absolute() or not root.is_dir():
                raise ValueError("Docker storage unavailable")
            headroom((Path(argv[3]), root), policy)
            return 0
        if op == "run":
            return execute(Path(argv[3]), Path(argv[4]), policy)
    except (OSError, ValueError, subprocess.SubprocessError):
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
