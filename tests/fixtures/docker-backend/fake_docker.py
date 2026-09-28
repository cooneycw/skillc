"""A deterministic stand-in for the `docker` CLI (#10), for tests with no
daemon.

    fake_docker.py --state DIR <subcommand> ...

`--state DIR` must come first: it is where this fake keeps its container
"daemon" state (one JSON file per container name, plus one `<name>.fsroot/`
directory simulating that container's filesystem - see `cp`/`exec` below),
since each subcommand is a separate process and needs somewhere durable to
read what an earlier `run`/`cp` left behind. Passing it as part of
`docker_bin` (the prefix `docker_backend.py` puts in front of every docker
invocation) means every call shares one state directory without any hidden
environment channel.

FAULT INJECTION IS FILE-BASED, NOT ENVIRONMENT-BASED, ON PURPOSE. A test's
`monkeypatch.setenv` reaches a `docker` invocation only by accident:
`DockerBackend` deliberately calls every docker CLI invocation with an
explicit, restricted environment (`_docker_env()` - PATH plus a named
connection-var allowlist), never the launching process's own environment.
Sentinel FILES under `--state DIR` reach every subcommand identically, since
the directory is passed as an explicit argv element, not inherited.

Subcommands, matching what `docker_backend.py` composes and queries - this is
not a docker clone:

    run --rm [-d] --name NAME --network N --user U --hostname H --init
        --memory M --memory-swap M --pids-limit P --cpus C --shm-size S
        -w WORKDIR [-e K=V ...] -- IMAGE ARGV...
        Non-detached (no `-d`): writes {name}.json as "running", then runs
        ARGV as a real subprocess with cwd = this container's fsroot work
        directory and env = EXACTLY the given -e pairs, never this process's
        own environment. On a normal exit, deletes the state file (--rm) -
        UNLESS a `.stuck-NAME` sentinel exists in the state dir, in which
        case it writes "exited" instead: simulating a daemon whose
        auto-removal does not fire despite --rm.
        Detached (`-d`, what `DockerBackend.prepare()` uses for its
        keep-alive placeholder): writes {name}.json as "running" (with the
        given `-e` pairs recorded under "env", for `exec` to use later) and
        returns immediately WITHOUT running ARGV - there is no real "sleep
        infinity" process in this fake, only the status flag `exec`/`kill`/
        `inspect`/`rm` all read and write. A `.refuse-run` sentinel makes
        EITHER form fail outright (exit 1, nothing created) - simulating the
        daemon itself refusing container creation, the fault
        `DockerBackend.prepare()` must turn into `BackendUnavailable` rather
        than a fallback. A `.refuse-start` sentinel instead simulates a
        container Docker CREATED but that then failed to START (`-d` only):
        the state file is left behind, a real ORPHAN, so a test can prove
        `prepare()` cleans it up before raising rather than leaving a
        partial resource behind. A `.hang-run` sentinel (its content, if
        any, is the sleep duration in seconds; empty/missing content defaults
        to 2.0) makes the DETACHED form sleep before returning 0 and writing
        any state at all - simulating a daemon that never answers `run -d`
        in time (issue #133 item 1), rather than one that answers quickly
        with a refusal. Combine with a short `DockerBackend(daemon_timeout=
        ...)` so a test proving the bound stays fast.
    exec [-i] -w WORKDIR -- NAME ARGV...
        Requires NAME's state to be "running" (else exit 1, "No such
        container" or "is not running"). Runs ARGV as a real subprocess
        (its own new session, so a teardown can `os.killpg()` the whole
        tree) with cwd = NAME's fsroot directory at WORKDIR, and env = PATH
        plus whatever `-e` pairs `run -d` recorded for NAME - simulating
        that `docker exec` runs with the CONTAINER's own declared
        environment, never the `docker exec` CLI client's own ambient
        environment. Records the child's pid on NAME's state file for the
        duration of the call - both `kill` and `rm -f` (each a SEPARATE OS
        process, sharing nothing but this state file) read it back to
        signal the right process group for real: `kill` with SIGKILL
        always, matching a real daemon's kernel-level PID-namespace
        teardown once the container's own PID 1 dies (issue #158 - a real
        `docker kill` never forwards its OWN requested signal to a
        separately exec'd session, but does not leave it running either);
        `rm -f` the same way, for a caller that removes a container
        without a preceding `kill` at all (see `kill`/`rm` below). `-i`
        passes this fake's own stdin through to ARGV, exactly
        as a real `docker exec -i` would.
        Any ARGV element that is `/work` or starts with `/work/` is rewritten
        to NAME's fsroot equivalent before launching (`_remap_absolute`) -
        `cwd=` alone resolves a RELATIVE path but does nothing for an
        absolute one, and #81's own demo command passes absolute paths
        (`verify.py`'s own probe invocation convention) that failed against
        this fake before that rewrite existed, even though the file
        genuinely existed in the simulated container filesystem.
        Exits with ARGV's own exit code, or 127 if ARGV's own binary cannot
        be found (docker's own convention for that case).
    kill [--signal SIG] NAME
        Fidelity-matched to real Docker (issue #158). A real `docker kill`
        reaches only the CONTAINER's own PID-1 (`tini` wrapping
        `sleep infinity`, which this fake has no real subprocess for - see
        `run -d` above); it never forwards a signal to a separately exec'd
        session directly. But a real daemon does not leave that session
        running either: PID 1 dying (from a forwarded TERM, or outright
        under an unblockable KILL) stops the container, and the KERNEL
        sigkills every other process left in its PID namespace, exec
        sessions included. So NAME's status flips to "exited" AND the pid a
        still-running `exec` recorded is `os.killpg`'d with SIGKILL -
        always SIGKILL, never the requested `SIG`, since the subject's
        death here is the kernel's own PID-namespace teardown, not a
        forwarded signal (the subject genuinely never receives a graceful
        TERM - that is #158's real bug and stands). UNLESS a `.stuck-NAME`
        sentinel exists, in which case NEITHER the status nor the subject
        changes (simulating a container that ignores the signal entirely, a
        daemon lie `confirm_stopped()` must not trust). `rm -f` (below)
        performs the same reaping for a caller that removes a container
        without a preceding `kill` at all.
    cp SRC DEST
        `SRC == "-"` (what `DockerBackend.install()` uses): reads a tar
        stream from stdin and extracts it into DEST (`NAME:PATH`) - this is
        how the real backend controls every copied-in member's ownership
        itself, since a plain host-path `docker cp` would instead preserve
        the SOURCE's own uid/gid.
        Otherwise, exactly one of SRC/DEST is a `NAME:PATH` reference; the
        other is an ordinary host path. Host -> container copies a file or
        directory into NAME's fsroot at PATH (creating parent directories as
        needed). Container -> host requires NAME:PATH to exist; a trailing
        `/.` on PATH copies PATH's CONTENTS into DEST (DEST must already
        exist, as a real `docker cp`'s directory-contents form requires),
        otherwise PATH itself is copied into DEST as a new entry named after
        PATH's own basename. Exits 1 (no such container/path) or 2 (bad
        usage) on the failure paths `DockerBackend.export()`/`install()`
        must handle.
    inspect --format {{.State.Status}} NAME
        Prints the state file's status, or exits 1 if absent ("No such
        object").
    inspect --format {{.Image}} NAME
        Prints the image id NAME was created from - the same fake digest
        `image inspect` prints for its image - unless `.image-id-NAME` holds
        another id, or `.no-image-id-NAME` makes the query exit 1.
    image inspect IMAGE --format {{.Id}}
        Prints a deterministic fake digest for IMAGE, unless a `.no-image`
        sentinel exists in the state dir, in which case it exits 1
        (simulating an unpullable/unknown image).
    rm -f NAME
        Signals the process GROUP recorded by a still-running `exec`
        (`os.killpg`, `SIGKILL` - real container removal does not offer a
        graceful option), same as `kill` (above) already does, then deletes
        the state file and NAME's fsroot directory, and exits 0. Real
        container removal reaps everything still inside it too, so this is
        the backstop for a caller that removes a container without a
        preceding `kill` at all (issue #158). EXCEPT: if a `.stuck-NAME`
        sentinel exists in the state dir, exits 0
        WITHOUT signaling, deleting, or changing anything - simulating a
        daemon that reports successful removal while the container (and
        anything still running inside it) is still there. The fixture's own
        negative control: proves a caller's post-rm `inspect` (never trusting
        rm's exit code alone) actually catches this.
    version --format {{.Server.Version}}
        Prints a fixed version and exits 0, unless a `.down` sentinel exists
        in the state dir, in which case it exits 1 with nothing printed - an
        unreachable daemon.
    ps -a [--filter label=KEY=VALUE ...] --format {{.Names}}
        Prints one matching container's name per line, ANDing every
        `--filter label=` given (#79). A container's labels are exactly what
        `run`'s own `--label KEY=VALUE` flags recorded for it, so a container
        started with no `--label` (or a different one) never matches a
        filter naming `skillc.managed` - a foreign look-alike is excluded
        structurally, not by convention. Reuses the SAME `.down` sentinel as
        `version`: an unreachable daemon cannot list anything either, and a
        caller must read that failure as UNKNOWN, never as an empty result.
"""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid
from collections.abc import Callable
from pathlib import Path

