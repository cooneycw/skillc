#!/usr/bin/env python3
"""Build one pinned CPP runtime supply. Stdlib only; no Docker on import/prepare.

Descriptor identity comes from a controller-selected external receipt, never
from a field inside the image claiming to identify that same image.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

RUNTIME_ID = "cpp-codex-flow-check-86641e8"
REVISION = "86641e817711d8a7746270745a5dfa7cacf04b0c"
PYPROJECT = "bc42953d69269328dbe5041d3b7ef6423804492db20b8cf8a59a94c0ee9f3774"
LOCK = "b8edbdd3e0036bc09c849cedee3c1231c468f0f0f9425090c8f2ec914108f3cf"
UV_VERSION = "0.9.7"
ENV = {
    "HOME": "/home/candidate",
    "UV_CACHE_DIR": "/home/candidate/.cache/uv",
    "UV_OFFLINE": "1",
    "UV_LOCKED": "1",
    "UV_PYTHON": "/usr/bin/python3",
    "UV_PYTHON_DOWNLOADS": "never",
    "UV_LINK_MODE": "copy",
}
TARGETS = ("profile-runtime", "profile-runtime-empty-cache", "profile-runtime-cache-permissions")
DESCRIPTOR_PATH = "/usr/local/share/skillc/runtime-supply.json"
IDENTITY = {
    "schema_version": 1,
    "runtime_id": RUNTIME_ID,
    "subject_revision": REVISION,
    "pyproject_sha256": PYPROJECT,
    "lock_sha256": LOCK,
}
POLICY_KEYS = set(IDENTITY) | {"uv_version", "required_env"}
DESCRIPTOR_KEYS = POLICY_KEYS | {"python"}
RECEIPT_KEYS = set(IDENTITY) | {
    "image_id",
    "descriptor_sha256",
    "recipe_sha256",
    "base_recipe_sha256",
    "source_commit",
    "target",
    "build_context_sha256",
}
SUBJECT = f"evals/subjects/{RUNTIME_ID}"
FIXTURE = f"tests/fixtures/profile-{RUNTIME_ID}"
MAX_JSON = 64 * 1024


class SupplyError(ValueError):
    """A runtime-supply contract cannot be established."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise SupplyError(f"duplicate JSON key: {key}")
        out[key] = value
    return out


