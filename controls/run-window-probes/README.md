# Run-window probes (Refs #797, #630)

These are the physical-fact probes P1–P8 from
[run-window-contracts.md](../../docs/specs/evaluation-facility/run-window-contracts.md)
section 7, as checked POSIX `sh` scripts. Owner ruling 2026-11-20 (Q3,
[#797](https://github.com/cooneycw/skillc/issues/797#issuecomment-7040081792)):
the probes may run through the owner's runner-VM helper **only after this
scripts PR is reviewed**. P9 runs only inside the first approved window and is
not here. These scripts handle no credential. They authorize no window,
login, spend or host action beyond the probe itself.

## Contract

- **One verdict per arm.** `CONFIRMED_NEGATIVE` (observed, nothing found),
  `SURVIVOR_OBSERVED` (observed, survivor found) or `OBSERVATION_FAILED`
  (could not observe completely). Output lines are only `ARM <arm> <verdict>`,
  `INFO …` and one final `PROBE <name> QUALIFIED|MISMATCH|REFUSED <reason>`.
- **Exit status.** 0 means every arm gave its expected verdict. 1 means at
  least one did not, and that is a finding about the VM, not a script error.
  2 means a refusal (usage, missing root, invalid image, runner active, setup
  failure) or a failed scratch cleanup.
- **Every probe has a clean arm, a survivor arm and a fault arm.** The fault
  arm deliberately makes its observation fail and must print
  `OBSERVATION_FAILED`. A missing, duplicated, malformed or failed reading is
  `OBSERVATION_FAILED`, never a zero. Decisions use exit statuses, errno
  numbers and parsed numbers or fixed tokens, never message text.
- **Two phases, one classifier.** Live mode observes and records readings,
  then classifies. `--classify FILE` runs only the classifier over committed
  readings. That is what CI tests (`tests/test_run_window_probes.py`), including
  committed blind twins that the fixtures must catch.
- **Residue** goes only to `skillc-dev-probe-<probe>-<pid>` under a tmpfs
  (`/dev/shm`) or `/run`. Every process, container (by the full ID `docker`
  returned, never by name) and mount is tracked as it is created. Cleanup
  runs on exit and on `HUP`, `INT` and `TERM`. It verifies each resource is
  gone (pid absent; `docker ps -a --filter id=` empty; path absent from
  `/proc/self/mountinfo`) before removing scratch. The final `PROBE` line is
  printed only after cleanup is verified. Otherwise the run prints
  `REFUSED cleanup-failed`, keeps the scratch for inspection and exits 2.
- **Runner exclusion.** Docker probes require the named unit to exist
  (`LoadState=loaded`) and be `inactive` or `failed`, at start and again
  before the verdicts. A typo'd unit refuses.

## Container storage (P5, P6)

The first live run refused P5 and P6 by name (`driver-not-overlay2`): Docker's
containerd image store reports the driver `overlayfs` with DriverStatus
`driver-type=io.containerd.snapshotter.v1`, and `docker inspect` carries no
graph-driver upper directory for it. Both probes now support exactly two
storage kinds and refuse anything else by name (`driver-unsupported`):

| Kind | Identified by | Upper directory shape |
|---|---|---|
| `overlay2` | driver `overlay2` | `<DockerRootDir>/overlay2/<hex id>/diff`; the relative `<hex id>/diff` the driver passes for long mount options is resolved against `<DockerRootDir>/overlay2` |
| `containerd-overlayfs` | driver `overlayfs` **and** exactly one `driver-type=io.containerd.snapshotter.v1` | absolute `…/io.containerd.snapshotter.v1.overlayfs/snapshots/<number>/fs` |

The driver name is never trusted alone, and the upper directory is never
taken from `docker inspect` alone. Each container runs, and `upper_dir_of ID
FD`:

1. reads the one `overlay` mount at `/` in its init process's
   `/proc/<pid>/mountinfo`. Every row must be well formed, exactly one row is
   at `/`, and its super options carry exactly one `upperdir=`;
2. revalidates the init pid (same pid, same start time) after that read;
3. accepts only plain path characters, so an escaped value fails closed, with
   no `.`, `..` or empty component, and requires the shape for its kind. A
   refused value is printed, scrubbed and bounded, as `INFO diag setup
   upperdir-raw …`, so a new runtime shape is recorded, not only refused;
4. on `overlay2`, requires it to equal the graph driver's own `UpperDir`;
5. **holds** the directory on file descriptor FD before proving it, so every
   later read (the proof, P5's search, P6's link count) goes through
   `/proc/$$/fd/FD`. Renaming or re-linking an ancestor afterwards cannot
   substitute another directory;
6. proves it is this container's: a fresh random token, written by the
   container into its own `/tmp/<token>`, must read back byte for byte as a
   regular file. The lookup is one `openat2(2)` relative to the held handle
   with `RESOLVE_BENEATH | RESOLVE_NO_XDEV | RESOLVE_NO_SYMLINKS`, so it
   cannot leave the directory, follow a symlink, or cross a mount (another
   tree's `tmp` bound over this one), and no path can be swapped between a
   check and the read (`marker_matches`, `python3 -I` with `ctypes`, stdlib
   only). A kernel without `openat2` (before 5.6) refuses, and a machine other
   than x86-64 or AArch64 refuses by name (`marker-arch-unsupported`), because
   the syscall number differs by ABI;
7. revalidates the init pid again after the proof.

Any failed step refuses by name (`upperdir-unreadable`, `container-pid-changed`,
`upperdir-shape`, `upperdir-disagrees`, `upperdir-missing`,
`upperdir-unverified`, `upperdir-open-failed`). P5's survivor marker now has a
random name too, so a stale file in another snapshot cannot answer for it.
The pure helpers (`storage_kind_from`, `overlay_upper`, `upper_resolve`) are
qualified in CI over committed mountinfo fixtures (`fixtures/lib/`) and inline
cases. `upper_dir_of` itself runs in CI under `sh -eu` against a stub `docker`
on `PATH` and a stub procfs (`PROBE_PROC`). Every one has blind twins the
cases must catch: a pid recheck removed, the start-time comparison removed,
the graph-driver comparison removed, the marker read-back removed, and a
symlinked `tmp` followed. A root-only case bind-mounts another tree's `tmp`
over the held one and requires refusal, with a twin that drops
`RESOLVE_NO_XDEV`; it skips where no mount can be made. The callers in P5–P8 need root and Docker, so CI
pins their wiring text (each in-container step through `step_capture`;
container stdout discarded) rather than running them.

The containerd fixtures are modelled on the snapshotter's documented layout.
No capture from the runner VM is committed yet. The stage-2 run records the
real value (`INFO diag setup upperdir-raw` on refusal), and a relative
`upperdir=` under containerd is refused rather than guessed.

## Step diagnostics (P5, P7, P8)

The first live run left P7 and P8 blind: every failed in-container step read
`OBSERVATION_FAILED` with its stderr sent to `/dev/null`. Each such step now
prints `INFO diag <arm> <step> exit <status>`, then up to the first 2048 bytes
of its stderr as `INFO diag <arm> <step> stderr: …` lines, and
`stderr-truncated <bytes>` when there was more (`lib.sh` `step_diag`). The
bound applies while the step runs: `step_capture` drains stderr to EOF
through `dd bs=1 count=2048` and only counts the rest, so a flooding step can
never fill the scratch filesystem. The step's own status travels through a
pipe into a shell variable, never a file, and the collector drains to
`/dev/null` if its file cannot be written. A full or unwritable scratch
therefore cannot change a status or a reading. Steps:
P7 `inventory`; P8 `binds` and `scan`, plus `ns-<name> unreadable`; P5's
`writes` on refusal, whose stdout is discarded along with that of the
identity-marker exec. Every byte outside printable ASCII becomes `?`, and
every line carries the `INFO` prefix and its own newline, so stderr text can
never print as an `ARM` or `PROBE` line. These are diagnostics only. Nothing
is recorded as a reading, no classifier reads them, and no verdict changed.
The containers hold no credential, so the text is not scrubbed beyond that.

## Stated limits

- The scripts cannot prove that the unit named by `--runner-unit` IS the
  runner, and a runner start between the two checks is not excluded. The
  operator supplies the unit and stops the runner's timer for the probe run,
  as for a window.
- P7 fails closed (`OBSERVATION_FAILED`) on any mountpoint that mountinfo had
  to escape (a backslash), rather than looking it up under the wrong name.
- P8 checks binds from the host side (a socket, or a directory containing
  one) **and** the socket files the container itself can see outside `/proc`
  and `/sys`. It does not model mount propagation beyond those two readings.
- Root probes make their scratch directory a private mountpoint before
  mounting anything under it, so probe mounts do not propagate to peer mount
  namespaces. The scratch self-bind itself is created on the (usually shared)
  parent and is unmounted at cleanup.
- P7's writability check is `access(2)` (GNU `find -writable`) OR the mode
  bits on rw mounts. Two ACL edge cases remain. A path writable only through
  a named-user ACL is seen by `access(2)` alone, so an I/O error in that one
  check would hide it; that needs two faults at once. And the mode-bit branch
  can over-report a path whose ACL mask sets a group bit the uid cannot use.
  That direction is fail-safe: a MISMATCH to investigate, never a false clean.
  Neither is excluded by the script.
- P5 and P6 accept a `DockerRootDir` reached through a symlink only if the
  kernel's mount options name the same string; otherwise they refuse
  (`upperdir-shape` or `upperdir-disagrees`) rather than resolve links.
- P5 and P6 need `sleep` and a writable `/tmp` in the image, for the running
  container and the identity marker, and `python3` on the host (as P8
  already does) for the descriptor-relative marker read. Without them they
  refuse by name.
- P2 identifies each planted holder by pid plus start time. Other pids
  are enumerated from one listing of `/proc`; a pid that exits mid-census is
  skipped, not counted as unreadable.

## Running (runner VM, through the owner's CLI helper, outside any run window)

Run at the reviewed commit of this directory, by file:

| Probe | Fact (#797) | Command | Root | Docker |
|---|---|---|---|---|
| P1 | tmpfs link counts (fact 1) | `sh controls/run-window-probes/p1.sh` | no | no |
| P2 | `/proc` fd + `map_files` census sees holders (fact 2) | `sh controls/run-window-probes/p2.sh`; run once unprivileged (the `unreadable` count is the measurement), then as root | **yes** (second run) | no |
| P3 | held fd blocks unmount; superblock absence; bind alias; lazy detach (facts 3–4) | `sh controls/run-window-probes/p3.sh` | **yes** | no |
| P4 | swap, piped core handler, resume device (1.2.3) | `sh controls/run-window-probes/p4.sh` | no | no |
| P5 | host-tmpfs home leaves nothing in the overlay upper dir, survives `docker rm` | `sh controls/run-window-probes/p5.sh --image-id <pinned> --runner-unit <unit>` | **yes** | **yes** |
| P6 | `docker rm` unlinks the upper dir object (mechanism only; `ABSENT_UNLINKED` never releases, Q1) | `sh controls/run-window-probes/p6.sh --image-id <pinned> --runner-unit <unit>` | **yes** | **yes** |
| P7 | writable set inside a contained container equals the declared surfaces (1.2.5) | `sh controls/run-window-probes/p7.sh --image-id <pinned> --runner-unit <unit>` | **yes** | **yes** |
| P8 | container channel isolation; the zero-byte `SCM_RIGHTS` limit (fact 2b) | `sh controls/run-window-probes/p8.sh --image-id <pinned> --runner-unit <unit>` | **yes** | **yes** |

`<pinned>` is the declaration's attempt image as a full `sha256:` ID. The
script refuses a tag, and refuses an ID the daemon does not hold exactly.
`<unit>` is the runner's systemd unit; a Docker probe refuses unless its
`ActiveState` is `inactive` or `failed`. `PROBE_USER` (default `1000:1000`)
sets the container uid for P5 and P7. P2, P3, P4 and P8 use `python3 -I`
(stdlib only) for `mmap`, `umount2` errno, a socket plant and `SCM_RIGHTS`.

## Expected live results

| Probe | Expected `PROBE` line | If MISMATCH |
|---|---|---|
| P1 | QUALIFIED | fact 1 cannot discriminate on this kernel; Contract A is blocked |
| P2 | unprivileged: MISMATCH (unreadable > 0); root: QUALIFIED | under root, census is incomplete; Contract A cannot reach ABSENT |
| P3 | QUALIFIED | fact 3 or 4 needs redesign for this kernel |
| P4 | QUALIFIED | the `live` arm shows swap, a piped core handler or a resume device: windows stay blocked until fixed |
| P5 | QUALIFIED | home bind leaks to VM disk or does not survive removal: PR-1 design must change |
| P6 | QUALIFIED | records the mechanism only. Each count is read immediately (`after`, evidence) and again after `PROBE_GC_WAIT` seconds (`after_late`, default 10, at most 300), and the verdict rests on the late one. An immediate positive count with a late 0 is asynchronous snapshot collection; a late positive count is retention |
| P7 | QUALIFIED, unless the image exposes an extra writable mount (for example `/dev/mqueue`), which PR-1 must then close | PR-1 containment must close the listed extra |
| P8 | QUALIFIED | channel isolation does not hold; fact 2b fails closed. If the `clean` arm's only survivor is a socket on fd 0–2 of the container's init (container-runtime stdio), record it: PR-1 must decide that case explicitly, not dismiss it |

## Review record

These scripts run as root and against Docker on the runner VM, so they were
reviewed by a different model family (Codex CLI, `gpt-6.2-sol`, read-only, with
the files supplied on stdin) before any run.

| Pass | Reviewed | Verdict | Outcome |
|---|---|---|---|
| 1 | `7c326416` | REQUEST-CHANGES (11 findings, 3 blockers) | P7 surface/file/word-split gaps; P8 nested socket binds; cleanup by name and unverified; P2 `mmap` kept an fd; P3 lazy arm; P4 and reader validation; runner unit existence; P8 receive validation; test pairing and twin validity. All addressed in `c4c9dfab` |
| 2 | `c4c9dfab` | REQUEST-CHANGES (4 closed, 6 partial, 1 new major) | escaped mountpoints; container-visible sockets; lost create responses; holder identity; P4 parsing; per-path survivors; arm-specific twins. Addressed in `461e96d1` |
| 3 | `461e96d1` | REQUEST-CHANGES (5 open, 1 new blocker) | the probes PR, unit identity and propagation were accepted as stated limits; pre-registered names; zombies; multi-line `core_pattern`; planted-path flags; `find \| wc` status. Addressed in `4f3ce389` |
| 4 | `4f3ce389` | REQUEST-CHANGES (4 of 5 fixed, plus residual false-verdict and cleanup paths) | P8 inspect status, pid revalidation and arm-specific signals; P7 four-reading consistency; P3 unusable tables; volume tracking; mount-read failure vs absence. Addressed in the commit that adds this record |
| 5 | `11c952d2` | REQUEST-CHANGES (7 of 9 fixed, plus residual paths) | P8 planted-bind and net-namespace specificity and mount-JSON validation; P3 strict row validation; P7 unusable rows, inaccessible mountpoints and a fault arm that must reach its own check (exit 4); P2 re-listing before skipping an entry; scratch absence checked by listing its parent. Addressed in the commit that adds this row |
| 6 | `b997cfd2` | REQUEST-CHANGES (9 of 12 fixed, plus residual paths) | mandatory mountinfo fields after the separator (P3, P7); P7 fault arm proven by an exit-4 `MISSING-SURFACE` token after a good table read; P8 mount-type validation, `shared_net`/`planted_binds` read and cross-checked on every arm, per-destination visibility; pid-lookup errors are not absence (P2, P3); an untracked new volume makes cleanup unverified (reported, never removed). Plus orchestrator hardening: scratch is a private self-bind before any probe mount (no propagation to peer namespaces), and scratch removal uses `--one-file-system`. Addressed in the commit that adds this row |
| 7 | `d2983b62` | REQUEST-CHANGES (pass-6 items fixed except one; 3 blockers, 2 minor) | P7 validates the whole mount table before its fault token, which now names `/probe-home`; P7 writability is `access(2)` OR mode bits (on rw mounts), so an access error cannot hide a writable path; P2 and P3 enumerate pids from one checked listing; P8 namespace counts bounded (at most 4, at most 3 non-net); P3 `fd_reads 0` fails. Cleanup and the scratch self-bind found correct. Addressed in the commit that adds this row |
| 8 | `10cf4c70` | REQUEST-CHANGES (3 of 5 fixed; the 2 remaining and 1 new item are ACL/row edge cases) | P7 mount rows now validated field by field (ids, `major:minor`, absolute roots and mountpoints), as in P3. The two ACL edge cases (named-user ACL hidden only by a concurrent `access(2)` I/O error; mode-bit over-report, which is fail-safe) are recorded under "Stated limits", not fixed. Review stopped here by the orchestrator's rule; the non-author review binds to the head that adds this row |
