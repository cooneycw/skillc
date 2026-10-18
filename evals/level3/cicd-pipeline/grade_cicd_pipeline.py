#!/usr/bin/env python3
"""Judge for the Level 3 cicd-pipeline task (#281). The agent never sees this file.

The probe EXECUTED the candidate's generated CI artifacts in the cicd project
runtime; this judge holds every expected value and grades five mandatory
criteria. Every verdict is about LOCAL execution, not hosted CI.

  - `artifacts-present`: a Makefile, `.claude/cicd.yml`, and at least one
    provider pipeline (`.github/workflows/ci.yml`, `.woodpecker.yml`).
  - `pipeline-covers-required-checks`: every provider pipeline runs each
    required stage (lint, test, typecheck) as its OWN `make <target>`
    obligation. An aggregate is never credited for stages it did not run. A
    step that cannot fail (`continue-on-error`, `failure: ignore`, `|| true`,
    `; exit 0`, `set +e`) or that is conditional (`if:`, step `when:`)
    VIOLATES; a command outside the probe's closed table is UNKNOWN.
  - `pipeline-green`: on the clean tree, every provider's obligations pass,
    in order, with work evidence: the test stage ran >= 1 test, the
    typecheck stage checked >= 1 source file. An install the uv cache cannot
    serve offline is UNKNOWN (a missing tool); any other failed install
    VIOLATES (the project itself is broken).
  - `pipeline-honest`: for each planted fault, the judge first requires the
    probe's proof that the bare tool rejects the plant (otherwise UNKNOWN),
    then requires that the FIRST failing obligation is the plant's own stage.
    A pipeline that passes the plant MISSED it, and one that fails an earlier
    stage MISATTRIBUTED it (both VIOLATE). A not-run stage is never credited.
    A red clean pipeline makes this UNKNOWN: rejections by a pipeline that
    rejects everything prove nothing.
  - `behavior-preserved`: every file of the agent's starting tree, other than
    the generated artifacts, is present and byte-identical, and running the
    pipeline changed no tracked file.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

GRADER = {"id": "cicd-pipeline", "revision": "1"}
TIMEOUT_SECONDS = 1500
HERE = Path(__file__).resolve().parent
MAX_REPORT_CHARS = 4_000_000
LABEL = "local execution, not hosted CI"

CRITERIA = ("artifacts-present", "pipeline-covers-required-checks", "pipeline-green", "pipeline-honest",
            "behavior-preserved")
REQUIRED_STAGES = ("lint", "test", "typecheck")
PROVIDER_FILES = {"github-actions": ".github/workflows/ci.yml", "woodpecker": ".woodpecker.yml"}
#: Each planted fault and the stage that must be the first to reject it.
PLANT_STAGE: tuple[tuple[str, str], ...] = (
    ("lint-unused-import", "lint"),
    ("test-failing-assertion", "test"),
    ("type-wrong-assignment", "typecheck"),
)
#: Per task instance (identified by its package): the providers it requires and
#: the `pipeline.provider` its `.claude/cicd.yml` must declare.
REQUIRED_PROVIDERS: dict[str, tuple[tuple[str, ...], str]] = {
    "calc_demo": (("github-actions", "woodpecker"), "both"),
    "ledger_tool": (("woodpecker",), "woodpecker"),
}
#: Files a candidate may add or change beyond its starting tree: the generated
#: CI/CD artifacts, and the harness's own expected.json.
ALLOWED_ARTIFACTS = frozenset({"Makefile", ".claude/cicd.yml", ".github/workflows/ci.yml", ".woodpecker.yml",
                               "expected.json"})
#: Each plant's own diagnostic, BOUND TO THE PLANTED FILE (`{file}`): the
#: precondition AND the rejecting stage must show it, or a neighbour's failure
#: (an F401 in another file, a pytest setup error) could stand in. The forms are
#: the pinned tools' real output (ruff 0.17 full format, pytest's short summary
#: with the planted assertion, mypy's error line).
PLANT_DIAGNOSTIC: dict[str, str] = {
    "lint-unused-import": r"(?:^{file}:\d+:\d+: F401\b)|(?:^F401\b[^\n]*\n\s*-->\s*{file}:\d+:\d+)",
    "test-failing-assertion": r"^FAILED {file}::test_skillc_planted_failure - assert 1 == 2$",
    "type-wrong-assignment": r"^{file}:\d+: error: Incompatible types in assignment\b",
}


def plant_diagnostic(pid: str, planted_file: str) -> re.Pattern[str]:
    return re.compile(PLANT_DIAGNOSTIC[pid].replace("{file}", re.escape(planted_file)), re.MULTILINE)


#: A recipe whose tool never launched: make reports the child's 126/127 as its
#: own exit 2, and uv reports a missing tool as "Failed to spawn".
CHILD_NOT_LAUNCHED = re.compile(r"\] Error 12[67]\b|Failed to spawn: |: command not found$|"
                                r"No such file or directory \(os error 2\)", re.MULTILINE)
#: Exit statuses that mean the tool never ran (not found, not executable).
NOT_LAUNCHED = (126, 127)
#: Markers that let a step pass whatever its obligation did, or skip it.
FAILING_MARKERS = re.compile(r"^(continue-on-error|failure: ignore|if: .*|when: .*)$")
#: uv 0.9.7's own wording when an offline install needs what the cache lacks,
#: in both of its forms ("...data wasn't found in the cache", "...was not found
#: in the cache ... the network was disabled"). uv wraps its diagnostics, so the
#: judge matches whitespace-collapsed text (tests/fixtures/uv-offline-cache-miss-0.9.7.txt).
OFFLINE_MISS = re.compile(r"(?:wasn't|was not|not) found in the cache|network connectivity is disabled"
                          r"|the network was disabled", re.IGNORECASE)


def _unknown(cid: str, reason: str) -> dict[str, object]:
    return {"id": cid, "mandatory": True, "outcome": "UNKNOWN", "missing": reason,
            "evidence": [f"{LABEL}: {reason}"]}


def _verdict(cid: str, outcome: str, evidence: list[str]) -> dict[str, object]:
    return {"id": cid, "mandatory": True, "outcome": outcome, "evidence": [LABEL, *evidence]}


def inputs() -> dict[str, object]:
    data = json.loads((HERE / "inputs.json").read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


#: The agent's starting tree, per task instance, by package name: every file
#: other than the generated artifacts, with its sha256. Expected values live in
#: the judge (it runs isolated, beside nothing); tests/test_level3_cicd_pipeline.py
#: pins this to the committed fixtures, so a fixture edit cannot drift silently.
PRESERVE: dict[str, dict[str, str]] = {
    "calc_demo": {
        ".gitignore": "892e630bc698e56abf7b3db2552772062b34438041b47d312085086106a1564c",
        "pyproject.toml": "a8763b5fcf1f32e5cddf44b973e3f858411cdecf23306c7207d4a00b2e7c1feb",
        "src/calc_demo/__init__.py": "ef995b398f3bbef29aecff133a11a1cef38bb958330cc51cd7a9221b40403c8a",
        "tests/conftest.py": "6bafb70adcd7ecca4f5b38efe782fb2408ff2d7af177b967e595d7093afd5c50",
        "tests/test_placeholder.py": "51ed6fb7436f3ea1a54fcf9a01e3e51e926afcc0177f6cb75db1b1fa23338753",
        "uv.lock": "9e4ee8f8eeefa4a59887645a9aa70591509ac0d8843dac3e69118affb0bf16f2"
    },
    "ledger_tool": {
        ".gitignore": "892e630bc698e56abf7b3db2552772062b34438041b47d312085086106a1564c",
        "pyproject.toml": "928b9300c84235c877829e0224c7e5d6060ee653e66cdf307596ee94a5e64fd1",
        "src/ledger_tool/__init__.py": "eca31b722eeafd6362350a406f02188703cc6e82b25b53238acbbc2a3aa32ab1",
        "src/ledger_tool/entries.py": "d086502fcce7ebc757128149b2c1529cef138c0d5f1e7f95daf725b67a478972",
        "tests/conftest.py": "6bafb70adcd7ecca4f5b38efe782fb2408ff2d7af177b967e595d7093afd5c50",
        "tests/test_entries.py": "78c8a77bee8c98370c4b82f8d463fb669098a196ee50aa12e3d7c07426f3d9aa",
        "tests/test_placeholder.py": "5799279b748d08d7f3239e6a384ea1a629ff4af81ac75524b781399b3b45a0f5",
        "uv.lock": "8312cefe0ca399f092f8f1d52f1bf453eb274c9ebfa1dd3331c8aca146bea322"
    }
}


def preserve_sets() -> dict[str, dict[str, str]]:
    return PRESERVE


def run_probe(candidate: Path, timeout: float = TIMEOUT_SECONDS,
              probe_inputs: dict[str, object] | None = None) -> dict[str, object]:
    """Run `probe.py` on a candidate directly (host tools). NOT the isolated
    path; qualify.py grades through the cicd project runtime."""
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-S", "-B", str(HERE / "probe.py"), str(candidate)],
            input=json.dumps(probe_inputs if probe_inputs is not None else inputs()),
            capture_output=True, text=True, timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired:
        return {"observations": "", "timed_out": True}
    return {"observations": proc.stdout, "timed_out": False}


def read_report(envelope: dict[str, object]) -> dict[str, object] | None:
    if envelope.get("timed_out"):
        return None
    raw = envelope.get("observations")
    if not isinstance(raw, str) or not raw.strip() or len(raw) > MAX_REPORT_CHARS:
        return None
    try:
        data = json.loads(raw.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None
    if not isinstance(data, dict) or data.get("label") != LABEL or not isinstance(data.get("providers"), dict) \
            or not isinstance(data.get("files"), dict):
        return None
    return data


def _instance(data: dict[str, object]) -> str | None:
    files = data["files"]
    assert isinstance(files, dict)
    packages = {rel.split("/")[1] for rel in files if rel.startswith("src/") and rel.count("/") >= 2}
    matches = [name for name in packages if name in PRESERVE]
    return matches[0] if len(matches) == 1 else None


def _artifacts(data: dict[str, object]) -> dict[str, object]:
    files = data["files"]
    assert isinstance(files, dict)
    instance = _instance(data)
    if instance is None:
        return _unknown("artifacts-present", "cannot identify the task instance from the candidate's packages")
    required, provider_setting = REQUIRED_PROVIDERS[instance]
    problems = [f"missing: {rel}" for rel in ("Makefile", ".claude/cicd.yml") if rel not in files]
    observed = _providers(data)
    for provider in required:
        if PROVIDER_FILES[provider] not in files:
            problems.append(f"missing the required {provider} pipeline ({PROVIDER_FILES[provider]})")
        elif provider not in observed:
            problems.append(f"the {provider} pipeline was not observed")
    config = data.get("config") if isinstance(data.get("config"), dict) else {}
    assert isinstance(config, dict)
    if ".claude/cicd.yml" in files and config.get("pipeline_provider") != provider_setting:
        problems.append(f".claude/cicd.yml declares pipeline.provider {config.get('pipeline_provider')!r}, "
                        f"not {provider_setting!r}")
    if problems:
        return _verdict("artifacts-present", "VIOLATED", problems)
    summary = f"providers: {', '.join(required)}; pipeline.provider {provider_setting}"
    return _verdict("artifacts-present", "SATISFIED", [summary])


def _providers(data: dict[str, object]) -> dict[str, dict[str, object]]:
    providers = data["providers"]
    assert isinstance(providers, dict)
    return {p: e for p, e in providers.items() if p in PROVIDER_FILES and isinstance(e, dict)}


def _coverage(data: dict[str, object]) -> dict[str, object]:
    providers = _providers(data)
    if not providers:
        return _verdict("pipeline-covers-required-checks", "VIOLATED", ["no provider pipeline to run"])
    violated, unknown, evidence = [], [], []
    for provider, entry in sorted(providers.items()):
        steps = entry.get("steps")
        if not isinstance(steps, list):
            unknown.append(f"{provider}: unparseable ({entry.get('parse_error', 'no steps')})")
            continue
        targets: list[str] = []
        for step in steps:
            commands = step.get("commands", []) if isinstance(step, dict) else []
            has_obligation = any(c.get("kind") == "obligation" for c in commands)
            for command in commands:
                if command.get("kind") == "obligation":
                    targets.append(str(command.get("target")))
                elif command.get("kind") == "unknown":
                    unknown.append(f"{provider}: unknown command {command.get('text')!r} ({command.get('why')})")
                if command.get("unconditional"):
                    violated.append(f"{provider}: step {step.get('name')!r} cannot fail ({command.get('text')!r})")
            if has_obligation:
                for marker in step.get("markers", []):
                    if FAILING_MARKERS.match(str(marker)):
                        violated.append(f"{provider}: step {step.get('name')!r} is {marker}")
            if step.get("matrix"):
                evidence.append(f"{provider}: matrix {json.dumps(step['matrix'], sort_keys=True)} not modelled "
                                f"(one runtime interpreter)")
        for stage in REQUIRED_STAGES:
            if stage not in targets:
                violated.append(f"{provider}: required stage {stage!r} is not its own obligation")
        evidence.append(f"{provider}: obligations {targets}")
    if violated:
        return _verdict("pipeline-covers-required-checks", "VIOLATED", violated + evidence)
    if unknown:
        return {**_unknown("pipeline-covers-required-checks", "; ".join(unknown)), "evidence": [LABEL, *unknown,
                                                                                                *evidence]}
    return _verdict("pipeline-covers-required-checks", "SATISFIED", sorted(set(evidence)))


def declared_targets(entry: dict[str, object]) -> list[str]:
    steps = entry.get("steps")
    return [str(c.get("target")) for step in steps if isinstance(step, dict) for c in step.get("commands", [])
            if c.get("kind") == "obligation"] if isinstance(steps, list) else []


def reconciled(entry: dict[str, object], run: object) -> str | None:
    """Why `run`'s observations are not exactly the declared obligations, or None."""
    observed = run.get("obligations") if isinstance(run, dict) else None
    if not isinstance(observed, list) or not all(isinstance(o, dict) for o in observed):
        return "no execution observations"
    declared = declared_targets(entry)
    if not declared:
        return "no declared obligation to observe"
    if [o.get("target") for o in observed] != declared:
        return f"observed {[o.get('target') for o in observed]}, declared {declared}"
    return None


