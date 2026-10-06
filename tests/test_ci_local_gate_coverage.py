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

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WOODPECKER_DIR = ROOT / ".woodpecker"
CI_YML = WOODPECKER_DIR / "ci.yml"
MAKEFILE = ROOT / "Makefile"

#: Each CI step name -> the make target(s) that cover it locally. "gate" maps
#: to four separate targets, not one, because AGENTS.md's `## Verify` lists
#: `skillc selftest`, `pytest`, `ruff check` and `mypy` as four checks - this
#: mapping did not invent that split, it names it.
#:
#: #309: docker-tests / docker-tests-control cover `.woodpecker/docker-tests.yml`,
#: a SEPARATE file from ci.yml - this mapping, and the function below reading
#: it, must glob every file under .woodpecker/, not just CI_YML, or a new
#: pipeline file's steps would be invisible to this check entirely (the same
#: class of gap #307 itself hit: a new step with no local coverage, just one
#: level up - a new FILE rather than a new step in the existing one).
CI_STEP_MAKE_TARGETS: dict[str, tuple[str, ...]] = {
    "gate": ("selftest", "test", "lint", "typecheck"),
    "negative-control": ("negative-control",),
    "typecheck-control": ("typecheck-control",),
    "secret-scan": ("secret-scan",),
    "leak-check": ("leak-check",),
    "changelog-check": ("changelog-check",),
    "readme-drift": ("readme-drift",),
    "git-tests-control": ("git-tests-control",),
    "docker-tests": ("docker-tests",),
    "docker-tests-control": ("docker-tests-control",),
}


def _ci_step_names(text: str) -> list[str]:
    config = yaml.safe_load(text)
    return [step["name"] for step in config["steps"]]


def _all_workflow_step_names() -> list[str]:
    names: list[str] = []
    for path in sorted(WOODPECKER_DIR.glob("*.yml")):
        names.extend(_ci_step_names(path.read_text(encoding="utf-8")))
    return names


def _unmapped_steps(step_names: list[str]) -> list[str]:
    return [s for s in step_names if s not in CI_STEP_MAKE_TARGETS]


def _make_target_names() -> set[str]:
    text = MAKEFILE.read_text(encoding="utf-8")
    return {m.group(1) for m in re.finditer(r"^([a-zA-Z0-9_-]+):", text, re.MULTILINE)}


def test_every_ci_step_maps_to_a_local_make_target() -> None:
    steps = _all_workflow_step_names()
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


# ----------------------------------------------- leak-check's exclude list (Nit Store #20)


#: `Makefile`'s SKILLC_LEAK_EXCLUDE adds exactly one path over CI's own
#: SKILLC_EXCLUDE_ARGS: `reports/` (`test`'s own -rA output, gitignored).
#: See SKILLC_LEAK_EXCLUDE's own comment in the Makefile for why - CI's
#: leak-check step runs in its own fresh checkout and never has a reports/
#: directory to see; only a local `make verify`'s prior `test` target,
#: run in the SAME tree, creates one.
LOCAL_ONLY_LEAK_EXCLUDES = frozenset({"reports"})


def _ci_leak_exclude_paths(text: str) -> list[str]:
    """The `--exclude PATH` arguments the leak-check CI step exports as
    `SKILLC_EXCLUDE_ARGS`."""
    config = yaml.safe_load(text)
    step = next(s for s in config["steps"] if s["name"] == "leak-check")
    for command in step["commands"]:
        match = re.search(r'SKILLC_EXCLUDE_ARGS="([^"]*)"', command)
        if match:
            return re.findall(r"--exclude (\S+)", match.group(1))
    raise AssertionError("the leak-check CI step never exports SKILLC_EXCLUDE_ARGS")


def _makefile_leak_exclude_paths(text: str) -> list[str]:
    """The `--exclude PATH` arguments in the Makefile's `SKILLC_LEAK_EXCLUDE`,
    which continues onto a second line with a trailing `\\` - `.` never
    matches a newline, so the value is assembled line by line instead of
    with one regex spanning the continuation."""
    lines = text.split("\n")
    start = next(i for i, line in enumerate(lines) if line.startswith("SKILLC_LEAK_EXCLUDE"))
    value_lines = [lines[start].split(":=", 1)[1]]
    i = start
    while value_lines[-1].rstrip().endswith("\\"):
        i += 1
        value_lines[-1] = value_lines[-1].rstrip()[:-1]
        value_lines.append(lines[i])
    value = " ".join(value_lines)
    return re.findall(r"--exclude (\S+)", value)


