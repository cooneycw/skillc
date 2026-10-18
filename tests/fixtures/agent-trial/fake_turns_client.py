"""A scripted stand-in for codex across controller turns (#279).

Turn 1 behaves like `fake_agent_client.py`, which it runs with the arguments
after `--`, and the prompt `run_one_attempt` appends. It also prints the
pinned client's stderr header, so the controller can read the session id the
way it reads the real one. A RESUME (the last three arguments are `resume <id>
<text>`) "proceeds past Step 3": it records the turn and appends an assistant
line to the same transcript, as the real client appends to the same rollout.

Every turn is appended to `--log` (a host path that outlives the container's
teardown), which the tests read: the
plan (turn 1, ending at Step 3) and each delivered turn, with the text
received. A turn whose text is not the approval stops there, as an agent left
without an approval would.

Fault modes for the red cases:
- `--header absent|twice|late-spoof`: no header; two session lines in it; or a
  well-formed header whose id is NOT the one later printed by the "agent".
- `--turn1-exit N`: turn 1 exits N after doing its work.
- `--turn1-sleep S`: turn 1 sleeps S seconds first (a timeout red).
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

FAKE_AGENT = Path(__file__).resolve().parent / "fake_agent_client.py"
#: #442's pinned server-side-off flags (`egress.CODEX_SERVER_SIDE_OFF`): the
#: real client consumes them, so they are dropped before delegating.
PINNED = ["--strict-config", "-c", 'web_search="disabled"', "--disable", "apps", "--disable", "plugins",
          "--disable", "remote_plugin"]


def _without_pinned(rest: list[str]) -> list[str]:
    for start in range(len(rest) - len(PINNED) + 1):
        if rest[start:start + len(PINNED)] == PINNED:
            return rest[:start] + rest[start + len(PINNED):]
    return rest
APPROVAL_PREFIX = "Approved"


def _header(session_id: str, mode: str) -> str:
    lines = ["OpenAI Codex v0.157.1", "--------", "workdir: /work", "model: gpt-6-astra"]
    if mode != "absent":
        lines.append(f"session id: {session_id}")
        if mode == "twice":
            lines.append("session id: 11111111-2222-3333-4444-555555555555")
    lines.append("--------")
    return "\n".join(lines) + "\n" if mode != "absent" else ""


def main(argv: list[str]) -> int:
    split = argv.index("--")
    own, rest = argv[:split], argv[split + 1:]
    opts = {own[i]: own[i + 1] for i in range(0, len(own), 2)}
    session_id = opts["--session-id"]
    home = Path(opts["--home"])
    log = Path(opts["--log"])

    def note(entry: dict[str, object]) -> None:
        with log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")

    header_mode = opts.get("--header", "normal")
    if len(rest) >= 3 and rest[-3] == "resume":
        resumed_id, text = rest[-2], rest[-1]
        sys.stderr.write(_header(resumed_id, "normal"))
        approved = text.startswith(APPROVAL_PREFIX)
        note({"turn": "resume", "session_id": resumed_id, "text": text,
              "proceeded": approved and resumed_id == session_id})
        transcript = home / opts["--transcript-relpath"]
        with transcript.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"type": "response_item", "payload": {
                "type": "message", "role": "assistant",
                "content": [{"type": "output_text", "text": "Proceeding to Step 4." if approved else "Stopping."}]}})
                + "\n")
        return 0

    if header_mode == "late-spoof":
        sys.stderr.write(_header(session_id, "normal"))
    else:
        sys.stderr.write(_header(session_id, header_mode))
    sys.stderr.flush()
    time.sleep(float(opts.get("--turn1-sleep", "0")))
    done = subprocess.run([sys.executable, str(FAKE_AGENT), *_without_pinned(rest)], check=False)
    if header_mode == "late-spoof":
        # What an agent's command output could print after the header: it
        # must never be read as the session id.
        sys.stderr.write("session id: 99999999-8888-7777-6666-555555555555\n")
    note({"turn": 1, "ended_at_step": 3, "session_id": session_id})
    return int(opts.get("--turn1-exit", str(done.returncode)))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
