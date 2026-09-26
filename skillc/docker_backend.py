"""The Docker backend: skillc's own, closing implementation of the execution
backend seam (#77, sub-issue of #10). Nothing here depends on any other
system, and it will drive a subject inside a container via the `docker` CLI
through `subprocess` - stdlib only, no SDK (AGENTS.md).

THIS PR IS THE INTERFACE ONLY (#77, "land its interface first" so #78 and #79
can build against it without waiting on the full implementation): the
`DockerBackend` constructor and config, `describe()`'s claims, the composed
`docker run` argv (`compose_run_argv`, itself a committed control surface -
see its own docstring), and the handle shape. `prepare`, `install`,
`execute`, `confirm_stopped`, `export`, `destroy` and `confirm_absent` are
present with the Protocol's exact signatures - so `isinstance(backend,
ExecutionBackend)` already holds, and callers can already construct and
`describe()` a real `DockerBackend` - but their bodies raise
`NotImplementedError` pending #77's own follow-up implementation PR.

NEUTRAL IDENTITY (interfaces.md "Execution backend" section; operator rule,
skillc is public, #63): a fixed non-root user, a fixed hostname, fixed
logical paths (`/work`, `/home/candidate`), and a container name derived from
the attempt ID alone. `describe()` and the handle report only those logical
values - never a host path, uid or hostname. The user/uid is FIXED
(`CANDIDATE_UID:CANDIDATE_GID`, see that constant's own comment) rather than
matched to the host caller's own uid/gid - an earlier draft did the latter to
solve a real bind-mount permission problem, and that broke this exact
obligation: the container's own `id`, file ownership and transcripts would
have carried the host's real uid/gid, not just `describe()`'s prose (design
correction, orchestrator review of PR #83, 2026-09-26).

RESOURCE LIMITS (addendum item C9): `--memory` and `--memory-swap` are always
equal - leaving `--memory-swap` unset lets the effective bound silently
double. `--pids-limit`, `--cpus` and `--shm-size` are always set; Chromium and
some test runners break on Docker's 64 MiB `/dev/shm` default otherwise. A
disk bound is opt-in (`disk_limit`, `--storage-opt size=`) because that flag
is refused outright by any storage driver other than `overlay2` on a
compatible backing filesystem - see `compose_run_argv`'s own docstring.

SANDBOX CHOICE (addendum item A3): recorded in `describe()` as
`SANDBOX_MODE`, not silently assumed. This image is not known to carry
bubblewrap, so a Codex subject would decline every shell command under
`--sandbox workspace-write` (kyle #1396) - the documented choice here is
UNSANDBOXED, because the container itself is the fence.

OWNERSHIP (issue #77): every container this backend composes carries a fixed
"this belongs to skillc" label plus a per-attempt label; #79's cleanup sweep
filters on the fixed label to find every skillc-owned container without
trusting name matching, so a foreign container sharing a similar name but
carrying neither label is never touched.

NO SOCKET, NO ESCAPE HATCH (addendum item C12): `compose_run_argv` emits a
FIXED, closed set of flags. There is no passthrough parameter for arbitrary
extra `docker run` arguments, so there is no code path through which a
caller could add a socket mount, `--privileged`, or a `docker` binary into
the trial - the guarantee is structural, not a convention nobody happens to
violate yet, exactly as `container_executor`'s own closed schema is
elsewhere in this fleet's ecosystem.

WHAT THIS PR DOES NOT DEMONSTRATE. `compose_run_argv`'s composition and
`describe()`'s claims are proven here; the actual lifecycle (a real `docker
run`, teardown confirmation via `docker inspect`, export, the liveness
canary) is #77's own follow-up implementation PR - see that PR's own
docstring for what remains owed to the live daemon run even after it lands.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .backend import (
    BackendDescription,
    Confirmation,
    ExecuteResult,
    Limits,
)

DAEMON_TIMEOUT = 5.0


#: The candidate user's FIXED, host-independent uid:gid (design correction,
#: orchestrator review of PR #83, 2026-09-26). An earlier draft of this
#: module derived this from `os.getuid()`/`os.getgid()` - the HOST caller's
#: own identity - to solve a real problem (a container started under a
#: different uid cannot write its own bind-mounted directories), but that
#: broke the neutral-identity obligation this seam itself imposes
#: (interfaces.md "Execution backend": "a fixed unprivileged user/uid").
#: `describe()` can hide a number from its own prose, but the CONTAINER
#: cannot: the subject under test runs `id`, lists file ownership and writes
#: transcripts, all of which would carry the host's real uid/gid straight
#: into the trial's own evidence - a leak this module's docstring already
#: claimed did not happen. `#78`'s image must create a `candidate` user at
#: exactly this uid:gid, with `/home/candidate`, `~/.claude` and `~/.codex`
#: already owned by it. DECIDED (not left open): the implementation PR moves
#: data in and out via `docker cp`/a tar stream, never a bind mount matched
#: to this uid - `compose_run_argv` composes no `-v` for the workspace or
#: home at all (see its own docstring). A per-trial host directory chmod'd
#: for this fixed uid was the alternative and was rejected: it is either
#: another uid-matching problem in a different place, or a directory
#: writable beyond what the controller's own process needs.
CANDIDATE_UID = 10001
CANDIDATE_GID = 10001


def _container_user() -> str:
    """The uid:gid the container's candidate user runs as - always
    `CANDIDATE_UID:CANDIDATE_GID`, never the host caller's own uid/gid
    (`os.getuid`/`os.getgid`). See `CANDIDATE_UID`'s own comment for why a
    host-derived value was tried and rejected."""
    return f"{CANDIDATE_UID}:{CANDIDATE_GID}"


#: A neutral HOSTNAME and logical paths - never the host's own (interfaces.md
#: "Execution backend"). `CANDIDATE_USER_NAME` is the identity `#78`'s image
#: must create at `CANDIDATE_UID:CANDIDATE_GID`.
CANDIDATE_USER_NAME = "candidate"
CONTAINER_HOSTNAME = "skillc-trial"
CONTAINER_WORKSPACE = "/work"
CONTAINER_HOME = "/home/candidate"

#: Resource limits (addendum item C9). --memory-swap MUST equal --memory or
#: swap silently doubles the effective bound.
DEFAULT_MEMORY = "1g"
DEFAULT_PIDS_LIMIT = "256"
DEFAULT_CPUS = "1.0"
DEFAULT_SHM_SIZE = "64m"

#: The sandbox decision (addendum item A3), recorded rather than assumed: this
#: image is not known to carry bubblewrap, so Codex would decline every shell
#: command under `--sandbox workspace-write` (kyle #1396). The container is
#: the fence instead.
SANDBOX_MODE = "unsandboxed-container-is-the-fence"

#: Which daemon/context the `docker` CLI talks to - forwarded EXPLICITLY and
#: identically to every invocation the implementation PR makes, never left to
#: each call's own ambient inheritance (a caller with `DOCKER_HOST` set could
#: otherwise have `execute()` target a different daemon than `confirm_stopped`
#: queries). Declared here since it shapes `DockerBackend`'s contract; used by
#: the implementation PR's own helpers.
DOCKER_CONNECTION_VARS = ("DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG", "DOCKER_CERT_PATH", "DOCKER_TLS_VERIFY")


def _docker_env() -> dict[str, str]:
    """A consistent environment for every docker CLI call this backend
    makes - never each call inheriting the ambient environment
    independently. Used by `describe()`'s own daemon probe here; the
    implementation PR uses it for every other docker invocation too."""
    env = {"PATH": os.environ.get("PATH", os.defpath)}
    for name in DOCKER_CONNECTION_VARS:
        value = os.environ.get(name)
        if value is not None:
            env[name] = value
    return env


def probe_daemon(
    docker_bin: Sequence[str], timeout: float = DAEMON_TIMEOUT, env: Mapping[str, str] | None = None,
) -> str | None:
    """The daemon's server version, or None when it cannot be reached. Never
    raises for "not found" or "unreachable" - a caller must turn either into
    a refusal, never a host-side fallback. `env=None` inherits the caller's
    own environment (the default, for standalone use); `DockerBackend`
    always passes `_docker_env()` explicitly."""
    try:
        proc = subprocess.run(
            [*docker_bin, "version", "--format", "{{.Server.Version}}"],
            capture_output=True, timeout=timeout, text=True, check=False, env=env,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def _env_args(env: Mapping[str, str]) -> list[str]:
    """`-e NAME=value`, always, never the bare `-e NAME` form, which copies
    the LAUNCHING process's own value into the container - the obvious way a
    declared allowlist leaks a host credential."""
    args: list[str] = []
    for key, value in env.items():
        if not isinstance(value, str):
            raise TypeError(
                f"docker backend refuses env {key!r}: an explicit string value is "
                f"required. A bare '-e {key}' would copy the launching process's "
                f"OWN value of {key!r} into the container"
            )
        args += ["-e", f"{key}={value}"]
    return args


#: The managed-ownership label every container this backend starts carries,
#: regardless of attempt (#77: "every container carries per-trial ...
#: labels"). A cleanup sweep (#79) filters on THIS label to find every
#: skillc-owned container without trusting name matching alone - a foreign
#: container that happens to share a similar name carries no such label and
#: is never touched.
OWNER_LABEL_KEY = "skillc.managed"
OWNER_LABEL_VALUE = "true"

#: The per-attempt label key; its value is the same attempt id already
#: embedded in the container's name; a label is still required because a
#: name is not something `docker ps --filter` can query except by substring.
ATTEMPT_LABEL_KEY = "skillc.attempt-id"


def compose_run_argv(
    docker_bin: Sequence[str],
    image: str,
    name: str,
    attempt_id: str,
    subject_argv: Sequence[str],
    env: Mapping[str, str],
    network: str,
    memory: str,
    pids_limit: str,
    cpus: str,
    shm_size: str,
    container_user: str,
    disk_limit: str | None,
) -> list[str]:
    """The full `docker run` argv. Pure - makes no call, mutates nothing. A
    FIXED, closed set of flags: there is no passthrough for arbitrary extra
    arguments, so nothing here can ever mount the docker socket, add
    `--privileged`, or otherwise widen the container (addendum item C12).

    NO BIND MOUNT for the workspace or home (design decision, orchestrator
    review of PR #83, 2026-09-26, choosing the "preferred" option over
    a per-trial directory chmod'd for the fixed candidate uid): a bind mount
    matched to `CANDIDATE_UID` would need a HOST directory the controller
    made writable for that exact uid, which is either another uid-matching
    problem in a different place or a directory writable beyond the
    controller's own process - and it is unnecessary, because `docker cp` (or
    an equivalent tar stream) moves the declared surface in and the exported
    output out without either container or host ever needing matching
    ownership. `-w CONTAINER_WORKSPACE` still sets the working directory -
    Docker creates it inside the container's own writable layer if the image
    does not already have it - and the implementation PR's `install()`/
    `export()` are the `docker cp` callers on either side of `execute()`.

    `-i` is always present so a caller MAY later deliver `execute(...,
    stdin=...)` (the implementation PR) - without it, `docker run` never
    attaches the client's stdin to the container at all. An attempt that
    never uses stdin sees no difference: an unread, empty stdin is not a
    hang, just an immediate EOF if the subject ever reads it.

    `disk_limit`, when given, becomes `--storage-opt size=<disk_limit>` -
    honoured only by the `overlay2` storage driver on an `xfs`/compatible
    backing filesystem; on any other host Docker refuses the flag outright.
    `None` (the default) omits it entirely rather than pass a flag most hosts
    reject, and `describe()`'s `unobserved` says so - a caller that needs a
    guaranteed disk bound must not assume this flag alone provides one.

    A literal `--` always separates the options above from `image` and
    `subject_argv` (found by cross-model review): without it, an `image`
    value that itself looks like a flag - `"--privileged"`, say - is not
    guaranteed to be consumed as the positional IMAGE argument by Docker's
    flag parser, which keeps scanning for recognized flags throughout the
    argument list rather than stopping at the first positional. `--` is
    Docker's own documented end-of-options marker, so this closes that gap
    without depending on Docker's flag-parsing behavior in the general
    case."""
    argv = [
        *docker_bin, "run", "--rm", "-i", "--name", name,
        "--label", f"{OWNER_LABEL_KEY}={OWNER_LABEL_VALUE}",
        "--label", f"{ATTEMPT_LABEL_KEY}={attempt_id}",
        "--network", network,
        "--user", container_user,
        "--hostname", CONTAINER_HOSTNAME,
        "--init",
        "--memory", memory, "--memory-swap", memory,
        "--pids-limit", pids_limit,
        "--cpus", cpus,
        "--shm-size", shm_size,
    ]
    if disk_limit is not None:
        argv += ["--storage-opt", f"size={disk_limit}"]
    argv += [
        "-w", CONTAINER_WORKSPACE,
        "-e", f"HOME={CONTAINER_HOME}",
        *_env_args(env),
        "--", image, *subject_argv,
    ]
    return argv


@dataclass
class _Handle:
    attempt_id: str
    name: str
    work_dir: Path
    home_dir: Path
    proc: subprocess.Popen[bytes] | None = None


@dataclass(frozen=True)
class DockerBackend:
    """One `ExecutionBackend` per attempt lifecycle. `image` should be pinned
    by digest where possible (`name@sha256:...`); the implementation PR
    resolves and records the digest that actually ran regardless (D13/D14).

    Every method below beyond `describe()` raises `NotImplementedError`
    pending #77's follow-up implementation PR - this PR lands the
    constructor/config, `describe()`'s claims, `compose_run_argv`'s
    committed argv shape, and the handle shape only, so #78 and #79 can
    build against a stable surface without waiting on the full lifecycle."""

    image: str
    base_dir: Path
    docker_bin: Sequence[str] = ("docker",)
    network: str = "none"
    memory: str = DEFAULT_MEMORY
    pids_limit: str = DEFAULT_PIDS_LIMIT
    cpus: str = DEFAULT_CPUS
    shm_size: str = DEFAULT_SHM_SIZE
    #: `--storage-opt size=<disk_limit>` when set - see `compose_run_argv`'s
    #: own docstring for why this is opt-in, not a default: the flag is
    #: refused outright on any host whose storage driver does not support it.
    disk_limit: str | None = None
    env: Mapping[str, str] = field(default_factory=dict)
    daemon_timeout: float = DAEMON_TIMEOUT

    def describe(self) -> BackendDescription:
        version = probe_daemon(self.docker_bin, self.daemon_timeout, _docker_env())
        return BackendDescription(
            name="docker",
            version=version or "unreachable",
            isolation=(
                "container (pid/mount/network namespaces)",
                f"network={self.network} by default",
                f"fixed non-root user {_container_user()} ({CANDIDATE_USER_NAME}), independent of the host caller",
                "resource limits enforced: memory, memory-swap (equal), pids, cpus, shm-size",
                (f"disk: --storage-opt size={self.disk_limit}" if self.disk_limit is not None
                 else "disk: no per-container bound set (disk_limit is None)"),
                f"every container labeled {OWNER_LABEL_KEY}={OWNER_LABEL_VALUE} and {ATTEMPT_LABEL_KEY}=<attempt id>",
                f"sandbox: {SANDBOX_MODE}",
                "no docker socket, no docker binary, no passthrough flags in the composed argv",
            ),
            unobserved=(
                ("the full lifecycle (prepare/install/execute/confirm_stopped/export/"
                 "destroy/confirm_absent) - this PR is #77's interface only; every "
                 "method beyond describe() raises NotImplementedError pending the "
                 "follow-up implementation PR"),
                "network egress actually blocked - not verified from inside the container",
                "file reads by candidate code",
                ("credential confidentiality against an ancestor's /proc/<pid>/environ - "
                 "the verifier's own boundary (verify.py's probe through this same seam)"),
                "the live daemon boundary itself, owed to the operator's live run (#10)",
                ("a disk bound actually enforced - --storage-opt size= is refused outright "
                 "by any storage driver other than overlay2 on a compatible backing "
                 "filesystem, so a set disk_limit is a request, not a guarantee"),
            ),
        )

    def prepare(self, attempt_id: str) -> object:
        raise NotImplementedError("#77 implementation PR: DockerBackend.prepare()")

    def install(self, handle: object, surface: Mapping[str, object]) -> dict[str, object]:
        raise NotImplementedError("#77 implementation PR: DockerBackend.install()")

    def execute(
        self, handle: object, argv: Sequence[str], limits: Limits,
        cancel: Callable[[], bool] | None = None, stdin: bytes | None = None,
    ) -> ExecuteResult:
        raise NotImplementedError("#77 implementation PR: DockerBackend.execute()")

    def confirm_stopped(self, handle: object) -> Confirmation:
        raise NotImplementedError("#77 implementation PR: DockerBackend.confirm_stopped()")

    def export(self, handle: object, dest: Path) -> None:
        raise NotImplementedError("#77 implementation PR: DockerBackend.export()")

    def destroy(self, handle: object) -> None:
        raise NotImplementedError("#77 implementation PR: DockerBackend.destroy()")

    def confirm_absent(self, handle: object) -> Confirmation:
        raise NotImplementedError("#77 implementation PR: DockerBackend.confirm_absent()")
