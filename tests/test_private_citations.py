"""Guard: no private fleet-message-number or worker-name citation in tracked
files (issue #100). skillc is public - a message like "msg 1401" or a bare
worker token like "w3" resolves to nothing outside the fleet that produced
this repository; a durable citation names an ADR section, an issue, or a PR
instead (all three are already the convention this codebase otherwise
follows).

Scope, per issue #100's own text: every real file under the repository root
except `docs/research/` (dated historical research documents that cite
another project's own paths and line numbers, never this fleet's messages),
`tests/test_leak.py` plus `tests/fixtures/leak_seeds/` (which name these
exact strings AS SEEDED LEAK EXAMPLES on purpose - excluding them is not
silencing a real hit, it is not re-flagging a fixture #63's own leak-check
gate already proves against), and - for the identical reason -
`tests/test_private_citations.py` (this file) and
`.github/PULL_REQUEST_TEMPLATE.md`, whose own committed examples and
checklist wording necessarily CONTAIN the pattern this guard exists to
forbid everywhere else (Codex code-review finding: an earlier version of
this file scanned itself and its own new PR template, and would have failed
CI on its own committed positive/negative-control examples forever).

WALKS THE FILESYSTEM, NEVER `git ls-files` (PR #104's own review):
the first version of this guard used `git ls-files` and skipped itself with
`pytest.mark.skipif` whenever `git` was not on PATH - which is true of the
CI gate's own `python:3.12-slim` image. So the ONE guard whose whole job is
to keep a citation out of what CI treats as green never actually ran in CI,
on this PR or any later one: `tests/test_private_citations.py s..s.....` in
the gate log, an `s` for each of the two tests this decorator disabled. A
gate that lets work through needs to be able to fail where it runs; this one
could not. `os.walk`, the same primitive `skillc/leak.py`'s own scanner
already uses (sharing its `SKIP_DIRS` rather than maintaining a second list
that could drift from it), needs no external binary and runs identically
everywhere pytest does. The tradeoff this accepts, stated rather than
silently assumed: an UNTRACKED file left in the working tree is now part of
the scanned population too (a real clone in CI never has one; a local
workspace with scratch files might) - `SKIP_DIRS` plus the explicit
exclusions above are what keep that population meaningful either way.

This is deliberately a CONTENT guard over files in the checkout, not a check
on PR bodies or commit messages - issue #100's own correction comment found
that distinction the hard way (a clean tracked-file sweep on PR #99 did not
prevent the same pattern from landing in that PR's squash-commit message,
which content grep run against the checkout can never see). That half is a
process rule stated in the PR template and README's Contributing section,
not something a test file can enforce.
"""

from __future__ import annotations

import bisect
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from skillc.leak import SKIP_DIRS

ROOT = Path(__file__).resolve().parent.parent

#: Version-control internals and caches are already excluded via
#: `skillc.leak.SKIP_DIRS`; a build directory is a class of its own (never a
#: cache, never version control) that only appears after `uv build`/`pip
#: build` runs locally - never in a fresh CI checkout, but excluded anyway so
#: a local run behaves the same way. `.gitignore` names exactly these three
#: shapes.
_EXTRA_SKIP_DIRS = frozenset({"dist", "build"})


def _skip_dir(name: str) -> bool:
    return name in SKIP_DIRS or name in _EXTRA_SKIP_DIRS or name.endswith(".egg-info")


#: A standalone `msg`/`msgs` followed by a 4-digit id, or a standalone
#: `w<digit>` token - the two shapes issue #100 names explicitly. Neither
#: form is used anywhere in this codebase for a legitimate, non-fleet reason
#: (confirmed by this test's own green run over every file it does not
#: exclude).
#:
#: SPELLED-OUT citations, widened in separately (found 2026-10-07: this
#: pattern only ever matched the ABBREVIATED "msg"/"msgs" forms, so a
#: spelled-out "message NNNN" or "mailbox message NNNN/NNNN" passed every
#: scan and the merged CI gate - "message" does not start with "msg" as a
#: token, so the original pattern never had a chance to see it). Added:
#: `message(s) [#]NNNN`, optionally followed by a `/NNNN` pair (the
#: "message NNNN/NNNN" shape), and `mailbox [message(s)] [#]NNNN` the same
#: way. Verified by running this widened pattern over the WHOLE tree before
#: committing it (not merely against the known offenders at the time) -
#: 2205 files inspected, exactly the known offenders matched, zero
#: unrelated hits; ordinary prose using the word "message" (error message,
#: commit message, log message, ...) never has a 4-digit number
#: immediately following it, so the narrow `\d{4}` anchor is what keeps
#: this from flagging those.
PRIVATE_CITATION = re.compile(
    r"\bmsgs? ?\d{4}\b"
    r"|\bw\d\b"
    r"|\bmessages? #?\d{4}(?:/\d{4})?\b"
    r"|\bmailbox(?: messages?)? #?\d{4}(?:/\d{4})?\b"
)

