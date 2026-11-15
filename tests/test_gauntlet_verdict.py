"""Skill-gauntlet round 5, the verdict (#737): `skillc gauntlet verdict` and `rule`.

The record each case reads is written by the REAL engine (`gauntlet run`) on a
fresh copy of the fixture collection, and round 2's findings come from a REAL
`inspect --json` run. Only round 3/4 and the overlap are planted, in the shapes
#736 and #726 part B document, because neither emits JSON on main yet. Every
control is paired with the input that flips it.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from skillc import gauntlet, gauntlet_verdict

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "evals" / "subjects" / "gauntlet-verdict"
REPORTS = FIX / "reports"
PASSAGE = "You MUST also restate every rule twice for emphasis, even though saying it once is enough."


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def coll(tmp_path: Path) -> Path:
    root = tmp_path / "coll"
    shutil.copytree(FIX / "collection", root)
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "fixture")
    return root


def _engine(coll: Path, skill: str, usage: bool = True) -> None:
    options = gauntlet.Options(offline=True, usage=[FIX / "usage"] if usage else [])
    gauntlet.run(coll, f"skills/{skill}", options, out=lambda _: None)


def _inspect(coll: Path, tmp_path: Path) -> Path:
    out = tmp_path / "inspect.json"
    done = subprocess.run(["python", "-m", "skillc.cli", "inspect", str(coll), "--offline", "--json"],
                          capture_output=True, text=True, check=False, cwd=ROOT)
    out.write_text(done.stdout)
    return out


def _verdict(coll: Path, skill: str, tmp_path: Path, **files: Any) -> tuple[int, list[str]]:
    defaults = {"round3": REPORTS / "round3-complete.json", "round4": REPORTS / "round4-keep.json",
                "declaration": REPORTS / "declaration-keep.json", "inspect": _inspect(coll, tmp_path),
                "overlap": REPORTS / "overlap-none.json"}
    defaults.update(files)
    lines: list[str] = []
    code = gauntlet_verdict.verdict(coll, f"skills/{skill}", gauntlet.Options(), out=lines.append, **defaults)
    return code, "\n".join(lines).splitlines()


def _verdict_line(lines: list[str]) -> str:
    found = [line for line in lines if line.startswith("ROUND 5 verdict:")]
    assert len(found) == 1, lines
    return found[0]


def _draft(coll: Path, skill: str) -> Path:
    return coll / ".skillc" / "gauntlet" / f"skills__{skill}"


def _skill_digest(coll: Path, skill: str) -> str:
    """The skill under review and its CHARTER.md: the record is the only file
    the gauntlet may write beside them, so it is left out."""
    folder = coll / "skills" / skill
    rows = sorted((p.name, hashlib.sha256(p.read_bytes()).hexdigest()) for p in folder.iterdir()
                  if p.is_file() and p.name != gauntlet.RECORD_NAME)
    return json.dumps(rows)


# ------------------------------------------------------------- the four controls

def test_a_lean_skill_reads_keep(coll: Path, tmp_path: Path) -> None:
    """The charter's guard test: keep, not trim just to have done something."""
    _engine(coll, "lean")
    code, lines = _verdict(coll, "lean", tmp_path)
    assert _verdict_line(lines).startswith("ROUND 5 verdict: KEEP") and code == gauntlet_verdict.EXIT_PROPOSED
    assert not (_draft(coll, "lean") / gauntlet_verdict.PATCH_FILE).exists()


