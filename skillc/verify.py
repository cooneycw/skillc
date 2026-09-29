"""Independent grading and result assembly (#9).

interfaces.md gives the verified result to "an independent verifier and controller
result assembler". This module is both. It grades what the controller froze
(skillc/trial.py) and writes the `verified-result` record. The subject, and the
candidate code it produced, never write one. See
docs/specs/evaluation-facility/verification.md.

GRADING IS THREE STAGES, AND ONLY ONE RUNS CANDIDATE CODE.

  1. PROBE (untrusted). A fresh owned directory receives a disposable copy of the
     frozen artifacts, rebuilt from the controller's content-addressed objects,
     plus the grader's probe harness and its held-out INPUTS. The answer key is
     not there. The probe runs under a supervisor that makes itself a Linux child
     subreaper, so a process that calls `setsid` is still its child. The
     supervisor kills every descendant and reports a confirmed sweep through its
     EXIT CODE, the one channel candidate code cannot write. What the probe
     prints is an observation, never a verdict.
  2. JUDGE (trusted). It starts only after that confirmed sweep, in a new
     directory holding just the judge, written from bytes read and pinned BEFORE
     any candidate code ran - never re-read from the grader's files. No
     candidate process is alive to write on its stdout, the success channel.
  3. ASSEMBLE (this process). The judge's report must carry exactly the grader's
     required criteria and satisfy the record contract. The status is DERIVED by
     `records.derive_status`, never copied, and the verifier adds its own
     `installation-ready` criterion from the attempt's receipt.

After grading, everything candidate code could have touched is re-checked. That
is the grader definition against the ledger's pin, the whole experiment store
against a snapshot, the ledger against its history, and the frozen bytes against
their digests. Any change REFUSES the result. It is never warn-and-proceed.

WHAT THIS DOES NOT ESTABLISH BY DEFAULT. Candidate code runs as the evaluator's
own user, so a write to the store or to the grader's files is DETECTED, not
prevented, and the answer key's file on disk is readable by a candidate that
goes looking for it. The environment is not inherited, but same-user code can
read an ancestor's through /proc, so evaluator credentials must not be in the
verifier's environment. If containment is lost, this process is quarantined:
every later grading run refuses until an operator clears it. The controller
host, this package and the Python standard library are trusted. verification.md
lists every assumption.

THE PROBE MAY RUN THROUGH AN EXECUTION BACKEND INSTEAD (#10 PR2). `grade`/
`grade_files` take an optional `backend: ExecutionBackend | None`. `None` (the
default) is the bare-subprocess path above, unchanged. Given a backend, ONLY
stage 1 changes: the probe runs inside a fresh, separate backend instance
(interfaces.md step 8 - "a SEPARATE backend instance, through this same seam")
via prepare/install/execute/confirm_stopped/export/destroy/confirm_absent,
exactly the seam `skillc/lifecycle.py` drives for agent execution. The judge
(stage 2) is unchanged either way: it is trusted code, never candidate code, so
it needs no container.

Confidentiality and prevention become the BACKEND's claims (`describe()`'s
`isolation`/`unobserved`), never this module's own - this module still performs
its detection-based checks regardless, as defense in depth, but a real
prevention claim is the backend's to make. No concrete backend ships in this
repository at this commit (`skillc/docker_backend.py` does not exist yet), so
every such claim is OWED TO THE LIVE RUN (issue #10 comment 5848522578, lesson
E17: "unit tests on a fake backend prove the lifecycle, never the boundary")
until one exists and is actually run this way -
`tests/test_verify.py::test_an_ancestors_environment_is_NOT_hidden` stays
exactly as documented; it cannot flip without that live run.

Stdlib only (AGENTS.md). Linux only: the bare-subprocess sweep needs `prctl` and
`/proc`. Anywhere else it fails closed, to INCONCLUSIVE.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import signal
import stat
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath

from . import checks, provenance, records, trial
from . import judge as judge_seam
from .backend import BackendUnavailable, Confirmation, ExecutionBackend, Limits
from .materialize import Refused as NotOwned
from .materialize import cleanup as remove_owned
from .materialize import create_root

Refused = trial.Refused

#: The only grading tier this build implements: deterministic outcome checks,
#: no model call. #69 (owner-ratified target: deterministic / llm-judge /
#: independent-llm-judge) adds the other two, each keyed by its own tier name
#: in `verification.verdicts` (below) - this constant is that key, never
#: "Level": skillc already uses that word for TASK difficulty (evals/level1,
#: #13-#15), so reusing it for grading tiers would read as a claim about the
#: task ladder instead.
GRADING_TIER = "deterministic"

#: The reserved `verification.disagreement` reason while fewer than two judge
#: tiers exist (#69 owner ruling): a per-criterion same-model-vs-independent
#: disagreement record needs two independently-graded verdicts to compare, and
#: today there is exactly one tier, ever. Reused verbatim so the reason string
#: cannot drift between the writer here and any reader that matches on it.
DISAGREEMENT_UNAVAILABLE_REASON = "fewer than two judge tiers"

GRADER_FILE = "grader.json"
_GRADER_KEYS = {"id", "revision", "criteria", "probe", "judge"}
#: Optional on top of `_GRADER_KEYS` (issue #13): declares each criterion's
#: outcome DIMENSION, so a reporter can group functional/constraint/
#: integration results separately without inferring it from the id's own
#: naming convention - a convention nobody enforces, so a future
#: "functional_smoke" or "integration2-x" id would silently mis-bucket or
#: fall through to "other" (review ruling, PR #13: declare, never infer).
#: Optional, not required: a grader with no `dimensions` key still loads -
#: every one of its criteria simply reports "unclassified" (`outcome_report.
#: py`), which is the honest answer for a task family that predates this
#: vocabulary or does not use it (Level 1, L4, L5 today).
_OPTIONAL_GRADER_KEYS = {"dimensions"}
_PROBE_KEYS = {"file", "inputs", "timeout"}
_JUDGE_KEYS = {"file", "timeout"}
#: The fixed, closed vocabulary `dimensions` values must be drawn from -
#: exactly issue #13's three named outcome dimensions. Anything else is a
#: LOAD-TIME refusal (never a silent "unclassified" fallback): an unknown
#: dimension value is a declaration someone got wrong, not an absent one.
OUTCOME_DIMENSIONS = ("functional", "constraint", "integration")

#: The verifier's own criterion. Candidate outcomes cannot claim it.
READINESS_CRITERION = "installation-ready"
#: The receipt facts records.md requires. Anything but SATISFIED is not ready.
READINESS_FACTS = ("discovery_canary", "baseline_absence")
#: What stands in for the installation receipt on the agent-trial path (#139),
#: recorded as `verification.readiness_source`. The agent path writes no
#: receipt: the baseline arm installs nothing, which the receipt contract
#: refuses, and nothing on it establishes that a client discovered what was
#: delivered. The attempt's `agent-observation` record stands in for ACCOUNTING
#: only - `records.attempt_accounting` requires it in the bundle - and never for
#: readiness: `installation-ready` stays UNKNOWN on this path, so readiness
#: still gates PASS (verification.md).
AGENT_OBSERVATION_READINESS = records.OBSERVATION_STAND_IN


def observation_record_name(attempt_id: str) -> str:
    """The agent-observation record's file name, beside the attempt's lifecycle
    record. `agent_trial` writes it; a stand-in result names it."""
    return f"observation-{attempt_id}.json"

#: The most of the probe's report the judge is given.
MAX_OBSERVATION_BYTES = 1024 * 1024
#: How long the supervisor may take to sweep the probe's descendants.
SWEEP_SECONDS = 10.0
#: Extra time the verifier allows the supervisor beyond the probe's own limit.
SUPERVISOR_SLACK = 10.0

#: The supervisor's exit codes. Only the first two are a confirmed sweep.
EXITED, TIMED_OUT, UNCONFIRMED, UNSUPPORTED = 0, 10, 20, 21
CONFIRMED = (EXITED, TIMED_OUT)

#: How a grading run ended. `verdict` is the only one where the judge's criteria
#: stand. Every other category makes each required criterion UNKNOWN.
CATEGORIES = ("verdict", "containment", "timeout", "exit-nonzero", "no-output",
              "unparseable", "criteria-set", "contract")

# Runs as `python -I -S -B -c SUPERVISOR TIMEOUT SWEEP OBSERVATIONS ARGV...`. It
# makes itself a child subreaper, so every descendant of the probe, including one
# that left its session, is reparented to it rather than to init. When the probe
# exits or times out, it SIGKILLs every child it has until none remains. Its exit
# code is the verdict on containment: candidate code can write any file or pipe
# this process holds, but it cannot choose this process's exit status.
SUPERVISOR = r"""
import ctypes, os, signal, subprocess, sys, time

