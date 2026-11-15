<!-- flow-run n=1 id=789ed24f39ea45c3ad92acbce5c942c6 -->
## Run 1 - issue #724 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #724
- Read at:      2026-11-14T23:31:45Z
- updatedAt:    2026-11-14T20:18:11Z   (context only - moves on comments and labels)
- Body digest:  aeef3209cfca6ed18b5e746b19a146b283567bb3640dad858aa48e43223df4a1   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 1178 of 1178 (cap 16384)

### Body as read
## What is wrong

`skillc/usage.py` assumes the wrong things about where a checkout's git data lives:
- `destination()` treats any git common directory whose name is not `.git` as a bare repository, and returns no destination.
- `collection_of()` returns `UNKNOWN` for the same reason.

The assumption is wrong for submodules, whose common dir is usually `.git/modules/<name>`, and for `--separate-git-dir` checkouts, whose common dir can have any name.

## Why it matters

In those layouts the hook silently records nothing. This fails safe, since nothing wrong is written, but submodule-hosted skill collections drop out of the usage history without any signal. An empty log there looks like "no skill was used".

## Fix

Ask git directly whether the repository is bare (`git rev-parse --is-bare-repository`), and resolve the main checkout from git's worktree metadata instead of from the common dir's parent. Cover a submodule and a `--separate-git-dir` checkout in tests, with each test shown failing on the pre-fix code.

Found by the counter-model review (Codex, codex/gpt-6.1-sol, pass 2) of the #719 branch. The owner ruled it deferred, since it fails safe. Refs #719.


<!-- end of body -->
