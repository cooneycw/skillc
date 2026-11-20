"""Producer integration for the task-protocol stream (#620 PR-B, B8b).

Composes an owned `DockerWave` with the merged protocol slices in ONE fixed
order. Every step's failure makes that step's evidence UNKNOWN, never
invented, and cleanup always runs.

1. Freeze the prelaunch inventory. Its one clock origin IS the wave
   deadline's start, which the journal and, through the B8a context, the wake
   capture also use.
2. Issue one lease per role, with a lease directory each, handed to
   `DockerWave` through its additive `task_protocol_dirs` hook.
3. `prepare()` the wave, take the census setup snapshot, then audit the
   daemon's own `docker inspect` records for exclusivity. A refused audit
   means no offers: every slot is unavailable.
4. Install the standalone client into each sandbox.
5. Bootstrap turn. Its independently drained header gives the session; bind
   it with the audit digest as evidence; then the barrier. Only after the
   barrier does the caller's `freeze` (PR-A `freeze_plan`) receive the
   barrier's sessions.
6. Serve each bound lease, then run the measured turns.
7. Fence, drain the turns, then the census's live settle snapshot, which must
   come before any shutdown.
8. `DockerWave.close()`: confirmed role and helper stops, the final capture,
   cleanup. Then stop the receiver (drain) and seal the journal.
9. Finalize the census with the CONFIRMED role and helper stops.

Decision (a) is ruled a1 (owner, 2026-11-20, "626 empty: a1"): the adapter,
not this module, proves a zero-event role empty for assembly v2. This module
changes no verdict.

WAKE MODE (#626 P2). `measured="wake"` hands the turns to `wave_wake.drive`
with the caller's approved policy. Its three inert-by-default hooks keep the
same order: drive runs every bootstrap turn, then `after_bootstrap` binds,
barriers, freezes and serves before any poke; `before_close` fences and takes
the live census before `wave.close()`; and terminal roles stay running (with
no further turn or poke) until then. The wake capture's own context digest
joins `protocol_v2`'s clock join, and the report carries the `wake` binding
for the assembly row. The default `measured="scripted"` path is unchanged.

The full export and assembly is the caller's. This returns the held
`protocol_v2` binding and the census report, never a verdict.

Stdlib only, per AGENTS.md.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

from . import task_protocol_docker as tpd
from . import task_protocol_journal as tj
from . import wave_wake
from .backend import Confirmation
from .docker_wave import DockerWave
from .task_protocol_lease import Inventory, LeaseError, Leases, Slot
from .task_protocol_receiver import PeerVerifier, Receiver
from .task_protocol_state import Machine, Offer, Plan

PRODUCER_VERSION = "skillc-wave-protocol-1"
Inspect = Callable[[str], Mapping[str, Any] | None]


def _inspect_with(wave: DockerWave) -> Inspect:
    def inspect(name: str) -> Mapping[str, Any] | None:
        try:
            value = json.loads(wave._call(["inspect", "--format", "{{json .}}", name]))
        except Exception:  # noqa: BLE001 - an unreadable record is unavailable, never clean
            return None
        return value if isinstance(value, dict) else None
    return inspect


def _bounded(exc: BaseException) -> str:
    """The exception's class, plus its closed `reason_class` when it carries
    one (#817). Never its message, which can hold paths or uids (B7)."""
    reason = getattr(exc, "reason_class", None)
    allowed = getattr(type(exc), "REASONS", ())
    return type(exc).__name__ + (":" + reason if isinstance(reason, str) and reason in allowed
                                 else "")


#: The doubles `wave_wake.drive` accepts; nothing else passes through.
WAKE_OPTIONS = frozenset({"read_revision", "deliver", "clock", "sleep"})


class _WakeDone(Exception):
    """Internal control flow, never escapes run(): the wake driver already
    ran the turns, fence and live census."""


class ProtocolWave:
    """One protocol-instrumented wave. Single use."""

    def __init__(self, wave: DockerWave, *, slots: Sequence[Slot], declaration_digest: str,
                 deadline_digest: str, deadline_seconds: float, lease_root: Path,
                 journal_root: Path,
                 census: Any = None, inspect: Inspect | None = None,
                 verifier: PeerVerifier | None = None,
                 freeze: Callable[[Mapping[str, str | None]], object] | None = None,
                 receiver_factory: Callable[..., Receiver] = Receiver,
                 clock_ns: Callable[[], int] = time.monotonic_ns,
                 measured: str = "scripted", wake_policy: Any = None,
                 wake_options: Mapping[str, Any] | None = None) -> None:
        if [s.role for s in slots] != [r.name for r in wave.roles]:
            raise ValueError("one slot per wave role, in role order")
        wants_policy = measured == "wake"
        if measured not in ("scripted", "wake") or wants_policy != (wake_policy is not None):
            raise ValueError("measured is 'scripted', or 'wake' with an approved wake policy")
        if wake_options is not None and set(wake_options) - WAKE_OPTIONS:
            raise ValueError("wake options are drive's observer and transport doubles only")
        if measured == "wake":
            # The adapter joins the wake capture only if both captures name one
            # approved declaration and one deadline, so refuse a mismatch now.
            bound = getattr(wave, "approved_wake", None)
            if getattr(bound, "approved_digest", None) != declaration_digest:
                raise ValueError("wake mode: the journal declaration is the approved wake one")
            budget = wave.deadline.marker(wave.attempt_id)["budget_id"]
            if deadline_digest != "sha256:" + str(budget):
                raise ValueError("wake mode: the journal deadline is the wave's own budget")
        self.measured, self.wake_policy = measured, wake_policy
        self.wake_options = dict(wake_options or {})
        self.wake_outcome: str | None = None
        self.wave = wave
        self.origin_ns = round(wave.deadline.start * 1e9)
        self.inventory = Inventory(wave.attempt_id, declaration_digest, tuple(slots),
                                   self.origin_ns)
        # The DECLARED allowance, not end - start: float subtraction near a
        # large monotonic origin can be nanoseconds off, and the adapter
        # requires deadline_ns == round(plan.deadline * 1e9) exactly.
        if abs((wave.deadline.end - wave.deadline.start) - deadline_seconds) > 1e-6:
            raise ValueError("deadline_seconds must be the wave's own allowance")
        self.deadline_ns = round(deadline_seconds * 1e9)
        self.context = tj.Context(wave.attempt_id, declaration_digest, self.inventory.digest,
                                  deadline_digest, PRODUCER_VERSION, self.inventory.principals)
        self.lease_root, self.journal_root = lease_root, journal_root
        self.census = census
        self.inspect = inspect or _inspect_with(wave)
        self.verifier = verifier
        self.freeze = freeze
        self.receiver_factory = receiver_factory
        self.clock_ns = clock_ns
        self.events: list[str] = []
        self.unknown: list[str] = []
        self.used = False

    def _event(self, name: str) -> None:
        self.events.append(name)

    def _fail(self, reason: str) -> None:
        if reason not in self.unknown:
            self.unknown.append(reason)

    def run(self) -> dict[str, Any]:
        if self.used:
            raise ValueError("a protocol wave is single-use")
        self.used = True
        leases = Leases(self.inventory)
        journal = tj.Journal(self.journal_root, self.context, self.origin_ns,
                             clock_ns=self.clock_ns)
        issued, dirs = {}, {}
        for slot in self.inventory.slots:
            issued[slot.role] = leases.issue(slot.principal)
            dirs[slot.role] = tpd.lease_dir(self.lease_root, issued[slot.role].endpoint_id)
        self.wave.task_protocol_dirs = dict(dirs)
        self._event("leased")
        receiver: Receiver | None = None
        audit: dict[str, Any] = {"ok": False, "reasons": ["not-run"], "digest": ""}
        planned: object = None
        census_report: dict[str, Any] | None = None
        wave_report: dict[str, Any] = {}
        sessions: dict[str, str | None] = {}
        try:
            self.wave.prepare()
            self._event("prepared")
            if self.census is not None:
                self.census.setup()
                self._event("census-setup")
            audit = self._audit(dirs)
            self._event("audited")
            installed = self._install(audit["ok"], leases)
            if self.measured == "wake":
                box: dict[str, Any] = {}
                try:
                    self._wake(installed, leases, journal, audit, issued, dirs, box)
                finally:
                    receiver = box.get("receiver")
                    planned = box.get("planned")
                    sessions = box.get("sessions", {})
                    census_report = box.get("census")
                raise _WakeDone
            self._bootstrap(installed, leases, journal, audit)
            self._event("bootstrapped")
            journal.append("barrier", **leases.barrier())
            self._event("barrier")
            sessions = leases.bound_sessions()
            if self.freeze is not None:
                planned = self.freeze(sessions)
                self._event("frozen")
            receiver = self._serve(leases, journal, issued, dirs)
            self._measured(installed)
            receiver.fence()
            self._event("fenced")
            if self.census is not None:
                census_report = {"after": "captured"}
                self.census.capture_after()
                self._event("census-after")
        except _WakeDone:
            pass
        except Exception as exc:  # noqa: BLE001 - recorded, then cleanup always runs
            self._fail("protocol-step-unavailable:" + _bounded(exc))
        finally:
            wave_report = self._close()
            reference = self._seal(receiver, journal)
            census_report = self._finalize_census(census_report)
        return self._report(wave_report, reference, audit, planned, census_report, sessions)

    # -- steps ---------------------------------------------------------------------

    def _audit(self, dirs: Mapping[str, Path]) -> dict[str, Any]:
        records, expected = {}, {}
        for slot in self.inventory.slots:
            state = self.wave.states[slot.role]
            record = self.inspect(DockerWave._name(state.handle))
            records[slot.principal] = record
            cid = record.get("Id") if isinstance(record, Mapping) else None
            expected[slot.principal] = (cid if isinstance(cid, str) else "",
                                        os.path.realpath(dirs[slot.role]))
        ok, reasons, digest = tpd.audit(records, expected)
        if not ok:
            self._fail("exclusivity-refused")
        return {"ok": ok, "reasons": reasons, "digest": digest,
                "instances": {p: c for p, (c, _) in expected.items()}}

    def _install(self, audited: bool, leases: Leases) -> dict[str, str]:
        installed: dict[str, str] = {}
        for slot in self.inventory.slots:
            if not audited:
                leases.mark_unavailable(slot.principal, "exclusivity-refused")
                continue
            state = self.wave.states[slot.role]
            path = tpd.install_client(state.backend, state.handle)
            if path is None:
                leases.mark_unavailable(slot.principal, "client-install-failed")
                self._fail(slot.role + ":client-install-unavailable")
            else:
                installed[slot.role] = path
        return installed

    def _bootstrap(self, installed: Mapping[str, str], leases: Leases, journal: tj.Journal,
                   audit: Mapping[str, Any]) -> None:
        """The audited container ids are the runtime instances; the audit's
        mapping digest is each binding's evidence."""
        for slot in self.inventory.slots:
            if slot.role not in installed:
                continue
            self.wave.turn(slot.role)
            self._bind(slot, leases, journal, audit)

    def _bind(self, slot: Slot, leases: Leases, journal: tj.Journal,
              audit: Mapping[str, Any]) -> None:
        session = self.wave.states[slot.role].session_id
        try:
            record = leases.bind(slot.principal,
                                 runtime_instance=audit["instances"][slot.principal],
                                 session_id=session, evidence_digest=audit["digest"])
        except LeaseError:
            self._fail(slot.role + ":startup-binding-unavailable")
            return
        journal.append("binding", **record)

    def _wake(self, installed: Mapping[str, str], leases: Leases, journal: tj.Journal,
              audit: Mapping[str, Any], issued: Mapping[str, Any], dirs: Mapping[str, Path],
              box: dict[str, Any]) -> None:
        """The wake driver owns the turns; the hooks keep the scripted order."""

        def after_bootstrap() -> None:
            for slot in self.inventory.slots:
                if slot.role in installed:
                    self._bind(slot, leases, journal, audit)
            self._event("bootstrapped")
            journal.append("barrier", **leases.barrier())
            self._event("barrier")
            box["sessions"] = leases.bound_sessions()
            if self.freeze is not None:
                box["planned"] = self.freeze(box["sessions"])
                self._event("frozen")
            box["receiver"] = self._serve(leases, journal, issued, dirs)

        def before_close() -> None:
            # Never raises: drive's cleanup must run, and each failure is recorded.
            self._event("turns-done")
            receiver = box.get("receiver")
            try:
                if receiver is None:
                    raise ValueError("no receiver to fence")
                receiver.fence()
                self._event("fenced")
            except Exception as exc:  # noqa: BLE001 - recorded
                self._fail("wake-fence-unavailable:" + type(exc).__name__)
                return
            if self.census is None:
                return
            try:
                for slot in self.inventory.slots:
                    self.census.completion(slot.role)
                self.census.capture_after()
                box["census"] = {"after": "captured"}
                self._event("census-after")
            except Exception as exc:  # noqa: BLE001 - recorded; the census stays UNKNOWN
                self._fail("census-settle-unavailable:" + type(exc).__name__)

        report = wave_wake.drive(self.wave, self.wake_policy, after_bootstrap=after_bootstrap,
                                 before_close=before_close, defer_terminal_stop=True,
                                 **self.wake_options)
        self.wake_outcome = report.get("outcome") if isinstance(report, dict) else None

    def _serve(self, leases: Leases, journal: tj.Journal, issued: Mapping[str, Any],
               dirs: Mapping[str, Path]) -> Receiver:
        offers = tuple(Offer(s.principal, "offer-" + s.role) for s in self.inventory.slots)
        machine = Machine(Plan(offers, self.deadline_ns))
        verifier = self.verifier or tpd.DockerPeerVerifier(
            [DockerWave._name(self.wave.states[s.role].handle) for s in self.inventory.slots],
            self.inspect)
        receiver = self.receiver_factory(leases, machine, journal, verifier)
        for slot in self.inventory.slots:
            receiver.serve(issued[slot.role], dirs[slot.role] / tpd.SOCKET_NAME)
        self._event("serving")
        return receiver

    def _measured(self, installed: Mapping[str, str]) -> None:
        """The declared literal resumes, concurrently per role, as
        `DockerWave.run_scripted` runs them; each role's completion is
        reported to the census when its turns end."""
        errors: list[BaseException] = []

        def actor(name: str) -> None:
            try:
                for text in self.wave.states[name].role.resume_texts:
                    result = self.wave.states[name].executions[-1]
                    if result.reason != "exited" or result.exit_code != 0:
                        break
                    self.wave.turn(name, text)
            except BaseException as exc:  # noqa: BLE001 - recorded after all threads end
                errors.append(exc)
            finally:
                if self.census is not None:
                    self.census.completion(name)

        threads = [threading.Thread(target=actor, args=(name,)) for name in installed]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        if self.census is not None:
            for slot in self.inventory.slots:
                if slot.role not in installed:
                    self.census.completion(slot.role)
        self._event("turns-done")
        if errors:
            self._fail("measured-turn-unavailable")

    def _close(self) -> dict[str, Any]:
        try:
            report: dict[str, Any] = self.wave.close()
        except Exception as exc:  # noqa: BLE001 - lifecycle evidence becomes unavailable
            self._fail("wave-close-unavailable:" + type(exc).__name__)
            return {}
        self._event("closed")
        return report

    def _seal(self, receiver: Receiver | None, journal: tj.Journal) -> tj.Reference | None:
        try:
            if receiver is not None:
                if not receiver.stop():
                    self._fail("receiver-drain-unavailable")
                reference = receiver.seal()
            else:
                if not journal.fenced:
                    journal.append("fence", reason="unavailable")
                reference = journal.seal(dict.fromkeys(self.inventory.principals, "unknown"))
        except Exception as exc:  # noqa: BLE001 - an unsealed journal is unavailable
            self._fail("journal-seal-unavailable:" + type(exc).__name__)
            return None
        self._event("sealed")
        return reference

    def _finalize_census(self, census_report: dict[str, Any] | None) -> dict[str, Any] | None:
        if self.census is None:
            return None
        stops = {name: state.stopped for name, state in self.wave.states.items()}
        helper = Confirmation.CONFIRMED if "fixture-stop-unconfirmed" not in self.wave.unknown \
            and self.wave.remote is not None else Confirmation.UNKNOWN
        try:
            if census_report is None:
                # The live settle snapshot never ran before shutdown.
                self._fail("census-settle-unavailable")
                report: dict[str, Any] = {"status": "UNKNOWN",
                                          "reason": "census settle snapshot not captured live"}
            else:
                report = self.census.finalize(role_stops=stops, helper_stop=helper)
        except Exception as exc:  # noqa: BLE001 - census evidence becomes unavailable
            self._fail("census-final-unavailable:" + type(exc).__name__)
            return {"status": "UNKNOWN", "reason": "census finalization unavailable"}
        self._event("census-final")
        return report

    def _report(self, wave_report: dict[str, Any], reference: tj.Reference | None,
                audit: dict[str, Any], planned: object, census: dict[str, Any] | None,
                sessions: Mapping[str, str | None]) -> dict[str, Any]:
        protocol: dict[str, Any] | None = None
        if reference is not None:
            protocol = {"root": str(self.journal_root), "reference": asdict(reference),
                        "context": self.context.fields(), "inventory": self.inventory.fields(),
                        "deadline_ns": self.deadline_ns,
                        "clock_join": {"inventory_digest": self.inventory.digest,
                                       "wake_context_digest": None,
                                       "origin_ns": self.inventory.clock_origin_ns}}
        wake = self._wake_binding()
        if protocol is not None and wake is not None:
            protocol["clock_join"]["wake_context_digest"] = wake["context_digest"]
        return {"version": 1, "scope": "protocol-lifecycle-only", "events": list(self.events),
                "unknown": list(self.unknown), "wave": wave_report,
                "audit": {k: audit[k] for k in ("ok", "reasons", "digest")},
                "sessions": dict(sessions), "planned_frozen": planned is not None,
                "protocol_v2": protocol, "census": census,
                "decision_a": "a2: zero-event complete roles stay UNKNOWN (owner ruling pending)",
                **({} if self.measured == "scripted" else {
                    "wake": None if wake is None else wake["binding"],
                    "wake_outcome": self.wake_outcome})}

    def _wake_binding(self) -> dict[str, Any] | None:
        """The sealed wake capture's held binding: its root, Reference and the
        OriginContext it recorded, which must carry the inventory's origin."""
        if self.measured != "wake":
            return None
        reference = getattr(self.wave, "wake_capture_reference", None)
        context = getattr(self.wave, "wake_capture_context", None)
        if reference is None or context is None or getattr(context, "clock_origin_ns", None) \
                != self.inventory.clock_origin_ns:
            self._fail("wake-capture-unavailable")
            return None
        return {"context_digest": context.digest,
                "binding": {"root": str(self.wave.root / "wake-capture"),
                            "reference": asdict(reference), "context": asdict(context)}}
