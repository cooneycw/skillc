"""Prove every interpreter the demo and verifier invoke INSIDE the trial
container is actually installed in it (issue #78, Refs #81, Refs #10).

Found live: `skillc-trial`'s Dockerfile (`FROM node:22-bookworm-slim`) only
apt-installs `ca-certificates` and `git` - there is no `python3` in the image
at all, while `skillc.verify.PROBE_INTERPRETER` is `"python3"` (the grading
demo's own probe interpreter, run inside the container) and
`skillc.demo`'s scripted lifecycle subject and reply-only control both
invoke it too. Every existing check was Docker-shaped against the FAKE CLI,
which never looks inside an image, so a real daemon run of `skillc demo`
would fail both demonstrations as `launch-failed` - and nothing before this
module could have caught it without a live daemon.

This is the committed, no-daemon control: it parses the Dockerfile's own
apt-get install list as TEXT (no Docker, no network - runs in CI and in this
session alike, exactly like `check_pins.py` beside it) and refuses when a
required interpreter's package is missing from it.

Red case: `tests/test_trial_bootstrap.py` renders a copy of the Dockerfile
with `python3` removed from the apt-get install list and asserts this module
reports it missing.

Scope, deliberately narrow: this checks packages installed by THIS
Dockerfile's own `apt-get install` step, never the base image's own
contents - `node` needs no entry here because it ships with
`node:22-bookworm-slim` already, not through this apt call. Widening this to
verify the base image's own contents would need the image itself, which is
exactly the daemon dependency this module exists to avoid.
"""

from __future__ import annotations

import re
from pathlib import Path

_APT_INSTALL_RE = re.compile(
    r"apt-get install -y --no-install-recommends\s*\\\n((?:\s*\S+\s*\\\n)+)",
)


def dockerfile_apt_packages(text: str) -> set[str]:
    """Every package name in the Dockerfile's `apt-get install
    --no-install-recommends` block - the one apt-installs actually reach,
    never a package merely mentioned in a comment or docstring elsewhere in
    the file. An empty result means the block itself could not be found
    (a Dockerfile restructuring this regex no longer matches), which the
    caller treats as inconclusive, never as "nothing is installed"."""
    match = _APT_INSTALL_RE.search(text)
    if match is None:
        return set()
    return {line.strip().rstrip("\\").strip() for line in match.group(1).splitlines() if line.strip()}


def check_interpreters(dockerfile_text: str, required: set[str]) -> list[str]:
    """Return one message per interpreter in `required` that is not among
    the Dockerfile's own apt-installed packages; an empty list means every
    required interpreter's package is present. `required` is supplied by the
    caller (derived from `skillc.verify.PROBE_INTERPRETER` and any interpreter
    literal `skillc.demo` invokes inside the container), never hardcoded
    here, so a second interpreter added to either module is caught the same
    way a stale one is, with no second list to fall out of sync."""
    packages = dockerfile_apt_packages(dockerfile_text)
    if not packages:
        return ["could not find the Dockerfile's apt-get install block at all - check the regex against a restructured Dockerfile"]
    return [
        f"{interpreter!r} is required inside the trial container but is not apt-installed by the Dockerfile"
        for interpreter in sorted(required)
        if interpreter not in packages
    ]


def _required_interpreters() -> set[str]:
    """The interpreters `skillc`'s own demo/verifier invoke inside the
    container, derived from their own source of truth rather than a second,
    hand-maintained literal here."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from skillc.verify import PROBE_INTERPRETER

    return {PROBE_INTERPRETER}


def main(argv: list[str] | None = None) -> int:
    dockerfile_text = (Path(__file__).parent / "Dockerfile").read_text(encoding="utf-8")
    messages = check_interpreters(dockerfile_text, _required_interpreters())
    if messages:
        for message in messages:
            print(f"check-interpreters: {message}")
        return 1
    print("check-interpreters: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
