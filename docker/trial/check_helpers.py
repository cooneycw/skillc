"""Prove a required helper script is actually COPYed into the trial image
and made executable (issue #183 PR B2), without needing a Docker daemon -
the same no-daemon, parse-the-Dockerfile-as-text family `check_pins.py` and
`check_interpreters.py` already belong to, and deliberately NOT an entry in
`check_pins.py` itself: that module is narrowly about Dockerfile `ARG`
version defaults matching `pinned-versions.json`, and has nothing to do
with whether a script got copied in at all.

Red case: `tests/test_trial_bootstrap.py` renders a copy of the Dockerfile
with the `COPY skillc-disrupt-tool.py ...` line removed and confirms this
module reports it missing.

Scope, deliberately narrow, matching `check_interpreters.py`'s own stated
limit: this checks THIS Dockerfile's own `COPY`/`chmod` lines, never the
base image's own contents and never whether the copied file is actually
correct - that needs the file itself, not the Dockerfile text, and is
covered by this helper's own source and its dedicated unit tests
(`tests/test_level5_recovery.py` and friends), not by this module.
"""

from __future__ import annotations

import re
from pathlib import Path

#: {source filename (relative to docker/trial/): installed path in the
#: image}. Grows the same way a second required interpreter would in
#: `check_interpreters.py`, by adding to this map, never by hand-
#: maintaining a second list anywhere else. The #332 shim is staged at a
#: path the subject never invokes directly (see the Dockerfile's own
#: comment) - this check only proves it is COPYed in and executable
#: THERE, same as any other required helper; it says nothing about
#: whether the overlay that reads it later is wired correctly.
REQUIRED_HELPERS = {
    "skillc-disrupt-tool.py": "/usr/local/bin/skillc-disrupt-tool",
    "flow-check-gate-shim.py": "/usr/local/share/skillc/flow-check-gate-shim.py",
}


#: Octal chmod modes whose LAST digit (the "other" permission triplet -
#: the one that matters here, since the file is root-owned and `candidate`
#: is neither owner nor group, codex:code_review finding) has the execute
#: bit set. Enumerated rather than computed from `int(mode, 8) & 1`: a
#: malformed mode (wrong length, non-octal digit) must refuse, not raise
#: or silently coerce, and an explicit set makes that refusal the default.
_EXECUTABLE_OTHER_MODES = frozenset(f"{a}{b}{c}" for a in "01234567" for b in "01234567" for c in "1357")


def check_helpers(dockerfile_text: str, required: dict[str, str] | None = None) -> list[str]:
    """Return one message per required helper that is not both COPYed to
    its installed path and made executable there (`chmod` naming that
    EXACT path, with a mode that actually grants execute to a non-owner,
    on an ACTIVE instruction line - not a comment) by the Dockerfile
    text - an empty list means every required helper is fully installed.
    `required` defaults to `REQUIRED_HELPERS`; a caller may pass a
    different mapping (the test suite's own red cases do), but an EMPTY
    mapping is refused outright (codex:code_review finding) rather than
    reporting "ok" for a population of zero helpers checked."""
    required = REQUIRED_HELPERS if required is None else required
    if not required:
        return ["no required helpers were given to check - refusing rather than reporting 'ok' for an empty population"]
    active_lines = [line for line in dockerfile_text.splitlines() if not line.strip().startswith("#")]
    active_text = "\n".join(active_lines)
    messages = []
    for source, installed_path in required.items():
        copy_pattern = re.compile(
            rf"^COPY\s+{re.escape(source)}\s+{re.escape(installed_path)}\s*$", re.MULTILINE,
        )
        if copy_pattern.search(active_text) is None:
            messages.append(f"{source!r} is required but no active 'COPY {source} {installed_path}' line was found")
            continue
        # The path must be the WHOLE chmod argument, not merely a prefix
        # of a longer one (codex:code_review finding: a neighbour path
        # like "<installed_path>.backup" must not satisfy this) - matched
        # by requiring whitespace or end-of-line immediately after it,
        # never a bare `\b` (which is satisfied before a literal `.` too).
        chmod_pattern = re.compile(
            rf"^RUN\s+chmod\s+([0-7]{{3}})\s+{re.escape(installed_path)}(?=\s|$)", re.MULTILINE,
        )
        match = chmod_pattern.search(active_text)
        if match is None or match.group(1) not in _EXECUTABLE_OTHER_MODES:
            messages.append(f"{installed_path!r} is copied in but never made executable for a non-owner (no matching chmod)")
    return messages


def main(argv: list[str] | None = None) -> int:
    dockerfile_text = (Path(__file__).parent / "Dockerfile").read_text(encoding="utf-8")
    messages = check_helpers(dockerfile_text)
    if messages:
        for message in messages:
            print(f"check-helpers: {message}")
        return 1
    print("check-helpers: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
