"""Real Docker certification of the Level 3 cicd-pipeline grader (#281).

Builds the runtime chain the task grades in - the flow-check profile runtime,
the cicd curl layer (#280), and the cicd project layer warmed from this task's
own `reference/uv.lock` - then runs `evals/level3/cicd-pipeline/qualify.py`,
which grades every case through skillc's staged verifier with the probe inside
that runtime (`--network none`), executing the candidates' generated CI.

MODES (skillc-400's D4 ruling): under run-real-docker, which holds evals26's
run.lock and says so (SKILLC_REAL_DOCKER_RUN_LOCK_HELD=1), the FULL matrix
runs and must report `QUALIFY: ok full (M of M)` - qualify.py itself fails a
full run that did not execute every manifest case. Anywhere else the
committed SUBSET runs and must say `subset (N of M)`.

Teardown follows #414's rule: images are removed only under run.lock and only
if absent before the build; otherwise the tagged build is kept and nothing is
removed. Skipped, not failed, without a reachable Docker daemon.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

import pytest

from skillc import docker_backend as d

ROOT = Path(__file__).resolve().parents[1]
TASK = ROOT / "evals" / "level3" / "cicd-pipeline"
_RUN_LOCK_HELD = os.environ.get("SKILLC_REAL_DOCKER_RUN_LOCK_HELD") == "1"

_DOCKER_BIN_PRESENT = shutil.which("docker") is not None
pytestmark = [
    pytest.mark.real_docker,
    pytest.mark.skipif(
        not _DOCKER_BIN_PRESENT or d.probe_daemon(["docker"]) is None,
        reason="no reachable Docker daemon in this environment (binary "
               + ("present" if _DOCKER_BIN_PRESENT else "absent")
               + ") - real-daemon execution is owed to the real-Docker runner (#315)",
    ),
]


def _load(name: str, relpath: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / relpath)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses resolve their module by name
    spec.loader.exec_module(module)
    return module


def _host_image_ids() -> set[str]:
    listed = subprocess.run(["docker", "image", "ls", "-a", "-q", "--no-trunc"], capture_output=True,
                            text=True, check=False, timeout=60)
    assert listed.returncode == 0, f"cannot list host images: {listed.stderr}"
    return set(listed.stdout.split())


@pytest.mark.timeout(3600)
def test_the_cicd_pipeline_grader_certifies_in_the_cicd_project_runtime() -> None:
    preexisting = _host_image_ids()
    scratch = Path(tempfile.mkdtemp(prefix="sk-281-live-"))
    receipts = {name: scratch / f"{name}.json" for name in ("base", "cicd", "project")}
    try:
        _load("profile_builder_281l", "docker/profile-trial/build.py").build_image(ROOT, receipts["base"])
        _load("cicd_builder_281l", "docker/cicd-trial/build.py").build_image(receipts["base"], receipts["cicd"])
        _load("project_builder_281l", "docker/cicd-project-trial/build.py").build_image(
            receipts["cicd"], TASK / "reference", receipts["project"])
        qualify = _load("qualify_281l", "evals/level3/cicd-pipeline/qualify.py")
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = qualify.main(["--receipt", str(receipts["project"]), *(["--full"] if _RUN_LOCK_HELD else [])])
        text = output.getvalue()
        total = len(qualify.manifest())
        if _RUN_LOCK_HELD:
            want = f"QUALIFY: ok full ({total} of {total})"
        else:
            want = f"QUALIFY: ok subset ({len(qualify.select(qualify.manifest(), full=False))} of {total})"
        last = text.strip().splitlines()[-1] if text.strip() else ""
        assert exit_code == 0 and last == want, f"qualify did not certify:\n{text[-4000:]}"
        assert not re.search(r"^XX ", text, re.MULTILINE), text
    finally:
        if _RUN_LOCK_HELD:
            built = [json.loads(receipts[n].read_bytes())["image_id"] for n in ("project", "cicd", "base")
                     if receipts[n].is_file()]
            for image in [i for i in dict.fromkeys(built) if i not in preexisting]:
                subprocess.run(["docker", "image", "rm", "-f", image], capture_output=True, check=False)
        shutil.rmtree(scratch, ignore_errors=True)
