"""A deterministic stand-in for a platform implementing
docs/specs/evaluation-facility/managed-backend-protocol.md, for tests with no
real platform - the same role `tests/fixtures/docker-backend/fake_docker.py`
plays for `DockerBackend`.

    stub_server.py --socket PATH --state DIR

Listens on a Unix domain socket at PATH, one connection per request (the
protocol page's own framing rule): accept, read one `\\n`-terminated JSON
line, write one `\\n`-terminated JSON line, close. Runs until killed - a
test's fixture is responsible for starting this as a subprocess and
terminating it at teardown, exactly like `fake_docker.py`'s own tests own its
process lifetime (there, per-invocation; here, for the server's whole run).

FAULT INJECTION IS FILE-BASED, NOT ENVIRONMENT-BASED (matching
`fake_docker.py`'s own stated reasoning: a test's `monkeypatch.setenv` reaches
a socket connection only by accident, since `ManagedBackend` never forwards
its own process's environment over the wire). `DIR/control.json` is read
FRESH on every single request, so a test can rewrite it mid-run to change
behaviour between calls without restarting the server. Recognized keys, all
optional:

    "refuse_ops": [str, ...]      - respond {"ok": false, "error": "..."} to
                                     these ops, never a partial success.
    "drop_ops": [str, ...]        - accept the connection, read the request,
                                     then close without writing anything -
                                     simulates a transport that died mid-call
                                     (the case `confirm_stopped`/
                                     `confirm_absent` must map to UNKNOWN,
                                     never a guessed CONFIRMED/NOT_CONFIRMED).
    "leak_value": str | null      - when set, `install`'s `image_digest` and
                                     `prepare`'s `handle` both embed this
                                     value verbatim - a deliberately
                                     non-neutral identity, for the
                                     neutral-identity leak-check test (#63).
                                     Never set by default: the ordinary
                                     lifecycle tests must see a clean,
                                     neutral identity.
    "require_credential": str | null - when set, `prepare` requests missing
                                     this exact `credential` value are
                                     refused. Lets a test prove the client
                                     sends the right value on `prepare` and
                                     nothing else, without the stub ever
                                     echoing the value back anywhere.

Every workspace this stub manages lives under `DIR/workspaces/<token>/` -
`install` writes declared entries there, `execute` runs the subject's real
argv with that directory as `cwd` and captures its stdout to
`<workspace>/observations` (the same convention `DockerBackend.execute()`
documents), and `export` tars up that directory's contents for the response.
"""

from __future__ import annotations

import base64
import io
import json
import os
import socketserver
import subprocess
import sys
import tarfile
import uuid
from pathlib import Path
from typing import Any

STATE_DIR: Path
SOCKET_PATH: Path


def _control() -> dict[str, Any]:
    path = STATE_DIR / "control.json"
    if not path.is_file():
        return {}
    try:
        loaded: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _workspace(token: str) -> Path:
    return STATE_DIR / "workspaces" / token


def _ok(result: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True, "result": result}


def _err(message: str) -> dict[str, Any]:
    return {"ok": False, "error": message}


def _handle_describe(_request: dict[str, Any]) -> dict[str, Any]:
    return _ok({
        "name": "managed-backend-stub",
        "version": "0",
        "isolation": ("subprocess (no real container - test stub only)",),
        "unobserved": ("everything a real platform would isolate - this is a fake",),
    })


def _handle_prepare(request: dict[str, Any], control: dict[str, Any]) -> dict[str, Any]:
    required = control.get("require_credential")
    if required is not None and request.get("credential") != required:
        return _err("credential rejected")
    attempt_id = str(request["attempt_id"])
    leak = control.get("leak_value")
    token = f"{leak}-{attempt_id}" if isinstance(leak, str) else f"stub-{uuid.uuid4().hex[:12]}"
    _workspace(token).mkdir(parents=True, exist_ok=True)
    return _ok({"handle": token})


def _handle_install(request: dict[str, Any], control: dict[str, Any]) -> dict[str, Any]:
    workspace = _workspace(str(request["handle"]))
    surface = request.get("surface") or {}
    installed = 0
    for name, entry in surface.items():
        content_b64 = entry.get("content_b64") if isinstance(entry, dict) else None
        if not isinstance(content_b64, str):
            continue
        target = workspace / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(base64.b64decode(content_b64))
        installed += 1
    nonce = request.get("canary_nonce")
    result: dict[str, Any] = {
        "discovery_canary": "SATISFIED" if installed else "VIOLATED",
        "baseline_absence": "SATISFIED",
        "declared": len(surface),
        "installed": installed,
        "image_digest": (
            f"managed-backend-stub@{control['leak_value']}"
            if isinstance(control.get("leak_value"), str)
            else "managed-backend-stub@sha256:0000000000000000000000000000000000000000000000000000000000000000"
        ),
    }
    if isinstance(nonce, str) and nonce:
        canary = workspace / "SKILLC_CANARY"
        canary.write_text(nonce, encoding="utf-8")
        result["canary_path"] = "SKILLC_CANARY"
    return _ok(result)


