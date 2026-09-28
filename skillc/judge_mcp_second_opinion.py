"""The `mcp-second-opinion` Judge adapter (#69 follow-up).

Implements `skillc.judge.Judge` against a real
[`cooneycw/mcp-second-opinion`](https://github.com/cooneycw/mcp-second-opinion)
server, speaking MCP as an EXTERNAL PROCESS: spawn plus line-delimited
JSON-RPC 2.0 over stdio (the `initialize` handshake, the `notifications/
initialized` notification, then one `tools/call`). Stdlib only - `subprocess`,
`json`, `select` - no MCP SDK, matching `skillc/docker_backend.py`'s own
precedent for talking to an external tool without vendoring its client
library.

WHAT THIS MODULE DOES NOT DO. It never calls a real `mcp-second-opinion`
process in this build's own test suite (#69's own acceptance: "No real model
call in the test suite"). Every test drives
`tests/fixtures/mcp-second-opinion/fake_server.py`, a committed fake that
speaks the same stdio protocol subset without a network or an API key.
`command` defaults to the real binary's name so a caller who HAS it installed
gets it for free, but every test overrides `command` explicitly to point at
the fake instead.

TWO SPAWNS PER TIER, ON PURPOSE (a known inefficiency, not a correctness
issue). `skillc.judge.run_tier` calls `describe()` then `evaluate()`
separately, and this adapter does not share a live process between them - it
spawns, handshakes, does its one call, and tears down, every time. A future
optimization could hold one process open across both calls; nothing about
this PR's correctness depends on avoiding the extra spawn.

BOTH READS AND WRITES ARE BOUNDED (cross-model review, this PR). A blocking
`stdin.write()` with no deadline can hang forever if the child stops reading
(a full candidate payload can exceed the OS pipe's capacity even when the
JSON-RPC MESSAGES themselves are small), which would let a single stuck judge
call escape every timeout this module claims to enforce. `_write` therefore
polls for writability with `select`, exactly as `_LineReader` already polled
for readability, and raises `JudgeUnavailable` on the same deadline discipline
as a read timeout. `stderr` is discarded (`DEVNULL`) rather than piped and
never drained, for the same reason: an unread pipe can fill and block the
child regardless of which end is slow.

ONE READER PER SPAWNED PROCESS, NOT PER CALL (cross-model review, this PR).
`_LineReader` buffers past a line boundary - the OS makes no promise that one
`read()` delivers exactly one JSON-RPC message - so building a fresh reader
for the handshake read and a second one for the tool-call read would silently
drop any bytes the first reader had already buffered past its own line. Both
`describe()` and `evaluate()` build exactly one reader per spawn and thread it
through every read that spawn makes.

RESPONSES ARE MATCHED BY ID, NOT BY ARRIVAL ORDER (cross-model review, this
PR). The MCP transport permits a server to interleave notifications (no `id`)
with the response to an outstanding request; a client that treats "the next
line" as "the response" misreads a notification as a malformed response and
fails a call the server actually completed successfully. `_read_result` reads
until it sees a message whose `id` matches the request it is waiting for,
skipping any notification or stale/foreign-id message in between, bounded by
the caller's overall timeout the whole time it does so.

THE REAL TOOL'S OWN SCHEMA IS RESPECTED, NOT WORKED AROUND. The real
`get_code_second_opinion` tool takes `code`/`language` (required) and
`context`/`issue_description`/`error_messages`/`code_files` (optional), with
`additionalProperties: false` - it has no field for a structured list of
criteria to grade. So `_compose_issue_description` embeds the criteria ids as
a JSON array LITERAL inside the `issue_description` string (a real model
reading that instruction is asked to answer in the same shape back), rather
than inventing a non-standard argument the real server would reject outright.
"""

from __future__ import annotations

import json
import os
import select
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import IO

from . import __version__
from .judge import JudgeAnswer, JudgeDescription, JudgeUnavailable

#: The real server's own published name (README, `cooneycw/mcp-second-opinion`).
#: A caller with it on PATH gets it by default; every test overrides this.
DEFAULT_COMMAND: tuple[str, ...] = ("mcp-second-opinion",)
DEFAULT_TOOL_NAME = "get_code_second_opinion"
PROTOCOL_VERSION = "2024-11-05"
_HANDSHAKE_REQUEST_ID = 1
_TOOL_CALL_REQUEST_ID = 2
_CHUNK_SIZE = 65536


