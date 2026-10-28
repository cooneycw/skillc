"""The committed description-optimizer batches (#238) stay runnable: every
skill's screen and confirmation declarations, as scripts/description_optimizer.py
derives them, parse and authorize - so a typo in a batch file fails here, not
eight hours into a live batch."""

from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import Any

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


def _report(cells: dict[str, dict[str, dict[str, int]]]) -> dict[str, object]:
    return {"cells": cells}


def test_a_screen_with_an_arm_undecided_on_a_case_is_incomplete() -> None:
    """Batch 1, flow-finish: published had 0 decided observations on one
    select case, scored on the other alone, and tied the variants - a tie
    from missing data must not keep published."""
    full = {"observed": 3, "selected": 3, "scheduled": 3}
    empty = {"observed": 0, "selected": 0, "scheduled": 3}
    complete = {"s1": {"published": full, "variant-a": full}, "a1": {"published": full, "variant-a": full}}
    incomplete = {"s1": {"published": empty, "variant-a": full}, "a1": {"published": full, "variant-a": full}}
    assert do.screen_complete(_report(complete)) is True  # type: ignore[attr-defined]
    assert do.screen_complete(_report(incomplete)) is False  # type: ignore[attr-defined]
    assert do.screen_complete(_report({})) is False  # type: ignore[attr-defined]


