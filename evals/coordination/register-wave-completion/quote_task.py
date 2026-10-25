"""Independent trusted-scripted quote qualification, not a wave runner (#571P)."""

from __future__ import annotations

import dataclasses
import hashlib
import itertools
import json
import math
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import Any

from skillc import git_snapshot, trial, verify

HERE = Path(__file__).resolve().parent
ROLES = ("worker-a", "worker-b", "service")
PATHS = {"worker-a": "src/subtotal.py", "worker-b": "src/tax.py"}
CASE_IDS = ("healthy", "alternate", "reverse", "alternate-reverse", "wrong-subtotal", "wrong-tax",
            "missing-patch", "unfinished", "wrong-remote-correct-local", "correct-remote-wrong-local",
            "forged-service-success", "wrong-ancestry", "corrupt-patch", "corrupt-snapshot",
            "missing-snapshot", "unavailable-observation")
EMITTER = "import json,pathlib,sys;v=json.loads(sys.argv[1]);pathlib.Path('actor-report.json').write_text('stopped');" \
          "pathlib.Path('patch.json').write_text(json.dumps(v,separators=(',',':'),ensure_ascii=False)) if v is not None else None"


class Expired(Exception):
    """The common case budget expired, never a new phase budget."""


class Unavailable(Exception):
    """No complete independently readable observation."""


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def definition() -> dict[str, Any]:
    data = json.loads((HERE / "quote-task.json").read_bytes())
    if (data["id"] != "coordination-quote" or data["revision"] != "1"
            or data["domain"] != {"qty": [0, 1, 2, 4], "unit": [0, 1, 7, 123, 199],
                                  "bp": [0, 500, 1300, 5000, 10000]}
            or set(data["seed"]) != {*PATHS.values(), "src/quote.py"}):
        raise ValueError("frozen quote declaration differs")
    population([c["id"] for c in data["cases"]])
    return data


def population(names: list[str]) -> None:
    if not names or len(names) != len(set(names)) or set(names) != set(CASE_IDS):
        raise ValueError("qualification requires the exact nonempty unique case population")


def remaining(deadline: float) -> float:
    value = deadline - time.monotonic()
    if value <= 0:
        raise Expired("completion deadline")
    return value


def git(repo: Path, deadline: float, *args: str, stdin: bytes | None = None) -> str:
    env = {"PATH": os.defpath, "HOME": str(repo), "LC_ALL": "C", "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_TERMINAL_PROMPT": "0", "GIT_ALLOW_PROTOCOL": "file",
           "GIT_AUTHOR_DATE": "2000-01-01T00:00:00+0000", "GIT_COMMITTER_DATE": "2000-01-01T00:00:00+0000"}
    return subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                           "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null",
                           "-c", "gc.auto=0", "-c", "maintenance.auto=false", *args],
                          cwd=repo, env=env, input=stdin, capture_output=True,
                          timeout=remaining(deadline), check=True).stdout.decode().strip()


def seed(work: Path, data: dict[str, Any], deadline: float) -> str:
    repo = work / "repo"
    repo.mkdir()
    for name, text in data["seed"].items():
        target = repo / name
        target.parent.mkdir(exist_ok=True)
        target.write_text(text)
    git(repo, deadline, "init", "--template=", "--initial-branch=main")
    git(repo, deadline, "add", "--all")
    git(repo, deadline, "commit", "-m", "seed")
    return git(repo, deadline, "rev-parse", "HEAD")


def valid_patch(value: Any, role: str, seeds: dict[str, str]) -> bool:
    return (isinstance(value, dict) and set(value) == {"role", "path", "base", "content"}
            and value["role"] == role and value["path"] == PATHS[role]
            and value["base"] == digest(seeds[PATHS[role]].encode())
            and isinstance(value["content"], str) and len(trial.canonical(value)) <= 4096)


