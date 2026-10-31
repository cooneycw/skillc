"""#654: the real-Docker runner certifies the TESTED commit's product code.

R1 pins the runner's own verdict/summary/posting code to an installed copy
(`$INSTALLED_ROOT`). Product code is the opposite: `import skillc` inside the
certifying pytest must resolve to the checkout under test (`$WORK_CHECKOUT`).
#578 exported `PYTHONPATH="$INSTALLED_ROOT"` process-wide, so pytest inherited
it and every status certified main's tests against the runner pin's `skillc/`.

These tests drive the REAL `run-real-docker` and the REAL opt-in helper with no
daemon and no network: `docker`, `curl` and `uv` are fakes on PATH, and both
roots are local git repositories whose `skillc/` copies differ. The fake `uv`
runs with `-S` (no site-packages) and appends the checkout to `sys.path`, which
is where the editable install puts it - BEHIND any `PYTHONPATH` entry, exactly
the precedence that let the pinned copy win on evals26. It records what
`import skillc` resolved to. On the pre-fix script both tests are red.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "ci" / "real-docker" / "run-real-docker"

pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or not shutil.which("flock") or not shutil.which("git"),
    reason="needs Linux, flock and git",
)

_GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "init.defaultBranch=main"]


def _git(*args: str, cwd: Path) -> str:
    return subprocess.run([*_GIT, *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def _commit_tree(path: Path) -> str:
    _git("init", "-q", cwd=path)
    _git("add", "-A", cwd=path)
    _git("commit", "-q", "-m", "fixture", cwd=path)
    return _git("rev-parse", "HEAD", cwd=path)


def _fake_bin(tmp_path: Path, record: Path) -> Path:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    uv = bindir / "uv"
    uv.write_text(
        f"#!{sys.executable} -S\n"
        "import json, os, sys\n"
        "sys.path.append(os.getcwd())  # the editable install's position: after PYTHONPATH\n"
        "import skillc\n"
        f"with open({str(record)!r}, 'a') as fh:\n"
        "    fh.write(json.dumps({'argv': sys.argv[1:], 'skillc': skillc.__file__,\n"
        "                         'PYTHONPATH': os.environ.get('PYTHONPATH')}) + '\\n')\n"
    )
    docker = bindir / "docker"
    docker.write_text(
        "#!/bin/sh\n"
        '[ "$1" = run ] || exit 0\n'
        'for a in "$@"; do [ "$a" = github.com ] && { echo reachable; exit 0; }; done\n'
        "echo unreachable\n"
    )
    curl = bindir / "curl"
    curl.write_text("#!/bin/sh\nexit 0\n")
    for tool in (uv, docker, curl):
        tool.chmod(0o755)
    return bindir


def _roots(tmp_path: Path) -> tuple[Path, Path, str]:
    installed = tmp_path / "installed"
    shutil.copytree(ROOT / "ci", installed / "ci", ignore=shutil.ignore_patterns("__pycache__"))
    (installed / "skillc").mkdir()
    (installed / "skillc" / "__init__.py").write_text("PIN = 'installed'\n")
    _commit_tree(installed)

    seed = tmp_path / "seed"
    (seed / "skillc").mkdir(parents=True)
    (seed / "skillc" / "__init__.py").write_text("PIN = 'checkout'\n")
    sha = _commit_tree(seed)
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(seed), str(origin)], check=True)
    work = tmp_path / "work"
    subprocess.run(["git", "clone", "-q", str(origin), str(work)], check=True)
    return installed, work, sha


def _records(record: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in record.read_text().splitlines()] if record.exists() else []


@pytest.mark.parametrize("inherited_pythonpath", [False, True])
def test_certifying_pytest_imports_skillc_from_the_checkout_not_the_pin(
        tmp_path: Path, inherited_pythonpath: bool) -> None:
    installed, work, sha = _roots(tmp_path)
    record = tmp_path / "uv-calls.jsonl"
    bindir = _fake_bin(tmp_path, record)
    token = tmp_path / "token"
    token.write_text("t\n")
    config = tmp_path / "config.env"
    config.write_text(
        f"INSTALLED_ROOT={installed}\nWORK_CHECKOUT={work}\nLOCK_FILE={tmp_path / 'lock'}\n"
        f"GITHUB_TOKEN_FILE={token}\nGITHUB_REPO=example/skillc\nPREFLIGHT_IMAGE=fake\n"
        "LAN_PROBE_TARGET=192.0.2.1:9\nLOCK_WAIT_SECONDS=5\n"
    )
    env = {
        "PATH": f"{bindir}:{Path(sys.executable).parent}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "SKILLC_REAL_DOCKER_CONFIG": str(config),
    }
    if inherited_pythonpath:  # an operator shell that already carries one
        env["PYTHONPATH"] = str(installed)
    result = subprocess.run([str(RUNNER_PATH), sha], env=env, capture_output=True,
                            text=True, timeout=120, check=False)

    calls = _records(record)
    pytest_calls = [c for c in calls if c["argv"][:1] == ["run"]]
    assert pytest_calls, f"the runner never reached pytest:\n{result.stderr}"
    for call in calls:
        assert str(call["skillc"]).startswith(f"{work}/"), call
        assert call["PYTHONPATH"] is None, call


def test_optin_pytest_imports_skillc_from_the_checkout_not_the_pin(tmp_path: Path) -> None:
    """The opt-in helper itself runs with PYTHONPATH=$INSTALLED_ROOT (it needs
    the pinned `ci` package); the pytest it launches must not inherit that."""
    installed, work, _sha = _roots(tmp_path)
    record = tmp_path / "uv-calls.jsonl"
    bindir = _fake_bin(tmp_path, record)
    probe = (
        "import dataclasses, os, pathlib, sys\n"
        "from ci import real_docker_optin as o\n"
        "work = pathlib.Path(sys.argv[1])\n"
        "o.execute(work, work / 'report.xml', dataclasses.replace(o.FLOW_AUTO_COLD, seconds=60))\n"
    )
    env = {"PATH": f"{bindir}:/usr/bin:/bin", "HOME": str(tmp_path), "PYTHONPATH": str(installed)}
    result = subprocess.run([sys.executable, "-c", probe, str(work)], cwd=installed, env=env,
                            capture_output=True, text=True, timeout=60, check=False)

    calls = _records(record)
    assert [c["argv"][0] for c in calls] == ["sync", "run"], result.stderr
    for call in calls:
        assert str(call["skillc"]).startswith(f"{work}/"), call
        assert call["PYTHONPATH"] is None, call


def test_the_runner_never_exports_pythonpath_process_wide() -> None:
    """Structural companion to the behavioural test above: the helper calls
    set PYTHONPATH inline, so a process-wide export has no remaining reader
    except the pytest it must not reach."""
    for line in RUNNER_PATH.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("export "):
            assert "PYTHONPATH" not in line, line
