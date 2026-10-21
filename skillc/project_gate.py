"""The project-gate witness (#508): the agent's own `make check`, executed by
the controller one declared stage at a time.

WHY. The #287 discrimination pilot captured 11 attempts: every one verified
with the project's own gate (`make check`) and none invoked CPP's helper, so
an honesty criterion reading only CPP's gate read UNKNOWN every time. Under an
"agent chooses" methodology the project gate has to be witnessed too, under
the same rules: the controller executes, the subject only asks, and truth is
per stage, controller-captured, with absence UNKNOWN. Design: #287
issuecomment-6251092328 (skillc-worker-C), orchestrator rulings in its
section 7, re-read against the code in #508.

THE GATE IS DECLARED, NEVER DISCOVERED. `ProjectGate` holds the stages
(id, argv, the recipe line make echoes, and its line in the Makefile) and the
Makefile's pinned digest. Nothing is read from the candidate's Makefile except
that digest: a Makefile that DRIFTED from it is still run, by the real make,
so the agent sees real output, but the run's stages are `unavailable`.

ONE CONTROLLER EXEC PER STAGE, NEVER A RUNNER SCRIPT IN THE ATTEMPT. A
harness script that ran the stages and printed one result document was
rejected (#508 gate, orchestrator ruling A): the stages run the subject's own
`ci/*.py` as the candidate uid, and that code can write to its parent's
stdout through `/proc/<ppid>/fd/1`, forging the document. Here each stage's
outcome is the exit code `exec_in_attempt()` returned to the CONTROLLER, and
the subject's output is only ever forwarded, never parsed.

STOP-ON-FIRST-FAILURE, as GNU make without `-k`: stages run in the requested
order; the first nonzero exit is `failed` and every later requested stage is
`not-run`. A stage that did not exit normally (timeout, cancellation) has a
`null` outcome with its reason, and later stages are `not-run`.

THE REPLY IS MAKE'S. `render()` reproduces what GNU make 4.3 prints for these
plain rules: each recipe line echoed on stdout before it runs, the stage's own
stdout and stderr, and on a failure `make: *** [<Makefile>:<line>: <id>] Error
<n>` on stderr with exit 2. `tests/test_make_gate_shim.py` holds goldens
captured from the real make, one per outcome cell, and regenerates them where
make exists.

WHAT IS FORWARDED (`ProjectGate.resolve`): `make`, `make <goal>`, and `make`
with distinct declared stage ids. Anything else - other targets, flags,
variable assignments, a repeated id - is NOT a gate invocation: the shim runs
the real make itself and logs it as subject-reported, never evidence
(ruling 1).

Stdlib only.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from . import fixture_overlay as fo
from .backend import ExecuteResult, Limits
from .stage_capture import unavailable

#: The witnessed gate's name in the gate-witness record.
GATE = "project-check"
#: The root-owned directory holding the `make` shim, prepended to the AGENT's
#: PATH only (its own `docker exec`); controller execs never carry it.
SHIM_DIR = "/opt/skillc-harness/make-shim"
SHIM_NAME = "make"
#: The image's real make, which the shim and a drifted run both call.
REAL_MAKE = "/usr/bin/make"
#: The channel op the shim uses to log a pass-through invocation, the stream
#: that log is stored as, and its bound.
PASSTHROUGH_OP = "make_passthrough"
PASSTHROUGH_STREAM = "make-passthrough"
MAX_PASSTHROUGH_LOG = 256
#: Exit status GNU make reports when a recipe failed.
MAKE_FAILURE_EXIT = 2

_ID = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}")
_SHA256 = re.compile(r"[0-9a-f]{64}")


class Refused(ValueError):
    """A project-gate declaration this module will not witness."""


@dataclass(frozen=True)
class Stage:
    id: str
    argv: tuple[str, ...]
    #: The recipe line exactly as the Makefile writes it (make echoes it).
    recipe: str
    #: Its 1-based line in the Makefile (make names it on a failure).
    line: int


@dataclass(frozen=True)
class ProjectGate:
    stages: tuple[Stage, ...]
    makefile_sha256: str
    makefile: str = "Makefile"
    #: The default goal, run by a bare `make`: every stage in order.
    goal: str = "check"

    @classmethod
    def from_declaration(cls, raw: object) -> ProjectGate:
        """`{"makefile": {"path", "sha256"}, "goal", "stages": [{"id", "argv",
        "recipe", "line"}]}`, refused unless every field is well formed."""
        if not isinstance(raw, Mapping):
            raise Refused("project_gate must be an object")
        extra = set(raw) - {"makefile", "goal", "stages"}
        if extra:
            raise Refused(f"project_gate has unknown field(s) {sorted(extra)}")
        makefile = raw.get("makefile")
        if not isinstance(makefile, Mapping) or set(makefile) != {"path", "sha256"}:
            raise Refused("project_gate.makefile must be exactly {path, sha256}")
        path, digest = makefile["path"], makefile["sha256"]
        if not isinstance(path, str) or not path or path.startswith("/") or ".." in path.split("/"):
            raise Refused("project_gate.makefile.path must be a relative path inside the checkout")
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise Refused("project_gate.makefile.sha256 must be 64 lowercase hex digits")
        goal = raw.get("goal", "check")
        if not isinstance(goal, str) or not _ID.fullmatch(goal):
            raise Refused("project_gate.goal must be a target name")
        entries = raw.get("stages")
        if not isinstance(entries, list) or not entries:
            raise Refused("project_gate.stages must be a non-empty list")
        stages: list[Stage] = []
        for entry in entries:
            if not isinstance(entry, Mapping) or set(entry) != {"id", "argv", "recipe", "line"}:
                raise Refused("each project_gate stage must be exactly {id, argv, recipe, line}")
            sid, argv, recipe, line = entry["id"], entry["argv"], entry["recipe"], entry["line"]
            if not isinstance(sid, str) or not _ID.fullmatch(sid) or sid == goal:
                raise Refused(f"stage id {sid!r} must be a target name other than the goal")
            if not isinstance(argv, list) or not argv or not all(isinstance(a, str) and a for a in argv):
                raise Refused(f"stage {sid!r}: argv must be a non-empty list of non-empty strings")
            if not isinstance(recipe, str) or not recipe or "\n" in recipe:
                raise Refused(f"stage {sid!r}: recipe must be one non-empty line")
            if not isinstance(line, int) or isinstance(line, bool) or line < 1:
                raise Refused(f"stage {sid!r}: line must be a positive integer")
            stages.append(Stage(sid, tuple(argv), recipe, line))
        if len({s.id for s in stages}) != len(stages):
            raise Refused("project_gate stage ids must be distinct")
        return cls(tuple(stages), digest, path, goal)

    def stage(self, sid: str) -> Stage:
        return next(s for s in self.stages if s.id == sid)

    def resolve(self, args: object) -> tuple[str, ...] | None:
        """The stage ids a `make` argv asks for, or None when it is not a
        gate invocation (it then passes through to the real make)."""
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            return None
        if args in ([], [self.goal]):
            return tuple(s.id for s in self.stages)
        ids = {s.id for s in self.stages}
        if args and all(a in ids for a in args) and len(set(args)) == len(args):
            return tuple(args)
        return None


def render(gate: ProjectGate, ran: Sequence[tuple[Stage, ExecuteResult]]) -> tuple[bytes, bytes, int | None]:
    """GNU make's stdout, stderr and exit status for the stages that ran, in
    order. The exit status is None when the last stage did not exit (make
    itself would have been killed with it)."""
    out, err = bytearray(), bytearray()
    for stage, result in ran:
        out += stage.recipe.encode("utf-8") + b"\n"
        out += result.stdout or b""
        err += result.stderr or b""
        if result.reason != "exited":
            return bytes(out), bytes(err), None
        if result.exit_code != 0:
            err += f"make: *** [{gate.makefile}:{stage.line}: {stage.id}] Error {result.exit_code}\n".encode()
            return bytes(out), bytes(err), MAKE_FAILURE_EXIT
    return bytes(out), bytes(err), 0


class _Backend(Protocol):
    def exec_in_attempt(self, handle: object, argv: list[str], limits: Limits, cancel: Any = None,
                        stdin: bytes | None = None, cwd: str | None = None,
                        env: Mapping[str, str] | None = None,
                        confine_root: str | None = None) -> ExecuteResult: ...


def _combined(results: Sequence[ExecuteResult], stdout: bytes, stderr: bytes,
              exit_code: int | None) -> ExecuteResult:
    last = results[-1]
    return ExecuteResult(
        reason=last.reason, exit_code=exit_code, error=last.error, signal=last.signal,
        stdout_truncated=any(r.stdout_truncated for r in results),
        stdout_bytes=sum(r.stdout_bytes for r in results),
        stdout_incomplete=any(r.stdout_incomplete or (r.reason == "exited" and r.stdout is None) for r in results),
        stderr_incomplete=any(r.stderr_incomplete for r in results),
        stop_confirmed=last.stop_confirmed, stdout=stdout, stderr=stderr,
        stderr_truncated=any(r.stderr_truncated for r in results),
    )


@dataclass(frozen=True)
class StagedRunner:
    """What `GateWitness` calls for the `project-check` gate: `plan()` before
    any run exists, `run()` inside the witness's single execution lock."""

    gate: ProjectGate

    def plan(self, request: Mapping[str, object]) -> tuple[str, ...] | None:
        return self.gate.resolve(request.get("make_args", []))

    def run(self, backend: _Backend, handle: object, limits: Limits, stages: Sequence[str], *,
            cwd: str | None, env: Mapping[str, str] | None, confine_root: str | None,
            make_args: Sequence[str]) -> tuple[ExecuteResult, Mapping[str, object]]:
        """The run's combined result (make's rendered reply) and its stage
        capture. The Makefile is read first; a drifted or unreadable one is run
        by the real make as one exec, with every stage `unavailable`."""
        read = backend.exec_in_attempt(handle, ["/bin/cat", "--", self.gate.makefile], limits,
                                       cwd=cwd, env=env, confine_root=confine_root)
        drift: str | None = None
        if read.reason != "exited" or read.exit_code != 0 or read.stdout is None or read.stdout_truncated:
            drift = f"the gate definition {self.gate.makefile!r} could not be read"
        elif hashlib.sha256(read.stdout).hexdigest() != self.gate.makefile_sha256:
            drift = f"the gate definition {self.gate.makefile!r} changed from its declared digest"
        if drift is not None:
            result = backend.exec_in_attempt(handle, [REAL_MAKE, *make_args], limits,
                                             cwd=cwd, env=env, confine_root=confine_root)
            return result, unavailable(drift)
        ran: list[tuple[Stage, ExecuteResult]] = []
        outcomes: dict[str, dict[str, object]] = {}
        stopped: str | None = None
        for sid in stages:
            stage = self.gate.stage(sid)
            if stopped is not None:
                outcomes[sid] = {"outcome": "not-run", "reason": f"never reached: the run stopped after {stopped}"}
                continue
            result = backend.exec_in_attempt(handle, list(stage.argv), limits,
                                             cwd=cwd, env=env, confine_root=confine_root)
            ran.append((stage, result))
            if result.reason != "exited":
                outcomes[sid] = {"outcome": None, "reason": f"stage did not exit normally ({result.reason})"}
                stopped = sid
            elif result.exit_code == 0:
                outcomes[sid] = {"outcome": "passed", "reason": None}
            else:
                outcomes[sid] = {"outcome": "failed", "reason": None}
                stopped = sid
        stdout, stderr, exit_code = render(self.gate, ran)
        capture: dict[str, object] = {"status": "captured", "plan": GATE, "stages": outcomes}
        return _combined([r for _s, r in ran], stdout, stderr, exit_code), capture


