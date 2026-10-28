#!/usr/bin/env python3
"""Build a NON-primary pinned profile runtime (#279, orchestrator policy B).

`build.py` builds the PRIMARY runtime, and its own bytes are that runtime's
build context (it is copied in as `runtime-build.py`), so it is never edited to
support another pin. For a runtime listed in `runtime-policy-extra.json`, this
generates `build.py` with exactly its identity lines (RUNTIME_ID, REVISION,
and - #529 - the dependency layer's PYPROJECT and LOCK) rebound, places it beside a copy of `Dockerfile.fragment` in a private
directory, and runs THAT builder: its identity checks, inside and outside the
image, are the selected runtime's, and its context is deterministic.

Usage: build_runtime.py --runtime <id> --receipt <new path> [--repo R] [--target T]
Stdlib only.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from types import ModuleType
from typing import Any

HERE = Path(__file__).resolve().parent
PRIMARY_LINES = ('RUNTIME_ID = "cpp-codex-flow-check-86641e8"\n',
                 'REVISION = "86641e817711d8a7746270745a5dfa7cacf04b0c"\n',
                 'PYPROJECT = "bc42953d69269328dbe5041d3b7ef6423804492db20b8cf8a59a94c0ee9f3774"\n',
                 'LOCK = "b8edbdd3e0036bc09c849cedee3c1231c468f0f0f9425090c8f2ec914108f3cf"\n')


class RuntimeRefused(ValueError):
    """The requested runtime is not one this builder supplies."""


def extra_runtimes() -> dict[str, dict[str, Any]]:
    data = json.loads((HERE / "runtime-policy-extra.json").read_bytes())
    entries = data.get("profile_runtimes") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise RuntimeRefused("runtime-policy-extra.json lists no profile runtimes")
    found: dict[str, dict[str, Any]] = {}
    for entry in entries:
        runtime_id = entry.get("runtime_id") if isinstance(entry, dict) else None
        if not isinstance(runtime_id, str) or runtime_id in found:
            raise RuntimeRefused("runtime-policy-extra.json has a missing or duplicate runtime_id")
        found[runtime_id] = entry
    return found


def builder_source(runtime_id: str, revision: str, pyproject: str | None = None, lock: str | None = None) -> bytes:
    """`build.py` with its identity rebound - and nothing else changed. #529:
    the dependency-layer identity too, for a pin whose `pyproject.toml` and
    `uv.lock` differ from the primary's; left unset, those lines are the
    primary's own, so a same-layer pin's builder (ca3030d) is unchanged."""
    text = (HERE / "build.py").read_text(encoding="utf-8")
    for line in PRIMARY_LINES:
        if text.count(line) != 1:
            raise RuntimeRefused("build.py's identity lines changed; this generator must be revisited")
    rebound = [f"RUNTIME_ID = {json.dumps(runtime_id)}\n", f"REVISION = {json.dumps(revision)}\n",
               *(f"{name} = {json.dumps(value)}\n" if value is not None else line
                 for name, value, line in (("PYPROJECT", pyproject, PRIMARY_LINES[2]), ("LOCK", lock, PRIMARY_LINES[3])))]
    for old, new in zip(PRIMARY_LINES, rebound, strict=True):
        text = text.replace(old, new)
    return text.encode("utf-8")


def load_builder(runtime_id: str, workdir: Path) -> tuple[ModuleType, bytes]:
    """The selected runtime's builder module, and its policy as build.py's own fields."""
    runtimes = extra_runtimes()
    if runtime_id not in runtimes:
        raise RuntimeRefused(f"runtime {runtime_id!r} is not an extra runtime of this builder "
                             "(the primary is built by build.py itself)")
    entry = runtimes[runtime_id]
    path = workdir / "build.py"
    path.write_bytes(builder_source(runtime_id, str(entry["subject_revision"]),
                                    str(entry["pyproject_sha256"]), str(entry["lock_sha256"])))
    (workdir / "Dockerfile.fragment").write_bytes((HERE / "Dockerfile.fragment").read_bytes())
    spec = importlib.util.spec_from_file_location(f"profile_runtime_build_{runtime_id.replace('-', '_')}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    policy = {key: entry[key] for key in sorted(module.POLICY_KEYS)}
    module.validate_policy(policy)
    return module, module.json_bytes(policy)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=HERE.parents[1])
    parser.add_argument("--target", default="profile-runtime")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="skillc-runtime-builder-") as tmp:
        try:
            build, policy = load_builder(args.runtime, Path(tmp))
            receipt = build.build_image(args.repo, args.receipt, target=args.target, policy_bytes=policy)
        except (RuntimeRefused, ValueError, OSError) as exc:
            print(f"runtime supply refused: {exc}", file=sys.stderr)
            return 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
