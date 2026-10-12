"""Controller-selected CPP runtime contract (#348/#360), never subject evidence.

The supported pin is deliberately bounded. A different SKILL description may
share this runtime; different dependency metadata does not inherit its proof.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MAX_JSON = 64 * 1024
RUNTIME_ID = "cpp-codex-flow-check-ea6dbfa"
LOCATOR = "github.com/cooneycw/claude-power-pack"
REVISION = "ea6dbfa45f9308ee6ba60f032d8e7031bd6938a1"
PROJECT = "Projects/claude-power-pack"
GATE = ".claude/scripts/flow-finish-gate.sh"
DESCRIPTOR_PATH = "/usr/local/share/skillc/runtime-supply.json"
PYPROJECT = "bc42953d69269328dbe5041d3b7ef6423804492db20b8cf8a59a94c0ee9f3774"
LOCK = "b8edbdd3e0036bc09c849cedee3c1231c468f0f0f9425090c8f2ec914108f3cf"
UV_VERSION = "0.9.7"
ENV = {
    "HOME": "/home/candidate", "UV_CACHE_DIR": "/home/candidate/.cache/uv",
    "UV_OFFLINE": "1", "UV_LOCKED": "1", "UV_PYTHON": "/usr/bin/python3",
    "UV_PYTHON_DOWNLOADS": "never", "UV_LINK_MODE": "copy",
}
IDENTITY = {"schema_version": 1, "runtime_id": RUNTIME_ID, "subject_revision": REVISION,
            "pyproject_sha256": PYPROJECT, "lock_sha256": LOCK}
RECEIPT_KEYS = set(IDENTITY) | {"image_id", "descriptor_sha256", "recipe_sha256",
                              "base_recipe_sha256", "build_context_sha256", "source_commit", "target"}
DESCRIPTOR_KEYS = set(IDENTITY) | {"uv_version", "python", "required_env"}
METADATA = {f"{PROJECT}/pyproject.toml": "sha256:" + PYPROJECT,
            f"{PROJECT}/uv.lock": "sha256:" + LOCK}


class Refused(ValueError):
    """The selected runtime cannot establish its declared identity or policy."""


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise Refused("duplicate runtime JSON key")
        result[key] = value
    return result


def load_json(raw: bytes) -> dict[str, Any]:
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_JSON:
        raise Refused("runtime JSON missing or oversized")
    try:
        value = json.loads(raw, object_pairs_hook=_pairs)
    except (UnicodeError, ValueError) as exc:
        raise Refused("malformed runtime JSON") from exc
    if not isinstance(value, dict):
        raise Refused("runtime JSON must be an object")
    return value


def _keys(value: object, expected: set[str], label: str) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise Refused(f"runtime {label} has missing or unknown fields")


def _identity(value: Mapping[str, object]) -> None:
    for key, expected in IDENTITY.items():
        if type(value.get(key)) is not type(expected) or value[key] != expected:
            raise Refused(f"unsupported runtime {key}")


def _hex(value: object, length: int) -> bool:
    return isinstance(value, str) and re.fullmatch(f"[0-9a-f]{{{length}}}", value) is not None


def _receipt(raw: bytes) -> dict[str, Any]:
    value = load_json(raw)
    _keys(value, RECEIPT_KEYS, "receipt")
    _identity(value)
    if value["target"] != "profile-runtime":
        raise Refused("runtime receipt target is not the normal runtime")
    if not isinstance(value["image_id"], str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", value["image_id"]):
        raise Refused("runtime receipt image must be immutable")
    if not _hex(value["source_commit"], 40):
        raise Refused("runtime receipt source commit is malformed")
    for key in ("descriptor_sha256", "recipe_sha256", "base_recipe_sha256", "build_context_sha256"):
        if not _hex(value[key], 64):
            raise Refused(f"runtime receipt {key} is malformed")
    return value


@dataclass(frozen=True)
class RuntimeSupply:
    """Immutable validated receipt bytes supplied by the controller/operator."""

    receipt_bytes: bytes = field(repr=False)

    def __post_init__(self) -> None:
        _receipt(self.receipt_bytes)

    @classmethod
    def from_path(cls, path: Path) -> RuntimeSupply:
        try:
            with path.open("rb") as stream:
                return cls(stream.read(MAX_JSON + 1))
        except OSError as exc:
            raise Refused("runtime receipt is unreadable") from exc

    @property
    def image_id(self) -> str:
        return str(_receipt(self.receipt_bytes)["image_id"])

    def descriptor(self, raw: bytes, *, actual_image: str) -> dict[str, Any]:
        receipt = _receipt(self.receipt_bytes)
        if actual_image != self.image_id:
            raise Refused("runtime actual image differs from selected receipt")
        if hashlib.sha256(raw).hexdigest() != receipt["descriptor_sha256"]:
            raise Refused("runtime descriptor bytes differ from selected receipt")
        value = load_json(raw)
        _keys(value, DESCRIPTOR_KEYS, "descriptor")
        _identity(value)
        if value["uv_version"] != UV_VERSION:
            raise Refused("runtime uv version differs from supported policy")
        required = value["required_env"]
        _keys(required, set(ENV) | {"PATH"}, "required environment")
        if any(required[key] != expected for key, expected in ENV.items()):
            raise Refused("runtime required environment differs from supported policy")
        path = required["PATH"]
        if not isinstance(path, str) or not path or any(
            not part.startswith("/") or "\0" in part or "\n" in part for part in path.split(":")
        ):
            raise Refused("runtime PATH must contain absolute nonempty entries")
        python = value["python"]
        _keys(python, {"executable", "version", "cache_tag", "platform", "machine"}, "Python identity")
        version = python["version"]
        if not isinstance(version, str) or not re.fullmatch(r"3\.[0-9]+\.[0-9]+", version):
            raise Refused("runtime Python version is malformed")
        major, minor, _ = map(int, version.split("."))
        if (minor < 11 or python["executable"] != ENV["UV_PYTHON"] or python["platform"] != "linux"
                or python["cache_tag"] != f"cpython-{major}{minor}" or python["machine"] not in ("x86_64", "aarch64")):
            raise Refused("runtime Python identity differs from supported policy")
        return value


def environment(raw: bytes) -> dict[str, str]:
    """Parse a complete bounded NUL-delimited environment without logging it."""
    if not raw or len(raw) > MAX_JSON or not raw.endswith(b"\0"):
        raise Refused("runtime environment is missing, oversized or incomplete")
    result: dict[str, str] = {}
    try:
        for item in raw[:-1].split(b"\0"):
            key, separator, value = item.decode("utf-8").partition("=")
            if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) or key in result:
                raise Refused("runtime environment has malformed or duplicate names")
            result[key] = value
    except UnicodeError as exc:
        raise Refused("runtime environment is not UTF-8") from exc
    return result


def validate_environment(env: Mapping[str, str], descriptor: Mapping[str, Any]) -> None:
    if "UV_PROJECT_ENVIRONMENT" in env:
        raise Refused("undeclared UV_PROJECT_ENVIRONMENT cannot select an external venv")
    if any(key.startswith("UV_") and key not in ENV for key in env):
        raise Refused("undeclared uv environment override")
    if any(env.get(key) != value for key, value in descriptor["required_env"].items()):
        raise Refused("effective runtime environment differs from selected policy")


def requires_supply(*, locator: str, revision: str, gate_entrypoint: str | None,
                    files: Mapping[str, str], tools: Sequence[Mapping[str, Any]]) -> bool:
    """Classify a freshly validated closure, never its directory or SKILL text.

    A derived skill may use this runtime only while retaining the same supported
    subject/dependency facts. Changed metadata in that family is a refusal, not
    a silent downgrade. Other pins/projects are not new supported runtimes.
    """
    selected = locator == LOCATOR and revision == REVISION and gate_entrypoint == GATE
    project_probe = any(probe.get("kind") == "python-import" and probe.get("uv_project") == PROJECT
                        for tool in tools for probe in tool.get("probes", ()))
    if selected and not project_probe:
        raise Refused("supported profile runtime project probe changed or is missing")
    if selected and any(files.get(path) != digest for path, digest in METADATA.items()):
        raise Refused("supported profile runtime metadata changed or is missing")
    return selected