def test_makefile_leak_exclude_derives_from_cis_own_list() -> None:
    """The two lists (#20 Nit Store: found during #134/#156 review) are
    hand-maintained in separate files with no shared source. If CI's list
    changes and the Makefile's does not, or the reverse, a local `make
    verify` goes red on something CI accepts, or green on something CI
    would catch - the local gate is only trustworthy while it agrees with
    CI. This does not unify the two definitions (the Makefile is `make`
    syntax, ci.yml is Woodpecker YAML - there is no single file both could
    read); it makes the two AGREEING a tested fact instead of an assumption."""
    ci_paths = _ci_leak_exclude_paths(CI_YML.read_text(encoding="utf-8"))
    make_paths = _makefile_leak_exclude_paths(MAKEFILE.read_text(encoding="utf-8"))
    assert set(make_paths) == set(ci_paths) | LOCAL_ONLY_LEAK_EXCLUDES, (
        f"Makefile's SKILLC_LEAK_EXCLUDE {make_paths} must equal CI's "
        f"SKILLC_EXCLUDE_ARGS {ci_paths} plus {sorted(LOCAL_ONLY_LEAK_EXCLUDES)} - "
        f"the two lists are hand-maintained separately and have drifted apart"
    )


def test_a_ci_side_drifted_leak_exclude_list_is_caught() -> None:
    """Red case, the ci.yml side: a copy of ci.yml's leak-check step gains
    one extra `--exclude` path the Makefile does not have, run through the
    SAME extraction function the test above calls - proving a genuine
    drift between the two files would fail this check, not just that the
    current, agreeing lists happen to pass."""
    ci_text = CI_YML.read_text(encoding="utf-8")
    drifted = ci_text.replace(
        'tests/fixtures/leak_seeds"',
        'tests/fixtures/leak_seeds --exclude a-brand-new-path-nobody-added-to-the-makefile"',
    )
    assert drifted != ci_text, "the replacement found nothing to drift - this red case is inert"
    ci_paths = _ci_leak_exclude_paths(drifted)
    make_paths = _makefile_leak_exclude_paths(MAKEFILE.read_text(encoding="utf-8"))
    assert set(make_paths) != set(ci_paths) | LOCAL_ONLY_LEAK_EXCLUDES


def test_a_makefile_side_drifted_leak_exclude_list_is_caught() -> None:
    """Red case, the Makefile side (orchestrator review): the check has TWO
    inputs, so a case on only the ci.yml side would not catch a parser that
    silently read nothing from the Makefile and happened to still compare
    unequal for an unrelated reason - each side needs its own committed
    case. A copy of the Makefile's text gains one extra `--exclude` path
    ci.yml does not have, run through the SAME extraction function the
    main test calls."""
    makefile_text = MAKEFILE.read_text(encoding="utf-8")
    drifted = makefile_text.replace(
        "--exclude reports\n",
        "--exclude reports --exclude a-brand-new-path-nobody-added-to-ci\n",
    )
    assert drifted != makefile_text, "the replacement found nothing to drift - this red case is inert"
    make_paths = _makefile_leak_exclude_paths(drifted)
    ci_paths = _ci_leak_exclude_paths(CI_YML.read_text(encoding="utf-8"))
    assert set(make_paths) != set(ci_paths) | LOCAL_ONLY_LEAK_EXCLUDES


def test_leak_exclude_parsers_are_never_vacuously_empty() -> None:
    """Positive control (orchestrator review): a regex that quietly matches
    nothing returns `[]`, and `set() == set() | LOCAL_ONLY_LEAK_EXCLUDES`
    is still correctly unequal today only because `LOCAL_ONLY_LEAK_EXCLUDES`
    is non-empty - that is an accident of the current data, not a property
    of the check. Each parser must be shown to find something real in the
    actual files, independent of whether the other side's result happens
    to differ from it."""
    make_paths = _makefile_leak_exclude_paths(MAKEFILE.read_text(encoding="utf-8"))
    ci_paths = _ci_leak_exclude_paths(CI_YML.read_text(encoding="utf-8"))
    assert make_paths, "the Makefile parser found no --exclude paths at all - probably broken, not really empty"
    assert ci_paths, "the ci.yml parser found no --exclude paths at all - probably broken, not really empty"