#: Must match docker_backend.CONTAINER_WORKSPACE. Kept as a separate literal
#: on purpose (this fixture does not import skillc): it is a fake CLI, not a
#: client of the module under test.
WORK_CONTAINER_PATH = "/work"

#: Must match docker_backend.CONTAINER_HOME - same reasoning as
#: WORK_CONTAINER_PATH above. Needed once an exec'd argv references the
#: container's home rather than its workspace (issue #101: an in-container
#: `codex debug prompt-input` needs `CODEX_HOME` pointed at where
#: `deliver_home_file` actually placed things, `<fsroot>/home/candidate`,
#: never the literal host path, which is not this fake's simulated
#: filesystem at all).
HOME_CONTAINER_PATH = "/home/candidate"

_FLAGS_WITH_VALUE = (
    "--network", "--user", "--hostname", "--memory", "--memory-swap",
    "--pids-limit", "--cpus", "--shm-size", "-w", "--storage-opt",
    "--signal",
)


def _state_file(state_dir: Path, name: str) -> Path:
    return state_dir / f"{name}.json"


def _container_root(state_dir: Path, name: str) -> Path:
    return state_dir / f"{name}.fsroot"


def _in_container(state_dir: Path, name: str, container_path: str) -> Path:
    return _container_root(state_dir, name) / container_path.lstrip("/")


