#!/usr/bin/env python3
"""Build a NON-primary pinned profile runtime (#279, orchestrator policy B).

`build.py` builds the PRIMARY runtime, and its own bytes are that runtime's
build context (it is copied in as `runtime-build.py`), so it is never edited to
support another pin. For a runtime listed in `runtime-policy-extra.json`, this
generates `build.py` with exactly its two identity lines (RUNTIME_ID, REVISION)
rebound, places it beside a copy of `Dockerfile.fragment` in a private
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
                 'REVISION = "86641e817711d8a7746270745a5dfa7cacf04b0c"\n')


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


def builder_source(runtime_id: str, revision: str) -> bytes:
    """`build.py` with its identity rebound - and nothing else changed."""
    text = (HERE / "build.py").read_text(encoding="utf-8")
    for line in PRIMARY_LINES:
        if text.count(line) != 1:
            raise RuntimeRefused("build.py's identity lines changed; this generator must be revisited")
    text = text.replace(PRIMARY_LINES[0], f"RUNTIME_ID = {json.dumps(runtime_id)}\n")
    return text.replace(PRIMARY_LINES[1], f"REVISION = {json.dumps(revision)}\n").encode("utf-8")


def load_builder(runtime_id: str, workdir: Path) -> tuple[ModuleType, bytes]:
    """The selected runtime's builder module, and its policy as build.py's own fields."""
    runtimes = extra_runtimes()
    if runtime_id not in runtimes:
        raise RuntimeRefused(f"runtime {runtime_id!r} is not an extra runtime of this builder "
                             "(the primary is built by build.py itself)")
    entry = runtimes[runtime_id]
    path = workdir / "build.py"
    path.write_bytes(builder_source(runtime_id, str(entry["subject_revision"])))
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