class _LineReader:
    """Buffers partial reads across calls so a line split across two OS
    reads, or two lines delivered in one read, are both handled correctly -
    `subprocess` pipes give no such guarantee. POSIX-only (`select`), matching
    this codebase's existing process-group/session assumptions
    (`os.killpg`, `start_new_session`) elsewhere. One instance is built per
    spawned process and reused across every read that process's caller makes,
    so bytes buffered past a line boundary on one read are not discarded
    before the next."""

    def __init__(self, stream: IO[bytes]) -> None:
        self._stream = stream
        self._buf = b""

    def read_line(self, timeout: float) -> bytes | None:
        """One line (without its trailing `\\n`), or `None` on timeout or EOF."""
        deadline = time.monotonic() + timeout
        while b"\n" not in self._buf:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            ready, _, _ = select.select([self._stream], [], [], remaining)
            if not ready:
                return None
            chunk = os.read(self._stream.fileno(), 4096)  # type: ignore[attr-defined]
            if not chunk:
                return None  # EOF - the server closed its output
            self._buf += chunk
        line, _, self._buf = self._buf.partition(b"\n")
        return line


def _compose_issue_description(criteria: Sequence[str]) -> str:
    """Embed the criteria ids as a JSON array literal the model is asked to
    answer back in the same shape - see the module docstring for why this,
    not a structured argument, is how criteria reach a judge whose real tool
    schema has no field for them."""
    return (
        "Grade the candidate code against exactly these criteria ids: "
        f"{json.dumps(list(criteria))}. Respond with a JSON array, one entry "
        'per criterion, each `{"id": <id>, "outcome": "SATISFIED"|"VIOLATED"|'
        '"UNKNOWN", "evidence": [<non-empty strings>]}` (or `"missing": '
        '<reason>` instead of `evidence` for `UNKNOWN`). Every criterion id '
        "listed above must appear exactly once."
    )


def _extract_json_array(text: str) -> list[Mapping[str, object]]:
    """The first `[...]` JSON array of OBJECTS in `text`, or `[]` if none
    parses. A non-object array element is dropped, not returned - the same
    "malformed entry never gets partial trust" rule `skillc.judge.
    parse_judge_verdict` applies one level down applies here to the shape of
    the array itself.

    Uses `json.JSONDecoder.raw_decode` at each candidate `[` rather than
    counting brackets by character (cross-model review, this PR): naive
    bracket counting does not know it is inside a JSON string, so a criterion
    whose own `evidence` text contains a literal `]` character - itself
    perfectly valid JSON - truncated the array early and turned a well-formed
    verdict into `[]`. An array that parses but holds no objects (for example
    an introductory `["R1"]` restating the criteria ids) is skipped rather
    than returned, so a later array that actually holds the verdict is not
    hidden behind it.

    A model's response is free text by nature (the real tool has no
    structured-output mode) - this never raises on a response that ignored
    the instruction entirely; `[]` flows into `skillc.judge.run_tier` as
    "no verdict for any criterion", which is an honest UNKNOWN, not a crash."""
    decoder = json.JSONDecoder()
    start = text.find("[")
    while start != -1:
        try:
            parsed, _ = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            start = text.find("[", start + 1)
            continue
        if isinstance(parsed, list):
            objects: list[Mapping[str, object]] = [item for item in parsed if isinstance(item, dict)]
            if objects:
                return objects
        start = text.find("[", start + 1)
    return []


