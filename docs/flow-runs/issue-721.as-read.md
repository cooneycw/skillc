<!-- flow-run n=1 id=57303a2d067448379328d46da1d61f75 -->
## Run 1 - issue #721 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #721
- Read at:      2026-11-14T21:27:40Z
- updatedAt:    2026-11-14T20:18:08Z   (context only - moves on comments and labels)
- Body digest:  92e829ac8d3dbef3c28d9da4e534ea238055041f96bc62ec9b03107787c79054   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 1403 of 1403 (cap 16384)

### Body as read
## What is wrong

`skillc usage hook` follows symlinks when it writes. In `skillc/usage.py`:
- `ensure_ignored()` may append `usage.jsonl` to `.skillc/.gitignore`.
- `append()` opens `.skillc/usage.jsonl` with `a+`.

Both follow a symlink. A checkout could ship either file as a symlink to any file the user can write, for example an SSH config. The hook runs automatically on every `Skill` call, so recording one skill invocation would append a line, or JSON records, to that target.

## Why it matters

This is a write-through from content a repository controls into files outside it. It happens from a hook that runs with no prompt. Right now nobody is exposed: #719 ships the hook unregistered, and registration is by hand (`docs/skill-usage-hook.md`). It becomes live the first time someone registers the hook globally.

## Fix

- Refuse a symlinked `.skillc/` directory, `.skillc/.gitignore` or `.skillc/usage.jsonl` before writing anything.
- Open files with `O_NOFOLLOW`, so nothing is checked and then swapped before the open.
- Add a regression case asserting that the symlink target is unchanged, and run it on the pre-fix code first so it is shown to fail there.

Found by the counter-model review (Codex, codex/gpt-6.1-sol, pass 3) of the #719 branch `issue-719-skill-usage-records-and-a-hook-that-writes-them-sk`. The owner's ruling was to defer pass-3 findings, not fix them. Refs #719.


<!-- end of body -->
