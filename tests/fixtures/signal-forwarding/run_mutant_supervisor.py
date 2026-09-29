#!/usr/bin/env python3
"""Test fixture only (issue #158 red case 2) - the mutant referenced by
`tests/test_skillc_supervisor.py`. Imports the REAL, unmodified
`docker/trial/skillc-supervisor.py` and monkeypatches its `_on_term` handler
to relay AND THEN EXIT: the exact bug `signal-forwarding.md` section 2a
item 6's must-not-exit rule forbids. The production script itself carries
no branch, flag, or environment variable that can trigger this behavior -
the mutant exists only here, in the test tree, per review ruling.
"""

from __future__ import annotations

import importlib.util
import os
import sys

_SUPERVISOR_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "docker", "trial", "skillc-supervisor.py",
)


def main() -> int:
    spec = importlib.util.spec_from_file_location("skillc_supervisor_mutant", _SUPERVISOR_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    real_on_term = mod._on_term  # type: ignore[attr-defined]

    def mutant_on_term(signum: int, frame: object) -> None:
        real_on_term(signum, frame)  # still relays - the mutation is ONLY the exit that follows
        sys.exit(0)  # THE BUG: tini's only child, exiting here takes PID 1 down with it

    # main() looks `_on_term` up from its own module globals at the moment
    # it calls `signal.signal(...)`, so patching the module attribute before
    # calling main() is sufficient - no need to touch main()'s own code.
    # A dynamically loaded module has no static type mypy can check this
    # attribute-set against - see the matching ignore on the read above.
    mod._on_term = mutant_on_term  # type: ignore[attr-defined]
    return mod.main()  # type: ignore[attr-defined, no-any-return]


if __name__ == "__main__":
    sys.exit(main())
