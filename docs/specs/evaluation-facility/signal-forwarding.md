# Design: in-container signal forwarding to the exec'd subject (#158)

- Status: Draft for review — design only, no implementation yet
- Date: 2026-09-28
- Refs: #158, #133 item 2, #78
- Touches: `skillc/docker_backend.py`, `docker/trial/Dockerfile`

## 1. Problem (restated from #158)

`DockerBackend.execute()` starts the subject with `docker exec` against an
already-running container whose foreground process is a keep-alive
placeholder (`_KEEPALIVE_ARGV = ("sleep", "infinity")`, started by
`prepare()`, before the real argv is known). On timeout/cancellation,
`_stop()` calls `docker kill --signal TERM` against the CONTAINER, which
reaches only that placeholder (PID 1's child under `--init`/tini) — never the
subject, which runs as a separate, sibling `docker exec` session in the same
PID namespace but outside the container's own process tree. The subject gets
no graceful shutdown signal; it dies when the container is removed at the
`SIGKILL` escalation. This is `describe()`'s `unobserved` entry and
`capture.md`'s matching note, both citing this issue.

The rejected client-side fix (`docker top` + `docker exec kill <pid>`) fails
on PID ambiguity: from outside, nothing distinguishes the subject's PID from
another live exec session or the subject's own forked children.

## 2. Design: register-then-exec wrapper, relayed by an in-container supervisor

The core idea: stop treating the subject as a sibling of the container's PID 1
and instead give the container's own foreground process (the thing `--init`
already forwards signals to) a way to learn the subject's PID with certainty,
not by guessing from outside. This sidesteps the ambiguity problem structurally
rather than solving it: **only one subject ever runs per container** (`execute()`
is documented "intended to be called ONCE per handle" — see its docstring), so
there is at most one PID to track, and the registration is authoritative
because it comes from the subject's own launch, not inferred after the fact.

Two new small components, both baked into the trial image:

### 2a. `skillc-supervisor` — replaces the keep-alive placeholder

`_keepalive_run_argv` currently starts the container with `_KEEPALIVE_ARGV =
("sleep", "infinity")` as the foreground process under `--init` (tini is
still PID 1; the placeholder is tini's direct child, and tini already
forwards signals to it — that part is unchanged). This design replaces that
placeholder with a small supervisor process that:

1. Creates a well-known Unix domain socket (e.g. `/run/skillc/control.sock`,
   a directory baked into the image, owned by `candidate`, mirroring the
   `~/.claude`/`~/.codex` precedent in `docker/trial/Dockerfile`) **before**
   entering its main loop, so it is guaranteed to exist by the time
   `prepare()` returns (which already blocks until the container is
   confirmed running) and long before `execute()` can possibly call
   `docker exec`.
2. Registers a `SIGTERM` handler. On receipt, if a subject **process group**
   has been registered (see 2b — revised per review: the group, not the bare
   PID), relays it: `os.killpg(pgid, signal.SIGTERM)`, after a liveness check
   (`os.killpg(pgid, 0)` — a process GROUP check, not `os.kill`, since a bare
   PID check can't confirm a whole group, only the leader — catching
   `ProcessLookupError`) so a subject that already exited is not chased into
   a pgid a redundant new process claimed.
   If nothing is registered yet, it does nothing extra — identical to
   today's behavior (there is nothing to forward to). **This "nothing
   registered" case, and any other case where forwarding did not happen, is
   itself recorded** — see the reporting requirement below.
3. Otherwise keeps the container alive exactly as `sleep infinity` does
   today. `SIGKILL` cannot be intercepted (unchanged, matches today: the
   container just dies, and the subject dies with it — the existing
   `_stop()` second-kill escalation is the backstop either way).
4. The registration handling itself must not block the supervisor's own
   signal responsiveness — accept connections on a background thread (or a
   `select`/`asyncio` loop), single global var for "current subject pgid",
   guarded by a lock only for the assignment itself.
