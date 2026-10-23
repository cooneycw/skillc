"""`cpp-codex-flow-check` at claude-power-pack `b318a14b` (#529): the profile
CPP #1532 needs - flow-check's content after CPP #1497 - with its gate
witnessed on the routes the population offers once CPP #1542 has removed the
installed one: the skill-bundled copy (the `gate_entrypoint`, declared
bundled) and the checkout copy the exit-127 fallback names.

Red cases:
- the 86641e8-shaped profile (installed gate) at this pin is refused
  `bundled-gate-unwitnessed`, as #525 left it;
- this profile with its bundled declaration removed is refused too. On the
  pre-#529 code it VALIDATED with 0 problems (measured, #529): the installed-
  gate overlay would have moved the bundled script away from its siblings;
- adding an installed `~/.claude/scripts` gate is refused (it would hide #1542),
  and so is the checkout copy left undeclared (`gate-copy-unwitnessed`);
- a delivered neighbour skill's bundled gate is refused at assembly, which is
  why the subject selects flow-check alone;
- a checkout copy that names an unselected skill, is declared twice, or is
  the gate_entrypoint is refused;
- the runtime is selected only with this pin's metadata.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from skillc import cli
from skillc import profile as p
from skillc import runtime_supply as rs

ROOT = Path(__file__).resolve().parent.parent
PIN = "b318a14b9e7935f2c50c0940144a5ff0ff9389ed"
RUNTIME_ID = "cpp-codex-flow-check-b318a14b"
SUBJECT_DIR = ROOT / "evals" / "subjects" / RUNTIME_ID
SNAPSHOT = ROOT / "tests" / "fixtures" / f"profile-{RUNTIME_ID}"
OLD_SUBJECT_DIR = ROOT / "evals" / "subjects" / "cpp-codex-flow-check-86641e8"
NOT_CLOSURE = {"README.md", "LICENSE"}
BUNDLED = ".codex/skills/flow-check/scripts/flow-finish-gate.sh"
CHECKOUT = "Projects/claude-power-pack/scripts/flow-finish-gate.sh"


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _diagnose(data: dict[str, Any], tmp_path: Path) -> list[str]:
    """Diagnose a variant of this profile against the snapshot; its categories."""
    (tmp_path / "subject.json").write_bytes((SUBJECT_DIR / "subject.json").read_bytes())
    (tmp_path / "profile.json").write_text(json.dumps(data), encoding="utf-8")
    prof = p.Profile.load(tmp_path / "profile.json")
    return [problem["category"] for problem in p.diagnose(prof, p.load_tree(prof, None, SNAPSHOT))["problems"]]


def test_the_profile_is_clean_against_its_own_pin() -> None:
    prof = p.Profile.load(SUBJECT_DIR / "profile.json")
    report = p.diagnose(prof, p.load_tree(prof, None, SNAPSHOT))
    assert report["complete"] is True and report["problems"] == []
    assert _json(SUBJECT_DIR / "subject.json")["revision"] == PIN
    assert prof.select == ("flow-check",)
    assert (prof.gate_entrypoint, prof.gate_witness) == (BUNDLED, "flow-check")
    assert prof.bundled_gate_entrypoints == (BUNDLED,)
    assert prof.checkout_gate_entrypoints == {CHECKOUT: "flow-check"}
    assert ".claude/scripts" not in prof.allowed_destinations
    assert "~/.qwen/projects" in {u["reference"] for u in _json(SUBJECT_DIR / "profile.json")["unsupported"]}


def test_the_snapshot_inventory_is_the_committed_evidence(tmp_path: Path) -> None:
    out = tmp_path / "inventory.json"
    assert cli.main(["profile", "validate", str(SUBJECT_DIR / "profile.json"), "--snapshot", str(SNAPSHOT),
                     "--out", str(out)]) == 0
    evidence, snapshot = _json(SUBJECT_DIR / "evidence" / "inventory.json"), _json(out)
    assert evidence["subject"]["revision"] == PIN
    strip = lambda inv: {k: v for k, v in inv.items() if k != "subject"}
    assert strip(snapshot) == strip(evidence)
    assert evidence["checkout_gate_entrypoints"] == {CHECKOUT: "flow-check"}


def _closure_sources() -> set[str]:
    inventory = _json(SUBJECT_DIR / "evidence" / "inventory.json")
    sources = {f["source"] for group in (inventory["skills"], inventory["dependencies"])
               for entry in group for f in entry.get("files") or [] if f.get("source")}
    for pair in [*inventory["mirrors"], *inventory["generated_from"]]:
        sources |= {pair["source"], pair["generated"]}
    return sources | {"CLAUDE.md"}


def test_the_snapshot_is_exactly_the_closure() -> None:
    caches = {"__pycache__", ".ruff_cache", ".mypy_cache", ".pytest_cache"}
    present = {path.relative_to(SNAPSHOT).as_posix() for path in SNAPSHOT.rglob("*")
               if path.is_file() and not caches & set(path.relative_to(SNAPSHOT).parts)}
    assert present - NOT_CLOSURE == _closure_sources()


def test_the_snapshot_records_its_provenance_and_carries_the_upstream_licence() -> None:
    readme = (SNAPSHOT / "README.md").read_text(encoding="utf-8")
    assert "https://github.com/cooneycw/claude-power-pack" in readme
    assert f"`{PIN}`" in readme and "MIT" in readme
    licence = (SNAPSHOT / "LICENSE").read_text(encoding="utf-8")
    assert licence.startswith("MIT License") and "permission notice shall be included in all" in licence


def test_the_gate_map_is_re_read_at_this_pin() -> None:
    """Not carried over from 86641e8: both prescribed calls, BARE, at this pin."""
    reference = (SNAPSHOT / "codex" / "skills" / "flow-check" / "reference.md").read_text(encoding="utf-8")
    assert "```bash\nscripts/flow-finish-gate.sh --plan check --evidence flow-check\n```" in reference
    assert "```bash\nscripts/flow-finish-gate.sh --check-summary\n```" in reference
    assert "the CPP-checkout copy" in reference  # the fallback route D1 witnesses
    for doc in ("SKILL.md", "reference.md"):
        assert ".claude/scripts" not in (SNAPSHOT / "codex" / "skills" / "flow-check" / doc).read_text(encoding="utf-8")


def test_the_two_witnessed_copies_are_the_same_gate() -> None:
    bundled = SNAPSHOT / "codex" / "skills" / "flow-check" / "scripts"
    for name in ("flow-finish-gate.sh", "gate-lib.sh"):
        assert (bundled / name).read_bytes() == (SNAPSHOT / "scripts" / name).read_bytes()


# --- reds -----------------------------------------------------------------------------

def test_red_the_86641e8_shape_at_this_pin_is_refused_unwitnessed(tmp_path: Path) -> None:
    """#525's refusal, kept: the installed-gate profile shape at a pin whose
    skill runs its bundled gate cannot validate."""
    data = _json(OLD_SUBJECT_DIR / "profile.json")
    assert data["gate_entrypoint"] == ".claude/scripts/flow-finish-gate.sh"
    assert "bundled-gate-unwitnessed" in _diagnose(data, tmp_path)


def test_red_the_bundled_entrypoint_left_undeclared_is_unwitnessed(tmp_path: Path) -> None:
    """The regression #529 fixes: a skill-bundled gate_entrypoint its skill
    invokes bare, not declared bundled, was accepted - and the installed-gate
    overlay would have run it without its siblings."""
    data = _json(SUBJECT_DIR / "profile.json")
    del data["bundled_gate_entrypoints"], data["checkout_gate_entrypoints"]
    assert _diagnose(data, tmp_path) == ["bundled-gate-unwitnessed"]


def _with_installed_gate(widen: bool) -> dict[str, Any]:
    data = _json(SUBJECT_DIR / "profile.json")
    data["dependencies"].append({
        "id": "helper-installed-gate", "kind": "helper", "scope": "treatment", "role": "would hide CPP #1542",
        "source_root": "scripts", "paths": ["flow-finish-gate.sh"], "destination": ".claude/scripts",
        "unreferenced_reason": "red case"})
    if widen:
        data["allowed_destinations"].append(".claude/scripts")
    return data


def test_red_an_installed_gate_is_refused(tmp_path: Path) -> None:
    """An installed gate would be the route agents choose (7/7 at ca3030d), and
    unwitnessed here: refused by destination, and - with the destination
    widened too - as an unwitnessed gate copy."""
    assert "destination-outside-allowed" in _diagnose(_with_installed_gate(widen=False), tmp_path)
    assert _diagnose(_with_installed_gate(widen=True), tmp_path) == ["gate-copy-unwitnessed"]


def test_red_the_checkout_copy_left_undeclared_is_unwitnessed(tmp_path: Path) -> None:
    """D1: the fallback's checkout copy is installed, so it must be witnessed."""
    data = _json(SUBJECT_DIR / "profile.json")
    del data["checkout_gate_entrypoints"]
    assert _diagnose(data, tmp_path) == ["gate-copy-unwitnessed"]


