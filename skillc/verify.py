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
     directory holding just the judge file, which holds the answers. No
     candidate process is alive to write on its stdout, the success channel.
  3. ASSEMBLE (this process). The judge's report must carry exactly the grader's
     required criteria and satisfy the record contract. The status is DERIVED by
     `records.derive_status`, never copied, and the verifier adds its own
     `installation-ready` criterion from the attempt's receipt.

After grading, everything candidate code could have touched is re-checked. That
is the grader definition against the ledger's pin, the whole experiment store
against a snapshot, the ledger against its history, and the frozen bytes against
their digests. Any change REFUSES the result. It is never warn-and-proceed.

WHAT THIS DOES NOT ESTABLISH. Candidate code runs as the evaluator's own user, so
a write to the store or to the grader's files is DETECTED, not prevented, and the
answer key's file on disk is readable by a candidate that goes looking for it.
Prevention needs a separate user or container, which is the Docker lane (#10).
The controller host, this package and the Python standard library are trusted.
verification.md lists every assumption.

Stdlib only (AGENTS.md). Linux only: the sweep needs `prctl` and `/proc`. Anywhere
else it fails closed, to INCONCLUSIVE.
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
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath

from . import checks, records, trial
from .materialize import Refused as NotOwned
from .materialize import cleanup as remove_owned
from .materialize import create_root

Refused = trial.Refused

GRADER_FILE = "grader.json"
_GRADER_KEYS = {"id", "revision", "criteria", "probe", "judge"}
_PROBE_KEYS = {"file", "inputs", "timeout"}
_JUDGE_KEYS = {"file", "timeout"}

#: The verifier's own criterion. Candidate outcomes cannot claim it.
READINESS_CRITERION = "installation-ready"
#: The receipt facts records.md requires. Anything but SATISFIED is not ready.
READINESS_FACTS = ("discovery_canary", "baseline_absence")

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
    """A regular file's bytes, never through a link."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
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
        unknown = set(data) - _GRADER_KEYS
        if unknown or set(data) != _GRADER_KEYS:
            raise Refused(f"{where}: fields must be exactly {sorted(_GRADER_KEYS)}")
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
        return cls(
            root=root, id=data["id"], revision=data["revision"], criteria=tuple(criteria),
            probe=_member(root, probe["file"], where), inputs=_member(root, probe["inputs"], where),
            judge=_member(root, judge["file"], where),
            probe_timeout=_timeout(probe["timeout"], where),
            judge_timeout=_timeout(judge["timeout"], where),
        )

    def with_judge(self, judge: Path) -> GraderDef:
        """The same grader with another judge: how a broken-grader control is run.
        Its digest differs, so a ledger pinned to the real grader refuses it."""
        judge = judge.resolve() if not judge.is_symlink() else judge
        if judge.is_symlink() or not judge.is_file():
            raise Refused(f"{judge} is not a regular file")
        return replace(self, judge=judge)

    def digest(self) -> str:
        return trial.sha256_bytes(trial.canonical({
            "id": self.id, "revision": self.revision, "criteria": list(self.criteria),
            "probe": trial.sha256_bytes(_read_regular(self.probe)),
            "inputs": trial.sha256_bytes(_read_regular(self.inputs)),
            "judge": trial.sha256_bytes(_read_regular(self.judge)),
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
    """The whole environment of a grading process. Nothing is inherited, so no
    evaluator credential reaches candidate code, or the judge."""
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


def _read_observations(path: Path) -> str:
    """The probe's report, bounded, never through a link. Absent reads as empty:
    the judge decides what no report means for the candidate."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return ""
    with os.fdopen(fd, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            return ""
        return handle.read(MAX_OBSERVATION_BYTES).decode("utf-8", errors="replace")


def _tail(path: Path) -> str:
    try:
        lines = path.read_bytes()[-4096:].decode("utf-8", errors="replace").strip().splitlines()
    except OSError:
        return "no stderr"
    return lines[-1] if lines else "no stderr"


def _probe(grader: GraderDef, work: Path) -> tuple[dict[str, object], dict[str, object]]:
    """Stage 1: run candidate code under the supervisor. Returns the envelope the
    judge will read and the containment observation."""
    harness, home = work / "harness", work / "home"
    for d in (harness, home):
        d.mkdir(mode=0o700)
    probe = harness / grader.probe.name
    _write_tree(harness, [(grader.probe.name, _read_regular(grader.probe), False)])
    inputs = _read_regular(grader.inputs)
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
        containment["reason"] = {
            UNCONFIRMED: "descendants of the probe survived the sweep",
            UNSUPPORTED: "this host cannot contain the probe (no prctl subreaper or /proc)",
            None: "the supervisor did not finish; its process group was killed",
        }.get(code, f"the supervisor ended abnormally ({code}); candidate code may have killed it")
        containment["stderr"] = _tail(errors)
    envelope = {"observations": _read_observations(observations), "timed_out": code == TIMED_OUT}
    return envelope, containment


def _judge(grader: GraderDef, work: Path, envelope: dict[str, object]) -> tuple[str, str, object]:
    """Stage 2: the trusted judge, in a directory created after the sweep."""
    home = work / "home"
    home.mkdir(mode=0o700, parents=True)
    judge = work / grader.judge.name
    _write_tree(work, [(grader.judge.name, _read_regular(grader.judge), False)])
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
                forbidden: list[Path] | None = None) -> Graded:
    """Grade candidate files through the three stages, in a disposable owned root.

    `files` are (relative path, bytes, executable). The root is removed afterwards,
    whatever happened, and its cleanup outcome is part of the containment record.
    """
    if not files:
        raise Refused("nothing to grade: an empty candidate is not a clean one")
    digests = sorted({trial.sha256_bytes(data) for _, data, _ in files})
    try:
        root, nonce = create_root(base, [*(forbidden or []), grader.root])
    except NotOwned as exc:
        raise Refused(str(exc)) from None
    try:
        probe_dir = root / "probe"
        probe_dir.mkdir(mode=0o700)
        (probe_dir / "candidate").mkdir(mode=0o700)
        _write_tree(probe_dir / "candidate", files)
        envelope, containment = _probe(grader, probe_dir)
        if not containment["confirmed"]:
            category, detail = "containment", f"the probe was not contained: {containment['reason']}"
            criteria = _unknown(grader, detail)
        else:
            category, detail, report = _judge(grader, root / "judge", envelope)
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


def grade_directory(grader: GraderDef, candidate: Path, base: Path | None = None) -> Graded:
    """Grade a committed candidate directory, as `qualify.py` does to certify a grader.

    Only regular files are copied; links and special files are not followed.
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
    return grade_files(grader, files, base if base is not None else Path(tempfile.gettempdir()))


# ------------------------------------------------------------ grading an attempt


def _snapshot(root: Path) -> dict[str, str]:
    """Every entry under the experiment, by content. Links are recorded, not followed."""
    seen: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in [*dirnames, *filenames]:
            path = Path(dirpath) / name
            rel = path.relative_to(root).as_posix()
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


def grade(experiment: trial.Experiment, attempt_id: str, grader: GraderDef, base: Path,
          forbidden: list[Path] | None = None, regrade_of: str | None = None) -> dict[str, object]:
    """Grade one captured attempt and store its `verified-result`.

    Refused, and nothing written, when the ledger pins no grader digest or another
    one, the attempt was not captured, its receipt is missing or stale, or anything
    candidate code could reach changed while it ran. A grader that gives no verdict
    is NOT a refusal: that result is stored, INCONCLUSIVE, with its reason.
    """
    planned = experiment.trial_of(attempt_id)
    pin = planned.get("grader")
    assert isinstance(pin, dict)
    if not isinstance(pin.get("digest"), str) or not pin["digest"]:
        raise Refused(f"trial {planned['trial_id']!r} pins no grader digest; "
                      "a missing digest is refused, never graded on trust")
    if (pin.get("id"), pin.get("revision")) != (grader.id, grader.revision):
        raise Refused(f"the ledger plans grader {pin.get('id')!r} revision {pin.get('revision')!r}, "
                      f"not {grader.id!r} revision {grader.revision!r}")
    if grader.digest() != pin["digest"]:
        raise Refused("the grader definition does not match the digest the ledger pinned")
    lifecycle = experiment.root / f"lifecycle-{attempt_id}.json"
    if lifecycle.is_symlink() or not lifecycle.is_file() or \
            json.loads(_read_regular(lifecycle)).get("disposition") != "captured":
        raise Refused(f"attempt {attempt_id!r} is not a finalized capture; nothing else can be graded")
    if base.resolve().is_relative_to(experiment.root.parent.resolve()):
        raise Refused("refusing to grade inside the evidence store")
    receipt_name, receipt = _receipt(experiment, attempt_id, planned)
    frozen = trial.frozen_artifacts(experiment, attempt_id)
    files = [
        (str(a["path"]), _read_frozen(experiment, str(a["digest"])), a.get("mode") == "x")
        for a in frozen
    ]

    before = _snapshot(experiment.root)
    graded = grade_files(grader, files, base, [*(forbidden or []), experiment.root.parent.resolve()])

    # Everything candidate code could have reached is checked again. A change here
    # is not a verdict on the candidate: the measurement itself is compromised.
    if grader.digest() != pin["digest"]:
        raise Refused("the grader definition changed while it was grading; no result is written")
    changed = _changed(before, _snapshot(experiment.root))
    if changed:
        raise Refused(f"the evidence store changed while candidate code ran ({changed}); no result is written")
    if trial.Experiment.open(experiment.root).ledger != experiment.ledger:
        raise Refused("the ledger changed while candidate code ran; no result is written")
    trial.frozen_artifacts(experiment, attempt_id)

    criteria = [*graded.criteria, _readiness(receipt_name, receipt)]
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
        "status": _status(criteria),
        "verification": {
            "category": graded.category, "detail": graded.detail,
            "containment": graded.containment, "ptrace_scope": _ptrace_scope(),
        },
    }
    if regrade_of is not None:
        result["regrade_of"] = regrade_of
    trial.add_result(experiment, result)
    return result


def _read_frozen(experiment: trial.Experiment, digest: str) -> bytes:
    data = _read_regular(experiment.object_path(digest))
    if trial.sha256_bytes(data) != digest:
        raise Refused(f"object {digest} was modified after it was stored")
    return data


def regrade(experiment: trial.Experiment, result_id: str, grader: GraderDef, base: Path,
            forbidden: list[Path] | None = None) -> dict[str, object]:
    """Grade the same frozen bytes again, as a NEW result linked to the original.

    The original is retained (protocol.md). The grader must still be the pinned
    one, so a deterministic grader gives the same criterion outcomes.
    """
    path = experiment.root / f"result-{result_id}.json"
    if path.is_symlink() or not path.is_file():
        raise Refused(f"no stored result {result_id!r} to regrade")
    original = json.loads(_read_regular(path))
    return grade(experiment, str(original.get("attempt_id")), grader, base, forbidden, regrade_of=result_id)
