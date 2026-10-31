"""Offline controls for the cicd runtime layer (skillc#280).

Two claims, each with a committed case that makes it report the other verdict:

1. The flow-check runtime's build inputs match its reviewed recipe.
   `docker/profile-trial/build.py`'s `prepare()` hashes every input a
   flow-check profile-runtime receipt is bound to. The current goldens were
   measured after #637's deliberate Codex 0.165.0 pin upgrade; historical
   declarations and runtime receipts are not rewritten. A one-byte change to
   any docker/trial input must move them (the negative control), so a pass
   here means "matches the reviewed inputs", not "not looked at".
2. `docker/cicd-trial/build.py` writes a receipt only for an image that is its
   validated base plus exactly one layer, with the base's configuration and
   descriptor. Each binding check has a fake-Docker case that breaks only it.

No Docker daemon is used. Whether the real layer builds and runs is
tests/test_cicd_profile_live.py's claim.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from skillc import runtime_supply as rs

ROOT = Path(__file__).resolve().parents[1]
from test_runtime_supply import DESCRIPTOR, RECEIPT

#: `prepare()` after #637's Codex 0.165.0 recipe/manifest pin upgrade.
GOLDEN_FLOW_CHECK_INPUTS = {
    "build_context_sha256": "4177260e9058a2e8f7118a7e8cf169a79d616576e8020eacade6bf51bb8501f6",
    "base_recipe_sha256": "23e9583d0c4498d37851d2d2cce8b7cb72ecf873fd4ce306e3b81739d78d8a85",
    "recipe_sha256": "1c8731b14c097db59b9daa3faef89d39340e369fee1f01b80e2ed5586e93a9a9",
}
SUBJECT = "evals/subjects/cpp-codex-flow-check-86641e8"
FIXTURE = "tests/fixtures/profile-cpp-codex-flow-check-86641e8"


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


profile_builder = _load("profile_runtime_builder_280", ROOT / "docker" / "profile-trial" / "build.py")
cicd_builder = _load("cicd_runtime_builder_280", ROOT / "docker" / "cicd-trial" / "build.py")


def _flow_check_inputs() -> dict[str, bytes]:
    """The working-tree bytes of every input family `source_inputs` reads from
    git - read from disk, because skillc's CI image has no git."""
    names = [q for q in (ROOT / "docker" / "trial").iterdir() if q.is_file() and not q.name.startswith(".")]
    inputs = {f"docker/trial/{q.name}": q.read_bytes() for q in names}
    for name in (f"{SUBJECT}/subject.json", f"{SUBJECT}/evidence/inventory.json",
                 f"{FIXTURE}/pyproject.toml", f"{FIXTURE}/uv.lock"):
        inputs[name] = (ROOT / name).read_bytes()
    return inputs


def _prepared(tmp_path: Path, inputs: dict[str, bytes]) -> dict[str, str]:
    prepared = profile_builder.prepare(ROOT, tmp_path / "context", inputs=inputs, source_commit="0" * 40)
    return {key: prepared[key] for key in GOLDEN_FLOW_CHECK_INPUTS}


def test_the_flow_check_runtime_build_inputs_match_the_reviewed_recipe(tmp_path: Path) -> None:
    assert _prepared(tmp_path, _flow_check_inputs()) == GOLDEN_FLOW_CHECK_INPUTS


@pytest.mark.parametrize(("name", "moves"), [
    ("docker/trial/Dockerfile", {"build_context_sha256", "base_recipe_sha256", "recipe_sha256"}),
    ("docker/trial/check_pins.py", {"build_context_sha256"}),
])
def test_a_one_byte_trial_change_moves_the_golden_hashes(tmp_path: Path, name: str, moves: set[str]) -> None:
    """Negative control: the golden comparison above can fail."""
    inputs = _flow_check_inputs()
    inputs[name] = inputs[name] + b"\n"
    changed = _prepared(tmp_path, inputs)
    assert {key for key in GOLDEN_FLOW_CHECK_INPUTS if changed[key] != GOLDEN_FLOW_CHECK_INPUTS[key]} == moves


# --- the layered build, through an explicit fake Docker boundary ------------

BASE_ID = json.loads(RECEIPT)["image_id"]
LAYERED_ID = "sha256:" + "a" * 64
CID = "c" * 64
BASE_ENV = ["HOME=/home/candidate", "UV_OFFLINE=1"]
BASE_CONFIG: dict[str, Any] = {"User": "candidate", "WorkingDir": "/work", "Env": BASE_ENV,
                               "Entrypoint": None, "Cmd": ["bash"]}


class FakeDocker:
    def __init__(self, *, layers: list[str] | None = None, config: dict[str, Any] | None = None,
                 descriptor: bytes = DESCRIPTOR, curl: str = "curl 7.88.1 (x86_64-pc-linux-gnu) libcurl/7.88.1\n"):
        self.layers = layers if layers is not None else ["sha256:l1", "sha256:l2", "sha256:curl"]
        self.config = config if config is not None else dict(BASE_CONFIG)
        self.descriptor = descriptor
        self.curl = curl
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str]) -> str:
        self.calls.append(argv)
        if argv[:2] == ["image", "inspect"]:
            if argv[2] == BASE_ID:
                return json.dumps([{"Id": BASE_ID, "RootFS": {"Layers": ["sha256:l1", "sha256:l2"]},
                                    "Config": BASE_CONFIG}])
            return json.dumps([{"Id": LAYERED_ID, "RootFS": {"Layers": self.layers}, "Config": self.config}])
        if argv[0] == "build":
            Path(argv[argv.index("--iidfile") + 1]).write_text(LAYERED_ID)
            return ""
        if argv[0] == "create":
            return CID + "\n"
        if argv[0] == "cp":
            Path(argv[2]).write_bytes(self.descriptor)
            return ""
        if argv[0] == "run":
            return self.curl
        return ""


