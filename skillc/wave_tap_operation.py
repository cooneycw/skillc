"""Fixed isolated root wrapper for the real pinned mailbox helper (#626).

Executed by the controller inside the role container, never as a participant
result-upload endpoint. No Git, caller-selected executable or shell text runs.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any


def _regular(path: Path, limit: int) -> bytes:
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("absolute controller path required")
    parent = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            os.close(parent)
            parent = child
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    finally:
        os.close(parent)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError("nonregular or over-bound evidence")
        with os.fdopen(os.dup(fd), "rb") as stream:
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError("over-bound evidence")
        return data
    finally:
        os.close(fd)


def operate(config: dict[str, Any], *, owner_uid: int = 0) -> dict[str, Any]:
    """The CLI always uses root ownership; tests may model a different owner."""
    scripts, shared = Path(config["scripts"]), Path(config["shared"])
    binding, op = config["binding"], config["operation"]
    if op not in {"assignment", "ack", "complete"}:
        raise ValueError("closed helper operation required")
    for value in (binding["role"], binding["wave_id"]):
        if not isinstance(value, str) or re.fullmatch(r"[a-z][a-z0-9-]{0,63}", value) is None:
            raise ValueError("invalid logical helper identity")
    # Every parent is pinned as a real directory; a candidate cannot redirect
    # an installed helper through a writable ancestor or a symlink.
    for parent in (scripts, *scripts.parents):
        info = os.lstat(parent)
        # A trusted test scratch parent may be shared; production's /opt
        # ancestry is root-owned and must never need this test allowance.
        if owner_uid == 0 and (not stat.S_ISDIR(info.st_mode) or info.st_uid != owner_uid
                               or stat.S_IMODE(info.st_mode) & 0o022):
            raise ValueError("untrusted helper ancestor")

    def pins() -> dict[str, str]:
        observed = {}
        for name in config["pins"]:
            if re.fullmatch(r"[a-z0-9-]+\.(sh|py)", name) is None:
                raise ValueError("unsafe helper name")
            path = scripts / name
            info = os.lstat(path)
            if info.st_uid != owner_uid or stat.S_IMODE(info.st_mode) & 0o022:
                raise ValueError("untrusted helper ownership")
            observed[name] = hashlib.sha256(_regular(path, 1024 * 1024)).hexdigest()
        if observed != config["pins"]:
            raise ValueError("helper source changed")
        return observed

    before = pins()
    role, wave = binding["role"], binding["wave_id"]
    message = {**binding, "op": "assignment" if op == "assignment" else "complete"}
    if op == "complete" and config.get("commit") is not None:
        if re.fullmatch(r"[0-9a-f]{40}", config["commit"]) is None:
            raise ValueError("invalid claimed artifact identity")
        message["commit"] = config["commit"]
    if op == "assignment":
        box = "inbox-controller.md" if role == "orchestrator" else "outbox-" + role + ".md"
        args = ["send", "--to", role, "--from", "controller", "--body", json.dumps(message, sort_keys=True)]
    elif op == "ack":
        box = "inbox-controller.md" if role == "orchestrator" else "outbox-" + role + ".md"
        args = ["ack", "--role", role, "--revs", str(config["assignment_rev"])]
        if role == "orchestrator":
            args += ["--from", "controller"]
        # The assignment is controller-known, not a participant-provided body.
        text = _regular(shared / wave / box, 1024 * 1024).decode()
        wanted = json.dumps({**binding, "op": "assignment"}, sort_keys=True)
        marker = r"^<!-- cc-flow-wave-msg rev=" + str(config["assignment_rev"]) + r" .*-->\n" + re.escape(wanted) + r"$"
        if re.search(marker, text, re.MULTILINE) is None:
            raise ValueError("assignment evidence changed or missing")
    else:
        box = "outbox-controller.md" if role == "orchestrator" else "inbox-" + role + ".md"
        args = ["send", "--to", "controller" if role == "orchestrator" else "orchestrator",
                "--from", role, "--body", json.dumps(message, sort_keys=True)]
    env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "HOME": "/nonexistent",
           "FLOW_WAVE_MAILBOX_DIR": str(shared), "FLOW_WAVE_REGISTRY_DIR": str(shared),
           "CLAUDE_CODE_SESSION_ID": binding["session_id"]}
    identity: dict[str, Any] = ({"user": config["candidate_uid"], "group": config["candidate_gid"], "extra_groups": []}
                                if owner_uid == 0 else {})
    result = subprocess.run(["/bin/bash", str(scripts / "flow-wave-mailbox.sh"), *args, "--wave", wave],
                            env=env, capture_output=True, timeout=config.get("timeout", 10), check=False, **identity)
    if len(result.stdout) > 32768 or len(result.stderr) > 32768:
        raise ValueError("helper output over bound")
    output = result.stdout.decode("utf-8")
    verdicts = re.findall(r"^FLOW_MAILBOX: (.+)$", output, re.MULTILINE)
    revisions = re.findall(r"^FLOW_MAILBOX_REV=(.+)$", output, re.MULTILINE)
    expected = "acked" if op == "ack" else "sent"
    receiver = ("controller" if role == "orchestrator" else "orchestrator") if op == "complete" else role
    identity_fields = (re.findall(r"^FLOW_MAILBOX_WAVE=(.+)$", output, re.MULTILINE) == [wave]
                       and re.findall(r"^FLOW_MAILBOX_ROLE=(.+)$", output, re.MULTILINE) == [receiver])
    effect = False
    revision = config.get("assignment_rev") if op == "ack" else None
    if result.returncode == 0 and verdicts == [expected] and identity_fields:
        if op == "ack":
            acknowledged = _regular(shared / wave / (".ack-" + box), 1024 * 1024).decode().splitlines()
            effect = str(revision) in acknowledged
        elif len(revisions) == 1 and revisions[0].isdigit() and int(revisions[0]) > 0:
            revision = int(revisions[0])
            text = _regular(shared / wave / box, 1024 * 1024).decode()
            marker = r"^<!-- cc-flow-wave-msg rev=" + str(revision) + r" .*-->\n" + re.escape(json.dumps(message, sort_keys=True)) + r"$"
            effect = re.search(marker, text, re.MULTILINE) is not None
    return {"nonce": config["nonce"], "operation": op, "box": box, "revision": revision,
            "exit_code": result.returncode, "stdout": output,
            "stderr": result.stderr.decode("utf-8", errors="replace"), "effect": effect,
            "pins_before": before, "pins_after": pins()}


if __name__ == "__main__":
    # This root process supplies the envelope; helper stdout cannot replace it.
    print(json.dumps(operate(json.loads(sys.argv[1])), sort_keys=True))
