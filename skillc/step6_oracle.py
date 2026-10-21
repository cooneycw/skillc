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
expected output, so "predicting the expectations" is bounded to computing
`parse()` correctly.

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
#: A delivered source larger than this is not run (UNKNOWN).
MAX_SOURCE_BYTES = 64 * 1024
#: Per-source child timeout inside the container, and the container's whole run.
CHILD_SECONDS = 5
CONTAINER_SECONDS = 60

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

#: Runs in the container: one child per source, each under its own timeout.
_HARNESS = r"""
import base64, json, subprocess, sys
job = json.loads(sys.stdin.read())
out = {}
for name, encoded in job["sources"].items():
    source = base64.b64decode(encoded).decode("utf-8", errors="replace")
    try:
        done = subprocess.run([sys.executable, "-I", "-S", "-B", "-c", job["child"]],
                              input=json.dumps({"source": source, "inputs": job["inputs"]}),
                              capture_output=True, text=True, timeout=job["child_seconds"])
    except subprocess.TimeoutExpired:
        out[name] = {"status": "timeout"}
        continue
    lines = [line for line in done.stdout.splitlines() if line.strip()]
    try:
        results = json.loads(lines[-1]) if done.returncode == 0 and lines else None
    except ValueError:
        results = None
    if not isinstance(results, list) or len(results) != len(job["inputs"]):
        out[name] = {"status": "error", "exit": done.returncode}
    else:
        out[name] = {"status": "ran", "results": results}
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
            "--network", "none", "--read-only",
            "--user", "65534:65534", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--memory", "256m", "--memory-swap", "256m", "--pids-limit", "64", "--cpus", "1",
            "--label", f"{OWNER_LABEL_KEY}={OWNER_LABEL_VALUE}", "--label", "skillc.purpose=step6-oracle",
            "--entrypoint", "/usr/bin/python3", "--workdir", "/", image, "-I", "-S", "-B", "-c", _HARNESS]


def container_runner(docker_bin: Sequence[str], image: str, *,
                     env: Mapping[str, str] | None = None) -> Runner:
    """A runner that executes the delivered sources only in a throwaway
    container of `image` (the measured trial image)."""
    def run(sources: Mapping[str, bytes]) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        runnable: dict[str, str] = {}
        for name, data in sources.items():
            if len(data) > MAX_SOURCE_BYTES:
                out[name] = {"status": "over-bound"}
            else:
                runnable[name] = base64.b64encode(data).decode("ascii")
        if not runnable:
            return out
        nonce = secrets.token_hex(16)
        name = f"skillc-step6-oracle-{nonce[:12]}"
        job = json.dumps({"sources": runnable, "inputs": list(CASES), "child": _CHILD,
                          "child_seconds": CHILD_SECONDS, "nonce": nonce})
        try:
            done = subprocess.run(_container_argv(docker_bin, image, name), input=job, capture_output=True,
                                  text=True, timeout=CONTAINER_SECONDS, env=dict(env) if env is not None else None,
                                  check=False)
        except subprocess.TimeoutExpired:
            subprocess.run([*docker_bin, "rm", "-f", name], capture_output=True, timeout=30, check=False,
                           env=dict(env) if env is not None else None)
            return {**out, **{n: {"status": "container-timeout"} for n in runnable}}
        line = next((ln for ln in reversed(done.stdout.splitlines()) if ln.startswith(nonce)), None)
        try:
            parsed = json.loads(line[len(nonce):]) if line is not None else None
        except ValueError:
            parsed = None
        if done.returncode != 0 or not isinstance(parsed, dict) or set(parsed) != set(runnable):
            return {**out, **{n: {"status": "container-failed", "exit": done.returncode} for n in runnable}}
        return {**out, **{n: dict(v) if isinstance(v, dict) else {"status": "error"} for n, v in parsed.items()}}
    return run


def runner_for(backend: object) -> Runner:
    """The container runner for an attempt's backend - refused for anything
    that is not a Docker backend with a declared image (C1: never the host)."""
    from .docker_backend import DockerBackend
    if not isinstance(backend, DockerBackend):
        raise Refused(f"the Step-6 oracle runs only in a container; {type(backend).__name__} is not a Docker backend")
    if not backend.image:
        raise Refused("the Step-6 oracle needs the attempt's measured trial image")
    from .docker_backend import _docker_env
    return container_runner(tuple(backend.docker_bin), backend.image, env=_docker_env())


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
