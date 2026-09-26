"""The Docker backend: skillc's own, closing implementation of the execution
backend seam (#77, sub-issue of #10). Nothing here depends on any other
system, and it drives a subject inside a container via the `docker` CLI
through `subprocess` - stdlib only, no SDK (AGENTS.md).

THIS PR IS #77's IMPLEMENTATION (the interface landed first in PR #83, so #78
and #79 could build against a stable surface without waiting on this): real
bodies for `prepare`, `install`, `execute`, `confirm_stopped`, `export`,
`destroy` and `confirm_absent`, on top of the constructor/config,
`describe()`'s claims, `compose_run_argv` and the ownership labels PR #83
already merged - none of that interface surface changes here.

ONE PERSISTENT CONTAINER PER ATTEMPT, ACTED ON THROUGH `docker cp`/`docker
exec` - NEVER a bind mount, and never a second container or a shared volume
(orchestrator direction, PR #83 review, 2026-09-26). `execute()`'s real argv
is not known until it is called, so the container cannot be created with the
subject's command baked in the way `compose_run_argv` composes it for a
one-shot `docker run`: `prepare()` instead starts the SAME composed argv with
a placeholder keep-alive command (`sleep infinity`) via `docker run -d`, and
`install()`/`execute()` act on that one running container afterward via
`docker cp` and `docker exec`. `--rm` is dropped from the composed argv for
this call specifically: this container's teardown is owned explicitly by
`destroy()`/`confirm_absent()` below, and Docker's own auto-removal on exit
would otherwise race `export()` after a forced `docker kill` (see `execute()`
and `_stop()`).

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
"this belongs to skillc" label plus a per-attempt label; `skillc/reap.py`'s
cleanup sweep (#79) filters on the fixed label to find every skillc-owned
container without trusting name matching, so a foreign container sharing a
similar name but carrying neither label is never touched. See
docs/specs/evaluation-facility/failure-matrix.md for the full failure-path
matrix and the reaping/snapshot contract.

NO SOCKET, NO ESCAPE HATCH (addendum item C12): `compose_run_argv` emits a
FIXED, closed set of flags. There is no passthrough parameter for arbitrary
extra `docker run` arguments, so there is no code path through which a
caller could add a socket mount, `--privileged`, or a `docker` binary into
the trial - the guarantee is structural, not a convention nobody happens to
violate yet, exactly as `container_executor`'s own closed schema is
elsewhere in this fleet's ecosystem.

UNKNOWN NEVER REAPS. `confirm_stopped()`/`confirm_absent()` return
`Confirmation.UNKNOWN` whenever the daemon cannot be asked at all (a timeout,
an unreachable daemon) - never a guessed `CONFIRMED` or `NOT_CONFIRMED`. A
"no such object" answer from a reachable daemon is a *positive* fact (the
container is definitely gone) and is reported as `CONFIRMED`, never confused
with the unreachable case.

WHAT THIS PR DOES NOT DEMONSTRATE. `execute()` stops a runaway subject by
killing the whole per-attempt container (`docker kill`) - and that reaches
the CONTAINER's own init/placeholder process, not a separately exec'd
subject: a real daemon does not forward a container-level signal to an exec
session the way `docker run --sig-proxy` forwards to its own foreground
process (cross-model review, PR #85, sharpening an earlier, vaguer claim
here). So `limits.grace`'s `SIGTERM`-then-`SIGKILL` escalation cannot promise
the SUBJECT itself gets a graceful signal - only that the whole attempt
stops within grace of the second kill. A true per-subject graceful signal
needs an in-container supervisor this backend does not provide; routed to
the Nit Store (#20) as a supplemental finding rather than built here.
`install()` materializes a declared surface entry only when its value names
an existing host path, and reports `discovery_canary`/`installed` from what
was ACTUALLY copied, never merely what was declared; a richer surface
contract (dependency resolution inside the container) is future work. Fake
`docker` CLI only in this test suite (`tests/fixtures/docker-backend/
fake_docker.py`) - this proves the LIFECYCLE state machine and the composed
argv, never a real containment boundary; that remains owed to the operator's
live run (#10). See `describe()`'s own `unobserved` claims for the rest.
"""

from __future__ import annotations

