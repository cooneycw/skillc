"""Tests for finish-close-ref's degraded arm builder (issue #150-B3b).

Every test here runs against the SYNTHETIC mini-checkout committed at
`tests/fixtures/degraded-prepare/` (fabricated "frobnicator" content, never
real claude-power-pack text) - `prepare.py`'s own module docstring states why
real CPP text is never read here: CPP's LICENSE does not cover
`codex/skills/`, so the real revision is only ever read at runbook time,
outside this suite, by an operator with a real checkout.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import shutil
import sys
import tomllib
from pathlib import Path
from types import ModuleType

import pytest

TASK = Path(__file__).resolve().parent.parent / "evals" / "level1" / "finish-close-ref"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "degraded-prepare"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"degraded_{name}", TASK / "degraded" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


prepare = _load("prepare")


def _line_sha256(line: str) -> str:
    return hashlib.sha256(line.encode("utf-8")).hexdigest()


def _checkout(tmp_path: Path) -> Path:
    dest = tmp_path / "checkout"
    shutil.copytree(FIXTURE / "checkout", dest)
    return dest


def _load_fixture_data() -> dict[str, object]:
    with (FIXTURE / "degrade.toml").open("rb") as fh:
        return tomllib.load(fh)


# --------------------------------------------------------------- green case


def test_prepare_writes_the_two_prepared_files_and_prints_the_override_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    checkout = _checkout(tmp_path)
    out = tmp_path / "out"
    rc = prepare.main(["--checkout", str(checkout), "--degrade-file", str(FIXTURE / "degrade.toml"), "--out", str(out)])
    assert rc == 0

    md = (out / "greet" / "reference.md").read_text(encoding="utf-8")
    assert "frobnicator" not in md.lower()
    sh = (out / "greet" / "scripts" / "tool.sh").read_text(encoding="utf-8")
    assert "guard_frobnicator_reversal()" not in sh  # the function definition is gone
    assert "guard_frobnicator_reversal" in sh  # the residual comment mention survives
    assert "check_widget_state" in sh  # the retained function is untouched

    printed = capsys.readouterr().out
    assert f"skillc degrade-subject cpp-codex --checkout {checkout}" in printed
    assert f"--override-file greet:reference.md={out / 'greet' / 'reference.md'}" in printed
    assert f"--override-file greet:scripts/tool.sh={out / 'greet' / 'scripts' / 'tool.sh'}" in printed


def test_printed_command_parses_with_skillcs_own_parser(tmp_path: Path) -> None:
    """Issue #150-B3b review, item 3: the printed `skillc degrade-subject`
    invocation must be built from the SAME flags `skillc/cli.py`'s real
    parser accepts, not a hand-maintained guess that can drift when the CLI
    changes. Calls `degrade_subject_command` directly (what `main` prints,
    shlex-joined) and feeds its argv straight to `skillc.cli.build_parser()`
    - a renamed or removed flag fails HERE, not only in a human's hands."""
    checkout = _checkout(tmp_path)
    out = tmp_path / "out"
    rc = prepare.main(["--checkout", str(checkout), "--degrade-file", str(FIXTURE / "degrade.toml"), "--out", str(out)])
    assert rc == 0

    prepared = [
        (Path("greet/reference.md"), out / "greet" / "reference.md"),
        (Path("greet/scripts/tool.sh"), out / "greet" / "scripts" / "tool.sh"),
    ]
    argv = prepare.degrade_subject_command("cpp-codex", checkout, prepared)
    assert argv[0] == "skillc" and argv[1] == "degrade-subject"

    from skillc import cli
    args = cli.build_parser().parse_args(argv[1:])
    assert args.command == "degrade-subject"
    assert args.subject == "cpp-codex"
    assert args.checkout == str(checkout)
    assert args.revision is None
    assert len(args.override_file) == 2
    assert args.out == prepare.DEGRADE_OUT_PLACEHOLDER


