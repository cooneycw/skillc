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
#: image}. One entry today - grows the same way a second required
#: interpreter would in `check_interpreters.py`, by adding to this map,
#: never by hand-maintaining a second list anywhere else.
REQUIRED_HELPERS = {
    "skillc-disrupt-tool.py": "/usr/local/bin/skillc-disrupt-tool",
}


def check_helpers(dockerfile_text: str, required: dict[str, str] | None = None) -> list[str]:
    """Return one message per required helper that is not both COPYed to
    its installed path and made executable (`chmod` naming that same
    path) by the Dockerfile text - an empty list means every required
    helper is fully installed. `required` defaults to `REQUIRED_HELPERS`;
    a caller may pass a different mapping (the test suite's own red
    cases do)."""
    required = REQUIRED_HELPERS if required is None else required
    messages = []
    for source, installed_path in required.items():
        copy_pattern = re.compile(
            rf"^COPY\s+{re.escape(source)}\s+{re.escape(installed_path)}\s*$", re.MULTILINE,
        )
        if copy_pattern.search(dockerfile_text) is None:
            messages.append(f"{source!r} is required but no 'COPY {source} {installed_path}' line was found")
            continue
        chmod_pattern = re.compile(rf"chmod\s+\S+\s+{re.escape(installed_path)}\b")
        if chmod_pattern.search(dockerfile_text) is None:
            messages.append(f"{installed_path!r} is copied in but never made executable (no matching chmod)")
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
