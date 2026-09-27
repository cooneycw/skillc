#!/usr/bin/env python3
"""A fake MCP stdio server, standing in for a real `mcp-second-opinion`
process in tests (#69 follow-up: "No real model call in the test suite").

Speaks the same subset of MCP-over-stdio the real adapter
(`skillc/judge_mcp_second_opinion.py`) uses: line-delimited JSON-RPC 2.0 on
stdin/stdout, an `initialize` handshake, and one `tools/call`. Reads its MODE
from argv[1] to simulate each failure class the adapter must handle without a
network:

  happy                  - a well-formed handshake and a well-formed verdict array
  garbage-handshake      - responds to initialize with invalid JSON
  hang                   - never writes anything at all (exercises the read timeout)
  tool-error             - handshake succeeds; tools/call returns isError: true
  unparseable-verdict    - handshake succeeds; tool result text is not JSON
  stall-after-handshake  - handshake succeeds, then never reads again (exercises
                           the WRITE timeout: a large enough tools/call payload
                           fills the OS pipe because nothing drains it)
  notify-before-result   - handshake succeeds; the tools/call response is
                           preceded by a notification carrying no "id"

Stdlib only, matching every other fake subprocess fixture in this repo
(`fake_docker.py`, `fake_subject.py`).
"""

from __future__ import annotations

import json
import re
import sys
import time

#: Matches the real adapter's own convention: it embeds the criteria ids as
#: a JSON array literal inside `issue_description`
#: (`skillc/judge_mcp_second_opinion.py`'s `_compose_issue_description`), so
#: this fake server (standing in for a real model that read the same
#: instruction) can answer for exactly the criteria actually asked about,
#: without needing a non-standard MCP argument the real tool schema forbids.
_CRITERIA_ARRAY_RE = re.compile(r"\[(?:\s*\"[^\"]*\"\s*,?)*\]")


def _read_request() -> dict[str, object] | None:
    line = sys.stdin.readline()
    if not line:
        return None
    return json.loads(line)


def _write(message: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "happy"

    if mode == "hang":
        time.sleep(3600)
        return 0

    request = _read_request()  # initialize
    if request is None:
        return 1

    if mode == "garbage-handshake":
        sys.stdout.write("not even json\n")
        sys.stdout.flush()
    else:
        _write({
            "jsonrpc": "2.0", "id": request.get("id"),
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "serverInfo": {"name": "fake-mcp-second-opinion", "version": "0.0.1-fake"},
            },
        })

    # The client sends a fire-and-forget "initialized" notification (no id,
    # no response expected) and then the tool call.
    notification = _read_request()
    if notification is None:
        return 0

    if mode == "stall-after-handshake":
        # Never read the tools/call request at all - the client's own write
        # of it must eventually fill the OS pipe and time out on its own,
        # never hang forever waiting for a read that will not happen.
        time.sleep(3600)
        return 0

    call = _read_request()
    if call is None:
        return 0
    call_id = call.get("id")

    if mode == "notify-before-result":
        # A notification (no "id") interleaved before the real response -
        # legal MCP traffic the client must not mistake for the answer.
        _write({"jsonrpc": "2.0", "method": "notifications/progress", "params": {}})
        _write({
            "jsonrpc": "2.0", "id": call_id,
            "result": {
                "content": [{"type": "text", "text": json.dumps([
                    {"id": "R1", "outcome": "SATISFIED", "evidence": ["fake-mcp:R1"]},
                ])}],
                "isError": False,
            },
        })
    elif mode == "tool-error":
        _write({
            "jsonrpc": "2.0", "id": call_id,
            "result": {"content": [{"type": "text", "text": "provider unreachable"}], "isError": True},
        })
    elif mode == "unparseable-verdict":
        _write({
            "jsonrpc": "2.0", "id": call_id,
            "result": {"content": [{"type": "text", "text": "Looks fine to me, no notes."}], "isError": False},
        })
    else:  # happy
        params = call.get("params")
        arguments = params.get("arguments") if isinstance(params, dict) else None
        issue_description = arguments.get("issue_description") if isinstance(arguments, dict) else None
        match = _CRITERIA_ARRAY_RE.search(issue_description) if isinstance(issue_description, str) else None
        criteria = json.loads(match.group(0)) if match else []
        verdicts = [
            {"id": cid, "outcome": "SATISFIED", "evidence": [f"fake-mcp:{cid}"]}
            for cid in criteria
        ]
        _write({
            "jsonrpc": "2.0", "id": call_id,
            "result": {"content": [{"type": "text", "text": json.dumps(verdicts)}], "isError": False},
        })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