def test_prepared_script_is_valid_bash(tmp_path: Path) -> None:
    checkout = _checkout(tmp_path)
    out = tmp_path / "out"
    rc = prepare.main(["--checkout", str(checkout), "--degrade-file", str(FIXTURE / "degrade.toml"), "--out", str(out)])
    assert rc == 0
    import subprocess
    result = subprocess.run(
        ["bash", "-n", str(out / "greet" / "scripts" / "tool.sh")], capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr


def test_general_fact_pattern_hits_original_and_misses_result(tmp_path: Path) -> None:
    """Issue #150-B3b review, item 5: a rule_patterns entry scoped to the
    GENERAL fact ("regardless of ..."), not an identifier, must hit the
    ORIGINAL (reference.md's own paragraph states it) and miss the PREPARED
    text (that whole paragraph is deleted) - proving the mechanical check
    sees this broader class too, the same way the real degrade.toml's own
    two "regardless of"/"does not care" patterns were verified against the
    real pinned revision (not reproduced here - no real CPP text in tests)."""
    checkout = _checkout(tmp_path)
    data = _load_fixture_data()
    pattern = re.compile("regardless of surrounding words", re.IGNORECASE)
    assert "regardless of surrounding words" in data["source"]["rule_patterns"]  # type: ignore[index]

    original = (checkout / "codex" / "skills" / "greet" / "reference.md").read_text(encoding="utf-8")
    assert pattern.search(original)

    out = tmp_path / "out"
    rc = prepare.main(["--checkout", str(checkout), "--degrade-file", str(FIXTURE / "degrade.toml"), "--out", str(out)])
    assert rc == 0
    prepared = (out / "greet" / "reference.md").read_text(encoding="utf-8")
    assert not pattern.search(prepared)


# ---------------------------------------------------------- red case: hash


def test_a_modified_original_refuses_with_no_files_written(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Red case: the checkout is not at the pinned revision (or the file
    moved/changed) - refused before anything is written, never a silent
    degrade against the wrong bytes."""
    checkout = _checkout(tmp_path)
    md_path = checkout / "codex" / "skills" / "greet" / "reference.md"
    md_path.write_text(md_path.read_text(encoding="utf-8") + "\nan extra line\n", encoding="utf-8")
    out = tmp_path / "out"

    rc = prepare.main(["--checkout", str(checkout), "--degrade-file", str(FIXTURE / "degrade.toml"), "--out", str(out)])

    assert rc == 1
    assert "original sha256 does not match" in capsys.readouterr().err
    assert not out.exists()


# --------------------------------------------- red case: deletion insufficient


def test_a_range_too_narrow_to_remove_the_rule_is_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Red case: the declared range only deletes PART of the stated rule, so
    the grep still hits after deletion - must refuse naming the surviving
    line, never silently accept a partial removal."""
    checkout = _checkout(tmp_path)
    data = _load_fixture_data()
    locations = data["locations"]
    assert isinstance(locations, list)
    md_loc = next(loc for loc in locations if loc["path"] == "reference.md")  # type: ignore[index]
    # Deletes the paragraph's last two lines but leaves its first ("The
    # frobnicator ALWAYS reverses widgets"), which alone still matches
    # rule_patterns.
    md_loc["delete_ranges"] = [[6, 7]]

    # The result hash no longer matches what a [5,7]-deletion produces, so
    # this red case would otherwise fail at the WRONG check (result_sha256)
    # rather than the one under test - recompute it here to isolate the check.
    original = (checkout / "codex" / "skills" / "greet" / "reference.md").read_text(encoding="utf-8")
    lines = original.split("\n")
    prepared = "\n".join(l for i, l in enumerate(lines, 1) if i not in (6, 7))
    md_loc["result_sha256"] = hashlib.sha256(prepared.encode("utf-8")).hexdigest()

    degrade_file = tmp_path / "degrade.toml"
    _write_toml(degrade_file, data)
    out = tmp_path / "out"

    rc = prepare.main(["--checkout", str(checkout), "--degrade-file", str(degrade_file), "--out", str(out)])

    assert rc == 1
    err = capsys.readouterr().err
    assert "still states the rule and is not a declared residual" in err
    assert not out.exists()


# ------------------------------------------------- red case: sixth location


def test_a_sixth_file_stating_the_rule_is_refused_by_the_whole_tree_check(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """Red case: a file OUTSIDE the five (well, two, in this fixture)
    declared locations still states the rule - per-file checks cannot see
    this; only the whole-tree scan does."""
    checkout = _checkout(tmp_path)
    tainted = checkout / "codex" / "skills" / "other" / "reference.md"
    tainted.write_text(
        tainted.read_text(encoding="utf-8") + "\nReminder: guard_frobnicator_reversal still applies here too.\n",
        encoding="utf-8",
    )
    out = tmp_path / "out"

    rc = prepare.main(["--checkout", str(checkout), "--degrade-file", str(FIXTURE / "degrade.toml"), "--out", str(out)])

    assert rc == 1
    err = capsys.readouterr().err
    assert "still stated outside the five declared files" in err
    assert "other/reference.md" in err
    assert not out.exists()


def test_the_clean_fixture_tree_passes_the_whole_tree_check(tmp_path: Path) -> None:
    """Positive control for the test above: proves the whole-tree check does
    not fire on the UNMODIFIED fixture - so the red case above is failing
    because of the planted taint, not because the check always refuses."""
    checkout = _checkout(tmp_path)
    out = tmp_path / "out"
    rc = prepare.main(["--checkout", str(checkout), "--degrade-file", str(FIXTURE / "degrade.toml"), "--out", str(out)])
    assert rc == 0


# --------------------------------------------- red case: replacement count


@pytest.mark.parametrize("mutation", ["duplicate", "remove"])
def test_a_replacement_whose_old_substring_is_not_exactly_one_occurrence_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], mutation: str,
) -> None:
    """Red case (issue #150-B3b review, item 3): `old` must occur EXACTLY
    once on the declared line - zero occurrences means nothing to replace
    (the line drifted), two-plus means the replacement is ambiguous about
    which occurrence was intended. Both must refuse, never guess."""
    checkout = _checkout(tmp_path)
    sh_path = checkout / "codex" / "skills" / "greet" / "scripts" / "tool.sh"
    lines = sh_path.read_text(encoding="utf-8").split("\n")
    if mutation == "duplicate":
        lines[1] = lines[1] + " [--allow-frobnicator-reversal] "
    else:
        lines[1] = lines[1].replace("[--allow-frobnicator-reversal] ", "")
    sh_path.write_text("\n".join(lines), encoding="utf-8")

    data = _load_fixture_data()
    locations = data["locations"]
    assert isinstance(locations, list)
    sh_loc = next(loc for loc in locations if loc["path"] == "scripts/tool.sh")  # type: ignore[index]
    # The line drifted on purpose, so its hash must be recomputed to reach
    # the check under test (occurrence count) rather than refusing earlier
    # on the line_sha256 staleness check.
    reps = sh_loc["replacements"]  # type: ignore[index]
    assert isinstance(reps, list)
    reps[0]["line_sha256"] = _line_sha256(lines[1])  # type: ignore[index]
    sh_loc["original_sha256"] = hashlib.sha256(sh_path.read_bytes()).hexdigest()

    degrade_file = tmp_path / "degrade.toml"
    _write_toml(degrade_file, data)
    out = tmp_path / "out"

    rc = prepare.main(["--checkout", str(checkout), "--degrade-file", str(degrade_file), "--out", str(out)])

    assert rc == 1
    err = capsys.readouterr().err
    assert "occurs" in err and "want exactly 1" in err
    assert not out.exists()


def test_a_replacement_line_that_drifted_from_its_declared_hash_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """Red case: the replacement line's OWN content no longer matches
    `line_sha256`, even though the whole-file hash check has not run yet for
    this location (it is a separate, earlier fact from `original_sha256`)."""
    checkout = _checkout(tmp_path)
    data = _load_fixture_data()
    locations = data["locations"]
    assert isinstance(locations, list)
    sh_loc = next(loc for loc in locations if loc["path"] == "scripts/tool.sh")  # type: ignore[index]
    reps = sh_loc["replacements"]  # type: ignore[index]
    assert isinstance(reps, list)
    reps[0]["line_sha256"] = "0" * 64

    degrade_file = tmp_path / "degrade.toml"
    _write_toml(degrade_file, data)
    out = tmp_path / "out"

    rc = prepare.main(["--checkout", str(checkout), "--degrade-file", str(degrade_file), "--out", str(out)])

    assert rc == 1
    assert "does not match its declared line_sha256" in capsys.readouterr().err
    assert not out.exists()


# ------------------------------------------- red case: must_still_contain


def test_a_range_that_swallows_a_preserved_line_is_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Red case: an over-wide delete_range removes the retained
    check_widget_state function too - must_still_contain catches this even
    though nothing about the rule pattern itself would notice."""
    checkout = _checkout(tmp_path)
    data = _load_fixture_data()
    locations = data["locations"]
    assert isinstance(locations, list)
    sh_loc = next(loc for loc in locations if loc["path"] == "scripts/tool.sh")  # type: ignore[index]
    sh_loc["delete_ranges"] = [[5, 5], [8, 11], [21, 37], [39, 39]]  # widened: swallows check_widget_state too

    original = (checkout / "codex" / "skills" / "greet" / "scripts" / "tool.sh").read_text(encoding="utf-8")
    lines = original.split("\n")
    lines[1] = lines[1].replace("[--allow-frobnicator-reversal] ", "")
    drop = set(range(5, 6)) | set(range(8, 12)) | set(range(21, 38)) | set(range(39, 40))
    prepared = "\n".join(l for i, l in enumerate(lines, 1) if i not in drop)
    sh_loc["result_sha256"] = hashlib.sha256(prepared.encode("utf-8")).hexdigest()
    # Declare the wider removal as "expected" too, so check (3) - a
    # different, EARLIER check for a related but distinct defect - does not
    # mask the one this test is actually exercising (must_still_contain).
    sh_loc["expected_removed_code_lines"] = sorted({
        _line_sha256(lines[n - 1]) for n in sorted(drop) if lines[n - 1].lstrip() and not lines[n - 1].lstrip().startswith("#")
    })

    degrade_file = tmp_path / "degrade.toml"
    _write_toml(degrade_file, data)
    out = tmp_path / "out"

    rc = prepare.main(["--checkout", str(checkout), "--degrade-file", str(degrade_file), "--out", str(out)])

    assert rc == 1
    assert "a declared must_still_contain line is gone" in capsys.readouterr().err
    assert not out.exists()


# --------------------------------------------------- red case: bash syntax


def test_a_delete_range_that_breaks_bash_syntax_is_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Red case: a range that deletes only the guard's closing brace (not the
    whole function) leaves invalid bash - `bash -n` catches it even though
    every hash still matches, since the hashes are computed from the same
    broken deletion."""
    checkout = _checkout(tmp_path)
    data = _load_fixture_data()
    locations = data["locations"]
    assert isinstance(locations, list)
    sh_loc = next(loc for loc in locations if loc["path"] == "scripts/tool.sh")  # type: ignore[index]
    sh_loc["delete_ranges"] = [[5, 5], [8, 11], [30, 30], [39, 39]]  # only the guard's closing "}" line

    original = (checkout / "codex" / "skills" / "greet" / "scripts" / "tool.sh").read_text(encoding="utf-8")
    lines = original.split("\n")
    lines[1] = lines[1].replace("[--allow-frobnicator-reversal] ", "")
    drop = {5, 8, 9, 10, 11, 30, 39}
    prepared = "\n".join(l for i, l in enumerate(lines, 1) if i not in drop)
    sh_loc["result_sha256"] = hashlib.sha256(prepared.encode("utf-8")).hexdigest()
    # Narrower removal than the fixture's own declaration (the guard's body,
    # lines 23-29, is NOT removed by this mutated range) - declare exactly
    # what IS removed, so check (3)'s stale-declaration half does not mask
    # `bash -n`, the check this test is actually exercising.
    sh_loc["expected_removed_code_lines"] = sorted({
        _line_sha256(lines[n - 1]) for n in sorted(drop) if lines[n - 1].lstrip() and not lines[n - 1].lstrip().startswith("#")
    })
    # This mutation also leaves the rule stated (the guard body/header
    # survive) - the residual check would refuse too, for a different,
    # equally real reason. Dropping the allowlist here isolates `bash -n` as
    # the check this test is actually exercising: confirmed by hand that with
    # residual_lines intact, `bash -n` still fires FIRST (it runs before the
    # residual scan), so this drop only removes a second, redundant refusal.
    sh_loc.pop("residual_lines", None)

    degrade_file = tmp_path / "degrade.toml"
    _write_toml(degrade_file, data)
    out = tmp_path / "out"

    rc = prepare.main(["--checkout", str(checkout), "--degrade-file", str(degrade_file), "--out", str(out)])

    assert rc == 1
    assert "bash -n" in capsys.readouterr().err
    assert not out.exists()


# ------------------------------------ red case: undeclared code in a range


def test_a_range_that_deletes_undeclared_code_in_the_retained_region_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """Red case (issue #150-B3b review, item 4): a range widened to also
    remove part of the RETAINED check_widget_state function - without also
    widening expected_removed_code_lines to match. This is the failure mode
    the field exists to catch: a range that swallows code nothing declared,
    inside the region that is supposed to keep every code line."""
    checkout = _checkout(tmp_path)
    data = _load_fixture_data()
    locations = data["locations"]
    assert isinstance(locations, list)
    sh_loc = next(loc for loc in locations if loc["path"] == "scripts/tool.sh")  # type: ignore[index]
    sh_loc["delete_ranges"] = [[5, 5], [8, 11], [21, 35], [39, 39]]  # swallows check_widget_state() { itself
    # expected_removed_code_lines deliberately LEFT AS THE FIXTURE DECLARES
    # IT - the whole point is that nothing was updated to expect this.

    degrade_file = tmp_path / "degrade.toml"
    _write_toml(degrade_file, data)
    out = tmp_path / "out"

    rc = prepare.main(["--checkout", str(checkout), "--degrade-file", str(degrade_file), "--out", str(out)])

    assert rc == 1
    err = capsys.readouterr().err
    assert "is CODE (not a comment) and is not a declared expected_removed_code_lines entry" in err
    assert "check_widget_state" in err
    assert not out.exists()


# --------------------------------------------------------------- helpers


def _write_toml(path: Path, data: dict[str, object]) -> None:
    """A tiny hand-rolled TOML writer for exactly this fixture's shape
    (strings, ints, lists of strings/ints, and one level of table arrays) -
    `tomllib` is read-only (stdlib), and pulling in a third-party writer for
    a handful of mutated test fixtures is not worth the dependency."""

    def scalar(v: object) -> str:
        if isinstance(v, str):
            return json.dumps(v)
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, int):
            return str(v)
        raise TypeError(f"unsupported scalar {v!r}")

    def array(v: list[object]) -> str:
        if v and isinstance(v[0], list):
            return "[" + ", ".join(array(item) for item in v) + "]"  # type: ignore[arg-type]
        if v and isinstance(v[0], dict):
            return "[" + ", ".join(inline_table(item) for item in v) + "]"  # type: ignore[arg-type]
        return "[" + ", ".join(scalar(item) for item in v) + "]"

    def inline_table(d: dict[str, object]) -> str:
        return "{ " + ", ".join(f"{k} = {scalar(v) if not isinstance(v, list) else array(v)}" for k, v in d.items()) + " }"

    lines: list[str] = []
    source = data["source"]
    assert isinstance(source, dict)
    lines.append("[source]")
    for k, v in source.items():
        lines.append(f"{k} = {array(v) if isinstance(v, list) else scalar(v)}")
    lines.append("")

    locations = data["locations"]
    assert isinstance(locations, list)
    for loc in locations:
        assert isinstance(loc, dict)
        lines.append("[[locations]]")
        for k, v in loc.items():
            lines.append(f"{k} = {array(v) if isinstance(v, list) else scalar(v)}")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def test_write_toml_helper_round_trips_the_committed_fixture(tmp_path: Path) -> None:
    """The hand-rolled writer above is itself only trustworthy if it
    round-trips the real fixture file - this is that check, not a test of
    prepare.py."""
    data = _load_fixture_data()
    out = tmp_path / "roundtrip.toml"
    _write_toml(out, data)
    with out.open("rb") as fh:
        reparsed = tomllib.load(fh)
    assert reparsed == data
