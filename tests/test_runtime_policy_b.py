"""#279 ca3030d re-pin (orchestrator policy B): a SECOND supported profile
runtime beside the unchanged primary.

Reds (orchestrator conditions):
1. selection is a FUNCTION: two runtimes on one (locator, revision, gate) key,
   or one runtime_id twice, refuse when the policies LOAD - never first-match;
2. the cicd runtime stays on the primary pin: a ca3030d cicd closure selects
   nothing, and a cicd receipt whose base is the ca3030d runtime is refused;
plus: a receipt for one pin never serves another pin's closure, and the image
builder supplies only the runtimes it knows.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest
from test_runtime_supply import DESCRIPTOR, RECEIPT, cicd_receipt, cicd_selection, selection

from skillc import runtime_supply as rs

ROOT = Path(__file__).resolve().parent.parent
CA3030D = "ca3030dbeba4a145166b61d714861f56e92cd034"
spec = importlib.util.spec_from_file_location("profile_trial_build_runtime", ROOT / "docker/profile-trial/build_runtime.py")
assert spec and spec.loader
build_runtime: Any = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_runtime)


def _ca3030d_receipt(descriptor: bytes) -> bytes:
    receipt = json.loads(RECEIPT)
    receipt.update(runtime_id="cpp-codex-flow-auto-ca3030d", subject_revision=CA3030D,
                   descriptor_sha256=hashlib.sha256(descriptor).hexdigest())
    return json.dumps(receipt).encode()


def _ca3030d_descriptor() -> bytes:
    value = json.loads(DESCRIPTOR)
    value.update(runtime_id="cpp-codex-flow-auto-ca3030d", subject_revision=CA3030D)
    return json.dumps(value).encode()


def test_two_profile_runtimes_load_the_primary_unchanged() -> None:
    policies = rs.profile_policies()
    assert [p["runtime_id"] for p in policies] == ["cpp-codex-flow-check-86641e8", "cpp-codex-flow-auto-ca3030d"]
    assert policies[0] == rs.supported_policy()
    assert policies[1]["subject_revision"] == CA3030D
    # The same dependency layer: only the pin differs.
    assert {k: v for k, v in policies[1].items() if k not in ("runtime_id", "subject_revision")} == \
        {k: v for k, v in policies[0].items() if k not in ("runtime_id", "subject_revision")}


def test_each_pin_selects_its_own_runtime_and_an_unknown_pin_selects_none() -> None:
    assert rs.selected_runtime(**selection()) == rs.PROFILE_RUNTIME  # 86641e8
    assert rs.selected_runtime(**{**selection(), "revision": CA3030D}) == rs.PROFILE_RUNTIME
    assert rs.selected_runtime(**{**selection(), "revision": "0" * 40}) is None


@pytest.mark.parametrize("clash", ["same-key", "same-id"])
def test_red_1_a_policy_with_two_runtimes_on_one_key_or_id_is_refused_at_load(
        monkeypatch: pytest.MonkeyPatch, clash: str) -> None:
    primary = rs.supported_policy()
    twin = dict(primary)
    if clash == "same-key":
        twin["runtime_id"] = "another-runtime"  # the same (locator, revision, gate)
    else:
        twin["subject_revision"] = CA3030D  # a different pin under the SAME id
    real = rs.resources.files

    class _Files:
        def __init__(self, inner: Any) -> None:
            self.inner = inner

        def joinpath(self, name: str) -> Any:
            if name != rs.EXTRA_POLICIES_RESOURCE:
                return self.inner.joinpath(name)
            raw = json.dumps({"profile_runtimes": [twin]}).encode()

            class _Res:
                def open(self, _mode: str) -> Any:
                    import io
                    return io.BytesIO(raw)
            return _Res()
    monkeypatch.setattr(rs.resources, "files", lambda pkg: _Files(real(pkg)))
    with pytest.raises(rs.Refused, match="share a"):
        rs.profile_policies()
    with pytest.raises(rs.Refused, match="share a"):
        rs.selected_runtime(**selection())  # never first-match


def test_red_2_the_cicd_runtime_stays_on_the_primary_pin() -> None:
    assert rs.selected_runtime(**cicd_selection()) == rs.CICD_RUNTIME
    assert rs.selected_runtime(**{**cicd_selection(), "revision": CA3030D}) is None
    receipt = cicd_receipt()
    receipt["base_receipt"] = json.loads(_ca3030d_receipt(_ca3030d_descriptor()))
    receipt["base_image_id"] = receipt["base_receipt"]["image_id"]
    with pytest.raises(rs.Refused, match="unsupported runtime"):
        rs.RuntimeSupply(json.dumps(receipt).encode())


def test_a_ca3030d_receipt_validates_against_its_own_policy() -> None:
    descriptor = _ca3030d_descriptor()
    supply = rs.RuntimeSupply(_ca3030d_receipt(descriptor))
    assert supply.subject_revision == CA3030D and supply.policy["runtime_id"] == "cpp-codex-flow-auto-ca3030d"
    image = json.loads(RECEIPT)["image_id"]
    assert supply.descriptor(descriptor, actual_image=image)["runtime_id"] == "cpp-codex-flow-auto-ca3030d"
    with pytest.raises(rs.Refused):  # the 86641e8 descriptor cannot pass as the ca3030d runtime's
        rs.RuntimeSupply(_ca3030d_receipt(DESCRIPTOR)).descriptor(DESCRIPTOR, actual_image=image)


def test_red_a_receipt_for_one_pin_never_serves_another_pins_closure() -> None:
    old = rs.RuntimeSupply(RECEIPT)  # the primary, 86641e8
    rs.require_kind(old, rs.PROFILE_RUNTIME, revision="86641e817711d8a7746270745a5dfa7cacf04b0c")
    with pytest.raises(rs.Refused, match="serves subject 86641e817711"):
        rs.require_kind(old, rs.PROFILE_RUNTIME, revision=CA3030D)
    new = rs.RuntimeSupply(_ca3030d_receipt(_ca3030d_descriptor()))
    with pytest.raises(rs.Refused, match="serves subject ca3030dbeba4"):
        rs.require_kind(new, rs.PROFILE_RUNTIME, revision="86641e817711d8a7746270745a5dfa7cacf04b0c")


def test_an_unknown_runtime_id_in_a_receipt_is_refused() -> None:
    receipt = json.loads(RECEIPT)
    receipt["runtime_id"] = "cpp-codex-someone-else"
    with pytest.raises(rs.Refused, match="unsupported runtime"):
        rs.RuntimeSupply(json.dumps(receipt).encode())


def test_the_builders_extra_policy_is_skillcs_byte_for_byte() -> None:
    assert (ROOT / "docker/profile-trial/runtime-policy-extra.json").read_bytes() == \
        (ROOT / "skillc/runtime-policy-extra.json").read_bytes()
    assert {i: e["subject_revision"] for i, e in build_runtime.extra_runtimes().items()} == \
        {p["runtime_id"]: p["subject_revision"] for p in rs.profile_policies()[1:]}


def test_the_primary_builder_is_untouched_and_the_extra_one_differs_only_in_identity() -> None:
    """build.py's bytes are the PRIMARY runtime's build context, so it is never
    edited for another pin; the generated builder rebinds two lines, no more."""
    primary = (ROOT / "docker/profile-trial/build.py").read_bytes()
    generated = build_runtime.builder_source("cpp-codex-flow-auto-ca3030d", CA3030D)
    changed = [(a, b) for a, b in zip(primary.decode().splitlines(), generated.decode().splitlines(), strict=True)
               if a != b]
    assert changed == [('RUNTIME_ID = "cpp-codex-flow-check-86641e8"', 'RUNTIME_ID = "cpp-codex-flow-auto-ca3030d"'),
                       ('REVISION = "86641e817711d8a7746270745a5dfa7cacf04b0c"', f'REVISION = "{CA3030D}"')]


def test_the_builder_prepares_the_ca3030d_runtime_from_its_own_profile(tmp_path: Path) -> None:
    (tmp_path / "builder").mkdir()
    build, policy = build_runtime.load_builder("cpp-codex-flow-auto-ca3030d", tmp_path / "builder")
    prepared = build.prepare(ROOT, tmp_path / "context", policy_bytes=policy)
    assert prepared["policy"]["runtime_id"] == "cpp-codex-flow-auto-ca3030d"
    assert prepared["policy"]["subject_revision"] == CA3030D
    # The image's own descriptor writer is the generated builder, so its
    # in-image identity check is this runtime's.
    assert (tmp_path / "context" / "runtime-build.py").read_bytes() == \
        build_runtime.builder_source("cpp-codex-flow-auto-ca3030d", CA3030D)


@pytest.mark.parametrize("runtime_id", ["cpp-codex-flow-check-ca3030d", "cpp-codex-flow-check-86641e8"])
def test_red_the_extra_builder_supplies_only_an_extra_runtime_it_knows(tmp_path: Path, runtime_id: str) -> None:
    """A deferred flow-check pin (#525) is no runtime; the primary is build.py's own."""
    with pytest.raises(build_runtime.RuntimeRefused, match="not an extra runtime"):
        build_runtime.load_builder(runtime_id, tmp_path)