def children():
    me, found = os.getpid(), []
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        try:
            with open(f"/proc/{name}/stat", "rb") as f:
                data = f.read()
        except OSError:
            continue
        fields = data[data.rfind(b")") + 2:].split()
        if len(fields) > 1 and int(fields[1]) == me:
            found.append(int(name))
    return found

def reap():
    while True:
        try:
            pid, _ = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return
        if pid == 0:
            return

def main():
    timeout, sweep, observations, argv = float(sys.argv[1]), float(sys.argv[2]), sys.argv[3], sys.argv[4:]
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
            return 21
        os.listdir("/proc")
    except (OSError, AttributeError):
        return 21
    with open(observations, "xb") as out:
        proc = subprocess.Popen(argv, stdout=out)
    timed_out = False
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
    deadline = time.monotonic() + sweep
    while time.monotonic() < deadline:
        kids = children()
        if not kids:
            break
        for pid in kids:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        reap()
        time.sleep(0.01)
    reap()
    if children():
        return 20
    return 10 if timed_out else 0

sys.exit(main())
"""


# ------------------------------------------------------------------ the grader


def _read_regular(path: Path) -> bytes:
    """A regular file's bytes, never through a link, and never blocking: a FIFO
    candidate code put in its place is refused, not waited on."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as exc:
        raise Refused(f"{path} is not a readable regular file: {exc.strerror}") from None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise Refused(f"{path} is not a regular file")
        chunks = []
        while chunk := os.read(fd, 1 << 20):
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def _timeout(value: object, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value <= 3600:
        raise Refused(f"{where}: timeout must be a number of seconds in (0, 3600]")
    return float(value)


def _member(root: Path, name: object, where: str) -> Path:
    """A file named by the definition: a plain name in the grader's own directory."""
    if not isinstance(name, str) or not name or "/" in name or name in (".", ".."):
        raise Refused(f"{where}: {name!r} is not a plain file name in the grader directory")
    path = root / name
    if path.is_symlink() or not path.is_file():
        raise Refused(f"{where}: {name} is not a regular file in {root}")
    return path


@dataclass(frozen=True)
class GraderDef:
    """A grader, as its definition file declares it.

    `digest()` covers the definition's own fields and the bytes of every file it
    names, and is re-read on every call. The ledger pins it before dispatch and
    `grade` compares it before and after grading (Coder Eval lesson 4: digest the
    answer key before grading, and check it again).
    """

    root: Path
    id: str
    revision: str
    criteria: tuple[str, ...]
    probe: Path
    inputs: Path
    judge: Path
    probe_timeout: float
    judge_timeout: float
    #: `{criterion_id: dimension}` (issue #13), covering as few or as many of
    #: `criteria` as the grader declares - never guessed for the rest. See
    #: `_OPTIONAL_GRADER_KEYS`'s own comment for why this is optional, and
    #: `OUTCOME_DIMENSIONS` for the closed vocabulary each value must be one
    #: of. Empty for a grader that declares none.
    dimensions: dict[str, str]

    @classmethod
    def load(cls, root: Path) -> GraderDef:
        root = root.resolve()
        where = str(root / GRADER_FILE)
        try:
            data = json.loads(_read_regular(root / GRADER_FILE))
        except json.JSONDecodeError as exc:
            raise Refused(f"{where}: not JSON: {exc}") from None
        if not isinstance(data, dict):
            raise Refused(f"{where}: not an object")
        allowed = _GRADER_KEYS | _OPTIONAL_GRADER_KEYS
        missing = _GRADER_KEYS - set(data)
        unknown = set(data) - allowed
        if missing or unknown:
            raise Refused(
                f"{where}: fields must be exactly {sorted(_GRADER_KEYS)}, "
                f"plus optionally {sorted(_OPTIONAL_GRADER_KEYS)}"
            )
        for key in ("id", "revision"):
            if not isinstance(data[key], str) or not records.ID_RE.match(data[key]):
                raise Refused(f"{where}: {key} is not an identifier")
        criteria = data["criteria"]
        if (not isinstance(criteria, list) or not criteria
                or not all(isinstance(c, str) and c.strip() for c in criteria)
                or len(set(criteria)) != len(criteria)):
            raise Refused(f"{where}: criteria must be a non-empty list of unique names")
        if READINESS_CRITERION in criteria:
            raise Refused(f"{where}: {READINESS_CRITERION!r} is the verifier's criterion, not a grader's")
        probe, judge = data["probe"], data["judge"]
        if not isinstance(probe, dict) or set(probe) != _PROBE_KEYS:
            raise Refused(f"{where}: probe must carry exactly {sorted(_PROBE_KEYS)}")
        if not isinstance(judge, dict) or set(judge) != _JUDGE_KEYS:
            raise Refused(f"{where}: judge must carry exactly {sorted(_JUDGE_KEYS)}")
        dimensions = data.get("dimensions", {})
        if not isinstance(dimensions, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in dimensions.items()):
            raise Refused(f"{where}: dimensions must be an object of criterion name to dimension name")
        unknown_ids = set(dimensions) - set(criteria)
        if unknown_ids:
            raise Refused(f"{where}: dimensions names {sorted(unknown_ids)} not in criteria")
        bad_values = {v for v in dimensions.values() if v not in OUTCOME_DIMENSIONS}
        if bad_values:
            raise Refused(
                f"{where}: dimensions has unknown value(s) {sorted(bad_values)}; "
                f"must be one of {list(OUTCOME_DIMENSIONS)}"
            )
        return cls(
            root=root, id=data["id"], revision=data["revision"], criteria=tuple(criteria),
            probe=_member(root, probe["file"], where), inputs=_member(root, probe["inputs"], where),
            judge=_member(root, judge["file"], where),
            probe_timeout=_timeout(probe["timeout"], where),
            judge_timeout=_timeout(judge["timeout"], where),
            dimensions=dict(dimensions),
        )

    def with_judge(self, judge: Path) -> GraderDef:
        """The same grader with another judge: how a broken-grader control is run.
        Its digest differs, so a ledger pinned to the real grader refuses it."""
        judge = judge.resolve() if not judge.is_symlink() else judge
        if judge.is_symlink() or not judge.is_file():
            raise Refused(f"{judge} is not a regular file")
        return replace(self, judge=judge)

    def read(self) -> dict[str, bytes]:
        """The bytes of the three files, read once. Grading executes THESE bytes,
        never the files again, so a file replaced while candidate code runs - even
        one that restores itself afterwards - is never what runs."""
        return {"definition": _read_regular(self.root / GRADER_FILE),
                "probe": _read_regular(self.probe), "inputs": _read_regular(self.inputs),
                "judge": _read_regular(self.judge)}

    def digest(self, loaded: dict[str, bytes] | None = None) -> str:
        """The pin: the definition file's bytes, the fields as loaded, the names and
        bytes of the files it runs (read now, unless `loaded` supplies the bytes that
        will actually run). A change to `grader.json` alone changes it too."""
        data = loaded if loaded is not None else self.read()
        return trial.sha256_bytes(trial.canonical({
            "definition": trial.sha256_bytes(data["definition"]),
            "files": [self.probe.name, self.inputs.name, self.judge.name],
            "id": self.id, "revision": self.revision, "criteria": list(self.criteria),
            "probe": trial.sha256_bytes(data["probe"]),
            "inputs": trial.sha256_bytes(data["inputs"]),
            "judge": trial.sha256_bytes(data["judge"]),
            "probe_timeout": self.probe_timeout, "judge_timeout": self.judge_timeout,
        }))

    def identity(self) -> dict[str, str]:
        """What a ledger pins: `{"grader": grader.identity()}` in the plan."""
        return {"id": self.id, "revision": self.revision, "digest": self.digest()}


# ---------------------------------------------------------------- one grading run


@dataclass
class Graded:
    """What one grading run concluded, before any record is written."""

    status: str
    category: str
    detail: str
    criteria: list[dict[str, object]]
    containment: dict[str, object]

    @property
    def violated(self) -> frozenset[str]:
        return frozenset(str(c["id"]) for c in self.criteria if c.get("outcome") == "VIOLATED")


def _env(home: Path) -> dict[str, str]:
    """The whole environment of a grading process. Nothing is INHERITED, so no
    evaluator credential is handed to candidate code or the judge. That is not
    confidentiality: same-user code can still read an ancestor's environment
    through /proc (verification.md, "Trust assumptions"); that needs #10's boundary."""
    return {"PATH": os.defpath, "HOME": str(home), "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"}


def _safe_parts(rel: str) -> tuple[str, ...]:
    """A manifest path as parts, refused if it could leave the copy's root.

    The manifest is the controller's, but a stored bundle is untrusted input to the
    verifier (Coder Eval lesson 6)."""
    path = PurePosixPath(rel)
    if path.is_absolute() or not path.parts or any(p in ("", ".", "..") for p in path.parts) or "\\" in rel:
        raise Refused(f"artifact path {rel!r} could leave the grading copy")
    return path.parts


def _write_tree(dest: Path, files: list[tuple[str, bytes, bool]]) -> None:
    """The disposable copy: every file written fresh from its verified bytes."""
    for rel, data, executable in files:
        target = dest.joinpath(*_safe_parts(rel))
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o700 if executable else 0o600)
        with os.fdopen(fd, "wb") as out:
            out.write(data)