def _optimize_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    counts: tuple[tuple[int, int, int], ...], *,
    unavailable: tuple[str, ...] = (), incomplete: bool = False, negative_zero: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Only snapshot building and study execution are fake; optimize returns."""
    driver: Any = do
    entry = json.loads(BATCHES[0].read_text())["skills"][0]
    skill = entry["skill"]
    cpp, work = tmp_path / "cpp", tmp_path / "work"
    published = cpp / "codex" / "skills" / skill / "SKILL.md"
    published.parent.mkdir(parents=True)
    published.write_text('---\nname: ' + skill + '\ndescription: "Published description"\n---\nBody.\n')
    calls: list[dict[str, Any]] = []

    def fake_degrade(cpp: Path, skill: str, override: Path, out: Path) -> Path:
        out.mkdir(parents=True)
        (out / "SKILL.md").write_bytes(override.read_bytes())
        return out

    def fake_study(decl_path: Path, rewritten: dict[str, Path], private: Path) -> dict[str, Any]:
        data = json.loads(decl_path.read_text())
        declaration = us.parse_declaration(data)
        screen = "screen" in decl_path.name
        calls.append({"screen": screen, "declaration": data, "rewritten": rewritten})
        cells: dict[str, dict[str, dict[str, int]]] = {}
        select_index = 0
        for case in declaration.cases:
            cells[case.id] = {}
            for index, arm in enumerate(declaration.arms):
                if screen:
                    selected = counts[index][select_index if case.expect == "select" else 2]
                    observed = 2
                    if ((arm in unavailable and case.expect == "select") or
                            (incomplete and index == 2 and select_index == 0 and case.expect == "select")):
                        observed = selected = 0
                else:
                    observed = case.attempts_per_arm
                    selected = observed // 2 if case.expect == "select" else 0
                cells[case.id][arm] = {"scheduled": case.attempts_per_arm,
                                        "observed": observed, "selected": selected}
                assert 0 <= selected <= observed <= case.attempts_per_arm
            if case.expect == "select":
                select_index += 1
        primary = None
        if not screen:
            rows = cells[declaration.primary.id]
            r, p = rows["rewritten"], rows["published"]
            probability = us.fisher_one_sided(r["selected"], r["observed"], p["selected"], p["observed"])
            primary = {
                "case": declaration.primary.id, "kind": "fisher-exact-one-sided",
                "direction": "rewritten > published", "alpha": declaration.alpha,
                "rewritten": f"{r['selected']}/{r['observed']}", "published": f"{p['selected']}/{p['observed']}",
                "available": True, "reason": None, "significant": probability <= declaration.alpha,
                "p_value": probability,
            }
        scores = us._scores(cells, declaration)
        if screen and negative_zero:
            # A report may serialize the same computed zero with either sign.
            assert scores["variant-a"]["score"] == 0.0
            scores["variant-a"]["score"] = -0.0
        return {"exit": 0, "report": {
            "version": 1, "kind": us.REPORT_KIND, "experiment_id": "fixture-screen" if screen else "fixture-confirm",
            "cells": cells, "scores": scores, "primary_test": primary,
        }}

    monkeypatch.setattr(driver, "degrade", fake_degrade)
    monkeypatch.setattr(driver, "run_study", fake_study)
    return driver.optimize(entry, cpp, work, driver.base_declaration()), calls


def _assert_confirmation(result: dict[str, Any], calls: list[dict[str, Any]], winner: str) -> None:
    assert result["winner"] == winner
    assert result["verdict"].startswith("not confirmed:")
    assert result["confirm"]["experiment"] == "fixture-confirm"
    assert len(calls) == 2 and calls[0]["screen"] and not calls[1]["screen"]
    [published, rewritten] = calls[1]["declaration"]["arms"]
    assert published["name"] == "published" and rewritten["name"] == "rewritten"
    assert rewritten["description"] == result["variants"][winner]
    [snapshot] = calls[1]["rewritten"].values()
    assert set(calls[1]["rewritten"]) == {"rewritten"} and snapshot.name == "rw-" + winner
    override = (snapshot / "SKILL.md").read_text()
    assert "description: " + json.dumps(result["variants"][winner]) in override
    assert len(calls[0]["rewritten"]) == len(result["variants"]) == 2
    assert snapshot == calls[0]["rewritten"][winner]


def test_optimize_zero_beats_negative_instead_of_wrongly_keeping_published(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, calls = _optimize_counts(tmp_path, monkeypatch, ((0, 1, 1), (1, 1, 1), (0, 0, 1)))
    assert result["screen"]["complete"] is True
    assert {a: s["score"] for a, s in result["screen"]["scores"].items()} == {
        "published": -0.25, "variant-a": 0.0, "variant-b": -0.5,
    }
    _assert_confirmation(result, calls, "variant-a")


def test_optimize_zero_routes_confirmation_to_zero_instead_of_negative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, calls = _optimize_counts(tmp_path, monkeypatch, ((0, 0, 2), (1, 1, 1), (0, 0, 1)))
    assert result["screen"]["complete"] is True
    assert result["screen"]["scores"]["published"]["score"] == -1.0
    _assert_confirmation(result, calls, "variant-a")


def test_optimize_keeps_a_strictly_better_published_description_without_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, calls = _optimize_counts(tmp_path, monkeypatch, ((2, 2, 0), (2, 2, 1), (0, 0, 1)))
    assert result["screen"]["complete"] is True
    assert result["verdict"].startswith("kept:")
    assert result["winner"] is None and result["confirm"] is None
    assert len(calls) == 1 and calls[0]["screen"]


def test_optimize_keeps_negative_zero_numeric(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    result, calls = _optimize_counts(
        tmp_path, monkeypatch, ((0, 0, 2), (1, 1, 1), (0, 0, 1)), negative_zero=True,
    )
    assert math.copysign(1, result["screen"]["scores"]["variant-a"]["score"]) == -1
    _assert_confirmation(result, calls, "variant-a")


@pytest.mark.parametrize(("counts", "unavailable", "incomplete", "winner", "complete"), [
    (((0, 0, 2), (1, 2, 1), (2, 2, 1)), (), False, "variant-b", True),  # positive ordering
    (((0, 0, 2), (0, 1, 1), (0, 0, 1)), (), False, "variant-a", True),  # negative ordering
    (((0, 0, 2), (0, 0, 1), (0, 0, 0)), ("variant-b",), False, "variant-a", False),
    (((0, 0, 2), (1, 1, 1), (0, 0, 0)), ("variant-b",), False, "variant-a", False),
    (((0, 0, 2), (1, 2, 1), (1, 2, 1)), (), False, "variant-a", True),  # stable variant tie
    (((2, 2, 1), (2, 2, 1), (1, 2, 1)), (), False, "variant-a", True),  # published tie
    (((2, 2, 0), (2, 2, 1), (0, 0, 1)), (), True, "variant-a", False),  # incomplete higher published
    (((0, 0, 0), (1, 2, 1), (2, 2, 1)), ("published",), False, "variant-b", False),
    (((2, 2, 0), (0, 0, 0), (0, 0, 0)), ("variant-a", "variant-b"), False, "variant-a", False),
], ids=["positive", "negative", "negative-over-none", "zero-over-none", "variant-tie", "published-tie",
        "incomplete", "published-none", "all-variants-none"])
def test_optimize_preserves_numeric_missing_tie_and_incomplete_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, counts: tuple[tuple[int, int, int], ...],
    unavailable: tuple[str, ...], incomplete: bool, winner: str, complete: bool,
) -> None:
    result, calls = _optimize_counts(tmp_path, monkeypatch, counts, unavailable=unavailable, incomplete=incomplete)
    assert result["screen"]["complete"] is complete
    _assert_confirmation(result, calls, winner)