def load_json(data: bytes, *, limit: int = MAX_JSON) -> dict[str, Any]:
    if not data or len(data) > limit:
        raise SupplyError("missing or oversized JSON input")
    try:
        value = json.loads(data, object_pairs_hook=_pairs)
    except (UnicodeError, ValueError) as exc:
        raise SupplyError(f"malformed JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise SupplyError("JSON object required")
    return value


def _keys(value: Any, expected: set[str], name: str) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise SupplyError(f"{name}: missing or unknown fields")


def _identity(value: dict[str, Any]) -> None:
    for key, expected in IDENTITY.items():
        if type(value.get(key)) is not type(expected) or value[key] != expected:
            raise SupplyError(f"{key}: unsupported pinned identity")


def validate_policy(value: dict[str, Any]) -> None:
    _keys(value, POLICY_KEYS, "policy")
    _identity(value)
    if value["uv_version"] != UV_VERSION or value["required_env"] != ENV:
        raise SupplyError("policy: uv version or required environment drift")


def validate_descriptor(value: dict[str, Any]) -> None:
    _keys(value, DESCRIPTOR_KEYS, "descriptor")
    _identity(value)
    if value["uv_version"] != UV_VERSION:
        raise SupplyError("descriptor: uv version drift")
    env = value["required_env"]
    _keys(env, set(ENV) | {"PATH"}, "required_env")
    if any(env[k] != v for k, v in ENV.items()):
        raise SupplyError("descriptor: required environment drift")
    path = env["PATH"]
    if (
        not isinstance(path, str)
        or not path
        or any(
            not part.startswith("/") or "\x00" in part or "\n" in part for part in path.split(":")
        )
    ):
        raise SupplyError("descriptor: PATH must contain absolute nonempty entries")
    python = value["python"]
    _keys(python, {"executable", "version", "cache_tag", "platform", "machine"}, "python")
    if python["executable"] != ENV["UV_PYTHON"] or python["platform"] != "linux":
        raise SupplyError("descriptor: unexpected interpreter/platform")
    version = python["version"]
    if not isinstance(version, str) or not re.fullmatch(r"3\.[0-9]+\.[0-9]+", version):
        raise SupplyError("descriptor: malformed Python version")
    major, minor, _ = map(int, version.split("."))
    if minor < 11 or python["cache_tag"] != f"cpython-{major}{minor}":
        raise SupplyError("descriptor: unsupported Python version/cache tag")
    if python["machine"] not in ("x86_64", "aarch64"):
        raise SupplyError("descriptor: unsupported machine")


def validate_receipt(
    value: dict[str, Any],
    descriptor_bytes: bytes,
    image_id: str,
    *,
    expected: dict[str, Any] | None = None,
    target: str = "profile-runtime",
) -> None:
    _keys(value, RECEIPT_KEYS, "receipt")
    _identity(value)
    validate_descriptor(load_json(descriptor_bytes))
    if not isinstance(image_id, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
        raise SupplyError("receipt: actual immutable image ID required")
    if value["image_id"] != image_id:
        raise SupplyError("receipt: actual image mismatch")
    if target not in TARGETS or value["target"] != target:
        raise SupplyError("receipt: target mismatch")
    for key in ("descriptor_sha256", "recipe_sha256", "base_recipe_sha256", "build_context_sha256"):
        if not isinstance(value[key], str) or not re.fullmatch(r"[0-9a-f]{64}", value[key]):
            raise SupplyError(f"receipt: malformed {key}")
    if not isinstance(value["source_commit"], str) or not re.fullmatch(
        r"[0-9a-f]{40}", value["source_commit"]
    ):
        raise SupplyError("receipt: full source commit required")
    if value["descriptor_sha256"] != sha256(descriptor_bytes):
        raise SupplyError("receipt: descriptor digest mismatch")
    if expected is not None:
        for key in ("source_commit", "recipe_sha256", "base_recipe_sha256", "build_context_sha256"):
            if value[key] != expected[key]:
                raise SupplyError(f"receipt: prepared {key} mismatch")


def validate_metadata(metadata: dict[str, bytes]) -> None:
    _keys(metadata, {"pyproject.toml", "uv.lock"}, "metadata")
    for name, expected in (("pyproject.toml", PYPROJECT), ("uv.lock", LOCK)):
        if sha256(metadata[name]) != expected:
            raise SupplyError(f"metadata: {name} digest mismatch")


def _files(value: Any) -> list[dict[str, Any]]:
    """Walk the pinned inventory's nested file records, not the fixture tree."""
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if "source" in value and "destination" in value:
            found.append(value)
        for child in value.values():
            found.extend(_files(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_files(child))
    return found


def validate_inventory(subject: dict[str, Any], inventory: dict[str, Any]) -> None:
    inventory_subject = inventory.get("subject")
    if (
        subject.get("revision") != REVISION
        or not isinstance(inventory_subject, dict)
        or inventory_subject.get("revision") != REVISION
    ):
        raise SupplyError("subject/inventory: revision mismatch")
    files = _files(inventory)
    for name, digest in (("pyproject.toml", PYPROJECT), ("uv.lock", LOCK)):
        records = [f for f in files if f["destination"] == f"Projects/claude-power-pack/{name}"]
        if (
            len(records) != 1
            or records[0].get("source") != name
            or records[0].get("digest") != ("sha256:" + digest)
            or records[0].get("origin") != "pinned"
        ):
            raise SupplyError(f"inventory: {name} missing or mismatched")


def validate_additions(paths: list[str]) -> None:
    """Closed final COPY destinations: source/skill/venv are never additions."""
    if paths != [DESCRIPTOR_PATH, ENV["UV_CACHE_DIR"]]:
        raise SupplyError("final additions: unexpected source, venv or other path")


def render_recipe(base: bytes, fragment: bytes, policy: dict[str, Any]) -> bytes:
    validate_policy(policy)
    if b"FROM base AS trial\n" not in base:
        raise SupplyError("base recipe: named trial stage missing")
    text = fragment.decode("utf-8")
    # Docker comments are physical lines. Joining first could hide the next
    # instruction inside a comment, so this bounded format forbids that syntax.
    if any(
        line.lstrip().startswith("#") and line.rstrip().endswith("\\") for line in text.splitlines()
    ):
        raise SupplyError("fragment: comment continuation is unsupported")
    if text.count("@RUNTIME_ENV@") != 1:
        raise SupplyError("fragment: missing or duplicate environment marker")
    env = "ENV " + " \\\n    ".join(
        f"{key}={json.dumps(val)}" for key, val in policy["required_env"].items()
    )
    text = text.replace("@RUNTIME_ENV@", env)
    # Check the final COPY allowlist against the recipe that will actually run.
    # Builder COPYs are intentionally excluded; that stage never ships.
    final = text.split("FROM trial AS profile-runtime-empty-cache\n")
    if len(final) != 2:
        raise SupplyError("fragment: common runtime stage missing")
    warm = [
        " ".join(line.split())
        for line in final[0].replace("\\\n", " ").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    expected_warm = [
        "FROM trial AS profile-runtime-cache",
        "USER root",
        "WORKDIR /tmp/runtime-supply",
        "COPY metadata/ ./metadata/",
        "COPY runtime-policy.json runtime-build.py ./",
        (
            "RUN UV_CACHE_DIR=/tmp/dependency-cache UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy "
            "uv sync --locked --no-install-project --python /usr/bin/python3 --project ./metadata "
            "&& /usr/bin/python3 runtime-build.py --write-descriptor /tmp/runtime-supply"
        ),
    ]
    if warm != expected_warm:
        raise SupplyError("warm recipe: unsupported instruction, base or locked-sync drift")
    copies = re.findall(r"^COPY\s+.*\s+(\S+)\s*$", final[1], re.MULTILINE)
    validate_additions(copies)
    copy_lines = re.findall(r"^COPY[^\n]+$", final[1], re.MULTILINE)
    if copy_lines != [
        "COPY --from=profile-runtime-cache /tmp/runtime-supply/runtime-supply.json "
        + DESCRIPTOR_PATH,
        "COPY --from=profile-runtime-cache --chown=candidate:candidate /tmp/dependency-cache "
        + ENV["UV_CACHE_DIR"],
    ]:
        raise SupplyError("final additions: unexpected COPY source or ownership")
    # This is a bounded recipe, not a general Dockerfile parser. Reject all
    # unrecognised final-stage instructions, including ADD, alternate COPY
    # spelling, shell copies and an inherited final root user. Docker accepts
    # leading spaces, lowercase instructions and line continuations.
    logical = final[1].replace("\\\n", " ")
    actual = [
        " ".join(line.split())
        for line in logical.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    expected = [
        "USER root",
        "WORKDIR /work",
        " ".join(env.replace("\\\n", " ").split()),
        copy_lines[0],
        (
            "RUN chmod 755 /usr/local /usr/local/share /usr/local/share/skillc "
            "&& chmod 644 /usr/local/share/skillc/runtime-supply.json "
            "&& mkdir -p /home/candidate/.cache/uv "
            "&& chown -R candidate:candidate /home/candidate/.cache"
        ),
        "USER candidate",
        "FROM profile-runtime-empty-cache AS profile-runtime",
        "USER root",
        copy_lines[1],
        "USER candidate",
        "FROM profile-runtime AS profile-runtime-cache-permissions",
        "USER root",
        (
            "RUN chown -R root:root /home/candidate/.cache/uv "
            "&& chmod -R a-w /home/candidate/.cache/uv"
        ),
        "USER candidate",
    ]
    if actual != expected:
        raise SupplyError("final recipe: unsupported instruction or runtime policy drift")
    return base + b"\n" + text.encode()


def _git(repo: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True).stdout


def source_inputs(repo: Path) -> tuple[str, dict[str, bytes]]:
    """Read committed inputs at one resolved HEAD, ignoring dirty/operator trees."""
    commit = _git(repo, "rev-parse", "HEAD").decode().strip()
    rows = _git(repo, "ls-tree", "-rz", commit, "docker/trial").split(b"\0")
    names = []
    for row in filter(None, rows):
        meta, name = row.split(b"\t", 1)
        mode, kind, _ = meta.split()
        if mode not in (b"100644", b"100755") or kind != b"blob":
            raise SupplyError("trial inputs: only tracked regular files accepted")
        names.append(name.decode())
    if not names:
        raise SupplyError("trial inputs: empty population")
    names += [f"{SUBJECT}/subject.json", f"{SUBJECT}/evidence/inventory.json"]
    names += [f"{FIXTURE}/{name}" for name in ("pyproject.toml", "uv.lock")]
    return commit, {name: _git(repo, "show", f"{commit}:{name}") for name in names}


def prepare(
    repo: Path,
    context: Path,
    *,
    inputs: dict[str, bytes] | None = None,
    source_commit: str | None = None,
    policy_bytes: bytes | None = None,
    fragment: bytes | None = None,
) -> dict[str, Any]:
    """Validate everything before writing the isolated context or invoking Docker."""
    here = Path(__file__).resolve().parent
    policy = load_json(
        policy_bytes if policy_bytes is not None else (here / "runtime-policy.json").read_bytes()
    )
    validate_policy(policy)
    if inputs is None:
        source_commit, inputs = source_inputs(repo)
    if source_commit is None or not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise SupplyError("source commit: full commit required")
    metadata = {
        name: inputs.get(f"{FIXTURE}/{name}", b"") for name in ("pyproject.toml", "uv.lock")
    }
    validate_metadata(metadata)
    validate_inventory(
        load_json(inputs.get(f"{SUBJECT}/subject.json", b"")),
        load_json(inputs.get(f"{SUBJECT}/evidence/inventory.json", b""), limit=1024 * 1024),
    )
    base = inputs.get("docker/trial/Dockerfile", b"")
    pins = load_json(inputs.get("docker/trial/pinned-versions.json", b""))
    if pins.get("uv", {}).get("version") != UV_VERSION:
        raise SupplyError("trial uv pin drift")
    # Reject extra input families and path traversal, rather than silently copy
    # source trees supplied by a future caller into a Docker context.
    expected = {f"{SUBJECT}/subject.json", f"{SUBJECT}/evidence/inventory.json"}
    expected |= {f"{FIXTURE}/{n}" for n in metadata}
    for name in inputs:
        if name in expected:
            continue
        path = Path(name)
        if path.parent != Path("docker/trial") or ".." in path.parts:
            raise SupplyError(f"unexpected build input: {name}")
    fragment = fragment if fragment is not None else (here / "Dockerfile.fragment").read_bytes()
    recipe = render_recipe(base, fragment, policy)
    context.mkdir(parents=True, exist_ok=False)
    for name, data in inputs.items():
        if Path(name).parent == Path("docker/trial") and Path(name).name != "Dockerfile":
            (context / Path(name).name).write_bytes(data)
    (context / "metadata").mkdir()
    for name, data in metadata.items():
        (context / "metadata" / name).write_bytes(data)
    (context / "runtime-policy.json").write_bytes(json_bytes(policy))
    (context / "runtime-build.py").write_bytes(Path(__file__).read_bytes())
    (context / "Dockerfile").write_bytes(recipe)
    context_digest = sha256(
        json_bytes(
            {
                str(path.relative_to(context)): sha256(path.read_bytes())
                for path in sorted(context.rglob("*"))
                if path.is_file()
            }
        )
    )
    return {
        "policy": policy,
        "source_commit": source_commit,
        "build_context_sha256": context_digest,
        "base_recipe_sha256": sha256(base),
        "recipe_sha256": sha256(recipe),
    }


def write_descriptor(root: Path) -> None:
    """Run only in the cache builder, under its actual trial interpreter."""
    policy = load_json((root / "runtime-policy.json").read_bytes())
    validate_policy(policy)
    validate_metadata(
        {n: (root / "metadata" / n).read_bytes() for n in ("pyproject.toml", "uv.lock")}
    )
    uv = subprocess.run(
        ["uv", "--version"], check=True, capture_output=True, text=True
    ).stdout.split()
    if len(uv) < 2 or uv[:2] != ["uv", UV_VERSION]:
        raise SupplyError("measured uv version mismatch")
    descriptor = dict(policy)
    descriptor["required_env"] = dict(ENV, PATH=os.environ["PATH"])
    descriptor["python"] = {
        "executable": sys.executable,
        "version": platform.python_version(),
        "cache_tag": sys.implementation.cache_tag,
        "platform": sys.platform,
        "machine": platform.machine(),
    }
    validate_descriptor(descriptor)
    (root / "runtime-supply.json").write_bytes(json_bytes(descriptor))


def docker(argv: list[str]) -> str:
    try:
        return subprocess.run(["docker", *argv], check=True, capture_output=True, text=True).stdout
    except subprocess.CalledProcessError as exc:
        diagnostic = (exc.stderr or exc.stdout or "no diagnostic")[-16000:]
        raise SupplyError(f"docker {argv[0]} exited {exc.returncode}: {diagnostic}") from exc


def image_tag(receipt: dict[str, Any]) -> str:
    """The deterministic tag a build gives its image (#414). An untagged build
    is dangling, and a host-wide `docker image prune` deletes it from under
    every receipt that names it by ID. Derived from the receipt alone, so
    rebuilding the same inputs re-tags the same name; 12 characters of the
    commit, so it never collides with a hand-made 7-character tag."""
    tag = f"skillc-profile-runtime:{receipt['runtime_id']}-{receipt['source_commit'][:12]}"
    if receipt["target"] != "profile-runtime":
        tag += f"-{receipt['target']}"
    return tag


def image_inventory(*, run: Callable[[list[str]], str] = docker) -> dict[str, Any]:
    """Every image ID and tag on the daemon now - taken BEFORE a build, so
    `release_build` can tell what that build added from what was already
    there (#414)."""
    ids: set[str] = set()
    tags: dict[str, str] = {}
    listing = run(["images", "-a", "--no-trunc", "--format", "{{.ID}}\t{{.Repository}}:{{.Tag}}"])
    for line in listing.splitlines():
        image_id, _, name = line.partition("\t")
        if not image_id:
            continue
        ids.add(image_id)
        if name and "<none>" not in name:
            tags[name] = image_id
    return {"ids": ids, "tags": tags}


def release_build(
    receipt: dict[str, Any], before: dict[str, Any], *, run: Callable[[list[str]], str] = docker,
) -> None:
    """Undo exactly what one `build_image` added (#414), and nothing else.

    An image ID that existed before the build is never touched - a co-tenant
    built the same inputs, and even removing our tag from it would delete the
    image if that tag were its only one. A NEW image goes, without `-f` and
    with `--no-prune`, so the daemon refuses if anything else references it
    and keeps any untagged parent. `docker tag` moves an existing tag, so a tag
    that pointed at another image before the build is put back first - even
    when the build reused an image that already existed: a pre-existing tag
    is never removed."""
    image_id = receipt["image_id"]
    tag = image_tag(receipt)
    previous = before["tags"].get(tag)
    # Restore first: a cached build can reuse an image that already existed
    # and still move the tag onto it (#414 review).
    if previous is not None and previous != image_id:
        run(["tag", previous, tag])
    if image_id in before["ids"]:
        return
    try:
        # --no-prune: an untagged parent that was already there stays.
        run(["image", "rm", "--no-prune", image_id])
    except SupplyError:
        pass  # still referenced elsewhere: not ours to force


def build_image(
    repo: Path,
    receipt_path: Path,
    *,
    target: str = "profile-runtime",
    run: Callable[[list[str]], str] = docker,
    **prepare_args: Any,
) -> dict[str, Any]:
    if target not in TARGETS:
        raise SupplyError("unsupported target")
    # Prevent a stale receipt from appearing to certify a failed new build.
    if receipt_path.exists():
        raise SupplyError("receipt output already exists; select a new output")
    with tempfile.TemporaryDirectory(prefix="skillc-profile-runtime-") as temp:
        scratch = Path(temp)
        context = scratch / "context"
        prepared = prepare(repo, context, **prepare_args)
        iidfile = scratch / "image-id"
        run(["build", "--target", target, "--iidfile", str(iidfile), str(context)])
        image_id = iidfile.read_text().strip()
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
            raise SupplyError("build did not produce an immutable image ID")
        info = json.loads(run(["image", "inspect", image_id]))
        if not isinstance(info, list) or len(info) != 1 or info[0].get("Id") != image_id:
            raise SupplyError("inspected image ID mismatch")
        if info[0].get("Config", {}).get("User") != "candidate":
            raise SupplyError("final image must run as candidate")
        cid = run(["create", "--network", "none", "--entrypoint", "/bin/true", image_id]).strip()
        if not re.fullmatch(r"[0-9a-f]{64}", cid):
            raise SupplyError("Docker create returned invalid container ID")
        try:
            descriptor_file = scratch / "descriptor.json"
            run(["cp", f"{cid}:{DESCRIPTOR_PATH}", str(descriptor_file)])
            descriptor = descriptor_file.read_bytes()
        finally:
            run(["rm", cid])
        receipt = dict(
            IDENTITY,
            image_id=image_id,
            target=target,
            descriptor_sha256=sha256(descriptor),
            **{
                k: prepared[k]
                for k in (
                    "source_commit",
                    "recipe_sha256",
                    "base_recipe_sha256",
                    "build_context_sha256",
                )
            },
        )
        validate_receipt(receipt, descriptor, image_id, expected=prepared, target=target)
        config_env: dict[str, str] = {}
        for item in info[0]["Config"].get("Env", []):
            key, sep, val = item.partition("=")
            if not sep or key in config_env:
                raise SupplyError("invalid image environment")
            config_env[key] = val
        if "UV_PROJECT_ENVIRONMENT" in config_env:
            raise SupplyError("image environment must not set UV_PROJECT_ENVIRONMENT")
        required = load_json(descriptor)["required_env"]
        if any(config_env.get(k) != v for k, v in required.items()):
            raise SupplyError("image configuration/descriptor environment mismatch")
        # Tag before the receipt exists, so a receipt always implies its tag
        # (#414); a failed tag raises and no receipt is written.
        run(["tag", image_id, image_tag(receipt)])
        # Exclusive creation ensures a concurrent build cannot replace evidence.
        with receipt_path.open("xb") as output:
            output.write(json_bytes(receipt))
        return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--target", choices=TARGETS, default="profile-runtime")
    parser.add_argument("--write-descriptor", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        if args.write_descriptor is not None:
            write_descriptor(args.write_descriptor)
        elif args.receipt is None:
            parser.error("--receipt is required")
        else:
            receipt = build_image(args.repo, args.receipt, target=args.target)
            print(json.dumps(receipt, sort_keys=True))
    except (SupplyError, OSError, subprocess.CalledProcessError) as exc:
        print(f"runtime supply refused: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