def _base_receipt(tmp_path: Path, raw: bytes | None = None) -> Path:
    receipt = json.loads(RECEIPT)
    receipt["descriptor_sha256"] = cicd_builder.sha256(DESCRIPTOR)
    path = tmp_path / "base.json"
    path.write_bytes(raw if raw is not None else json.dumps(receipt).encode())
    return path


def _build(tmp_path: Path, fake: FakeDocker, base: Path | None = None) -> dict[str, Any]:
    result: dict[str, Any] = cicd_builder.build_image(
        base or _base_receipt(tmp_path), tmp_path / "cicd.json", run=fake,
        recipe=("9" * 40, (ROOT / "docker" / "cicd-trial" / "Dockerfile").read_bytes()),
    )
    return result


def test_a_bound_layer_writes_a_cicd_receipt_the_controller_accepts(tmp_path: Path) -> None:
    fake = FakeDocker()
    receipt = _build(tmp_path, fake)
    supply = rs.RuntimeSupply.from_path(tmp_path / "cicd.json")
    rs.require_kind(supply, rs.CICD_RUNTIME)
    assert supply.image_id == LAYERED_ID and receipt["base_image_id"] == BASE_ID
    assert receipt["curl_version"] == "7.88.1"
    assert supply.descriptor(DESCRIPTOR, actual_image=LAYERED_ID) == json.loads(DESCRIPTOR)
    # The base is named by a deterministic tag and never untagged (an untag of
    # an image's only name deletes it).
    assert ["image", "tag", BASE_ID, cicd_builder.base_tag(BASE_ID)] in fake.calls
    assert ["image", "tag", LAYERED_ID, cicd_builder.runtime_tag(LAYERED_ID)] in fake.calls
    assert not any(call[:2] in (["image", "rm"], ["rmi", cicd_builder.base_tag(BASE_ID)]) for call in fake.calls)
    curl_call, = [call for call in fake.calls if call[0] == "run"]
    assert curl_call[:4] == ["run", "--rm", "--network", "none"]


@pytest.mark.parametrize(("fake", "symptom"), [
    (FakeDocker(layers=["sha256:l1", "sha256:l2", "sha256:curl", "sha256:extra"]), "exactly one layer"),
    (FakeDocker(layers=["sha256:l1", "sha256:l2"]), "exactly one layer"),
    (FakeDocker(layers=["sha256:l1", "sha256:other", "sha256:curl"]), "exactly one layer"),
    (FakeDocker(config={**BASE_CONFIG, "User": "root"}), "changed its base's User"),
    (FakeDocker(config={**BASE_CONFIG, "Env": [*BASE_ENV, "UV_PROJECT_ENVIRONMENT=/x"]}), "Env"),
    (FakeDocker(config={**BASE_CONFIG, "WorkingDir": "/"}), "WorkingDir"),
    (FakeDocker(descriptor=DESCRIPTOR + b"\n"), "descriptor differs"),
    (FakeDocker(curl="curl: command not found\n"), "did not name a version"),
], ids=["extra-layer", "no-layer", "replaced-base-layer", "user", "env", "workdir", "descriptor", "curl"])
def test_each_binding_check_refuses_its_own_break(tmp_path: Path, fake: FakeDocker, symptom: str) -> None:
    """M-d among them: an extra layer is refused, so no receipt exists."""
    with pytest.raises(cicd_builder.BuildError, match=symptom):
        _build(tmp_path, fake)
    assert not (tmp_path / "cicd.json").exists()


def test_the_base_must_be_a_valid_flow_check_receipt(tmp_path: Path) -> None:
    bad = json.loads(RECEIPT)
    bad["target"] = "profile-runtime-empty-cache"
    fake = FakeDocker()
    with pytest.raises(cicd_builder.BuildError, match="base receipt refused"):
        _build(tmp_path, fake, _base_receipt(tmp_path, json.dumps(bad).encode()))
    assert fake.calls == [], "a refused base must never reach Docker"


def test_a_cicd_receipt_cannot_be_layered_again(tmp_path: Path) -> None:
    _build(tmp_path, FakeDocker())
    fake = FakeDocker()
    nested = tmp_path / "nested"
    nested.mkdir()
    with pytest.raises(cicd_builder.BuildError, match="base receipt refused"):
        cicd_builder.build_image(tmp_path / "cicd.json", nested / "out.json", run=fake, recipe=("9" * 40, b""))
    assert fake.calls == []


def test_an_existing_output_is_refused_before_docker(tmp_path: Path) -> None:
    (tmp_path / "cicd.json").write_text("stale")
    fake = FakeDocker()
    with pytest.raises(cicd_builder.BuildError, match="already exists"):
        _build(tmp_path, fake)
    assert fake.calls == []
