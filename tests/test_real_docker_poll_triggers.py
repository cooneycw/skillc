"""Whole-process tests for `ci/real-docker/poll-triggers` (#392), the
systemd timer's entry point for the #315 runner.

Before #392 the script handed each page of GitHub issue comments to
`python3 -c` as a command-line argument. Linux caps one argv string at
128 KiB (`MAX_ARG_STRLEN`), and one page of this repository's newest 100
comments already carries about 162 KB of body text, so every tick died
with `Argument list too long` before deciding anything. The red case below
reproduces that with a fixture page; the rest pins the trigger semantics
the fix must keep (newest-first fetch, stop at a known id, 20-page cap,
one run per decision) - semantics that had no whole-process control at all
before this file (the README's "Known simplifications" said so).

These run the REAL script with external I/O replaced: `curl` serves fixture
JSON and logs every URL, and the installed `run-real-docker` is a recorder
that logs the sha it was asked to run. No network, no Docker. They prove the
script's own logic, not real GitHub pagination - the live tick on the runner
host is what closes that gap (#392 acceptance item 3).
"""

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

ROOT = Path(__file__).resolve().parent.parent
REPO = "example/project"
OWNER = "the-owner"
MAIN_SHA = "c" * 40
REQUESTED_SHA = "d" * 40
MAX_ARG_STRLEN = 128 * 1024

_FAKE_CURL = '''#!/usr/bin/env python3
import json, os, pathlib, sys, urllib.parse
url = sys.argv[-1]
with open(os.environ["POLL_TEST_EVENTS"], "a") as stream:
    stream.write(json.dumps({"tool": "curl", "url": url, "argv": sys.argv[1:]}) + "\\n")
fixtures = pathlib.Path(os.environ["POLL_TEST_FIXTURES"])
parsed = urllib.parse.urlparse(url)
if parsed.path.endswith("/commits/main"):
    print(json.dumps({"sha": os.environ["POLL_TEST_MAIN_SHA"]}))
elif parsed.path.endswith("/issues/comments"):
    page = urllib.parse.parse_qs(parsed.query)["page"][0]
    page_file = fixtures / f"page-{page}.json"
    content = page_file.read_text() if page_file.exists() else "[]"
    if content == "FAIL":
        sys.stdout.write('{"message": "Server Error"}')
        sys.exit(22)
    sys.stdout.write(content)
elif parsed.path.endswith("/repos/" + os.environ["POLL_TEST_REPO"]):
    print(json.dumps({"owner": {"login": os.environ["POLL_TEST_OWNER"]}}))
else:
    print("unexpected url " + url, file=sys.stderr)
    sys.exit(22)
'''

_FAKE_RUNNER = '''#!/usr/bin/env python3
import json, os, sys
with open(os.environ["POLL_TEST_EVENTS"], "a") as stream:
    stream.write(json.dumps({"tool": "runner", "argv": sys.argv[1:]}) + "\\n")
sys.exit(int(os.environ.get("POLL_TEST_RUNNER_EXIT", "0")))
'''


def _comment(comment_id: int, body: str, login: str = "someone-else") -> dict[str, Any]:
    return {"id": comment_id, "body": body, "user": {"login": login}}


def _page(first_id: int, count: int = 100, body_bytes: int = 64) -> list[dict[str, Any]]:
    """`count` comments, ids DESCENDING from `first_id` (newest first, as
    the script requests)."""
    return [_comment(first_id - i, "x" * body_bytes) for i in range(count)]


