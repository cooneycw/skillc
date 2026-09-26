"""Controller-owned trial accounting and artifact capture (#8).

interfaces.md gives the controller two contracts - the trial ledger, and the
artifact and observation bundle - and protocol.md the lifecycle they record. This
module is the controller side of both. It is backend-neutral: a subject is an
argv and a directory, and nothing here knows which client or skill collection it
is running. See docs/specs/evaluation-facility/capture.md.

WHAT THE CONTROLLER OWNS, AND WHY IT MATTERS. Every fact that decides a verdict
is written here, by the controller, into a store the subject cannot reach:

  - the expected population, written BEFORE dispatch, with controller-generated
    identities and the resolved configuration stored and digested;
  - what happened to each attempt - dispatched, stopped and how, whether the stop
    was CONFIRMED, what cleanup did - in an append-only journal;
  - the frozen output, copied AFTER the confirmed stop into content-addressed
    objects, with a manifest of path/type/size/digest;
  - the account of every planned attempt, including the ones that never ran.

Nothing the subject wrote is authority. A `task.json` saying PASS, a config
echoed back, a sentinel line on stdout: each is captured as bytes with its origin
and never becomes a result or a provenance claim. That is the trap
docs/research/coder-eval-lessons.md records in Coder Eval (pitfalls 1-3).

WHAT THIS DOES NOT ESTABLISH. The controller host is trusted (interfaces.md): an
operator can edit the store, and the digests here detect accidental or subject
change, not a forger on the controller. A confirmed stop covers the subject's
process GROUP; a process that leaves the group is not seen - containment is the
Docker lane's job (#10). The secret filter is a list of names and patterns, not a
census of every secret shape.

Stdlib only (AGENTS.md).
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import secrets
import signal
import stat
import subprocess
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from . import checks, records
from .materialize import Refused as NotOwned
from .materialize import cleanup as remove_owned
from .materialize import create_root, forbidden_roots, refuse_protected

STORE_MARKER = ".skillc-store"
LEDGER = "ledger.json"
HISTORY = "ledger-history.jsonl"
OBJECTS = "objects"
JOURNAL = "journal"
SPOOL = "spool"

#: Owner-only. Evidence is local and private until someone decides otherwise.
DIR_MODE = 0o700
FILE_MODE = 0o400

#: Keys a plan may carry. Anything else is refused: an unread key is a setting its
#: author believes is honoured.
_PLAN_KEYS = {"experiment", "trials"}
_TRIAL_KEYS = {"label", "case", "grader", "subject", "client", "image", "config", "attempts", "budget"}
_IDENTITIES = {
    "case": ("id", "revision"),
    "grader": ("id", "revision"),
    "subject": ("digest",),
    "client": ("name", "version"),
    "image": ("digest",),
}
_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,47}$")

#: Directories never exported, whatever the declared scope: VCS metadata, and the
#: homes where clients and tools keep credentials.
SECRET_DIRS = (".git", ".ssh", ".aws", ".gnupg", ".codex", ".claude", ".docker", ".kube")
#: File names never exported.
SECRET_NAMES = (
    ".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "id_rsa*", "id_dsa*",
    "id_ecdsa*", "id_ed25519*", ".netrc", ".npmrc", ".pypirc", ".git-credentials",
    "auth.json", "credentials", "credentials.*",
)
#: Content that marks a file as holding a credential. The finding names the
#: pattern, never the matched value.
SECRET_CONTENT = (
    ("private key", re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("AWS access key", re.compile(rb"\bAKIA[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("API key", re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("Slack token", re.compile(rb"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
)

#: Keys in an imported record that claim an attempt identity.
_IDENTITY_KEYS = ("attempt_id", "attempt")


class Refused(Exception):
    """The controller will not do this, and says why."""


@dataclass(frozen=True)
class Limits:
    """The bound on one capture. Exceeding it is a recorded capture failure and a
    `partial` coverage - never a silent truncation."""

    max_files: int = 1000
    max_file_bytes: int = 16 * 1024 * 1024
    max_total_bytes: int = 64 * 1024 * 1024
    max_stream_bytes: int = 8 * 1024 * 1024


@dataclass(frozen=True)
class Import:
    """A record a client or collector produced, offered for capture.

    `digest` is the digest its transport reported. Required: a record with no
    digest is refused, never imported (Coder Eval pitfall 4 warns and proceeds).
    """

    path: Path
    stream: str
    origin: str
    digest: str | None


# ------------------------------------------------------------------ helpers


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def canonical(value: object) -> bytes:
    """One byte form per JSON value, so equal configurations digest equally."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _write_new(path: Path, data: bytes, mode: int = FILE_MODE) -> None:
    """Write `path` once. Refuses to overwrite, and refuses to follow a symlink.

    The bytes go to a unique temporary name opened O_EXCL|O_NOFOLLOW, then are
    hard-linked into place: `link` fails when the name exists, so an existing
    record is never replaced, and a reader never sees a half-written one.
    """
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, mode)
        try:
            os.link(tmp, path)
        except FileExistsError:
            raise Refused(f"{path.name} already exists; the controller never overwrites a record")
    finally:
        tmp.unlink(missing_ok=True)


def _replace(path: Path, data: bytes) -> None:
    """Atomically replace `path` (the ledger, on an append-only revision only)."""
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(tmp, FILE_MODE)
    os.replace(tmp, path)


def _append(path: Path, entry: dict[str, object]) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")


def _dump(record: dict[str, object]) -> bytes:
    return (json.dumps(record, indent=1) + "\n").encode()


def _is_git_marker(marker: Path) -> bool:
    """A `.git` that git itself would recognize: a directory holding HEAD, or a
    worktree/submodule file pointing at one. A bare empty `.git` directory - which
    a shared /tmp can acquire - is a name, not a repository."""
    if marker.is_dir():
        return (marker / "HEAD").is_file()
    if marker.is_file():
        try:
            return marker.read_text(encoding="utf-8", errors="replace").startswith("gitdir:")
        except OSError:
            return False
    return False


