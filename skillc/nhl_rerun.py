"""Controller-owned, model-free NHL delivered-code replay grading (#634).

Private snapshot preparation and Docker execution are separate explicit steps.
Only served payloads enter the server; expected reports never enter either
container. A controller adapter selects commands from the project's README.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import selectors
import signal
import stat
import subprocess
import tempfile
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from . import nhl_oracle as oracle
from . import nhl_snapshot as snapshot
from .nhl_snapshot import Json, ReferenceError


class InfrastructureError(ReferenceError):
    """Controller execution failed; no candidate verdict can be inferred."""


class _CandidateFailure(ReferenceError):
    """A documented candidate obligation failed with controller-held evidence."""


class _CaptureLimit(InfrastructureError):
    """The harness cut off command output; this is not a task-failure verdict."""



@dataclass(frozen=True)
class _InvocationEvidence:
    path: Path
    digest: str

    def read(self, candidate: str, entrypoint: str, runtime: str) -> Json:
        raw = self.path.read_bytes()
        if snapshot.sha256(raw) != self.digest:
            raise InfrastructureError('controller termination record changed')
        record = json.loads(raw)
        fields = {'candidate', 'entrypoint', 'signal_tracking_complete', 'signals_sent',
                  'harness_timed_out', 'runtime_sha256'}
        if (type(record) is not dict or set(record) != fields
                or record['candidate'] != candidate or record['entrypoint'] != entrypoint
                or record['signal_tracking_complete'] is not True
                or type(record['harness_timed_out']) is not bool
                or type(record['signals_sent']) is not list
                or any(type(value) is not str or not value for value in record['signals_sent'])
                or record['runtime_sha256'] != snapshot.sha256(runtime.encode())):
            raise InfrastructureError('controller termination coverage unavailable')
        return record


class _Terminations:
    """Private controller journal; every owned termination request is recorded first."""

    def __init__(self, evidence: Path, candidate: str) -> None:
        self.directory = evidence
        self.candidate = candidate
        self.signals: list[str] = []
        self.timed_out = False
        self.entrypoint: str | None = None
        self.sequence = 0
        self.cutoff_reason: str | None = None
        self.event('controller-termination-tracking-started')

    def event(self, name: str, **fields: Any) -> None:
        record = {'sequence': self.sequence, 'event': name, 'candidate': self.candidate, **fields}
        with (self.directory / 'termination.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(record, sort_keys=True) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        descriptor = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        self.sequence += 1

    def begin(self, entrypoint: str) -> None:
        self.event('documented-entrypoint-invoked', entrypoint=entrypoint)
        self.entrypoint = entrypoint

    def signal(self, action: str) -> None:
        self.event('controller-termination-request', action=action)
        self.signals.append(action)

    def timeout(self) -> None:
        self.event('harness-timeout', entrypoint=self.entrypoint)
        self.timed_out = True

    def cutoff(self, reason: str) -> None:
        # Command-client kills are observed after the runner raises. Never
        # publish a no-signal attestation after such an interrupted command.
        self.cutoff_reason = reason
        self.event('command-cutoff-observed', reason=reason, entrypoint=self.entrypoint)

    def capture(self, runtime: str) -> _InvocationEvidence:
        if self.cutoff_reason is not None:
            raise InfrastructureError(self.cutoff_reason)
        if self.entrypoint is None:
            raise InfrastructureError('documented invocation not recorded')
        record = {'candidate': self.candidate, 'entrypoint': self.entrypoint,
                  'signal_tracking_complete': True, 'signals_sent': self.signals[:],
                  'harness_timed_out': self.timed_out, 'runtime_sha256': snapshot.sha256(runtime.encode())}
        path = self.directory / f'attribution-{self.sequence}.json'
        raw = (json.dumps(record, sort_keys=True) + '\n').encode()
        with path.open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        self.event('attribution-captured', path=path.name, sha256=snapshot.sha256(raw))
        return _InvocationEvidence(path, snapshot.sha256(raw))


def _attribute_failure(inspected: subprocess.CompletedProcess[str], *, entrypoint: str,
                       command_exit: int | None, timed_out: bool, candidate: str,
                       evidence: _InvocationEvidence | None) -> None:
    """Attribute a failed documented command from independently held runtime facts.

    A harness resource limit has no approved task-failure authority yet (#639).
    Additional runtime fields are allowed, but every fact we consume is required
    and typed; partial, contradictory or daemon-error state is not candidate blame.
    """
    unknown = InfrastructureError("candidate runtime state unconfirmed")
    if type(inspected.returncode) is not int or inspected.returncode != 0:
        raise unknown
    try:
        state = json.loads(inspected.stdout)
    except (ValueError, TypeError) as exc:
        raise unknown from exc
    if (type(state) is not dict or any(type(state.get(key)) is not bool
            for key in ('Running', 'OOMKilled', 'Dead', 'Restarting'))
            or type(state.get('Status')) is not str or type(state.get('Error')) is not str
            or type(state.get('ExitCode')) is not int or not 0 <= state['ExitCode'] <= 255
            or state['Error'] or state['Dead'] or state['Restarting']):
        raise unknown
    if state['OOMKilled'] and not state['Running'] and state['Status'] == 'exited' and state['ExitCode'] > 0:
        raise InfrastructureError('candidate exceeded the harness memory limit (#639 approval pending): ' + entrypoint)
    missing = ('signal-range exit without a positive no-signal record' if state['ExitCode'] >= 128 else
               'controller termination coverage unavailable')
    if type(evidence) is not _InvocationEvidence:
        raise InfrastructureError(missing)
    try:
        held = evidence.read(candidate, entrypoint, inspected.stdout)
    except (OSError, ValueError) as exc:
        raise InfrastructureError(missing) from exc
    if held['signals_sent']:
        raise InfrastructureError('harness-signalled candidate: ' + ','.join(held['signals_sent']))
    if held['harness_timed_out'] or timed_out:
        raise InfrastructureError('candidate exceeded the harness wall-time limit (#639 approval pending): ' + entrypoint)
    running = state['Running']
    if running:
        if state['Status'] != 'running' or state['ExitCode'] != 0 or state['OOMKilled']:
            raise unknown
        if type(command_exit) is int and 0 < command_exit <= 255:
            raise _CandidateFailure(f'documented entry point failed (exit {command_exit}): {entrypoint}')
        raise unknown
    if state['Status'] != 'exited' or state['ExitCode'] == 0:
        raise unknown
    raise _CandidateFailure(f'documented entry point failed (container exit {state["ExitCode"]}): {entrypoint}')


def custody(project: Path, *private: Path) -> None:
    root = project.resolve()
    if not project.is_dir() or project.is_symlink() or root == Path(root.anchor):
        raise ReferenceError("delivered project must be a distinct directory")
    if any(path.resolve().is_relative_to(root) for path in private):
        raise ReferenceError("controller private material must be outside delivered project")


def route(endpoint: str) -> str:
    parsed = urlsplit(endpoint)
    return parsed.path + ("?" + parsed.query if parsed.query else "")


def inject(value: Any) -> Any:
    """Add fields at every existing object depth without changing known facts."""
    if isinstance(value, dict):
        if "skillc_added_field" in value:
            raise ReferenceError("drift marker already present in reference")
        return {**{k: inject(v) for k, v in value.items()},
                "skillc_added_field": {"nested": [True, {"value": "retained"}]}}
    if isinstance(value, list):
        return [inject(v) for v in value]
    return value


def reports(games: list[Json], payloads: Json) -> dict[int, Json]:
    result = {}
    for game in games:
        sources = {}
        for source in snapshot.SOURCE_IDS:
            url = snapshot.endpoint(source, game["id"])
            sources[source] = ({"source_id": source, "endpoint": url,
                                "availability": "AVAILABLE", "retrieved_at_utc": snapshot.utc_now(),
                                "payload_sha256": snapshot.sha256(json.dumps(payloads[route(url)], sort_keys=True).encode()),
                                "reason": ""}, payloads[route(url)])
        result[game["id"]] = oracle.GameOracle(game, sources).reconcile()
    return result


def scenarios(root: Path, manifest_sha256: str, sample: list[int], plants: list[Json]) -> list[Json]:
    """Validate declared private mutations against the actual oracle before use.

    Recipes name existing JSON paths, original values and replacements. They
    are controller material, never provided to the delivered project. Side
    effects in other families must match the oracle too.
    """
    if snapshot.sha256((root / "manifest.json").read_bytes()) != manifest_sha256:
        raise ReferenceError("reference manifest pin mismatch")
    manifest, population = snapshot.load(root)
    ids = {g["id"] for g in manifest["games"]}
    if len(sample) < 2 or len(set(sample)) != len(sample) or not set(sample) <= ids:
        raise ReferenceError("replay needs at least two distinct declared games")
    if len(plants) != 8 or {p.get("family_id") for p in plants} != set(oracle.FAMILIES):
        raise ReferenceError("declare exactly one plant per F1-F8")
    games = [g for g in manifest["games"] if g["id"] in sample]
    payloads: Json = {}
    for identity, sources in population.items():
        for name, (entry, data) in sources.items():
            if name == "schedule":
                if data is None:
                    raise ReferenceError("replay schedule unavailable")
                data = copy.deepcopy(data)
                for day in data["gameWeek"]:
                    day["games"] = [g for g in day["games"] if g.get("id") in sample]
            elif identity not in sample:
                continue
            if data is None:
                raise ReferenceError("replay requires available sources")
            payloads[route(entry["endpoint"])] = copy.deepcopy(data)
            if name == "schedule":
                for day in data["gameWeek"]:
                    # Same measured page shape for any date in its coverage.
                    payloads.setdefault(route(snapshot.endpoint("schedule", day["date"])), copy.deepcopy(data))
    clean = reports(games, payloads)
    # Clean games must really be clean to measure false positive reports.
    if any(f["status"] != "PASS" for r in clean.values() for f in r["families"]):
        raise ReferenceError("choose clean complete replay games; baseline has non-PASS family")
    result: list[Json] = [{"name": "clean", "payloads": payloads, "expected": clean},
              {"name": "drift", "payloads": {p: inject(v) for p, v in payloads.items()}}]
    result[1]["expected"] = reports(games, result[1]["payloads"])
    for identity in sample:
        if oracle.compare(clean[identity], result[1]["expected"][identity], fresh=True)["status"] != "PASS":
            raise ReferenceError("injected fields changed expected facts")
    for plant in plants:
        identity = plant["game_id"]
        family = plant["family_id"]
        if identity not in sample or plant["source_id"] not in snapshot.SOURCE_IDS:
            raise ReferenceError("plant outside declared population")
        path = plant["path"]
        if not isinstance(path, list) or not path:
            raise ReferenceError("plant requires existing nonempty JSON path")
        altered = copy.deepcopy(payloads)
        value = altered[route(snapshot.endpoint(plant["source_id"], identity))]
        for key in path[:-1]:
            value = value[key]
        if value[path[-1]] != plant["before"] or plant["before"] == plant["after"]:
            raise ReferenceError("plant precondition failed or mutation is empty")
        value[path[-1]] = copy.deepcopy(plant["after"])
        expected = reports(games, altered)
        target = next(f for f in expected[identity]["families"] if f["family_id"] == family)
        if target["status"] != "DISCREPANCY":
            raise ReferenceError(f"plant did not produce {family} DISCREPANCY")
        for other in set(sample) - {identity}:
            if oracle.compare(clean[other], expected[other], fresh=True)["status"] != "PASS":
                raise ReferenceError("plant changed an undeclared game")
        result.append({"name": family, "game_id": identity, "payloads": altered, "expected": expected})
    return result


def safe_file(root: Path, relative: str) -> Path:
    path = root / relative
    if (not relative or Path(relative).is_absolute() or ".." in Path(relative).parts
            or not path.resolve().is_relative_to(root.resolve())
            or any(p.is_symlink() for p in [path, *path.parents] if p != root.parent)):
        raise ReferenceError("unsafe artifact path")
    if not stat.S_ISREG(path.stat().st_mode) or path.stat().st_size > 64 * 1024 * 1024:
        raise ReferenceError("artifact must be a bounded regular file")
    return path


def grade(case: Json, output: Path, adapter: Json, *, requested: list[str] | None = None) -> Json:
    """Read ordinary delivered exports via controller-selected path mapping.

    Payload equality is structural JSON equality, preserving every field and
    list member, but allowing equivalent serialization. No injected markers
    alone can substitute for the retained complete source records.
    """
    reasons = []
    try:
        retained = adapter["payloads"]
        observed = set(case["payloads"] if requested is None else requested)
        required = {route(snapshot.endpoint(source, identity)) for identity in case["expected"]
                    for source in snapshot.SOURCE_IDS}
        schedules = {path for path in observed if path.startswith("/v1/schedule/")}
        if not required <= observed or not schedules or not observed <= set(case["payloads"]):
            raise ReferenceError("retriever did not request schedule and every required game source")
        if not observed <= set(retained):
            raise ReferenceError("retained-source mapping missing requested endpoint")
        for endpoint in observed:
            expected = case["payloads"][endpoint]
            actual = json.loads(safe_file(output, retained[endpoint]).read_text())
            if json.dumps(actual, sort_keys=True) != json.dumps(expected, sort_keys=True):
                reasons.append(f"retained payload differs: {endpoint}")
        exported = json.loads(safe_file(output, adapter["reconciliation"]).read_text())
        games = exported["games"]
        if (not isinstance(games, list) or len(games) != len(case["expected"])
                or {g["game_id"] for g in games} != set(case["expected"])):
            raise ReferenceError("reconciliation game population differs")
        for candidate in games:
            comparison = oracle.compare(case["expected"][candidate["game_id"]], candidate, fresh=True)
            if comparison["status"] != "PASS":
                reasons.append(f"reconciliation differs for game {candidate['game_id']}: {comparison}")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        reasons.append(f"missing/invalid documented export: {exc}")
    return {"name": case["name"], "status": "FAIL" if reasons else "PASS", "reasons": reasons}


Run = Callable[[list[str], float], subprocess.CompletedProcess[str]]


def run_command(argv: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    # Bound captured bytes as well as wall time. Killing the Docker client alone
    # does not stop an exec; execute() always removes its owned container later.
    with subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          start_new_session=True) as process:
        assert process.stdout is not None and process.stderr is not None
        buffers = {process.stdout.fileno(): bytearray(), process.stderr.fileno(): bytearray()}
        deadline = time.monotonic() + timeout
        try:
            with selectors.DefaultSelector() as selector:
                for stream in buffers:
                    selector.register(stream, selectors.EVENT_READ)
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise subprocess.TimeoutExpired(argv, timeout)
                    for key, _ in selector.select(min(remaining, .1)):
                        chunk = os.read(key.fd, 65536)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        buffers[key.fd].extend(chunk)
                        if sum(len(value) for value in buffers.values()) > 4 * 1024 * 1024:
                            raise _CaptureLimit("harness-output-cap: command exceeded the harness output capture limit (four MiB capture cap; #639 approval pending)")
                returncode = process.wait(timeout=max(.001, deadline - time.monotonic()))
        except BaseException:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            raise
        return subprocess.CompletedProcess(argv, returncode,
            buffers[process.stdout.fileno()].decode('utf-8', errors='replace'),
            buffers[process.stderr.fileno()].decode('utf-8', errors='replace'))


def validate_adapter(project: Path, adapter: Json) -> None:
    try:
        readme = safe_file(project, adapter["readme"]).read_text()
    except FileNotFoundError as exc:
        raise _CandidateFailure("documented README missing") from exc
    commands = adapter.get("commands")
    if (not isinstance(commands, list) or not commands
            or any(not isinstance(c, str) or not c.strip() for c in commands)):
        raise ReferenceError("invalid controller command mapping")
    if any(command not in readme for command in commands):
        raise _CandidateFailure("documented install/retrieve/reconcile/export entry points missing")
    environment = adapter.get("base_env")
    placeholder = adapter.get("api_base_placeholder")
    if environment is not None and (not isinstance(environment, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", environment)):
        raise ReferenceError("invalid documented endpoint override environment name")
    if environment is None and placeholder is None:
        raise ReferenceError("controller endpoint override mapping absent")
    if not ((environment and environment in readme) or
            (isinstance(placeholder, str) and placeholder and any(placeholder in c for c in commands))):
        raise _CandidateFailure("endpoint override absent from README")
    extractions = adapter.get("controller_extract_commands", [])
    if not isinstance(extractions, list) or any(not isinstance(c, str) or not c.strip() for c in extractions):
        raise ReferenceError("invalid controller source extraction commands")
    # Export path belongs to the candidate container, not a host mount.
    export = adapter["export_dir"]
    if not isinstance(export, str) or not export.startswith("/project/") or ".." in Path(export).parts:
        raise ReferenceError("export directory must be under /project")


class DockerReplay:
    """Two containers on one internal network, no host/custody mounts.

    Images must be preloaded and digest-pinned. Candidate installation therefore
    uses dependencies already in its image, not undeclared internet access.
    """
    def __init__(self, candidate_image: str, server_image: str, *, timeout: float = 120,
                 run: Run = run_command) -> None:
        for image in (candidate_image, server_image):
            if not re.fullmatch(r"[^\s]+@sha256:[0-9a-f]{64}", image):
                raise ReferenceError("replay images must be pinned by SHA-256 digest")
        if not 0 < timeout <= 3600:
            raise ReferenceError("invalid replay wall-time cap")
        self.candidate_image, self.server_image = candidate_image, server_image
        self.timeout, self.run = timeout, run

    def execute(self, project: Path, adapter: Json, case: Json, evidence: Path) -> Json:
        evidence.mkdir(parents=True, exist_ok=False)
        try:
            custody(project, evidence)
            validate_adapter(project, adapter)
        except _CandidateFailure as exc:
            verdict = {"name": case["name"], "status": "FAIL", "reasons": [str(exc)]}
            (evidence / "verdict.json").write_text(json.dumps(verdict, indent=2))
            return verdict
        except (OSError, ValueError, KeyError, TypeError) as exc:
            verdict = {"name": case["name"], "status": "UNKNOWN",
                       "reasons": ["controller replay configuration unavailable: " + str(exc)]}
            (evidence / "verdict.json").write_text(json.dumps(verdict, indent=2))
            return verdict
        token = "nhl-replay-" + uuid.uuid4().hex
        network, server, candidate = token, token + "-source", token + "-candidate"
        transcript: list[Json] = []
        deadline = time.monotonic() + self.timeout
        try:
            terminations = _Terminations(evidence, candidate)
        except OSError:
            verdict = {"name": case["name"], "status": "UNKNOWN",
                       "reasons": ["controller termination journal unavailable"]}
            (evidence / "verdict.json").write_text(json.dumps(verdict, indent=2))
            (evidence / "execution.json").write_text(json.dumps({"commands": [], "cleanup": [],
                                                               "error": "journal unavailable before launch"}, indent=2))
            return verdict
        documented_entrypoint: str | None = None

        def call(args: list[str], *, candidate_command: bool = False) -> str:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise InfrastructureError("replay exceeded the harness wall-time limit (#639 approval pending)")
            def candidate_failure(*, command_exit: int | None, timed_out: bool) -> None:
                # The controller has not requested candidate stop at this point.
                # Only the runtime inspect response, never candidate stdout,
                # can establish the container's terminal or memory-limit state.
                inspection = ["docker", "inspect", "--format", "{{json .State}}", candidate]
                try:
                    state = self.run(inspection, 3)
                except (OSError, ValueError, subprocess.SubprocessError) as exc:
                    terminations.cutoff("candidate runtime inspect or transport unavailable")
                    transcript.append({"argv": inspection[1:], "error": "runtime inspect unavailable"})
                    raise InfrastructureError("candidate runtime state unconfirmed") from exc
                transcript.append({"argv": inspection[1:], "returncode": state.returncode,
                                   "stdout": state.stdout, "stderr": state.stderr})
                held = terminations.capture(state.stdout)
                _attribute_failure(state, entrypoint=documented_entrypoint or args[-1],
                                   command_exit=command_exit, timed_out=timed_out,
                                   candidate=candidate, evidence=held)

            if candidate_command:
                if documented_entrypoint is None:
                    raise InfrastructureError('documented invocation not recorded')
                terminations.begin(documented_entrypoint)
            if args[0] in ('stop', 'kill', 'restart') and candidate in args:
                terminations.signal(args[0])
            try:
                completed = self.run(["docker", *args], remaining)
            except _CaptureLimit:
                transcript.append({"argv": args, "error": "harness output capture limit"})
                terminations.cutoff("harness output capture limit (#639 approval pending)")
                raise
            except subprocess.TimeoutExpired as exc:
                transcript.append({"argv": args, "error": "timeout"})
                if candidate_command:
                    terminations.timeout()
                    candidate_failure(command_exit=None, timed_out=True)
                raise InfrastructureError("replay exceeded the harness wall-time limit (#639 approval pending)") from exc
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                transcript.append({"argv": args, "error": "controller command transport unavailable"})
                terminations.cutoff("controller command transport unavailable")
                raise InfrastructureError("controller command transport unavailable") from exc
            transcript.append({"argv": args, "returncode": completed.returncode,
                               "stdout": completed.stdout, "stderr": completed.stderr})
            if completed.returncode:
                if candidate_command:
                    candidate_failure(command_exit=completed.returncode, timed_out=False)
                raise InfrastructureError(f"Docker operation failed: {args[0]} (exit {completed.returncode})")
            return completed.stdout

        try:
            # Never pull images or attach to a pre-existing shared network.
            call(["network", "create", "--internal", network])
            limits = ["--pull=never", "--cap-drop=ALL", "--security-opt=no-new-privileges",
                      "--pids-limit=128", "--memory=512m", "--cpus=1", "--network", network,
                      "--no-healthcheck", "--log-driver=none"]
            call(["create", *limits, "--name", server, "--network-alias", "nhl-source",
                  "--entrypoint", "python3", "--", self.server_image, "/server.py", "--payloads", "/payloads.json",
                  "--access-log", "/access.jsonl"])
            with tempfile.TemporaryDirectory() as temporary:
                data = Path(temporary) / "payloads.json"
                data.write_text(json.dumps(case["payloads"]))
                call(["cp", str(data), f"{server}:/payloads.json"])
            call(["cp", str(Path(__file__).with_name("nhl_serve.py")), f"{server}:/server.py"])
            call(["start", server])
            environment = (["--env", adapter["base_env"] + "=http://nhl-source:8080"] if adapter.get("base_env") else [])
            call(["create", *limits, "--name", candidate, "--workdir", "/project",
                  *environment,
                  "--entrypoint", "python3", "--", self.candidate_image,
                  "-c", "import time; time.sleep(3600)"])
            call(["cp", str(project) + "/.", f"{candidate}:/project"])
            call(["start", candidate])
            # Readiness is checked from the same isolated network, no host port.
            ready = ("import socket,time\n"
                     "for i in range(50):\n"
                     " try: socket.create_connection(('nhl-source',8080),timeout=1).close(); break\n"
                     " except OSError: time.sleep(.1)\n"
                     "else: raise SystemExit('source server unavailable')")
            call(["exec", candidate, "python3", "-c", ready])
            for command in adapter["commands"]:
                if adapter.get("api_base_placeholder"):
                    command = command.replace(adapter["api_base_placeholder"], "http://nhl-source:8080")
                documented_entrypoint = command
                call(["exec", candidate, "/bin/sh", "-eu", "-c", command], candidate_command=True)
            # Trusted adapter extraction reads existing retained source records;
            # it is not a delivered entry point or a replacement reconciler.
            for command in adapter.get("controller_extract_commands", []):
                call(["exec", candidate, "/bin/sh", "-eu", "-c", command])
            check_export = "from pathlib import Path;raise SystemExit(0 if Path(" + repr(adapter["export_dir"]) + ").is_dir() else 71)"
            call(["exec", candidate, "python3", "-c", check_export], candidate_command=True)
            # Stop delivered code before collecting files; no live writer races.
            call(["stop", "--time", "1", candidate])
            output = evidence / "output"
            output.mkdir()
            call(["cp", f"{candidate}:{adapter['export_dir']}/.", str(output)])
            call(["stop", "--time", "1", server])
            access_log = evidence / "access.jsonl"
            call(["cp", f"{server}:/access.jsonl", str(access_log)])
            requested = [json.loads(line) for line in access_log.read_text().splitlines()]
            verdict = grade(case, output, adapter, requested=requested)
        except _CandidateFailure as exc:
            verdict = {"name": case["name"], "status": "FAIL", "reasons": [str(exc)]}
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
            verdict = {"name": case["name"], "status": "UNKNOWN", "reasons": [str(exc)]}
        finally:
            # Cleanup is independent of the exhausted execution deadline.
            cleanup = []
            for args in (["rm", "-f", candidate, server], ["network", "rm", network]):
                try:
                    journal_error = None
                    if args[0] == "rm" and candidate in args:
                        try:
                            terminations.signal("cleanup-rm-force")
                        except OSError:
                            # A failed journal must not strand owned containers.
                            # This is after the attribution interval closed.
                            journal_error = "cleanup termination record unavailable"
                    receipt = self.run(["docker", *args], 30)
                    cleanup.append({"argv": args, "returncode": receipt.returncode,
                                    "stdout": receipt.stdout, "stderr": receipt.stderr,
                                    "journal_error": journal_error})
                except (OSError, ValueError, subprocess.SubprocessError) as exc:
                    cleanup.append({"argv": args, "error": str(exc)})
            (evidence / "execution.json").write_text(json.dumps({"commands": transcript, "cleanup": cleanup}, indent=2))
        if any(c.get("returncode") != 0 for c in cleanup):
            verdict = {"name": case["name"], "status": "UNKNOWN",
                       "reasons": ["container/network cleanup unconfirmed"], "candidate_verdict": verdict}
        (evidence / "verdict.json").write_text(json.dumps(verdict, indent=2))
        return verdict


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("selftest", help="trusted committed model-free HTTP/SQLite controls")
    run = commands.add_parser("run", help="explicit isolated delivered-project replays")
    run.add_argument("--reference", type=Path, required=True)
    run.add_argument("--manifest-sha256", required=True)
    run.add_argument("--sample", type=int, nargs="+", required=True)
    run.add_argument("--goal", type=Path, required=True)
    run.add_argument("--plants", type=Path, required=True)
    run.add_argument("--project", type=Path, required=True)
    run.add_argument("--adapter", type=Path, required=True)
    run.add_argument("--candidate-image", required=True)
    run.add_argument("--server-image", required=True)
    run.add_argument("--timeout", type=float, default=120)
    run.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "selftest":
            from .nhl_rerun_control import qualify

            result = qualify()
            print(json.dumps(result, sort_keys=True))
            return 0
        custody(args.project, args.reference, args.plants, args.adapter, args.evidence)
        cases = scenarios(args.reference, args.manifest_sha256, args.sample, json.loads(args.plants.read_text()))
        frozen = {path: snapshot.sha256(path.read_bytes()) for path in (args.goal, args.adapter, args.plants)}
        adapter = json.loads(args.adapter.read_text())
        executor = DockerReplay(args.candidate_image, args.server_image, timeout=args.timeout)
        args.evidence.mkdir(parents=True, exist_ok=False)
        results = [executor.execute(args.project, adapter, case, args.evidence / case["name"]) for case in cases]
        if any(snapshot.sha256(path.read_bytes()) != digest for path, digest in frozen.items()):
            raise ReferenceError("controller declaration inputs changed during replay")
        status = "UNKNOWN" if any(r["status"] == "UNKNOWN" for r in results) else "FAIL" if any(r["status"] == "FAIL" for r in results) else "PASS"
        result = {"status": status, "manifest_sha256": args.manifest_sha256,
                  "goal_sha256": snapshot.sha256(args.goal.read_bytes()),
                  "adapter_sha256": snapshot.sha256(args.adapter.read_bytes()),
                  "plants_sha256": snapshot.sha256(args.plants.read_bytes()),
                  "code_sha256": {name: snapshot.sha256(Path(path).read_bytes()) for name, path in
                                  (("replay", __file__), ("oracle", oracle.__file__),
                                   ("snapshot", snapshot.__file__),
                                   ("server", str(Path(__file__).with_name("nhl_serve.py"))))},
                  "sample": args.sample, "cases": results}
        (args.evidence / "report.json").write_text(json.dumps(result, indent=2))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result = {"status": "UNKNOWN", "reason": str(exc)}
    print(json.dumps(result, sort_keys=True))
    return {"PASS": 0, "FAIL": 1, "UNKNOWN": 2}[result["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
