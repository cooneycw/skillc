"""A second redcase for #80's no-Docker-required check (cross-model review,
PR #87): like imports_docker_backend_at_load.py, but ALSO prints something
during import. Proves the check parses the LAST line of stdout, never the
whole captured text, so an unrelated print cannot mask a genuine positive -
the pre-fix probe compared the whole stdout against the literal "yes" and
reported this exact shape as a false negative.
"""

from __future__ import annotations

print("unrelated startup output")

import skillc.docker_backend  # noqa: F401
