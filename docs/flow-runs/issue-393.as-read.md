<!-- flow-run n=1 id=1505c3543da14eeca8e7251d5b5695ad -->
## Run 1 - issue #393 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #393
- Read at:      2026-10-14T17:06:22Z
- updatedAt:    2026-10-14T17:06:03Z   (context only - moves on comments and labels)
- Body digest:  c7e1982cc923ed472f84a9487f512b2c7fbafd05512e7431df3ee39dcf2f5749   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 2751 of 2751 (cap 16384)

### Body as read
## Problem

`DockerBackend.install()` delivers a bytes-backed surface (how every task fixture reaches `/work`) one file at a time through `_owned_tar_bytes(key, value)` (`skillc/docker_backend.py`, around line 1190). Each tar stream holds a **single file entry and no directory entries**. For a nested path such as `tests/test_windows.py`, `docker cp - NAME:/work` therefore creates the missing parent `tests/` itself, **owned by root** (`root:root 0755`). The file is correctly candidate-owned; its parent directory is not.

The candidate (uid 10001) can then edit every existing fixture file, but **cannot create a new file in any fixture subdirectory**.

Reproduced on #315's runner (Docker 29.8.2) with the `86641e8` runtime image:

```
drwxr-xr-x 1 candidate candidate /work
drwxr-xr-x 2 root      root      /work/tests
touch: cannot touch '/work/tests/new.py': Permission denied
```

Observed in the #375 smoke run: the scripted actor for `gate-stops-early`'s reference candidate died on `PermissionError: [Errno 13] Permission denied: '/work/tests/test_windows_regression.py'`.

## Why it matters

This is the real-agent path, not only the campaign's. A real agent asked to add a regression test (what the #270 Level-3 tasks expect: the reference adds `tests/test_windows_regression.py`) cannot create it where the project keeps its tests. It must write somewhere else, or fail. Results from live attempts on any task with nested fixture directories may be shaped by this, which bears on how past live evidence is read. `_owned_tar(host_path)` (the path-backed variant) adds directories recursively and is not affected.

## Outcome

Every directory install creates under `/work` (and under `CONTAINER_HOME` for home-file delivery, if the same shape applies there) is owned by the candidate, so the candidate can create files anywhere in its own workspace.

## Acceptance

- [ ] Installed parent directories are candidate-owned. For example, include an owned directory entry for each missing ancestor in the tar stream, or create the parents as the candidate before copying.
- [ ] Regression control on real Docker, in the #315 floor or an existing live file: after installing a nested bytes surface, the candidate can create a file in the nested directory. This **fails on today's code** with `Permission denied`.
- [ ] Home-file delivery (`deliver_home_file`, `_owned_tar_bytes` into `CONTAINER_HOME`) is checked for the same shape and fixed, or shown unaffected.
- [ ] Say whether existing live evidence (e.g. #203, #287 pilots) involved fixtures with nested directories and agent-created files there, so their reading can be qualified if needed.

## Related

Found by #375's production-path smoke run (PR for #375). Blocks #375's campaign.

