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
from . import fixture_overlay as fo
from . import fixture_service as fs
from . import git_snapshot as gs
from .decide_reply_channel import ChannelRefusal
from .exec_git_remote import ExecGitRemote

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


class _FixtureBackend(Protocol):
    @property
    def witness_io(self) -> bool: ...

    def export(self, handle: object, dest: Path, root: str | None = None) -> None: ...

    def trigger_log(self, handle: object) -> object: ...


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
    _finishing: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        self.guard = cg.CodexGuardSession(self.attempt_id)

    def routes(self) -> dict[str, tuple[Callable[[Mapping[str, object]], Mapping[str, object]], frozenset[str]]]:
        return {"gh": (self._gh, fs.REQUEST_KEYS), "codex_guard": (self._guard, cg.REQUEST_KEYS)}

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
            remote = ExecGitRemote(backend, handle, git_dir=self.fixture.git_dir)
            service = fs.FixtureService(self.fixture.declaration, remote, self.attempt_id)
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
        channel_ok = True
        try:
            channel_ok = backend.trigger_log(handle) is not None
        except Exception:  # noqa: BLE001 - a failed drain is an unhealthy channel, never a clean one
            channel_ok = False
        if not channel_ok:
            self.guard.channel_unavailable = True
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
        self.guard.finalize()

    def guard_record(self) -> dict[str, Any]:
        return cg.summarize(self.attempt_id, list(self.guard.decisions), self.guard.channel_unavailable)

    def extras(self, final_report: str | None) -> dict[str, object]:
        return {"case": self.fixture.case, "service": self.record, "git": self.git,
                "git_unreadable": self.git_unreadable, "final_report": final_report,
                "codex_guard": self.guard_record()}


class _UnreadableRemote:
    """The finalize-time remote when the exported remote cannot be read: every
    answer raises, so the service records its integrity as UNKNOWN."""

    def __init__(self, reason: str) -> None:
        self.reason = reason

    def resolve(self, ref: str) -> str | None:
        raise gs.Unreadable(self.reason)

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        raise gs.Unreadable(self.reason)
