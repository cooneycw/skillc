"""Red-case child for `skillc demo --control`'s cancellation seed (issue #122).

Runs skillc's own CLI with ONE change: the interrupt handler's sweep is no
longer scoped to this run's recorded attempt ids. Every skillc-owned
container on the daemon is removed first, then the scoped reap runs as
before - the host-global `reap_all_owned()` behaviour issue #118's review
removed after it reaped a foreign run's container under a genuine SIGINT.

The seed must report NOT CAUGHT against this child, because the foreign
container it prepared does not survive. Used only by `tests/test_demo.py`.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterable, Mapping, Sequence

from skillc import cli, reap

_scoped_reap = reap.reap


def _unscoped_reap(
    docker_bin: Sequence[str], attempt_ids: Iterable[str],
    env: Mapping[str, str] | None = None, timeout: float = 10,
) -> reap.ReapReport:
    for name in reap.snapshot(docker_bin, env, timeout).owned:
        subprocess.run([*docker_bin, "rm", "-f", name], capture_output=True, env=env, check=False, timeout=timeout)
    return _scoped_reap(docker_bin, attempt_ids, env, timeout)


reap.reap = _unscoped_reap  # type: ignore[assignment]

if __name__ == "__main__":
    raise SystemExit(cli.main(sys.argv[1:]))