def _read_untrusted(path: Path, limit: int, tail: bool = False) -> bytes | None:
    """At most `limit` bytes of a file candidate code could have replaced.

    Opened non-blocking and without following a link, and read only if it is a
    regular file: a FIFO swapped in for it would otherwise block forever, after
    every deadline has passed. None when it is not a readable regular file."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode):
            return None
        if tail and info.st_size > limit:
            handle.seek(info.st_size - limit)
        return handle.read(limit)


def _read_observations(path: Path) -> str:
    """The probe's report. Absent or not a regular file reads as empty: the judge
    decides what no report means for the candidate."""
    data = _read_untrusted(path, MAX_OBSERVATION_BYTES)
    return data.decode("utf-8", errors="replace") if data is not None else ""


def _tail(path: Path) -> str:
    data = _read_untrusted(path, 4096, tail=True)
    lines = data.decode("utf-8", errors="replace").strip().splitlines() if data else []
    return lines[-1] if lines else "no stderr"


def _abnormal_exit_reason(code: int | None) -> str:
    """Why the supervisor ended abnormally, named EXPLICITLY when the cause is
    knowable, never a guessed "OOM" or "candidate code may have killed it"
    (issue #10 addendum item 12: "exit 137 is SIGKILL, not OOM"; three parties
    once relayed OOM for a kill a memory check showed was not one).

    Python's `Popen.returncode` is the NEGATIVE signal number when a process is
    terminated by a signal (POSIX; positive is a normal exit status), so a
    negative code here names the exact signal - still not its CAUSE (the kernel
    OOM killer, an operator, a resource limit), which this process cannot see
    from the exit code alone. That is why this says "terminated by", never
    "killed by the OOM killer": stating the mechanism it can prove, not a
    reason it would have to guess.
    """
    if code is not None and code < 0:
        try:
            name = signal.Signals(-code).name
        except ValueError:
            name = f"signal {-code}"
        return (
            f"the supervisor was terminated by {name} (exit code {code}); this process "
            "cannot tell from the exit code alone whether that was the kernel OOM killer, "
            "an operator, or a resource limit - check the host's own OOM/cgroup records"
        )
    return f"the supervisor ended abnormally ({code}); candidate code may have killed it"


#: Set when a probe's containment was lost. Every later grading run in this
#: process refuses until an operator clears it: a surviving candidate process could
#: otherwise write into the next run's store or judge.
_quarantine: str | None = None


def _set_quarantine(reason: str) -> None:
    global _quarantine
    _quarantine = reason


def clear_quarantine() -> None:
    """An operator's statement that the host was checked after lost containment."""
    global _quarantine
    _quarantine = None


def _kill_inside(work: Path, home: Path) -> int:
    """Best effort, after the supervisor failed: SIGKILL every process whose working
    directory is inside this probe's directory or whose HOME is its HOME. A process
    that moved out and changed both is not found; that is why the caller quarantines."""
    prefix, killed, me = str(work) + os.sep, 0, os.getpid()
    marker = f"HOME={home}".encode()
    for name in os.listdir("/proc") if os.path.isdir("/proc") else []:
        if not name.isdigit() or int(name) == me:
            continue
        inside = False
        try:
            inside = (os.readlink(f"/proc/{name}/cwd") + os.sep).startswith(prefix)
        except OSError:
            pass
        if not inside:
            try:
                with open(f"/proc/{name}/environ", "rb") as handle:
                    inside = marker in handle.read().split(b"\0")
            except OSError:
                pass
        if inside:
            try:
                os.kill(int(name), signal.SIGKILL)
                killed += 1
            except OSError:
                pass
    return killed


def _probe(grader: GraderDef, loaded: dict[str, bytes], work: Path) -> tuple[dict[str, object], dict[str, object]]:
    """Stage 1: run candidate code under the supervisor. Returns the envelope the
    judge will read and the containment observation."""
    harness, home = work / "harness", work / "home"
    for d in (harness, home):
        d.mkdir(mode=0o700)
    probe = harness / grader.probe.name
    _write_tree(harness, [(grader.probe.name, loaded["probe"], False)])
    inputs = loaded["inputs"]
    observations, errors = work / "observations", work / "probe.stderr"
    argv = [
        sys.executable, "-I", "-S", "-B", "-c", SUPERVISOR,
        str(grader.probe_timeout), str(SWEEP_SECONDS), str(observations),
        sys.executable, "-I", "-S", "-B", str(probe), str(work / "candidate"),
    ]
    with open(errors, "xb") as err:
        proc = subprocess.Popen(argv, cwd=work / "candidate", env=_env(home), stdin=subprocess.PIPE,
                                stdout=subprocess.DEVNULL, stderr=err, start_new_session=True)
        try:
            proc.communicate(inputs, timeout=grader.probe_timeout + SWEEP_SECONDS + SUPERVISOR_SLACK)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
            code: int | None = None
        else:
            code = proc.returncode
    confirmed = code in CONFIRMED
    containment: dict[str, object] = {
        "supervisor_exit": code, "confirmed": confirmed, "timed_out": code == TIMED_OUT,
    }
    if not confirmed:
        containment["fallback_killed"] = _kill_inside(work, home)
        containment["reason"] = {
            UNCONFIRMED: "descendants of the probe survived the sweep",
            UNSUPPORTED: "this host cannot contain the probe (no prctl subreaper or /proc)",
            None: "the supervisor did not finish; its process group was killed",
        }.get(code, _abnormal_exit_reason(code))
        containment["stderr"] = _tail(errors)
        if code != UNSUPPORTED:
            # Nothing established that every candidate process is gone. One that left
            # the root and changed its environment is out of reach of the fallback,
            # and could interfere with the next grading run, so this verifier stops.
            _set_quarantine(f"probe containment was lost ({containment['reason']})")
    envelope = {"observations": _read_observations(observations), "timed_out": code == TIMED_OUT}
    return envelope, containment


