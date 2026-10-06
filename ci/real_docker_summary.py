"""Leak-safe summary formatting for the `<agent-host>` real-Docker runner
(#315). Full JUnit XML and pytest's own stdout/stderr stay on the VM; this
module builds the ONLY text that ever leaves it (a GitHub commit status
description and an optional comment body).

ALLOWLISTED BY CONSTRUCTION, not by scanning-and-redacting: a test failure's
message/traceback can embed an absolute path or a container id, and a scan
for "things that look like a leak" can always miss a pattern nobody thought
to list. So this module never touches that content at all - it takes only
the verdict's STATUS and STRUCTURED COUNTS (`check_real_docker_ran.Verdict`,
read for its dataclass fields, never for `.reason` - see below), plus the
caller-supplied SHA and runner SHA, and renders its OWN fixed, hand-written
sentence per status. `Verdict.reason` is never included: it happens to be
built from fixed templates today, but this module does not rely on that
staying true forever - decoupling from it is what keeps this module's own
safety independent of a future change elsewhere.

Even test IDENTIFIERS (`failed_ids`, pytest's own `classname::name` strings)
are filtered through a strict allowed-character pattern before being
included, rather than trusted as already-safe - a test id is ordinarily just
code-identifier characters, but "ordinarily" is not a guarantee, and the one
thing worse than omitting a weird id is posting it unfiltered.

Stdlib only (AGENTS.md).
"""

from __future__ import annotations

import re

from ci.check_real_docker_ran import ERROR, FAILURE, SUCCESS, Verdict

#: Deliberately independent of `Verdict.reason` - see module docstring.
_STATUS_SENTENCE = {
    SUCCESS: "every declared real-Docker file executed at least one test, no failures",
    FAILURE: "a real-Docker test failed, or the declared population collected but never executed",
    ERROR: "the real-Docker population could not be determined (not collected, or unreadable)",
}

#: A pytest test id is `module.path.ClassName::test_name` - letters, digits,
#: underscore, dot, colon, brackets (parametrize ids) and hyphen. Anything
#: outside this set is treated as untrusted and the whole id is dropped
#: rather than partially included.
_SAFE_TEST_ID = re.compile(r"^[A-Za-z0-9_.:\[\]-]+$")
_MAX_TEST_ID_LEN = 200
_MAX_FAILED_IDS_SHOWN = 5


def _safe_ids(ids: tuple[str, ...]) -> tuple[list[str], int]:
    """Returns (safe ids, how many were dropped for failing the charset or
    length check) - the drop count is itself safe to post (just a number)."""
    safe = [i for i in ids if len(i) <= _MAX_TEST_ID_LEN and _SAFE_TEST_ID.fullmatch(i)]
    return safe, len(ids) - len(safe)


def format_status_description(result: Verdict, *, sha: str, runner_sha: str) -> str:
    """The GitHub commit-status `description` field (short; GitHub itself
    truncates past ~140 chars, so this stays well under that)."""
    counts = f"{sum(result.executed_by_file.values())} executed" if result.executed_by_file else "0 executed"
    return f"{result.status}: {counts} (sha {sha[:12]}, runner {runner_sha[:12]})"


def format_comment_body(result: Verdict, *, sha: str, runner_sha: str) -> str:
    """The fuller, optional PR/issue comment - still allowlisted, just with
    room for per-file counts and a few failing test ids."""
    lines = [
        f"**real-Docker run: {result.status}**",
        "",
        _STATUS_SENTENCE[result.status],
        "",
        f"- Commit under test: `{sha}`",
        f"- Runner (installed, reviewed copy): `{runner_sha}`",
    ]
    if result.executed_by_file:
        lines.append("- Per-file executed counts:")
        for name, count in sorted(result.executed_by_file.items()):
            lines.append(f"  - `{name}`: {count}")
    if result.skipped_only_files:
        lines.append(f"- Collected but never executed: {', '.join(sorted(result.skipped_only_files))}")
    if result.failed_ids:
        safe, dropped = _safe_ids(result.failed_ids)
        shown = safe[:_MAX_FAILED_IDS_SHOWN]
        lines.append(f"- Failing test id(s) ({len(result.failed_ids)} total):")
        for test_id in shown:
            lines.append(f"  - `{test_id}`")
        remaining = len(safe) - len(shown)
        if remaining > 0:
            lines.append(f"  - (+{remaining} more)")
        if dropped > 0:
            lines.append(f"  - ({dropped} id(s) omitted - did not match the allowed test-id character set)")
    lines.append("")
    lines.append("Full logs are retained on the runner host only.")
    return "\n".join(lines)
