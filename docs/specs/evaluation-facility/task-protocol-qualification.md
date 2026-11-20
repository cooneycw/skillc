# Task-protocol socket: physical qualification probe (#620 PR-B, B0)

Status: qualification instrument. This adds no controller, receiver or client, and
it grants no live run, model call, credential or image change. CI runs only the
no-Docker `selftest`. Physical readings come later, from a separately authorized
run on the evaluation environment.

The accepted design ([task-protocol-stream.md](task-protocol-stream.md), section 2)
marks three deployment facts UNVERIFIED: read-only socket mount behavior,
peer-credential visibility and exclusive runtime mapping. It requires model-free
qualification of each before declared use. `scripts/probe_task_protocol_socket.py`
measures them. The owner's 2026-11-20 ruling on #620 allows a second
controller-named mount and lets this probe's readings choose its shape.

## What it measures

| Fact | Built-in control, run first | Measured | `fails` means |
| --- | --- | --- | --- |
| F1 `ro-mount:file`, `ro-mount:dir` | No mount: no endpoint may answer. World-writable rw mount: the endpoint must be replaceable. | The candidate connects, then tries unlink, rename away, rename over, file create, socket bind and mkdir, then reconnects. Mount options come from `/proc/self/mountinfo`. | Connect refused with the mount present, another listener reached, mount rw, any replace succeeded, or the endpoint lost |
| F1 `recreate:file`, `recreate:dir` | The sandbox reached the original listener, and a host process reaches the new one. | The host unlinks and re-binds the lease socket while the sandbox lives, then the sandbox reconnects. | Not a gate: reports `reaches-new` or `dead-end` |
| F2 `peercred` | Per basis: a separate host process must NOT identify as the sandbox. | From `SO_PEERCRED`'s pid, for the owned sandbox and for a second sandbox under the same candidate uid on the same listener: the `ns` basis (PID-namespace inode) and the `cgroup` basis (cgroup v2 `docker-<id>.scope`, confirmed against the owned container's init process), with the start time read before and after. | A readable basis does not identify the owned sandbox, identifies the same-uid sibling, or sees remapped credentials. Any readable basis failing (including two bases disagreeing) fails the fact |
| F3 `exclusive:file`, `exclusive:dir` | Deliberate mis-mount (A's endpoint also mounted in B): the audit of the daemon's own mount records must refuse it, and B's reach scan must see A. | Two sandboxes with one lease each: the audit, plus a scan of every in-sandbox mount point for reachable listeners. | The audit refuses the healthy pair (shared ancestor, extra or rw endpoint mount, Docker socket, privileged or host namespace), or a sandbox reaches the other's listener |

The design treats peer identity as unprovable when the peer's PID is 0 or
invisible, its namespace is unreadable, or its start time changes during the probe.
Each of those reads `not-covered`, never `holds`.

F2 reports two bases, each with its own control and its own verdict:

- `ns` compares the peer's PID-namespace inode with the owned container's. Reading
  another uid's `/proc/<pid>/ns/pid` needs ptrace-level access, so a non-root
  controller reads it as `not-covered`. That is an honest answer about the
  controller's identity, not a refuted fact.
- `cgroup` reads the world-readable `/proc/<pid>/cgroup`. It identifies only a
  single cgroup v2 line naming exactly one `docker-<64 hex>.scope` component, and
  only when the owned container's own init process is in that scope. A cgroupfs
  path, a v1 or hybrid layout, an unreadable file, or an init process in another
  scope reads `not-covered`.

The fact holds only if at least one readable basis discriminates. It is not covered
if no basis is readable, and it fails if any readable basis fails. A start time is
read before and after every peer read, so a pid that exited or was reused between
`SO_PEERCRED` and the read is `not-covered`.

## Outcomes and exit codes

Each gated fact is `holds`, `fails` or `not-covered`, and the probe never merges
them. A real fact failure is its most important answer, so it is never reported as
`not-covered`. Exit codes: `0` every requested fact holds, `4` at least one fails,
`3` nothing fails but something is not covered, `2` usage. `selftest` exits `0`
pass, `1` fail, `3` unreadable cases.

The receipt records the image id and repo digests, the daemon's server version,
security options, cgroup driver and version, the daemon and local kernel versions,
and the daemon endpoint scheme. If any of these is unreadable, or the daemon is not
local, every fact is `not-covered`: bind mounts and `SO_PEERCRED` only mean
something beside the daemon. The receipt records the scheme only, never a
`DOCKER_HOST` value.

## Choosing the mount shape

The 2026-11-20 ruling sets two conditions:

- (A) A single-file read-only bind is used only if the controller never recreates
  the socket while a sandbox lives. The bind pins the old inode, and
  `recreate:file` is expected to read `dead-end`.
- (B) Otherwise a read-only controller-owned parent directory holding only that
  socket is used. `recreate:dir` is expected to read `reaches-new`.

Whether the controller recreates a lease socket during a sandbox's life is a B4/B5
design decision, recorded there. The design's revocation is durable and an old
endpoint is never reassigned, which argues for revocation by close rather than by
replace. These expectations are hypotheses for the physical run to confirm or
refute, not readings.

## Limits

- The probe sandboxes use `--network none`, `--cap-drop ALL`,
  `no-new-privileges` and the candidate uid. They do not reproduce the full trial
  launch argv, so the readings qualify kernel and daemon behavior for these mount
  shapes, not a specific trial launch.
- The reach scan walks mount points other than the image root and kernel
  filesystems, up to a bound, and reads `not-covered` past it. A host listener can
  only appear through a mount.
- The probe never pulls. The image must already be present and must provide
  `python3`, as trial images do.
- The audit here is the probe's own. B5b's production audit gets its own controls
  and must not cite this probe as its qualification.