def _inside_git_work_tree(path: Path) -> Path | None:
    """The work tree `path` sits in, found by walking up - no git binary needed."""
    for parent in [path, *path.parents]:
        if _is_git_marker(parent / ".git"):
            return parent
    return None


def _overlap(a: Path, b: Path) -> bool:
    a, b = a.resolve(), b.resolve()
    return a == b or a.is_relative_to(b) or b.is_relative_to(a)


# ------------------------------------------------------------------- the store


def open_store(path: Path, forbidden: list[Path]) -> Path:
    """Create or open controller-owned storage.

    Refused inside the subject's source, a host client home, or a git work tree:
    records never live in the subject's writable environment (records.md), and
    evidence inside a work tree is one `git add` from being published.
    """
    path = path.resolve()
    try:
        # The host's client homes are always forbidden; the caller adds the source.
        refuse_protected(path, [*forbidden_roots(None), *forbidden], "keep evidence")
    except NotOwned as exc:
        raise Refused(str(exc)) from None
    tree = _inside_git_work_tree(path)
    if tree is not None:
        raise Refused(
            f"refusing to keep evidence inside the git work tree {tree}: private evidence "
            f"is never one commit away from publication"
        )
    path.mkdir(parents=True, exist_ok=True, mode=DIR_MODE)
    marker = path / STORE_MARKER
    if not marker.exists():
        if any(path.iterdir()):
            raise Refused(f"{path} is not empty and is not a skillc store")
        _write_new(marker, _dump({"store": "skillc", "created": _now()}))
    os.chmod(path, DIR_MODE)
    return path


@dataclass
class Experiment:
    """One experiment: a bundle directory under the store, and its ledger."""

    root: Path
    ledger: dict[str, object]

    @property
    def id(self) -> str:
        return str(self.ledger["experiment_id"])

    def attempts(self) -> Iterator[tuple[dict[str, object], dict[str, object]]]:
        yield from _plan_pairs(self.ledger)

    def trial_of(self, attempt_id: str) -> dict[str, object]:
        for trial, attempt in self.attempts():
            if attempt.get("attempt_id") == attempt_id:
                return trial
        raise Refused(f"the ledger issued no attempt {attempt_id!r}")

    def object_path(self, digest: str) -> Path:
        return self.root / OBJECTS / digest.removeprefix("sha256:")

    def journal(self, attempt_id: str) -> Path:
        self.trial_of(attempt_id)
        return self.root / JOURNAL / f"{attempt_id}.jsonl"

    def events(self, attempt_id: str) -> list[dict[str, object]]:
        path = self.journal(attempt_id)
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]

    def record(self, attempt_id: str, event: str, **detail: object) -> None:
        if event not in records.LIFECYCLE_EVENTS and event not in _DETAIL_EVENTS:
            raise ValueError(f"unknown lifecycle event {event!r}")
        _append(self.journal(attempt_id), {"event": event, "at": _now(), **detail})

    @classmethod
    def open(cls, root: Path) -> Experiment:
        """Load an experiment, proving its ledger and configuration are unchanged.

        Every ledger revision is kept as an object and listed in the history; the
        current ledger must be the last revision, and each revision must only ADD
        attempts to the one before it. Every stored configuration must still hash
        to the digest the ledger bound.
        """
        root = root.resolve()
        path = root / LEDGER
        history_path = root / HISTORY
        history = [
            json.loads(line)["digest"]
            for line in history_path.read_text(encoding="utf-8").splitlines() if line
        ] if history_path.is_file() else []
        if not history:
            raise Refused(f"{root} holds no ledger history")
        if path.is_symlink():
            raise Refused(f"{root} ledger is a link")
        current = sha256_bytes(path.read_bytes()) if path.is_file() else None
        if current != history[-1]:
            # An interrupted commit: the newest revision is recorded but not in
            # place. Complete it ONLY when the file on disk is exactly the previous
            # recorded revision (or, for the first, absent); anything else is a
            # ledger nobody's history vouches for.
            prior = history[-2] if len(history) > 1 else None
            if current != prior:
                raise Refused("the ledger differs from its last recorded revision; it changed outside the controller")
            _replace(path, _read_object(root, history[-1]))
        data = path.read_bytes()
        previous: dict[str, object] | None = None
        for digest in history:
            blob = _read_object(root, digest)
            revision = json.loads(blob)
            if previous is not None:
                problem = _extension_problem(previous, revision)
                if problem:
                    raise Refused(f"ledger revision {digest} rewrote history: {problem}")
            previous = revision
        ledger = json.loads(data)
        for trial, _attempt in _plan_pairs(ledger):
            config = trial.get("config")
            digest = config.get("digest") if isinstance(config, dict) else None
            if not isinstance(digest, str):
                raise Refused(f"trial {trial.get('trial_id')!r} binds no configuration digest")
            _read_object(root, digest)
        return cls(root=root, ledger=ledger)


#: Journal entries that carry detail but are not lifecycle events in their own right.
_DETAIL_EVENTS = ("workspace",)


def _read_object(root: Path, digest: str) -> bytes:
    """An object's bytes, refused unless they still hash to their name."""
    path = root / OBJECTS / digest.removeprefix("sha256:")
    if path.is_symlink() or not path.is_file():
        raise Refused(f"object {digest} is missing")
    data = path.read_bytes()
    if sha256_bytes(data) != digest:
        raise Refused(f"object {digest} was modified after it was stored")
    return data


