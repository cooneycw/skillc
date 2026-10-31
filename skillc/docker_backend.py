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
exec` - NEVER a workspace/home bind mount, and never a second role container
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
and `_stop()`). #621 adds one closed named-volume mount at the fixed wave-state
path for roles owned by `DockerWave`; the wave controller owns that volume,
network and fixture remote. Every role still owns an independent workspace,
home and PID namespace. This opt-in does not change existing callers.

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

NO ESCAPE HATCH, WITH NAMED, NARROW EXCEPTIONS (addendum item C12; #183,
owner ruling 2026-10-03): `compose_run_argv` emits a FIXED, closed set of
flags. There is still no passthrough parameter for arbitrary extra `docker
run` arguments, so there is no code path through which a caller could add
`--privileged`, a `docker` binary, an arbitrary mount, or a mount at a caller-
chosen target - the guarantee is structural for all of those, not a
convention nobody happens to violate yet, exactly as `container_executor`'s
own closed schema is elsewhere in this fleet's ecosystem. The socket exception:
`DockerBackend.trigger_decide`, when set, bind-mounts exactly ONE
host-owned Unix socket at the single hardcoded target `TRIGGER_SOCKET_PATH`
- the controller-owned decide-and-reply channel #183 and #269 build on. The
SOURCE path is derived by `prepare()` from the attempt id alone, never
accepted from an arbitrary caller; the TARGET is never a parameter at all.
See `compose_run_argv`'s own `trigger_socket_host_path` docstring and
`docs/specs/evaluation-facility/decide-reply-channel.md` §2c for the full
reasoning and for what stays refused.

#621 additionally permits one controller-owned named volume at a fixed path
through `wave_attachment`. Its closed type refuses host paths and arbitrary
targets; the wave controller owns creation, capture and removal. A role's
workspace and home still use no shared mount.

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
here). So `limits.grace`'s `SIGTERM`-then-`SIGKILL` escalation alone cannot
promise the SUBJECT itself gets a graceful signal - only that the whole
attempt stops within grace of the second kill. Issue #158 closes this when
the image supports it AND the supervisor is actually running:
`_forwarding_available` probes for both `skillc-wrap`'s executable bit
(`docker/trial/skillc-wrap.py`) and the running `skillc-supervisor.py`'s
control socket before prefixing the exec argv with the wrapper -
capability-gated so this module's own behavior is unchanged whenever
either is missing, which is every image today: the #78 Dockerfile change
that bakes the two scripts in, AND `_keepalive_run_argv`'s own switch from
`sleep infinity` to the supervisor, are BOTH held pending the operator's
#150 discriminating run (docs/specs/evaluation-facility/
signal-forwarding.md sections 3 and 7). `ExecuteResult.term_forwarding`
reports what THIS module observed from the host side for a given attempt -
never a trusted claim about what happened inside the container, which the
supervisor/wrapper cannot themselves prove any more than the subject they
describe can (same trust boundary, same user, see `term_forwarding`'s own
docstring). `install()` materializes a declared surface entry only when its value names
an existing host path, and reports `discovery_canary`/`installed` from what
was ACTUALLY copied, never merely what was declared; a richer surface
contract (dependency resolution inside the container) is future work. Fake
`docker` CLI only in this test suite (`tests/fixtures/docker-backend/
fake_docker.py`) - this proves the LIFECYCLE state machine and the composed
argv, never a real containment boundary; that remains owed to the operator's
live run (#10). See `describe()`'s own `unobserved` claims for the rest.
"""

from __future__ import annotations

import hashlib
import io
import ipaddress
import json
import os
import re
import signal
import stat
import subprocess
import tarfile
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath
from typing import IO

from . import egress as eg
from . import runtime_supply as rs
from .backend import CANDIDATE_GID as _CANDIDATE_GID
from .backend import CANDIDATE_UID as _CANDIDATE_UID
from .backend import (
    BackendDescription,
    BackendUnavailable,
    Confirmation,
    ExecuteResult,
    Limits,
)
from .completion import CompletionUnavailable, number
from .decide_reply_channel import DecideFn, DecideReplyChannel, LoggedDecision
from .lifecycle import CANARY_NONCE_KEY
from .verify import SURFACE_EXECUTABLE_KEY
from .wave_attachment import WaveAttachment

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
# Defined in `backend` (#235) so `leak` can exempt this identity without
# importing this module at load time (`tests/test_no_docker_required.py`).
CANDIDATE_UID = _CANDIDATE_UID
CANDIDATE_GID = _CANDIDATE_GID


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

#: The path `docker/trial/skillc-wrap.py` is baked into the trial image at,
#: once the #78 image change lands (issue #158; currently HELD - see that
#: file's own docstring, and docs/specs/evaluation-facility/
#: signal-forwarding.md section 3). `_forwarding_available` probes for this
#: exact path; `execute()` prefixes the subject argv with it only when the
#: probe confirms it is actually there.
SKILLC_WRAP_PATH = "/usr/local/bin/skillc-wrap"

#: #338: the wrapper-owned status record `exec_in_attempt()`'s confining
#: wrapper writes as the FIRST bytes of its stderr - `READY` immediately
#: before it execs the real argv, `REFUSED` instead when the cwd check
#: fails. Nothing else can write to that stderr before the record: the
#: check's own diagnostics (dash's "cannot open ...", `readlink`'s, `cd`'s)
#: go to /dev/null, and the gate has not been exec'd yet. The Python side
#: reads only that LEADING record, through a slot separate from the gate's
#: own retained stderr (`_BoundedDrain`'s `status_record_max`), so a gate
#: that prints either line itself is just printing output, never status.
CWD_CONFINEMENT_READY_RECORD = b"skillc-cwd-confinement:ready\n"
CWD_CONFINEMENT_REFUSED_RECORD = b"skillc-cwd-confinement:refused\n"
#: The bound on that leading record: a line longer than this, or no line
#: at all, is an invalid status, never something read further into the
#: stream looking for one.
CWD_CONFINEMENT_RECORD_MAX = 64

#: `ExecuteResult.error` for each way a confining exec can end without the
#: gate having been exec'd: the check refused the cwd, or the status record
#: was missing or malformed (the wrapper never reached its READY write, so
#: the gate never ran - but nothing confirmed a refusal either).
CWD_CONFINEMENT_REFUSED_SENTINEL = "skillc-cwd-confinement-refused"
CWD_CONFINEMENT_STATUS_MISSING = "skillc-cwd-confinement-status-missing"
CWD_CONFINEMENT_STATUS_INVALID = "skillc-cwd-confinement-status-invalid"

#: Must match skillc-supervisor.py's own default (`$SKILLC_CONTROL_SOCKET`
#: unset). `_forwarding_available` requires this socket to exist, not only
#: `SKILLC_WRAP_PATH`'s executable bit (review must-fix, PR #182): in THIS
#: PR, `prepare()` still starts every container with `_KEEPALIVE_ARGV`
#: (`sleep infinity`, never the supervisor) - `_keepalive_run_argv`'s own
#: switch to the supervisor binary belongs with the held image change
#: (section 3), not here (section 7's landing order says so explicitly).
#: So even on an image that carries both scripts, nothing runs the
#: supervisor yet, and this socket never exists - the wrap-binary check
#: alone would report "available" for a capability nothing can actually
#: use, prefixing the argv onto a wrapper that can never reach a
#: supervisor. Requiring the socket too means the gate reports
#: `unavailable-in-image` until the SAME held change that starts the
#: supervisor also makes the socket real.
SKILLC_CONTROL_SOCKET_PATH = "/run/skillc/control.sock"

#: The forwarding probe `_forwarding_available` runs on every `execute()` call,
#: and the command text the daemon's exec events show for it. #317 appends a
#: per-call `$0` token (`_FORWARDING_PROBE_TOKEN_PREFIX`) so that call's probe
#: event - the lower bound of its refused-exec decision window - can never be
#: confused with another call's identical probe.
_FORWARDING_PROBE_SCRIPT = f"test -x {SKILLC_WRAP_PATH} && test -S {SKILLC_CONTROL_SOCKET_PATH}"
_FORWARDING_PROBE_COMMAND = f"sh -c {_FORWARDING_PROBE_SCRIPT}"
_FORWARDING_PROBE_TOKEN_PREFIX = "skillc-probe-"

#: Where #183's controller-owned decide-and-reply channel is bind-mounted
#: into the container, when `DockerBackend.trigger_decide` is set (see that
#: field's own docstring and `docs/specs/evaluation-facility/
#: decide-reply-channel.md` §2c). A single hardcoded constant, never a
#: `compose_run_argv` parameter: the one narrow exception the owner's
#: 2026-10-03 ruling authorized is "the controller may mount ONE socket at
#: a path it names", never "a caller may choose the in-container target."
#: Distinct from `SKILLC_CONTROL_SOCKET_PATH` above (#158's own, unrelated,
#: still-held in-container control socket) - two different mechanisms, two
#: different paths, so neither can be mistaken for the other in a log or a
#: capability probe.
TRIGGER_SOCKET_PATH = "/run/skillc/trigger.sock"

#: Where the HOST side of #183's socket lives, by default - deliberately
#: SHORT and independent of `base_dir` (a workspace/session clone root),
#: because a Unix domain socket path is capped by the kernel
#: (`sizeof(sun_path)`, 108 bytes on Linux including the terminator;
#: `DecideReplyChannel.start()` enforces a safety margin below it and
#: names the limit if one is ever handed a path that violates it). A
#: `base_dir`-derived path routinely overflows that limit on its own,
#: before any attempt-specific suffix - found running this backend's own
#: integration test against a realistic (pytest `tmp_path`-derived)
#: `base_dir`. `_trigger_socket_host_path` hashes the attempt id to a
#: fixed-length name for the same reason: `attempt_id` is caller-supplied
#: and unbounded, and a long one must not reintroduce the overflow this
#: default was chosen to avoid.
DEFAULT_TRIGGER_SOCKET_DIR = Path(tempfile.gettempdir()) / "skillc-trigger"


def trigger_socket_host_path_for(trigger_socket_dir: Path, name: str) -> Path:
    """Pure - the exact host-side socket path `_start_trigger_channel` binds
    and `compose_run_argv`'s `trigger_socket_host_path` mounts, factored out
    so a test can assert the path a real `prepare()` call used without
    duplicating the hash. The filename is a hash of `name` (itself derived
    from `attempt_id` alone), never `name` verbatim: `_container_name` allows
    up to 128 characters, which alone can violate `DecideReplyChannel.
    start()`'s AF_UNIX safety margin once a real `trigger_socket_dir` is
    added on top of it - a fixed-length digest bounds the result regardless
    of how long the caller's `attempt_id` is (`DEFAULT_TRIGGER_SOCKET_DIR`'s
    own comment)."""
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:16]
    return trigger_socket_dir / f"{digest}.sock"


#: #183's socket access control (design doc §2f), decisions (a)/(b).
#:
#: (a) DIRECTORY: `_ensure_private_trigger_dir` below creates
#: `trigger_socket_dir` at mode 0700, owned by this process - never
#: `exist_ok=True`'d blindly. If the directory already exists, its owner
#: and mode are checked and the whole attempt is refused
#: (`BackendUnavailable`) on a mismatch, rather than silently trusting
#: something another host user or process created. A host-wide world-
#: readable/writable temp directory would let any other process on the
#: host list, pre-create, or replace a socket path before this backend
#: ever gets to it; a private, owner-verified directory means no other
#: host process can even TRAVERSE to a socket's name, regardless of that
#: socket file's own mode (directory execute/search permission is checked
#: before a file's own permission bits, for every syscall that resolves a
#: path through it - `stat()`, `connect()`, `unlink()`, all of them).
#:
#: (b) SOCKET MODE: the subject inside the container runs as the fixed
#: `CANDIDATE_UID:CANDIDATE_GID` (`compose_run_argv`'s `--user`), which is
#: essentially never this controller PROCESS's own uid - so a mode-0600,
#: owner-only socket (`DecideReplyChannel`'s own generic default, correct
#: for a caller running AS its own subject) would make the subject's own
#: `connect()` fail with EACCES, breaking the channel outright. Granting
#: "other" access looks wide in isolation, but the REAL access-control
#: boundary here is (a)'s directory, not this file's own mode: nothing on
#: the host other than this controller process can even resolve the
#: socket's HOST-side path to open it, because the directory's own 0700
#: blocks every other host user's traversal regardless of what the file
#: inside it allows. GROUP is granted too (`0o666`, not `0o606` -
#: cross-model review): the socket's actual group is whatever
#: this controller process's own primary group happens to be, essentially
#: never `CANDIDATE_GID` - changing it to an arbitrary target gid would
#: need the calling process to either own that gid as a supplementary
#: group or hold `CAP_CHOWN`, a privilege this backend does not require
#: anywhere else - so zeroing GROUP while granting OTHER bought nothing: a
#: deployment where the two processes' groups happen to coincide would be
#: denied for no reason, and (a)'s directory is doing the real work
#: either way. The container's OWN view of the bind-mounted file is
#: governed by the image's `/run/skillc/` directory (an image-level,
#: #78/PR-B concern, not this one) plus this file's own mode - never by
#: the host directory surrounding it, since a single-FILE bind mount
#: exposes only that one file, not its host-side neighbours.
TRIGGER_SOCKET_MODE = 0o666