def _stuck(state_dir: Path, name: str) -> bool:
    return (state_dir / f".stuck-{name}").exists()


def _atomic_write_json(path: Path, data: dict) -> None:
    """Write `data` to `path` via a temp file in the SAME directory plus
    `os.replace()` - atomic on POSIX, so a concurrent reader (a separate
    `inspect`/`kill`/`exec` invocation, each its own OS process) sees either
    the complete old content or the complete new content, never a torn
    write. An in-place `path.write_text(...)` truncates the file before the
    new bytes land, so a reader racing it can see a partial or empty file
    and raise `JSONDecodeError` - exactly the flake orchestrator review of
    PR #94 found in `test_execute_cancellation_kills_the_container` (#77):
    `kill` and `exec`'s own background write raced `inspect`, which then
    exited nonzero on a decode error rather than "no such object" -
    `DockerBackend._inspect_status` correctly read that as UNKNOWN, not a
    guess, but the fixture's own write was the actual bug.
    """
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.tmp-")
    try:
        with os.fdopen(fd, "w") as tmp_file:
            tmp_file.write(json.dumps(data))
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def _rewrite_state(
    state_dir: Path, name: str, mutate: Callable[[dict], dict],
) -> dict:
    """Read-modify-write NAME's state file under an exclusive per-name file
    lock, so two independent writers (`kill`'s status flip and `exec`'s own
    `finally` block clearing `exec_pid`, run from separate OS processes)
    can never lose one's update to the other's stale read - the other half
    of the same race `_atomic_write_json` closes for readers. `mutate`
    receives the CURRENT on-disk dict (never a snapshot taken before the
    lock was acquired) and returns the dict to write, so whichever writer
    runs last always builds on the other's result - a status flip to
    `"exited"` is never silently overwritten back to `"running"` by a
    write that started earlier but finished later.
    """
    lock_path = state_dir / f".lock-{name}"
    with open(lock_path, "a+") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            path = _state_file(state_dir, name)
            data = json.loads(path.read_text(encoding="utf-8"))
            data = mutate(data)
            _atomic_write_json(path, data)
            return data
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


