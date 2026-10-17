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


BACKEND_MODULE = "skillc.docker_backend"


def _bindings(tree: ast.Module) -> tuple[set[str], set[str]]:
    """Names bound to the `skillc.docker_backend` module, and names bound to
    its `DockerBackend` class or a subclass: imports (with `as`), simple
    assignments and class definitions. A same-named class that does not derive
    from it is not counted. Bindings are per file, not per scope: a file that
    binds the real class in one function and defines an unrelated
    `DockerBackend` in another reads the second as the backend - a loud false
    red, never a silent green. Dynamic construction (`getattr`, a factory
    defined in another module) is outside what a source scan can resolve."""
    modules: set[str] = set()
    classes: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == BACKEND_MODULE and alias.asname:
                    modules.add(alias.asname)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if node.module == "skillc" and alias.name == "docker_backend":
                    modules.add(alias.asname or alias.name)
                elif node.module == BACKEND_MODULE and alias.name == "DockerBackend":
                    classes.add(alias.asname or alias.name)

    def is_backend(expr: ast.expr) -> bool:
        if isinstance(expr, ast.Name):
            return expr.id in classes
        if isinstance(expr, ast.Attribute) and expr.attr == "DockerBackend":
            value = expr.value
            if isinstance(value, ast.Name):
                return value.id in modules
            return ast.unparse(value) == BACKEND_MODULE
        return False

    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name not in classes:
                if any(is_backend(base) for base in node.bases):
                    classes.add(node.name)
                    changed = True
            elif isinstance(node, ast.Assign):
                value = node.value
                is_module = (isinstance(value, ast.Name) and value.id in modules) \
                    or ast.unparse(value) == BACKEND_MODULE
                bound = modules if is_module else classes if is_backend(value) else None
                if bound is None:
                    continue
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id not in bound:
                        bound.add(target.id)
                        changed = True
    return modules, classes


def _constructions(source: str, filename: str) -> list[tuple[str, bool]]:
    """(file:line, passes daemon_timeout) for each backend construction."""
    tree = ast.parse(source, filename=filename)
    modules, classes = _bindings(tree)
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        constructs = (
            (isinstance(func, ast.Name) and func.id in classes)
            or (isinstance(func, ast.Attribute) and func.attr == "DockerBackend"
                and ((isinstance(func.value, ast.Name) and func.value.id in modules)
                     or ast.unparse(func.value) == BACKEND_MODULE))
        )
        if constructs:
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


def test_red_case_aliased_constructions_are_resolved() -> None:
    """Counter-model finding (#390): a name-only scan let an imported or
    assigned alias through. Each spelling below binds the real class."""
    planted = (
        "import skillc.docker_backend as dbm\n"
        "from skillc.docker_backend import DockerBackend as DB\n"
        "Backend = dbm.DockerBackend\n"
        "a = DB(image='x', base_dir=None)\n"
        "b = Backend(image='x', base_dir=None)\n"
        "c = dbm.DockerBackend(image='x', base_dir=None, daemon_timeout=30.0)\n"
        "alias = dbm\n"
        "e = alias.DockerBackend(image='x', base_dir=None)\n"
    )
    assert _constructions(planted, "planted_live.py") == [
        ("planted_live.py:4", False), ("planted_live.py:5", False), ("planted_live.py:6", True),
        ("planted_live.py:8", False),
    ]


def test_a_same_named_class_that_is_not_the_backend_is_not_counted() -> None:
    planted = (
        "class DockerBackend:\n"
        "    def __init__(self, **kwargs): ...\n"
        "x = DockerBackend(image='x')\n"
    )
    assert _constructions(planted, "planted_live.py") == []


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
