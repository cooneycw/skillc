#!/usr/bin/env python3
"""Build the cicd runtime: one curl layer on a validated flow-check receipt.

skillc#280. The input is an EXTERNAL `profile-runtime` receipt that
`skillc.runtime_supply` accepts (the #360 builder's output); the output is a
`cicd-runtime` receipt embedding that base receipt whole. Before writing it,
the builder binds the new image to the base:

1. its layers are the base's layers plus exactly one;
2. its user, working directory, environment, entrypoint and command are the
   base's;
3. its runtime descriptor is the base's, byte for byte;
4. `curl --version`, run with no network, names a version, which is recorded.

The recipe is read from the committed tree at HEAD, never a dirty file.
docker/trial and docker/profile-trial are not inputs and are never changed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from skillc import runtime_supply as rs

RECIPE_PATH = "docker/cicd-trial/Dockerfile"
#: Image configuration the layer must inherit unchanged.
INHERITED_CONFIG = ("User", "WorkingDir", "Env", "Entrypoint", "Cmd")


class BuildError(ValueError):
    """The cicd runtime cannot be bound to its base."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def runtime_tag(image_id: str) -> str:
    """Deterministic name for the built layer, so a kept build is never
    dangling and no prune removes it (#414)."""
    return "skillc-cicd-runtime:" + image_id.removeprefix("sha256:")[:12]


def base_tag(base_image_id: str) -> str:
    """Deterministic local name for the base, left in place after the build.

    Untagging an image's only name deletes it, which would remove the
    operator's base runtime, so the builder never untags.
    """
    return "skillc-cicd-base:" + base_image_id.removeprefix("sha256:")[:12]


def check_layers(base: dict[str, Any], layered: dict[str, Any]) -> None:
    base_layers = base.get("RootFS", {}).get("Layers")
    layers = layered.get("RootFS", {}).get("Layers")
    if not isinstance(base_layers, list) or not isinstance(layers, list) or not base_layers:
        raise BuildError("image layer lists are unreadable")
    if layers[: len(base_layers)] != base_layers or len(layers) != len(base_layers) + 1:
        raise BuildError("the cicd image is not its base plus exactly one layer")


def check_config(base: dict[str, Any], layered: dict[str, Any]) -> None:
    for key in INHERITED_CONFIG:
        if base.get("Config", {}).get(key) != layered.get("Config", {}).get(key):
            raise BuildError(f"the cicd image changed its base's {key}")


def parse_curl_version(text: str) -> str:
    found = re.match(r"curl ([0-9]+\.[0-9]+\.[0-9]+)\b", text)
    if found is None:
        raise BuildError("curl --version did not name a version")
    return found.group(1)


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


def build_image(
    base_receipt_path: Path,
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
        rs.require_kind(base_supply, rs.PROFILE_RUNTIME)
    except rs.Refused as exc:
        raise BuildError(f"base receipt refused: {exc}") from exc
    base_receipt = json.loads(base_raw)
    source_commit, recipe_bytes = recipe if recipe is not None else committed_recipe(repo)
    base_id = base_supply.image_id
    base_info = _inspect(run, base_id)

    with tempfile.TemporaryDirectory(prefix="skillc-cicd-runtime-") as temp:
        scratch = Path(temp)
        context = scratch / "context"
        context.mkdir()
        (context / "Dockerfile").write_bytes(recipe_bytes)
        tag = base_tag(base_id)
        run(["image", "tag", base_id, tag])
        iidfile = scratch / "image-id"
        run(["build", "--build-arg", f"BASE={tag}", "--iidfile", str(iidfile), str(context)])
        image_id = iidfile.read_text().strip()
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
            raise BuildError("build did not produce an immutable image ID")
        layered = _inspect(run, image_id)
        run(["image", "tag", image_id, runtime_tag(image_id)])
        check_layers(base_info, layered)
        check_config(base_info, layered)

        cid = run(["create", "--network", "none", "--entrypoint", "/bin/true", image_id]).strip()
        if not re.fullmatch(r"[0-9a-f]{64}", cid):
            raise BuildError("Docker create returned an invalid container ID")
        try:
            descriptor_file = scratch / "descriptor.json"
            run(["cp", f"{cid}:{rs.DESCRIPTOR_PATH}", str(descriptor_file)])
            descriptor = descriptor_file.read_bytes()
        finally:
            run(["rm", cid])
        if sha256(descriptor) != base_receipt["descriptor_sha256"]:
            raise BuildError("the cicd image's runtime descriptor differs from its base's")
        curl_version = parse_curl_version(
            run(["run", "--rm", "--network", "none", "--entrypoint", "curl", image_id, "--version"])
        )

    receipt = {key: base_receipt[key] for key in rs.IDENTITY_KEYS}
    receipt.update(
        image_id=image_id,
        descriptor_sha256=base_receipt["descriptor_sha256"],
        recipe_sha256=sha256(recipe_bytes),
        source_commit=source_commit,
        target=rs.CICD_RUNTIME,
        base_receipt=base_receipt,
        base_image_id=base_id,
        curl_version=curl_version,
    )
    raw = json_bytes(receipt)
    try:
        rs.require_kind(rs.RuntimeSupply(raw), rs.CICD_RUNTIME)
    except rs.Refused as exc:
        raise BuildError(f"built receipt refused: {exc}") from exc
    # Exclusive creation: a concurrent build cannot replace evidence.
    with receipt_path.open("xb") as output:
        output.write(raw)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-receipt", type=Path, required=True, help="a profile-runtime receipt")
    parser.add_argument("--receipt", type=Path, required=True, help="new cicd-runtime receipt path")
    parser.add_argument("--repo", type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        receipt = build_image(args.base_receipt, args.receipt, repo=args.repo)
    except (BuildError, OSError, subprocess.CalledProcessError) as exc:
        print(f"cicd runtime refused: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({k: receipt[k] for k in ("image_id", "base_image_id", "curl_version")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
