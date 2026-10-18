#!/usr/bin/env python3
"""Probe for the Level 3 cicd-pipeline task (#281): the ONLY grading code that
runs candidate code. It EXECUTES the candidate's generated CI artifacts.

Usage: probe.py CANDIDATE_DIR, with inputs.json's object on stdin.

It runs inside the cicd project runtime (`--network none`; ruff, pytest, mypy
and pyyaml served from the warmed uv cache) and reports observations, never a
verdict - grade_cicd_pipeline.py --judge holds every expected value.

For each provider file the candidate generated (`.github/workflows/ci.yml`,
`.woodpecker.yml`) it:

1. parses the YAML (pyyaml, offline) and classifies EVERY command against a
   CLOSED table: `make <one target>` is an obligation; `pip install uv`,
   `uv sync` and the checkout/setup-python/cache actions are provider setup
   with a declared local equivalent; anything else is `unknown` and is never
   run. Unconditional-success markers (`|| true`, `continue-on-error`,
   `failure: ignore`, ...) are recorded per step;
2. runs the obligations in provider order on a fresh copy of the clean tree,
   stopping at the first failure as the provider would, so every later
   obligation is `not-run` - never passed;
3. for each planted fault: proves its precondition with the bare tool on the
   planted file, then runs the same obligations on a fresh planted copy.

It also reports each obligation's work evidence (pytest "N passed", mypy "in
N source files") and the digest of every candidate file, so the judge can
check preservation against the agent's starting state.

Everything is LOCAL execution: provider images, matrix rows, triggers,
secrets and caches are recorded, not modelled. Runs under `python -I -S -B`.
"""

import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

PROVIDER_FILES = (("github-actions", ".github/workflows/ci.yml"), ("woodpecker", ".woodpecker.yml"))
YAML_VERSION = "6.0.3"
STEP_TIMEOUT = 300
SETUP_TIMEOUT = 300
TAIL = 2000
LABEL = "local execution, not hosted CI"