# ----------------------------------------------- agent routing labels (#315)

#: #309's future workflow file - the one named exception to "no host label,
#: no docker-ci label" below. Does not exist yet; the tests here are written
#: ahead of #309 landing so the requirement is checked from the moment the
#: file appears, rather than relying on someone remembering it.
DOCKER_TESTS_WORKFLOW = "docker-tests.yml"


def _ordinary_workflow_files() -> list[Path]:
    return [p for p in sorted((ROOT / ".woodpecker").glob("*.yml")) if p.name != DOCKER_TESTS_WORKFLOW]


def _workflow_labels(text: str) -> dict[str, object]:
    config = yaml.safe_load(text)
    return config.get("labels") or {}


def test_ordinary_workflows_never_carry_a_host_label() -> None:
    """#315: containment for skillc's CI is the dedicated agent's own
    server-side `repo` Filter, not a label this repo's YAML declares - a
    label here is author-controlled (any PR can add one) and so is never a
    security boundary; see #315's write-up. ci.yml used to carry
    labels: {host: kyleci}, pinning it to the agent kyle also uses - this
    pins that regression against every ordinary workflow file, current or
    future. docker-tests.yml (#309) is the one named exception."""
    offenders = [p.name for p in _ordinary_workflow_files() if "host" in _workflow_labels(p.read_text(encoding="utf-8"))]
    assert offenders == [], (
        f"{offenders} carry a 'host' label - routing containment is the dedicated "
        f"agent's server-side repo Filter (#315), not a label an ordinary skillc "
        f"workflow declares; remove it"
    )


def test_a_reintroduced_host_label_is_caught() -> None:
    """Red case: ci.yml's real text with labels: {host: kyleci} spliced
    back in, run through the same two functions the test above calls -
    proving this would catch the exact regression #315 fixed, not just
    that the current label-free file happens to pass."""
    text = CI_YML.read_text(encoding="utf-8")
    drifted = text.replace("steps:\n", "labels:\n  host: kyleci\n\nsteps:\n", 1)
    assert drifted != text, "the splice found nothing to anchor on - this red case is inert"
    assert "host" in _workflow_labels(drifted)


def test_docker_tests_workflow_carries_its_own_label_when_it_exists() -> None:
    """#315/#309: once docker-tests.yml exists, it must carry a docker-ci
    label - that's what the dedicated agent's mandatory !docker-ci=yes
    filter actually matches against. Skips (not fails) while the file is
    genuinely absent - #309 has not landed - which is a different fact from
    a step that exists and silently stopped running (the #307 standard);
    there is nothing yet to check."""
    path = ROOT / ".woodpecker" / DOCKER_TESTS_WORKFLOW
    if not path.exists():
        pytest.skip(f"{DOCKER_TESTS_WORKFLOW} does not exist yet (#309 not landed)")
    labels = _workflow_labels(path.read_text(encoding="utf-8"))
    assert labels.get("docker-ci") is not None, (
        f"{DOCKER_TESTS_WORKFLOW} must carry a docker-ci label so the dedicated "
        f"agent's mandatory !docker-ci=yes filter routes it there"
    )


def test_a_docker_tests_workflow_missing_its_label_is_caught(tmp_path: Path) -> None:
    """Red case for the test above: a docker-tests.yml with no docker-ci
    label, run through the same extraction function - proving a genuinely
    mislabelled #309 file would be caught, not just that "file absent"
    currently skips past the check with no file to look at."""
    bad = tmp_path / DOCKER_TESTS_WORKFLOW
    bad.write_text("steps:\n  - name: docker-tests\n    commands: [true]\n", encoding="utf-8")
    labels = _workflow_labels(bad.read_text(encoding="utf-8"))
    assert labels.get("docker-ci") is None
