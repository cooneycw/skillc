"""The controller's record of the credential steward (#518 A).

`docker/fixture-service/skillc-credential-steward.py` runs inside the attempt,
AS ROOT, and withdraws the agent's codex credential from its home once the
controller's own client has read it, so a nested client the agent launches
finds nothing to authenticate with. It sends each event here over the
attempt's one trigger socket as one `credential_steward` request; this
session keeps them, in the controller, where nothing in the container can
edit them.

THE RECORD FAILS CLOSED. `status` is:
- `held`: a healthy channel; one `armed` per launch the controller made
  (`expected_arms`: turn 1 plus each delivered resume); every arm followed by
  a quiet-period `withdrawn`; no re-creation, no error; and a final
  `stopped`, proving the steward watched to the end;
- `refreshed`: the credential re-appeared while withdrawn and was captured.
  During that gap a nested client could have read it, so the attempt is never
  credited and the schedule stops;
- `unknown`: anything else - a withdrawal only at the deadline (the client
  was never seen to load it), a missing arm or stop, an error, an unhealthy
  channel. Never read as `held`.

RESIDUAL (orchestrator A3): the agent shares the client's uid, so this is
ADR 0007's hygiene boundary against an instructed or accidental nested
launch, never a security boundary against a hostile agent.

Stdlib only (AGENTS.md).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .decide_reply_channel import ChannelRefusal

EVENTS = ("armed", "withdrawn", "withdrawn-at-deadline", "refreshed-captured", "stopped", "error")
REQUEST_KEYS = frozenset({"op", "event", "seq", "opens", "closes"})
MAX_EVENTS = 200
#: Where the steward is placed and its working paths (in the container).
STEWARD_PATH = "/opt/skillc-harness/credential-steward.py"
VAULT = "/opt/skillc-vault"
PIDFILE = "/run/skillc/credential-steward.pid"
#: Measured on codex-cli 0.157.1 (#518 A): the worst gap between the client's
#: auth.json reads was 1.33 s; 3 s withdraws after all four.
QUIET_MS = 3000
DEADLINE_S = 30


def _count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


@dataclass
class CredentialStewardSession:
    """One attempt's steward record, decided and recorded before each reply."""

    attempt_id: str
    events: list[dict[str, Any]] = field(default_factory=list)
    channel_unavailable: bool = False
    finalized: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def decide(self, request: Mapping[str, object]) -> Mapping[str, object]:
        with self._lock:
            problem = self._problem(request)
            if problem is not None:
                self.channel_unavailable = True
                raise ChannelRefusal(f"credential_steward: {problem}")
            self.events.append({"seq": request["seq"], "event": request["event"],
                                "opens": request["opens"], "closes": request["closes"]})
            return {"recorded": len(self.events)}

    def _problem(self, request: Mapping[str, object]) -> str | None:
        if self.finalized:
            return "the record is finalized"
        if set(request) != REQUEST_KEYS or request.get("op") != "credential_steward":
            return f"fields must be exactly {sorted(REQUEST_KEYS)}"
        if request.get("event") not in EVENTS:
            return f"unknown event {request.get('event')!r}"
        if not all(_count(request.get(k)) for k in ("seq", "opens", "closes")):
            return "seq, opens and closes must be non-negative integers"
        if self.events and int(request["seq"]) <= int(self.events[-1]["seq"]):  # type: ignore[call-overload]
            return "seq did not increase"
        if len(self.events) >= MAX_EVENTS:
            return f"more than {MAX_EVENTS} events"
        return None

    def finalize(self, expected_arms: int) -> dict[str, Any]:
        with self._lock:
            self.finalized = True
            return summarize(list(self.events), self.channel_unavailable, expected_arms)


def summarize(events: list[dict[str, Any]], channel_unavailable: bool, expected_arms: int) -> dict[str, Any]:
    names = [str(e["event"]) for e in events]
    arms = names.count("armed")
    refreshed = names.count("refreshed-captured")
    # Each arm must be followed by a quiet-period withdrawal before the next arm.
    every_arm_withdrawn = True
    pending = False
    for name in names:
        if name == "armed":
            if pending:
                every_arm_withdrawn = False
            pending = True
        elif name == "withdrawn":
            pending = False
        elif name == "withdrawn-at-deadline":
            every_arm_withdrawn = False
            pending = False
    if pending:
        every_arm_withdrawn = False
    if refreshed:
        status = "refreshed"
    elif (not channel_unavailable and arms == expected_arms and every_arm_withdrawn
          and "error" not in names and names[-1:] == ["stopped"]):
        status = "held"
    else:
        status = "unknown"
    return {"status": status, "arms": arms, "expected_arms": expected_arms,
            "withdrawn": names.count("withdrawn"), "withdrawn_at_deadline": names.count("withdrawn-at-deadline"),
            "refreshed_captured": refreshed, "errors": names.count("error"),
            "stopped": names[-1:] == ["stopped"], "channel_unavailable": channel_unavailable}


