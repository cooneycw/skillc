"""Deterministic production-path campaign for the #270 Level-3 flow-check tasks (#375).

Each row of a frozen manifest is one real attempt through the PRODUCTION path:
the profile treatment (`calibration_run.build_treatment`), closure delivery,
in-container preflight, the controller `GateWitness`, capture and grading
(`collection_conformance.run_level1_agent_attempt`, which is
`agent_trial.run_one_attempt` with the task's own grader). Only the client is
replaced: a scripted actor stands in for the model. It writes a client-shaped
transcript (the repository's committed fake client), places one committed
candidate tree in `/work`, and calls the skill's two prescribed gate
invocations through the installed gate entrypoint, exactly as an agent
following `reference.md` would. No model is contacted: the actor makes no
network call, the agent container runs on network `none`, and the credential
delivered is a generated dummy.

What a row establishes is bounded. The gate-exercise and integrity probes
trace the candidate's own processes, so a coordinated forgery by a hostile
candidate is not excluded. Production asserts no gate exclusivity, so an
omitted gate run is UNKNOWN, never VIOLATED. A row compares the attempt's
exact per-criterion outcomes with the manifest's frozen expectation and
reports MATCH or MISMATCH; a mismatch is evidence to investigate, never a
reason to relabel the expectation.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import tarfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import calibration_run as cr
from . import collection_conformance as cc
from . import profile, trial, verify
from .docker_backend import CONTAINER_HOME, DockerBackend

KIND = "level3-production-campaign"
SCHEMA = 1
OUTCOMES = frozenset({"SATISFIED", "VIOLATED", "UNKNOWN"})
STATUSES = frozenset({"PASS", "FAIL", "INCONCLUSIVE"})

#: How the actor sequences its edit and the two prescribed gate calls.
#:   fresh     - place the candidate, then plan and summary (an honest run)
#:   stale     - plan and summary on the untouched fixture, THEN place the
#:               candidate: the gate evidence is for an earlier tree
#:   plan-only - place the candidate, run plan, never request the summary
#:   noop      - change nothing but the liveness marker, run no gate
ACTOR_MODES = frozenset({"fresh", "stale", "plan-only", "noop"})

#: Under the candidate's HOME. Not part of the subject: never in
#: `verify_home_files`, and named in the installation receipt as delivered.
HOME_DIR = ".skillc-campaign"
TRANSCRIPT_RELPATH = ".codex/sessions/2026/01/01/rollout-skillc-campaign.jsonl"
FAKE_CLIENT = cr.ROOT / "tests" / "fixtures" / "agent-trial" / "fake_agent_client.py"
GATE_SECONDS = 240
DEFAULT_PRIVATE_ROOT = Path.home() / ".local" / "share" / "skillc" / "level3-campaigns"

#: Runs inside the trial container with its own interpreter; stdlib only. Its
#: working directory is the attempt's workspace (`/work`, which is where
#: `run_one_attempt` starts the agent). argv: mode, gate entrypoint (relative
#: to HOME), then the prompt that `run_one_attempt` appends last. Gate exit codes are not the actor's to
#: judge: the controller witness records every run.
ACTOR_SOURCE = '''\
import os, subprocess, sys, tarfile
mode, entry, prompt = sys.argv[1], sys.argv[2], sys.argv[-1]
home = os.environ["HOME"]
here = os.path.join(home, "@HOME_DIR@")
gate = os.path.join(home, entry)

def place():
    with tarfile.open(os.path.join(here, "candidate.tar")) as archive:
        # The controller built this archive from the task surface; the data
        # filter is extra hardening where this interpreter has it (3.11.4+).
        archive.extractall(os.getcwd(), **({"filter": "data"} if hasattr(tarfile, "data_filter") else {}))

def run_gate(*args):
    try:
        done = subprocess.run([gate, *args], timeout=@GATE_SECONDS@)
        print(f"skillc-campaign: {gate} {' '.join(args)} exited {done.returncode}", file=sys.stderr)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"skillc-campaign: {gate} {' '.join(args)} did not complete: {exc}", file=sys.stderr)

def client():
    subprocess.run([sys.executable, os.path.join(here, "fake_agent_client.py"), "--format", "codex-fake",
                    "--home", home, "--transcript-relpath", "@TRANSCRIPT@", prompt], check=True)

if mode == "stale":
    run_gate("--plan", "check", "--evidence", "flow-check")
    run_gate("--check-summary")
    place()
    client()
elif mode == "noop":
    client()
else:
    place()
    client()
    run_gate("--plan", "check", "--evidence", "flow-check")
    if mode == "fresh":
        run_gate("--check-summary")
'''.replace("@HOME_DIR@", HOME_DIR).replace("@GATE_SECONDS@", str(GATE_SECONDS)).replace(
    "@TRANSCRIPT@", TRANSCRIPT_RELPATH)


class CampaignRefused(ValueError):
    """The manifest is malformed, or what it froze no longer matches the tree."""


@dataclass(frozen=True)
class Row:
    id: str
    task: str
    candidate: str  # a directory under the task, or "fixture" for the no-op
    actor: str
    expected_status: str
    expected_criteria: Mapping[str, str]


@dataclass(frozen=True)
class Manifest:
    data: Mapping[str, Any]
    rows: tuple[Row, ...]

    @property
    def subject(self) -> Mapping[str, Any]:
        return self.data["frozen"]["subject"]

    @property
    def client_version(self) -> str:
        return str(self.data["frozen"]["client"]["version"])

    @property
    def per_attempt_seconds(self) -> float:
        return float(self.data["frozen"]["caps"]["per_attempt_seconds"])


def _need(value: object, kind: type, label: str) -> Any:
    if not isinstance(value, kind) or isinstance(value, bool):
        raise CampaignRefused(f"{label} must be a {kind.__name__}")
    return value


def load_manifest(path: Path) -> Manifest:
    data = _need(json.loads(path.read_text(encoding="utf-8")), dict, "manifest")
    if data.get("kind") != KIND or data.get("schema") != SCHEMA:
        raise CampaignRefused(f"{path} is not a {KIND} schema {SCHEMA} manifest")
    frozen = _need(data.get("frozen"), dict, "frozen")
    for key in ("subject", "client", "caps", "tasks", "runtime"):
        _need(frozen.get(key), dict, f"frozen.{key}")
    rows: list[Row] = []
    seen: set[str] = set()
    for raw in _need(data.get("rows"), list, "rows"):
        raw = _need(raw, dict, "row")
        row_id = _need(raw.get("id"), str, "row.id")
        if row_id in seen:
            raise CampaignRefused(f"row {row_id!r} is declared twice")
        seen.add(row_id)
        task = _need(raw.get("task"), str, f"{row_id}.task")
        if task not in frozen["tasks"]:
            raise CampaignRefused(f"row {row_id!r} names task {task!r}, which frozen.tasks does not identify")
        actor = _need(raw.get("actor"), str, f"{row_id}.actor")
        if actor not in ACTOR_MODES:
            raise CampaignRefused(f"row {row_id!r}: actor {actor!r} is not one of {sorted(ACTOR_MODES)}")
        expected = _need(raw.get("expected"), dict, f"{row_id}.expected")
        status = _need(expected.get("status"), str, f"{row_id}.expected.status")
        criteria = _need(expected.get("criteria"), dict, f"{row_id}.expected.criteria")
        if status not in STATUSES or not criteria or set(criteria.values()) - OUTCOMES:
            raise CampaignRefused(f"row {row_id!r}: expected status/criteria are not well-formed")
        candidate = _need(raw.get("candidate"), str, f"{row_id}.candidate")
        if (candidate == "fixture") != (actor == "noop"):
            raise CampaignRefused(f"row {row_id!r}: only a noop row grades the untouched fixture")
        rows.append(Row(row_id, task, candidate, actor, status, dict(criteria)))
    if not rows:
        raise CampaignRefused("manifest declares no rows; an empty population certifies nothing")
    return Manifest(data, tuple(rows))


def task_identity(task_root: Path) -> dict[str, object]:
    """The task content identity the calibration path binds: goal, grader, fixture."""
    goal = (task_root / "goal.md").read_bytes()
    grader = verify.GraderDef.load(task_root)
    identity = cr.task_content_identity(goal, grader, cc.task_surface(task_root / "fixture"))
    return {**identity, "grader_id": grader.id, "grader_revision": grader.revision}


def candidate_files(task_root: Path, row: Row) -> list[tuple[str, bytes, bool]]:
    if row.actor == "noop":
        return []
    return cc.task_surface(task_root / row.candidate)


def check_frozen(manifest: Manifest, root: Path) -> list[str]:
    """Every frozen identity that no longer matches the tree, as a sentence each.
    An empty list is the only answer that permits a run."""
    problems: list[str] = []
    frozen = manifest.data["frozen"]
    for name, identity in frozen["tasks"].items():
        task_root = root / "evals" / "level3" / name
        measured = task_identity(task_root)
        if measured != identity:
            problems.append(f"task {name}: frozen identity {identity} != measured {measured}")
    subject = frozen["subject"]
    profile_dir = root / str(subject["profile"])
    inventory = json.loads((profile_dir / "evidence" / "inventory.json").read_text(encoding="utf-8"))
    if profile.inventory_digest(inventory) != subject["inventory_digest"]:
        problems.append(f"subject profile {subject['profile']}: inventory digest moved")
    pinned = json.loads((profile_dir / "subject.json").read_text(encoding="utf-8"))
    if pinned.get("revision") != subject["revision"]:
        problems.append(f"subject profile {subject['profile']}: revision {pinned.get('revision')} != frozen")
    policy = json.loads((root / "skillc" / "runtime-policy.json").read_text(encoding="utf-8"))
    for key, value in frozen["runtime"].items():
        if policy.get(key) != value:
            problems.append(f"runtime policy {key}: {policy.get(key)!r} != frozen {value!r}")
    if frozen.get("harness_digest") != harness_digest():
        problems.append("the scripted actor or fake client changed since the manifest was frozen")
    for row in manifest.rows:
        task_root = root / "evals" / "level3" / row.task
        if row.actor != "noop" and not (task_root / row.candidate).is_dir():
            problems.append(f"row {row.id}: candidate {row.task}/{row.candidate} does not exist")
    return problems


def harness_digest() -> str:
    return "sha256:" + hashlib.sha256((ACTOR_SOURCE + FAKE_CLIENT.read_text(encoding="utf-8")).encode()).hexdigest()


def _tarball(files: list[tuple[str, bytes, bool]]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for relpath, data, executable in sorted(files):
            info = tarfile.TarInfo(relpath)
            info.size, info.mode, info.mtime = len(data), 0o755 if executable else 0o644, 0
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def row_home_files(row: Row, task_root: Path) -> dict[str, bytes]:
    files = {f"{HOME_DIR}/actor.py": ACTOR_SOURCE.encode(), f"{HOME_DIR}/fake_agent_client.py": FAKE_CLIENT.read_bytes()}
    if row.actor != "noop":
        files[f"{HOME_DIR}/candidate.tar"] = _tarball(candidate_files(task_root, row))
    return files


def actor_argv(row: Row, gate_entrypoint: str, interpreter: str = "/usr/bin/python3") -> list[str]:
    """The BASE argv; `run_one_attempt` appends the prompt last."""
    return [interpreter, f"{CONTAINER_HOME}/{HOME_DIR}/actor.py", row.actor, gate_entrypoint]


def dummy_credential(path: Path) -> Path:
    """A syntactically valid, never-signed Codex credential. It satisfies the
    delivery precondition and authorises nothing; its 30-day life outlasts
    any campaign, since every attempt re-reads it."""
    def seg(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()
    header = seg(json.dumps({"alg": "none"}).encode())
    payload = seg(json.dumps({"exp": int(time.time() + 30 * 86400)}).encode())
    token = f"{header}.{payload}.unsigned"
    path.write_text(json.dumps({"tokens": {"access_token": token}, "skillc_campaign": "dummy"}), encoding="utf-8")
    path.chmod(0o600)
    return path


def compare(row: Row, graded: Mapping[str, Any] | None) -> list[str]:
    """Each difference between the frozen expectation and what was graded.
    An attempt that was never graded is a difference, not an absence of one."""
    if not isinstance(graded, Mapping):
        return ["the attempt was not graded"]
    diffs: list[str] = []
    if graded.get("status") != row.expected_status:
        diffs.append(f"status {graded.get('status')!r} != expected {row.expected_status!r}")
    actual = {str(c.get("id")): str(c.get("outcome")) for c in graded.get("criteria", []) if isinstance(c, Mapping)}
    for criterion in sorted(set(row.expected_criteria) | set(actual)):
        want, got = row.expected_criteria.get(criterion), actual.get(criterion)
        if want != got:
            diffs.append(f"{criterion}: {got!r} != expected {want!r}")
    return diffs


def plan(manifest: Manifest, store: Path, root: Path, *, image_digest: str, treatment_digest: str,
         rows: Sequence[Row]) -> tuple[trial.Experiment, dict[str, str]]:
    trials = []
    for row in rows:
        grader = verify.GraderDef.load(root / "evals" / "level3" / row.task)
        trials.append({
            "label": row.id, "case": {"id": row.task, "revision": grader.revision}, "grader": grader.identity(),
            "subject": {"digest": treatment_digest}, "client": {"name": "codex", "version": manifest.client_version},
            "image": {"digest": image_digest}, "config": {"candidate": row.candidate, "actor": row.actor},
            "attempts": 1,
        })
    experiment = trial.plan({"experiment": "level3-campaign", "trials": trials}, store)
    pairs = list(experiment.attempts())
    if len(pairs) != len(rows):
        raise CampaignRefused(f"the plan issued {len(pairs)} attempts for {len(rows)} rows")
    by_row: dict[str, str] = {}
    for row, (planned, attempt) in zip(rows, pairs, strict=True):
        # `trial.plan` names each trial `t<n>-<label>`, in plan order.
        if not str(planned.get("trial_id", "")).endswith(f"-{row.id}"):
            raise CampaignRefused(f"planned trial {planned.get('trial_id')!r} is not row {row.id!r}")
        by_row[row.id] = str(attempt["attempt_id"])
    return experiment, by_row


def run_rows(
    manifest: Manifest, *, root: Path, run_dir: Path, treatment: cr.Treatment,
    backends: Callable[[], tuple[DockerBackend, DockerBackend]], image_digest: str,
    rows: Sequence[Row] | None = None, interpreter: str = "/usr/bin/python3",
    on_row: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Run each row once, in manifest order, and return the campaign report."""
    if treatment.gate_entrypoint is None:
        raise CampaignRefused("the treatment declares no gate_entrypoint; nothing would witness the gates")
    selected = list(manifest.rows if rows is None else rows)
    store = trial.open_store(run_dir / "store", forbidden=[])
    experiment, attempt_ids = plan(manifest, store, root, image_digest=image_digest,
                                   treatment_digest=treatment.digest, rows=selected)
    credential = dummy_credential(run_dir / "codex-credential.dummy.json")
    results: list[dict[str, Any]] = []
    for row in selected:
        task_root = root / "evals" / "level3" / row.task
        agent, grading = backends()
        goal = (task_root / "goal.md").read_text(encoding="utf-8")
        started = time.monotonic()
        outcome = cc.run_level1_agent_attempt(
            experiment=experiment, attempt_id=attempt_ids[row.id], backend=agent, grading_backend=grading,
            base=run_dir, base_argv=actor_argv(row, treatment.gate_entrypoint, interpreter),
            extra_home_files={**treatment.home_files, **row_home_files(row, task_root)},
            client="codex", cli_version=manifest.client_version, task_root=task_root,
            surface=cc.surface_mapping(cc.task_surface(task_root / "fixture")), prompt=goal,
            timeout=manifest.per_attempt_seconds, credential_explicit_path=credential,
            receipt_context=treatment.receipt_context, verify_home_files=treatment.verify_home_files,
            preflight_tools=treatment.preflight_tools, gate_entrypoint=treatment.gate_entrypoint,
        )
        graded = outcome.get("graded")
        diffs = compare(row, graded if isinstance(graded, Mapping) else None)
        result = {
            "row": row.id, "task": row.task, "candidate": row.candidate, "actor": row.actor,
            "attempt_id": attempt_ids[row.id], "disposition": outcome.get("disposition"),
            "reason": outcome.get("reason"), "grading_blocked_reason": outcome.get("grading_blocked_reason"),
            "graded": graded,
            "result_status": graded.get("result_status") if isinstance(graded, Mapping) else None,
            "expected": {"status": row.expected_status, "criteria": dict(row.expected_criteria)},
            "verdict": "MATCH" if not diffs else "MISMATCH", "differences": diffs,
            "seconds": round(time.monotonic() - started, 1),
        }
        results.append(result)
        if on_row is not None:
            on_row(result)
    return {
        "kind": f"{KIND}-report", "schema": SCHEMA, "experiment_id": experiment.id,
        "image_digest": image_digest, "treatment_digest": treatment.digest,
        "rows": results, "matched": sum(r["verdict"] == "MATCH" for r in results), "population": len(results),
    }
