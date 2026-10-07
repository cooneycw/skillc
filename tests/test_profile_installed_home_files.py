"""Tests for `skillc.profile.installed_home_files` (skillc#334): the
in-memory `{destination: bytes}` form of `install()`'s own validated
population, for delivery into a live container's HOME directory - which
`install()`'s host-filesystem `home: Path` argument structurally cannot
reach (`lifecycle.run_through_backend`'s `install(handle, surface)` step
only ever reaches `CONTAINER_WORKSPACE`; home is reached through its
`before_execute` hook instead).

The real ea6dbfa-pin fixture (`tests/fixtures/profile-cpp-codex-flow-check-
ea6dbfa/`) is used rather than a synthetic one, so this exercises the exact
closure skillc#334 must deliver - not a stand-in shaped to make the test
pass.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from skillc import profile as p

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = Path(__file__).resolve().parent / "fixtures" / "profile-cpp-codex-flow-check-ea6dbfa"
DECLARATION = ROOT / "evals" / "subjects" / "cpp-codex-flow-check-ea6dbfa" / "profile.json"


def _inventory_and_tree() -> tuple[dict[str, Any], p.DirTree]:
    prof = p.Profile.load(DECLARATION)
    tree = p.DirTree(SNAPSHOT)
    return p.validate(prof, tree), tree


def test_every_file_is_digest_verified_against_the_real_pin_fixture() -> None:
    inventory, tree = _inventory_and_tree()
    files = p.installed_home_files(inventory, tree)
    assert len(files) > 0
    records_by_destination = {r["destination"]: r for group in ("skills", "dependencies")
                              for entry in inventory[group] for r in entry["files"]}
    assert set(files) == set(records_by_destination)
    for destination, data in files.items():
        expected_digest = records_by_destination[destination]["digest"]
        assert f"sha256:{hashlib.sha256(data).hexdigest()}" == expected_digest, destination


def test_the_checkout_detection_marker_and_the_real_gate_script_are_both_present() -> None:
    """The #303/#308 synthetic marker and the real helper script this
    issue exists to deliver - both must come through this function,
    since both are declared dependencies of the same inventory."""
    inventory, tree = _inventory_and_tree()
    files = p.installed_home_files(inventory, tree)
    assert files["Projects/claude-power-pack/CLAUDE.md"] == (
        b"# Synthetic checkout marker only - not agent instructions.\n# See skillc#303.\n"
    )
    assert b"lib.cicd run --plan" in files[".claude/scripts/flow-finish-gate.sh"]


def test_install_and_installed_home_files_agree_on_every_byte(tmp_path: Path) -> None:
    """The host-install path (`install()`) and the in-memory path
    (`installed_home_files()`) share `_verified_file_records` - prove they
    produce IDENTICAL bytes for every destination, not just that each
    passes its own checks independently."""
    inventory, tree = _inventory_and_tree()
    mapping = p.installed_home_files(inventory, tree)
    home = tmp_path / "home"
    home.mkdir()
    p.install(inventory, tree, home)
    for destination, data in mapping.items():
        assert (home / destination).read_bytes() == data, destination


def test_red_case_a_tampered_source_is_refused_not_silently_delivered() -> None:
    """Mutation check: corrupt one source file after validation, before
    `installed_home_files` reads it - the digest check inherited from
    `install()`'s own preflight must still fire for the in-memory path."""
    inventory, tree = _inventory_and_tree()
    target = SNAPSHOT / "codex" / "skills" / "flow-check" / "scripts" / "gate-lib.sh"
    original = target.read_bytes()
    try:
        target.write_bytes(original + b"\n# tampered\n")
        with pytest.raises(p.Refused, match="source digest changed"):
            p.installed_home_files(inventory, tree)
    finally:
        target.write_bytes(original)


# ------------------------------------------------------------- inventory_digest


def test_inventory_digest_is_stable_and_content_sensitive() -> None:
    inventory, _tree = _inventory_and_tree()
    first = p.inventory_digest(inventory)
    second = p.inventory_digest(dict(inventory))  # a different dict object, same content
    assert first == second
    mutated = {**inventory, "selection": [*inventory["selection"], "an-extra-entry"]}
    assert p.inventory_digest(mutated) != first


def test_inventory_digest_matches_the_committed_evidence_file() -> None:
    """The committed `evidence/inventory.json` (#330) was generated against
    a real git checkout at the pinned revision - its digest is the value
    skillc#334's approval binding checks against, read directly, never
    recomputed against this file's own DirTree fixture (which reports
    source_kind='snapshot', not 'git', and would disagree on exactly those
    two fields even when every file's content is identical)."""
    committed = json.loads((ROOT / "evals" / "subjects" / "cpp-codex-flow-check-ea6dbfa"
                            / "evidence" / "inventory.json").read_text(encoding="utf-8"))
    assert p.inventory_digest(committed) == "sha256:43d4cf5683130cbe599a4b8c0fbfb12ae392216d8b595843a9a404bf88d5cc8e"


def test_red_case_a_duplicate_destination_across_entries_is_refused() -> None:
    """If two dependency entries ever declared the same destination (a
    schema/authoring error `_install_records` sorts but does not itself
    dedupe), `installed_home_files` must refuse rather than silently keep
    only the last one seen - a host install would at least leave a file on
    disk to inspect; an in-memory dict would not even leave that trace."""
    inventory, tree = _inventory_and_tree()
    first_dep = inventory["dependencies"][0]
    duplicate_entry = {**first_dep, "id": f"{first_dep['id']}-duplicate"}
    inventory = {**inventory, "dependencies": [*inventory["dependencies"], duplicate_entry]}
    with pytest.raises(p.Refused, match="duplicate destination"):
        p.installed_home_files(inventory, tree)
