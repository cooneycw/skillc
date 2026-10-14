"""Closed #360 schema controls; fixture bytes are synthetic, never runtime evidence."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import venv
import zipfile
from pathlib import Path
from typing import Any

import pytest

from skillc import docker_backend as d
from skillc import runtime_supply as rs
from skillc.backend import ExecuteResult, Limits

DESCRIPTOR = b'{\n  "lock_sha256": "b8edbdd3e0036bc09c849cedee3c1231c468f0f0f9425090c8f2ec914108f3cf",\n  "pyproject_sha256": "bc42953d69269328dbe5041d3b7ef6423804492db20b8cf8a59a94c0ee9f3774",\n  "python": {\n    "cache_tag": "cpython-311",\n    "executable": "/usr/bin/python3",\n    "machine": "x86_64",\n    "platform": "linux",\n    "version": "3.11.2"\n  },\n  "required_env": {\n    "HOME": "/home/candidate",\n    "PATH": "/usr/local/bin:/usr/bin:/bin",\n    "UV_CACHE_DIR": "/home/candidate/.cache/uv",\n    "UV_LINK_MODE": "copy",\n    "UV_LOCKED": "1",\n    "UV_OFFLINE": "1",\n    "UV_PYTHON": "/usr/bin/python3",\n    "UV_PYTHON_DOWNLOADS": "never"\n  },\n  "runtime_id": "cpp-codex-flow-check-86641e8",\n  "schema_version": 1,\n  "subject_revision": "86641e817711d8a7746270745a5dfa7cacf04b0c",\n  "uv_version": "0.9.7"\n}\n'
RECEIPT = b'{\n  "base_recipe_sha256": "3333333333333333333333333333333333333333333333333333333333333333",\n  "build_context_sha256": "4444444444444444444444444444444444444444444444444444444444444444",\n  "descriptor_sha256": "fc9a50f31881c38e170b059dc56709c4b4b83f1bddf993829d84ec33d204cec7",\n  "image_id": "sha256:1111111111111111111111111111111111111111111111111111111111111111",\n  "lock_sha256": "b8edbdd3e0036bc09c849cedee3c1231c468f0f0f9425090c8f2ec914108f3cf",\n  "pyproject_sha256": "bc42953d69269328dbe5041d3b7ef6423804492db20b8cf8a59a94c0ee9f3774",\n  "recipe_sha256": "2222222222222222222222222222222222222222222222222222222222222222",\n  "runtime_id": "cpp-codex-flow-check-86641e8",\n  "schema_version": 1,\n  "source_commit": "5555555555555555555555555555555555555555",\n  "subject_revision": "86641e817711d8a7746270745a5dfa7cacf04b0c",\n  "target": "profile-runtime"\n}\n'


def encoded(value: object) -> bytes:
    return json.dumps(value).encode()


def supply_for(descriptor: bytes = DESCRIPTOR) -> rs.RuntimeSupply:
    receipt = json.loads(RECEIPT)
    receipt["descriptor_sha256"] = hashlib.sha256(descriptor).hexdigest()
    return rs.RuntimeSupply(encoded(receipt))


def expected_policy() -> dict[str, Any]:
    descriptor = json.loads(DESCRIPTOR)  # independently committed expected pin
    return {
        **{key: descriptor[key] for key in ("schema_version", "runtime_id", "subject_revision",
                                            "pyproject_sha256", "lock_sha256", "uv_version")},
        "required_env": {key: value for key, value in descriptor["required_env"].items() if key != "PATH"},
        "subject_locator": "github.com/cooneycw/claude-power-pack",
        "project": "Projects/claude-power-pack", "gate_entrypoint": ".claude/scripts/flow-finish-gate.sh",
    }


def test_packaged_policy_keeps_independent_supported_pin() -> None:
    assert rs.supported_policy() == expected_policy()


@pytest.mark.parametrize("fault", [None, "missing", "malformed", "duplicate", "oversized", "unknown", "missing-field",
                                  "bool-schema", "wrong-type", "bad-revision", "bad-digest", "bad-version",
                                  "escaping-project", "absolute-gate", "bad-env", "extra-env"])
def test_fixed_resource_loader_refuses_bad_policy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                fault: str | None) -> None:
    policy = expected_policy()
    changes = {"unknown": ("extra", 1), "bool-schema": ("schema_version", True),
               "wrong-type": ("runtime_id", []), "bad-revision": ("subject_revision", "short"),
               "bad-digest": ("lock_sha256", "short"), "bad-version": ("uv_version", "latest"),
               "escaping-project": ("project", "../escape"), "absolute-gate": ("gate_entrypoint", "/gate")}
    if fault in changes:
        key, value = changes[fault]
        policy[key] = value
    if fault == "missing-field":
        del policy["project"]
    if fault == "bad-env":
        policy["required_env"]["UV_OFFLINE"] = True
    if fault == "extra-env":
        policy["required_env"]["UV_PROJECT_ENVIRONMENT"] = "/external"
    raw = encoded(policy)
    if fault == "malformed":
        raw = b"{bad"
    elif fault == "duplicate":
        raw = b'{"schema_version":1,"schema_version":1}'
    elif fault == "oversized":
        raw = b"x" * (rs.MAX_JSON + 1)
    package = tmp_path / "package"
    package.mkdir()
    if fault != "missing":
        (package / "runtime-policy.json").write_bytes(raw)
    monkeypatch.setattr(rs.resources, "files", lambda name: package)
    if fault is None:
        assert rs.supported_policy() == expected_policy()
    else:
        with pytest.raises(rs.Refused):
            rs.supported_policy()
        with pytest.raises(rs.Refused):
            rs.RuntimeSupply(RECEIPT)
    # Unrelated no-gate classification needs no policy, even if package data is bad.
    assert not rs.requires_supply(locator="unrelated", revision="a" * 40, gate_entrypoint=None, files={}, tools=[])


def test_policy_path_cannot_come_from_cwd_or_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "runtime-policy.json").write_text("{}")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SKILLC_RUNTIME_POLICY", str(tmp_path / "runtime-policy.json"))
    assert rs.supported_policy() == expected_policy()


@pytest.fixture(scope="session")
def wheel_build_cache() -> str:
    # Resolve only the build-tool cache before function fixtures replace HOME.
    # Runtime trials never use this cache; credential isolation stays intact.
    return subprocess.check_output(["uv", "cache", "dir"], text=True, timeout=10).strip()


def test_installed_wheel_uses_its_policy_resource_and_refuses_its_loss(tmp_path: Path, wheel_build_cache: str) -> None:
    """Build/install the real wheel offline, then import outside the checkout."""
    root = Path(__file__).resolve().parents[1]
    wheels = tmp_path / "wheels"
    env = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "PYTHONHOME", "UV_PROJECT_ENVIRONMENT"}}
    env["UV_CACHE_DIR"] = wheel_build_cache
    built = subprocess.run(["uv", "build", "--offline", "--wheel", "--out-dir", str(wheels)], cwd=root,
                           env=env, check=False, capture_output=True, timeout=60)
    assert built.returncode == 0, built.stderr.decode(errors="replace")
    wheel, = wheels.glob("*.whl")
    with zipfile.ZipFile(wheel) as archive:
        assert json.loads(archive.read("skillc/runtime-policy.json")) == expected_policy()
    destination = tmp_path / "installed"
    venv.EnvBuilder(with_pip=False).create(destination)
    python = destination / "bin" / "python"
    subprocess.run(["uv", "pip", "install", "--offline", "--no-deps", "--python", str(python), str(wheel)],
                   env=env, check=True, capture_output=True, timeout=60)
    other_cwd = tmp_path / "other"
    other_cwd.mkdir()
    script = ("import json,sys; from skillc import runtime_supply as r; "
              "r.RuntimeSupply(sys.stdin.buffer.read()); "
              "print(json.dumps(dict(policy=r.supported_policy(),module=r.__file__)))")
    run = subprocess.run([str(python), "-I", "-c", script], input=RECEIPT, cwd=other_cwd,
                         env=env, check=True, capture_output=True, timeout=10)
    found = json.loads(run.stdout)
    assert found["policy"] == expected_policy()
    module = Path(found["module"])
    assert module.is_relative_to(destination)
    module.with_name("runtime-policy.json").unlink()
    # Source policy still exists, but installed code cannot fall back to it.
    refused = subprocess.run([str(python), "-I", "-c", script], input=RECEIPT, cwd=root,
                             env=env, check=False, capture_output=True, timeout=10)
    assert refused.returncode != 0 and b"controller runtime policy is missing" in refused.stderr
    unrelated = subprocess.run([str(python), "-I", "-c",
        "from skillc import runtime_supply as r; assert not r.requires_supply(locator='x',revision='x',gate_entrypoint=None,files={},tools=[])"],
        cwd=other_cwd, env=env, check=False, capture_output=True, timeout=10)
    assert unrelated.returncode == 0, unrelated.stderr


@pytest.mark.parametrize("fault", [None, "image", "descriptor", "writable", "unknown-permission",
                                  "python", "uv", "environment", "metadata", "project", "venv",
                                  "missing-output", "truncated", "incomplete", "failed-read"])
@pytest.mark.parametrize("treated", [False, True])
def test_backend_consumes_measured_runtime_and_refuses_bad_facts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str | None, treated: bool,
) -> None:
    """Real validation, with only Docker's execution/identity transport supplied."""
    supply = supply_for()
    backend = d.DockerBackend(image=supply.image_id, base_dir=tmp_path, runtime_supply=supply, witness_io=True)
    handle = d._Handle("attempt", "container", {})
    descriptor = json.loads(DESCRIPTOR)
    effective = dict(descriptor["required_env"])
    if fault == "environment":
        effective["UV_PROJECT_ENVIRONMENT"] = ""
    calls: list[list[str]] = []

    def execute(self: d.DockerBackend, actual: object, argv: object, limits: Limits) -> ExecuteResult:
        assert actual is handle and isinstance(argv, list)
        calls.append(argv)
        assert limits.max_captured_stdout_bytes <= rs.MAX_JSON + 1
        assert "run" not in argv and "sync" not in argv
        if argv == ["env", "-0"]:
            raw = b"".join(f"{key}={value}\0".encode() for key, value in effective.items())
        elif rs.DESCRIPTOR_PATH in argv:
            assert "is_symlink" in argv[2]
            raw = DESCRIPTOR + (b"\n" if fault == "descriptor" else b"")
        elif argv == ["uv", "--version"]:
            raw = b"uv 0.0.0\n" if fault == "uv" else b"uv 0.9.7\n"
        elif argv[-1].endswith("/.venv"):
            return ExecuteResult(reason="exited", exit_code=1 if fault == "venv" else 0, stdout=b"")
        else:
            raw = encoded({**descriptor["python"], "version": "3.11.0"} if fault == "python" else descriptor["python"])
        return ExecuteResult(reason="exited", exit_code=1 if fault == "failed-read" else 0,
                             stdout=None if fault == "missing-output" else raw,
                             stdout_truncated=fault == "truncated", stdout_incomplete=fault == "incomplete")

    def writable(self: d.DockerBackend, actual: object, path: str, **kwargs: object) -> bool | None:
        if path.startswith("/home/candidate/"):
            return fault != "project"
        if fault == "unknown-permission":
            return None
        return fault == "writable"

    monkeypatch.setattr(d.DockerBackend, "exec_in_attempt", execute)
    monkeypatch.setattr(d.DockerBackend, "candidate_can_write_in_attempt", writable)
    monkeypatch.setattr(d.DockerBackend, "image_id", lambda *args: "bad" if fault == "image" else supply.image_id)
    verified = rs.metadata(rs.supported_policy()) if treated else {}
    if fault == "metadata" and treated:
        verified[next(iter(verified))] = "changed"
    refused = fault is not None and (treated or fault not in {"metadata", "project", "venv"})
    if refused:
        with pytest.raises(rs.Refused):
            backend.runtime_environment(handle, Limits(timeout=10), verified)
    else:
        assert backend.runtime_environment(handle, Limits(timeout=10), verified) == effective
        assert any(call[-1].endswith("/.venv") for call in calls) is treated