def test_a_removable_passage_reads_trim_and_its_diff_removes_it(coll: Path, tmp_path: Path) -> None:
    _engine(coll, "trimmable")
    code, lines = _verdict(coll, "trimmable", tmp_path, round4=REPORTS / "round4-trim.json",
                           declaration=REPORTS / "declaration-trim.json")
    assert _verdict_line(lines).startswith("ROUND 5 verdict: TRIM") and code == gauntlet_verdict.EXIT_PROPOSED
    patch = (_draft(coll, "trimmable") / gauntlet_verdict.PATCH_FILE).read_text()
    removed = "".join(line[1:] for line in patch.splitlines() if line.startswith("-") and not line.startswith("---"))
    added = "".join(line[1:] for line in patch.splitlines() if line.startswith("+") and not line.startswith("+++"))
    assert PASSAGE in removed and PASSAGE not in added and len(added) < len(removed)
    assert any(line.startswith("  clause report: intact 4/4 -> lean-1 4/4") for line in lines)


def test_a_skill_whose_duty_another_charter_owns_reads_retire_naming_the_owner(coll: Path, tmp_path: Path) -> None:
    _engine(coll, "shadowed")
    code, lines = _verdict(coll, "shadowed", tmp_path, overlap=REPORTS / "overlap-retire.json")
    assert _verdict_line(lines).startswith("ROUND 5 verdict: RETIRE") and "reporter" in _verdict_line(lines)
    assert "  retire: duty shadowed.report is owned by reporter" in lines and code == gauntlet_verdict.EXIT_PROPOSED


def test_an_unknown_round_reads_unknown_and_next_names_it(coll: Path, tmp_path: Path) -> None:
    _engine(coll, "lean", usage=False)  # round 0 reads UNKNOWN: no usage log
    code, lines = _verdict(coll, "lean", tmp_path)
    assert _verdict_line(lines).startswith("ROUND 5 verdict: UNKNOWN - round 0 did not decide")
    assert [line for line in lines if line.startswith("NEXT:")] == [
        next(line for line in lines if line.startswith("NEXT:"))] and "round 0" in next(
        line for line in lines if line.startswith("NEXT:"))
    assert code == gauntlet_verdict.EXIT_UNKNOWN


@pytest.mark.parametrize("case", ["keep", "trim", "retire", "unknown"])
def test_every_case_prints_one_verdict_line_and_one_next_line(coll: Path, tmp_path: Path, case: str) -> None:
    skill = {"keep": "lean", "trim": "trimmable", "retire": "shadowed", "unknown": "lean"}[case]
    _engine(coll, skill, usage=case != "unknown")
    files: dict[str, Path] = {"trim": {"round4": REPORTS / "round4-trim.json",
                                        "declaration": REPORTS / "declaration-trim.json"},
                              "retire": {"overlap": REPORTS / "overlap-retire.json"}}.get(case, {})
    _, lines = _verdict(coll, skill, tmp_path, **files)
    assert sum(line.startswith("ROUND 5 verdict:") for line in lines) == 1
    assert sum(line.startswith("NEXT:") for line in lines) == 1


# ------------------------------------------------------- UNKNOWN, never keep

@pytest.mark.parametrize("missing,round_name", [
    ({"overlap": None}, "round 1 overlap"), ({"overlap": REPORTS / "overlap-not-examined.json"}, "round 1 overlap"),
    ({"round3": None}, "round 3"), ({"round3": REPORTS / "round3-unknown.json"}, "round 3"),
    ({"round4": None}, "round 4"), ({"inspect": None}, "round 2")])
def test_an_absent_or_undecided_input_is_unknown_never_keep(coll: Path, tmp_path: Path, missing: dict[str, Any],
                                                             round_name: str) -> None:
    _engine(coll, "lean")
    code, lines = _verdict(coll, "lean", tmp_path, **missing)
    assert _verdict_line(lines).startswith(f"ROUND 5 verdict: UNKNOWN - {round_name} did not decide"), lines
    assert code == gauntlet_verdict.EXIT_UNKNOWN


