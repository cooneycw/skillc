#!/usr/bin/env python3
"""Proves `probe.py`'s MODE-SELECTION branch (prefer real pip when
available, else emulate) actually works, decoupled from whether a real
backend happens to be present on any given host - because none is present
anywhere in this repository today (see README.md), so this is the ONLY way
to exercise `install_mode == "real-pip"` at all.

`fixtures/fake-pip/` is a committed, controllable fake standing in for a
real `pip`/`hatchling` - the same fault-injection convention
`tests/fixtures/docker-backend/fake_docker.py` already establishes for this
repo, adapted for a module (`python -m pip`) rather than a CLI on PATH,
since that is what `probe.py._pip_available`/`_real_pip_install` actually
invoke. It implements exactly `--version` and `install --no-index
--no-build-isolation --target DIR SRC`, nothing else, and its own `install`
copies only the declared package directories - the SAME selective-copy
semantics as the stdlib emulation - so a known-bad that defeats the
emulation (an undeclared `scratch/` fix) must ALSO be caught in `real-pip`
mode, proving the two modes are not just switch-named but behaviourally
equivalent on the cases that matter.

Run: `python3 check_real_pip_mode.py` - prints each assertion and exits
non-zero on the first failure.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FAKE_PIP_DIR = HERE / "fixtures" / "fake-pip"
INPUTS = json.loads((HERE / "inputs.json").read_text(encoding="utf-8"))


def _run(candidate: str, *, with_fake_pip: bool) -> dict:
    env = dict(os.environ)
    if with_fake_pip:
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = str(FAKE_PIP_DIR) + (os.pathsep + existing if existing else "")
    else:
        env.pop("PYTHONPATH", None)
    proc = subprocess.run(
        [sys.executable, str(HERE / "probe.py"), str(HERE / candidate)],
        input=json.dumps(INPUTS), capture_output=True, text=True, env=env, timeout=30, check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(f"probe.py exited {proc.returncode} on {candidate}: {proc.stderr}")
    return json.loads(proc.stdout)


def check(label: str, condition: bool) -> None:
    print(f"{'ok  ' if condition else 'FAIL'} {label}")
    if not condition:
        raise SystemExit(1)


def main() -> int:
    without = _run("reference", with_fake_pip=False)
    check("without fake pip on PYTHONPATH, reference falls back to stdlib-emulation",
          without["install_mode"] == "stdlib-emulation")

    with_fake = _run("reference", with_fake_pip=True)
    check("with fake pip on PYTHONPATH, reference selects real-pip",
          with_fake["install_mode"] == "real-pip")
    check("real-pip mode still produces the correct installed output on reference",
          with_fake["installed_outputs"] == [{"value": "rock-and-roll"}, {"value": "user-at-host"}])

    scratch_fake = _run("wrong/scratch-copy", with_fake_pip=True)
    check("real-pip mode also excludes an undeclared scratch/ fix (known-bad (a))",
          scratch_fake["installed_outputs"][0] == {"value": "rock-and-roll-"})

    print("check_real_pip_mode: ok - mode-selection and real-pip install logic both proven")
    return 0


if __name__ == "__main__":
    sys.exit(main())
