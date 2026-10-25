"""Model-free preparation check; launch-ready never launches a model.

Run from the isolated checkout with its own Python. Output contains logical
identities only. The committed controls exercise the same production validators.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import py_compile
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
# Existing timestamp-valid or unchecked-hash bytecode can disagree with the
# verified .py. Use a newly created, private, empty cache BEFORE controller
# imports. -B alone would prevent writes but still consume old caches.
SOURCE_CACHE = tempfile.TemporaryDirectory(prefix="skillc-557-source-cache-")
sys.pycache_prefix = SOURCE_CACHE.name

from skillc import calibration, credential, egress, trial_bootstrap, verify
from skillc import calibration_run as cr
from skillc import collection_conformance as cc


class Refused(Exception):
    """An input does not meet this repeat's declared boundary."""


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(ROOT), *args], stderr=subprocess.PIPE)


def object_id(path: Path) -> str:
    return git("hash-object", "--no-filters", "--", str(path)).decode().strip()


def tracked_files(revision: str, prefix: str) -> dict[str, tuple[str, str]]:
    rows = git("ls-tree", "-r", "-z", revision, "--", prefix).split(b"\0")
    result = {}
    for row in filter(None, rows):
        metadata, path = row.split(b"\t", 1)
        mode, kind, blob = metadata.decode().split()
        if kind != "blob" or mode not in ("100644", "100755"):
            raise Refused("source contains an unsupported file mode")
        result[path.decode()] = (mode, blob)
    if not result:
        raise Refused("source population is empty")
    return result