def _write_state(
    state_dir: Path, name: str, status: str, image: str, env: dict[str, str], labels: dict[str, str],
    container_id: str,
) -> None:
    _atomic_write_json(
        _state_file(state_dir, name),
        {"status": status, "image": image, "env": env, "labels": labels, "id": container_id},
    )


def _resolve_name(state_dir: Path, ref: str) -> str | None:
    """`ref` may be a container NAME (state files are keyed by name) or an
    ID (`run`'s freshly generated `id`, #79) - real docker accepts either
    for `rm`. Tries the direct name lookup first (the common case, and the
    only one that works before any container has ever been created, when
    `state_dir` itself may not exist yet); falls back to a linear scan by
    `id` only if that misses."""
    direct = _state_file(state_dir, ref)
    if direct.is_file():
        return ref
    if not state_dir.is_dir():
        return None
    for path in state_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("id") == ref:
            return path.stem
    return None


def cmd_version(state_dir: Path, _rest: list[str]) -> int:
    if (state_dir / ".down").exists():
        return 1
    print("26.0.0-fake")
    return 0


def cmd_ps(state_dir: Path, rest: list[str]) -> int:
    """`-a` is accepted and ignored (this fake always shows every container);
    every repeated `--filter label=KEY=VALUE` narrows the result, ANDed
    together (#79). `--format` decides what's printed: a template containing
    `.ID` prints each match's `id` (see `run`'s freshly generated one,
    below); anything else (including the default, or an explicit `.Names`)
    prints the container's name - one per line either way. `.down` (an
    unreachable daemon) is handled by `main()` before any subcommand handler
    runs - not re-checked here."""
    wanted: dict[str, str] = {}
    want_id = False
    i = 0
    while i < len(rest):
        arg = rest[i]
        if arg == "--filter" and i + 1 < len(rest):
            raw = rest[i + 1]
            if raw.startswith("label="):
                k, _, v = raw[len("label="):].partition("=")
                wanted[k] = v
            i += 2
        elif arg == "--format" and i + 1 < len(rest):
            want_id = ".ID" in rest[i + 1]
            i += 2
        else:
            i += 1  # -a, or anything else: accepted, unused
    if not state_dir.is_dir():
        return 0
    for path in sorted(state_dir.glob("*.json")):
        name = path.stem
        data = json.loads(path.read_text(encoding="utf-8"))
        labels = data.get("labels", {})
        if all(labels.get(k) == v for k, v in wanted.items()):
            print(data.get("id", name) if want_id else name)
    return 0


def cmd_inspect(state_dir: Path, rest: list[str]) -> int:
    name = rest[-1]
    if (state_dir / f".inspect-error-{name}").exists():
        # An UNRECOGNIZED daemon-side error (permission denial, TLS failure,
        # ...) - the same non-zero exit real docker also uses for "no such
        # object", but a DIFFERENT message. DockerBackend must treat this as
        # UNKNOWN, never as a confirmed absence.
        print("Error: permission denied while trying to inspect", file=sys.stderr)
        return 1
    path = _state_file(state_dir, name)
    if not path.is_file():
        print("Error: No such object: " + name, file=sys.stderr)
        return 1
    data = json.loads(path.read_text(encoding="utf-8"))
    if "{{.Image}}" in rest:
        # The image id the container was CREATED from (#12): the same
        # deterministic fake digest `image inspect` prints for that image, so
        # a ledger digest resolved through `image inspect` matches it. A
        # `.image-id-NAME` sentinel overrides it (a tag republished between
        # planning and the run); `.no-image-id-NAME` makes this one query fail.
        if (state_dir / f".no-image-id-{name}").exists():
            print("Error: permission denied while trying to inspect", file=sys.stderr)
            return 1
        override = state_dir / f".image-id-{name}"
        print(override.read_text(encoding="utf-8").strip() if override.is_file()
              else f"sha256:fake-digest-for-{data.get('image', '')}")
        return 0
    print(data.get("status", "unknown"))
    return 0


