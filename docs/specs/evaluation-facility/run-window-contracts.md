# Run-window contracts: deleted-root absence and in-memory reference retention (Refs #630, Refs #624)

**Status: DRAFT DESIGN, not approved.** This note is the design for the two
real-window blockers recorded with the slice 3 design approval on #630
(2026-11-09): "a trusted absence-evidence contract for deleted roots" and "a
lawful in-memory reference-retention bridge for the scan". It carries no code
and authorizes nothing. It does not authorize a declaration, a window, a login,
spend, access to a credential, or any host or Docker action. If the owner
approves it, implementation is SECRET-PATH: an owner `approve <PR>`, a review by
a different model family, committed no-leak tests and exact-head CI. #624's role
credential adapter stays behind both contracts.

Read with: [remnant-scan.md](remnant-scan.md) (slice 4),
[vm-credential-window.md](vm-credential-window.md) (slice 3),
[vm-admission.md](vm-admission.md) (slice 2) and
[wave-export.md](wave-export.md).

## 0. The problem, in one paragraph

Slice 3's close order is: stop dispatch, freeze the census, capture steward
facts, stop writers, log out, remove all copies, run the slice 4 scan, then
export. Two steps in that order cannot produce evidence today.

1. **Remove all copies** turns the credential-bearing roots (role homes, role
   vaults, staging, the owner's login home) into missing paths. Slice 4 rules
   that a missing root does not establish absence, so every removed surface
   reads UNKNOWN and the runner stays held forever.
2. **The scan** needs the delivered credential values as references. The only
   place those values exist is the files that step 1 just deleted, and slice 4
   rules that references are never learned from the files under test.

Contract A says what controller-held evidence turns a removed root into ABSENT.
Contract B says how the references survive step 1 without touching disk.
`vm_credential_window.BLOCKERS` names exactly these two
(`removed-root-absence-contract-unavailable`,
`reference-retention-contract-unavailable`). Each blocker is lifted only by its
own approved implementation, never by a flag.

## 1. Trust boundary shared by both contracts

- **The window controller** is one long-lived skillc process on the VM, started
  from the reviewed install that slice 1 binds. It runs for exactly one declared
  window. Contract A needs it to read every process's `/proc/<pid>/fd` and
  `/proc/<pid>/mountinfo`. Section 7 asks whether that needs root on the VM.
  Same-process Python is trusted, as in slice 4.
- **Threat actors:** participant processes (model clients and the tools they
  run, inside containers) and accidental leakage by skillc itself (reprs,
  tracebacks, logs, receipts, temp files, argv, environment). A hostile root on
  the VM is out of scope. That is the VM trust boundary, and the owner's
  isolation and admission checks (slice 2) are what stand against it.
- **Never inferred, always held:** every identity in these contracts is read by
  the controller from the kernel (`fstat` on a held file descriptor,
  `/proc/*/mountinfo`). None comes from a path string, a participant report, a
  Docker exit code or a callback's word.
- **Verdicts never upgrade.** UNKNOWN never becomes CLEAN or ABSENT through a
  retry, a later observation, a public dictionary or an operator note. Only a
  fresh window with a fresh census can produce a new verdict.

## 2. Contract A: trusted absence evidence for removed roots

### 2.1 Threat and failure mode

The failure is a **false CLEAN through deletion**. A credential-bearing root is
"removed" and the path is gone, but the bytes survive somewhere the scan does
not look:

| Survival route | Why a path check misses it |
|---|---|
| The root or a file in it was **renamed or moved** (into another directory, or out of the declared root) | The old path is ENOENT, and the inode lives on under a new name |
| A file was **hard-linked** elsewhere before the unlink | Same as rename. One name goes, the other stays |
| A process still holds an **open fd** or **mmap** of a deleted file | The data stays readable through `/proc/<pid>/fd/N` until the last reference closes |
| The tmpfs was **lazily unmounted** (`umount -l`) while still referenced | `findmnt` no longer shows it, and its content stays reachable through any held reference |
| **Deleted, then recreated** at the same path with benign content | A path-based scanner sees a present, readable, CLEAN root. The original survives through any of the routes above |
| The root sat on a **persistent filesystem** (for example a container's overlay upper directory on VM disk) | Unlinking removes the name. It does not erase blocks, so a forensic reader could still recover them |

A second failure is a **false ABSENT through blindness**: the controller cannot
read a parent directory, a `/proc` entry or a mount table, and it reads
"nothing found" as "nothing there". The negative-control rule in
`ADR 0001` applies directly: the absence check must be shown to find something.

### 2.2 Mechanism

**Declare dispositions up front.** Every required surface from
`remnant_scan.surfaces()` gets a fixed close disposition by class. The class
decides it. The caller does not:

| Class | Disposition at close | Evidence required |
|---|---|---|
| `home`, `vault`, `staging`, plus a new `login-home` (the owner's transient login session) | **removed** | Contract A ABSENT |
| `stdout`, `transcript`, `cache-log`, `export-payload` | **retained** | slice 4 scan of a present root, at least one readable file |

The dispositions join the existing approval digest through the closed
declaration (`run_window_contracts`, version 1). An approved declaration cannot
reclassify a surface afterwards.

**Census at freeze (step "freeze census").** Writers are stopped before this
step. For each removed-class root, and for every entry under it, within slice 4's
bounds, the controller:

1. Opens the root with `O_RDONLY | O_DIRECTORY | O_NOFOLLOW`, walking from a
   held fd on the declared parent. It never resolves a path string again later.
2. Opens every regular file and directory beneath it with `O_PATH | O_NOFOLLOW`
   and keeps the fds. The entry cap is 4096, so the fd budget is declared and
   checked against `RLIMIT_NOFILE` before the window opens. An unmet budget is
   a refusal at admission, not a later UNKNOWN.
3. Records `(st_dev, st_ino, st_mode, st_nlink)` for each held object, the
   mount ID and superblock device of the containing mount (from
   `/proc/self/mountinfo`), and its filesystem type.

A special entry (FIFO, socket, device, symlink) inside a removed-class root
makes that root UNKNOWN at census time, matching slice 4. The census is an
in-memory object bound to the declaration digest, the exact root mapping and
slice 4's opaque `generation` object, with the same `matches(...)` identity
guard as `ScanResult`. It has a redacted repr and refuses pickling and copying.

**Removal (step "remove all copies").** This is unchanged: the slice 3 and #624
adapters perform it. The contract never removes anything itself.

**Absence observation, after removal.** For each removed-class root, the
controller collects four facts:

1. **Unlinked, not moved.** `fstat` on every held fd shows `st_nlink == 0`. For
   a directory, `rmdir` leaves 0 and a rename leaves 2 or more. For a file,
   any remaining hard link or rename leaves 1 or more. This is the kernel's own
   statement that no name anywhere in that filesystem refers to the object. A
   path string cannot say this.
2. **No other holder.** A census of every `/proc/<pid>/fd/*` and
   `/proc/<pid>/map_files/*` finds no reference to any recorded `(st_dev,
   st_ino)` outside the controller itself. **The census is complete only if
   every pid's entries were readable.** One unreadable pid makes the root
   UNKNOWN. Pids that exit mid-census are re-checked by listing `/proc` again
   until two consecutive listings agree, within the collection timeout from
   slice 2.
3. **Mount gone, if declared tmpfs.** After the controller closes its own held
   fds (step 4 of the order below), the recorded mount ID is absent from
   `/proc/<pid>/mountinfo` for every pid. That covers other mount namespaces,
   including containers, and the same all-readable completeness rule applies.
   A mount that is detached but still referenced is not gone.
4. **No recreation masks it.** Each declared path, still resolved from the held
   parent fd, either is ENOENT, or is present with an identity different from
   every recorded one. A present path is **never** read as absence of the
   original. It becomes a new population that slice 4 must scan (see 2.3).

Order inside this step: collect facts 1, 2 and 4 while holding the fds. Close
the fds. Then unmount the tmpfs, which the owner-run close performs and
records. Then collect fact 3. Closing the fds first is required, because a held
`O_PATH` fd pins the mount and the unmount would fail with `EBUSY`. Section 7
asks the VM to confirm that.

**Persistent filesystems.** A removed-class root on a non-tmpfs mount can reach
ABSENT for facts 1, 2 and 4. The verdict is then `ABSENT_UNLINKED`, never
`ABSENT_ERASED`, and the window report says so. **Whether `ABSENT_UNLINKED` can
satisfy release is an owner decision (Q1 in section 8).** The recommended
design avoids the question by keeping every credential-bearing surface on
tmpfs: role homes and vaults go on a container `--tmpfs` mount, not the overlay
writable layer, which sits on VM disk. Section 7 asks the VM to confirm that a
`--tmpfs` home leaves nothing in the overlay upper directory.

### 2.3 Verdict states

Per removed-class root:

| State | Condition |
|---|---|
| `ABSENT` | Census complete, all four facts hold, and the declared storage is tmpfs |
| `ABSENT_UNLINKED` | Facts 1, 2 and 4 hold on a non-tmpfs mount. Release eligibility is open (Q1) |
| `PRESENT` | The declared path resolves to a recorded identity (removal failed), or to a new identity (recreated) |
| `UNKNOWN` | Anything else: no census, census incomplete or over budget, a held object with `st_nlink > 0`, a foreign holder found, `/proc` or mountinfo incomplete, the mount still listed, an unreadable or changed parent, a special entry, a mismatched generation, or an exception at the reader boundary |

Composition with slice 4, per surface:

- **Retained class:** the slice 4 status stands, with one addition. ABSENT
  evidence for a retained root is **UNKNOWN**, because the evidence that should
  be there is lost. It is never CLEAN.
- **Removed class, ABSENT:** satisfies that surface's release prerequisite.
- **Removed class, PRESENT:** slice 4 scans whatever is present. A recreated
  root gets the recreated population, and the original's absence still comes
  only from the held fds. A match makes it **NOT_CLEAN**. With no match it is
  still **UNKNOWN**: the removal did not happen, so the surface is not
  released, even if its bytes scan clean.
- **Removed class, UNKNOWN:** UNKNOWN.

Window verdict: any NOT_CLEAN gives NOT_CLEAN. Otherwise, any UNKNOWN gives
UNKNOWN. Otherwise every surface is either retained CLEAN or removed ABSENT, and
the verdict is CLEAN. Per the slice 3 approval, CLEAN is a **prerequisite**:
releasing the runner (step H) stays the owner's act. An UNKNOWN or NOT_CLEAN
window keeps the runner held until the owner directs release.

### 2.4 Committed negative controls (synthetic, CI)

Each case is a placement or action descriptor in `controls/run-window-absence/`
that runs against a temporary tree, with references generated in memory as in
slice 4. "Blind twin" means a committed mutant of the checker that the case must
reject.

| # | Case | Expected | Blind twin it defeats |
|---|---|---|---|
| A1 | Remnant planted under a root that was **deleted, then recreated** at the same path | NOT_CLEAN (found in the recreated root). The original's absence is judged only from its held fds | "Path present and scans clean, so released" |
| A2 | Recreated root, no remnant | UNKNOWN (removal failed), never CLEAN | Same |
| A3 | Root **renamed** out of its parent instead of removed | UNKNOWN (`st_nlink >= 2`) | "ENOENT, so ABSENT" |
| A4 | A file **hard-linked** outside the root before removal | UNKNOWN (`st_nlink == 1`) | Same |
| A5 | A helper process holds an **open fd** to a deleted file | UNKNOWN (holder found) | A checker with no fd census |
| A6 | One `/proc/<pid>/fd` made **unreadable** (an injected reader refusal) | UNKNOWN, never ABSENT | "Unreadable, so nothing there" |
| A7 | **Unreadable parent** (EACCES at census or observation) | UNKNOWN, never CLEAN or ABSENT | Same |
| A8 | Parent directory **replaced** (different identity) between census and observation | UNKNOWN | A path-resolving checker |
| A9 | **No census** recorded (the root missing at freeze) | UNKNOWN. This is today's slice 4 rule, now pinned by a case | "Missing at freeze, so never existed" |
| A10 | Mount ID still listed in another namespace's mountinfo (a synthetic table) | UNKNOWN | A checker reading only `/proc/self/mountinfo` |
| A11 | Retained-class root ABSENT | UNKNOWN | "Absent equals clean for every class" |
| A12 | A census or result **copied** from another generation | Refused by the `matches` guard | An equality-only guard |
| A13 | Census exceeds the fd budget | Refused at admission, never a truncated census | A checker that drops entries to fit |
| A14 | All facts hold on tmpfs | ABSENT. The positive case, so the suite cannot be passed by always answering UNKNOWN | An always-UNKNOWN checker |

A3, A4 and A5 need real kernel link-count semantics, so they run against a real
temporary directory in CI rather than a fake reader. A6, A8 and A10 use the
injectable reader and mountinfo source. Each regression-style case must be run
red on the parent commit before the fix and reported in the PR, per the
negative-control rule.

## 3. Contract B: lawful in-memory reference retention

### 3.1 Threat and failure mode

- **False CLEAN through wrong references.** The scan finds only what it is
  given. A reference that is stale, truncated, wrong-format, or learned from a
  tampered source misses the real remnant and reports CLEAN.
- **False CLEAN through learning from the population.** A reference read from
  the surfaces under test can be pre-shaped by a participant. Slice 4 forbids
  it.
- **The bridge becomes the leak.** Retaining the credential to detect it must
  not create a new copy at rest (temp file, swap, core dump, log, pickle, child
  argv or environment, a receipt hash) that outlives the window. A copy at rest
  is the exact failure the whole window exists to prevent.
- **Refreshed values are not references.** If a client rotates its token
  during the window, the new value was never captured, so the scan cannot see
  it.

### 3.2 Mechanism

**One capture point, from the source, before any participant exists.** The
window order becomes: owner login, **capture**, **seal**, live positive control,
delivery and dispatch. Dispatch refuses until a sealed capture exists.

1. **Source.** The only lawful source is the owner's fresh interactive login
   credential file in the declared transient `login-home` (the tmpfs window-user
   session from slice 3). The controller reads it through the same held-fd,
   no-follow reader as Contract A's census. It checks that the file is a
   regular file, mode 0600, owned by the window user, on the declared tmpfs
   mount, and was written after the slice 2 `credential-login` receipt's
   `login_at` and within the window. Any mismatch leaves the capture
   **UNAVAILABLE**: no references, so slice 4 returns UNKNOWN.
2. **Extraction.** A closed, client-specific extractor, declared in the plan
   by client name (only `codex` initially, matching slice 3's `client`), yields
   (a) the whole source file's bytes and (b) each secret-bearing field value.
   This must fit slice 4's cap of 8 values and 64 KiB. An unrecognized format,
   a missing field or an over-cap population leaves the capture UNAVAILABLE,
   never "capture what we can".
3. **Delivery-side references.** If the home delivery seam transforms the bytes
   (for example by re-serializing the file), it adds the exact bytes it wrote
   to the same sealed set from its own in-memory buffer. It never re-reads them
   from disk. After **seal**, no addition is possible, so any later delivery
   must be byte-identical to a sealed value, or the window holds.
4. **Holding.** One `References` object (slice 4's opaque type), owned by the
   controller for the window's lifetime. It has no file, environment, argv,
   pipe, pickle or copy path. `__reduce__`, `__copy__` and `__deepcopy__`
   refuse. It never crosses a process boundary: the scan runs in-process, and a
   test makes any `fork`, `exec` or `subprocess` call fail while references are
   live.
5. **Persistence prevention (process level).** Before capture the controller
   sets `RLIMIT_CORE` to 0 and `prctl(PR_SET_DUMPABLE, 0)`, which also blocks
   same-uid ptrace. It then re-reads both to verify. Swap and hibernation are
   already window preconditions under slice 3: the window is blocked unless
   they are prevented. Capture also re-checks swap immediately before reading
   (the procedure is in section 7). Python cannot promise erasure. The lifetime
   bound is the controller's process exit, with swap off and dumps disabled.
   Best-effort overwrite of `bytearray` buffers is done but never claimed.
6. **Live positive control, before dispatch.** Immediately after delivery, the
   controller scans each role's delivered home with the sealed references. It
   **must** get NOT_CLEAN for each role. Missing that positive proves the
   references or the delivery are wrong, and the window holds before any model
   starts. Only a boolean `delivery_matched` is kept.
7. **Release of the references.** Drop them immediately after the final close
   scan, before export. Their lifetime ends there, at the latest at process
   exit.
8. **Loss is final.** A controller crash or restart, or a lost object, loses
   the references. **There is no reload path.** The window's close verdict is
   UNKNOWN and the runner stays held. Re-capture is impossible by construction,
   because the source was removed and re-reading any surface is learning from
   the population. Recovery is an owner decision (for example logging out
   provider-side to revoke the credential, then a new window).
9. **Refresh.** Stop-on-refresh is unchanged. A refresh or credential-file
   reappearance seen by any steward, or a source-file inode change seen through
   the held fd, latches a hold. The window verdict is **UNKNOWN for the life of
   the window**, even if the final scan is CLEAN, because the refreshed values
   are not references. The scan does not cover this residual. The hold does.

### 3.3 Verdict states

Capture: `SEALED` (positive control passed) or `UNAVAILABLE` (any failure in
steps 1 to 6). Effect on the window: UNAVAILABLE refuses dispatch. A refresh
latch, a lost capture, or a capture taken after the first delivery or dispatch
makes the close verdict UNKNOWN. SEALED is a prerequisite for a CLEAN window,
never sufficient alone.

**Retention receipt:** a closed schema of **booleans and durations only**:

```json
{
  "version": 1,
  "captured": true,
  "captured_before_first_delivery": true,
  "delivery_matched": true,
  "refresh_latched": false,
  "dumps_disabled": true,
  "released_before_export": true,
  "capture_after_login_s": 41.0,
  "retention_s": 3120.5
}
```

The receipt holds no counts, lengths, hashes, IDs, field names, paths or
timestamps that could fingerprint the credential. Any extra key refuses at
construction. (The values above are synthetic.)

### 3.4 Committed negative controls (synthetic, CI)

| # | Case | Expected |
|---|---|---|
| B1 | Capture attempted after first delivery or dispatch | UNAVAILABLE, dispatch refused |
| B2 | Source is a symlink, wrong mode, wrong owner, not on the declared tmpfs, or older than `login_at` | UNAVAILABLE |
| B3 | Capture source pointed at a tested surface (a role home) | Refused structurally: the API takes only the declared `login-home` |
| B4 | Unknown client format or over-cap field population | UNAVAILABLE, never a partial set |
| B5 | Delivery rewrites bytes and does not add them before seal | Live positive control misses, hold before dispatch |
| B6 | Planted **refreshed** token (not in the references) after a refresh latch | Scan CLEAN **and** window UNKNOWN, showing the hold (not the scan) covers it |
| B7 | Controller object lost or restarted mid-window | Close UNKNOWN. A structural test asserts that no constructor reads a file, environment, argv or stdin |
| B8 | Receipt with an injected count, length or hash field | Refused |
| B9 | Leaking twins: retention that writes a temp file, sets an env var, or spawns a child with the value in argv | Each must fail the no-leak oracle (section 4) |
| B10 | Positive: fresh source, sealed, matched, no refresh | SEALED, so the suite cannot be passed by always answering UNAVAILABLE |

## 4. No-leak tests (both contracts)

These reuse slice 4's independent `no_marker` oracle (raw bytes, repr and
escaped forms, JSON escaping, every fixed detector encoding). Material is
synthetic and generated per test in memory, independently per role, with no
raw-derived test IDs.

1. **Receipts and public results:** absence results, the retention receipt and
   the window report contain no marker under any encoding. Their schemas are
   exact allowlists.
2. **Diagnostics:** reprs, str, exceptions, chained exceptions and tracebacks
   with locals (forced failure inside census, observation, capture and scan)
   contain no marker. Opaque holders keep a forced traceback from serializing
   one.
3. **Process surface:** captured stdout, stderr and logs. A monkeypatched
   `subprocess`, `os.exec*`, `os.fork` and `os.posix_spawn` fail the test if
   called while references are live. The environment snapshot after the run
   equals the one before.
4. **Disk:** every file the test process created is under a monitored
   temporary root, and a recursive `no_marker` audit of that root after the run
   finds nothing. No file is created outside it (checked by an `os.open` and
   `open` audit hook via `sys.addaudithook`).
5. **Multi-role:** a remnant planted only in role 3's surfaces is found, and a
   leak planted only in role 3's diagnostics fails the oracle. A single-role
   pass cannot go green (#624's requirement).
6. **Oracle self-test:** a deliberately leaking renderer fails the oracle (the
   existing `test_no_marker_oracle_refuses_a_deliberately_leaking_renderer`
   pattern), so the oracle itself can be shown to fail.

## 5. How the contracts slot into the slice 3 order (A to H)

| Slice 3 step | Added by these contracts |
|---|---|
| A to D: identity, reserve and drain, time and isolation, install | Admission also checks the fd budget (A13), and verifies swap and hibernation off and dumps disabled for the controller |
| E: owner login | B: capture, seal, live positive control (dispatch refused until SEALED) |
| Run | B: refresh latch. A: nothing |
| Close: stop dispatch, then **freeze census** | A: census of removed-class roots with held fds (writers already stopped) |
| Steward facts, stop writers, logout, **remove all copies** | Unchanged (performed by the adapters) |
| A: absence observation | Facts 1, 2 and 4, close fds, owner-run tmpfs unmount, then fact 3 |
| **slice 4 scan** | Retained roots plus any present removed-class root, with the sealed references. Then the references are dropped |
| Export | Only after the composed verdict, with export UNKNOWN rules unchanged |
| H: runner release | Owner only, after a CLEAN composed verdict. UNKNOWN or NOT_CLEAN stays held |

## 6. What this changes in code (for the later PRs, not now)

- New `skillc/run_window_absence.py` (Contract A) and
  `skillc/reference_retention.py` (Contract B), stdlib-only, with no kyle
  import. Pattern sources, if any are copied, are cited per #630's borrowing
  terms. The census follows the `mountinfo_orphaned` idea from the kyle
  credential-freshness module, re-derived in skillc, at the pinned kyle SHA
  that #624 already names.
- `remnant_scan`: a new `login-home` class, a disposition table, and a
  composition function taking `(ScanResult, AbsenceResult, CaptureState)`. The
  existing `scan()` behaviour and the no-opt-in bytes are unchanged and pinned
  by the existing legacy fixture.
- `vm_credential_window.BLOCKERS`: each entry is removed only in the PR that
  implements and qualifies its contract. Two PRs (A, then B), each SECRET-PATH.

## 7. Physical facts that need a VM run (DRAFT requests)

None of these is authorized by this note. Each needs the owner's go-ahead, runs
through the owner-started skillc CLI helper, **outside any run window**, with
residue only under the named dev directory, which is removed after the run. All
commands are POSIX shell plus coreutils. No skillc install and no skillc code
are needed, so they are pinned by this note's commit SHA (run them exactly as
written in `git show <sha>:docs/specs/evaluation-facility/run-window-contracts.md`).

Indicative only: P1's three cases were run once inside a Kyle session container
on its `/dev/shm` tmpfs (container kernel, not the runner VM). They read
rmdir 0, rename 2, hard link 1, and 0 after the last unlink. That is not VM
evidence.

**P1: link counts on the VM's tmpfs (Contract A fact 1).** No Docker. Unprivileged.

```sh
D=/dev/shm/skillc-dev-probes; mkdir -p "$D" && cd "$D" && bash -c '
d=$(mktemp -d ./p.XXXX); exec 9<"$d"; rmdir "$d"; echo rmdir=$(stat -L -c %h /proc/$$/fd/9)
e=$(mktemp -d ./q.XXXX); exec 8<"$e"; mv "$e" "$e.m"; echo rename=$(stat -L -c %h /proc/$$/fd/8); rmdir "$e.m"
f=$(mktemp ./f.XXXX); exec 7<"$f"; ln "$f" "$f.l"; rm "$f"; echo hardlink=$(stat -L -c %h /proc/$$/fd/7); rm "$f.l"; echo last=$(stat -L -c %h /proc/$$/fd/7)
df -T . | tail -1 | awk "{print \"fstype=\"\$2}"'; cd / && rm -rf "$D"
```

Expected: `rmdir=0 rename=2 hardlink=1 last=0 fstype=tmpfs`. The negative
control is in the same run: `rename` and `hardlink` must not read 0. If they
do, fact 1 cannot discriminate on this kernel and Contract A is blocked.

**P2: fd census finds a holder, and shows whether the controller needs root (fact 2).** No Docker.

```sh
D=/dev/shm/skillc-dev-probes; mkdir -p "$D" && f=$(mktemp "$D/h.XXXX") && \
( exec 3<"$f"; sleep 30 ) & H=$!; sleep 1; rm "$f"; \
found=0; unread=0; for p in /proc/[0-9]*; do [ -r "$p/fd" ] || { unread=$((unread+1)); continue; }; \
ls -l "$p/fd" 2>/dev/null | grep -q "$D/h\..* (deleted)" && found=$((found+1)); done; \
echo found=$found unreadable=$unread uid=$(id -u); kill $H; wait $H 2>/dev/null; \
sleep 1; ls -l /proc/[0-9]*/fd 2>/dev/null | grep -c "$D/h\..* (deleted)"; rm -rf "$D"
```

Expected as a normal user: `found` of at least 1 (the holder subshell and its
`sleep` may both hold the fd), `unreadable` greater than 0, and the
final count `0` (the negative control: once the holder exits, nothing is
found). An `unreadable` count above 0 means an unprivileged census is
incomplete, so Contract A requires a root controller (owner Q2). Run it a
second time as root only if the owner approves root for the helper. Expected
there: `unreadable=0`.

**P3: a held fd blocks unmount, and mountinfo absence after a real unmount (facts 3 and 4).** No Docker. **Root required.**

```sh
M=/mnt/skillc-dev-probe; mkdir -p "$M" && mount -t tmpfs -o size=1m,mode=0700 skillc-dev-probe "$M" && \
id=$(awk -v m="$M" '$5==m{print $1}' /proc/self/mountinfo); echo mount_id=$id; \
exec 9<"$M"; umount "$M" 2>&1 | grep -q busy && echo held_blocks=yes || echo held_blocks=no; \
exec 9<&-; umount "$M" && echo umount=ok; \
cat /proc/[0-9]*/mountinfo 2>/dev/null | awk -v i="$id" '$1==i' | wc -l; rmdir "$M"
```

Expected: `held_blocks=yes`, `umount=ok`, then `0` (no namespace still lists
the mount ID). The negative control is in the same run: `held_blocks=yes` shows
the probe can see a busy mount. A further case, `umount -l` while fd 9 is held,
followed by a mountinfo listing, is expected to show the mount gone from
`/proc/self` while still referenced. It records why fact 3 is read only after
the fds are closed.

**P4: persistence preconditions (Contract B step 5).** No Docker. Read-only. Unprivileged.

```sh
echo swap=[$(swapon --show --noheadings | wc -l)] core_pattern=[$(cat /proc/sys/kernel/core_pattern)] \
 ulimit_c=[$(ulimit -c)] hibernate=[$(systemctl is-enabled hibernate.target 2>&1)] power=[$(cat /sys/power/state)]
```

Expected for a window to open: `swap=[0]`, and hibernation masked or disabled.
This only records today's VM facts. Any nonzero swap means the window is
blocked under the slice 3 rule. The negative control is a committed unit case:
the admission check given a recorded reading with one swap line must report
BLOCKED.

**P5: a container `--tmpfs` home leaves nothing in the overlay upper directory (2.2, "Persistent filesystems").** **Touches Docker.** Root or docker group. Needs the pinned attempt image ID (`<IMAGE_ID>`, from the declaration, never a tag).

```sh
c=$(docker create --tmpfs /probe-home:mode=0700 <IMAGE_ID> sh -c 'echo skillc-dev-marker > /probe-home/t; echo skillc-dev-marker > /probe-disk; findmnt -n -o FSTYPE /probe-home; sleep 5') || exit 1
up=$(docker inspect -f '{{.GraphDriver.Data.UpperDir}}' "$c")
docker start -a "$c" & S=$!; sleep 3
echo tmpfs_in_upper=$(find "$up" -path '*probe-home/t' | wc -l) disk_in_upper=$(find "$up" -name probe-disk | wc -l)
wait $S; docker rm "$c" >/dev/null
```

Expected: `tmpfs`, `tmpfs_in_upper=0`, `disk_in_upper=1`. The negative control
is in the same run: the non-tmpfs write is found in the upper directory, so a
zero is not blindness. The marker is a fixed benign string, not a credential.
Do not run while a runner job is active.

**P6: `docker rm` unlinks the upper directory (Contract A for container roots).** **Touches Docker.** **Root required** (to open the upper directory).

```sh
c=$(docker create <IMAGE_ID> true) && up=$(docker inspect -f '{{.GraphDriver.Data.UpperDir}}' "$c") && \
bash -c 'exec 9<"$1"; docker rm "$2" >/dev/null; echo after_rm=$(stat -L -c %h /proc/$$/fd/9)' _ "$up" "$c"; \
c2=$(docker create <IMAGE_ID> true); up2=$(docker inspect -f '{{.GraphDriver.Data.UpperDir}}' "$c2"); \
bash -c 'exec 9<"$1"; echo kept=$(stat -L -c %h /proc/$$/fd/9)' _ "$up2"; docker rm "$c2" >/dev/null
```

Expected: `after_rm=0`, and `kept` 2 or more (the negative control: a container
that is not removed keeps its upper directory linked). Note that the upper
directory sits on VM disk, so even `after_rm=0` is `ABSENT_UNLINKED`, not
erased. That is why section 2.2 recommends tmpfs homes.

**Not probeable without a real window:** whether the native client rewrites
its credential file during a turn (rename versus in-place), and how often it
refreshes. Those facts come only from a real login, which is a window action.
They are observed through the refresh latch during the first approved window,
not before.

## 8. Open questions for the owner

- **Q1.** Can `ABSENT_UNLINKED` (unlinked on VM disk, not erased) ever satisfy
  release? Recommended: **no**. Keep every credential-bearing surface on tmpfs,
  and treat a disk-backed removed-class root as UNKNOWN.
- **Q2.** Can the window controller run as root on the VM, as P2 may show the
  fd census needs? If not, Contract A cannot reach ABSENT. Every removed root
  stays UNKNOWN, and release is the owner's directed act each time.
- **Q3.** Can the probes P1 to P6 be run through the CLI helper, with P3 and P6
  under root, and P5 and P6 touching Docker outside a runner job?
- **Q4.** For loss of the references mid-window (B7), the recommended response
  is held, then the owner logs out provider-side to revoke, then a new window.
  Does the owner want a different recovery?

## 9. Out of scope

- Forensic block-level erasure, process-memory erasure, or protection against a
  hostile root on the VM.
- Content copied by a participant to an **undeclared** location. The scan
  covers declared surfaces only (slice 4's stated limit). Isolation and egress
  policy are the controls there.
- Provider-side token revocation. That is the owner's action, not a skillc
  guarantee.
- Any change to #619 residue inventory semantics. Zero clutter is still not
  absence evidence.
