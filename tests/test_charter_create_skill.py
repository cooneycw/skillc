"""The `/charter-create` dialogue skill (#778 PR B): its size, the rules that
keep it from answering for the owner, and its launcher."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / ".claude" / "skills" / "charter-create"
SKILL_MD = SKILL / "SKILL.md"
LAUNCHER = SKILL / "scripts" / "charter.sh"
#: The dialogue's size limit. It may be LOWERED; raising it is the change this
#: test exists to make visible (#718 never raises a word budget).
WORD_BUDGET = 600


def _body_words(text: str) -> int:
    return len(text.split("---", 2)[2].split())


def test_the_skill_stays_inside_its_word_budget() -> None:
    assert _body_words(SKILL_MD.read_text(encoding="utf-8")) <= WORD_BUDGET


def test_the_word_budget_fails_one_word_over() -> None:
    assert _body_words("---\nname: x\n---\n" + "word " * (WORD_BUDGET + 1)) > WORD_BUDGET


@pytest.mark.parametrize("rule", [
    "You never answer for the\nowner",
    "Never answer, approve or pick for the owner",
    "Never set `approve` or `approved_on` without the owner's explicit yes.",
    "No\n  shortcut, no rule",
    "Never commit, stage or push the charter or the stubs",
    "A `not examined` source was not\nread",
    "One suggestion per question.",
])
def test_the_skill_keeps_its_owner_rules(rule: str) -> None:
    assert rule in SKILL_MD.read_text(encoding="utf-8")


def test_the_skill_names_the_engine_steps_it_runs() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    assert "charter.sh evidence" in text and "charter.sh create" in text


def test_the_launcher_runs_this_checkouts_charter_commands() -> None:
    done = subprocess.run([str(LAUNCHER), "create", "--help"], capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0 and "--answers" in done.stdout


def test_the_launcher_refuses_any_other_command() -> None:
    done = subprocess.run([str(LAUNCHER), "draft", "x"], capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 2 and "CHARTER_CREATE: usage" in done.stderr


def test_the_launcher_outside_a_checkout_refuses_with_its_one_line(tmp_path: Path) -> None:
    copy = tmp_path / "charter.sh"
    shutil.copy(LAUNCHER, copy)
    os.chmod(copy, 0o755)
    done = subprocess.run([str(copy), "evidence"], capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 2
    assert done.stderr.startswith("CHARTER_CREATE: cannot find a usable skillc (")