def cmd_image(state_dir: Path, rest: list[str]) -> int:
    if not rest or rest[0] != "inspect":
        print(f"fake_docker: unimplemented image subcommand {rest!r}", file=sys.stderr)
        return 2
    if (state_dir / ".no-image").exists():
        print("Error: No such image", file=sys.stderr)
        return 1
    image = rest[1] if len(rest) > 1 else ""
    print(f"sha256:fake-digest-for-{image}")
    return 0


def cmd_rm(state_dir: Path, rest: list[str]) -> int:
    """Real container removal reaps everything still running inside it,
    exec'd sessions included - `cmd_kill` (issue #158) already does this
    same `os.killpg`-with-SIGKILL reaping too, matching a real daemon's own
    kernel-level PID-namespace teardown once a `kill`'d container's PID 1
    dies. This is the backstop for a caller that removes a container
    WITHOUT a preceding `kill` at all (`destroy()` is always called, but
    not every test path drives a timeout/cancellation through `_stop()`
    first) - without it, a subject that never received any `kill` call
    would outlive its "removed" container, the same class of leak `kill`
    itself exists to prevent."""
    ref = rest[-1]
    name = _resolve_name(state_dir, ref) or ref
    path = _state_file(state_dir, name)
    if _stuck(state_dir, name):
        return 0  # lies: reports success, leaves the state file in place
    if not path.is_file():
        print("Error: No such container: " + ref, file=sys.stderr)
        return 1
    data = json.loads(path.read_text(encoding="utf-8"))
    pid = data.get("exec_pid")
    if isinstance(pid, int):
        try:
            os.killpg(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    path.unlink()
    shutil.rmtree(_container_root(state_dir, name), ignore_errors=True)
    return 0


def cmd_kill(state_dir: Path, rest: list[str]) -> int:
    """Fidelity-matched to real Docker (issue #158, corrected once - see git
    history for the intermediate "pure status flip" version this replaces,
    which was wrong in the other direction). `docker kill` reaches only the
    CONTAINER's own placeholder/PID-1 process (`tini`, wrapping
    `sleep infinity` - see `run -d`'s own docstring for why this fake has no
    real PID-1 subprocess to signal), never a separately exec'd session
    directly - but a real daemon does NOT leave that exec'd session running
    either: when PID 1 exits (TERM forwarded to `sleep`, which exits, then
    `tini` exits - or PID 1 dies outright under an unblockable SIGKILL), the
    container stops and the KERNEL sigkills every other process left in its
    PID namespace, exec sessions included. So the subject never receives a
    graceful TERM (that part of the earlier fix stands - #158's whole
    premise), but it does not survive `docker kill` either, whatever signal
    was requested: it dies by SIGKILL, as a side effect of the container's
    own PID-1 dying, not because anything forwarded a signal to it on
    purpose. Modeling `kill` as a bare status flip left a fake where the
    container reads "stopped" while the subject keeps running - a new blind
    spot a real daemon does not have, and one a caller could not tell apart
    from #158's actual bug by reading `confirm_stopped()` alone.

    So: flip status to "exited" AND `os.killpg` the recorded `exec_pid` with
    SIGKILL - never the requested `--signal` value, since the subject's
    death here is the kernel's PID-namespace teardown, not a forwarded
    signal. `--signal` is still accepted (argv-shape parity with real
    `docker kill`) but never changes what signal actually reaches the
    subject. A `.stuck-NAME` sentinel still short-circuits all of this
    (simulating a container that ignores the signal entirely, a daemon lie
    `confirm_stopped()` must not trust) - neither the status nor the
    subject changes. `cmd_rm`'s own docstring covers the separate,
    still-needed removal-time reaping for a `rm -f` a caller issues without
    a preceding `kill` at all."""
    name = rest[-1] if rest else ""
    path = _state_file(state_dir, name)
    if not path.is_file():
        print("Error: No such container: " + name, file=sys.stderr)
        return 1
    if _stuck(state_dir, name):
        return 0  # lies: reports success without actually stopping anything
    data = json.loads(path.read_text(encoding="utf-8"))
    pid = data.get("exec_pid")
    if isinstance(pid, int):
        try:
            os.killpg(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    _rewrite_state(state_dir, name, lambda d: {**d, "status": "exited"})
    return 0


def _remap_absolute(state_dir: Path, name: str, value: str) -> str:
    """A real `docker exec` resolves an absolute argv path inside the
    container's OWN filesystem; this fake has no real chroot, only a `cwd=`
    change for the subprocess it launches, which resolves RELATIVE paths but
    does nothing for an absolute one. An argv element under the fixed
    workspace prefix (`/work`, `/work/...`) is rewritten to this container's
    fsroot equivalent - found by #81's own demo command, whose probe
    invocation (`verify.py`'s own convention) passes an absolute path
    (`/work/probe.py`) that failed with "No such file or directory" against
    the pre-fix fake, even though the file genuinely existed in the
    container's simulated filesystem - `cwd=` alone never helped it.

    The home prefix (`/home/candidate`) is remapped the same way, and as a
    substring anywhere in the token, not only a whole-argv-element match
    (issue #101): `env CODEX_HOME=/home/candidate/.codex codex ...` names the
    container's home path INSIDE a `VAR=value` token, never as its own argv
    element, and a whole-token check alone would leave it unrewritten -
    pointing a discovery listing at a literal host path that is not this
    fake's simulated filesystem at all, rather than at `deliver_home_file`'s
    own `<fsroot>/home/candidate`."""
    for prefix in (WORK_CONTAINER_PATH, HOME_CONTAINER_PATH):
        mapped = str(_in_container(state_dir, name, prefix))
        if value == prefix:
            return mapped
        if prefix + "/" in value:
            value = value.replace(prefix + "/", mapped + "/")
    return value


def cmd_exec(state_dir: Path, rest: list[str]) -> int:
    i = 0
    interactive = False
    workdir = "/"
    while i < len(rest):
        arg = rest[i]
        if arg == "-i":
            interactive = True
            i += 1
        elif arg == "-w":
            workdir = rest[i + 1]
            i += 2
        elif arg == "--":
            i += 1
            break
        else:
            break
    if i >= len(rest):
        print("fake_docker: exec requires NAME ARGV...", file=sys.stderr)
        return 2
    name = rest[i]
    argv = [_remap_absolute(state_dir, name, a) for a in rest[i + 1:]]
    path = _state_file(state_dir, name)
    if not path.is_file():
        print("Error: No such container: " + name, file=sys.stderr)
        return 1
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("status") != "running":
        print(f"Error: Container {name} is not running", file=sys.stderr)
        return 1
    cwd = _in_container(state_dir, name, workdir)
    cwd.mkdir(parents=True, exist_ok=True)
    env = {"PATH": os.environ.get("PATH", "")}
    env.update(data.get("env", {}))
    try:
        proc = subprocess.Popen(
            argv, cwd=cwd, env=env,
            stdin=(sys.stdin if interactive else subprocess.DEVNULL),
            start_new_session=True,  # so `kill` can os.killpg() the whole tree, not just this one pid
        )
    except OSError:
        print(f"OCI runtime exec failed: exec: {argv[0]!r}: executable file not found", file=sys.stderr)
        return 127
    # Recorded so a SEPARATE `docker kill` invocation - a different OS
    # process, sharing nothing but this state file - can actually reach and
    # signal it. See cmd_kill's own docstring. Locked read-modify-write
    # (`_rewrite_state`), not a blind write of `data`: a concurrent `kill`
    # could otherwise still be holding an EARLIER read of this same file,
    # and whichever of the two writes lands second would silently discard
    # the other's update.
    _rewrite_state(state_dir, name, lambda d: {**d, "exec_pid": proc.pid})
    try:
        proc.wait()
    finally:
        if path.is_file():
            # Mutates whatever is CURRENTLY on disk, never the `data` this
            # function read at entry: a concurrent `kill` may have flipped
            # `status` to `"exited"` in between, and that must survive this
            # write untouched - only `exec_pid` is ever removed here.
            _rewrite_state(state_dir, name, lambda d: {k: v for k, v in d.items() if k != "exec_pid"})
    return proc.returncode


def _copy_any(src: Path, dst: Path) -> None:
    if src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=True)
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def _is_container_ref(token: str) -> tuple[str, str] | None:
    """`NAME:PATH` - never confused with an absolute host path (which never
    contains `:`) or a Windows-style path (not a concern on this fixture's
    only target platform, linux)."""
    if ":" not in token:
        return None
    name, _, path = token.partition(":")
    if not name or not path.startswith("/"):
        return None
    return name, path


def cmd_cp(state_dir: Path, rest: list[str]) -> int:
    if len(rest) != 2:
        print("fake_docker: cp requires SRC DEST", file=sys.stderr)
        return 2
    src, dest = rest

    if src == "-":
        # A tar stream on stdin, extracted into the container - what
        # `DockerBackend.install()` uses so it controls every member's
        # ownership itself, rather than a plain host-path copy (which would
        # preserve the SOURCE's own uid/gid, never the fixed candidate one).
        dest_ref = _is_container_ref(dest)
        if not dest_ref:
            print("fake_docker: cp - requires a NAME:PATH destination", file=sys.stderr)
            return 2
        name, cpath = dest_ref
        if not _state_file(state_dir, name).is_file():
            print(f"Error: No such container: {name}", file=sys.stderr)
            return 1
        mapped = _in_container(state_dir, name, cpath)
        mapped.mkdir(parents=True, exist_ok=True)
        try:
            with tarfile.open(fileobj=sys.stdin.buffer, mode="r|*") as tar:
                tar.extractall(mapped, filter="data")
        except tarfile.TarError as exc:
            print(f"Error: bad tar stream: {exc}", file=sys.stderr)
            return 1
        return 0

    if dest == "-":
        # The reverse of the `src == "-"` case above: a tar stream OUT to
        # stdout (`docker_backend.DockerBackend.read_home_file`, #98), rather
        # than a plain host-directory copy - real `docker cp` supports both
        # directions of `-`, and a caller reading a single file back (to
        # compare against what it delivered) needs the stream form, not a
        # directory dumped on disk.
        src_ref = _is_container_ref(src)
        if not src_ref:
            print("fake_docker: cp SRC - requires a NAME:PATH source", file=sys.stderr)
            return 2
        name, cpath = src_ref
        if not _state_file(state_dir, name).is_file():
            print(f"Error: No such container:path: {src}", file=sys.stderr)
            return 1
        mapped = _in_container(state_dir, name, cpath)
        if not mapped.exists():
            print(f"Error: No such container:path: {src}", file=sys.stderr)
            return 1
        with tarfile.open(fileobj=sys.stdout.buffer, mode="w|") as tar:
            tar.add(mapped, arcname=Path(cpath).name)
        return 0

    src_ref = _is_container_ref(src)
    dest_ref = _is_container_ref(dest)

    if src_ref and not dest_ref:
        name, cpath = src_ref
        if not _state_file(state_dir, name).is_file():
            print(f"Error: No such container:path: {src}", file=sys.stderr)
            return 1
        trailing_dot = cpath.endswith("/.")
        clean = cpath[:-2] if trailing_dot else cpath
        mapped = _in_container(state_dir, name, clean)
        if not mapped.exists():
            print(f"Error: No such container:path: {src}", file=sys.stderr)
            return 1
        dest_path = Path(dest)
        dest_path.mkdir(parents=True, exist_ok=True)
        if mapped.is_dir() and trailing_dot:
            for item in mapped.iterdir():
                _copy_any(item, dest_path / item.name)
        else:
            _copy_any(mapped, dest_path / mapped.name)
        return 0

    if dest_ref and not src_ref:
        name, cpath = dest_ref
        if not _state_file(state_dir, name).is_file():
            print(f"Error: No such container: {name}", file=sys.stderr)
            return 1
        src_path = Path(src)
        if not src_path.exists():
            print(f"Error: no such file or directory: {src}", file=sys.stderr)
            return 1
        mapped = _in_container(state_dir, name, cpath)
        mapped.parent.mkdir(parents=True, exist_ok=True)
        _copy_any(src_path, mapped)
        return 0

    print("fake_docker: cp requires exactly one of SRC/DEST to be NAME:PATH", file=sys.stderr)
    return 2


def cmd_run(state_dir: Path, rest: list[str]) -> int:
    name = ""
    detached = False
    env: dict[str, str] = {}
    labels: dict[str, str] = {}
    i = 0
    while i < len(rest):
        arg = rest[i]
        if arg in ("--rm", "--init"):
            i += 1
        elif arg == "-d":
            detached = True
            i += 1
        elif arg == "--name":
            name, i = rest[i + 1], i + 2
        elif arg == "-e":
            k, _, v = rest[i + 1].partition("=")
            env[k] = v
            i += 2
        elif arg == "--label":
            k, _, v = rest[i + 1].partition("=")
            labels[k] = v
            i += 2
        elif arg in _FLAGS_WITH_VALUE:
            i += 2  # consume and ignore the value; not needed for the simulation
        elif arg.startswith("-"):
            i += 1  # an unrecognized boolean flag: skip just the flag itself
        else:
            break  # first non-flag token is the image
    image = rest[i] if i < len(rest) else ""
    argv = rest[i + 1:]

    if (state_dir / ".refuse-run").exists():
        print("Error response from daemon: container creation refused (fault injection)", file=sys.stderr)
        return 1

    state_dir.mkdir(parents=True, exist_ok=True)
    _in_container(state_dir, name, WORK_CONTAINER_PATH).mkdir(parents=True, exist_ok=True)
    # One fresh id per CALL to run - a new instance every time, even when a
    # later run reuses the same --name (#79): reap.py acts and confirms by
    # this id, never by name, so a foreign replacement under a reused name
    # is never mistaken for the container an earlier reap() call targeted.
    container_id = uuid.uuid4().hex[:12]

    if detached:
        hang = state_dir / ".hang-run"
        if hang.exists():
            duration_text = hang.read_text(encoding="utf-8").strip()
            time.sleep(float(duration_text) if duration_text else 2.0)
        if (state_dir / ".refuse-start").exists():
            # Simulates a container Docker CREATED but that then failed to
            # actually START (e.g. an image missing the placeholder binary):
            # the state file/fsroot are left behind as a real orphan would
            # be, so a test can prove DockerBackend.prepare() cleans it up
            # itself before raising, per backend.py's own stated contract.
            _write_state(state_dir, name, "created", image, env, labels, container_id)
            print("Error response from daemon: OCI runtime create failed (fault injection)", file=sys.stderr)
            return 1
        _write_state(state_dir, name, "running", image, env, labels, container_id)
        return 0

    _write_state(state_dir, name, "running", image, env, labels, container_id)
    try:
        proc = subprocess.run(argv, cwd=_in_container(state_dir, name, WORK_CONTAINER_PATH), env=env, check=False)
    except OSError as exc:
        print(f"docker: Error response from daemon: {exc}", file=sys.stderr)
        return 125
    # --rm: only reached on a normal return, exactly like a real container
    # whose process exited - a SIGKILL of THIS fake never reaches here, which
    # is the scenario DockerBackend's own destroy() exists to close.
    if _stuck(state_dir, name):
        _write_state(state_dir, name, "exited", image, env, labels, container_id)
        return proc.returncode
    path = _state_file(state_dir, name)
    if path.is_file():
        path.unlink()
    shutil.rmtree(_container_root(state_dir, name), ignore_errors=True)
    return proc.returncode


SUBCOMMANDS = {
    "run": cmd_run, "inspect": cmd_inspect, "rm": cmd_rm, "version": cmd_version,
    "kill": cmd_kill, "exec": cmd_exec, "cp": cmd_cp, "ps": cmd_ps,
}


def main(argv: list[str]) -> int:
    if len(argv) < 3 or argv[0] != "--state":
        print("fake_docker: usage: fake_docker.py --state DIR <subcommand> ...", file=sys.stderr)
        return 2
    state_dir = Path(argv[1])
    subcommand, rest = argv[2], argv[3:]
    # `.down` simulates an unreachable daemon for EVERY subcommand, not just
    # `version` - a real unreachable daemon fails every CLI call the same
    # way, and DockerBackend._inspect_status() distinguishes this from "no
    # such object" only by this exact message substring.
    if subcommand != "version" and (state_dir / ".down").exists():
        print("Cannot connect to the Docker daemon. Is the docker daemon running?", file=sys.stderr)
        return 1
    if subcommand == "image":
        return cmd_image(state_dir, rest)
    handler = SUBCOMMANDS.get(subcommand)
    if handler is None:
        print(f"fake_docker: unimplemented subcommand {subcommand!r}", file=sys.stderr)
        return 2
    return handler(state_dir, rest)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
