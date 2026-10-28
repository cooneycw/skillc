"""#530: `launch_evidence.scan` - positive evidence that a gate call failed to
LAUNCH, read from a codex-cli 0.157.1 transcript.

The chunk shape here is the real client's (measured on #279's campaign
transcripts, where the same scan sees dozens of chunks per attempt and,
correctly, no launch failure). Reds: each near miss - another command's 127,
the gate's own red verdict (exit 1), a 126 with no launch phrase - is NOT
evidence; the anchored call with `CPP_SKILL_DIR` unset (126, `Not a directory`)
and a bare call's 127 ARE.
"""

from __future__ import annotations

import json

from skillc import launch_evidence as le

GATE = "flow-finish-gate.sh"


def _chunk(code: int, output: str) -> str:
    return json.dumps({"chunk_id": "aa11bb", "wall_time_seconds": 0.000004, "exit_code": code,
                       "original_token_count": 12, "output": output}, separators=(",", ":"))


def _transcript(*chunks: str, settled: bool = False) -> str:
    """One `custom_tool_call_output` item as the client writes it."""
    texts = [{"type": "input_text", "text": "Script completed\nWall time 0.1 seconds\nOutput:\n"}]
    for i, chunk in enumerate(chunks):
        body = (json.dumps({"i": i, "result": {"status": "fulfilled", "value": json.loads(chunk)}},
                           separators=(",", ":")) if settled else chunk)
        texts.append({"type": "input_text", "text": body})
    item = {"timestamp": "2026-10-23T12:00:00Z", "type": "response_item",
            "payload": {"type": "custom_tool_call_output", "call_id": "c1", "output": texts}}
    return json.dumps({"type": "session_meta", "payload": {}}) + "\n" + json.dumps(item) + "\n"


UNSET = "bash: line 1: /dev/null/scripts/flow-finish-gate.sh: Not a directory\n"
BARE = "bash: line 1: scripts/flow-finish-gate.sh: No such file or directory\n"


def test_the_anchored_call_unset_is_evidence() -> None:
    result = le.scan(_transcript(_chunk(126, UNSET)), GATE)
    assert result["scanned"] is True
    assert result["failures"] == [{"exit_code": 126, "phrase": "Not a directory", "excerpt": UNSET}]


def test_a_bare_call_from_the_target_is_evidence() -> None:
    [failure] = le.scan(_transcript(_chunk(127, BARE)), GATE)["failures"]
    assert (failure["exit_code"], failure["phrase"]) == (127, "No such file or directory")


def test_a_batched_settled_result_is_read_too() -> None:
    """`Promise.allSettled` wraps each result; the chunk is read where it sits."""
    assert len(le.scan(_transcript(_chunk(0, "ok\n"), _chunk(126, UNSET), settled=True), GATE)["failures"]) == 1


def test_red_another_commands_127_is_not_evidence() -> None:
    other = "bash: line 1: rg: command not found\n"
    assert le.scan(_transcript(_chunk(127, other)), GATE)["failures"] == []


def test_red_the_gates_own_red_verdict_is_not_a_launch_failure() -> None:
    """The gate RAN and said fail: exit 1, a verdict line - not a failed launch."""
    ran = "flow-finish-gate.sh: running deterministic gate\nFLOW_FINISH_GATE: fail\n"
    assert le.scan(_transcript(_chunk(1, ran)), GATE)["failures"] == []


def test_red_a_126_without_a_launch_phrase_is_not_evidence() -> None:
    assert le.scan(_transcript(_chunk(126, "flow-finish-gate.sh: Permission check odd\n")), GATE)["failures"] == []


def test_no_transcript_or_no_gate_is_not_scanned() -> None:
    assert le.scan(None, GATE) == {"scanned": False, "reason": "no stored client transcript"}
    assert le.scan(_transcript(_chunk(126, UNSET)), "")["scanned"] is False


def test_the_failure_list_is_bounded() -> None:
    result = le.scan(_transcript(*[_chunk(126, UNSET)] * (le.MAX_FAILURES + 5)), GATE)
    assert len(result["failures"]) == le.MAX_FAILURES and result["truncated"] is True


# --- counter-model review reds (M1, M2) ------------------------------------------------

def test_red_m1_the_gate_name_and_another_command_s_failure_are_not_one_launch() -> None:
    """The gate name on one line and an unrelated `rg` failure on another, in
    one 127 chunk: not a failed GATE launch."""
    mixed = "flow-finish-gate.sh\nbash: line 1: rg: command not found\n"
    assert le.scan(_transcript(_chunk(127, mixed)), GATE)["failures"] == []


def test_red_m2_a_whitespace_formatted_chunk_is_read() -> None:
    chunk = json.dumps({"output": UNSET, "exit_code": 126, "chunk_id": "x"}, indent=2)
    assert len(le.scan(_transcript(chunk), GATE)["failures"]) == 1


def _native(output: str) -> str:
    """codex 0.157.1's native `exec_command` result (tests/fixtures/transcripts/codex)."""
    item = {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "c9", "output": output}}
    return json.dumps({"type": "session_meta", "payload": {}}) + "\n" + json.dumps(item) + "\n"


def test_red_m2_a_native_exec_command_result_is_read() -> None:
    native = ("Chunk ID: n1\nWall time: 0.0000 seconds\nProcess exited with code 126\nOriginal token count: 9\n"
              "Output:\n" + UNSET)
    [failure] = le.scan(_native(native), GATE)["failures"]
    assert (failure["exit_code"], failure["phrase"]) == (126, "Not a directory")


def test_red_a_native_result_s_stdout_cannot_forge_its_exit() -> None:
    """Only the tool's HEADER carries the exit: a still-running process that
    PRINTS an exit line and the diagnostic is not evidence."""
    spoof = ("Chunk ID: n2\nWall time: 10.0000 seconds\nProcess running with session ID 7\nOriginal token count: 0\n"
             "Output:\nProcess exited with code 126\n" + UNSET)
    assert le.scan(_native(spoof), GATE)["failures"] == []