@pytest.mark.parametrize("checkout,match", [
    ({CHECKOUT: "flow-auto"}, "not a selected skill"),
    ({BUNDLED: "flow-check"}, "declared twice"),
    ({"Projects/claude-power-pack/scripts/other.sh": "flow-check"}, "not a copy of the declared gate_entrypoint"),
])
def test_red_a_malformed_checkout_declaration_is_refused(tmp_path: Path, checkout: dict[str, str],
                                                         match: str) -> None:
    data = _json(SUBJECT_DIR / "profile.json")
    data["checkout_gate_entrypoints"] = checkout
    with pytest.raises(p.Refused, match=match):
        _diagnose(data, tmp_path)


def test_red_the_checkout_copy_can_never_be_the_entrypoint(tmp_path: Path) -> None:
    data = _json(SUBJECT_DIR / "profile.json")
    data["gate_entrypoint"] = CHECKOUT
    data["bundled_gate_entrypoints"] = [BUNDLED]
    with pytest.raises(p.Refused, match="never a checkout copy"):
        _diagnose(data, tmp_path)


def test_a_declared_checkout_copy_that_is_not_installed_is_a_problem() -> None:
    problems = p.bundled_gate_problems({BUNDLED: b"x"}, BUNDLED, (BUNDLED,), {}, manifest_name="SHA256SUMS",
                                       require_consumers_installed=False, checkout={CHECKOUT: "flow-check"})
    assert ("checkout-gate-not-installed", CHECKOUT) in [(c, path) for c, _m, path in problems]