def launch_failed(ob: dict[str, object]) -> bool:
    return bool(ob.get("launch_error") or ob.get("exit") in NOT_LAUNCHED
                or CHILD_NOT_LAUNCHED.search(str(ob.get("output_tail", ""))))


def _obligation_problem(ob: dict[str, object]) -> tuple[str, str] | None:
    """(severity, reason) for a clean-run obligation that did not prove itself."""
    target = ob.get("target")
    if ob.get("timed_out"):
        return "unknown", f"{target} timed out"
    if launch_failed(ob):
        return "unknown", f"{target} could not launch its tool (exit {ob.get('exit')})"
    if ob.get("status") != "passed":
        return "violated", f"{target} {ob.get('status')} (exit {ob.get('exit')})"
    evidence = ob.get("evidence") if isinstance(ob.get("evidence"), dict) else {}
    assert isinstance(evidence, dict)
    if target == "test" and not (isinstance(evidence.get("tests_passed"), int) and evidence["tests_passed"] >= 1):
        return "violated", "test passed without running any test (no discovery)"
    if target == "typecheck" and not (isinstance(evidence.get("type_checked_files"), int)
                                      and evidence["type_checked_files"] >= 1):
        return "violated", "typecheck passed without checking any source file"
    return None


def _green(data: dict[str, object]) -> dict[str, object]:
    providers = _providers(data)
    if not providers:
        return _unknown("pipeline-green", "no provider pipeline to run")
    violated, unknown, evidence = [], [], []
    for provider, entry in sorted(providers.items()):
        clean = entry.get("clean")
        if not isinstance(clean, dict):
            unknown.append(f"{provider}: not run ({entry.get('parse_error', 'no clean run')})")
            continue
        if clean.get("setup_sync_timed_out"):
            unknown.append(f"{provider}: the install timed out")
            continue
        if clean.get("setup_sync_exit") != 0:
            tail = str(clean.get("setup_sync_tail", ""))
            (unknown if OFFLINE_MISS.search(" ".join(tail.split())) else violated).append(
                f"{provider}: install failed: {tail.strip().splitlines()[-1:] or ['no output']}")
            continue
        mismatch = reconciled(entry, clean)
        if mismatch:
            unknown.append(f"{provider}: {mismatch}")
            continue
        for ob in clean.get("obligations", []):
            problem = _obligation_problem(ob)
            if problem:
                # The first problem stops the provider; its not-run successors are its
                # consequence, never a separate violation (an infrastructure stop stays UNKNOWN).
                (violated if problem[0] == "violated" else unknown).append(f"{provider}: {problem[1]}")
                break
        evidence.append(f"{provider}: {[(o.get('target'), o.get('status')) for o in clean.get('obligations', [])]}")
    if violated:
        return _verdict("pipeline-green", "VIOLATED", violated + evidence)
    if unknown:
        return {**_unknown("pipeline-green", "; ".join(unknown)), "evidence": [LABEL, *unknown, *evidence]}
    return _verdict("pipeline-green", "SATISFIED", evidence)


