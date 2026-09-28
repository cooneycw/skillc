#!/usr/bin/env python3
"""Prepares finish-close-ref's degraded arm from a real claude-power-pack
checkout at the pinned revision (issue #150-B3b).

CPP's own LICENSE ("## Scope") does not cover `codex/skills/`, so this repo
never vendors that text - `degrade.toml` commits only facts ABOUT the five
files (their sha256 at the pinned revision, exactly what to delete or
replace, and the sha256 the result must have), never their content. This
script turns those facts into the five prepared files, given a real checkout
to read them from - it is a runbook step, not something CI or this module's
own tests run against real CPP text (`tests/test_degraded_prepare.py` uses a
SYNTHETIC mini-checkout instead; see that file's own module docstring).

The degradation removes what an agent could READ that tells it "a
close/fix/resolve keyword next to #N still closes the issue, regardless of
grammar" - not CPP's merge tooling. `guard_negated_close_keywords` and every
PROSE statement of the rule are deleted, including inside the retained
`guard_incidental_close_keywords` region; `guard_incidental_close_keywords`
itself (and the doc lines about the ONE OTHER retained flag,
`--allow-base-move`) is kept CODE-INTACT, because that guard still runs at
merge time and disabling it would change behaviour, not just text.
`_is_incidental_close_match`'s own negation-awareness (it must decline a
negated match, deferring to the other guard) is retained code that
necessarily still mentions the removed guard by name in two comment lines -
`residual_lines` names those exact lines, by content hash, as the only thing
`rule_pattern` may still match after preparation (DEGRADATION.md's own
"Residual honesty check" section says plainly that an agent reading the
retained guard's control flow could still infer the rule from its CODE,
which this script does not and cannot remove).

For each declared location:
  1. sha256 of the checkout's file must match `original_sha256` - refuses
     otherwise, since the pinned revision, not "whatever is checked out
     today", is what every range/hash below was computed against.
  2. Each declared `replacements` entry: the line's CURRENT content must hash
     to `line_sha256` (staleness check, independent of the whole-file hash),
     and `old` must occur in it EXACTLY once (never zero - nothing to
     replace; never two-plus - which occurrence?) before being swapped for
     `new`.
  3. `.sh` locations only: every non-comment, non-blank ORIGINAL line inside
     a declared `delete_ranges` span must have its content hash in
     `expected_removed_code_lines` - refused by name otherwise (and the
     reverse: a declared hash that is not actually removed is refused too).
     A markdown location has no such field - its whole declared range IS the
     removed prose, with no separate code/comment distinction to protect.
     This is the check that keeps `delete_ranges` honest about removing only
     PROSE plus the short, separately-named list of real code lines - a
     range that swallows an undeclared code line fails here even though
     every hash below would still happen to match by coincidence.
  4. Delete the declared 1-indexed inclusive `delete_ranges` line ranges,
     applied to the ORIGINAL line numbers (replacements happen first, above,
     also against original numbers - the two never renumber each other since
     the declared script locations don't overlap).
  5. sha256 of the result must match `result_sha256`.
  6. A `.sh` result must still pass `bash -n`.
  7. `rule_pattern` must match the ORIGINAL text at least once - the positive
     control.
  8. `rule_pattern` matches against the PREPARED text are checked one by one:
     each matched line's own content hash must be in `residual_lines`, or
     preparation is refused naming the line. This is an ALLOWLIST of exact
     lines, never a loosened pattern, so a genuinely NEW statement of the
     rule - one that slips in some other way - still fails.
  9. Every hash in `must_still_contain` (the retained exit-6/base-move
     bullet, the retained guard's own definition AND call-site lines, ...)
     must appear somewhere in the prepared text - catching a range that
     swallowed more than intended.

Once every declared file passes 1-9, the WHOLE checkout's `codex/skills/`
tree, excluding the five declared files, is scanned for `rule_pattern` too -
proving the rule is not ALSO stated somewhere this run never touches, which
per-file checks cannot see on their own. No residual allowlist applies there.

Only then are the five prepared files written to `--out DIR`, mirroring
`<skill>/<path>`, and the exact `skillc degrade-subject` command printed.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shlex
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import cast

HERE = Path(__file__).resolve().parent
DEFAULT_DEGRADE_FILE = HERE / "degrade.toml"


class PrepareRefused(Exception):
    pass


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_line(line: str) -> str:
    return hashlib.sha256(line.encode("utf-8")).hexdigest()


def _apply_replacements(text: str, replacements: list[dict[str, object]], label: str) -> str:
    lines = text.split("\n")
    for rep in replacements:
        lineno = cast(int, rep["line"])
        old, new = str(rep["old"]), str(rep["new"])
        expect_hash = str(rep["line_sha256"])
        if not (1 <= lineno <= len(lines)):
            raise PrepareRefused(f"{label}: replacement line {lineno} is out of bounds")
        line = lines[lineno - 1]
        if _sha256_line(line) != expect_hash:
            raise PrepareRefused(f"{label}: line {lineno} does not match its declared line_sha256 - the file has drifted")
        count = line.count(old)
        if count != 1:
            raise PrepareRefused(f"{label}: line {lineno}: {old!r} occurs {count} time(s), want exactly 1")
        lines[lineno - 1] = line.replace(old, new, 1)
    return "\n".join(lines)


def _delete_ranges(text: str, ranges: list[list[int]], label: str) -> str:
    """1-indexed inclusive `[start, end]` line ranges, all removed together -
    indexed against the ORIGINAL line list once, so later ranges are
    unaffected by earlier ones removing lines."""
    lines = text.split("\n")
    drop: set[int] = set()
    for start, end in ranges:
        if start < 1 or end < start or end > len(lines):
            raise PrepareRefused(f"{label}: range [{start}, {end}] is out of bounds for a {len(lines)}-line file")
        drop.update(range(start, end + 1))
    return "\n".join(line for i, line in enumerate(lines, start=1) if i not in drop)


def _check_bash_syntax(text: str, label: str) -> None:
    result = subprocess.run(["bash", "-n", "-c", text], capture_output=True, text=True, timeout=10, check=False)
    if result.returncode != 0:
        raise PrepareRefused(f"{label}: prepared text failed `bash -n`: {result.stderr.strip()}")


def _check_only_declared_code_was_removed(
    original_text: str, ranges: list[list[int]], location: dict[str, object], label: str,
) -> None:
    """`delete_ranges` is meant to remove PROSE (comments) plus a short,
    separately-named list of real code lines (the removed guard itself, its
    call site, its CLI flag). This is the independent check that a range
    never swallows anything else: every non-comment, non-blank ORIGINAL line
    that falls inside any declared range must have its exact content hash in
    `expected_removed_code_lines` - refused by name otherwise. The reverse
    also refuses: a declared hash that is NOT actually removed is a stale or
    over-broad declaration, not a smaller problem than an undeclared one."""
    expected = set(cast("list[str]", location.get("expected_removed_code_lines", [])))
    lines = original_text.split("\n")
    drop: set[int] = set()
    for start, end in ranges:
        drop.update(range(start, end + 1))
    actual: set[str] = set()
    for lineno in sorted(drop):
        line = lines[lineno - 1]
        stripped = line.lstrip()
        if stripped == "" or stripped.startswith("#"):
            continue
        line_hash = _sha256_line(line)
        actual.add(line_hash)
        if line_hash not in expected:
            raise PrepareRefused(
                f"{label}: line {lineno} is CODE (not a comment) and is not a declared "
                f"expected_removed_code_lines entry: {line!r}"
            )
    stale = expected - actual
    if stale:
        raise PrepareRefused(f"{label}: expected_removed_code_lines declares {sorted(stale)} which delete_ranges does not actually remove")


def load_degrade_file(path: Path) -> dict[str, object]:
    with path.open("rb") as fh:
        return tomllib.load(fh)


def prepare_one(checkout: Path, location: dict[str, object], rule_pattern: re.Pattern[str]) -> tuple[Path, str]:
    """Returns `(skill/path relative location, prepared text)`."""
    skill, rel = str(location["skill"]), str(location["path"])
    label = f"{skill}/{rel}"
    source = checkout / "codex" / "skills" / skill / rel
    try:
        original_bytes = source.read_bytes()
    except OSError as exc:
        raise PrepareRefused(f"{label}: could not read {source}: {exc}") from exc
    original_text = original_bytes.decode("utf-8")

    if _sha256_bytes(original_bytes) != str(location["original_sha256"]):
        raise PrepareRefused(
            f"{label}: original sha256 does not match degrade.toml - "
            "the checkout is not at the pinned revision, or the file has moved"
        )
    if not rule_pattern.search(original_text):
        raise PrepareRefused(f"{label}: positive control failed - rule_pattern does not match the ORIGINAL text")

    replacements = cast("list[dict[str, object]]", location.get("replacements", []))
    text = _apply_replacements(original_text, replacements, label)
    ranges = [list(r) for r in cast("list[list[int]]", location["delete_ranges"])]
    if rel.endswith(".sh"):
        # Comment-vs-code only means something for a script; a markdown
        # location's entire declared range IS the removed prose, with no
        # separate "code" concept to protect - `expected_removed_code_lines`
        # is a `.sh`-only field for exactly that reason.
        _check_only_declared_code_was_removed(original_text, ranges, location, label)
    prepared_text = _delete_ranges(text, ranges, label)
    prepared_bytes = prepared_text.encode("utf-8")

    if _sha256_bytes(prepared_bytes) != str(location["result_sha256"]):
        raise PrepareRefused(f"{label}: prepared sha256 does not match degrade.toml - the declared edits produced something else")
    if rel.endswith(".sh"):
        _check_bash_syntax(prepared_text, label)

    residual_allowlist = set(cast("list[str]", location.get("residual_lines", [])))
    for lineno, line in enumerate(prepared_text.split("\n"), start=1):
        if rule_pattern.search(line) and _sha256_line(line) not in residual_allowlist:
            raise PrepareRefused(f"{label}: line {lineno} still states the rule and is not a declared residual: {line!r}")

    must_contain = set(cast("list[str]", location.get("must_still_contain", [])))
    present = {_sha256_line(line) for line in prepared_text.split("\n")}
    missing = must_contain - present
    if missing:
        raise PrepareRefused(f"{label}: a declared must_still_contain line is gone (over-wide range?): {sorted(missing)}")

    return Path(skill) / rel, prepared_text


def check_tree_is_otherwise_clean(
    checkout: Path, locations: list[dict[str, object]], rule_pattern: re.Pattern[str],
) -> None:
    skills_root = checkout / "codex" / "skills"
    declared = {(str(loc["skill"]), str(loc["path"])) for loc in locations}
    hits: list[str] = []
    for path in sorted(skills_root.rglob("*")):
        if not path.is_file():
            continue
        rel_to_root = path.relative_to(skills_root)
        skill = rel_to_root.parts[0]
        rel = str(Path(*rel_to_root.parts[1:]))
        if (skill, rel) in declared:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if rule_pattern.search(text):
            hits.append(str(path.relative_to(checkout)))
    if hits:
        raise PrepareRefused("the rule is still stated outside the five declared files: " + ", ".join(hits))


#: The out-dir placeholder in the printed command's argv: prepare.py's own
#: `--out` holds the five prepared FILES; `degrade-subject --out` holds
#: `receipt.json` and the persisted degraded tree - a different directory
#: the operator chooses, which this script has no way to know.
DEGRADE_OUT_PLACEHOLDER = "<DEGRADE_OUT_DIR>"


def degrade_subject_command(subject: str, checkout: Path, prepared: list[tuple[Path, Path]]) -> list[str]:
    """The exact `skillc degrade-subject` argv this run's output feeds -
    `--checkout` (reusing the SAME real checkout this script read from,
    never `--revision`, which would waste a second clone this script's own
    caller already has) plus one `--override-file SKILL:PATH=FILE` per
    prepared file, matching `skillc/cli.py`'s real parser
    (`tests/test_degraded_prepare.py::test_printed_command_parses_with_skillcs_own_parser`
    feeds this straight to `build_parser().parse_args`, so a flag rename
    there fails this module's own tests, not only a human copy-pasting it)."""
    argv = ["skillc", "degrade-subject", subject, "--checkout", str(checkout)]
    for rel_path, out_path in prepared:
        skill = rel_path.parts[0]
        argv.extend(["--override-file", f"{skill}:{Path(*rel_path.parts[1:])}={out_path}"])
    argv.extend(["--out", DEGRADE_OUT_PLACEHOLDER])
    return argv


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--checkout", required=True, type=Path, help="a claude-power-pack checkout at the pinned revision")
    parser.add_argument("--out", required=True, type=Path, help="directory to write the five prepared files into")
    parser.add_argument("--degrade-file", type=Path, default=DEFAULT_DEGRADE_FILE)
    parser.add_argument("--subject", default="cpp-codex", help="the skillc subject name the printed command targets")
    args = parser.parse_args(argv)

    data = load_degrade_file(args.degrade_file)
    source = data["source"]
    assert isinstance(source, dict)
    rule_pattern = re.compile("|".join(str(p) for p in source["rule_patterns"]), re.IGNORECASE)  # type: ignore[union-attr]
    locations = data["locations"]
    assert isinstance(locations, list)

    try:
        prepared = [prepare_one(args.checkout, loc, rule_pattern) for loc in locations]
        check_tree_is_otherwise_clean(args.checkout, locations, rule_pattern)
    except PrepareRefused as exc:
        print(f"prepare.py: refused: {exc}", file=sys.stderr)
        return 1

    written: list[tuple[Path, Path]] = []
    for rel_path, text in prepared:
        out_path = args.out / rel_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")
        written.append((rel_path, out_path))

    print("prepare.py: wrote", len(prepared), "file(s) to", args.out)
    print(shlex.join(degrade_subject_command(args.subject, args.checkout, written)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