def service(config: dict[str, Any]) -> None:
    """One closed transaction on an already controller-created repository."""
    if set(config) != {"patches", "seed", "fault", "order", "deadline"}:
        raise ValueError("closed service configuration")
    patches, seeds, fault, deadline = (config[k] for k in ("patches", "seed", "fault", "deadline"))
    if fault not in CASE_IDS or set(config["order"]) != set(PATHS):
        raise ValueError("closed service mode/order")
    repo = Path("repo")
    first = git(repo, deadline, "rev-parse", "HEAD")
    valid = len(patches) == 2 and all(valid_patch(patches.get(r), r, seeds) for r in PATHS)
    if valid and fault not in {"unfinished", "forged-service-success"}:
        for role in config["order"]:
            (repo / PATHS[role]).write_text(patches[role]["content"])
            git(repo, deadline, "add", "--", PATHS[role])
            git(repo, deadline, "commit", "-m", role)
    head = git(repo, deadline, "rev-parse", "HEAD")
    if fault == "wrong-ancestry":
        tree = git(repo, deadline, "rev-parse", "HEAD^{tree}")
        head = git(repo, deadline, "commit-tree", tree, stdin=b"unrelated\n")
    if fault == "wrong-remote-correct-local":
        head = first
    git(repo, deadline, "update-ref", "refs/heads/delivered", head)
    git(Path.cwd(), deadline, "clone", "--bare", "--no-hardlinks", "--", "repo", "fixture-remote.git")
    git(Path("fixture-remote.git"), deadline, "config", "--remove-section", "remote.origin")
    if fault == "correct-remote-wrong-local":
        (repo / PATHS["worker-a"]).write_text("def subtotal(qty, unit):\n    return -999\n")
    Path("service-claim.json").write_text('{"ok":true,"complete":true}')


def frozen(experiment: trial.Experiment, aid: str) -> list[dict[str, Any]]:
    manifest = json.loads((experiment.root / f"manifest-{aid}.json").read_bytes())
    if manifest["capture_failures"]:
        raise Unavailable("partial capture")
    return trial.frozen_artifacts(experiment, aid)


def patch_value(experiment: trial.Experiment, aid: str) -> Any:
    artifacts = [a for a in frozen(experiment, aid) if a["path"] == "patch.json"]
    if not artifacts:
        return None
    raw = trial.read_object(experiment, artifacts[0]["digest"])
    if len(raw) > 4096:
        return {"invalid_patch": "whole-object-byte-cap", "raw_size": len(raw)}
    return json.loads(raw)