#: Directory prefixes end in "/" and match anything underneath; anything
#: else is matched by EXACT equality only - `startswith()` on every entry
#: (an earlier version of this file) would also have excluded
#: `tests/test_leak.py.bak` or `tests/test_leak.py_extra` alongside the one
#: file actually meant (Codex code-review finding).
EXCLUDED_PREFIXES = (
    "docs/research/",
    "tests/fixtures/leak_seeds/",
    "tests/test_leak.py",
    "tests/test_private_citations.py",
    ".github/PULL_REQUEST_TEMPLATE.md",
)

#: This repository holds several hundred files today. A count far below this
#: is not "clean" - it is the walk running from the wrong directory or
#: pruning too much, and a scan that saw almost nothing must not be read as
#: a scan that found nothing wrong (Codex code-review finding: an empty or
#: near-empty population previously passed silently).
MINIMUM_EXPECTED_CANDIDATE_FILES = 100


def _is_excluded(rel_path: str) -> bool:
    for prefix in EXCLUDED_PREFIXES:
        if prefix.endswith("/"):
            if rel_path.startswith(prefix):
                return True
        elif rel_path == prefix:
            return True
    return False


def _candidate_files(root: Path = ROOT) -> list[str]:
    """Every file under `root`, forward-slash relative paths, minus
    `SKIP_DIRS`/`_EXTRA_SKIP_DIRS` - the real filesystem, not `git ls-files`
    (see the module docstring for why)."""
    candidates: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not _skip_dir(d))
        for name in sorted(filenames):
            candidates.append((Path(dirpath) / name).relative_to(root).as_posix())
    return candidates


def _joined_for_search(text: str) -> tuple[str, list[int], list[int]]:
    """One search space for the whole file, plus enough to map a match
    position back to its original line.

    A citation routinely WRAPS across a Python comment continuation - this
    guard's own would-be fix for `skillc/lifecycle.py` read
    `"...review, msg\\n            # 1331)."` in the source: "msg" ends one
    comment line and the number opens the next, both prefixed with their own
    "# ". A plain per-line search never sees the two halves as one token
    (checked independently: it does not), and neither does a naive
    newline-to-space join, because the "# " marker still sits between them.
    So each line has its leading whitespace and at most one "#" marker
    stripped before joining with a single space - this is what actually
    reconnects a wrapped citation into one matchable token."""
    offsets: list[int] = []
    line_numbers: list[int] = []
    pieces: list[str] = []
    offset = 0
    for line_no, line in enumerate(text.split("\n"), start=1):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            stripped = stripped[1:].lstrip()
        offsets.append(offset)
        line_numbers.append(line_no)
        pieces.append(stripped)
        offset += len(stripped) + 1  # +1 for the single joining space below
    return " ".join(pieces), offsets, line_numbers


@dataclass(frozen=True)
class ScanResult:
    offenses: list[str]
    #: Files whose content was actually read and searched - the population
    #: this check's verdict is actually about. `inspected == 0` means the
    #: check saw NOTHING, which must never look identical to "saw everything
    #: and it was clean" (Codex code-review finding).
    inspected: int
    excluded: int
    #: Present in the input but not counted in `inspected`: missing, a
    #: symlink (see below), or not decodable as UTF-8.
    unreadable: int


def _scan(rel_paths: Sequence[str], root: Path = ROOT) -> ScanResult:
    offenses: list[str] = []
    inspected = 0
    excluded = 0
    unreadable = 0
    for rel_path in rel_paths:
        if _is_excluded(rel_path):
            excluded += 1
            continue
        path = root / rel_path
        if path.is_symlink():
            # A symlink's `read_text()` follows the link and reads the
            # TARGET's content under this path's name - so editing some
            # unrelated file this repository does not even track could flip
            # this guard's verdict without anything TRACKED changing at all
            # (Codex code-review finding; `skillc/leak.py` already treats a
            # symlink the same way, for the same reason). Its own tracked
            # content is the link text, which is never itself a citation.
            unreadable += 1
            continue
        if not path.is_file():
            unreadable += 1  # a tracked path missing from this checkout (submodule, sparse checkout)
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            unreadable += 1  # not this check's population - #63's leak-check already treats this as UNKNOWN
            continue
        inspected += 1
        joined, offsets, line_numbers = _joined_for_search(text)
        for match in PRIVATE_CITATION.finditer(joined):
            index = bisect.bisect_right(offsets, match.start()) - 1
            offenses.append(f"{rel_path}:{line_numbers[index]}: {match.group(0)!r}")
    return ScanResult(offenses=offenses, inspected=inspected, excluded=excluded, unreadable=unreadable)


