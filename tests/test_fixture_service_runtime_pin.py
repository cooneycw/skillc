"""Pin the current reviewed flow-check build inputs (#276, #637).

`docker/profile-trial/build.py` builds the flow-check image from EVERY file
under `docker/trial/` plus a fixed set of subject and fixture inputs, so any
file added there moves `build_context_sha256`. The fixture-service shim
therefore lives in `docker/fixture-service/`. #637 deliberately upgrades the
shared native Codex recipe to 0.165.0, under the recorded ruling, without
rewriting historical image IDs, receipts or declarations. The values below
pin that new reviewed recipe. The check reads working files, not git, so it
runs in CI's shallow clone. `build.py` copies itself into the context as
`runtime-build.py`; an edit there also changes the context.

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
    "build_context_sha256": "4177260e9058a2e8f7118a7e8cf169a79d616576e8020eacade6bf51bb8501f6",
    "base_recipe_sha256": "23e9583d0c4498d37851d2d2cce8b7cb72ecf873fd4ce306e3b81739d78d8a85",
    "recipe_sha256": "1c8731b14c097db59b9daa3faef89d39340e369fee1f01b80e2ed5586e93a9a9",
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


def test_the_flow_check_build_context_and_recipe_match_the_reviewed_pin(tmp_path: Path) -> None:
    assert _digests(_inputs(), tmp_path) == GOLDEN


def test_the_pin_moves_when_a_file_enters_docker_trial(tmp_path: Path) -> None:
    # Negative control: the shim placed back under docker/trial/ must move the
    # context digest, or the comparison above is blind.
    inputs = _inputs()
    inputs["docker/trial/skillc-gh-shim.py"] = (ROOT / "docker/fixture-service/skillc-gh-shim.py").read_bytes()
    assert _digests(inputs, tmp_path)["build_context_sha256"] != GOLDEN["build_context_sha256"]
