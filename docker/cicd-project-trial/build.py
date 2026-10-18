#!/usr/bin/env python3
"""Build the cicd project runtime: a warmed project-tools cache on a validated
cicd receipt (skillc#281).

The input is an EXTERNAL `cicd-runtime` receipt that `skillc.runtime_supply`
accepts and a task project directory holding `pyproject.toml`, `uv.lock` and
its `src/` package. The output is a `cicd-project-runtime` receipt embedding
the base receipt whole. Before writing it, the builder binds the new image:

1. its layers are the base's layers plus exactly two (the COPY and the warm);
2. `User`, `WorkingDir`, `Env`, `Entrypoint` and `Cmd` are the base's;
3. the runtime descriptor is the base's, byte for byte;
4. every tool the lock pins (ruff, pytest, mypy) runs offline, in a fresh
   `--network none` container, on a copy of the project, and reports exactly
   the version the lock pins.

The recipe is read from the committed tree at HEAD. Nothing is removed or
untagged: the layer is tagged `skillc-cicd-project-runtime:<id12>` and its
base `skillc-cicd-project-base:<id12>`, so a kept build is never dangling.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from skillc import runtime_supply as rs

RECIPE_PATH = "docker/cicd-project-trial/Dockerfile"
INHERITED_CONFIG = ("User", "WorkingDir", "Env", "Entrypoint", "Cmd")
ADDED_LAYERS = 2
#: The YAML loader the grading probe uses (CPP's own lock pins it at 86641e8).
YAML_VERSION = "6.0.3"
#: What the warm stage copies from a task project; never its tests or artifacts.
WARM_FILES = ("pyproject.toml", "uv.lock")
WARM_DIRS = ("src",)


class BuildError(ValueError):
    """The cicd project runtime cannot be bound to its base or its lock."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def _id12(image_id: str) -> str:
    return image_id.removeprefix("sha256:")[:12]


def base_tag(image_id: str) -> str:
    return "skillc-cicd-project-base:" + _id12(image_id)


def runtime_tag(image_id: str) -> str:
    return "skillc-cicd-project-runtime:" + _id12(image_id)


def locked_tool_versions(lock: bytes) -> dict[str, str]:
    """The registry versions the lock pins for each project tool."""
    packages = tomllib.loads(lock.decode("utf-8")).get("package", [])
    versions = {pkg["name"]: pkg["version"] for pkg in packages
                if isinstance(pkg, dict) and "registry" in pkg.get("source", {})}
    missing = [tool for tool in rs.PROJECT_TOOLS if tool not in versions]
    if missing:
        raise BuildError(f"the project lock pins no {', '.join(missing)}")
    return {tool: versions[tool] for tool in rs.PROJECT_TOOLS}


def check_layers(base: dict[str, Any], layered: dict[str, Any]) -> None:
    base_layers = base.get("RootFS", {}).get("Layers")
    layers = layered.get("RootFS", {}).get("Layers")
    if not isinstance(base_layers, list) or not isinstance(layers, list) or not base_layers:
        raise BuildError("image layer lists are unreadable")
    if layers[: len(base_layers)] != base_layers or len(layers) != len(base_layers) + ADDED_LAYERS:
        raise BuildError(f"the cicd project image is not its base plus exactly {ADDED_LAYERS} layers")


def check_config(base: dict[str, Any], layered: dict[str, Any]) -> None:
    for key in INHERITED_CONFIG:
        if base.get("Config", {}).get(key) != layered.get("Config", {}).get(key):
            raise BuildError(f"the cicd project image changed its base's {key}")


def parse_tool_versions(text: str) -> dict[str, str]:
    """`<tool> <version>` lines from the offline smoke run, one per tool."""
    found: dict[str, str] = {}
    for line in text.splitlines():
        match = re.match(r"^(ruff|pytest|mypy)[ =](?:\S* )?([0-9]+(?:\.[0-9]+)+)\b", line.strip())
        if match:
            found.setdefault(match.group(1), match.group(2))
    return found


#: Run as the candidate in a fresh --network none container: a copy of the
#: project, then each tool through the project's own `uv run`, offline.
SMOKE = (
    "set -e; cp -r /tmp/skillc-smoke-src /tmp/skillc-smoke && cd /tmp/skillc-smoke && "
    "uv run --offline --locked ruff --version && "
    "uv run --offline --locked pytest --version && "
    "uv run --offline --locked mypy --version && "
    f"uv run --offline --no-project --with pyyaml=={YAML_VERSION} python -c "
    "'import yaml; print(\"pyyaml \" + yaml.__version__)'"
)


def committed_recipe(repo: Path) -> tuple[str, bytes]:
    def git(*args: str) -> bytes:
        return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True).stdout

    commit = git("rev-parse", "HEAD").decode().strip()
    return commit, git("show", f"{commit}:{RECIPE_PATH}")


def docker(argv: list[str]) -> str:
    try:
        return subprocess.run(["docker", *argv], check=True, capture_output=True, text=True).stdout
    except subprocess.CalledProcessError as exc:
        diagnostic = (exc.stderr or exc.stdout or "no diagnostic")[-16000:]
        raise BuildError(f"docker {argv[0]} exited {exc.returncode}: {diagnostic}") from exc


