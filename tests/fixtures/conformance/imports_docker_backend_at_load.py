"""The committed redcase for #80's no-Docker-required check (ADR 0001): a
module that WRONGLY imports `skillc.docker_backend` at module load, exactly
the defect the check exists to catch in a real static-command module. The
check must report this file as importing the Docker backend, proving it is
not vacuously green against everything.
"""

from __future__ import annotations

import skillc.docker_backend  # noqa: F401