def _tick(
    tmp_path: Path,
    pages: dict[int, list[dict[str, Any]]],
    *,
    state: dict[str, Any],
    main_sha: str = MAIN_SHA,
    runner_exit: int = 0,
    raw_pages: dict[int, str] | None = None,
    python3: Path | None = None,
    hostile_cwd: bool = False,
    relative_paths: bool = False,
) -> tuple[subprocess.CompletedProcess[str], list[dict[str, Any]], dict[str, Any]]:
    installed = tmp_path / "installed"
    shutil.copytree(ROOT / "ci", installed / "ci")
    runner = installed / "ci" / "real-docker" / "run-real-docker"
    runner.write_text(_FAKE_RUNNER)
    runner.chmod(0o755)

    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    for number, comments in pages.items():
        (fixtures / f"page-{number}.json").write_text(json.dumps(comments))
    for number, raw in (raw_pages or {}).items():
        (fixtures / f"page-{number}.json").write_text(raw)

    token = tmp_path / "token"
    token.write_text("not-a-credential")
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps(state))
    config = tmp_path / "config.env"
    values = {
        "INSTALLED_ROOT": str(installed), "GITHUB_REPO": REPO,
        "GITHUB_TOKEN_FILE": str(token), "STATE_FILE": str(state_file),
    }
    config.write_text("".join(f"{key}={shlex.quote(value)}\n" for key, value in values.items()))

    binaries = tmp_path / "bin"
    binaries.mkdir()
    (binaries / "python3").symlink_to(python3 or sys.executable)
    curl = binaries / "curl"
    curl.write_text(_FAKE_CURL)
    curl.chmod(0o755)

    events = tmp_path / "events.jsonl"
    events.touch()
    work = tmp_path
    if hostile_cwd:
        work = tmp_path / "hostile"
        (work / "ci").mkdir(parents=True)
        (work / "ci/__init__.py").write_text("")
        (work / "ci/real_docker_trigger.py").write_text(
            "from types import SimpleNamespace\nfrom pathlib import Path\n"
            f"Path({str(tmp_path / 'imported-target')!r}).write_text('bad')\n"
            "def select_requested_shas(*a, **kw):\n"
            f" return SimpleNamespace(requests=((999,{REQUESTED_SHA!r}),), newly_seen_ids=(999,), optin_requests=())\n")
        (work / "json.py").write_text(
            f"from pathlib import Path\nPath({str(tmp_path / 'imported-json')!r}).write_text('bad')\n"
            "raise SystemExit('WORK json was imported')\n")
    if relative_paths:
        for key in ('INSTALLED_ROOT', 'STATE_FILE', 'GITHUB_TOKEN_FILE'):
            values[key] = os.path.relpath(values[key], work)
        config.write_text(''.join(f'{key}={shlex.quote(value)}\n' for key, value in values.items()))
    env = {
        "PATH": f"{binaries}{os.pathsep}{os.defpath}",
        "SKILLC_REAL_DOCKER_CONFIG": os.path.relpath(config, work) if relative_paths else str(config),
        "POLL_TEST_EVENTS": str(events), "POLL_TEST_FIXTURES": str(fixtures),
        "POLL_TEST_MAIN_SHA": main_sha, "POLL_TEST_REPO": REPO, "POLL_TEST_OWNER": OWNER,
        "POLL_TEST_RUNNER_EXIT": str(runner_exit),
    }
    result = subprocess.run(
        ["bash", str(installed / "ci" / "real-docker" / "poll-triggers")], cwd=work, env=env, text=True,
        capture_output=True, timeout=60, check=False,
    )
    logged = [json.loads(line) for line in events.read_text().splitlines()]
    return result, logged, json.loads(state_file.read_text())


def _runs(events: list[dict[str, Any]]) -> list[list[str]]:
    return [event["argv"] for event in events if event["tool"] == "runner"]


def _comment_page_numbers(events: list[dict[str, Any]]) -> list[int]:
    from urllib.parse import parse_qs, urlparse
    return [
        int(parse_qs(urlparse(event["url"]).query)["page"][0])
        for event in events
        if event["tool"] == "curl" and "/issues/comments" in event["url"]
    ]


# ----------------------------------------------------------------- the red case

def test_red_case_a_page_larger_than_max_arg_strlen_is_an_idle_tick_not_a_crash(tmp_path: Path) -> None:
    """#392's defect. 100 comments whose JSON exceeds 128 KiB: on the
    pre-fix script this dies with `Argument list too long` (exit 126);
    fixed, it is an ordinary tick with nothing to do."""
    big_page = _page(10_000, body_bytes=1_800)
    assert len(json.dumps(big_page).encode()) > MAX_ARG_STRLEN  # the fixture really is oversized
    state = {"last_main_sha": MAIN_SHA, "processed_comment_ids": []}

    result, events, new_state = _tick(tmp_path, {1: big_page}, state=state)

    assert "Argument list too long" not in result.stderr
    assert result.returncode == 0, result.stderr
    assert _runs(events) == []
    # Every comment was seen and none triggered, so all are remembered.
    assert new_state["processed_comment_ids"] == sorted(c["id"] for c in big_page)
    assert new_state["last_main_sha"] == MAIN_SHA


