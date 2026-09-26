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

UNKNOWN NEVER REAPS. `confirm_stopped()`/`confirm_absent()` return
`Confirmation.UNKNOWN` whenever the daemon cannot be asked at all (a timeout,
an unreachable daemon) - never a guessed `CONFIRMED` or `NOT_CONFIRMED`. A
"no such object" answer from a reachable daemon is a *positive* fact (the
container is definitely gone) and is reported as `CONFIRMED`, never confused
with the unreachable case.

WHAT THIS PR DOES NOT DEMONSTRATE. `execute()` stops a runaway subject by
killing the whole per-attempt container (`docker kill`), not the exec'd
process alone - `docker exec` does not reliably proxy signals to the exec'd
process the way `docker run --sig-proxy` does for its own foreground process,
and every container here belongs to exactly one attempt, so this is safe but
coarser than a per-process signal. `install()` materializes a declared
surface entry only when its value names an existing host path; a richer
surface contract (dependency resolution inside the container) is future
work. Fake `docker` CLI only in this test suite (`tests/fixtures/docker-backend/
fake_docker.py`) - this proves the LIFECYCLE state machine and the composed
argv, never a real containment boundary; that remains owed to the operator's
live run (#10). See `describe()`'s own `unobserved` claims for the rest.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
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


@dataclass(frozen=True)
class _Handle:
    """Opaque to the controller (backend.py's own rule): `attempt_id` and
    `name` are both derived from the attempt ID alone, so `str(handle)`
    (the dataclass default) never leaks a host path, uid or hostname. No
    `work_dir`/`home_dir` fields - there is no host-side directory backing
    this attempt at all, since data moves by `docker cp`, never a bind
    mount."""

    attempt_id: str
    name: str


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
                ("a timeout or cancellation stopping only the exec'd process - execute() "
                 "stops the WHOLE per-attempt container instead, because docker exec does "
                 "not reliably proxy signals to the exec'd process the way docker run "
                 "--sig-proxy does for its own foreground process"),
                ("dependency resolution inside the container - install() copies in any "
                 "declared surface entry naming an existing host path; it does not run a "
                 "package manager or resolve a dependency closure"),
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
        `docker run` itself fails; nothing is left behind on that path since
        no container was ever created."""
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
            raise BackendUnavailable(
                f"docker run failed to start a container for {attempt_id!r}: {started.stderr.strip()}"
            )
        return _Handle(attempt_id=attempt_id, name=name)

    def install(self, handle: object, surface: Mapping[str, object]) -> dict[str, object]:
        """Step 4: copy every declared surface entry that names an existing
        host path into the running container via `docker cp`, plant the
        liveness canary (`lifecycle.CANARY_NONCE_KEY`) the same way when
        present, and report readiness evidence. Raises `BackendUnavailable`
        if a declared copy fails - a materialization failure makes this
        attempt's backend unusable, exactly like an unreachable daemon."""
        assert isinstance(handle, _Handle)
        env = _docker_env()
        nonce = surface.get(CANARY_NONCE_KEY)
        declared = {k: v for k, v in surface.items() if k != CANARY_NONCE_KEY}

        for key, value in declared.items():
            host_path = _as_existing_path(value)
            if host_path is None:
                continue
            dest = f"{handle.name}:{CONTAINER_WORKSPACE}/{key}"
            try:
                copied = subprocess.run(
                    [*self.docker_bin, "cp", str(host_path), dest],
                    capture_output=True, text=True, env=env, check=False,
                )
            except OSError as exc:
                raise BackendUnavailable(f"docker cp failed installing {key!r}: {exc}") from exc
            if copied.returncode != 0:
                raise BackendUnavailable(
                    f"docker cp failed installing {key!r} for {handle.attempt_id!r}: {copied.stderr.strip()}"
                )

        readiness: dict[str, object] = {
            "discovery_canary": "SATISFIED" if declared else "VIOLATED",
            "baseline_absence": "SATISFIED",
            "declared": len(declared),
        }
        if isinstance(nonce, str) and nonce:
            with tempfile.TemporaryDirectory() as tmp:
                canary_file = Path(tmp) / CANARY_HOST_FILENAME
                canary_file.write_text(nonce, encoding="utf-8")
                copied = subprocess.run(
                    [*self.docker_bin, "cp", str(canary_file),
                     f"{handle.name}:{CONTAINER_WORKSPACE}/{CANARY_HOST_FILENAME}"],
                    capture_output=True, text=True, env=env, check=False,
                )
            # A failed canary plant is not fatal to install() itself - the
            # driver's weaker content-diff fallback still applies whenever
            # canary_path is absent (lifecycle.py's own documented fallback).
            if copied.returncode == 0:
                readiness["canary_path"] = CANARY_RESULT_FILENAME
        return readiness

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
        otherwise keep it reporting "running" forever."""
        assert isinstance(handle, _Handle)
        exec_argv = [*self.docker_bin, "exec"]
        if stdin is not None:
            exec_argv.append("-i")
        exec_argv += ["-w", CONTAINER_WORKSPACE, "--", handle.name, *argv]

        try:
            proc = subprocess.Popen(
                exec_argv, env=_docker_env(),
                stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            )
        except OSError as exc:
            return ExecuteResult(reason="launch-failed", exit_code=None, error=str(exc))

        if stdin is not None:
            assert proc.stdin is not None
            try:
                proc.stdin.write(stdin)
            except BrokenPipeError:
                pass
            finally:
                proc.stdin.close()

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
            self._stop_container(handle.name)

        stderr = proc.stderr.read() if proc.stderr else b""
        code = proc.returncode
        error = None
        if reason == "exited" and code not in (0, None) and stderr:
            error = stderr.decode("utf-8", errors="replace").strip() or None
        return ExecuteResult(reason=reason, exit_code=code, error=error, signal=signal_name)

    def _stop_container(self, name: str) -> None:
        """Cleanup after a subject that exited on its own: the container's
        own placeholder process (`_KEEPALIVE_ARGV`) is otherwise never
        signaled and keeps the container reporting "running" forever. Not
        graceful - there is nothing mid-work to interrupt in an idle
        placeholder - so a single default-signal `docker kill` is enough."""
        subprocess.run([*self.docker_bin, "kill", name], capture_output=True, env=_docker_env(), check=False)

    def _stop(self, handle: _Handle, proc: subprocess.Popen[bytes], grace: float) -> str:
        """Timeout/cancellation escalation: a `docker exec` client process
        does not reliably proxy signals to the exec'd process the way
        `docker run --sig-proxy` does for its own foreground process, so
        this stops the WHOLE per-attempt container instead - safe, because
        every container this backend creates belongs to exactly one
        attempt. `SIGTERM` first (honoring `limits.grace`), `SIGKILL` if the
        exec client has not exited within grace."""
        env = _docker_env()
        subprocess.run(
            [*self.docker_bin, "kill", "--signal", "TERM", handle.name],
            capture_output=True, env=env, check=False,
        )
        try:
            proc.wait(timeout=grace)
            return "SIGTERM"
        except subprocess.TimeoutExpired:
            pass
        subprocess.run(
            [*self.docker_bin, "kill", "--signal", "KILL", handle.name],
            capture_output=True, env=env, check=False,
        )
        try:
            proc.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            pass
        return "SIGKILL"

    def _inspect_status(self, name: str) -> str | None:
        """The container's `.State.Status`, `""` if the daemon reports it
        gone ("no such object" - a confident, positive fact, never guessed),
        or `None` if the daemon could not be asked at all
        (unreachable/timeout, or a non-zero exit whose stderr says so).
        `confirm_stopped()`/`confirm_absent()` turn `None` into
        `Confirmation.UNKNOWN`, never a guessed CONFIRMED/NOT_CONFIRMED -
        UNKNOWN never reaps.

        A non-zero exit is NOT on its own "gone": docker's own CLI uses
        the same exit code for "no such object" and "cannot connect to the
        Docker daemon" (found while testing this exact method) - conflating
        them would let a merely-unreachable daemon read as a *confirmed*
        absence, which is precisely the guessed confidence this seam's
        UNKNOWN exists to refuse. Only stderr distinguishes them."""
        try:
            proc = subprocess.run(
                [*self.docker_bin, "inspect", "--format", "{{.State.Status}}", name],
                capture_output=True, text=True, timeout=self.daemon_timeout, env=_docker_env(), check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if proc.returncode != 0:
            if "cannot connect" in proc.stderr.lower():
                return None
            return ""
        return proc.stdout.strip()

    def confirm_stopped(self, handle: object) -> Confirmation:
        """Step 6: ask the daemon, independent of `execute()`'s own return,
        whether this attempt's container has stopped. Never trusts
        `execute()`'s own observation - the same discipline `confirm_absent`
        applies to `destroy()`."""
        assert isinstance(handle, _Handle)
        status = self._inspect_status(handle.name)
        if status is None:
            return Confirmation.UNKNOWN
        if status in ("", "exited", "dead"):
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
                capture_output=True, text=True, env=_docker_env(), check=False,
            )
        except OSError as exc:
            raise OSError(f"docker cp export failed for {handle.attempt_id!r}: {exc}") from exc
        if copied.returncode != 0:
            raise OSError(f"docker cp export failed for {handle.attempt_id!r}: {copied.stderr.strip()}")

    def destroy(self, handle: object) -> None:
        """Step 9: `docker rm -f` - safe to call more than once, and safe to
        call after a failed `install`/`execute` (the container is always
        created by the time a caller has a handle at all)."""
        assert isinstance(handle, _Handle)
        subprocess.run(
            [*self.docker_bin, "rm", "-f", handle.name], capture_output=True, env=_docker_env(), check=False,
        )

    def confirm_absent(self, handle: object) -> Confirmation:
        """Step 9: ask the daemon whether this attempt's container is
        actually gone, after `destroy()` - never trusts `docker rm -f`'s own
        exit code alone, exactly as `confirm_stopped` never trusts
        `execute()`'s. Only a genuine "no such object" answer is CONFIRMED;
        an unreachable daemon is UNKNOWN, never a guess."""
        assert isinstance(handle, _Handle)
        status = self._inspect_status(handle.name)
        if status is None:
            return Confirmation.UNKNOWN
        if status == "":
            return Confirmation.CONFIRMED
        return Confirmation.NOT_CONFIRMED
