"""#279 PR-3: the Step-6 S4 oracle against a REAL daemon and the REAL trial
image (no model; network none).

1. The committed outcome table (`oracle-goldens.json`) is what the container
   computes now - the control that qualify's table is real.
2. Orchestrator C1's red: delivered code that writes a file, or opens a
   socket, never PASSES, and its side effect never reaches the controller
   host. The write targets a fresh path under the HOST's own /tmp: were the
   code executed on the host, the file would exist afterwards.
"""

from __future__ import annotations

import importlib.util
import json
import os
import secrets
import sys
from pathlib import Path
from typing import Any

import pytest
from test_codex_guard_live import pytestmark as _live_marks

from skillc import step6_oracle as so

pytestmark = _live_marks
ROOT = Path(__file__).resolve().parent.parent
TASK = ROOT / "evals" / "level3" / "flow-auto-step6-gate"
IMAGE = os.environ.get("SKILLC_TRIAL_IMAGE", "skillc-trial:latest")


def _qualify() -> Any:
    spec = importlib.util.spec_from_file_location("step6_qualify_live", TASK / "qualify.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.timeout(600)
def test_the_committed_oracle_table_is_what_the_container_computes() -> None:
    q = _qualify()
    variants = q.core_variants()
    ran = so.container_runner(("docker",), IMAGE)({n: t.encode() for n, t in variants.items()})
    table = json.loads(q.ORACLE_GOLDENS.read_text())
    for name, text in variants.items():
        assert table[q._sha(text)] == ran[name], name


@pytest.mark.timeout(600)
def test_side_effects_never_pass_and_never_reach_the_host() -> None:
    sentinel = Path("/tmp") / f"skillc-oracle-sidefx-{secrets.token_hex(8)}"
    fixed_body = ('    if not text or text[0] == "#":\n        return []\n'
                  '    return [part.strip() for part in text.split(",")]\n')
    sources = {
        "writes": f"open({str(sentinel)!r}, 'w').write('x')\n\n\ndef parse(text):\n{fixed_body}".encode(),
        "connects": ("import socket\nsocket.create_connection(('1.1.1.1', 80), timeout=2)\n\n\n"
                     f"def parse(text):\n{fixed_body}").encode(),
    }
    ran = so.container_runner(("docker",), IMAGE)(sources)
    for name, outcome in ran.items():
        assert outcome.get("status") != "ran", (name, outcome)  # never judged as passing
    assert not sentinel.exists()
