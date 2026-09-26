"""The execution backend seam (#10): where a subject actually runs.

interfaces.md's installation and execution lifecycle names nine steps but never
says what performs steps 3 through 7's process side and 9's teardown - only
that they happen "in allocated workspace/home locations" under the evaluator's
control. This module makes that explicit as a stdlib `Protocol`: an
`ExecutionBackend` is the thing that owns a workspace, starts a skill's
installation and the agent under test INSIDE whatever isolation it provides,
and can be asked - independently of what it reported while running - whether
its work actually stopped and whether nothing of it remains.

skillc ships its own Docker-backed implementation
(`skillc/docker_backend.py`), and that backend is a complete, standalone
answer to #10: it needs no other system. The seam exists so ANOTHER backend -
a different isolation technology, or one supplied by a larger system this
skillc instance happens to run inside - can implement the same contract
later, without this module importing, calling, naming or assuming anything
about it. Nothing here does; a backend is exactly `ExecutionBackend`'s six
methods and `describe()`'s claims, never more.

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
from pathlib import Path
from typing import Protocol, runtime_checkable


class BackendUnavailable(Exception):
    """The backend cannot be used right now (no daemon, no credentials, an
    unreachable remote). Always a refusal - see the module docstring. Never
    caught and silently retried as a host execution."""


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
    this into `trial.finalize` largely unchanged."""

    reason: str  # "exited" | "timeout" | "operator-cancelled" | "launch-failed"
    exit_code: int | None
    error: str | None = None


@dataclass(frozen=True)
class Limits:
    """Resource bounds `execute()` must enforce inside its own isolation, not
    merely pass through to the subject as advice."""

    timeout: float
    grace: float = 2.0


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
        cannot actually use - a handle implies the isolation exists."""
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
        cancel: Callable[[], bool] | None = None,
    ) -> ExecuteResult:
        """Step 5: start the subject's real argv INSIDE the backend and wait,
        subject to `limits.timeout` and `cancel`. The agent under test starts
        inside the isolation - never on the host with the backend only
        watching it."""
        ...

    def confirm_stopped(self, handle: object) -> bool:
        """Step 6: ask the BACKEND, independent of `execute()`'s own return,
        whether every process it started for `handle` is gone. The only fact
        a caller may treat as a confirmed stop - never `execute()`'s own
        exit/timeout observation, which cannot see what the isolation hides or
        what outlived its own launcher. (The Docker lane's own history is why
        this is its own method rather than folded into `execute()`: `docker
        run`'s host-side CLI process ending proves nothing about the
        container, which is owned by the daemon, not the CLI's process tree.)
        """
        ...

    def export(self, handle: object, dest: Path) -> None:
        """Step 7 (backend side only): copy `handle`'s output to `dest`, a
        controller-owned directory outside the backend. The CONTROLLER
        re-hashes and freezes what lands here (`trial.capture`); `export`
        itself produces no manifest, digest or verdict, and nothing it claims
        about what it copied is trusted without that freeze."""
        ...

    def destroy(self, handle: object) -> None:
        """Step 9: tear down everything `handle` owns. Safe to call more than
        once, and safe to call after a failed `prepare`/`install`/`execute`."""
        ...

    def confirm_absent(self, handle: object) -> bool:
        """Step 9: ask the BACKEND whether `handle`'s resources are actually
        gone, after `destroy()`. Never trust `destroy()`'s own return value
        alone - `docker rm -f` can report success while the daemon still
        lists the container, so this asks again, independently, exactly as
        `confirm_stopped` never trusts `execute()`."""
        ...