@pytest.mark.parametrize("times", [0, 2])
def test_a_trim_passage_that_does_not_occur_exactly_once_is_unknown(coll: Path, tmp_path: Path, times: int) -> None:
    skill_md = coll / "skills" / "trimmable" / "SKILL.md"
    text = skill_md.read_text()
    skill_md.write_text(text.replace(PASSAGE, "") if times == 0 else text + "\n" + PASSAGE + "\n")
    _engine(coll, "trimmable")
    code, lines = _verdict(coll, "trimmable", tmp_path, round4=REPORTS / "round4-trim.json",
                           declaration=REPORTS / "declaration-trim.json")
    assert f"occurs {times} times" in _verdict_line(lines) and code == gauntlet_verdict.EXIT_UNKNOWN


def test_a_report_and_declaration_that_disagree_on_the_passage_is_unknown(coll: Path, tmp_path: Path) -> None:
    _engine(coll, "trimmable")
    other = tmp_path / "declaration-other.json"
    other.write_text(json.dumps({"variants": [{"arm": "lean-1", "file": "SKILL.md", "remove": "something else",
                                               "clause": "x"}]}))
    _, lines = _verdict(coll, "trimmable", tmp_path, round4=REPORTS / "round4-trim.json", declaration=other)
    assert "the declaration says" in _verdict_line(lines)


def test_class_b_findings_become_proposed_checks_and_keep_their_prose(coll: Path, tmp_path: Path) -> None:
    _engine(coll, "lean")
    planted = tmp_path / "inspect-b.json"
    planted.write_text(json.dumps({"findings": [{"bucket": "B", "path": "skills/lean/SKILL.md", "line": 5,
                                                 "rule": "x", "detail": "names tests/test_missing.py"}]}))
    _, lines = _verdict(coll, "lean", tmp_path, inspect=planted)
    assert any(line.startswith("  round 2 B -> proposed check") and "prose kept" in line for line in lines)


# ------------------------------------------------------- never writes the skill

@pytest.mark.parametrize("case", ["keep", "trim", "retire"])
def test_verdict_and_rule_never_write_the_skill_or_its_charter(coll: Path, tmp_path: Path, case: str) -> None:
    skill = {"keep": "lean", "trim": "trimmable", "retire": "shadowed"}[case]
    _engine(coll, skill)
    before = _skill_digest(coll, skill)
    files: dict[str, Path] = {"trim": {"round4": REPORTS / "round4-trim.json",
                                        "declaration": REPORTS / "declaration-trim.json"},
                              "retire": {"overlap": REPORTS / "overlap-retire.json"}}.get(case, {})
    _, lines = _verdict(coll, skill, tmp_path, **files)
    digest = re.search(r"VERDICT_DIGEST: (\S+)", "\n".join(lines))
    assert digest is not None
    gauntlet_verdict.rule(coll, f"skills/{skill}", gauntlet.Options(), "accept", digest.group(1), "2026-11-15", None,
                          out=lambda _: None)
    assert _skill_digest(coll, skill) == before


def test_a_verdict_rerun_leaves_the_record_byte_identical(coll: Path, tmp_path: Path) -> None:
    _engine(coll, "lean")
    record = coll / "skills" / "lean" / gauntlet.RECORD_NAME
    before = record.read_bytes()
    _verdict(coll, "lean", tmp_path)
    _verdict(coll, "lean", tmp_path)
    assert record.read_bytes() == before


def test_verdict_outputs_are_deterministic(coll: Path, tmp_path: Path) -> None:
    _engine(coll, "trimmable")
    files = {"round4": REPORTS / "round4-trim.json", "declaration": REPORTS / "declaration-trim.json"}
    _verdict(coll, "trimmable", tmp_path, **files)
    first = {p.name: p.read_bytes() for p in _draft(coll, "trimmable").iterdir() if p.name.startswith("round5")}
    _verdict(coll, "trimmable", tmp_path, **files)
    assert {p.name: p.read_bytes() for p in _draft(coll, "trimmable").iterdir() if p.name.startswith("round5")} == first


# ------------------------------------------------------------------ the ruling

