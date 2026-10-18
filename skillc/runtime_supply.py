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
from importlib import resources
from pathlib import Path, PurePosixPath
from typing import Any

MAX_JSON = 64 * 1024
DESCRIPTOR_PATH = "/usr/local/share/skillc/runtime-supply.json"
IDENTITY_KEYS = {"schema_version", "runtime_id", "subject_revision", "pyproject_sha256", "lock_sha256"}
ENV_KEYS = {"HOME", "UV_CACHE_DIR", "UV_OFFLINE", "UV_LOCKED", "UV_PYTHON", "UV_PYTHON_DOWNLOADS", "UV_LINK_MODE"}
POLICY_KEYS = IDENTITY_KEYS | {"subject_locator", "project", "gate_entrypoint", "uv_version", "required_env"}
RECEIPT_KEYS = IDENTITY_KEYS | {"image_id", "descriptor_sha256", "recipe_sha256",
                              "base_recipe_sha256", "build_context_sha256", "source_commit", "target"}
DESCRIPTOR_KEYS = IDENTITY_KEYS | {"uv_version", "python", "required_env"}
#: The two named runtimes (#280). `profile-runtime` is the flow-check runtime
#: the #360 builder produces; `cicd-runtime` is that exact image plus one curl
#: layer (docker/cicd-trial/), with the base receipt embedded whole.
PROFILE_RUNTIME = "profile-runtime"
CICD_RUNTIME = "cicd-runtime"
CICD_RECEIPT_KEYS = IDENTITY_KEYS | {"image_id", "descriptor_sha256", "recipe_sha256", "source_commit",
                                    "target", "base_receipt", "base_image_id", "curl_version"}


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


def _identity(value: Mapping[str, object], policy: Mapping[str, Any]) -> None:
    for key in IDENTITY_KEYS:
        expected = policy[key]
        if type(value.get(key)) is not type(expected) or value[key] != expected:
            raise Refused(f"unsupported runtime {key}")


def _hex(value: object, length: int) -> bool:
    return isinstance(value, str) and re.fullmatch(f"[0-9a-f]{{{length}}}", value) is not None


def supported_policy() -> dict[str, Any]:
    """Read only the bounded package resource; no caller selects its authority.

    Loaded on runtime use, not module import, so absent package data cannot
    break unrelated static commands or backends that select no runtime.
    """
    try:
        with resources.files(__package__).joinpath("runtime-policy.json").open("rb") as stream:
            value = load_json(stream.read(MAX_JSON + 1))
    except (OSError, ValueError) as exc:
        raise Refused("controller runtime policy is missing or malformed") from exc
    _keys(value, POLICY_KEYS, "controller policy")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise Refused("unsupported controller policy schema")
    for key in ("runtime_id", "subject_locator", "project", "gate_entrypoint", "uv_version"):
        if not isinstance(value[key], str) or not value[key] or any(c in value[key] for c in "\0\n\r"):
            raise Refused("controller policy has an invalid string identity")
    if not _hex(value["subject_revision"], 40) or any(
        not _hex(value[key], 64) for key in ("pyproject_sha256", "lock_sha256")
    ):
        raise Refused("controller policy has malformed pinned identities")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", value["uv_version"]):
        raise Refused("controller policy has an invalid runtime version")
    for key in ("project", "gate_entrypoint"):
        path = PurePosixPath(value[key])
        if path.is_absolute() or not path.parts or ".." in path.parts:
            raise Refused("controller policy paths must be nonescaping relative paths")
    env = value["required_env"]
    _keys(env, ENV_KEYS, "controller environment policy")
    if any(not isinstance(v, str) or not v or "\0" in v or "\n" in v for v in env.values()):
        raise Refused("controller environment policy has invalid values")
    return value


def metadata(policy: Mapping[str, Any]) -> dict[str, str]:
    project = policy["project"]
    return {f"{project}/pyproject.toml": "sha256:" + policy["pyproject_sha256"],
            f"{project}/uv.lock": "sha256:" + policy["lock_sha256"]}


def _receipt(raw: bytes) -> dict[str, Any]:
    return _profile_receipt(load_json(raw))


def _profile_receipt(value: dict[str, Any]) -> dict[str, Any]:
    _keys(value, RECEIPT_KEYS, "receipt")
    _identity(value, supported_policy())
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