def oracle_inputs(experiment: trial.Experiment, aids: dict[str, str], seeds: dict[str, str],
                  first: str, snapshot: Path) -> tuple[list[tuple[str, bytes, bool]], bytes]:
    """Read only verified captures; no host Git and no service-claim authority."""
    patches = {r: patch_value(experiment, aids[r]) for r in PATHS}
    service_artifacts = frozen(experiment, aids["service"])
    for artifact in service_artifacts:
        rel = PurePosixPath(artifact["path"])
        if rel.is_absolute() or ".." in rel.parts:
            raise Unavailable("unsafe captured path")
        path = snapshot / str(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(trial.read_object(experiment, artifact["digest"]))
    tree = git_snapshot.SafeTree(snapshot)
    remote = git_snapshot.GitDir(tree, "fixture-remote.git")
    remote.check_plain()
    refs = remote.refs()
    head = refs.get("refs/heads/delivered")
    tree_id = remote.tree_of(head) if head is not None else None
    members = remote.tree_files(tree_id) if tree_id is not None else {}
    files, entries = [], {}
    for name, meta in members.items():
        mode, oid = meta.split()
        kind, payload = remote.object(oid) if mode in {"100644", "100755"} else ("not-read", b"")
        entries[name] = {"mode": mode, "oid": oid, "kind": kind}
        if mode in {"100644", "100755"} and kind == "blob":
            files.append((name, payload, mode == "100755"))
    sources = {name: payload for name, payload, _ in files}
    good = (head is not None and first in remote.reachable([head]) and head != first
            and all(entry["mode"] == "100644" and entry["kind"] == "blob" for entry in entries.values())
            and set(sources) == set(seeds) and sources.get("src/quote.py") == seeds["src/quote.py"].encode())
    for role, path in PATHS.items():
        value = patches[role]
        good = good and valid_patch(value, role, seeds) and sources.get(path) == value["content"].encode()
    trusted = {"version": 1, "task": "coordination-quote:1", "service_attempt": aids["service"],
               "seed": first, "head": head, "tree": tree_id, "refs": refs, "entries": entries,
               "delivery": "SATISFIED" if good else "VIOLATED",
               "source": {name: digest(data) for name, data, _ in files},
               "service_manifest": digest((experiment.root / f"manifest-{aids['service']}.json").read_bytes()),
               "patches": [{"role": r, "attempt": aids[r],
                            "manifest": digest((experiment.root / f"manifest-{aids[r]}.json").read_bytes()),
                            "object": next((a["digest"] for a in frozen(experiment, aids[r])
                                            if a["path"] == "patch.json"), None),
                            "value": digest(trial.canonical(patches[r]))} for r in PATHS]}
    if not files:
        # Preserve actual snapshot evidence as the nonempty verifier input.
        # Never substitute expected or local source when delivery is absent.
        files = [(a["path"], trial.read_object(experiment, a["digest"]), False)
                 for a in service_artifacts if a["path"].startswith("fixture-remote.git/")]
    return files, trial.canonical(trusted)


def run_case(name: str, base: Path, *, judge: Path | None = None, budget: float = 30) -> tuple[dict[str, Any], trial.Experiment]:
    deadline = time.monotonic() + budget
    if name not in CASE_IDS or isinstance(budget, bool) or not math.isfinite(budget) or not 0 < budget <= 30:
        raise ValueError("closed case/budget")
    data = definition()
    expected = next(c for c in data["cases"] if c["id"] == name)
    source = Path(__file__).read_bytes()
    experiment = trial.plan({"experiment": "quote-qualification", "trials": [
        {"label": r, "case": {"id": name, "revision": "1"},
         "grader": {"id": "coordination-quote", "revision": "1"},
         "subject": {"digest": digest(source if r == "service" else EMITTER.encode())},
         "client": {"name": "trusted-scripted", "version": sys.version.split()[0]},
         "image": {"digest": "trusted-host-not-isolated"}, "config": {"model": None}, "attempts": 1}
        for r in ROLES]}, trial.open_store(base / "store", []))
    aids = {r: str(a["attempt_id"]) for r, (_, a) in zip(ROLES, experiment.attempts(), strict=True)}
    row: dict[str, Any] = {"id": name, "experiment": experiment.root.name,
                           "expected": expected["status"], "status": "UNKNOWN", "violated": [],
                           "oracle_executed": False, "fault_observed": False, "cleanup_confirmed": True,
                           "oracle_cleanup_confirmed": None, "attempts": {}, "task_digest": digest(trial.canonical(data))}
    try:
        with tempfile.TemporaryDirectory(prefix="quote-", dir=base) as staging:
            stage = Path(staging)
            actor = stage / "service.py"
            actor.write_bytes(source)
            actor.chmod(0o400)
            work = {r: trial.allocate_workspace(experiment, aids[r], base, []) for r in ROLES}
            first = seed(work["service"], data, deadline)
            for role, path in PATHS.items():
                code = data["implementations"][role][int(name in {"alternate", "alternate-reverse"})]
                if name == "wrong-subtotal" and role == "worker-a":
                    code = "def subtotal(qty, unit):\n    return qty + unit\n"
                if name == "wrong-tax" and role == "worker-b":
                    code = "def tax(net, bp):\n    return net * bp // 10000\n"
                value = {"role": role, "path": path, "base": digest(data["seed"][path].encode()), "content": code}
                if name == "missing-patch" and role == "worker-b":
                    value = None
                stop = trial.run_attempt(experiment, aids[role], [sys.executable, "-I", "-c", EMITTER, json.dumps(value)],
                                         work[role], remaining(deadline), grace=0.2)
                if stop["confirmed"] is not True or stop["exit_code"] != 0:
                    raise Unavailable("patch producer unavailable")
                trial.capture(experiment, aids[role], work[role])
            values = {r: patch_value(experiment, aids[r]) for r in PATHS}
            order = list(reversed(PATHS)) if name in {"reverse", "alternate-reverse"} else list(PATHS)
            config = {"patches": {r: v for r, v in values.items() if v is not None}, "seed": data["seed"],
                      "fault": name, "order": order, "deadline": deadline}
            stop = trial.run_attempt(experiment, aids["service"], [sys.executable, "-I", str(actor), json.dumps(config)],
                                     work["service"], remaining(deadline), grace=0.2)
            if stop["reason"] == "timeout":
                raise Expired("service deadline")
            if stop["confirmed"] is not True or stop["exit_code"] != 0:
                raise Unavailable("service unavailable")
            manifest = trial.capture(experiment, aids["service"], work["service"],
                                     limits=trial.Limits(max_total_bytes=1 << 20))
            if name in {"corrupt-patch", "corrupt-snapshot", "missing-snapshot"}:
                artifacts = frozen(experiment, aids["worker-a"]) if name == "corrupt-patch" else manifest["artifacts"]
                target = "patch.json" if name == "corrupt-patch" else "fixture-remote.git/HEAD"
                picked = next(a for a in artifacts if a["path"] == target)
                obj = experiment.object_path(str(picked["digest"]))
                obj.unlink()
                if name != "missing-snapshot":
                    obj.write_bytes(b"injected captured-object corruption")
                row["fault_observed"] = not obj.exists() or digest(obj.read_bytes()) != picked["digest"]
                if not row["fault_observed"]:
                    raise RuntimeError("corruption control did not change its input")
            files, trusted = oracle_inputs(experiment, aids, data["seed"], first, stage / "snapshot")
            grader_root = stage / "grader"
            grader_root.mkdir()
            (grader_root / "grader.json").write_bytes((HERE / "quote-grader.json").read_bytes())
            for filename in ("quote_probe.py", "quote_judge.py"):
                (grader_root / filename).write_bytes((HERE / filename).read_bytes())
            vectors = list(itertools.product(*(data["domain"][k] for k in ("qty", "unit", "bp"))))
            (grader_root / "inputs.json").write_text(json.dumps(vectors))
            grader = verify.GraderDef.load(grader_root)
            if judge is not None:
                grader = grader.with_judge(judge)
            cap = remaining(deadline) / 2
            grader = dataclasses.replace(grader, probe_timeout=min(2, cap), judge_timeout=min(2, cap))
            if name == "unavailable-observation":
                row["fault_observed"] = True
            graded = verify.grade_files(grader, files, base,
                                        trusted_observation=None if name == "unavailable-observation" else trusted)
            row.update(status="UNKNOWN" if graded.status == "INCONCLUSIVE" else graded.status,
                       violated=sorted(graded.violated), oracle_executed=True, criteria=graded.criteria,
                       grade_category=graded.category,
                       containment=graded.containment, grader_digest=grader.digest(), vectors=len(vectors),
                       trusted_digest=None if name == "unavailable-observation" else digest(trusted))
            row["oracle_cleanup_confirmed"] = (graded.containment.get("confirmed") is True
                                                and graded.containment.get("cleanup") == "removed")
            if not row["oracle_cleanup_confirmed"] and row["status"] != "FAIL":
                row["status"] = "UNKNOWN"
    except Expired:
        row.update(status="FAIL", violated=["deadline"], reason="completion deadline")
    except (OSError, ValueError, Unavailable, trial.Refused, verify.Refused,
            git_snapshot.Unreadable, subprocess.SubprocessError) as exc:
        row.update(status="UNKNOWN", reason=type(exc).__name__)
    finally:
        for role, aid in aids.items():
            try:
                events = experiment.events(aid)
                stops = [e for e in events if e["event"] == "stopped"]
                safe = not any(e["event"] == "dispatched" for e in events) or (stops and stops[-1]["confirmed"] is True)
                if safe:
                    cleanup = trial.cleanup_workspace(experiment, aid)
                    row["cleanup_confirmed"] &= not cleanup["errors"] and cleanup["status"] in {"removed", "not-needed", "already-absent"}
                else:
                    row["cleanup_confirmed"] = False
            except (OSError, trial.Refused):
                row["cleanup_confirmed"] = False
            try:
                lifecycle = trial.finalize(experiment, aid)
                row["attempts"][role] = {"id": aid, "lifecycle": lifecycle["disposition"], "cleanup": lifecycle["cleanup"]}
            except (OSError, trial.Refused):
                row["cleanup_confirmed"] = False
                row["attempts"][role] = {"id": aid, "lifecycle": "accounting-unavailable"}
        if not row["cleanup_confirmed"] and row["status"] != "FAIL":
            row["status"] = "UNKNOWN"
    row["on_time"] = time.monotonic() < deadline
    if not row["on_time"] and row["status"] == "PASS":
        row.update(status="FAIL", violated=["deadline"])
    wanted_oracle = name not in {"corrupt-patch", "corrupt-snapshot", "missing-snapshot"}
    row["matches"] = (row["status"] == expected["status"] and row["violated"] == expected["violated"]
                      and row["on_time"] and row["cleanup_confirmed"] and row["oracle_cleanup_confirmed"] is not False
                      and row["oracle_executed"] == wanted_oracle
                      and (expected["status"] != "UNKNOWN" or row["fault_observed"]))
    return row, experiment


def qualify(base: Path, *, cases: list[str] | None = None, judge: Path | None = None) -> dict[str, Any]:
    """No empty/subset qualification; certify statuses AND violated criteria."""
    names = list(CASE_IDS) if cases is None else cases
    population(names)
    rows = [run_case(name, base, judge=judge)[0] for name in names]
    return {"certified": all(row["matches"] for row in rows), "planned": len(CASE_IDS),
            "executed": len(rows), "oracle_executed": sum(row["oracle_executed"] for row in rows), "rows": rows}


if __name__ == "__main__":
    service(json.loads(sys.argv[1]))
