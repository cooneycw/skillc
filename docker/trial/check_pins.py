"""Prove the Dockerfile's ARG defaults match pinned-versions.json (issue #78).

The Dockerfile cannot import JSON, so its ARG defaults are a second literal
by construction - exactly the drift #73 closed for skillc's own version, one
level down. This script is the committed control: it reads both sources and
refuses on any mismatch. It needs no Docker daemon and no network, so it runs
in CI and in this session alike, unlike the image build itself.

Red case: `tests/test_trial_bootstrap.py` renders a copy of the Dockerfile
with a stale ARG default and asserts `check_pins` reports it as drifted.

A Codex code-review finding on issue #78 caught the first version of this
module conflating two different populations under one check: it required
EVERY Dockerfile `ARG` to be one of exactly two hardcoded, hand-maintained
names, so an unrelated build argument (say `ARG BUILD_LABEL=trial`) failed
the check even though the actual CLI pins still agreed - "our thing changed"
and "a neighbour changed" were indistinguishable. It also could not notice a
THIRD pin added to `pinned-versions.json` without a matching, hand-added
entry in this file's own mapping, which is exactly the silent-miss shape a
manifest-driven check exists to prevent. Both are fixed the same way: the
required ARG name for each manifest entry is DERIVED from the manifest key
(`claude_code` -> `CLAUDE_CODE_VERSION`), so there is no second mapping to
fall out of sync, and only ARG names that themselves look like a version pin
(`*_VERSION`) are checked for being untracked - an unrelated ARG is left
alone entirely.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_ARG_RE = re.compile(r"^ARG\s+(\w+)=(\S+)\s*$", re.MULTILINE)

#: Only ARGs shaped like a version pin are candidates for the "untracked"
#: check below - an ARG with an unrelated purpose (`BUILD_LABEL`, say) is
#: none of this instrument's business and must not be flagged.
_VERSION_ARG_SUFFIX = "_VERSION"


class PinDrift(Exception):
    """The Dockerfile's ARG defaults and pinned-versions.json disagree."""


def dockerfile_args(text: str) -> dict[str, str]:
    """Every `ARG NAME=value` default in `text`, in the order they appear."""
    return dict(_ARG_RE.findall(text))


def required_pins(manifest: dict[str, object]) -> dict[str, str]:
    """Map each manifest entry with a `version` to the Dockerfile ARG name
    REQUIRED to pin it, derived mechanically from the manifest key
    (`claude_code` -> `CLAUDE_CODE_VERSION`) rather than a second,
    hand-maintained mapping that a new pin could be added without updating."""
    pins: dict[str, str] = {}
    for key, entry in manifest.items():
        if key.startswith("_"):
            continue
        if isinstance(entry, dict) and isinstance(entry.get("version"), str):
            pins[f"{key.upper()}{_VERSION_ARG_SUFFIX}"] = entry["version"]
    return pins


def check_pins(dockerfile_text: str, manifest: dict[str, object]) -> list[str]:
    """Return one message per drift; an empty list means the pins agree.

    Never returns an empty list merely because nothing was found to compare:
    a manifest entry with no corresponding ARG, or an ARG whose value
    disagrees with the manifest, is reported. Separately, any Dockerfile ARG
    that itself LOOKS like a version pin (ends in `_VERSION`) but names no
    manifest entry is reported too - a stray, unpinned-by-manifest pin
    cannot pass by omission. An ARG that does not look like a version pin at
    all (no `_VERSION` suffix) is none of this check's business and is never
    reported, however unrelated to CLI pinning it is.
    """
    args = dockerfile_args(dockerfile_text)
    pins = required_pins(manifest)
    messages: list[str] = []
    for arg_name, manifest_version in pins.items():
        if arg_name not in args:
            messages.append(f"Dockerfile has no ARG {arg_name}, required by pinned-versions.json")
            continue
        dockerfile_version = args[arg_name]
        if dockerfile_version != manifest_version:
            messages.append(f"{arg_name}={dockerfile_version} in Dockerfile but pinned-versions.json says {manifest_version}")
    for arg_name in args:
        if arg_name.endswith(_VERSION_ARG_SUFFIX) and arg_name not in pins:
            messages.append(f"Dockerfile ARG {arg_name} looks like a version pin but pinned-versions.json has no matching entry")
    return messages


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).parent
    dockerfile_text = (root / "Dockerfile").read_text(encoding="utf-8")
    manifest = json.loads((root / "pinned-versions.json").read_text(encoding="utf-8"))
    messages = check_pins(dockerfile_text, manifest)
    if messages:
        for message in messages:
            print(f"check-pins: {message}")
        return 1
    print("check-pins: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