def test_rule_records_the_ruling_with_its_date(coll: Path, tmp_path: Path) -> None:
    _engine(coll, "lean")
    _, lines = _verdict(coll, "lean", tmp_path)
    digest = re.search(r"VERDICT_DIGEST: (\S+)", "\n".join(lines)).group(1)  # type: ignore[union-attr]
    code = gauntlet_verdict.rule(coll, "skills/lean", gauntlet.Options(), "amend", digest, "2026-11-15",
                                 "keep, but revisit after the next CPP release", out=lambda _: None)
    entry = json.loads((coll / "skills" / "lean" / gauntlet.RECORD_NAME).read_text())["rounds"]["5"]
    assert code == 0 and entry["verdict"] == "KEEP" and entry["ruling"] == "amend"
    assert entry["ruled_on"] == "2026-11-15" and entry["inputs"] == {"verdict": digest}


def test_rule_refuses_a_stale_verdict_digest(coll: Path, tmp_path: Path) -> None:
    _engine(coll, "lean")
    _verdict(coll, "lean", tmp_path)
    record = coll / "skills" / "lean" / gauntlet.RECORD_NAME
    before = record.read_bytes()
    code = gauntlet_verdict.rule(coll, "skills/lean", gauntlet.Options(), "accept", "sha256:" + "0" * 64,
                                 "2026-11-15", None, out=lambda _: None)
    assert code == gauntlet_verdict.EXIT_REFUSED and record.read_bytes() == before


def test_rule_refuses_to_rule_on_an_unknown_verdict(coll: Path, tmp_path: Path) -> None:
    _engine(coll, "lean")
    _, lines = _verdict(coll, "lean", tmp_path, overlap=None)
    digest = re.search(r"VERDICT_DIGEST: (\S+)", "\n".join(lines)).group(1)  # type: ignore[union-attr]
    code = gauntlet_verdict.rule(coll, "skills/lean", gauntlet.Options(), "accept", digest, "2026-11-15", None,
                                 out=lambda _: None)
    assert code == gauntlet_verdict.EXIT_REFUSED


def test_an_engine_rerun_keeps_the_ruling_and_still_caches(coll: Path, tmp_path: Path) -> None:
    _engine(coll, "lean")
    _, lines = _verdict(coll, "lean", tmp_path)
    digest = re.search(r"VERDICT_DIGEST: (\S+)", "\n".join(lines)).group(1)  # type: ignore[union-attr]
    gauntlet_verdict.rule(coll, "skills/lean", gauntlet.Options(), "accept", digest, "2026-11-15", None,
                          out=lambda _: None)
    seen: list[str] = []
    gauntlet.run(coll, "skills/lean", gauntlet.Options(offline=True, usage=[FIX / "usage"]), out=seen.append)
    entry = json.loads((coll / "skills" / "lean" / gauntlet.RECORD_NAME).read_text())["rounds"]
    assert entry["5"]["ruling"] == "accept"
    assert all(line.endswith("(cached)") for line in seen if line.startswith("ROUND"))


# ------------------------------------------------ the round 3/4 reader, pinned

def test_the_planted_reports_carry_every_field_the_verdict_reads() -> None:
    for name in ("round3-complete.json", "round4-keep.json", "round4-trim.json"):
        data = json.loads((REPORTS / name).read_text())
        assert set(gauntlet_verdict.ROUND_FIELDS) <= set(data), name
        for row in data["variants"].values():
            assert set(gauntlet_verdict.VARIANT_FIELDS) <= set(row), name


def test_the_real_round_report_carries_every_field_read() -> None:
    """Against the REAL #736 class, once #736 PR 1 is on main: a rename upstream
    must break this reader loudly, not silently."""
    trials = pytest.importorskip("skillc.gauntlet_trials", reason="SKIPPED UNTIL #736 PR 1 IS ON MAIN: the real "
                                 "RoundReport is not in this skillc; round 5 reads planted reports until then")
    fields = {f.name for f in dataclasses.fields(trials.RoundReport)}
    assert set(gauntlet_verdict.ROUND_FIELDS) <= fields