5. **The supervisor does not own a shutdown clock of its own.** It relays
   TERM and returns immediately — it does not wait for the subject to exit,
   does not escalate to KILL on any timer, and does not retry. All timing
   (how long to wait after TERM before the host's own `_stop()` sends the
   second `docker kill --signal KILL`) stays exactly where it is today: the
   host, via `_stop()`'s existing `grace` parameter and `proc.wait(timeout=
   grace)` calls. This design adds a relay, not a second escalation policy —
   two clocks deciding when to give up would be its own source of
   disagreement, and the host's is already the one `execute()`'s caller
   controls via `Limits.grace`.
6. **The supervisor MUST NOT exit after relaying TERM — this is load-bearing,
   not a style preference (review must-fix).** It is `tini`'s only child. If
   its `SIGTERM` handler relays and then lets the process exit — the default
   outcome for a plain Python process with nothing else keeping it alive, or
   any handler that itself calls `sys.exit`/returns control to a normal
   post-signal exit path — `tini` has nothing left to supervise and exits
   too. PID 1 gone means the kernel tears down the PID namespace and
   SIGKILLs everything left in it, subject included, within microseconds of
   the relay. The subject would receive TERM and then SIGKILL almost
   immediately after — defeated by the exact kernel mechanism #176 modeled
   for the NO-supervisor case, now self-inflicted by the supervisor's own
   exit. Concretely: the handler relays, and the supervisor's main loop
   keeps running — holding the container's PID 1 alive — until the HOST's
   own escalation (a second `docker kill --signal KILL`) or container
   removal ends it, exactly as `sleep infinity` survives its own container
   staying up today. This is the only way the subject actually gets the
   `grace` window `_stop()` intends to give it.

### 2b. `skillc-wrap` — a one-shot registering exec wrapper

`execute()`'s `docker exec` argv changes from

```
docker exec -w WORKSPACE -- NAME <subject argv...>
```

to

```
docker exec -w WORKSPACE -- NAME /usr/local/bin/skillc-wrap <subject argv...>
```

`skillc-wrap` is a tiny script (baked into the image, matching the
`verify_codex_sidecar.js` precedent for small image-resident helpers) that:

1. Calls `os.setsid()` to become its own process group leader — **before**
   registering, so the group id it reports is stable for the subject's
   whole life. This is the process-group revision from review: a CLI agent
   subject will very plausibly fork its own children (subprocess calls,
   tool invocations), and relaying to a bare PID would leave every child
   unreached. `os.setsid()` makes `skillc-wrap`'s (soon to be the subject's,
   post-`exec`) pid its own pgid, and every child it forks inherits that
   group unless a child explicitly starts its own session — so
   `os.killpg(pgid, SIGTERM)` reaches the subject and its ordinary
   descendants, not just the top-level process.
2. Connects to the supervisor's control socket and sends its **own** pgid
   (`os.getpgrp()`, equal to its own pid after step 1), best-effort, with a
   short bounded timeout (on the order of the module's existing
   `daemon_timeout` discipline — this is a local, same-host, same-container
   socket write, so a generous bound like 1s is already conservative).
3. **Reports the outcome of that registration attempt**, not just attempts
   it silently. Whether the socket connect/write succeeded or failed (and,
   separately, whether the supervisor's later relay actually finds a live
   pgid to signal) must be observable evidence, not inferred from "the
   subject launched" — see the reporting requirement below. If registration
   fails for any reason, `skillc-wrap` proceeds to exec anyway — **fails
   open to today's behavior** (subject still runs, just without forwarding),
   never blocks or refuses the subject's launch over a supervisor hiccup.
4. Immediately `exec()`s into the real subject argv (`os.execvp`), replacing
   its own process image. Because `exec()` preserves the PID (and, from step
   1, the pgid), the pgid the supervisor just recorded **is** the subject's
   process group for the rest of its life — no separate parent/child
   relationship to track, no second lookup.

**Reporting requirement, with a concrete shape (ruled in review — Q3): a
NEW `ExecuteResult` field**, not an overload of the existing `signal` field
(which means the container-level signal and should keep meaning only that).
Suggested values: `forwarded` / `registration-failed` / `not-registered` /
`unavailable-in-image` (the last one is §2d's capability-gate outcome). A
green "TERM forwarded" must never be *inferred* from the fact that a launch
proceeded normally — that conflates "we don't know" with "it worked," which
is exactly the posture this module's `_inspect()`/`Confirmation.UNKNOWN`
discipline elsewhere in this same file already refuses to do.

**This evidence is advisory, not trusted (review must-fix — who can forge
it).** The supervisor and `skillc-wrap` both run as `candidate`, inside the
SAME container as the subject, with no privilege boundary between them. The
subject — untrusted code under evaluation — can connect to the same control
socket itself, register any pgid it chooses (including a decoy), or simply
kill or replace the supervisor process outright. So ANY `forwarded` (or
other) outcome reported from inside the container is evidence the SUBJECT
can shape or fabricate — the same class of problem as the #14 forged-log
gap: a provenance marker inside an artifact proves nothing, because
anything that can write the artifact can write the marker. This in-container
reporting must be read as advisory instrumentation for a human debugging a
trial, never as trusted evidence anything grading or verification relies
on. §5 names the one thing the host CAN corroborate independently.

This is the property that keeps the change small: from the host side,
`execute()`'s `subprocess.Popen(exec_argv, ...)` still directly owns the
`docker exec` process, still gets the same stdout/stderr/stdin pipes it gets
today (the wrapper's own stdio, inherited by `exec()`), and every downstream
mechanism — `_BoundedDrain`, the stdin-feeder thread, the deadlock-avoidance
ordering, `proc.wait()`, `proc.returncode` — is **untouched**. Only two things
change: the argv gets a one-token prefix, and the placeholder command run at
`prepare()` time changes from `sleep infinity` to the supervisor binary.

### 2c. `_stop()`

No structural change. `_kill_container(handle, "TERM")` still targets the
container; it now reaches the supervisor (as it reaches the placeholder
today), which relays to the registered subject PID if one exists. The
existing grace-wait-then-SIGKILL escalation is unchanged — this design only
changes what the first TERM *does* once it lands, not the escalation shape.

### 2d. Capability-gated activation (review must-fix: landing order)

§7's landing order put implementation (step 3) ahead of the image change
(step 4) without saying how that works — but step 3 as originally written
prefixes every `docker exec` with `/usr/local/bin/skillc-wrap`
unconditionally, and on the CURRENT image (the one the operator's #150 run
also uses), that path does not exist, so every trial would exit 127. The
implementation cannot land ahead of the image unless it is inert on an
image that lacks the two new binaries.

Resolved as option (a): `execute()` does not assume `skillc-wrap` is
present. Before composing the exec argv, it probes whether the running
container's image actually carries the forwarding components — a bounded
check in the same style `prepare()` already uses before `run -d` (its own
`_image_present_locally` pre-check refuses to assume and asks first,
rather than let a later call fail ambiguously). Present: use the
`skillc-wrap` prefix exactly as §§2a/2b describe. Absent: run today's exact
argv, unprefixed — behaviorally identical to the pre-#158 code — and record
`unavailable-in-image` (§2b's `ExecuteResult` field, see the ruling below)
rather than silently doing nothing. The probe result is cacheable for a
handle's whole lifetime (checked once, not per `execute()` call — this
module's own docstring already establishes `execute()` runs at most once
per handle), a detail rather than a load-bearing choice.

This is what makes the implementation reviewable, testable against the
fake CLI (which can declare `skillc-wrap` present or absent per test), and
mergeable well before the image itself carries the two new binaries — and
it is INERT, not merely safe, on any container whose image predates this
work, including #150's.

## 3. Image change (#78 interaction — called out explicitly, per assignment)

**Status: HELD.** This change is kept on its own branch, unmerged, until the
operator's #150 discriminating run has happened — that run builds the trial
image from `main`, so the image must not change underneath it while it is
pending. Once that run lands, a follow-up adds a note to
`docs/runbooks/150-discriminating-run.md` saying the image needs to be
rebuilt to pick this up. The design below is reviewable now; the image
itself does not land until that dependency clears.

This requires changes to `docker/trial/Dockerfile`, which #78 pinned and
which the assignment says needs a decision before it lands:

- Two new baked files: `skillc-supervisor` and `skillc-wrap` (Python,
  consistent with the image already carrying a full `python3` per #81 for
  `skillc.verify`'s probe and `skillc.demo`'s subject — no new interpreter
  dependency).
- A new directory, `/run/skillc/`, created and `chown`'d to `candidate` at
  build time, same pattern as the existing `~/.claude`/`~/.codex`
  pre-creation — **empty control-plane scaffolding baked in, never per-trial
  content**, matching the Dockerfile's own stated principle for those
  directories.
- `_keepalive_run_argv` in `docker_backend.py` changes its placeholder
  command from `_KEEPALIVE_ARGV` to the supervisor's path.
- A build-time, no-daemon control in the style of `check_interpreters.py` /
  `check_pins.py`: assert both scripts are present, executable, and
  (best-effort) syntactically valid — catching a broken/missing component at
  BUILD time, per #78's own stated design principle, rather than at trial
  time.
- No change to `--init`, the base image, the non-root `candidate` user, or
  any of the other #78-established Dockerfile properties (no docker binary,
  no bubblewrap, pinned CLI versions). This is additive.

## 4. The fake CLI could not show the red case - fixed in #176

Acceptance criterion 3 in #158 asks for "a red case against the fake docker
CLI showing the pre-fix subject never receiving TERM, and green after."
While writing this design I found that `fake_docker.py`'s `cmd_kill`
signaled the exec'd process's real pid with the REQUESTED signal directly
(`os.killpg(exec_pid, sig)`) — more capable than real Docker, which never
forwards its own requested signal to a sibling `docker exec` session. That
made the criterion undemonstrable against the fixture as it stood: the
"subject" a red-case test plants already appeared to receive TERM, so there
was nothing to show going red.

**Landed as #176 (commit `ee00e41` on `main`).** `cmd_kill` now flips the
container's status to `"exited"` AND `os.killpg`s the recorded `exec_pid`
with **SIGKILL always** — never the requested `--signal` — modeling a real
container's actual behavior: PID 1 dying (from a forwarded TERM, or an
outright KILL) triggers a kernel PID-namespace teardown that SIGKILLs every
other process in it, exec sessions included. So the subject never receives
a *graceful, forwarded* TERM (that remains the real bug §158 exists to
fix), but it does not survive a container-level kill either. (An
intermediate draft during review modeled `kill` as a bare status flip
touching nothing at all — also wrong, the other way: it left a fake where
the container reads "stopped" while the subject keeps running, a blind
spot no real daemon has. Not merged.) `cmd_rm` gained the identical
`killpg` reaping as a backstop, for a caller that removes a container
without a preceding `kill` at all.

#176's own committed red/green pair — verified by hand against the actual
pre-fix fake and the intermediate draft, both red, the merged version green
— is #158's acceptance criterion 3, delivered:
`test_a_container_level_kill_does_not_reach_the_execd_subject_but_still_kills_it`
in `tests/test_docker_backend.py`. A full suite run pinned to the merge
commit was clean: 1863 collected, 1860 passed, 3 skipped, 0 failed — no
other test depended on `kill` reaching the subject with the requested
signal.

**#176's fake now always kills the exec group on `kill` — which is correct
for the no-supervisor case, but means it cannot yet represent a
*successful* forward.** This design's supervisor (§2a) needs the fake to
distinguish "PID 1 dies, kernel reaps everything" from "PID 1 (the
supervisor) survives and relays gracefully"; that fake extension is scoped
to the implementation PR, not this one — see §7 step 3.

See §7 for how this fits the overall landing order.

## 5. Accepted limitations (stated, not silently solved)

- **The in-container forwarding evidence is forgeable by the subject it
  describes (review must-fix — full reasoning in §2b).** The supervisor and
  `skillc-wrap` run as the same unprivileged user, in the same container, as
  the subject under evaluation — there is no trust boundary between them.
  The subject can register a pgid of its own choosing, connect to the
  control socket directly, or kill/replace the supervisor outright, so any
  `ExecuteResult` value this design reports (`forwarded`, etc.) is advisory,
  never trusted evidence. **The only host-side corroboration this design
  provides is indirect and outcome-only, not mechanism-specific**: whether
  the subject process exited within `grace` after the container-level TERM
  (observed via `_stop()`'s own existing `proc.wait(timeout=grace)`, from
  OUTSIDE the container, through a mechanism already in place today) versus
  surviving to the SIGKILL escalation. That timing fact corroborates that
  *something* caused a prompt exit — it does not corroborate that THIS
  design's relay was the cause, as opposed to the subject's own unrelated
  exit timing. Anything stronger would need evidence sourced from outside
  the container's own trust boundary entirely, which this design does not
  attempt to build.
- **Process-group relay (§2b) still only reaches descendants that stay in
  the subject's own group.** A child that starts its own session (rare, but
  possible for a subject that deliberately daemonizes something) is out of
  reach, same as a bare shell job-control `kill` would miss it. Not solved
  here.
- **Fail-open, not fail-safe.** If the wrapper can't reach the supervisor
  (crashed, socket permission issue, image predates this change), the
  subject still launches, just without forwarding — identical to today's
  behavior. This is deliberate: a trial should not fail to start over a
  signal-forwarding side channel.
- **A race window exists** between "TERM delivered to the supervisor" and "the
  wrapper's registration write has landed" — if `_stop()`'s first TERM fires
  before the wrapper has registered (e.g. the subject genuinely hasn't been
  execed yet), it is dropped exactly as today, and the existing grace-then-
  SIGKILL escalation is the only backstop. This is one of the
  never-attempted states the reporting requirement in §2b covers, so it is
  visible after the fact rather than silently indistinguishable from a
  successful relay. Given registration is a local, same-host socket write
  completing in well under a millisecond, the window itself is negligible
  against any realistic `grace`, and I'm not proposing a full handshake/ack
  protocol to close it unless it's observed to matter in practice.
- **Whether a real subject actually receives and can act on the forwarded
  signal remains unobserved by this design alone** — matching #158's own
  acceptance criterion 4, this needs the live-daemon run; nothing here should
  be read as fixed until it has.

## 6. Mapping to #158's acceptance criteria

1. "An in-container supervisor design... stated precisely enough to review
   before building." — this document (§2).
2. "The #78 image change it requires, if any, called out explicitly before
   it lands." — §3. Held pending the operator's #150 discriminating run; the
   design is reviewable now, the image does not land until that dependency
   clears.
3. "A red case against the fake docker CLI showing the pre-fix subject never
   receiving TERM, and green after." — §4: **done**. Delivered by #176
   (`ee00e41`), merged before this design doc.
4. "Live-daemon verification..." — operator-owed, unchanged from the issue
   text. Not simulated here or anywhere in this design.

## 7. Landing order

1. ~~Fake-fidelity PR~~ — **done**: #176 (`ee00e41`), merged. `cmd_kill` now
   flips status AND `os.killpg`s the recorded `exec_pid` with SIGKILL
   always; `cmd_rm` carries the identical reaping as a backstop. Full suite
   clean on that commit: 1860 passed, 3 skipped, 0 failed. See §4.
2. This design doc, as a doc-only PR (no code) — **in review now**.
3. Implementation PR(s) for `skillc-supervisor`/`skillc-wrap`, the
   `execute()`/`_keepalive_run_argv` changes, and §2d's capability gate,
   using #176's red case as #158's acceptance evidence (criterion 3,
   already satisfied). **Can land ahead of the image** (§2d): inert,
   behaviorally identical to today, on any image that lacks the two new
   binaries — including the one #150's operator run uses. This PR owes two
   more things, both found in review and neither optional:
   - **The fake CLI needs a new capability it does not have yet** (see §4):
     `cmd_kill` (#176) always `os.killpg`s the exec group with SIGKILL,
     unconditionally — correct for the no-supervisor case #176 fixed, but
     it means the fake as it stands **cannot represent a successful
     forward at all**: there is no way to simulate "PID 1 (the supervisor)
     survives a TERM and relays it gracefully" versus "PID 1 dies and the
     kernel reaps everything." The fake needs to learn the difference —
     e.g. a state flag meaning "a supervisor is present and stays alive
     after `kill`," under which the exec'd process receives a real,
     catchable TERM instead of an unconditional SIGKILL — before any test
     can show §2a's relay actually working.
   - **A committed red case for §2a's must-not-exit rule**: a supervisor
     that relays TERM and then exits (the bug §2a item 6 exists to
     forbid) must be shown making the subject die within `grace` WITHOUT
     completing its own TERM handler — i.e. reaped by the kernel's
     PID-namespace teardown, the same failure mode #176 modeled for the
     no-supervisor case, now self-inflicted. Green is a supervisor that
     relays and keeps running, letting the subject's own handler complete
     within `grace`.
4. The `docker/trial/Dockerfile` image change (§3) — held, separately,
   until the operator's #150 discriminating run has completed. Once it
   activates, step 3's capability gate flips to using the wrap prefix with
   no further code change.

## 8. Decisions from review

1. **Registration channel: Unix domain socket** (not FIFO or a `docker
   cp`'d file-drop) — trivial "reachable or not" framing, no
   cleanup-on-restart ambiguity.
2. **`/run/skillc/`, outside `CONTAINER_WORKSPACE`** — so `install()`'s
   baseline-absence check (§133 item 4's `_workspace_baseline`) never sees
   the control socket at all, rather than needing to special-case it.
3. **A new `ExecuteResult` field** for the forwarding outcome, not an
   overload of `signal` (which keeps meaning only the container-level
   signal). See §2b for the field's values and the forgeability caveat
   attached to it.