def test_no_github_content_reaches_python_on_the_command_line(tmp_path: Path) -> None:
    """The structural form of the fix: a distinctive comment body must never
    appear in any python3 argv. Checked by wrapping python3 and logging its
    arguments, so a future edit that reintroduces argv passing fails here even
    when the fixture is small enough to fit."""
    marker = "MARKER-392-comment-body-must-stay-off-argv"
    pages = {1: [_comment(5, marker)]}
    state = {"last_main_sha": MAIN_SHA, "processed_comment_ids": []}
    real_python = sys.executable

    # Interpose a logging python3 ahead of the symlink _tick installs.
    wrapper_dir = tmp_path / "wrap"
    wrapper_dir.mkdir()
    argv_log = tmp_path / "python-argv.log"
    wrapper = wrapper_dir / "python3"
    wrapper.write_text(
        "#!/bin/bash\n"
        f'printf "%s\\0" "$@" >> {shlex.quote(str(argv_log))}\n'
        f'exec {shlex.quote(real_python)} "$@"\n',
    )
    wrapper.chmod(0o755)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    result, _events, _state = _tick(run_dir, pages, state=state, python3=wrapper)

    assert result.returncode == 0, result.stderr
    logged = argv_log.read_bytes()
    assert logged, "the python3 wrapper logged nothing - this check would be blind"
    assert marker.encode() not in logged


# -------------------------------------------------- trigger semantics, unchanged

def test_an_idle_tick_runs_nothing_and_only_reads(tmp_path: Path) -> None:
    state = {"last_main_sha": MAIN_SHA, "processed_comment_ids": [100]}
    result, events, new_state = _tick(tmp_path, {1: [_comment(100, "old")]}, state=state)
    assert result.returncode == 0, result.stderr
    assert _runs(events) == []
    curl_calls = [event for event in events if event["tool"] == "curl"]
    assert curl_calls and all("-X" not in event["argv"] and "-d" not in event["argv"] for event in curl_calls)
    assert new_state == state


def test_a_new_main_sha_triggers_exactly_one_run_and_is_persisted(tmp_path: Path) -> None:
    state = {"last_main_sha": "e" * 40, "processed_comment_ids": [100]}
    result, events, new_state = _tick(tmp_path, {1: [_comment(100, "old")]}, state=state)
    assert result.returncode == 0, result.stderr
    assert _runs(events) == [[MAIN_SHA]]
    assert new_state["last_main_sha"] == MAIN_SHA


def test_a_main_run_that_never_started_is_not_persisted(tmp_path: Path) -> None:
    """S1: exit 3 means the lock was never acquired - retry next tick."""
    state = {"last_main_sha": "e" * 40, "processed_comment_ids": [100]}
    result, events, new_state = _tick(tmp_path, {1: [_comment(100, "old")]}, state=state, runner_exit=3)
    assert result.returncode == 0, result.stderr
    assert _runs(events) == [[MAIN_SHA]]
    assert new_state["last_main_sha"] == "e" * 40


def test_an_owner_trigger_on_page_two_runs_once_and_a_non_owner_copy_does_not(tmp_path: Path) -> None:
    page_one = _page(1_000)  # 1000..901, nothing known, nothing matching
    page_two = [
        _comment(900, f"/run-real-docker {REQUESTED_SHA}", login=OWNER),
        _comment(899, f"/run-real-docker {'f' * 40}", login="not-the-owner"),
        _comment(898, "already handled"),
    ]
    state = {"last_main_sha": MAIN_SHA, "processed_comment_ids": [898]}

    result, events, new_state = _tick(tmp_path, {1: page_one, 2: page_two}, state=state)

    assert result.returncode == 0, result.stderr
    assert _runs(events) == [[REQUESTED_SHA]]
    assert _comment_page_numbers(events) == [1, 2]
    assert {900, 899, 898} <= set(new_state["processed_comment_ids"])
    assert {c["id"] for c in page_one} <= set(new_state["processed_comment_ids"])


def test_pagination_stops_at_the_first_page_holding_a_known_id(tmp_path: Path) -> None:
    pages = {1: _page(3_000), 2: _page(2_900), 3: _page(2_800)}
    state = {"last_main_sha": MAIN_SHA, "processed_comment_ids": [2_850]}  # on page 2
    result, events, _state = _tick(tmp_path, pages, state=state)
    assert result.returncode == 0, result.stderr
    assert _comment_page_numbers(events) == [1, 2]


def test_pagination_is_capped_at_twenty_pages(tmp_path: Path) -> None:
    pages = {n: _page(100_000 - (n - 1) * 100, body_bytes=8) for n in range(1, 23)}
    state = {"last_main_sha": MAIN_SHA, "processed_comment_ids": []}
    result, events, new_state = _tick(tmp_path, pages, state=state)
    assert result.returncode == 0, result.stderr
    assert _comment_page_numbers(events) == list(range(1, 21))
    assert len(new_state["processed_comment_ids"]) == 2_000