def test_no_tracked_file_cites_a_private_message_number_or_worker_name() -> None:
    candidates = _candidate_files()
    assert len(candidates) >= MINIMUM_EXPECTED_CANDIDATE_FILES, (
        f"only {len(candidates)} candidate files were found (expected at least "
        f"{MINIMUM_EXPECTED_CANDIDATE_FILES}) - the walk may have run from the "
        "wrong directory or pruned too much; a check that saw almost nothing "
        "must not be read as a check that found nothing wrong"
    )
    result = _scan(candidates)
    assert result.inspected > 0, "no file was actually inspected - a scan of nothing is not a clean scan"
    assert result.offenses == [], (
        "private fleet citation found (issue #100) - replace with an ADR section, "
        "issue, or PR reference instead:\n" + "\n".join(result.offenses)
    )


def test_an_empty_population_reports_zero_inspected_not_silently_clean() -> None:
    """Red case: an empty input must be distinguishable from a clean scan of
    a real population - both have `offenses == []`, but only the real one
    has `inspected > 0`."""
    result = _scan([])
    assert result.inspected == 0
    assert result.offenses == []


def test_a_population_of_only_unreadable_files_reports_zero_inspected(tmp_path: Path) -> None:
    """Red case: a file that cannot be decoded as UTF-8 is skipped, not
    scanned - even though it contains a real offender in its raw bytes,
    `inspected` must stay 0 rather than silently passing it as clean."""
    (tmp_path / "binary.dat").write_bytes(b"\xff\xfe\x00\x01msg 1331")
    result = _scan(["binary.dat"], root=tmp_path)
    assert result.inspected == 0
    assert result.offenses == []


def test_a_tracked_symlink_is_not_scanned_as_its_target(tmp_path: Path) -> None:
    """Red case: `Path.read_text()` follows a symlink, so scanning one would
    silently read an UNRELATED file's content under this path's name - a
    change to that external target could flip this guard's verdict without
    this repository's own tracked content changing at all."""
    outside = tmp_path / "outside_target.txt"
    outside.write_text("msg 1331\n", encoding="utf-8")
    link_dir = tmp_path / "repo"
    link_dir.mkdir()
    link = link_dir / "linked.py"
    link.symlink_to(outside)
    result = _scan(["linked.py"], root=link_dir)
    assert result.inspected == 0
    assert result.offenses == []


def test_the_pattern_matches_a_planted_message_number_offender() -> None:
    """Negative control: a realistic `msg NNNN` offender is actually caught,
    not merely never triggered."""
    assert PRIVATE_CITATION.search("Recorded per orchestrator review (msg 1331).")


def test_the_pattern_matches_a_planted_worker_name_offender() -> None:
    """Negative control: a realistic bare worker-name offender is actually
    caught, not merely never triggered."""
    assert PRIVATE_CITATION.search("Found by w3's cross-model review.")


def test_the_pattern_does_not_match_an_ordinary_word_ending_in_a_digit() -> None:
    """The word-boundary anchors must not turn this into a blunt scan for
    any letter-then-digit pair - the worker-name half requires the token to
    be EXACTLY `w` plus one digit, not a prefix of a longer identifier."""
    assert PRIVATE_CITATION.search("w2-g1") is not None, "w2-g1 legitimately contains the bare token w2"
    assert PRIVATE_CITATION.search("row3") is None
    assert PRIVATE_CITATION.search("view2") is None


