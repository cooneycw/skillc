"""Closed trusted rehearsal actor. Diagnostic mail is never controller evidence."""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

ROLES = ("orchestrator", "worker-a", "worker-b")
MODES = {"healthy", "disappear", "stale-ack", "wrong-role-ack", "duplicate-completion",
         "unfinished-integration", "wait-for-deadline", "leave-unretired", "wrong-tax"}
STATE = Path(".rehearsal-state.json")
SCRIPT_DIR = Path(__file__).resolve().parent


def run(argv: list[str], env: dict[str, str]) -> str:
    result = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=10, check=False)
    if result.returncode:
        raise RuntimeError("rehearsal operation failed: " + argv[0])
    return result.stdout


def main(argv: list[str]) -> None:
    role, mode, *turn = argv
    if role not in ROLES or mode not in MODES:
        raise ValueError("closed role/mode required")
    if turn and turn[0] == "resume":
        if len(turn) != 3 or not STATE.is_file():
            raise ValueError("resume requires existing session and literal")
        state = json.loads(STATE.read_text())
        if state["session"] != turn[1] or state["role"] != role or state["mode"] != mode:
            raise ValueError("stale session or role")
    else:
        if len(turn) != 1 or STATE.exists():
            raise ValueError("one initial declaration required")
        config = json.loads(turn[0])
        if (set(config) not in ({"wave_id", "bindings"}, {"wave_id", "bindings", "tap"})
                or set(config["bindings"]) != set(ROLES)
                or ("tap" in config and config["tap"] is not True)):
            raise ValueError("closed role population required")
        state = {"role": role, "mode": mode, "session": str(uuid.uuid4()),
                 "config": config, "assigned": False, "done": False}
    session, config = state["session"], state["config"]
    sys.stderr.write("OpenAI Codex v0.157.1\n--------\nsession id: " + session + "\n--------\n")
    sys.stderr.flush()
    transcript = Path.home() / ".codex/sessions" / (role + ".jsonl")
    transcript.parent.mkdir(parents=True, exist_ok=True)
    if not transcript.exists():
        transcript.write_text(json.dumps({"type": "session_meta", "payload": {"id": session}}) + "\n")
    with transcript.open("a") as stream:
        stream.write(json.dumps({"type": "rehearsal_turn", "payload": {"session": session}}) + "\n")
    env = dict(os.environ, CLAUDE_PID=str(os.getpid()), CLAUDE_CODE_SESSION_ID=session)
    if not env.get("FLOW_WAVE_MAILBOX_DIR") or env.get("FLOW_WAVE_MAILBOX_DIR") != env.get("FLOW_WAVE_REGISTRY_DIR"):
        raise ValueError("one explicit shared root required")

    def helper(name: str, *args: str) -> str:
        return run(["bash", str(SCRIPT_DIR / ("flow-wave-" + name + ".sh")),
                    *args, "--wave", config["wave_id"]], env)

    def save() -> None:
        STATE.write_text(json.dumps(state, sort_keys=True))

    def send(to: str, message: dict[str, Any]) -> None:
        helper("mailbox", "send", "--to", to, "--from", role,
               "--body", json.dumps(message, sort_keys=True))

    def read(sender: str | None = None) -> list[tuple[str, dict[str, Any]]]:
        args = ["read", "--role", role, "--peek"]
        if sender is not None:
            args += ["--from", sender]
        text = helper("mailbox", *args)
        rows = []
        revision = None
        for line in text.splitlines():
            match = re.match(r"<!-- cc-flow-wave-msg rev=([1-9][0-9]*) ", line)
            if match:
                revision = match[1]
            elif line.startswith("{") and revision is not None:
                rows.append((revision, json.loads(line)))
                revision = None
        return rows

    def acknowledge(revision: str, sender: str | None = None) -> None:
        args = ["ack", "--role", role, "--revs", revision]
        if sender is not None:
            args += ["--from", sender]
        helper("mailbox", *args)

    def binding(worker: str, sid: str) -> dict[str, Any]:
        return {**config["bindings"][worker], "wave_id": config["wave_id"],
                "role": worker, "session_id": sid}

    def tap(operation: str, claim: dict[str, Any], commit: str | None = None) -> None:
        token = json.loads((SCRIPT_DIR / ("turn-" + role + ".json")).read_text())["turn_nonce"]
        request = {"kind": "wave-helper", "op": operation, "binding": claim, "turn_nonce": token}
        if commit is not None:
            request["commit"] = commit
        with socket.socket(socket.AF_UNIX) as client:
            client.settimeout(20)
            client.connect("/run/skillc/trigger.sock")
            client.sendall(json.dumps(request).encode() + b"\n")
            with client.makefile("rb") as stream:
                reply = json.loads(stream.readline(16384))
        if reply.get("ok") is not True or reply.get("result", {}).get("accepted") is not True:
            raise RuntimeError("trusted helper operation unavailable or refused")

    if state["done"]:
        return
    helper("registry", "register", role)
    if config.get("tap") and turn[0] != "resume":
        # The controller must observe this bootstrap header before admitting
        # any measured receipt/completion operation on a later turn.
        save()
        return
    task = json.loads((SCRIPT_DIR / "task.json").read_text())
    if role != "orchestrator":
        for revision, message in read():
            expected = binding(role, session)
            if message != {**expected, "op": "assignment"}:
                raise ValueError("assignment binding mismatch")
            claim = dict(expected)
            if role == "worker-a" and mode == "stale-ack":
                claim["revision"] += 1
            if role == "worker-a" and mode == "wrong-role-ack":
                claim["role"] = "worker-b"
            if config.get("tap"):
                tap("ack", claim)
            else:
                acknowledge(revision)
                send("orchestrator", {**claim, "op": "ack"})
            if role == "worker-a" and mode == "disappear":
                raise SystemExit(7)
            if role == "worker-a" and mode == "wait-for-deadline":
                while True:
                    time.sleep(1)
            source = "src/subtotal.py" if role == "worker-a" else "src/tax.py"
            content = task["implementations"][role]
            if role == "worker-b" and mode == "wrong-tax":
                content = "def tax(net, bp):\n    return 0\n"
            Path(source).write_text(content)
            run(["git", "add", "--", source], env)
            run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                 "commit", "-m", "scripted worker output"], env)
            run(["git", "push", "origin", "HEAD:refs/heads/" + role], env)
            commit = run(["git", "rev-parse", "HEAD"], env).strip()
            completion = {**expected, "op": "complete", "commit": commit}
            if config.get("tap"):
                tap("complete", expected, commit)
            else:
                send("orchestrator", completion)
            if role == "worker-a" and mode == "duplicate-completion":
                if config.get("tap"):
                    tap("complete", expected, commit)
                else:
                    send("orchestrator", completion)
            state["done"] = True
            if mode != "leave-unretired":
                helper("registry", "release", role)
            break
    else:
        if config.get("tap"):
            state["assigned"] = True  # assignments come from the controller tap
            if not state.get("own_assignment_received"):
                for _, message in read("controller"):
                    if message != {**binding(role, session), "op": "assignment"}:
                        raise ValueError("integrator assignment binding mismatch")
                    tap("ack", binding(role, session))
                    state["own_assignment_received"] = True
                if not state.get("own_assignment_received"):
                    save()
                    return
        if not state["assigned"]:
            sessions = {}
            for worker in ROLES[1:]:
                try:
                    output = helper("registry", "get", worker)
                except RuntimeError:
                    # A concurrent worker may not have registered yet. There
                    # is no success claim; a later shared change can resume us.
                    state["pending"] = "peer-registry-unavailable"
                    save()
                    return
                matches = re.findall(r"^FLOW_WAVE_SESSION=(.+)$", output, re.MULTILINE)
                if len(matches) != 1 or matches[0] == "-":
                    save()
                    return
                sessions[worker] = matches[0]
            for worker in ROLES[1:]:
                send(worker, {**binding(worker, sessions[worker]), "op": "assignment"})
            state["assigned"], state["sessions"] = True, sessions
        outputs = state.setdefault("outputs", {})
        for worker in ROLES[1:]:
            for revision, message in read(worker):
                # These are participant claims, retained for a future trusted
                # collector to assess. They never become normalized observations.
                acknowledge(revision, worker)
                if message.get("op") == "complete":
                    outputs[worker] = message["commit"]
        if set(outputs) == set(ROLES[1:]) and mode != "unfinished-integration":
            for worker in ROLES[1:]:
                run(["git", "fetch", "origin", worker], env)
                actual = run(["git", "rev-parse", "FETCH_HEAD"], env).strip()
                if actual != outputs[worker]:
                    raise ValueError("worker ref/claim mismatch")
                run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                     "cherry-pick", actual], env)
            run(["git", "push", "origin", "HEAD:refs/heads/delivered"], env)
            if config.get("tap"):
                tap("complete", binding(role, session), run(["git", "rev-parse", "HEAD"], env).strip())
            state["done"] = True
            if mode != "leave-unretired":
                helper("registry", "release", role)
    save()


if __name__ == "__main__":
    main(sys.argv[1:])