def _put_object(root: Path, data: bytes) -> str:
    digest = sha256_bytes(data)
    path = root / OBJECTS / digest.removeprefix("sha256:")
    if path.exists():
        _read_object(root, digest)  # an existing object must still be what its name says
    else:
        try:
            _write_new(path, data)
        except Refused:  # written concurrently by the same bytes
            _read_object(root, digest)
    return digest


def _plan_pairs(ledger: dict[str, object]) -> Iterator[tuple[dict[str, object], dict[str, object]]]:
    trials = ledger.get("trials")
    for trial in trials if isinstance(trials, list) else []:
        if isinstance(trial, dict):
            for attempt in trial.get("attempts") or []:
                if isinstance(attempt, dict):
                    yield trial, attempt


def _extension_problem(old: dict[str, object], new: dict[str, object]) -> str | None:
    """Why `new` is not `old` with attempts appended, or None when it is."""
    strip = {k: v for k, v in old.items() if k != "trials"}
    if strip != {k: v for k, v in new.items() if k != "trials"}:
        return "experiment fields changed"
    before, after = old.get("trials"), new.get("trials")
    if not isinstance(before, list) or not isinstance(after, list) or len(before) != len(after):
        return "the set of trials changed"
    for a, b in zip(before, after):
        if not isinstance(a, dict) or not isinstance(b, dict):
            return "a trial is not an object"
        if {k: v for k, v in a.items() if k != "attempts"} != {k: v for k, v in b.items() if k != "attempts"}:
            return f"trial {a.get('trial_id')!r} changed its identities or configuration"
        planned, now = a.get("attempts") or [], b.get("attempts") or []
        if now[: len(planned)] != planned:
            return f"trial {a.get('trial_id')!r} changed or removed a planned attempt"
    return None


# ------------------------------------------------------------------ planning


def _strict_identity(trial: dict[str, object], name: str, keys: tuple[str, ...]) -> dict[str, str]:
    value = trial.get(name)
    if not isinstance(value, dict):
        raise Refused(f"trial {trial.get('label')!r}: no {name} identity")
    unknown = set(value) - set(keys)
    if unknown:
        raise Refused(f"trial {trial.get('label')!r}: {name} carries unknown fields {sorted(unknown)}")
    for key in keys:
        if not isinstance(value.get(key), str) or not str(value[key]).strip():
            raise Refused(f"trial {trial.get('label')!r}: {name} identity has no {key}")
    return {k: str(value[k]) for k in keys}


def plan(spec: dict[str, object], store: Path) -> Experiment:
    """Create the expected population, before anything is dispatched.

    The plan names trials and how many attempts each gets; the CONTROLLER issues
    every identifier, so no subject or caller chooses the ID a later record will
    cite. The resolved configuration is stored as an object and the ledger binds
    its digest. Unknown fields and loose types are refused: `"attempts": true` is
    an integer to Python and would quietly plan one attempt.
    """
    if not (store / STORE_MARKER).is_file():
        raise Refused(f"{store} is not a skillc store; open it with open_store first")
    unknown = set(spec) - _PLAN_KEYS
    if unknown:
        raise Refused(f"plan carries unknown fields {sorted(unknown)}")
    label = spec.get("experiment")
    if not isinstance(label, str) or not _LABEL_RE.fullmatch(label):
        raise Refused(f"experiment label {label!r} is not {_LABEL_RE.pattern}")
    trials = spec.get("trials")
    if not isinstance(trials, list) or not trials:
        raise Refused("plan selects no trials; an empty selection is refused, not passed")

    experiment_id = f"{label}-{secrets.token_hex(4)}"
    root = store / experiment_id
    root.mkdir(mode=DIR_MODE)
    for sub in (OBJECTS, JOURNAL, SPOOL):
        (root / sub).mkdir(mode=DIR_MODE)

    planned: list[dict[str, object]] = []
    labels: set[str] = set()
    for index, trial in enumerate(trials):
        if not isinstance(trial, dict):
            raise Refused(f"trial {index} is not an object")
        unknown = set(trial) - _TRIAL_KEYS
        if unknown:
            raise Refused(f"trial {trial.get('label', index)!r} carries unknown fields {sorted(unknown)}")
        trial_label = trial.get("label")
        if not isinstance(trial_label, str) or not _LABEL_RE.fullmatch(trial_label):
            raise Refused(f"trial {index}: label {trial_label!r} is not {_LABEL_RE.pattern}")
        if trial_label in labels:
            raise Refused(f"trial label {trial_label!r} is planned twice")
        labels.add(trial_label)
        count = trial.get("attempts")
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise Refused(f"trial {trial_label!r}: attempts must be a positive integer, not {count!r}")
        config = trial.get("config")
        if not isinstance(config, dict):
            raise Refused(f"trial {trial_label!r}: no resolved configuration object")
        entry: dict[str, object] = {
            "trial_id": f"t{index + 1}-{trial_label}",
            **{name: _strict_identity(trial, name, keys) for name, keys in _IDENTITIES.items()},
            "config": {"digest": _put_object(root, canonical(config))},
            "attempts": [{"attempt_id": _new_attempt_id()} for _ in range(count)],
        }
        if "budget" in trial:
            if not isinstance(trial["budget"], dict):
                raise Refused(f"trial {trial_label!r}: budget is not an object")
            entry["budget"] = trial["budget"]
        planned.append(entry)

    ledger: dict[str, object] = {
        "version": 2,
        "kind": records.TRIAL_LEDGER,
        "producer": "controller",
        "experiment_id": experiment_id,
        "created": _now(),
        "trials": planned,
    }
    problems = [f.detail for f in checks.run_record(records.Record(root / LEDGER, ledger))]
    if problems:
        raise Refused(f"the planned ledger is not valid: {problems[0]}")
    _commit_ledger(root, ledger, first=True)
    experiment = Experiment(root=root, ledger=ledger)
    for _trial, attempt in experiment.attempts():
        experiment.record(str(attempt["attempt_id"]), "planned")
    return experiment


