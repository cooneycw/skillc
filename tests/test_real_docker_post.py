"""Tests for `ci/real_docker_post.py` (#315). The subprocess test below is
R1's required red case: proving the posted verdict is computed by the
INSTALLED copy, never by a copy the requested commit could have edited."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from ci import check_real_docker_ran as c
from ci import real_docker_post as p

ROOT = Path(__file__).resolve().parent.parent
SHA = "a" * 40
RUNNER_SHA = "b" * 40

_FAKE_EXTERNAL = '''#!/usr/bin/env python3
import json, os, pathlib, sys
tool = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
event = {"tool": tool}
if tool == "curl":
    event["payload"] = json.loads(args[args.index("-d") + 1])
    event["config"] = args[args.index("-K") + 1]
if tool == "docker":
    event["operation"] = args[:2]
with open(os.environ["RUNNER_TEST_EVENTS"], "a") as stream:
    stream.write(json.dumps(event) + "\\n")
if tool == "git" and "rev-parse" in args:
    print("b" * 40 if args[1] == os.environ["RUNNER_TEST_INSTALLED"] else "a" * 40)
if tool == "docker" and args[0] == "run":
    print("reachable" if args[-3] == "github.com" else "unreachable")
'''


def _run_installed_runner(
    tmp_path: Path, status: str, break_spec: str, helper: str | None = None,
) -> tuple[subprocess.CompletedProcess[str], list[dict[str, Any]]]:
    """Run the actual shell and posting modules; replace external I/O only."""
    installed = tmp_path / "installed"
    shutil.copytree(ROOT / "ci", installed / "ci")
    if helper is not None:
        (installed / "ci" / "real_docker_post.py").write_text(helper)
    checkout = tmp_path / "checkout"
    (checkout / ".git").mkdir(parents=True)
    (checkout / "reports").mkdir()
    if status != c.ERROR:
        cases = [f'<testcase classname="{name}" name="test_intact"/>' for name in c.DECLARED_REAL_DOCKER_FILES]
        if status == c.FAILURE:
            cases.append(
                '<testcase classname="tests.test_trial_image_tools_live" name="test_uv">'
                '<skipped type="pytest.xfail" message="no-uv"/></testcase>',
            )
        (checkout / "reports" / "real-docker-report.xml").write_text(
            '<testsuite>' + ''.join(cases) + '</testsuite>',
        )
    token = tmp_path / "token"
    token.write_text("not-a-credential")
    config = tmp_path / "config.env"
    values = {
        "INSTALLED_ROOT": str(installed), "WORK_CHECKOUT": str(checkout),
        "LOCK_FILE": str(tmp_path / "run.lock"), "GITHUB_TOKEN_FILE": str(token),
        "GITHUB_REPO": "example/project", "GITHUB_COMMENT_ISSUE": "315",
        "PREFLIGHT_IMAGE": "probe-fixture", "LAN_PROBE_TARGET": "target.invalid:443",
    }
    config.write_text(''.join(f'{key}={shlex.quote(value)}\n' for key, value in values.items()))
    binaries = tmp_path / "bin"
    binaries.mkdir()
    (binaries / "python3").symlink_to(sys.executable)
    for name in ("git", "docker", "curl", "uv"):
        command = binaries / name
        command.write_text(_FAKE_EXTERNAL)
        command.chmod(0o755)
    events = tmp_path / "events.jsonl"
    env = {
        "PATH": f"{binaries}{os.pathsep}{os.defpath}",
        "SKILLC_REAL_DOCKER_CONFIG": str(config),
        "RUNNER_TEST_EVENTS": str(events), "RUNNER_TEST_INSTALLED": str(installed),
    }
    result = subprocess.run(
        ["bash", str(installed / "ci" / "real-docker" / "run-real-docker"), SHA, "--break", break_spec],
        cwd=tmp_path, env=env, text=True, capture_output=True, timeout=30, check=False,
    )
    return result, [json.loads(line) for line in events.read_text().splitlines()]


@pytest.mark.parametrize(("status", "break_spec", "context", "exit_code"), [
    (c.SUCCESS, "none", "skillc/real-docker", 0),
    (c.FAILURE, "none", "skillc/real-docker", 1),
    (c.FAILURE, "trialimage:no-uv", "skillc/real-docker-control", 1),
    (c.ERROR, "none", "skillc/real-docker", 2),
    (c.ERROR, "trialimage:no-uv", "skillc/real-docker-control", 2),
])
def test_runner_posts_every_valid_verdict_and_cleans_up(
    tmp_path: Path, status: str, break_spec: str, context: str, exit_code: int,
) -> None:
    result, events = _run_installed_runner(tmp_path, status, break_spec)
    assert result.returncode == exit_code, result.stderr
    posts = [event for event in events if event["tool"] == "curl"]
    statuses = [event["payload"] for event in posts if "context" in event["payload"]]
    assert len(statuses) == 1, result.stderr
    assert statuses[0]["state"] == {c.SUCCESS: "success", c.FAILURE: "failure", c.ERROR: "error"}[status]
    assert statuses[0]["context"] == context
    assert ("EXPECTED-RED" in statuses[0]["description"]) == (break_spec != "none")
    assert len(posts) == 2  # commit status and configured comment
    assert all(not Path(str(event["config"])).exists() for event in posts)
    operations = {tuple(event["operation"]) for event in events if event["tool"] == "docker"}
    # #414: the run snapshots before and cleans only its own artifacts after -
    # never a host-wide prune (cleanup-lib.sh, tests/test_real_docker_cleanup.py).
    assert {("images", "-aq"), ("ps", "-aq"), ("images", "-q")} <= operations  # snapshot, then removal
    assert not [op for op in operations if "prune" in op]


@pytest.mark.parametrize("helper", [
    "raise RuntimeError('helper failed')\n",
    "print('not a verdict')\n",
    "print('SUCCESS\\nlooks green\\n---\\nbody'); raise SystemExit(9)\n",
    "print('SUCCESS\\nlooks green\\n---\\nbody'); raise SystemExit(1)\n",
    "print('SUCCESS\\nlooks green')\n",
    "print('SUCCESS\\n\\n---\\nbody')\n",
])
def test_runner_reports_helper_crash_or_malformed_output_as_error(tmp_path: Path, helper: str) -> None:
    result, events = _run_installed_runner(tmp_path, c.SUCCESS, "trialimage:no-uv", helper)
    assert result.returncode == 2, result.stderr
    statuses = [
        event["payload"] for event in events
        if event["tool"] == "curl" and "context" in event["payload"]
    ]
    assert len(statuses) == 1, result.stderr
    assert statuses[0]["state"] == "error"
    assert statuses[0]["context"] == "skillc/real-docker-control"
    # Cleanup was still reached: its removal listing (`images -q`), distinct
    # from the pre-run snapshot's `images -aq` (#414).
    assert any(event.get("operation") == ["images", "-q"] for event in events)

_FAIL_REPORT = (
    '<?xml version="1.0"?><testsuites><testsuite name="pytest">'
    '<testcase classname="tests.test_decide_reply_channel_live" name="test_x" time="1.0">'
    '<failure message="boom">trace</failure></testcase>'
    '</testsuite></testsuites>'
)

#: A complete-enough malicious stub: always claims SUCCESS regardless of
#: input, but still exports every name `real_docker_post.py` imports, so a
#: vulnerable invocation fails by LYING, not by crashing on an incomplete
#: fixture - a crash would make the mutation-check test below pass for the
#: wrong reason.
_MALICIOUS_STUB = (
    "SUCCESS = 'SUCCESS'\n"
    "FAILURE = 'FAILURE'\n"
    "ERROR = 'ERROR'\n"
    "class Verdict:\n"
    "    def __init__(self, **kw): self.status = 'SUCCESS'; self.reason = 'lying'\n"
    "    executed_by_file = {}\n"
    "    failed_ids = ()\n"
    "    skipped_only_files = ()\n"
    "def verdict(*a, **kw): return Verdict()\n"
)


def test_compute_maps_a_missing_report_to_error(tmp_path: Path) -> None:
    result = p.compute(str(tmp_path / "missing.xml"), sha=SHA, runner_sha=RUNNER_SHA)
    assert result.status == c.ERROR


def test_render_contains_all_three_sections(tmp_path: Path) -> None:
    report = tmp_path / "report.xml"
    report.write_text(_FAIL_REPORT, encoding="utf-8")
    result = p.compute(str(report), sha=SHA, runner_sha=RUNNER_SHA)
    text = p.render(result, sha=SHA, runner_sha=RUNNER_SHA)
    lines = text.split("\n")
    assert lines[0] == "FAILURE"
    assert "---" in lines
    assert "Full logs are retained on the runner host only." in text


def test_main_exit_code_matches_the_status_word(tmp_path: Path) -> None:
    report = tmp_path / "report.xml"
    report.write_text(_FAIL_REPORT, encoding="utf-8")
    assert p.main(["real_docker_post.py", str(report), SHA, RUNNER_SHA]) == 1


# --------------------------------------------------------------- R1's red case


def test_red_case_r1_a_malicious_checkout_copy_cannot_change_the_posted_verdict(tmp_path: Path) -> None:
    """R1, verbatim from the orchestrator's review: 'a fixture checkout
    whose own check_real_docker_ran.py always says SUCCESS must still
    yield FAILURE on a failing report.'

    Builds two separate trees: `installed/` (a copy of THIS repo's real
    `ci/` package - the reviewed, pinned installation) and `checkout/` (a
    fixture simulating a requested commit, whose OWN `ci/check_real_docker_
    ran.py` is a malicious stub that always reports SUCCESS regardless of
    input). Invokes `real_docker_post.py` exactly as `run-real-docker` is
    specified to: by the INSTALLED copy's absolute path, with `PYTHONPATH`
    set to the installed root only, and the process's CURRENT WORKING
    DIRECTORY set to the checkout (as it would be right after a pytest run
    there) - the adversarial condition this test exists to rule out.

    A failing report must still come back FAILURE, never the checkout's
    claimed SUCCESS - proving the installed copy's code ran, not the
    checkout's."""
    installed = tmp_path / "installed"
    checkout = tmp_path / "checkout"
    (installed / "ci").mkdir(parents=True)
    (checkout / "ci").mkdir(parents=True)

    # The installed copy: the REAL modules, copied byte-for-byte from this repo.
    for name in ("check_real_docker_ran.py", "real_docker_summary.py", "real_docker_post.py"):
        (installed / "ci" / name).write_bytes((ROOT / "ci" / name).read_bytes())
    (installed / "ci" / "__init__.py").write_text("", encoding="utf-8")

    # The checkout: a MALICIOUS check_real_docker_ran.py that always claims
    # SUCCESS, no matter what report it is handed - simulating a requested
    # commit that edited this file to lie about its own result.
    (checkout / "ci" / "check_real_docker_ran.py").write_text(_MALICIOUS_STUB, encoding="utf-8")
    (checkout / "ci" / "__init__.py").write_text("", encoding="utf-8")

    report = checkout / "report.xml"  # the checkout also holds the report pytest wrote
    report.write_text(_FAIL_REPORT, encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(installed / "ci" / "real_docker_post.py"), str(report), SHA, RUNNER_SHA],
        cwd=str(checkout),  # exactly where run-real-docker is after its pytest invocation
        env={"PYTHONPATH": str(installed), "PATH": "/usr/bin:/bin"},  # ONLY the installed root
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.stdout.split("\n")[0] == "FAILURE", (
        f"the malicious checkout copy influenced the posted verdict - stdout was:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    assert result.returncode == 1


def test_mutation_check_pointing_pythonpath_at_the_checkout_leaks_the_lie(tmp_path: Path) -> None:
    """Mutation check for the red case above, made concrete rather than
    asserted: the SAME two trees, the SAME failing report, but invoked the
    VULNERABLE way - `PYTHONPATH` pointed at the checkout instead of the
    installed copy (what `run-real-docker` must never do). This must
    produce the malicious stub's `SUCCESS`, proving the red case above is a
    real attack this design closes and not an inert scenario that would
    pass under any invocation."""
    installed = tmp_path / "installed"
    checkout = tmp_path / "checkout"
    (installed / "ci").mkdir(parents=True)
    (checkout / "ci").mkdir(parents=True)

    for name in ("check_real_docker_ran.py", "real_docker_summary.py", "real_docker_post.py"):
        (installed / "ci" / name).write_bytes((ROOT / "ci" / name).read_bytes())
    (installed / "ci" / "__init__.py").write_text("", encoding="utf-8")

    (checkout / "ci" / "check_real_docker_ran.py").write_text(_MALICIOUS_STUB, encoding="utf-8")
    # The checkout needs a working real_docker_summary.py too, for this
    # (deliberately vulnerable) invocation to resolve ALL of real_docker_
    # post.py's imports from the checkout, exactly as a fully self-contained
    # malicious commit would ship both files together, not just one.
    (checkout / "ci" / "real_docker_summary.py").write_bytes((ROOT / "ci" / "real_docker_summary.py").read_bytes())
    (checkout / "ci" / "__init__.py").write_text("", encoding="utf-8")

    report = checkout / "report.xml"
    report.write_text(_FAIL_REPORT, encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(installed / "ci" / "real_docker_post.py"), str(report), SHA, RUNNER_SHA],
        cwd=str(checkout),
        # THE MUTATION: PYTHONPATH points at the checkout, not the installed
        # copy - exactly the invocation R1 forbids.
        env={"PYTHONPATH": str(checkout), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.stdout.split("\n")[0] == "SUCCESS", (
        f"expected the vulnerable invocation to leak the malicious stub's SUCCESS - got:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}\nif this changed, the red case above may no longer be testing anything real"
    )
