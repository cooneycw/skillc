# Claude Code transcript fixtures (issue #106)

Hand-built, entirely synthetic JSONL matching the REAL on-disk shape a
Claude Code session writes under `~/.claude/projects/<slug>/<uuid>.jsonl` -
observed directly against a real transcript on this host (2026-09-27), never
guessed from documentation alone. Every value here is fake: nonces, skill
names, file paths, uuids, timestamps.

Confirmed shape:

- Each line is one JSON object, `{"type": "user"|"assistant", "message": {...}, ...}`.
- `message.content` is a plain **string** for a real human/CLI prompt, or a
  **list of content blocks** otherwise (`tool_use`, `tool_result`, `text`,
  `thinking`).
- A `tool_use` block: `{"type": "tool_use", "id": ..., "name": ..., "input": {...}}`,
  on an `assistant`-role message.
- A `tool_result` block: `{"type": "tool_result", "tool_use_id": ..., "content": ..., "is_error": bool}`,
  on a **`user`-role** message (Anthropic's own Messages API convention: a
  tool result is delivered as a user-role turn).
- A `Skill` tool invocation is an ordinary `tool_use` block whose `name` is
  literally `"Skill"` and whose `input.skill` names the invoked skill -
  confirmed against 4 real skill invocations in this session's own
  transcript.
- A real `Write` tool's `tool_result.content` is a fixed confirmation
  string ("File created successfully at: ...") - it **never** echoes the
  file's own written content. `live-canary.jsonl` therefore uses a `Bash`
  tool whose command pipes the canary text through `tee` (so it lands in
  the command's own captured stdout, which the tool result DOES carry) -
  see `skillc/transcript_adapter.py`'s module docstring for why this is a
  driver-level choice, not something the adapter can compensate for.

Fixtures:

- `live-canary.jsonl` - a skill invocation, then a tool call whose
  confirmed, error-free output contains the canary marker. Green case.
- `tool-call-fails.jsonl` - the same canary tool call, but its result is
  `is_error: true` and never carries the marker. Red case (#106's own
  acceptance: "red when a tool call is requested but fails").
- `no-op.jsonl` - a prompt and a prose-only reply, no tool call at all. Red
  case (#106's own acceptance: "red on a no-op transcript").
