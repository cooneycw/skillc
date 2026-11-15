"""Negative controls for ci/timing_inventory.py (#758, under #462).

The ratchet is a gate that lets work through: a green `make timing-check` is
read as "no new load-sensitive sub-second bound landed", and nothing
downstream re-derives that. So each verdict it can give has a committed input
here, and so does each shape the scanner claims to see.

Planted sources are JOINED FROM FRAGMENTS at run time (`_j`). This file is
itself under tests/, and a whole literal like the planted ones would be a real
hit the ratchet would have to baseline. A fragment alone matches no pattern.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from ci import timing_inventory as ti

ROOT = Path(__file__).resolve().parents[1]


def _j(*parts: str) -> str:
    return "".join(parts)


DOT = "0."  # every planted sub-second value is DOT + digits


def _tree(tmp_path: Path, files: dict[str, str], baseline: str = "") -> Path:
    for rel, text in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text), encoding="utf-8")
    (tmp_path / "skillc").mkdir(exist_ok=True)
    (tmp_path / "ci").mkdir(exist_ok=True)
    (tmp_path / "ci" / "timing-baseline.txt").write_text(baseline, encoding="utf-8")
    return tmp_path


# Every shape the docstring of ci/timing_inventory.py names, once each.
ALL_SHAPES = _j(
    "import subprocess, time\n",
    "import pytest\n",
    "POLL_INTERVAL = ", DOT, "05\n",
    "def helper(wait_seconds=", DOT, "2):\n",
    "    return wait_seconds\n",
    "@pytest.mark.parametrize('mode, settle', [('x', ", DOT, "5)])\n",
    "def test_all(mode, settle):\n",
    "    subprocess.run(['true'], timeout=", DOT, "3)\n",
    "    time.sleep(", DOT, "1)\n",
    "    started = time.monotonic()\n",
    "    assert time.monotonic() - started < ", DOT, "9\n",
    "    script = 'import time; time.sl", "eep(", DOT, "4)'\n",
    "    fake = 'x_time", "out=", DOT, "6'\n",
    "    gate = 'deadline=time.monot", "onic()+", DOT, "7'\n",
    "    shell = 'time", "out ", DOT, "8s true'\n",
)
EXPECTED_KINDS = {"const", "default", "param", "kw", "sleep", "elapsed", "str-sleep", "str-kw", "str-deadline",
                  "str-timeout-cli"}


def test_the_scanner_sees_every_shape_it_names(tmp_path: Path) -> None:
    root = _tree(tmp_path, {"tests/test_planted.py": ALL_SHAPES})
    kinds = {h.kind for h in ti.scan_tree(root, "tests")}
    assert kinds == EXPECTED_KINDS


def test_a_clean_twin_has_no_sub_second_bound(tmp_path: Path) -> None:
    """The other side: the same file with every bound taken from a shared name
    (as TEST_SETUP_BOUND is) gives the ratchet nothing to see."""
    clean = _j(
        "import subprocess, time\n",
        "from conftest import TEST_SETUP_BOUND\n",
        "def test_all():\n",
        "    subprocess.run(['true'], timeout=TEST_SETUP_BOUND)\n",
        "    started = time.monotonic()\n",
        "    assert time.monotonic() - started < TEST_SETUP_BOUND\n",
    )
    root = _tree(tmp_path, {"tests/test_clean.py": clean})
    assert ti.scan_tree(root, "tests") == []
    ok, lines = ti.check(root, root / "ci" / "timing-baseline.txt")
    assert ok and lines[-1] == "TIMING_CHECK: ok"


# Today's (#758) literal reds, as the lines stood on main 8e0e02e before the fix.
KNOWN_REDS = {
    "tests/test_trial_bootstrap.py": (_j(
        "def test_548_probe_reports_a_cleanup_it_could_not_confirm(tmp_path, mode, reason):\n",
        "    docker_bin, _log = _probe_docker(tmp_path, mode)\n",
        "    probe = tb.probe_image_cli_version(docker_bin, 'sha', 'codex', timeout=", DOT, "3, settle=", DOT, "5)\n",
    ), "test_548_probe_reports_a_cleanup_it_could_not_confirm", 0.5),
    "tests/test_docker_backend.py": (_j(
        "def test_a_stalled_events_client_cannot_outlive_the_daemon_deadline(base, docker_state):\n",
        "    backend = _backend(base, docker_state, daemon_timeout=", DOT, "2)\n",
    ), "test_a_stalled_events_client_cannot_outlive_the_daemon_deadline", 0.2),
    "tests/test_authority_interceptor.py": (_j(
        "def test_a_subject_created_observations_that_differs_from_the_backends_is_still_caught(base, docker_state):\n",
        "    interceptor = AuthorityInterceptor(backend, handle, allowed_prefixes=ALLOWED, interval=", DOT, "05)\n",
    ), "test_a_subject_created_observations_that_differs_from_the_backends_is_still_caught", 0.05),
}


@pytest.mark.parametrize("rel", sorted(KNOWN_REDS))
def test_the_ratchet_finds_each_of_todays_literal_reds(tmp_path: Path, rel: str) -> None:
    """Each pre-fix line is a NEW sub-second bound to an empty baseline. If the
    scanner could not see the bounds that actually turned main red, its green
    would mean nothing."""
    text, scope, value = KNOWN_REDS[rel]
    root = _tree(tmp_path, {rel: text})
    ok, lines = ti.check(root, root / "ci" / "timing-baseline.txt")
    assert not ok
    assert any(line.startswith(f"TIMING_NEW: {rel}:") and f" {value:g} in {scope} " in line for line in lines), lines


def test_the_inventory_sees_a_deadline_inside_an_embedded_script(tmp_path: Path) -> None:
    """The fourth literal red (test_inventory_runtime, pipeline 1478) sat in a
    string: an oracle driver with `deadline=time.monotonic()+15`."""
    text = _j("DRIVER = '''\n", "deadline=time.monot", "onic()+15; capacity=1\n", "'''\n")
    root = _tree(tmp_path, {"tests/test_inventory_runtime.py": text})
    assert [(h.kind, h.value) for h in ti.scan_tree(root, "tests")] == [("str-deadline", 15.0)]


def _literal_test(note: str) -> str:
    return _j("import subprocess\n", "def test_x():\n",
              "    subprocess.run(['true'], timeout=", DOT, "3)", note, "\n")


def test_check_is_red_on_a_new_unannotated_literal(tmp_path: Path) -> None:
    root = _tree(tmp_path, {"tests/test_x.py": _literal_test("")})
    assert ti.main(["check", "--root", str(root)]) == 1


def test_check_is_green_on_an_annotated_must_fire_literal(tmp_path: Path) -> None:
    root = _tree(tmp_path, {"tests/test_x.py": _literal_test(_j("  # tim", "ing: must-fire - the fake blocks"))})
    ok, lines = ti.check(root, root / "ci" / "timing-baseline.txt")
    assert ok, lines


@pytest.mark.parametrize("note", [
    _j("  # tim", "ing: must-fire"),          # no reason at all
    _j("  # tim", "ing: must-fire - "),       # an empty reason
    _j("  # tim", "ing: must-beat - setup"),  # must-beat has no sub-second literal
])
def test_check_is_red_on_a_bad_annotation(tmp_path: Path, note: str) -> None:
    root = _tree(tmp_path, {"tests/test_x.py": _literal_test(note)})
    ok, lines = ti.check(root, root / "ci" / "timing-baseline.txt")
    assert not ok and any(line.startswith("TIMING_ANNOTATION_ERROR:") for line in lines), lines


def test_check_is_green_on_the_exact_baseline_and_red_when_it_is_stale(tmp_path: Path) -> None:
    entry = "tests/test_x.py::test_x::kw::0.3\n"
    root = _tree(tmp_path, {"tests/test_x.py": _literal_test("")}, baseline=entry)
    assert ti.check(root, root / "ci" / "timing-baseline.txt")[0]
    # The member is fixed but its entry stays: a freed slot must not be reusable.
    (root / "tests" / "test_x.py").write_text("def test_x():\n    pass\n", encoding="utf-8")
    ok, lines = ti.check(root, root / "ci" / "timing-baseline.txt")
    assert not ok and any(line.startswith("TIMING_STALE: tests/test_x.py::test_x::kw::0.3") for line in lines)


def test_a_second_occurrence_is_new_even_when_one_is_baselined(tmp_path: Path) -> None:
    """Entries count per occurrence, so a baselined literal does not license a
    copy of itself in the same function."""
    body = _j("import subprocess\n", "def test_x():\n",
              "    subprocess.run(['true'], timeout=", DOT, "3)\n",
              "    subprocess.run(['true'], timeout=", DOT, "3)\n")
    root = _tree(tmp_path, {"tests/test_x.py": body}, baseline="tests/test_x.py::test_x::kw::0.3\n")
    ok, lines = ti.check(root, root / "ci" / "timing-baseline.txt")
    assert not ok and sum(line.startswith("TIMING_NEW:") for line in lines) == 1


def test_an_unparsable_file_is_an_error_never_a_clean_scan(tmp_path: Path) -> None:
    root = _tree(tmp_path, {"tests/test_broken.py": "def (:\n"})
    assert ti.main(["check", "--root", str(root)]) == 2


def test_a_missing_baseline_is_an_error_never_an_empty_one(tmp_path: Path) -> None:
    root = _tree(tmp_path, {"tests/test_x.py": "def test_x():\n    pass\n"})
    (root / "ci" / "timing-baseline.txt").unlink()
    assert ti.main(["check", "--root", str(root)]) == 2


def test_the_committed_tree_passes_its_own_ratchet() -> None:
    """The real gate, run here too, so a local test run catches baseline drift."""
    ok, lines = ti.check(ROOT, ROOT / ti.DEFAULT_BASELINE)
    assert ok, "\n".join(lines)


# --------------------------------------------- counter-model pass 1 (#758): forms that dodged the ratchet

@pytest.mark.parametrize("source", [
    # Column names as a tuple, not one string.
    _j("import pytest\n", "@pytest.mark.parametrize(('mode', 'settle'), [('x', ", DOT, "3)])\n",
       "def test_x(mode, settle):\n", "    pass\n"),
    # A pytest.param() row.
    _j("import pytest\n", "@pytest.mark.parametrize('settle', [pytest.param(", DOT, "3, id='fast')])\n",
       "def test_x(settle):\n", "    pass\n"),
    # A typed module constant.
    _j("POLL_INTERVAL: float = ", DOT, "3\n", "def test_x():\n", "    pass\n"),
], ids=["tuple-columns", "pytest-param", "annotated-constant"])
def test_review_forms_are_new_to_an_empty_baseline(tmp_path: Path, source: str) -> None:
    """Reviewer's exact inputs: each passed an empty baseline before the fix."""
    root = _tree(tmp_path, {"tests/test_x.py": source})
    ok, lines = ti.check(root, root / "ci" / "timing-baseline.txt")
    assert not ok and any(line.startswith("TIMING_NEW: tests/test_x.py:") for line in lines), lines


def test_a_bad_annotation_on_a_pytest_param_row_is_still_an_error(tmp_path: Path) -> None:
    source = _j("import pytest\n", "@pytest.mark.parametrize('settle', [pytest.param(", DOT, "3)])",
                "  # tim", "ing: must-fire\n", "def test_x(settle):\n", "    pass\n")
    root = _tree(tmp_path, {"tests/test_x.py": source})
    ok, lines = ti.check(root, root / "ci" / "timing-baseline.txt")
    assert not ok and any(line.startswith("TIMING_ANNOTATION_ERROR:") for line in lines), lines


def test_an_empty_population_is_an_error_never_a_clean_scan(tmp_path: Path) -> None:
    """Reviewer's exact input: an empty tests/ with an empty baseline read ok.
    (A tests/ whose files hold no bound is still ok: the clean twin above.)"""
    root = _tree(tmp_path, {})
    (root / "tests").mkdir()
    assert ti.main(["check", "--root", str(root)]) == 2