def check_files(expected: dict[str, tuple[str, str]], source: str, destination: Path) -> None:
    wanted = {str(Path(path).relative_to(source)): value for path, value in expected.items()}
    found = {str(p.relative_to(destination)) for p in destination.rglob("*")
             if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"}
    if set(wanted) != found:
        raise Refused("source file population differs")
    for rel, (mode, blob) in wanted.items():
        path = destination / rel
        if path.is_symlink() or not path.is_file():
            raise Refused("source contains a symlink or missing file")
        actual_mode = "100755" if path.stat().st_mode & stat.S_IXUSR else "100644"
        if object_id(path) != blob or mode != actual_mode:
            raise Refused(f"source bytes or executable mode differs: {rel}")


def check_controller(data: dict, *, checkout: Path = ROOT) -> None:
    binding = data["controller"]
    revision = binding["source_commit"]
    required = {"skillc", "docker", "evals/subjects/cpp-codex", "pyproject.toml", "uv.lock"}
    if set(binding["objects"]) != required:
        raise Refused("controller dependency population differs")
    for path, expected in binding["objects"].items():
        if git("rev-parse", f"{revision}:{path}").decode().strip() != expected:
            raise Refused("controller source differs from recorded commit")
        files = tracked_files(revision, path)
        local = checkout / path
        if local.is_file():
            mode, blob = files[path]
            actual_mode = "100755" if local.stat().st_mode & stat.S_IXUSR else "100644"
            if local.is_symlink() or object_id(local) != blob or mode != actual_mode:
                raise Refused("controller source differs from working tree")
        else:
            try:
                check_files(files, path, local)
            except Refused as exc:
                raise Refused("controller source differs from working tree: " + str(exc)) from exc
    for name, module in list(sys.modules.items()):
        if name == "skillc" or name.startswith("skillc."):
            location = getattr(module, "__file__", None)
            if location is not None and not Path(location).resolve().is_relative_to(ROOT / "skillc"):
                raise Refused("controller imports are outside the frozen checkout")
    if cr.ROOT.resolve() != ROOT:
        raise Refused("controller runtime root differs from frozen checkout")


def check_task(data: dict) -> None:
    source = data["historical_source"]
    tree = git("rev-parse", f"{source['skillc_commit']}:{source['task_path']}").decode().strip()
    if tree != source["task_tree"]:
        raise Refused("historical task tree differs")
    task = ROOT / data["task"]["path"]
    check_files(tracked_files(source["skillc_commit"], source["task_path"]), source["task_path"], task)
    measured = cr.task_content_identity(
        (task / "goal.md").read_bytes(), verify.GraderDef.load(task), cc.task_surface(task / "fixture"))
    if measured != data["historical_source"]["content"]:
        raise Refused("task_content differs")


def check_design(data: dict) -> None:
    historical = json.loads((ROOT / data["historical_source"]["original_declaration"]).read_text())
    for field in ("arms", "attempts_per_arm", "arm_order", "retain_transcripts", "primary_endpoint"):
        if data[field] != historical[field]:
            raise Refused(f"historical design differs: {field}")
    for field in ("client", "model", "reasoning_effort", "per_attempt_seconds", "total_seconds"):
        if data["shared"][field] != historical["shared"][field]:
            raise Refused(f"historical shared identity differs: {field}")
    calibration.parse_declaration(data)
    expected = {"policy": cc.AGENT_NETWORK_POLICY, "allowlist_digest": egress.allowlist_digest(),
                "codex_server_side_off": list(egress.CODEX_SERVER_SIDE_OFF)}
    if data["shared"]["agent_network"] != expected:
        raise Refused("provider-only egress binding differs")
    if not all(cr.guard_kwargs("codex", data["shared"]["model"]).values()):
        raise Refused("nested guard is not enabled")
    calibration.resolve_run_store(data["run_store"])


def check_launch(data: dict, *, require_frozen: bool = True) -> None:
    calibration.require_approved(calibration.parse_declaration(data), ROOT)
    if require_frozen and data["controller"]["retention_547_reviewed"] is not True:
        raise Refused("controller has not been reviewed after retention #547")


def control_draft(data: dict) -> dict:
    """An in-memory control ONLY; never saved or used to invoke an agent."""
    draft = copy.deepcopy(data)
    draft["approval"] = {"by": "synthetic-control-only", "at": "2026-10-24",
                         "attempts_per_arm": 6, "declaration_digest": calibration.declaration_digest(draft)}
    return draft


def source_process(script: Path) -> subprocess.CompletedProcess:
    """The actual qualification subprocess boundary, also used by its control."""
    with tempfile.TemporaryDirectory(prefix="skillc-557-qualifier-cache-") as cache:
        return subprocess.run(
            [sys.executable, "-X", f"pycache_prefix={cache}", str(script)],
            env={**os.environ, "PYTHONPATH": str(ROOT)}, capture_output=True, text=True,
            timeout=300, check=False)


def exercise_control(case: dict, data: dict) -> None:
    draft = control_draft(data)
    # A positive control through the production gate establishes that a red
    # is caused by its mutation, rather than by an already-broken base input.
    check_launch(draft, require_frozen=False)
    action = case["action"]
    if action == "original-current-task":
        original = json.loads((ROOT / data["historical_source"]["original_declaration"]).read_text())
        calibration.require_approved(calibration.parse_declaration(original), ROOT)
    elif action == "stale-image":
        draft["shared"]["image"]["digest"] = data["historical_source"]["original_image"]
        check_launch(draft, require_frozen=False)
    elif action == "task-content":
        draft["historical_source"]["content"]["goal_digest"] = "sha256:" + "0" * 64
        check_task(draft)
    elif action == "schedule":
        draft["arm_order"]["sequence"][0] = "provided"
        calibration.parse_declaration(draft)
    elif action == "temp-store":
        draft["run_store"] = "/tmp/skillc-557-control"
        calibration.parse_declaration(draft)
    elif action == "controller":
        draft["controller"]["objects"]["skillc"] = "0" * 40
        check_controller(draft)
    elif action == "controller-bytes":
        with tempfile.TemporaryDirectory(prefix="skillc-557-controller-control-") as tmp:
            checkout = Path(tmp)
            for path in draft["controller"]["objects"]:
                original, copied = ROOT / path, checkout / path
                if original.is_dir():
                    shutil.copytree(original, copied, ignore=shutil.ignore_patterns("__pycache__"))
                else:
                    copied.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(original, copied)
            check_controller(draft, checkout=checkout)
            target = checkout / case["path"]
            target.write_bytes(target.read_bytes() + case["append"].encode())
            check_controller(draft, checkout=checkout)
    elif action == "archive-bytes":
        source = draft["historical_source"]
        with tempfile.TemporaryDirectory(prefix="skillc-557-archive-control-") as tmp:
            checkout = Path(tmp) / "task"
            shutil.copytree(ROOT / draft["task"]["path"], checkout,
                            ignore=shutil.ignore_patterns("__pycache__"))
            target = checkout / case["path"]
            target.write_bytes(target.read_bytes() + case["append"].encode())
            check_files(tracked_files(source["skillc_commit"], source["task_path"]),
                        source["task_path"], checkout)
    elif action == "divergent-bytecode":
        with tempfile.TemporaryDirectory(prefix="skillc-557-bytecode-control-") as tmp:
            scratch = Path(tmp)
            source = scratch / "sentinel557.py"
            source.write_text(case["source"])
            divergent = scratch / "divergent.py"
            divergent.write_text(case["cached_source"])
            # Explicit default-cache spelling: cache_from_source would use
            # the fresh production prefix established by this module above.
            tag = sys.implementation.cache_tag
            cache = scratch / "__pycache__" / f"sentinel557.{tag}.pyc"
            cache.parent.mkdir()
            py_compile.compile(str(divergent), cfile=str(cache), dfile=str(source), doraise=True,
                               invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)
            before = ("import sys;sys.path.insert(0," + repr(str(scratch))
                      + ");import sentinel557;assert sentinel557.VALUE == 'CACHE'")
            subprocess.run([sys.executable, "-I", "-B", "-c", before],
                           check=True, capture_output=True, timeout=30)
            # Loading THIS preflight as a module installs its production
            # fresh-cache boundary before importing the identical sentinel.
            after = ("import sys,runpy;sys.path.insert(0," + repr(str(scratch)) + ");"
                     + "runpy.run_path(" + repr(str(Path(__file__).resolve())) + ");"
                     + "import sentinel557;assert sentinel557.VALUE == 'SOURCE'")
            subprocess.run([sys.executable, "-I", "-B", "-c", after],
                           check=True, capture_output=True, timeout=30)
            qualifier = scratch / "qualify.py"
            qualifier.write_text("import sentinel557\nassert sentinel557.VALUE == 'SOURCE'\n")
            result = source_process(qualifier)
            if result.returncode:
                raise Refused("qualification boundary consumed divergent bytecode")
            raise Refused("loadable divergent bytecode excluded by preflight and qualifier; source executed")
    elif action == "missing-approval":
        draft["approval"] = None
        check_launch(draft)
    else:
        raise Refused("unrecognized control action")


def controls(data: dict) -> None:
    cases = json.loads((HERE / "controls.json").read_text())
    expected = {"original-current-task", "stale-image", "task-content", "schedule",
                "temp-store", "controller", "controller-bytes", "archive-bytes", "divergent-bytecode",
                "missing-approval"}
    if len(cases) != len(expected) or {c["action"] for c in cases} != expected:
        raise Refused("negative-control population differs")
    for case in cases:
        try:
            exercise_control(case, data)
        except (Refused, calibration.DeclarationRefused) as exc:
            if case["refusal"] not in str(exc):
                raise Refused(f"control {case['name']} refused for the wrong reason") from exc
            print(f"CONTROL {case['name']}: REFUSED as expected")
        else:
            raise Refused(f"control {case['name']} unexpectedly ACCEPTED")


def image_check(data: dict) -> None:
    digest = data["shared"]["image"]["digest"]
    actual = subprocess.check_output(
        ["docker", "image", "inspect", digest, "--format", "{{.Id}}"], stderr=subprocess.PIPE,
        timeout=30).decode().strip()
    if actual != digest:
        raise Refused("resolved image differs")
    version = subprocess.check_output(
        ["docker", "run", "--rm", "--network", "none", "--entrypoint", "codex", digest, "--version"],
        stderr=subprocess.PIPE, timeout=30).decode().strip()
    if version != "codex-cli " + data["shared"]["client"]["version"]:
        raise Refused("actual image client differs")
    if trial_bootstrap.pinned_cli_version("codex") != data["shared"]["client"]["version"]:
        raise Refused("controller client pin differs")
    print("IMAGE: exact digest resolved; credential-free network-none " + version)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("prepare", "launch-ready"), default="prepare")
    parser.add_argument("--image", action="store_true", help="network-none client version probe only")
    parser.add_argument("--credential", action="store_true", help="eligibility only; never print credential bytes")
    parser.add_argument("--qualify", action="store_true", help="certify historical grader; no model")
    args = parser.parse_args()
    try:
        data = json.loads((HERE / "run-manifest.json").read_text())
        check_controller(data)
        check_task(data)
        check_design(data)
        controls(data)
        print("DECLARATION: " + calibration.declaration_digest(data))
        if args.image:
            image_check(data)
        else:
            print("IMAGE: actual image/client NOT CHECKED in this invocation")
        if args.credential:
            # The existing selector and lifetime check are the runtime path's
            # own. Paths, token bytes and exception text never enter output.
            try:
                payload = credential.read_fresh(credential.resolve_path("codex"))
                credential.check_remaining_life_or_refuse(
                    "codex", payload, minimum_seconds=data["shared"]["per_attempt_seconds"])
                del payload
            except (credential.CredentialRefused, OSError, ValueError) as exc:
                raise Refused("local subscription credential eligibility refused; use the normal login flow") from exc
            print("CREDENTIAL: local selector/lifetime eligible; re-read separately before every attempt")
        else:
            print("CREDENTIAL: NOT CHECKED in this invocation")
        if args.qualify:
            proc = source_process(ROOT / data["task"]["path"] / "qualify.py")
            if proc.returncode or "QUALIFY: ok" not in proc.stdout:
                raise Refused("historical grader certification refused")
            print(next(line for line in proc.stdout.splitlines() if line.startswith("QUALIFY: ok")))
        else:
            print("GRADER: certification NOT RUN in this invocation")
        if args.stage == "launch-ready":
            check_launch(data)
            if not (args.image and args.credential and args.qualify):
                raise Refused("launch-ready requires --image --credential --qualify")
            if os.environ.get("SKILLC_ALLOW_REAL_AGENT") != "1":
                raise Refused("launch-ready requires SKILLC_ALLOW_REAL_AGENT=1")
            print("PREFLIGHT: LAUNCH-READY; no model launched; runtime evidence remains unobserved")
        else:
            print("PREFLIGHT: PREPARED; NOT AUTHORIZED TO LAUNCH; controller freeze="
                  + str(data["controller"]["retention_547_reviewed"]).lower())
        return 0
    except (Refused, calibration.DeclarationRefused, OSError, ValueError, KeyError,
            subprocess.SubprocessError) as exc:
        # Detailed exceptions may contain host paths or credential selectors.
        # Only logical Refused/DeclarationRefused text is safe to publish.
        detail = str(exc) if isinstance(exc, (Refused, calibration.DeclarationRefused)) else type(exc).__name__
        print("PREFLIGHT: REFUSED - " + detail, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
