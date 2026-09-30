"""The #211 incident catalogue's tables follow from its committed records.

`docs/research/cpp-incident-catalogue.md` ranks failure classes for #203's next
task. Its tables are rendered by `scripts/cpp_incident_counts.py` from the
per-item records beside it, and this test is what keeps them rendered: a
reader choosing a task from the ranking will not re-derive it.

The check is a gate that lets a document through, so it carries its own red
cases here: one changed record, and one missing block, must each turn it red.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "cpp_incident_counts.py"
DATA = ROOT / "docs" / "research" / "cpp-incident-catalogue"
DOC = ROOT / "docs" / "research" / "cpp-incident-catalogue.md"


def _load() -> ModuleType:
    """`scripts/` is not a package; import by file location."""
    spec = importlib.util.spec_from_file_location("cpp_incident_counts", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


counts = _load()


def test_every_table_in_the_catalogue_matches_its_records() -> None:
    assert counts.stale_blocks(DOC.read_text(encoding="utf-8")) == []


def test_one_reclassified_record_turns_the_check_red(tmp_path: Path) -> None:
    data = tmp_path / "data"
    shutil.copytree(DATA, data)
    rows = [json.loads(line) for line in (data / "issues.jsonl").read_text().splitlines()]
    target = next(r for r in rows if r["defect"] and r["cls"] == "BLIND")
    target["cls"] = "LOGIC"
    (data / "issues.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    stale = counts.stale_blocks(DOC.read_text(encoding="utf-8"), data)
    assert "classes" in stale and "ranking" in stale


def test_a_missing_block_is_red_not_skipped() -> None:
    text = DOC.read_text(encoding="utf-8").replace("<!-- counts:agreement -->", "")
    assert counts.stale_blocks(text) == ["agreement (block missing)"]


def test_records_cover_the_whole_population_with_known_codes() -> None:
    classes = set(counts.CLASSES)
    issues = counts.load("issues.jsonl")
    assert len({r["n"] for r in issues}) == len(issues) == 682
    for r in issues:
        if r["defect"]:
            assert r["cls"] in classes and set(r["cls2"]) <= classes, r["n"]
            assert r["stage"] in {"yes", "partial", "no"}, r["n"]
        else:
            assert r["cls"] is None, r["n"]
    for r in counts.load("nit-store.jsonl"):
        assert (r["cls"] in classes) if r["finding"] else r["cls"] is None, r["comment"]
    for r in counts.load("counter-model.jsonl"):
        assert all(f["cls"] in classes for f in r["itemized"]), r["pr"]
    sampled = {r["n"] for r in counts.load("second-rater.jsonl")}
    assert sampled <= {r["n"] for r in issues} and len(sampled) == 68