# --- the runtime ----------------------------------------------------------------------

def _closure_facts() -> tuple[dict[str, str], list[dict[str, Any]]]:
    inventory = _json(SUBJECT_DIR / "evidence" / "inventory.json")
    files = {f["destination"]: f["digest"] for group in (inventory["skills"], inventory["dependencies"])
             for entry in group for f in entry.get("files") or []}
    tools = [dep for dep in inventory["dependencies"] if dep["kind"] == "tool"]
    return files, tools


def test_the_closure_selects_this_pins_runtime() -> None:
    files, tools = _closure_facts()
    [policy] = [x for x in rs.profile_policies() if x["runtime_id"] == RUNTIME_ID]
    assert (policy["subject_revision"], policy["gate_entrypoint"]) == (PIN, BUNDLED)
    assert rs.selected_runtime(locator="github.com/cooneycw/claude-power-pack", revision=PIN,
                               gate_entrypoint=BUNDLED, files=files, tools=tools) == rs.PROFILE_RUNTIME
    assert (SNAPSHOT / "uv.lock").read_bytes() != (ROOT / "tests" / "fixtures" / "profile-cpp-codex-flow-auto-ca3030d"
                                                   / "uv.lock").read_bytes()  # why it is not shared


def test_red_changed_runtime_metadata_is_refused() -> None:
    files, tools = _closure_facts()
    changed = copy.deepcopy(files)
    changed["Projects/claude-power-pack/uv.lock"] = "sha256:" + "0" * 64
    with pytest.raises(rs.Refused, match="metadata changed"):
        rs.selected_runtime(locator="github.com/cooneycw/claude-power-pack", revision=PIN,
                            gate_entrypoint=BUNDLED, files=changed, tools=tools)


def test_both_runtime_policy_copies_are_identical() -> None:
    assert ((ROOT / "skillc" / "runtime-policy-extra.json").read_bytes()
            == (ROOT / "docker" / "profile-trial" / "runtime-policy-extra.json").read_bytes())


# --- the delivered home (treatment assembly) ------------------------------------------

def _delivered() -> dict[str, bytes]:
    """The closure as a treatment delivers it: destination -> snapshot bytes."""
    inventory = _json(SUBJECT_DIR / "evidence" / "inventory.json")
    return {f["destination"]: (SNAPSHOT / f["source"]).read_bytes()
            for group in (inventory["skills"], inventory["dependencies"]) for entry in group
            for f in entry.get("files") or [] if f.get("source") and f.get("origin") != "synthetic"}


def _assembly_problems(files: dict[str, bytes]) -> list[tuple[str, str]]:
    prof = p.Profile.load(SUBJECT_DIR / "profile.json")
    return [(c, path) for c, _m, path in p.bundled_gate_problems(
        files, prof.gate_entrypoint, prof.bundled_gate_entrypoints, prof.checksum_consumers,
        manifest_name=prof.bundled_checksum_manifest, require_consumers_installed=True,
        checkout=prof.checkout_gate_entrypoints)]


def test_the_targeted_delivery_has_every_gate_copy_witnessed() -> None:
    assert _json(SUBJECT_DIR / "subject.json")["select"] == ["flow-check"]
    assert _assembly_problems(_delivered()) == []


