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
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from . import nhl_oracle as oracle
from . import nhl_snapshot as snapshot
from .nhl_snapshot import Json, ReferenceError


class InfrastructureError(ReferenceError):
    """Controller execution failed; no candidate verdict can be inferred."""


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
                            raise ReferenceError("command output exceeds four MiB capture cap")
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
    readme = safe_file(project, adapter["readme"]).read_text()
    commands = adapter.get("commands")
    if (not isinstance(commands, list) or not commands
            or any(not isinstance(c, str) or not c.strip() or c not in readme for c in commands)):
        raise ReferenceError("documented install/retrieve/reconcile/export entry points missing")
    environment = adapter.get("base_env")
    placeholder = adapter.get("api_base_placeholder")
    if environment is not None and (not isinstance(environment, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", environment)):
        raise ReferenceError("invalid documented endpoint override environment name")
    if not ((environment and environment in readme) or
            (isinstance(placeholder, str) and placeholder and any(placeholder in c for c in commands))):
        raise ReferenceError("endpoint override absent from README")
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
        except (OSError, ValueError, KeyError, TypeError) as exc:
            verdict = {"name": case["name"], "status": "FAIL", "reasons": [str(exc)]}
            (evidence / "verdict.json").write_text(json.dumps(verdict, indent=2))
            return verdict
        token = "nhl-replay-" + uuid.uuid4().hex
        network, server, candidate = token, token + "-source", token + "-candidate"
        transcript: list[Json] = []
        deadline = time.monotonic() + self.timeout

        def call(args: list[str], *, candidate_command: bool = False) -> str:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ReferenceError("replay exceeded whole-case wall-time cap")
            try:
                completed = self.run(["docker", *args], remaining)
            except subprocess.TimeoutExpired as exc:
                transcript.append({"argv": args, "error": "timeout"})
                if candidate_command:
                    state = self.run(["docker", "inspect", "--format", "{{.State.Running}}", candidate], 3)
                    transcript.append({"argv": ["inspect", candidate], "returncode": state.returncode,
                                       "stdout": state.stdout, "stderr": state.stderr})
                    if state.returncode == 0 and state.stdout.strip() == "true":
                        raise ReferenceError("documented entry point exceeded declared wall-time cap") from exc
                raise
            transcript.append({"argv": args, "returncode": completed.returncode,
                               "stdout": completed.stdout, "stderr": completed.stderr})
            if completed.returncode:
                if candidate_command:
                    state = self.run(["docker", "inspect", "--format", "{{.State.Running}}", candidate], max(.001, deadline - time.monotonic()))
                    transcript.append({"argv": ["inspect", candidate], "returncode": state.returncode,
                                       "stdout": state.stdout, "stderr": state.stderr})
                    if state.returncode == 0 and state.stdout.strip() == "true":
                        raise ReferenceError(f"documented entry point failed (exit {completed.returncode})")
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
                call(["exec", candidate, "/bin/sh", "-eu", "-c", command], candidate_command=True)
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
        except (OSError, InfrastructureError, subprocess.SubprocessError) as exc:
            verdict = {"name": case["name"], "status": "UNKNOWN", "reasons": [str(exc)]}
        except (ValueError, KeyError, TypeError) as exc:
            verdict = {"name": case["name"], "status": "FAIL", "reasons": [str(exc)]}
        finally:
            # Cleanup is independent of the exhausted execution deadline.
            cleanup = []
            for args in (["rm", "-f", candidate, server], ["network", "rm", network]):
                try:
                    receipt = self.run(["docker", *args], 30)
                    cleanup.append({"argv": args, "returncode": receipt.returncode,
                                    "stdout": receipt.stdout, "stderr": receipt.stderr})
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
        adapter = json.loads(args.adapter.read_text())
        executor = DockerReplay(args.candidate_image, args.server_image, timeout=args.timeout)
        args.evidence.mkdir(parents=True, exist_ok=False)
        results = [executor.execute(args.project, adapter, case, args.evidence / case["name"]) for case in cases]
        status = "UNKNOWN" if any(r["status"] == "UNKNOWN" for r in results) else "FAIL" if any(r["status"] == "FAIL" for r in results) else "PASS"
        result = {"status": status, "manifest_sha256": args.manifest_sha256, "sample": args.sample, "cases": results}
        (args.evidence / "report.json").write_text(json.dumps(result, indent=2))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result = {"status": "UNKNOWN", "reason": str(exc)}
    print(json.dumps(result, sort_keys=True))
    return {"PASS": 0, "FAIL": 1, "UNKNOWN": 2}[result["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
