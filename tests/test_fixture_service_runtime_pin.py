"""#276 must not move the pinned flow-check runtime (orchestrator ruling).

`docker/profile-trial/build.py` builds the flow-check image from EVERY file
under `docker/trial/` plus a fixed set of subject and fixture inputs, so any
file added there moves `build_context_sha256` - the runtime the final #375 run
is pre-registered against. The fixture-service shim therefore lives in
`docker/fixture-service/`. This pins the context and recipe digests as measured
on #276's base (origin/main 88b3999 and 1fc1e6e agree). It reads the working
tree, not git, so it runs on CI's shallow clone.

A change that moves these digests on purpose needs an orchestrator ruling,
and then a new golden value here - never a silent update.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("profile_trial_build_pin", ROOT / "docker/profile-trial/build.py")
assert _spec is not None and _spec.loader is not None
build: Any = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build)

GOLDEN = {
    "build_context_sha256": "0fda8029dafe53a49308f99b52b78de39079daa6ff55efdd147aa91c21c1a114",
    "base_recipe_sha256": "8dd69ef9b9de6ae2d777f98d4a6dbb76ef25d938fc8799bd3c81453c756a92b6",
    "recipe_sha256": "ed3290c0983ba9e72e9a64365127890d33bc5aa540ab3d104959f9e52b94eb96",
}


def _inputs() -> dict[str, bytes]:
    names = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "docker/trial").rglob("*")
                   if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc")
    names += [f"{build.SUBJECT}/subject.json", f"{build.SUBJECT}/evidence/inventory.json"]
    names += [f"{build.FIXTURE}/{name}" for name in ("pyproject.toml", "uv.lock")]
    return {name: (ROOT / name).read_bytes() for name in names}


def _digests(inputs: dict[str, bytes], tmp_path: Path) -> dict[str, str]:
    prepared = build.prepare(ROOT, tmp_path / "context", inputs=inputs, source_commit="0" * 40)
    return {key: prepared[key] for key in GOLDEN}


def test_the_flow_check_build_context_and_recipe_are_unchanged(tmp_path: Path) -> None:
    assert _digests(_inputs(), tmp_path) == GOLDEN


def test_the_pin_moves_when_a_file_enters_docker_trial(tmp_path: Path) -> None:
    # Negative control: the shim placed back under docker/trial/ must move the
    # context digest, or the comparison above is blind.
    inputs = _inputs()
    inputs["docker/trial/skillc-gh-shim.py"] = (ROOT / "docker/fixture-service/skillc-gh-shim.py").read_bytes()
    assert _digests(inputs, tmp_path)["build_context_sha256"] != GOLDEN["build_context_sha256"]
