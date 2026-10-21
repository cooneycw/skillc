"""The Step-6 task's behavioural oracle (#279 PR-3): does the DELIVERED
`widget/core.py` behave like the fix, whatever its wording?

The step6 grader's `work-preserved` (S4) used to credit only a declared blob
identity (the necessity builder's `_FIXED_CORE`): a correct fix worded
differently read UNKNOWN, and a broken edit read UNKNOWN instead of VIOLATED.
This module runs held-out `parse()` cases against each delivered copy and
returns its OUTPUTS; the judge holds the expected values and compares.

SUBJECT BYTES ARE NEVER EXECUTED ON THE CONTROLLER HOST (orchestrator
condition C1). `python3 -I -S -B` is not a sandbox. Every run is a throwaway
container from the measured trial image:

  - `--network none`, no mounts (sources and inputs go in over STDIN);
  - non-root (`--user 65534:65534`), `--cap-drop ALL`, no new privileges;
  - `--read-only` root filesystem and NO writable mount (not even /tmp): a
    delivered side effect fails, so such code never passes (the live red);
  - memory, pid and CPU limits, and a wall-clock timeout that removes the
    container;
  - each source runs in its OWN child process, under its own timeout, so one
    infinite loop costs only its own verdict.

`runner_for(backend)` refuses anything that is not a Docker backend: there is
no host fallback, by construction.

HELD OUT, NOT SECRET (C3). The case inputs live here, in skillc, which is
public; they are absent from the agent's tree and reach the container only on
stdin. The delivered code sees each input as it is called with it, never the
expected output.

A FORGED RESULT IS BOUNDED TO BEING CORRECT (counter-model review). The
delivered code shares its child process with the line that reports results,
so it could print a result list and exit without ever defining `parse()`. A
fixed, public case list alone would let it print the known answers. So every
run also carries `CHALLENGES` fresh random inputs, drawn in the container by
the trusted harness BEFORE the child starts; the outcome records every input,
and the judge recomputes every expected output with its own reference
`parse()`. Printing a passing list therefore requires computing `parse()`
correctly on inputs nobody saw in advance.

Stdlib only.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import subprocess
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from .docker_backend import OWNER_LABEL_KEY, OWNER_LABEL_VALUE

#: The held-out inputs. The judge holds the expected outputs (and a test pins
#: the two lists against each other).
CASES: tuple[str, ...] = ("", "# note", "a, b,c", " x ", "#", "a,,b")
#: Random challenge inputs per run, drawn in the container (see the docstring).
CHALLENGES = 8
#: A delivered source larger than this is not run (UNKNOWN).
MAX_SOURCE_BYTES = 64 * 1024
#: Per-source child timeout inside its container, and each container's whole run.
#: Every source runs in its OWN container, so one source never costs another's
#: verdict (counter-model review).
CHILD_SECONDS = 5
CONTAINER_SECONDS = 30

#: Runs one source: exec its module code, call `parse` on each input, print one
#: JSON line of results. A value that is not a list of strings is reported by
#: its type name, never trusted further.
_CHILD = r"""
import json, sys
job = json.loads(sys.stdin.read())
namespace = {"__name__": "widget.core"}
exec(compile(job["source"], "widget/core.py", "exec"), namespace)
parse = namespace["parse"]
results = []
for arg in job["inputs"]:
    try:
        value = parse(arg)
    except Exception as exc:
        results.append({"error": type(exc).__name__})
        continue
    if isinstance(value, list) and all(type(item) is str for item in value):
        results.append({"value": list(value)})
    else:
        results.append({"type": type(value).__name__})
sys.stdout.write("\n" + json.dumps(results) + "\n")
"""

#: Runs in the container: draws the challenge inputs, then runs the ONE
#: source in a child under its own timeout.
_HARNESS = r"""
import base64, json, random, subprocess, sys
job = json.loads(sys.stdin.read())
rng = random.SystemRandom()
alphabet = "ab#, x"
inputs = list(job["cases"]) + ["".join(rng.choice(alphabet) for _ in range(rng.randint(0, 9)))
                                for _ in range(job["challenges"])]
source = base64.b64decode(job["source"]).decode("utf-8", errors="replace")
try:
    done = subprocess.run([sys.executable, "-I", "-S", "-B", "-c", job["child"]],
                          input=json.dumps({"source": source, "inputs": inputs}),
                          capture_output=True, text=True, timeout=job["child_seconds"])
except subprocess.TimeoutExpired:
    out = {"status": "timeout"}
else:
    lines = [line for line in done.stdout.splitlines() if line.strip()]
    try:
        results = json.loads(lines[-1]) if done.returncode == 0 and lines else None
    except ValueError:
        results = None
    if not isinstance(results, list) or len(results) != len(inputs):
        out = {"status": "error", "exit": done.returncode}
    else:
        out = {"status": "ran", "inputs": inputs, "results": results}