#: The backend's fixed logical workspace root for a probe-shaped install
#: (#10 PR2, agreed directly with the Docker backend's author over mailbox
#: coordination) - the same example backend.py's own module docstring already
#: names ("fixed logical paths (e.g. /work, /home/candidate) - never the
#: host's own").
PROBE_WORKDIR = "/work"


#: A portable command name, not a host filesystem path (codex review found
#: the earlier version used `sys.executable` - the VERIFIER's own interpreter
#: path, e.g. under this host's `.venv`, which a real backend's isolation has
#: no reason to contain). Matches how agent CLI binaries are already referenced
#: by bare name rather than a host path; a probe-serving backend's image is
#: expected to carry a `python3` on `PATH`, exactly as an agent image is
#: expected to carry `codex`/`claude`.
PROBE_INTERPRETER = "python3"

#: Surface key naming which placed candidate paths need the executable bit
#: (codex review: the bytes-only surface convention otherwise drops it
#: silently). A backend that does not yet honour this key installs every file
#: without +x - stated as a real, current limitation for a candidate that
#: must be exec'd directly rather than imported; today's shipped graders only
#: import candidate code, so this does not block them.
SURFACE_EXECUTABLE_KEY = "__executable__"


def _probe_surface(grader: GraderDef, loaded: dict[str, bytes],
                    files: list[tuple[str, bytes, bool]]) -> dict[str, object]:
    """The grader-shaped surface for a probe-style `install()`: flat
    `{relative path: bytes}` entries, one per file the backend must place
    under `PROBE_WORKDIR`, plus `SURFACE_EXECUTABLE_KEY` naming which of them
    need +x. NOT #7's skill-materialization vocabulary -
    `ExecutionBackend.install()`'s `surface` has no Protocol-fixed key set, so
    probe callers use their own, agreed directly with the Docker backend's
    author rather than guessed: any declared entry whose value is `bytes` is
    written at that relative path. Held-out `inputs` are NOT here - they go to
    the probe's stdin at `execute()`, matching the bare-subprocess path
    exactly, so an existing probe.py needs no rewrite to run either way."""
    surface: dict[str, object] = {grader.probe.name: loaded["probe"]}
    executable: list[str] = []
    for rel, data, is_executable in files:
        path = f"candidate/{rel}"
        surface[path] = data
        if is_executable:
            executable.append(path)
    surface[SURFACE_EXECUTABLE_KEY] = executable
    return surface


