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
        than a fallback.
    exec [-i] -w WORKDIR -- NAME ARGV...
        Requires NAME's state to be "running" (else exit 1, "No such
        container" or "is not running"). Runs ARGV as a real subprocess
        (its own new session, so a `kill` can `os.killpg()` the whole tree)
        with cwd = NAME's fsroot directory at WORKDIR, and env = PATH plus
        whatever `-e` pairs `run -d` recorded for NAME - simulating that
        `docker exec` runs with the CONTAINER's own declared environment,
        never the `docker exec` CLI client's own ambient environment. Records
        the child's pid on NAME's state file for the duration of the call -
        `kill` (a SEPARATE OS process, sharing nothing but this state file)
        reads it back to signal the right process for real, since a bare
        status flip would leave a real timed-out subject running forever
        while the backend believed it had stopped. `-i` passes this fake's
        own stdin through to ARGV, exactly as a real `docker exec -i` would.
        Exits with ARGV's own exit code, or 127 if ARGV's own binary cannot
        be found (docker's own convention for that case).
    kill [--signal SIG] NAME
        Signals the pid recorded by a still-running `exec` (`os.killpg`,
        `SIG` or `SIGKILL` if unspecified) and sets NAME's status to
        "exited", returning 0 - UNLESS a `.stuck-NAME` sentinel exists, in
        which case it reports success without signaling anything or changing
        the state (simulating a container that ignores the signal, a daemon
        lie `confirm_stopped()` must not trust).
    cp SRC DEST
        Exactly one of SRC/DEST is a `NAME:PATH` reference; the other is an
        ordinary host path. Host -> container copies a file or directory
        into NAME's fsroot at PATH (creating parent directories as needed).
        Container -> host requires NAME:PATH to exist; a trailing `/.` on
        PATH copies PATH's CONTENTS into DEST (DEST must already exist, as a
        real `docker cp`'s directory-contents form requires), otherwise PATH
        itself is copied into DEST as a new entry named after PATH's own
        basename. Exits 1 (no such container/path) or 2 (bad usage) on the
        failure paths `DockerBackend.export()`/`install()` must handle.
    inspect --format {{.State.Status}} NAME
        Prints the state file's status, or exits 1 if absent ("No such
        object").
    image inspect IMAGE --format {{.Id}}
        Prints a deterministic fake digest for IMAGE, unless a `.no-image`
        sentinel exists in the state dir, in which case it exits 1
        (simulating an unpullable/unknown image).
    rm -f NAME
        Deletes the state file and NAME's fsroot directory, and exits 0.
        EXCEPT: if a `.stuck-NAME` sentinel exists in the state dir, exits 0
        WITHOUT deleting either - simulating a daemon that reports successful
        removal while the container is still there. The fixture's own
        negative control: proves a caller's post-rm `inspect` (never trusting
        rm's exit code alone) actually catches this.
    version --format {{.Server.Version}}
        Prints a fixed version and exits 0, unless a `.down` sentinel exists
        in the state dir, in which case it exits 1 with nothing printed - an
        unreachable daemon.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

#: Must match docker_backend.CONTAINER_WORKSPACE. Kept as a separate literal
#: on purpose (this fixture does not import skillc): it is a fake CLI, not a
#: client of the module under test.
WORK_CONTAINER_PATH = "/work"

_FLAGS_WITH_VALUE = (
    "--network", "--user", "--hostname", "--memory", "--memory-swap",
    "--pids-limit", "--cpus", "--shm-size", "-w", "--label", "--storage-opt",
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


def cmd_version(state_dir: Path, _rest: list[str]) -> int:
    if (state_dir / ".down").exists():
        return 1
    print("26.0.0-fake")
    return 0


def cmd_inspect(state_dir: Path, rest: list[str]) -> int:
    name = rest[-1]
    path = _state_file(state_dir, name)
    if not path.is_file():
        print("Error: No such object: " + name, file=sys.stderr)
        return 1
    data = json.loads(path.read_text(encoding="utf-8"))
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
    name = rest[-1]
    path = _state_file(state_dir, name)
    if _stuck(state_dir, name):
        return 0  # lies: reports success, leaves the state file in place
    if not path.is_file():
        print("Error: No such container: " + name, file=sys.stderr)
        return 1
    path.unlink()
    shutil.rmtree(_container_root(state_dir, name), ignore_errors=True)
    return 0


def cmd_kill(state_dir: Path, rest: list[str]) -> int:
    """Unlike `run`/`exec`, a `kill` invocation is a SEPARATE OS process from
    whichever `exec` is still blocked in its own `subprocess.run` - there is
    no shared memory between them, only the state file. So killing for real
    means reading the exec'd process's own pid back out of the state file
    (`cmd_exec` records it there before waiting) and signaling it directly -
    a status flip alone would leave a real timed-out subject running forever
    while `DockerBackend.execute()` believed it had stopped."""
    sig = signal.SIGKILL
    if "--signal" in rest:
        idx = rest.index("--signal")
        raw = rest[idx + 1]
        sig = getattr(signal, raw if raw.startswith("SIG") else f"SIG{raw}", signal.SIGKILL)
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
            os.killpg(pid, sig)
        except (ProcessLookupError, PermissionError):
            pass
    data["status"] = "exited"
    path.write_text(json.dumps(data))
    return 0


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
    argv = rest[i + 1:]
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
    # signal it. See cmd_kill's own docstring.
    data["exec_pid"] = proc.pid
    path.write_text(json.dumps(data))
    try:
        proc.wait()
    finally:
        if path.is_file():
            latest = json.loads(path.read_text(encoding="utf-8"))
            latest.pop("exec_pid", None)
            path.write_text(json.dumps(latest))
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

    if detached:
        _state_file(state_dir, name).write_text(json.dumps({"status": "running", "image": image, "env": env}))
        return 0

    _state_file(state_dir, name).write_text(json.dumps({"status": "running", "image": image, "env": env}))
    try:
        proc = subprocess.run(argv, cwd=_in_container(state_dir, name, WORK_CONTAINER_PATH), env=env, check=False)
    except OSError as exc:
        print(f"docker: Error response from daemon: {exc}", file=sys.stderr)
        return 125
    # --rm: only reached on a normal return, exactly like a real container
    # whose process exited - a SIGKILL of THIS fake never reaches here, which
    # is the scenario DockerBackend's own destroy() exists to close.
    if _stuck(state_dir, name):
        _state_file(state_dir, name).write_text(json.dumps({"status": "exited", "image": image, "env": env}))
        return proc.returncode
    path = _state_file(state_dir, name)
    if path.is_file():
        path.unlink()
    shutil.rmtree(_container_root(state_dir, name), ignore_errors=True)
    return proc.returncode


SUBCOMMANDS = {
    "run": cmd_run, "inspect": cmd_inspect, "rm": cmd_rm, "version": cmd_version,
    "kill": cmd_kill, "exec": cmd_exec, "cp": cmd_cp,
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