def test_red_a_delivered_neighbour_skills_gate_is_refused() -> None:
    """Why the subject selects flow-check alone: at this pin every generated
    skill runs its own bundled gate, so a delivered neighbour (here flow-auto,
    as `select: all` would deliver it) is a gate route nobody witnesses."""
    files = _delivered()
    neighbour = ".codex/skills/flow-auto/scripts/flow-finish-gate.sh"
    files[neighbour] = files[BUNDLED]
    files[".codex/skills/flow-auto/reference.md"] = b"```bash\nscripts/flow-finish-gate.sh\n```\n"
    assert ("gate-copy-unwitnessed", neighbour) in _assembly_problems(files)


# --- counter-model review reds (Codex, #529) ------------------------------------------

@pytest.mark.parametrize("skill", ["../../../../home/candidate/redirect", "..", ".hidden", "a/b", ""])
def test_review_an_unsafe_checkout_skill_name_is_refused(tmp_path: Path, skill: str) -> None:
    """HIGH: the skill names the root-owned mirror directory, so it must be a
    single safe path component - never a traversal into the candidate's home."""
    data = _json(SUBJECT_DIR / "profile.json")
    data["checkout_gate_entrypoints"] = {CHECKOUT: skill}
    with pytest.raises(p.Refused):
        _diagnose(data, tmp_path)


def test_review_a_checkout_copy_needs_an_explicit_select(tmp_path: Path) -> None:
    """HIGH (Codex): under `select: all` the skill name went unchecked, so a
    traversal value reached the root-owned mirror path. The real red for it,
    with the controller guard; the parametrized case above is caught by
    membership in this profile's explicit select."""
    data = _json(SUBJECT_DIR / "profile.json")
    data["select"] = "all"
    with pytest.raises(p.Refused, match="explicit select"):
        _diagnose(data, tmp_path)


def test_review_one_checkout_copy_per_skill(tmp_path: Path) -> None:
    """MEDIUM: two copies on one `checkout:<skill>` route would share a variant
    and a mirror, so one would run while both read witnessed."""
    data = _json(SUBJECT_DIR / "profile.json")
    data["checkout_gate_entrypoints"] = {CHECKOUT: "flow-check",
                                         "Projects/other-checkout/scripts/flow-finish-gate.sh": "flow-check"}
    with pytest.raises(p.Refused, match="one checkout copy per skill"):
        _diagnose(data, tmp_path)


def test_review_a_skill_copy_relabelled_checkout_is_refused_and_consumers_still_scanned() -> None:
    """MEDIUM: the label must not decide the coverage. A copy beside the
    skill's own manifest is a bundled copy; and with ANY mirrored copy the
    checksum-consumer preflight runs."""
    files = {BUNDLED: b"#!/usr/bin/env bash\n", ".codex/skills/flow-check/scripts/SHA256SUMS": b"",
             ".codex/skills/flow-check/scripts/verify.sh": b"sha256sum -c SHA256SUMS\n"}
    problems = [(c, path) for c, _m, path in p.bundled_gate_problems(
        files, CHECKOUT, (), {}, manifest_name="SHA256SUMS", require_consumers_installed=False,
        checkout={BUNDLED: "flow-check"})]
    assert ("checkout-gate-in-skill", BUNDLED) in problems
    assert ("checksum-consumer-undeclared", ".codex/skills/flow-check/scripts/verify.sh") in problems


def test_review_a_checkout_only_inventory_keeps_its_checksum_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    """MEDIUM (Codex re-review): the consumers and the manifest name ride the
    inventory with ANY mirrored copy, so a treatment rebuilt from it keeps the
    delivery-time consumer scan - an undeclared `load_manifest("SHA256SUMS")`
    reader is still caught."""
    import dataclasses
    prof = dataclasses.replace(p.Profile.load(SUBJECT_DIR / "profile.json"), bundled_gate_entrypoints=())
    # This snapshot's bundled copy is bare-called, so no checkout-only variant
    # of it validates; the copy checks are stubbed to reach the serializer.
    monkeypatch.setattr(p, "bundled_gate_problems", lambda *_a, **_k: [])
    inventory = p.validate(prof, p.load_tree(prof, None, SNAPSHOT))
    assert "bundled_gate_entrypoints" not in inventory
    assert inventory["bundled_checksum_manifest"] == "SHA256SUMS" and inventory["checksum_consumers"] == []
    files = {CHECKOUT: b"#!/usr/bin/env bash\n", "Projects/x/reader.py": b'load_manifest("SHA256SUMS")\n'}
    monkeypatch.undo()
    problems = p.bundled_gate_problems(files, BUNDLED, (), {}, manifest_name=inventory["bundled_checksum_manifest"],
                                       require_consumers_installed=True, checkout=prof.checkout_gate_entrypoints)
    assert ("checksum-consumer-undeclared", "Projects/x/reader.py") in [(c, path) for c, _m, path in problems]
