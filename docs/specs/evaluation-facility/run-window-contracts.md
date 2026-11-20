# Run-window contracts: removed-root absence and in-memory reference retention (Refs #797, parent #630, Refs #624)

**Status: DRAFT DESIGN, revision 7, not approved.** This note is the design for
the two real-window blockers recorded with the slice 3 design approval on #630
(2026-11-09): "a trusted absence-evidence contract for deleted roots" and "a
lawful in-memory reference-retention bridge for the scan". They are tracked as
#797. Revisions 2 to 7 take in reviews by a different model family, recorded in
Appendix R.

This note carries no code and authorizes nothing. It does not authorize a
declaration, a window, a login, spend, access to a credential, or any host or
Docker action. If the owner approves it, implementation is SECRET-PATH: owner
`approve <PR>`, a review by a different model family, committed no-leak tests
and exact-head CI. #624's role credential adapter stays behind both contracts.

Read with: [remnant-scan.md](remnant-scan.md) (slice 4),
[vm-credential-window.md](vm-credential-window.md) (slice 3),
[vm-admission.md](vm-admission.md) (slice 2) and
[wave-export.md](wave-export.md).

## 0. The problem

At close, the credential-bearing roots are removed: role homes, role vaults,
staging and the owner's login home. Slice 4 rules that a missing root does not
establish absence, so every removed surface reads UNKNOWN and the runner stays
held forever. The scan also needs the delivered credential values as
references. Slice 4 forbids learning those from the files under test, and the
files that held them have just been deleted.

Contract A defines what controller-held evidence lets a removed root count
toward release. Contract B defines how the references survive removal without
touching disk. `vm_credential_window.BLOCKERS` names exactly these two
(`removed-root-absence-contract-unavailable`,
`reference-retention-contract-unavailable`). Each blocker is lifted only by the
PR that implements and qualifies its own contract, never by a flag.

**What the contracts claim, stated narrowly.** ABSENT is evidence about a
*recorded population of original objects* and the processes that could hold
them. It is not a claim that the credential's bytes exist nowhere. The release
claim is conditional on three things: the containment preconditions in 1.2;
the teardown boundary in 2.2; and a complete scan of every surviving declared
surface. If any of those cannot be proved, the verdict stays UNKNOWN.

## 1. Shared trust boundary and preconditions

### 1.1 Who is trusted

- **The window controller** is one skillc process on the VM, started from the
  reviewed install that slice 1 binds. It lives for exactly one declared
  window, and same-process Python is trusted, as in slice 4. Contract A needs
  it to read every process's `/proc` entries and mount tables. Whether that
  requires root is owner question Q2.
- **Threat actors:** participant processes (model clients and their tools, in
  containers), the owner's login session as a process tree, and accidental
  leakage by skillc itself. A hostile root on the VM is out of scope. The VM
  is the trust boundary, defended by admission (slice 2) and isolation.
- **Identities are held, never inferred.** Every identity is read from the
  kernel through a held descriptor or a mount table. None comes from a path
  string, a participant report, a Docker exit code or a callback's word.
- **Verdicts never upgrade.** UNKNOWN never becomes CLEAN or ABSENT through a
  retry, a later observation, a public dictionary or an operator note.

### 1.2 Containment preconditions (checked at admission, held to teardown)

These are what make "copied to an undeclared place" either impossible or
covered by a scan. If any is unmet, the window does not open.

1. **Every participant-writable location is a declared surface.** Participant
   containers run with a read-only root filesystem. Each writable mount is
   either a removed-class tmpfs or a retained, declared output directory.
   Nothing else is writable from inside a container.
2. **No host channel into a container.** No host socket, host IPC namespace,
   host PID namespace or shared mount propagation is given to a participant
   container. A participant therefore cannot pass a descriptor or bytes to a
   process outside the holder domain (2.2).
3. **Persistence is off for every credential-bearing process, for the whole
   window.** Swap is off. Hibernation cannot be entered. The effective
   system-wide dump policy is verified, including `core_pattern`, because a
   piped core handler ignores `RLIMIT_CORE`. Dumps are disabled for the
   controller, the login session and every role container
   (`--ulimit core=0`). These are verified **before login**, sampled again at
   every `before_turn` and on a declared interval, and verified at close. Any
   change, or a missed sample, makes the window UNKNOWN. Changing them needs
   root. A change made and restored between two samples is within the VM's
   trust boundary (a hostile root, out of scope); sampling narrows it but
   does not close it.
4. **Egress follows the #442 provider-only policy, narrowed to forbid
   refresh.** From **login completion** (the slice 2 `credential-login`
   receipt, before the authoritative capture read) until the **teardown
   boundary is confirmed**
   (2.2 step 3), the egress allowlist admits the provider's inference
   endpoints but **not** its token-issuance or refresh endpoint. That covers
   every role and the login container, including writers still alive after
   dispatch stops. The block lifts only after the holder domain is empty.
   The firewall revision is digest-pinned at admission (slice 2, value (e)).
   A refresh then cannot mint a new value, which is what closes the
   transient-refresh route (3.2.6). If the pinned client cannot separate
   refresh from inference by endpoint, this precondition fails, and the
   window does not open unless the owner rules otherwise (Q5). Content sent
   off the VM is otherwise out of scope (section 9).
5. **The login runs in a login container (proposed refinement, owner Q6).**
   The owner still logs in to the VM interactively over SSH, as slice 3
   approved. The credential-bearing step, the client's interactive login, runs
   inside a controller-created **login container**. That container has the
   same containment as a role (items 1 and 2): a read-only root filesystem;
   private network, IPC, PID and mount namespaces; no host socket; and
   `--ulimit core=0`. The owner's outer SSH shell never holds the credential.
   The holder domain is then **containers only**. Its only channel to a
   surviving host process is the controller-owned terminal attach, which is a
   pty and cannot carry descriptors. This closes the queued-descriptor route
   by construction (fact 2b), rather than by a measurement that zero-byte
   datagrams can evade. **The boundary is a lifetime invariant, not a launch
   check.** Every container starts with only fds 0 to 2, bound to its pty or
   to null. The launcher closes every other descriptor. The controller reads
   each container process's `/proc/<pid>/fd` at start, at every
   `before_turn` and at teardown, and any descriptor that resolves to a host
   socket, a host file or a foreign namespace latches UNKNOWN (A23).
   Containers use Docker's `none` log driver, verified by inspect, so pty
   output never lands in an undeclared host log. The terminal attach itself
   is not recorded (A24). Probe P7 inventories the directories writable from
   inside each container on every visible filesystem. That inventory must
   equal the declared surfaces.
   **Scratch topology:** every container's `/tmp`, `/var/tmp` and `/dev/shm`
   are **three separate** controller-owned host tmpfs instances. Each is its
   own removed-class surface (`scratch-tmp`, `scratch-vartmp`,
   `scratch-shm`), so there are no permitted aliases. Docker's default
   per-container `/dev/shm` is replaced by the bind, never left as a
   container tmpfs (A22).
