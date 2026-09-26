"""The Docker backend: skillc's own, closing implementation of the execution
backend seam (#10). It is a complete, standalone answer: nothing here depends
on any other system, and it drives a subject inside a container via the
`docker` CLI through `subprocess` - stdlib only, no SDK (AGENTS.md).

WHY `execute()` DOES NOT REUSE `trial.run_attempt`. The Protocol's `execute()`
takes `(handle, argv, limits, cancel)` - no `experiment`, no `attempt_id`. It
cannot call `trial.run_attempt`, which needs both to write journal events; that
is `skillc/lifecycle.py`'s job, one layer up. So `execute()` manages its own
`docker run` subprocess directly (Popen, poll, timeout/cancel, TERM-then-KILL),
mirroring `tests/test_lifecycle.py`'s `FakeBackend` - the difference is what
gets launched, not how it is watched.

WHY `confirm_stopped()`/`confirm_absent()` NEVER TRUST `execute()`'s OWN EXIT.
Killing the host-side `docker run` CLI process (this backend's escalation path
when TERM does not finish in time) does not stop the CONTAINER: the container
is owned by dockerd/containerd-shim, not the CLI's process tree, and `--rm`'s
auto-cleanup only fires on a graceful daemon-observed exit. Both methods query
`docker inspect` independently, every time - never the CLI subprocess's
returncode, never `destroy()`'s own return value.

NEUTRAL IDENTITY (interfaces.md "Execution backend" section; operator rule,
skillc is public, #63): a fixed non-root user, a fixed hostname, fixed
logical paths (`/work`, `/home/candidate`), and a container name derived from
the attempt ID alone. `describe()`, `install()`'s readiness and `str(handle)`
report only those logical values - never a host path, uid or hostname.

CREDENTIALS (issue #10 addendum item B5): a trial-scoped credential, if
`surface` declares one, is written FRESH into the private home this backend
creates for the attempt - never a bind mount of a host file, never the
controller's own environment. The private home itself (`.claude`, `.codex`)
is created empty per attempt and never mounted from the host (addendum item
14): a shared mount would let one trial read another's transcripts.

RESOURCE LIMITS (addendum item C9): `--memory` and `--memory-swap` are always
equal - leaving `--memory-swap` unset lets the effective bound silently
double. `--pids-limit`, `--cpus` and `--shm-size` are always set; Chromium and
some test runners break on Docker's 64 MiB `/dev/shm` default otherwise.

SANDBOX CHOICE (addendum item A3): recorded in `describe()` as
`SANDBOX_MODE`, not silently assumed. This image is not known to carry
bubblewrap, so a Codex subject would decline every shell command under
`--sandbox workspace-write` (kyle #1396) - the documented choice here is
UNSANDBOXED, because the container itself is the fence.

IMAGE AND CLIENT IDENTITY (addendum items D13/D14): `install()` resolves and
records the digest of the image that actually RAN (`docker image inspect
--format {{.Id}}`), never trusting the tag alone - two builds of one tag can
differ, and only the digest that ran is evidence.

NO SOCKET, NO ESCAPE HATCH (addendum item C12): `compose_run_argv` emits a
FIXED, closed set of flags. There is no passthrough parameter for arbitrary
extra `docker run` arguments, so there is no code path through which a
caller could add a socket mount, `--privileged`, or a `docker` binary into
the trial - the guarantee is structural, not a convention nobody happens to
violate yet, exactly as `container_executor`'s own closed schema is
elsewhere in this fleet's ecosystem.

WHAT THIS BACKEND DOES NOT DEMONSTRATE HERE. Tested in this PR only against
a fake `docker` CLI script (no daemon in this session) - the argv
composition and the state machine are proven; the isolation properties
themselves (network egress actually blocked, credentials actually
unreachable, the container boundary holding under pressure) are owed to the
live daemon run (issue #10 comment 5848577772, lesson E17). `describe()`
says so under `unobserved`, not just this docstring.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import signal
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO

from . import provenance
from .backend import (
    BackendDescription,
    BackendUnavailable,
    Confirmation,
    ExecuteResult,
    Limits,
)
from .lifecycle import CANARY_NONCE_KEY

DAEMON_TIMEOUT = 5.0

def _container_user() -> str:
    """The uid:gid the container runs as. MUST be the real host uid/gid, not a
    fixed placeholder like "1000:1000" (bug found by cross-model review):
    `prepare()` creates `work_dir`/`home_dir` owned by whatever user runs this
    process, and a container started with a DIFFERENT uid cannot read or
    write its own bind-mounted directories - it fails at the first write, not
    at startup, which is why a fixed constant looked fine in every test
    against a fake CLI. `os.getuid`/`os.getgid` are POSIX-only, matching this
    package's `subprocess`-and-Docker approach generally (AGENTS.md)."""
    return f"{os.getuid()}:{os.getgid()}"


