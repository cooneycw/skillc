"""The execution backend seam (#10): where a subject actually runs.

interfaces.md's installation and execution lifecycle names nine steps but never
says what performs steps 3 through 7's process side and 9's teardown - only
that they happen "in allocated workspace/home locations" under the evaluator's
control. This module makes that explicit as a stdlib `Protocol`: an
`ExecutionBackend` is the thing that owns a workspace, starts a skill's
installation and the agent under test INSIDE whatever isolation it provides,
and can be asked - independently of what it reported while running - whether
its work actually stopped and whether nothing of it remains.

skillc will ship its own Docker-backed implementation (`skillc/docker_backend.py`,
a later #10 PR - it does not exist at this commit), and that backend will be a
complete, standalone answer to #10: it needs no other system. The seam exists
so ANOTHER backend - a different isolation technology, or one supplied by a
larger system this skillc instance happens to run inside - can implement the
same contract later, without this module importing, calling, naming or
assuming anything about it. Nothing here does; a backend is exactly
`ExecutionBackend`'s methods and `describe()`'s claims, never more.

NEUTRAL IDENTITY IS A BACKEND OBLIGATION, not an implementation detail left to
whichever backend ships first (operator rule, skillc is public: no hostnames,
usernames, uids, home paths, IPs or internal URLs in anything committed,
reported or graded). Every backend must:

  - present a fixed, non-host identity inside its isolation: a fixed
    unprivileged user/uid (e.g. `candidate`), a fixed `--hostname`-style
    value, and fixed logical paths (e.g. `/work`, `/home/candidate`) - never
    the host's own;
  - report only those logical values from `describe()`, from anything
    `install()` or `execute()` returns, and from `str(handle)` - a handle
    whose string form embeds a host path, hostname or uid has already leaked
    the thing this rule exists to keep out of a public ledger or receipt;
  - derive a per-attempt name (a container name or equivalent) from the
    attempt ID alone, never from anything host-identifying.
  - The controller does the same on its own side: a host-side location (the
    evidence store, an export destination) is recorded relative or logical,
    never as an absolute host path, in anything that could be committed or
    pasted into a public issue.

WHICH LIFECYCLE STEP OWNS WHICH SIDE (interfaces.md's numbering):

| Step | What it is | Owner |
|---|---|---|
| 1 | Describe supported layouts, clients, limits | `describe()` |
| 2 | Resolve immutable inputs, permitted config | controller (`trial.plan`) |
| 3 | Prepare workspace/home | `prepare()` |
| 4 | Verify native installation, dependency closure | `install()` |
| 5 | Execute the public goal | `execute()` |
| 6 | Stop and CONFIRM no owned process remains | `confirm_stopped()`, never inferred |
| 7 | Capture into controller-owned storage | `export()` hands bytes out; `trial.capture()` freezes and digests them on the CONTROLLER's side, so a backend cannot forge what was frozen |
| 8 | Verify in a fresh environment | a SEPARATE backend instance, through this same seam (below) |
| 9 | Cleanup | `destroy()` + `confirm_absent()`, both idempotent |

Step 8 is not a special case. `skillc/verify.py`'s probe (#9) is planned to run
through its own instance of this same seam (#10's PR2), so the isolation a
backend provides for an agent under test and the isolation it provides for
untrusted candidate code during grading are the same property, established
once rather than twice. PR2 delivers that; this module only makes the seam
capable of it.

THE STRUCTURAL GUARANTEE THIS SEAM EXISTS TO ENFORCE: an unavailable backend is
a refusal, never a reason to run the subject on the host. A caller that cannot
`prepare()` (or whose pre-flight fails) must declare the attempt
`unavailable` through `trial.finalize(experiment, attempt_id,
disposition="unavailable", reason=...)` - see `BackendUnavailable` below - and
must not construct an argv for `subprocess.Popen` as a fallback. There is no
method on this Protocol whose failure mode is "try the host instead."

Stdlib only (AGENTS.md): `typing.Protocol`, nothing about any concrete
backend's transport.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol, runtime_checkable

#: The fixed uid/gid of the trial container's candidate user - the identity
#: `docker_backend` runs every subject as, and `/home/candidate`'s owner.
#: Here, in the dependency-free seam, so `leak` can exempt it (#235) without
#: importing the Docker backend; `docker_backend` re-exports both names.
CANDIDATE_UID = 10001
CANDIDATE_GID = 10001


class BackendUnavailable(Exception):
    """The backend cannot be used right now (no daemon, no credentials, an
    unreachable remote). Always a refusal - see the module docstring. Never
    caught and silently retried as a host execution."""


class Confirmation(Enum):
    """The only three answers `confirm_stopped()`/`confirm_absent()` may give.

    A caller-visible `bool` cannot say "I could not observe" - a backend whose
    daemon died mid-attempt would have to answer either True (a confirmation
    it never made) or False (indistinguishable from "confirmed still there").
    UNKNOWN is a third, real answer, and it is NEVER treated as CONFIRMED: the
    same rule interfaces.md already states for a criterion outcome ("missing
    mandatory evidence prevents PASS") and #39 states for observation
    coverage. A backend that cannot tell must return UNKNOWN, not guess.
    """

    CONFIRMED = "confirmed"
    NOT_CONFIRMED = "not-confirmed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class BackendDescription:
    """`describe()`'s answer: identity and claims for the ledger's installation
    receipt (interfaces.md: "adapter/client versions... readiness evidence"),
    and for a reader deciding how much to trust a result.

    `isolation` and `unobserved` are both required, not just `isolation`: a
    backend that only ever lists what it claims, never what it does not
    establish, reads as stronger than it is - exactly the gap verification.md's
    "Trust assumptions" and "Unobserved properties" sections exist to keep
    visible for the verifier. A backend's own claims deserve the same
    discipline.
    """

    name: str
    version: str
    isolation: tuple[str, ...]  # claims this backend makes, e.g. ("pid-namespace", "no-network")
    unobserved: tuple[str, ...]  # claims it explicitly does NOT make, e.g. ("file-read-monitoring",)


@dataclass(frozen=True)
class ExecuteResult:
    """What `execute()` observed while the subject ran - NEVER a claim that
    nothing of it remains. That is `confirm_stopped()`'s job, asked
    independently, because a launcher exiting (or being killed) proves
    nothing about what it left running inside the backend's isolation.
    Mirrors `trial.run_attempt`'s own stop-record shape, so a caller can carry
    this into `trial.finalize` largely unchanged.

    `signal` names an infrastructure kill EXPLICITLY - never a guessed cause
    (issue #10 addendum item 12: "exit 137 is SIGKILL, not OOM"; three parties
    once relayed "OOM" for a kill a memory check showed was not one). Set it
    from the signal that actually terminated the process (`SIGKILL`,
    `SIGTERM`, ...), never inferred from a raw exit code alone - a backend
    that cannot determine the signal leaves this `None` rather than guess.

    `stdout_bytes` is the bytes the subject wrote to stdout that the backend's
    own drain observed BEFORE it stopped waiting for that drain to finish -
    not a guarantee the pipe reached EOF (a descendant process inheriting the
    fd could in principle keep it open past the parent's own exit; #102 does
    not close that gap, only the unbounded-retention one). Whether or not all
    observed bytes were captured, a backend must keep draining the pipe past
    `Limits.max_captured_stdout_bytes` so the subject can never block on a
    full pipe buffer, so this count can legitimately exceed what was
    retained. `stdout_truncated` is `True` exactly when it does (#102: a
    subject that writes continuously used to grow an unbounded in-memory
    list, a host resource-exhaustion path independent of any container-side
    memory limit). Never a silent cap - a caller reading only the captured
    bytes without checking this flag would otherwise read a partial capture
    as if it were the whole thing.

    `stdout_incomplete`/`stderr_incomplete` are the #102 gap named above,
    made explicit rather than left as prose (issue #133 item 3): `True` when
    the backend stopped WAITING for its drain thread before that thread
    confirmed EOF - a descendant the subject left running, holding the pipe
    open past every kill this backend issued. Independent of `truncated`:
    a drain can reach EOF with room to spare (`incomplete=False`) yet still
    have been capped (`truncated=True`), or time out waiting before the cap
    is ever reached (`incomplete=True`, `truncated=False`). A backend that
    cannot distinguish "read everything, some was discarded" from "gave up
    reading" must never collapse the second into the first by reporting only
    `truncated`.

    `term_forwarding` names what the HOST observed about a container-level
    TERM reaching the subject (issue #158), never what any in-container
    component *reports* about itself - the supervisor and wrapper this
    backend may use both run as the same unprivileged user as the subject
    they describe, so anything they say about themselves is forgeable by
    exactly the code under evaluation (the same class of problem as a
    provenance marker inside an artifact it could also write). Named for
    what was OBSERVED, not what is inferred to have caused it - a subject
    observed to exit promptly may have been finishing anyway, not reacting
    to a forwarded signal, and this field does not claim otherwise:
    - `"unavailable-in-image"`: the capability probe found no forwarding
      support in this container's image; the exec argv was never prefixed.
    - `"not-needed"`: forwarding support was present, but no stop path ran
      at all (the subject exited on its own; nothing was ever sent).
    - `"exited-within-grace"`: forwarding support was present, a
      container-level TERM was sent, and the subject was gone before the
      SIGKILL escalation - the same host-side wait this module already
      performs, not a new observation channel.
    - `"killed-at-escalation"`: forwarding support was present, and the
      subject was still alive when `grace` expired, requiring the SIGKILL
      escalation - covers a forward that never reached the subject, one
      that reached it too late, and one the subject simply ignored; this
      field cannot and does not distinguish those from the host side.
    `None` normally means "this backend does not report forwarding at
    all" - every backend but `DockerBackend` (this field is #158-specific),
    and a caller reading a stored result should read `None` from any of
    them that way: nothing to measure, not merely unmeasured. `DockerBackend`
    itself has exactly one narrow exception, on its `"launch-failed"` path:
    if the capability probe found forwarding present but the exec still
    failed to launch for some OTHER reason, `None` there means genuinely
    UNMEASURED, not inapplicable - `execute()`'s own comment at that return
    states which case applies. Every other `DockerBackend` result -
    including every other `"launch-failed"` one - sets one of the four
    values above; only that one combination leaves it `None`.

    `observations_capture` (issue #186) names whether the exec'd process's
    captured stdout was actually written back into the workspace as
    `observations` (`verify.py`'s own documented convention, #76) - checked,
    never swallowed. `"written"` means the write-back subprocess exited 0;
    `"failed"` means it did not, whatever the cause (a non-zero exit - e.g.
    the subject pre-created `observations` as a directory, which makes the
    tar extraction fail with `IsADirectoryError` - a raised `OSError`, or a
    timeout). `None` means this backend does not report it at all (every
    backend but `DockerBackend`) OR the write-back was never attempted
    because the subject's own process never ran (the `"launch-failed"`
    path, before any capture exists to write back) - `execute()`'s own
    comment at that return states which case applies, mirroring
    `term_forwarding`'s identical `None` convention. `"written"` is NOT a
    claim that the file's CONTENT is correct or complete - `stdout_
    truncated`/`stdout_incomplete` already answer that, orthogonally - only
    that the write-back subprocess itself reported success. A caller must
    treat anything but `"written"` as "no captured observations reached the
    workspace", never assume the file is there and readable."""

    reason: str  # "exited" | "timeout" | "operator-cancelled" | "launch-failed"
    exit_code: int | None
    error: str | None = None
    signal: str | None = None
    stdout_truncated: bool = False
    stdout_bytes: int = 0
    stdout_incomplete: bool = False
    stderr_incomplete: bool = False
    term_forwarding: str | None = None
    observations_capture: str | None = None


@dataclass(frozen=True)
class Limits:
    """Resource bounds `execute()` must enforce inside its own isolation, not
    merely pass through to the subject as advice.

    `max_captured_stdout_bytes`/`max_captured_stderr_bytes` bound how much of
    the subject's stdout/stderr a backend RETAINS in memory while it runs
    (#102: a subject that floods either stream can exhaust the HOST
    controller's own memory, independent of any container-side limit - found
    for stdout first, then for stderr by the same review since it is the
    identical unbounded-list pattern one screen down). Two independent
    fields, not one shared cap: a probe's real report can legitimately be
    large on stdout while its errors stay small on stderr, or the reverse.
    Distinct from `skillc.trial.Limits`, an unrelated dataclass of the same
    name that bounds a DIFFERENT stage (reading an already-captured file back
    off disk during export); the two are not interchangeable and importing
    one to satisfy the other would suggest a shared config surface that does
    not exist. 8 MiB matches that other `Limits`' own `max_stream_bytes`
    default for the same class of bound."""

    timeout: float
    grace: float = 2.0
    max_captured_stdout_bytes: int = 8 * 1024 * 1024
    max_captured_stderr_bytes: int = 8 * 1024 * 1024


@runtime_checkable
class ExecutionBackend(Protocol):
    """One attempt's execution, start to teardown, inside one isolation.

    A handle returned by `prepare()` is opaque to the controller: nothing
    about it is meaningful outside the backend that produced it, and the
    controller stores only what `describe()` and `str(handle)` report. Every
    other method takes that handle and refers to the same attempt.
    """

    def describe(self) -> BackendDescription:
        """Step 1: what this backend is, and what it does and does not
        establish. Called once, before any attempt is prepared."""
        ...

    def prepare(self, attempt_id: str) -> object:
        """Step 3: allocate a workspace/home INSIDE this backend's own
        isolation for `attempt_id` and return an opaque handle. Must raise
        `BackendUnavailable` rather than return a handle for a backend it
        cannot actually use - a handle implies the isolation exists.

        A raising `prepare()` owns cleanup of whatever it already allocated
        before the failure - it must never leave a partial resource (a created
        but unready container, a half-written home) behind on any exception.
        No handle is returned on that path, and `destroy()`/`confirm_absent()`
        both require one; a caller has no other way to reach it. `destroy()`
        after a successful `prepare()` is the only supported cleanup path this
        Protocol provides (issue #10 review: /codex:code_review)."""
        ...

    def install(self, handle: object, surface: Mapping[str, object]) -> dict[str, object]:
        """Step 4: materialize the declared skill surface INSIDE the backend
        and return readiness evidence (interfaces.md's installation-receipt
        fields: selected surface, dependencies, installed paths/digests). The
        skill starts inside the isolation - never staged on the host and
        merely copied in afterward. `surface`'s exact shape is #7's
        materialization contract; this seam only requires that whatever is
        passed here is what actually gets installed, not a host-side proxy
        for it.
        """
        ...

    def execute(
        self, handle: object, argv: Sequence[str], limits: Limits,
        cancel: Callable[[], bool] | None = None, stdin: bytes | None = None,
    ) -> ExecuteResult:
        """Step 5: start the subject's real argv INSIDE the backend and wait,
        subject to `limits.timeout` and `cancel`. The agent under test starts
        inside the isolation - never on the host with the backend only
        watching it.

        `stdin`, when not None, is written to the started process's standard
        input and then closed - the same delivery `subprocess.Popen.communicate`
        gives a bare host process. Added for #10 PR2 (issue #10, mailbox
        coordination): a grading probe's held-out inputs are delivered this
        way today (`skillc/verify.py`'s bare-subprocess path already does,
        via `proc.communicate`), and `lifecycle.py`'s docstring had already
        named this exact gap as expected future work before PR2 hit it - an
        agent's own argv/prompt delivery does not need this, which is why no
        existing caller passes it and every existing call keeps working
        unchanged (default `None`). A backend that cannot honour `stdin` must
        say so through `describe()`'s `unobserved`, never silently drop it."""
        ...

    def exec_in_attempt(
        self, handle: object, argv: Sequence[str], limits: Limits,
        cancel: Callable[[], bool] | None = None, stdin: bytes | None = None,
    ) -> ExecuteResult:
        """Run `argv` inside the SAME running isolation `handle` already
        identifies, WITHOUT stopping or removing it - added for #269's
        gate-execution witness, which needs to exec a declared gate
        (possibly more than once, possibly while the subject's own primary
        `execute()` is still running) against the attempt's live, evolving
        state, never a fresh copy of it and never at the cost of the
        attempt itself. `execute()` cannot be reused for this: it is
        one-shot per handle by its own contract, and always stops the
        isolation before returning (skillc #304 tracks that behavior
        separately; this method does not touch it).

        REFUSED, never folded into a guessed `exited` result, when:
        - the attempt's own primary process is not reachable to exec into
          at all (not started, already stopped, or confirmed absent) -
          `ExecuteResult(reason="attempt-not-running", exit_code=None)`;
        - this backend does not implement this method at all -
          `ExecuteResult(reason="unsupported", exit_code=None)`. A caller
          that receives this must treat the WHOLE mechanism as unavailable
          for this attempt, not merely this one call - `exit_code=None`
          here is never retried as if it might succeed differently next
          time.

        Same `stdin` delivery convention as `execute()`. `limits.timeout`
        bounds only THIS exec call. A backend that cannot isolate a
        same-identity, same-network in-place exec from the attempt's own
        primary process must refuse via `unsupported` rather than attempt
        a weaker approximation silently."""
        ...

    def confirm_stopped(self, handle: object) -> Confirmation:
        """Step 6: ask the BACKEND, independent of `execute()`'s own return,
        whether every process it started for `handle` is gone. The only fact
        a caller may treat as a confirmed stop - never `execute()`'s own
        exit/timeout observation, which cannot see what the isolation hides or
        what outlived its own launcher. (The Docker lane's own history is why
        this is its own method rather than folded into `execute()`: `docker
        run`'s host-side CLI process ending proves nothing about the
        container, which is owned by the daemon, not the CLI's process tree.)

        Returns `Confirmation.UNKNOWN`, never a guessed `NOT_CONFIRMED` or
        `CONFIRMED`, when the backend itself cannot be reached to ask (the
        daemon died mid-attempt, a remote went unreachable). `UNKNOWN` is
        never treated as a confirmed stop by any caller."""
        ...

    def export(self, handle: object, dest: Path) -> None:
        """Step 7 (backend side only): copy `handle`'s output to `dest`, a
        controller-owned directory outside the backend. The CONTROLLER
        re-hashes and freezes what lands here (`trial.capture`); `export`
        itself produces no manifest, digest or verdict, and nothing it claims
        about what it copied is trusted without that freeze.

        May be called more than once per attempt, to different `dest`
        directories, and must not mutate what it reads: the lifecycle driver
        takes a liveness snapshot before `execute()` and compares it against
        the post-execution export (PR1b) - a backend for which `export` has a
        side effect, or that returns something different on a second call
        with nothing having run in between, breaks that comparison."""
        ...

    def destroy(self, handle: object) -> None:
        """Step 9: tear down everything `handle` owns. Safe to call more than
        once, and safe to call after a failed `prepare`/`install`/`execute`."""
        ...

    def confirm_absent(self, handle: object) -> Confirmation:
        """Step 9: ask the BACKEND whether `handle`'s resources are actually
        gone, after `destroy()`. Never trust `destroy()`'s own return value
        alone - `docker rm -f` can report success while the daemon still
        lists the container, so this asks again, independently, exactly as
        `confirm_stopped` never trusts `execute()`.

        Returns `Confirmation.UNKNOWN`, never a guessed answer, when the
        backend cannot be reached to ask - the same rule `confirm_stopped`
        follows, and for the same reason."""
        ...
