"""Offline controls for the actual #360 preparation and receipt validators.

These tests never launch Docker. They certify refusal/binding logic only;
cache consumption, permissions and baseline purity require the live handoff.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SUPPLY = ROOT / "docker/profile-trial"
CASES = ROOT / "tests/fixtures/profile-trial-runtime"
spec = importlib.util.spec_from_file_location("profile_trial_build", SUPPLY / "build.py")
assert spec and spec.loader
build: Any = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


def test_selected_pin_prepares_without_docker(tmp_path: Path) -> None:
    prepared = build.prepare(ROOT, tmp_path / "context")
    assert prepared["policy"]["runtime_id"] == "cpp-codex-flow-check-86641e8"
    assert prepared["recipe_sha256"] == build.sha256((tmp_path / "context/Dockerfile").read_bytes())
    for name in ("pyproject.toml", "uv.lock"):
        assert (tmp_path / "context/metadata" / name).read_bytes() == (
            ROOT / "tests/fixtures/profile-cpp-codex-flow-check-86641e8" / name
        ).read_bytes()


def _read(name: str) -> Any:
    return json.loads((CASES / name).read_bytes())


def _change(value: Any, path: list[str], replacement: Any, op: str = "set") -> Any:
    if not path:
        return replacement
    node = value
    for key in path[:-1]:
        node = node[key]
    if op == "delete":
        del node[path[-1]]
    else:
        node[path[-1]] = replacement
    return value


CONTRACT_CASES = _read("contract-cases.json")
INPUT_CASES = _read("input-cases.json")


@pytest.fixture(scope="module")
def source() -> tuple[str, dict[str, bytes]]:
    return build.source_inputs(ROOT)


def test_good_contracts_and_exact_descriptor_bytes() -> None:
    descriptor = (CASES / "descriptor.good.json").read_bytes()
    receipt = _read("receipt.good.json")
    build.validate_policy(build.load_json((SUPPLY / "runtime-policy.json").read_bytes()))
    build.validate_descriptor(build.load_json(descriptor))
    build.validate_receipt(receipt, descriptor, receipt["image_id"], expected=receipt)
    with pytest.raises(build.SupplyError, match="digest mismatch"):
        build.validate_receipt(receipt, descriptor + b"\n", receipt["image_id"])


@pytest.mark.parametrize("case", CONTRACT_CASES, ids=lambda c: c["contract"] + ":" + c["name"])
def test_closed_contract_controls(case: dict[str, Any]) -> None:
    contract = case["contract"]
    good = (
        build.load_json((SUPPLY / "runtime-policy.json").read_bytes())
        if contract == "policy"
        else _read(contract + ".good.json")
    )
    changed = _change(copy.deepcopy(good), case["path"], case["value"], case["op"])
    with pytest.raises(build.SupplyError, match=case["error"]):
        if contract == "receipt":
            build.validate_receipt(
                changed,
                (CASES / "descriptor.good.json").read_bytes(),
                good["image_id"],
                expected=good,
            )
        else:
            getattr(build, "validate_" + contract)(changed)


@pytest.mark.parametrize("name", ["malformed.json", "duplicate.json", "empty.json"])
def test_malformed_json_controls(name: str) -> None:
    with pytest.raises(build.SupplyError, match="JSON"):
        build.load_json((CASES / name).read_bytes())


@pytest.mark.parametrize("case", INPUT_CASES, ids=lambda c: c["name"])
def test_input_refusals_make_zero_docker_calls(
    tmp_path: Path,
    source: tuple[str, dict[str, bytes]],
    case: dict[str, Any],
) -> None:
    commit, inputs = source
    changed = dict(inputs)
    if case["op"] == "delete":
        del changed[case["path"]]
    elif case["op"] == "bytes":
        changed[case["path"]] = case["value"].encode()
    else:
        value = build.load_json(changed[case["path"]], limit=1024 * 1024)
        changed[case["path"]] = build.json_bytes(_change(value, case["field"], case["value"]))
    calls: list[list[str]] = []

    def forbidden(argv: list[str]) -> str:
        calls.append(argv)
        raise AssertionError("invalid preparation invoked Docker")

    with pytest.raises(build.SupplyError, match=case["error"]):
        build.build_image(
            ROOT, tmp_path / "receipt.json", run=forbidden, inputs=changed, source_commit=commit
        )
    assert calls == []
    assert not (tmp_path / "receipt.json").exists()


@pytest.mark.parametrize(
    "case", [c for c in CONTRACT_CASES if c["contract"] == "policy"], ids=lambda c: c["name"]
)
def test_policy_refusals_make_zero_docker_calls(tmp_path: Path, case: dict[str, Any]) -> None:
    policy = build.load_json((SUPPLY / "runtime-policy.json").read_bytes())
    changed = _change(policy, case["path"], case["value"], case["op"])
    calls: list[list[str]] = []

    def forbidden(argv: list[str]) -> str:
        calls.append(argv)
        raise AssertionError("invalid policy invoked Docker")

    with pytest.raises(build.SupplyError, match=case["error"]):
        build.build_image(
            ROOT, tmp_path / "receipt.json", run=forbidden, policy_bytes=build.json_bytes(changed)
        )
    assert calls == []


@pytest.mark.parametrize("paths", _read("additions.bad.json"))
def test_final_copy_source_and_venv_controls(paths: list[str]) -> None:
    build.validate_additions(paths[:2])
    with pytest.raises(build.SupplyError, match="unexpected source"):
        build.validate_additions(paths)
    # Drive the actual recipe renderer too; a separate hand-coded predicate
    # accepting good data would not prove the builder uses the allowlist.
    fragment = (SUPPLY / "Dockerfile.fragment").read_bytes()
    fragment += f"\nCOPY metadata/ {paths[-1]}\n".encode()
    with pytest.raises(build.SupplyError, match="unexpected source"):
        build.render_recipe(
            b"FROM base AS trial\n",
            fragment,
            build.load_json((SUPPLY / "runtime-policy.json").read_bytes()),
        )


class FakeDocker:
    """Explicit fake command boundary. Never accesses a daemon or starts a process."""

    def __init__(
        self,
        *,
        image_drift: bool = False,
        env_drift: bool = False,
        project_environment: str | None = None,
        user: str = "candidate",
        descriptor: bytes | None = None,
    ) -> None:
        self.calls: list[list[str]] = []
        self.image_id = _read("receipt.good.json")["image_id"]
        self.image_drift = image_drift
        self.env_drift = env_drift
        self.project_environment = project_environment
        self.user = user
        self.descriptor = descriptor or (CASES / "descriptor.good.json").read_bytes()
        self.context: dict[str, bytes] = {}

    def __call__(self, argv: list[str]) -> str:
        self.calls.append(argv)
        if argv[0] == "build":
            Path(argv[argv.index("--iidfile") + 1]).write_text(self.image_id + "\n")
            context = Path(argv[-1])
            self.context = {
                str(p.relative_to(context)): p.read_bytes()
                for p in context.rglob("*")
                if p.is_file()
            }
            return ""
        if argv[:2] == ["image", "inspect"]:
            env = _read("descriptor.good.json")["required_env"]
            if self.env_drift:
                env.pop("UV_OFFLINE")
            if self.project_environment is not None:
                env["UV_PROJECT_ENVIRONMENT"] = self.project_environment
            return json.dumps(
                [
                    {
                        "Id": "sha256:" + "0" * 64 if self.image_drift else self.image_id,
                        "Config": {"User": self.user, "Env": [f"{k}={v}" for k, v in env.items()]},
                    }
                ]
            )
        if argv[0] == "create":
            assert argv == [
                "create",
                "--network",
                "none",
                "--entrypoint",
                "/bin/true",
                self.image_id,
            ]
            return "a" * 64 + "\n"
        if argv[0] == "cp":
            assert argv[1] == "a" * 64 + ":" + build.DESCRIPTOR_PATH
            Path(argv[2]).write_bytes(self.descriptor)
            return ""
        if argv[0] == "rm":
            assert argv == ["rm", "a" * 64]
            return ""
        raise AssertionError(f"unexpected Docker command: {argv}")


@pytest.mark.parametrize("target", build.TARGETS)
def test_build_binds_observed_identity_and_generated_context(tmp_path: Path, target: str) -> None:
    fake = FakeDocker()
    receipt_path = tmp_path / "receipt.json"
    receipt = build.build_image(ROOT, receipt_path, run=fake, target=target)
    assert fake.calls[0][:3] == ["build", "--target", target]
    assert receipt == _read_path(receipt_path)
    assert receipt["recipe_sha256"] == build.sha256(fake.context["Dockerfile"])
    assert receipt["build_context_sha256"] == build.sha256(
        build.json_bytes({name: build.sha256(data) for name, data in sorted(fake.context.items())})
    )
    assert {k for k in fake.context if k.startswith("metadata/")} == {
        "metadata/pyproject.toml",
        "metadata/uv.lock",
    }
    assert fake.calls[-1] == ["rm", "a" * 64]
    build.validate_receipt(receipt, fake.descriptor, fake.image_id, target=target)
    if target != "profile-runtime":
        with pytest.raises(build.SupplyError, match="target mismatch"):
            build.validate_receipt(receipt, fake.descriptor, fake.image_id)


def _read_path(path: Path) -> Any:
    return json.loads(path.read_bytes())


@pytest.mark.parametrize(
    "kwargs,error",
    [
        ({"image_drift": True}, "image ID mismatch"),
        ({"env_drift": True}, "environment mismatch"),
        ({"user": "root"}, "candidate"),
        ({"descriptor": b"{}"}, "fields"),
    ],
)
def test_build_refuses_observed_drift_without_receipt(
    tmp_path: Path,
    kwargs: dict[str, Any],
    error: str,
) -> None:
    fake = FakeDocker(**kwargs)
    output = tmp_path / "receipt.json"
    with pytest.raises(build.SupplyError, match=error):
        build.build_image(ROOT, output, run=fake)
    assert not output.exists()
    if any(call[0] == "create" for call in fake.calls):
        assert fake.calls[-1] == ["rm", "a" * 64]


def test_invalid_target_and_existing_receipt_do_not_call_docker(tmp_path: Path) -> None:
    fake = FakeDocker()
    output = tmp_path / "receipt.json"
    with pytest.raises(build.SupplyError, match="unsupported target"):
        build.build_image(ROOT, output, run=fake, target="trial")
    output.write_text("historical receipt")
    with pytest.raises(build.SupplyError, match="already exists"):
        build.build_image(ROOT, output, run=fake)
    assert fake.calls == []
    assert output.read_text() == "historical receipt"


@pytest.mark.parametrize(
    "replacement", ["/tmp/runtime-supply/metadata", "/tmp/runtime-supply/metadata/.venv"]
)
def test_final_copy_cannot_disguise_project_as_cache(replacement: str) -> None:
    fragment = (
        (SUPPLY / "Dockerfile.fragment")
        .read_bytes()
        .replace(
            b" /tmp/dependency-cache /home/candidate/.cache/uv",
            f" {replacement} /home/candidate/.cache/uv".encode(),
        )
    )
    with pytest.raises(build.SupplyError, match="COPY source"):
        build.render_recipe(
            b"FROM base AS trial\n",
            fragment,
            build.load_json((SUPPLY / "runtime-policy.json").read_bytes()),
        )


def test_inventory_metadata_binding_control(source: tuple[str, dict[str, bytes]]) -> None:
    _, inputs = source
    subject = build.load_json(inputs[f"{build.SUBJECT}/subject.json"])
    inventory = build.load_json(
        inputs[f"{build.SUBJECT}/evidence/inventory.json"], limit=1024 * 1024
    )
    build.validate_inventory(subject, inventory)
    records = build._files(inventory)
    for record in records:
        if record["source"] == "uv.lock":
            record["digest"] = "sha256:" + "0" * 64
    with pytest.raises(build.SupplyError, match="uv.lock missing or mismatched"):
        build.validate_inventory(subject, inventory)


@pytest.mark.parametrize(
    "instruction",
    [
        "copy metadata/ /home/candidate/Projects/claude-power-pack/",
        "  COPY metadata/ /home/candidate/Projects/claude-power-pack/",
        "ADD metadata/ /home/candidate/Projects/claude-power-pack/",
        "RUN cp -r /tmp/runtime-supply/metadata /home/candidate/Projects/claude-power-pack",
        "USER root",
    ],
)
def test_unknown_final_instruction_is_refused(instruction: str) -> None:
    fragment = (SUPPLY / "Dockerfile.fragment").read_bytes() + (instruction + "\n").encode()
    with pytest.raises(build.SupplyError, match="final recipe"):
        build.render_recipe(
            b"FROM base AS trial\n",
            fragment,
            build.load_json((SUPPLY / "runtime-policy.json").read_bytes()),
        )


@pytest.mark.parametrize(
    "uv_output,changed_lock,error",
    [
        ("uv 0.9.7\n", False, None),
        ("uv 0.0.0\n", False, "measured uv version"),
        ("uv 0.9.7\n", True, "uv.lock digest mismatch"),
    ],
)
def test_descriptor_writer_measures_version_and_post_sync_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source: tuple[str, dict[str, bytes]],
    uv_output: str,
    changed_lock: bool,
    error: str | None,
) -> None:
    _, inputs = source
    (tmp_path / "runtime-policy.json").write_bytes((SUPPLY / "runtime-policy.json").read_bytes())
    (tmp_path / "metadata").mkdir()
    for name in ("pyproject.toml", "uv.lock"):
        (tmp_path / "metadata" / name).write_bytes(inputs[f"{build.FIXTURE}/{name}"])
    if changed_lock:
        (tmp_path / "metadata/uv.lock").write_bytes(b"changed during sync")
    calls = []

    def observed(argv: list[str], **kwargs: Any) -> Any:
        calls.append(argv)
        assert argv == ["uv", "--version"]
        assert kwargs == {"check": True, "capture_output": True, "text": True}
        return SimpleNamespace(stdout=uv_output)

    monkeypatch.setattr(build, "subprocess", SimpleNamespace(run=observed))
    monkeypatch.setattr(
        build,
        "sys",
        SimpleNamespace(
            executable="/usr/bin/python3",
            platform="linux",
            implementation=SimpleNamespace(cache_tag="cpython-311"),
        ),
    )
    monkeypatch.setattr(
        build,
        "platform",
        SimpleNamespace(
            python_version=lambda: "3.11.2",
            machine=lambda: "x86_64",
        ),
    )
    monkeypatch.setenv("PATH", "/usr/local/bin:/usr/bin:/bin")
    if error:
        with pytest.raises(build.SupplyError, match=error):
            build.write_descriptor(tmp_path)
        assert not (tmp_path / "runtime-supply.json").exists()
    else:
        build.write_descriptor(tmp_path)
        assert (tmp_path / "runtime-supply.json").read_bytes() == (
            CASES / "descriptor.good.json"
        ).read_bytes()
    assert calls == ([] if changed_lock else [["uv", "--version"]])


@pytest.mark.parametrize(
    "rows,error",
    [
        (b"", "empty population"),
        (b"120000 blob " + b"0" * 40 + b"\tdocker/trial/Dockerfile\0", "regular files"),
    ],
)
def test_source_population_controls(
    monkeypatch: pytest.MonkeyPatch,
    rows: bytes,
    error: str,
) -> None:
    def git(_repo: Path, *args: str) -> bytes:
        if args == ("rev-parse", "HEAD"):
            return b"1" * 40 + b"\n"
        assert args == ("ls-tree", "-rz", "1" * 40, "docker/trial")
        return rows

    monkeypatch.setattr(build, "_git", git)
    with pytest.raises(build.SupplyError, match=error):
        build.source_inputs(ROOT)


def test_oversized_and_non_object_json_controls() -> None:
    for data in (b" " * build.MAX_JSON + b"{}", b"[]", b"null"):
        with pytest.raises(build.SupplyError, match="JSON"):
            build.load_json(data)


@pytest.mark.parametrize(
    "old,new",
    [
        (
            "FROM trial AS profile-runtime-empty-cache",
            "RUN cp -a /tmp/runtime-supply/metadata/.venv /tmp/dependency-cache/project-venv\n\nFROM trial AS profile-runtime-empty-cache",
        ),
        ("FROM trial AS profile-runtime-cache", "FROM different-image AS profile-runtime-cache"),
        ("uv sync --locked --no-install-project", "uv sync --no-install-project"),
    ],
)
def test_warm_stage_cannot_change_base_lock_or_cache_contents(old: str, new: str) -> None:
    fragment = (SUPPLY / "Dockerfile.fragment").read_bytes().replace(old.encode(), new.encode(), 1)
    with pytest.raises(build.SupplyError, match="warm recipe"):
        build.render_recipe(
            b"FROM base AS trial\n",
            fragment,
            build.load_json((SUPPLY / "runtime-policy.json").read_bytes()),
        )


@pytest.mark.parametrize("key", ["recipe_sha256", "base_recipe_sha256", "build_context_sha256"])
def test_receipt_digest_format_without_prepared_context(key: str) -> None:
    receipt = _read("receipt.good.json")
    receipt[key] = "not-a-digest"
    with pytest.raises(build.SupplyError, match=f"malformed {key}"):
        build.validate_receipt(
            receipt, (CASES / "descriptor.good.json").read_bytes(), receipt["image_id"]
        )


def test_docker_failure_retains_bounded_diagnostic(monkeypatch: pytest.MonkeyPatch) -> None:
    def failed(argv: list[str], **kwargs: Any) -> Any:
        raise subprocess.CalledProcessError(1, argv, stderr="x" * 20000 + "offline package missing")

    monkeypatch.setattr(
        build,
        "subprocess",
        SimpleNamespace(
            run=failed,
            CalledProcessError=subprocess.CalledProcessError,
        ),
    )
    with pytest.raises(build.SupplyError, match="offline package missing") as error:
        build.docker(["build", "--target", "profile-runtime", "/context"])
    assert len(str(error.value)) < 17000


@pytest.mark.parametrize(
    "anchor,instruction",
    [
        (
            "FROM trial AS profile-runtime-empty-cache",
            "RUN cp -a /tmp/runtime-supply/metadata/.venv /tmp/dependency-cache/project-venv",
        ),
        (
            "FROM profile-runtime AS profile-runtime-cache-permissions",
            "copy metadata/ /home/candidate/Projects/claude-power-pack/",
        ),
    ],
)
def test_physical_comment_cannot_hide_recipe_instruction(anchor: str, instruction: str) -> None:
    hidden = "# ignored physical comment " + "\\" + "\n" + instruction + "\n" + anchor
    fragment = (
        (SUPPLY / "Dockerfile.fragment").read_bytes().replace(anchor.encode(), hidden.encode())
    )
    with pytest.raises(build.SupplyError, match="comment continuation"):
        build.render_recipe(
            b"FROM base AS trial\n",
            fragment,
            build.load_json((SUPPLY / "runtime-policy.json").read_bytes()),
        )


@pytest.mark.parametrize("override", ["/external/dev-venv", ""])
def test_observed_image_cannot_select_an_undeclared_project_environment(
    tmp_path: Path, override: str,
) -> None:
    # Descriptor and all required values remain valid. Only the independently
    # observed image Env carries the override, including the empty-value case.
    fake = FakeDocker(project_environment=override)
    output = tmp_path / "receipt.json"
    with pytest.raises(build.SupplyError, match="UV_PROJECT_ENVIRONMENT"):
        build.build_image(ROOT, output, run=fake)
    assert not output.exists()
    assert fake.calls[-1] == ["rm", "a" * 64]