#: Reconstructs the SHAPE of the three real offenders found on main
#: 2026-10-07 (found by counter-model review while editing an unrelated
#: #332 file) with obviously-fake, non-colliding numbers - never the real
#: ids themselves, which this committed test file must not republish any
#: more than the files it fixed should have carried them. Each shape is
#: realistic and is what the ABBREVIATED-only pattern missed for months
#: on this exact codebase before the fix below. Named here, not only in
#: the regex's own comment, so a future edit that narrows the pattern
#: again has a concrete sentence to re-run against, not just a
#: description.
_SPELLED_OUT_OFFENDERS = (
    "(orchestrator guidance, message 9999): its claim is about the shim's",
    "ruling 2026-10-06, mailbox message 9998/9997).",
    "Orchestrator ruling (message 9996): a degraded subject carrying a",
)


def test_the_pattern_matches_each_spelled_out_offender_shape_found_on_main() -> None:
    """Positive control: the widened pattern actually catches the three
    offender SHAPES this fix was written for (synthetic numbers; see
    `_SPELLED_OUT_OFFENDERS`' own docstring) - not merely a synthetic
    shape that happens to look similar for some other reason."""
    for offender in _SPELLED_OUT_OFFENDERS:
        assert PRIVATE_CITATION.search(offender), f"expected a match in: {offender!r}"


def test_the_pre_fix_pattern_missed_all_three_spelled_out_offender_shapes() -> None:
    """Mutation check: the OLD (abbreviated-only) pattern must NOT catch
    any of the three offender shapes above - proving this fix actually
    closes a real gap, not a hypothetical one. If the old pattern already
    matched these, the widening would be solving a problem that did not
    exist."""
    pre_fix_pattern = re.compile(r"\bmsgs? ?\d{4}\b|\bw\d\b")
    for offender in _SPELLED_OUT_OFFENDERS:
        assert not pre_fix_pattern.search(offender), (
            f"the pre-fix pattern should NOT have matched {offender!r} - "
            "if it did, this red case is inert"
        )


def test_the_pattern_does_not_flag_ordinary_prose_using_the_word_message() -> None:
    """The word "message" is common prose in this codebase (error
    message, commit message, log message, ...) - the widened pattern must
    stay narrow to "message/mailbox immediately followed by a 4-digit
    number", never fire on the bare word alone."""
    assert PRIVATE_CITATION.search("the error message was truncated") is None
    assert PRIVATE_CITATION.search("write a clear commit message") is None
    assert PRIVATE_CITATION.search("the log message format changed") is None
    assert PRIVATE_CITATION.search("a message queue with no mailbox at all") is None


def test_the_pattern_matches_a_hash_prefixed_and_a_pair_form_message_citation() -> None:
    """Positive controls for the two sub-shapes added alongside the three
    offender shapes above: a `#`-prefixed message number, and a bare
    (non-mailbox-prefixed) pair form. Synthetic numbers throughout."""
    assert PRIVATE_CITATION.search("see message #9995 for the ruling")
    assert PRIVATE_CITATION.search("message 9994/9993 covers both halves")


def test_a_citation_wrapped_across_a_comment_continuation_is_still_caught(tmp_path: Path) -> None:
    """Red case, found while building this guard: a citation split across a
    wrapped Python comment line - exactly the shape
    `skillc/lifecycle.py` originally had - is invisible to a per-line search
    and to a naive newline-to-space join, because the second line's own
    "# " marker still separates the two halves. This same, more careful
    check went on to catch a real offender an earlier manual text search
    over the same tracked population had missed for the identical reason
    (`skillc/verify.py`, since fixed)."""
    planted = tmp_path / "planted.py"
    planted.write_text(
        "def f() -> None:\n"
        "    # Recorded whichever path is taken (orchestrator review, msg\n"
        "    # 1331): a capture that passed the weaker fallback.\n",
        encoding="utf-8",
    )
    result = _scan(["planted.py"], root=tmp_path)
    assert result.inspected == 1
    assert result.offenses == ["planted.py:2: 'msg 1331'"]


def test_the_exclusions_cover_exactly_the_stated_scope() -> None:
    """Red case for the exclusion list itself: a path just outside a stated
    entry must NOT be excluded, and a path inside/equal to one must be."""
    assert _is_excluded("docs/research/coder-eval-lessons.md")
    assert _is_excluded("tests/test_leak.py")
    assert _is_excluded("tests/fixtures/leak_seeds/judge_seeds.py")
    assert _is_excluded("tests/test_private_citations.py")
    assert _is_excluded(".github/PULL_REQUEST_TEMPLATE.md")
    assert not _is_excluded("docs/research.md")
    assert not _is_excluded("tests/test_leak.py.bak")
    assert not _is_excluded("tests/test_leak.py_extra")
    assert not _is_excluded("skillc/cost_estimate.py")