def _inspect(run: Callable[[list[str]], str], image_id: str) -> dict[str, Any]:
    info = json.loads(run(["image", "inspect", image_id]))
    if not isinstance(info, list) or len(info) != 1 or info[0].get("Id") != image_id:
        raise BuildError("inspected image ID mismatch")
    result: dict[str, Any] = info[0]
    return result


def _warm_context(project: Path, context: Path) -> bytes:
    warm = context / "warm"
    warm.mkdir(parents=True)
    for name in WARM_FILES:
        if not (project / name).is_file():
            raise BuildError(f"the project has no {name}")
        shutil.copy2(project / name, warm / name)
    for name in WARM_DIRS:
        if not (project / name).is_dir():
            raise BuildError(f"the project has no {name}/")
        shutil.copytree(project / name, warm / name)
    return (project / "uv.lock").read_bytes()


def build_image(
    base_receipt_path: Path,
    project: Path,
    receipt_path: Path,
    *,
    repo: Path = ROOT,
    run: Callable[[list[str]], str] = docker,
    recipe: tuple[str, bytes] | None = None,
) -> dict[str, Any]:
    if receipt_path.exists():
        raise BuildError("receipt output already exists; select a new output")
    base_raw = base_receipt_path.read_bytes()
    try:
        base_supply = rs.RuntimeSupply(base_raw)
        rs.require_kind(base_supply, rs.CICD_RUNTIME)
    except rs.Refused as exc:
        raise BuildError(f"base receipt refused: {exc}") from exc
    base_receipt = json.loads(base_raw)
    source_commit, recipe_bytes = recipe if recipe is not None else committed_recipe(repo)
    base_id = base_supply.image_id

    with tempfile.TemporaryDirectory(prefix="skillc-cicd-project-runtime-") as temp:
        scratch = Path(temp)
        context = scratch / "context"
        lock = _warm_context(project, context)
        pinned = locked_tool_versions(lock)
        base_info = _inspect(run, base_id)
        (context / "Dockerfile").write_bytes(recipe_bytes)
        run(["image", "tag", base_id, base_tag(base_id)])
        iidfile = scratch / "image-id"
        run(["build", "--build-arg", f"BASE={base_tag(base_id)}", "--iidfile", str(iidfile), str(context)])
        image_id = iidfile.read_text().strip()
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
            raise BuildError("build did not produce an immutable image ID")
        layered = _inspect(run, image_id)
        run(["image", "tag", image_id, runtime_tag(image_id)])
        check_layers(base_info, layered)
        check_config(base_info, layered)

        cid = run(["create", "--network", "none", "--entrypoint", "sh", image_id, "-c", SMOKE]).strip()
        if not re.fullmatch(r"[0-9a-f]{64}", cid):
            raise BuildError("Docker create returned an invalid container ID")
        try:
            descriptor_file = scratch / "descriptor.json"
            run(["cp", f"{cid}:{rs.DESCRIPTOR_PATH}", str(descriptor_file)])
            descriptor = descriptor_file.read_bytes()
            run(["cp", f"{context / 'warm'}/.", f"{cid}:/tmp/skillc-smoke-src"])
            smoke = run(["start", "--attach", cid])
        finally:
            run(["rm", "-f", cid])
        if sha256(descriptor) != base_receipt["descriptor_sha256"]:
            raise BuildError("the cicd project image's runtime descriptor differs from its base's")
        if f"pyyaml {YAML_VERSION}" not in smoke.splitlines():
            raise BuildError(f"the offline YAML loader (pyyaml {YAML_VERSION}) did not run")
        measured = parse_tool_versions(smoke)
        if measured != pinned:
            raise BuildError(f"offline tools {measured} differ from the lock's pins {pinned}")

    receipt = {key: base_receipt[key] for key in rs.IDENTITY_KEYS}
    receipt.update(
        image_id=image_id,
        descriptor_sha256=base_receipt["descriptor_sha256"],
        recipe_sha256=sha256(recipe_bytes),
        source_commit=source_commit,
        target=rs.CICD_PROJECT_RUNTIME,
        base_receipt=base_receipt,
        base_image_id=base_id,
        project_lock_sha256=sha256(lock),
        tool_versions=pinned,
    )
    raw = json_bytes(receipt)
    try:
        rs.require_kind(rs.RuntimeSupply(raw), rs.CICD_PROJECT_RUNTIME)
    except rs.Refused as exc:
        raise BuildError(f"built receipt refused: {exc}") from exc
    with receipt_path.open("xb") as output:
        output.write(raw)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-receipt", type=Path, required=True, help="a cicd-runtime receipt")
    parser.add_argument("--project", type=Path, required=True, help="the task project whose lock to warm")
    parser.add_argument("--receipt", type=Path, required=True, help="new cicd-project-runtime receipt path")
    parser.add_argument("--repo", type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        receipt = build_image(args.base_receipt, args.project, args.receipt, repo=args.repo)
    except (BuildError, OSError, subprocess.CalledProcessError) as exc:
        print(f"cicd project runtime refused: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({k: receipt[k] for k in ("image_id", "base_image_id", "tool_versions")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
