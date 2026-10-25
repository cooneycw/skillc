"""Bounded trusted scripted-process coordination (#569A).

This is an explicit controller-host profile over ``trial.run_attempt``, never
a fallback for an unavailable isolation backend or a launcher for live agents.
The trusted caller pins the actor bytes; no arbitrary argv or shell is accepted.
Sockets bind routing, not hostile same-UID identity. Requests/decisions and
participant receipt claims establish neither native wake nor tool execution.
One wave is primary; its three role attempts remain diagnostic records.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import platform
import secrets
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

from . import trial
from .decide_reply_channel import ChannelRefusal, DecideReplyChannel

ROLES = ("orchestrator", "worker-a", "worker-b")
MODES = frozenset({"healthy", "wrong-role", "wrong-session", "wrong-generation",
                   "wrong-revision", "wrong-wave", "wrong-task", "duplicate-completion",
                   "forged-completion", "no-integration", "hang", "disappear", "late-decision",
                   "wrong-attempt", "wrong-nonce", "wrong-boolean-generation", "wrong-boolean-revision",
                   "duplicate-registration", "duplicate-receipt", "unregistered-poll", "unreceived-completion",
                   "request-flood"})
MAX_EVENTS = 128
MAX_MESSAGE = 4096
_BASE_KEYS = frozenset({"op", "wave", "role", "session", "generation", "attempt_id"})


@dataclass(frozen=True)
class WavePlan:
    """Exactly two independent outputs, followed by their integration."""

    actor_digest: str
    case_id: str = "healthy"
    mode: str = "healthy"
    order: tuple[str, str] = ("worker-a", "worker-b")
    values: tuple[str, str] = ("alpha", "beta")
    deadline: float = 10.0
    offer_delay: float = 0.0


@dataclass(frozen=True)
class WaveResult:
    experiment: trial.Experiment
    report: dict[str, Any]


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _write(path: Path, value: object) -> str:
    data = trial.canonical(value)
    with path.open("xb") as handle:
        handle.write(data)
    path.chmod(0o400)
    return _digest(data)


def _validate(plan: WavePlan, actor: Path) -> bytes:
    if (plan.mode not in MODES or set(plan.order) != set(ROLES[1:])
            or len(plan.order) != 2 or not plan.case_id
            or len(plan.case_id) > 64 or not plan.case_id.isascii()):
        raise ValueError("unsupported scripted wave declaration")
    for value in (plan.deadline, plan.offer_delay):
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
            raise ValueError("wave bounds must be finite numbers")
    if not 0 < plan.deadline <= 30 or not 0 <= plan.offer_delay <= 1:
        raise ValueError("wave bounds exceed the scripted profile")
    if len(plan.values) != 2 or any(not isinstance(v, str) or not 0 < len(v.encode()) <= 256 for v in plan.values):
        raise ValueError("wave must declare two bounded artifact values")
    if actor.is_symlink() or not actor.is_file():
        raise ValueError("actor must be a pinned regular source file")
    source = actor.read_bytes()
    if not source or len(source) > 16384 or _digest(source) != plan.actor_digest:
        raise ValueError("scripted actor source identity disagrees")
    return source


class _Controller:
    def __init__(self, plan: WavePlan, experiment: trial.Experiment, started: float,
                 clock: Callable[[], float]) -> None:
        self.plan, self.experiment, self.started, self.clock = plan, experiment, started, clock
        self.lock = threading.RLock()
        self.cancel = threading.Event()
        self.events: list[dict[str, Any]] = []
        self.failures: set[str] = set()
        self.unknown: set[str] = set()
        self.unavailable_roles: set[str] = set()
        self.registered: set[str] = set()
        self.offered: set[str] = set()
        self.received: set[str] = set()
        self.claimed: set[str] = set()
        self.outputs: dict[str, str] = {}
        self.roles: dict[str, dict[str, Any]] = {}
        self.requests = 0
        self.release_at: float | None = None
        for role, (_, attempt) in zip(ROLES, experiment.attempts(), strict=True):
            self.roles[role] = {"attempt_id": str(attempt["attempt_id"]), "role": role,
                                "session": secrets.token_hex(16), "generation": 0,
                                "task": "integrate" if role == ROLES[0] else role,
                                "revision": 1, "nonce": secrets.token_hex(16)}

    def event(self, role: str, kind: str, **detail: Any) -> int:
        with self.lock:
            if len(self.events) >= MAX_EVENTS:
                self.unavailable_roles.add(role)
                self.fail("event-limit", unknown=True)
                return -1
            seq = len(self.events) + 1
            self.events.append({"seq": seq, "role": role,
                                "attempt_id": self.roles[role]["attempt_id"], "event": kind,
                                "elapsed": self.clock() - self.started, **detail})
            return seq

    def fail(self, reason: str, *, unknown: bool = False) -> None:
        with self.lock:
            (self.unknown if unknown else self.failures).add(reason)
            self.cancel.set()

    def cancel_for_deadline(self) -> None:
        with self.lock:
            # Preserve a witnessed timeout before later cleanup loses evidence;
            # earlier infrastructure cancellation does not witness a timeout.
            unfinished = self.received - self.claimed - self.unavailable_roles
            if unfinished and not self.cancel.is_set():
                self.fail("deadline")
            self.cancel.set()

    def decide(self, role: str, request: Mapping[str, object]) -> Mapping[str, object]:
        with self.lock:
            self.requests += 1
            if self.requests > MAX_EVENTS:
                self.unavailable_roles.add(role)
                self.fail("request-limit", unknown=True)
                raise ChannelRefusal("request-limit")
            bound = self.roles[role]
            op = request.get("op")
            if not isinstance(op, str):
                self.fail("invalid-operation")
                raise ChannelRefusal("invalid-operation")
            keys = _BASE_KEYS | ({"task", "revision", "nonce"} if op in {"ack", "complete"} else set())
            valid = (set(request) == keys and request.get("wave") == self.experiment.root.name
                     and all(type(request.get(k)) is type(bound[k]) and request.get(k) == bound[k]
                             for k in ("role", "session", "generation", "attempt_id")))
            if not valid or op not in {"register", "poll", "ack", "complete"}:
                self.event(role, "request-refused", operation=str(op)[:32])
                self.fail("wrong-assignment-identity")
                raise ChannelRefusal("wrong-assignment-identity")
            reply: dict[str, Any] = {"state": "wait"}
            if op == "register":
                if role in self.registered:
                    self.fail("duplicate-registration")
                self.registered.add(role)
            elif role not in self.registered:
                self.fail("unregistered-request")
            elif op == "poll":
                ready = (all(r in self.outputs for r in ROLES[1:]) if role == ROLES[0]
                         else role == self.plan.order[0] or self.plan.order[0] in self.offered)
                if role == self.plan.order[0] and self.release_at is None:
                    self.release_at = self.clock() + self.plan.offer_delay
                    if self.plan.offer_delay:
                        self.event(role, "offer-deferred")
                delayed = role == self.plan.order[0] and self.clock() < (self.release_at or 0)
                if ready and not delayed and not self.cancel.is_set() and role not in self.offered:
                    self.event(role, "offer-decision", previously_deferred=bool(self.plan.offer_delay))
                    self.offered.add(role)
                    payload = dict(self.outputs) if role == ROLES[0] else self.plan.values[ROLES.index(role) - 1]
                    reply = {"state": "offered", "task": bound["task"], "revision": 1,
                             "nonce": bound["nonce"], "payload": payload}
            elif (role not in self.offered or any(type(request.get(k)) is not type(bound[k])
                                                 or request.get(k) != bound[k]
                                                 for k in ("task", "revision", "nonce"))):
                self.fail("wrong-assignment-revision")
            elif op == "ack":
                if role in self.received:
                    self.fail("duplicate-receipt")
                self.received.add(role)
                reply = {"state": "receipt-recorded"}
            elif role not in self.received or role in self.claimed:
                self.fail("duplicate-or-unreceived-completion")
            else:
                self.claimed.add(role)
                reply = {"state": "claim-recorded"}
            seq = self.event(role, "request-decided", request=dict(request), reply=reply)
            return {**reply, "decision_id": seq}


def _captured_output(experiment: trial.Experiment, manifest: Mapping[str, Any],
                     expected: bytes) -> str:
    if manifest.get("capture_failures"):
        raise trial.Refused("partial capture")
    artifacts = [a for a in manifest["artifacts"] if a.get("path") == "output.json"]
    if len(artifacts) != 1:
        raise ValueError("missing integration or role artifact")
    artifact = artifacts[0]
    data = trial.read_object(experiment, artifact["digest"])
    if data != expected or artifact["size"] != len(data):
        raise ValueError("incorrect captured artifact")
    return str(artifact["digest"])


def run_wave(plan: WavePlan, actor: Path, store: Path, workspace_base: Path,
             *, clock: Callable[[], float] = time.monotonic) -> WaveResult:
    """Execute only controller-trusted pinned scripted participants.

    The common deadline includes setup/capture/cleanup and provisional evidence.
    Final decision-record emission follows the immutable completion boundary.
    Cancellation reaches
    live process groups through trial's poll loop; host filesystem operations
    and Python threads have no hard interrupt guarantee. Teardown can exceed
    the deadline and never earns on-time success. No native wake is observed.
    """
    started = clock()
    source = _validate(plan, actor)
    store = trial.open_store(store, forbidden=[workspace_base])
    spec = dataclasses.asdict(plan)
    experiment = trial.plan({"experiment": "scripted-wave", "trials": [
        {"label": role, "case": {"id": plan.case_id, "revision": "1"},
         "grader": {"id": "scripted-wave-artifacts", "revision": "1"},
         "subject": {"digest": plan.actor_digest}, "client": {"name": "scripted-python", "version": platform.python_version()},
         "image": {"digest": "not-isolated-trusted-host"},
         "config": {"wave_plan": spec, "role": role, "model": None}, "attempts": 1}
        for role in ROLES]}, store)
    controller = _Controller(plan, experiment, started, clock)
    plan_digest: str | None = None
    diagnostics: dict[str, Any] = {}
    channels: dict[str, DecideReplyChannel] = {}
    channel_logs: dict[str, list[Any]] = {}
    channel_digests: dict[str, str] = {}
    errors: list[BaseException] = []

    def finalize_channel(role: str) -> bool:
        if role not in channels:
            return False
        try:
            channel = channels[role]
            log = channel.log_or_finalize()
            if channel.dropped_connections():
                raise trial.Refused("dropped channel requests")
            channel_logs[role] = log
            return True
        except (OSError, RuntimeError, trial.Refused):
            controller.fail("channel-coverage-unavailable", unknown=True)
            return False
        except BaseException as exc:  # noqa: BLE001 - retained for re-raise after all channels close
            errors.append(exc)
            controller.fail("channel-controller-exception", unknown=True)
            return False
        finally:
            try:
                channels[role].close()
            except BaseException as exc:  # noqa: BLE001 - do not abandon other owned channels
                errors.append(exc)
                controller.fail("channel-close-unconfirmed", unknown=True)

    def account(role: str, record: dict[str, Any]) -> None:
        aid = controller.roles[role]["attempt_id"]
        try:
            lifecycle = trial.finalize(experiment, aid)
            record["lifecycle"] = lifecycle["disposition"]
            record["lifecycle_digest"] = _digest((experiment.root / f"lifecycle-{aid}.json").read_bytes())
        except (OSError, trial.Refused):
            controller.fail("accounting-unavailable", unknown=True)
        except BaseException as exc:  # noqa: BLE001 - retained for re-raise after all roles accounted
            errors.append(exc)
            controller.fail("accounting-exception", unknown=True)
        diagnostics[role] = record

    def participant(role: str, socket_path: Path, staged_actor: Path) -> None:
        binding = controller.roles[role]
        aid = binding["attempt_id"]
        workspace: Path | None = None
        stopped = False
        record: dict[str, Any] = {"attempt_id": aid, "model": None, "client": "scripted-python"}
        try:
            workspace = trial.allocate_workspace(experiment, aid, workspace_base, [])
            remaining = plan.deadline - (clock() - started)
            if controller.cancel.is_set():
                return
            if remaining <= 0:
                controller.cancel_for_deadline()
                return
            config = {k: binding[k] for k in ("role", "session", "generation", "attempt_id")}
            config.update(wave=experiment.root.name, mode=plan.mode)
            result = trial.run_attempt(experiment, aid,
                                       [sys.executable, "-I", str(staged_actor), str(socket_path), json.dumps(config)],
                                       workspace, remaining, grace=0.2, cancel=controller.cancel.is_set)
            record["stop"] = result
            stopped = result.get("confirmed") is True
            if result.get("reason") == "launch-failed":
                controller.fail("launch-unavailable", unknown=True)
                return
            if not stopped:
                controller.fail("stop-unconfirmed", unknown=True)
                return
            finalized = finalize_channel(role)
            if result.get("reason") == "timeout":
                with controller.lock:
                    # The runner independently witnessed this role's timeout.
                    if role in controller.received and role not in controller.claimed and role not in controller.unavailable_roles:
                        controller.fail("deadline")
                    controller.cancel.set()
            elif (result.get("reason") == "exited" and result.get("exit_code") != 0
                  and role not in controller.unavailable_roles):
                controller.fail("participant-exit")
            with controller.lock:
                own_events = [dict(e) for e in controller.events if e["role"] == role]
            event_file = experiment.root / f"events-{aid}.json"
            event_digest = _write(event_file, {"attempt_id": aid, "events": own_events,
                                              "channel_finalized": finalized})
            manifest = trial.capture(experiment, aid, workspace,
                                     imports=(trial.Import(event_file, "coordination-events", "observed", event_digest),))
            record["manifest"] = f"manifest-{aid}.json"
            record["manifest_digest"] = _digest((experiment.root / record["manifest"]).read_bytes())
            with controller.lock:
                expected_value: object = ({r: controller.outputs[r] for r in ROLES[1:]}
                                          if role == ROLES[0] and len(controller.outputs) == 2
                                          else plan.values[ROLES.index(role) - 1] if role != ROLES[0] else {})
                expected = trial.canonical(expected_value)
                if role not in controller.received or role not in controller.claimed:
                    if not controller.cancel.is_set():
                        controller.fail("missing-receipt-or-completion")
                elif finalized:
                    digest = _captured_output(experiment, manifest, expected)
                    controller.outputs[role] = digest
                    controller.event(role, "artifact-captured", digest=digest)
        except ValueError:
            controller.fail("incorrect-or-absent-artifact")
        except (OSError, trial.Refused):
            controller.fail("capture-or-controller-unavailable", unknown=True)
        except BaseException as exc:  # noqa: BLE001 - re-raised after accounting and teardown
            controller.fail("controller-exception", unknown=True)
            errors.append(exc)
        finally:
            try:
                events = experiment.events(aid)
                if stopped or not any(e["event"] == "dispatched" for e in events):
                    cleanup = trial.cleanup_workspace(experiment, aid)
                    record["cleanup"] = cleanup["status"]
                    if cleanup["status"] not in {"removed", "already-absent", "not-needed"} or cleanup["errors"]:
                        controller.fail("cleanup-unconfirmed", unknown=True)
                else:
                    controller.fail("cleanup-unconfirmed", unknown=True)
            except (OSError, trial.Refused):
                controller.fail("cleanup-unconfirmed", unknown=True)
            except BaseException as exc:  # noqa: BLE001 - retain and still account for the attempt
                errors.append(exc)
                controller.fail("cleanup-exception", unknown=True)
            finally:
                with controller.lock:
                    account(role, record)

    # Short socket paths respect AF_UNIX bounds. Only trusted scripted actors
    # share this host; no same-UID authentication/containment claim is made.
    sockets: tempfile.TemporaryDirectory[str] | None = None
    threads: list[threading.Thread] = []
    try:
        plan_digest = _write(experiment.root / "wave-plan.json", {"spec": spec, "roles": controller.roles})
        sockets = tempfile.TemporaryDirectory(prefix="sw-")
        socket_root = Path(sockets.name)
        staged_actor = socket_root / "actor.py"
        staged_actor.write_bytes(source)
        staged_actor.chmod(0o400)
        for role in ROLES:
            path = socket_root / f"{role}.sock"
            channel = DecideReplyChannel(path, partial(controller.decide, role),
                                         controller.roles[role]["attempt_id"], max_request_bytes=MAX_MESSAGE,
                                         max_concurrent_handlers=2, request_timeout=0.5, handler_drain_timeout=0.5)
            channels[role] = channel
            channel.start()
        for role in (ROLES[0], *plan.order):
            thread = threading.Thread(target=participant, args=(role, socket_root / f"{role}.sock", staged_actor))
            threads.append(thread)
            thread.start()
        while any(t.is_alive() for t in threads):
            with controller.lock:
                if clock() - started >= plan.deadline:
                    controller.cancel_for_deadline()
            for thread in threads:
                thread.join(timeout=0.01)
    except BaseException as exc:  # noqa: BLE001 - re-raised after accounting and teardown
        controller.fail("setup-or-controller-exception", unknown=True)
        errors.append(exc)
        for thread in threads:
            if thread.ident is not None:
                thread.join()
    finally:
        # Close every channel BEFORE publishing any teardown evidence.
        for role in channels:
            finalize_channel(role)
        for role in channels:
            try:
                channel_digests[role] = _write(experiment.root / f"channel-{role}.json", {
                    "attempt_id": controller.roles[role]["attempt_id"],
                    "decisions": [dataclasses.asdict(item) for item in channel_logs.get(role, [])]})
            except OSError:
                controller.fail("channel-publication-unavailable", unknown=True)
            except BaseException as exc:  # noqa: BLE001 - retain and continue accounting
                errors.append(exc)
                controller.fail("channel-publication-exception", unknown=True)
        for role in ROLES:
            if role not in diagnostics:
                account(role, {"attempt_id": controller.roles[role]["attempt_id"], "cleanup": "not-needed"})
        if sockets is not None:
            try:
                sockets.cleanup()
            except OSError:
                controller.fail("socket-cleanup-unconfirmed", unknown=True)
            except BaseException as exc:  # noqa: BLE001 - retain original failure
                errors.append(exc)
                controller.fail("socket-cleanup-exception", unknown=True)
    # Re-read captured bytes and all joins after every role has stopped. A worker
    # output used for integration is not exempt from this final integrity check.
    try:
        if _digest((experiment.root / "wave-plan.json").read_bytes()) != plan_digest:
            raise trial.Refused("wave declaration changed")
        for role, record in diagnostics.items():
            aid = record["attempt_id"]
            channel_path = experiment.root / f"channel-{role}.json"
            data = channel_path.read_bytes()
            channel_data = json.loads(data)
            if (channel_digests[role] != _digest(data) or channel_data["attempt_id"] != aid
                    or channel_data["decisions"] != [dataclasses.asdict(e) for e in channel_logs[role]]):
                raise trial.Refused("retained channel evidence disagrees")
            lifecycle_path = experiment.root / f"lifecycle-{aid}.json"
            if _digest(lifecycle_path.read_bytes()) != record["lifecycle_digest"]:
                raise trial.Refused("lifecycle changed")
            if "manifest" not in record:
                continue
            path = experiment.root / record["manifest"]
            if _digest(path.read_bytes()) != record["manifest_digest"]:
                raise trial.Refused("manifest changed")
            manifest = json.loads(path.read_bytes())
            if (manifest["attempt_id"] != aid
                    or manifest["trial_id"] != experiment.trial_of(aid)["trial_id"]):
                raise trial.Refused("manifest identity disagrees")
            for item in [*manifest["artifacts"], *manifest["observations"]]:
                if len(trial.read_object(experiment, item["digest"])) != item["size"]:
                    raise trial.Refused("captured size disagrees")
            observations = [o for o in manifest["observations"] if o["stream"] == "coordination-events"]
            if len(observations) != 1:
                raise trial.Refused("missing or duplicate coordination capture")
            observation = observations[0]
            payload = json.loads(trial.read_object(experiment, observation["digest"]))
            own = [e for e in controller.events if e["role"] == role and e["event"] != "artifact-captured"]
            if (observation["origin"] != "observed" or observation["coverage"] != "complete"
                    or observation["attempt_id"] != aid or payload["attempt_id"] != aid
                    or not payload["channel_finalized"] or payload["events"] != own):
                raise trial.Refused("coordination coverage disagrees")
            decisions = {e["seq"]: e for e in own if e["event"] == "request-decided"}
            log = channel_logs[role]
            if len(log) != len(decisions) or any(
                entry.request != decisions.get(entry.result["decision_id"], {}).get("request")
                or entry.result != {**decisions[entry.result["decision_id"]]["reply"],
                                    "decision_id": entry.result["decision_id"]} for entry in log
            ):
                raise trial.Refused("channel decision join disagrees")
    except (OSError, ValueError, KeyError, trial.Refused):
        controller.fail("final-evidence-unavailable", unknown=True)
    if len(controller.outputs) != 3 and not controller.unknown:
        controller.fail("incomplete-wave")
    def publish(path: Path, value: object) -> str:
        try:
            return _write(path, value)
        except BaseException as exc:
            if errors:
                raise errors[0] from exc
            raise

    events_digest = publish(experiment.root / "wave-events.json", controller.events)
    if clock() - started > plan.deadline and not controller.unknown:
        controller.fail("deadline")
    report: dict[str, Any] = {"version": 1, "primary": {"unit": "wave", "planned": 1},
                              "status": "FAIL" if controller.failures else "UNKNOWN" if controller.unknown else "PASS",
                              "failures": sorted(controller.failures), "unknown": sorted(controller.unknown),
                              "elapsed": clock() - started, "deadline": plan.deadline,
                              "roles": diagnostics, "plan_digest": plan_digest, "events_digest": events_digest,
                              "channel_digests": channel_digests,
                              "outputs": dict(controller.outputs), "native_wake": "UNOBSERVED"}
    report["clock"] = "monotonic" if clock is time.monotonic else "injected-policy-only"
    report["primary"]["completed"] = int(report["status"] == "PASS")
    provisional = {**report, "status": "UNKNOWN", "primary": {**report["primary"], "completed": 0},
                   "unknown": sorted(controller.unknown | {"decision-publication-pending"})}
    publish(experiment.root / "wave-report.json", provisional)
    completion_elapsed = clock() - started
    report.update(elapsed=completion_elapsed, completion_elapsed=completion_elapsed,
                  deadline_scope="through-verified-cleanup-and-provisional-evidence",
                  final_decision_emission="outside-completion-deadline")
    if completion_elapsed > plan.deadline and not controller.unknown:
        report.update(status="FAIL", failures=sorted(controller.failures | {"deadline"}))
        report["primary"]["completed"] = 0
    late = experiment.root / "wave-report-late.json"  # Staged candidate, never authoritative.
    publish(late, report)
    try:
        late.replace(experiment.root / "wave-report.json")
    except BaseException as exc:
        if errors:
            raise errors[0] from exc
        raise
    if errors:
        raise errors[0]
    return WaveResult(experiment, report)