#: GitHub actions with a declared local equivalent; any other `uses:` is unknown.
KNOWN_ACTIONS = {
    "actions/checkout": "the candidate tree is already the workspace",
    "actions/setup-python": "the runtime's own interpreter (version recorded, not matched)",
    "actions/cache": "no cache: the runtime's warmed uv cache serves every run",
}
#: Provider setup commands and their local equivalents.
SETUP_COMMANDS = {
    "pip install uv": "the runtime's pinned uv (no install)",
    "uv sync": "uv sync --offline --locked, once per copy",
}
MAKE = re.compile(r"make ([A-Za-z0-9_-]+)")
#: Command text that makes a step pass whatever its command did.
UNCONDITIONAL = re.compile(r"\|\|\s*(true|:|exit\s+0)\b|;\s*exit\s+0\b|^\s*set\s+\+e\b")
#: Settings that change WHERE or HOW an obligation runs. The local run does not
#: model them, so a step carrying one is not certified: its command is unknown.
#: Checked at workflow AND job scope; an `env` anywhere is unmodelled too (an
#: environment such as MAKEFLAGS=-i can suppress every failure).
UNSUPPORTED_GH = ("defaults.run.working-directory", "defaults.run.shell", "container", "services", "env")
UNSUPPORTED_GH_STEP = ("working-directory", "shell", "env")
UNSUPPORTED_WP_STEP = ("directory", "entrypoint", "commands_shell", "environment")
#: Tool caches a local run creates. Everything else a candidate submits -
#: including `build/` or `dist/` - is part of its file population.
SKIP_PARTS = {".venv", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache"}


def _run(argv, cwd, timeout):
    try:
        proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return {"exit": None, "timed_out": True, "output": ""}
    except OSError as exc:
        return {"exit": None, "launch_error": str(exc), "output": ""}
    return {"exit": proc.returncode, "output": proc.stdout + proc.stderr, "stdout": proc.stdout}


def _yaml_to_json(path, scratch):
    script = os.path.join(scratch, "yaml2json.py")
    with open(script, "w", encoding="utf-8") as handle:
        handle.write("import json, sys, yaml\nprint(json.dumps(yaml.safe_load(open(sys.argv[1], encoding='utf-8'))))\n")
    result = _run(["uv", "run", "--offline", "--no-project", "--with", f"pyyaml=={YAML_VERSION}",
                   "python", script, path], scratch, 120)
    if result["exit"] != 0:
        return None, result["output"][-TAIL:]
    try:
        return json.loads(result["stdout"].strip().splitlines()[-1]), ""
    except (ValueError, IndexError):
        return None, "the YAML loader printed no JSON"


def _classify_command(text):
    line = text.strip()
    entry = {"text": line}
    if UNCONDITIONAL.search(line):
        entry["unconditional"] = True
    if re.search(r"\bmake\b", line):
        found = MAKE.fullmatch(line)
        if found:
            entry.update(kind="obligation", target=found.group(1))
        else:
            entry.update(kind="unknown", why="make in a form other than `make <one target>`")
    elif line in SETUP_COMMANDS:
        entry.update(kind="setup", local=SETUP_COMMANDS[line])
    else:
        entry.update(kind="unknown", why="not in the closed command table")
    return entry


def _lines(block):
    return [line for line in str(block).splitlines() if line.strip()]


def classify(provider, doc):
    """Ordered steps, each with its classified commands and markers."""
    steps = []
    if not isinstance(doc, dict):
        return None
    if provider == "github-actions":
        jobs = doc.get("jobs")
        if not isinstance(jobs, dict):
            return None
        workflow_unsupported = [f"{key} (workflow)" for key in UNSUPPORTED_GH if _has(doc, key)]
        for job_name, job in jobs.items():
            if not isinstance(job, dict) or not isinstance(job.get("steps"), list):
                return None
            matrix = (job.get("strategy") or {}).get("matrix") if isinstance(job.get("strategy"), dict) else None
            job_markers = []
            if job.get("continue-on-error") not in (None, False):
                job_markers.append("continue-on-error")
            if "if" in job:
                job_markers.append(f"if: {job['if']}")
            job_unsupported = workflow_unsupported + [f"{key} (job)" for key in UNSUPPORTED_GH if _has(job, key)]
            for index, step in enumerate(job["steps"]):
                if not isinstance(step, dict):
                    return None
                record = {"job": job_name, "name": step.get("name") or step.get("uses") or f"step {index}",
                          "commands": [], "markers": list(job_markers), "matrix": matrix}
                if "uses" in step:
                    action = str(step["uses"]).split("@", 1)[0]
                    record["commands"].append(
                        {"text": f"uses: {step['uses']}", "kind": "setup", "local": KNOWN_ACTIONS[action]}
                        if action in KNOWN_ACTIONS else
                        {"text": f"uses: {step['uses']}", "kind": "unknown", "why": "action not in the closed table"})
                if "run" in step:
                    record["commands"].extend(_classify_command(line) for line in _lines(step["run"]))
                if step.get("continue-on-error") not in (None, False):
                    record["markers"].append("continue-on-error")
                if "if" in step:
                    record["markers"].append(f"if: {step['if']}")
                for setting in job_unsupported + [key for key in UNSUPPORTED_GH_STEP if key in step]:
                    record["commands"].append({"text": f"setting: {setting}", "kind": "unknown",
                                               "why": "an execution setting the local run does not model"})
                steps.append(record)
    else:
        raw = doc.get("steps")
        items = raw.items() if isinstance(raw, dict) else enumerate(raw) if isinstance(raw, list) else None
        if items is None:
            return None
        for key, step in items:
            if not isinstance(step, dict):
                return None
            record = {"name": step.get("name", key), "image": step.get("image"),
                      "commands": [_classify_command(line) for line in step.get("commands") or []],
                      "markers": []}
            if step.get("failure") == "ignore":
                record["markers"].append("failure: ignore")
            if "when" in step:
                record["markers"].append(f"when: {json.dumps(step['when'], sort_keys=True)}")
            for key in UNSUPPORTED_WP_STEP:
                if key in step:
                    record["commands"].append({"text": f"setting: {key}", "kind": "unknown",
                                               "why": "an execution setting the local run does not model"})
            steps.append(record)
        for key in ("environment", "workspace", "clone"):
            if key in doc and steps:
                steps[0]["commands"].append({"text": f"setting: {key} (pipeline)", "kind": "unknown",
                                             "why": "an execution setting the local run does not model"})
        record_when = doc.get("when")
        if record_when is not None and steps:
            steps[0]["pipeline_when"] = record_when
    return steps


def _has(mapping, dotted):
    node = mapping
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return True


def _evidence(output):
    found = {}
    passed = re.findall(r"\b(\d+) passed\b", output)
    if passed:
        found["tests_passed"] = int(passed[-1])
    if re.search(r"\bno tests ran\b|\bcollected 0 items\b", output):
        found["tests_collected"] = 0
    checked = re.findall(r"in (\d+) source files?\b", output)
    if checked:
        found["type_checked_files"] = int(checked[-1])
    return found


def _copy(candidate, scratch, name):
    dest = os.path.join(scratch, name)
    shutil.copytree(candidate, dest, ignore=shutil.ignore_patterns(*SKIP_PARTS))
    return dest


def execute(steps, tree):
    """Run the obligations in order; stop at the first failure, as a provider does."""
    sync = _run(["uv", "sync", "--offline", "--locked"], tree, SETUP_TIMEOUT)
    results = []
    stopped = None
    for step in steps:
        for command in step["commands"]:
            if command["kind"] != "obligation":
                continue
            entry = {"step": step["name"], "target": command["target"]}
            if stopped is not None:
                entry["status"] = "not-run"
            else:
                outcome = _run(["make", command["target"]], tree, STEP_TIMEOUT)
                entry.update(exit=outcome["exit"], timed_out=outcome.get("timed_out", False),
                             launch_error=outcome.get("launch_error"),
                             output_tail=outcome["output"][-TAIL:], evidence=_evidence(outcome["output"]),
                             output_sha256=hashlib.sha256(outcome["output"].encode()).hexdigest())
                entry["status"] = "passed" if outcome["exit"] == 0 else "failed"
                if outcome["exit"] != 0:
                    stopped = command["target"]
            results.append(entry)
    return {"setup_sync_exit": sync["exit"], "setup_sync_timed_out": sync.get("timed_out", False),
            "setup_sync_tail": sync["output"][-TAIL:], "obligations": results}


def _digests(tree):
    out = {}
    for dirpath, dirnames, filenames in os.walk(tree):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_PARTS)
        for name in sorted(filenames):
            path = os.path.join(dirpath, name)
            if os.path.isfile(path) and not os.path.islink(path):
                with open(path, "rb") as handle:
                    out[os.path.relpath(path, tree).replace(os.sep, "/")] = hashlib.sha256(handle.read()).hexdigest()
    return out