sys.stdout.write(job["nonce"] + json.dumps(out) + "\n")
"""


class Refused(RuntimeError):
    """The oracle cannot run where it was asked to (never a host backend)."""


#: `(sources by location) -> outcomes by location`.
Runner = Callable[[Mapping[str, bytes]], dict[str, dict[str, Any]]]


def _container_argv(docker_bin: Sequence[str], image: str, name: str) -> list[str]:
    return [*docker_bin, "run", "--rm", "-i", "--name", name,
            # No writable filesystem at all: a delivered side effect (a file
            # written anywhere, /tmp included) fails, so it can never pass.
            # `--ipc none` removes /dev/shm and /dev/mqueue, the writable
            # mounts `--read-only` leaves (counter-model review).
            "--network", "none", "--read-only", "--ipc", "none", "--pull", "never",
            "--user", "65534:65534", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--memory", "256m", "--memory-swap", "256m", "--pids-limit", "64", "--cpus", "1",
            "--label", f"{OWNER_LABEL_KEY}={OWNER_LABEL_VALUE}", "--label", "skillc.purpose=step6-oracle",
            "--entrypoint", "/usr/bin/python3", "--workdir", "/", image, "-I", "-S", "-B", "-c", _HARNESS]


def container_runner(docker_bin: Sequence[str], image: str, *,
                     env: Mapping[str, str] | None = None) -> Runner:
    """A runner that executes each delivered source only in its OWN throwaway
    container of `image` - the attempt's measured, immutable image ID."""
    docker_env = dict(env) if env is not None else None

    def one(data: bytes) -> dict[str, Any]:
        nonce = secrets.token_hex(16)
        name = f"skillc-step6-oracle-{nonce[:12]}"
        job = json.dumps({"source": base64.b64encode(data).decode("ascii"), "cases": list(CASES),
                          "challenges": CHALLENGES, "child": _CHILD, "child_seconds": CHILD_SECONDS,
                          "nonce": nonce})
        try:
            done = subprocess.run(_container_argv(docker_bin, image, name), input=job, capture_output=True,
                                  text=True, timeout=CONTAINER_SECONDS, env=docker_env, check=False)
        except subprocess.TimeoutExpired:
            subprocess.run([*docker_bin, "rm", "-f", name], capture_output=True, timeout=30, check=False,
                           env=docker_env)
            return {"status": "container-timeout"}
        line = next((ln for ln in reversed(done.stdout.splitlines()) if ln.startswith(nonce)), None)
        try:
            parsed = json.loads(line[len(nonce):]) if line is not None else None
        except ValueError:
            parsed = None
        if done.returncode != 0 or not isinstance(parsed, dict):
            return {"status": "container-failed", "exit": done.returncode}
        return dict(parsed)

    def run(sources: Mapping[str, bytes]) -> dict[str, dict[str, Any]]:
        return {name: ({"status": "over-bound"} if len(data) > MAX_SOURCE_BYTES else one(data))
                for name, data in sources.items()}
    return run


def runner_for(backend: object, handle: object = None) -> Runner:
    """The container runner for an attempt's backend - refused for anything
    that is not a Docker backend, or whose attempt image cannot be measured
    (C1: never the host; and never a tag that could have moved)."""
    from .docker_backend import DockerBackend, _docker_env
    if not isinstance(backend, DockerBackend):
        raise Refused(f"the Step-6 oracle runs only in a container; {type(backend).__name__} is not a Docker backend")
    image = backend.image_id(handle) if handle is not None else None
    if not isinstance(image, str) or not image.startswith("sha256:"):
        raise Refused("the Step-6 oracle needs the attempt's measured image ID; it is unavailable")
    return container_runner(tuple(backend.docker_bin), image, env=_docker_env())


def outcomes(sources: Mapping[str, dict[str, Any]], runner: Runner) -> dict[str, dict[str, Any]]:
    """The capture's `fix_sources` (base64 bytes, or a status) turned into
    `fix_outcomes`: each location's oracle result and its source digest. The
    bytes themselves never reach the judge."""
    readable = {name: base64.b64decode(str(entry["source_b64"])) for name, entry in sources.items()
                if entry.get("status") == "read"}
    ran = runner(readable) if readable else {}
    result: dict[str, dict[str, Any]] = {}
    for name, entry in sources.items():
        if entry.get("status") != "read":
            result[name] = {"status": str(entry.get("status"))}
            continue
        data = readable[name]
        result[name] = {**ran.get(name, {"status": "not-run"}), "sha256": hashlib.sha256(data).hexdigest()}
    return result
