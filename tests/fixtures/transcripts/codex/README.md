# Codex transcript fixtures (issue #106)

Hand-built, entirely synthetic JSONL matching the REAL on-disk shape a Codex
CLI session writes to `~/.codex/sessions/<date>/rollout-*.jsonl` - observed
directly against live `codex exec` runs on this host (2026-09-27,
codex-cli 0.157.1), never guessed from documentation alone. Every value here
is fake: nonces, skill names, paths, ids.

Confirmed shape (three real, freshly-run probes; details in the PR):

- Each line of interest is `{"type": "response_item", "payload": {...}}`.
- A message: `payload.type == "message"`, with `role` and a `content` list
  of `{"type": "input_text"|"output_text", "text": ...}` blocks.
- **The harness injects a `role: "user"` message wrapped in
  `<environment_context>...</environment_context>` BEFORE the real prompt.**
  It is not the prompt that was sent; a transcript adapter must skip it when
  looking for "the first user message", or every prompt-delivery check would
  compare against harness boilerplate instead of what was actually sent.
- A tool call (Codex has exactly one kind on this host - its own shell/exec
  tool; no distinct "Write" tool the way Claude Code has one):
  `payload.type == "custom_tool_call"`, `name: "exec"`, `call_id`, and
  `input` is the exec call's own **command text**, not structured JSON.
  Paired with `payload.type == "custom_tool_call_output"` by `call_id`.
- **No explicit success/failure field anywhere in the output payload.** The
  only signal is a doubly-JSON-encoded chunk embedded as one of the output
  blocks' `text` values: `{"chunk_id":...,"exit_code":<int>,"output":...}`.
  A caller must parse THAT nested string as its own JSON document to learn
  whether the command failed.
- **Codex has no distinct "skill invocation" transcript event at all** - a
  live probe asking Codex to invoke its own `skill-creator` skill showed
  the agent simply running `cat .../skill-creator/SKILL.md` through the
  ordinary `exec` tool, indistinguishable from any other file read.
  `skillc/transcript_adapter.py`'s Codex skill-invocation detection is
  therefore a NAMED HEURISTIC (a `.../skills/<name>/SKILL.md` path
  referenced in an `exec` command), not a structural guarantee - see that
  module's docstring.
- A real `exec` write command's output only carries the command's OWN
  stdout, never a separately-read file's content - `live-canary.jsonl`'s
  write command therefore pipes the canary text through `tee` so it lands
  in the captured output, exactly like the Claude Code fixture's `Bash`
  command does, and for the same reason (see that fixture's own README).

Fixtures:

- `live-canary.jsonl` - a skill-path `exec` read, then a write `exec` call
  whose exit code is `0` and whose output carries the canary marker. Green
  case.
- `tool-call-fails.jsonl` - the same write call, but `exit_code: 1` and no
  marker in the output. Red case (#106's own acceptance: "red when a tool
  call is requested but fails").
- `no-op.jsonl` - a prompt and a prose-only reply, no tool call at all. Red
  case (#106's own acceptance: "red on a no-op transcript").
- `run-metadata.jsonl` - the run-identity events a real rollout carries
  beside the conversation (issue #12): `session_meta.cli_version`, one
  `turn_context` per turn (`model`, `effort`), cumulative `token_count`
  events, and assistant messages. Two turns with DIFFERENT models and two
  token counts, so a reader that takes the first value instead of the last
  is caught. Shapes observed on a live codex-cli 0.157.1 rollout
  (2026-09-27); every value is fake.
- `exec-command.jsonl` - #486 (2026-10-20). A skill-path read and a canary write,
  each as a `function_call` named `exec_command`. Then one `exec` script that
  batches two calls with `Promise.allSettled` and prints each settled result.
  Every exit is 0. Green case.
- `exec-command-fails.jsonl` - the same shapes, every one unconfirmable:
  - an `exec_command` that exits 1;
  - an `exec_command` result with no exit line;
  - a batch with a REJECTED item;
  - a batch with a non-zero nested `exit_code`;
  - a function call other than `exec_command`;
  - an orphaned `function_call_output`.

  Red case.

### The 2026-10-20 shapes (#486)

On 2026-10-20, the same client (codex-cli 0.157.1) and model (gpt-6-astra)
produced two shapes that none of the fixtures above contains. #434's live
campaign then graded 0 of 10 attempts. These fixtures MIRROR that capture in
shape only. The real lines are the owner's private run evidence and are not
committed. `tests/test_transcript_adapter.py` reads them from the private store
when it is present, and skips loudly, naming the path, when it is not.

- `{"type": "function_call", "name": "exec_command", "call_id": ..., "arguments":
  "<JSON string>"}`. The arguments are `{"cmd", "max_output_tokens"[, "workdir"]}`.
  It pairs by `call_id` with `{"type": "function_call_output", "output":
  "<string>"}`. The output is a plain string whose exit status is a line
  `Process exited with code N`; there is no JSON `exit_code`.
- `exec` is a SCRIPT runner. A script that batches calls prints each settled
  result itself, e.g. `{"i":N,"result":{"status":"fulfilled","value":{"chunk_id":
  ...,"exit_code":0,...}}}`. A rejected call reads `"status":"rejected"` with a
  `reason`. Other observed prints are `{"status":...,"value":...}` and
  `{"part":N,"status":...}`. So the exit code is NESTED, wherever the script put
  it. The adapter reads every nested `exit_code` and treats any rejection as a
  failure, and the worst result wins.
- Lines also carry `id`, `internal_chat_message_metadata_passthrough`, and
  top-level `timestamp`, `ordinal` and `metadata`. The adapter ignores them. The
  fixtures carry fake values, so the shape is faithful.
