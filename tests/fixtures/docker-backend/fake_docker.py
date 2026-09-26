"""A deterministic stand-in for the `docker` CLI (#10), for tests with no
daemon.

    fake_docker.py --state DIR <subcommand> ...

`--state DIR` must come first: it is where this fake keeps its container
"daemon" state (one JSON file per container name), since each subcommand is a
separate process and needs somewhere durable to read what an earlier `run`
left behind. Passing it as part of `docker_bin` (the prefix `docker_backend.py`
puts in front of every docker invocation) means every call - run, inspect, rm,
version, image inspect - shares one state directory without any hidden
environment channel.

FAULT INJECTION IS FILE-BASED, NOT ENVIRONMENT-BASED, ON PURPOSE. A test's
`monkeypatch.setenv` reaches the `execute()`-launched `docker run` invocation
only by accident: `DockerBackend.execute()` deliberately calls it with
`env={"PATH": ...}` (never the launching process's own environment - that is
the property the `-e NAME=value`-only design exists to prove), while every
other call (`inspect`, `rm`, `version`, `image inspect`) inherits the full
environment because it never overrides `env=`. An env-var-based fault toggle
would therefore reach some subcommands and silently not others, depending on
which one happens to run it - found exercising exactly this: a
`FAKE_DOCKER_STUCK_NAME` env var set by a test never reached the `run`
subcommand, so the state file was already deleted (by `run`'s own `--rm`
simulation) before `destroy()`'s `rm -f` ever got a chance to lie about it.
Sentinel FILES under `--state DIR` reach every subcommand identically, since
the directory is passed as an explicit argv element, not inherited.

Subcommands, matching what `docker_backend.compose_run_argv` composes and
what the backend queries - this is not a docker clone:

    run --rm --name NAME --network N --user U --hostname H --init
        --memory M --memory-swap M --pids-limit P --cpus C --shm-size S
        -v HOST:CONTAINER:MODE [-v HOST:CONTAINER:MODE ...] -w WORKDIR
        [-e K=V ...] IMAGE ARGV...
        Writes {name}.json as "running", then runs ARGV as a real subprocess
        with cwd = the host side of the mount whose container path is
        "/work" (docker_backend.CONTAINER_WORKSPACE, hardcoded here too - see
        the module docstring's warning about keeping them in sync), and
        env = EXACTLY the given -e pairs, never this process's own
        environment. On a normal exit, deletes the state file (--rm) - UNLESS
        a `.stuck-NAME` sentinel exists in the state dir, in which case it
        writes "exited" instead: simulating a daemon whose auto-removal does
        not fire despite --rm (a daemon bug, or a container wedged
        "Removing"), the scenario an explicit destroy()/rm -f exists to
        catch. A SIGKILL of this fake (simulating execute()'s escalation)
        leaves the state file behind regardless - the fixture must not paper
        over that by cleaning up in a signal handler.
    inspect --format {{.State.Status}} NAME
        Prints the state file's status, or exits 1 if absent ("No such
        object").
    image inspect IMAGE --format {{.Id}}
        Prints a deterministic fake digest for IMAGE, unless a `.no-image`
        sentinel exists in the state dir, in which case it exits 1
        (simulating an unpullable/unknown image).
    rm -f NAME
        Deletes the state file and exits 0. EXCEPT: if a `.stuck-NAME`
        sentinel exists in the state dir, exits 0 WITHOUT deleting the state
        file - simulating a daemon that reports successful removal while the
        container is still there. The fixture's own negative control: proves
        a caller's post-rm `inspect` (never trusting rm's exit code alone)
        actually catches this.
    version --format {{.Server.Version}}
        Prints a fixed version and exits 0, unless a `.down` sentinel exists
        in the state dir, in which case it exits 1 with nothing printed - an
        unreachable daemon.
"""

from __future__ import annotations

import json
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
)


def _state_file(state_dir: Path, name: str) -> Path:
    return state_dir / f"{name}.json"


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
    return 0


def cmd_run(state_dir: Path, rest: list[str]) -> int:
    name = ""
    mounts: dict[str, str] = {}  # container path -> host path
    env: dict[str, str] = {}
    i = 0
    while i < len(rest):
        arg = rest[i]
        if arg in ("--rm", "--init"):
            i += 1
        elif arg == "--name":
            name, i = rest[i + 1], i + 2
        elif arg == "-v":
            parts = rest[i + 1].split(":")
            if len(parts) >= 2:
                mounts[parts[1]] = parts[0]
            i += 2
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
    host_work_dir = mounts.get(WORK_CONTAINER_PATH, "")

    state_dir.mkdir(parents=True, exist_ok=True)
    _state_file(state_dir, name).write_text(json.dumps({"status": "running", "image": image}))
    try:
        proc = subprocess.run(argv, cwd=host_work_dir or None, env=env, check=False)
    except OSError as exc:
        print(f"docker: Error response from daemon: {exc}", file=sys.stderr)
        return 125
    # --rm: only reached on a normal return, exactly like a real container
    # whose process exited - a SIGKILL of THIS fake never reaches here, which
    # is the scenario DockerBackend's own destroy() exists to close.
    if _stuck(state_dir, name):
        _state_file(state_dir, name).write_text(json.dumps({"status": "exited", "image": image}))
        return proc.returncode
    path = _state_file(state_dir, name)
    if path.is_file():
        path.unlink()
    return proc.returncode


SUBCOMMANDS = {"run": cmd_run, "inspect": cmd_inspect, "rm": cmd_rm, "version": cmd_version}


def main(argv: list[str]) -> int:
    if len(argv) < 3 or argv[0] != "--state":
        print("fake_docker: usage: fake_docker.py --state DIR <subcommand> ...", file=sys.stderr)
        return 2
    state_dir = Path(argv[1])
    subcommand, rest = argv[2], argv[3:]
    if subcommand == "image":
        return cmd_image(state_dir, rest)
    handler = SUBCOMMANDS.get(subcommand)
    if handler is None:
        print(f"fake_docker: unimplemented subcommand {subcommand!r}", file=sys.stderr)
        return 2
    return handler(state_dir, rest)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
