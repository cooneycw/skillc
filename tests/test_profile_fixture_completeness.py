"""The committed ea6dbfa fixture holds every file the pin's own inventory
names, byte for byte (issue #356), and the `.gitignore` exception that made
that possible stays narrow.

`tests/fixtures/profile-cpp-codex-flow-check-ea6dbfa/` is a vendored copy of
CPP at `ea6dbfa`. Its `lib/security/modules/secrets.py` - CPP's secrets
SCANNER, a source module - was never committed: this repository's
`secrets.*` ignore rule matched it and `git add` skipped it without a word.
Every host-side test that reads the fixture through `DirTree` sees only what
is present, so nothing noticed until the cold-container live test imported
`lib.security` and failed on the missing module.

The committed evidence inventory (`evals/subjects/cpp-codex-flow-check-
ea6dbfa/evidence/inventory.json`) was computed against a REAL git checkout
at the pin, not against this fixture, so it is an independent list of what
the fixture must contain. Checking the fixture against it needs no git and
no Docker, so it runs in CI - the place the original loss went unseen.

Red case: on `origin/main` 450445d (before #356) the first test fails naming
`lib/security/modules/secrets.py` as missing.

The second test is the negative control for the narrowed ignore rule: the
`!tests/fixtures/**/secrets.py` exception must re-include ONLY a Python
module inside a fixture, and `secrets.*` must still ignore secret-bearing
files everywhere else. It needs git (`git check-ignore`), which skillc's CI
image does not have, so it runs on hosts - including the local `make verify`.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "tests" / "fixtures" / "profile-cpp-codex-flow-check-ea6dbfa"
EVIDENCE = ROOT / "evals" / "subjects" / "cpp-codex-flow-check-ea6dbfa" / "evidence" / "inventory.json"

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def _pinned_file_records() -> list[dict[str, Any]]:
    """Every file record the evidence inventory derived from the real pin."""
    inventory = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    return [record for group in ("skills", "dependencies")
            for entry in inventory[group] for record in entry["files"]
            if record["origin"] == "pinned"]


def test_the_fixture_holds_every_pinned_file_the_evidence_inventory_names() -> None:
    records = _pinned_file_records()
    # A broken extractor would report nothing missing from nothing read.
    assert len(records) > 50, f"evidence inventory yielded only {len(records)} pinned file records"
    missing: list[str] = []
    wrong: list[str] = []
    for record in records:
        path = SNAPSHOT / record["source"]
        if not path.is_file():
            missing.append(record["source"])
            continue
        if f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}" != record["digest"]:
            wrong.append(record["source"])
    assert not missing, f"fixture is missing pinned files (a .gitignore rule may have swallowed them): {missing}"
    assert not wrong, f"fixture files differ from the pin: {wrong}"


def _ignored(relative: str) -> bool:
    """Whether this repository's ignore rules exclude `relative` (no index:
    the answer is about the RULES, not whether the path is already tracked)."""
    result = subprocess.run(
        ["git", "-C", str(ROOT), "check-ignore", "-q", "--no-index", relative],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode in (0, 1), f"git check-ignore failed: {result.stderr}"
    return result.returncode == 0


@needs_git
@pytest.mark.parametrize("relative", [
    "secrets.py",
    "secrets.json",
    "secrets.yaml",
    "lib/security/modules/secrets.py",
    "tests/fixtures/any-fixture/secrets.json",
    "tests/fixtures/any-fixture/config/secrets.yaml",
    "tests/fixtures/any-fixture/secrets.env",
])
def test_secret_bearing_files_are_still_ignored(relative: str) -> None:
    assert _ignored(relative), f"{relative} is no longer ignored - the #356 exception is wider than intended"


@needs_git
def test_the_vendored_scanner_module_is_not_ignored() -> None:
    relative = "tests/fixtures/profile-cpp-codex-flow-check-ea6dbfa/lib/security/modules/secrets.py"
    assert not _ignored(relative)