@dataclass(frozen=True)
class McpSecondOpinionJudge:
    """A real `Judge` (see `skillc.judge.Judge`), talking to an
    `mcp-second-opinion` server as an external process.

    `command` is the argv to spawn the server - override it in any test to
    point at `tests/fixtures/mcp-second-opinion/fake_server.py` instead of
    the real binary. `tier_name` is carried only for error messages; the
    caller decides which `skillc.judge` tier this instance answers for.
    """

    tier_name: str = "independent"
    command: tuple[str, ...] = DEFAULT_COMMAND
    tool_name: str = DEFAULT_TOOL_NAME
    handshake_timeout: float = 10.0
    call_timeout: float = 120.0

    def describe(self) -> JudgeDescription:
        """The MCP `initialize` handshake's `serverInfo` names the SERVER,
        never the LLM behind it, so it is reported as `server_name`/
        `server_version` and `model` stays `None` (#12). The model is only
        known once a call is answered: `evaluate()` reports it."""
        proc = self._spawn()
        try:
            reader = _LineReader(self._stdout(proc))
            server_info = self._handshake(proc, reader)
        finally:
            self._terminate(proc)
        return JudgeDescription(
            name=f"mcp-second-opinion:{self.tier_name}",
            model=None,
            version=None,
            server_name=str(server_info.get("name")) if server_info else None,
            server_version=str(server_info.get("version")) if server_info else None,
        )

    def evaluate(
        self, criteria: Sequence[str], goal_text: str, candidate_files: Sequence[tuple[str, bytes]]
    ) -> JudgeAnswer:
        proc = self._spawn()
        try:
            reader = _LineReader(self._stdout(proc))
            self._handshake(proc, reader)
            self._notify_initialized(proc)
            text, model = self._call_tool(proc, reader, criteria, goal_text, candidate_files)
        finally:
            self._terminate(proc)
        return JudgeAnswer(verdicts=_extract_json_array(text), model=model)

    # ---------------------------------------------------------- MCP wire protocol

    def _spawn(self) -> subprocess.Popen[bytes]:
        try:
            return subprocess.Popen(
                self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            raise JudgeUnavailable(f"cannot start {self.command[0]!r}: {exc}") from exc

    def _stdout(self, proc: subprocess.Popen[bytes]) -> IO[bytes]:
        assert proc.stdout is not None
        return proc.stdout

    def _write(self, proc: subprocess.Popen[bytes], message: dict[str, object], timeout: float) -> None:
        """Writes `message` as one JSON-RPC line, polling for writability
        rather than calling the buffered `stdin.write()` directly - a
        candidate payload can exceed the OS pipe's capacity, and a plain
        blocking write has no deadline at all if the child stops reading
        (cross-model review, this PR: `test_a_stalled_reader_is_a_write_timeout`).

        The fd is NON-BLOCKING for the loop (#129): `select` reports a pipe
        writable when ANY space is free, not when a whole chunk fits, so a
        blocking `os.write` of a chunk larger than the free space waited
        forever once the child stopped reading - the deadline was never
        checked again. Non-blocking, a write takes what fits and a full pipe
        raises `BlockingIOError`, which goes back to `select` and the clock."""
        assert proc.stdin is not None
        stdin = proc.stdin
        fd = stdin.fileno()
        payload = (json.dumps(message) + "\n").encode("utf-8")
        deadline = time.monotonic() + timeout
        sent = 0
        was_blocking = os.get_blocking(fd)
        try:
            os.set_blocking(fd, False)
            while sent < len(payload):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise JudgeUnavailable(f"{self.command[0]!r} did not accept input within {timeout:g}s")
                _, ready, _ = select.select([], [stdin], [], remaining)
                if not ready:
                    raise JudgeUnavailable(f"{self.command[0]!r} did not accept input within {timeout:g}s")
                try:
                    sent += os.write(fd, payload[sent:sent + _CHUNK_SIZE])
                except BlockingIOError:
                    continue
        except (BrokenPipeError, OSError) as exc:
            raise JudgeUnavailable(f"could not write to {self.command[0]!r}: {exc}") from exc
        finally:
            try:
                os.set_blocking(fd, was_blocking)
            except OSError:
                pass  # the pipe may already be gone; nothing left to restore

    def _read_result(self, reader: _LineReader, timeout: float, what: str, expected_id: int) -> dict[str, object]:
        """Reads until a message whose `id` matches `expected_id` arrives,
        skipping any notification (no `id`) or reply to a different request
        in between - both are legal for the server to interleave, and
        neither is this call's own answer (cross-model review, this PR:
        `test_a_notification_before_the_result_is_not_mistaken_for_it`)."""
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise JudgeUnavailable(f"{self.command[0]!r} did not respond to {what} within {timeout:g}s")
            line = reader.read_line(remaining)
            if line is None:
                raise JudgeUnavailable(f"{self.command[0]!r} did not respond to {what} within {timeout:g}s")
            try:
                response = json.loads(line)
            except json.JSONDecodeError as exc:
                raise JudgeUnavailable(f"{self.command[0]!r}'s {what} response is not JSON: {exc}") from exc
            if not isinstance(response, dict):
                raise JudgeUnavailable(f"{self.command[0]!r}'s {what} response is not a JSON object")
            if response.get("id") != expected_id:
                continue  # a notification, or a reply to a different request
            if "result" not in response:
                error = response.get("error")
                raise JudgeUnavailable(f"{self.command[0]!r}'s {what} response carries no result (error: {error!r})")
            result = response["result"]
            if not isinstance(result, dict):
                raise JudgeUnavailable(f"{self.command[0]!r}'s {what} result is not an object")
            return result

    def _handshake(self, proc: subprocess.Popen[bytes], reader: _LineReader) -> Mapping[str, object] | None:
        self._write(proc, {
            "jsonrpc": "2.0", "id": _HANDSHAKE_REQUEST_ID, "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                "clientInfo": {"name": "skillc", "version": __version__},
            },
        }, self.handshake_timeout)
        result = self._read_result(reader, self.handshake_timeout, "initialize", _HANDSHAKE_REQUEST_ID)
        server_info = result.get("serverInfo")
        return server_info if isinstance(server_info, dict) else None

    def _notify_initialized(self, proc: subprocess.Popen[bytes]) -> None:
        # A notification carries no "id" and gets no response - fire and forget.
        self._write(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"}, self.handshake_timeout)

    def _call_tool(
        self, proc: subprocess.Popen[bytes], reader: _LineReader, criteria: Sequence[str], goal_text: str,
        candidate_files: Sequence[tuple[str, bytes]],
    ) -> tuple[str, str | None]:
        code = "\n\n".join(
            f"# {name}\n{content.decode('utf-8', errors='replace')}" for name, content in candidate_files
        )
        arguments = {
            "code": code,
            "language": "text",
            "context": goal_text,
            "issue_description": _compose_issue_description(criteria),
        }
        self._write(proc, {
            "jsonrpc": "2.0", "id": _TOOL_CALL_REQUEST_ID,
            "params": {"name": self.tool_name, "arguments": arguments}, "method": "tools/call",
        }, self.call_timeout)
        result = self._read_result(reader, self.call_timeout, "tools/call", _TOOL_CALL_REQUEST_ID)
        if result.get("isError"):
            content = result.get("content")
            detail = content[0].get("text") if isinstance(content, list) and content and isinstance(content[0], dict) else content
            raise JudgeUnavailable(f"{self.command[0]!r} reported a tool error: {detail!r}")
        content = result.get("content")
        parts = [item.get("text", "") for item in content if isinstance(item, dict) and item.get("type") == "text"] \
            if isinstance(content, list) else []
        return self._reply(result.get("structuredContent"), "\n".join(str(p) for p in parts))

    def _reply(self, structured: object, text: str) -> tuple[str, str | None]:
        """The verdict text and the model that answered, from one tool result.

        The real `get_code_second_opinion` returns an object - `analysis`,
        `model_used`, `success`, `error` (cooneycw/mcp-second-opinion
        `src/server.py`, `get_code_second_opinion`, at eb90aec) - which
        FastMCP sends as `structuredContent` AND as that object's JSON in the
        text content. The verdict array lives INSIDE `analysis`; read from the
        raw text it is JSON-escaped and never parses, so every criterion came
        back UNKNOWN (#12). `model_used` is the model that actually answered,
        a fallback included. `success: false` is the provider failing, which
        is this tier being unavailable, not a verdict. Any other shape is read
        as verdict text with no model stated."""
        payload = structured
        if not isinstance(payload, dict):
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                payload = None
        if not isinstance(payload, dict) or "analysis" not in payload:
            return text, None
        if payload.get("success") is False:
            raise JudgeUnavailable(f"{self.command[0]!r} could not reach its model: {payload.get('error')!r}")
        model = payload.get("model_used")
        analysis = payload.get("analysis")
        return (
            analysis if isinstance(analysis, str) else "",
            model if isinstance(model, str) and model and model != "none" else None,
        )

    def _terminate(self, proc: subprocess.Popen[bytes]) -> None:
        if proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
