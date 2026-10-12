"""The optional managed-container backend (#64): skillc talks to a platform
that already manages its own containers, over the protocol published at
`docs/specs/evaluation-facility/managed-backend-protocol.md` - status
"Proposed", since nothing implements it yet.

PLATFORM-NEUTRAL BY NAME AND BY CONSTRUCTION (operator direction, #64
review): nothing in this module names, imports or assumes any particular
platform. `SKILLC_MANAGED_BACKEND_SOCKET` and
`SKILLC_MANAGED_BACKEND_TOKEN_FILE` are the only two environment inputs; the
protocol page's own "Implementers" note is the only place a first intended
implementer is named, and that note is a pointer to another project's issue,
not a dependency.

THIS IS THE CLIENT HALF ONLY. The server half - whatever process listens on
`SKILLC_MANAGED_BACKEND_SOCKET` and actually creates a container - does not
exist yet anywhere in this repository or in this module; a platform that
wants to back this backend implements the protocol page, not this file.
`tests/fixtures/managed-backend/stub_server.py` is a TEST-ONLY stand-in, the
same role `tests/fixtures/docker-backend/fake_docker.py` plays for
`DockerBackend` - it proves this client's shape against a fake, never a real
containment boundary. Conformance against a real platform-created container
is owed (`docs/specs/evaluation-facility/support-matrix.md` carries that row
as `owed`, not `demonstrated`, until a platform actually implements the
protocol page).

THE PROTOCOL PAGE IS THE SPEC; THIS MODULE'S FIELD TABLES ARE A COPY OF IT.
`REQUEST_FIELDS`/`RESPONSE_RESULT_FIELDS`/`RESPONSE_REQUIRED_FIELDS` below
must match the page's "Request fields"/"Response fields" tables exactly -
`tests/test_managed_backend.py` parses the page directly and asserts they
agree, so the doc and the code cannot drift apart unnoticed. Every outgoing
request is built from a field set drawn only from `REQUEST_FIELDS[op]`, and
every incoming response is refused (treated as a transport failure - see
`_call`) if `result` carries a key outside `RESPONSE_RESULT_FIELDS[op]` or is
missing one required by `RESPONSE_REQUIRED_FIELDS[op]` - a closed schema in
BOTH directions, never silent tolerance of an unrecognized field on either
side.

ERROR AND UNAVAILABLE SEMANTICS follow the protocol page's table exactly,
which is itself just `skillc/backend.py`'s own per-method contract applied to
one more kind of failure (a dead socket, a timeout, a malformed or
out-of-schema response) beside the ones `DockerBackend` already maps (a dead
daemon, a failed `docker run`): `describe()` never raises;
`prepare()`/`install()` raise `BackendUnavailable`; `execute()` never raises,
returning `ExecuteResult(reason="launch-failed", ...)`;
`confirm_stopped()`/`confirm_absent()` return `Confirmation.UNKNOWN`, never a
guessed answer; `export()` raises `OSError`; `destroy()` never raises
(best-effort).

THE CREDENTIAL HOOK (`SKILLC_MANAGED_BACKEND_TOKEN_FILE`) is read once, held
on the frozen dataclass with `repr=False` (the same discipline
`DockerBackend`'s own `env` field already uses for the same reason - printing
this backend must never leak something a ledger or a log could pick up), and
sent on the `prepare` request only - the platform is expected to scope the
whole attempt to the credential presented once at allocation, never
re-authorized per call. It is never echoed into an exception message this
module constructs, never appears in `describe()`'s claims, and never appears
in any `ExecutionBackend` return value.

CANCELLATION IS NOT WIRED. `execute()`'s `cancel` callable is accepted for
seam compatibility but never polled - protocol version 1 has no side channel
to interrupt an in-flight blocking call (see the protocol page's "Not yet
covered"). `describe()`'s `unobserved` names this explicitly; a caller
relying on early cancellation must not rely on this backend for it yet.

Stdlib only (`socket`, `json`, `base64`, `tarfile`), like the rest of
`skillc/` (AGENTS.md).
"""

from __future__ import annotations

import base64
import io
import json
import os
import socket
import tarfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .backend import (
    BackendDescription,
    BackendUnavailable,
    Confirmation,
    ExecuteResult,
    Limits,
)
from .lifecycle import CANARY_NONCE_KEY

#: The only protocol version this module or the protocol page defines.
PROTOCOL_VERSION = 1

SOCKET_ENV_VAR = "SKILLC_MANAGED_BACKEND_SOCKET"
TOKEN_FILE_ENV_VAR = "SKILLC_MANAGED_BACKEND_TOKEN_FILE"