6. **Declared roots are physically disjoint.** No root's held ancestor chain
   may contain another root's identity, so one root cannot sit nested inside
   another. Identical roots are also refused (A12).

## 2. Contract A: removed-root absence

### 2.1 Threat and failure mode

**False release through deletion.** The path is gone, but the bytes survive:

| Route | Closed by |
|---|---|
| The object was renamed, moved or hard-linked | Fact 1 (`st_nlink`) |
| A process holds an fd or mapping, or an fd is in flight over a Unix socket, or an fd was passed to a process already inspected | The teardown boundary (2.2): every process that could hold one is gone. The `/proc` census is corroboration only |
| The bytes were copied into a new inode, memfd or anonymous memory | Containment (1.2): new inodes can only be in declared surfaces, so they are scanned or removed. memfd and anonymous memory die with the holder domain |
| A lazily detached tmpfs, or a bind alias with a different mount ID | Fact 3, checked by superblock rather than mount ID, and lazy detach refused |
| Deleted, then recreated at the same path | Fact 4: a recreated root is PRESENT and is scanned |
| The parent directory was renamed or replaced, so a lookup through the held fd says ENOENT while the declared path holds a remnant | Fact 4: the declared path is resolved again from a held ancestor chain |
| The data sat on a persistent filesystem | Not releasable (2.3, Q1) |

**False release through blindness.** Unreadable or failed observations read as
"nothing there". Every observation has three outcomes, and only
`CONFIRMED_NEGATIVE` can contribute to ABSENT. The other two are
`SURVIVOR_OBSERVED` and `OBSERVATION_FAILED`.

### 2.2 Mechanism

**Dispositions are declared by class** in the closed `run_window_contracts`
declaration (version 1). They join the existing approval digest, and no caller
can change them:

| Class | Disposition | Release evidence |
|---|---|---|
| `home`, `vault`, `staging`, `login-home` (new), and for every role and the login container `scratch-tmp`, `scratch-vartmp`, `scratch-shm` (new) | removed | Contract A ABSENT, on tmpfs |
| `stdout`, `transcript`, `cache-log`, `export-payload` | retained | A complete per-surface slice 4 CLEAN, through held physical roots |

**Every removed-class tmpfs is a VM-side mount the controller creates and
owns.** Each role's `home` and `vault` is a controller-created host tmpfs,
directory-bind-mounted into the role container. It is never a container
`--tmpfs`, which Docker destroys with the container in step 3, before the
census could inspect it. A host tmpfs outlives container removal, so the
census in step 4 still holds it. This is a directory mount, not a single-file
bind mount, so #624's inode-staleness concern does not apply.

**The close sequence** fixes one observation boundary. It refines slice 3's
approved order. That order's "freeze census" is the pre-stop steward and
population inventory, and it is unchanged. The post-stop filesystem census
below is new.

1. Stop dispatch. Take slice 3's pre-stop inventory and steward facts while the
   stewards are still accessible.
2. Stop the role writers. The owner then revokes provider-side, **before
   teardown**, by one of two routes. The route is declared at admission.
   (b) is the default and is admissible with no prior qualification: an
   account-level session revocation by the owner, outside the VM. (a) is the
   client's own logout inside the login container, using only a separately
   admitted revocation endpoint while refresh stays blocked. (a) is
   admissible only after P9 has qualified it in an earlier approved window.
   For (b), the receipt is collected through the slice 2 `credential-logout`
   collector after step 3 and before acceptance. For (a), it is collected
   here. The owner then leaves the login container.
3. **Teardown boundary.** The holder domain is every process in a role
   container or in the login container. The controller confirms that the
   domain is empty in three ways: no `/proc` entry in any of those containers'
   cgroups; no process sharing one of their PID, mount, network or IPC
   namespaces (compared by namespace inode); and Docker reports each container
   removed. The inotify watches (3.2.6) are drained at this point, before the
   controller deletes anything. Every read must succeed. An unreadable or
   failed read is OBSERVATION_FAILED, and the window is UNKNOWN. From here on,
   the only processes are the controller and the declared host workload
   (slice 2: the runner, sshd and time sync).
4. **Post-stop census.** The controller resolves each removed-class root
   component by component, from a held fd on `/`, with `O_NOFOLLOW` at every
   step. It holds an fd for every ancestor and for the root, and an `O_PATH`
   fd for every entry beneath it. For each object it records
   `(st_dev, st_ino, st_mode, st_nlink)` and the superblock device of its
   mount. Any special entry gives UNKNOWN. Any second mount of the same
   superblock, in any readable mount table, is an alias and gives UNKNOWN.
   Retained roots are resolved the same way, and their root fds are held for
   the scan.
5. **Removal of entries.** The controller is the only actor, since no other
   process exists after step 3. It removes every entry beneath each
   removed-class root while still holding the census fds. A tmpfs root
   directory is a mountpoint and is not removed here.
6. **Facts 1 and 2**, collected while the census fds are still held.
7. **Close every census fd, then unmount** each tmpfs non-lazily, checking the
   errno. The unmount fails with `EBUSY` if any fd is still held, which is why
   the fds are closed first (P3). A lazy detach (`MNT_DETACH`) is never used,
   and observing one gives UNKNOWN.
8. **Facts 3 and 4.**
9. **Scan.** Slice 4 runs with the sealed references over every retained root
   (held root fds, never path strings) **and over every removed-class root
   that fact 4 found PRESENT** (freshly resolved, held, then scanned). It
   also scans **the replacement path wherever fact 4 found an ancestor
   mismatch**, re-resolved safely from `/` with `O_NOFOLLOW` at every step.
   That root keeps its sticky UNKNOWN, and a match still gives NOT_CLEAN.
   This is the path by which A1 and A9 find their remnants. The scan records
   per-file digests of `export-payload` in memory.