def credit_block(record: Mapping[str, Any] | None) -> str | None:
    """Why the attempt cannot be credited, or None when the credential was held."""
    if not isinstance(record, Mapping):
        return "not credited: the credential steward record is absent"
    if record.get("status") == "held":
        return None
    if record.get("status") == "refreshed":
        return "not credited: the codex credential re-appeared in the agent's home mid-attempt"
    return (f"not credited: the credential steward record is unknown (arms {record.get('arms')}/"
            f"{record.get('expected_arms')}, at-deadline {record.get('withdrawn_at_deadline')}, "
            f"stopped {record.get('stopped')}, channel unavailable {record.get('channel_unavailable')})")


def stop_reason(record: Mapping[str, Any] | None) -> str | None:
    """Why the schedule stops, or None. Every non-`held` record stops it."""
    block = credit_block(record)
    return block.removeprefix("not credited: ") if block else None


# ------------------------------------------------------------- the driver

STEWARD_SOURCE = Path(__file__).resolve().parent.parent / "docker" / "fixture-service" / "skillc-credential-steward.py"
CANDIDATE = "candidate"


class StewardBackend(Protocol):
    def start_root_daemon_in_attempt(self, handle: object, argv: Sequence[str],
                                     timeout: float | None = None) -> bool: ...

    def root_output_in_attempt(self, handle: object, argv: Sequence[str], timeout: float | None = None,
                               max_bytes: int = ...) -> bytes | None: ...


class StewardFailed(Exception):
    """The steward could not be placed, started, re-armed or restored."""


@dataclass
class CredentialSteward:
    """Drives one attempt's steward and holds its record. Each step is
    confirmed by the steward's OWN event over the trigger socket, never by a
    docker return code."""

    session: CredentialStewardSession
    home_codex: str
    auth_relpath: str = "auth.json"
    wait_s: float = 10.0
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    failure: str | None = None
    arms_requested: int = 0

    def _await(self, event: str, after: int) -> bool:
        deadline = self.clock() + self.wait_s
        while self.clock() < deadline:
            if any(e["event"] == event for e in self.session.events[after:]):
                return True
            self.sleep(0.05)
        return False

    def start(self, backend: StewardBackend, handle: object, place: Callable[[bytes], None]) -> None:
        """Place the steward root-owned (via `place`, the overlay's verified
        placement) and start it; confirmed by its `armed` event."""
        place(STEWARD_SOURCE.read_bytes())
        before = len(self.session.events)
        argv = ["python3", "-IS", STEWARD_PATH, "--home-codex", self.home_codex, "--vault", VAULT,
                "--pidfile", PIDFILE, "--quiet-ms", str(QUIET_MS), "--deadline-s", str(DEADLINE_S)]
        if not backend.start_root_daemon_in_attempt(handle, argv):
            raise StewardFailed("the credential steward could not be started")
        self.arms_requested += 1
        if not self._await("armed", before):
            raise StewardFailed("the credential steward never reported armed")

    def restore_for_turn(self, backend: StewardBackend, handle: object) -> None:
        """Before a resume turn: RE-ARM FIRST (so the restore is not read as a
        re-creation), confirmed by `armed`; then restore the vaulted file,
        candidate-owned 0600, for the resumed client to read."""
        before = len(self.session.events)
        if backend.root_output_in_attempt(handle, ["sh", "-c", 'kill -USR1 "$(cat "$1")"', "sh", PIDFILE]) is None:
            raise StewardFailed("the credential steward could not be signalled to re-arm")
        self.arms_requested += 1
        if not self._await("armed", before):
            raise StewardFailed("the credential steward never re-armed for the resume turn")
        dest = f"{self.home_codex}/{self.auth_relpath}"
        script = ('cp -- "$1/auth.json" "$2" && chown "$3:$3" -- "$2" && chmod 0600 -- "$2"')
        if backend.root_output_in_attempt(handle, ["sh", "-c", script, "sh", VAULT, dest, CANDIDATE]) is None:
            raise StewardFailed("the vaulted credential could not be restored for the resume turn")

    def stop(self, backend: StewardBackend, handle: object) -> None:
        before = len(self.session.events)
        backend.root_output_in_attempt(handle, ["sh", "-c", 'kill -TERM "$(cat "$1")"', "sh", PIDFILE])
        self._await("stopped", before)  # a missing `stopped` reads UNKNOWN in the record

    def vault_bytes(self, backend: StewardBackend, handle: object) -> bytes | None:
        """The credential as it ends the attempt: the vault's copy (the home
        no longer holds it). For #98's refresh observation."""
        return backend.root_output_in_attempt(handle, ["cat", "--", f"{VAULT}/auth.json"])

    def record(self) -> dict[str, Any]:
        return self.session.finalize(expected_arms=self.arms_requested)
