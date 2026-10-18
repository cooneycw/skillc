<!-- flow-run n=1 id=1643bcb63aba44bbbab5f5301688125a -->
## Run 1 - issue #470 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #470
- Read at:      2026-10-18T17:05:49Z
- updatedAt:    2026-10-18T15:24:47Z   (context only - moves on comments and labels)
- Body digest:  d0e21c774d1b9c27a8558292e425cd547953cecf4714fcdea3ef531c5f316e87   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 1382 of 1382 (cap 16384)

### Body as read
## Problem

`make leak-check` passed a committed fixture file whose tracebacks contained a Claude Code scratchpad path: an encoded home directory (`-home-<user>-…`), a uid and a session id. The leak check is the gate that keeps owner-identifying paths out of the repository, and it did not recognise the **encoded** form of a home path (dashes instead of slashes), nor the `/tmp/claude-<uid>/…` scratchpad layout.

Found by the counter-model review (pass 2) of the #287 auto6 grader revision. The file was fixed before push (normalized to `<TREE>`). Nit-store record: https://github.com/cooneycw/skillc/issues/20#issuecomment-6251639544

## Why an issue, not only a nit

The owner's standing rule is never to expose identifying details. This gate lets content through to a repository, and nothing downstream re-derives its verdict. A blind spot here is a live privacy risk on every commit, not a cosmetic gap.

## Acceptance

- [ ] `leak-check` flags the encoded home form (`-home-<name>-`), `/tmp/claude-<uid>/` scratchpad paths, and session-id-shaped path segments, in addition to the literal `/home/<name>` it already catches.
- [ ] Committed red cases: each form planted in a fixture file is caught, and a benign look-alike (for example `-home-` inside an unrelated word) is not.
- [ ] A one-time sweep of the current tree with the strengthened check, with any hits fixed.

