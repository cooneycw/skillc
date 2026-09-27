"""Tests for the `mcp-second-opinion` Judge adapter (#69 follow-up).

Every test drives `tests/fixtures/mcp-second-opinion/fake_server.py`, never
a real server - #69's own acceptance forbids a real model call in the test
suite, and this adapter is no exception. Each failure class the orchestrator
named gets its own committed case: an absent binary, a failed handshake, and
a timeout.
"""

from __future__ import annotations

import ast
import sys
import time
from pathlib import Path

import pytest

from skillc import judge, judge_mcp_second_opinion
from skillc.judge_mcp_second_opinion import McpSecondOpinionJudge, _extract_json_array

FAKE = Path(__file__).resolve().parent / "fixtures" / "mcp-second-opinion" / "fake_server.py"


def _judge(mode: str, **kwargs: object) -> McpSecondOpinionJudge:
    return McpSecondOpinionJudge(command=(sys.executable, str(FAKE), mode), **kwargs)  # type: ignore[arg-type]


def test_describe_reads_the_servers_own_identity() -> None:
    description = _judge("happy").describe()
    assert description.model == "fake-mcp-second-opinion"
    assert description.version == "0.0.1-fake"
    assert description.name == "mcp-second-opinion:independent"


def test_describe_names_the_configured_tier() -> None:
    description = _judge("happy", tier_name="same-model").describe()
    assert description.name == "mcp-second-opinion:same-model"


def test_evaluate_returns_a_verdict_per_criterion() -> None:
    j = _judge("happy")
    raw = j.evaluate(["R1", "R2"], "fix the bug", [("out.txt", b"print(1)")])
    assert {r["id"] for r in raw} == {"R1", "R2"}
    assert all(r["outcome"] == "SATISFIED" for r in raw)


def test_evaluate_output_survives_parse_judge_verdict() -> None:
    """The adapter's raw output must actually satisfy the seam's own schema
    validation - not merely look plausible to a human reader."""
    j = _judge("happy")
    raw = j.evaluate(["R1"], "goal", [("out.txt", b"x")])
    verdict = judge.parse_judge_verdict(raw[0], "R1")
    assert verdict.outcome == "SATISFIED"


# --------------------------------------------------------------- failure classes


def test_an_absent_binary_is_unavailable() -> None:
    j = McpSecondOpinionJudge(command=("/nonexistent/mcp-second-opinion-xyz",))
    with pytest.raises(judge.JudgeUnavailable, match="cannot start"):
        j.describe()


def test_a_failed_handshake_is_unavailable() -> None:
    j = _judge("garbage-handshake")
    with pytest.raises(judge.JudgeUnavailable, match="not JSON"):
        j.describe()


def test_a_handshake_timeout_is_unavailable() -> None:
    j = _judge("hang", handshake_timeout=0.5)
    started = time.monotonic()
    with pytest.raises(judge.JudgeUnavailable, match="did not respond"):
        j.describe()
    assert time.monotonic() - started < 5, "the timeout must actually bound the wait, not merely be accepted as a parameter"


def test_a_tool_error_is_unavailable() -> None:
    j = _judge("tool-error")
    with pytest.raises(judge.JudgeUnavailable, match="tool error"):
        j.evaluate(["R1"], "goal", [("out.txt", b"x")])


def test_an_unparseable_verdict_is_an_empty_list_not_a_crash() -> None:
    """A model that answered in prose instead of the requested JSON shape is
    not a reachability failure - `run_tier` turns an empty answer into
    per-criterion UNKNOWN, an honest reflection of what happened."""
    j = _judge("unparseable-verdict")
    assert j.evaluate(["R1"], "goal", [("out.txt", b"x")]) == []


def test_a_stalled_reader_is_a_write_timeout() -> None:
    """Cross-model review: a plain blocking `stdin.write()` has no deadline
    at all if the child stops reading - a large enough candidate payload
    fills the OS pipe (independent of the JSON-RPC message sizes this module
    otherwise deals in) and would hang forever pre-fix. `stall-after-
    handshake` completes the handshake normally, then never reads again, so
    the tool-call write itself - not a read - must be what times out."""
    j = _judge("stall-after-handshake", call_timeout=0.5)
    big_candidate = [("out.txt", b"x" * 500_000)]
    started = time.monotonic()
    with pytest.raises(judge.JudgeUnavailable, match="did not accept input"):
        j.evaluate(["R1"], "goal", big_candidate)
    assert time.monotonic() - started < 5, "the write timeout must actually bound the wait"