def test_comments_are_requested_newest_first(tmp_path: Path) -> None:
    state = {"last_main_sha": MAIN_SHA, "processed_comment_ids": []}
    result, events, _state = _tick(tmp_path, {1: [_comment(1, "x")]}, state=state)
    assert result.returncode == 0, result.stderr
    urls = [event["url"] for event in events if "/issues/comments" in event["url"]]
    assert urls and all("sort=created" in url and "direction=desc" in url for url in urls)


def test_a_failed_comment_fetch_stops_the_tick_before_any_decision(tmp_path: Path) -> None:
    """An HTTP error on a comment page (curl --fail-with-body exits 22) must
    abort the tick, never read as an empty listing - even with a new main
    sha pending, nothing runs and nothing is persisted."""
    state = {"last_main_sha": "e" * 40, "processed_comment_ids": []}
    result, events, new_state = _tick(tmp_path, {}, state=state, raw_pages={1: "FAIL"})
    assert result.returncode != 0
    assert _runs(events) == []
    assert new_state == state
    assert _comment_page_numbers(events) == [1]  # the failure was really reached


def test_an_unparseable_comment_page_stops_the_tick_before_any_decision(tmp_path: Path) -> None:
    """curl succeeded but the body is not JSON. A parse that tolerated it
    (read as an empty page) would end pagination and go on to run main on a
    tick that read nothing; the tick must stop instead."""
    state = {"last_main_sha": "e" * 40, "processed_comment_ids": []}
    result, events, new_state = _tick(tmp_path, {}, state=state, raw_pages={1: "not json"})
    assert result.returncode != 0
    assert "JSONDecodeError" in result.stderr
    assert _runs(events) == []
    assert new_state == state


@pytest.mark.parametrize("name", ["flow-auto-cold", "unknown-control"])
def test_optin_owner_command_is_forwarded_once(tmp_path: Path, name: str) -> None:
    """#576: unknown names must reach installed refusal, not vanish in parsing."""
    command = f"/run-real-docker {REQUESTED_SHA} --opt-in {name}"
    result, events, state = _tick(tmp_path, {1: [_comment(901, command, OWNER),
                                               _comment(900, command)]},
                                  state={"last_main_sha": MAIN_SHA, "processed_comment_ids": []})
    assert result.returncode == 0, result.stderr
    assert _runs(events) == [[REQUESTED_SHA, "--opt-in", name]]
    assert state["processed_comment_ids"] == [900, 901]


def test_work_cwd_cannot_replace_installed_trigger_policy(tmp_path: Path) -> None:
    result, events, _ = _tick(tmp_path, {1: [_comment(1, 'ordinary text')]},
                              state={'last_main_sha': MAIN_SHA, 'processed_comment_ids': []}, hostile_cwd=True)
    assert result.returncode == 0, result.stderr
    assert _runs(events) == []
    assert not (tmp_path / 'imported-target').exists()
    assert not (tmp_path / 'imported-json').exists()


def test_lock_retry_preserves_original_optin_tuple_after_edit(tmp_path: Path) -> None:
    first_path, second_path = tmp_path / 'first', tmp_path / 'second'
    first_path.mkdir(); second_path.mkdir()
    original = f'/run-real-docker {REQUESTED_SHA} --opt-in flow-auto-cold'
    _, first_events, state = _tick(first_path, {1: [_comment(901, original, OWNER)]},
                                   state={'last_main_sha': MAIN_SHA, 'processed_comment_ids': []}, runner_exit=3)
    assert _runs(first_events) == [[REQUESTED_SHA, '--opt-in', 'flow-auto-cold']]
    edited = f'/run-real-docker {"e"*40} --opt-in unknown-control'
    result, events, final = _tick(second_path, {1: [_comment(901, edited, OWNER)]}, state=state)
    assert result.returncode == 0, result.stderr
    assert _runs(events) == [[REQUESTED_SHA, '--opt-in', 'flow-auto-cold']]
    assert final['processed_comment_ids'] == [901]


def test_trusted_cwd_preserves_relative_private_config_paths(tmp_path: Path) -> None:
    command = f'/run-real-docker {REQUESTED_SHA} --opt-in flow-auto-cold'
    result, events, _ = _tick(tmp_path, {1: [_comment(1, command, OWNER)]},
                              state={'last_main_sha': MAIN_SHA, 'processed_comment_ids': []},
                              hostile_cwd=True, relative_paths=True)
    assert result.returncode == 0, result.stderr
    assert _runs(events) == [[REQUESTED_SHA, '--opt-in', 'flow-auto-cold']]
    assert not (tmp_path / 'imported-json').exists() and not (tmp_path / 'imported-target').exists()
