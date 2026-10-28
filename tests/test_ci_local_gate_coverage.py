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
import shlex
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
    "clean-install": ("clean-install",),
    "git-tests-control": ("git-tests-control",),
    "pytest-population-control": ("pytest-population-control",),
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


# ----------------------------------------------- parallel population gate (#364)


def _parallel_contract(ci_text: str, make_text: str) -> bool:
    config = yaml.safe_load(ci_text)
    gate = next(step for step in config["steps"] if step["name"] == "gate")
    run = next((c for c in gate["commands"] if "ci/run_pytest_lanes.py" in c), "")
    make_run = next((line for line in make_text.splitlines() if "ci/run_pytest_lanes.py" in line), "")
    if not run or not make_run:
        return False
    make_run = make_run.replace("$(PYTEST_WORKERS)", "auto")
    make_run = make_run.replace("$(PYTEST_REPORT_DIR)", ".")
    make_run = make_run.replace(" -- $(PYTEST_ARGS)", "")
    make_run = make_run.split(" |", 1)[0]
    expected = ["uv", "run", "--no-sync", "python3", "ci/run_pytest_lanes.py",
                "--workers", "auto", "--maxprocesses=8", "--dist=loadgroup",
                "--durations=0", "--report-dir", "."]
    return (shlex.split(run) == shlex.split(make_run) == expected
            and "PYTEST_WORKERS ?= auto" in make_text
            and "PYTEST_ARGS ?=\n" in make_text
            and " -- $(PYTEST_ARGS) | tee" in make_text
            and "python3 ci/check_pytest_population.py" in make_text
            and "pytest-population-control: test" in make_text
            and "\tbash ci/pytest-lanes-control.sh" in make_text
            and "pytest-population-control" in make_text.split("verify:", 1)[1]
            and any(step["name"] == "pytest-population-control"
                    and step["depends_on"] == ["gate"]
                    and "python3 ci/check_pytest_population.py pytest-collected.txt pytest-report.xml"
                    in step["commands"]
                    and "bash ci/pytest-population-control.sh" in step["commands"]
                    and "bash ci/pytest-lanes-control.sh" in step["commands"]
                    for step in config["steps"]))


def test_ci_and_local_parallel_population_contract() -> None:
    assert _parallel_contract(CI_YML.read_text(), MAKEFILE.read_text())


def test_parallel_contract_rejects_serial_or_missing_control() -> None:
    ci_text, make_text = CI_YML.read_text(), MAKEFILE.read_text()
    for old, new in (("--workers auto", "--workers 0"),
                     ("ci/run_pytest_lanes.py", "pytest --version"),
                     ("python3 ci/check_pytest_population.py", "true")):
        changed = ci_text.replace(old, new)
        assert changed != ci_text
        assert not _parallel_contract(changed, make_text)
    for old, new in (("PYTEST_WORKERS ?= auto", "PYTEST_WORKERS ?= 0"),
                     ("ci/run_pytest_lanes.py", "pytest --version"),
                     ("python3 ci/check_pytest_population.py", "true")):
        changed = make_text.replace(old, new)
        assert changed != make_text
        assert not _parallel_contract(ci_text, changed)


def test_parallel_contract_rejects_ci_only_selection_and_worker_overrides() -> None:
    ci_text, make_text = CI_YML.read_text(), MAKEFILE.read_text()
    for option in ("--ignore=tests/test_docker_backend.py", "--workers 0"):
        changed = ci_text.replace("--report-dir .", "--report-dir . -- " + option)
        assert not _parallel_contract(changed, make_text)


def _records_gate_host_state(ci_text: str) -> bool:
    """#412: the gate step's FIRST command prints the CI VM's `nproc` and
    `/proc/loadavg` and sets an EXIT trap that prints them again, so a timing red is
    attributable to the machine's state from the CI log alone."""
    gate = next(step for step in yaml.safe_load(ci_text)["steps"] if step["name"] == "gate")
    first = gate["commands"][0]
    start, sep, rest = first.partition("; trap '")
    body, sep2, _ = rest.partition("' EXIT")
    measured = ("$(nproc)", "$(cat /proc/loadavg)")
    return (bool(sep and sep2) and "gate-host start" in start and all(m in start for m in measured)
            and "gate-host end" in body and all(m in body for m in measured))


