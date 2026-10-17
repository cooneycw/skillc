"""Each committed CPP pin fixture (`ea6dbfa`, and `86641e8` since #376) holds
every file its pin's own inventory names, byte for byte (issue #356), and the
`.gitignore` exception that made that possible stays narrow.

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

Red cases: on `origin/main` 450445d (before #356) the first test fails naming
`lib/security/modules/secrets.py` as missing; and the #376 control below puts
the `ea6dbfa` bytes of `lib/cicd/runner.py` into a copy of the `86641e8`
snapshot, which the same check must name as differing from the pin.

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
PINS = ("ea6dbfa", "86641e8")


def _snapshot(pin: str) -> Path:
    return ROOT / "tests" / "fixtures" / f"profile-cpp-codex-flow-check-{pin}"


def _evidence(pin: str) -> Path:
    return ROOT / "evals" / "subjects" / f"cpp-codex-flow-check-{pin}" / "evidence" / "inventory.json"


needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def _pinned_file_records(pin: str) -> list[dict[str, Any]]:
    """Every file record the evidence inventory derived from the real pin."""
    inventory = json.loads(_evidence(pin).read_text(encoding="utf-8"))
    return [record for group in ("skills", "dependencies")
            for entry in inventory[group] for record in entry["files"]
            if record["origin"] == "pinned"]


def _compare(snapshot: Path, records: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    missing: list[str] = []
    wrong: list[str] = []
    for record in records:
        path = snapshot / record["source"]
        if not path.is_file():
            missing.append(record["source"])
            continue
        if f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}" != record["digest"]:
            wrong.append(record["source"])
    return missing, wrong


@pytest.mark.parametrize("pin", PINS)
def test_the_fixture_holds_every_pinned_file_the_evidence_inventory_names(pin: str) -> None:
    records = _pinned_file_records(pin)
    # A broken extractor would report nothing missing from nothing read.
    assert len(records) > 50, f"evidence inventory yielded only {len(records)} pinned file records"
    missing, wrong = _compare(_snapshot(pin), records)
    assert not missing, f"fixture is missing pinned files (a .gitignore rule may have swallowed them): {missing}"
    assert not wrong, f"fixture files differ from the pin: {wrong}"


def test_red_case_old_pin_bytes_in_the_new_snapshot_are_named(tmp_path: Path) -> None:
    """#376: a snapshot with the right paths and an older pin's bytes must fail."""
    copy = tmp_path / "snapshot"
    shutil.copytree(_snapshot("86641e8"), copy)
    stale = "lib/cicd/runner.py"
    old = (_snapshot("ea6dbfa") / stale).read_bytes()
    assert old != (copy / stale).read_bytes(), "the control needs a file that differs between the pins"
    (copy / stale).write_bytes(old)

    missing, wrong = _compare(copy, _pinned_file_records("86641e8"))
    assert missing == []
    assert wrong == [stale]


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
@pytest.mark.parametrize("pin", PINS)
def test_the_vendored_scanner_module_is_not_ignored(pin: str) -> None:
    relative = f"tests/fixtures/profile-cpp-codex-flow-check-{pin}/lib/security/modules/secrets.py"
    assert not _ignored(relative)