def _ensure_private_trigger_dir(path: Path) -> None:
    """Design doc §2f decision (a). Creates `path` at mode 0700 if absent.
    If present, refuses (raises `BackendUnavailable`) unless it is already
    owned by this process's own uid and already mode 0700 - never widens
    an existing directory to match, and never proceeds past a mismatch on
    the assumption it is probably fine. `os.chmod` after `mkdir` rather
    than relying on `mkdir(mode=...)` alone: `mkdir`'s own `mode` argument
    is still subject to the process umask, which can only narrow it
    further for 0700 (every bit already absent from "group"/"other"), but
    stating the final mode explicitly removes any dependence on what the
    umask happens to be rather than reasoning about whether it is safe
    this time. Concurrent creators arbitrate with mkdir itself: only the
    successful creator finalizes its mode. An existing or competing leaf must
    pass lstat/type/owner/mode checks without following a link or changing it.
    This does not exclude later same-uid path replacement."""
    try:
        path.mkdir(parents=True, mode=0o700)
    except FileExistsError:
        pass  # validate the winner exactly as any already-existing leaf
    else:
        os.chmod(path, 0o700)
        return
    st = path.lstat()
    if not stat.S_ISDIR(st.st_mode):
        raise BackendUnavailable(
            f"refusing to use trigger socket directory {path}: not a real directory"
        )
    if st.st_uid != os.getuid():
        raise BackendUnavailable(
            f"refusing to use trigger socket directory {path}: owned by uid {st.st_uid}, "
            f"not this process's own uid {os.getuid()}"
        )
    if stat.S_IMODE(st.st_mode) != 0o700:
        raise BackendUnavailable(
            f"refusing to use trigger socket directory {path}: mode "
            f"{oct(stat.S_IMODE(st.st_mode))}, expected 0o700"
        )


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
    trigger_socket_host_path: Path | None = None,
    dns: str | None = None,
    wave_attachment: WaveAttachment | None = None,
) -> list[str]:
    """The full `docker run` argv. Pure - makes no call, mutates nothing. A
    FIXED, closed set of flags: there is no passthrough for arbitrary extra
    arguments, so nothing here can ever mount the docker socket, add
    `--privileged`, or otherwise widen the container (addendum item C12).
    `trigger_socket_host_path` (below) is the ONE deliberate, narrow
    exception the owner's 2026-10-03 ruling on #183 authorized. #621's
    `wave_attachment` adds one controller-owned NAMED volume at a fixed
    wave-state path; it accepts neither host paths nor caller-chosen targets.
    All other mounts and arbitrary flags remain refused.

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
    callers on either side of `execute()`. This reasoning is unchanged and
    still governs the workspace/home: `trigger_socket_host_path` mounts
    neither. It mounts exactly one host-owned Unix socket, read-write, at
    the single fixed in-container path `TRIGGER_SOCKET_PATH` - never a
    directory, never anything content-bearing the way a workspace or home
    bind mount would be, and the TARGET is never a parameter (#183's design
    doc §2c): there is no way to call this function and have it mount
    anywhere else. `None` (the default - every existing caller, every other
    backend construction) omits the flag entirely; the rest of this
    docstring's argv is then byte-for-byte what it was before #183.

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
        *(("--dns", dns) if dns is not None else ()),
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
    if trigger_socket_host_path is not None:
        argv += ["--mount", f"type=bind,source={trigger_socket_host_path},target={TRIGGER_SOCKET_PATH}"]
    if wave_attachment is not None:
        argv += wave_attachment.mount_args()
    argv += [
        "-w", CONTAINER_WORKSPACE,
        "-e", f"HOME={CONTAINER_HOME}",
        *_env_args({**env, **(wave_attachment.environment() if wave_attachment else {})}),
        "--", image, *subject_argv,
    ]
    return argv


#: `prepare()`'s placeholder main command: never the real subject. The real
#: argv is not known until `execute()` is called, so the container is
#: started keeping itself alive, and `install()`/`execute()` act on it
#: afterward through `docker cp`/`docker exec` (see the module docstring).
_KEEPALIVE_ARGV: tuple[str, ...] = ("sleep", "infinity")

#: #317: the per-call token `execute()` passes as `$0` of a no-op prelude,
#: `sh -c 'exec "$@"' TOKEN ARGV`. It writes nothing anywhere; it only makes
#: this call's exec identifiable in the daemon's own event record, which the
#: subject can neither write nor erase.
_EXEC_TOKEN_PREFIX = "skillc-exec-"

#: Upper bound on the `docker events` answer read for one decision. Past it the
#: answer is "unknown" and the real result stands.
_EXEC_EVENTS_MAX_BYTES = 1024 * 1024

#: How much earlier than the controller's own window start `--since` reaches.
#: The decision orders events by the DAEMON's clock only; controller time just
#: chooses where to start reading, generously.
_EXEC_EVENTS_SINCE_MARGIN_NS = 2_000_000_000

#: Wall-clock nanoseconds for the event window, bound at import: the window is
#: compared against the daemon's own `timeNano`, so it must stay real time even
#: where a caller replaces this module's `time` for its own pacing.
_wall_ns = time.time_ns

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


def _clean_write_probe_result(returncode: int, stderr: bytes) -> bool | None:
    """The pure decision `candidate_can_write_in_attempt` makes from a
    completed `test -w` exec - extracted so the exact boundary (counter-
    model review finding: a signal-killed exec, e.g. 137 for SIGKILL, can
    exit outside `test`'s own `{0, 1}` vocabulary while still leaving
    stderr empty) is directly testable with synthetic inputs, no
    subprocess or Docker needed. `test` itself exits exactly 0 (writable)
    or 1 (not writable) and writes nothing to stderr either way; any
    OTHER exit code, or any stderr output at all, means something other
    than a clean test happened and must read as `None` (unverifiable),
    never guessed as a confident `False`."""
    if returncode not in (0, 1):
        return None
    if stderr:
        # ANY stderr at all, not merely non-whitespace content (counter-
        # model review finding): a genuinely clean `test -w` writes
        # EXACTLY zero bytes on either outcome, so even a lone newline is
        # evidence something else happened, never an ordinary trailing
        # newline to tolerate.
        return None
    return returncode == 0


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


def _owned_tar_dirs(arcnames: Sequence[str]) -> bytes:
    """A tar stream of DIRECTORY entries only, each candidate-owned mode
    0755, in the given order (parents first) - #393's missing-parent
    delivery. Never pass a directory that already exists in the container:
    extracting a directory entry over an existing one rewrites ITS owner and
    mode (verified on a real daemon), which is why `install()` sends only
    the parents its existence probe reported absent."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for arcname in arcnames:
            info = tarfile.TarInfo(name=arcname)
            info.type = tarfile.DIRTYPE
            info.mode = 0o755
            tar.addfile(_owned_tarinfo(info))
    return buf.getvalue()


def _missing_parent_candidates(keys: Sequence[str]) -> list[str]:
    """Every proper ancestor directory of every key, relative, parents
    before children and each once: `tests/unit/x.py` -> `tests`,
    `tests/unit`. A top-level key contributes nothing."""
    ancestors: set[str] = set()
    for key in keys:
        parents = PurePosixPath(key).parents
        ancestors.update(str(p) for p in parents if str(p) != ".")
    return sorted(ancestors, key=lambda a: (a.count("/"), a))


class _BoundedDrain:
    """Drains `pipe` (stdout or stderr - one instance each) to EOF on its own
    thread, so the subject can never block on a full pipe buffer - the
    classic two-pipe deadlock `execute()`'s own docstring documents - while
    retaining at most `cap` bytes of it (#102: the pre-fix drain for EACH
    stream appended every chunk to an unbounded `list[bytes]`, so a subject
    that wrote continuously to either one could exhaust the HOST
    controller's memory before `limits.timeout` ever fired, a
    resource-exhaustion path independent of any container-side memory
    limit).

    `total_bytes` counts every byte read off the pipe, retained or not, so a
    caller always learns the subject's true output size even when most of it
    was discarded. Bytes past the cap are read and thrown away, never kept
    and never re-requested - the point is exactly to stop retaining without
    ever stopping draining.

    `run()` reads with `os.read()` on the raw fd, not `IO.read()` (issue
    #189): `read(size)` on a non-interactive stream may issue MULTIPLE
    underlying reads to fill the full requested size, blocking until either
    that much data arrives or EOF - so a subject that writes some data
    (under one read's worth) and then leaves the pipe open without writing
    more or closing it was never captured at all, silently, however long
    the caller's own join timeout later gives this thread to finish.
    `os.read(fd, size)` is one raw syscall: it returns whatever is
    currently available (possibly less than requested), only blocking when
    truly nothing has arrived yet, and returns `b""` at EOF exactly like
    `IO.read()` does - a caller whose join times out before EOF still sees
    whatever was written and delivered so far, matching what
    `stdout_incomplete`/`stderr_incomplete` already promise: an incomplete,
    partial capture, never a silently empty one. (`IO[bytes]`, this class's
    own `pipe` type, declares `read()` but not `read1()` - `fileno()` is
    the portable way to reach the same one-syscall behavior without
    narrowing that type.)"""

    def __init__(self, pipe: IO[bytes], cap: int, status_record_max: int = 0) -> None:
        self._pipe = pipe
        self._cap = cap
        self._chunks: list[bytes] = []
        self._captured_len = 0
        self.total_bytes = 0
        self.truncated = False
        # #338: when `status_record_max` > 0, the stream's first line (at
        # most that many bytes, newline included) is a wrapper-owned status
        # record, taken into `status_record` and never into the retained
        # capture, `total_bytes` or the cap - so a gate's own retention cap
        # (even 0) can never cost the status, and the status can never be
        # mistaken for, or displace, the gate's own output.
        self._status_max = status_record_max
        self._status_buf = b""
        self.status_record: bytes | None = None
        self.status_overflowed = False

    def _take_status(self, chunk: bytes) -> bytes:
        """Moves leading bytes into the status slot until a newline or the
        bound; returns whatever of `chunk` is past the record."""
        self._status_buf += chunk
        newline = self._status_buf.find(b"\n", 0, self._status_max)
        if newline >= 0:
            self.status_record = self._status_buf[:newline + 1]
            rest = self._status_buf[newline + 1:]
        elif len(self._status_buf) >= self._status_max:
            self.status_record = self._status_buf[:self._status_max]
            self.status_overflowed = True
            rest = self._status_buf[self._status_max:]
        else:
            return b""
        self._status_buf = b""
        return rest

    def run(self) -> None:
        while chunk := os.read(self._pipe.fileno(), 65536):
            if self._status_max and self.status_record is None:
                chunk = self._take_status(chunk)
                if not chunk:
                    continue
            self.total_bytes += len(chunk)
            if self._captured_len >= self._cap:
                self.truncated = True
                continue
            remaining = self._cap - self._captured_len
            if len(chunk) > remaining:
                chunk = chunk[:remaining]
                self.truncated = True
            self._chunks.append(chunk)
            self._captured_len += len(chunk)

    def captured_bytes(self) -> bytes:
        return b"".join(self._chunks)


def _confinement_status(drain: _BoundedDrain) -> str:
    """#338: `"ready"`, `"refused"`, `"missing"` or `"invalid"` for a
    confining exec's stderr drain. Only an EXACT leading record counts:
    an empty stream is `"missing"`; anything else - a partial line at EOF,
    a line past `CWD_CONFINEMENT_RECORD_MAX`, a `docker exec` client error
    that got there first, any other text - is `"invalid"`. Neither of
    those two can be read as a refusal or as a started gate."""
    record = drain.status_record
    if record is None:
        return "invalid" if drain._status_buf else "missing"
    if drain.status_overflowed:
        return "invalid"
    if record == CWD_CONFINEMENT_READY_RECORD:
        return "ready"
    if record == CWD_CONFINEMENT_REFUSED_RECORD:
        return "refused"
    return "invalid"


class HomeTreeTooLarge(Exception):
    """`read_home_tree` refuses rather than silently truncate (in the spirit
    of #102's bounded-capture rule): a directory this large is itself
    unexpected for a single trial's private home, and reading all of it
    into memory unconditionally is not safe. Distinct from
    `BackendUnavailable` - this is a population-too-large refusal, not an
    infrastructure failure."""


@dataclass(frozen=True)
class _Handle:
    """Opaque to the controller (backend.py's own rule): `attempt_id` and
    `name` are both derived from the attempt ID alone, so `str(handle)`
    (the dataclass default) never leaks a host path, uid or hostname. No
    `work_dir`/`home_dir` fields - the WORKSPACE and HOME are still never
    bind-mounted; that data moves by `docker cp`, exactly as before #183.
    `trigger_channel` (below) is the one exception elsewhere in this
    module (#183's one named mount), and it is excluded from `repr` for
    the same reason `env` is - see that field's own comment.

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
    already has to honor for uid/hostname/paths.

    `trigger_channel` is `None` for every attempt whose backend was not
    constructed with `trigger_decide` set (every caller before #183) -
    `repr=False` so a handle's string form never leaks the socket's
    host-side path (`DecideReplyChannel` itself does not override
    `__repr__`, but a handle must not rely on that staying true)."""

    attempt_id: str
    name: str
    env: Mapping[str, str] = field(repr=False)
    trigger_channel: DecideReplyChannel | None = field(default=None, repr=False)
    #: #442: this attempt's own internal network and egress proxy container,
    #: when the backend runs with `egress`; `None` otherwise.
    egress_network: str | None = None
    egress_proxy: str | None = None


def _unconfirmed_cleanup_note(reason: str, attempt_id: str) -> str:
    """#540: the clause a raising prepare() adds when its cleanup ran without
    the daemon's answer to `run -d`, so a create still in flight may land
    after it. Names the label a sweep can find that container by."""
    return (
        f"; {reason}, so a container it creates after this cleanup is not removed - "
        f"find it by label {ATTEMPT_LABEL_KEY}={attempt_id}"
    )