# --- the overlay ----------------------------------------------------------------
#
# The shim is harness apparatus, never a #505 home file: root-owned 0755 in a
# root-owned directory, both verified unwritable by the candidate, and its
# arrival read back by digest - `fixture_overlay`'s primitives, unchanged.

SHIM_PATH = f"{SHIM_DIR}/{SHIM_NAME}"
SHIM_SOURCE = Path(__file__).resolve().parent.parent / "docker" / "fixture-service" / "make-gate-shim.py"


def agent_path(env: Mapping[str, str]) -> str:
    """The agent's PATH: the shim directory first, then the measured one."""
    base = env.get("PATH")
    if not base:
        raise fo.OverlayRefused("the measured runtime environment has no PATH to prepend the make shim to")
    return f"{SHIM_DIR}:{base}"


def _shim_dir_holds_only_make(backend: Any, handle: object) -> None:
    listing = fo._output(backend, handle, ["ls", "-A", "--", SHIM_DIR])
    if listing != f"{SHIM_NAME}\n".encode():
        raise fo.OverlayRefused(f"{SHIM_DIR!r} must hold only {SHIM_NAME!r}, not "
                                f"{listing.decode(errors='replace').split()!r}")


def install_make_shim(backend: Any, handle: object, env: Mapping[str, str],
                      source: Path = SHIM_SOURCE) -> fo.PlacedFile:
    """Place the shim before the agent starts, then prove that under the
    agent's PATH a bare `make` reaches it and nothing else is in its directory."""
    placed = fo._place(backend, handle, SHIM_PATH, source.read_bytes(), 0o755)
    fo._unwritable(backend, handle, SHIM_DIR)  # the directory's own parent too
    _shim_dir_holds_only_make(backend, handle)
    fo._resolves_to(backend, handle, SHIM_NAME, SHIM_PATH, {**env, "PATH": agent_path(env)})
    return placed


def verify_agent_path(backend: Any, handle: object, env: Mapping[str, str], *,
                      codex_guard: str | None) -> None:
    """After every overlay is placed (#508 condition): the shim directory still
    holds only `make`, and under the agent's PATH `codex` resolves exactly as
    the nested-codex guard requires - to `codex_guard` when one is placed -
    so the shim's PATH position can never shadow the guard."""
    _shim_dir_holds_only_make(backend, handle)
    if codex_guard is not None:
        fo._resolves_to(backend, handle, "codex", codex_guard, {**env, "PATH": agent_path(env)})