def test_the_gate_records_the_ci_hosts_state_at_start_and_exit() -> None:
    assert _records_gate_host_state(CI_YML.read_text())


def test_gate_host_state_check_rejects_a_missing_trap_or_a_late_start_line() -> None:
    ci_text = CI_YML.read_text()
    first = next(s for s in yaml.safe_load(ci_text)["steps"] if s["name"] == "gate")["commands"][0]
    no_trap = ci_text.replace(first, first.split("; trap", 1)[0])
    assert no_trap != ci_text and not _records_gate_host_state(no_trap)
    moved = ci_text.replace("      - " + first + "\n", "", 1).replace(
        "      - pip install uv\n", "      - pip install uv\n      - " + first + "\n", 1)
    assert moved != ci_text and not _records_gate_host_state(moved)
    # Counter-model review: measurements present only in the START line must
    # not satisfy the check - the trap body is checked on its own.
    body = first.split("; trap '", 1)[1].split("' EXIT", 1)[0]
    unmeasured_end = ci_text.replace(body, 'echo "gate-host end"', 1)
    assert unmeasured_end != ci_text and not _records_gate_host_state(unmeasured_end)


def test_parallel_contract_rejects_dropping_durations_from_either_side() -> None:
    ci_text, make_text = CI_YML.read_text(), MAKEFILE.read_text()
    assert not _parallel_contract(ci_text.replace("--durations=0 ", "", 1), make_text)
    assert not _parallel_contract(ci_text, make_text.replace("--durations=0 ", "", 1))


def test_generated_collection_is_excluded_from_both_leak_scans() -> None:
    assert "pytest-collected.txt" in _ci_leak_exclude_paths(CI_YML.read_text())
    assert "pytest-collected.txt" in _makefile_leak_exclude_paths(MAKEFILE.read_text())


def _clean_install_commands_present(ci_text: str, make_text: str) -> bool:
    config = yaml.safe_load(ci_text)
    step = next((s for s in config["steps"] if s["name"] == "clean-install"), None)
    if step is None:
        return False
    required = (
        "bash ci/clean-install-check.sh",
        "CLEAN_INSTALL_CONTROL=neuter-installed-rule bash ci/clean-install-check.sh",
        "CLEAN_INSTALL_CONTROL=delete-scratch-controls bash ci/clean-install-check.sh",
        "bash ci/clean-install-comparison-control.sh",
    )
    target = re.search(r"^clean-install:.*\n((?:\t.*\n)+)", make_text, re.MULTILINE)
    verify = re.search(r"^verify:((?:.*\\\n)*.*)", make_text, re.MULTILINE)
    return (
        target is not None and verify is not None
        and "clean-install" in verify.group(1).split()
        and all(command in step["commands"] for command in required)
        and all(f"\t{command}\n" in target.group(1) for command in required)
    )


def test_clean_install_and_both_controls_run_in_both_gates() -> None:
    assert _clean_install_commands_present(CI_YML.read_text(), MAKEFILE.read_text())


def test_clean_install_wiring_controls() -> None:
    ci_text, make_text = CI_YML.read_text(), MAKEFILE.read_text()
    assert _clean_install_commands_present(ci_text, make_text)
    for command in (
        "bash ci/clean-install-check.sh",
        "CLEAN_INSTALL_CONTROL=neuter-installed-rule bash ci/clean-install-check.sh",
        "CLEAN_INSTALL_CONTROL=delete-scratch-controls bash ci/clean-install-check.sh",
        "bash ci/clean-install-comparison-control.sh",
    ):
        assert not _clean_install_commands_present(ci_text.replace(f"      - {command}\n", ""), make_text)
        assert not _clean_install_commands_present(ci_text, make_text.replace(f"\t{command}\n", ""))
    assert not _clean_install_commands_present(ci_text, make_text.replace("pytest-population-control clean-install\n", "pytest-population-control\n"))