def test_committed_contract_pair_and_immutable_receipt(tmp_path: Path) -> None:
    path = tmp_path / "receipt.json"
    path.write_bytes(RECEIPT)
    supply = rs.RuntimeSupply.from_path(path)
    path.write_text("changed after selection")
    assert supply.receipt_bytes == RECEIPT
    assert supply.descriptor(DESCRIPTOR, actual_image=supply.image_id) == json.loads(DESCRIPTOR)
    assert "receipt_bytes" not in repr(supply)


@pytest.mark.parametrize("raw", [b"", b"[]", b"{bad", b'{"x":1,"x":2}', b"x" * (rs.MAX_JSON + 1)])
def test_bad_json_cannot_select_a_runtime(raw: bytes) -> None:
    with pytest.raises(rs.Refused):
        rs.RuntimeSupply(raw)


@pytest.mark.parametrize(("key", "value"), [
    ("schema_version", True), ("runtime_id", "other"), ("subject_revision", "a" * 40),
    ("pyproject_sha256", "a" * 64), ("lock_sha256", "a" * 64), ("image_id", "tag:mutable"),
    ("descriptor_sha256", "bad"), ("recipe_sha256", "bad"), ("base_recipe_sha256", "bad"),
    ("build_context_sha256", "bad"), ("source_commit", "short"), ("target", "profile-runtime-empty-cache"),
    ("extra", "unknown"),
])
def test_receipt_closed_schema_and_expected_policy(key: str, value: object) -> None:
    receipt = json.loads(RECEIPT)
    receipt[key] = value
    with pytest.raises(rs.Refused):
        rs.RuntimeSupply(encoded(receipt))