def _probe_via_backend(
    grader: GraderDef, loaded: dict[str, bytes], files: list[tuple[str, bytes, bool]],
    work: Path, backend: ExecutionBackend, recorded_attempt_ids: list[str] | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    """Stage 1, through an `ExecutionBackend` instead of a bare host subprocess
    (#10 PR2, interfaces.md step 8: "a SEPARATE backend instance, through this
    same seam"). Returns the SAME (envelope, containment) shape `_probe`
    does, so `_judge`/`_assemble` need no changes at all - only what produces
    the envelope changes.

    Confidentiality and prevention are the BACKEND's claims (`describe()`'s
    `isolation`/`unobserved`), never asserted here. See the module docstring:
    no concrete backend exists in this repository at this commit, so those
    claims are owed to the live run, whatever this function returns.

    `confirm_stopped()` is the SOLE containment authority - there is no
    subreaper-supervisor trick here, because that exists specifically to
    catch a same-PID-namespace escapee; a backend's own teardown (`destroy`,
    confirmed by `confirm_absent`) is what removes everything regardless.
    `BackendUnavailable`, from either `prepare()` or `install()`, is a
    refusal - `confirmed` stays False and nothing falls back to the bare
    subprocess path silently.

    QUARANTINE APPLIES HERE TOO (codex review): a probe that actually started
    (past `install()`) and was not confirmed stopped, or whose backend could
    not confirm its resources gone after `destroy()`, leaves this verifier in
    exactly the state the bare-subprocess path's fallback sweep exists to
    guard against - a surviving candidate-controlled process or resource that
    could reach the NEXT grading run. `prepare()`/`install()` failing before
    anything started is not quarantined (nothing to survive); everything
    after is.

    THE OBSERVATIONS CONVENTION. `ExecutionBackend.execute()` has no field for
    a launched process's own stdout - `lifecycle.py`'s `_ensure_spool_files`
    already names this exact gap for agent execution ("a real backend's
    stdio becomes an ordinary exported artifact today, not the client-events/
    client-stderr observation streams run_attempt-driven attempts get") and
    resolves it the same way this does: a probe-serving backend is expected to
    capture the started process's stdout to a file named `observations` at its
    workspace root, so it appears after `export()` at exactly the path this
    function reads. Documented convention, not a Protocol change - the same
    tier as the `candidate/<path>` placement convention above.
    """
    describe = backend.describe()
    backend_identity: dict[str, object] = {
        "name": describe.name, "version": describe.version,
        "isolation": list(describe.isolation), "unobserved": list(describe.unobserved),
    }
    empty_envelope = {"observations": "", "timed_out": False}

    probe_attempt_id = f"probe-{secrets.token_hex(8)}"
    if recorded_attempt_ids is not None:
        recorded_attempt_ids.append(probe_attempt_id)  # before prepare(), so a caller's sweep can name it
    try:
        handle = backend.prepare(probe_attempt_id)
    except BackendUnavailable as exc:
        return empty_envelope, {
            "backend": backend_identity, "confirmed": False, "timed_out": False,
            "backend_unavailable": True, "reason": f"backend unavailable at prepare(): {exc}",
        }

    containment: dict[str, object] = {"backend": backend_identity, "confirmed": False, "timed_out": False}
    envelope = empty_envelope
    try:
        try:
            backend.install(handle, _probe_surface(grader, loaded, files))
        except BackendUnavailable as exc:
            containment["backend_unavailable"] = True
            containment["reason"] = f"backend unavailable at install(): {exc}"
        else:
            argv = [
                PROBE_INTERPRETER, "-I", "-S", "-B",
                f"{PROBE_WORKDIR}/{grader.probe.name}", f"{PROBE_WORKDIR}/candidate",
            ]
            result = backend.execute(
                handle, argv, Limits(timeout=grader.probe_timeout), stdin=loaded["inputs"],
            )
            stop_confirmation = backend.confirm_stopped(handle)
            confirmed = stop_confirmation is Confirmation.CONFIRMED
            containment["confirmed"] = confirmed
            containment["timed_out"] = result.reason == "timeout"
            containment["exit_code"] = result.exit_code
            if result.error is not None:
                containment["error"] = result.error
            if result.signal is not None:
                containment["signal"] = result.signal
            if not confirmed:
                containment["reason"] = (
                    f"the backend could not confirm the probe stopped ({stop_confirmation.value})"
                )
                # A probe that actually started (past install()) and was not
                # confirmed stopped may still have a candidate-controlled
                # process alive - the same reason the bare-subprocess path's
                # unswept-descendant case quarantines (codex review).
                _set_quarantine(f"backend probe containment was lost ({containment['reason']})")
            else:
                exported = work / "exported"
                exported.mkdir(mode=0o700, exist_ok=True)
                try:
                    backend.export(handle, exported)
                except OSError as exc:
                    containment["confirmed"] = False
                    containment["reason"] = f"export failed: {exc}"
                else:
                    envelope = {
                        "observations": _read_observations(exported / "observations"),
                        "timed_out": containment["timed_out"],
                    }
    finally:
        # TEARDOWN ITSELF MUST NOT BE ABLE TO SKIP QUARANTINE (codex review):
        # the first version let an exception from destroy() or
        # confirm_absent() propagate before either the teardown record or a
        # quarantine was ever written - execute() may have started a
        # candidate-controlled process, and an unexpected backend exception
        # here answers NOTHING about whether it is gone. Both calls are made,
        # both raise-paths are caught, and quarantine is set whenever
        # anything short of a confirmed absence resulted - a raised
        # exception included - before the ORIGINAL exception (if any) is
        # re-raised. Nothing here reads as a clean teardown that wasn't.
        destroy_error: BaseException | None = None
        try:
            backend.destroy(handle)
        except Exception as exc:  # noqa: BLE001 - deliberately broad: any teardown failure is a containment question, not a specific one to filter for
            destroy_error = exc
        try:
            teardown_confirmation = backend.confirm_absent(handle)
        except Exception as exc:  # deliberately broad: see above
            containment["teardown"] = "unknown"
            containment["teardown_error"] = str(exc)
            _set_quarantine(f"backend confirm_absent() raised during teardown: {exc}")
            if destroy_error is None:
                raise
        else:
            containment["teardown"] = teardown_confirmation.value
            if teardown_confirmation is not Confirmation.CONFIRMED:
                _set_quarantine(
                    f"backend teardown was not confirmed absent ({teardown_confirmation.value})"
                )
        if destroy_error is not None:
            containment["destroy_error"] = str(destroy_error)
            _set_quarantine(f"backend destroy() raised during teardown: {destroy_error}")
            raise destroy_error

    return envelope, containment


def _judge(grader: GraderDef, loaded: dict[str, bytes], work: Path,
           envelope: dict[str, object]) -> tuple[str, str, object]:
    """Stage 2: the trusted judge, in a directory created after the sweep."""
    home = work / "home"
    home.mkdir(mode=0o700, parents=True)
    judge = work / grader.judge.name
    _write_tree(work, [(grader.judge.name, loaded["judge"], False)])
    proc = subprocess.Popen(
        [sys.executable, "-I", "-S", "-B", str(judge), "--judge"], cwd=work, env=_env(home),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
    )
    try:
        out, err = proc.communicate(json.dumps(envelope).encode(), timeout=grader.judge_timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        return "timeout", f"the judge did not finish within {grader.judge_timeout:g}s", None
    if proc.returncode != 0:
        tail = err.decode("utf-8", errors="replace").strip().splitlines()[-1:] or ["no stderr"]
        return "exit-nonzero", f"the judge exited {proc.returncode}: {tail[0]}", None
    if not out.strip():
        return "no-output", "the judge exited 0 and emitted no result", None
    try:
        report = json.loads(out)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return "unparseable", f"the judge's output is not JSON: {exc}", None
    if not isinstance(report, dict):
        return "unparseable", "the judge's output is not an object", None
    return "verdict", "", report


def criteria_problem(criteria: object, required: tuple[str, ...]) -> str | None:
    """Why a report's criteria are not exactly the grader's required set, or None."""
    if not isinstance(criteria, list):
        return "no criteria list"
    ids = [c.get("id") for c in criteria if isinstance(c, dict)]
    if len(ids) != len(criteria) or not all(isinstance(i, str) for i in ids):
        return "a criterion is not an object with a string id"
    if len(set(ids)) != len(ids):
        return "criterion ids are not unique"
    if set(ids) != set(required):
        missing = sorted(set(required) - set(map(str, ids)))
        extra = sorted(set(map(str, ids)) - set(required))
        return f"criteria differ from the required set (missing {missing}, extra {extra})"
    if not all(c.get("mandatory") is True for c in criteria):
        return "a required criterion is not mandatory"
    return None


def _assemble(grader: GraderDef, report: object, digests: list[str]) -> tuple[str, str, list[dict[str, object]] | None]:
    """Stage 3: the judge's criteria, if and only if they are a verdict on this task."""
    assert isinstance(report, dict)
    shape = criteria_problem(report.get("criteria"), grader.criteria)
    if shape:
        return "criteria-set", f"the report is not a verdict on this task: {shape}", None
    probe = records.Record(path=Path("<judge report>"), data={
        "version": 2, "kind": records.VERIFIED_RESULT, "result_id": "judge-report",
        "grader": {"id": grader.id, "revision": grader.revision},
        "graded_digests": digests, "criteria": report["criteria"],
    })
    problems = [*records.criterion_vocabulary(probe), *records.result_evidence(probe)]
    if problems:
        return "contract", f"the report breaks the result contract: {problems[0]}", None
    criteria = report["criteria"]
    assert isinstance(criteria, list)
    keep = ("id", "mandatory", "outcome", "evidence", "missing")
    return "verdict", "", [{k: c[k] for k in keep if k in c} for c in criteria]


def _unknown(grader: GraderDef, why: str) -> list[dict[str, object]]:
    return [{"id": c, "mandatory": True, "outcome": "UNKNOWN", "missing": f"the grader gave no verdict: {why}"}
            for c in grader.criteria]


def _status(criteria: list[dict[str, object]]) -> str:
    return records.derive_status(records.Record(path=Path("<criteria>"), data={"criteria": criteria}))


def grade_files(grader: GraderDef, files: list[tuple[str, bytes, bool]], base: Path,
                forbidden: list[Path] | None = None, loaded: dict[str, bytes] | None = None,
                backend: ExecutionBackend | None = None,
                recorded_attempt_ids: list[str] | None = None,
                trusted_observation: bytes | None = None) -> Graded:
    """Grade candidate files through the three stages, in a disposable owned root.

    `files` are (relative path, bytes, executable). The root is removed afterwards,
    whatever happened, and its cleanup outcome is part of the containment record.

    `backend` is None by default: stage 1 (the probe) runs as it always has, a
    bare host subprocess under the supervisor. Given an `ExecutionBackend`
    (#10 PR2), stage 1 runs inside a fresh, separate instance of it instead -
    see the module docstring for what that does and does not establish. Stage
    2 (the judge) never changes: it is trusted code, not candidate code.

    `recorded_attempt_ids`, given with a `backend`, gets the probe's own
    attempt id appended before `prepare()` (issue #122): a caller's
    label-scoped reap sweep can then cover the probe's container too, not
    only the attempts it created itself. Omitted, nothing changes.

    `trusted_observation` (issue #14) is bytes the CALLER already holds and
    that neither the probe nor candidate code produced - a controller-owned
    fixture-service log, captured no earlier than a confirmed stop. Given,
    it is added to the judge's envelope as `"trusted"`, a key `_probe`/
    `_probe_via_backend` never set, so it reaches the judge without ever
    passing through candidate-shared code. Omitted, the envelope carries no
    `"trusted"` key at all - a judge must read that absence as UNKNOWN, never
    as an empty-but-present log. Its sha256 is recorded in `containment` as
    `trusted_observation_digest`, alongside `backend`, for the same reason
    that field is: so a reader of the stored result never has to infer which
    boundary applied.
    """
    if _quarantine is not None:
        raise Refused(f"this verifier is quarantined: {_quarantine}; an operator must check the host "
                      "and call verify.clear_quarantine() before grading again")
    if not files:
        raise Refused("nothing to grade: an empty candidate is not a clean one")
    if loaded is None:
        loaded = grader.read()
    digests = sorted({trial.sha256_bytes(data) for _, data, _ in files})
    try:
        root, nonce = create_root(base, [*(forbidden or []), grader.root])
    except NotOwned as exc:
        raise Refused(str(exc)) from None
    try:
        probe_dir = root / "probe"
        probe_dir.mkdir(mode=0o700)
        if backend is None:
            (probe_dir / "candidate").mkdir(mode=0o700)
            _write_tree(probe_dir / "candidate", files)
            envelope, containment = _probe(grader, loaded, probe_dir)
        else:
            # Candidate/probe/inputs bytes go THROUGH the backend's install(),
            # never staged on this host first - install()'s own contract
            # ("the skill starts inside the isolation - never staged on the
            # host and merely copied in afterward") applies here too.
            envelope, containment = _probe_via_backend(
                grader, loaded, files, probe_dir, backend, recorded_attempt_ids,
            )
        if trusted_observation is not None:
            # Set after the probe returns and BEFORE the judge runs, never
            # earlier: this key must never be reachable from `_probe`/
            # `_probe_via_backend`, which build `envelope` from candidate-
            # shared state alone.
            envelope["trusted"] = trusted_observation.decode("utf-8", errors="replace")
            containment["trusted_observation_digest"] = trial.sha256_bytes(trusted_observation)
        if not containment["confirmed"]:
            category, detail = "containment", f"the probe was not contained: {containment['reason']}"
            criteria = _unknown(grader, detail)
        else:
            category, detail, report = _judge(grader, loaded, root / "judge", envelope)
            assembled = None
            if category == "verdict":
                category, detail, assembled = _assemble(grader, report, digests)
            criteria = assembled if assembled is not None else _unknown(grader, detail)
    finally:
        cleanup = remove_owned(root, nonce)
    containment["cleanup"] = cleanup["status"]
    status = _status(criteria)
    if category == "verdict":
        unmet = [str(c["id"]) for c in criteria if c.get("outcome") != "SATISFIED"]
        detail = "all mandatory criteria satisfied" if not unmet else "not satisfied: " + ", ".join(unmet)
    return Graded(status=status, category=category, detail=detail, criteria=criteria, containment=containment)


def grade_directory(grader: GraderDef, candidate: Path, base: Path | None = None,
                    trusted_observation: bytes | None = None) -> Graded:
    """Grade a committed candidate directory, as `qualify.py` does to certify a grader.

    Only regular files are copied; links and special files are not followed.

    `trusted_observation`, given, is NOT read from `candidate` - a fixture's
    trusted-log companion lives beside it (e.g. a sibling `trusted/` or
    `expected.json`, task-specific), never inside the directory being frozen
    and graded as the candidate's own files. See `grade_files`.
    """
    files: list[tuple[str, bytes, bool]] = []
    for dirpath, dirnames, filenames in os.walk(candidate, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
        for name in sorted(filenames):
            path = Path(dirpath) / name
            info = path.lstat()
            if stat.S_ISREG(info.st_mode):
                rel = path.relative_to(candidate).as_posix()
                files.append((rel, path.read_bytes(), bool(info.st_mode & stat.S_IXUSR)))
    return grade_files(grader, files, base if base is not None else Path(tempfile.gettempdir()),
                       trusted_observation=trusted_observation)


# ------------------------------------------------------------ grading an attempt


def _in_flight_scratch(experiment: trial.Experiment, attempt_id: str) -> frozenset[str]:
    """The only paths a grade's snapshot leaves out (#12): the journal and
    spool files of OTHER attempts the ledger plans and that are not yet
    finalized. Those are written while a sibling RUNS - by its controller's
    journal and by the subject's own redirected output - for as long as it
    runs, so no lock can make them hold still.

    What this gives up, stated: candidate code that wrote into an unfinished
    sibling's journal or spool would not be caught by THIS grade. It is not
    what contains candidate code - the grading backend and the forbidden
    store root are - and that sibling's own capture hashes those bytes when it
    is frozen. Everything else still refuses: the ledger and its history,
    every object, every finalized attempt's files, this attempt's own files,
    and any path naming an attempt the ledger does not plan. The set is fixed
    before grading; a sibling cannot finalize mid-grade, since `finalize`
    waits for the experiment lock this grade holds."""
    skip: set[str] = set()
    for _trial, attempt in experiment.attempts():
        other = str(attempt["attempt_id"])
        if other == attempt_id or (experiment.root / f"lifecycle-{other}.json").exists():
            continue
        skip.update((f"{trial.JOURNAL}/{other}.jsonl", f"{trial.SPOOL}/{other}.stdout",
                     f"{trial.SPOOL}/{other}.stderr"))
    return frozenset(skip)


def _snapshot(root: Path, skip: frozenset[str] = frozenset()) -> dict[str, str]:
    """Every entry under the experiment, by content, except the relative paths
    in `skip`. Links are recorded, not followed."""
    seen: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in [*dirnames, *filenames]:
            path = Path(dirpath) / name
            rel = path.relative_to(root).as_posix()
            if rel in skip:
                continue
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                seen[rel] = "link:" + os.readlink(path)
            elif stat.S_ISDIR(info.st_mode):
                seen[rel] = "dir"
            elif stat.S_ISREG(info.st_mode):
                seen[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
            else:
                seen[rel] = f"special:{stat.S_IFMT(info.st_mode)}"
    return seen


def _changed(before: dict[str, str], after: dict[str, str]) -> str | None:
    for rel in sorted(set(before) | set(after)):
        if before.get(rel) != after.get(rel):
            how = "appeared" if rel not in before else "disappeared" if rel not in after else "changed"
            return f"{rel} {how}"
    return None


def _receipt(experiment: trial.Experiment, attempt_id: str, planned: dict[str, object]) -> tuple[str, dict[str, object]]:
    """The attempt's installation receipt, refused if absent, invalid or stale."""
    name = f"receipt-{attempt_id}.json"
    path = experiment.root / name
    if path.is_symlink() or not path.is_file():
        raise Refused(f"attempt {attempt_id!r} has no installation receipt; a graded result "
                      "without one is refused by attempt-accounting, so it is not graded")
    data = json.loads(_read_regular(path))
    problems = [f.detail for f in checks.run_record(records.Record(path, data))]
    if problems:
        raise Refused(f"{name} is not valid: {problems[0]}")
    for ident, keys in (("subject", ("digest",)), ("client", ("name", "version"))):
        got, want = data.get(ident), planned.get(ident)
        if not isinstance(got, dict) or not isinstance(want, dict) or any(got.get(k) != want.get(k) for k in keys):
            raise Refused(f"{name}: its {ident} is not the trial's planned {ident}; a stale receipt is not graded")
    # #150-D: a receipt measured in one container image must not be applied to
    # an attempt planned against another. Only receipts that CLAIM an image
    # identity are checked - the native install path (materialize.py) predates
    # Docker and never writes one, and a receipt silent on image says nothing
    # about it either way, so it is not treated as stale on that account alone.
    image = data.get("image")
    if image is not None:
        want_image = planned.get("image")
        if (not isinstance(image, dict) or not isinstance(want_image, dict)
                or image.get("digest") != want_image.get("digest")):
            raise Refused(f"{name}: its image is not the trial's planned image; a stale receipt is not graded")
    if data.get("attempt_id") != attempt_id or data.get("trial_id") != planned.get("trial_id"):
        raise Refused(f"{name} names another attempt or trial; a stale receipt is not graded")
    return name, data


def _readiness(name: str, receipt: dict[str, object]) -> dict[str, object]:
    """The verifier's own mandatory criterion: was the subject installed as planned?

    Anything but SATISFIED on both required facts is UNKNOWN, so the trial cannot
    PASS: it did not measure the subject as installed. An observed task violation
    still derives FAIL, because VIOLATED is tested before UNKNOWN.
    """
    readiness = receipt.get("readiness")
    facts = {k: (readiness.get(k) if isinstance(readiness, dict) else None) for k in READINESS_FACTS}
    shown = ", ".join(f"{k}={v}" for k, v in facts.items())
    if all(v == "SATISFIED" for v in facts.values()):
        return {"id": READINESS_CRITERION, "mandatory": True, "outcome": "SATISFIED",
                "evidence": [f"{name}: {shown}"]}
    return {"id": READINESS_CRITERION, "mandatory": True, "outcome": "UNKNOWN",
            "missing": f"installation readiness is not established ({shown} in {name}); "
                       "this trial did not measure the subject as installed"}


def _ptrace_scope() -> str:
    try:
        return Path("/proc/sys/kernel/yama/ptrace_scope").read_text(encoding="ascii").strip()
    except OSError:
        return "unknown"


def _observation_readiness(attempt_id: str) -> dict[str, object]:
    """The verifier's `installation-ready` criterion on the agent-trial path
    (#139, owner decision B1): UNKNOWN, always. The observation that stands in
    for the receipt shows the prompt arrived and the agent was live - not that
    the subject was installed as planned and discovered - so it cannot satisfy
    readiness, and the trial cannot PASS on it."""
    return {"id": READINESS_CRITERION, "mandatory": True, "outcome": "UNKNOWN",
            "missing": f"no installation receipt on the agent-trial path; "
                       f"{observation_record_name(attempt_id)} stands in for it in attempt accounting "
                       "but does not establish that the subject was installed and discovered"}


def _eligible_observation(attempt_id: str, observation: Mapping[str, object]) -> None:
    """Refuse to grade on an observation that did not confirm the attempt."""
    if observation.get("status") == "unknown":
        raise Refused(f"attempt {attempt_id!r}: its transcript observation is unknown; "
                      "an unconfirmed attempt is never graded")
    if observation.get("grading_eligible") is not True or observation.get("prompt_delivered") is not True \
            or observation.get("canary_satisfied") is not True:
        raise Refused(f"attempt {attempt_id!r}: its observation does not confirm both prompt delivery and "
                      "the canary, so it cannot stand in for an installation receipt")


def grade_agent_attempt(experiment: trial.Experiment, attempt_id: str, grader: GraderDef, base: Path,
                        observation: Mapping[str, object], backend: ExecutionBackend | None = None,
                        forbidden: list[Path] | None = None,
                        trusted_observation: bytes | None = None) -> tuple[dict[str, object], Graded]:
    """Grade one captured agent-trial attempt and store its `verified-result`
    (#139), exactly as `grade` does - the same pin, capture, snapshot, ledger
    and frozen-digest checks - except that the controller's transcript
    `observation` (what `agent_trial` records for the attempt) stands in for
    the installation receipt. Refused, nothing written, unless it confirms
    both prompt delivery and the canary.

    `trusted_observation` (issue #14) is forwarded to `grade_files` - see
    there. On this path it is a runtime fixture service's own log (an
    authority-boundary interceptor's or a disruption trigger's), captured by
    the caller no earlier than the backend's confirmed stop, never anything
    the subject's own process produced.

    Returns the stored result and the task grade (`Graded`, without the
    verifier's readiness criterion), which is what the agent driver reports
    as the attempt's own grade."""
    _eligible_observation(attempt_id, observation)
    return _grade_and_store(experiment, attempt_id, grader, base, forbidden, backend=backend,
                            readiness_source=AGENT_OBSERVATION_READINESS,
                            trusted_observation=trusted_observation)


def grade(experiment: trial.Experiment, attempt_id: str, grader: GraderDef, base: Path,
          forbidden: list[Path] | None = None, regrade_of: str | None = None,
          backend: ExecutionBackend | None = None,
          judges: Mapping[str, judge_seam.Judge] | None = None, goal_text: str = "") -> dict[str, object]:
    """Grade one captured attempt and store its `verified-result`.

    Refused, and nothing written, when the ledger pins no grader digest or another
    one, the attempt was not captured, its receipt is missing or stale, or anything
    candidate code could reach changed while it ran. A grader that gives no verdict
    is NOT a refusal: that result is stored, INCONCLUSIVE, with its reason.

    `backend` is forwarded to `grade_files` (see there). Every result records
    `verification.tiers_enabled` (`[GRADING_TIER]`, plus one entry per key in
    `judges` - #69's own tier names, `skillc.judge.SAME_MODEL_TIER`/
    `INDEPENDENT_TIER`) and `verification.verdicts`, a collection keyed by
    tier name, each entry carrying its own `status`, `criteria` and (for the
    deterministic tier) `backend` - so a reader never has to infer which
    boundary applied from the shape of `containment` alone, and no tier's
    verdict ever overwrites or averages with another's. The top-level
    `status`/`criteria` stay exactly the deterministic tier's own, whatever
    `judges` says - #69 requires it never be read as a blend.

    `judges`, when given, maps a tier name to a `skillc.judge.Judge` - see
    that module for the seam, schema validation and the ONLY implementation
    it ships (`FakeJudge`, for tests: #69's own acceptance forbids a real
    model call in this suite). Each judge grades `grader.criteria` - the
    SAME ids the deterministic tier already checks, so its own
    `verification.disagreement` comparison is between two opinions of the
    same criteria, not different ones - against `goal_text` and the frozen
    candidate files, THROUGH `skillc.judge.run_tier`, which leak-checks that
    input before either judge is ever called (#63) and turns an unreachable
    judge into that tier's own `UNAVAILABLE` verdict, never a refusal of the
    whole grade. A LEAK, unlike an unreachable judge, IS a refusal
    (`Refused`, nothing written) - candidate-carried machine identity must
    never reach an external judge process, approved budget or not.
    `verification.disagreement` is computed by `skillc.judge.compute_disagreement`
    and stays unavailable (`skillc.judge.DISAGREEMENT_UNAVAILABLE_REASON`)
    unless both the same-model and independent tiers report a real verdict.

    This is a reshape of the single `verification.grading_tier` field #76
    shipped, not a new envelope version: nothing outside this build's own
    tests has ever produced or read that field on a real trial (PR #88's
    own ruling, Refs #69), so there is no consumer for record-envelope
    versioning to protect.
    """
    return _grade_and_store(experiment, attempt_id, grader, base, forbidden, regrade_of,
                            backend, judges, goal_text)[0]


def _grade_and_store(experiment: trial.Experiment, attempt_id: str, grader: GraderDef, base: Path,
                     forbidden: list[Path] | None = None, regrade_of: str | None = None,
                     backend: ExecutionBackend | None = None,
                     judges: Mapping[str, judge_seam.Judge] | None = None, goal_text: str = "",
                     readiness_source: str = records.INSTALLATION_RECEIPT,
                     trusted_observation: bytes | None = None) -> tuple[dict[str, object], Graded]:
    """Holds the experiment lock (#12) from the first read to the stored
    result, so a sibling attempt's capture, finalize or stored result waits
    for this grade instead of reading to its snapshot as tampering.

    Grades against the experiment as STORED once the lock is held - reopened,
    so its whole ledger history is re-verified - never the ledger the
    caller's instance loaded earlier: a sibling's retry committed before the
    lock is the current ledger, not a change made while candidate code ran
    (counter-model finding)."""
    with trial.experiment_lock(experiment.root):
        current = trial.Experiment.open(experiment.root)
        return _grade_and_store_held(current, attempt_id, grader, base, forbidden, regrade_of,
                                     backend, judges, goal_text, readiness_source, trusted_observation)


def _grade_and_store_held(experiment: trial.Experiment, attempt_id: str, grader: GraderDef, base: Path,
                          forbidden: list[Path] | None, regrade_of: str | None,
                          backend: ExecutionBackend | None,
                          judges: Mapping[str, judge_seam.Judge] | None, goal_text: str,
                          readiness_source: str,
                          trusted_observation: bytes | None = None) -> tuple[dict[str, object], Graded]:
    if judges:
        unknown_tiers = set(judges) - set(judge_seam.JUDGE_TIERS)
        if unknown_tiers:
            raise Refused(
                f"judges carries key(s) {sorted(unknown_tiers)}, not one of {list(judge_seam.JUDGE_TIERS)} - "
                f"{GRADING_TIER!r} in particular must never be passed here, or a judge's own verdict "
                "would silently overwrite the deterministic tier's"
            )
    planned = experiment.trial_of(attempt_id)
    pin = planned.get("grader")
    assert isinstance(pin, dict)
    if not isinstance(pin.get("digest"), str) or not pin["digest"]:
        raise Refused(f"trial {planned['trial_id']!r} pins no grader digest; "
                      "a missing digest is refused, never graded on trust")
    if (pin.get("id"), pin.get("revision")) != (grader.id, grader.revision):
        raise Refused(f"the ledger plans grader {pin.get('id')!r} revision {pin.get('revision')!r}, "
                      f"not {grader.id!r} revision {grader.revision!r}")
    loaded = grader.read()
    if grader.digest(loaded) != pin["digest"]:
        raise Refused("the grader definition does not match the digest the ledger pinned")
    lifecycle = experiment.root / f"lifecycle-{attempt_id}.json"
    if lifecycle.is_symlink() or not lifecycle.is_file() or \
            json.loads(_read_regular(lifecycle)).get("disposition") != "captured":
        raise Refused(f"attempt {attempt_id!r} is not a finalized capture; nothing else can be graded")
    if base.resolve().is_relative_to(experiment.root.parent.resolve()):
        raise Refused("refusing to grade inside the evidence store")
    if readiness_source == records.INSTALLATION_RECEIPT:
        receipt_name, receipt = _receipt(experiment, attempt_id, planned)
        readiness = _readiness(receipt_name, receipt)
    elif readiness_source == AGENT_OBSERVATION_READINESS:
        readiness = _observation_readiness(attempt_id)
    else:
        raise Refused(f"unknown readiness source {readiness_source!r}")
    frozen = trial.frozen_artifacts(experiment, attempt_id)
    files = [
        (str(a["path"]), _read_frozen(experiment, str(a["digest"])), a.get("mode") == "x")
        for a in frozen
    ]

    in_flight = _in_flight_scratch(experiment, attempt_id)
    before = _snapshot(experiment.root, in_flight)
    graded = grade_files(grader, files, base, [*(forbidden or []), experiment.root.parent.resolve()],
                          loaded, backend=backend, trusted_observation=trusted_observation)

    # Everything candidate code could have reached is checked again. A change here
    # is not a verdict on the candidate: the measurement itself is compromised.
    if grader.digest() != pin["digest"]:
        raise Refused("the grader definition changed while it was grading; no result is written")
    changed = _changed(before, _snapshot(experiment.root, in_flight))
    if changed:
        raise Refused(f"the evidence store changed while candidate code ran ({changed}); no result is written")
    if trial.Experiment.open(experiment.root).ledger != experiment.ledger:
        raise Refused("the ledger changed while candidate code ran; no result is written")
    trial.frozen_artifacts(experiment, attempt_id)

    criteria = [*graded.criteria, readiness]
    status = _status(criteria)

    tiers_enabled = [GRADING_TIER]
    verdicts: dict[str, object] = {
        GRADING_TIER: {
            "status": status,
            "criteria": criteria,
            "backend": graded.containment.get("backend"),
            "trusted_observation_digest": graded.containment.get("trusted_observation_digest"),
        },
    }
    if judges:
        candidate_files = [(str(a["path"]), _read_frozen(experiment, str(a["digest"]))) for a in frozen]
        for tier_name, one_judge in judges.items():
            try:
                verdicts[tier_name] = judge_seam.run_tier(
                    tier_name, one_judge, grader.criteria, goal_text, candidate_files
                )
            except judge_seam.JudgeInputLeaked as exc:
                raise Refused(str(exc)) from exc
            tiers_enabled.append(tier_name)
    disagreement = (
        judge_seam.compute_disagreement(verdicts) if judges
        else {"available": False, "reason": DISAGREEMENT_UNAVAILABLE_REASON}
    )

    result: dict[str, object] = {
        "version": 2,
        "kind": records.VERIFIED_RESULT,
        "producer": "assembler",
        "attempt_id": attempt_id,
        "trial_id": planned["trial_id"],
        "result_id": "r-" + secrets.token_hex(6),
        "grader": {"id": grader.id, "revision": grader.revision, "digest": pin["digest"]},
        "graded_digests": sorted({str(a["digest"]) for a in frozen}),
        "criteria": criteria,
        # `status` is the deterministic tier's own status, literally the same
        # value stored at verification.verdicts.deterministic.status below -
        # never a blend, and #69 requires this stay true once other tiers exist.
        "status": status,
        "verification": {
            "category": graded.category, "detail": graded.detail,
            "containment": graded.containment, "ptrace_scope": _ptrace_scope(),
            "provenance": provenance.stamp().as_dict(),
            "tiers_enabled": tiers_enabled,
            "verdicts": verdicts,
            "disagreement": disagreement,
        },
    }
    if readiness_source != records.INSTALLATION_RECEIPT:
        verification = result["verification"]
        assert isinstance(verification, dict)
        verification["readiness_source"] = readiness_source
    if regrade_of is not None:
        result["regrade_of"] = regrade_of
    trial.add_result(experiment, result)
    return result, graded


def _read_frozen(experiment: trial.Experiment, digest: str) -> bytes:
    data = _read_regular(experiment.object_path(digest))
    if trial.sha256_bytes(data) != digest:
        raise Refused(f"object {digest} was modified after it was stored")
    return data


def regrade(experiment: trial.Experiment, result_id: str, grader: GraderDef, base: Path,
            forbidden: list[Path] | None = None, backend: ExecutionBackend | None = None) -> dict[str, object]:
    """Grade the same frozen bytes again, as a NEW result linked to the original.

    The original is retained (protocol.md). The grader must still be the pinned
    one, so a deterministic grader gives the same criterion outcomes.
    """
    path = experiment.root / f"result-{result_id}.json"
    if path.is_symlink() or not path.is_file():
        raise Refused(f"no stored result {result_id!r} to regrade")
    original = json.loads(_read_regular(path))
    attempt_id = str(original.get("attempt_id"))
    verification = original.get("verification")
    if isinstance(verification, dict) and verification.get("readiness_source") == AGENT_OBSERVATION_READINESS:
        # Agent-written candidate code is never run as a bare host process
        # (codex review): the original grade ran inside a separate backend
        # instance, and a regrade must not quietly downgrade that boundary.
        if backend is None:
            raise Refused(f"result {result_id!r} grades agent-written code; regrading it needs an explicit "
                          "grading backend, never the bare host subprocess")
        # The same stand-in the original was graded on (#139), read back from
        # the store: an agent attempt has no receipt to regrade against.
        _eligible_observation(attempt_id, _stored_observation(experiment, attempt_id, original))
        return _grade_and_store(experiment, attempt_id, grader, base, forbidden, regrade_of=result_id,
                                backend=backend, readiness_source=AGENT_OBSERVATION_READINESS)[0]
    return grade(experiment, attempt_id, grader, base, forbidden, regrade_of=result_id, backend=backend)


def _stored_observation(experiment: trial.Experiment, attempt_id: str,
                        original: Mapping[str, object]) -> dict[str, object]:
    """The attempt's stored agent-observation, flattened to the fields
    `_eligible_observation` reads. Refused when absent, not a valid
    agent-observation, or bound to another attempt or trial - the same
    staleness `_receipt` refuses (codex review: a copied observation from
    another attempt must not stand in for this one)."""
    path = experiment.root / observation_record_name(attempt_id)
    if path.is_symlink() or not path.is_file():
        raise Refused(f"attempt {attempt_id!r} has no {path.name}; its agent-path result cannot be regraded")
    data = json.loads(_read_regular(path))
    record = records.Record(path, data)
    if record.kind != records.AGENT_OBSERVATION:
        raise Refused(f"{path.name} is not an agent-observation record")
    problems = [f.detail for f in checks.run_record(record)]
    if problems:
        raise Refused(f"{path.name} is not valid: {problems[0]}")
    if data.get("attempt_id") != attempt_id or data.get("trial_id") != original.get("trial_id"):
        raise Refused(f"{path.name} names another attempt or trial; a stale observation stands in for nothing")
    transcript = data.get("transcript")
    status = data.get("status")
    return {"status": "unknown" if status != "observed" else status,
            **(transcript if isinstance(transcript, dict) else {})}