import io
import os
import re
import subprocess
import tarfile
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .backend import (
    BackendDescription,
    BackendUnavailable,
    Confirmation,
    ExecuteResult,
    Limits,
)
from .lifecycle import CANARY_NONCE_KEY

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
#: already owned by it. DECIDED (not left open): data moves in and out via
#: `docker cp` (never a bind mount matched to this uid) - `compose_run_argv`
#: composes no `-v` for the workspace or home at all (see its own docstring).
#: A per-trial host directory chmod'd for this fixed uid was the alternative
#: and was rejected: it is either another uid-matching problem in a
#: different place, or a directory writable beyond what the controller's own
#: process needs.
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
#: identically to every invocation this backend makes, never left to each
#: call's own ambient inheritance (a caller with `DOCKER_HOST` set could
#: otherwise have `execute()` target a different daemon than
#: `confirm_stopped` queries).
DOCKER_CONNECTION_VARS = ("DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG", "DOCKER_CERT_PATH", "DOCKER_TLS_VERIFY")


def _docker_env() -> dict[str, str]:
    """A consistent environment for every docker CLI call this backend
    makes - never each call inheriting the ambient environment
    independently."""
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
    does not already have it - and `install()`/`export()` are the `docker cp`
    callers on either side of `execute()`.

    `-i` is always present so a caller MAY later deliver `execute(...,
    stdin=...)` - without it, `docker run` never attaches the client's stdin
    to the container at all. An attempt that never uses stdin sees no
    difference: an unread, empty stdin is not a hang, just an immediate EOF
    if the subject ever reads it. (`prepare()` starts this container as a
    keep-alive placeholder rather than the real subject - see the module
    docstring - so the real per-call stdin delivery `execute()` needs is its
    own separate `docker exec -i`, not this flag; it stays here because
    `compose_run_argv` is the one composed shape both a one-shot caller and
    this backend's own keep-alive use share.)

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


#: `prepare()`'s placeholder main command: never the real subject. The real
#: argv is not known until `execute()` is called, so the container is
#: started keeping itself alive, and `install()`/`execute()` act on it
#: afterward through `docker cp`/`docker exec` (see the module docstring).
_KEEPALIVE_ARGV: tuple[str, ...] = ("sleep", "infinity")

#: The canary files' names, relative to `CONTAINER_WORKSPACE` inside the
#: container - matching `tests/fixtures/backend-lifecycle/fake_client.py`'s
#: own convention exactly, since a real subject built the same way would
#: look for its input/output at these same relative paths.
CANARY_HOST_FILENAME = ".skillc-canary"
CANARY_RESULT_FILENAME = ".skillc-canary-result"

_NAME_UNSAFE = re.compile(r"[^a-zA-Z0-9_.-]")


def _container_name(attempt_id: str) -> str:
    """A container name derived from the attempt ID alone (interfaces.md's
    neutral-identity rule: "derive a per-attempt name ... never from
    anything host-identifying"), sanitized to Docker's own name character
    set (`[a-zA-Z0-9][a-zA-Z0-9_.-]*`)."""
    safe = _NAME_UNSAFE.sub("-", attempt_id)
    return f"skillc-{safe}"[:128]


def _as_existing_path(value: object) -> Path | None:
    """`surface`'s exact shape is out of this seam's scope
    (`backend.ExecutionBackend.install`'s own docstring: "this seam only
    requires that whatever is passed here is what actually gets installed").
    This backend materializes any declared entry whose value names an
    existing host path (`str` or `Path`) by copying it in via `docker cp`;
    any other value is still counted in `declared`, just not copied - a
    future caller with a richer surface contract can extend this without
    changing the Protocol."""
    if isinstance(value, Path):
        return value if value.exists() else None
    if isinstance(value, str):
        candidate = Path(value)
        return candidate if candidate.exists() else None
    return None


def _owned_tarinfo(info: tarfile.TarInfo) -> tarfile.TarInfo:
    """Every tar member `install()` sends into a container is rewritten to
    the fixed candidate identity - never the host's own uid/gid, which is
    whatever happened to create the surface file on the controller's side
    (cross-model review, PR #85: a plain `docker cp` preserves the SOURCE's
    ownership verbatim, so a mode-0600 file copied in under a different uid
    would be unreadable to `candidate` after a fully "successful" install)."""
    info.uid = CANDIDATE_UID
    info.gid = CANDIDATE_GID
    info.uname = CANDIDATE_USER_NAME
    info.gname = CANDIDATE_USER_NAME
    return info


def _owned_tar(host_path: Path, arcname: str) -> bytes:
    """A tar stream of `host_path` (file or directory, recursively), every
    member owned by the fixed candidate identity - for `docker cp -
    NAME:DEST`, which extracts it there. See `_owned_tarinfo`."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        tar.add(host_path, arcname=arcname, filter=_owned_tarinfo)
    return buf.getvalue()


def _owned_tar_bytes(arcname: str, data: bytes, mode: int = 0o644) -> bytes:
    """Like `_owned_tar`, for in-memory bytes with no host file backing them
    (the liveness canary, and #98's subscription credential) - never staged
    to a temp file first. `mode` defaults to the liveness canary's own
    0o644; #98's credential delivery passes 0o600 explicitly, since a
    world/group-readable credential file would defeat the point of a fixed,
    single-user candidate identity."""
    buf = io.BytesIO()
    info = tarfile.TarInfo(name=arcname)
    info.size = len(data)
    info.mode = mode
    info = _owned_tarinfo(info)
    with tarfile.open(fileobj=buf, mode="w") as tar:
        tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


@dataclass(frozen=True)
class _Handle:
    """Opaque to the controller (backend.py's own rule): `attempt_id` and
    `name` are both derived from the attempt ID alone, so `str(handle)`
    (the dataclass default) never leaks a host path, uid or hostname. No
    `work_dir`/`home_dir` fields - there is no host-side directory backing
    this attempt at all, since data moves by `docker cp`, never a bind
    mount.

    `env` is the exact environment `prepare()` resolved and used to start
    THIS attempt's container, captured once and reused by every later call
    (`install`/`execute`/`confirm_stopped`/`export`/`destroy`/
    `confirm_absent`) instead of each one re-reading `os.environ` on its own
    (cross-model review, PR #85: an ambient `DOCKER_HOST`/`DOCKER_CONTEXT`
    change mid-attempt could otherwise point later calls at a DIFFERENT
    daemon than the one that actually holds this container - a stale
    connection's "no such object" would then read as a false CONFIRMED
    absence, and a same-named container on the NEW daemon could be killed or
    removed by mistake). `repr=False`: printing a handle must never leak a
    connection string that could itself be host-identifying (a local socket
    path, a remote host/port) - the same neutral-identity rule `str(handle)`
    already has to honor for uid/hostname/paths."""

    attempt_id: str
    name: str
    env: Mapping[str, str] = field(repr=False)


@dataclass(frozen=True)
class DockerBackend:
    """One `ExecutionBackend` per attempt lifecycle. `image` should be pinned
    by digest where possible (`name@sha256:...`); resolving and recording the
    digest that actually ran (D13/D14) is tracked separately, not this PR."""

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
                ("one persistent container per attempt (docker run -d at prepare()); "
                 "install()/execute() act on it via docker cp/docker exec - no bind mount, "
                 "no shared volume, no second container"),
            ),
            unobserved=(
                "network egress actually blocked - not verified from inside the container",
                "file reads by candidate code",
                ("credential confidentiality against an ancestor's /proc/<pid>/environ - "
                 "the verifier's own boundary (verify.py's probe through this same seam)"),
                ("the live daemon boundary itself - tested here only against a fake docker "
                 "CLI (tests/fixtures/docker-backend/fake_docker.py), never a real daemon; "
                 "that remains owed to the operator's live run (#10)"),
                ("a disk bound actually enforced - --storage-opt size= is refused outright "
                 "by any storage driver other than overlay2 on a compatible backing "
                 "filesystem, so a set disk_limit is a request, not a guarantee"),
                ("a graceful signal delivered to the exec'd subject itself on timeout or "
                 "cancellation - docker kill reaches this attempt's CONTAINER (its own "
                 "init/placeholder process), never a separately exec'd session, so the "
                 "SIGTERM-then-SIGKILL escalation only bounds when the whole attempt stops, "
                 "not whether the subject itself got a chance to flush anything"),
                ("dependency resolution inside the container - install() copies in any "
                 "declared surface entry naming an existing host path or carrying raw "
                 "bytes; it does not run a package manager or resolve a dependency closure"),
                ("baseline_absence - always reported SATISFIED without checking the "
                 "image's own contents for an undeclared skill already present, matching "
                 "the reference FakeBackend's own scope (tests/test_lifecycle.py)"),
            ),
        )

    def _keepalive_run_argv(self, name: str, attempt_id: str) -> list[str]:
        """`prepare()`'s `docker run -d` argv: `compose_run_argv`'s own
        composed flags (identity, network, resource limits, ownership
        labels), with the placeholder `_KEEPALIVE_ARGV` in place of a real
        subject, detached (`-d`), and with `--rm` removed - this container's
        teardown is owned explicitly by `destroy()`/`confirm_absent()`, and
        Docker's own auto-removal on exit would otherwise race `export()`
        after a forced `docker kill` (see `execute()`/`_stop()`)."""
        argv = compose_run_argv(
            docker_bin=self.docker_bin, image=self.image, name=name, attempt_id=attempt_id,
            subject_argv=_KEEPALIVE_ARGV, env=self.env, network=self.network, memory=self.memory,
            pids_limit=self.pids_limit, cpus=self.cpus, shm_size=self.shm_size,
            container_user=_container_user(), disk_limit=self.disk_limit,
        )
        argv.insert(argv.index("run") + 1, "-d")
        argv.remove("--rm")
        return argv

    def prepare(self, attempt_id: str) -> object:
        """Step 3: start this attempt's one persistent container, detached,
        running the keep-alive placeholder. Raises `BackendUnavailable` -
        never returns a handle - when the daemon is unreachable or the
        `docker run` itself fails.

        Docker creates a container before it starts it, so a failed START
        (an image missing the placeholder binary, say) can still leave one
        behind - and `--rm` cannot save us here, since `_keepalive_run_argv`
        deliberately drops it (see that method's own docstring). A raising
        `prepare()` must not leave a partial resource behind
        (`backend.ExecutionBackend.prepare`'s own stated contract) - found by
        cross-model review, which named the pre-fix code an actual violation
        of that already-merged contract, not merely a hardening opportunity."""
        env = _docker_env()
        if probe_daemon(self.docker_bin, self.daemon_timeout, env) is None:
            raise BackendUnavailable(f"docker daemon unreachable via {' '.join(self.docker_bin)!r}")
        name = _container_name(attempt_id)
        argv = self._keepalive_run_argv(name, attempt_id)
        try:
            started = subprocess.run(argv, capture_output=True, text=True, env=env, check=False)
        except OSError as exc:
            raise BackendUnavailable(
                f"docker run failed to start a container for {attempt_id!r}: {exc}"
            ) from exc
        if started.returncode != 0:
            # Best-effort: whether or not a container was actually created,
            # this makes sure none is left behind under this name.
            subprocess.run(
                [*self.docker_bin, "rm", "-f", name], capture_output=True, env=env, check=False,
            )
            raise BackendUnavailable(
                f"docker run failed to start a container for {attempt_id!r}: {started.stderr.strip()}"
            )
        return _Handle(attempt_id=attempt_id, name=name, env=env)

    def install(self, handle: object, surface: Mapping[str, object]) -> dict[str, object]:
        """Step 4: copy every declared surface entry into the running
        container - a host path (`str`/`Path`, materialize.py's own
        skill-installation convention) or raw `bytes` (verify.py's own
        probe-surface convention, #76: `_probe_via_backend`'s `{relative
        path: bytes}` shape, discovered NOT to work at all against this
        backend until #81's demo command actually exercised the combination
        - every file silently failed to install, since `_as_existing_path`
        correctly returns `None` for bytes and the pre-fix loop just skipped
        it, no error, no readiness signal) - plants the liveness canary
        (`lifecycle.CANARY_NONCE_KEY`) the same way when present, and
        reports readiness evidence. Raises `BackendUnavailable` if a
        declared copy fails - a materialization failure makes this
        attempt's backend unusable, exactly like an unreachable daemon.
        Any OTHER value type (for example verify.py's own
        `SURFACE_EXECUTABLE_KEY` metadata list) is silently not copied, same
        as always - it is still counted in `declared`, just not installed.

        Copied as a TAR STREAM this method builds itself (`_owned_tar`/
        `_owned_tar_bytes`), piped into `docker cp - NAME:DEST`, never a
        plain `docker cp HOST_PATH NAME:DEST` (cross-model review, PR #85):
        a real `docker cp` preserves
        the SOURCE's own uid/gid in the copied tar, which is whatever the
        CONTROLLER's host process happens to own - not `CANDIDATE_UID`. A
        mode-0600 declared file, or a mode-0700 declared directory, would
        install successfully and then be unreadable to the very identity
        meant to use it. Building the tar ourselves lets every entry's
        ownership be set to the fixed candidate identity regardless of what
        the host file is actually owned by."""
        assert isinstance(handle, _Handle)
        nonce = surface.get(CANARY_NONCE_KEY)
        declared = {k: v for k, v in surface.items() if k != CANARY_NONCE_KEY}

        installed = 0
        for key, value in declared.items():
            if isinstance(value, bytes):
                # Raw in-memory content, no host file backing it - the
                # convention `verify.py`'s own probe surface uses (#76,
                # #81's demo command: grading through this same backend
                # seam silently installed NOTHING before this fix, since
                # every declared file there is bytes, never a host path -
                # `_as_existing_path` correctly returned None for all of
                # them, and the pre-fix loop just skipped them without
                # error, so the probe failed with "no such file" the first
                # time this combination was actually exercised).
                payload = _owned_tar_bytes(key, value)
            else:
                host_path = _as_existing_path(value)
                if host_path is None:
                    continue
                payload = _owned_tar(host_path, key)
            try:
                copied = subprocess.run(
                    [*self.docker_bin, "cp", "-", f"{handle.name}:{CONTAINER_WORKSPACE}"],
                    input=payload, capture_output=True, env=handle.env, check=False,
                    timeout=self.daemon_timeout,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise BackendUnavailable(f"docker cp failed installing {key!r}: {exc}") from exc
            if copied.returncode != 0:
                raise BackendUnavailable(
                    f"docker cp failed installing {key!r} for {handle.attempt_id!r}: "
                    f"{copied.stderr.decode('utf-8', errors='replace').strip()}"
                )
            installed += 1

        # `discovery_canary`/`installed` reflect what was actually copied,
        # never merely what was declared (cross-model review, PR #85): a
        # surface entry naming a missing path, or a non-path value, must not
        # certify readiness for something that was never materialized.
        readiness: dict[str, object] = {
            "discovery_canary": "SATISFIED" if installed else "VIOLATED",
            # Never independently verified - always reported SATISFIED,
            # matching the reference FakeBackend's own scope
            # (tests/test_lifecycle.py). See describe()'s `unobserved`.
            "baseline_absence": "SATISFIED",
            "declared": len(declared),
            "installed": installed,
        }
        if isinstance(nonce, str) and nonce:
            payload = _owned_tar_bytes(CANARY_HOST_FILENAME, nonce.encode("utf-8"))
            canary_copied: subprocess.CompletedProcess[bytes] | None
            try:
                canary_copied = subprocess.run(
                    [*self.docker_bin, "cp", "-", f"{handle.name}:{CONTAINER_WORKSPACE}"],
                    input=payload, capture_output=True, env=handle.env, check=False,
                    timeout=self.daemon_timeout,
                )
            except (OSError, subprocess.TimeoutExpired):
                canary_copied = None
            # A failed canary plant is not fatal to install() itself - the
            # driver's weaker content-diff fallback still applies whenever
            # canary_path is absent (lifecycle.py's own documented fallback).
            if canary_copied is not None and canary_copied.returncode == 0:
                readiness["canary_path"] = CANARY_RESULT_FILENAME
        return readiness

    def deliver_home_file(self, handle: object, container_relpath: str, data: bytes, *, mode: int = 0o600) -> None:
        """Copy `data` into the container's HOME directory at
        `container_relpath` (relative to `CONTAINER_HOME`, e.g.
        `.claude/.credentials.json`) - the same candidate-owned tar-stream
        mechanism `install()` uses for `CONTAINER_WORKSPACE`, aimed at
        `CONTAINER_HOME` instead (#98: the operator's subscription
        credential belongs in the candidate's home, where each client's own
        standard location expects to find it, never in `/work`).

        NOT part of the `ExecutionBackend` Protocol (`backend.py`) - this is
        Docker-specific for now, until a second backend needs the same
        capability and this generalizes into the seam itself. Never a bind
        mount, never baked into the image, never in argv - the same three
        guarantees `install()` already gives, extended to a destination
        `install()` itself does not reach.

        A direct structural consequence, not merely a policy: `export()`
        only ever reads from `CONTAINER_WORKSPACE` (see its own
        implementation), so the bytes delivered HERE, at this exact
        location, can NEVER appear in an exported workspace by way of
        `export()` itself - not because of a check, but because export()
        never looks in `CONTAINER_HOME` at all. This is a narrower
        guarantee than "the credential can never leak into an export": a
        running candidate process can still read its own home directory and
        write those same bytes into `CONTAINER_WORKSPACE` on purpose or by
        accident (cross-model review, #98) - `deliver_home_file`/`export()`
        do not and cannot prevent that, which is exactly why `skillc/leak.py`
        scans exported content for credential material independently rather
        than relying on this placement alone.

        `.claude` and `.codex` already exist under `CONTAINER_HOME`, owned
        by the candidate identity (#78's image build) - this method never
        creates a directory itself, only a leaf file inside one that must
        already exist.
        """
        assert isinstance(handle, _Handle)
        payload = _owned_tar_bytes(container_relpath, data, mode=mode)
        try:
            copied = subprocess.run(
                [*self.docker_bin, "cp", "-", f"{handle.name}:{CONTAINER_HOME}"],
                input=payload, capture_output=True, env=handle.env, check=False,
                timeout=self.daemon_timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise BackendUnavailable(
                f"docker cp failed delivering {container_relpath!r} to home for {handle.attempt_id!r}: {exc}"
            ) from exc
        if copied.returncode != 0:
            raise BackendUnavailable(
                f"docker cp failed delivering {container_relpath!r} to home for {handle.attempt_id!r}: "
                f"{copied.stderr.decode('utf-8', errors='replace').strip()}"
            )

    def read_home_file(self, handle: object, container_relpath: str) -> bytes:
        """Read back the current bytes at `container_relpath` (relative to
        `CONTAINER_HOME`) - the read-side counterpart to `deliver_home_file`,
        for exactly one purpose (#98): letting a caller compare a delivered
        credential's bytes against its current in-container bytes to observe
        whether an in-container refresh happened, before `destroy()` discards
        the container and that fact along with it.

        `docker cp NAME:PATH -` streams a tar archive to stdout even for a
        single file, so this reads that stream back with `tarfile` rather
        than treating stdout as the raw file content. Raises
        `BackendUnavailable` on any failure - an unreadable container is the
        same class of fact as an unreachable daemon, not a signal about the
        credential itself.
        """
        assert isinstance(handle, _Handle)
        try:
            result = subprocess.run(
                [*self.docker_bin, "cp", f"{handle.name}:{CONTAINER_HOME}/{container_relpath}", "-"],
                capture_output=True, env=handle.env, check=False, timeout=self.daemon_timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise BackendUnavailable(
                f"docker cp failed reading {container_relpath!r} from home for {handle.attempt_id!r}: {exc}"
            ) from exc
        if result.returncode != 0:
            raise BackendUnavailable(
                f"docker cp failed reading {container_relpath!r} from home for {handle.attempt_id!r}: "
                f"{result.stderr.decode('utf-8', errors='replace').strip()}"
            )
        with tarfile.open(fileobj=io.BytesIO(result.stdout), mode="r:*") as tar:
            members = tar.getmembers()
            if not members:
                raise BackendUnavailable(
                    f"docker cp for {container_relpath!r} returned an empty archive for {handle.attempt_id!r}"
                )
            extracted = tar.extractfile(members[0])
            if extracted is None:
                raise BackendUnavailable(
                    f"docker cp for {container_relpath!r} returned a non-regular-file entry for {handle.attempt_id!r}"
                )
            return extracted.read()

    def execute(
        self, handle: object, argv: Sequence[str], limits: Limits,
        cancel: Callable[[], bool] | None = None, stdin: bytes | None = None,
    ) -> ExecuteResult:
        """Step 5: run `argv` inside the already-running container via
        `docker exec -w CONTAINER_WORKSPACE`, honoring `limits.timeout` and
        `cancel`. `stdin`, when given, is written and closed exactly like
        `subprocess.Popen.communicate` gives a bare host process (`-i` is
        added to the exec only when `stdin is not None`).

        Intended to be called ONCE per handle, mirroring interfaces.md's
        per-attempt step numbering (5 "Execute", then 6 "Stop and confirm").
        Whether the subject exits on its own or is killed for timeout/
        cancellation, this attempt's container is always stopped before
        returning - `confirm_stopped()` (step 6) must confirm the WHOLE
        attempt has stopped, not merely that the exec'd process did, and the
        container's own placeholder process (`_KEEPALIVE_ARGV`) would
        otherwise keep it reporting "running" forever.

        Stdin delivery and stderr collection each run on their own thread,
        started BEFORE the deadline/cancel poll loop begins (cross-model
        review, PR #85). A synchronous `proc.stdin.write(stdin)` beforehand
        would block on a subject that never reads its stdin - for as long as
        the pipe buffer allows, defeating `limits.timeout` before the loop
        even starts - and reading `proc.stderr` only after `proc.wait()`
        risks the classic two-pipe deadlock: a subject that writes past the
        stderr pipe's buffer blocks on that write while nothing is draining
        it, and this method was blocked in `proc.wait()` waiting for exit."""
        assert isinstance(handle, _Handle)
        exec_argv = [*self.docker_bin, "exec"]
        if stdin is not None:
            exec_argv.append("-i")
        exec_argv += ["-w", CONTAINER_WORKSPACE, "--", handle.name, *argv]

        try:
            proc = subprocess.Popen(
                exec_argv, env=handle.env,
                stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
        except OSError as exc:
            return ExecuteResult(reason="launch-failed", exit_code=None, error=str(exc))

        stdout_chunks: list[bytes] = []
        assert proc.stdout is not None
        stdout_pipe = proc.stdout

        def _drain_stdout() -> None:
            while chunk := stdout_pipe.read(65536):
                stdout_chunks.append(chunk)

        stdout_thread = threading.Thread(target=_drain_stdout, daemon=True)
        stdout_thread.start()

        stderr_chunks: list[bytes] = []
        assert proc.stderr is not None
        stderr_pipe = proc.stderr

        def _drain_stderr() -> None:
            while chunk := stderr_pipe.read(65536):
                stderr_chunks.append(chunk)

        stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
        stderr_thread.start()

        if stdin is not None:
            assert proc.stdin is not None
            stdin_pipe = proc.stdin
            payload = stdin

            def _feed_stdin() -> None:
                try:
                    stdin_pipe.write(payload)
                except (BrokenPipeError, OSError):
                    pass
                finally:
                    try:
                        stdin_pipe.close()
                    except OSError:
                        pass

            threading.Thread(target=_feed_stdin, daemon=True).start()

        deadline = time.monotonic() + limits.timeout
        reason = "exited"
        while proc.poll() is None:
            if time.monotonic() >= deadline:
                reason = "timeout"
                break
            if cancel is not None and cancel():
                reason = "operator-cancelled"
                break
            time.sleep(0.02)

        signal_name: str | None = None
        if reason != "exited":
            signal_name = self._stop(handle, proc, limits.grace)
        else:
            proc.wait()
            self._kill_container(handle, "KILL")

        stdout_thread.join(timeout=limits.grace + self.daemon_timeout)
        stderr_thread.join(timeout=limits.grace + self.daemon_timeout)
        stdout = b"".join(stdout_chunks)
        stderr = b"".join(stderr_chunks)
        code = proc.returncode
        error = None
        if reason == "exited" and code not in (0, None) and stderr:
            error = stderr.decode("utf-8", errors="replace").strip() or None

        # The exec'd process's stdout is written back into the container at
        # `<workspace>/observations` (`verify.py`'s own documented
        # convention, #76: "a probe-serving backend is expected to capture
        # the started process's stdout to a file named `observations` at its
        # workspace root") - discovered NOT to happen at all until #81's
        # demo command actually exercised grading through this backend: the
        # exec'd process's own stdout was thrown away (`DEVNULL`), so a
        # probe that reports its verdict on stdout (skillc's own probe
        # convention) always looked like it "produced no report", whatever
        # it actually printed. Best-effort: a failure to write this file is
        # not fatal to execute() itself, matching the canary plant's own
        # best-effort discipline in install().
        try:
            payload = _owned_tar_bytes("observations", stdout)
            subprocess.run(
                [*self.docker_bin, "cp", "-", f"{handle.name}:{CONTAINER_WORKSPACE}"],
                input=payload, capture_output=True, env=handle.env, check=False,
                timeout=self.daemon_timeout,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass

        return ExecuteResult(reason=reason, exit_code=code, error=error, signal=signal_name)

    def _kill_container(self, handle: _Handle, sig: str) -> None:
        """`docker kill --signal SIG` against this attempt's own container,
        bounded by `daemon_timeout` and never letting an exception escape -
        best-effort, because `confirm_stopped()`/`confirm_absent()`
        independently verify the outcome afterward rather than trusting this
        call's own success (cross-model review, PR #85: an unbounded
        `subprocess.run` here could hang forever against a stalled daemon)."""
        try:
            subprocess.run(
                [*self.docker_bin, "kill", "--signal", sig, handle.name],
                capture_output=True, env=handle.env, check=False, timeout=self.daemon_timeout,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass

    def _stop(self, handle: _Handle, proc: subprocess.Popen[bytes], grace: float) -> str:
        """Timeout/cancellation escalation: `docker kill` reaches this
        attempt's CONTAINER (its own init/placeholder process), not the
        separately exec'd subject - a real daemon does not forward a
        container-level signal to an exec session the way `docker run
        --sig-proxy` forwards to its own foreground process. So this cannot
        promise the subject itself gets a graceful `SIGTERM`; what it
        guarantees is that the whole attempt (container included) stops
        within `grace` of the second kill. `SIGKILL` on the local exec
        client itself is the final fallback if even that leaves our own
        child process still running - `proc` must never outlive this call
        (cross-model review, PR #85: the pre-fix code could return with
        `proc` still alive after two `subprocess.TimeoutExpired`s, leaking
        it)."""
        self._kill_container(handle, "TERM")
        try:
            proc.wait(timeout=grace)
            return "SIGTERM"
        except subprocess.TimeoutExpired:
            pass
        self._kill_container(handle, "KILL")
        try:
            proc.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            proc.kill()  # our OWN child process, not the container - SIGKILL cannot be blocked
            proc.wait()
        return "SIGKILL"

    def _inspect(self, handle: _Handle) -> tuple[bool, bool, str | None]:
        """Returns `(reachable, absent, status)`.

        - `reachable=False` (daemon unreachable, a timeout, or ANY docker CLI
          error this method cannot positively identify as "no such object")
          means `confirm_stopped()`/`confirm_absent()` must answer
          `Confirmation.UNKNOWN` - never a guess. `absent`/`status` are
          meaningless in this case.
        - `reachable=True, absent=True` means the daemon gave a genuine "no
          such object" answer - a confident, positive fact.
        - `reachable=True, absent=False, status=<str>` is the container's
          own `.State.Status`.

        Docker's own CLI uses the SAME non-zero exit code for "no such
        object" and for "cannot connect to the Docker daemon" - and, found
        by cross-model review, also for permission failures, TLS errors, a
        malformed name, and any other daemon-side error this method has no
        specific text for. Treating every non-zero exit as "gone" (the
        pre-fix code's actual bug, not merely a hardening gap) would let a
        merely-unreachable daemon read as a *confirmed* absence - so only an
        explicit "no such" message is trusted as absence; every OTHER
        failure, unrecognized or not, is UNKNOWN. A successful call with
        empty stdout is likewise never trusted as a status - an existing
        container's inspect does not do that in practice, so empty output is
        itself treated as something this method cannot make sense of,
        UNKNOWN rather than a guessed absence."""
        try:
            proc = subprocess.run(
                [*self.docker_bin, "inspect", "--format", "{{.State.Status}}", handle.name],
                capture_output=True, text=True, timeout=self.daemon_timeout, env=handle.env, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False, False, None
        if proc.returncode != 0:
            if "no such" in proc.stderr.lower():
                return True, True, None
            return False, False, None
        status = proc.stdout.strip()
        if not status:
            return False, False, None
        return True, False, status

    def confirm_stopped(self, handle: object) -> Confirmation:
        """Step 6: ask the daemon, independent of `execute()`'s own return,
        whether this attempt's container has stopped. Never trusts
        `execute()`'s own observation - the same discipline `confirm_absent`
        applies to `destroy()`."""
        assert isinstance(handle, _Handle)
        reachable, absent, status = self._inspect(handle)
        if not reachable:
            return Confirmation.UNKNOWN
        if absent or status in ("exited", "dead"):
            return Confirmation.CONFIRMED
        if status == "running":
            return Confirmation.NOT_CONFIRMED
        return Confirmation.UNKNOWN

    def export(self, handle: object, dest: Path) -> None:
        """Step 7 (backend side): copy the container's workspace contents
        into `dest` via `docker cp NAME:/work/. dest` - contents only, never
        nesting `/work` itself inside `dest`. Read-only on the container
        side and safe to call more than once, per the Protocol's own rule."""
        assert isinstance(handle, _Handle)
        dest.mkdir(parents=True, exist_ok=True)
        try:
            copied = subprocess.run(
                [*self.docker_bin, "cp", f"{handle.name}:{CONTAINER_WORKSPACE}/.", str(dest)],
                capture_output=True, text=True, env=handle.env, check=False, timeout=self.daemon_timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise OSError(f"docker cp export failed for {handle.attempt_id!r}: {exc}") from exc
        if copied.returncode != 0:
            raise OSError(f"docker cp export failed for {handle.attempt_id!r}: {copied.stderr.strip()}")

    def destroy(self, handle: object) -> None:
        """Step 9: `docker rm -f` - safe to call more than once, and safe to
        call after a failed `install`/`execute` (the container is always
        created by the time a caller has a handle at all)."""
        assert isinstance(handle, _Handle)
        try:
            subprocess.run(
                [*self.docker_bin, "rm", "-f", handle.name],
                capture_output=True, env=handle.env, check=False, timeout=self.daemon_timeout,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass  # best-effort; confirm_absent() independently verifies the outcome

    def confirm_absent(self, handle: object) -> Confirmation:
        """Step 9: ask the daemon whether this attempt's container is
        actually gone, after `destroy()` - never trusts `docker rm -f`'s own
        exit code alone, exactly as `confirm_stopped` never trusts
        `execute()`'s. Only a genuine "no such object" answer is CONFIRMED;
        an unreachable daemon is UNKNOWN, never a guess."""
        assert isinstance(handle, _Handle)
        reachable, absent, _status = self._inspect(handle)
        if not reachable:
            return Confirmation.UNKNOWN
        return Confirmation.CONFIRMED if absent else Confirmation.NOT_CONFIRMED
