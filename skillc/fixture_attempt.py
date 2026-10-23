"""One live attempt against a fixture-service task (#434 PR 2b): what
`agent_trial.run_one_attempt(fixture=...)` composes onto the attempt's one
trigger socket, installs before the agent starts, and reads after it stops.

The task supplies an `AttemptFixture`: its case label, the fixture-service
declaration, the controller-held build facts, and a `capture` function that
reads the post-stop git state from an EXPORTED copy (`capture_snapshot` for
flow-auto-necessity). The fixture's repository and remote are delivered as
the attempt's ordinary surface, so they live inside the container.

WHERE EVERY GIT CALL RUNS (#434's hard item):

- before the attempt exists: the task's builder, host git, in a
  controller-owned directory. Nothing is subject-writable yet;
- DURING the attempt: the service's decisions, through `ExecGitRemote`,
  inside the container as the candidate;
- AFTER the agent stops: no git process at all. `git_snapshot` reads the
  exported bytes, both for the service's finalize-time divergence check
  (`SnapshotGitRemote`) and for the task's capture.

`FixtureSession.routes()` gives `fixture_service.dispatch` its `gh` and
`codex_guard` routes. A request before `bind()` finished, or after `finish()`
started, is refused. A channel that failed at any point marks the service and
the guard record channel-unavailable, so neither can read as complete.

`extras()` is the controller-held evidence the judge reads beside the gate
witness (`verify`'s `trusted_extras`): `case`, `service`, `git`,
`final_report` and `codex_guard`. A capture that cannot be read faithfully is
`git: None`, which the judge reads as UNKNOWN, never as clean.

Stdlib only (AGENTS.md).
"""

from __future__ import annotations

import tempfile
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from . import codex_guard as cg
from . import credential_steward as cs
from . import fixture_overlay as fo
from . import fixture_service as fs
from . import git_snapshot as gs
from . import source_digest as sd
from .decide_reply_channel import ChannelRefusal
from .exec_git_remote import ExecGitRemote
from .ordering import Order

FLOW_AUTO_GATE_SHIM = Path(__file__).resolve().parent.parent / "docker" / "fixture-service" / "flow-auto-gate-shim.py"


@dataclass(frozen=True)
class AttemptFixture:
    """A fixture-service task's per-attempt facts, all controller-held.

    `capture(export_root, facts)` reads the post-stop git state from the
    exported `/work`; it raises `git_snapshot.Unreadable` when it cannot.
    `gates` maps each declared gate name to the argv that follows the real
    helper's harness path; `gate_shim_source` is the shim placed at the
    subject's gate entrypoint."""

    case: str
    declaration: Mapping[str, Any]
    facts: Mapping[str, Any]
    capture: Callable[[Path, Mapping[str, Any]], dict[str, Any]]
    git_dir: str = "/work/.remote/widget.git"
    remote_relpath: str = ".remote/widget.git"
    gates: Mapping[str, Sequence[str]] = field(default_factory=lambda: {"flow-auto-finish": ()})
    gate_shim_source: Path = FLOW_AUTO_GATE_SHIM
    #: #279 PR-3: an optional controller step over the capture, given the
    #: attempt's backend and handle (the Step-6 task runs its behavioural
    #: oracle in a throwaway container of the attempt's measured image here).
    #: None leaves the capture exactly as before.
    post_capture: Callable[[dict[str, Any], Any, object], dict[str, Any]] | None = None
    #: #530: opt in to `gate_launch_evidence` in the trusted extras (the
    #: flow-check-route task's `report-honest`). Off keeps every earlier
    #: fixture's record byte-identical.
    launch_evidence: bool = False


class _FixtureBackend(Protocol):
    @property
    def witness_io(self) -> bool: ...

    def export(self, handle: object, dest: Path, root: str | None = None) -> None: ...

    def trigger_log(self, handle: object) -> object: ...

    def trigger_dropped(self, handle: object) -> int | None: ...

    # #518: the credential steward's root primitives.
    def start_root_daemon_in_attempt(self, handle: object, argv: Sequence[str],
                                     timeout: float | None = None) -> bool: ...

    def root_output_in_attempt(self, handle: object, argv: Sequence[str], timeout: float | None = None,
                               max_bytes: int = ...) -> bytes | None: ...


