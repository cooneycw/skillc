"""Controls for the #462 failure-time capture (`tests/failure_context.py`).

Each case runs a small inner pytest session in a subprocess, with the plugin
registered exactly as `tests/conftest.py` registers it:

- an OUTER session (no marker inherited) records exactly one context per
  failure, with every section present, and none for a pass;
- a NESTED session (the marker of another live session inherited, as every
  subprocess pytest started by this suite inherits it) records NOTHING, which
  is what keeps the suite's many expected inner failures out of gate logs;
- the same two cases under xdist, where workers belong to the outer session;
- docker that hangs is bounded and recorded `unavailable`, never dropped;
- SKILLC_FAILURE_CONTEXT=0 records nothing.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import failure_context as fc
import pytest

TESTS_DIR = Path(__file__).resolve().parent

_CONFTEST = f'''
import sys
sys.path.insert(0, {str(TESTS_DIR)!r})
import failure_context

def pytest_configure(config):
    config.pluginmanager.register(failure_context, "skillc-failure-context")
'''

_TESTS = '''
import time

def test_passes():
    pass

def test_fails_after_a_moment():
    time.sleep(1.5)  # the sampler has history to report
    assert False, "expected inner failure"
'''

_DOCKER_TEST = '''
def test_docker_thing_fails():
    assert False
'''


def _run(tmp_path: Path, *, nested: bool, extra_args: tuple[str, ...] = (),
         env_extra: dict[str, str] | None = None, body: str = _TESTS) -> tuple[str, list[dict]]:
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "conftest.py").write_text(_CONFTEST)
    (proj / "test_inner.py").write_text(body)
    reports = tmp_path / "reports"
    env = {k: v for k, v in os.environ.items()
           if k not in (fc.OUTER_ENV, fc.DISABLE_ENV, "PYTEST_XDIST_WORKER",
                        "PYTEST_XDIST_WORKER_COUNT", "PYTEST_ADDOPTS")}
    env["PYTEST_REPORT_DIR"] = str(reports)
    if nested:
        # The marker a live outer session exports: this process is one.
        env[fc.OUTER_ENV] = str(os.getpid())
    env.update(env_extra or {})
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", *extra_args, str(proj)],
        cwd=proj, env=env, capture_output=True, text=True, timeout=120, check=False,
    )
    out = reports / "failure-context.jsonl"
    records = [json.loads(line) for line in out.read_text().splitlines()] if out.exists() else []
    return proc.stdout + proc.stderr, records


def test_an_outer_session_records_exactly_one_context_per_failure(tmp_path):
    output, records = _run(tmp_path, nested=False)
    assert "1 failed, 1 passed" in output
    assert [r["nodeid"] for r in records] == ["test_inner.py::test_fails_after_a_moment"]
    (record,) = records
    for key in ("now", "neighbours", "history", "sampler_gaps", "duration"):
        assert key in record, key
    assert record["history"], "the sampler took no samples during a 1.5 s test"
    assert isinstance(record["now"]["loadavg"], list)
    assert "procs_running" in record["now"]
    assert "FAILURE_CONTEXT: test_inner.py::test_fails_after_a_moment" in output
    assert "docker" not in record, "docker is queried only for docker tests"


def test_a_nested_session_records_nothing(tmp_path):
    """The committed control the ruling requires: the suite's expected inner
    failures (mutation and control runs) must not fill gate logs."""
    output, records = _run(tmp_path, nested=True)
    assert "1 failed, 1 passed" in output, "the inner failure must still happen"
    assert records == []
    assert "FAILURE_CONTEXT" not in output
    assert "failure context" not in output, "a nested session attached a context section"


def test_xdist_workers_record_for_their_outer_session(tmp_path):
    output, records = _run(tmp_path, nested=False, extra_args=("-n", "2"))
    assert "1 failed, 1 passed" in output
    assert [r["nodeid"] for r in records] == ["test_inner.py::test_fails_after_a_moment"]
    assert records[0]["neighbours"]["worker"] in ("gw0", "gw1")
    assert "FAILURE_CONTEXT: test_inner.py::test_fails_after_a_moment" in output


def test_a_nested_xdist_session_records_nothing(tmp_path):
    output, records = _run(tmp_path, nested=True, extra_args=("-n", "2"))
    assert "1 failed, 1 passed" in output
    assert records == []
    assert "FAILURE_CONTEXT" not in output
    assert "failure context" not in output, "a nested session attached a context section"


def test_a_hanging_docker_is_bounded_and_recorded_unavailable(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    docker = bindir / "docker"
    docker.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(3600)\n")
    docker.chmod(0o755)
    output, records = _run(
        tmp_path, nested=False, body=_DOCKER_TEST,
        env_extra={"PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}"},
    )
    assert "1 failed" in output
    (record,) = records
    assert str(record["docker"]["containers"]).startswith("unavailable")
    assert str(record["docker"]["kyle_containers"]).startswith("unavailable")
    assert str(record["docker"]["events_60s"]).startswith("unavailable")


def test_disabled_records_nothing(tmp_path):
    output, records = _run(tmp_path, nested=False, env_extra={fc.DISABLE_ENV: "0"})
    assert "1 failed, 1 passed" in output
    assert records == []


def test_psi_is_read_back_exactly():
    text = ("some avg10=1.25 avg60=0.50 avg300=0.10 total=123\n"
            "full avg10=0.75 avg60=0.25 avg300=0.05 total=45\n")
    assert fc.read_psi(text) == {"some10": 1.25, "some60": 0.5, "full10": 0.75, "full60": 0.25}


def test_the_kyle_count_keeps_no_names(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    docker = bindir / "docker"
    docker.write_text(
        f"#!{sys.executable}\nimport sys\n"
        "if sys.argv[1] == 'ps':\n    print('kyle-web-dev\\nkyle-master-x\\nsomething-else')\n"
        "else:\n    print('container\\ncontainer\\nnetwork')\n")
    docker.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    out = fc._docker()
    assert out == {"containers": 3, "kyle_containers": 2,
                   "events_60s": {"container": 2, "network": 1}}
    assert "kyle-web" not in json.dumps(out)


@pytest.mark.parametrize("text", ["", "garbage\n"])
def test_psi_tolerates_no_or_odd_input(text):
    assert fc.read_psi(text) == {}