def _cicd_receipt(value: dict[str, Any]) -> dict[str, Any]:
    """A curl layer on one validated flow-check receipt, embedded whole.

    The embedded base passes the unchanged flow-check validator, so a cicd
    receipt can never certify a base image that receipt could not. The
    descriptor is inherited byte-for-byte; a layer that rewrote it is refused.
    """
    _keys(value, CICD_RECEIPT_KEYS, "cicd receipt")
    _identity(value, supported_policy())
    if value["target"] != CICD_RUNTIME:
        raise Refused("cicd receipt target is not the cicd runtime")
    base = value["base_receipt"]
    if not isinstance(base, dict):
        raise Refused("cicd receipt base is not a receipt object")
    base = _profile_receipt(base)
    if value["base_image_id"] != base["image_id"]:
        raise Refused("cicd receipt base image differs from its embedded base receipt")
    if not isinstance(value["image_id"], str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", value["image_id"]):
        raise Refused("runtime receipt image must be immutable")
    if value["image_id"] == base["image_id"]:
        raise Refused("cicd receipt names its base image, not the layered one")
    if value["descriptor_sha256"] != base["descriptor_sha256"]:
        raise Refused("cicd receipt descriptor differs from its base runtime")
    if not _hex(value["source_commit"], 40) or not _hex(value["recipe_sha256"], 64):
        raise Refused("cicd receipt source commit or recipe is malformed")
    if not isinstance(value["curl_version"], str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", value["curl_version"]):
        raise Refused("cicd receipt curl version is malformed")
    return value


def _any_receipt(raw: bytes) -> dict[str, Any]:
    value = load_json(raw)
    if value.get("target") == CICD_RUNTIME:
        return _cicd_receipt(value)
    return _profile_receipt(value)


@dataclass(frozen=True)
class RuntimeSupply:
    """Immutable validated receipt bytes supplied by the controller/operator."""

    receipt_bytes: bytes = field(repr=False)

    def __post_init__(self) -> None:
        _any_receipt(self.receipt_bytes)

    @classmethod
    def from_path(cls, path: Path) -> RuntimeSupply:
        try:
            with path.open("rb") as stream:
                return cls(stream.read(MAX_JSON + 1))
        except OSError as exc:
            raise Refused("runtime receipt is unreadable") from exc

    @property
    def image_id(self) -> str:
        return str(_any_receipt(self.receipt_bytes)["image_id"])

    @property
    def kind(self) -> str:
        """`profile-runtime` or `cicd-runtime`: which named runtime this is."""
        return str(_any_receipt(self.receipt_bytes)["target"])

    def descriptor(self, raw: bytes, *, actual_image: str) -> dict[str, Any]:
        receipt = _any_receipt(self.receipt_bytes)
        if actual_image != self.image_id:
            raise Refused("runtime actual image differs from selected receipt")
        if hashlib.sha256(raw).hexdigest() != receipt["descriptor_sha256"]:
            raise Refused("runtime descriptor bytes differ from selected receipt")
        value = load_json(raw)
        _keys(value, DESCRIPTOR_KEYS, "descriptor")
        policy = supported_policy()
        _identity(value, policy)
        if value["uv_version"] != policy["uv_version"]:
            raise Refused("runtime uv version differs from supported policy")
        required = value["required_env"]
        _keys(required, ENV_KEYS | {"PATH"}, "required environment")
        if any(required[key] != expected for key, expected in policy["required_env"].items()):
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
        if (minor < 11 or python["executable"] != policy["required_env"]["UV_PYTHON"] or python["platform"] != "linux"
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
    if any(key.startswith("UV_") and key not in ENV_KEYS for key in env):
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
    if gate_entrypoint is None:
        return False
    policy = supported_policy()
    selected = (locator == policy["subject_locator"] and revision == policy["subject_revision"]
                and gate_entrypoint == policy["gate_entrypoint"])
    project_probe = any(probe.get("kind") == "python-import" and probe.get("uv_project") == policy["project"]
                        for tool in tools for probe in tool.get("probes", ()))
    if selected and not project_probe:
        raise Refused("supported profile runtime project probe changed or is missing")
    if selected and any(files.get(path) != digest for path, digest in metadata(policy).items()):
        raise Refused("supported profile runtime metadata changed or is missing")
    return selected


def selected_runtime(*, locator: str, revision: str, gate_entrypoint: str | None,
                     files: Mapping[str, str], tools: Sequence[Mapping[str, Any]]) -> str | None:
    """Which named runtime a freshly validated closure selects, if any (#280).

    `requires_supply` decides the flow-check runtime first and unchanged, with
    every refusal it raises. Only a closure it does not select, that declares
    NO gate, sits at the supported subject pin, and declares both the policy
    project's import probe and a curl command probe selects the cicd runtime -
    which shares that pin's dependency metadata, so the same metadata refusal
    applies. Everything else selects nothing, as before.
    """
    if requires_supply(locator=locator, revision=revision, gate_entrypoint=gate_entrypoint,
                       files=files, tools=tools):
        return PROFILE_RUNTIME
    if gate_entrypoint is not None:
        return None
    probes = [probe for tool in tools for probe in tool.get("probes", ())]
    curl_probe = any(probe.get("kind") == "command" and probe.get("name") == "curl" for probe in probes)
    # Like requires_supply, an unrelated closure is classified without the
    # policy resource, so absent package data cannot refuse it.
    if not curl_probe or not any(probe.get("kind") == "python-import" for probe in probes):
        return None
    policy = supported_policy()
    if locator != policy["subject_locator"] or revision != policy["subject_revision"]:
        return None
    if not any(probe.get("kind") == "python-import" and probe.get("uv_project") == policy["project"]
               for probe in probes):
        return None
    if any(files.get(path) != digest for path, digest in metadata(policy).items()):
        raise Refused("supported cicd runtime metadata changed or is missing")
    return CICD_RUNTIME


def require_kind(supply: RuntimeSupply, selected: str | None) -> None:
    """A receipt serves only the runtime its closure selected (#280)."""
    if selected is None:
        raise Refused("runtime receipt supplied for an unrelated or absent profile")
    if supply.kind != selected:
        raise Refused(f"runtime receipt is a {supply.kind} receipt, but the closure selects {selected}")
