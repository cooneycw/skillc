"""#287 P3: the checks that bind the two completed pilot declarations.

Each is a gate that lets a PAID study through and that nothing downstream
re-derives, so each has a committed red case. Every red here was also run
against the pre-P3 code, where the bad input was accepted (or the check did
not exist); see the PR body for those runs.

C1  placeholder identities ("PENDING", "PROPOSED") are refused at approval.
C2  an outcome-endpoint calibration declaration must carry a tolerance, and its
    report applies it.
C3  the run is bound to the declared image TAG, its resolved image ID, and the
    exact runtime receipt bytes.
C4  the declaration is bound to provider-only egress (#442), and an attempt
    whose recorded egress does not match is ineligible.
C5  the declared run store is durable: absolute, never /tmp or a scratchpad,
    and the CLI writes there.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from skillc import calibration, egress
from skillc import calibration_run as cr
from skillc import collection_conformance as cc

ROOT = Path(__file__).resolve().parent.parent
DISCRIMINATION = ROOT / "evals/calibration-287/pilot-discrimination-declaration.json"
IMPROVEMENT = ROOT / "evals/calibration-287/pilot-improvement-declaration.json"
INVENTORY_DIGEST = "sha256:4ee34823eb9f12c86d35f67d731b97a4c86dcd37ef77f9cada1ba78efe5f695a"


def _draft(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _approve(data: dict[str, Any]) -> dict[str, Any]:
    """A TEST-ONLY approval stamped at the declaration's own digest - never
    committed; the committed drafts keep `approval: null`."""
    data = copy.deepcopy(data)
    data["approval"] = {"by": "TEST ONLY", "at": "2026-10-17", "attempts_per_arm": data["attempts_per_arm"],
                        "profile_inventory_digest": INVENTORY_DIGEST}
    if data["kind"] == calibration.DISCRIMINATION_KIND:
        data["approval"]["mutated_digest"] = next(a for a in data["arms"] if a["name"] == "degraded")["mutation"][
            "mutated_digest"]
    fixture = data["task"].get("fixture")
    if fixture and fixture != "fixture":
        data["approval"]["task_fixture"] = fixture
    data["approval"]["declaration_digest"] = calibration.declaration_digest(data)
    return data


def _authorize(data: dict[str, Any]) -> None:
    if data["kind"] == calibration.DISCRIMINATION_KIND:
        calibration.require_approved_discrimination(calibration.parse_discrimination_declaration(data), ROOT)
    else:
        calibration.require_approved(calibration.parse_declaration(data), ROOT)


@pytest.mark.parametrize("path", [DISCRIMINATION, IMPROVEMENT], ids=["discrimination", "improvement"])
def test_the_completed_drafts_authorize_under_a_test_approval(path: Path) -> None:
    """The positive control every red below departs from."""
    _authorize(_approve(_draft(path)))


@pytest.mark.parametrize("path", [DISCRIMINATION, IMPROVEMENT], ids=["discrimination", "improvement"])
def test_the_committed_drafts_stay_unapproved(path: Path) -> None:
    assert _draft(path)["approval"] is None


# ------------------------------------------------------------------- C1

@pytest.mark.parametrize("marker", ["PENDING", "PROPOSED: gpt-6-astra"])
@pytest.mark.parametrize("path", [DISCRIMINATION, IMPROVEMENT], ids=["discrimination", "improvement"])
def test_c1_a_placeholder_identity_is_refused(path: Path, marker: str) -> None:
    data = _draft(path)
    data["shared"]["model"] = marker
    with pytest.raises(calibration.DeclarationRefused, match="placeholder"):
        _authorize(_approve(data))


def test_c1_a_placeholder_inside_an_arm_subject_is_refused() -> None:
    data = _draft(IMPROVEMENT)
    data["shared"]["image"]["provenance"] = "PENDING rebuild"
    with pytest.raises(calibration.DeclarationRefused, match="placeholder"):
        _authorize(_approve(data))


@pytest.mark.parametrize("prose", [
    "Recorded image replaces the PROPOSED image in the earlier draft.",
    "no longer PENDING: measured at P3",
])
def test_c1_prose_that_mentions_a_marker_is_not_a_placeholder(prose: str) -> None:
    """Counter-model finding: commentary about an earlier placeholder is bound
    by the whole-declaration digest, not refused as a placeholder."""
    data = _draft(IMPROVEMENT)
    data["shared"]["image"]["provenance"] = prose
    _authorize(_approve(data))


# ------------------------------------------------------------------- C2

def test_c2_an_endpoint_declaration_without_a_tolerance_is_refused() -> None:
    data = _draft(IMPROVEMENT)
    del data["tolerance"]
    with pytest.raises(calibration.DeclarationRefused, match="tolerance"):
        calibration.parse_declaration(data)


def test_c2_the_improvement_tolerance_is_parsed_and_applied_at_the_boundary() -> None:
    declaration = calibration.parse_declaration(_draft(IMPROVEMENT))
    tolerance = declaration.tolerance_non_evaluable_per_arm
    assert tolerance == 1
    report = {"attempts": [{"arm": "intact", "primary_endpoint": {"status": s}} for s in ("PASS", "NOT_GRADED")]
              + [{"arm": "baseline", "primary_endpoint": {"status": s}} for s in ("PASS", "NOT_GRADED", "NOT_GRADED")]}
    out = cr.apply_tolerance(report, tolerance)
    assert out["intact"]["verdict_status"] == "EVALUABLE"
    assert out["baseline"]["verdict_status"] == "UNKNOWN"


def test_c2_a_legacy_declaration_without_an_endpoint_needs_no_tolerance() -> None:
    legacy = calibration.load_declaration(ROOT / "evals/calibration-204/run-manifest.json")
    assert legacy.tolerance_non_evaluable_per_arm is None


# ------------------------------------------------------------------- C3

def _receipt(tmp_path: Path, body: bytes = b'{"receipt": "bytes"}') -> tuple[Path, str]:
    path = tmp_path / "receipt.json"
    path.write_bytes(body)
    return path, "sha256:" + hashlib.sha256(body).hexdigest()


def _with_receipt(data: dict[str, Any], digest: str) -> calibration.CalibrationDeclaration:
    data = copy.deepcopy(data)
    data["shared"]["image"]["receipt_sha256"] = digest
    return calibration.parse_declaration(data)


def test_c3_the_declared_tag_id_and_receipt_bind(tmp_path: Path) -> None:
    receipt, digest = _receipt(tmp_path)
    declaration = _with_receipt(_draft(IMPROVEMENT), digest)
    image = declaration.shared["image"]
    cr.require_image_binding(declaration, image_arg=image["tag"], resolved_digest=image["digest"],  # type: ignore[index]
                             receipt_path=receipt)


def test_c3_the_right_digest_under_another_tag_is_refused(tmp_path: Path) -> None:
    receipt, digest = _receipt(tmp_path)
    declaration = _with_receipt(_draft(IMPROVEMENT), digest)
    with pytest.raises(cr.CalibrationRefused, match="tag"):
        cr.require_image_binding(declaration, image_arg="skillc-trial:latest",
                                 resolved_digest=declaration.shared["image"]["digest"],  # type: ignore[index]
                                 receipt_path=receipt)


def test_c3_the_declared_tag_re_pointed_at_another_image_is_refused(tmp_path: Path) -> None:
    """The tag string matches, but the daemon resolves it to a different ID."""
    receipt, digest = _receipt(tmp_path)
    declaration = _with_receipt(_draft(IMPROVEMENT), digest)
    with pytest.raises(cr.CalibrationRefused, match="resolves to"):
        cr.require_image_binding(declaration, image_arg=declaration.shared["image"]["tag"],  # type: ignore[index]
                                 resolved_digest="sha256:" + "9" * 64, receipt_path=receipt)


def test_c3_a_receipt_with_one_byte_changed_is_refused(tmp_path: Path) -> None:
    receipt, digest = _receipt(tmp_path)
    declaration = _with_receipt(_draft(IMPROVEMENT), digest)
    receipt.write_bytes(receipt.read_bytes() + b" ")
    with pytest.raises(cr.CalibrationRefused, match="receipt"):
        cr.require_image_binding(declaration, image_arg=declaration.shared["image"]["tag"],  # type: ignore[index]
                                 resolved_digest=declaration.shared["image"]["digest"],  # type: ignore[index]
                                 receipt_path=receipt)


def test_c3_a_missing_receipt_is_refused(tmp_path: Path) -> None:
    declaration = calibration.parse_declaration(_draft(IMPROVEMENT))
    with pytest.raises(cr.CalibrationRefused, match="receipt"):
        cr.require_image_binding(declaration, image_arg=declaration.shared["image"]["tag"],  # type: ignore[index]
                                 resolved_digest=declaration.shared["image"]["digest"],  # type: ignore[index]
                                 receipt_path=None)


@pytest.mark.parametrize("value", ["DELETE", None, "", "0eb308d3", "sha256:XYZ"])
@pytest.mark.parametrize("path", [DISCRIMINATION, IMPROVEMENT], ids=["discrimination", "improvement"])
def test_c3_a_new_kind_declaration_without_a_well_formed_receipt_digest_is_refused(path: Path, value: object) -> None:
    """Counter-model finding: a deleted receipt digest fell back to the legacy
    ID-only check, and a null one skipped the receipt check entirely."""
    data = _draft(path)
    if value == "DELETE":
        del data["shared"]["image"]["receipt_sha256"]
    else:
        data["shared"]["image"]["receipt_sha256"] = value
    with pytest.raises(calibration.DeclarationRefused, match="receipt_sha256"):
        _authorize(_approve(data))


@pytest.mark.parametrize("value", [None, ""])
def test_c3_the_run_binding_refuses_a_null_declared_receipt(tmp_path: Path, value: object) -> None:
    receipt, _digest = _receipt(tmp_path)
    data = _draft(IMPROVEMENT)
    data["shared"]["image"]["receipt_sha256"] = value
    declaration = calibration.parse_declaration(data)
    with pytest.raises(cr.CalibrationRefused, match="receipt"):
        cr.require_image_binding(declaration, image_arg=declaration.shared["image"]["tag"],  # type: ignore[index]
                                 resolved_digest=declaration.shared["image"]["digest"],  # type: ignore[index]
                                 receipt_path=receipt)


# ------------------------------------------------------------------- C4

@pytest.mark.parametrize("field, value", [
    ("allowlist_digest", "sha256:" + "0" * 64),
    ("policy", "bridge"),
    ("codex_server_side_off", ["--strict-config"]),
])
@pytest.mark.parametrize("path", [DISCRIMINATION, IMPROVEMENT], ids=["discrimination", "improvement"])
def test_c4_a_declaration_off_the_provider_only_policy_is_refused(path: Path, field: str, value: object) -> None:
    data = _draft(path)
    data["shared"]["agent_network"][field] = value
    with pytest.raises(calibration.DeclarationRefused, match="agent_network"):
        _authorize(_approve(data))


def test_c4_a_new_kind_declaration_without_agent_network_is_refused() -> None:
    data = _draft(DISCRIMINATION)
    del data["shared"]["agent_network"]
    with pytest.raises(calibration.DeclarationRefused, match="agent_network"):
        _authorize(_approve(data))


def _record(egress_summary: object) -> dict[str, object]:
    return {"disposition": "captured", "observation": {"egress": egress_summary}}


def test_c4_an_attempt_with_the_declared_allowlist_is_egress_eligible() -> None:
    ok, reason = cr.egress_eligibility(_record({"status": "read", "allowlist_digest": egress.allowlist_digest(),
                                                "allowed": {"chatgpt.com:443": 3}, "denied": {}}),
                                       egress.allowlist_digest())
    assert ok and reason is None


@pytest.mark.parametrize("summary, match", [
    ({"status": "read", "allowlist_digest": "sha256:" + "0" * 64}, "allowlist"),
    ({"status": "unread", "reason": "x"}, "not read"),
    (None, "no egress"),
])
def test_c4_an_attempt_without_matching_egress_evidence_is_ineligible(summary: object, match: str) -> None:
    ok, reason = cr.egress_eligibility(_record(summary), egress.allowlist_digest())
    assert ok is False and match in str(reason)


def test_c4_the_declared_policy_is_the_code_s_policy() -> None:
    network = _draft(DISCRIMINATION)["shared"]["agent_network"]
    assert network["policy"] == cc.AGENT_NETWORK_POLICY
    assert network["allowlist_digest"] == egress.allowlist_digest()
    assert network["codex_server_side_off"] == list(egress.CODEX_SERVER_SIDE_OFF)


# ------------------------------------------------------------------- C5

@pytest.mark.parametrize("store", [
    "/tmp/calibration-287", "/var/tmp/x", "relative/store",
    "/tmp/claude-1000/project/session/scratchpad/runs", "/srv/u/work/scratchpad/runs",
    "~other/skillc-evidence", "~", "~/../../tmp/x", "/srv/u/../../tmp/x", "~/work/scratchpad/runs",
    "/./tmp/x", "/var//tmp/x", "/dev//shm/x", "//tmp/x", "~/./x", "~//x",
])
@pytest.mark.parametrize("path", [DISCRIMINATION, IMPROVEMENT], ids=["discrimination", "improvement"])
def test_c5_a_non_durable_run_store_is_refused(path: Path, store: str) -> None:
    data = _draft(path)
    data["run_store"] = store
    with pytest.raises(calibration.DeclarationRefused, match="run_store"):
        _authorize(_approve(data))


def test_c5_a_new_kind_declaration_without_run_store_is_refused() -> None:
    data = _draft(IMPROVEMENT)
    del data["run_store"]
    with pytest.raises(calibration.DeclarationRefused, match="run_store"):
        _authorize(_approve(data))


def test_c5_the_cli_writes_to_the_expanded_declared_store_and_refuses_another(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", "/srv/runner")
    monkeypatch.delenv("TMPDIR", raising=False)
    data = _draft(DISCRIMINATION)
    assert str(data["run_store"]).startswith("~/"), "the committed declaration carries no host path"
    declaration = calibration.parse_discrimination_declaration(data)
    expanded = Path("/srv/runner/skillc-evidence/calibration-287/pilot-discrimination")
    assert cr.private_root(declaration, None) == expanded
    assert cr.private_root(declaration, str(expanded)) == expanded
    with pytest.raises(cr.CalibrationRefused, match="run_store"):
        cr.private_root(declaration, "/var/lib/elsewhere")


@pytest.mark.parametrize("home, tmpdir", [
    ("/tmp/home-runner", None),                       # HOME itself under /tmp
    ("/srv/ci-tmp/home", "/srv/ci-tmp"),              # HOME under $TMPDIR
    ("/srv/u/.claude/scratchpad", None),             # HOME inside a session scratchpad
    ("", None),                                       # HOME unset: nothing to expand against
    ("/var/../tmp/home", None),                       # HOME spelled to hide /tmp
    ("/srv//tmp-free/../../tmp/h", None),
])
def test_c5_a_home_store_that_expands_somewhere_non_durable_is_refused_at_launch(
        monkeypatch: pytest.MonkeyPatch, home: str, tmpdir: str | None) -> None:
    """The `~/` literal parses (the digest binds the string); the refusal applies
    to the EXPANDED path, before any acquisition or container."""
    monkeypatch.setenv("HOME", home)
    if tmpdir is None:
        monkeypatch.delenv("TMPDIR", raising=False)
    else:
        monkeypatch.setenv("TMPDIR", tmpdir)
    declaration = calibration.parse_declaration(_draft(IMPROVEMENT))
    with pytest.raises(cr.CalibrationRefused, match="run_store"):
        cr.private_root(declaration, None)


def test_c5_a_store_whose_real_destination_is_a_temp_directory_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """A symlinked ancestor can carry a durable-looking path into /tmp; the
    check reads the real destination too (simulated: a non-temp symlink cannot
    be created inside a test's temp directory)."""
    import os
    real = os.path.realpath
    monkeypatch.setattr(os.path, "realpath", lambda p: "/tmp/evidence" if str(p).startswith("/srv/linked") else real(p))
    monkeypatch.delenv("TMPDIR", raising=False)
    data = _draft(IMPROVEMENT)
    data["run_store"] = "/srv/linked/calibration-287"
    with pytest.raises(calibration.DeclarationRefused, match="resolves to '/tmp/evidence'"):
        _authorize(_approve(data))
