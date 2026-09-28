"""Every Woodpecker CI step must have a stated local equivalent (#134, #156
cross-model review: #155 went red on `changelog-check`, which no local gate
ran, because `make verify` mirrored only the `gate` and `negative-control`
steps). `CI_STEP_MAKE_TARGETS` is the explicit mapping; a CI step missing
from it fails `test_every_ci_step_maps_to_a_local_make_target`, so a new
Woodpecker step with no local coverage is caught here rather than discovered
the next time it goes red in CI on something nobody ran locally.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CI_YML = ROOT / ".woodpecker" / "ci.yml"
MAKEFILE = ROOT / "Makefile"

#: Each CI step name -> the make target(s) that cover it locally. "gate" maps
#: to four separate targets, not one, because AGENTS.md's `## Verify` lists
#: `skillc selftest`, `pytest`, `ruff check` and `mypy` as four checks - this
#: mapping did not invent that split, it names it.
CI_STEP_MAKE_TARGETS: dict[str, tuple[str, ...]] = {
    "gate": ("selftest", "test", "lint", "typecheck"),
    "negative-control": ("negative-control",),
    "typecheck-control": ("typecheck-control",),
    "secret-scan": ("secret-scan",),
    "leak-check": ("leak-check",),
    "changelog-check": ("changelog-check",),
    "readme-drift": ("readme-drift",),
}


def _ci_step_names(text: str) -> list[str]:
    config = yaml.safe_load(text)
    return [step["name"] for step in config["steps"]]


def _unmapped_steps(step_names: list[str]) -> list[str]:
    return [s for s in step_names if s not in CI_STEP_MAKE_TARGETS]


def _make_target_names() -> set[str]:
    text = MAKEFILE.read_text(encoding="utf-8")
    return {m.group(1) for m in re.finditer(r"^([a-zA-Z0-9_-]+):", text, re.MULTILINE)}


def test_every_ci_step_maps_to_a_local_make_target() -> None:
    steps = _ci_step_names(CI_YML.read_text(encoding="utf-8"))
    unmapped = _unmapped_steps(steps)
    assert unmapped == [], (
        f"CI step(s) {unmapped} have no entry in CI_STEP_MAKE_TARGETS - add one "
        f"(new make target(s), wired into `verify`) so `make verify` cannot "
        f"silently miss a new gate the way it missed changelog-check"
    )

    targets = _make_target_names()
    for step, mapped in CI_STEP_MAKE_TARGETS.items():
        for target in mapped:
            assert target in targets, (
                f"CI step {step!r} claims make target {target!r}, which does not "
                f"exist in the Makefile"
            )


def test_a_ci_step_with_no_mapping_is_caught() -> None:
    """Red case (#156 review): a copy of ci.yml with an extra, unmapped step,
    run through the SAME function the test above calls, must be reported as
    unmapped - proving a genuinely new CI step would fail coverage, not just
    that the current, fully-mapped file happens to pass."""
    config = yaml.safe_load(CI_YML.read_text(encoding="utf-8"))
    config["steps"].append({"name": "a-brand-new-step-nobody-mapped-yet", "commands": ["true"]})
    steps = [step["name"] for step in config["steps"]]
    unmapped = _unmapped_steps(steps)
    assert unmapped == ["a-brand-new-step-nobody-mapped-yet"], unmapped