def test_a_nearly_full_pipe_cannot_block_the_write_past_its_deadline() -> None:
    """#129: `select` reports a pipe writable when ANY space is free, not when
    a whole chunk fits, so a blocking 64 KiB `os.write` into a pipe with one
    free page waited forever once the reader stopped - the intermittent CI
    hang in `test_a_stalled_reader_is_a_write_timeout`. Here the pipe is
    pre-filled to exactly that state, deterministically. SIGALRM turns the
    pre-fix hang into a failure rather than a stuck suite."""
    import fcntl
    import os
    import signal
    from types import SimpleNamespace

    read_fd, write_fd = os.pipe()
    flags = fcntl.fcntl(write_fd, fcntl.F_GETFL)
    fcntl.fcntl(write_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
    try:
        while True:
            os.write(write_fd, b"x" * 4096)
    except BlockingIOError:
        pass
    os.read(read_fd, 4096)  # one page free; nothing reads again
    fcntl.fcntl(write_fd, fcntl.F_SETFL, flags)  # blocking, as subprocess hands it over
    stdin = os.fdopen(write_fd, "wb", buffering=0)
    proc = SimpleNamespace(stdin=stdin)

    def hung(signum: int, frame: object) -> None:
        raise AssertionError("_write blocked past its deadline (#129)")

    previous = signal.signal(signal.SIGALRM, hung)
    signal.alarm(10)
    try:
        started = time.monotonic()
        with pytest.raises(judge.JudgeUnavailable, match="did not accept input"):
            _judge("happy")._write(proc, {"payload": "y" * 65536}, 0.5)  # type: ignore[arg-type]
        assert time.monotonic() - started < 5
        assert os.get_blocking(write_fd), "the fd's own blocking mode is restored afterwards"
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)
        stdin.close()
        os.close(read_fd)


def test_a_notification_before_the_result_is_not_mistaken_for_it() -> None:
    """Cross-model review: the MCP transport permits a notification (no
    "id") to arrive before the response to an outstanding request. Treating
    "the next line" as "the response" would misread that notification as a
    malformed reply and fail a call the server actually completed."""
    j = _judge("notify-before-result")
    raw = j.evaluate(["R1"], "goal", [("out.txt", b"x")])
    assert {r["id"] for r in raw} == {"R1"}


def test_a_hung_process_is_killed_not_leaked() -> None:
    """The timed-out child must not become a zombie or an orphan - `_terminate`
    runs even on the failure path."""
    j = _judge("hang", handshake_timeout=0.5)
    proc = j._spawn()
    reader = judge_mcp_second_opinion._LineReader(j._stdout(proc))
    with pytest.raises(judge.JudgeUnavailable):
        j._handshake(proc, reader)
    j._terminate(proc)
    time.sleep(0.2)
    assert proc.poll() is not None, "the hung child must be terminated, not left running"


# --------------------------------------------------------------- through run_tier


def test_run_tier_reports_unavailable_for_a_hung_real_adapter() -> None:
    """Integration: the seam (`skillc.judge.run_tier`) must turn this
    adapter's JudgeUnavailable into a proper UNAVAILABLE tier verdict, exactly
    as it already does for FakeJudge."""
    result = judge.run_tier(
        judge.INDEPENDENT_TIER, _judge("hang", handshake_timeout=0.5), ["R1"], "goal", [("out.txt", b"x")]
    )
    assert result["status"] == "UNAVAILABLE"
    reason = result["reason"]
    assert isinstance(reason, str) and "did not respond" in reason


def test_run_tier_accepts_a_healthy_real_adapter() -> None:
    result = judge.run_tier(judge.SAME_MODEL_TIER, _judge("happy"), ["R1"], "goal text", [("out.txt", b"x")])
    assert result["status"] == "PASS"


# --------------------------------------------------------------- _extract_json_array