def _new_attempt_id() -> str:
    return f"a-{secrets.token_hex(6)}"


def _commit_ledger(root: Path, ledger: dict[str, object], first: bool = False) -> None:
    """Object, then history, then the ledger file. A crash after the history entry
    leaves a revision that is recorded and verifiable but not yet in place, which
    `Experiment.open` completes; the reverse order would leave a legitimate ledger
    that no history vouches for, indistinguishable from tampering."""
    data = _dump(ledger)
    digest = _put_object(root, data)
    _append(root / HISTORY, {"digest": digest, "at": _now()})
    if first:
        _write_new(root / LEDGER, data)
    else:
        _replace(root / LEDGER, data)


def retry(experiment: Experiment, attempt_id: str) -> str:
    """Plan a new attempt linked to `attempt_id`, erasing nothing.

    protocol.md: "A rerun gets a new ID and links to the original." The original
    must already be accounted for - retrying an attempt still in flight would give
    one trial two live accounts. The ledger gains an attempt and nothing else; the
    previous revision is kept, and `Experiment.open` refuses a revision that
    changed anything already planned.
    """
    trial = experiment.trial_of(attempt_id)
    if not (experiment.root / _lifecycle_name(attempt_id)).exists():
        raise Refused(f"attempt {attempt_id!r} is not finalized; retry an attempt only once it is accounted for")
    new_id = _new_attempt_id()
    ledger = json.loads(json.dumps(experiment.ledger))
    for candidate in ledger["trials"]:
        if candidate["trial_id"] == trial["trial_id"]:
            candidate["attempts"].append({"attempt_id": new_id, "retry_of": attempt_id})
    problem = _extension_problem(experiment.ledger, ledger)
    assert problem is None, problem
    _commit_ledger(experiment.root, ledger)
    experiment.ledger = ledger
    experiment.record(new_id, "planned", retry_of=attempt_id)
    return new_id


# ------------------------------------------------------------------ execution


def allocate_workspace(experiment: Experiment, attempt_id: str, base: Path, forbidden: list[Path]) -> Path:
    """A disposable, owned directory for the subject to work in.

    It may not overlap the store: the subject writes here, and nothing it writes
    may land among the records that judge it.
    """
    experiment.trial_of(attempt_id)
    store = experiment.root.parent
    if base.resolve().is_relative_to(store.resolve()):
        raise Refused("refusing a workspace inside the evidence store")
    try:
        root, nonce = create_root(base, [*forbidden, store.resolve()])
    except NotOwned as exc:
        raise Refused(str(exc)) from None
    experiment.record(attempt_id, "workspace", path=str(root), nonce=nonce)
    # The subject works one level down, so the ownership marker is not among the
    # files it writes and capture exports.
    work = root / "work"
    work.mkdir(mode=DIR_MODE)
    return work


def cleanup_workspace(experiment: Experiment, attempt_id: str) -> dict[str, object]:
    """Remove only the workspace this attempt was given. Safe to repeat."""
    owned = [e for e in experiment.events(attempt_id) if e.get("event") == "workspace"]
    if not owned:
        outcome: dict[str, object] = {"status": "not-needed", "errors": []}
    else:
        entry = owned[-1]
        outcome = remove_owned(Path(str(entry["path"])), str(entry["nonce"]))
    experiment.record(attempt_id, "cleaned", status=outcome["status"], failures=outcome["errors"])
    return outcome


def _dispatched(events: list[dict[str, object]]) -> bool:
    return any(e.get("event") == "dispatched" for e in events)


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _stop_group(proc: subprocess.Popen[bytes], grace: float) -> bool:
    """TERM, then KILL, the whole group; True once no member remains.

    The leader is reaped while waiting: an unreaped leader is a zombie, and a
    zombie still answers for its group, so the stop could never be confirmed.
    """
    pgid = proc.pid
    for sig, wait in ((signal.SIGTERM, grace), (signal.SIGKILL, grace)):
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            return True
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            proc.poll()
            if not _group_alive(pgid):
                return True
            time.sleep(0.02)
    proc.poll()
    return not _group_alive(pgid)


