"""The committed description-optimizer batches (#238) stay runnable: every
skill's screen and confirmation declarations, as scripts/description_optimizer.py
derives them, parse and authorize - so a typo in a batch file fails here, not
eight hours into a live batch."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from skillc import uptake_study as us

ROOT = Path(__file__).resolve().parent.parent
BATCHES = sorted((ROOT / "evals" / "description-optimizer").glob("batch-*.json"))


def _driver() -> object:
    spec = importlib.util.spec_from_file_location("description_optimizer", ROOT / "scripts" / "description_optimizer.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


do = _driver()


def test_there_is_at_least_one_batch() -> None:
    assert BATCHES, "no evals/description-optimizer/batch-*.json found - an empty population checks nothing"


@pytest.mark.parametrize("batch", BATCHES, ids=lambda p: p.name)
def test_every_skill_in_a_batch_derives_valid_authorized_declarations(batch: Path) -> None:
    data = json.loads(batch.read_text(encoding="utf-8"))
    base = do.base_declaration()  # type: ignore[attr-defined]
    subject = base["subject"]
    assert len(data["skills"]) == len({e["skill"] for e in data["skills"]}) <= 14
    for entry in data["skills"]:
        skill = entry["skill"]
        assert {c["expect"] for c in entry["development"]} == {"select", "abstain"}, skill
        assert sorted(c["expect"] for c in entry["held_out"]) == ["abstain", "select"], skill
        arms = [{"name": "published", "subject": subject}] + [
            {"name": arm, "subject": subject, "target_skill": skill, "description": d}
            for arm, d in entry["variants"].items()]
        screen = do.declaration(base, skill, "screen", arms,  # type: ignore[attr-defined]
                                [{**c, "attempts_per_arm": 3, "primary": False} for c in entry["development"]],
                                test=False)
        us.require_approved(us.parse_declaration(screen), ROOT)
        held = [{**c, "attempts_per_arm": 8 if c["expect"] == "select" else 5, "primary": c["expect"] == "select"}
                for c in entry["held_out"]]
        winner = next(iter(entry["variants"]))
        confirm = do.declaration(base, skill, "confirm",  # type: ignore[attr-defined]
                                 [{"name": "published", "subject": subject},
                                  {"name": "rewritten", "subject": subject, "target_skill": skill,
                                   "description": entry["variants"][winner]}], held, test=True)
        us.require_approved(us.parse_declaration(confirm), ROOT)


def test_the_total_cap_allows_per_attempt_overhead() -> None:
    """Nit Store #20 / PR #311: a cap of exactly attempts x cut-off ran out
    before the schedule finished. The driver budgets overhead per attempt."""
    assert do.OVERHEAD_SECONDS >= 30  # type: ignore[attr-defined]