10. **Two-phase export.** Export transfers the payload, read through the held
    fds, into a **quarantined arrival area** on the operator side. Nothing is
    published or accepted during transfer. Arrival verification (#677)
    compares every digest with the step 9 digests. The composed verdict (2.3)
    is computed; it includes the logout receipt. Only then is the arrival
    accepted, in one step. A mismatch,
    or any non-CLEAN verdict, leaves the arrival quarantined, never accepted,
    and the wave UNKNOWN. No streaming exporter can publish ahead of the gate.
11. **Drop the references** (Contract B).

**The four facts.** Each must be CONFIRMED_NEGATIVE.

1. **Unlinked.** `fstat` on every held census fd beneath the root shows
   `st_nlink == 0`. After `rmdir` a directory shows 0, and after a rename it
   shows 2 or more. A file with any remaining name shows 1 or more. The tmpfs
   root itself is covered by fact 3.
2. **No holder.** This follows from the teardown boundary in step 3. A census
   of `/proc/*/fd` and `/proc/*/map_files` over the remaining processes finds
   no recorded `(st_dev, st_ino)` outside the controller. That census is
   corroboration and cannot make up for a failed step 3. Any unreadable entry
   is OBSERVATION_FAILED.
3. **Superblock gone.** After the controller closes its own census fds and the
   unmount succeeds, no readable mount table lists the recorded superblock
   device. Checking the superblock catches bind aliases with a different mount
   ID. Every pid's table must be readable.
4. **Declared path re-resolved.** Re-walk each declared path from the held `/`
   fd. Every ancestor must still match its recorded identity; a mismatch is
   UNKNOWN, which catches a replaced or renamed parent. After unmount, the
   path resolves to the **underlying mountpoint directory**. The controller
   created that directory empty at window open and recorded its identity
   (`M0`). The fact holds only if the path resolves to `M0` and `M0`
   enumerates as empty. A different identity, or a non-empty `M0`, is
   PRESENT, and step 9 scans it. A present root is never evidence that the
   original is gone.

**Queued descriptors are closed by channel isolation (fact 2b).** A
descriptor queued unread on a surviving process's socket appears in no fd
table. A queue-length check cannot exclude it: a zero-byte Unix datagram can
carry `SCM_RIGHTS` with `Recv-Q == 0`. Revision 5 therefore closes the route
by construction. Every holder is a container with private network, IPC and
mount namespaces and no host socket (1.2.2, 1.2.5), so no holder could ever
reach a surviving host process's socket. Fact 2b holds when admission
verified that isolation (no host socket path or shared namespace in any
container's mounts or namespaces, by namespace inode) and the same is true at
close. Any container whose namespaces or mounts cannot be read is
OBSERVATION_FAILED, and the window is UNKNOWN. A per-socket `Recv-Q` reading
is kept only as corroboration, with the zero-byte limit stated. Probe P8
qualifies the isolation check, including a planted host-socket bind.

The fd budget is reserved at admission: `RLIMIT_NOFILE` minus the
descriptors already open and the reader's overhead must cover the declared
entry cap. If the census still exceeds the budget at runtime, the result is
UNKNOWN, never a truncated census.

### 2.3 Verdicts and the total release predicate

Per removed-class root: `ABSENT` (census complete, all four facts
CONFIRMED_NEGATIVE, tmpfs), `ABSENT_UNLINKED` (the same facts, but on a
persistent filesystem), `PRESENT`, or `UNKNOWN` (anything else).

**Release predicate, an allowlist.** The window is CLEAN only if **all** of
these hold:

- every declared retained surface has its own per-surface slice 4 result of
  COMPLETE and CLEAN, bound to this window's capture and held roots;
- every declared removed surface is `ABSENT`;
- the Contract B capture is `SEALED` and no latch is set;
- a window-bound provider-side **logout receipt** exists. Its revocation
  must be dated after the last turn and before teardown (2.2 step 2), and the
  receipt itself must be collected before acceptance (Q5);
- the 1.2 preconditions held at admission and again at close;
- the evidence set matches the declared surface set exactly, with none
  missing and none extra, and every item matches the context.

Any match anywhere gives NOT_CLEAN. **Everything else is UNKNOWN**, including:

- `ABSENT_UNLINKED` (the recommended answer to Q1);
- PRESENT on a removed root, even if its bytes scan clean;
- ABSENT on a retained root;
- a missing result, an extra result or a reused result;
- a public dictionary offered in place of evidence.

The class-level aggregate from slice 4's `public()` is never the input: one
unreadable retained role must not be hidden by another role's CLEAN.

CLEAN is a prerequisite, not release. Releasing the runner (step H) stays the
owner's act. UNKNOWN or NOT_CLEAN keeps the runner held until the owner
directs otherwise.

### 2.4 Committed negative controls (synthetic, CI)

The controls are descriptors in `controls/run-window-absence/`. A "blind twin"
is a committed checker mutant that the case must reject. Every regression-style
case is run red on its parent commit, and the PR reports that run.

| # | Case | Expected | Blind twin |
|---|---|---|---|
| A1 | Remnant planted under a root deleted, then recreated | NOT_CLEAN | "Present and scans clean, so released" |
| A2 | Recreated root, no remnant | UNKNOWN | Same |
| A3 | Root renamed instead of removed | UNKNOWN (`st_nlink >= 2`) | "ENOENT, so ABSENT" |
| A4 | File hard-linked outside before removal | UNKNOWN (`st_nlink == 1`) | Same |
| A5 | Survivor process remains in the holder domain | UNKNOWN at step 3 | A checker that runs only the `/proc` census |
| A6 | fd passed to an already-inspected process, or in flight over a socket, while the domain is not empty | UNKNOWN (step 3), not rescued by the census | Same |
| A7 | One `/proc` or mount-table read fails (injected) | UNKNOWN | "Unreadable, so nothing there" |
| A8 | Root or ancestor unreadable | UNKNOWN, never CLEAN | Same |
| A9 | Parent renamed and a new parent placed at the declared path, holding a remnant | NOT_CLEAN (the remnant is found); without the remnant, UNKNOWN | A held-parent-only lookup |
| A10 | Bind alias of a removed tmpfs with a different mount ID | UNKNOWN | A mount-ID-only check |
| A11 | Lazy detach observed | UNKNOWN | Same |
| A12 | Two retained roots alias the same directory | UNKNOWN | A path-string duplicate check |
| A13 | Retained root found absent | UNKNOWN | "Absent equals clean" |
| A14 | Disk-backed removed root, all facts hold | UNKNOWN (`ABSENT_UNLINKED`) | A checker that releases on unlinked |
| A15 | Evidence from another generation or capture, or a public dictionary | Refused | An equality-only guard |
| A16 | Census over the reserved fd budget at runtime | UNKNOWN, no truncation | A checker that drops entries to fit |
| A17 | Positive: everything holds | ABSENT | An always-UNKNOWN checker |
| A18 | After unmount, the mountpoint `M0` is non-empty, or is not `M0` | PRESENT, then scanned; NOT_CLEAN with a remnant, otherwise UNKNOWN | A checker that treats unmount as absence |
| A19 | Nested declared roots | UNKNOWN at admission | An equal-identity-only check |
| A20 | A digest mismatch on the second export file | Arrival quarantined, zero acceptances | A streaming exporter |
| A21 | A container given a host socket bind or a shared network or IPC namespace; or its namespaces unreadable | Refused at admission; UNKNOWN at close | A checker that reads only `Recv-Q`, which a zero-byte datagram passes |
| A23 | Container launched holding an inherited host socket fd, or one acquired mid-window | Latch UNKNOWN at the next fd sample | A checker that inspects only mounts and namespaces |
| A24 | Container with a host log driver (`json-file`) | Refused at admission | Same |
| A22 | A role home that is a container `--tmpfs` (destroyed before the census) | Refused at admission | A checker that accepts any tmpfs |

A3, A4, A9 and A12 use real temporary trees, because they depend on kernel
link and lookup semantics. A5 to A7, A10 and A11 use the injectable `/proc`,
mount-table and Docker readers.

## 3. Contract B: in-memory reference retention

### 3.1 Threat and failure mode

- **Wrong or incomplete references** give a false CLEAN, because the scan only
  finds what it is given.
- **References learned from the population** can be pre-shaped by a
  participant.
- **The bridge becomes the leak:** a copy at rest in a temp file, swap, a dump,
  a log, a pickle, a child's argv or environment, or a receipt.
- **Values minted during the window** (refreshed tokens) are not references.

### 3.2 Mechanism

**Window order:** the controller creates an empty `login-home`, the owner logs
in, then capture, seal, delivery from the seal, the live check, and dispatch.
Dispatch refuses until the capture is `SEALED`.

1. **The source is bound to the login session.** At window open, the controller
   creates `login-home` as an empty tmpfs (mode 0700, held fd, census
   recorded). The pinned client is configured to use **only** that directory
   for authentication. The token endpoint is reachable only while the
   interactive login runs. It is blocked at login completion, before the
   capture read (1.2.4), so the client cannot mint a value between capture
   and seal. Any alternative auth source makes capture UNAVAILABLE:
   an API-key variable, a keyring, a second config directory, or a credential
   file outside `login-home`. The owner's one interactive login runs inside
   the login container (1.2.5), where `login-home` is bind-mounted. Capture waits for the slice 2 `credential-login` receipt
   (login completed). It then requires two things: exactly one credential file
   in `login-home`, created after the directory and owned by the login container's uid
   with mode 0600; and the same file content on two reads separated by a
   declared settle interval, which shows that nothing was still writing it.
   Anything else is UNAVAILABLE. After each role's first turn, the role's
   credential bytes must still equal the seal, and the steward must report
   no reappearance. That is the evidence the client consumed the sealed
   source and nothing else. It is not proof that the client wrote those
   bytes. The remaining assurance comes from the empty directory, the single
   session and the B3 alternative-source refusal. `login-home` is both the authorized source
   and a removed-class root at close.
2. **Closed extraction.** A per-client extractor, initially only `codex`,
   classifies **every** field of the source format as secret or non-secret. An
   unclassified field, a missing secret field, or a set over slice 4's cap of
   8 values and 64 KiB gives UNAVAILABLE. It never captures a partial set. The
   sealed set is the whole file's bytes plus each secret field's value.
3. **Delivery consumes the seal.** The home delivery seam gets role artifacts
   **only** from the sealed object. It has no other byte source, so a delivered
   credential that is not sealed cannot exist by construction. A delivery or
   restore that would write bytes outside the sealed artifact set refuses.
   Transforms are computed from the sealed object before seal and sealed with
   it.
4. **Holding.** References stay in slice 4's opaque `References` object, owned
   by the controller. These are code changes: `__reduce__`, `__copy__` and
   `__deepcopy__` refuse. There is no file, environment, argv, stdin or pipe
   constructor. No process is created while references are live. Frames that
   handle secrets run under a locals guard. Inside the `except` block, the
   guard only sets a flag and clears the original traceback's frames
   (`traceback.clear_frames`). It raises its fixed-text error **after leaving
   the block**, so the new error's `__context__` and `__cause__` are both
   `None`. `from None` alone would leave `__context__` reachable. The guard
   frame's own locals hold only the opaque `References` object and fixed
   strings. Even a traceback rendered with locals cannot show the `value`,
   `text` or `patterns` locals of the current `_compile()`.
   The scan result binds the identity of the `References` object, as it binds
   the generation.
5. **Live end-to-end check, before dispatch.** Each role's delivered home is
   scanned with the sealed references and must be NOT_CLEAN. This is a
   placement test that the delivery happened and the scanner sees it. It is
   **not** the completeness argument; step 3 is.
6. **Refresh is observed directly, not inferred from an inode.** Stop-on-refresh
   is unchanged, and these latch a whole-window UNKNOWN:
   - Each role's steward reports a refresh or a credential reappearance.
   - At every `before_turn` and at close, the controller compares each role's
     delivered credential bytes, and the `login-home` source, against the
     sealed set in memory. Any difference latches, whether from a replaced
     file, an in-place write or a role-local refresh.
   - A comparison that cannot be read latches as a gap.
   - **Write observation (corroboration, with a bounded lifecycle).** The
     role credential files sit on controller-owned host tmpfs (2.2). The
     controller **arms** an inotify watch on each role's credential directory
     after that role's delivery completes, so its own delivery writes are not
     seen. It **drains** the watch at the teardown boundary (2.2 step 3),
     before its own deletions. Each event triggers an immediate byte
     comparison against the seal. The controller's own restore-and-rearm
     writes are **atomic**: written to a controller-named staging file **on
     the same mount** as the destination (the role's credential tmpfs), then
     `rename`d into place. A same-mount rename never fails with `EXDEV`. A comparison therefore never sees a half-written
     file. Sealed bytes compare equal and do not latch; any difference does
     latch. A queue overflow (`IN_Q_OVERFLOW`), or a
     watch removed before the drain, latches as a gap. inotify does not see
     writes through a shared `mmap` (`MAP_SHARED`), so this is corroboration,
     not the closing mechanism. The closing mechanism is refresh prevention,
     below.
   - Admission also requires the sealed credential's known remaining lifetime
     to cover the planned window (#624). That way the client has no scheduled
     reason to refresh.

   **Refresh is prevented, not only detected.** Precondition 1.2.4 blocks the
   token endpoint from login completion (before the capture read) through the
   confirmed teardown boundary, so no
   new value can be minted by any role or the login container, even by a
   writer still alive after dispatch stops. Anything
   that would have refreshed fails, and the steward's stop-on-refresh holds
   the window. This closes the route of a value minted, copied into a
   retained output and overwritten between checks, which detection alone
   could not close. **Acceptance also requires the owner's provider-side
   logout receipt**, revoked in 2.2 step 2 and part of the 2.3 predicate,
   before the quarantined arrival is accepted (2.2 step 10). Revocation is
   therefore always attempted before acceptance. Whether the native
   client's logout revokes server-side is a fact for the first approved
   window. Until it is shown, the endpoint block is the closing mechanism,
   and the logout is defence in depth.
7. **Lifetime.** References are dropped right after the final scan and export
   digest check. `released_before_export` records that **ownership transfer
   only**. The enforced bound is controller process exit, with swap and dumps
   off per 1.2. Best-effort buffer overwrite is done but not claimed.
8. **Loss is final.** A crash, a restart or a lost object means no references.
   There is no reload path, and re-reading any surface would learn from the
   population. The window is UNKNOWN, and recovery is the owner's decision
   (Q4).

### 3.3 Verdicts and receipt

Capture is `SEALED` or `UNAVAILABLE`. UNAVAILABLE refuses dispatch. SEALED is
necessary for CLEAN and never sufficient. A latch, a loss, or a capture after
first delivery makes the window UNKNOWN.

The **retention receipt** is a closed schema of booleans and durations only.
Any extra key refuses at construction. The values below are synthetic:

```json
{
  "version": 1,
  "captured": true,
  "source_bound_to_login": true,
  "captured_before_first_delivery": true,
  "delivery_from_seal_only": true,
  "delivery_matched": true,
  "refresh_latched": false,
  "comparison_gap": false,
  "persistence_controls_held": true,
  "released_before_export": true,
  "capture_after_login_s": 41.0,
  "retention_s": 3120.5
}
```

### 3.4 Committed negative controls (synthetic, CI)

| # | Case | Expected |
|---|---|---|
| B1 | Capture after first delivery or dispatch | UNAVAILABLE, dispatch refused |
| B2 | Source a symlink, wrong mode or owner, not in the empty `login-home`, created before it, two files, or unstable across the settle reads | UNAVAILABLE |
| B3 | An alternative auth source is present (API-key variable, second config directory) | UNAVAILABLE |
| B4 | Capture pointed at a tested surface | Refused structurally |
| B5 | Unclassified field, missing secret field, or over cap | UNAVAILABLE, no partial set |
| B6 | **A+B omission:** delivery requests artifact B while only A is sealed | Delivery refuses. This is an independent check, not one derived from the seal |
| B7 | Role-local refresh: in-place rewrite, replacement, or a new file | Latch (inotify event), window UNKNOWN |
| B7a | inotify queue overflow, or the watch removed before the drain | Gap latch, window UNKNOWN |
| B7c | Ordinary delivery, a restore-and-rearm with sealed bytes (including an event read mid-restore), and controller teardown deletions | **No** latch: restores are atomic, and the arm and drain points are correct |
| B7e | A value minted between the capture read and seal (block activated late) | Admission refuses the plan; at runtime, UNKNOWN |
| B7d | Endpoint block lifted at stop-dispatch while a writer is still alive | Admission refuses the plan; at runtime, the latch fires and the window is UNKNOWN |
| B14 | Missing or late logout receipt | Zero acceptances |
| B7b | Egress policy admits the token endpoint during dispatch | Admission refuses (1.2.4) |
| B8 | Planted refreshed token (not a reference) after a latch | Scan CLEAN, window UNKNOWN: the latch covers it, not the scan |
| B9 | Comparison unreadable at a turn | Gap latch, UNKNOWN |
| B10 | Controller loss mid-window | UNKNOWN. A structural test asserts that no constructor reads files, the environment, argv or stdin |
| B11 | Receipt with an injected count, length, hash or path | Refused |
| B12 | Forced exception inside `_compile`, extraction, delivery or scan, rendered with locals | No marker in the output |
| B13 | Positive: everything holds | SEALED |

## 4. No-leak tests (both contracts)

These use the independent `no_marker` oracle over raw, repr, escaped, JSON and
every fixed detector encoding. The material is synthetic, generated per test
in memory, independently for each role, and never used in test IDs.

1. **Every sink, at the descriptor level.** Capture is installed in every
   module (`conftest.py`, not one module's fixture), and file descriptors 1
   and 2 are redirected into pipes so a callback writing straight to fd 2 is
   still caught. The oracle audits receipts, public results, reprs, str,
   exceptions and chained tracebacks with locals, and logs.
2. **Process boundary.** Monkeypatched `subprocess`, `os.exec*`, `os.fork` and
   `os.posix_spawn` fail the test while references are live. A
   `sys.addaudithook` records `os.putenv` and `os.unsetenv`, so a transient
   environment change that is restored before the final snapshot is still
   caught.
3. **Disk, including transient writes.** The same audit hook refuses any
   write-open outside the monitored temporary root. Inside that root, it
   snapshots a file's bytes **before** each `os.remove`, `os.unlink`,
   `os.rename`, `os.replace` and `os.truncate`. That catches a write through
   an already-open fd followed by deletion. Names count as a sink. **Stated
   limit:** an in-place overwrite of a marker within one still-existing file,
   with no removal or truncation in between, is not snapshotted. The final
   content is still audited.
4. **Fragments.** The production detector matches exact bytes only, which is
   slice 4's stated limit. The test oracle is stricter: it also flags any
   16-byte window of a reference, including one split across two writes to the
   same sink. A committed split-output twin must fail it.
5. **Multi-role.** A leak planted only in role 3 must be found, so a single-role
   pass cannot go green (#624).
6. **Leaking mutants for each sink.** One deliberate mutant per sink (stderr,
   filename, transient file, environment, receipt field, traceback local) must
   fail the oracle through that sink's real path, not by calling the predicate
   on a hand-built witness.

## 5. Release integration controls

These cover the composed close, so the contract suites cannot pass while the
integration is either always held or wrongly open.

- **R1, clean arm.** Every prerequisite is evidenced synthetically, including
  the logout receipt. Exactly **one** arrival is **accepted**, carrying the
  frozen payload. Running close a second time is idempotent: zero further
  transfers and zero further acceptances.
- **R2 to Rn, one gate at a time.** Starting from R1, mutate a single
  prerequisite: a known match, a retained surface UNKNOWN, a removed surface
  `PRESENT`, `ABSENT_UNLINKED`, a capture UNAVAILABLE, a latch, a stale or
  substituted reference object, a payload digest mismatch, a missing logout
  receipt, a nonzero socket queue, or a precondition changed at close. Each
  must give **zero acceptances** and the expected verdict. A transfer into
  quarantine may still happen.
- The current slice 3 hard-hold tests remain until the PR that lifts each
  blocker.

## 6. What this changes in code (later PRs, not now)

- `skillc/run_window_absence.py` (Contract A) and
  `skillc/reference_retention.py` (Contract B). Both are stdlib-only with no
  kyle import. Any copied pattern source is cited under #630's borrowing terms.
- `remnant_scan`: a `login-home` class, the disposition table, per-surface
  private results, scanning from held root fds, binding of the reference-set
  identity, copy and pickle refusal on `References`, and the locals guard. The
  existing no-opt-in behaviour stays byte-identical, pinned by the legacy
  fixture.
- `vm_credential_window`: the refined close sequence and the total predicate.
  Each `BLOCKERS` entry is removed only in its own contract's PR. That is two
  SECRET-PATH PRs, A then B, and each also carries its part of R1 to Rn.

## 7. Physical facts that need the runner VM (DRAFT requests)

None of these is authorized. They join the VM batch only after the owner answers
Q2 and Q3. They run through the owner-started skillc CLI helper, outside any run
window, with residue only in the named dev directory, which is removed after
each run.

**The probes will be a reviewed artifact, not inline one-liners.** Review found
real bugs in revision 1's inline commands: a backgrounded `&&` list lost its
variables, suppressed errors turned into zero counts, error text was matched by
locale, and literal `<IMAGE_ID>` placeholders meant the commands could not run
as written. Each probe will be a checked POSIX shell script under
`controls/run-window-probes/`, committed in its own small PR and run as
`sh controls/run-window-probes/pN.sh [--image-id sha256:…]` at that PR's sha.
Each script uses `set -eu`, checks every exit status and parsed value, and
prints exactly one of `CONFIRMED_NEGATIVE`, `SURVIVOR_OBSERVED` or
`OBSERVATION_FAILED` for each arm. Every probe has a clean arm, a planted
survivor arm and a fault arm, and the fault arm must not print a passing
result.

| Probe | Fact qualified | Arms (expected) | Root | Docker |
|---|---|---|---|---|
| P1 | Link counts on the VM's tmpfs (fact 1) | rmdir gives 0 (negative); rename gives at least 2, hard link gives 1 (survivor); `stat` failure (fault) | No | No |
| P2 | `/proc` fd and `map_files` census can see a holder (fact 2 corroboration), and whether the controller uid reads every entry | one directly managed holder with a readiness handshake and a deleted file: fd-only and mmap-only holders (survivor); holder reaped and confirmed (negative); a denied read (fault) | Second run only if Q2 approves | No |
| P3 | Superblock absence after a non-lazy unmount, and that a held fd blocks unmount (fact 3) | errno-checked `EBUSY` while held; unmount succeeds and no table lists the superblock (negative); a bind alias at a second path (survivor); lazy detach (survivor); an unreadable table (fault) | Yes | No |
| P4 | Persistence controls (1.2.3) | swap off, verified dump policy, hibernation not enterable (negative); planted swap or piped handler readings (survivor); failed reads (fault) | No (read-only) | No |
| P5 | A bind-mounted host-tmpfs home leaves nothing in the overlay upper directory, and survives container removal | storage driver verified; write completion synchronized; a host-tmpfs write absent from the upper directory and still present on the host tmpfs after `docker rm` (negative); a write to the container root filesystem present in the upper directory (survivor); `find` denied (fault) | Yes (read the upper directory) | **Yes** |
| P6 | `docker rm` unlinks the upper-directory object | a held directory with a positive baseline link count goes to 0 after a checked removal (negative); a kept twin stays positive (survivor); a failed removal (fault) | Yes | **Yes** |
| P8 | Container channel isolation (fact 2b) | a container with private namespaces and no host socket (negative); a planted host-socket bind and a shared network namespace (survivor); a corroborating zero-byte `SCM_RIGHTS` datagram that shows `Recv-Q == 0` (documents the limit); unreadable namespaces (fault) | Yes | **Yes** |
| P9 | The pinned client's refresh endpoint can be blocked separately from inference (1.2.4) | runs inside the first approved window only: client inference succeeds while the token endpoint is refused (negative); a forced refresh is refused and the steward latches (survivor); also qualifies which logout route (2.2 step 2, (a) or (b)) works under the block | n/a | n/a |
| P7 | Writable-path inventory for the window uid (1.2.5) | inventory equals the declared set (negative); a planted writable directory (survivor); an unreadable mount (fault) | Yes (to read every mount) | No |

P5 and P6 take a validated image ID argument, the pinned attempt image from the
declaration, and must not run while a runner job is active. Indicative, not
runner-VM evidence: P1's arms were run once on a tmpfs elsewhere and read rmdir
0, rename 2, hard link 1, and 0 after the last unlink.

**Not probeable without a real window:** how the native client writes and
refreshes its credential. Those facts come only from a real login, which is a
window action, and are observed through the 3.2.6 latches in the first
approved window.

## 8. Open questions for the owner

- **Q1.** Can `ABSENT_UNLINKED` (unlinked on VM disk, not erased) ever satisfy
  release? This revision treats it as UNKNOWN, so every credential-bearing
  surface must be tmpfs. Confirm, or rule otherwise.
- **Q2.** Can the window controller run as root on the VM? The teardown
  boundary and census need to read every process's `/proc` entries and mount
  tables (P2 will measure whether that requires root). Without root, Contract A
  cannot reach ABSENT, and every release is the owner's directed act.
- **Q3.** May P1 to P8 run through the CLI helper (P9 belongs to the first approved window), with P3, P5, P6, P7 and P8 under
  root, and P5 and P6 touching Docker outside a runner job?
- **Q4.** When the references are lost mid-window, the proposed response is:
  hold the window, the owner logs out provider-side to revoke the credential,
  then a new window. Does the owner want a different recovery?

- **Q5.** Two parts. (a) The owner's provider-side logout becomes a required
  step at **every** window close, before any acceptance, whatever the
  verdict. Recommended: yes. (b) If the pinned client cannot have refresh
  blocked separately from inference by egress endpoint (1.2.4), should
  windows stay closed, or does the owner accept detection-only refresh
  handling (inotify plus comparisons), with its stated residual?
  Recommended: stay closed.
- **Q6.** Revision 5 moves the client's interactive login into a
  controller-created login container (1.2.5). The owner still reaches the VM
  over SSH. This refines the slice 3 design, which was approved as an
  interactive SSH login into a transient window-user session, so it needs the
  owner's approval. Recommended: yes. It is what closes queued-descriptor
  transfer by construction.

## 9. Out of scope

- Forensic block erasure, process-memory erasure, and a hostile root on the VM.
- Bytes sent off the VM. The egress policy (#442) is the control.
- A value minted and fully overwritten between two comparisons (3.2.6), beyond
  the latches and the lifetime precondition.
- Provider-side token revocation: an owner action, not a skillc guarantee.
- #619 residue semantics. Zero clutter is still not absence evidence.

## Appendix R: review record

**Reviewer:** OpenAI Codex CLI 0.171.0, model `gpt-6.2-sol`, resolved from
the run's own rollout record. It ran in a read-only sandbox and executed
nothing.

**Pass 1** could not read local files (the sandbox launcher was unavailable).
It reviewed the GitHub copies of the companion specs and code, without the
draft. **Pass 2** reviewed revision 1's full text, supplied on stdin.

**Verdict on revision 1: UNSOUND.** Its minimum changes for
SOUND-WITH-FIXES are listed below, with the dispositions taken in revision 2.
Revision 2 was re-reviewed (pass 3, below).

| # | Finding (severity) | Disposition |
|---|---|---|
| 1 | ABSENT tracks only original objects. Copies in new inodes, memfd or anonymous memory survive (blocker) | **Accepted.** Narrowed claim (0), containment preconditions (1.2), teardown boundary (2.2 step 3) |
| 2 | A stable PID list does not prove stable reference ownership: in-flight fds, fds passed to inspected pids, bind aliases, lazy detach (blocker) | **Accepted.** The holder domain must be empty, with `/proc` only as corroboration; superblock check; lazy detach refused; A5, A6, A10, A11 |
| 3 | Scan scope binds path strings: aliases, replaced roots, files added after enumeration (blocker) | **Accepted.** Held physical roots, alias refusal, quiescence from step 3, export digest check (2.2 steps 9–10); A12 |
| 4 | A positive check from the sealed set cannot detect an omitted reference (blocker) | **Accepted.** Delivery consumes only the seal (3.2.3); closed field classification; independent A+B control B6; the positive check is demoted to a placement test |
| 5 | No-leak sink coverage incomplete: fd 2, filenames, transient writes, fragments (major) | **Accepted.** Section 4 items 1–4 and 6 |
| 6 | No clean arm reaches export, so an always-held integration passes (major) | **Accepted.** Section 5 (R1, R2 to Rn) |
| 7 | Probes cannot tell a negative from an observation failure (major) | **Accepted.** Three-outcome probe scripts (section 7) |
| 8 | Capture authenticates metadata, not provenance or the source the client actually uses (blocker) | **Accepted.** Empty controller-created `login-home`, single auth source, settle reads, B2 and B3 |
| 9 | Refresh detection through a held fd's inode cannot see replacement, in-place writes or role-local refresh (blocker) | **Accepted.** Direct byte comparison at every turn and at close, a gap latch, and a lifetime precondition (3.2.6). Residual stated |
| 10 | The observation boundary was inconsistent: §2.2 put writers stopped before the census, while §5 put the census first (blocker) | **Accepted.** One close sequence (2.2), reconciled with slice 3's pre-stop "freeze census" |
| 11 | Composition was not total; `ABSENT_UNLINKED` had no branch, and the class aggregate could hide a role (blocker) | **Accepted.** Total allowlist predicate (2.3); `ABSENT_UNLINKED` is UNKNOWN pending Q1; per-surface results |
| 12 | A held parent fd does not detect replacement of the parent name (major) | **Accepted.** Re-resolution from `/` through the held ancestor chain (fact 4); A9 |
| 13 | Lifetime and privacy claims exceeded the code: `_compile` locals; `References` lacks copy and pickle refusal (major) | **Accepted.** Locals guard and refusals as code changes (3.2.4, section 6); B12; `released_before_export` redefined as an ownership transfer |
| 14 | Persistence must cover every credential-bearing process for the whole window, including a piped `core_pattern` (major) | **Accepted.** 1.2.3, verified before login and at close |
| 15 | A13 promised an admission decision about a future tree (major) | **Accepted.** Split into a reserved budget at admission and a runtime UNKNOWN (A16) |
| 16 | P1–P6 command bugs: a backgrounded `&&` list (P2), suppressed errors, locale-dependent matching, placeholders (blocker/major/minor) | **Accepted.** Inline commands withdrawn and replaced by reviewed probe scripts (section 7) |

**Pass 3** reviewed revision 2. **Verdict: UNSOUND.** Findings 4, 6, 7, 10, 11,
12, 15 and 16 were judged CLOSED. Findings 1, 2, 3, 5, 8, 9, 13 and 14 were
judged PARTIAL. Pass 3 also found three new issues. Revision 3's dispositions:

| # | Pass 3 finding | Revision 3 disposition |
|---|---|---|
| 17 | **Blocker.** Removal could not establish its own facts. Unmounting before inspecting the held fds destroys the link-count evidence (and a held fd blocks the unmount), and unmounting exposes the underlying mountpoint | **Accepted.** Re-ordered: remove entries, facts 1–2 while held, close fds, errno-checked unmount, then facts 3–4. Fact 4 checks the recorded empty mountpoint `M0` (A18) |
| 18 | **Blocker.** Export could precede its gate: a streaming exporter publishes before a later digest mismatch | **Accepted.** Two-phase export into quarantine; accepted in one step only after the composed verdict (2.2 step 10, A20) |
| 19 | **Major.** A1 and A9 had no scan path for a recreated removed root | **Accepted.** Step 9 scans every PRESENT removed-class root |
| 1, 2 | PARTIAL: the login session's own writable locations and channels; a prior lazy detach | **Accepted.** 1.2.5 confines the login session (writable-path inventory P7, no forwarding, no lingering). Lazy detach is moot once the domain is empty, and a surviving holder is visible to the census. The queued-fd case is a **stated residual** (2.2) |
| 3 | PARTIAL: host-workload quiescence; nested roots | **Accepted** in part. Disjoint roots (1.2.6, A19). Host workload stays the declared minimal set under the VM trust boundary |
| 5 | PARTIAL: a write through an existing fd, then deletion | **Accepted.** Snapshot before remove, rename or truncate. The in-place overwrite case is a stated limit |
| 8 | PARTIAL: no proof that the client wrote or used those bytes | **Accepted** in part. Post-first-turn seal equality plus no reappearance. "Wrote" is a stated limit |
| 9 | PARTIAL: a transient refresh copied to output, then overwritten | **Stated residual, not closed.** Mitigation is owner question Q5: provider-side logout at every close |
| 13 | PARTIAL: `from None` leaves `__context__` set; the guard frame's own locals | **Accepted.** The fixed error is raised outside the `except` block; the guard frame holds only opaque objects |
| 14 | PARTIAL: endpoint checks miss a mid-window change | **Accepted** in part. Sampled at every turn and on an interval. A change and restore between samples needs root, so it is under the VM trust boundary |

Revision 3 was re-reviewed (pass 4, below).

**Pass 4** reviewed revision 3. **Verdict: UNSOUND.** It closed 17 in
principle and closed 18 for publication. It found 19 partially closed. It
accepted the no-leak in-place-overwrite limit, the client-authorship limit
and the scope limits (exact-byte detection, erasure, egress, root changes
between samples). It ruled that two stated residuals were blockers and found
one new blocker. Revision 4's dispositions:

| # | Pass 4 finding | Revision 4 disposition |
|---|---|---|
| 20 | **Blocker.** `login-tmp` was missing from the closed disposition table | **Accepted.** Added as removed-class |
| 21 | **Blocker.** A descriptor queued on a surviving host socket is invisible to the census (the residual must fail closed) | **Accepted.** Fact 2b: every surviving Unix socket must show `Recv-Q == 0` (`SCM_RIGHTS` needs at least one data byte), and an unreadable queue is UNKNOWN; A21, P8 |
| 22 | **Blocker.** A transient refresh could reach accepted output, Q5 was insufficient, and acceptance could come before revocation | **Accepted.** Refresh is prevented by the egress endpoint block (1.2.4, B7b, P9); complete inotify write observation with a gap latch (B7a); the logout receipt is required before acceptance |
| 23 | **Major.** The tmpfs lifetime through Docker removal was unspecified | **Accepted.** Role surfaces are controller-owned host tmpfs, directory-bind-mounted, never a container `--tmpfs` (2.2, A22, P5) |
| 24 | **Major.** A9's ancestor mismatch never reached the scan | **Accepted.** Step 9 also scans the safely re-resolved replacement path; that root keeps its sticky UNKNOWN, and a match gives NOT_CLEAN |
| 25 | **Minor.** R2 and A20 counted exports rather than acceptances | **Accepted.** Both count acceptances; a quarantine transfer is allowed |

Revision 4 was re-reviewed (pass 5, below).

**Pass 5** reviewed revision 4. **Verdict: UNSOUND.** Findings 20, 23, 24 and
25 were judged CLOSED. Findings 21 and 22 were reopened, and two majors were
new. Revision 5's dispositions:

| # | Pass 5 finding | Revision 5 disposition |
|---|---|---|
| 21 | **Blocker.** A zero-byte Unix datagram can carry `SCM_RIGHTS` with `Recv-Q == 0`, so the queue check is unsound | **Accepted.** The route is closed by construction: the login moves into a login container, so every holder has private namespaces and no host socket (1.2.5, fact 2b, A21, P8). `Recv-Q` is demoted to corroboration with the limit stated. Needs owner Q6 |
| 22a | **Blocker.** The endpoint block covered dispatch only; a writer alive after stop-dispatch could refresh | **Accepted.** The block runs from seal to the confirmed teardown boundary (1.2.4, B7d) |
| 22b | **Blocker.** The logout gate was missing from step 10 and 2.3, and a local logout may not revoke | **Accepted** in part. The logout receipt is in the 2.3 predicate and step 10, and is obtained in step 2 (B14). Server-side revocation stays unverified, as a stated fact for the first window. The endpoint block, not revocation, is the closing mechanism |
| 26 | **Major.** inotify could latch on the controller's own writes, and misses `MAP_SHARED` writes | **Accepted.** Armed after delivery and drained at teardown; each event triggers a byte comparison; the watch is demoted to corroboration (B7c) |
| 27 | **Major.** One `login-tmp` mounted at three paths contradicts the alias rule | **Accepted.** Three separate controller-owned tmpfs per container (`scratch-tmp`, `scratch-vartmp`, `scratch-shm`), with no permitted aliases |

Revision 5 was re-reviewed (pass 6, below).

**Pass 6** reviewed revision 5. **Verdict: SOUND-WITH-FIXES.** Findings 22a,
22b and 27 were judged CLOSED. Findings 21 and 26 were judged PARTIAL, and
two timing and liveness gaps were new. Revision 6 applies the four minimum
fixes:

| # | Pass 6 finding | Revision 6 disposition |
|---|---|---|
| 21 | PARTIAL: inherited host descriptors, and the pty path persisting through Docker logging | **Accepted.** Lifetime fd invariant sampled at start, at each turn and at teardown (A23); `none` log driver (A24) |
| 28 | The refresh block came only after the capture read, so the client could mint between capture and seal | **Accepted.** Block active at login completion, before capture (1.2.4, 3.2.1, B7e) |
| 29 | The logout receipt might be unobtainable under the refresh block | **Accepted.** Two qualified logout routes, chosen at admission (P9); admission refuses if neither is qualified |
| 26 | PARTIAL: a non-atomic restore could latch a clean window (implementation detail) | **Accepted.** Atomic staged rename; B7c covers the interleaving |

Revision 6 was re-reviewed (pass 7, below).

**Pass 7** was a confirm-only pass on revision 6. **Verdict:
SOUND-WITH-FIXES.** No new route from UNKNOWN to CLEAN or ABSENT. Fixes 21
and 28 were judged APPLIED. Fixes 29 and 26 were judged NOT APPLIED. Revision
7 applies only these minimum fixes:

| # | Pass 7 finding | Revision 7 disposition |
|---|---|---|
| 29 | The logout route was "chosen at admission" by P9, which runs only inside a window, and the external receipt's timing contradicted 2.3 | **Applied.** Route (b) is the default and needs no prior qualification; route (a) is admissible only after P9 qualifies it in an earlier window. Revocation happens before teardown, and the receipt is collected before acceptance (2.2 step 2, 2.3) |
| 26 | Staging the restore on another tmpfs breaks the rename (`EXDEV`) | **Applied.** The staging file is on the destination mount; B7c is retained |
| 28 | The 3.2.6 "from seal" wording did not match 1.2.4 | **Applied.** Now "from login completion (before the capture read)" |

Revision 7 has not been re-reviewed. The orchestrator ruled that no eighth
pass is required unless pass 7 had said UNSOUND.
