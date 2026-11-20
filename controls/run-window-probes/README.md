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
| P6 | QUALIFIED | records the mechanism only |
| P7 | QUALIFIED, unless the image exposes an extra writable mount (for example `/dev/mqueue`), which PR-1 must then close | PR-1 containment must close the listed extra |
| P8 | QUALIFIED | channel isolation does not hold; fact 2b fails closed. If the `clean` arm's only survivor is a socket on fd 0–2 of the container's init (container-runtime stdio), record it: PR-1 must decide that case explicitly, not dismiss it |