def _handle_execute(request: dict[str, Any]) -> dict[str, Any]:
    workspace = _workspace(str(request["handle"]))
    argv = [str(a) for a in request["argv"]]
    timeout = float(request["timeout"]) + float(request["grace"])
    stdin_b64 = request.get("stdin_b64")
    stdin_bytes = base64.b64decode(stdin_b64) if isinstance(stdin_b64, str) else None
    try:
        proc = subprocess.run(
            argv, cwd=workspace, input=stdin_bytes, capture_output=True, timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired:
        return _ok({
            "reason": "timeout", "exit_code": None, "error": "stub: timed out", "signal": None,
            "stdout_truncated": False, "stdout_bytes": 0,
        })
    except OSError as exc:
        return _ok({
            "reason": "launch-failed", "exit_code": None, "error": str(exc), "signal": None,
            "stdout_truncated": False, "stdout_bytes": 0,
        })
    (workspace / "observations").write_bytes(proc.stdout)
    error = proc.stderr.decode("utf-8", errors="replace").strip() or None if proc.returncode != 0 else None
    return _ok({
        "reason": "exited", "exit_code": proc.returncode, "error": error, "signal": None,
        "stdout_truncated": False, "stdout_bytes": len(proc.stdout),
    })


def _handle_confirm_stopped(request: dict[str, Any]) -> dict[str, Any]:
    # The stub runs execute() synchronously, so by the time this is called
    # the subject has already exited - always CONFIRMED unless the workspace
    # was never prepared at all.
    workspace = _workspace(str(request["handle"]))
    return _ok({"state": "confirmed" if workspace.is_dir() else "unknown"})


def _handle_export(request: dict[str, Any]) -> dict[str, Any]:
    workspace = _workspace(str(request["handle"]))
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        if workspace.is_dir():
            for entry in sorted(workspace.rglob("*")):
                if entry.is_file():
                    tar.add(entry, arcname=str(entry.relative_to(workspace)))
    return _ok({"archive_b64": base64.b64encode(buffer.getvalue()).decode("ascii")})


def _handle_destroy(request: dict[str, Any]) -> dict[str, Any]:
    workspace = _workspace(str(request["handle"]))
    if workspace.is_dir():
        for entry in sorted(workspace.rglob("*"), reverse=True):
            if entry.is_file():
                entry.unlink()
            else:
                entry.rmdir()
        workspace.rmdir()
    return _ok({})


def _handle_confirm_absent(request: dict[str, Any]) -> dict[str, Any]:
    workspace = _workspace(str(request["handle"]))
    return _ok({"state": "not-confirmed" if workspace.is_dir() else "confirmed"})


_HANDLERS = {
    "execute": _handle_execute,
    "confirm_stopped": _handle_confirm_stopped,
    "export": _handle_export,
    "destroy": _handle_destroy,
    "confirm_absent": _handle_confirm_absent,
}


def _dispatch(request: dict[str, Any]) -> dict[str, Any] | None:
    """Returns `None` exactly when the control file names this op as
    dropped - the caller must close the connection without writing
    anything."""
    op = request.get("op")
    if not isinstance(op, str):
        return _err("missing op")
    control = _control()
    if op in control.get("drop_ops", []):
        return None
    if op in control.get("refuse_ops", []):
        return _err(f"{op}: refused by control.json")
    if op == "describe":
        return _handle_describe(request)
    if op == "prepare":
        return _handle_prepare(request, control)
    if op == "install":
        return _handle_install(request, control)
    handler = _HANDLERS.get(op)
    if handler is None:
        return _err(f"unknown op {op!r}")
    return handler(request)


class _RequestHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        chunks: list[bytes] = []
        while True:
            chunk = self.request.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
            if b"\n" in chunk:
                break
        line = b"".join(chunks).split(b"\n", 1)[0]
        try:
            request = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.request.sendall(json.dumps(_err("malformed request")).encode("utf-8") + b"\n")
            return
        if not isinstance(request, dict):
            self.request.sendall(json.dumps(_err("malformed request")).encode("utf-8") + b"\n")
            return
        with (STATE_DIR / "requests.jsonl").open("a", encoding="utf-8") as log:
            log.write(json.dumps(request) + "\n")
        response = _dispatch(request)
        if response is None:
            return  # deliberately dropped - close with no response written
        self.request.sendall(json.dumps(response).encode("utf-8") + b"\n")


class _Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True


def main(argv: list[str]) -> int:
    global STATE_DIR, SOCKET_PATH
    if len(argv) != 4 or argv[0] != "--socket" or argv[2] != "--state":
        print("stub_server: usage: stub_server.py --socket PATH --state DIR", file=sys.stderr)
        return 2
    SOCKET_PATH = Path(argv[1])
    STATE_DIR = Path(argv[3])
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    (STATE_DIR / "workspaces").mkdir(parents=True, exist_ok=True)
    if SOCKET_PATH.exists():
        SOCKET_PATH.unlink()
    server = _Server(str(SOCKET_PATH), _RequestHandler)
    try:
        os.chmod(SOCKET_PATH, 0o600)
        server.serve_forever(poll_interval=0.05)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
