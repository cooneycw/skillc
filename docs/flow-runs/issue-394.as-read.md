<!-- flow-run n=1 id=ca3db0a89f7144488a1f3d32936bceb8 -->
## Run 1 - issue #394 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #394
- Read at:      2026-10-14T17:11:45Z
- updatedAt:    2026-10-14T17:06:30Z   (context only - moves on comments and labels)
- Body digest:  9a35ade04e6e301930cf7ffcce3636450802f07b8d060e07dcfa8b3829b48b5b   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 3389 of 3389 (cap 16384)

### Body as read
## Problem

On #315's certified runner (Docker 29.8.2, overlayfs with the containerd snapshotter, `86641e8` runtime image `sha256:e5131d76…`), **every witnessed live attempt fails capture**:

```
capture failed: export failed: docker cp export failed for 'a-…': Error response from daemon: Could not find the file /work/. in container skillc-a-…
```

The attempt is then `inconclusive`, and grading never runs.

Observed in #375's smoke run: 3 of 3 rows (`gse.reference`, `gse.fixture`, `gse.wrong.unconditional-green`), plus one instrumented rerun. The failure does **not** depend on what the subject did. The no-op row's actor exited 0 and capture still failed.

## What the instrumented run showed

`DockerBackend.export` was wrapped to dump the container's state immediately before the real export:

- **The exports before the agent's main capture all succeeded,** with the attempt's container `running`. `docker exec ls -la /work` listed the installed workspace.
- **The failing export runs once the agent container has `exited` (137).** At that point `docker diff` reports only `C /run`: not the `/work` contents installed by `docker cp -`, not the closure under `/home/candidate`, not even the `A /usr/sbin/docker-init` that every `--init` container shows. `docker cp …:/work/.` then reports that `/work` does not exist.
- **Mounts:** only the controller trigger socket, a bind mount at `/run/skillc/trigger.sock`.

## What it is not (each reproduced on the same host and image)

| Setup | `docker cp …:/work/.` after the container stops |
|---|---|
| plain container, file written via `docker exec`, `docker stop` | works |
| same, `docker kill` | works |
| same plus a bind mount at `/run/skillc/trigger.sock`, `docker kill` | works; `docker diff` shows `/usr/sbin/docker-init` and the `/work` change as expected |

So the loss comes from something in the full production sequence between the agent exiting and the export: the lifecycle's stop/confirm, the witness finish, the runtime environment, or the resource flags (`--memory 1g`, `--pids-limit`, `--cpus`, `--shm-size`, `--hostname`, labels). It is not a plain stop, a kill, or the bind mount alone. **Root cause not yet established.**

## Why it matters

Until this is fixed, no witnessed live attempt on the certified runner can be graded, whether the subject is scripted or a real model. #375's campaign is blocked on it, and so would any live study on this host be. #315's 23-run certification did not cover this: the real-Docker floor exercises backend pieces directly and never runs a full lifecycle capture after stop.

## Acceptance

- [ ] Root cause identified and stated: which step makes the exited container's filesystem unreadable to `docker cp`.
- [ ] Fixed in production code, not the campaign harness. Possibilities: capture before the stop, or whatever the cause dictates.
- [ ] Regression control on real Docker that runs the full production lifecycle (install, execute, stop, export). It **fails on today's code** on the runner and passes after the fix. It belongs in the #315 floor so the runner keeps checking it.
- [ ] #375's smoke rows then capture and grade.

## Related

Found by #375's production-path smoke run. Blocks #375. #393 (root-owned install directories) was found in the same run. It is independent but sits on the same path, so fix #393 first so a retest isn't blocked by it.