def run_attempt(
    experiment: Experiment,
    attempt_id: str,
    argv: list[str],
    cwd: Path,
    timeout: float,
    env: dict[str, str] | None = None,
    cancel: Callable[[], bool] | None = None,
    grace: float = 2.0,
) -> dict[str, object]:
    """Run the subject once and confirm it stopped.

    The subject runs in its own process group with its output spooled into
    controller storage. On the deadline or a cancellation the whole group is
    stopped; after a normal exit, leftover group members are stopped too - a
    leader that exits while a child keeps writing has not stopped. The stop is
    CONFIRMED only when no member of the group remains. The attempt's identity is
    never given to the subject: nothing it writes can claim it by knowing it.
    """
    events = experiment.events(attempt_id)
    if _dispatched(events):
        raise Refused(f"attempt {attempt_id!r} was already dispatched; a rerun is a retry with a new ID")
    if (experiment.root / _lifecycle_name(attempt_id)).exists():
        raise Refused(f"attempt {attempt_id!r} is already accounted for")
    experiment.record(attempt_id, "dispatched")
    spool = experiment.root / SPOOL
    out_path, err_path = spool / f"{attempt_id}.stdout", spool / f"{attempt_id}.stderr"
    stop: dict[str, object]
    with open(out_path, "xb") as out, open(err_path, "xb") as err:
        try:
            proc = subprocess.Popen(
                argv, cwd=cwd, env=env if env is not None else {"PATH": os.environ.get("PATH", os.defpath)},
                stdin=subprocess.DEVNULL, stdout=out, stderr=err, start_new_session=True,
            )
        except OSError as exc:
            stop = {"reason": "launch-failed", "confirmed": True, "exit_code": None, "error": str(exc)}
            experiment.record(attempt_id, "stopped", **stop)
            experiment.record(attempt_id, "stop-confirmed")
            return stop
        pgid = proc.pid
        try:
            experiment.record(attempt_id, "started", pid=proc.pid)
            deadline = time.monotonic() + timeout
            reason = "exited"
            while proc.poll() is None:
                if time.monotonic() >= deadline:
                    reason = "timeout"
                    break
                if cancel is not None and cancel():
                    reason = "operator-cancelled"
                    break
                time.sleep(0.02)
        except BaseException:
            # Whatever interrupted the controller - Ctrl-C, a raising cancel(), a
            # failed journal write - the subject must not outlive control. Stop and
            # reap the group, record what can be recorded, then re-raise.
            halted = _stop_group(proc, grace)
            try:
                proc.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                halted = False
            try:
                experiment.record(attempt_id, "stopped", reason="operator-cancelled",
                                  confirmed=halted, exit_code=proc.returncode)
                experiment.record(attempt_id, "stop-confirmed" if halted else "stop-unconfirmed")
            except OSError:
                pass
            raise
        if reason != "exited":
            experiment.record(attempt_id, "stop-requested", reason=reason)
        confirmed = _stop_group(proc, grace) if (reason != "exited" or _group_alive(pgid)) else True
        try:
            proc.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            confirmed = False
        stop = {"reason": reason, "confirmed": confirmed, "exit_code": proc.returncode}
    experiment.record(attempt_id, "stopped", **stop)
    experiment.record(attempt_id, "stop-confirmed" if confirmed else "stop-unconfirmed")
    return stop


# -------------------------------------------------------------------- capture


@dataclass
class _Capture:
    artifacts: list[dict[str, object]] = field(default_factory=list)
    exclusions: list[dict[str, str]] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    total: int = 0


def _secret_name(rel: str) -> str | None:
    parts = rel.split("/")
    for part in parts[:-1]:
        if part in SECRET_DIRS:
            return f"inside {part}/, which is never exported"
    for pattern in SECRET_NAMES:
        if fnmatch.fnmatchcase(parts[-1], pattern):
            return f"name matches {pattern!r}, which is never exported"
    return None


def _secret_content(data: bytes) -> str | None:
    for label, pattern in SECRET_CONTENT:
        if pattern.search(data):
            return f"content looks like a {label}; never exported"
    return None


def _in_scope(rel: str, include: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatchcase(rel, pattern) for pattern in include)


def _walk(root: Path) -> Iterator[tuple[str, os.stat_result]]:
    """Every entry under root, as (relative posix path, lstat). Never follows a link,
    and never descends into a directory in SECRET_DIRS (it is yielded, not entered)."""
    stack = [""]
    while stack:
        rel_dir = stack.pop()
        with os.scandir(root / rel_dir if rel_dir else root) as entries:
            for entry in sorted(entries, key=lambda e: e.name):
                rel = f"{rel_dir}/{entry.name}" if rel_dir else entry.name
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode) and entry.name not in SECRET_DIRS:
                    stack.append(rel)
                yield rel, info