@dataclass
class FixtureSession:
    """One attempt's fixture service and guard record, controller-owned."""

    fixture: AttemptFixture
    attempt_id: str
    service: fs.FixtureService | None = None
    guard: cg.CodexGuardSession = field(init=False)
    overlays: dict[str, object] = field(default_factory=dict)
    record: dict[str, Any] | None = None
    git: dict[str, Any] | None = None
    git_unreadable: str | None = None
    failure: str | None = None
    #: #279: the first turn plus each delivered controller turn; the guard's
    #: nested verdict is judged against it. Set by `run_one_attempt`.
    expected_top_level: int = 1
    #: #279: the declaration's nested-codex policy (`codex_guard.NESTED_POLICIES`),
    #: or None; recorded beside the counts only when declared.
    nested_policy: str | None = None
    #: #279 PR-2a: the attempt's ordering counter (a multi-turn attempt only),
    #: given to the fixture service; with it, the git record gains the SOURCE
    #: digest of every remote ref head and the extras the controller turns.
    order: Order | None = None
    turn_records: list[dict[str, Any]] | None = None
    #: #518: the credential steward's record and driver.
    steward: cs.CredentialStewardSession = field(init=False)
    steward_driver: cs.CredentialSteward | None = None
    _steward_record: dict[str, Any] | None = None
    _finishing: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        self.guard = cg.CodexGuardSession(self.attempt_id)
        self.steward = cs.CredentialStewardSession(self.attempt_id)

    def routes(self) -> dict[str, tuple[Callable[[Mapping[str, object]], Mapping[str, object]], frozenset[str]]]:
        return {"gh": (self._gh, fs.REQUEST_KEYS), "codex_guard": (self._guard, cg.REQUEST_KEYS),
                "credential_steward": (self.steward.decide, cs.REQUEST_KEYS)}

    def watch(self, decide: Callable[[Mapping[str, object]], Mapping[str, object]]
              ) -> Callable[[Mapping[str, object]], Mapping[str, object]]:
        """The attempt's composed `decide`, with one addition: a `codex_guard`
        request refused anywhere, `dispatch`'s own key check included, marks
        the guard record unhealthy. A refused guard line is a decision the
        record never holds, so the count must read unknown, never zero."""
        def watched(request: Mapping[str, object]) -> Mapping[str, object]:
            try:
                return decide(request)
            except ChannelRefusal:
                if request.get("op") == "codex_guard":
                    self.guard.channel_unavailable = True
                elif request.get("op") == "credential_steward":
                    self.steward.channel_unavailable = True
                raise
        return watched

    def _gh(self, request: Mapping[str, object]) -> Mapping[str, object]:
        with self._lock:
            service = None if self._finishing else self.service
        if service is None:
            raise ChannelRefusal("gh: the fixture service is not accepting requests")
        return service.decide(request)

    def _guard(self, request: Mapping[str, object]) -> Mapping[str, object]:
        return self.guard.decide(request)

    def bind(self, backend: Any, handle: object, environment: Mapping[str, str]) -> None:
        """Place the overlays, then start the service over the in-attempt
        remote. Before the agent starts; any failure refuses the attempt."""
        try:
            self.overlays["gh"] = fo.install_gh_shim(backend, handle, environment).__dict__
            self.overlays["codex_guard"] = fo.install_codex_guard(backend, handle, environment)
            self.steward_driver = cs.start_for(self.steward, backend, handle)  # #518
            remote = ExecGitRemote(backend, handle, git_dir=self.fixture.git_dir)
            service = fs.FixtureService(self.fixture.declaration, remote, self.attempt_id, order=self.order,
                                        ship_stamper=(lambda commit: _ship_stamp(backend, handle, self.fixture.remote_relpath,
                                                                                 commit))
                                        if self.order is not None else None)
        except Exception as exc:
            self.failure = f"fixture binding failed: {type(exc).__name__}: {exc}"
            raise
        with self._lock:
            self.service = service

    def finish(self, backend: _FixtureBackend, handle: object) -> None:
        """After the agent stops: finalize the service against a snapshot of
        the exported remote, capture the git state, close the guard record."""
        with self._lock:
            if self._finishing:
                return
            self._finishing = True
            service = self.service
        if self.steward_driver is not None:
            self.steward_driver.stop(backend, handle)  # while the channel still listens
        channel_ok = True
        try:
            channel_ok = backend.trigger_log(handle) is not None
        except Exception:  # noqa: BLE001 - a failed drain is an unhealthy channel, never a clean one
            channel_ok = False
        try:
            dropped = backend.trigger_dropped(handle)
        except Exception:  # noqa: BLE001 - an unreadable count is incomplete coverage
            dropped = None
        if dropped is None or dropped > 0:
            # A connection closed before any route saw it may have been a guard
            # line (counter-model review, pass 2): the count cannot be zero.
            self.guard.channel_unavailable = True
            self.steward.channel_unavailable = True
        if not channel_ok:
            self.guard.channel_unavailable = True
            self.steward.channel_unavailable = True
            if service is not None:
                service.channel_unavailable = True
        with tempfile.TemporaryDirectory(prefix="skillc-fixture-export-") as directory:
            export_root = Path(directory) / "work"
            try:
                backend.export(handle, export_root)
            except Exception as exc:  # noqa: BLE001 - recorded as unreadable below
                self.git_unreadable = f"the attempt's workspace could not be exported: {exc}"
            if service is not None:
                try:
                    snapshot = gs.SnapshotGitRemote(gs.SafeTree(export_root), self.fixture.remote_relpath)
                    self.record = service.finalize(self.attempt_id, remote=snapshot).to_json()
                except gs.Unreadable as exc:
                    self.record = service.finalize(self.attempt_id, remote=_UnreadableRemote(str(exc))).to_json()
            if self.git_unreadable is None:
                try:
                    self.git = self.fixture.capture(export_root, self.fixture.facts)
                except gs.Unreadable as exc:
                    self.git_unreadable = str(exc)
                if self.git is not None and self.fixture.post_capture is not None:
                    self.git = self.fixture.post_capture(self.git, backend, handle)
            if self.order is not None and self.git is not None:
                self.git["remote_ref_sources"] = _remote_ref_sources(export_root, self.fixture.remote_relpath,
                                                                     self.git.get("remote_refs"))
        self.guard.finalize()

    def steward_record(self) -> dict[str, Any]:
        if self._steward_record is None:
            self._steward_record = cs.record_of(self.steward, self.steward_driver)
        return self._steward_record

    def guard_record(self) -> dict[str, Any]:
        return cg.summarize(self.attempt_id, list(self.guard.decisions), self.guard.channel_unavailable,
                            expected_top_level=self.expected_top_level, nested_policy=self.nested_policy)

    def extras(self, final_report: str | None) -> dict[str, object]:
        extras: dict[str, object] = {
            "case": self.fixture.case, "service": self.record, "git": self.git,
            "git_unreadable": self.git_unreadable, "final_report": final_report,
            "codex_guard": self.guard_record(), "credential_steward": self.steward_record()}
        if self.order is not None:
            # #279 PR-2a: the turns as the controller recorded them, ordered.
            extras["controller_turns"] = list(self.turn_records or [])
        return extras


