"""Per-client transcript adapters (issue #106, split 1 of 2: the driver loop
itself is a separate PR under the same issue).

`skillc/trial_bootstrap.verify_first_user_message` and `.check_canary`
already consume, and are already tested against
(`tests/test_trial_bootstrap.py`), a fixed NORMALIZED event shape:

  - a message:         {"role": ..., "content": ...}
  - a skill invocation: {"type": "skill_invocation", "skill": <name>}
  - a tool use:         {"type": "tool_use", "output": ..., "error": <bool>}

Both functions' own docstrings name translating a client's REAL on-disk
transcript into this shape as "a thin per-client adapter, owed to the live
run" - this module is that adapter, one function per client
(`parse_claude_code_transcript`, `parse_codex_transcript`), each taking the
transcript file's raw text and returning a list of normalized events.

GROUNDED IN REAL TRANSCRIPTS, NOT GUESSED. Every shape below was read
directly from a real Claude Code transcript on this host, and from three
freshly-run, live `codex exec` transcripts (2026-09-27, codex-cli 0.157.1) -
never invented from documentation or memory alone. Issue #98's own
credential-schema bug (a guessed JSON key path that would have refused every
real Codex login) is exactly the failure mode this discipline exists to
avoid repeating. `tests/fixtures/transcripts/{claude-code,codex}/` are
hand-built and entirely synthetic (fake nonces, names, ids) but match the
REAL shapes observed, documented in each directory's own README.

WHAT THIS MODULE DOES NOT DO - owed to #106's driver-loop half, not this
one. That issue's own scope item 7 states the adapter "must pair a tool call
with its success result, OR READ THE FILE BACK, so the canary can pass on a
genuinely live run." This module does the FIRST half only: pairing a tool
call with whatever result the transcript itself already contains. It cannot
do the second half - reading a file back requires a LIVE filesystem (a
running container), which a pure transcript parser has no access to.
Confirmed empirically, not assumed: a real Claude Code `Write` tool result
is a fixed confirmation string ("File created successfully at: ...") that
NEVER echoes the file's own content, and a real Codex `exec` result only
carries the command's OWN stdout, never a separately-read file's content -
so a canary WRITE COMMAND that does not itself echo the written text to
stdout (a bare `... > file`, versus `... | tee file`) will not satisfy
`check_canary` against a real transcript from either client, however this
module parses it. Which command the canary instruction actually runs is a
DRIVER decision, deliberately not made here.

CODEX HAS NO SKILL_INVOCATION TRANSCRIPT MARKER OF ITS OWN (confirmed
empirically, 2026-09-27): unlike Claude Code's dedicated `Skill` tool call,
"invoking a skill" is not a distinct tool or event type in Codex's rollout
format at all. A live probe asking Codex to invoke its own `skill-creator`
skill showed the agent simply running `cat .../skill-creator/SKILL.md`
through its ordinary `exec` tool - indistinguishable in the transcript from
any other file read. `_codex_skill_name_from_exec_input` is therefore a
NAMED HEURISTIC (an `exec` command referencing a `.../skills/<name>/SKILL.md`
path), not a structural guarantee - easily defeated by a different reader
tool, a relative path, or a renamed file. Say so wherever its result is used.

Stdlib only (AGENTS.md): `json`, `re`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping

NormalizedEvent = dict[str, object]

#: Claude Code's own `Skill` tool - a `tool_use` block whose `name` is
#: exactly this, confirmed against four real skill invocations in a real
#: transcript on this host.
_CLAUDE_SKILL_TOOL_NAME = "Skill"


def parse_claude_code_transcript(raw_jsonl: str) -> list[NormalizedEvent]:
    """Normalize a real Claude Code transcript (the raw text of a
    `~/.claude/projects/<slug>/<uuid>.jsonl` file) into skillc's fixed event
    shape.

    Message events are appended in FILE ORDER (`verify_first_user_message`
    depends on this to find the first one); `tool_use`/`skill_invocation`
    events are appended afterward and in no particular order, since
    `check_canary` only ever asks "does any event of this type/value exist"
    with no ordering requirement.

    A `tool_use` block with no matching `tool_result` anywhere in the
    transcript (the call never completed) contributes NO `tool_use` event -
    an unconfirmed call is not "confirmed, error-free output", so omitting
    it entirely is equivalent to, and simpler than, emitting one with
    `error=True`. A `Skill` tool_use DOES still contribute a
    `skill_invocation` event regardless of whether its own tool_result ever
    arrives - that event means "the agent requested this skill", never "and
    it was confirmed successful" (`check_canary`'s own two-track design:
    skill_invocation is a request signal, tool_use is a confirmed-output
    signal, deliberately not the same check).
    """
    tool_use_blocks: dict[str, Mapping[str, object]] = {}
    tool_results: dict[str, Mapping[str, object]] = {}
    events: list[NormalizedEvent] = []

    for line in raw_jsonl.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict) or obj.get("type") not in ("user", "assistant"):
            continue
        message = obj.get("message")
        if not isinstance(message, Mapping):
            continue
        role = message.get("role")
        content = message.get("content")

        if isinstance(content, str):
            events.append({"role": role, "content": content})
            continue
        if not isinstance(content, list):
            continue

        # A LIST-valued message can carry a genuine prompt too - the
        # Messages API allows plain `text` blocks alongside or instead of a
        # bare string (cross-model review: an earlier version only ever
        # read `content` as a string here, so a real prompt delivered as
        # `[{"type": "text", "text": ...}]` silently vanished, and
        # `verify_first_user_message` would then either refuse a real
        # delivery or wrongly accept a LATER string-valued message as the
        # first one). A tool-result-only turn must never become a message
        # event, so this only fires when the list carries no `tool_result`
        # block at all.
        has_tool_result = any(
            isinstance(block, Mapping) and block.get("type") == "tool_result" for block in content
        )
        if not has_tool_result:
            text_parts: list[str] = []
            for block in content:
                if not isinstance(block, Mapping) or block.get("type") != "text":
                    continue
                text = block.get("text")
                if isinstance(text, str):
                    text_parts.append(text)
            if text_parts:
                events.append({"role": role, "content": "\n".join(text_parts)})

        for block in content:
            if not isinstance(block, Mapping):
                continue
            block_type = block.get("type")
            if block_type == "tool_use":
                tool_id = block.get("id")
                if isinstance(tool_id, str):
                    tool_use_blocks[tool_id] = block
                if block.get("name") == _CLAUDE_SKILL_TOOL_NAME:
                    tool_input = block.get("input")
                    skill = tool_input.get("skill") if isinstance(tool_input, Mapping) else None
                    events.append({"type": "skill_invocation", "skill": skill})
            elif block_type == "tool_result":
                tool_use_id = block.get("tool_use_id")
                if isinstance(tool_use_id, str):
                    tool_results[tool_use_id] = block

    for tool_id in tool_use_blocks:
        result = tool_results.get(tool_id)
        if result is None:
            continue
        events.append({
            "type": "tool_use",
            "output": result.get("content"),
            "error": bool(result.get("is_error")),
        })

    return events


#: The harness-injected wrapper a real Codex transcript's FIRST `user`-role
#: message carries, ahead of the actual prompt - confirmed empirically
#: (2026-09-27): every live probe's first `user` message was this, never
#: the text actually sent. Matched by prefix, not equality, since the tag's
#: own contents (cwd, sandbox mode) vary per run.
_CODEX_ENV_CONTEXT_PREFIX = "<environment_context>"

#: An `exec` command referencing a `.../skills/<name>/SKILL.md` path -
#: see this module's own docstring for why this is a named heuristic, never
#: a structural guarantee. BOTH boundaries are required (cross-model
#: review): the lookbehind refuses a bare substring match on a directory
#: like `oldskills/demo-skill/SKILL.md` (which is not a `skills/` directory
#: at all, merely a name ending in those letters), and the lookahead
#: refuses a suffixed file like `SKILL.md.bak` (a backup copy, never read
#: as a real invocation) - an unanchored version of this regex matched both.
_CODEX_SKILL_PATH_RE = re.compile(
    r'(?<![\w.-])skills/([\w.-]+)/SKILL\.md(?=$|[\s"\'])', re.IGNORECASE
)


def _codex_message_text(content: object) -> str:
    if not isinstance(content, list):
        return ""
    parts = []
    for block in content:
        if isinstance(block, Mapping):
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts)


def _codex_output_text(output: object) -> str:
    """Codex's `custom_tool_call_output.output` is observed in BOTH shapes
    on this host: a bare string (one live probe), and a list of
    `{"type": "input_text", "text": ...}` blocks (two others) - never assume
    one over the other."""
    if isinstance(output, str):
        return output
    if isinstance(output, list):
        parts = []
        for block in output:
            if isinstance(block, Mapping):
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    return ""


def _codex_exec_exit_code(output_text: str) -> int | None:
    """The embedded, DOUBLY-JSON-ENCODED chunk(s) a real `exec` call's
    output carries (confirmed empirically, 2026-09-27): one or more lines
    within `output_text` that each parse as JSON with an integer
    `exit_code` key - the `chunk_id` field observed alongside it implies a
    long-running command's output CAN arrive as more than one chunk, never
    confirmed as exactly one.

    Scans EVERY parseable chunk and returns the WORST (any non-zero beats
    a zero, found by cross-model review): a single `exec` call whose
    output contains one chunk reporting `exit_code: 0` and another
    reporting `exit_code: 1` must read as failed, not as whichever chunk
    happened to parse first - taking "the first chunk found" let an
    unrelated successful chunk certify a failed one's output as confirmed.
    `None` only when NO chunk yields a determinable exit code at all -
    never guessed as `0` ("probably succeeded"), matching this codebase's
    "undeterminable is refused/treated as failure, never assumed fine" rule
    (see `skillc/credential.py`)."""
    best: int | None = None
    for raw_line in output_text.splitlines():
        candidate = raw_line.strip()
        if not candidate.startswith("{"):
            continue
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            exit_code = parsed.get("exit_code")
            if isinstance(exit_code, int) and not isinstance(exit_code, bool):
                if exit_code != 0:
                    return exit_code  # any failure anywhere wins immediately
                best = 0
    return best


def _codex_skill_name_from_exec_input(input_text: str) -> str | None:
    match = _CODEX_SKILL_PATH_RE.search(input_text)
    return match.group(1) if match is not None else None


def parse_codex_transcript(raw_jsonl: str) -> list[NormalizedEvent]:
    """Normalize a real Codex transcript (the raw text of a
    `~/.codex/sessions/<date>/rollout-*.jsonl` file) into skillc's fixed
    event shape - see this module's own docstring for the two named,
    documented gaps (no read-back, no structural skill marker) this
    function cannot close by itself.

    A `custom_tool_call_output` with no matching `custom_tool_call` (an
    orphaned result), or an `exec` call whose output carries no parseable
    `exit_code`, is treated as `error=True` - undeterminable, never assumed
    successful. A non-`exec` tool call (e.g. an MCP tool) has no observed
    success/failure convention on this host at all, and is likewise always
    `error=True` for the same reason: this adapter's own `tool_use` events
    exist to support `check_canary`'s CONFIRMED-output requirement, and an
    unconfirmable result cannot satisfy it either way.
    """
    calls: dict[str, Mapping[str, object]] = {}
    events: list[NormalizedEvent] = []

    for line in raw_jsonl.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict) or obj.get("type") != "response_item":
            continue
        payload = obj.get("payload")
        if not isinstance(payload, Mapping):
            continue
        payload_type = payload.get("type")

        if payload_type == "message":
            role = payload.get("role")
            if role not in ("user", "assistant"):
                continue
            text = _codex_message_text(payload.get("content"))
            if role == "user" and text.startswith(_CODEX_ENV_CONTEXT_PREFIX):
                continue
            events.append({"role": role, "content": text})

        elif payload_type == "custom_tool_call":
            call_id = payload.get("call_id")
            if isinstance(call_id, str):
                calls[call_id] = payload

        elif payload_type == "custom_tool_call_output":
            call_id = payload.get("call_id")
            call = calls.get(call_id) if isinstance(call_id, str) else None
            output_text = _codex_output_text(payload.get("output"))

            if call is not None and call.get("name") == "exec":
                exit_code = _codex_exec_exit_code(output_text)
                error = exit_code is None or exit_code != 0
                input_text = call.get("input")
                if isinstance(input_text, str):
                    skill = _codex_skill_name_from_exec_input(input_text)
                    if skill is not None:
                        events.append({"type": "skill_invocation", "skill": skill})
            else:
                error = True

            events.append({"type": "tool_use", "output": output_text, "error": error})

    return events