def _read_bounded(path: Path, limit: int) -> bytes | None:
    """The file's bytes, or None when it exceeds `limit`. Refuses to follow a link."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise OSError("not a regular file")
        data = handle.read(limit + 1)
    return None if len(data) > limit else data


def _export(experiment: Experiment, output: Path, include: tuple[str, ...], limits: Limits) -> _Capture:
    got = _Capture()
    for rel, info in _walk(output):
        if stat.S_ISDIR(info.st_mode):
            if rel.split("/")[-1] in SECRET_DIRS:
                got.exclusions.append({"path": rel + "/", "reason": "a credential or VCS directory; never exported"})
            continue
        if not _in_scope(rel, include):
            continue
        if stat.S_ISLNK(info.st_mode):
            got.exclusions.append({"path": rel, "reason": "symlink; never followed out of the output root"})
            continue
        if not stat.S_ISREG(info.st_mode):
            got.exclusions.append({"path": rel, "reason": "not a regular file"})
            continue
        reason = _secret_name(rel)
        if reason:
            got.exclusions.append({"path": rel, "reason": reason})
            continue
        if len(got.artifacts) >= limits.max_files:
            got.failures.append(f"{rel}: not captured, the capture already holds {limits.max_files} files")
            continue
        try:
            data = _read_bounded(output / rel, limits.max_file_bytes)
        except OSError as exc:
            got.failures.append(f"{rel}: unreadable ({exc})")
            continue
        if data is None:
            got.failures.append(f"{rel}: larger than {limits.max_file_bytes} bytes; not captured")
            continue
        if got.total + len(data) > limits.max_total_bytes:
            got.failures.append(f"{rel}: not captured, the capture would exceed {limits.max_total_bytes} bytes")
            continue
        reason = _secret_content(data)
        if reason:
            got.exclusions.append({"path": rel, "reason": reason})
            continue
        got.total += len(data)
        got.artifacts.append({
            "path": rel, "type": "file", "size": len(data),
            "digest": _put_object(experiment.root, data),
            "mode": "x" if info.st_mode & stat.S_IXUSR else "-",
        })
    return got


def _stream(experiment: Experiment, attempt_id: str, path: Path, stream: str, origin: str,
            limits: Limits, failures: list[str]) -> dict[str, object]:
    total = path.stat().st_size
    with open(path, "rb") as handle:
        data = handle.read(limits.max_stream_bytes)
    coverage = "complete"
    if total > limits.max_stream_bytes:
        failures.append(f"{stream}: {total} bytes, truncated to {limits.max_stream_bytes}")
        coverage = "partial"
    return {
        "stream": stream, "origin": origin, "coverage": coverage, "attempt_id": attempt_id,
        "ref": f"{OBJECTS}/{sha256_bytes(data).removeprefix('sha256:')}",
        "digest": _put_object(experiment.root, data), "size": len(data),
    }


def _claimed_attempts(value: object) -> Iterator[str]:
    """Every attempt identity a JSON payload claims, top level or per JSONL line."""
    if isinstance(value, dict):
        for key in _IDENTITY_KEYS:
            if key in value:
                yield str(value[key])


def _import(experiment: Experiment, attempt_id: str, item: Import, failures: list[str]) -> dict[str, object] | None:
    """Bind a client/collector record to this attempt, or refuse it.

    Refused - recorded as a capture failure, never dropped and never trusted:
      - no transport digest, or bytes that do not match it (changed in transit);
      - a payload claiming a DIFFERENT attempt: a stale record from another run.
    An accepted record is an observation with its declared origin. A PASS inside
    it is still only something the client said.
    """
    shown = f"import {item.stream} ({item.path.name})"
    if item.origin not in records.OBSERVATION_ORIGINS:
        failures.append(f"{shown}: origin {item.origin!r} is not one of {list(records.OBSERVATION_ORIGINS)}")
        return None
    if not item.digest:
        failures.append(f"{shown}: refused, no transport digest; a record without one is never imported")
        return None
    try:
        data = _read_bounded(item.path, Limits().max_stream_bytes)
    except OSError as exc:
        failures.append(f"{shown}: unreadable ({exc})")
        return None
    if data is None or sha256_bytes(data) != item.digest:
        failures.append(f"{shown}: refused, its bytes do not match the reported digest {item.digest}")
        return None
    claims: set[str] = set()
    try:
        claims.update(_claimed_attempts(json.loads(data)))
    except ValueError:
        for line in data.splitlines():
            try:
                claims.update(_claimed_attempts(json.loads(line)))
            except ValueError:
                continue
    stale = sorted(claims - {attempt_id})
    if stale:
        failures.append(f"{shown}: refused, a stale record - it claims attempt {stale[0]!r}, not {attempt_id!r}")
        return None
    return {
        "stream": item.stream, "origin": item.origin, "coverage": "complete",
        "attempt_id": attempt_id, "ref": f"{OBJECTS}/{item.digest.removeprefix('sha256:')}",
        "digest": _put_object(experiment.root, data), "size": len(data),
    }


def capture(
    experiment: Experiment,
    attempt_id: str,
    output: Path | None = None,
    include: tuple[str, ...] = ("*",),
    imports: tuple[Import, ...] = (),
    limits: Limits | None = None,
) -> dict[str, object]:
    """Freeze what the subject left, after its stop was confirmed.

    Files are read without following links, copied into content-addressed objects
    and listed with path, type, size and digest. A symlink, a non-regular file, a
    secret by name or content, and anything outside `include` is not exported;
    each exclusion that was in scope is recorded with its reason. A breach of the
    bound is a capture failure and makes the capture partial - never a silent
    truncation. Returns the manifest, which is written once.
    """
    events = experiment.events(attempt_id)
    names = [e.get("event") for e in events]
    if "stop-confirmed" not in names:
        raise Refused(
            f"attempt {attempt_id!r} has no confirmed stop; capturing output that "
            f"could still be changing is not capture"
        )
    stop = next(e for e in reversed(events) if e.get("event") == "stopped")
    if stop.get("reason") in records.NOTHING_RAN:
        raise Refused(f"attempt {attempt_id!r} never ran ({stop.get('reason')}); there is nothing to capture")
    if "captured" in names or "capture-failed" in names:
        raise Refused(f"attempt {attempt_id!r} was already captured; a capture is frozen once")
    if (experiment.root / _lifecycle_name(attempt_id)).exists():
        raise Refused(f"attempt {attempt_id!r} is already finalized; its account is closed to capture")
    # The output is bound to THIS attempt: only its own allocated workspace, or a
    # directory inside it, may be captured under its identity. Another attempt's
    # workspace - possibly still running - would otherwise be frozen as this one's.
    owned = [e for e in events if e.get("event") == "workspace"]
    if not owned:
        raise Refused(f"attempt {attempt_id!r} was given no workspace; the controller captures only what it allocated")
    workspace = Path(str(owned[-1]["path"])) / "work"
    output = workspace if output is None else Path(output)
    if output.is_symlink() or not output.is_dir():
        experiment.record(attempt_id, "capture-failed", reason=f"output root {output} is not a directory")
        raise Refused(f"output root {output} is not a directory (or is a link)")
    if not output.resolve().is_relative_to(workspace.resolve()):
        raise Refused(f"output root {output} is not inside attempt {attempt_id!r}'s own workspace")
    if _overlap(output, experiment.root.parent):
        raise Refused("the output root overlaps the evidence store")

    limits = limits or Limits()
    got = _export(experiment, output, include, limits)
    spool = experiment.root / SPOOL
    observations = [
        _stream(experiment, attempt_id, spool / f"{attempt_id}.stdout", "client-events", "client-reported", limits, got.failures),
        _stream(experiment, attempt_id, spool / f"{attempt_id}.stderr", "client-stderr", "client-reported", limits, got.failures),
    ]
    for item in imports:
        bound = _import(experiment, attempt_id, item, got.failures)
        if bound is not None:
            observations.append(bound)
    journal = experiment.journal(attempt_id).read_bytes()
    observations.append({
        "stream": "process-lifecycle", "origin": "observed",
        "coverage": "complete" if stop.get("confirmed") else "partial",
        "attempt_id": attempt_id, "ref": f"{OBJECTS}/{sha256_bytes(journal).removeprefix('sha256:')}",
        "digest": _put_object(experiment.root, journal), "size": len(journal),
    })
    if not got.artifacts:
        reason = "no artifact within the declared export scope"
        experiment.record(attempt_id, "capture-failed", reason=reason, failures=got.failures)
        raise Refused(f"attempt {attempt_id!r}: {reason}; an empty capture is not a clean one")

    trial = experiment.trial_of(attempt_id)
    manifest: dict[str, object] = {
        "version": 2,
        "kind": records.ARTIFACT_MANIFEST,
        "producer": "controller",
        "attempt_id": attempt_id,
        "trial_id": trial["trial_id"],
        "captured": _now(),
        "artifacts": got.artifacts,
        "exclusions": got.exclusions,
        "observations": observations,
        "capture_failures": got.failures,
    }
    problems = [f.detail for f in checks.run_record(records.Record(Path("manifest"), manifest))]
    if problems:
        raise Refused(f"the manifest is not valid: {problems[0]}")
    _write_new(experiment.root / f"manifest-{attempt_id}.json", _dump(manifest))
    experiment.record(attempt_id, "captured", artifacts=len(got.artifacts), failures=len(got.failures))
    return manifest


def frozen_artifacts(experiment: Experiment, attempt_id: str) -> list[dict[str, object]]:
    """The captured artifacts of `attempt_id`, re-verified against their bytes.

    This is the gate between capture and grading (#9). Each object is re-hashed and
    its size re-checked, and the manifest must be the one this attempt's trial
    planned. A modified object, a manifest for another attempt or trial, or a
    missing one is refused: none of those can become a verified result.
    """
    path = experiment.root / f"manifest-{attempt_id}.json"
    if path.is_symlink() or not path.is_file():
        raise Refused(f"attempt {attempt_id!r} has no manifest")
    manifest = json.loads(path.read_bytes())
    trial = experiment.trial_of(attempt_id)
    if manifest.get("attempt_id") != attempt_id or manifest.get("trial_id") != trial["trial_id"]:
        raise Refused(
            f"manifest-{attempt_id}.json names attempt {manifest.get('attempt_id')!r} under "
            f"{manifest.get('trial_id')!r}; a stale or mismatched manifest"
        )
    problems = [f.detail for f in checks.run_record(records.Record(path, manifest))]
    if problems:
        raise Refused(f"manifest-{attempt_id}.json is not valid: {problems[0]}")
    frozen = []
    for artifact in manifest["artifacts"]:
        digest = str(artifact.get("digest"))
        data = _read_object(experiment.root, digest)
        if len(data) != artifact.get("size"):
            raise Refused(f"artifact {artifact.get('path')!r} is {len(data)} bytes, not {artifact.get('size')}")
        frozen.append({**artifact, "object": str(experiment.object_path(digest))})
    return frozen


# ---------------------------------------------------------------- accounting


def _lifecycle_name(attempt_id: str) -> str:
    return f"lifecycle-{attempt_id}.json"


def finalize(
    experiment: Experiment,
    attempt_id: str,
    disposition: str | None = None,
    reason: str | None = None,
) -> dict[str, object]:
    """Write this attempt's `attempt-lifecycle` record, derived from its journal.

    The disposition is DERIVED: never dispatched is `not-run`; failed to launch is
    `unavailable`; an unconfirmed stop, or a capture that failed or never
    happened, is `inconclusive`; a completed capture is `captured`. A caller may
    downgrade to `unavailable` or `inconclusive` with a reason (a provider found
    unreachable, an operator ruling), but never declare `captured` and never
    downgrade an attempt whose bytes were captured - that capture may already have
    been graded, and the two accounts would disagree.
    """
    name = experiment.root / _lifecycle_name(attempt_id)
    if name.exists():
        raise Refused(f"attempt {attempt_id!r} is already finalized")
    events = experiment.events(attempt_id)
    names = [e.get("event") for e in events]
    stops = [e for e in events if e.get("event") == "stopped"]
    stop_event = stops[-1] if stops else None

    derived: str
    why: str | None
    if not _dispatched(events):
        derived, why = "not-run", reason or "not dispatched before the experiment was closed"
        stop: dict[str, object] = {"reason": "never-started", "confirmed": True}
        experiment.record(attempt_id, "not-run", reason=why)
    else:
        if stop_event is None:
            stop = {"reason": "unobserved", "confirmed": False}
            experiment.record(attempt_id, "stop-unconfirmed", reason="no stop was observed")
        else:
            stop = {k: stop_event[k] for k in ("reason", "confirmed", "exit_code") if k in stop_event}
        if stop.get("reason") == "launch-failed":
            derived, why = "unavailable", f"the subject could not be launched: {stop_event and stop_event.get('error')}"
            experiment.record(attempt_id, "unavailable", reason=why)
        elif stop.get("confirmed") is not True:
            derived, why = "inconclusive", "the stop was never confirmed, so no output could be captured"
        elif "captured" in names:
            derived, why = "captured", None
        elif "capture-failed" in names:
            failed = next(e for e in reversed(events) if e.get("event") == "capture-failed")
            derived, why = "inconclusive", f"capture failed: {failed.get('reason')}"
        else:
            derived, why = "inconclusive", "the attempt stopped but was never captured"
    if disposition is not None:
        if disposition not in ("unavailable", "inconclusive"):
            raise Refused(f"a caller may declare unavailable or inconclusive, not {disposition!r}")
        if derived == "captured":
            raise Refused(f"attempt {attempt_id!r} was captured; its disposition is not the caller's to change")
        if not reason:
            raise Refused(f"declaring {disposition} needs a reason")
        derived, why = disposition, reason
        if disposition == "unavailable" and "unavailable" not in names:
            experiment.record(attempt_id, "unavailable", reason=reason)

    cleaned = [e for e in events if e.get("event") == "cleaned"]
    workspace = any(e.get("event") == "workspace" for e in events)
    cleanup = (
        {"status": cleaned[-1].get("status"), "failures": cleaned[-1].get("failures", [])}
        if cleaned else
        {"status": "not-needed" if not workspace else "partial",
         "failures": [] if not workspace else ["the workspace was never cleaned up"]}
    )
    lifecycle_events = [
        {"event": e["event"], "at": e["at"]}
        for e in experiment.events(attempt_id) if e.get("event") in records.LIFECYCLE_EVENTS
    ]
    record: dict[str, object] = {
        "version": 2,
        "kind": records.ATTEMPT_LIFECYCLE,
        "producer": "controller",
        "attempt_id": attempt_id,
        "trial_id": experiment.trial_of(attempt_id)["trial_id"],
        "disposition": derived,
        "stop": stop,
        "events": lifecycle_events,
        "cleanup": cleanup,
    }
    if why is not None:
        record["reason"] = why
    problems = [f.detail for f in checks.run_record(records.Record(name, record))]
    if problems:
        raise Refused(f"the lifecycle record is not valid: {problems[0]}")
    _write_new(name, _dump(record))
    return record


def close(experiment: Experiment, reason: str = "not dispatched before the experiment was closed") -> dict[str, object]:
    """Finalize every planned attempt that is not yet accounted for.

    This is what makes "never silently drop an attempt" true: an attempt nobody
    dispatched becomes `not-run` with a reason, rather than simply being absent.
    """
    for _trial, attempt in list(experiment.attempts()):
        attempt_id = str(attempt["attempt_id"])
        if not (experiment.root / _lifecycle_name(attempt_id)).exists():
            finalize(experiment, attempt_id, reason=reason if not _dispatched(experiment.events(attempt_id)) else None)
    return account(experiment)


def account(experiment: Experiment) -> dict[str, object]:
    """The declared population and what became of each attempt.

    protocol.md section 7 starts every report with the population. An attempt with
    no lifecycle yet is `open`, never omitted.
    """
    counts: dict[str, int] = {d: 0 for d in (*records.DISPOSITIONS, "open")}
    rows = []
    for trial, attempt in experiment.attempts():
        attempt_id = str(attempt["attempt_id"])
        path = experiment.root / _lifecycle_name(attempt_id)
        state = json.loads(path.read_bytes())["disposition"] if path.exists() else "open"
        counts[state] += 1
        rows.append({"trial_id": trial["trial_id"], "attempt_id": attempt_id, "state": state,
                     **({"retry_of": attempt["retry_of"]} if "retry_of" in attempt else {})})
    return {"experiment_id": experiment.id, "population": len(rows), "counts": counts, "attempts": rows}


# ------------------------------------------------------ records from other producers


def add_receipt(experiment: Experiment, receipt: dict[str, object]) -> Path:
    """Store an installation receipt (#7's producer) for a planned attempt, once."""
    return _add(experiment, receipt, records.INSTALLATION_RECEIPT, f"receipt-{receipt.get('attempt_id')}.json")


def add_result(experiment: Experiment, result: dict[str, object]) -> Path:
    """Store a verified result, never replacing one.

    A result that grades bytes must grade bytes that are STILL what was captured:
    `frozen_artifacts` re-hashes them first, so a modified artifact cannot become a
    verified result. A regrade must link to a result already stored, which is
    retained - regrading adds, it never erases (protocol.md).
    """
    attempt_id = str(result.get("attempt_id"))
    if result.get("run_state") not in records.DECLARABLE_RUN_STATES:
        lifecycle = experiment.root / _lifecycle_name(attempt_id)
        if not lifecycle.exists() or json.loads(lifecycle.read_bytes()).get("disposition") != "captured":
            raise Refused(f"attempt {attempt_id!r} is not a finalized capture; nothing else can be graded")
        have = {a["digest"] for a in frozen_artifacts(experiment, attempt_id)}
        graded = result.get("graded_digests")
        missing = [d for d in graded if d not in have] if isinstance(graded, list) else ["(none)"]
        if missing:
            raise Refused(f"result grades {missing[0]!r}, which this attempt's capture does not hold")
    original = result.get("regrade_of")
    if original is not None and not (experiment.root / f"result-{original}.json").exists():
        raise Refused(f"regrade of {original!r}, which is not retained; a regrade never replaces its original")
    return _add(experiment, result, records.VERIFIED_RESULT, f"result-{result.get('result_id')}.json")


def _add(experiment: Experiment, record: dict[str, object], kind: str, filename: str) -> Path:
    if record.get("kind") != kind:
        raise Refused(f"expected a {kind}, got {record.get('kind')!r}")
    attempt_id = str(record.get("attempt_id"))
    trial = experiment.trial_of(attempt_id)
    if record.get("trial_id") != trial["trial_id"]:
        raise Refused(f"{kind} names trial {record.get('trial_id')!r}, but {attempt_id!r} belongs to {trial['trial_id']!r}")
    path = experiment.root / filename
    problems = [f.detail for f in checks.run_record(records.Record(path, record))]
    if problems:
        raise Refused(f"{kind} is not valid: {problems[0]}")
    # Consistency with what is already stored. Only the contradictions the
    # CANDIDATE introduces count: an experiment still in progress is incomplete
    # (attempts owed a result), and that is not this record's doing.
    existing = records.bundle_at(experiment.root)
    before = list(existing.records) if existing is not None else []
    after = records.Bundle(experiment.root, [*before, records.Record(path, record)])
    rules = (records.ledger_binding, records.unique_ids, records.lineage)
    old = {d for rule in rules for d in rule(records.Bundle(experiment.root, before))}
    new = [d for rule in rules for d in rule(after) if d not in old]
    if new:
        raise Refused(f"{kind} contradicts the stored evidence: {new[0]}")
    _write_new(path, _dump(record))
    return path