def test_extract_json_array_survives_a_closing_bracket_inside_a_string() -> None:
    """Cross-model review: naive bracket counting does not know it is inside
    a JSON string, so a criterion whose own evidence text contains a literal
    `]` character - perfectly valid JSON - used to truncate the array early
    and silently produce `[]` instead of the real verdict."""
    text = '[{"id": "R1", "outcome": "SATISFIED", "evidence": ["handles a closing ] character"]}]'
    result = _extract_json_array(text)
    assert result == [{"id": "R1", "outcome": "SATISFIED", "evidence": ["handles a closing ] character"]}]


def test_extract_json_array_skips_an_introductory_non_object_array() -> None:
    """A response that restates the criteria ids as a plain string array
    before the real verdict array must not stop at that first, object-less
    array."""
    text = '["R1"] then: [{"id": "R1", "outcome": "SATISFIED", "evidence": ["ok"]}]'
    result = _extract_json_array(text)
    assert result == [{"id": "R1", "outcome": "SATISFIED", "evidence": ["ok"]}]


# --------------------------------------------------------------- no real model call


def _find_unsafe_constructions(tree: ast.AST) -> list[ast.Call]:
    """A `McpSecondOpinionJudge(...)` call is unsafe when it omits `command=`
    entirely (falls back to `DEFAULT_COMMAND`, the real binary's name) OR
    passes `command=DEFAULT_COMMAND` explicitly (the same real binary by
    name, cross-model review: an explicit-looking keyword is not the same
    fact as a safe one). This is a narrow, stated guarantee, not a general
    anti-pattern scanner: it does not follow an alias
    (`import ... as OtherName`) and it does not evaluate a dynamically
    constructed `command` value - the whole test suite constructs this class
    by its own name with a literal tuple, so that is the population this
    check actually covers."""
    offenders = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "McpSecondOpinionJudge"):
            continue
        command_kw = next((kw for kw in node.keywords if kw.arg == "command"), None)
        omitted = command_kw is None
        real_default = isinstance(command_kw, ast.keyword) and isinstance(command_kw.value, ast.Name) and command_kw.value.id == "DEFAULT_COMMAND"
        if omitted or real_default:
            offenders.append(node)
    return offenders


def test_no_test_constructs_this_judge_without_overriding_command() -> None:
    """#69's own acceptance: 'No real model call in the test suite. That is
    structural and refused unless explicitly opted in.' `command` defaults
    to the REAL binary's name (`DEFAULT_COMMAND`) - this walks every test
    file's AST (recursively, so a file in a subdirectory is covered too) for
    an unsafe `McpSecondOpinionJudge(...)` construction, per
    `_find_unsafe_constructions`'s stated scope."""

    tests_dir = Path(__file__).resolve().parent
    offenders: list[str] = []
    for path in sorted(tests_dir.rglob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in _find_unsafe_constructions(tree):
            offenders.append(f"{path.relative_to(tests_dir)}:{node.lineno}")
    assert offenders == [], f"McpSecondOpinionJudge constructed unsafely (would use the REAL binary): {offenders}"


def test_the_ast_walk_can_see_a_planted_offender_with_no_command() -> None:
    """Negative control: a construction with no `command=` keyword at all is
    actually caught, not merely never triggered."""

    tree = ast.parse("j = McpSecondOpinionJudge(tier_name='x')\n", filename="<planted>")
    assert len(_find_unsafe_constructions(tree)) == 1


def test_the_ast_walk_can_see_a_planted_offender_with_the_real_default() -> None:
    """Negative control: an explicit `command=DEFAULT_COMMAND` - the real
    binary's name spelled out rather than omitted - is caught too, not only
    a bare omission."""

    tree = ast.parse("j = McpSecondOpinionJudge(command=DEFAULT_COMMAND)\n", filename="<planted>")
    assert len(_find_unsafe_constructions(tree)) == 1


def test_the_ast_walk_does_not_flag_a_safe_construction() -> None:
    """Positive control: the pattern every real test in this file uses -
    `command=` pointing at the fake server - must not be flagged."""

    tree = ast.parse(
        "j = McpSecondOpinionJudge(command=(sys.executable, str(FAKE), 'happy'))\n", filename="<planted>"
    )
    assert _find_unsafe_constructions(tree) == []
