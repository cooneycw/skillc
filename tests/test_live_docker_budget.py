"""Real-Docker live tests run their backend on an explicit daemon budget (#390).

`DockerBackend` defaults every daemon call - container start included - to
`DAEMON_TIMEOUT` (5 s). On #315's dedicated runner a real `docker run -d`
occasionally stalls past that right after an image build: measured 7.61 s
once in 27 starts, against a typical 0.13-0.62 s. Two of campaign 1's 22
negative controls failed in setup that way, before reaching their planted
fault, so they proved nothing. Production is not exposed: every CLI path
passes its own `daemon_timeout`.

Two instruments:

- A static check that every `DockerBackend` (or subclass) constructed in a
  `tests/*_live.py` file passes `daemon_timeout`. It fails on the pre-#390
  tree, which had six such constructions and none passing it. A population
  floor keeps a blind scan from passing, and a planted construction proves
  it can report the other verdict.
- Behaviour on the fake CLI's `.delay-run`: a start slower than the module
  default succeeds on the live budget, and a start slower than the budget
  is still refused - the budget is a bound, not an exemption.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest
from conftest import LIVE_DOCKER_DAEMON_TIMEOUT

from skillc import docker_backend as d
from skillc.backend import BackendUnavailable

ROOT = Path(__file__).resolve().parent.parent
LIVE_FILES = sorted((ROOT / "tests").glob("test_*_live.py"))
FAKE_DOCKER = ROOT / "tests" / "fixtures" / "docker-backend" / "fake_docker.py"

#: Six constructions existed when #390 was written. A scan that finds fewer has
#: stopped reading them, which must not read as "all of them pass the budget".
CONSTRUCTION_FLOOR = 6


def _backend_classes(tree: ast.Module) -> set[str]:
    """`DockerBackend` plus every class this module derives from it."""
    names = {"DockerBackend"}
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name not in names:
                for base in node.bases:
                    base_name = base.attr if isinstance(base, ast.Attribute) else getattr(base, "id", None)
                    if base_name in names:
                        names.add(node.name)
                        changed = True
    return names


def _constructions(source: str, filename: str) -> list[tuple[str, bool]]:
    """(file:line, passes daemon_timeout) for each backend construction."""
    tree = ast.parse(source, filename=filename)
    classes = _backend_classes(tree)
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        if name in classes:
            found.append((f"{filename}:{node.lineno}",
                          any(kw.arg == "daemon_timeout" for kw in node.keywords)))
    return sorted(found, key=lambda item: int(item[0].rsplit(":", 1)[1]))


def _all_live_constructions() -> list[tuple[str, bool]]:
    found: list[tuple[str, bool]] = []
    for path in LIVE_FILES:
        found.extend(_constructions(path.read_text(encoding="utf-8"), path.relative_to(ROOT).as_posix()))
    return found


def test_every_live_backend_construction_passes_a_daemon_budget() -> None:
    found = _all_live_constructions()
    assert len(found) >= CONSTRUCTION_FLOOR, f"scanned {len(LIVE_FILES)} live files, found only {found}"
    missing = [where for where, passes in found if not passes]
    assert not missing, f"real-Docker backends on the 5 s module default: {missing}"


def test_red_case_a_construction_without_the_budget_is_named() -> None:
    planted = (
        "from skillc import docker_backend as d\n"
        "class _Sub(d.DockerBackend):\n"
        "    pass\n"
        "a = d.DockerBackend(image='x', base_dir=None, daemon_timeout=30.0)\n"
        "b = _Sub(image='x', base_dir=None)\n"
    )
    found = _constructions(planted, "planted_live.py")
    assert found == [("planted_live.py:4", True), ("planted_live.py:5", False)]


def _fake_backend(base: Path, state: Path, budget: float) -> d.DockerBackend:
    return d.DockerBackend(
        image="fake-image:1", base_dir=base,
        docker_bin=(sys.executable, str(FAKE_DOCKER), "--state", str(state)),
        network="none", daemon_timeout=budget,
    )


def test_a_start_slower_than_the_module_default_succeeds_on_the_live_budget(tmp_path: Path) -> None:
    delay = d.DAEMON_TIMEOUT + 1.0
    assert delay < LIVE_DOCKER_DAEMON_TIMEOUT
    state = tmp_path / "state"
    state.mkdir()
    (state / ".delay-run").write_text(str(delay), encoding="utf-8")

    backend = _fake_backend(tmp_path / "base", state, LIVE_DOCKER_DAEMON_TIMEOUT)
    handle = backend.prepare("a-live-budget-0000000000001")
    backend.destroy(handle)


@pytest.mark.parametrize("budget, delay", [(d.DAEMON_TIMEOUT, d.DAEMON_TIMEOUT + 1.0), (1.0, 3.0)])
def test_a_start_slower_than_the_budget_is_still_refused(tmp_path: Path, budget: float, delay: float) -> None:
    """The first case is the pre-#390 live test: the 5 s default refuses a 6 s start."""
    state = tmp_path / "state"
    state.mkdir()
    (state / ".delay-run").write_text(str(delay), encoding="utf-8")

    backend = _fake_backend(tmp_path / "base", state, budget)
    with pytest.raises(BackendUnavailable, match="timed out"):
        backend.prepare("a-live-budget-0000000000002")