def plant(tree, spec):
    matches = sorted(glob.glob(os.path.join(tree, spec["file"])))
    if len(matches) != 1:
        return {"error": f"{spec['file']} matched {len(matches)} files, not exactly one"}
    with open(matches[0], "a", encoding="utf-8") as handle:
        handle.write(spec["text"])
    return {"file": os.path.relpath(matches[0], tree).replace(os.sep, "/")}


def precondition(tree, spec, planted):
    argv = [part.replace("{file}", planted) for part in spec["precondition"]["argv"]]
    outcome = _run(argv, tree, STEP_TIMEOUT)
    return {"argv": argv, "exit": outcome["exit"], "output_tail": outcome["output"][-TAIL:]}


def main():
    candidate = os.path.abspath(sys.argv[1])
    inputs = json.loads(sys.stdin.read())
    report = {"label": LABEL, "files": _digests(candidate), "providers": {}}
    with tempfile.TemporaryDirectory(prefix="cicd-pipeline-probe-") as scratch:
        config_path = os.path.join(candidate, ".claude", "cicd.yml")
        if os.path.isfile(config_path):
            config, error = _yaml_to_json(config_path, scratch)
            pipeline = config.get("pipeline") if isinstance(config, dict) else None
            report["config"] = {"pipeline_provider": pipeline.get("provider") if isinstance(pipeline, dict) else None,
                                "error": error or None}
        for provider, rel in PROVIDER_FILES:
            path = os.path.join(candidate, rel)
            if not os.path.isfile(path):
                continue
            doc, error = _yaml_to_json(path, scratch)
            steps = classify(provider, doc) if doc is not None else None
            entry = {"file": rel, "steps": steps}
            if steps is None:
                entry["parse_error"] = error or "the document is not a recognisable pipeline"
                report["providers"][provider] = entry
                continue
            clean = _copy(candidate, scratch, f"{provider}-clean")
            before = _digests(clean)
            entry["clean"] = execute(steps, clean)
            after = _digests(clean)
            entry["clean"]["changed_by_run"] = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
            entry["plants"] = []
            for spec in inputs["plants"]:
                tree = _copy(candidate, scratch, f"{provider}-{spec['id']}")
                applied = plant(tree, spec)
                record = {"id": spec["id"], "applied": applied}
                if "error" not in applied:
                    record["precondition"] = precondition(tree, spec, applied["file"])
                    record["run"] = execute(steps, tree)
                entry["plants"].append(record)
            report["providers"][provider] = entry
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