@pytest.mark.parametrize("key", list(json.loads(RECEIPT)))
def test_missing_receipt_field_refuses(key: str) -> None:
    receipt = json.loads(RECEIPT)
    del receipt[key]
    with pytest.raises(rs.Refused):
        rs.RuntimeSupply(encoded(receipt))


@pytest.mark.parametrize(("key", "value"), [
    ("schema_version", True), ("runtime_id", "other"), ("subject_revision", "a" * 40),
    ("pyproject_sha256", "a" * 64), ("lock_sha256", "a" * 64), ("uv_version", "0.0.0"),
    ("extra", None), ("python", {}), ("required_env", {}),
])
def test_self_consistent_descriptor_hash_cannot_change_expected_policy(key: str, value: object) -> None:
    descriptor = json.loads(DESCRIPTOR)
    descriptor[key] = value
    raw = encoded(descriptor)
    supply = supply_for(raw)
    with pytest.raises(rs.Refused):
        supply.descriptor(raw, actual_image=supply.image_id)


@pytest.mark.parametrize("fault", ["bytes", "image"])
def test_actual_descriptor_bytes_and_image_bind_to_receipt(fault: str) -> None:
    supply = supply_for()
    with pytest.raises(rs.Refused):
        supply.descriptor(DESCRIPTOR + (b"\n" if fault == "bytes" else b""),
                          actual_image="sha256:" + "f" * 64 if fault == "image" else supply.image_id)


