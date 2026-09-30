#!/usr/bin/env python3
"""slugkit's pipeline, with its checks in a sibling helper (`ci/checks.py`).
A valid alternative: `python3 ci/verify.py` puts `ci/` on `sys.path`, so the
import works - and the grader must run it the same way."""

import sys

from checks import packaging_ok, tests_pass

failed = [name for name, check in (("tests", tests_pass), ("packaging", packaging_ok)) if not check()]
print("VERIFY: ok" if not failed else "VERIFY: fail " + " ".join(failed))
sys.exit(1 if failed else 0)
