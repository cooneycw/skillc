# Recording skill usage (#719)

`skillc usage hook` writes one `skill-usage` line when a skill starts and one
when the session ends. That way, which skill version ran where, and how it
ended, is recorded by the client rather than left to the model. The record
shape and its four rules are defined in the
[records spec's `skill-usage` section](specs/evaluation-facility/records.md#skill-usage-a-per-repo-usage-log-719).

Records go to `<main checkout>/.skillc/usage.jsonl`. A run from a linked
worktree lands in the same file. The `.skillc/` directory ignores itself
(`.skillc/.gitignore` holds `*`), so nothing is committed by accident.
Nothing is sent anywhere.

## Register the hook by hand

`/cpp:init` does not register it yet; that is a separate CPP-side change. Add
the hook to the `.claude/settings.json` of the repository you want recorded, or
to `~/.claude/settings.json` to record every repository. Use whatever runs
skillc on this host: an installed `skillc`, or
`uv run --quiet --project <skillc checkout> skillc`.

```json
{
  "hooks": {
    "PreToolUse": [
      {"matcher": "Skill", "hooks": [{"type": "command", "command": "skillc usage hook"}]}
    ],
    "UserPromptSubmit": [
      {"hooks": [{"type": "command", "command": "skillc usage hook"}]}
    ],
    "SessionEnd": [
      {"hooks": [{"type": "command", "command": "skillc usage hook"}]}
    ]
  }
}
```

- **PreToolUse, matcher `Skill`:** the model invoked a skill. This writes a
  `start` with `invocation: model-selected`.
- **UserPromptSubmit:** the prompt begins with a typed `/<name>`. This writes a
  `start` with `invocation: explicit`, but only when `<name>` resolves by exact
  lookup to an installed skill (`.claude/skills/<name>/SKILL.md`) or command
  (`.claude/commands/[<ns>/]<name>.md`), in `~/.claude/` first and then the
  project. A built-in such as `/clear`, or a path such as `/tmp/x`, writes
  nothing. A typed `/<skill>` does not also fire a `Skill` tool call (checked
  live, Claude Code 2.1.322), so it is counted once.
- **SessionEnd:** closes every open `start` of this session with an `end`,
  `outcome: "UNKNOWN"`. You can register **Stop** instead, and it behaves the
  same way, but Stop fires at the end of every turn. That closes a skill that is
  paused at an approval gate before it has finished, so prefer SessionEnd.

The hook always exits 0. A payload it cannot use writes nothing and prints a
line to stderr. It never reads the transcript.

## Declaring an outcome (optional)

A skill that knows how it ended can say so:

```bash
skillc usage end --skill flow:auto --outcome stopped --stop-reason approval-gate
```

This closes the oldest open `start` for `($CLAUDE_CODE_SESSION_ID, flow:auto)`
with `origin: declared`. With no open start it writes nothing and prints
`SKILLC_USAGE: no-open-start`. It still exits 0, so the skill calling it never
fails because of it. Nothing depends on this command being called.

## Reading the log

```bash
skillc check-records .skillc/usage.jsonl   # the four skill-usage rules
skillc usage report .skillc/usage.jsonl    # counts by skill and digest, outcome mix, UNKNOWN rate
```

## What is not recorded

- **Codex:** there is no observed route yet (`coverage: unsupported`), so no
  records are written for Codex.
- **Model:** the hook payload does not carry the model, so `model` is
  `"UNKNOWN"`.
- **Plugin skills:** they are recorded, but with `skill_digest: "UNKNOWN"`,
  because their files are not looked up.