@pytest.mark.parametrize("raw", [b"", b"A=x", b"A=x\0A=y\0", b"=x\0", b"BAD-NAME=x\0", b"A=\xff\0",
                                  b"A=" + b"x" * rs.MAX_JSON + b"\0"])
def test_environment_wire_refuses_ambiguity_and_partial_population(raw: bytes) -> None:
    with pytest.raises(rs.Refused):
        rs.environment(raw)


def test_environment_wire_and_selected_policy() -> None:
    descriptor = json.loads(DESCRIPTOR)
    env = descriptor["required_env"]
    raw = b"\0".join(f"{key}={value}".encode() for key, value in env.items()) + b"\0"
    assert rs.environment(raw) == env
    rs.validate_environment(env, descriptor)
    for key in env:
        changed = dict(env)
        del changed[key]
        with pytest.raises(rs.Refused):
            rs.validate_environment(changed, descriptor)
        changed[key] = "wrong"
        with pytest.raises(rs.Refused):
            rs.validate_environment(changed, descriptor)
    for key in ("UV_PROJECT_ENVIRONMENT", "UV_NO_SYNC", "UV_CONFIG_FILE"):
        with pytest.raises(rs.Refused):
            rs.validate_environment({**env, key: ""}, descriptor)


def selection() -> dict[str, Any]:
    descriptor = json.loads(DESCRIPTOR)
    return {
        "locator": "github.com/cooneycw/claude-power-pack", "revision": descriptor["subject_revision"],
        "gate_entrypoint": ".claude/scripts/flow-finish-gate.sh",
        "files": {"Projects/claude-power-pack/pyproject.toml": "sha256:" + descriptor["pyproject_sha256"],
                  "Projects/claude-power-pack/uv.lock": "sha256:" + descriptor["lock_sha256"]},
        "tools": [{"probes": [{"kind": "python-import", "uv_project": "Projects/claude-power-pack"}]}],
    }


def test_relocated_and_derived_skill_runtime_classification_uses_validated_facts() -> None:
    facts = selection()
    assert rs.requires_supply(**facts)
    # Neither the controller profile pathname nor SKILL content is a selector.
    # A derived description keeps this runtime only with separately validated
    # identical dependency facts; this test does not assert study approval.
    facts["files"][".codex/skills/flow-check/SKILL.md"] = "sha256:" + "a" * 64
    assert rs.requires_supply(**facts)
    facts["files"][".codex/skills/flow-check/SKILL.md"] = "sha256:" + "b" * 64
    assert rs.requires_supply(**facts)
    for key in ("locator", "revision", "gate_entrypoint"):
        assert not rs.requires_supply(**{**facts, key: "unrelated"})


@pytest.mark.parametrize("fault", ["missing-lock", "changed-project", "changed-probe"])
def test_supported_family_never_downgrades_changed_runtime_facts(fault: str) -> None:
    facts = selection()
    if fault == "missing-lock":
        del facts["files"]["Projects/claude-power-pack/uv.lock"]
    elif fault == "changed-project":
        facts["files"]["Projects/claude-power-pack/pyproject.toml"] = "sha256:" + "f" * 64
    else:
        facts["tools"][0]["probes"][0]["uv_project"] = "Other/project"
    with pytest.raises(rs.Refused):
        rs.requires_supply(**facts)