#: A neutral HOSTNAME and logical paths - never the host's own (interfaces.md
#: "Execution backend"). The container's UID is real (see `_container_user`);
#: neutrality here means no host machine identity, not a fake numeric owner.
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
#: identically to every invocation this backend makes (see `_docker_env`),
#: never left to each call's own ambient inheritance.
DOCKER_CONNECTION_VARS = ("DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG", "DOCKER_CERT_PATH", "DOCKER_TLS_VERIFY")


def _docker_env() -> dict[str, str]:
    """A consistent environment for every docker CLI call THIS BACKEND makes
    - never each call inheriting the ambient environment independently
    (found by cross-model review: `execute()` stripped its subprocess to just
    `PATH` while every other call inherited the full environment, so a
    caller with `DOCKER_HOST`/`DOCKER_CONTEXT` set could have `execute()`
    target the default daemon while `confirm_stopped`/`confirm_absent`/
    `destroy` queried a DIFFERENT one - an absence there would falsely
    confirm teardown of a container still running on the daemon `execute()`
    actually used)."""
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


def container_state(
    docker_bin: Sequence[str], name: str, timeout: float = DAEMON_TIMEOUT, env: Mapping[str, str] | None = None,
) -> str | None:
    """Ask the DAEMON whether `name` exists, and its status if so - the only
    fact `confirm_stopped`/`confirm_absent` trust. Three distinct answers:
    a status string (present), `None` (CONFIRMED absent), or `"unknown"`
    (the query itself failed, or failed for a reason OTHER than "this
    container does not exist" - never collapsed into "absent"; found by
    cross-model review: a disconnected daemon, a permission error or a
    server error also exit non-zero, and treating that the same as a genuine
    "No such object" would let a query the daemon never actually answered
    read as a confirmed teardown). `env=None` inherits the caller's own
    environment; `DockerBackend` always passes `_docker_env()` explicitly."""
    try:
        proc = subprocess.run(
            [*docker_bin, "inspect", "--format", "{{.State.Status}}", name],
            capture_output=True, timeout=timeout, text=True, check=False, env=env,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    if proc.returncode != 0:
        return None if "No such" in proc.stderr else "unknown"
    return proc.stdout.strip() or None


def force_remove(
    docker_bin: Sequence[str], name: str, timeout: float = DAEMON_TIMEOUT, env: Mapping[str, str] | None = None,
) -> bool:
    """`docker rm -f name`: idempotent (an already-absent container is
    success - there is nothing left to remove), and forcibly stops a running
    one, so a separate `docker stop` is not needed first. `env=None` inherits
    the caller's own environment; `DockerBackend` always passes
    `_docker_env()` explicitly."""
    try:
        proc = subprocess.run(
            [*docker_bin, "rm", "-f", name], capture_output=True, timeout=timeout, text=True, check=False, env=env,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if proc.returncode == 0:
        return True
    return "No such container" in proc.stderr


def _copy_tree_no_symlinks(src: Path, dest: Path) -> None:
    """Recursively copy `src` into `dest`, skipping (never following) a
    symlink at ANY depth. `shutil.copytree(symlinks=False)` DEREFERENCES a
    symlink found inside the tree instead of skipping it - exactly backwards
    for untrusted candidate output: a `nested/leak -> /etc/passwd` would
    otherwise export the host file it points to (found by cross-model
    review). Matches `trial.py`'s own capture discipline: never follow,
    whatever a link points to."""
    for entry in src.iterdir():
        if entry.is_symlink():
            continue
        target = dest / entry.name
        if entry.is_dir():
            target.mkdir(exist_ok=True)
            _copy_tree_no_symlinks(entry, target)
        elif entry.is_file():
            shutil.copy2(entry, target)


def _resolve_image_digest(
    docker_bin: Sequence[str], image: str, timeout: float = DAEMON_TIMEOUT, env: Mapping[str, str] | None = None,
) -> str | None:
    """The digest of the image that will actually run - never the tag alone
    (addendum D13/D14: two builds of one tag can differ). `env=None` inherits
    the caller's own environment; `DockerBackend` always passes
    `_docker_env()` explicitly."""
    try:
        proc = subprocess.run(
            [*docker_bin, "image", "inspect", image, "--format", "{{.Id}}"],
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


def compose_run_argv(
    docker_bin: Sequence[str],
    image: str,
    name: str,
    work_dir: Path,
    home_dir: Path,
    subject_argv: Sequence[str],
    env: Mapping[str, str],
    network: str,
    memory: str,
    pids_limit: str,
    cpus: str,
    shm_size: str,
    container_user: str,
) -> list[str]:
    """The full `docker run` argv. Pure - makes no call, mutates nothing. A
    FIXED, closed set of flags: there is no passthrough for arbitrary extra
    arguments, so nothing here can ever mount the docker socket, add
    `--privileged`, or otherwise widen the container (addendum item C12).

    `-i` is always present so a caller MAY deliver `execute(..., stdin=...)`
    - without it, `docker run` never attaches the client's stdin to the
    container at all, regardless of what `execute()` writes on its own side.
    An attempt that never uses stdin sees no difference: an unread, empty
    stdin is not a hang, just an immediate EOF if the subject ever reads it."""
    return [
        *docker_bin, "run", "--rm", "-i", "--name", name,
        "--network", network,
        "--user", container_user,
        "--hostname", CONTAINER_HOSTNAME,
        "--init",
        "--memory", memory, "--memory-swap", memory,
        "--pids-limit", pids_limit,
        "--cpus", cpus,
        "--shm-size", shm_size,
        "-v", f"{work_dir}:{CONTAINER_WORKSPACE}:rw",
        "-v", f"{home_dir}:{CONTAINER_HOME}:rw",
        "-w", CONTAINER_WORKSPACE,
        "-e", f"HOME={CONTAINER_HOME}",
        *_env_args(env),
        image, *subject_argv,
    ]


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
    by digest where possible (`name@sha256:...`); `install()` resolves and
    records the digest that actually ran regardless, per D13/D14."""

    image: str
    base_dir: Path
    docker_bin: Sequence[str] = ("docker",)
    network: str = "none"
    memory: str = DEFAULT_MEMORY
    pids_limit: str = DEFAULT_PIDS_LIMIT
    cpus: str = DEFAULT_CPUS
    shm_size: str = DEFAULT_SHM_SIZE
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
                f"non-root user {_container_user()}",
                "resource limits enforced: memory, memory-swap (equal), pids, cpus, shm-size",
                f"sandbox: {SANDBOX_MODE}",
                "no docker socket, no docker binary, no passthrough flags in the composed argv",
            ),
            unobserved=(
                "network egress actually blocked - not verified from inside the container",
                "file reads by candidate code",
                ("credential confidentiality against an ancestor's /proc/<pid>/environ - "
                 "that is PR2's boundary (verify.py's probe through this same seam)"),
                ("the live daemon boundary itself, when this backend is tested only against "
                 "a fake docker CLI (issue #10 comment 5848577772, lesson E17)"),
            ),
        )

    def prepare(self, attempt_id: str) -> object:
        version = probe_daemon(self.docker_bin, self.daemon_timeout, _docker_env())
        if version is None:
            raise BackendUnavailable(
                f"docker daemon unreachable via {' '.join(self.docker_bin)!r}"
            )
        name = f"skillc-{attempt_id}"
        root = self.base_dir / f"handle-{attempt_id}"
        if root.exists():
            # Refuse, never destroy: a second `prepare()` for an attempt_id
            # already prepared (found by cross-model review) must not
            # `rmtree` a workspace that may be IN USE - the old code's except
            # block ran on ANY OSError, including the FileExistsError from
            # this exact collision, and wiped the pre-existing directory
            # regardless of what it held.
            raise BackendUnavailable(f"a workspace for attempt {attempt_id!r} already exists")
        work_dir, home_dir = root / "work", root / "home"
        try:
            for d in (work_dir, home_dir):
                d.mkdir(parents=True, mode=0o700)
            # A private, EMPTY home per trial (addendum item 14) - never
            # mounted from the host. A shared mount would let one trial read
            # another's transcripts, which contain what THAT trial's
            # candidate code read.
            for sub in (".claude", ".codex"):
                (home_dir / sub).mkdir(mode=0o700)
        except OSError:
            # Safe here: this call is the one that just created `root`, so a
            # failure partway through belongs to THIS attempt alone.
            shutil.rmtree(root, ignore_errors=True)
            raise
        return _Handle(attempt_id=attempt_id, name=name, work_dir=work_dir, home_dir=home_dir)

    def install(self, handle: object, surface: Mapping[str, object]) -> dict[str, object]:
        assert isinstance(handle, _Handle)
        nonce = surface.get(CANARY_NONCE_KEY)
        declared = {k: v for k, v in surface.items() if k != CANARY_NONCE_KEY}
        readiness: dict[str, object] = {
            "image_digest": _resolve_image_digest(self.docker_bin, self.image, self.daemon_timeout, _docker_env()),
            "sandbox_mode": SANDBOX_MODE,
            "declared": len(declared),
            # Which skillc produced this receipt (operator request, addendum
            # item E) - the CONTROLLER's own checkout, never the candidate's
            # or the experiment's tree. Agreed field names with w3 (#10 PR2),
            # who stamps the same shape on verified-result records.
            "provenance": provenance.stamp().as_dict(),
        }
        if not declared:
            readiness["discovery_canary"] = "VIOLATED"
            readiness["baseline_absence"] = "SATISFIED"
            return readiness

        # GENERIC MATERIALIZATION: any declared entry whose value is `bytes`
        # is written into the container's WORKSPACE at that relative path -
        # how a caller gets real file content into `/work` without this
        # backend needing to know what the files mean. This is the hook a
        # grader-shaped surface (probe harness, inputs, candidate files - #9's
        # PR2, a different vocabulary than #7's skill materialization) uses;
        # the domain-specific keys below (`credential`, `client`,
        # `client_version`) are never bytes, so the two conventions do not
        # collide. Path safety matches the canary's own escape check.
        for name, content in declared.items():
            if isinstance(content, bytes):
                target = (handle.work_dir / name).resolve()
                if not target.is_relative_to(handle.work_dir.resolve()):
                    raise ValueError(f"surface entry {name!r} escapes the workspace")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)

        # A trial-scoped credential, written FRESH - never a bind mount of a
        # host file, never the controller's own environment (addendum B5).
        credential = declared.get("credential")
        if isinstance(credential, str):
            cred_path = handle.home_dir / ".skillc-credential"
            cred_path.write_text(credential, encoding="utf-8")
            cred_path.chmod(0o600)

        # Onboarding seed (addendum A1). A real client's exact seed shape is
        # version-sensitive and measured, not guessed here; this records the
        # documented required keys and the pinned client version, and NEVER
        # auto-answers a prompt at runtime - there is no runtime prompt
        # handling here at all, because no real client runs in this PR's
        # demo. A backend actually driving Claude Code must replace this
        # with a seed measured against the pinned CLI version and update
        # `readiness["client_version"]` to match.
        client = declared.get("client")
        if client == "claude":
            client_version = declared.get("client_version", "unpinned")
            seed = {
                "hasCompletedOnboarding": True,
                "bypassPermissionsModeAccepted": True,
                "projects": {
                    CONTAINER_WORKSPACE: {
                        "hasTrustDialogAccepted": True,
                        "enabledMcpjsonServers": [],
                    },
                },
            }
            (handle.home_dir / ".claude.json").write_text(json.dumps(seed), encoding="utf-8")
            readiness["client_version"] = client_version

        if isinstance(nonce, str):
            (handle.work_dir / ".skillc-canary").write_text(nonce, encoding="utf-8")
            readiness["canary_path"] = ".skillc-canary-result"
        # UNKNOWN, never a blind SATISFIED (bug found by cross-model review):
        # this backend only WRITES the declared surface into the workspace -
        # it never runs `materialize.py`'s own discovery/baseline observation
        # against a real client, so it has no evidence for either fact.
        # Claiming SATISFIED here would be a guess dressed as a check result.
        readiness["discovery_canary"] = "UNKNOWN"
        readiness["baseline_absence"] = "UNKNOWN"
        return readiness

    def execute(
        self, handle: object, argv: Sequence[str], limits: Limits,
        cancel: Callable[[], bool] | None = None, stdin: bytes | None = None,
    ) -> ExecuteResult:
        assert isinstance(handle, _Handle)
        docker_argv = compose_run_argv(
            self.docker_bin, self.image, handle.name, handle.work_dir, handle.home_dir,
            argv, self.env, self.network, self.memory, self.pids_limit, self.cpus, self.shm_size,
            _container_user(),
        )
        # `stdin` is delivered via a real FILE, never a pipe this process
        # writes to by hand: a pipe write large enough to fill the OS buffer
        # would deadlock against the poll loop below, since nothing is
        # draining it concurrently. A file has no such limit, and `-i` in
        # compose_run_argv is what makes docker actually attach it to the
        # container.
        with contextlib.ExitStack() as stack:
            stdin_source: int | IO[bytes] = subprocess.DEVNULL
            if stdin is not None:
                stdin_path = handle.work_dir.parent / f"{handle.attempt_id}.stdin"
                stdin_path.write_bytes(stdin)
                stdin_source = stack.enter_context(open(stdin_path, "rb"))
            try:
                proc = subprocess.Popen(
                    docker_argv, cwd=handle.work_dir, env=_docker_env(),
                    stdin=stdin_source, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
            except OSError as exc:
                return ExecuteResult(reason="launch-failed", exit_code=None, error=str(exc))
            # The stack closes stdin_source here, once Popen returns - safe:
            # Popen has already duplicated the fd into the child by this point.
        handle.proc = proc
        deadline = time.monotonic() + limits.timeout
        reason = "exited"
        while proc.poll() is None:
            if time.monotonic() >= deadline:
                reason = "timeout"
                break
            if cancel is not None and cancel():
                reason = "operator-cancelled"
                break
            time.sleep(0.05)
        if reason != "exited":
            # This stops the `docker run` CLI PROCESS - never assume it stops
            # the container. confirm_stopped()/confirm_absent() ask the
            # daemon directly; destroy() force-removes unconditionally.
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                proc.wait(timeout=limits.grace)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait()
        else:
            proc.wait()
        code = proc.returncode
        signal_name = signal.Signals(-code).name if code is not None and code < 0 else None
        return ExecuteResult(reason=reason, exit_code=code, signal=signal_name)

    def confirm_stopped(self, handle: object) -> Confirmation:
        assert isinstance(handle, _Handle)
        status = container_state(self.docker_bin, handle.name, self.daemon_timeout, _docker_env())
        if status == "unknown":
            return Confirmation.UNKNOWN
        if status is None or status in ("exited", "dead"):
            return Confirmation.CONFIRMED
        return Confirmation.NOT_CONFIRMED  # "running", "created", "paused", ...

    def export(self, handle: object, dest: Path) -> None:
        assert isinstance(handle, _Handle)
        _copy_tree_no_symlinks(handle.work_dir, dest)

    def destroy(self, handle: object) -> None:
        assert isinstance(handle, _Handle)
        force_remove(self.docker_bin, handle.name, self.daemon_timeout, _docker_env())
        shutil.rmtree(handle.work_dir.parent, ignore_errors=True)

    def confirm_absent(self, handle: object) -> Confirmation:
        assert isinstance(handle, _Handle)
        status = container_state(self.docker_bin, handle.name, self.daemon_timeout, _docker_env())
        if status == "unknown":
            return Confirmation.UNKNOWN
        return Confirmation.CONFIRMED if status is None else Confirmation.NOT_CONFIRMED
