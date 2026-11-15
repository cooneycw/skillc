"""The plain-English gauntlet report (#783) and the machine lines it must not change.

Owner, 2026-11-15: "Output is engine-speak." `gauntlet run` now leads with a
report a person reads - for each round reached, what was Checked, what was
Found, what it Means, and the one thing to Do next - then prints the machine
lines (ROUND / RECORD / NEXT / GAUNTLET) BYTE-IDENTICAL to before, because
tests and `gauntlet verdict` read them.

Every fixture stop has two goldens in tests/fixtures/gauntlet-report/:
`<case>.machine.txt`, captured from the engine BEFORE #783 (f29e3a3), and
`<case>.plain.txt`, the report the owner reads. Set GAUNTLET_REPORT_CAPTURE=1
to rewrite them; the machine goldens must never need it.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from skillc import gauntlet

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "evals" / "subjects" / "gauntlet"
GOLDEN = ROOT / "tests" / "fixtures" / "gauntlet-report"
CAPTURE = os.environ.get("GAUNTLET_REPORT_CAPTURE") == "1"
MACHINE_PREFIXES = ("GAUNTLET ", "ROUND ", "RECORD: ", "NEXT: ", "GAUNTLET: ", "  ")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _collection(tmp_path: Path) -> Path:
    root = tmp_path / "coll"
    shutil.copytree(FIXTURES / "collection", root)
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "fixture")
    return root


def _edit(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    assert old in text, (path, old)
    path.write_text(text.replace(old, new, 1))


UNBACKED = """owner: owner
invariants:
  always: []
  never:
    - id: alpha.never-guess
      test: checks/alpha-never-guess/{bad,good}
    - id: alpha.never-push
      test: checks/alpha-never-push/{bad,good}
"""


def _charter(coll: Path) -> Path:
    return coll / "skills" / "alpha" / "CHARTER.md"


#: Each fixture stop the owner can reach: the skill, the change that reaches
#: it, and the run's settings.
CASES: dict[str, tuple[str, Callable[[Path], None], dict[str, object]]] = {
    "no-charter": ("skills/beta", lambda c: None, {}),
    "draft-unbacked": ("skills/alpha", lambda c: _edit(_charter(c), "owner: owner\n", UNBACKED), {}),
    "contract-bad": ("skills/alpha", lambda c: _edit(_charter(c), "owner: owner\n", "owner: owner\nnot_a_field: 1\n"),
                     {}),
    "unapproved": ("skills/alpha", lambda c: _edit(_charter(c), "  approved: 2026-11-15\n", ""), {}),
    "inspect-errors": ("skills/alpha", lambda c: _edit(c / "skills" / "alpha" / "SKILL.md", "\n",
                                                       "\nRun `scripts/deleted-helper.sh` first.\n"), {}),
    "inspect-unknown": ("skills/alpha", lambda c: None, {"issue_states": None, "offline": True}),
    "findings-round3": ("skills/alpha", lambda c: None, {}),
}


def _run(tmp_path: Path, case: str, mode: str | None = None) -> tuple[int, list[str], Path]:
    skill, change, extra = CASES[case]
    coll = _collection(tmp_path)
    change(coll)
    settings: dict[str, object] = {"issue_states": coll / "issue-states.json", "repo": "example/gauntlet",
                                   "usage": [FIXTURES / "usage"]}
    settings.update(extra)
    if mode is not None:
        settings["output"] = mode
    lines: list[str] = []
    code = gauntlet.run(coll, skill, gauntlet.Options(**settings), out=lines.append)  # type: ignore[arg-type]
    return code, lines, coll


def _normal(lines: list[str], coll: Path) -> str:
    text = "\n".join(lines) + "\n"
    return text.replace(str(coll), "<COLL>")


def _golden(name: str, text: str) -> str:
    path = GOLDEN / name
    if CAPTURE:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return path.read_text()


def _machine(lines: list[str]) -> list[str]:
    """The machine part: from the GAUNTLET header line to the end."""
    start = next(i for i, line in enumerate(lines) if line.startswith("GAUNTLET ") and not line.startswith("GAUNTLET:"))
    return lines[start:]


@pytest.mark.parametrize("case", sorted(CASES))
def test_the_machine_lines_are_byte_identical_to_before(tmp_path: Path, case: str) -> None:
    """Captured from f29e3a3's engine, before #783: tests and `gauntlet
    verdict` read these lines, so the plain report must never change them."""
    _code, lines, coll = _run(tmp_path, case)
    assert _normal(_machine(lines), coll) == _golden(f"{case}.machine.txt", _normal(_machine(lines), coll))