def plant_verdict(provider: str, expected: str, record: dict[str, object],
                  entry: dict[str, object]) -> tuple[str, str]:
    pid = record.get("id")
    applied = record.get("applied")
    if not isinstance(applied, dict) or "error" in applied:
        return "unknown", f"{provider}/{pid}: not applied ({applied})"
    diagnostic = plant_diagnostic(str(pid), str(applied.get("file")))
    pre = record.get("precondition")
    if (not isinstance(pre, dict) or pre.get("exit") in (0, None, *NOT_LAUNCHED)
            or not diagnostic.search(str(pre.get("output_tail", "")))):
        return "unknown", f"{provider}/{pid}: the bare tool did not reject the plant with its own diagnostic"
    run = record.get("run")
    if not isinstance(run, dict) or run.get("setup_sync_exit") != 0 or run.get("setup_sync_timed_out"):
        return "unknown", f"{provider}/{pid}: the planted copy did not install"
    mismatch = reconciled(entry, run)
    if mismatch:
        return "unknown", f"{provider}/{pid}: {mismatch}"
    obligations = run["obligations"]
    if any(o.get("timed_out") for o in obligations):
        return "unknown", f"{provider}/{pid}: an obligation timed out"
    failed = [o for o in obligations if o.get("status") == "failed"]
    if not failed:
        return "missed", f"{provider}/{pid}: every obligation passed the planted fault"
    first = failed[0]
    if launch_failed(first):
        return "unknown", f"{provider}/{pid}: {first.get('target')!r} could not launch its tool"
    if first.get("target") != expected:
        return "misattributed", f"{provider}/{pid}: rejected first by {first.get('target')!r}, not {expected!r}"
    if not diagnostic.search(str(first.get("output_tail", ""))):
        return "unknown", f"{provider}/{pid}: {expected!r} failed without the plant's own diagnostic"
    return "detected", f"{provider}/{pid}: rejected by {expected!r}"