@dataclass(frozen=True)
class DockerBackend:
    """One `ExecutionBackend` per attempt lifecycle. `image` should be pinned
    by digest where possible (`name@sha256:...`), but a pin is only declared:
    `install()` asks the running container which image it was created from
    and reports that id as readiness `image_digest` (#12), so a tag
    republished after planning shows up as a different digest, not as the
    image the ledger names."""

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
    #: #183: opt-in, not a default, matching `disk_limit`'s own shape -
    #: every caller before #183 leaves this `None` and gets the exact same
    #: argv as before. When set, `prepare()` bind-mounts ONE host-owned
    #: Unix socket at `TRIGGER_SOCKET_PATH` and owns a `DecideReplyChannel`
    #: against it for each attempt's whole lifetime; `trigger_log()`
    #: retrieves the finalized log. See `docs/specs/evaluation-facility/
    #: decide-reply-channel.md`.
    trigger_decide: DecideFn | None = field(default=None, repr=False)
    #: Gate witnessing must not change the capture population through its own
    #: observations/PID bookkeeping. Default probe write-back stays unchanged.
    witness_io: bool = False
    runtime_supply: rs.RuntimeSupply | None = field(default=None, repr=False)
    #: #442: provider-only egress for a LIVE agent container. When set, the
    #: attempt's container joins only its own `--internal` network, with no DNS
    #: and the per-attempt allowlisting proxy's address in its proxy env;
    #: `network` is then not used for it (`egress.py`). Grading and scripted
    #: containers leave this False and keep `network` (default "none").
    egress: bool = False
    #: The hosts the egress proxy forwards to. Production never sets this:
    #: the default IS the measured allowlist. Only the real-Docker control's
    #: `allow-all` break widens it, to prove the denial check can fail.
    egress_hosts: tuple[str, ...] = eg.ALLOWED_HOSTS
    #: #460: how long `prepare()` waits for the egress proxy to accept
    #: connections before refusing the attempt. Without the wait, a proxy slower
    #: to start than the agent container refuses the agent's first CONNECTs.
    egress_ready_seconds: float = 30.0
    #: Host-side directory for #183's socket files - see
    #: `DEFAULT_TRIGGER_SOCKET_DIR`'s own comment for why this is NOT
    #: `base_dir`. `repr=False`: a host filesystem path, same reasoning as
    #: `env`.
    trigger_socket_dir: Path = field(default=DEFAULT_TRIGGER_SOCKET_DIR, repr=False)
    #: #508: environment applied to the AGENT's own `docker exec` only
    #: (`execute()`), read when it launches - the project-gate witness puts its
    #: `make` shim directory first on the agent's PATH this way. Controller
    #: execs (`exec_in_attempt`, `controller_output`) never receive it, so a
    #: controller-run gate never re-enters the shim. `None` keeps every
    #: earlier caller's argv unchanged.
    agent_exec_env: Callable[[], Mapping[str, str]] | None = field(default=None, repr=False)
    #: #621: one closed named-volume mount, created and retired by the wave controller.
    wave_attachment: WaveAttachment | None = None

    def describe(self) -> BackendDescription:
        version = probe_daemon(self.docker_bin, self.daemon_timeout, _docker_env())
        return BackendDescription(
            name="docker",
            version=version or "unreachable",
            isolation=(
                "container (pid/mount/network namespaces)",
                ("network: a per-attempt --internal network, no DNS; egress only through the "
                 f"per-attempt proxy to {', '.join(self.egress_hosts)}:443 (#442; client-side fetches only - "
                 "server-side tools are closed by the client's declared flags and the transcript census)"
                 if self.egress else
                 f"network={self.network} by default" if self.network == "none"
                 else f"network={self.network}: egress OPEN (no egress policy set)"),
                f"fixed non-root user {_container_user()} ({CANDIDATE_USER_NAME}), independent of the host caller",
                "resource limits enforced: memory, memory-swap (equal), pids, cpus, shm-size",
                (f"disk: --storage-opt size={self.disk_limit}" if self.disk_limit is not None
                 else "disk: no per-container bound set (disk_limit is None)"),
                f"every container labeled {OWNER_LABEL_KEY}={OWNER_LABEL_VALUE} and {ATTEMPT_LABEL_KEY}=<attempt id>",
                f"sandbox: {SANDBOX_MODE}",
                "no docker socket, no docker binary, no passthrough flags in the composed argv",
                ("one persistent container per attempt (docker run -d at prepare()); "
                 "install()/execute() act on it via docker cp/docker exec - no bind mount, "
                 "no shared volume, no second container" if self.wave_attachment is None else
                 "one role container with private workspace, home and PID namespace; controller-owned "
                 "wave-state named volume mounted at a fixed path; wave controller owns shared topology"),
            ),
            unobserved=(
                *(("wave shared-state delivery and peer network isolation require real-daemon qualification",)
                  if self.wave_attachment is not None else ()),
                *(("network egress actually blocked - not verified from inside the container",)
                  if self.network == "none" and not self.egress else ()),
                *((("egress restriction verified only by the real-Docker live controls (#442), not on "
                    "every attempt; the proxy log of each attempt is captured as evidence"),)
                  if self.egress else ()),
                "file reads by candidate code",
                ("credential confidentiality against an ancestor's /proc/<pid>/environ - "
                 "the verifier's own boundary (verify.py's probe through this same seam)"),
                ("the live daemon boundary itself - tested here only against a fake docker "
                 "CLI (tests/fixtures/docker-backend/fake_docker.py), never a real daemon; "
                 "that remains owed to the operator's live run (#10)"),
                ("a disk bound actually enforced - --storage-opt size= is refused outright "
                 "by any storage driver other than overlay2 on a compatible backing "
                 "filesystem, so a set disk_limit is a request, not a guarantee"),
                ("whether a live daemon actually delivers a forwarded TERM to the exec'd "
                 "subject and lets it act on it - issue #158's in-container supervisor "
                 "(skillc-supervisor/skillc-wrap) and the capability gate that activates it "
                 "are implemented and tested against the fake docker CLI, but TWO things are "
                 "held pending the operator's #150 discriminating run: the #78 Dockerfile "
                 "change that bakes the two scripts in, and _keepalive_run_argv's own switch "
                 "from sleep infinity to the supervisor - the gate requires BOTH the wrap "
                 "binary and a running supervisor's control socket, so it reports unavailable "
                 "until both land, not merely the first. Even once they do, this is owed to a "
                 "live daemon the same way the rest of this list is (#10) - never simulated "
                 "here. ExecuteResult.term_forwarding reports what the HOST observed for a "
                 "given attempt (capability present or not, and whether the subject was gone "
                 "before escalation), never a trusted claim about what the container itself "
                 "did - see that field's own docstring for why an in-container report is "
                 "forgeable by the subject it would describe"),
                ("dependency resolution inside the container - install() copies in any "
                 "declared surface entry naming an existing host path or carrying raw "
                 "bytes; it does not run a package manager or resolve a dependency closure"),
                ("baseline_absence's own content check - it compares declared entry NAMES "
                 "against a top-level listing of the container's workspace taken before any "
                 "copy, so a same-named file whose CONTENT differs from what the image "
                 "already shipped is not distinguished from one this attempt genuinely "
                 "installed; only the name-level contamination case is caught (issue #133 "
                 "item 4)"),
            ),
        )

    def _keepalive_run_argv(
        self, name: str, attempt_id: str, trigger_socket_host_path: Path | None = None,
        *, network: str | None = None, extra_env: Mapping[str, str] | None = None, dns: str | None = None,
    ) -> list[str]:
        """`prepare()`'s `docker run -d` argv: `compose_run_argv`'s own
        composed flags (identity, network, resource limits, ownership
        labels), with the placeholder `_KEEPALIVE_ARGV` in place of a real
        subject, detached (`-d`), and with `--rm` removed - this container's
        teardown is owned explicitly by `destroy()`/`confirm_absent()`, and
        Docker's own auto-removal on exit would otherwise race `export()`
        after a forced `docker kill` (see `execute()`/`_stop()`).
        `trigger_socket_host_path` is #183's one named exception - see
        `compose_run_argv`'s own docstring; `None` (every caller before
        #183) changes nothing here."""
        argv = compose_run_argv(
            docker_bin=self.docker_bin, image=self.image, name=name, attempt_id=attempt_id,
            subject_argv=_KEEPALIVE_ARGV, env={**self.env, **(extra_env or {})},
            network=self.network if network is None else network, memory=self.memory,
            pids_limit=self.pids_limit, cpus=self.cpus, shm_size=self.shm_size,
            container_user=_container_user(), disk_limit=self.disk_limit,
            trigger_socket_host_path=trigger_socket_host_path, dns=dns,
            wave_attachment=self.wave_attachment,
        )
        argv.insert(argv.index("run") + 1, "-d")
        argv.remove("--rm")
        return argv

    def prepare(self, attempt_id: str) -> object:
        """Step 3: start this attempt's one persistent container, detached,
        running the keep-alive placeholder. Raises `BackendUnavailable` -
        never returns a handle - when the daemon is unreachable, the image is
        not present locally, or the `docker run` itself fails or stalls.

        Docker creates a container before it starts it, so a failed START
        (an image missing the placeholder binary, say) can still leave one
        behind - and `--rm` cannot save us here, since `_keepalive_run_argv`
        deliberately drops it (see that method's own docstring). A raising
        `prepare()` must not leave a partial resource behind
        (`backend.ExecutionBackend.prepare`'s own stated contract) - found by
        cross-model review, which named the pre-fix code an actual violation
        of that already-merged contract, not merely a hardening opportunity.

        BOUNDED, WITH AN EXPLICIT IMAGE PRECHECK (issue #133 item 1): `docker
        run -d` used to carry no `timeout=` at all, unlike every other daemon
        call in this module - and unlike those, a missing local image makes it
        implicitly PULL over the network mid-call, which can run far longer
        than any reasonable per-call bound before the CLI even attempts to
        create a container. `docker image inspect` (bounded by
        `daemon_timeout`, like every other read here) runs FIRST and refuses
        outright when the image is not already present locally, so `run -d`
        itself never has a pull to wait on and can safely carry the same
        bound as the rest of this module. A `run -d` that still exceeds it -
        daemon overload, not a pull - is read exactly like a nonzero exit: the
        best-effort `rm -f` cleanup below runs either way, itself bounded, and
        `prepare()` raises rather than returning a handle for a container this
        call cannot confirm the state of. After a timeout, that cleanup waits
        for the daemon's answer first (`_run_awaiting_answer`, issue #540), so
        a create still in flight cannot land behind it."""
        env = _docker_env()
        if probe_daemon(self.docker_bin, self.daemon_timeout, env) is None:
            raise BackendUnavailable(f"docker daemon unreachable via {' '.join(self.docker_bin)!r}")
        if not self._image_present_locally(env):
            raise BackendUnavailable(
                f"image {self.image!r} is not present locally; refusing rather than letting "
                f"'docker run -d' pull it mid-trial with no bound on how long that takes"
            )
        name = _container_name(attempt_id)
        egress_network: str | None = None
        egress_proxy: str | None = None
        egress_args: dict[str, object] = {}
        if self.egress:
            egress_network, egress_proxy, proxy_ip = self._start_egress(name, attempt_id, env)
            egress_args = {"network": egress_network, "extra_env": eg.agent_proxy_env(proxy_ip),
                           "dns": eg.AGENT_DNS}
        channel: DecideReplyChannel | None = None
        try:
            channel, trigger_socket_host_path = self._start_trigger_channel(name, attempt_id)
            argv = self._keepalive_run_argv(name, attempt_id, trigger_socket_host_path, **egress_args)  # type: ignore[arg-type]
        except BaseException:
            # #442: egress is already up; nothing between acquiring it and
            # handing back a handle may strand it - a refused channel, an
            # invalid argv value, an interrupt. The original exception stands.
            if channel is not None:
                channel.close()
            self._stop_egress(egress_proxy, egress_network, env)
            raise
        try:
            started, timed_out, answered = self._run_awaiting_answer(argv, env)
        except OSError as exc:
            # Best-effort: whether or not a container was actually created,
            # this makes sure none is left behind under this name. Also
            # bounded - a cleanup call that itself hangs must not turn a
            # raising prepare() into a hanging one. The channel's own
            # listener is torn down too (`close()`, idempotent) - a raising
            # prepare() must not leave a partial resource behind, and a
            # socket with nothing ever going to mount it is exactly that.
            if channel is not None:
                channel.close()
            cleanup_note = self._best_effort_rm(name, env) + self._stop_egress(egress_proxy, egress_network, env)
            raise BackendUnavailable(
                f"docker run failed to start a container for {attempt_id!r}: {exc}{cleanup_note}"
            ) from exc
        except BaseException:
            # #442: an interrupt mid-`run` still removes what this call made.
            if channel is not None:
                channel.close()
            self._best_effort_rm(name, env)
            self._stop_egress(egress_proxy, egress_network, env)
            raise
        if timed_out is not None:
            # #540: the cleanup runs only once the daemon has answered, so a
            # create still in flight cannot land after it. A daemon that never
            # answered leaves that unconfirmable, and the message says so.
            if channel is not None:
                channel.close()
            cleanup_note = self._best_effort_rm(name, env)
            if not answered:
                cleanup_note += _unconfirmed_cleanup_note(
                    f"the daemon did not answer 'docker run -d' within a further {self.daemon_timeout}s", attempt_id,
                )
            cleanup_note += self._stop_egress(egress_proxy, egress_network, env)
            raise BackendUnavailable(
                f"docker run failed to start a container for {attempt_id!r}: {timed_out}{cleanup_note}"
            ) from timed_out
        assert started is not None
        if started.returncode != 0:
            if channel is not None:
                channel.close()
            cleanup_note = self._best_effort_rm(name, env)
            if not answered:
                cleanup_note += _unconfirmed_cleanup_note(
                    f"the 'docker run -d' CLI was ended by signal {-started.returncode} before the daemon answered",
                    attempt_id,
                )
            cleanup_note += self._stop_egress(egress_proxy, egress_network, env)
            raise BackendUnavailable(
                f"docker run failed to start a container for {attempt_id!r}: {started.stderr.strip()}{cleanup_note}"
            )
        return _Handle(attempt_id=attempt_id, name=name, env=env, trigger_channel=channel,
                       egress_network=egress_network, egress_proxy=egress_proxy)

    def _egress_call(self, argv: list[str], env: Mapping[str, str], what: str) -> str:
        """One bounded daemon call for #442's egress setup; raises
        `BackendUnavailable` naming `what` on any failure, else returns stdout."""
        try:
            done = subprocess.run(argv, capture_output=True, text=True, env=env, check=False,
                                  timeout=self.daemon_timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise BackendUnavailable(f"egress setup failed to {what}: {exc}") from exc
        if done.returncode != 0:
            raise BackendUnavailable(f"egress setup failed to {what}: {done.stderr.strip()}")
        return done.stdout

    def _start_egress(self, name: str, attempt_id: str, env: Mapping[str, str]) -> tuple[str, str, str]:
        """#442: the attempt's internal network and its allowlisting proxy,
        joined to it. Returns `(network, proxy container, proxy address on the
        network)`. Whatever this call created is removed again before it
        raises - a refused prepare() leaves no network and no proxy behind."""
        network, proxy = eg.network_name(name), eg.proxy_name(name)
        labels = {OWNER_LABEL_KEY: OWNER_LABEL_VALUE, ATTEMPT_LABEL_KEY: attempt_id}
        # Marked BEFORE each call: a create that takes effect but whose answer is
        # lost or late (a timeout) still leaves the object behind, so cleanup
        # must try it. Removing something that was never made is harmless.
        created_network = created_proxy = False
        try:
            created_network = True
            self._egress_call(eg.create_network_argv(self.docker_bin, network, labels), env,
                              f"create internal network {network}")
            subnet = self._egress_call(eg.network_subnet_argv(self.docker_bin, network), env,
                                       f"read {network}'s subnet").strip()
            try:
                ipaddress.ip_network(subnet)
            except ValueError as exc:
                raise BackendUnavailable(f"egress network {network} has no usable subnet: {subnet!r}") from exc
            created_proxy = True  # `run -d` can create a container even when it fails to start
            self._egress_call(eg.proxy_run_argv(self.docker_bin, image=self.image, name=proxy, labels=labels,
                                                container_user=_container_user(), subnet=subnet,
                                                hosts=self.egress_hosts),
                              env, f"start egress proxy {proxy}")
            self._egress_call(eg.network_connect_argv(self.docker_bin, network, proxy), env,
                              f"connect {proxy} to {network}")
            address = self._egress_call(eg.proxy_address_argv(self.docker_bin, network, proxy), env,
                                        f"read {proxy}'s address on {network}").strip()
            if not re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", address):
                raise BackendUnavailable(f"egress proxy {proxy} has no IPv4 address on {network}: {address!r}")
            self._await_proxy_ready(proxy, env)
        except BackendUnavailable as exc:
            note = self._stop_egress(proxy if created_proxy else None, network if created_network else None, env)
            raise BackendUnavailable(f"{exc}{note}") from exc
        except BaseException:
            # Anything else - an interrupt, a bug - still removes what was
            # made, and the original exception propagates unchanged.
            self._stop_egress(proxy if created_proxy else None, network if created_network else None, env)
            raise
        return network, proxy, address

    def _await_proxy_ready(self, proxy: str, env: Mapping[str, str]) -> None:
        """#460: return only once the proxy accepts TCP connections, probed from
        inside its own container (a loopback peer, which the proxy does not
        log). Refuses with `BackendUnavailable` after `egress_ready_seconds`,
        naming the last probe's error; `_start_egress` then removes the proxy
        and network as for any other setup failure."""
        deadline = time.monotonic() + self.egress_ready_seconds
        last = "no probe ran"
        while True:
            # Every probe and pause is capped at what is left of the budget, so
            # a hanging `docker exec` cannot carry the wait past it (#460
            # counter-model review).
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise BackendUnavailable(f"egress proxy {proxy} did not accept connections within "
                                         f"{self.egress_ready_seconds:g}s (last probe: {last})")
            try:
                done = subprocess.run(eg.proxy_ready_argv(self.docker_bin, proxy), capture_output=True, text=True,
                                      env=env, check=False, timeout=min(self.daemon_timeout, remaining))
            except (OSError, subprocess.TimeoutExpired) as exc:
                last = str(exc)
            else:
                if done.returncode == 0:
                    return
                last = (done.stderr.strip().splitlines() or [f"exit {done.returncode}"])[-1]
            time.sleep(max(0.0, min(0.2, deadline - time.monotonic())))

    def _stop_egress(self, proxy: str | None, network: str | None, env: Mapping[str, str]) -> str:
        """Best-effort, bounded removal of #442's proxy container and network.
        Returns "" when everything named was removed, else a clause saying
        what was left behind - never raises."""
        notes = []
        if proxy is not None:
            note = self._best_effort_rm(proxy, env)
            if note:
                notes.append(note)
        if network is not None:
            try:
                removed = subprocess.run(eg.remove_network_argv(self.docker_bin, network), capture_output=True,
                                         text=True, env=env, check=False, timeout=self.daemon_timeout)
            except (OSError, subprocess.TimeoutExpired) as exc:
                notes.append(f"; cleanup 'docker network rm {network}' also failed: {exc}")
            else:
                if removed.returncode != 0 and "not found" not in removed.stderr.lower():
                    notes.append(f"; cleanup 'docker network rm {network}' also failed: {removed.stderr.strip()}")
        return "".join(notes)

    def egress_log(self, handle: object) -> bytes | None:
        """#442: the attempt's proxy log as the proxy wrote it, read while the
        proxy is still running (before `destroy()`). `None` when this attempt
        has no proxy or the log could not be read - never empty bytes standing
        in for "could not read"."""
        assert isinstance(handle, _Handle)
        if handle.egress_proxy is None:
            return None
        try:
            done = subprocess.run(eg.proxy_log_argv(self.docker_bin, handle.egress_proxy), capture_output=True,
                                  env=handle.env, check=False, timeout=self.daemon_timeout)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return done.stdout if done.returncode == 0 else None

    def _run_awaiting_answer(
        self, argv: list[str], env: Mapping[str, str],
    ) -> tuple[subprocess.CompletedProcess[str] | None, subprocess.TimeoutExpired | None, bool]:
        """prepare()'s `run -d`, bounded by `daemon_timeout`. Returns
        `(completed, None, True)` within the bound, else `(None, timeout,
        answered)`.

        Issue #540: `run -d` is create-then-start in one CLI call, and killing
        the CLI at its bound does not stop a create the daemon is still
        working on. The cleanup that followed found "No such container", and
        the create landed after it: kyle19's never-started
        `skillc-a-live-conformance-fbba8d601e10`. So a timed-out call is given
        one further `daemon_timeout` to return. Once it has, the daemon has
        settled whether NAME exists, and the caller's `rm -f` is reliable.
        `answered` is False when it did not return then either (the CLI is
        killed), or when something else ended it by a signal in either window;
        either way the caller cannot confirm its cleanup."""
        proc = subprocess.Popen(
            argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
        )
        try:
            try:
                stdout, stderr = proc.communicate(timeout=self.daemon_timeout)
            except subprocess.TimeoutExpired:
                timed_out = subprocess.TimeoutExpired(argv, self.daemon_timeout)
                try:
                    proc.communicate(timeout=self.daemon_timeout)
                except subprocess.TimeoutExpired:
                    return None, timed_out, False
                # A CLI ended by a signal never heard the daemon's answer, so
                # its exit says nothing about whether the create has settled.
                return None, timed_out, proc.returncode >= 0
            return subprocess.CompletedProcess(argv, proc.returncode, stdout, stderr), None, proc.returncode >= 0
        finally:
            if proc.poll() is None:
                # Reap without draining: a pipe held open by anything the CLI
                # left behind must not turn this bounded call into a hang.
                proc.kill()
                proc.wait()
            for stream in (proc.stdout, proc.stderr):
                if stream is not None:
                    stream.close()

    def _best_effort_rm(self, name: str, env: Mapping[str, str]) -> str:
        """prepare()'s failure-path cleanup: make sure no container is left
        behind under `name`, bounded like every other daemon call. Returns ""
        when the call completed, else a clause for the `BackendUnavailable`
        message. Issue #416: the call used to be unguarded, so a cleanup that
        HIT its bound raised `TimeoutExpired` out of prepare() in place of the
        `BackendUnavailable` its contract promises - on exactly the slow daemon
        the cleanup exists for. A nonzero exit is reported too, except "No such
        container": `run` that failed before creating one is the ordinary case,
        and a daemon that cannot remove a container it DID create is not."""
        try:
            removed = subprocess.run(
                [*self.docker_bin, "rm", "-f", name],
                capture_output=True, text=True, env=env, check=False, timeout=self.daemon_timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return f"; cleanup 'docker rm -f {name}' also failed: {exc}"
        if removed.returncode != 0 and "No such container" not in removed.stderr:
            return f"; cleanup 'docker rm -f {name}' also failed: exit {removed.returncode}: {removed.stderr.strip()}"
        return ""

    def _start_trigger_channel(
        self, name: str, attempt_id: str,
    ) -> tuple[DecideReplyChannel | None, Path | None]:
        """#183: when `self.trigger_decide` is set, create and BIND the
        attempt's socket on the host BEFORE `docker run -d` ever runs -
        required ordering, not a convenience: a bind mount of a Unix socket
        captures the inode that exists at mount time, so the real socket
        must already exist at `trigger_socket_host_path` before the
        container that mounts it is created, or the container would
        either fail to start (no such source path) or - on a Docker
        version that creates a placeholder - mount an empty regular file
        that this channel could never `bind()` over afterward without the
        mount itself going stale (the same write-then-rename hazard
        `CLAUDE.md`'s credential-freshness section documents for a
        single-file mount, applied here to socket creation instead of
        rotation). Returns `(None, None)` when no channel is configured -
        every caller before #183, and the argv this produces downstream is
        then unchanged (`compose_run_argv`'s own docstring)."""
        if self.trigger_decide is None:
            return None, None
        trigger_socket_host_path = trigger_socket_host_path_for(self.trigger_socket_dir, name)
        _ensure_private_trigger_dir(trigger_socket_host_path.parent)
        # retain_socket_path (#394): finalizing the log (`trigger_log()`,
        # which the gate witness calls right after the confirmed stop) must
        # not delete this container's bind-mount source - every later
        # `docker cp` against the stopped container, the capture export
        # included, would then fail. `destroy()` removes it after the
        # container is gone.
        channel = DecideReplyChannel(
            trigger_socket_host_path, self.trigger_decide, attempt_id, socket_mode=TRIGGER_SOCKET_MODE,
            retain_socket_path=True,
        )
        channel.start()
        return channel, trigger_socket_host_path

    def trigger_dropped(self, handle: object) -> int | None:
        """#434: how many connections this attempt's channel closed before its
        `decide` saw a request; `None` when there is no channel at all."""
        assert isinstance(handle, _Handle)
        if handle.trigger_channel is None:
            return None
        return handle.trigger_channel.dropped_connections()

    def trigger_log(self, handle: object) -> list[LoggedDecision] | None:
        """#183: the finalized decide-and-reply log for this attempt.
        `None` means "this backend has no channel at all" (`trigger_decide`
        was never set) - a fact about CONFIGURATION, never about what
        happened during the attempt. A caller that DID configure a channel
        and still wants the `no-controller-witness` / `witnessed` / `
        channel-unavailable` three-way read builds its own
        `decide_reply_channel.TrustedLog` from this method's return value
        (an empty, non-`None` list is the bypass case - see that module's
        own `TrustedLog.witnessed`). Idempotent: safe to call more than
        once, and after `destroy()` has already closed the channel -
        `DecideReplyChannel.log_or_finalize()`'s own idempotence, not
        reimplemented here."""
        assert isinstance(handle, _Handle)
        if handle.trigger_channel is None:
            return None
        return handle.trigger_channel.log_or_finalize()

    def _image_present_locally(self, env: Mapping[str, str]) -> bool:
        """Whether `self.image` already exists in the local image store,
        bounded by `daemon_timeout` like every other read in this module. A
        timeout, an unreachable daemon, or a nonzero exit are all treated the
        same as "not present" - `prepare()` refuses either way, rather than
        risking `docker run -d`'s own implicit pull on an ambiguous answer."""
        try:
            proc = subprocess.run(
                [*self.docker_bin, "image", "inspect", self.image],
                capture_output=True, env=env, check=False, timeout=self.daemon_timeout,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return proc.returncode == 0

    def _forwarding_available(self, handle: _Handle, probe_token: str | None = None) -> bool:
        """Whether THIS container can actually forward a TERM right now
        (issue #158's capability gate, design doc section 2d) - checked
        against the running container itself, via `docker exec`, never
        assumed from `self.image`'s name or any label.

        BOTH the wrap binary AND the supervisor's control socket must be
        present (review must-fix, PR #182) - `test -x` alone is not enough.
        In this PR, `prepare()` still starts every container with
        `_KEEPALIVE_ARGV` (`sleep infinity`), never the supervisor - that
        switch belongs with the held image change (section 3), not here -
        so even an image that carries `skillc-wrap` has nothing listening
        on `SKILLC_CONTROL_SOCKET_PATH` yet. Checking only the binary would
        report "available" for a capability nothing can actually use: the
        argv gets prefixed, the wrapper's own registration attempt finds no
        socket, and every stop reports `killed-at-escalation` - forwarding
        that production can never produce, exactly the excess-capability
        shape issue #176 already named once for the fake CLI's `cmd_kill`.
        One `sh -c` call keeps this a single bounded exec rather than two.

        Bounded by `daemon_timeout` like every other read in this module.
        A timeout, an unreachable daemon, or a nonzero exit (either check
        genuinely fails, OR any docker-side error this call cannot tell
        apart from that) are all treated the same as "not available" -
        `execute()` falls back to today's exact argv either way, rather
        than risking a 127 on an ambiguous answer. This is the same
        fail-open posture `skillc-wrap` itself uses if it cannot reach the
        supervisor - absence of certainty is never treated as presence."""
        probe = _FORWARDING_PROBE_SCRIPT
        token_arg = [probe_token] if probe_token is not None else []
        try:
            proc = subprocess.run(
                [*self.docker_bin, "exec", "--", handle.name, "sh", "-c", probe, *token_arg],
                capture_output=True, env=handle.env, check=False, timeout=self.daemon_timeout,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return proc.returncode == 0

    def install(self, handle: object, surface: Mapping[str, object], root: str | None = None) -> dict[str, object]:
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
        DockerBackend honours SURFACE_EXECUTABLE_KEY for bytes-backed files.
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
        the host file is actually owned by.

        NESTED PARENTS (#393): the tar stream for key `tests/x.py` names
        the file but not `tests/`, and `docker cp` creates a missing parent
        itself, owned by ROOT - the candidate could edit `x.py` but never
        add a file beside it. So before any entry is copied, one read-only
        probe (`_absent_parents`) asks which ancestors of the copied keys
        do not exist yet, and exactly those are delivered first as
        candidate-owned directory entries (`_owned_tar_dirs`). Only the
        absent ones: a directory entry extracted over an EXISTING directory
        rewrites its owner and mode, so existing directories are never
        sent. This works whoever owns `root` (a plain image's `/work` is
        root-owned, so creating the parents AS the candidate would not).
        A probe that cannot answer raises `BackendUnavailable`; a surface
        with no nested keys makes no probe.

        PER-ENTRY READINESS (issue #133 item 4): `discovery_canary` used to
        be all-or-nothing - VIOLATED only when NOTHING installed, so one
        missing entry among several was invisible whenever at least one
        other entry succeeded. `readiness["entries"]` now names every
        declared entry's own outcome (`installed`, `missing` - a `str`/`Path`
        value that does not resolve to an existing host file, the real bug
        this item exists to surface - or `not-a-path` - a value that was
        never meant to be copied, like `SURFACE_EXECUTABLE_KEY`'s metadata
        list, and must not be confused with a missing file), and
        `discovery_canary` is SATISFIED only when something was declared,
        something was installed, AND no entry is `missing`.

        BASELINE INSPECTION (issue #133 item 4): before any entry is copied,
        `_workspace_baseline` lists what `CONTAINER_WORKSPACE` already holds
        - the image's own contents, never this attempt's own installs, since
        nothing has been copied yet. Any declared key already present there
        is a pre-seeded skill this run did not actually install, and
        `baseline_absence` reports it VIOLATED rather than the previous
        permanent, unverified SATISFIED. The listing itself can fail (an
        unreachable daemon) independently of every later `docker cp`, in
        which case `baseline_absence` is UNKNOWN, never a guessed SATISFIED -
        the same "UNKNOWN never reaps" posture `confirm_stopped()` already
        holds elsewhere in this module.

        `root` (#332 follow-up) names the destination directory surface
        entries install under - `None` (every existing caller) means
        `CONTAINER_WORKSPACE`, unchanged. A caller installing somewhere
        else (#334's profile closure into the agent's home directory, say)
        passes it explicitly; the baseline inspection and canary plant
        below are scoped to the SAME `root`, since "already present" and
        "the attempt's own install" only mean something relative to one
        directory."""
        assert isinstance(handle, _Handle)
        effective_root = root if root is not None else CONTAINER_WORKSPACE
        nonce = surface.get(CANARY_NONCE_KEY)
        declared = {k: v for k, v in surface.items() if k != CANARY_NONCE_KEY}

        baseline, baseline_observed = self._workspace_baseline(handle, root=effective_root)
        preexisting = sorted(k for k in declared if k in baseline)

        entries: dict[str, str] = {}
        installed = 0
        executable_rels = surface.get(SURFACE_EXECUTABLE_KEY)
        executable_set = set(executable_rels) if isinstance(executable_rels, (list, tuple, set)) else set()
        payloads: dict[str, bytes] = {}
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
                payload = _owned_tar_bytes(key, value, mode=0o755 if key in executable_set else 0o644)
            elif isinstance(value, (str, Path)):
                host_path = _as_existing_path(value)
                if host_path is None:
                    entries[key] = "missing"
                    continue
                payload = _owned_tar(host_path, key)
            else:
                entries[key] = "not-a-path"
                continue
            payloads[key] = payload

        # NESTED PARENTS (#393) - see the method docstring. Only entries
        # that will actually be copied contribute; a flat surface makes no
        # probe and no extra copy.
        missing_parents = self._absent_parents(handle, effective_root, _missing_parent_candidates(list(payloads)))
        if missing_parents:
            self._copy_into(handle, effective_root, _owned_tar_dirs(missing_parents), "nested parent directories")

        for key, payload in payloads.items():
            try:
                copied = subprocess.run(
                    [*self.docker_bin, "cp", "-", f"{handle.name}:{effective_root}"],
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
            entries[key] = "installed"
            installed += 1

        # `discovery_canary`/`installed` reflect what was actually copied,
        # never merely what was declared (cross-model review, PR #85): a
        # surface entry naming a missing path, or a non-path value, must not
        # certify readiness for something that was never materialized. Since
        # #133 item 4, a missing entry among several successes is no longer
        # invisible either - see the method docstring's "PER-ENTRY READINESS".
        entries = {k: entries[k] for k in declared if k in entries}  # declared order, as before #393
        missing = [k for k in entries if entries[k] == "missing"]
        readiness: dict[str, object] = {
            "discovery_canary": "SATISFIED" if (declared and installed and not missing) else "VIOLATED",
            "baseline_absence": (
                "UNKNOWN" if not baseline_observed else "VIOLATED" if preexisting else "SATISFIED"
            ),
            "declared": len(declared),
            "installed": installed,
            "entries": entries,
            # What ACTUALLY ran (#12), asked of this attempt's own container -
            # never `self.image`, which may be a floating tag. None when the
            # daemon cannot say, never a guess.
            "image_digest": self._image_id(handle),
        }
        if preexisting:
            readiness["preexisting"] = preexisting
        if isinstance(nonce, str) and nonce:
            payload = _owned_tar_bytes(CANARY_HOST_FILENAME, nonce.encode("utf-8"))
            canary_copied: subprocess.CompletedProcess[bytes] | None
            try:
                canary_copied = subprocess.run(
                    [*self.docker_bin, "cp", "-", f"{handle.name}:{effective_root}"],
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

    def _absent_parents(self, handle: _Handle, root: str, relatives: Sequence[str]) -> list[str]:
        """Which of `relatives` (directories under `root`, parents first)
        do NOT yet exist in the container - asked with ONE read-only exec,
        as root so that a directory the candidate cannot traverse still
        reads as present (and so is never rewritten). Anything already
        present, including a symlink, is excluded. Raises
        `BackendUnavailable` when the probe cannot answer: an unknown
        answer must not be guessed either way - guessing "absent" would
        rewrite an existing directory, guessing "present" would leave a
        root-owned one (#393)."""
        if not relatives:
            return []
        absolute = [str(PurePosixPath(root) / rel) for rel in relatives]
        try:
            probed = subprocess.run(
                [*self.docker_bin, "exec", "-u", "0", "--", handle.name, "sh", "-c",
                 'i=0; for p do if [ -e "$p" ] || [ -L "$p" ]; then echo "$i"; fi; i=$((i+1)); done', "sh",
                 *absolute],
                capture_output=True, env=handle.env, check=False, timeout=self.daemon_timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise BackendUnavailable(f"install parent probe failed for {handle.attempt_id!r}: {exc}") from exc
        if probed.returncode != 0:
            raise BackendUnavailable(
                f"install parent probe failed for {handle.attempt_id!r}: "
                f"{probed.stderr.decode('utf-8', errors='replace').strip()}"
            )
        # Indices, never echoed paths: an index cannot be mangled by a path
        # holding a newline, and means the same whatever the path looks like.
        try:
            present = {int(line) for line in probed.stdout.decode("ascii").split()}
        except (UnicodeDecodeError, ValueError) as exc:
            raise BackendUnavailable(f"install parent probe answered unreadably for {handle.attempt_id!r}") from exc
        if not present <= set(range(len(relatives))):
            raise BackendUnavailable(f"install parent probe answered out of range for {handle.attempt_id!r}")
        return [rel for i, rel in enumerate(relatives) if i not in present]

    def _copy_into(self, handle: _Handle, root: str, payload: bytes, what: str) -> None:
        """`docker cp - NAME:root` for one owned tar stream; raises
        `BackendUnavailable` naming `what` on any failure."""
        try:
            copied = subprocess.run(
                [*self.docker_bin, "cp", "-", f"{handle.name}:{root}"],
                input=payload, capture_output=True, env=handle.env, check=False,
                timeout=self.daemon_timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise BackendUnavailable(f"docker cp failed installing {what} for {handle.attempt_id!r}: {exc}") from exc
        if copied.returncode != 0:
            raise BackendUnavailable(
                f"docker cp failed installing {what} for {handle.attempt_id!r}: "
                f"{copied.stderr.decode('utf-8', errors='replace').strip()}"
            )

    def _workspace_baseline(self, handle: _Handle, root: str = CONTAINER_WORKSPACE) -> tuple[frozenset[str], bool]:
        """Every top-level entry already present under `root` (#332
        follow-up: defaults to `CONTAINER_WORKSPACE`, unchanged for every
        existing caller) before `install()` copies anything - the image's
        own baseline, never this attempt's own installs, since this is
        called before the first `docker cp`. `(names, True)` on a
        successful listing; `(frozenset(), False)` when the daemon could
        not be asked at all, which callers must read as UNKNOWN, never as
        a confirmed-empty baseline (issue #133 item 4; the same "UNKNOWN
        never reaps" posture `confirm_stopped()` already holds for this
        module).

        `ls -1A` runs relative to `-w root`'s own working directory rather
        than naming `root` in the argv, so no absolute-path remapping is
        needed against the fake CLI fixture either (`tests/fixtures/
        docker-backend/fake_docker.py`'s own `cwd=`-only containment)."""
        try:
            proc = subprocess.run(
                [*self.docker_bin, "exec", "-w", root, "--", handle.name,
                 "sh", "-c", "ls -1A ."],
                capture_output=True, text=True, env=handle.env, check=False, timeout=self.daemon_timeout,
            )
        except (OSError, subprocess.TimeoutExpired):
            return frozenset(), False
        if proc.returncode != 0:
            return frozenset(), False
        return frozenset(line.strip() for line in proc.stdout.splitlines() if line.strip()), True

    def image_id(self, handle: object) -> str | None:
        """Public entry point for `_image_id` (#150-D): a caller that never
        calls `install()` at all - the agent-trial discovery-listing
        containers, which use `deliver_home_file` instead - still needs "the
        image that ran" (#151's own discipline: never the configured tag) for
        a container it prepared itself."""
        assert isinstance(handle, _Handle)
        return self._image_id(handle)

    def _image_id(self, handle: _Handle) -> str | None:
        """The id of the image this attempt's container was created from
        (`docker inspect --format {{.Image}}`), or `None` when the query
        fails or answers with anything that is not a `sha256:` id."""
        try:
            proc = subprocess.run(
                [*self.docker_bin, "inspect", "--format", "{{.Image}}", handle.name],
                capture_output=True, text=True, env=handle.env, check=False, timeout=self.daemon_timeout,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        image_id = proc.stdout.strip()
        if proc.returncode != 0 or not image_id.startswith("sha256:") or len(image_id) <= len("sha256:"):
            return None
        return image_id

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

        Missing parents are created as the candidate before tar delivery.
        Existing owners/modes are preserved; an unwritable parent refuses,
        never triggers privileged creation or a recursive ownership change.
        """
        assert isinstance(handle, _Handle)
        relative = PurePosixPath(container_relpath)
        if (not container_relpath or relative.is_absolute() or not relative.parts
                or ".." in relative.parts or "\0" in container_relpath):
            raise BackendUnavailable("home delivery requires a nonescaping relative file path")
        parent = str(PurePosixPath(CONTAINER_HOME) / relative.parent)
        try:
            prepared = subprocess.run(
                [*self.docker_bin, "exec", "-u", _container_user(), "--", handle.name,
                 "mkdir", "-p", "--", parent],
                capture_output=True, env=handle.env, check=False, timeout=self.daemon_timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise BackendUnavailable("home delivery parent setup failed") from exc
        if prepared.returncode != 0:
            raise BackendUnavailable("home delivery parent setup failed")
        payload = _owned_tar_bytes(relative.as_posix(), data, mode=mode)
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

    def controller_output(self, handle: object, argv: Sequence[str], limits: Limits) -> bytes:
        """Complete bounded output from the controller drain, never an artifact."""
        result = self.exec_in_attempt(handle, argv, limits)
        if (result.reason != "exited" or result.exit_code != 0 or result.stdout is None
                or result.stdout_truncated or result.stdout_incomplete or result.stderr_incomplete):
            raise rs.Refused("controller measurement failed or returned incomplete output")
        return result.stdout

    def runtime_environment(
        self, handle: object, limits: Limits, verified_files: Mapping[str, str],
    ) -> Mapping[str, str]:
        """Measure selected runtime facts as candidate before any subject runs.

        Raw environment stays private. The caller still verifies every installed
        closure file through its ordinary preflight before dispatch.
        """
        assert isinstance(handle, _Handle)
        if self.runtime_supply is None:
            raise rs.Refused("no controller runtime supply selected")
        if not self.witness_io:
            raise rs.Refused("runtime measurement requires private controller output")
        bounded = Limits(timeout=min(limits.timeout, self.daemon_timeout),
                         max_captured_stdout_bytes=rs.MAX_JSON + 1)

        def read(argv: Sequence[str]) -> bytes:
            return self.controller_output(handle, argv, bounded)

        env = rs.environment(read(["env", "-0"]))
        descriptor_path = PurePosixPath(rs.DESCRIPTOR_PATH)
        for path in (descriptor_path, *descriptor_path.parents):
            if self.candidate_can_write_in_attempt(handle, str(path)) is not False:
                raise rs.Refused("runtime descriptor or ancestor is writable or unmeasurable")
        # Reject symlink ancestry, including a descriptor whose target's parents
        # are outside the inspected chain. No subject runs during these reads.
        descriptor = read(["/usr/bin/python3", "-c",
            ("import pathlib,sys; p=pathlib.Path(sys.argv[1]); "
             "assert not any(q.is_symlink() for q in (p,*p.parents)); "
             "sys.stdout.buffer.write(p.open('rb').read(int(sys.argv[2])))"),
            rs.DESCRIPTOR_PATH, str(rs.MAX_JSON + 1)])
        actual_image = self.image_id(handle)
        if actual_image is None:
            raise rs.Refused("runtime image identity is unmeasurable")
        declared = self.runtime_supply.descriptor(descriptor, actual_image=actual_image)
        rs.validate_environment(env, declared)
        measured_python = rs.load_json(read(["/usr/bin/python3", "-c",
            ("import json,platform,sys; print(json.dumps(dict(executable=sys.executable, "
             "version=platform.python_version(),cache_tag=sys.implementation.cache_tag, "
             "platform=sys.platform,machine=platform.machine())))")]))
        if measured_python != declared["python"]:
            raise rs.Refused("actual Python identity differs from selected runtime")
        policy = self.runtime_supply.policy  # #279 policy B: the receipt's own pin
        uv = read(["uv", "--version"]).decode("utf-8", errors="strict").split()
        if len(uv) < 2 or uv[:2] != ["uv", policy["uv_version"]]:
            raise rs.Refused("actual uv version differs from selected runtime")
        if verified_files:
            if any(verified_files.get(path) != digest for path, digest in rs.metadata(policy).items()):
                raise rs.Refused("installed closure metadata does not match selected runtime")
            project = f"{CONTAINER_HOME}/{policy['project']}"
            if self.candidate_can_write_in_attempt(handle, project) is not True:
                raise rs.Refused("selected project cannot create its candidate-owned venv")
            read(["/usr/bin/python3", "-c",
                  "import pathlib,sys; assert not pathlib.Path(sys.argv[1]).exists()",
                  project + "/.venv"])
        return env

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

    #: Conservative defaults for `read_home_tree` - a single trial's private
    #: home (#78: fresh, empty, never shared) has no legitimate reason to
    #: hold more than a handful of small transcript files.
    HOME_TREE_MAX_BYTES = 8 * 1024 * 1024
    HOME_TREE_MAX_FILES = 256

    def read_home_tree(
        self, handle: object, container_reldir: str, *,
        max_bytes: int | None = None, max_files: int | None = None,
    ) -> dict[str, bytes]:
        """Read back every REGULAR FILE under `container_reldir` (relative
        to `CONTAINER_HOME`) as `{relpath: bytes}`, `relpath` given relative
        to `container_reldir` itself - the directory-tree counterpart to
        `read_home_file`, for exactly one purpose (#106): finding a real
        agent's transcript file, whose exact name each client CLI chooses
        for itself at runtime and which cannot be predicted in advance (a
        session UUID, embedded in the filename).

        A MISSING directory - the ordinary state before an agent has
        written anything there yet - is NOT an error: `docker cp`'s own
        failure on a path that does not exist becomes an EMPTY result here,
        because from a caller's perspective "nothing exists yet" and
        "nothing was found" are the same fact. Only a subprocess-level
        failure (the daemon itself is unreachable) raises
        `BackendUnavailable` - the same distinction `read_home_file`
        already makes for a single file.

        Bounded, never silently truncated (in the spirit of #102's
        bounded-capture rule) - AND never unboundedly BUFFERED first either
        (cross-model review: an earlier version called `subprocess.run
        (capture_output=True)`, which reads the WHOLE tar stream into
        memory before either limit is ever checked - a single huge file
        under `container_reldir` could exhaust host memory before
        `HomeTreeTooLarge` ever got a chance to fire, exactly the
        resource-exhaustion path #102 closed for `execute()`'s own stdout).
        The raw tar stream itself now drains through `_BoundedDrain`, the
        same mechanism `execute()` uses: `max_bytes` bounds the RAW stream,
        not merely the sum of extracted file contents (tar's own per-entry
        overhead means the true content bound is always slightly smaller
        than `max_bytes`, never larger - a conservative direction). A
        truncated stream is refused outright, before any tar parsing is
        attempted, rather than parsed as a corrupt archive. `max_files`
        still bounds the member COUNT once parsing does happen. Either
        bound raises `HomeTreeTooLarge` with a stated reason rather than
        returning a partial tree a caller could mistake for the whole one -
        a private trial home this large would itself be an unexplained
        fact, not something to quietly read part of.
        """
        assert isinstance(handle, _Handle)
        max_bytes = self.HOME_TREE_MAX_BYTES if max_bytes is None else max_bytes
        max_files = self.HOME_TREE_MAX_FILES if max_files is None else max_files
        try:
            proc = subprocess.Popen(
                [*self.docker_bin, "cp", f"{handle.name}:{CONTAINER_HOME}/{container_reldir}", "-"],
                env=handle.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
        except OSError as exc:
            raise BackendUnavailable(
                f"docker cp failed reading {container_reldir!r} from home for {handle.attempt_id!r}: {exc}"
            ) from exc

        assert proc.stdout is not None and proc.stderr is not None
        stdout_drain = _BoundedDrain(proc.stdout, max_bytes)
        stdout_thread = threading.Thread(target=stdout_drain.run, daemon=True)
        stdout_thread.start()
        stderr_drain = _BoundedDrain(proc.stderr, 65536)
        stderr_thread = threading.Thread(target=stderr_drain.run, daemon=True)
        stderr_thread.start()

        try:
            returncode = proc.wait(timeout=self.daemon_timeout)
        except subprocess.TimeoutExpired as exc:
            proc.kill()
            proc.wait()
            raise BackendUnavailable(
                f"docker cp timed out reading {container_reldir!r} from home for {handle.attempt_id!r}: {exc}"
            ) from exc
        finally:
            # ONE shared deadline (issue #20 Nit Store, the same fix
            # execute()'s own joins just got): both drain threads run
            # concurrently already, so joining each against its own full
            # daemon_timeout, sequentially, could cost up to 2x that bound
            # instead of 1x - measured directly at ~2.02x under a
            # constructed still-alive-at-join-time case. `proc` itself is
            # never candidate-controlled code the way execute()'s exec'd
            # argv is (this is always our own `docker cp` invocation), so
            # the trigger here is host scheduling delay rather than an
            # adversarial detached descendant - but the cost, when it
            # happens, is the same shape.
            join_deadline = time.monotonic() + self.daemon_timeout
            stdout_thread.join(timeout=max(0.0, join_deadline - time.monotonic()))
            stderr_thread.join(timeout=max(0.0, join_deadline - time.monotonic()))

        if returncode != 0:
            return {}  # no such directory yet - nothing to find, not a failure

        if stdout_drain.truncated:
            raise HomeTreeTooLarge(
                f"{container_reldir!r}'s raw archive stream exceeded {max_bytes} bytes for "
                f"{handle.attempt_id!r} - refusing rather than parse a truncated tree"
            )

        tree: dict[str, bytes] = {}
        top = PurePosixPath(container_reldir).name
        with tarfile.open(fileobj=io.BytesIO(stdout_drain.captured_bytes()), mode="r:*") as tar:
            for member in tar.getmembers():
                if not member.isfile():
                    continue
                if len(tree) >= max_files:
                    raise HomeTreeTooLarge(
                        f"{container_reldir!r} has more than {max_files} file(s) for "
                        f"{handle.attempt_id!r} - refusing rather than return a partial tree"
                    )
                extracted = tar.extractfile(member)
                if extracted is None:
                    continue
                member_path = PurePosixPath(member.name)
                relpath = member_path.relative_to(top) if member_path.parts and member_path.parts[0] == top else member_path
                tree[str(relpath)] = extracted.read()
        return tree

    def _launch_and_wait(
        self, handle: _Handle, argv: Sequence[str], limits: Limits,
        cancel: Callable[[], bool] | None, stdin: bytes | None, *, prefix_wrap: bool,
        after_launch: Callable[[], None] | None = None, cwd: str | None = None,
        stderr_status_record_max: int = 0, exec_env: Mapping[str, str] | None = None,
    ) -> tuple[subprocess.Popen[bytes], _BoundedDrain, _BoundedDrain, threading.Thread, threading.Thread, str] | ExecuteResult:
        """Shared `docker exec` launch-drain-wait mechanics for `execute()`
        and `exec_in_attempt()` (#269) - everything up to, but NOT
        including, what happens to the container afterward, which is the
        one thing the two callers must do differently (`execute()` always
        stops it; `exec_in_attempt()` never does). Returns the running
        pieces a caller needs to finish building its own `ExecuteResult`,
        or an `ExecuteResult` directly when the exec itself never launched
        (`reason="launch-failed"`, caller-decorated with its own
        `term_forwarding` convention since that field means different
        things to the two callers).

        `after_launch`, when given, runs once the LOCAL `docker exec`
        client has launched, before the wait loop begins - `exec_in_
        attempt()`'s own hook for reading back the in-container PID its
        wrapped argv just wrote (orchestrator ruling on finding 3), which
        `execute()` has no need for and leaves `None`.

        `cwd` (#332 follow-up), when given, overrides the default
        `CONTAINER_WORKSPACE` working directory via `docker exec`'s own
        `-w` - `execute()` never passes this and keeps the default;
        `exec_in_attempt()`'s own docstring states the confinement a
        caller must apply before passing one through here.

        `stderr_status_record_max` (#338) is passed straight to the stderr
        drain's `status_record_max` - only `exec_in_attempt()`'s confining
        wrapper writes a leading status record, so every other caller
        leaves it 0 and its stderr capture is unchanged."""
        exec_argv = [*self.docker_bin, "exec"]
        if stdin is not None:
            exec_argv.append("-i")
        exec_argv += ["-w", cwd if cwd is not None else CONTAINER_WORKSPACE]
        if exec_env:
            exec_argv += _env_args(exec_env)
        exec_argv += ["--", handle.name]
        if prefix_wrap:
            exec_argv.append(SKILLC_WRAP_PATH)
        exec_argv += list(argv)

        try:
            if limits.completion_deadline is not None:
                limits = replace(limits, timeout=limits.completion_deadline.remaining(limits.timeout))
            if limits.execution_deadline is not None:
                left = number(limits.execution_deadline) - number(time.monotonic())
                if left <= 0:
                    raise CompletionUnavailable("local execution deadline exhausted")
                limits = replace(limits, timeout=min(limits.timeout, left))
        except CompletionUnavailable as exc:
            return ExecuteResult(reason="launch-failed", exit_code=None, error=str(exc))
        deadline = time.monotonic() + limits.timeout
        if limits.execution_deadline is not None:
            deadline = min(deadline, limits.execution_deadline)
        try:
            proc = subprocess.Popen(
                exec_argv, env=handle.env,
                stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                start_new_session=True,
            )
        except OSError as exc:
            return ExecuteResult(reason="launch-failed", exit_code=None, error=str(exc))

        if after_launch is not None:
            after_launch()

        assert proc.stdout is not None
        stdout_drain = _BoundedDrain(proc.stdout, limits.max_captured_stdout_bytes)
        stdout_thread = threading.Thread(target=stdout_drain.run, daemon=True)
        stdout_thread.start()

        assert proc.stderr is not None
        stderr_drain = _BoundedDrain(proc.stderr, limits.max_captured_stderr_bytes, stderr_status_record_max)
        stderr_thread = threading.Thread(target=stderr_drain.run, daemon=True)
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

        reason = "exited"
        while proc.poll() is None:
            if time.monotonic() >= deadline:
                reason = "timeout"
                break
            if cancel is not None and cancel():
                reason = "operator-cancelled"
                break
            time.sleep(0.02)

        return proc, stdout_drain, stderr_drain, stdout_thread, stderr_thread, reason

    def execute(
        self, handle: object, argv: Sequence[str], limits: Limits,
        cancel: Callable[[], bool] | None = None, stdin: bytes | None = None,
        keep_running: bool = False,
    ) -> ExecuteResult:
        """Step 5: run `argv` inside the already-running container via
        `docker exec -w CONTAINER_WORKSPACE`, honoring `limits.timeout` and
        `cancel`. `stdin`, when given, is written and closed exactly like
        `subprocess.Popen.communicate` gives a bare host process (`-i` is
        added to the exec only when `stdin is not None`).

        Intended to be called ONCE per handle, mirroring interfaces.md's
        per-attempt step numbering (5 "Execute", then 6 "Stop and confirm").
        A SECOND call against a handle this method already stopped is
        REFUSED, not retried: `reason="attempt-not-running", exit_code=None`
        (#304 - this used to fall through to a real `docker exec`, which the
        daemon rejects, and the rejection's own nonzero exit read as an
        ordinary `reason="exited"` - fabricating an execution that never
        touched the container). The check is a fresh `_inspect()` at entry,
        refusing only on a CONFIRMED non-running status - unlike
        `exec_in_attempt()`'s otherwise-identical guard, an UNREACHABLE
        inspect (daemon down, binary missing) falls through to the real
        attempt instead of refusing, because this method's own existing
        contract already names that case `launch-failed`, and folding it
        into `attempt-not-running` regressed that documented behavior
        (`test_execute_reports_launch_failed_when_the_docker_binary_is_missing`,
        caught by running it).

        THE CHECK-THEN-ACT WINDOW IS CLOSED BY THE DAEMON'S OWN RECORD (#317).
        The entry check above can still race: the container can stop between
        it and the real `docker exec`, and the daemon's refusal then exits
        nonzero exactly like a subject that ran and failed. Two earlier
        designs were rejected in review. Matching the daemon's "is not
        running" wording in stderr reads the SUBJECT's output. An in-container
        marker file is subject-writable, and since the container runs with
        `--init` a subject can kill its keepalive and stop the container
        itself. Instead the argv runs behind a no-op prelude,
        `sh -c 'exec "$@"' skillc-exec-<uuid> ARGV`, which writes nothing and
        only puts a per-call token in the exec's command, so the daemon's
        own `exec_create`/`exec_start` events can name this call. After a
        nonzero exit, and before this method's own kill,
        `_exec_never_started` reclassifies to `attempt-not-running` only when
        ALL of these hold: the container is `exited`/`dead`; the
        `docker events` answer parses within a byte bound; it holds THIS
        call's forwarding-probe exec event (which runs on every call) after
        the window start, with its command readable, AND the container's
        `die` after it; and no exec in that window carries the token. No
        input is the subject's.

        THE CONSERVATIVE PROPERTY: a daemon whose events are dropped,
        reformatted, unreadable or oversized fails one of the proofs, and the
        real result stands. A mismatch with the real daemon can only FAIL to
        reclassify, never misreclassify. The event shape the fake CLI models
        was measured on Docker 29.8.2 (#426).

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
        it, and this method was blocked in `proc.wait()` waiting for exit.

        BOTH streams drain through `_BoundedDrain` (#102 - stdout first,
        stderr by the same review, since it is the identical pattern one
        screen down): each keeps reading its pipe to EOF regardless of its
        own `Limits.max_captured_std{out,err}_bytes`, for the pipe-deadlock
        reason above, but stops RETAINING bytes past that cap - a subject
        that writes continuously used to grow an unbounded `list[bytes]` for
        EITHER stream, a host memory-exhaustion path independent of any
        container-side memory limit. `ExecuteResult.stdout_truncated`/
        `.stdout_bytes` report stdout's outcome explicitly rather than
        silently capping what `observations` (below) ends up holding; a
        truncated stderr is folded into `error` itself as an explicit
        `"(truncated, N bytes total)"` suffix, since stderr has no field of
        its own on `ExecuteResult` - `error` is already the only surface it
        feeds.

        CAPABILITY-GATED TERM FORWARDING (issue #158, design doc section
        2d): `_forwarding_available` probes THIS container for
        `skillc-wrap` before the argv below is composed. Present: the argv
        is prefixed with it, so a container-level TERM this method's own
        `_stop()` sends can reach the subject via the in-container
        supervisor (docs/specs/evaluation-facility/signal-forwarding.md).
        Absent (every image before the #78 change lands, HELD separately):
        today's exact argv, unprefixed - this method's behavior is
        otherwise byte-for-byte what it was before #158. Either way,
        `ExecuteResult.term_forwarding` reports what was actually OBSERVED
        from the host side, never a claim about what happened inside the
        container - see that field's own docstring for the forgeability
        reasoning."""
        assert isinstance(handle, _Handle)
        if limits.completion_deadline is not None and limits.execution_deadline is None:
            limits = replace(limits, execution_deadline=time.monotonic() + limits.timeout)
        reachable, absent, status = self._inspect(handle)
        if reachable and (absent or status != "running"):
            # #304: a second `execute()` against an already-stopped handle
            # (this method's own docstring - "always stopped before
            # returning") used to fall through to `_launch_and_wait()`,
            # whose `docker exec` launches fine as a host process but is
            # rejected by the daemon - a real nonzero exit that read as an
            # ordinary `reason="exited"`, fabricating execution that never
            # touched the container. Same refusal reason `exec_in_attempt()`
            # uses - already a recognized "not started" reason everywhere
            # downstream (gate_witness.py's `_NOT_STARTED_REASONS`).
            #
            # Deliberately `reachable and (...)`, NOT `not reachable or
            # (...)`:
            # `reachable=False` means `_inspect()` itself could not get an
            # answer (unreachable daemon, missing binary) - a DIFFERENT,
            # unconfirmed fact, not a positive "not running". Folding it in
            # here regressed `test_execute_reports_launch_failed_when_the_
            # docker_binary_is_missing` (caught by running it, not
            # reasoned about): a broken `docker_bin` made `_inspect` itself
            # fail, and the then-identical guard reported a confident
            # "attempt-not-running" for a case this method's own contract
            # already correctly named "launch-failed" - a different kind of
            # guess replacing the first. Only a CONFIRMED non-running status
            # short-circuits; an unreachable daemon falls through to the
            # real attempt below, which still reports its own accurate
            # `launch-failed` exactly as it did before this guard existed.
            # `exec_in_attempt()` can fold the two together harmlessly
            # because gate_witness.py's `_NOT_STARTED_REASONS` already
            # treats them identically downstream; `execute()`'s caller
            # (`lifecycle.py`) does not get that same guarantee, so this
            # method may not assume it either (filed in the Nit Store as
            # worth a closer look, not fixed here - out of #304's scope).
            return ExecuteResult(reason="attempt-not-running", exit_code=None)
        # #317: the lower bound of this call's event window, taken BEFORE the
        # forwarding probe, so the probe's own exec event (which runs on every
        # call) falls inside it.
        window_start_ns = _wall_ns()
        call_id = uuid.uuid4().hex
        forwarding_available = self._forwarding_available(handle, f"{_FORWARDING_PROBE_TOKEN_PREFIX}{call_id}")
        # #317: a no-op prelude whose `$0` names this call. It writes nothing
        # to the filesystem or either stream (#334); `exec` keeps the pid,
        # stdin, exit code and the skillc-wrap prefix exactly as before.
        token = f"{_EXEC_TOKEN_PREFIX}{call_id}"
        inner = [SKILLC_WRAP_PATH, *argv] if forwarding_available else list(argv)
        wrapped_argv = ["sh", "-c", 'exec "$@"', token, *inner]
        launched = self._launch_and_wait(
            handle, wrapped_argv, limits, cancel, stdin, prefix_wrap=False,
            exec_env=dict(self.agent_exec_env()) if self.agent_exec_env is not None else None,
        )
        if isinstance(launched, ExecuteResult):
            if limits.completion_deadline is not None or limits.execution_deadline is not None:
                self._kill_container(handle, "KILL")
            # Launch itself failed (`OSError` from `Popen`) - `_launch_and_wait`
            # already built the `launch-failed` result; add the one piece of
            # context only THIS caller has (whether the wrap prefix it asked
            # for was even available), exactly as before the refactor.
            return ExecuteResult(
                reason=launched.reason, exit_code=launched.exit_code, error=launched.error,
                term_forwarding="unavailable-in-image" if not forwarding_available else None,
            )
        proc, stdout_drain, stderr_drain, stdout_thread, stderr_thread, reason = launched

        signal_name: str | None = None
        never_started = False
        if reason != "exited":
            signal_name = self._stop(handle, proc, limits.grace)
        else:
            proc.wait()
            # #317: decided BEFORE this method's own kill below, which would
            # otherwise make every container read as stopped.
            never_started = (proc.returncode not in (0, None)
                             and self._exec_never_started(handle, call_id, window_start_ns))
            if not keep_running:
                self._kill_container(handle, "KILL")

        # term_forwarding names what the HOST observed, never what the
        # container reports about itself (ExecuteResult's own docstring).
        # "exited-within-grace" and "killed-at-escalation" read directly off
        # `signal_name`, which `_stop()` already derives from the same
        # `proc.wait(timeout=grace)` this module used before #158 - no new
        # observation channel, just a name for an existing one.
        if not forwarding_available:
            term_forwarding = "unavailable-in-image"
        elif reason == "exited":
            term_forwarding = "not-needed"
        elif signal_name == "SIGTERM":
            term_forwarding = "exited-within-grace"
        else:
            term_forwarding = "killed-at-escalation"

        if never_started:
            # #317: the daemon refused the exec (container confirmed stopped,
            # no marker), so nothing ran. Join the drains and report it as
            # #304 does, without writing an `observations` file into a
            # workspace the subject never touched.
            join_deadline = time.monotonic() + limits.grace + self.daemon_timeout
            stdout_thread.join(timeout=max(0.0, join_deadline - time.monotonic()))
            stderr_thread.join(timeout=max(0.0, join_deadline - time.monotonic()))
            return ExecuteResult(reason="attempt-not-running", exit_code=None)

        return self._finish_result(
            handle, proc, stdout_drain, stderr_drain, stdout_thread, stderr_thread,
            limits, reason, signal_name=signal_name, term_forwarding=term_forwarding,
        )

    def _exec_never_started(self, handle: _Handle, call_id: str, window_start_ns: int) -> bool:
        """#317: True only when the daemon's own record PROVES `execute()`'s
        exec never started. ALL of these must hold, or the real result stands:

        1. the container exists and its status is `exited` or `dead` (not
           running, paused or restarting);
        2. the `docker events` answer for this container parses within
           `_EXEC_EVENTS_MAX_BYTES` and the query deadline, and every exec
           event in it has a readable command;
        3. it holds THIS call's forwarding-probe exec event - its command is
           the probe's exact command plus this call's own probe token, which
           no other call can produce: the buffer reaches back to just before
           our launch, in a format whose command field is readable;
        4. it holds this container's `die` AFTER that probe event in the
           daemon's own stream: the window runs through the stop;
        5. no `exec_create`/`exec_start` anywhere in the answer carries this
           call's exec token (it is unique to this call).

        Ordering uses only the daemon's own `timeNano`; the controller's clock
        only chooses where `docker events --since` starts reading, with
        `_EXEC_EVENTS_SINCE_MARGIN_NS` to spare, so the rule holds even if the
        controller and the daemon keep different clocks.

        Every input is the daemon's; none is the subject's output, files or
        streams. Measured on Docker 29.8.2 (#426): a refused exec records no
        event at all; the command lives only in `Action`, space-joined, with
        the `$0` token verbatim; `timeNano` is the host clock. The daemon keeps
        a GLOBAL 256-event ring that drops its OLDEST entries first, so on a
        busy host the probe (older) is evicted before any later token event:
        eviction fails proof 3 and keeps the real result. A daemon whose events
        are dropped, reformatted or unreadable fails 2-4 the same way: a
        mismatch can only fail to reclassify, never misreclassify."""
        reachable, absent, status = self._inspect(handle)
        if not reachable or absent or status not in ("exited", "dead"):
            return False
        events = self._exec_events(handle, window_start_ns - _EXEC_EVENTS_SINCE_MARGIN_NS)
        if events is None:
            return False
        execs = [(ns, command) for ns, kind, command in events if kind in ("exec_create", "exec_start")]
        if any(command is None for _, command in execs):
            return False
        probe_command = f"{_FORWARDING_PROBE_COMMAND} {_FORWARDING_PROBE_TOKEN_PREFIX}{call_id}"
        probe_ns = [ns for ns, command in execs if command == probe_command]
        if not probe_ns:
            return False
        lower = min(probe_ns)
        if not any(kind == "die" and ns > lower for ns, kind, _ in events):
            return False
        token = f"{_EXEC_TOKEN_PREFIX}{call_id}"
        return not any(command is not None and token in command for _, command in execs)

    def _exec_events(self, handle: _Handle, since_ns: int) -> list[tuple[int, str, str | None]] | None:
        """This container's daemon events since `since_ns` as
        `(time_ns, kind, command)`, `command` being the text after `exec_*: `
        in the action (None for other kinds). None when the query fails, times
        out, exceeds the byte bound, or any line does not parse."""
        since = f"{since_ns // 1_000_000_000}.{since_ns % 1_000_000_000:09d}"
        until = f"{_wall_ns() // 1_000_000_000 + 1}"
        try:
            proc = subprocess.Popen(
                [*self.docker_bin, "events", "--since", since, "--until", until,
                 "--filter", f"container={handle.name}", "--format", "{{json .}}"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=handle.env, start_new_session=True,
            )
        except OSError:
            return None
        assert proc.stdout is not None
        # One deadline covers the read AND the exit: a client that stalls
        # with stdout open cannot hold execute() past `daemon_timeout`.
        drain = _BoundedDrain(proc.stdout, _EXEC_EVENTS_MAX_BYTES)
        reader = threading.Thread(target=drain.run, daemon=True)
        reader.start()
        deadline = time.monotonic() + self.daemon_timeout
        reader.join(timeout=max(0.0, deadline - time.monotonic()))
        try:
            proc.wait(timeout=max(0.0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            pass
        if reader.is_alive() or proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass
            proc.wait()
            return None
        if proc.returncode != 0 or drain.truncated:
            return None
        data = drain.captured_bytes()
        parsed: list[tuple[int, str, str | None]] = []
        for line in data.decode("utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                return None
            action = event.get("Action") if isinstance(event, dict) else None
            time_ns = event.get("timeNano") if isinstance(event, dict) else None
            if not isinstance(action, str) or not isinstance(time_ns, int):
                return None
            kind, sep, command = action.partition(": ")
            parsed.append((time_ns, kind, command if sep and kind.startswith("exec_") else None))
        return parsed

    def _finish_result(
        self, handle: _Handle, proc: subprocess.Popen[bytes],
        stdout_drain: _BoundedDrain, stderr_drain: _BoundedDrain,
        stdout_thread: threading.Thread, stderr_thread: threading.Thread,
        limits: Limits, reason: str, *, signal_name: str | None, term_forwarding: str | None,
        stop_confirmed: bool | None = None,
    ) -> ExecuteResult:
        """Shared join/error/observations-write-back tail for `execute()`
        and `exec_in_attempt()` (#269) - the delicate part neither caller
        should duplicate: the shared drain-join deadline (issue #20 Nit
        Store, filed against #174), the truncated/incomplete distinction on
        `error` (#102, #133 item 3), and the `observations` write-back
        (#76, #186). `signal_name`/`term_forwarding` are accepted as
        parameters rather than computed here because they mean different
        things to the two callers - `execute()` derives them from stopping
        the whole container; `exec_in_attempt()` never stops it at all and
        passes `None` for both."""
        # ONE shared deadline: joining both threads against their own FULL
        # `grace + daemon_timeout` each, sequentially, doubled the
        # worst-case wall time a subject that holds both pipes open costs
        # this method - measured directly (not merely reasoned about) at
        # ~2.08x the single bound before this fix, ~1x after. Both threads
        # already run CONCURRENTLY (started in `_launch_and_wait`); only
        # the two blocking `.join()` calls in the calling thread were
        # sequential. A shared deadline lets a fast stdout drain leave the
        # full remaining budget for stderr, and a slow one still cannot
        # push the total past the one bound - `max(0.0, ...)` because a
        # `.join(timeout=<negative>)` returns immediately rather than
        # raising, but negative reads oddly in a trace.
        join_deadline = time.monotonic() + limits.grace + self.daemon_timeout
        stdout_thread.join(timeout=max(0.0, join_deadline - time.monotonic()))
        stderr_thread.join(timeout=max(0.0, join_deadline - time.monotonic()))
        # #133 item 3: a join that times out before the drain thread finishes
        # means the read never reached EOF - some descendant the subject left
        # running (past every kill this method issued above) still holds the
        # pipe open. `is_alive()` right after `.join()` is the ONLY way to
        # tell that apart from "read everything, gave up nothing": reading
        # `captured_bytes()`/`total_bytes` below regardless would silently
        # read a still-open pipe as a finished one (the exact gap
        # ExecuteResult's own docstring already named as unclosed by #102's
        # retention cap alone).
        stdout_incomplete = stdout_thread.is_alive()
        stderr_incomplete = stderr_thread.is_alive()
        stdout = stdout_drain.captured_bytes()
        stderr = stderr_drain.captured_bytes()
        code = proc.returncode
        error = None
        if reason == "exited" and code not in (0, None) and stderr:
            error = stderr.decode("utf-8", errors="replace").strip() or None
            if error and stderr_drain.truncated:
                # Explicit, not a silently shown prefix (orchestrator review
                # of this PR, #102): a caller reading `error` alone must not
                # mistake a capped stderr for the subject's whole message.
                error = f"{error} (truncated, {stderr_drain.total_bytes} bytes total)"
            if error and stderr_incomplete:
                # Distinct from truncation (#133 item 3): this is "we stopped
                # waiting", not "we read it all and discarded past the cap".
                error = f"{error} (capture incomplete, drain did not reach EOF)"

        # The exec'd process's stdout is written back into the container at
        # `<workspace>/observations` (`verify.py`'s own documented
        # convention, #76: "a probe-serving backend is expected to capture
        # the started process's stdout to a file named `observations` at its
        # workspace root") - discovered NOT to happen at all until #81's
        # demo command actually exercised grading through this backend: the
        # exec'd process's own stdout was thrown away (`DEVNULL`), so a
        # probe that reports its verdict on stdout (skillc's own probe
        # convention) always looked like it "produced no report", whatever
        # it actually printed. `stdout` is `stdout_drain`'s own bounded
        # capture (#102), so an `observations` file this writes for a chatty
        # subject is itself bounded - `ExecuteResult.stdout_truncated`/
        # `stdout_bytes` is what tells a caller this file is not the
        # subject's whole output.
        #
        # NOT fatal to this call if the write-back fails (issue #186: this
        # used to also mean NOT REPORTED - `check=False` and the result was
        # never inspected, so a subject that pre-creates `observations` as
        # a directory made the tar extraction fail with `IsADirectoryError`
        # - measured against the fake CLI - completely silently: no
        # exception here, no field on the result, the subject's own object
        # left in place). `observations_capture` now names the checked
        # outcome instead of swallowing it.
        observations_capture = None
        if not self.witness_io:
            try:
                payload = _owned_tar_bytes("observations", stdout)
                write_back = subprocess.run(
                    [*self.docker_bin, "cp", "-", f"{handle.name}:{CONTAINER_WORKSPACE}"],
                    input=payload, capture_output=True, env=handle.env, check=False,
                    timeout=self.daemon_timeout,
                )
                observations_capture = "written" if write_back.returncode == 0 else "failed"
            except (OSError, subprocess.TimeoutExpired):
                observations_capture = "failed"

        return ExecuteResult(
            reason=reason, exit_code=code, error=error, signal=signal_name,
            stdout_truncated=stdout_drain.truncated, stdout_bytes=stdout_drain.total_bytes,
            stdout_incomplete=stdout_incomplete, stderr_incomplete=stderr_incomplete,
            term_forwarding=term_forwarding, observations_capture=observations_capture,
            stop_confirmed=stop_confirmed, stdout=stdout,
            # #334: the raw stream on EVERY exit, beside the summary in
            # `error` (nonzero exits only, stripped, annotated), so a gate's
            # stderr can be forwarded byte-for-byte.
            stderr=stderr, stderr_truncated=stderr_drain.truncated,
        )

    def exec_in_attempt(
        self, handle: object, argv: Sequence[str], limits: Limits,
        cancel: Callable[[], bool] | None = None, stdin: bytes | None = None,
        cwd: str | None = None, env: Mapping[str, str] | None = None,
        confine_root: str | None = None,
    ) -> ExecuteResult:
        """Run `argv` inside the attempt's ALREADY-RUNNING container via a
        bare `docker exec`, WITHOUT ever stopping or removing it - added for
        #269's gate-execution witness, which needs to exec a declared gate
        possibly more than once (and possibly while the subject's own
        primary `execute()` is still running) against the SAME live,
        evolving container, never a fresh one. `execute()` itself cannot be
        reused for this: it is one-shot per handle BY DESIGN (its own
        docstring: "this attempt's container is always stopped before
        returning") - calling it for a gate would stop the attempt and, if
        the subject's own primary process were still inside it, kill that
        too. skillc #304 tracks `execute()`'s own stop-after-exec behavior
        separately; this method does not touch it.

        REFUSED (never an "exited" result) when the attempt's own primary
        process is confirmed not running: not yet started,
        already stopped, or the container is simply gone - `reason=
        "attempt-not-running"`, `exit_code=None`, checked via the SAME
        `_inspect()` `confirm_stopped()` already uses. An unreachable
        daemon leaves that state unknown and returns `launch-failed`,
        with no exec attempted. Otherwise a rejected Docker CLI call could
        read as an exited gate even though the gate never started.
        This is a REFUSAL, not a
        guessed result - the orchestrator ruling this was built to satisfy
        is explicit that a "container not running" exec must never be
        folded into a normal exit code (#183's own channel already proved
        a request arriving, never that work happened; this closes the
        analogous gap for a gate the attempt itself cannot run).

        Returns the real exit code from THIS exec alone - never the
        subject's own primary process, never a prior call's result.
        `term_forwarding` is always `None` here, meaning NOT APPLICABLE
        rather than "this backend never reports it" (`execute()`'s own
        convention for that field does not extend to this method): this
        method never sends a container-level signal, because it must
        never touch the container at all, so there is no container-level
        TERM for anything to forward.

        TIMEOUT/CANCEL ESCALATION CONFIRMS THE IN-CONTAINER PROCESS IS DEAD
        (orchestrator ruling on finding 3, codex `code_review`: leaving a
        possibly-still-running process free to keep mutating the tree it
        was measuring would corrupt exactly the facts this witness exists
        to certify - "a terminal state needs confirmed absence", the same
        rule `confirm_stopped()`/`confirm_absent()` already apply to the
        whole attempt). `argv` is wrapped as `sh -c 'echo $$ > MARKER;
        exec "$@"' sh <argv...>` so the in-container process reports its
        OWN pid (surviving the `exec` that replaces the shell with it) to
        a per-call marker path this method reads back via a second `docker
        exec ... cat MARKER`. On timeout or `cancel()`, a THIRD exec sends
        `kill -TERM` to that pid inside the container, polls `kill -0`
        for `limits.grace`, escalates to `kill -KILL` if still alive, and
        polls again - never touching the container itself, only this one
        pid. `ExecuteResult.stop_confirmed` reports the outcome: `True`
        only once `kill -0` is independently observed to fail; `False`
        when the pid was never learned, the kill exec itself could not be
        reached, or the process is still alive after escalation. `None`
        for `reason == "exited"` (no kill was ever needed) and for every
        `execute()` result (not applicable there).

        A REAL daemon's `docker exec` behavior for this three-exec
        sequence (marker write-back, in-container kill, in-container
        `kill -0` confirmation) is exercised here only against the fake
        CLI (`tests/fixtures/docker-backend/fake_docker.py`) - named as
        owed, matching every other real-daemon question this feature
        already defers (the real `tree_digest_fn`, the #158 forwarding
        capability check). The LOCAL `docker exec` client's own process
        group is still reaped afterward regardless (`start_new_session=
        True` at launch), so this method's own call returns promptly
        rather than waiting on a client whose remote session may outlive
        it.

        `cwd` alone (no `confine_root`) sets `docker exec -w`, native
        support rather than a shell `cd` - this method does not validate
        it, so a caller exposing `cwd` to anything the subject influences
        must confine it first (realpath-resolve inside the container, e.g.
        via `resolve_realpath_in_attempt()`, and check the result against a
        known root). This path is unchanged since #332 and stays the right
        one for a `cwd` the subject never influences at all.

        `cwd` WITH `confine_root` (#338) is for exactly the case the
        paragraph above warns about: a `cwd` the subject can influence.
        `gate_witness.py`'s `_decide_run_gate()` already resolves and
        root-checks a subject-forwarded cwd via `_confine_requested_cwd()`
        before calling here - but that check and this call are two
        SEPARATE `docker exec`s, separated by real wall-clock time (lock
        acquisition, `tree_digest_fn()`), during which the subject (same
        container, owns the whole workspace tree) can swap an ancestor of
        the already-resolved path for a symlink pointing outside the root.
        `docker exec -w` re-resolves the path STRING fresh at the moment
        IT runs, with no binding to the directory `_confine_requested_cwd`
        actually observed - so passing its resolved string straight
        through as plain `cwd` would carry the gap forward unfixed.

        So when `confine_root` is given, this method does NOT pass `cwd`
        to `docker exec -w` at all. Instead the wrapped argv opens `cwd`
        ONCE, as fd 9, and from then on uses only that fd, never the name:
        the check reads the kernel's own path for the open directory
        (`readlink /proc/self/fd/9` - deliberately NOT `readlink -f`, which
        would take that answer and walk it again by name), compares it with
        `confine_root` (equal, or strictly below it), and the move is a
        physical `cd -P /proc/self/fd/9` - a chdir to the directory fd 9
        holds, so `$PWD` and the gate's real cwd are that directory's real
        path, never the `/proc/self/fd/9` string a logical `cd` would leave
        behind. The fd lives on a compound command (`{ ...; } 9<"$1"`),
        never a bare `exec 9<"$1"` (dash treats `exec`'s own redirection
        failure as fatal to the whole non-interactive shell, so a missing
        cwd could not be refused cleanly), and closes when that block ends,
        so the gate never inherits it.

        What this guarantees, and what it does not. The directory the gate
        starts in IS the directory the check examined, and at the moment of
        the check that directory's own path was `confine_root` or below it.
        It does NOT guarantee the directory stays below `confine_root`: a
        subject who can rename it (or an ancestor) can move the open
        directory itself elsewhere - between the check and the `cd`, or at
        any time while the gate runs - and the gate's cwd moves with it,
        because a held directory follows the directory, not the path. In
        this backend's actual shape the workspace is the container's own
        writable layer, so such a move stays inside the same container;
        closing it fully needs a tree the subject cannot rename, which is
        a placement change, not something one exec can do.
        `_confine_requested_cwd` itself is NOT redundant: it is a cheap,
        non-load-bearing early rejection (a fast error for an obviously
        wrong cwd, before any exec is built at all).

        STATUS comes from the wrapper, never from the gate. The wrapper's
        first stderr bytes are one fixed record (`CWD_CONFINEMENT_READY_
        RECORD` immediately before it execs the real argv - and it execs
        only if that write succeeded - or `CWD_CONFINEMENT_REFUSED_RECORD`
        instead, then exit 125), and the stderr drain takes that leading
        record into its own bounded slot, outside the gate's retained
        stderr and its cap. So: READY means the result is the gate's own,
        its stderr excluding the record and its exit code untouched -
        including a gate that itself exits 125 or prints either record.
        REFUSED (with exit 125) is `reason="launch-failed"`,
        `error=CWD_CONFINEMENT_REFUSED_SENTINEL`. A missing or malformed
        record is also `"launch-failed"` (the gate is exec'd only after
        READY is written, so without it the gate never ran), with
        `CWD_CONFINEMENT_STATUS_MISSING`/`_INVALID` as `error` - never the
        refusal, and never a gate result. A timeout or cancel keeps its own
        reason whatever the record says: those already mean "not a
        complete run" and still need the in-container stop confirmation.

        `env`, when given, runs the wrapped argv under `env -i <env
        pairs>`, replacing the exec'd process's whole environment rather
        than adding to whatever the container's own default carries
        (`docker exec -e` only ADDS/overrides named vars on top of that
        default, which cannot express "exactly this set, nothing
        inherited") - needed so a gate's output can be compared
        byte-for-byte against a real invocation under a declared,
        reproducible environment rather than whatever the controller
        process happens to be carrying (#332's environment-parity
        condition)."""
        assert isinstance(handle, _Handle)
        reachable, absent, status = self._inspect(handle)
        if not reachable:
            return ExecuteResult(
                reason="launch-failed", exit_code=None,
                error="attempt state unknown: Docker inspect unreachable",
            )
        if absent or status != "running":
            return ExecuteResult(reason="attempt-not-running", exit_code=None)

        marker_root = CONTAINER_HOME if self.witness_io else CONTAINER_WORKSPACE
        marker_path = f"{marker_root}/.skillc-exec-pid-{uuid.uuid4().hex}"
        confining = cwd is not None and confine_root is not None
        # #338: open `$1` ONCE as fd 9, then use only the fd - see the
        # docstring for the guarantee and its limit. `readlink` without
        # `-f` is the kernel's own path for the open directory; `-f` would
        # walk that string again by name. The trailing `.` keeps command
        # substitution from stripping newlines out of the path itself, so
        # a directory named "<root>\n" cannot compare equal to "<root>".
        # The whole check's stderr goes to /dev/null - dash's own "cannot
        # open" diagnostic included - so the status record below is the
        # first thing on this exec's stderr, whatever happens.
        confinement_check = (
            "NL='\n'\n"
            'if { {\n'
            '  REAL=$(readlink /proc/self/fd/9 && echo .) &&\n'
            '  case "$REAL" in\n'
            '    "$2$NL.") ;;\n'
            '    "$2"/*"$NL.") ;;\n'
            '    *) false ;;\n'
            '  esac &&\n'
            '  cd -P /proc/self/fd/9\n'
            '} 9<"$1"; } 2>/dev/null\n'
            'then\n'
            '  shift 2\n'
            f"  printf '{CWD_CONFINEMENT_READY_RECORD.decode()[:-1]}\\n' >&2 || exit 125\n"
            'else\n'
            f"  printf '{CWD_CONFINEMENT_REFUSED_RECORD.decode()[:-1]}\\n' >&2\n"
            '  exit 125\n'
            'fi\n'
        ) if confining else ""
        if env is not None:
            env_pairs = [f"{k}={v}" for k, v in env.items()]
            script = f'{confinement_check}echo $$ > {marker_path}; exec env -i "$@"'
            positional = [cwd, confine_root, *env_pairs, *argv] if confining else [*env_pairs, *argv]
        else:
            script = f'{confinement_check}echo $$ > {marker_path}; exec "$@"'
            positional = [cwd, confine_root, *argv] if confining else [*argv]
        wrapped_argv = ["sh", "-c", script, "sh", *positional]
        in_container_pid: list[int | None] = [None]

        def _capture_pid() -> None:
            in_container_pid[0] = self._read_in_container_pid(handle, marker_path)

        # Once `confining`, the outer `docker exec -w` stays at its default:
        # passing `cwd` there too would be one more resolution of the path
        # string, the thing this fix stops trusting.
        launched = self._launch_and_wait(
            handle, wrapped_argv, limits, cancel, stdin, prefix_wrap=False, after_launch=_capture_pid,
            cwd=None if confining else cwd,
            stderr_status_record_max=CWD_CONFINEMENT_RECORD_MAX if confining else 0,
        )
        if isinstance(launched, ExecuteResult):
            return launched  # launch-failed, built by _launch_and_wait itself
        proc, stdout_drain, stderr_drain, stdout_thread, stderr_thread, reason = launched

        stop_confirmed: bool | None = None
        if reason != "exited":
            pid = in_container_pid[0]
            # `False` when the pid was never learned at all - indistinguishable
            # from "cannot confirm" either way, per the orchestrator's ruling.
            stop_confirmed = self._confirm_and_kill_in_container(handle, pid, limits.grace) if pid is not None else False
            # The LOCAL client's own process group is reaped regardless, so
            # this call returns promptly - never the container, never a
            # substitute for the in-container confirmation above.
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                pass
            try:
                proc.wait(timeout=limits.grace)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError, OSError):
                    pass
                try:
                    proc.wait(timeout=self.daemon_timeout)
                except subprocess.TimeoutExpired:
                    proc.kill()  # our OWN local client process, final fallback
                    proc.wait()
        else:
            proc.wait()

        result = self._finish_result(
            handle, proc, stdout_drain, stderr_drain, stdout_thread, stderr_thread,
            limits, reason, signal_name=None, term_forwarding=None, stop_confirmed=stop_confirmed,
        )
        if not confining or result.reason != "exited":
            return result
        # #338: the wrapper's leading record, never the gate's output or its
        # exit code, says whether the gate was exec'd at all.
        status = _confinement_status(stderr_drain)
        if status == "ready":
            return result
        if status == "refused" and result.exit_code == 125:
            error = CWD_CONFINEMENT_REFUSED_SENTINEL
        elif status == "missing":
            error = CWD_CONFINEMENT_STATUS_MISSING
        else:
            error = CWD_CONFINEMENT_STATUS_INVALID
        return ExecuteResult(
            reason="launch-failed", exit_code=None, error=error,
            stdout_incomplete=result.stdout_incomplete, stderr_incomplete=result.stderr_incomplete,
        )

    def resolve_realpath_in_attempt(self, handle: object, path: str, timeout: float = 2.0) -> str | None:
        """Resolves `path` to its real, symlink-free absolute form INSIDE
        the attempt's container via `realpath` - for a caller (#332's
        `gate_witness.py`) that must CONFINE a subject-forwarded path to a
        known root before trusting it for anything, including as a `cwd`
        to `exec_in_attempt()`. A string-prefix check on the unresolved
        input would miss a symlink pointing outside the root; this asks
        the container itself to resolve it first. `None` on any failure to
        read a single absolute-path line (unreachable exec, nonexistent
        path, timeout, a `realpath` that printed nothing) - never a guess,
        and never the unresolved input returned as if it were confirmed."""
        assert isinstance(handle, _Handle)
        try:
            proc = subprocess.run(
                [*self.docker_bin, "exec", "--", handle.name, "sh", "-c", 'realpath -- "$1" 2>/dev/null', "sh", path],
                capture_output=True, env=handle.env, timeout=timeout, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if proc.returncode != 0:
            return None
        text = proc.stdout.decode("utf-8", errors="replace").strip()
        return text if text.startswith("/") else None

    def write_root_owned_file_in_attempt(
        self, handle: object, path: str, content: bytes, mode: int = 0o755, timeout: float | None = None,
    ) -> bool:
        """Writes `content` to `path` INSIDE the live container AS ROOT
        (`docker exec -u 0`), creating any missing parent directory along
        the way (also root-owned, mode `0755`) - for #332 follow-up's
        gate-witness harness copy of the real `flow-finish-gate.sh`,
        which must land somewhere the candidate identity cannot write.
        Deliberately NEVER routed through `install()`'s own candidate-
        owned tar convention (`_owned_tarinfo`): that convention exists
        precisely so a declared skill surface is usable by the candidate,
        the opposite of what this primitive is for. Returns `True` on
        success, `False` on ANY failure (daemon unreachable, timeout, a
        nonzero exit) - never raises, matching `resolve_realpath_in_
        attempt`'s own best-effort posture; a caller must verify the
        result independently (`candidate_can_write_in_attempt`) rather
        than trust this return value alone for anything security-relevant."""
        assert isinstance(handle, _Handle)
        wait = timeout if timeout is not None else self.daemon_timeout
        script = 'dir=$(dirname "$1") && mkdir -p "$dir" && chmod 0755 "$dir" && cat > "$1" && chmod "$2" "$1"'
        try:
            proc = subprocess.run(
                [*self.docker_bin, "exec", "-u", "0", "-i", "--", handle.name,
                 "sh", "-c", script, "sh", path, format(mode, "o")],
                input=content, capture_output=True, env=handle.env, timeout=wait, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return proc.returncode == 0

    def start_root_daemon_in_attempt(self, handle: object, argv: Sequence[str], timeout: float | None = None) -> bool:
        """Starts `argv` DETACHED inside the live container AS ROOT
        (`docker exec -d -u 0`): #518's credential steward, which must outlive
        this call and run as a uid the candidate cannot signal. Returns `True`
        when docker accepted the start, `False` on any failure - never raises.
        A caller confirms the daemon by its own first report (the steward's
        `armed` event over the trigger socket), never by this return value."""
        assert isinstance(handle, _Handle)
        wait = timeout if timeout is not None else self.daemon_timeout
        try:
            proc = subprocess.run([*self.docker_bin, "exec", "-d", "-u", "0", "--", handle.name, *argv],
                                  capture_output=True, env=handle.env, timeout=wait, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return False
        return proc.returncode == 0

    def root_output_in_attempt(self, handle: object, argv: Sequence[str], timeout: float | None = None,
                               max_bytes: int = 1 << 20) -> bytes | None:
        """Runs `argv` inside the container AS ROOT and returns its stdout, or
        `None` on any failure, a nonzero exit or output over `max_bytes`
        (#518: the steward's vault and signals, which the candidate cannot
        reach). Never raises."""
        assert isinstance(handle, _Handle)
        wait = timeout if timeout is not None else self.daemon_timeout
        try:
            proc = subprocess.run([*self.docker_bin, "exec", "-u", "0", "--", handle.name, *argv],
                                  capture_output=True, env=handle.env, timeout=wait, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if proc.returncode != 0 or len(proc.stdout) > max_bytes:
            return None
        return proc.stdout

    def remove_file_in_attempt(self, handle: object, path: str, timeout: float = 5.0) -> bool:
        """Deletes `path` inside the attempt's container and confirms it is
        gone, via a bare `docker exec` - deliberately NOT routed through
        `exec_in_attempt()` (skillc#334). That method's
        own shared tail (`_finish_result`, #76/#186) unconditionally writes
        the exec'd process's stdout back to `CONTAINER_WORKSPACE/observations`
        AFTER every call, even one whose stdout is empty - `_owned_tar_bytes`
        builds a real (zero-length) tar entry regardless, and `docker cp`
        extracts it. So using `exec_in_attempt()` itself to remove that very
        file would always leave a freshly-recreated empty one in its place:
        the file would never again be ABSENT, only ever emptied. This
        mirrors `resolve_realpath_in_attempt`'s own raw-`docker exec` shape,
        which has the same property for the same reason - neither one goes
        through the write-back tail at all.

        Returns `True` only once the removal AND an immediate `[ ! -e ]`
        check, in the same shell invocation, both succeed - never from
        `rm -f`'s own exit code alone, since `rm -f` reports success even
        when the path never existed, which would read as a confirmed
        removal that was never actually checked."""
        assert isinstance(handle, _Handle)
        try:
            proc = subprocess.run(
                [*self.docker_bin, "exec", "--", handle.name, "sh", "-c",
                 'rm -f -- "$1" && [ ! -e "$1" ]', "sh", path],
                capture_output=True, env=handle.env, timeout=timeout, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return proc.returncode == 0

    def candidate_can_write_in_attempt(self, handle: object, path: str, timeout: float | None = None) -> bool | None:
        """Empirically tests whether the CANDIDATE identity (never root)
        can write `path` INSIDE the live container, via `test -w` run AS
        that uid (`docker exec -u CANDIDATE_UID`) - never inferred from
        mode bits alone, which can be fooled by an unexpected owner or an
        ACL this check does not read. `True`/`False` only when `sh`
        itself genuinely ran `test` and produced a clean result: `test`'s
        OWN exit codes are exactly `{0, 1}` with nothing on stderr either
        way, so ANY other exit code (counter-model review finding: a
        process killed by a signal - 137 for SIGKILL, say - exits outside
        that set but can still leave stderr empty) OR any stderr output
        at all means something OTHER than a clean test happened - a
        daemon-level exec failure, an OOM kill, say - and must not be
        read as a confident `False`. `None` - never guessed either way -
        covers all of that, plus an unreachable exec/timeout. A caller
        must treat `None` exactly like `False` for any refusal this feeds
        (#332 follow-up's own ruling: an unverified harness destination is
        refused, the same as a confirmed-writable one) - but must never
        report `None` AS `False` in anything that claims the check
        actually ran.

        CHECKS ONLY THIS ONE PATH - never its parent directory (counter-
        model review finding: Unix write permission on a FILE controls
        modifying its contents, but write+execute permission on its
        CONTAINING DIRECTORY is what actually controls whether it can be
        unlinked and replaced entirely, regardless of the file's own
        mode or owner). A caller protecting a file against replacement -
        not merely in-place modification - must check the ENCLOSING
        DIRECTORY the same way, not infer it from this result
        (`apply_flow_check_gate_overlay` does both)."""
        assert isinstance(handle, _Handle)
        wait = timeout if timeout is not None else self.daemon_timeout
        try:
            proc = subprocess.run(
                [*self.docker_bin, "exec", "-u", str(CANDIDATE_UID), "--", handle.name,
                 "sh", "-c", 'test -w "$1"', "sh", path],
                capture_output=True, env=handle.env, timeout=wait, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        return _clean_write_probe_result(proc.returncode, proc.stderr)

    def _read_in_container_pid(self, handle: _Handle, marker_path: str, timeout: float = 2.0) -> int | None:
        """Polls `docker exec ... cat MARKER` for the pid `exec_in_attempt()`'s
        wrapped argv writes to its own per-call marker - the marker write
        happens before the real command even starts, so this should
        resolve almost immediately; the poll exists only to absorb the
        unavoidable gap between this process launching and that write
        landing. `None` on any failure to read a positive integer within
        `timeout` - never a guess."""
        deadline = time.monotonic() + timeout
        while True:
            try:
                proc = subprocess.run(
                    [*self.docker_bin, "exec", "--", handle.name, "cat", marker_path],
                    capture_output=True, env=handle.env, timeout=self.daemon_timeout, check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                proc = None
            if proc is not None and proc.returncode == 0:
                text = proc.stdout.decode("utf-8", errors="replace").strip()
                if text.isdigit():
                    return int(text)
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.02)

    def _confirm_and_kill_in_container(self, handle: _Handle, pid: int, grace: float) -> bool:
        """`kill -TERM` then `kill -KILL` against `pid` INSIDE the
        container (never the container itself), confirming death via
        `kill -0` after each - returns `True` only once that confirmation
        is independently observed, `False` if the process is still alive
        after escalation or any exec in this sequence could not be
        reached. Mirrors `_stop()`'s own escalation shape, one level down
        (a single in-container pid instead of the whole container).

        Every call here goes through `sh -c 'kill ...'`, not a bare `kill`
        argv - `kill` is a POSIX SHELL BUILTIN (dash, bash), so this needs
        no standalone `kill` binary on the exec'd image's PATH at all
        (verified: `env -i PATH=/nonexistent sh -c 'kill -0 $$'` still
        answers correctly). A minimal image such as CI's `python:3.12-slim`
        is not guaranteed to carry the `procps` package `kill` usually
        comes from - this is what keeps that irrelevant."""
        def _alive() -> bool | None:
            # True/False only from an EXPLICIT, recognized signal - kill
            # -0's own exit 0 (alive) or its own "No such process" text
            # (confirmed dead). Any other nonzero exit (the exec
            # infrastructure itself failing to even run `sh` - a bad
            # docker_bin, a daemon that dropped mid-call, an unparseable
            # error) is None, UNKNOWN - never guessed as either answer.
            # Mirrors _inspect()'s own discipline: a nonzero exit code
            # alone conflates "the process is gone" with "I could not ask".
            try:
                proc = subprocess.run(
                    [*self.docker_bin, "exec", "--", handle.name, "sh", "-c", f"kill -0 {pid}"],
                    capture_output=True, env=handle.env, timeout=self.daemon_timeout, check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                return None
            if proc.returncode == 0:
                return True
            if "no such process" in proc.stderr.decode("utf-8", errors="replace").lower():
                return False
            return None

        def _signal(sig: str) -> None:
            try:
                subprocess.run(
                    [*self.docker_bin, "exec", "--", handle.name, "sh", "-c", f"kill -{sig} {pid}"],
                    capture_output=True, env=handle.env, timeout=self.daemon_timeout, check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                pass

        _signal("TERM")
        deadline = time.monotonic() + grace
        while time.monotonic() < deadline:
            if _alive() is False:
                return True
            time.sleep(0.02)
        _signal("KILL")
        deadline = time.monotonic() + self.daemon_timeout
        while time.monotonic() < deadline:
            if _alive() is False:
                return True
            time.sleep(0.02)
        return False

    def execute_turn(
        self, handle: object, argv: Sequence[str], limits: Limits, cancel: Callable[[], bool] | None = None,
    ) -> ExecuteResult:
        """#279: one turn of a multi-turn attempt - `execute()`, except that a
        turn which EXITS leaves the container running for the next turn. A
        timeout or cancel still stops it exactly as `execute()` does. Whoever
        calls this owns ending the attempt with `end_attempt()` (lifecycle does,
        in a `finally`), and the attempt's last turn uses plain `execute()`."""
        return self.execute(handle, argv, limits, cancel, keep_running=True)

    def end_attempt(self, handle: object) -> None:
        """#279: stop a container a kept-running turn left up - the same KILL
        `execute()` sends after a clean exit. Best-effort like that kill;
        `confirm_stopped()` independently verifies the outcome."""
        assert isinstance(handle, _Handle)
        self._kill_container(handle, "KILL")

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

    def export(self, handle: object, dest: Path, root: str | None = None) -> None:
        """Step 7 (backend side): copy `root`'s contents (#332 follow-up:
        `None`, every existing caller, means `CONTAINER_WORKSPACE`,
        unchanged) into `dest` via `docker cp NAME:{root}/. dest` -
        contents only, never nesting `root` itself inside `dest`.
        Read-only on the container side and safe to call more than once,
        per the Protocol's own rule."""
        assert isinstance(handle, _Handle)
        effective_root = root if root is not None else CONTAINER_WORKSPACE
        dest.mkdir(parents=True, exist_ok=True)
        try:
            copied = subprocess.run(
                [*self.docker_bin, "cp", f"{handle.name}:{effective_root}/.", str(dest)],
                capture_output=True, text=True, env=handle.env, check=False, timeout=self.daemon_timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise OSError(f"docker cp export failed for {handle.attempt_id!r}: {exc}") from exc
        if copied.returncode != 0:
            raise OSError(f"docker cp export failed for {handle.attempt_id!r}: {copied.stderr.strip()}")

    def destroy(self, handle: object) -> None:
        """Step 9: `docker rm -f` - safe to call more than once, and safe to
        call after a failed `install`/`execute` (the container is always
        created by the time a caller has a handle at all). Also closes
        #183's channel, if this attempt had one and the caller never
        called `trigger_log()`/finalized it directly - best-effort, never
        raises (`DecideReplyChannel.close()`'s own idempotent contract), so
        a caller that forgot to retrieve the log before tearing down still
        leaves no listening thread behind; it only loses the log it never
        asked for.

        The container goes FIRST, the channel's socket file second (#394):
        the socket is this container's bind-mount source, and a stopped
        container whose source has vanished answers every `docker cp` with
        "Could not find the file", so the file must outlive the container,
        not the listener (`_start_trigger_channel`'s `retain_socket_path`).
        The listener always stops here; the file is released only once the
        daemon CONFIRMS the container is gone. A failed or timed-out removal
        leaves both, so the container stays readable for diagnosis and a
        later `destroy()` (safe to repeat) or the reaper finishes the job."""
        assert isinstance(handle, _Handle)
        try:
            subprocess.run(
                [*self.docker_bin, "rm", "-f", handle.name],
                capture_output=True, env=handle.env, check=False, timeout=self.daemon_timeout,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass  # best-effort; confirm_absent() independently verifies the outcome
        if handle.egress_proxy is not None or handle.egress_network is not None:
            # #442: the agent container goes first (it holds the network), then
            # the proxy, then the network. Best-effort like the rest of destroy().
            self._stop_egress(handle.egress_proxy, handle.egress_network, handle.env)
        channel = handle.trigger_channel
        if channel is not None:
            if self.confirm_absent(handle) is Confirmation.CONFIRMED:
                channel.close()
            else:
                try:
                    channel.log_or_finalize()  # stop listening; keep the bind source
                except RuntimeError:
                    pass  # best-effort, matching close(); the log read reports its own failure

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
        if not absent:
            return Confirmation.NOT_CONFIRMED
        # #442: the attempt's proxy and network are its resources too - a
        # teardown that left either behind is not a confirmed one.
        for kind, name in (("container", handle.egress_proxy), ("network", handle.egress_network)):
            if name is None:
                continue
            gone = self._object_absent(kind, name, handle.env)
            if gone is None:
                return Confirmation.UNKNOWN
            if not gone:
                return Confirmation.NOT_CONFIRMED
        return Confirmation.CONFIRMED

    def _object_absent(self, kind: str, name: str, env: Mapping[str, str]) -> bool | None:
        """#442: whether a container or network is gone. `None` when the daemon
        could not be asked or answered with something other than "not found"."""
        argv = [*self.docker_bin, "network", "inspect", name] if kind == "network" \
            else [*self.docker_bin, "inspect", name]
        try:
            done = subprocess.run(argv, capture_output=True, text=True, env=env, check=False,
                                  timeout=self.daemon_timeout)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if done.returncode == 0:
            return False
        err = done.stderr.lower()
        return True if ("no such" in err or "not found" in err) else None
