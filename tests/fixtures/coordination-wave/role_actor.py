"""Trusted deterministic participants; no model/client or command evaluator."""

import json
import os
import socket
import sys
import time
from pathlib import Path


def main():
    endpoint, config = sys.argv[1], json.loads(sys.argv[2])
    mode = config.pop("mode")
    role = config["role"]
    base = {**config}
    Path("actor-report.json").write_text(json.dumps({"role": role, "mode": mode}))

    def request(op, assignment=None, mutate=False):
        payload = {**base, "op": op}
        if assignment is not None:
            payload.update({k: assignment[k] for k in ("task", "revision", "nonce")})
        if mutate:
            key, value = {
                "wrong-role": ("role", "worker-b"),
                "wrong-session": ("session", "obsolete"),
                "wrong-generation": ("generation", 1),
                "wrong-revision": ("revision", 0),
                "wrong-wave": ("wave", "obsolete"),
                "wrong-task": ("task", "obsolete"),
                "wrong-attempt": ("attempt_id", "obsolete"),
                "wrong-nonce": ("nonce", "obsolete"),
                "wrong-boolean-generation": ("generation", False),
                "wrong-boolean-revision": ("revision", True),
            }[mode]
            payload[key] = value
        try:
            with socket.socket(socket.AF_UNIX) as connection:
                connection.settimeout(2)
                connection.connect(endpoint)
                connection.sendall(json.dumps(payload).encode() + b"\n")
                with connection.makefile("rb") as stream:
                    reply = json.loads(stream.readline(8192))
        except OSError:
            # No subject-failure claim for unavailable transport; the controller
            # must inspect channel coverage and required artifacts independently.
            raise SystemExit(0) from None
        if not reply["ok"]:
            raise SystemExit(2)
        # Deliberate fixture pacing: receiving a reply can precede the server
        # handler's final bookkeeping. This is not a transport retry.
        time.sleep(0.01)
        return reply["result"]

    if role == "worker-a" and mode == "unregistered-poll":
        request("poll")
    request("register")
    if role == "worker-a" and mode == "duplicate-registration":
        request("register")
    if role == "worker-a" and mode == "request-flood":
        for _ in range(129):
            request("poll")
    while True:
        assignment = request("poll")
        if assignment["state"] == "offered":
            break
        time.sleep(0.03)
    if not (role == "worker-a" and mode == "unreceived-completion"):
        request("ack", assignment, mutate=role == "worker-a" and mode.startswith("wrong-"))
    if role == "worker-a" and mode == "duplicate-receipt":
        request("ack", assignment)
    if role == "worker-a" and mode == "hang":
        while True:
            time.sleep(1)
    if role == "worker-a" and mode == "disappear":
        os._exit(7)
    omit = ((role == "orchestrator" and mode == "no-integration")
            or (role == "worker-a" and mode == "forged-completion"))
    if not omit:
        Path("output.json").write_bytes(json.dumps(assignment["payload"], sort_keys=True,
                                                  separators=(",", ":"), ensure_ascii=False).encode())
    request("complete", assignment)
    if role == "worker-a" and mode == "duplicate-completion":
        request("complete", assignment)
    if role == "worker-a" and mode == "late-decision":
        with socket.socket(socket.AF_UNIX) as connection:
            connection.connect(endpoint)
            connection.sendall(json.dumps({**base, "op": "poll"}).encode() + b"\n")
            time.sleep(0.1)


if __name__ == "__main__":
    main()
