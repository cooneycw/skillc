"""#279 PR-3: the Step-6 S4 oracle against a REAL daemon and the REAL trial
image (no model; network none).

The image is the guard's: a prebuilt `SKILLC_TRIAL_IMAGE`, verified present,
or a freshly built, uniquely tagged one removed afterwards - and the oracle
runs it by its IMAGE ID, as production does.

1. The committed outcome table (`oracle-goldens.json`) gives every variant
   the same S4 verdict as a container run now (its random challenges differ
   per run, so verdicts are compared, not bytes) - the control that
   qualify's table is real.
2. Orchestrator C1's red: delivered code that writes a file - to /tmp,
   /dev/shm, /dev/mqueue or its home - or opens a socket, fails INSIDE the
   child (`status: error`), never passes, and the write never reaches the
   controller host (the /tmp target is a fresh HOST path: were the code run
   on the host, it would exist afterwards). A correct parser beside them is
   the positive control: it runs and passes, so these failures are the side
   effects', not a container that never started.
"""

from __future__ import annotations

import importlib.util
import secrets
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from test_codex_guard_live import _trial_image
from test_codex_guard_live import pytestmark as _live_marks

from skillc import step6_oracle as so

pytestmark = _live_marks
ROOT = Path(__file__).resolve().parent.parent
TASK = ROOT / "evals" / "level3" / "flow-auto-step6-gate"


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def image_id() -> Iterator[str]:
    tag, built = _trial_image()
    try:
        found = subprocess.run(["docker", "image", "inspect", tag, "--format", "{{.Id}}"], capture_output=True,
                               text=True, timeout=30, check=False)
        assert found.returncode == 0 and found.stdout.startswith("sha256:"), found.stderr
        yield found.stdout.strip()
    finally:
        if built:
            subprocess.run(["docker", "image", "rm", "-f", tag], capture_output=True, check=False)


@pytest.mark.timeout(1800)
def test_the_committed_oracle_table_gives_what_the_container_gives(image_id: str) -> None:
    import json
    q = _load("step6_qualify_live", TASK / "qualify.py")
    judge = _load("step6_judge_live", TASK / "grade_gate_stops_early_step6.py")
    variants = q.core_variants()
    ran = so.container_runner(("docker",), image_id)({n: t.encode() for n, t in variants.items()})
    table = json.loads(q.ORACLE_GOLDENS.read_text())
    for name, text in variants.items():
        committed, now = table[q._sha(text)], ran[name]
        assert (committed.get("status"), judge._behaves(committed)) == (now.get("status"), judge._behaves(now)), name


_FIXED = ('def parse(text):\n    if not text or text[0] == "#":\n        return []\n'
          '    return [part.strip() for part in text.split(",")]\n')


@pytest.mark.timeout(1800)
def test_side_effects_fail_in_the_child_never_pass_and_never_reach_the_host(image_id: str) -> None:
    judge = _load("step6_judge_live_2", TASK / "grade_gate_stops_early_step6.py")
    sentinel = Path("/tmp") / f"skillc-oracle-sidefx-{secrets.token_hex(8)}"
    writes = {"tmp": str(sentinel), "shm": "/dev/shm/skillc-pwned", "mqueue": "/dev/mqueue/skillc-pwned",
              "home": "~/skillc-pwned"}
    sources = {f"writes-{k}": (f"import os\nopen(os.path.expanduser({v!r}), 'w').write('x')\n\n\n{_FIXED}").encode()
               for k, v in writes.items()}
    sources["connects"] = ("import socket\nsocket.create_connection(('1.1.1.1', 80), timeout=2)\n\n\n"
                           f"{_FIXED}").encode()
    sources["control"] = _FIXED.encode()
    ran = so.container_runner(("docker",), image_id)(sources)
    assert set(ran) == set(sources)
    assert ran["control"].get("status") == "ran" and judge._behaves(ran["control"]) == "passes", ran["control"]
    for name, outcome in ran.items():
        if name != "control":
            assert outcome.get("status") == "error", (name, outcome)  # failed in the child, after startup
    assert not sentinel.exists()