class _UnreadableRemote:
    """The finalize-time remote when the exported remote cannot be read: every
    answer raises, so the service records its integrity as UNKNOWN."""

    def __init__(self, reason: str) -> None:
        self.reason = reason

    def resolve(self, ref: str) -> str | None:
        raise gs.Unreadable(self.reason)

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        raise gs.Unreadable(self.reason)


def _ship_stamp(backend: Any, handle: object, remote_relpath: str, commit: str) -> dict[str, object]:
    """#279 PR-2b: the source and gate-definition digests of `commit`, read AT a
    ship request from a fresh controller-owned export of the attempt's remote -
    the same no-git-process reader `remote_ref_sources` uses after the stop."""
    with tempfile.TemporaryDirectory(prefix="skillc-ship-stamp-") as directory:
        export_root = Path(directory) / "work"
        backend.export(handle, export_root)
        return sd.ship_stamp(gs.GitDir(gs.SafeTree(export_root), remote_relpath), commit)


def _remote_ref_sources(export_root: Path, remote_relpath: str, refs: object) -> dict[str, str]:
    """#279 PR-2a: the SOURCE digest (`source_digest`) of the commit every
    remote ref names - what a pushed branch or a merged main actually ships -
    read from the exported remote with no git process. A ref that cannot be
    read is `unreadable: ...`, which never matches a gated tree."""
    out: dict[str, str] = {}
    if not isinstance(refs, Mapping):
        return out
    try:
        bare = gs.GitDir(gs.SafeTree(export_root), remote_relpath)
    except gs.Unreadable as exc:
        return {str(ref): f"unreadable: {exc}" for ref in refs}
    for ref, sha in sorted(refs.items()):
        try:
            out[str(ref)] = sd.digest_commit(bare, str(sha))
        except (gs.Unreadable, sd.SourceUnreadable, ValueError) as exc:
            out[str(ref)] = f"unreadable: {exc}"
    return out