DEFAULT_TIMEOUT = 10.0

#: Request field sets, one per op - copied from
#: docs/specs/evaluation-facility/managed-backend-protocol.md's "Request
#: fields" table. `tests/test_managed_backend.py` parses that table and
#: asserts this dict matches it exactly.
REQUEST_FIELDS: dict[str, frozenset[str]] = {
    "describe": frozenset({"op", "protocol"}),
    "prepare": frozenset({"op", "protocol", "attempt_id", "credential"}),
    "install": frozenset({"op", "protocol", "handle", "attempt_id", "surface", "canary_nonce"}),
    "execute": frozenset({
        "op", "protocol", "handle", "attempt_id", "argv", "timeout", "grace",
        "max_captured_stdout_bytes", "max_captured_stderr_bytes", "stdin_b64",
    }),
    "confirm_stopped": frozenset({"op", "protocol", "handle", "attempt_id"}),
    "export": frozenset({"op", "protocol", "handle", "attempt_id"}),
    "destroy": frozenset({"op", "protocol", "handle", "attempt_id"}),
    "confirm_absent": frozenset({"op", "protocol", "handle", "attempt_id"}),
}

#: Response `result` field sets, one per op - copied from the same page's
#: "Response fields" table. `destroy`'s result is always `{}` (stated in the
#: page's prose, not a table row) and is not covered by the parity test.
RESPONSE_RESULT_FIELDS: dict[str, frozenset[str]] = {
    "describe": frozenset({"name", "version", "isolation", "unobserved"}),
    "prepare": frozenset({"handle"}),
    "install": frozenset({
        "discovery_canary", "baseline_absence", "declared", "installed", "image_digest", "canary_path",
    }),
    "execute": frozenset({"reason", "exit_code", "error", "signal", "stdout_truncated", "stdout_bytes"}),
    "confirm_stopped": frozenset({"state"}),
    "export": frozenset({"archive_b64"}),
    "destroy": frozenset(),
    "confirm_absent": frozenset({"state"}),
}

#: The subset of each op's response fields that must be present - everything
#: in `RESPONSE_RESULT_FIELDS` except `install`'s `canary_path`, which the
#: page marks optional (present only when a nonce was planted and the plant
#: succeeded).
RESPONSE_REQUIRED_FIELDS: dict[str, frozenset[str]] = {
    op: (fields - {"canary_path"} if op == "install" else fields)
    for op, fields in RESPONSE_RESULT_FIELDS.items()
}

_CONFIRMATION_STATES: dict[str, Confirmation] = {
    "confirmed": Confirmation.CONFIRMED,
    "not-confirmed": Confirmation.NOT_CONFIRMED,
    "unknown": Confirmation.UNKNOWN,
}


class _ProtocolFailure(Exception):
    """Internal only - never escapes this module. Every public
    `ExecutionBackend` method catches this and maps it to ITS OWN failure
    vocabulary per the protocol page's error-and-unavailable-semantics
    table."""


@dataclass(frozen=True)
class _Handle:
    """Opaque to the controller (`backend.py`'s own rule). `token` is
    whatever the platform returned from `prepare` - round-tripped verbatim on
    every later request for this attempt, never parsed or interpreted here.
    Content-neutrality of `token` itself is the PLATFORM's obligation (the
    protocol page's "Handle rule"); this module only provides the leak-check
    instrument that would catch a violation, never a guarantee that a real
    platform satisfies it."""

    attempt_id: str
    token: str


def _surface_bytes(value: object) -> bytes | None:
    """`surface`'s exact shape is out of this seam's scope
    (`backend.ExecutionBackend.install`'s own docstring). This backend reads
    any declared entry whose value is raw `bytes`, or names an existing host
    path (`str`/`Path`), into memory for base64 transport - there is no
    shared filesystem with the platform, unlike `DockerBackend`'s `docker
    cp`. Any other value is still counted in `declared` (by the platform,
    from `len(surface)` minus the canary key), just not sent."""
    if isinstance(value, bytes):
        return value
    if isinstance(value, (str, Path)):
        path = Path(value)
        if path.exists():
            return path.read_bytes()
        return None
    return None


def _confirmation_from(state: object) -> Confirmation:
    """An unrecognized or missing state is never guessed as CONFIRMED or
    NOT_CONFIRMED - only the three states the protocol page names are ever
    returned as anything but UNKNOWN."""
    if isinstance(state, str) and state in _CONFIRMATION_STATES:
        return _CONFIRMATION_STATES[state]
    return Confirmation.UNKNOWN