def _honest(data: dict[str, object], green: dict[str, object]) -> dict[str, object]:
    if green["outcome"] != "SATISFIED":
        return _unknown("pipeline-honest", "the clean pipeline is not green, so its rejections prove nothing")
    results = []
    for provider, entry in sorted(_providers(data).items()):
        records = entry.get("plants")
        if not isinstance(records, list) or [r.get("id") for r in records] != [pid for pid, _ in PLANT_STAGE]:
            results.append(("unknown", f"{provider}: the probe did not report exactly the declared plants"))
            continue
        results.extend(plant_verdict(provider, stage, record, entry)
                       for (_pid, stage), record in zip(PLANT_STAGE, records, strict=True))
    evidence = [f"{verdict}: {detail}" for verdict, detail in results]
    verdicts = {v for v, _ in results}
    if verdicts & {"missed", "misattributed"}:
        return _verdict("pipeline-honest", "VIOLATED", evidence)
    if "unknown" in verdicts or not results:
        return {**_unknown("pipeline-honest", "; ".join(d for v, d in results if v == "unknown") or "no plants"),
                "evidence": [LABEL, *evidence]}
    return _verdict("pipeline-honest", "SATISFIED", evidence)


def _preserved(data: dict[str, object]) -> dict[str, object]:
    files = data["files"]
    assert isinstance(files, dict)
    instance = _instance(data)
    if instance is None:
        return _unknown("behavior-preserved", "cannot identify the starting tree from the candidate's packages")
    expected = preserve_sets()[instance]
    changed = [rel for rel, digest in sorted(expected.items()) if files.get(rel) != digest]
    by_run = sorted({rel for entry in _providers(data).values() if isinstance(entry.get("clean"), dict)
                     for rel in entry["clean"].get("changed_by_run", [])})  # type: ignore[union-attr]
    added = sorted(set(files) - set(expected) - ALLOWED_ARTIFACTS)
    problems = ([f"changed or removed: {rel}" for rel in changed] + [f"added: {rel}" for rel in added]
                + [f"the pipeline run changed {rel}" for rel in by_run])
    if problems:
        return _verdict("behavior-preserved", "VIOLATED", problems)
    return _verdict("behavior-preserved", "SATISFIED", [f"{len(expected)} starting files unchanged"])


def judge(envelope: dict[str, object]) -> dict[str, object]:
    data = read_report(envelope)
    if data is None:
        return {"grader": GRADER, "criteria": [_unknown(c, "the probe produced no well-formed report")
                                               for c in CRITERIA]}
    green = _green(data)
    return {"grader": GRADER, "criteria": [_artifacts(data), _coverage(data), green, _honest(data, green),
                                           _preserved(data)]}


def grade(candidate: Path, timeout: float = TIMEOUT_SECONDS) -> dict[str, object]:
    return judge(run_probe(candidate, timeout))


def main(argv: list[str]) -> int:
    if argv[1:] == ["--judge"]:
        print(json.dumps(judge(json.loads(sys.stdin.read())), indent=1))
        return 0
    if len(argv) != 2:
        print("usage: grade_cicd_pipeline.py --judge < ENVELOPE | grade_cicd_pipeline.py CANDIDATE_DIR",
              file=sys.stderr)
        return 2
    print(json.dumps(grade(Path(argv[1])), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