def _send_receive(socket_path: str, payload: Mapping[str, object], timeout: float) -> object:
    """One connection, one request line, one response line - the protocol
    page's own framing rule. Raises `OSError`/`ValueError` on anything that
    is not a complete, well-formed response; `_call` turns either into a
    `_ProtocolFailure`."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.settimeout(timeout)
        sock.connect(socket_path)
        sock.sendall(json.dumps(payload).encode("utf-8") + b"\n")
        sock.shutdown(socket.SHUT_WR)
        chunks: list[bytes] = []
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        sock.close()
    line = b"".join(chunks).split(b"\n", 1)[0]
    if not line:
        raise ValueError("empty response")
    return json.loads(line.decode("utf-8"))


@dataclass(frozen=True)
class ManagedBackend:
    """One `ExecutionBackend` per attempt lifecycle, talking to a platform
    over `socket_path`. `credential`, when set, rides `prepare` requests only
    - see the module docstring. Construct via `from_env()` in production; the
    explicit constructor is for tests that point directly at a stub's socket
    without touching the environment."""

    socket_path: str | None
    credential: str | None = field(default=None, repr=False)
    timeout: float = DEFAULT_TIMEOUT

    @classmethod
    def from_env(cls, *, timeout: float = DEFAULT_TIMEOUT) -> ManagedBackend:
        """Reads `SKILLC_MANAGED_BACKEND_SOCKET` and, when set,
        `SKILLC_MANAGED_BACKEND_TOKEN_FILE` - the file's contents, stripped
        of trailing whitespace, read exactly once here, never re-read per
        call."""
        socket_path = os.environ.get(SOCKET_ENV_VAR) or None
        token_file = os.environ.get(TOKEN_FILE_ENV_VAR)
        credential = Path(token_file).read_text(encoding="utf-8").rstrip() if token_file else None
        return cls(socket_path=socket_path, credential=credential, timeout=timeout)

    def _call(self, op: str, fields: Mapping[str, object], *, timeout: float | None = None) -> dict[str, object]:
        if self.socket_path is None:
            raise _ProtocolFailure(f"{op}: no managed-backend socket configured ({SOCKET_ENV_VAR} unset)")
        payload: dict[str, object] = {"op": op, "protocol": PROTOCOL_VERSION, **fields}
        allowed_request = REQUEST_FIELDS[op]
        if not set(payload) <= allowed_request:
            # A bug in THIS module, not a platform fact - the closed-schema
            # rule applies to what we send, too.
            raise _ProtocolFailure(
                f"{op}: internal error - built a request with fields outside the protocol page: "
                f"{sorted(set(payload) - allowed_request)}"
            )
        try:
            response = _send_receive(self.socket_path, payload, self.timeout if timeout is None else timeout)
        except (OSError, ValueError) as exc:
            raise _ProtocolFailure(f"{op}: {exc}") from exc
        if not isinstance(response, dict) or "ok" not in response:
            raise _ProtocolFailure(f"{op}: malformed response")
        if response["ok"] is not True:
            raise _ProtocolFailure(f"{op}: {response.get('error', 'refused')}")
        result = response.get("result")
        if not isinstance(result, dict):
            raise _ProtocolFailure(f"{op}: response carried no result object")
        allowed_result = RESPONSE_RESULT_FIELDS[op]
        if not set(result) <= allowed_result:
            raise _ProtocolFailure(
                f"{op}: response carried fields outside the protocol page: {sorted(set(result) - allowed_result)}"
            )
        missing = RESPONSE_REQUIRED_FIELDS[op] - set(result)
        if missing:
            raise _ProtocolFailure(f"{op}: response missing required fields: {sorted(missing)}")
        return result

    def describe(self) -> BackendDescription:
        """Step 1: never raises - an unreachable platform is reported as
        `version="unreachable"`, matching `DockerBackend.describe()`'s own
        convention."""
        try:
            result = self._call("describe", {})
        except _ProtocolFailure as exc:
            return BackendDescription(
                name="managed-backend", version="unreachable",
                isolation=(), unobserved=(f"platform unreachable: {exc}",),
            )
        isolation = result["isolation"]
        unobserved = result["unobserved"]
        assert isinstance(isolation, list)
        assert isinstance(unobserved, list)
        return BackendDescription(
            name=str(result["name"]), version=str(result["version"]),
            isolation=tuple(str(v) for v in isolation),
            unobserved=(
                *(str(v) for v in unobserved),
                ("cancellation mid-execute - protocol version 1 has no side channel to interrupt "
                 "an in-flight blocking execute() call"),
            ),
        )

    def prepare(self, attempt_id: str) -> object:
        """Step 3: raises `BackendUnavailable` on any protocol/transport
        failure - never returns a handle for a platform it could not
        actually reach."""
        fields: dict[str, object] = {"attempt_id": attempt_id}
        if self.credential is not None:
            fields["credential"] = self.credential
        try:
            result = self._call("prepare", fields)
        except _ProtocolFailure as exc:
            raise BackendUnavailable(f"managed backend unavailable for {attempt_id!r}: {exc}") from exc
        return _Handle(attempt_id=attempt_id, token=str(result["handle"]))

    def install(self, handle: object, surface: Mapping[str, object], root: str | None = None) -> dict[str, object]:
        """Step 4: encodes every declared entry as base64 content - there is
        no shared filesystem with the platform to `cp` into, unlike
        `DockerBackend`. Raises `BackendUnavailable` on failure, exactly like
        `DockerBackend.install()`'s own stated reasoning: a materialization
        failure makes this attempt's backend unusable, same as an
        unreachable daemon.

        `root` (#332 follow-up): the managed-backend protocol page has no
        root concept yet - every entry installs to the remote's own fixed
        default. A non-`None` root is refused outright (`BackendUnavailable`)
        rather than silently honored-as-default, since silently installing
        somewhere other than what the caller asked for is a worse failure
        than a loud refusal - same posture as `exec_in_attempt`'s own
        unconditional `reason="unsupported"` for a protocol surface not yet
        extended here."""
        assert isinstance(handle, _Handle)
        if root is not None:
            raise BackendUnavailable(
                f"managed backend does not support installing at a non-default root ({root!r}) - "
                "the protocol has no root concept yet"
            )
        nonce = surface.get(CANARY_NONCE_KEY)
        encoded: dict[str, object] = {}
        for key, value in surface.items():
            if key == CANARY_NONCE_KEY:
                continue
            content = _surface_bytes(value)
            if content is None:
                continue
            encoded[key] = {"content_b64": base64.b64encode(content).decode("ascii")}
        fields: dict[str, object] = {
            "handle": handle.token, "attempt_id": handle.attempt_id, "surface": encoded,
        }
        if isinstance(nonce, str) and nonce:
            fields["canary_nonce"] = nonce
        try:
            result = self._call("install", fields)
        except _ProtocolFailure as exc:
            raise BackendUnavailable(f"managed backend install failed for {handle.attempt_id!r}: {exc}") from exc
        readiness: dict[str, object] = {
            "discovery_canary": result["discovery_canary"],
            "baseline_absence": result["baseline_absence"],
            "declared": result["declared"],
            "installed": result["installed"],
            "image_digest": result["image_digest"],
        }
        if "canary_path" in result:
            readiness["canary_path"] = result["canary_path"]
        return readiness

    def execute(
        self, handle: object, argv: Sequence[str], limits: Limits,
        cancel: Callable[[], bool] | None = None, stdin: bytes | None = None,
    ) -> ExecuteResult:
        """Step 5: a single blocking call - see the module docstring on
        `cancel`. Never raises: a protocol/transport failure maps to
        `ExecuteResult(reason="launch-failed", ...)`, matching
        `DockerBackend.execute()`'s own `OSError` handling."""
        assert isinstance(handle, _Handle)
        del cancel  # not honoured by protocol version 1 - see module docstring
        fields: dict[str, object] = {
            "handle": handle.token, "attempt_id": handle.attempt_id, "argv": list(argv),
            "timeout": limits.timeout, "grace": limits.grace,
            "max_captured_stdout_bytes": limits.max_captured_stdout_bytes,
            "max_captured_stderr_bytes": limits.max_captured_stderr_bytes,
        }
        if stdin is not None:
            fields["stdin_b64"] = base64.b64encode(stdin).decode("ascii")
        call_timeout = limits.timeout + limits.grace + self.timeout
        try:
            result = self._call("execute", fields, timeout=call_timeout)
        except _ProtocolFailure as exc:
            return ExecuteResult(reason="launch-failed", exit_code=None, error=str(exc))
        exit_code = result["exit_code"]
        error = result["error"]
        signal = result["signal"]
        stdout_bytes = result["stdout_bytes"]
        assert exit_code is None or isinstance(exit_code, int)
        assert error is None or isinstance(error, str)
        assert signal is None or isinstance(signal, str)
        assert isinstance(stdout_bytes, int)
        return ExecuteResult(
            reason=str(result["reason"]), exit_code=exit_code, error=error, signal=signal,
            stdout_truncated=bool(result["stdout_truncated"]), stdout_bytes=stdout_bytes,
        )

    def exec_in_attempt(
        self, handle: object, argv: Sequence[str], limits: Limits,
        cancel: Callable[[], bool] | None = None, stdin: bytes | None = None,
        cwd: str | None = None, env: Mapping[str, str] | None = None,
        confine_root: str | None = None,
    ) -> ExecuteResult:
        """Not yet a protocol version 1 operation (#269) - the managed-backend
        protocol page (`docs/specs/evaluation-facility/
        managed-backend-protocol.md`) carries no `exec_in_attempt` row, so
        there is no request to send. Refuses unconditionally with
        `reason="unsupported"` rather than attempting a weaker
        approximation (e.g. falling back to `execute()`, which would stop
        the attempt - exactly what this method exists to never do). A
        caller (the gate-execution witness) that receives this must treat
        the whole mechanism as unavailable for this attempt, never retry.
        Adding real support here is owed to whichever issue extends the
        protocol page with this operation - not done in this change.
        `confine_root` (#338) is accepted for the same reason `cwd` already
        is - unsupported here regardless, never a path to run `cwd`
        unconfined."""
        assert isinstance(handle, _Handle)
        del argv, limits, cancel, stdin, cwd, env, confine_root
        return ExecuteResult(reason="unsupported", exit_code=None)

    def resolve_realpath_in_attempt(self, handle: object, path: str, timeout: float = 2.0) -> str | None:
        """#332: not a protocol version 1 operation here either, for the
        same reason `exec_in_attempt` is unsupported - `None` unconditionally,
        which safely refuses every cwd a caller would otherwise confine."""
        assert isinstance(handle, _Handle)
        del path, timeout
        return None

    def confirm_stopped(self, handle: object) -> Confirmation:
        """Step 6: `Confirmation.UNKNOWN` on any protocol/transport failure -
        never a guessed CONFIRMED/NOT_CONFIRMED."""
        assert isinstance(handle, _Handle)
        try:
            result = self._call("confirm_stopped", {"handle": handle.token, "attempt_id": handle.attempt_id})
        except _ProtocolFailure:
            return Confirmation.UNKNOWN
        return _confirmation_from(result.get("state"))

    def export(self, handle: object, dest: Path, root: str | None = None) -> None:
        """Step 7 (backend side): decodes the platform's base64 tar stream
        and extracts it under `dest` - contents only, never nesting the
        workspace itself inside `dest`. `filter="data"` refuses an absolute
        path or a symlink escape in the archive (stdlib, Python 3.12+).

        `root` (#332 follow-up): refused outright when not `None`, same
        posture and reasoning as `install()`'s own refusal - the protocol
        has no root concept yet, so a non-default root cannot be honored
        and must not be silently ignored."""
        assert isinstance(handle, _Handle)
        if root is not None:
            raise BackendUnavailable(
                f"managed backend does not support exporting from a non-default root ({root!r}) - "
                "the protocol has no root concept yet"
            )
        dest.mkdir(parents=True, exist_ok=True)
        try:
            result = self._call("export", {"handle": handle.token, "attempt_id": handle.attempt_id})
        except _ProtocolFailure as exc:
            raise OSError(f"managed backend export failed for {handle.attempt_id!r}: {exc}") from exc
        archive = base64.b64decode(str(result["archive_b64"]))
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:*") as tar:
            tar.extractall(dest, filter="data")

    def destroy(self, handle: object) -> None:
        """Step 9: best-effort, never raises - `confirm_absent()` is what a
        caller trusts, exactly as `DockerBackend.destroy()`'s own
        discipline."""
        assert isinstance(handle, _Handle)
        try:
            self._call("destroy", {"handle": handle.token, "attempt_id": handle.attempt_id})
        except _ProtocolFailure:
            pass

    def confirm_absent(self, handle: object) -> Confirmation:
        """Step 9: `Confirmation.UNKNOWN` on any protocol/transport failure -
        never trusts `destroy()`'s own outcome, exactly as `confirm_stopped`
        never trusts `execute()`'s."""
        assert isinstance(handle, _Handle)
        try:
            result = self._call("confirm_absent", {"handle": handle.token, "attempt_id": handle.attempt_id})
        except _ProtocolFailure:
            return Confirmation.UNKNOWN
        return _confirmation_from(result.get("state"))
